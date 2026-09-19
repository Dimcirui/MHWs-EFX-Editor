# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/attractor.py —— `Attractor`（吸引子：弹簧力 + 阻尼 + 速度乘区）

字段语义全部来自用户 2026-09-17/18 实机测试（详见 blender_efx_re/semantics/
mhws_field_labels.json 对应 evidence、tools/vendor-patches/README.md #0006、
docs/PITFALLS.md #29）。这里只实现其中"一档/二档/三档"（把握够、能用现有架构落地的部分），
四/五档（`AttractAxisBias`、`SpawnDelay`、Shape 系统）**故意不做**，理由见下方对应小节。

目标点：两个分量矢量相加
--------------------------
`AttractPositionLocal`（恒生效，局部空间偏移）+ `AttractPositionWorld`（只在 `Flags` 低 2 位
选到"世界系目标点"时生效）。`Flags` 低 2 位是一个 4 值枚举：

    0 = 默认（仅 AttractPositionLocal）
    1 = unknMode，从未测出效果——按默认处理，仅 note 一次
    2 = 世界系目标点叠加
    3 = 目标点替换成粒子自身出生点（AttractPositionWorld/Local 都不再参与）

⚠ **"世界系"这里是局部空间近似，不是真的世界坐标**：`efx_sim` 的 behavior 全都在发射器
局部坐标系里算（`velocity3d.py` 的方向模型也是同一条约束），没有宿主矩阵可用。这里直接把
`AttractPositionWorld` 当成再叠加一个局部偏移处理，等价于"假装发射器就蹲在世界原点、没有
额外旋转"——发射器实际不在原点或带了旋转时，预览效果会跟实机不一致，`on_emitter_init` 会
note 这条近似。

力学模型：阻尼弹簧，不是逐帧乘法衰减
------------------------------------
`ForceStatic`/`ForceBiRand` 已实机确认是弹簧力常数（`accel = k * (target - pos)`，`k` 越大
振荡周期越短）。`ForceResistWilds`（原阻尼系数猜测）**改成阻力项而不是速度乘法**：
`accel -= damping * vel`——这是用户实机订正的结论：阻尼字段的实际表现是让粒子维持在某个
恒定速度继续运动（阻力和弹簧力互相平衡的终端速度），如果是 `vel *= (1-damping)` 这种纯乘法
衰减，速度只会单调趋于零，不会出现"稳定维持在某个非零速度"这种现象。两者都写进同一个
`accel`，一起乘 `dt` 积分进 `p.vel`——本 behavior 只写速度（`STAGE = FORCE`，在
`INTEGRATE` 之前跑，`Velocity3D` 负责把 `p.vel` 累进 `p.pos`）。

`MaxAttractDistance`：超出直接不受力
--------------------------------------
实机确认的距离阈值，`-1` 是"无限制"哨兵值。超出时**整个 accel 都不计算**（弹簧力和阻尼一起
失效），不是只关掉弹簧力——"完全不受力"是实机原话。

`MultZoneRadius`+`ZoneVelocityMultiplier`：简化成球形死区
------------------------------------------------------------
实机确认的完整几何是"两个偏置点之间的胶囊"，但胶囊的两个端点由 Shape 系统（`ShapeRangeX/Y/Z`+
`ShapeRotation`）决定，而 Shape 系统本身语义还没解决（"始终正对摄像机的正方形边框"那个反常
现象，见 docs/PITFALLS.md 和 tools/vendor-patches/README.md #0006 追记 4/5）。**这里退化成
"以目标点为球心的球形死区"**——Shape 关闭（`Flags` 数值 8 那一位不开）时这就是实机的真实几何，
Shape 打开时会跟实机有出入，`on_emitter_init` 会 note。区域内的公式是"每帧对速度做乘法"
（`Static≈1` 时区域被完全忽略、等价于正常弹簧力这条已实机确认），随机项按 `ZoneVelocityMultiplier`
是不是标准 Static+Random 尚未验证——用项目当前默认的对称双向公式（`rng.DIST_SYMMETRIC`，
`FieldView.roll()` 默认值），跟 `ForceBiRand` 已确认的公式一致，但这个具体字段没有单独验证过，
`on_emitter_init` 会 note 这条假设。

故意不做的部分
--------------
- **`AttractAxisBias`**：命名和"各轴独立收缩+负值高速飞出"都是推导结论，没有逐条验证过
  （confidence=guess）。做出来的曲线如果和实机对不上，没法判断是模拟写错了还是猜测本身错了，
  先跳过，只在非零时 note。
- **`SpawnDelay`**：连单位都不知道（帧？秒？），硬编一个单位大概率是错的，只在非零时 note。
- **Shape 系统**（`ShapeRangeX/Y/Z`/`ShapeRotation`/`Flags` 数值 8/16 那两位）：根基性问题
  没解决（见上），非零/开启时只 note，不参与计算。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from .. import rng as _rng
from ..registry import Behavior, register
from ..stages import FORCE
from ..state import Vec3

TYPE_NAME = "Attractor"

_MODE_MASK = 3
_MODE_DEFAULT = 0
_MODE_UNKNOWN = 1
_MODE_WORLD = 2
_MODE_SPAWN_POINT = 3

_SHAPE_BIT = 8


@register(TYPE_NAME)
class Attractor(Behavior):
    """FORCE 阶段：只写 `p.vel`，位置积分交给 `Velocity3D`（INTEGRATE 阶段，排在本阶段之后）。"""

    STAGE = FORCE
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return

        flags = f.i("Flags")
        mode = flags & _MODE_MASK
        if mode == _MODE_UNKNOWN:
            em.note("Attractor.Flags 目标点模式=1（unknMode）从未测出效果，按默认（仅局部"
                    "偏移）处理")
        elif mode == _MODE_WORLD:
            em.note("Attractor.Flags 目标点模式=2（世界系目标点）在预览里按局部空间近似"
                    "处理——假装发射器蹲在世界原点、没有额外旋转，实际发射器位置/朝向不同"
                    "时会跟实机不一致")

        if flags & _SHAPE_BIT:
            em.note("Attractor.Flags 打开了 Shape 系统（数值 8/16 那两位），但 ShapeRangeX/"
                    "Y/Z 和 ShapeRotation 语义未定（见 docs/PITFALLS.md），预览按 Shape 关闭"
                    "处理——死区只画成以目标点为球心的球，不是实机的胶囊形状")

        if f.f("MultZoneRadius") > 0.0:
            em.note("Attractor.ZoneVelocityMultiplier 是否遵守标准 Static+Random 公式还是"
                    "像 ForceBiRand 那样双向对称尚未验证，预览按项目当前默认（双向对称）处理")

        if f.f("AttractAxisBias") != 0.0:
            em.note("Attractor.AttractAxisBias 非零，但语义是推导结论（confidence=guess），"
                    "未参与模拟")

        if f.sr("SpawnDelay") != (0.0, 0.0):
            em.note("Attractor.SpawnDelay 非零，但单位/公式未确认，未参与模拟")

        if f.f("unkn1") != 0.0:
            em.note("Attractor.unkn1 非零，语义未知，未参与模拟")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        p.rolled["attractor_k"] = _rng.roll_static_random(
            f.f("ForceStatic"), f.f("ForceBiRand"), rng, mode)
        p.rolled["attractor_zone_mult"] = f.roll(
            "ZoneVelocityMultiplier", rng, mode, default=(1.0, 0.0))

    def on_particle_step(self, p, em):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        dt = em.config.dt()

        flags = f.i("Flags")
        target_mode = flags & _MODE_MASK
        if target_mode == _MODE_SPAWN_POINT:
            target = p.spawn_pos
        else:
            target = f.vec3("AttractPositionLocal", Vec3())
            if target_mode == _MODE_WORLD:
                target = target + f.vec3("AttractPositionWorld", Vec3())

        delta = target - p.pos
        dist = delta.length()

        max_dist = f.f("MaxAttractDistance", -1.0)
        if max_dist >= 0.0 and dist > max_dist:
            return  # 超出最大作用距离：完全不受力（实机原话），弹簧力和阻尼都不计算

        zone_r = f.f("MultZoneRadius")
        if zone_r > 0.0 and dist <= zone_r:
            mult = p.rolled.get("attractor_zone_mult", 1.0)
            if mult != 1.0:
                p.vel = p.vel * mult
            return

        k = p.rolled.get("attractor_k", 0.0)
        damping = f.f("ForceResistWilds")
        accel = delta * k - p.vel * damping
        p.vel = p.vel + accel * dt
