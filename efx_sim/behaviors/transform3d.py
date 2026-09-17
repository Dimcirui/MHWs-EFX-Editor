# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/transform3d.py —— `Transform3D`（Entry 局部变换）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `Transform3D`）：

    LocalPosition   Vector3   局部位置偏移
    LocalRotation   Vector3   局部旋转（vendor 弧度，见 CLAUDE.md 已定项）
    LocalScale      Vector3   局部缩放
    RotationOrder   enum      旋转轴顺序

**这个 behavior 只贡献"相对烘焙基准的增量"，不认识矩阵本身。** 原因是 `Transform3D` 的
位置/旋转/缩放本来完全不走 `efx_sim`——`blender_efx_re/transform3d_view.py` 在用户编辑
字段时就把它们烘进了 entry 对象的 `matrix_basis`，预览渲染直接拿 `entry_obj.matrix_world`
当整体变换（见 `sim_preview.py::_entry_matrix()` 的说明），`efx_sim` 原本压根不需要认识
`Transform3D`。Expression 曲线接入之后这个假设出现了裂缝：曲线驱动的值是**逐帧变化**的，
而矩阵只在编辑时烘一次，不会跟着模拟跑——所以这个 behavior 把"当前值相对烘焙时刻的增量"
喂回三个量：

    em.drift            LocalPosition 的增量（`Simulator.step()` 用
                        `origin = host_origin + drift` 合成发射器位置，这是既有机制）
    em.rotation_drift   LocalRotation 的增量（弧度，逐分量相减）
    em.scale_drift      LocalScale 的增量（逐分量比值，`当前/基准`，恒等 = (1,1,1)）

`em.drift` 早已经通过 `em.origin` 影响粒子出生位置。`em.rotation_drift`/`em.scale_drift`
本身**不直接**渲染或参与物理——它们是**累计量**（这一刻相对烘焙基准的总差值），真正消费
它们的是 `Simulator.step()` 派生出的**逐帧增量** `em.rotation_velocity`/`em.scale_velocity`
（同 `em.velocity` 之于 `em.origin`：累计量算完之后，核心层自己再减一次上一帧的累计量，
得到"这一帧多变了多少"），交给 `parentoptions.py`（`ParentOptions.ParticleUseLocal` 打开
时）逐帧刚体作用在已出生粒子的 `p.pos` 上——**不是**在渲染路径统一叠一层矩阵。理由见
parentoptions.py 模块说明：`RIBBON` 这类渲染体的几何是跨越多帧的历史轨迹（`p.trail`），
渲染时统一叠一层"当前朝向"的矩阵会把整条历史都按现在的朝向刚体转一遍，而不是让粒子自己
的逐帧运动"甩"出一条弧线。

**这里必须用"（相对基准的）增量"，不能用"当前值"**：矩阵已经把三者在烘焙那一刻的值算
进去了，如果这里再把当前值整个塞进去，静态（没有 Expression 驱动）的情况就会把同一个
偏移/旋转/缩放叠两遍。用 `on_emitter_init` 时的快照当基准，之后只报告"比基准多出来的
部分"——没有曲线驱动时这部分恒为零（`rotation_drift=Vec3()`、`scale_drift=(1,1,1)`），
行为和"完全不模拟"时一致。

⚠ **逐帧增量的计算本身对烘焙基准是否恒等无感**：`(current-base)-(prev-base) ==
current-prev`，基准在相减时抵消掉了，所以"基准本身是不是恒等变换"这件事不影响
`parentoptions.py` 这条消费路径的准确度（这点和这里最初的一版实现——渲染时统一叠一层
*累计*矩阵——不一样，那条路径已经被真实场景推翻并移除，见 CLAUDE.md 的教训记录）。
仍然近似的地方是：`rotate_euler()` 每帧用**这一帧的增量**当作一整个 Euler 三元组重新
分解旋转，假设的是"每帧的转动增量足够小、可以当近似的角速度积分步"——公式本身一帧内
跳变一个大角度（比如硬编码从 0° 跳到 90°）时这一帧会有可见的离散化误差，是任何逐帧仿真
的通病，不是这里特有的缺陷。

坐标空间：不做 `coords.game_pos_to_blender()` 那次基变换——`em.drift`/`em.origin`/
`p.pos` 全都是"entry 局部、未过基变换"的游戏坐标（`_to_world()` 才做基变换 + 过矩阵），
这里读到什么就原样相减/相除，不转换。`em.rotation_order` 原样传 `RotationOrder` 字段的
原始标量值（不在这里解释成顺序串）——胶水层的 `coords.rotation_order_to_euler_order()`
已经认这个原始值，不用在核心层重复一遍。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import FORCE
from ..state import Vec3

TYPE_NAME = "Transform3D"

_BASE_POS_KEY = "_transform3d_base_local_position"
_BASE_ROT_KEY = "_transform3d_base_local_rotation"
_BASE_SCALE_KEY = "_transform3d_base_local_scale"

_SCALE_IDENTITY = Vec3(1.0, 1.0, 1.0)


def _safe_ratio(current, base):
    """`current/base`，`base==0` 时退回 1.0（无法表示为比例，视作"没有额外缩放"，
    调用方负责在这种情况下 note）。"""
    return current / base if base else 1.0


@register(TYPE_NAME)
class Transform3D(Behavior):
    """只贡献 `em.drift`/`em.rotation_drift`/`em.scale_drift`（相对烘焙基准的增量），
    不参与逐粒子 step。"""

    STAGE = FORCE
    ORDER = -10  # 发射器位置这类基础量，习惯上排在同阶段其余 behavior 之前

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        base_pos = f.vec3("LocalPosition", Vec3())
        base_rot = f.vec3("LocalRotation", Vec3())
        base_scale = f.vec3("LocalScale", _SCALE_IDENTITY.copy())
        em.user[_BASE_POS_KEY] = base_pos
        em.user[_BASE_ROT_KEY] = base_rot
        em.user[_BASE_SCALE_KEY] = base_scale
        em.rotation_order = f.i("RotationOrder")

        if base_scale.x == 0.0 or base_scale.y == 0.0 or base_scale.z == 0.0:
            em.note("Transform3D.LocalScale 基准有分量为 0，缩放增量无法表示成比例，"
                    "该分量按 1.0（不额外缩放）处理")

    def on_emitter_step(self, em):
        f = em.f(TYPE_NAME)

        base_pos = em.user.get(_BASE_POS_KEY, Vec3())
        current_pos = f.vec3("LocalPosition", base_pos)
        em.drift = current_pos - base_pos

        base_rot = em.user.get(_BASE_ROT_KEY, Vec3())
        current_rot = f.vec3("LocalRotation", base_rot)
        em.rotation_drift = current_rot - base_rot

        base_scale = em.user.get(_BASE_SCALE_KEY, _SCALE_IDENTITY)
        current_scale = f.vec3("LocalScale", base_scale)
        em.scale_drift = Vec3(_safe_ratio(current_scale.x, base_scale.x),
                              _safe_ratio(current_scale.y, base_scale.y),
                              _safe_ratio(current_scale.z, base_scale.z))
