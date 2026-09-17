# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/velocity3d.py —— `Velocity3D`（初速度 + 逐帧积分），四档方向模型

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `Velocity3D`，TypeID 84）。这是全表标注
质量最高的属性：14 个字段里 6 个 confirmed、6 个 likely。⚠ 但**单位没定**，见下。

    DirectionVectorX/Y/Z  Range   运动方向。**仅 VelocityType=Direction/Spread 生效**
    Offset                Vec3    全体粒子共同的方向分量。**仅 Normal 生效**
    Size                  Vec3    逐轴发散强度（1=该轴无效果 >1 向外 <1 向内）。**仅 Normal 生效**
    Spread                Range   锥角（弧度）。**仅 Spread 生效**
    Speed                 Range   初速度（时间基见下）
    SpeedCoef             Range   每帧对速度乘一次的系数（无量纲）：1=匀速 >1 加速 <1 减速
    GravityRate           Range   下坠加速度：**正值向下**（时间基见下，符号见下方 note）
    SpeedDelayFrame       RangeI  开始运动前的延迟帧数
    GravityDelayFrame     RangeI  重力开始生效前的延迟帧数
    VelocityType          enum    0=Direction 1=Normal 2=Radial 3=Spread 4=ScreenSpace
    InheritRate / InheritDistance 继承发射器自身位移，未实现

方向模型：和姊妹项目 EFX-Editor（MHWI）是**同一个模型**
-------------------------------------------------------
MHWI 的 `VELOCITY3D.velocityType` 已实测（`blender_efx/annotations.py`）：

    0 Directional        baseAxis + rotation 定方向
    1 DirectionalSpread  V_i = (divergence_i - 1) * 生成坐标_i + velocity_i，再归一化
    2 Radial             始终沿生成坐标向外，其余字段全部无效

MHWs 把 `baseAxis + rotation` 换成了一个自由向量 `DirectionVector`，并给两个 Vector3
换了名字。**字段对应关系是全语料分桶实测定的，不是照名字猜的**（600 个随机文件、1266 个
`Velocity3D` 实例，`VelocityType` 分桶）：

| 判据                        | VT=0 Direction | VT=1 Normal | 结论                    |
|-----------------------------|----------------|-------------|-------------------------|
| `Size` 三轴全 1（= 无效果）  | 68.2%          | **6.2%**    | `Size` = `divergence`   |
| `Offset` 三轴全 0            | 70.3%          | **24.9%**   | `Offset` = `velocity`   |
| `DirectionVector` 全 0       | 0.2%           | 0.9%        | 两档都"非零"，见下      |
| `Size` 全 1 **且** `Offset` 全 0（速度非零） | 61.8% | **0.4%** | Normal 的方向只能来自这两个 |

最后一行是正判据：Normal 档里"两个都没设"= 方向恒为零向量 = 粒子不动，全语料只有 0.4%
（3/690）——作者几乎总会设其中之一，说明方向确实由 `Size`/`Offset` 提供。

⚠ **`DirectionVector` 在 Normal 档里不生效**，尽管它 99.1% 非零：那是编辑器默认值。
VT=1 里 `(1,0,0)` 占 55.6%（VT=0 只有 15.4%）——如果它真的是 Normal 档的基准方向，
全游戏 55% 的发散型发射器都会整体往 +X 漂（`(Size-1)*生成坐标` 量级只有 0.05 上下，
一个单位长的 `(1,0,0)` 会把方向完全压倒）。这不可能，所以它在这一档是残留默认值。

`Spread`(3) 是 MHWI 没有的第四档，全语料只有 42 个实例（0.07%）
---------------------------------------------------------------
`Spread` 字段只在这一档有值（非零率 88.1%，其余三档 ≤0.9%），取值全是弧度制的整度数：
`1.7453294`=100° `1.0471976`=60° `0.8726647`=50° `3.1415927`=180° `6.2831855`=360°。
按**全锥角**处理（半角 = `Spread`/2）：100° 全锥是常见的喷射角，按半角读就是 200° 全锥，
讲不通。锥轴取 `DirectionVector`——这一档的 `DirectionVector` 是真的被作者写过的
（`0.0`/`-1.0`/`1.0` 都有，不是清一色默认值）。**样本只有 42 个，置信度低于前三档。**

`ScreenSpace`(4) / `Max`(5) 全语料零样本，遇到就记 note 并按无初速处理。

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
目前按绝对加速度处理并 note。

**符号是 `EfxBridge fieldstats` 定的：正值向下。** 全语料非零值里正数是负数的 3.6 倍
（30078 vs 8341），中位数/p90/p99 全是正——"Gravity"这个名字加上"绝大多数样本是正数"，
只可能是"正值 = 向下拉"，所以积分时是 `p.vel.y -= GravityRate * dt`（减，不是加）。少数
负值样本（"漂浮"特效，如烟雾/羽毛上升）符号相反，符合直觉。

**乘法递推那部分保留**：`SpeedCoef` 每帧乘一次，不是"每秒乘一次再开方"之类的东西——
上游 `velocity3d.py` 明写"别改成 dt"，指的正是这个系数。

⚠ 方向在**发射器局部坐标系**里算，不额外转发射器朝向：本仓的 entry 用 Blender 原生
parent-child，宿主矩阵由胶水层（`sim_preview.py::_entry_matrix()`）作用在整棵子树上。
上游那句 `emitter_rotate()` 在这里没有对应物。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import math

from ..registry import Behavior, register
from ..stages import INTEGRATE
from ..state import Vec3

TYPE_NAME = "Velocity3D"

VT_DIRECTION = 0
VT_NORMAL = 1
VT_RADIAL = 2
VT_SPREAD = 3
VT_NAMES = {0: "Direction", 1: "Normal", 2: "Radial", 3: "Spread", 4: "ScreenSpace",
            5: "Max"}

#: 已实现的四档。其余（`ScreenSpace`/`Max`，全语料零样本）记 note 并按无初速处理。
VT_IMPLEMENTED = frozenset({VT_DIRECTION, VT_NORMAL, VT_RADIAL, VT_SPREAD})

#: `Size` 缺省值。vendor 的 `Vector3 Size` 没有默认值概念，但全语料 99.8% 非零、众数是
#: `(1,1,1)`，而 `(Size-1)` 这个式子要求"无效果"对应 1——字段缺失时按无效果读。
_SIZE_DEFAULT = Vec3(1.0, 1.0, 1.0)

def _random_unit(rng):
    """球面上均匀取一个单位向量。

    `Radial` 档粒子恰好生在原点（没有 `EmitterShape3D`、或形状退化成一点）时没有『向外』
    可言，退回它——和上游 `EFX-Editor` 同一处的处理一致。让粒子原地不动是更糟的选择：
    那和『这一档没实现』长得一模一样。
    """
    z = rng.uniform(-1.0, 1.0)
    a = rng.uniform(0.0, 2.0 * math.pi)
    r = math.sqrt(max(0.0, 1.0 - z * z))
    return Vec3(math.cos(a) * r, z, math.sin(a) * r)


def _orthonormal_basis(axis):
    """给单位向量 `axis` 配两个与之正交的单位向量。参考轴挑 `axis` 最小分量对应的坐标轴，
    这样叉积永远不会退化（挑固定轴时 `axis` 恰好平行于它就会得到零向量）。"""
    ax, ay, az = abs(axis.x), abs(axis.y), abs(axis.z)
    ref = Vec3(1.0, 0.0, 0.0) if ax <= ay and ax <= az else (
        Vec3(0.0, 1.0, 0.0) if ay <= az else Vec3(0.0, 0.0, 1.0))
    u = Vec3(axis.y * ref.z - axis.z * ref.y,
             axis.z * ref.x - axis.x * ref.z,
             axis.x * ref.y - axis.y * ref.x).normalized()
    v = Vec3(axis.y * u.z - axis.z * u.y,
             axis.z * u.x - axis.x * u.z,
             axis.x * u.y - axis.y * u.x)
    return u, v


def _cone_sample(axis, half_angle, rng):
    """在以 `axis` 为轴、半角 `half_angle` 的圆锥内**按立体角均匀**取一个方向。

    按 `cosθ = 1 - u(1 - cos h)` 取（不是 `θ = u·h`）：后者会让粒子在锥心堆积，半角一大
    就看得出来是个"实心射线 + 稀疏外缘"而不是均匀喷雾。
    """
    half_angle = max(0.0, min(math.pi, half_angle))
    cos_h = math.cos(half_angle)
    cos_t = 1.0 - rng.random() * (1.0 - cos_h)
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))
    phi = rng.uniform(0.0, 2.0 * math.pi)
    u, v = _orthonormal_basis(axis)
    return (axis * cos_t + u * (sin_t * math.cos(phi)) + v * (sin_t * math.sin(phi))
            ).normalized(fallback=axis)


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
        if vtype not in VT_IMPLEMENTED:
            em.note("Velocity3D.VelocityType=%s 未实现（全语料零样本），粒子按无初速处理"
                    % VT_NAMES.get(vtype, vtype))
        elif vtype == VT_SPREAD:
            em.note("Velocity3D.VelocityType=Spread 按『以 DirectionVector 为轴、Spread 为"
                    "全锥角』处理；全语料只有 42 个样本，置信度低于其余三档")
        elif vtype == VT_NORMAL:
            # 这一档的方向只来自 Size/Offset，两个都是"无效果"值时方向恒为零向量。全语料
            # 只有 0.4%（3/690）这么写，真遇到八成是文件本身就没打算让粒子动——但"粒子不动"
            # 看起来和"预览没实现这一档"一模一样，所以明说一声。
            if (f.vec3("Size", _SIZE_DEFAULT).as_tuple() == (1.0, 1.0, 1.0)
                    and f.vec3("Offset", Vec3()).as_tuple() == (0.0, 0.0, 0.0)):
                em.note("Velocity3D.VelocityType=Normal 但 Size 三轴全 1、Offset 三轴全 0，"
                        "方向恒为零——这个 entry 的粒子本来就不动")
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

        vtype = f.i("VelocityType")
        if vtype not in VT_IMPLEMENTED:
            p.vel = Vec3()          # 已在 on_emitter_init 里 note 过，这里不重复
            return

        speed = f.roll("Speed", rng, mode)
        direction = self._initial_direction(vtype, f, p, rng, mode)
        # p.vel 的单位跟着 velocity_unit 走：per_second 时是米/秒，per_frame 时是米/帧。
        # 两种模式共用下面同一条积分路径，差别全在 config.dt()。
        p.vel = direction * speed

    def _initial_direction(self, vtype, f, p, rng, mode):
        """返回**单位**方向向量（拿不到方向时返回零向量 = 这个粒子不动）。

        四档的依据全在模块说明的对照表里。`Speed` 只提供大小，方向完全由这里决定。
        """
        if vtype == VT_NORMAL:
            # V_i = (Size_i - 1) * 生成坐标_i + Offset_i，再归一化。
            # `Size` 是逐轴发散强度（1=该轴无效果），`Offset` 是全体粒子共同的方向分量。
            # ⚠ 这一档**不读 `DirectionVector`**——它在 55.6% 的样本里是编辑器默认的
            #    `(1,0,0)`，当成基准方向会让全游戏一半的发散发射器整体往 +X 漂。
            size = f.vec3("Size", _SIZE_DEFAULT)
            off = f.vec3("Offset", Vec3())
            s = p.spawn_pos
            return Vec3((size.x - 1.0) * s.x + off.x,
                        (size.y - 1.0) * s.y + off.y,
                        (size.z - 1.0) * s.z + off.z).normalized()

        if vtype == VT_RADIAL:
            # 始终沿生成坐标向外；DirectionVector / Offset / Size 全部无效。
            return p.spawn_pos.normalized(fallback=_random_unit(rng))

        direction = f.roll_vec3("DirectionVectorX", "DirectionVectorY", "DirectionVectorZ",
                                rng, mode)
        if vtype == VT_SPREAD:
            axis = direction.normalized()
            if not axis.length():
                return Vec3()
            return _cone_sample(axis, 0.5 * f.roll("Spread", rng, mode), rng)

        return direction.normalized()      # VT_DIRECTION

    def on_particle_step(self, p, em):
        dt = em.config.dt()

        # SpeedCoef 每帧乘一次（无量纲，**不受 velocity_unit 影响**）
        coef = p.rolled.get("v_coef", 1.0)
        if coef != 1.0:
            p.vel *= coef

        if p.age >= p.rolled.get("v_grav_delay", 0):
            g = p.rolled.get("v_gravity", 0.0)
            if g:
                # 游戏坐标系 +Y = 上。全语料 `GravityRate` 非零值里正数是负数的 3.6 倍
                # （30078 vs 8341，`fieldstats` 实测），中位数、p90、p99 全是正——一个叫
                # "Gravity"的字段绝大多数样本是正的，只可能是"正值 = 向下拉"，所以要**减**：
                # 正的 GravityRate 让 vel.y 变小（往下坠），不是变大（往上飘）。
                p.vel.y -= g * dt
        if p.age >= p.rolled.get("v_move_delay", 0):
            p.pos += p.vel * dt
