# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/parentoptions.py —— `ParentOptions`，只做"粒子跟不跟发射器走"这一半

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `ParentOptions`）分两组，语义分别
来自完全不同的层：

    RelationPos/RelationRot/RelationScl   Int3   发射器本身怎么跟随它绑定的父级（物体/骨骼）
    ParticleUseLocal                       bool   已经出生的粒子还要不要继续跟着发射器走
    ConstInheritRate                       Range  跟踪比例（1=完全跟随，0=不跟）
    ConstFrame/ConstReleaseFrame/
    ConstInheritReleaseRate                       跟踪多少帧后开始释放 + 释放曲线的形状

**这个 behavior 只管 `ParticleUseLocal` + `ConstInheritRate` 这一半。**
`RelationPos`/`RelationRot`/`RelationScl`（发射器相对父级/骨骼的运动）从来不是
`efx_sim` 的事——entry 的父子关系、骨骼绑定在导入时就已经烘进 Blender 自己的 object
parenting / 约束里了（见 `bone_binding.py`），`sim_preview.py::_entry_matrix()` 直接读
`entry_obj.matrix_world` 拿到结果，`efx_sim` 全程不知道"父级"是什么，也不需要知道——和
`transform3d.py` 把 `LocalPosition`/`LocalRotation`/`LocalScale` 整体甩给 Blender 矩阵是
同一个理由。

这个 behavior 管的是完全另一件事：**已经出生、脱手的粒子**要不要继续跟着"发射器自己这
一帧动了多少"——不只是位置，转/缩放同理。这件事矩阵管不到——粒子的世界位置是 `efx_sim`
自己在算的（`p.pos`，entry 局部坐标，见 `transform3d.py` 的坐标空间说明），Blender 的
父子关系再怎么更新也不会反过来影响一个已经算好的 `Vec3`。

**为什么位置/旋转/缩放三者都要在这里（逐粒子、逐帧增量），而不是像"渲染矩阵"那样在
渲染路径统一叠一层**：`RibbonFollow`/`RibbonLength` 这类渲染体的几何是 `p.trail`——
**跨越多帧的历史位置列表**。如果转/缩放增量只在渲染时对"当前这一帧的矩阵"统一叠一遍，
效果是把**整条历史轨迹**都按"这一帧的朝向"整体转/缩一遍——包括那些在更早的帧、朝向根本
还不一样的时候记下来的历史点。真实故障：`Transform3DExpression` 转圈的 entry，
`RibbonFollow` 的尾迹会跟着"现在转到哪"整体刚体转动，而不是自己被粒子的历史运动"甩"出
一条弧线——本末倒置了，**应该是粒子每帧的运动本身描出弧线，尾迹只是记录，不能被单独
再转一次**。

修法是把转/缩放增量**烘进逐帧的 `p.pos` 本身**（和位置增量早就在做的事完全对称）：
每帧只把"这一帧比上一帧多转/多缩了多少"（`em.rotation_velocity`/`em.scale_velocity`，
`Simulator.step()` 算好的增量，同 `em.velocity` 之于 `em.origin`）刚体作用在 `p.pos`
上（绕 entry 局部原点，先缩放、再旋转、再平移——同 `coords.local_matrix_to_blender()`
的 TRS 顺序）。这样粒子出生之后每一帧都在**当时那个朝向**的基础上继续走，`p.trail`
里记下来的每一个历史点天然就是"那一刻真实在哪"，画尾迹时只需要一次性套上 entry 的
**静态**烘焙矩阵（`entry_obj.matrix_world`，不叠任何逐帧矩阵）就能拼出正确的弧线——
不会有"整条历史被按当前朝向重转一遍"这种自相矛盾的结果。**因此这个 behavior 不往
`sim_preview.py` 的渲染矩阵旁路任何东西**：转/缩放增量只应该在这里、只应该在粒子出生
之后逐帧生效。

`ConstFrame`/`ConstReleaseFrame`/`ConstInheritReleaseRate`（跟踪多少帧后开始释放、释放
要几帧、释放曲线的形状）本仓不做：语料里这三个字段绝大多数是 `(0, 0)`，是"永不释放"还是
"默认值=没配置、实际有别的隐含含义"两种读法都说得通，没有实机对拍分不出来（不把猜测当事实）。
P0 只处理"一直按 `ConstInheritRate` 跟踪到粒子死亡"这一种情况，三个字段非零时如实
note，不假装模拟了释放曲线。

⚠ **没有 `ParentOptions`（或 `ParticleUseLocal=0`）的 entry，`Transform3D` 的
`LocalRotation`/`LocalScale` 曲线驱动对已出生的粒子完全没有可见效果**——和位置漂移
一直以来的行为完全对称（脱手的粒子本来就不跟位置漂移），不是新引入的缺口。

坐标空间：`em.velocity`/`em.rotation_velocity`/`em.scale_velocity` 都是"entry 局部、
未过基变换"的这一帧增量（`transform3d.py` 同一套约定），直接作用在 `p.pos` 上，不做
任何坐标转换。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import CONSTRAIN
from ..vecmath import rotate_euler, rotation_order_name

TYPE_NAME = "ParentOptions"

_SCALE_IDENTITY = (1.0, 1.0, 1.0)


@register(TYPE_NAME)
class ParentOptions(Behavior):
    """CONSTRAIN 阶段：`ParticleUseLocal` 打开时，把发射器这一帧自己的缩放/旋转/位移
    增量（`em.scale_velocity`/`em.rotation_velocity`/`em.velocity`，Transform3D 曲线
    驱动的都算在里面）按 `ConstInheritRate` 的比例、以 TRS 顺序刚体作用在每个活着的粒子
    头上——不这么做，脱手的粒子和"发射器自己在动"这件事就完全脱节：Expression 驱动
    `Transform3D` 的效果只在粒子出生那一刻的位置上体现一次，之后发射器再怎么继续
    移动/转动都跟这个粒子没关系了。"""

    STAGE = CONSTRAIN
    ORDER = 5  # 排在 PtCollision 之类的边界约束之前——先跟上发射器，边界约束再收尾

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        use_local = bool(f.i("ParticleUseLocal"))
        rate = f.sr("ConstInheritRate", default=(1.0, 0.0))[0] if f.has("ConstInheritRate") else 1.0
        em.user["_parentoptions_use_local"] = use_local
        em.user["_parentoptions_rate"] = rate
        if use_local and (f.sr("ConstFrame") != (0.0, 0.0)
                          or f.sr("ConstReleaseFrame") != (0.0, 0.0)
                          or f.f("ConstInheritReleaseRate") != 0.0):
            em.note("ParentOptions.ConstFrame/ConstReleaseFrame/ConstInheritReleaseRate"
                    "（跟踪多少帧后开始释放）未模拟，粒子会一直按 ConstInheritRate 跟踪到死亡")

    def on_particle_step(self, p, em):
        if not em.user.get("_parentoptions_use_local"):
            return
        if p.birth_frame == em.frame:
            # 出生这一帧 `p.pos` 已经是 `_consume_spawn()` 刚拷贝的**当前**（已经过
            # 这一帧变化后的）`em.origin`——再叠一次这一帧的增量会把这一帧的位移/转动/
            # 缩放多算一遍（出生当帧多跑出去一截，往后每帧都在这个多出来的量上继续
            # 累积，永远追不上真实 origin）。
            return
        rate = em.user.get("_parentoptions_rate", 1.0)
        if not rate:
            return

        sv = em.scale_velocity
        if (sv.x, sv.y, sv.z) != _SCALE_IDENTITY:
            # 缩放增量按 rate 插值："跟一半"就是缩放比例本身往 1.0（不缩放）插值一半，
            # 不是把比例本身乘 0.5（那会让 rate=0.5、真实比例 2.0 时变成"缩小到 1.0 的
            # 一半"这种反直觉的东西）。
            sx = 1.0 + (sv.x - 1.0) * rate
            sy = 1.0 + (sv.y - 1.0) * rate
            sz = 1.0 + (sv.z - 1.0) * rate
            p.pos.x *= sx
            p.pos.y *= sy
            p.pos.z *= sz

        rv = em.rotation_velocity
        if rv.x or rv.y or rv.z:
            order = rotation_order_name(em.rotation_order)
            p.pos = rotate_euler(p.pos, rv.x * rate, rv.y * rate, rv.z * rate,
                                 order=order, applied=em.config.rot_order_applied)

        p.pos = p.pos + em.velocity * rate
