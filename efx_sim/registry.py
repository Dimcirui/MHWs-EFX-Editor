# -*- coding: utf-8 -*-
"""
efx_sim/registry.py —— Behavior 协议 + 注册表

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/registry.py`（见 docs/SIM_PORT_PLAN.md §4.1）。

**加一个属性 = 新建一个文件 + `@register("TypeName")`，不改任何现有代码。**

六个钩子（作用域/时机，与 stage 正交）
--------------------------------------
    on_emitter_init  (em, rng)                 一次
    on_emitter_step  (em)                      每帧 ×1
    on_particle_spawn(p, em, rng)              每粒子一次
    on_particle_step (p, em)                   每帧 ×N   <- 签名里没有 rng，故意的
    on_particle_death(p, em) -> [SpawnRequest]
    build_render     (p, em, view, item) -> item

三条结构性保证（详见各自出处）
------------------------------
    (a) step 拿不到 rng         —— rng.py
    (b) 字段只能通过 FieldView 读 —— shapes.py
    (c) step 必须与视角无关      —— simulator.py / state.ViewContext

与上游的两处差异
----------------
1. **注册键是短类型名字符串**（`"Velocity3D"`），不是 hash、也不是 `efx_type_id` 整数。
   短名就是 ATTRIBUTE_TYPES.md 的索引键，读代码不用查表；范围只做 MHWs（CLAUDE.md #20），
   不需要为跨游戏版本的 TypeID 漂移留余地。取名走
   `blender_efx_re/model.py::short_attr_name()`（`…EFXAttributeVelocity3D` -> `Velocity3D`）。
2. **`STAGE` 必须显式声明。** 上游没声明时会去查它自己的 `categories.py` 分类表推一个默认，
   本仓没有那张表，照抄一张半吊子的只会让"这个 behavior 为什么跑在这里"变得不可追。

未注册的属性类型不进逐帧流程，但会被记进 `em.unsupported`，UI 上列出"本 entry 有 N 个未模拟
属性"。**预览不静默撒谎**——这是铁律 #2 那条"宁可拒绝，不要悄悄丢"在只读侧的对应物。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from . import stages as _stages


# ---------------------------------------------------------------------------
# Behavior 基类
# ---------------------------------------------------------------------------

class Behavior(object):
    """一个 EFX 属性类型的模拟行为。子类只实现自己关心的钩子。"""

    #: 本 behavior 写哪一类字段，决定它在逐帧流程里的位置。**必须显式声明。**
    STAGE = None

    #: 同 stage 内的先后；小的先跑。可被 `SimConfig.order_override` 覆盖。
    ORDER = 100

    #: 本 behavior 负责的属性短类型名（由 `@register` 填）
    TYPE_NAME = ""

    #: 声明"我要逐帧的位置历史"。任一 behavior 打开它，Simulator 就开始给每个粒子记
    #: `p.trail`。条带类渲染体要用。默认关——绝大多数属性不需要，记录是白白的拷贝开销。
    NEEDS_TRAIL = False

    def __init__(self, type_name):
        self.type_name = type_name

    # -- 钩子（默认全是 no-op）---------------------------------------------
    def on_emitter_init(self, em, rng):
        """发射器开始播放时一次。预计算、播种、常量表都放这里。"""

    def on_emitter_step(self, em):
        """每帧一次，发射器时间轴。Spawn 在这里决定这一帧生几个。"""

    def on_particle_spawn(self, p, em, rng):
        """每个粒子出生一次。**所有随机抽取必须在这里做**，抽完存 `p.rolled`。"""

    def on_particle_step(self, p, em):
        """每帧、每个活着的粒子。注意签名里没有 rng：逐帧随机用 `em.noise*`。"""

    def on_particle_death(self, p, em):
        """粒子死亡。返回 `[SpawnRequest]` 或 None（PtLife 将来住这儿）。"""
        return None

    def build_render(self, p, em, view, item):
        """渲染 pass。RENDER_BODY 阶段 `item` 为 None、负责产出；RENDER_MOD 阶段 `item`
        是上游产物、就地改。返回 item（或 None 表示不渲染）。"""
        return item

    def __repr__(self):
        return "<%s %s>" % (type(self).__name__, self.type_name)


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_REGISTRY = {}     # type_name -> Behavior 子类


def register(*type_names):
    """把一个 Behavior 子类绑到一个或多个属性短类型名上。

        @register("Velocity3D")
        class Velocity3D(Behavior):
            STAGE = INTEGRATE
    """
    def deco(cls):
        if not issubclass(cls, Behavior):
            raise TypeError("%r 不是 Behavior 子类" % cls)
        if cls.STAGE is None:
            raise TypeError(
                "%s 没有声明 STAGE。本仓不做分类回退，每个 behavior 必须显式声明它写什么"
                "（见 stages.py 模块说明）" % cls.__name__)
        if cls.STAGE not in _stages.ALL_STAGES:
            raise TypeError("%s.STAGE=%r 不是合法阶段" % (cls.__name__, cls.STAGE))
        for name in type_names:
            name = str(name)
            if name in _REGISTRY and _REGISTRY[name] is not cls:
                raise ValueError("属性 %r 已被 %s 注册，不能再绑 %s"
                                 % (name, _REGISTRY[name].__name__, cls.__name__))
            _REGISTRY[name] = cls
        cls.TYPE_NAME = str(type_names[0]) if type_names else ""
        return cls
    return deco


def registered_names():
    return frozenset(_REGISTRY)


def behavior_class_for(type_name):
    return _REGISTRY.get(str(type_name))


def resolve_stage(cls, type_name, config):
    """算出最终 `(stage, order)`：`SimConfig.order_override` > 类上的 `STAGE`/`ORDER`。"""
    ov = config.order_override.get(str(type_name)) if config else None
    if ov:
        return int(ov[0]), int(ov[1])
    return int(cls.STAGE), int(cls.ORDER)


class BoundBehavior(object):
    """behavior 实例 + 它在这个 entry 里对应的那一块属性数据。"""

    __slots__ = ("behavior", "type_name", "stage", "order", "fields", "attr_index")

    def __init__(self, behavior, type_name, stage, order, fields, attr_index):
        self.behavior = behavior
        self.type_name = type_name
        self.stage = stage
        self.order = order
        self.fields = fields          # FieldView
        self.attr_index = attr_index

    @property
    def sort_key(self):
        return (self.stage, self.order, self.attr_index)

    def __repr__(self):
        return ("<Bound %s stage=%s order=%d>"
                % (self.type_name, _stages.stage_name(self.stage), self.order))


def build_behaviors(blocks, config):
    """`blocks` 是 `[(type_name, fields_dict), ...]`（entry 里属性的原始顺序）。

    返回 `(bound_list, unsupported)`：
      bound_list  —— 已按 (stage, order, 属性在 entry 里的位置) 排序
      unsupported —— `[type_name, ...]`，未注册或被 disable 的
    """
    from .shapes import FieldView

    bound = []
    unsupported = []
    for idx, (type_name, fields) in enumerate(blocks):
        type_name = str(type_name)
        if config is not None and type_name in config.disabled:
            unsupported.append(type_name)
            continue
        cls = _REGISTRY.get(type_name)
        if cls is None:
            unsupported.append(type_name)
            continue
        stage, order = resolve_stage(cls, type_name, config)
        bound.append(BoundBehavior(cls(type_name), type_name, stage, order,
                                   FieldView(fields, type_name), idx))
    bound.sort(key=lambda b: b.sort_key)
    return bound, unsupported


def implements(bound, hook_name):
    """这个 behavior 是否真的覆写了某个钩子（没覆写就不进逐帧循环，省调用开销）。"""
    cls = type(bound.behavior)
    return getattr(cls, hook_name) is not getattr(Behavior, hook_name)
