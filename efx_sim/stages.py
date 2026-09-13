# -*- coding: utf-8 -*-
"""
efx_sim/stages.py —— behavior 的阶段划分

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/stages.py`（见 docs/SIM_PORT_PLAN.md §4.2）。

设计要点（照搬上游）：**阶段按"写什么"命名，不按"什么时候跑"命名。**

`pre/motion/post` 这类相对时机命名的问题是：叠加顺序本来就未确认，以后每加一个属性都可能
要插队，而"pre"里挤满互不相干的东西之后，没人说得清一个新 behavior 该放哪。改成按写入目标
命名之后：写速度的都在 `FORCE`、彼此用 `ORDER` 排；"写 pos 不写 vel"的进 `CONSTRAIN`，这个
名字自己解释了它为什么必须排在 `INTEGRATE` 后面。

与上游的差异：**没有 `default_stage_for()` 的分类回退。** 上游查它自己的
`efx_format/categories.py`（一张属性分类表）来给没声明 `STAGE` 的 behavior 一个默认值。本仓
没有那张表，**照抄一张半吊子的分类只会让"这个 behavior 为什么跑在这里"变得不可追**——所以
这里要求每个 `Behavior` 子类**显式声明 `STAGE`**，没声明就在注册时报错。

阶段顺序是**数据不是代码**：`DEFAULT_STAGE_ORDER` 只是默认值，`SimConfig` 可整体替换——
把"顺序未知"变成可调参数，而不是待定的代码分支。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

# -- 阶段常量 ---------------------------------------------------------------
# 数值留空隙，方便以后往中间插（例如 WARP = 15：积分前改位置）。
FORCE       = 10   # 写 p.vel          —— Noise / PtVortexelWind / 重力
INTEGRATE   = 20   # p.pos <- p.vel    —— Velocity3D 独占
CONSTRAIN   = 30   # 覆写 p.pos        —— PtCollision / 各种边界
XFORM       = 40   # 写 p.scale / p.rot —— ScaleAnim / RotateAnim
SHADE       = 50   # 写 p.color/p.alpha —— Life 淡入淡出 / RgbCommon / Blink
RENDER_BODY = 60   # 产出 RenderItem   —— TypeBillboard3D / TypeMesh / TypeNoDraw
RENDER_MOD  = 70   # 改 RenderItem     —— UVSequence / ShaderSettings / FadeBy*

#: 逐粒子 step 用到的阶段（顺序即执行顺序）
DEFAULT_STAGE_ORDER = (FORCE, INTEGRATE, CONSTRAIN, XFORM, SHADE)

#: 渲染 pass 用到的阶段（与 step 分开，见 simulator.build_render）
DEFAULT_RENDER_STAGE_ORDER = (RENDER_BODY, RENDER_MOD)

STAGE_NAMES = {
    FORCE:       "FORCE",
    INTEGRATE:   "INTEGRATE",
    CONSTRAIN:   "CONSTRAIN",
    XFORM:       "XFORM",
    SHADE:       "SHADE",
    RENDER_BODY: "RENDER_BODY",
    RENDER_MOD:  "RENDER_MOD",
}

STAGE_LABELS = {
    FORCE:       {"EN": "Force (writes velocity)",    "ZH": "受力（写速度）"},
    INTEGRATE:   {"EN": "Integrate (vel -> pos)",     "ZH": "积分（速度→位置）"},
    CONSTRAIN:   {"EN": "Constrain (overwrites pos)", "ZH": "约束（覆写位置）"},
    XFORM:       {"EN": "Transform (scale/rotation)", "ZH": "变换（缩放/旋转）"},
    SHADE:       {"EN": "Shade (color/alpha)",        "ZH": "着色（颜色/透明度）"},
    RENDER_BODY: {"EN": "Render body",                "ZH": "渲染主体"},
    RENDER_MOD:  {"EN": "Render modifier",            "ZH": "渲染修饰"},
}

# -- 契约：每个阶段允许写哪些 Particle 槽位（strict 模式据此断言）-------------
# `rolled` / `user` / `alive` 任何阶段都可写，不列入检查（见 EXEMPT_SLOTS）。
STAGE_WRITES = {
    FORCE:       frozenset({"vel"}),
    INTEGRATE:   frozenset({"pos", "vel"}),
    CONSTRAIN:   frozenset({"pos", "vel"}),
    XFORM:       frozenset({"scale", "rot"}),
    SHADE:       frozenset({"color", "alpha"}),
    RENDER_BODY: frozenset(),   # 渲染阶段完全不许碰粒子状态
    RENDER_MOD:  frozenset(),
}

#: 任何阶段都可写的槽位（behavior 私有状态 + 存活标志）
EXEMPT_SLOTS = frozenset({"rolled", "user", "alive"})

#: strict 模式检查的槽位全集
CHECKED_SLOTS = frozenset({"pos", "vel", "scale", "rot", "color", "alpha", "age"})

#: 全部合法阶段
ALL_STAGES = frozenset(STAGE_NAMES)


def stage_name(stage):
    return STAGE_NAMES.get(stage, "STAGE_%s" % stage)
