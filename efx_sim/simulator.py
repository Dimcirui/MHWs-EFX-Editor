# -*- coding: utf-8 -*-
"""
efx_sim/simulator.py —— 顶层驱动（EmitterState + Simulator）

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/simulator.py`（见 docs/SIM_PORT_PLAN.md §4.2）。

逐帧流程
--------
    frame += 1
    1. on_emitter_step   —— Spawn 在这里决定这一帧生几个
    2. 合成发射器位置     —— 必须在生成之前，本帧出生的粒子要用它
    3. 消化生成队列       —— 新粒子逐个跑 on_particle_spawn（**唯一能抽 rng 的地方**）
    4. on_particle_step   —— 按 stage 顺序，逐个活着的粒子
    5. 收割死亡           —— on_particle_death 收集 SpawnRequest（P0 不消化）

**step() 与 build_render(view) 是两个独立调用。** 逐帧模拟与视角无关，所以暂停时转视角
只要重跑 build_render，不用步进；核心也因此能没有相机就单测。

已定的取舍（会影响观感，标定时优先复核）
----------------------------------------
- **出生当帧就参与 step**：frame N 生成的粒子在 frame N 以 age=0 跑一次 step，
  所以寿命 1 帧的粒子正好活 1 帧。另一种可能是"出生帧不动、下一帧才开始"，未验证。
- **先生成、后收割**：本帧要死的粒子在本帧做生成决策时仍占着 `MaxParticles` 的名额。
  两种都说得通，未验证；换顺序只需调整 step() 里这两段的位置。
- **不做子步**：EFX 全程整数帧，逐帧乘法递推没有 dt 的位置，不要引入。

与上游的差异
------------
- 输入是 `[(短类型名, fields_dict)]`，不是 `(type_hash, ...)`；`em.f(name)` 直接返回
  `shapes.FieldView`，**没有 TIML/Clip 曲线那一层**（P0 不做 Clip，见 §4.2）。
- `_has_renderer_body()` 不查分类表（本仓没有），改用 vendor 自己的 `IsTypeAttribute` 规则。
- 没有 `SimResources`（P0 不做 UVSequence 帧表）。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import math

from . import expr as _expr
from . import registry as _reg
from . import rng as _rng
from . import stages as _stages
from .config import SimConfig
from .shapes import FieldView
from .state import Particle, RenderItem, Vec3, ViewContext
from .uvs_table import SimResources

#: vendor `ExpressionAssignType`（`EfxCommon.cs:8`，Add=0/Subtract=1/Multiply=2/Divide=3/
#: Assign=4，无 vendor"not sure"注释，视为确认）。公式结果和目标字段**导入时的原始值**
#: （不是上一帧被改过的值——否则 Add/Multiply 每帧都会在上一帧结果上再叠一次，无限发散）
#: 按这个表合成，key 缺失（理论上不会，防御性兜底）按 Assign 处理。
_EXPR_ASSIGN_OPS = {
    0: lambda base, result: base + result,
    1: lambda base, result: base - result,
    2: lambda base, result: base * result,
    3: lambda base, result: (base / result) if result != 0 else 0.0,
    4: lambda base, result: result,
}

#: `_ExprCurve.is_angle_degrees` 只在这三档转换公式结果（度 -> 弧度）：Add(0)/Subtract(1)
#: 把结果当成一个要叠加到弧度制基准上的角度增量，Assign(4) 直接替换成一个角度——三者的
#: 结果本身就"是"一个角度。Multiply(2)/Divide(3) 不转：结果在这两档里是无量纲的倍率
#: （"转速乘 2 倍"），不是角度本身，见 `_eval_expressions()` 的调用点。
_DEGREES_CONVERTED_ASSIGN_TYPES = frozenset({0, 1, 4})


def _ratio(current, prev):
    """`current/prev`，`prev==0` 时退回 1.0（无法表示成比例，等同"这一帧没有额外缩放"）。
    用于从 `scale_drift` 的累计值推导逐帧增量（`em.scale_velocity`），镜像
    `transform3d.py::_safe_ratio` 但不依赖那个模块——核心层内部的小工具，不值得为它
    建一条跨模块依赖。"""
    return current / prev if prev else 1.0


class _ExprCurve(object):
    """一条已经解析、定位好目标字段（+ 子键）的 Expression 曲线
    （`Simulator._resolve_expr_curves()` 的产物）。"""

    __slots__ = ("type_name", "field", "sub_key", "parsed", "assign_type", "base_value",
                "is_angle_degrees")

    def __init__(self, type_name, field, sub_key, parsed, assign_type, base_value,
                is_angle_degrees=False):
        self.type_name = type_name
        self.field = field
        #: `None`=整个字段就是标量；`"primary"`/`"secondary"`=`{s,r}`/`{x,y}` 形状字段的
        #: 主/副值；`"X"`/`"Y"`/`"Z"`=向量字段的某个分量。见 `_EXPR_FIELD_OVERRIDES`。
        self.sub_key = sub_key
        self.parsed = parsed
        self.assign_type = assign_type
        #: 目标（字段或子键）**导入时**的原始值——`ExpressionAssignType.Add/Subtract/
        #: Multiply/Divide` 都是相对它算，不是相对上一帧被改过的值，否则每帧都会在自己
        #: 头上再叠一次。
        self.base_value = base_value
        #: 目标字段是不是确认过的弧度制角度字段（`blender_efx_re.semantics.
        #: is_angle_radians_field()` 算好、经胶水层随 `expressions=` 传进来的，核心层
        #: 自己不认识语义表）。**这不是 UI 的"角度显示"开关**——是引擎/文件格式本身的事实：
        #: 全语料实测 `Transform3DExpression` 的 227 个"和公式根节点同单位"的字面量常量，
        #: 0 个落在弧度制常见值（π 的有理数倍）附近，172/202 超过 2π，众数是 360/10/5/30——
        #: **公式里的字面量按度写，`LocalRotation` 的静态存储却已经字节级确认是弧度**。
        #: 见 `efx_sim/behaviors/__init__.py` 或 `docs/EXPRESSION_SEMANTICS.md` 的记录。
        self.is_angle_degrees = is_angle_degrees


#: bit_name -> `(目标字段名, 子键)` 的每类型覆盖表。子键：`None`=整个标量字段；
#: `"primary"`/`"secondary"`=只改 `{s,r}`/`{r,s}`/`{x,y}` 形状字段的主值/副值（主键按
#: `_pick_primary_secondary_key()`——`{s,r}` 按 int/float 选 `r`/`s`，`{x,y}` 固定
#: `x`=min=主值，同 `shapes.py::_primary_secondary()`/`FieldView.xy()` 的既有约定，不
#: 重新发明）；`"X"`/`"Y"`/`"Z"`=只改向量字段的某一个分量。
#:
#: **"哪个字段"来自 vendor 源码本身**（"...Expression" 类的 `BitNameDict`/`BitNames`
#: 用 `nameof()` 指向的本地字段，和 sibling 类的字段布局对照确认，不是猜）——bit_name
#: 常常是语义化标签，不是字段名的机械变形（`appearLife` vs `AppearFrame`，见
#: `EfxBasics.cs:169`）。**"主值还是副值"这一层是推断**：vendor 没有明说 `XxxRand`/
#: `XxxRange` 变体一定对应副值，是从"单值字段 + 对应变体字段"这个命名规律反推的，
#: 没有实机确认，标注来源方便以后复核。
_EXPR_FIELD_OVERRIDES = {
    # EfxBasics.cs:158 LifeExpression：bit 1/2/3 有名字（4/5/6 的 XxxRand 变体不在 vendor
    # 的 BitNameDict 里，目前必然是空 bit_name，不会走到这里，收进表只是保持完整）。
    ("Life", "appearLife"): ("AppearFrame", "primary"),
    ("Life", "keepLife"): ("KeepFrame", "primary"),
    ("Life", "vanishLife"): ("VanishFrame", "primary"),
    ("Life", "appearLifeRand"): ("AppearFrame", "secondary"),
    ("Life", "keepLifeRand"): ("KeepFrame", "secondary"),
    ("Life", "vanishLifeRand"): ("VanishFrame", "secondary"),

    # EfxBasics.cs:72 SpawnExpression：spawnNum/intervalFrame/emitterDelayFrame 直接对应
    # 同名 `Int2` 字段（主值=x=min）；*Range 变体在 `EFXAttributeSpawn` 上没有独立字段，
    # 推断是同一个 Int2 的 y（max）分量。`speed` 在 `EFXAttributeSpawn` 上没有任何对应
    # 字段，不收进表——按"找不到字段"处理，不瞎猜它到底想改什么。
    ("Spawn", "spawnNum"): ("SpawnNum", "primary"),
    ("Spawn", "spawnNumRange"): ("SpawnNum", "secondary"),
    ("Spawn", "intervalFrame"): ("IntervalFrame", "primary"),
    ("Spawn", "intervalFrameRange"): ("IntervalFrame", "secondary"),
    ("Spawn", "emitterDelayFrame"): ("EmitterDelayFrame", "primary"),
    ("Spawn", "emitterDelayFrameRange"): ("EmitterDelayFrame", "secondary"),

    # EfxTransform.cs:118 Transform3DExpression：9 个 bit 分别对应 LocalPosition/
    # LocalRotation/LocalScale 三个 Vector3 各自的 X/Y/Z 分量。⚠ **`Transform3D` 目前
    # 不是 efx_sim 里已注册的 behavior**（`efx_sim/behaviors/` 没有 transform3d.py），
    # 这张表能把 bit_name 定位到正确的字段+分量，但 `_resolve_expr_curves()` 仍会因为
    # `em._views` 里没有 "Transform3D" 这个 view 而跳过——这是"这个属性本来就没被模拟"，
    # 不是这张表的问题，见 sim_preview 报告里的说明。
    ("Transform3D", "translationX"): ("LocalPosition", "X"),
    ("Transform3D", "translationY"): ("LocalPosition", "Y"),
    ("Transform3D", "translationZ"): ("LocalPosition", "Z"),
    ("Transform3D", "rotationX"): ("LocalRotation", "X"),
    ("Transform3D", "rotationY"): ("LocalRotation", "Y"),
    ("Transform3D", "rotationZ"): ("LocalRotation", "Z"),
    ("Transform3D", "scaleX"): ("LocalScale", "X"),
    ("Transform3D", "scaleY"): ("LocalScale", "Y"),
    ("Transform3D", "scaleZ"): ("LocalScale", "Z"),

    # EfxVelocity.cs:133 Velocity3DExpression：19 位里 vendor 的 `BitNameDict` 只给 8 位
    # 起了名，其余是 `unkn3`~`unkn19`（反射表 `semantics/mhws_bit_names.json` 按声明顺序
    # 补齐的占位名）。**占位名一个都不进表**——`unkn5`(bit4，全语料 198 次)、
    # `unkn6`(bit5，75 次)、`unkn3`(bit2，34 次) 都是真被作者用过的，但 vendor 自己都没认出
    # 它们指哪个字段，猜一个进来只会让预览拿错字段算出一条看着合理的假曲线（铁律 #6）。
    # 定位不到的曲线走 `_resolve_expr_target()` 返回 None 那条路，由调用方 note 出来。
    #
    # `speed`/`speedRand` -> `Speed` 没有歧义：`EFXAttributeVelocity3D` 上只有一个 `Speed`。
    # ⚠ `velocity{X,Y,Z}` 落到 `DirectionVector{X,Y,Z}` **比上面两条弱一档**，靠的是字段
    # **形状**而不是名字：带 `…Random` 变体的 bit 必须落在一个有主/副值的 `via.Range` 上，
    # 而 `Velocity3D` 上唯一的"逐轴 Range 三元组"就是 `DirectionVectorX/Y/Z`
    # （`Offset`/`Size` 是 `Vector3`，没有主副值可分）。4 个 Range × 主/副 = 正好 8 位，
    # 和 vendor 起了名的 8 位严丝合缝。反证也一起记着：vendor 在 [13]~[15] 注释掉了
    # `vectorX/Y/Z // direction?`，说明它怀疑还有第二组方向——真是那样的话这三条就错了，
    # 复核时从这里查。
    ("Velocity3D", "speed"): ("Speed", "primary"),
    ("Velocity3D", "speedRand"): ("Speed", "secondary"),
    ("Velocity3D", "velocityX"): ("DirectionVectorX", "primary"),
    ("Velocity3D", "velocityXRandom"): ("DirectionVectorX", "secondary"),
    ("Velocity3D", "velocityY"): ("DirectionVectorY", "primary"),
    ("Velocity3D", "velocityYRandom"): ("DirectionVectorY", "secondary"),
    ("Velocity3D", "velocityZ"): ("DirectionVectorZ", "primary"),
    ("Velocity3D", "velocityZRandom"): ("DirectionVectorZ", "secondary"),

    # --- 以下是**推断**，不是 vendor 源码给的名字（上面全部是）。判据、正对照成绩和
    # 被否掉的两条判据记在 docs/EXPRESSION_SEMANTICS.md 第 15 节，工具是
    # `EfxBridge exprhostcorr` + `tools/infer_expression_bit_fields.py`。
    #
    # EfxMiscStructs.cs:460 NoiseExpression：`new BitSet(8)`，**没有 BitNameDict**，8 位
    # 全是 `unkn1`~`unkn8`。本体 `EFXAttributeNoise` 恰好只有 4 个 `via.Range`，声明顺序
    # LowFrequency / LowFrequencyWidth / HighFrequency / HighFrequencyWidth ——
    # **8 位 = 4 字段 × 主/副值，没有多余候选**。三条独立线索一致：
    # ① "偶数位=主值、奇数位=副值"这个形状在四个**有名字**的类型上都成立
    #    （Life 6=3×2、Spawn 6=3×2、EmitterShape3D 6=3×2、Velocity3D 有名字的 8=4×2）；
    # ② 全语料用量在每一对里都是偶数位 > 奇数位（320>161、320>152、261>142、181>80），
    #    和 `speed`(1031) > `speedRand`(351) 同一个形状；
    # ③ 真实文件对读：`11_guide_006.efx.5571972` 的 `[003] tubu_out` 置位的是 bit2/bit6、
    #    assign 都是 Multiply、两条公式都是 `1 - Clamp(TIMER, 90, 30)` —— 按这张表读就是
    #    "把低频和高频的**振幅**（Width）在第 30~90 帧之间乘到 0"，噪声淡出的标准写法；
    #    换成"bit2 = LowFrequency"则读成"把频率降到 0"（噪声变得无限慢而不是消失），讲不通。
    # ⚠ 仍然是推断。现在**接上也不改变任何行为**——`efx_sim/behaviors/` 里没有 noise.py，
    # `Noise` 不是注册过的 behavior，`em._views` 里没有它这条视图，曲线照样会被跳过并 note。
    # 等真的实现 `Noise` 的那天，先拿实机确认这四对再让它生效。
    ("Noise", "unkn1"): ("LowFrequency", "primary"),
    ("Noise", "unkn2"): ("LowFrequency", "secondary"),
    ("Noise", "unkn3"): ("LowFrequencyWidth", "primary"),
    ("Noise", "unkn4"): ("LowFrequencyWidth", "secondary"),
    ("Noise", "unkn5"): ("HighFrequency", "primary"),
    ("Noise", "unkn6"): ("HighFrequency", "secondary"),
    ("Noise", "unkn7"): ("HighFrequencyWidth", "primary"),
    ("Noise", "unkn8"): ("HighFrequencyWidth", "secondary"),
}


def _pick_primary_secondary_key(value, which):
    """`{s,r}`/`{x,y}` 形状的 dict -> `which`（`"primary"`/`"secondary"`）对应的**键名**。

    和 `shapes.py::_primary_secondary()` 同一套判据（镜像，不是重新发明）：`{s,r}` 两个
    分量都是 int 时主键是 `r`，否则是 `s`；`{x,y}` 固定 `x` 是主值（`MIN_MAX_INT2_FIELDS`
    的既有约定，见 `shapes.py::FieldView.xy()`）。查不出形状返回 `None`。
    """
    if "s" in value and "r" in value:
        s, r = value["s"], value["r"]
        is_ranged_int = (isinstance(s, int) and isinstance(r, int)
                         and not isinstance(s, bool) and not isinstance(r, bool))
        primary_key, secondary_key = ("r", "s") if is_ranged_int else ("s", "r")
    elif "x" in value and "y" in value:
        primary_key, secondary_key = "x", "y"
    else:
        return None
    return primary_key if which == "primary" else secondary_key


def _is_plain_scalar(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def resolve_expr_field_name(base_type_name, bit_name):
    """`(base_type_name, bit_name)` -> 它驱动的 sibling 字段名（不含 sub_key，也不校验
    字段是否真的存在于某个具体实例上）——纯字符串规则，供只需要"哪个字段"这一层信息的
    调用方用（比如 `blender_efx_re` 那边查语义表的 `unit` 标注，判断这条曲线是不是在
    驱动一个弧度制角度字段），不需要 sibling 的原始字段 dict。`_resolve_expr_target()`
    要完整定位（含 sub_key + 当前值）时在这基础上再往下走一层，两边共享同一张
    `_EXPR_FIELD_OVERRIDES` 覆盖表 + fallback 规则，不重复维护两份。"""
    override = _EXPR_FIELD_OVERRIDES.get((base_type_name, bit_name))
    if override is not None:
        return override[0]
    return bit_name[:1].upper() + bit_name[1:]


def _resolve_expr_target(base_type_name, bit_name, raw):
    """`(base_type_name, bit_name)` + sibling attribute的原始字段 dict ->
    `(field_name, sub_key, 当前标量值)`，或者 `None`（定位不到，调用方负责 note）。

    没在 `_EXPR_FIELD_OVERRIDES` 里的类型退回旧的启发式（去掉 Expression 后缀 + 首字母
    大写）——这只在少数字段刚好是"色彩"、"速度"这种单值概念、命名又恰好对得上时才准，
    没被验证过的类型请把它当"最后一搏"而不是"应该对"，见 `collect_expressions()` 的说明。
    """
    if not bit_name:
        return None
    override = _EXPR_FIELD_OVERRIDES.get((base_type_name, bit_name))
    field_name = resolve_expr_field_name(base_type_name, bit_name)
    sub_key = override[1] if override is not None else None

    if field_name not in raw:
        return None
    value = raw[field_name]

    if sub_key is None:
        return (field_name, None, value) if _is_plain_scalar(value) else None

    if not isinstance(value, dict):
        return None
    if sub_key in ("primary", "secondary"):
        actual_key = _pick_primary_secondary_key(value, sub_key)
    else:  # "X" / "Y" / "Z"
        actual_key = sub_key if sub_key in value else sub_key.lower()
        if actual_key not in value:
            actual_key = None
    if actual_key is None:
        return None
    sub_value = value.get(actual_key)
    return (field_name, actual_key, sub_value) if _is_plain_scalar(sub_value) else None

#: 没有可用渲染体时，退化点的显示尺寸（米）。**纯显示默认值，不来自文件**——真实尺寸只有
#: 渲染体属性（`TypeBillboard3D` 等）知道，这里没有，所以不假装知道。
FALLBACK_SIZE = 0.1

#: `IsTypeAttribute` 的 Clip/Expression 变体后缀（vendor `EfxFile.cs:181` 的排除规则）
_TYPE_ATTR_EXCLUDED_SUFFIXES = ("Clip", "Expression")


def is_render_body_name(type_name):
    """这个短类型名是不是"渲染主体"。

    照抄 vendor 自己的判据（`EFXAttribute.IsTypeAttribute => type.ToString()
    .StartsWith("Type") && 不是 Clip/Expression 变体`，`EfxFile.cs:181`，一个 Entry 至多
    一个）。上游 EFX-Editor 是手工维护一张渲染体类型白名单，本仓不需要——vendor 已经算好了，
    而且 `Object.efx_is_type_attribute` 就存着这个结果（见 model.py 的 Entry 显示名后缀）。
    """
    name = str(type_name)
    if not name.startswith("Type"):
        return False
    return not name.endswith(_TYPE_ATTR_EXCLUDED_SUFFIXES)


def _has_renderer_body(blocks):
    """这个 entry 有没有渲染主体——决定"退化成点" vs "干脆不画"（见 build_render）。

    没有主体的 entry（纯当 Action 召唤枢纽、或者只有 `Spawn`/`Life` 这类骨架属性）本来就
    不该有画面，画一个退化点是凭空捏造。
    """
    return any(is_render_body_name(name) for name, _fields in blocks)


# ---------------------------------------------------------------------------
# EmitterState
# ---------------------------------------------------------------------------

class EmitterState(object):
    """一个发射器实例的运行期状态。behavior 通过它拿字段、拿噪声、排队生成。"""

    __slots__ = (
        "frame", "config", "seed",
        "origin", "host_origin", "drift", "velocity", "prev_origin",
        "rotation_drift", "scale_drift", "rotation_order",
        "prev_rotation_drift", "prev_scale_drift",
        "rotation_velocity", "scale_velocity",
        "particles", "spawned_total", "spawn_requests",
        "unsupported", "user", "finished", "trail", "resources",
        "_views", "_pending_spawn", "_notes",
    )

    def __init__(self, config, seed, resources=None):
        self.frame = -1
        self.config = config
        self.seed = seed
        #: 宿主注入的外部资源（`.uvs` 帧表等）。**恒非 None**——behavior 不必到处判空。
        self.resources = resources if resources is not None else SimResources()

        # 发射器位置拆成两份，每帧合成 `origin = host_origin + drift`：
        #   host_origin —— **宿主**报进来的位置（Blender 里就是 entry empty 的世界位置）。
        #   drift       —— 模拟层自己算出来的漂移（P0 没有属性会写它，恒为 0）。
        # 分开存是因为两者都会动：合并成一个的话，宿主每帧写一次就把累积的漂移冲掉了。
        self.host_origin = Vec3()
        self.drift = Vec3()
        self.origin = Vec3()
        self.velocity = Vec3()        # 每帧位移
        self.prev_origin = Vec3()

        #: `Transform3D` 的 `LocalRotation`/`LocalScale` 相对烘焙基准的**累计**增量
        #: （`transform3d.py` 写）。`rotation_order` 是 `RotationOrder` 字段的原始标量值
        #: （不在这里转换成顺序串，见 transform3d.py）。
        #:
        #: `rotation_velocity`/`scale_velocity` 是从这两个累计量派生出的**逐帧增量**
        #: （同 `velocity` 之于 `origin`：`origin` 是累计位置，`velocity` 是这一帧的位移）
        #: ——只有 `ParentOptions`（已出生的粒子要不要跟着发射器转/缩放）消费，核心层
        #: 不解释。用累计量相减取增量而不是直接记"上一帧的原始字段值"，是因为增量在
        #: 基准是否恒等这件事上**天然无关**（`(cur-base)-(prev-base) == cur-prev`，
        #: 基准抵消掉了）——不需要重复 `transform3d.py` 里"基准是否恒等"那层判断。
        #: 没有 `Transform3D` 的 entry 里全部恒为默认值（零增量）。
        self.rotation_drift = Vec3()
        self.scale_drift = Vec3(1.0, 1.0, 1.0)
        self.rotation_order = 0
        self.prev_rotation_drift = Vec3()
        self.prev_scale_drift = Vec3(1.0, 1.0, 1.0)
        self.rotation_velocity = Vec3()
        self.scale_velocity = Vec3(1.0, 1.0, 1.0)

        self.particles = []
        self.spawned_total = 0        # 累计生成数（逐粒子播种的序号）
        self.spawn_requests = []      # 子发射请求（PtLife，P0 不消化）

        self.unsupported = []         # [短类型名]，未模拟的属性
        self.user = {}                # 发射器级的 behavior 私有状态
        self.trail = []
        self.finished = False         # 发射器不再生成且粒子清空

        self._views = {}
        self._pending_spawn = 0
        self._notes = []

    # -- 字段访问（唯一入口）------------------------------------------------
    def f(self, type_name, p=None):
        """取某个属性块的字段视图；该 entry 没有这个属性则 `None`。

        `p` 目前没用上（P0 没有 Clip 曲线，字段值与粒子年龄无关），留着是为了 P2 接
        `EfxClipData` 时 behavior 的调用点不用改——上游那边同一个签名承担的正是这件事。
        """
        return self._views.get(str(type_name))

    def has(self, type_name):
        return str(type_name) in self._views

    # -- 生成队列 ------------------------------------------------------------
    def request_spawn(self, n):
        """排队生成 n 个粒子（本帧结算）。软上限由调用方（Spawn 的 `MaxParticles`）把关，
        这里只挡硬上限。"""
        if n > 0:
            self._pending_spawn += int(n)

    @property
    def alive_count(self):
        return len(self.particles)

    # -- 噪声（step 里唯一的"随机"来源）--------------------------------------
    def noise1(self, seed, channel=0):
        return _rng.noise1(seed, self.frame, channel)

    def noise3(self, seed, channel=0):
        return _rng.noise3(seed, self.frame, channel)

    def noise_smooth3(self, seed, channel=0, period=8.0):
        return _rng.noise_smooth3(seed, self.frame, channel, period)

    # -- Expression 曲线用：跨属性字段读写 ------------------------------------
    def patch_field(self, type_name, key, value, sub_key=None):
        """把 Expression 求值结果写回某个属性的某个字段（或字段的某个子键，见
        `_ExprCurve.sub_key`）。找不到对应 view 就什么都不做——调用方
        （`Simulator._eval_expressions`）已经先 `note()` 过，这里不重复记。"""
        view = self._views.get(str(type_name))
        if view is None:
            return
        if sub_key is None:
            view.raw[key] = value
            return
        container = view.raw.get(key)
        if isinstance(container, dict) and sub_key in container:
            container[sub_key] = value

    # -- 记事（给 UI：本次模拟里跳过 / 猜了什么）------------------------------
    def note(self, msg):
        """**预览不静默撒谎**：凡是没模拟、按假设处理、被上限截断的，都要在这里留一条，
        面板逐条列出来。这是铁律 #2"宁可拒绝，不要悄悄丢"在只读侧的对应物。"""
        if msg not in self._notes:
            self._notes.append(msg)

    @property
    def notes(self):
        return list(self._notes)

    def __repr__(self):
        return ("<EmitterState frame=%d particles=%d spawned=%d>"
                % (self.frame, len(self.particles), self.spawned_total))


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator(object):
    """一个 EFX Entry 的粒子模拟。

    输入是 `[(短类型名, fields_dict), ...]`——**不是**解析好的文件对象，也不是 Blender
    属性树。胶水层从当前正在编辑的属性树构造它，这样预览反映的是未保存的改动。
    """

    def __init__(self, blocks, config=None, resources=None, expressions=None,
                 expr_parameters=None):
        self.blocks = list(blocks or [])
        self._has_body = _has_renderer_body(self.blocks)
        self.config = config or SimConfig()
        #: 属性块里没有、必须由宿主给的外部数据（`UVSequence` 的 `.uvs` 帧表）。
        #: 换资源要 reset —— 帧表在 on_emitter_init 里只看一次。
        self.resources = resources if resources is not None else SimResources()
        #: `IExpressionAttribute` 的曲线，胶水层已经解析好"哪条曲线驱动哪个 sibling
        #: attribute 的哪个字段"：`[(base_type_name, target_field, formula_text,
        #: assign_type), ...]`。`efx_sim` 只管文本求值 + 按 `ExpressionAssignType` 合成，
        #: 不认识 `Object`/`EFXExpressionCurveItem`（见 efx_sim/expr.py 的说明）。
        self._expressions_raw = list(expressions or [])
        #: 文件级具名参数表（`EfxFile.ExpressionParameters`）-> `{名字: 标量值}`。公式里
        #: `Length`/`Color_A`/`BombRate` 这类名字就是从这张表来的。**不给的话它们会全部
        #: 落成"未知变量 -> 0.0"**，公式算出来的数和面板读数会不一致——这是真踩过的坑，
        #: 面板那半边在 `blender_efx_re/expr_preview.py`，两边的优先级必须保持一致。
        self._expr_parameters = dict(expr_parameters or {})
        self._expr_curves = []

        self.bound = []
        self.em = None
        self._h_emitter_step = []
        self._h_spawn = []
        self._h_step = []
        self._h_death = []
        self._h_render = []
        self._record_trail = False
        self.reset()

    # -- 生命周期 ------------------------------------------------------------
    def reset(self):
        """回到未开始状态（frame = -1），重新跑 on_emitter_init。"""
        cfg = self.config
        self.bound, unsupported = _reg.build_behaviors(self.blocks, cfg)

        em = EmitterState(cfg, _rng.emitter_seed(cfg.seed), self.resources)
        em.unsupported = list(unsupported)
        for b in self.bound:
            em._views[b.type_name] = b.fields

        self._expr_curves = self._resolve_expr_curves(em)

        self._h_emitter_step = [b for b in self.bound
                                if _reg.implements(b, "on_emitter_step")]
        self._h_spawn = [b for b in self.bound if _reg.implements(b, "on_particle_spawn")]
        self._h_step = [b for b in self.bound if _reg.implements(b, "on_particle_step")]
        self._h_death = [b for b in self.bound if _reg.implements(b, "on_particle_death")]
        self._h_render = [b for b in self.bound
                          if _reg.implements(b, "build_render")
                          and b.stage in cfg.render_stage_order]
        self._h_render.sort(key=lambda b: (cfg.render_stage_order.index(b.stage),
                                           b.order, b.attr_index))

        # 任一 behavior 声明 NEEDS_TRAIL -> 全局开启逐帧位置历史。开销是每粒子每帧一次
        # Vec3 拷贝，只在真需要时付。
        self._record_trail = any(type(b.behavior).NEEDS_TRAIL for b in self.bound)

        init_rng = _rng.particle_rng(em.seed, 0)
        for b in self.bound:
            b.behavior.on_emitter_init(em, init_rng)

        for name in unsupported:
            em.note("未模拟属性：%s" % name)

        self.em = em
        return em

    # -- 推进 ----------------------------------------------------------------
    def step(self):
        """推进一帧。返回本帧结束后的 EmitterState。"""
        em = self.em
        cfg = self.config
        em.frame += 1
        if em.frame > cfg.max_frames:
            if not em.finished:
                em.note("到达 max_frames=%d，预览停在这里（不代表特效本身结束）"
                        % cfg.max_frames)
            em.finished = True
            return em

        em.prev_origin = em.origin.copy()
        em.prev_rotation_drift = em.rotation_drift.copy()
        em.prev_scale_drift = em.scale_drift.copy()

        # 0. Expression 曲线——必须在其余 behavior 读字段之前算完，见 _eval_expressions()
        if self._expr_curves:
            self._eval_expressions(em)

        # 1. 发射器时间轴
        for b in self._h_emitter_step:
            b.behavior.on_emitter_step(em)

        # 2. 合成发射器位置。**必须在生成之前**——本帧出生的粒子要用它，放到生成之后
        #    就变成读上一帧的值。
        em.origin = em.host_origin + em.drift
        em.velocity = em.origin - em.prev_origin
        em.rotation_velocity = em.rotation_drift - em.prev_rotation_drift
        em.scale_velocity = Vec3(
            _ratio(em.scale_drift.x, em.prev_scale_drift.x),
            _ratio(em.scale_drift.y, em.prev_scale_drift.y),
            _ratio(em.scale_drift.z, em.prev_scale_drift.z))
        if self._record_trail:
            em.trail.append(em.origin.copy())

        # 3. 消化生成队列
        self._consume_spawn(em)

        # 4. 逐粒子 step
        strict = cfg.strict
        record_trail = self._record_trail
        for p in em.particles:
            if not p.alive:
                continue
            if p.delay_left > 0:
                p.delay_left -= 1
                continue
            # **年龄在跑 behavior 之前推进**（出生当帧不推，所以新粒子的第一帧 age=0）。
            # 放在末尾的话 `build_render()` 看到的 age 会比 SHADE 阶段刚算过的那一帧大 1
            # ——`Life` 按 age=N 写的 alpha，和 `UVSequence` 按 age=N+1 取的序列帧，
            # 画在同一个 RenderItem 上却不是同一帧。放在开头两边就一致了。
            if p.birth_frame != em.frame:
                p.age += 1
            for b in self._h_step:
                if strict:
                    self._strict_call(b, p, em)
                else:
                    b.behavior.on_particle_step(p, em)
            if record_trail:
                p.trail.append(p.pos.copy())

        # 5. 收割
        dead = [p for p in em.particles if not p.alive]
        if dead:
            for p in dead:
                for b in self._h_death:
                    req = b.behavior.on_particle_death(p, em)
                    if req:
                        em.spawn_requests.extend(req)
            em.particles = [p for p in em.particles if p.alive]

        return em

    def run_to(self, frame):
        """推进到指定帧（frame 从 0 起）。已经越过则先 reset。"""
        if frame < self.em.frame:
            self.reset()
        while self.em.frame < frame:
            self.step()
        return self.em

    def run(self, frames):
        """从当前状态再推进 `frames` 帧。"""
        for _ in range(int(frames)):
            self.step()
        return self.em

    # -- 渲染 pass（与 step 解耦；可重复调用，不改状态）-----------------------
    def build_render(self, view=None):
        em = self.em
        view = view or ViewContext()
        out = []
        for p in em.particles:
            if not p.active:
                continue
            item = None
            for b in self._h_render:
                item = b.behavior.build_render(p, em, view, item)
            if item is not None and item.kind == "NONE":
                continue      # 渲染体明说"我不该有视觉输出"（TypeNoDraw），不走退化点
            if item is None:
                if not self._has_body:
                    # 这个 entry 压根没有渲染主体类属性——不是"有主体但没实现"，是本来就
                    # 不该有画面，同 TypeNoDraw 一样明确不画（见 _has_renderer_body）。
                    continue
                # 有渲染主体、只是没实现（比如主体是 TypeGpuMesh）-> 退化成一个点，
                # 至少能看见"有多少、在哪、多亮"。
                item = RenderItem(kind="POINT", pos=p.pos.copy(),
                                  size=p.scale * FALLBACK_SIZE)
                item.color = [p.color[0], p.color[1], p.color[2], p.alpha]
                item.extra["vel"] = p.vel.copy()
                item.extra["age"] = p.age
            out.append(item)
        return out

    def emitter_outline(self, segments=28):
        """生成区域的线框（成对的点，与粒子同一坐标空间）。没有形状属性就返回 `[]`。

        按"behavior 有没有 `outline()`"找，**不写死 `EmitterShape3D`**——以后别的形状类
        属性加上同名方法就自动被画出来。
        """
        out = []
        for b in self.bound:
            fn = getattr(b.behavior, "outline", None)
            if fn is None:
                continue
            out.extend(fn(self.em, segments) or ())
        return out

    def suggested_duration(self, default=180):
        """『播放一次』该放多长（帧）。按各 behavior 的 `duration_hint()` 取最大值。

        三种返回值分开处理（见 `registry.DURATION_INFINITE`）：

            > 0                  有限长度，参与取 max
            0                    没有意见，忽略
            DURATION_INFINITE    没有自然终点 -> 至少放满 `default`

        最后一条是关键：**只要有一个 behavior 说"没有终点"，播放长度就不能被别人的有限
        提示压下去。** 真实故障——一个 `Spawn.LoopNum=0`（无限）+ `Life.Flags=持续性` 的
        entry，这两个都返回"无限"，全场唯一的正数提示是 `UVSequence` 的"这条 `.uvs` 只有
        1 帧"，旧写法（`0` 当"没意见"、直接取 max）算出播放长度 = 1 帧：每个 tick 步进到
        第 0 帧就撞线重置回第 -1 帧，面板上帧数在 -1 上不停跳、视口里永远看不到粒子。
        """
        best = 0
        infinite = False
        for b in self.bound:
            fn = getattr(b.behavior, "duration_hint", None)
            if fn is None:
                continue
            got = int(fn(self.em) or 0)
            if got == _reg.DURATION_INFINITE:
                infinite = True
            elif got > 0:
                best = max(best, got)
        if infinite:
            return max(best, default)
        return best or default

    # -- Expression 曲线 -------------------------------------------------------
    def _resolve_expr_curves(self, em):
        """把 `self._expressions_raw` 解析成 `[_ExprCurve, ...]`：解析公式文本、定位目标
        字段、快照"导入时的原始值"（`_EXPR_ASSIGN_OPS` 要用它当基准，不能用上一帧被改过的
        值，见该表的说明）。任何一步失败都是"这条曲线不动"，不是"整条模拟崩掉"（铁律 #2
        的只读侧对应物：note 一条，不静默丢、也不拖垮其他曲线）。"""
        out = []
        for item in self._expressions_raw:
            # 第 5 个元素（是不是弧度制角度字段）是可选的：旧调用点/测试传 4 元组时
            # 按"不是角度"处理，不强制所有调用方一起改。
            base_type_name, bit_name, formula_text, assign_type = item[:4]
            is_angle_degrees = bool(item[4]) if len(item) > 4 else False
            base_type_name = str(base_type_name)
            view = em._views.get(base_type_name)
            if view is None:
                em.note("expr: 找不到属性 %s（曲线 bit_name=%r 无法生效，这个属性本身没被"
                        "模拟——见 unsupported 列表）" % (base_type_name, bit_name))
                continue
            target = _resolve_expr_target(base_type_name, bit_name, view.raw)
            if target is None:
                em.note("expr: %s 找不到 bit_name=%r 对应的（标量）字段，曲线无法生效"
                        % (base_type_name, bit_name))
                continue
            field_name, sub_key, base_value = target
            try:
                parsed = _expr.parse(formula_text)
            except _expr.ExprError as exc:
                em.note("expr: %s.%s 公式解析失败（%s），曲线无法生效"
                        % (base_type_name, field_name, exc))
                continue
            out.append(_ExprCurve(base_type_name, field_name, sub_key, parsed,
                                   int(assign_type), float(base_value), is_angle_degrees))
        return out

    def _eval_expressions(self, em):
        """每帧在其余 behavior 之前跑一遍：拼变量表 -> 逐条曲线求值 -> 按
        `ExpressionAssignType` 合成 -> `patch_field()` 写回。变量表每帧重建（`TIMER`/
        跨属性字段都可能变），不缓存。"""
        variables = self._expr_builtin_vars(em)
        # 优先级：内置外部变量 > 文件级具名参数 > 兄弟属性的标量字段。内置的最特殊
        # （引擎全局），字段名最宽松（任何标量字段都能撞上），所以按这个顺序 setdefault。
        for name, value in self._expr_parameters.items():
            variables.setdefault(name, float(value))
        for view in em._views.values():
            for key, value in view.raw.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                variables.setdefault(key, float(value))

        notes = []
        ctx = _expr.EvalContext(variables, self.config.expr_unknown_func_policy, notes,
                                self.config.expr_clamp_mode)
        for curve in self._expr_curves:
            try:
                result = _expr.evaluate(curve.parsed, ctx)
            except _expr.ExprError as exc:
                em.note("expr: %s.%s 求值失败（%s）" % (curve.type_name, curve.field, exc))
                continue
            if curve.is_angle_degrees and curve.assign_type in _DEGREES_CONVERTED_ASSIGN_TYPES:
                # 全语料实测：Expression 公式驱动一个确认过的弧度制角度字段时，公式本身按
                # **度**写（见 `_ExprCurve.is_angle_degrees` 的说明），但字段的静态存储是
                # 弧度——真正吃公式结果的只有 Add/Subtract/Assign（全语料 560 条真实绑定的
                # `Transform3DExpression.rotationX/Y/Z` 公式，assign_type 只出现过
                # Assign=427/Add=133，Multiply/Divide/Subtract 一次都没有），这里只转这三档：
                # Multiply/Divide 的公式结果是无量纲的倍率，不该被当角度换算。
                result = math.radians(result)
            op = _EXPR_ASSIGN_OPS.get(curve.assign_type, _EXPR_ASSIGN_OPS[4])
            em.patch_field(curve.type_name, curve.field, op(curve.base_value, result), curve.sub_key)
        for msg in notes:
            em.note("expr: " + msg)

    def _expr_builtin_vars(self, em):
        """公式里几个**不对应任何属性字段**的内置变量。语义置信度分层见 `efx_sim/expr.py`
        模块 docstring——这里额外补的是"预览怎么建模"这一层（游戏本身怎么算，本仓不掌握）：

        - `PI`：`math.pi`，无歧义。
        - `TIMER`：按 `SimConfig.expr_timer_unit` 取帧数或秒数，已实机确认是帧数（默认档）。
        - `RAND`：借用已有的确定性噪声 `em.noise1()`（同一个 seed/frame 恒定复现），映到
          `[0, 1)`——范围本身也是猜的（"RAND"没有量级证据），选 `[0,1)` 是多数引擎的
          常见约定。
        - `EM_INIRAND`/`EM_INIRAND_SHARED`：命名暗示"初始化时抽一次、不逐帧变"，用
          `on_emitter_init` 那条播种流抽一次并缓存在 `em.user`。两者按同一个值处理——
          "SHARED" 大概率是"多个同时播放的实例共享同一个值"，预览只模拟单个实例，这一层
          差异建模不出来。
        - `PLAY_SPEED`：没有对应的模拟概念，固定给 1.0（未建模，不是"确认了就是 1"）。
        """
        cfg = self.config
        if cfg.expr_timer_unit == "seconds":
            timer = em.frame / float(cfg.fps or 60)
        else:
            timer = float(em.frame)
        inirand = em.user.get("_expr_inirand")
        if inirand is None:
            inirand = (em.noise1(em.seed, channel=0x5152) + 1.0) * 0.5
            em.user["_expr_inirand"] = inirand
        return {
            "PI": math.pi,
            "TIMER": timer,
            "RAND": (em.noise1(em.seed, channel=0x5241) + 1.0) * 0.5,
            "EM_INIRAND": inirand,
            "EM_INIRAND_SHARED": inirand,
            "PLAY_SPEED": 1.0,
        }

    # -- 内部 ----------------------------------------------------------------
    def _consume_spawn(self, em):
        n = em._pending_spawn
        em._pending_spawn = 0
        if n <= 0:
            return
        room = self.config.max_particles - len(em.particles)
        if room <= 0:
            em.note("触发硬上限 max_particles=%d，本帧不再生成"
                    % self.config.max_particles)
            return
        if n > room:
            em.note("触发硬上限 max_particles=%d，本帧生成被截断"
                    % self.config.max_particles)
            n = room
        for _ in range(n):
            idx = em.spawned_total
            em.spawned_total += 1
            p = Particle(idx, _rng.particle_seed(em.seed, idx), em.frame)
            # 默认出生在发射器原点。`EmitterShape3D` 会覆写成"原点 + 形状内采样点"，
            # 但没有生成方式属性的 entry 也得站在发射器上，不能留在世界原点。
            p.pos = em.origin.copy()
            prng = _rng.particle_rng(em.seed, idx)
            for b in self._h_spawn:
                b.behavior.on_particle_spawn(p, em, prng)
            em.particles.append(p)

    def _strict_call(self, b, p, em):
        """strict 模式：逐调用校验 behavior 没有越出它声明的阶段去写字段。

        这是"阶段按写什么命名"换来的唯一能自动检查的契约——behavior 多起来之后，没有它
        谁也说不清是谁把 pos 改坏的。
        """
        allowed = _stages.STAGE_WRITES.get(b.stage, frozenset())
        before = self._snapshot(p)
        b.behavior.on_particle_step(p, em)
        after = self._snapshot(p)
        for slot in _stages.CHECKED_SLOTS:
            if before[slot] != after[slot] and slot not in allowed:
                raise AssertionError(
                    "%s 在 %s 阶段写了 p.%s（该阶段只允许写 %s）"
                    % (b.type_name, _stages.stage_name(b.stage), slot,
                       ", ".join(sorted(allowed)) or "（无）"))

    @staticmethod
    def _snapshot(p):
        return {
            "pos": p.pos.as_tuple(),
            "vel": p.vel.as_tuple(),
            "scale": p.scale.as_tuple(),
            "rot": p.rot.as_tuple(),
            "color": tuple(p.color),
            "alpha": p.alpha,
            "age": p.age,
        }
