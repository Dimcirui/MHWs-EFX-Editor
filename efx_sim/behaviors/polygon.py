# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/polygon.py —— `TypePolygon`（固定朝向的片，不朝相机）

和 `TypeBillboard3D` 的唯一本质区别：**不朝相机**。

朝向模型（2026-09-13 按实机样本纠正过一次，见下）
--------------------------------------------------
    RotationOrder + RotationX/Y/Z（Range，各自独立 roll）
        法线 = **固定静止轴 `_REST_NORMAL`**（game -Z）经这三个角欧拉旋转。
        `rotation_order_name()` 取顺序串，`rotate_euler()` 转开。
    OrientDirectionUpVector（`AxisXYZ`，X/Y/Z 三选一，默认 1=Y）
        **不参与法线计算**，喂给 `_oriented_basis()` 当"up 参考向量"——用来在算出来的
        法线基础上定横/纵轴（同 lookAt(dir, up) 里 up 的角色），对应它字面意思
        "朝向用的上方向量"。
    SizeScalar / Width / Height / Color / ColorRange
        同 `TypeBillboard3D` 的 SizeScalar / SizeX / SizeY / Color / ColorRange，语义一致、
        只是改了名。

⚠ 这次纠正的依据（铁律 #6：没有样本不断言，这里如实记依据，不是拍脑袋）
------------------------------------------------------------------------
上一版模型是"`OrientDirectionUpVector` 选基准轴，`RotationX/Y/Z` 整体转开"（姊妹项目
EFX-Editor 的 PLANE 是这个思路），**被真实场景实测推翻**：`[029] partical_4 (GpuPolygon)`
实测 `RotationX=1.5708`(90°)、`Y=Z=0`、`OrientDirectionUpVector=1`，旧模型算出的法线是
game (0,0,1)，游戏里实际朝向却是 game (0,1,0)——也就是说这个明摆着写了整 90° 的字段，
正确结果下应该对法线**毫无影响**。

全语料抽样复核（61 个真实 `TypePolygon`/`TypeGpuPolygon` 实例）支持同一个结论：
`OrientDirectionUpVector` 几乎恒为 1，`RotationX`/`RotationY` 几乎全是"整 0 或整 90°、
两者互斥"——旧模型下"绕 Y 轴（=基准轴本身）转 90°"对法线是**零效果**（转轴与向量共线），
可语料里 `RotationY=90°` 和 `RotationX=90°` 出现频率相当，没道理有一半文件在设置一个
没有视觉效果的字段。反推：法线的静止基准必须是一个**固定轴**、不能和"绕哪根轴转"绑定，
否则"选中的那根轴自己转自己"就会白转。用 game -Z 代入"绕 X 转 90°"，算出来正好是
game (0,1,0)——与实机样本精确吻合。

**置信度**：1 个实机样本 + 语料统计佐证，不是逐条验证过的定论。`RotationZ` 在抽样里全是
0，没有独立样本；`OrientDirectionUpVector` 的"喂给 up 参考"这个新角色也还没有单独验证过
（旧模型把它读成基准轴时至少还"看起来能用"，这次只是解释了为什么会跑偏，新角色本身有待
以后对更多样本时复核）。

P0 只画纯色片（同 `TypeBillboard3D`）
-------------------------------------
`ColorRate` / `Intensity` / `AlphaRate` / `EdgeBlendRange` / `ShadowMultiplier` 未消费；
`Flags` / `Flags2` 疑似控制混合/形状变体，取值语义未确认，`blend` 恒为 `ALPHA`；`Offset`
未消费。都照 `TypeBillboard3D` 的先例处理，理由同那边的模块说明。

`RotateAnim` 叠加
-----------------
`RotateAnim`（若存在）逐帧往 `p.rot` 上加角度（见 `rotateanim.py`）。`p.rot` 累积的量
按分量直接叠进静态 RotationX/Y/Z 再重算法线——同一条 `rotate_euler()`，不再发明第二套
合成方式。`_has_rotate` 只在 entry 真有 `RotateAnim` 时才逐帧重算（没有的话法线在 spawn
时算一次就够，省一次 `rotate_euler` 调用），仿 `TypeBillboard3D`/EFX-Editor `PLANE` 的
`_has_tracks` 先例。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ..vecmath import rotate_euler, rotation_order_name

TYPE_NAME = "TypePolygon"

_UINT32_MAX = 0xFFFFFFFF

#: 法线的静止基准（game 坐标系），见模块说明的实机推算。
_REST_NORMAL = Vec3(0.0, 0.0, -1.0)

#: `AxisXYZ`（vendor `EFXEnums.cs`）：0=X 1=Y 2=Z。喂给 `_oriented_basis()` 当 up 参考。
_AXIS_VECS = {0: Vec3(1.0, 0.0, 0.0), 1: Vec3(0.0, 1.0, 0.0), 2: Vec3(0.0, 0.0, 1.0)}


def _unpack_rgba(raw):
    """同 `billboard3d.unpack_rgba`：`{"rgba": <uint32>}` -> `(r, g, b, a)`，低字节 R。
    两边独立各存一份，不跨 behavior 文件 import——本仓的 behavior 一直是自包含的
    （见 `efx_sim/behaviors/__init__.py`），没有 `_common.py`。"""
    raw = int(raw) & _UINT32_MAX
    return ((raw & 0xFF) / 255.0,
            ((raw >> 8) & 0xFF) / 255.0,
            ((raw >> 16) & 0xFF) / 255.0,
            ((raw >> 24) & 0xFF) / 255.0)


def _color_of(f, key, default=(1.0, 1.0, 1.0, 1.0)):
    v = f.get(key)
    if isinstance(v, dict) and "rgba" in v:
        return _unpack_rgba(v["rgba"])
    return default


def _oriented_basis(normal, up_hint):
    """法线 + up 参考 -> 一对正交横/纵轴（同 lookAt(dir, up) 的构造）。

    `up_hint` 退化（与法线接近平行）时退回 Z，再退化就退回 X——同一套兜底顺序，只是
    现在优先用字段给的 `OrientDirectionUpVector`，不是猜一个固定参考轴。
    """
    n = normal.normalized(fallback=_REST_NORMAL)
    ref = up_hint.normalized(fallback=Vec3(0.0, 1.0, 0.0))
    if abs(n.dot(ref)) > 0.99:
        ref = Vec3(0.0, 0.0, 1.0)
        if abs(n.dot(ref)) > 0.99:
            ref = Vec3(1.0, 0.0, 0.0)
    u = ref.cross(n).normalized(fallback=Vec3(1.0, 0.0, 0.0))
    v = n.cross(u).normalized(fallback=Vec3(0.0, 0.0, 1.0))
    return u, v


@register(TYPE_NAME)
class TypePolygon(Behavior):
    """RENDER_BODY 阶段：产出 kind='PLANE' 的固定朝向面片（`axis_u`/`axis_v` 非空 -> glue
    不按相机现算方向，见 `state.RenderItem`）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    _has_rotate = False

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        self._has_rotate = em.f("RotateAnim") is not None
        if f.i("Flags"):
            em.note("TypePolygon.Flags=%d 未参与模拟（疑似混合类型，取值语义未确认）"
                    % f.i("Flags"))
        if f.i("Flags2"):
            em.note("TypePolygon.Flags2=%d 未参与模拟（取值语义未确认）" % f.i("Flags2"))
        if f.sr("Offset") != (0.0, 0.0):
            em.note("TypePolygon.Offset 非 0，未参与模拟")
        for key in ("ColorRate", "Intensity", "AlphaRate", "EdgeBlendRange",
                    "ShadowMultiplier"):
            if f.has(key):
                em.note("TypePolygon.%s 未参与模拟（P0 只画纯色片）" % key)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        scalar = f.roll("SizeScalar", rng, mode, default=(1.0, 0.0))
        p.rolled["pg_size"] = Vec3(f.roll("Width", rng, mode, default=(1.0, 0.0)) * scalar,
                                   f.roll("Height", rng, mode, default=(1.0, 0.0)) * scalar,
                                   1.0)

        order = rotation_order_name(f.i("RotationOrder"))
        rx = f.roll("RotationX", rng, mode)
        ry = f.roll("RotationY", rng, mode)
        rz = f.roll("RotationZ", rng, mode)
        p.rolled["pg_normal"] = rotate_euler(_REST_NORMAL, rx, ry, rz, order=order,
                                             applied=em.config.rot_order_applied)
        p.rolled["pg_up"] = _AXIS_VECS.get(f.i("OrientDirectionUpVector", 1), _AXIS_VECS[1])
        if self._has_rotate:
            p.rolled["pg_rot_base"] = (rx, ry, rz)
            p.rolled["pg_rot_order"] = order

        p.rolled["pg_color"] = _color_of(f, "Color")
        p.rolled["pg_color_range"] = _color_of(f, "ColorRange")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item
        size = p.rolled.get("pg_size", Vec3(1.0, 1.0, 1.0))
        col = p.rolled.get("pg_color", (1.0, 1.0, 1.0, 1.0))
        up_hint = p.rolled.get("pg_up", Vec3(0.0, 1.0, 0.0))
        if self._has_rotate and "pg_rot_base" in p.rolled:
            rx, ry, rz = p.rolled["pg_rot_base"]
            normal = rotate_euler(_REST_NORMAL, rx + p.rot.x, ry + p.rot.y, rz + p.rot.z,
                                  order=p.rolled["pg_rot_order"],
                                  applied=em.config.rot_order_applied)
        else:
            normal = p.rolled.get("pg_normal", _REST_NORMAL)

        it = RenderItem(kind="PLANE", pos=p.pos.copy(),
                        size=Vec3(size.x * p.scale.x, size.y * p.scale.y, 1.0))
        it.axis_u, it.axis_v = _oriented_basis(normal, up_hint)
        it.rot = 0.0                # 朝向已经烘进 axis_u/axis_v，不再给 glue 转
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
