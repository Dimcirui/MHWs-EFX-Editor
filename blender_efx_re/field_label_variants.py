# -*- coding: utf-8 -*-
"""
blender_efx_re/field_label_variants.py —— 按模式字段切换 label/tooltip/unit（纯 UI 层）

某些字段的底层字节在不同模式值下代表完全不同的量——同一个 `{s,r}` 存储槽位，
`EmitterShape3D` 的 `ScaleHorizontal`/`ScaleVertical` 按 `ShapeType` 分别是"角度"
（Sphere/Cylinder 的方位角、Sphere 的立体角补角）和"缩放系数"（Cylinder 的径向锥度、Box 的
X/Z 轴锥度），套同一条 label/tooltip/角度显示开关会文不对题——"水平扫描"这个名字在 Box 上
根本不是扫描，"角度转度数"开关在 Box 上会把缩放系数误显示成假的度数。见
`efx_sim/behaviors/emittershape3d.py` 模块说明、`docs/SIM_PORT_PLAN.md` §8.4。

这里只覆盖 `label_zh`/`tooltip_zh`/`unit` 三个键，其余键（`confidence`/`evidence`/`tester`/
`date`）仍然从知识表原条目继承——面板不展示这几项（见 `panels._field_tooltip()` 的说明），
但保留它们语义完整，将来要是给 evidence 加显示入口不用回头改这张表。

表结构：`attr_type -> field_key -> (mode_field, {mode_value: override_dict})`。
`override_dict` 里某个键的值是 `None` 表示"删掉这个键"（`unit: None` 用来在缩放系数分支
去掉继承来的 `angle_radians` 标注，不然角度显示开关会误命中）。
"""

FIELD_LABEL_VARIANTS = {
    "ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape3D": {
        "ScaleHorizontal": ("ShapeType", {
            0: {"label_zh": "水平锥度",
                "tooltip_zh": "沿高度线性变化的 X 轴缩放系数；需勾选“启用扩展”才生效。",
                "unit": None},
            1: {"label_zh": "水平扫描角",
                "tooltip_zh": "弧度制方位角，起始角+跨度；需勾选“启用扩展”才生效。",
                "unit": "angle_radians"},
            2: {"label_zh": "水平扫描角",
                "tooltip_zh": "弧度制方位角，起始角+跨度；需勾选“启用扩展”才生效。",
                "unit": "angle_radians"},
        }),
        "ScaleVertical": ("ShapeType", {
            0: {"label_zh": "垂直锥度",
                "tooltip_zh": "沿高度线性变化的 Z 轴缩放系数；需勾选“启用扩展”才生效。",
                "unit": None},
            1: {"label_zh": "垂直扫描角",
                "tooltip_zh": "弧度制立体角补角；需勾选“启用扩展”才生效。",
                "unit": "angle_radians"},
            2: {"label_zh": "径向锥度",
                "tooltip_zh": "沿高度线性变化的径向缩放系数；需勾选“启用扩展”才生效。",
                "unit": None},
        }),
        # RangeDivideVerticalNum 同一个字段在 Sphere 上是"纬度分几档"、Cylinder 上是
        # "高度分几层"——数值语义相同（都是"均分成 n 个点，含两端"），但均分的是哪根轴不同，
        # 文案跟着 ShapeType 换（Box 不出现在这张表里：field_visibility.py 已经把它对 Box
        # 整个隐藏了，压根不会走到这条覆盖）。
        "RangeDivideVerticalNum": ("ShapeType", {
            1: {"tooltip_zh": "把张角均分成 n 个纬度圆锥面（n=2/3 退化为竖线/赤道面）。"},
            2: {"tooltip_zh": "把高度均分成 n 个垂直于 Y 轴的圆环面。"},
        }),
    },
}


def resolve_entry(attr_type, field_key, base_entry, get_value):
    """按当前模式值返回覆盖后的知识表条目；查不到规则、或读不到模式值时原样返回
    `base_entry`——跟 `field_visibility.field_hidden()`"读不到模式值就保守显示"是同一个
    原则：不确定就不改文案。`get_value(mode_field) -> int|None`。
    """
    table = FIELD_LABEL_VARIANTS.get(attr_type)
    rule = table.get(field_key) if table else None
    if rule is None:
        return base_entry
    mode_field, variants = rule
    mode_value = get_value(mode_field)
    if mode_value is None:
        return base_entry
    try:
        override = variants.get(int(mode_value))
    except (TypeError, ValueError):
        return base_entry
    if override is None:
        return base_entry
    merged = dict(base_entry or {})
    for key, value in override.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged
