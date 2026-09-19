# -*- coding: utf-8 -*-
"""
blender_efx_re/field_visibility.py —— 按模式字段过滤生效字段（纯 UI 层，对齐姊妹项目
EFX-Editor 的 `blender_efx/field_visibility.py`）

某些字段只在另一个"模式"字段取特定值时才对游戏生效，其余取值下引擎直接忽略。这里按模式值
过滤显示：选定模式只暴露对应生效字段，其余隐藏。**纯视觉、非破坏**——隐藏字段的字节原样
保留，导出不受影响；面板有 `efx_re_show_all_fields` 开关兜底，随时能看到全部字段。

表结构：attr_type（$type 全名）-> { conditional_field: (mode_field, predicate) }
  predicate(mode_value:int) -> True 显示 / False 隐藏。
未列出的字段恒显示；mode 字段本身恒显示；读不到模式值时保守显示。

⚠ 置信度：Velocity3D 的 VelocityType 门控双重验证——(1) `EfxBridge condstats` 对全语料按
VelocityType 分桶统计字段取值分布：DirectionVectorX/Y/Z 在 VelocityType=0(Direction) 桶里
的取值多样性（distinct 计数、非众数占比）明显高于 1/2/3 桶；Offset/Size 反过来在
VelocityType=1(Normal) 桶里明显更活跃；Spread 只在 VelocityType=3(Spread) 桶里明显活跃
（其余三桶 99%+ 集中在 0.0，Spread 桶只有 31.6% 停在众数）。(2) 姊妹项目 EFX-Editor 对
MHWI 同名机制的研究本身就是从 RE-Engine 原生 VelocityType 枚举语义反查、再经 MHWI 实机
测试验证过的（`EFX-Editor/efx_format/schema/attributes.py:316-324`），两边独立证据一致。
VelocityType=2(Radial)/3(Spread) 两档下 Direction/Offset/Size 三组字段统计上都不活跃，
这是下面这套谓词（Direction 只在 0 显示、Offset/Size 只在 1 显示）的自然结果，不需要为
2/3 单独写规则。VelocityType=4(ScreenSpace)/5(Max) 全语料零样本（9241 个文件里一次没
出现过），同一套谓词下也会隐藏 Direction/Offset/Size——这是预测性外推，不是实测结论。
InheritRate/InheritDistance/GravityRate(+DelayFrame)/Speed(+Coef/DelayFrame) 在
condstats 里各个 VelocityType 桶之间没有看出差异（同样活跃或同样不活跃），暂不门控。
"""

# ── 版本性排除字段（结构性证据，不是语料统计巧合）─────────────────────────────
# 这批字段和上面 FIELD_VISIBILITY 的门控字段不是一回事：上面那些字段"在 MHWilds 里会被正常
# 读写，只是某个模式值下引擎不用它"；这里这些字段是 vendor 源码里 `RszVersion`/
# `RszVersionExact` 版本条件本身，**代入 Version=MHWilds(5571972) 求值恒为 False**——
# 生成的读写代码里那个 `if (条件)` 分支对 MHWilds 文件永远进不去，字段值只可能是 C# 默认值
# （0/false/null），不是"作者没用"，是"这个游戏版本的解析代码压根不会碰它"。
#
# 判据（tools/scan_version_excluded_fields.py，2026-09-17）：解析 vendor `EFX/*.cs` 里每个
# 字段的 RszVersion/RszVersionExact 条件文本，还原生成器的拼接规则（单参数→`>= X`；双参数
# 比较符→`运算符 X`；RszVersionExact→多个 `== X` 用 `||` 连；同一字段/EndAt 范围内的多个条件
# 按生成器的嵌套 if 语义 `&&` 在一起），代入 `Version = EfxVersion.MHWilds` 求值。同一个
# `EfxAttributeType` 有时有多个版本专属实现类（如 `TypeGpuMeshTrail` 的 V1/V2、
# `TypeStrainRibbon` 的 V1/V2/V3），必须用 `mhws_attribute_types.json`（`EfxBridge types`
# 实际按 MHWilds 解析出来的类名）核对候选字段所在的类是不是 MHWilds 真正用的那个，
# 扫描脚本天然会把同一枚举名下所有历史实现类的字段都收进来，这一步筛掉了 2 个假阳性
# （`TypeGpuMeshTrail.unkn3` 属于已被 V2 取代的旧类、`TypeStrainRibbon.unkn1_20_re8` 属于
# 已被 V3 取代的 V2 类）。剩下 82 个字段里 72 个还能在全语料（9175 个可读文件）里查到实例
# 并确认 `distinct==1`（恒为默认值，0 例外）；另外 10 个字段所在的 attribute 类型在这份语料
# 里出现次数是 0（如 `TypeRibbonTrail`/`TypeNodeBillboard`/`PtUvSequence`），没有样本可核对，
# 但结构性证据本身不依赖样本——读写代码进不去的分支不可能因为语料而有例外。
VERSION_EXCLUDED_FIELDS = {
    "ReeLib.Efx.Structs.Basic.EFXAttributeSpawn": {
        "LoopNumDmc5",
        "UseSpawnFrameInt",
        "re4_unkn0",
        "re4_unkn1",
        "re4_unkn2",
        "re4_unkn3",
        "re4_unkn4",
    },
    "ReeLib.Efx.Structs.Basic.EFXAttributeParentOptions": {
        "ParticleUseLocal_re7",
        "PragUkn1",
        "PragUkn2",
    },
    "ReeLib.Efx.Structs.Basic.EFXAttributeShaderSettings": {
        "LayerPositive",
        "toggle_re7",
        "unkn19",
        "toggle_re4",
        "re8_unkn3",
        "re8_unkn4",
        "re8_unkn5",
        "unkn25",
        "unkn26",
        "unkn27",
        "unkn28",
        "unkn29",
    },
    "ReeLib.Efx.Structs.Pt.EFXAttributePtBehavior": {
        "varCount",
    },
    "ReeLib.Efx.Structs.Pt.EFXAttributePtColliderAction": {
        "dd2_unkn2",
    },
    "ReeLib.Efx.Structs.Pt.EFXAttributePtCollision": {
        "unkn13",
        "LookNormalDirectionOffset",
        "DelayFrameCollision",
    },
    "ReeLib.Efx.Structs.Pt.EFXAttributePtUvSequence": {
        "unkn1_2",
    },
    "ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3D": {
        "prag_unkn",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3D": {
        "ShadowType",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeNodeBillboard": {
        "Area0Blend_RE7",
        "Area1Blend_RE7",
        "Area2Blend_RE7",
        "Area3Blend_RE7",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuBillboard": {
        "instanceCount",
        "unkn3",
        "re4Ukn",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshClip": {
        "mdfPropertyCount",
        "mdfPropertyCountDouble",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshExpression": {
        "matExpressionCount",
        "matExpressionSize",
        "indicesCount",
        "materialExpressionsList",
        "materialIndices",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMesh": {
        "unkn3",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMeshTrailV2": {
        "unkn33",
        "unkn34",
        "unkn35",
        "unkn36",
        "unkn39",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypePolygon": {
        "AlphaRateLegacy",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuPolygon": {
        "unkn1",
        "unkn2",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLengthMaterial": {
        "dd2_unkn1",
        "Flags2",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonChain": {
        "unkn2_18",
        "sb_unkn1",
        "sb_unkn2",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFixEnd": {
        "Flags2",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFollow": {
        "unkn14_re2",
        "unkn_re7",
        "unkn_re7_2",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonTrail": {
        "FlagsRe4",
        "FlagsDmc5",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuRibbonFollow": {
        "unkn1",
        "unkn2",
        "unkn3",
        "unkn4",
        "re4_unkn5",
        "UknDmc5",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuRibbonLength": {
        "unkn1",
        "unkn_Re4",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonV3": {
        "unkn8_0",
        "unkn8_color1",
        "unkn8_color2",
        "unkn8_3",
        "unkn8_4",
        "unkn8_5",
        "unkn8_6",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonMaterial": {
        "unkn46",
        "dd2Unkn",
    },
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonMaterialExpression": {
        "unkn22",
    },
}


# ── 谓词（模块级具名，便于复用/可读）───────────────────────────────────────────
def _eq0(v): return v == 0
def _eq1(v): return v == 1
def _eq2(v): return v == 2
def _eq3(v): return v == 3
def _eq0_or_3(v): return v == 0 or v == 3
def _is_sphere_or_cylinder(v): return v == 1 or v == 2

#: `EFXAttributeAttractor.Flags` 低 2 位是"吸引目标模式"枚举（0=默认/1=未知/2=世界系目标点/
#: 3=锁定粒子生成点，见 mhws_field_labels.json 该字段的 `bits` 段说明），第 4 位（数值 8）
#: 是形状系统总开关。这里的 `v` 是 `Flags` 整个字段的原始值，不是解出来的子段值，
#: 直接按位运算取子段——跟 `_mode_getter()` 读回来的是同一个原始 int。
def _attract_target_is_world(v): return (v & 3) in (1, 2)  # 模式1未知，保守不隐藏
def _shape_system_active(v): return (v & 8) != 0


FIELD_VISIBILITY = {
    # Velocity3D：VelocityType=0(Direction) 用 DirectionVector 定方向；
    # =1(Normal) 用 Offset+Size 共同决定方向；=3(Spread) 时 Spread（扩散锥角，弧度制）生效，
    # 锥轴仍取 DirectionVector，所以它在 0 和 3 两档都要显示（见
    # `efx_sim/behaviors/velocity3d.py` 的四档方向模型）。
    "ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity3D": {
        "DirectionVectorX": ("VelocityType", _eq0_or_3),
        "DirectionVectorY": ("VelocityType", _eq0_or_3),
        "DirectionVectorZ": ("VelocityType", _eq0_or_3),
        "Offset":           ("VelocityType", _eq1),
        "Size":             ("VelocityType", _eq1),
        "Spread":           ("VelocityType", _eq3),
    },
    # EmitterShape3D：`RangeDivideNum`/`RangeDivideAxis`（等分数量/等分坐标轴）实机确认只有
    # ShapeType=0(Box) 用；`RangeDivideHorizontalNum`/`RangeDivideVerticalNum`（横/纵向等分
    # 数量）只有 ShapeType∈{1(Sphere),2(Cylinder)} 用（用户 2026-09-17 实机测试确认，三档形状
    # 互斥，没有交集）。
    #
    # ⚠ `ScaleHorizontal`/`ScaleVertical` **故意不在这张表里**——之前这里按 §8.4 的 ShapeType
    # 分桶加过"球+圆柱用 ScaleHorizontal、只有球用 ScaleVertical"两条规则，2026-09-17 用
    # `EfxBridge condstats EmitterShape3D ShapeType,UseExtension`（联合分桶）复核后发现是错的，
    # 已经撤掉：`UseExtension=false` 时两个字段确实都锁死在中性默认值上（Box/Cylinder 的
    # ScaleVertical 恒为 `(1.0,0.0)`、Box 的 ScaleHorizontal 也恒为 `(1.0,0.0)`，无一例外），
    # 但 **`UseExtension=true` 时 Box 的 ScaleHorizontal/ScaleVertical 都出现了大量非默认取值
    # （distinct 11/8，非弧度常数，是 0~2 之间的小数——看着像缩放/锥度系数，不是角度）**，
    # Cylinder 的 ScaleVertical 同样在 `UseExtension=true` 下出现 38 个非默认取值（同样是
    # 0~1.5 一带的小数，不是 π 的倍数）。也就是说这两个字段被"按形状复用"了：球体上两者都是
    # 弧度角（已实机确认的锥面/补角模型），圆柱体上 Horizontal 仍是角度但 Vertical 变成别的
    # （疑似类似上一代 ES3D 的起止半径/锥度），立方体上两者都变成别的。真正决定"这个字段现在
    # 是不是角度"的是 `UseExtension`，不是 `ShapeType`——而当前 `field_hidden()` 的谓词只支持
    # 单一模式字段，且 Blender 侧读 Bool 型模式字段的 `_mode_getter()`（panels.py）还没打通
    # （`model._read_packed_int()` 认的是 `int_value`，Bool 节点存在 `bool_value` 里，混用会
    # 读出错误的 0）。在这两块都打通之前宁可不筛（本形状可能用得上，隐藏了才是真的骗用户），
    # 详见 `docs/SIM_PORT_PLAN.md` §8.4 追记。
    #
    # 追记（2026-09-17，`EfxBridge condstats … DivideEquidistant`）：`DivideEquidistant` /
    # `DivideEquidistantCalcOuterCurveData` / `DivideEquidistantRecalcEveryFrameData` 这三个
    # "存疑"布尔全语料仅 197 个非默认样本（188+5+4），但**这 197 个无一例外 ShapeType=2
    # (Cylinder)**——三个字段互相独立出现（没有两个同时为 true 的样本），但没有一个出现在
    # Box/Sphere 桶里。样本量小，先按 Cylinder-only 门控，字段本身的作用仍未知（不升级
    # tooltip，只加门控）。这三个字段不受上面 ScaleHorizontal/ScaleVertical 那条撤回的影响——
    # 它们的门控字段是 ShapeType（int），不是 UseExtension（bool），`_mode_getter()` 认得。
    "ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape3D": {
        "RangeDivideNum":                       ("ShapeType", _eq0),
        "RangeDivideAxis":                       ("ShapeType", _eq0),
        "RangeDivideHorizontalNum":              ("ShapeType", _is_sphere_or_cylinder),
        "RangeDivideVerticalNum":                ("ShapeType", _is_sphere_or_cylinder),
        "DivideEquidistant":                     ("ShapeType", _eq2),
        "DivideEquidistantCalcOuterCurveData":   ("ShapeType", _eq2),
        "DivideEquidistantRecalcEveryFrameData": ("ShapeType", _eq2),
    },
    # Attractor：`Flags` 是好几个互不相关的子系统共用一个 uint 拼出来的（低 2 位一个目标点
    # 模式枚举 + 独立的形状系统开关，中间夹着一个还没验证出效果的单比特），门控字段直接填
    # "Flags" 自己，谓词按位取子段，不走标准的"整数相等"比较。用户 2026-09-17/18 实机测试：
    # 模式=2 才会激活 AttractPositionWorld（模式=1 从没单独测出效果，保守不隐藏，模式=0/3
    # 确认无效）；`Flags` 第 4 位（数值 8）不开，`ShapeRangeX/Y/Z`/`ShapeRotation` 这一整套
    # 形状参数不生效。取值分布/分档细节见 mhws_field_labels.json 该字段的 `bits` 段。
    "ReeLib.Efx.Structs.Misc.EFXAttributeAttractor": {
        "AttractPositionWorld": ("Flags", _attract_target_is_world),
        "ShapeRangeX":          ("Flags", _shape_system_active),
        "ShapeRangeY":          ("Flags", _shape_system_active),
        "ShapeRangeZ":          ("Flags", _shape_system_active),
        "ShapeRotation":        ("Flags", _shape_system_active),
    },
}


# ── 行为性废弃字段（实机证据，不是结构性证据）───────────────────────────────
# 跟 VERSION_EXCLUDED_FIELDS 不是一回事：那批字段是"这个版本的读写代码压根进不去这个分支"，
# 有 RszVersion 条件文本可以代入求值证明；这里这些字段在 MHWilds 下**照常读写**，只是实机
# 测试发现改任何值都测不出效果，判定是老游戏版本遗留、被同 attribute 的别的字段接管了功能。
# 证据强度比结构性排除弱（"测不出效果"没法像条件求值一样穷举证明），所以单独放一张表，
# 不跟 VERSION_EXCLUDED_FIELDS 混在一起——别把这两种证据的置信度混为一谈。
BEHAVIORALLY_DEAD_FIELDS = {
    # EFXAttributeAttractor.ForceResist：RE4/DD2 就有的老字段，MHWilds 下全语料 9175 个文件
    # 1105 个 Attractor 实例里 1104 个恒为 0.0（唯一例外 0.2），用户实机测试改任意值无可见效果；
    # 同一 attribute 的 MHWilds 专属字段 ForceResistWilds 已确认接管了阻尼/阻力的语义
    # （2026-09-17，见 tools/vendor-patches/README.md #0006）。
    "ReeLib.Efx.Structs.Misc.EFXAttributeAttractor": {
        "ForceResist",
    },
}


def has_rules(attr_type) -> bool:
    """该 attribute 类型是否有任何隐藏规则（模式门控、版本性排除或行为性废弃）——决定面板
    要不要画"显示全部字段"开关。"""
    return (
        attr_type in FIELD_VISIBILITY
        or attr_type in VERSION_EXCLUDED_FIELDS
        or attr_type in BEHAVIORALLY_DEAD_FIELDS
    )


def field_hidden(attr_type, ori_name, get_value) -> bool:
    """该字段当前是否应隐藏。get_value(field_name)->int|None。

    版本性排除（VERSION_EXCLUDED_FIELDS）和行为性废弃（BEHAVIORALLY_DEAD_FIELDS）都恒隐藏，
    不看任何模式值——前者是结构性证据（条件恒假），后者是实机测试证据（改值无效果）。"""
    if ori_name in VERSION_EXCLUDED_FIELDS.get(attr_type, ()):
        return True
    if ori_name in BEHAVIORALLY_DEAD_FIELDS.get(attr_type, ()):
        return True
    rules = FIELD_VISIBILITY.get(attr_type)
    if not rules:
        return False
    rule = rules.get(ori_name)
    if rule is None:
        return False
    mode_field, pred = rule
    cur = get_value(mode_field)
    if cur is None:
        return False  # 读不到模式值 → 保守显示
    try:
        return not pred(int(cur))
    except Exception:
        return False
