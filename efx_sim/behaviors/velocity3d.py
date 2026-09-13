# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/velocity3d.py —— `Velocity3D`（初速度 + 逐帧积分），**P0 只做 Direction 一档**

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `Velocity3D`，TypeID 84）。这是全表标注
质量最高的属性：14 个字段里 6 个 confirmed、6 个 likely。⚠ 但**单位没定**，见下。

    DirectionVectorX/Y/Z  Range   运动方向分量（无量纲）。**仅 VelocityType=Direction 生效**
    Speed                 Range   初速度（时间基见下）
    SpeedCoef             Range   每帧对速度乘一次的系数（无量纲）：1=匀速 >1 加速 <1 减速
    GravityRate           Range   叠加到速度上的下坠量（时间基见下）
    SpeedDelayFrame       RangeI  开始运动前的延迟帧数
    GravityDelayFrame     RangeI  重力开始生效前的延迟帧数
    VelocityType          enum    0=Direction 1=Normal 2=Radial 3=Spread 4=ScreenSpace
    Offset / Size                 仅 Normal 生效；Spread 仅 Spread 生效；Inherit* 未门控

时间基：`Speed` / `GravityRate` 按**秒**，`SpeedCoef` 按**帧**（`SimConfig.velocity_unit`）
----------------------------------------------------------------------------------
知识表把 `Speed` 标成"米/帧"（confidence `likely`），但**全语料量级否掉了这个读法**：

    Speed        非零 90.0%   中位(非零) 2.2    p90 10     p99 45     max 1500
    GravityRate  非零 63.8%   中位(非零) 0.3    p90 0.8    p99 1.6
    SpeedCoef    非零 99.7%   中位(非零) 0.99   p90 1.0    p99 1.0

按帧读，`Speed` 中位就是 132 m/s、p99 是 2700 m/s——粒子特效不会这么快。按秒读是 2.2 m/s
（走路）、45 m/s（爆炸碎片），量级正常。`SpeedCoef` 恰好相反：`0.99^60 = 0.55`（一秒衰减
一半）只有按帧才讲得通，按秒读这个字段基本不起作用。

所以**两者时间基不同**，和上游 EFX-Editor 在 MHWI 上遇到的情况一样（它的 `t3d_velocity_unit`
默认 per_second、`uvs_speed_unit` 默认 per_frame）。开关是 `SimConfig.velocity_unit`，
默认 `per_second`；`SpeedCoef` **不受它影响**。

⚠ `GravityRate` 还有一层没定：名字是"Rate"，可能是**标准重力的倍率**（0.3 → 0.3×9.8 ≈
2.9 m/s²）而不是绝对加速度（0.3 m/s²）。两者都在合理量级里，语料分不出来，实机对拍才能定。
P0 按绝对加速度处理并 note。

**乘法递推那部分保留**：`SpeedCoef` 每帧乘一次，不是"每秒乘一次再开方"之类的东西——
上游 `velocity3d.py` 明写"别改成 dt"，指的正是这个系数。

P0 只支持 `VelocityType_Direction`(0)
-------------------------------------
其余四档**一律记 note 并按"无初速"处理，不按 Direction 近似**。模式门控本身已经被
`EfxBridge condstats` 全语料分桶验证过（见 `blender_efx_re/field_visibility.py` 头部），
但 `Normal`(Offset+Size 合成方向) / `Radial` / `Spread`(锥角) 的具体公式没有实测——按
Direction 糊过去会画出一个看着合理、实际全错的运动，比明说"这一档没做"更糟。
`ScreenSpace`(4) / `Max`(5) 全语料零样本，遇到就是异常。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import INTEGRATE
from ..state import Vec3

TYPE_NAME = "Velocity3D"

VT_DIRECTION = 0
VT_NAMES = {0: "Direction", 1: "Normal", 2: "Radial", 3: "Spread", 4: "ScreenSpace",
            5: "Max"}


@register(TYPE_NAME)
class Velocity3D(Behavior):
    """INTEGRATE 阶段：把速度积到位置上。改速度的（Noise / PtVortexelWind）排在 FORCE 阶段，
    自动跑在本阶段之前。"""

    STAGE = INTEGRATE
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        vtype = f.i("VelocityType")
        if vtype != VT_DIRECTION:
            em.note("Velocity3D.VelocityType=%s 未实现（P0 只做 Direction），粒子按无初速处理"
                    % VT_NAMES.get(vtype, vtype))
        for key in ("InheritRate", "InheritDistance"):
            if f.has(key) and f.sr(key) != (0.0, 0.0):
                em.note("Velocity3D.%s 非 0，未参与模拟" % key)
        if f.sr("GravityRate") != (0.0, 0.0):
            em.note("Velocity3D.GravityRate 按绝对加速度处理；它也可能是标准重力的倍率"
                    "（名字是 Rate），语料分不出来")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist

        p.rolled["v_coef"] = f.roll("SpeedCoef", rng, mode, default=(1.0, 0.0))
        p.rolled["v_gravity"] = f.roll("GravityRate", rng, mode)
        p.rolled["v_move_delay"] = max(0, f.roll_int("SpeedDelayFrame", rng, mode))
        p.rolled["v_grav_delay"] = max(0, f.roll_int("GravityDelayFrame", rng, mode))

        if f.i("VelocityType") != VT_DIRECTION:
            p.vel = Vec3()          # 已在 on_emitter_init 里 note 过，这里不重复
            return

        speed = f.roll("Speed", rng, mode)
        direction = f.roll_vec3("DirectionVectorX", "DirectionVectorY", "DirectionVectorZ",
                                rng, mode)
        # p.vel 的单位跟着 velocity_unit 走：per_second 时是米/秒，per_frame 时是米/帧。
        # 两种模式共用下面同一条积分路径，差别全在 config.dt()。
        p.vel = direction.normalized() * speed

    def on_particle_step(self, p, em):
        dt = em.config.dt()

        # SpeedCoef 每帧乘一次（无量纲，**不受 velocity_unit 影响**）
        coef = p.rolled.get("v_coef", 1.0)
        if coef != 1.0:
            p.vel *= coef

        if p.age >= p.rolled.get("v_grav_delay", 0):
            g = p.rolled.get("v_gravity", 0.0)
            if g:
                # 游戏坐标系 +Y = 上。`GravityRate` 的标注是"叠加到运动速度上的**下坠量**"，
                # 语料里它本身就常是负数（样本 -0.2）——所以是**加**不是减，别再取一次负号。
                p.vel.y += g * dt
        if p.age >= p.rolled.get("v_move_delay", 0):
            p.pos += p.vel * dt
