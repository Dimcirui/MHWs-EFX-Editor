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

# ── 谓词（模块级具名，便于复用/可读）───────────────────────────────────────────
def _eq0(v): return v == 0
def _eq1(v): return v == 1
def _eq3(v): return v == 3


FIELD_VISIBILITY = {
    # Velocity3D：VelocityType=0(Direction) 用 DirectionVector 定方向；
    # =1(Normal) 用 Offset+Size 共同决定方向；=3(Spread) 时 Spread（扩散锥角，弧度制）生效。
    "ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity3D": {
        "DirectionVectorX": ("VelocityType", _eq0),
        "DirectionVectorY": ("VelocityType", _eq0),
        "DirectionVectorZ": ("VelocityType", _eq0),
        "Offset":           ("VelocityType", _eq1),
        "Size":             ("VelocityType", _eq1),
        "Spread":           ("VelocityType", _eq3),
    },
}


def field_hidden(attr_type, ori_name, get_value) -> bool:
    """该字段当前是否应隐藏（据其模式字段的当前值）。get_value(field_name)->int|None。"""
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
