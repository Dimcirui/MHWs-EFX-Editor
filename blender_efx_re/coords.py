"""
blender_efx_re/coords.py —— MHWS/RE Engine 场景坐标 <-> Blender 坐标换算

结论来源：姊妹项目 RE-Mesh-Editor（同为 RE Engine/MHWS，网格导入实测确认，
`modules/mesh/blender_re_mesh.py`）：
  - 位置：**1:1，不除 100**——RE Engine 场景坐标本身已经是米，和 Blender 一致。
    `re_mesh_parse.py.ReadPosBuffer()` 直接把顶点浮点数转成 Python list，不做任何缩放；
    `blender_re_mesh.py` 全文没有位置相关的缩放系数。
  - 轴变换：**Rx(+90°) 基变换**（game Y-up -> Blender Z-up），不是朴素分量交换取负——
    `blender_re_mesh.py` 用 `Matrix.Rotation(radians(90), 4, 'X')` 对网格数据 `.transform()`，
    导出用 `Matrix.Rotation(radians(-90), 4, 'X')` 还原，UI 选项名 "Convert Z Up To Y Up"
    默认开启。

⚠ 和姊妹项目 EFX-Editor 不一样：那边目标是 Monster Hunter World（MT Framework 引擎，场景
单位是厘米），对应 `EXTERN_TRANSFORM3D` 的位置要 **/100**；这里的 MHWS 用的是 RE Engine，
场景单位本身就是米，**不能照抄 100:1**，否则所有 Transform3D 位置会被错误缩小 100 倍。
两边"Y/Z 轴交换"这一步的结论一致（都是 Y-up 引擎 -> Z-up Blender），只有单位系数不同。

RotationOrder（`EFXAttributeTransform3D.RotationOrder`，6 个取值，
vendor `EFXEnums.cs:641-649`）去掉 `RotationOrder_` 前缀正好是 Blender `mathutils.Euler`
认识的合法 order 字符串（`'XYZ'`/`'YZX'`/`'ZXY'`/`'ZYX'`/`'YXZ'`/`'XZY'`），且两者对
"intrinsic Euler，matrix = R_首轴 @ R_次轴 @ R_末轴"的约定语义相同（业界通行约定，
Unity/Unreal 同款，Blender 自己对 Euler order 字符串的解释也是这一套）——直接复用
`mathutils.Euler`，不用按 6 种顺序手搓矩阵乘法分支。

`LocalRotation` 的角度单位是**弧度**（用户确认，2026-07-07；此前一版误以为是度，已改正）——
存储值本身不需要再乘 `radians()`。人工在面板里读写弧度不方便，这个不便交给
`panels.py` 的"角度显示"开关解决（`EFXValueNode.degrees_value` 代理属性 +
`Scene.efx_re_angle_degrees`，纯 UI 层换算，不影响这里的矩阵计算，也不改变
`efx_fields` 里存储的原始弧度值）——见 `model.py`/`panels.py`。
"""

from __future__ import annotations

from math import radians

from mathutils import Euler, Matrix, Vector

# game(Y-up, RE Engine/MHWS) -> Blender(Z-up) 基变换矩阵，见模块说明。
_G2B_BASIS = Matrix.Rotation(radians(90), 3, "X")
_G2B_BASIS_INV = _G2B_BASIS.inverted()

_ROTATION_ORDER_NAMES = {
    0: "XYZ",
    1: "YZX",
    2: "ZXY",
    3: "ZYX",
    4: "YXZ",
    5: "XZY",
}
_VALID_EULER_ORDERS = frozenset(_ROTATION_ORDER_NAMES.values())


def rotation_order_to_euler_order(value) -> str:
    """把 `RotationOrder` 字段的原始标量值（vendor 枚举名字符串，如 "RotationOrder_XYZ"，
    或数字下标）规整成 `mathutils.Euler` 认识的 order 字符串。识别不了的一律回退 "XYZ"
    （vendor 枚举默认值同为 0，见 EFXEnums.cs:643）。"""
    if isinstance(value, str):
        name = value.rsplit("_", 1)[-1].upper()
        return name if name in _VALID_EULER_ORDERS else "XYZ"
    try:
        return _ROTATION_ORDER_NAMES.get(int(value), "XYZ")
    except (TypeError, ValueError):
        return "XYZ"


def game_pos_to_blender(x: float, y: float, z: float) -> Vector:
    """位置：1:1（不除 100，见模块说明）+ Rx(+90°) 基变换 —— (x, y, z) -> (x, -z, y)。"""
    return Vector((x, -z, y))


def game_scale_to_blender(x: float, y: float, z: float) -> Vector:
    """缩放：对角缩放矩阵在同一个基变换下的共轭只置换分量、不引入负号
    （置换轴的特征值不变，共轭不改变对角矩阵的特征值，只改变它们分别绑在哪根轴上）
    —— (x, y, z) -> (x, z, y)。"""
    return Vector((x, z, y))


def game_rot_matrix_to_blender(x: float, y: float, z: float, rotation_order) -> Matrix:
    """旋转：按 `rotation_order` 用 `mathutils.Euler` 求出 game 空间的 3x3 旋转矩阵，再用
    `R_blender = M @ R_game @ M⁻¹` 换基（`M` = Rx(+90°)）——旋转是共轭变换，不能像位移那样
    直接交换/取负分量。`x`/`y`/`z` 是弧度（见模块说明），不再经过 `radians()` 转换。"""
    order = rotation_order_to_euler_order(rotation_order)
    r_game = Euler((x, y, z), order).to_matrix()
    return _G2B_BASIS @ r_game @ _G2B_BASIS_INV


def local_matrix_to_blender(pos, rot, scale, rotation_order) -> Matrix:
    """组合成一个 Blender 本地变换矩阵（Translation @ Rotation @ Scale，对应 game 侧
    Local Position/Rotation/Scale 的 TRS 组合约定）。三部分各自独立换算再按同样顺序组合，
    等价于对完整 TRS 矩阵整体做一次 `M @ A @ M⁻¹` 共轭（M 在乘法中对每一段分别结合，
    `M@T@R@S@M⁻¹ == (M@T@M⁻¹)@(M@R@M⁻¹)@(M@S@M⁻¹)`）。"""
    loc = game_pos_to_blender(*pos)
    rot4 = game_rot_matrix_to_blender(*rot, rotation_order).to_4x4()
    scl = game_scale_to_blender(*scale)
    scale_mat = Matrix.Diagonal((scl.x, scl.y, scl.z, 1.0))
    return Matrix.Translation(loc) @ rot4 @ scale_mat
