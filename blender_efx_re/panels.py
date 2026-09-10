"""
blender_efx_re/panels.py —— 面板层

面板划分对齐姊妹项目 EFX-Editor（见其 CLAUDE.md §4「UI / 命名约定」）：

1. **工具功能 vs 属性数据**：导入/导出/校验/复制粘贴这类"对对象做操作"的东西放 N 面板；
   "对象自身解析出来的数据"（Root 的骨骼表/参数表、Entry 的 EffectGroups 标签、Attribute 的
   字段/Clip/Expression）既放 N 面板也镜像进属性编辑器的 Object Data 标签。两处**共用同一个
   `_draw_*_content()` 函数**，绝不让绘制逻辑分叉——分叉之后两边迟早不一致。
2. **一个关注点一个 Panel**，靠 `poll()` 按 `~TYPE` 显隐，而不是在一个巨型面板里
   `if type_tag == ...` 分支平铺（本文件上一版就是那样，选中一个 attribute 时元信息、Clip
   曲线、Expression 公式、字段树一路铺到底，没法单独折叠、也不记状态）。
3. **`bl_order` 用负数**：Blender 里没显式设 `bl_order` 的面板默认值就是 0，用正数反而会被排到
   那些"默认顺序"面板后面（姊妹项目踩过这个坑，直接抄结论）。

与姊妹项目刻意不同的两点：

- **N 面板标签页叫 `Wilds EFX`，不跟它统一成 `EFX`**：两个插件可能装在同一个 Blender 里，
  `bl_category` 撞名会把两套面板混进同一个标签页。
- **属性编辑器只镜像 `bl_context="data"`，不做 `"object"` 保底**：姊妹项目两个都注册，是因为
  当时不确定 Empty 的 Data 标签在各版本上渲不渲染。本项目的 `~TYPE` 对象全部由
  `io_tree._new_empty()` 创建，必然是 Empty，而 Empty 的 Data 标签（"空物体"设置页）在
  blender_manifest.toml 声明的 4.3+ 上是有效的；两个都注册的话同一份字段列表会在两个标签页里
  各画一遍，纯噪音。真遇到渲染不出来的版本再加保底。

字段级的文案（标签/tooltip）来自 semantics/ 知识表，不走 i18n.py 的 `T()`——见 `_field_label()`。
"""

from __future__ import annotations

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from bpy.types import Menu, Panel, UIList

from . import attribute_types, bitfield, bridge, copy_paste, i18n, io_tree, model, semantics, structure_ops
from .i18n import T

# 取活动对象一律用 `getattr(context, "object", None)` 而不是 `context.object`：脚本/后台
# 调用（比如通过 MCP 桥或 `--background`）拿到的 Context 上**没有** `object` 属性，直接取会
# AttributeError 而不是拿到 None，算子的 poll 会当场炸掉而不是安静地返回 False。


class EFX_RE_OT_field_info(bpy.types.Operator):
    """悬浮显示字段知识表里的说明文字的占位按钮——点击不做任何事，只借用 Blender operator
    tooltip 支持动态文本（`description()` classmethod）这一机制来显示 tooltip，
    因为 `UILayout.label()` 本身不支持 tooltip。"""

    bl_idname = "efx_re.field_info"
    bl_label = ""
    bl_options = {"INTERNAL"}

    tooltip_text: StringProperty(options={"HIDDEN"})

    @classmethod
    def description(cls, context, properties):
        return properties.tooltip_text or "（此字段暂无标注）"

    def execute(self, context):
        return {"CANCELLED"}


def _field_label(entry: dict | None, key: str) -> str:
    """一个字段该显示的名字。

    知识表目前只有中文标注（`label_zh`/`tooltip_zh`），英文那一侧**故意退回原始 JSON 键名**
    （`RelationPos` 这种）——键名本来就是英文，而且是这个字段在 RE-Engine-Lib / 010 模板 /
    社区讨论里的权威名字，比现编一个英文意译更有用。表里以后要是补了 `label_en`，这里自动优先用。
    """
    if entry is None:
        return key
    if i18n.get_lang() == "EN":
        return entry.get("label_en") or key
    return entry.get("label_zh") or key


def _field_tooltip(entry: dict | None) -> str:
    """一个字段的 tooltip。英文侧没有 `tooltip_en` 时退回中文原文，而不是留空——整张表现在
    都是中文，英文模式下全部丢掉说明是更大的损失。

    只取 `label_*`/`tooltip_*`。表里的 `confidence`/`evidence`/`tester`/`date` **不进界面**：
    这几项是给我们自己排查用的元数据，使用者需要知道的是"这个字段干什么"，不是"这条结论谁验的、
    验没验过"（CLAUDE.md 第 23 条，姊妹项目 EFX-Editor 的同一条规则是其 CLAUDE.md §4.1）。
    """
    if entry is None:
        return ""
    if i18n.get_lang() == "EN":
        return entry.get("tooltip_en") or entry.get("tooltip_zh") or ""
    return entry.get("tooltip_zh") or ""


def _draw_label(layout, text: str) -> None:
    """画一个字段的标签：纯 label()，天然左对齐，不用再操心跟按钮抢对齐方式。

    translate=False：这里的 text 要么是原始 JSON 键名（如 "Saturation"），要么是知识表里
    已经写好的中文——都不该再被 Blender 自带的界面翻译表拦截替换。默认 translate=True 时，
    只要这段文字碰巧和 Blender 内置词条完全相同（"Saturation" 这种常见颜色管理术语就撞上了），
    界面语言选中文时会被静默换成"饱和度"，看起来像是我们知识表标注的结果，实际上跟内容语义
    无关——在 Blender 5.1 中文界面下实测复现过。

    tooltip 不在这里画，见 `_draw_field_help_icon()`——早先版本把整个字段名做成
    operator() 按钮来借用它的动态 tooltip，踩了两个坑：(1) 按钮默认居中画文字，跟
    label() 的左对齐不一致，得再套一层 alignment='LEFT' 的子 row 才能纠正；(2) 纠正
    对齐的同时按钮会收缩到只剩文字本身那么宽，鼠标必须精确停在文字上才触发，稍微偏一点
    落在原本按钮占的空白区域就完全没反应——用户反馈"tooltip 完全看不见"，实际是命中率
    问题不是真的没画。改成对齐姊妹项目 EFX-Editor 的 ⓘ 图标机制（`_draw_field_row_buttons`）
    以后，图标本身多大鼠标命中区就多大，不存在这个问题。
    """
    layout.label(text=text, translate=False)


def _draw_field_help_icon(row, entry: dict | None) -> None:
    """字段行末尾追加一个 ⓘ 图标，只有这个字段在知识表里有 tooltip 才画，悬停即显示说明。
    对齐姊妹项目 EFX-Editor 的做法（见其 `_draw_field_row_buttons()`）：tooltip 交给一个
    独立的小图标承载，不跟字段名文字本身混在一起。"""
    tooltip = _field_tooltip(entry)
    if not tooltip:
        return
    op = row.operator("efx_re.field_info", text="", icon="INFO", emboss=False)
    op.tooltip_text = tooltip


# 字段树里"标签 | 值"这类行必须统一用 split(factor=...) 而不是"先画 label 再另起一个
# row() 分列表格"：在 Blender 5.1 实测确认过，同一个 column(align=True) 里如果相邻几行的
# 标签宽度不一致（label()/operator() 按文字长度自适应宽度，"LoopNum" 和 "EmitterDelayFrame"
# 长度差很多），行与行之间的对齐合并会把某一行值区的第二个及以后的控件整个吞掉——不报错、
# Python 侧该调的 prop() 也都调了，纯粹是 Blender 内部按钮合并算法按错位的列边界瞎配对
# 导致的静默丢画。用固定 factor 的 split() 保证所有行的标签列宽度完全一致，问题消失（同一份
# 数据、同一套子字段形状，split() 版本和 row() 版本对照验证过）。
_FIELD_SPLIT_FACTOR = 0.32


# data_type -> 对应存储标量值的 Object 属性名（NULL 没有对应 slot，单独处理）。
_SCALAR_PROP_ATTR = {
    "FLOAT": "float_value",
    "INT": "int_value",
    "BIGINT": "uint_str",
    "BOOL": "bool_value",
    "STRING": "string_value",
}


def _draw_scalar_prop(layout, node, text: str = "", prop_name: str | None = None) -> None:
    """画一个标量节点自身的值控件（不画字段名标签）。XYZ/static-random 并排列布局和普通单行
    布局共用这个函数，只是传的 layout/text 不同——单行布局传 text=""（标签已经在旁边画过），
    并排列布局传 text="X"/"Value" 这类，让 Blender 把短标签内联画在数值框左边（对齐姊妹项目
    EFX-Editor `comp_row.prop(item, "int3_value", index=0, text="X")` 的做法）。

    `prop_name` 显式指定要绑定的属性名，覆盖按 `data_type` 推算的默认值——目前只有"角度显示"
    开关命中时会传 `"degrees_value"`（画弧度制角度字段的 X/Y/Z 分量），见 `draw_node()` 的
    XYZ 分支。"""
    attr = prop_name or _SCALAR_PROP_ATTR.get(node.data_type)
    if attr is None:
        layout.label(text="null", translate=False)
        return
    layout.prop(node, attr, text=text)


def draw_node(layout, node, attr_type: str | None = None, root_obj=None, attr_owner=None) -> None:
    """递归绘制一个 EFXValueNode：标量画一行 prop()，OBJECT/ARRAY 如果只有 1~3 个标量子项就
    并排画在同一行（不值得折叠），否则画一个可折叠 box 递归绘制 children。ui_expand 只影响
    面板显示，不参与导出——见 model.py 里 EFXValueNode 的说明。

    attr_type 只在最外层调用（`_draw_fields_content()`）传入，用来查知识表；递归到子字段时传
    None——Vector 类型的 x/y/z 这类子字段名字本身已经够自解释，知识表不索引这一层。
    root_obj 同理只在最外层传（该 attribute 所属的 EFX_ROOT），供 ParentBone 字段画
    prop_search 时定位 efx_bones 列表；递归到子字段时不需要，因为骨骼引用字段结构上必然只出现
    在 attribute 的顶层内容字段，不会嵌套在子对象里（见 model.is_bone_reference_field()）。
    """
    entry = semantics.get_field_entry(attr_type, node.key) if attr_type else None
    label_text = _field_label(entry, node.key)

    dtype = node.data_type
    if root_obj is not None and model.is_bone_reference_field(node, attr_type):
        # ParentBone：按名字引用 EFX_ROOT.efx_bones 里的条目，不是裸下标（C# 后端自己在
        # 读时把下标解析成名字、写时再反查回下标，见 docs/TOPLEVEL_STRUCTURE.md）。用 Blender
        # 原生 prop_search——和挑选顶点组/骨骼同一个"输入名字、自动补全校验"控件，比裸文本框
        # 更不容易手滑打错字；导出前 io_tree.check_bone_references() 还会再校验一遍防止
        # 引用了列表外的名字（那种情况 C# 后端会静默丢弃绑定，不报错）。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        split.prop_search(node, "string_value", root_obj, "efx_bones", text="", icon="BONE_DATA")
        _draw_field_help_icon(row, entry)
        return

    segs = bitfield.segments(entry)
    if not segs and dtype in ("INT", "BIGINT") and attr_type:
        # C# 侧声明成枚举的字段：合成一个"单段位域"规格，直接复用位域那套编辑器。
        # 枚举本来就是位域的退化情形（一整个字段就是一段），没必要另写一条绘制/编辑路径。
        members = attribute_types.enum_members(attr_type, node.key)
        if members:
            segs = [{"mask": 0xFFFFFFFF, "label_zh": label_text, "label_en": label_text,
                     "items": [[v, n, n] for v, n in members]}]

    if segs and dtype in ("INT", "BIGINT"):
        if len(segs) == 1 and segs[0]["mask"] == 0xFFFFFFFF:
            # 只有一段、且这一段占满整个字段：本质就是一个单选枚举（RotationOrder、
            # "持续开关"这类"退化成单选项的位域"），不值得为了一个选项弹窗多点一次——
            # 直接内联画下拉（对齐姊妹项目 EFX-Editor 的做法：真正的多值位域才弹窗，
            # 见 bitfield.py 顶部说明）。真正的多段位域（`UVSequence.Flags` 那种）
            # mask 不会占满整个字段，仍然走下面的弹窗。
            _draw_single_enum_row(layout, node, label_text, entry, segs[0])
            return
        # 多段位域：画一个显示解码摘要的按钮，点开弹窗逐段选（见 bitfield.py）。
        # 不再画裸数字——`UVSequence.Flags` 的众数是 41，谁看得出那是"循环+水平随机翻+
        # 垂直随机翻+正向"。
        _draw_bitfield_row(layout, node, label_text, entry, segs, attr_owner)
        return

    if dtype == "OBJECT" and model.is_rgba_color_node(node):
        # via.Color 在 JSON 里的真实形状是单键 {"rgba": <打包 uint32>}，不是 [R,G,B,A] 四个
        # 独立字段（C# 端 R/G/B/A 是 [JsonIgnore] 计算属性，不落盘）——见 model.py 的说明。
        # 画成颜色轮而不是"1 items 折叠框 + 一个巨大整数"，get/set 直接读写那个 rgba 子节点。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        split.prop(node, "color_value", text="")
        _draw_field_help_icon(row, entry)
        return

    xyz_order = model.xyz_child_order(node) if dtype == "OBJECT" else None
    if xyz_order is not None:
        # Vector3 类形状画成三列并排（对齐姊妹项目 EFX-Editor 的 XYZ 展示风格），不画成
        # "3 items" 折叠框——X/Y/Z 分量本身已经够自解释，不需要再单独折叠/查知识表。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        by_key = {c.key: c for c in node.children}
        cols = split.row(align=True)
        # 属性编辑器（Object Data 标签）默认 use_property_split=True，会把带 text= 的 prop()
        # 画成"标签独占一列 + 冒号 + 数值另起一列"——数字滑条控件不受这个影响（label 是画在
        # 按钮内部的，天生紧凑），但下拉框（enum_proxy）会被拆成"X: [很宽的下拉]"，X 和冒号
        # 之间还带着列对齐的空隙，比原来的裸数字滑条明显松散。关掉它，X/Y/Z 标签自己用
        # label() 画（见下面的 axis_enum_items 分支），不依赖 prop() 的隐式标签列。
        cols.use_property_split = False
        # 弧度制角度字段（知识表 unit == "angle_radians"，目前只标注了 Transform3D.
        # LocalRotation）+ Scene.efx_re_angle_degrees 开关同时命中时，X/Y/Z 分量改画
        # degrees_value（Blender ANGLE 子类型代理属性，按度显示/输入，内部仍存弧度，见
        # model.py EFXValueNode 的说明），不改变 float_value 本身。
        show_degrees = (
            entry is not None and entry.get("unit") == "angle_radians"
            and getattr(bpy.context.scene, "efx_re_angle_degrees", False)
        )
        # 分轴枚举（`ParentOptions.RelationPos/RelationRot/RelationScl` 这类"X/Y/Z 每个分量
        # 各自是同一张选项表里的单选枚举"）：知识表按字段整体标注一张共享的 axis_enum_items，
        # 三个分量各画一个内联下拉，不再画裸数字——0-3 的编号谁也记不住哪个是哪个。
        axis_enum_items = entry.get("axis_enum_items") if entry else None
        for key in xyz_order:
            child = by_key[key]
            if axis_enum_items and child.data_type in ("INT", "BIGINT"):
                # 下拉框自己画标签（不借 prop() 的 text=）：对齐姊妹项目 EFX-Editor 画
                # EnumVec3 的方式（`r.label(text=axis); r.prop(item, prop, text="")`），
                # 不留冒号。裸 label() 在 row() 里默认还是会按"剩余空间平分"占一份宽度，
                # 不是按文字宽度收紧——必须显式 ui_units_x 卡死宽度才不会在 X 和下拉框之间
                # 留一整块空白。
                label_col = cols.row(align=True)
                label_col.ui_units_x = 1.1
                label_col.label(text=key.upper(), translate=False)
                model.set_inline_enum_items(child, axis_enum_items)
                cols.prop(child, "enum_proxy", text="")
                continue
            prop_name = "degrees_value" if show_degrees and child.data_type == "FLOAT" else None
            _draw_scalar_prop(cols, child, text=key, prop_name=prop_name)
        _draw_field_help_icon(row, entry)
        return

    if dtype == "OBJECT" and model.is_min_max_node(node):
        # SpawnNum/IntervalFrame/EmitterDelayFrame：序列化形状跟普通二维向量一样是 {x, y}，
        # 但实测语义是 min/max（见 model.is_min_max_node() 的说明）。画成 Min/Max 两列，
        # 顺手在 max < min 时给红字提示——这个组合会让游戏崩溃，不是普通的数值校验问题。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        by_key = {c.key: c for c in node.children}
        cols = split.row(align=True)
        _draw_scalar_prop(cols, by_key["x"], text="Min")
        _draw_scalar_prop(cols, by_key["y"], text="Max")
        _draw_field_help_icon(row, entry)
        if model.node_scalar(by_key["y"]) < model.node_scalar(by_key["x"]):
            warn = layout.row()
            warn.alert = True
            warn.label(text=T("attribute.min_max_crash_warning"), icon="ERROR", translate=False)
        return

    if dtype == "OBJECT" and model.is_sr_index_node(node):
        # SequenceNo：形状和 static/random 一样是 {s,r}，但实测 s 恒等于 r+1(或+4)、随机只在
        # [0,r] 里选——画成 UnknIndex(s)/Index(r)，不是 Static/Random（见 model.py 的说明）。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        by_key = {c.key: c for c in node.children}
        cols = split.row(align=True)
        _draw_scalar_prop(cols, by_key["r"], text="Index")
        _draw_scalar_prop(cols, by_key["s"], text="UnknIndex")
        _draw_field_help_icon(row, entry)
        return

    if dtype == "OBJECT" and model.is_sr_min_max_node(node):
        # PatternNo/PlaySpeed：形状和 static/random 一样是 {s,r}，但实测是 min/max 范围。
        # PatternNo 是 s=Max/r=Min（顺序和 is_min_max_node 的 x/y 相反），PlaySpeed 是
        # s=Min/r=Max（顺序本来就对）——按字段名分别决定哪个是 Min 哪个是 Max。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        by_key = {c.key: c for c in node.children}
        cols = split.row(align=True)
        if node.key == "PatternNo":
            min_child, max_child = by_key["r"], by_key["s"]
        else:
            min_child, max_child = by_key["s"], by_key["r"]
        _draw_scalar_prop(cols, min_child, text="Min")
        _draw_scalar_prop(cols, max_child, text="Max")
        _draw_field_help_icon(row, entry)
        return

    if dtype == "OBJECT" and model.is_static_random_node(node):
        # via.Range{s,r} 画成两列并排：Static（对应 s）/ Random（对应 r）。用户明确要求用这组
        # REE 惯例命名而不是 MHWI 社区惯用的 Value/Jitter——这套命名以后计划回哺到 EFX-Editor，
        # 两边统一用 REE 这边的说法（不是反过来）。
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, label_text)
        by_key = {c.key: c for c in node.children}
        cols = split.row(align=True)
        _draw_scalar_prop(cols, by_key["s"], text="Static")
        _draw_scalar_prop(cols, by_key["r"], text="Random")
        _draw_field_help_icon(row, entry)
        return

    if dtype == "OBJECT" or dtype == "ARRAY":
        small_list = (
            1 <= len(node.children) <= 3
            and not any(c.data_type in ("OBJECT", "ARRAY") for c in node.children)
        )
        if small_list:
            # 1~3 个标量子项：不值得再套一层可折叠 box——直接并排画（对齐 xyz/static-random
            # 那两种特化形状已经在用的展示风格），子项的 key 本身就是够用的短标签。
            row = layout.row(align=True)
            split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
            _draw_label(split, label_text)
            cols = split.row(align=True)
            for child in node.children:
                _draw_scalar_prop(cols, child, text=child.key)
            _draw_field_help_icon(row, entry)
            return
        header = layout.row(align=True)
        icon = "TRIA_DOWN" if node.ui_expand else "TRIA_RIGHT"
        header.prop(node, "ui_expand", icon=icon, icon_only=True, emboss=False)
        _draw_label(header, f"{label_text}  ({len(node.children)} {T('common.items_suffix')})")
        _draw_field_help_icon(header, entry)
        if node.ui_expand:
            box = layout.box()
            # MdfProperty（TypeMesh 系列 attribute 的 properties 数组元素）子字段用合成类型名
            # "MdfProperty" 查知识表——这批字段在所有引用它的 attribute 类型间物理布局相同，
            # 不按外层 attr_type 区分。见 model.is_mdf_property_node() 的说明。
            child_attr_type = "MdfProperty" if model.is_mdf_property_node(node) else None
            for child in node.children:
                draw_node(box, child, attr_type=child_attr_type, attr_owner=attr_owner)
        return

    row = layout.row(align=True)
    split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
    _draw_label(split, label_text)
    value_row = split.row(align=True)
    _draw_scalar_prop(value_row, node)
    _draw_hash_name(value_row, node)
    _draw_field_help_icon(row, entry)


def _draw_bitfield_row(layout, node, label_text, entry, segs, attr_owner) -> None:
    """位域字段：标签 + 一个显示解码摘要的按钮。点开是 bitfield 弹窗。"""
    row = layout.row(align=True)
    split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
    _draw_label(split, label_text)
    value_row = split.row(align=True)
    packed = bitfield.read_packed(node)
    if packed is None or attr_owner is None:
        # 拿不到值或不知道字段挂在哪个 attribute 上（比如 Root 的 FieldParameter 树），
        # 退回普通数字框，总比画不出来强。
        _draw_scalar_prop(value_row, node)
        _draw_field_help_icon(row, entry)
        return
    op = value_row.operator("efx_re.edit_bitfield",
                      text=bitfield.summary(packed, segs), icon="OPTIONS", translate=False)
    op.node_path = bitfield.node_path(attr_owner.efx_fields, node)
    op.spec_json = json.dumps(segs, ensure_ascii=False)
    op.current_value = packed
    op.field_label = label_text
    _draw_field_help_icon(row, entry)


def _draw_single_enum_row(layout, node, label_text, entry, seg) -> None:
    """单段位域（本质就是一个枚举）：标签 + 内联下拉，不弹窗——见 draw_node() 里的说明。"""
    row = layout.row(align=True)
    split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
    _draw_label(split, label_text)
    model.set_inline_enum_items(node, seg.get("items", []))
    split.prop(node, "enum_proxy", text="")
    _draw_field_help_icon(row, entry)


def _hash_name(node) -> str | None:
    """整数节点的值如果是某个已知名字的 MurMur3(UTF-8) 哈希，返回那个名字。

    RE Engine 用这种哈希代替字符串存材质属性名 / 贴图槽名 / Expression 参数名，落到 JSON 里
    就是一串裸数字（`3292093210`），面板上光看数字完全没法和 mdf 编辑器里的东西对上。
    """
    if node.data_type == "BIGINT":
        raw = node.uint_str
    elif node.data_type == "INT":
        raw = node.int_value
    else:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        value += 1 << 32  # 万一哪天有 uint32 被当成有符号读进来，按无符号还原
    return semantics.lookup_name_hash(value)


def _draw_hash_name(row, node) -> None:
    """能解出名字就在数值右边补一段灰字。灰字（enabled=False）而不是可编辑控件：这是从数值
    反查出来的展示信息，不是另一个可编辑字段，改名字得改数值本身。"""
    name = _hash_name(node)
    if not name:
        return
    sub = row.row()
    sub.alignment = "RIGHT"
    sub.enabled = False
    sub.label(text=name, translate=False)


# ─────────────────────────────────────────────────────────────────────────────
# UIList + 列表条目增删算子
# ─────────────────────────────────────────────────────────────────────────────

class EFX_RE_UL_groups(UIList):
    bl_idname = "EFX_RE_UL_groups"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # 图标名是 BOOKMARKS（复数），没有单数的 BOOKMARK——写错了要到这个列表**真的有条目**
        # 需要画的时候才会炸，见 tools/verify_ui.py 的说明。
        layout.prop(item, "name", text="", emboss=False, icon="BOOKMARKS")


class EFX_RE_OT_group_add(bpy.types.Operator):
    bl_idname = "efx_re.group_add"
    bl_label = "Add Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") == model.TYPE_ENTRY

    def execute(self, context):
        obj = getattr(context, "object", None)
        item = obj.efx_groups.add()
        item.name = "Group"
        obj.efx_groups_active_index = len(obj.efx_groups) - 1
        return {"FINISHED"}


class EFX_RE_OT_group_remove(bpy.types.Operator):
    bl_idname = "efx_re.group_remove"
    bl_label = "Remove Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") == model.TYPE_ENTRY and len(obj.efx_groups) > 0

    def execute(self, context):
        obj = getattr(context, "object", None)
        obj.efx_groups.remove(obj.efx_groups_active_index)
        obj.efx_groups_active_index = min(obj.efx_groups_active_index, len(obj.efx_groups) - 1)
        return {"FINISHED"}


class EFX_RE_UL_bones(UIList):
    bl_idname = "EFX_RE_UL_bones"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=str(index), translate=False)
        row.prop(item, "name", text="", emboss=False, icon="BONE_DATA")


class EFX_RE_OT_bone_add(bpy.types.Operator):
    bl_idname = "efx_re.bone_add"
    bl_label = "Add Bone"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_root(context) is not None

    def execute(self, context):
        obj = _active_root(context)
        item = obj.efx_bones.add()
        item.name = "Bone"
        obj.efx_bones_active_index = len(obj.efx_bones) - 1
        return {"FINISHED"}


class EFX_RE_OT_bone_remove(bpy.types.Operator):
    bl_idname = "efx_re.bone_remove"
    bl_label = "Remove Bone"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _active_root(context)
        return root is not None and len(root.efx_bones) > 0

    def execute(self, context):
        obj = _active_root(context)
        obj.efx_bones.remove(obj.efx_bones_active_index)
        obj.efx_bones_active_index = min(obj.efx_bones_active_index, len(obj.efx_bones) - 1)
        return {"FINISHED"}


class EFX_RE_UL_field_parameters(UIList):
    bl_idname = "EFX_RE_UL_field_parameters"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "name", text="", emboss=False, icon="FORCE_FORCE")


class EFX_RE_OT_field_parameter_add(bpy.types.Operator):
    bl_idname = "efx_re.field_parameter_add"
    bl_label = "Add Field Parameter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_root(context) is not None

    def execute(self, context):
        obj = _active_root(context)
        item = obj.efx_field_parameters.add()
        item.name = "FieldParameter"
        obj.efx_field_parameters_active_index = len(obj.efx_field_parameters) - 1
        return {"FINISHED"}


class EFX_RE_OT_field_parameter_remove(bpy.types.Operator):
    bl_idname = "efx_re.field_parameter_remove"
    bl_label = "Remove Field Parameter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _active_root(context)
        return root is not None and len(root.efx_field_parameters) > 0

    def execute(self, context):
        obj = _active_root(context)
        obj.efx_field_parameters.remove(obj.efx_field_parameters_active_index)
        obj.efx_field_parameters_active_index = min(
            obj.efx_field_parameters_active_index, len(obj.efx_field_parameters) - 1
        )
        return {"FINISHED"}


class EFX_RE_UL_uvar_groups(UIList):
    bl_idname = "EFX_RE_UL_uvar_groups"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"#{index}", translate=False)
        row.label(text=item.path or "(no path)", translate=False)


class EFX_RE_OT_uvar_group_add(bpy.types.Operator):
    bl_idname = "efx_re.uvar_group_add"
    bl_label = "Add Uvar Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_root(context) is not None

    def execute(self, context):
        obj = _active_root(context)
        item = obj.efx_uvar_groups.add()
        # 枚举只有 '1'（标记位）和 '2'（带路径的外部 .uvar 引用），没有 '0'——写 "0" 会
        # TypeError。这里不显式赋值，直接沿用 PropertyGroup 声明的 default="2"
        # （见 model.EFXUvarGroupItem），新建一条默认就是"要填路径"的那种，也是常见的那种。
        obj.efx_uvar_groups_active_index = len(obj.efx_uvar_groups) - 1
        return {"FINISHED"}


class EFX_RE_OT_uvar_group_remove(bpy.types.Operator):
    bl_idname = "efx_re.uvar_group_remove"
    bl_label = "Remove Uvar Group"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _active_root(context)
        return root is not None and len(root.efx_uvar_groups) > 0

    def execute(self, context):
        obj = _active_root(context)
        obj.efx_uvar_groups.remove(obj.efx_uvar_groups_active_index)
        obj.efx_uvar_groups_active_index = min(
            obj.efx_uvar_groups_active_index, len(obj.efx_uvar_groups) - 1
        )
        return {"FINISHED"}


class EFX_RE_UL_expression_parameters(UIList):
    bl_idname = "EFX_RE_UL_expression_parameters"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="DRIVER")
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.label(text=item.param_type, translate=False)


class EFX_RE_OT_expression_parameter_add(bpy.types.Operator):
    bl_idname = "efx_re.expression_parameter_add"
    bl_label = "Add Expression Parameter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_root(context) is not None

    def execute(self, context):
        obj = _active_root(context)
        item = obj.efx_expression_parameters.add()
        item.name = "Parameter"
        obj.efx_expression_parameters_active_index = len(obj.efx_expression_parameters) - 1
        return {"FINISHED"}


class EFX_RE_OT_expression_parameter_remove(bpy.types.Operator):
    bl_idname = "efx_re.expression_parameter_remove"
    bl_label = "Remove Expression Parameter"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _active_root(context)
        return root is not None and len(root.efx_expression_parameters) > 0

    def execute(self, context):
        obj = _active_root(context)
        obj.efx_expression_parameters.remove(obj.efx_expression_parameters_active_index)
        obj.efx_expression_parameters_active_index = min(
            obj.efx_expression_parameters_active_index, len(obj.efx_expression_parameters) - 1
        )
        return {"FINISHED"}


class EFX_RE_UL_clip_curves(UIList):
    bl_idname = "EFX_RE_UL_clip_curves"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"bit {item.bit_index}", translate=False)
        row.label(text=item.bit_name or "-", translate=False)
        sub = row.row()
        sub.alignment = "RIGHT"
        sub.label(text=f"{len(item.keyframes)} kf", translate=False)


class EFX_RE_OT_clip_curve_add(bpy.types.Operator):
    bl_idname = "efx_re.clip_curve_add"
    bl_label = "Add Clip Curve"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE and obj.efx_is_clip_attribute

    def execute(self, context):
        obj = getattr(context, "object", None)
        used = {c.bit_index for c in obj.efx_clip_curves}
        free = next((i for i in range(obj.efx_clip_bit_count) if i not in used), 0)
        curve = obj.efx_clip_curves.add()
        curve.bit_index = free
        obj.efx_clip_curves_active_index = len(obj.efx_clip_curves) - 1
        return {"FINISHED"}


class EFX_RE_OT_clip_curve_remove(bpy.types.Operator):
    bl_idname = "efx_re.clip_curve_remove"
    bl_label = "Remove Clip Curve"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return (
            obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE
            and len(obj.efx_clip_curves) > 0
        )

    def execute(self, context):
        obj = getattr(context, "object", None)
        obj.efx_clip_curves.remove(obj.efx_clip_curves_active_index)
        obj.efx_clip_curves_active_index = min(
            obj.efx_clip_curves_active_index, len(obj.efx_clip_curves) - 1
        )
        return {"FINISHED"}


class EFX_RE_UL_clip_keyframes(UIList):
    bl_idname = "EFX_RE_UL_clip_keyframes"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"f{item.frame_time:g}", translate=False)
        row.label(text=f"{item.value:g}", translate=False)


def _active_clip_curve(obj):
    index = obj.efx_clip_curves_active_index
    if 0 <= index < len(obj.efx_clip_curves):
        return obj.efx_clip_curves[index]
    return None


class EFX_RE_OT_clip_keyframe_add(bpy.types.Operator):
    bl_idname = "efx_re.clip_keyframe_add"
    bl_label = "Add Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE and _active_clip_curve(obj) is not None

    def execute(self, context):
        curve = _active_clip_curve(context.object)
        kf = curve.keyframes.add()
        kf.frame_time = max((k.frame_time for k in curve.keyframes), default=0.0) + 1.0
        curve.keyframes_active_index = len(curve.keyframes) - 1
        return {"FINISHED"}


class EFX_RE_OT_clip_keyframe_remove(bpy.types.Operator):
    bl_idname = "efx_re.clip_keyframe_remove"
    bl_label = "Remove Keyframe"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        if obj is None or obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            return False
        curve = _active_clip_curve(obj)
        return curve is not None and len(curve.keyframes) > 0

    def execute(self, context):
        curve = _active_clip_curve(context.object)
        curve.keyframes.remove(curve.keyframes_active_index)
        curve.keyframes_active_index = min(curve.keyframes_active_index, len(curve.keyframes) - 1)
        return {"FINISHED"}


class EFX_RE_UL_expression_curves(UIList):
    bl_idname = "EFX_RE_UL_expression_curves"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"bit {item.bit_index}", translate=False)
        row.label(text=item.bit_name or item.formula or "-", translate=False)
        if item.formula_error:
            row.label(text="", icon="ERROR")


class EFX_RE_OT_expression_curve_add(bpy.types.Operator):
    bl_idname = "efx_re.expression_curve_add"
    bl_label = "Add Expression"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return (
            obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE
            and obj.efx_is_expression_attribute
        )

    def execute(self, context):
        obj = getattr(context, "object", None)
        used = {c.bit_index for c in obj.efx_expression_curves}
        free = next((i for i in range(obj.efx_expression_bit_count) if i not in used), 0)
        curve = obj.efx_expression_curves.add()
        curve.bit_index = free
        curve.formula = "0"
        obj.efx_expression_curves_active_index = len(obj.efx_expression_curves) - 1
        return {"FINISHED"}


class EFX_RE_OT_expression_curve_remove(bpy.types.Operator):
    bl_idname = "efx_re.expression_curve_remove"
    bl_label = "Remove Expression"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return (
            obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE
            and len(obj.efx_expression_curves) > 0
        )

    def execute(self, context):
        obj = getattr(context, "object", None)
        obj.efx_expression_curves.remove(obj.efx_expression_curves_active_index)
        obj.efx_expression_curves_active_index = min(
            obj.efx_expression_curves_active_index, len(obj.efx_expression_curves) - 1
        )
        return {"FINISHED"}


def _active_expression_curve(obj):
    index = obj.efx_expression_curves_active_index
    if 0 <= index < len(obj.efx_expression_curves):
        return obj.efx_expression_curves[index]
    return None


class EFX_RE_OT_expression_formula_check(bpy.types.Operator):
    """把当前公式送给 EfxBridge 的 exprcheck 校验一遍语法，把结果写回 formula_error——
    让用户不用跑一次完整导出就知道公式写错没有。"""

    bl_idname = "efx_re.expression_formula_check"
    bl_label = "Validate Formula"
    bl_description = "校验当前公式的语法，不用跑一次完整导出就能知道写错没有"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE and _active_expression_curve(obj) is not None

    def execute(self, context):
        curve = _active_expression_curve(context.object)
        try:
            error = bridge.check_expression(curve.formula)
        except bridge.BridgeError as ex:
            error = str(ex)
        curve.formula_error = error or ""
        if error:
            self.report({"WARNING"}, "公式有问题，详见面板")
        else:
            self.report({"INFO"}, "公式语法正确")
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 内容绘制函数
#
# 每个都接收显式的 obj，**不从 context.active_object 现取**——N 面板和属性编辑器镜像都画
# 活动对象，但显式传参让这些函数将来也能被"逐个画出整棵树"这类场景复用（姊妹项目的 Entry
# Inspector 就是这么用的），而且省得每个函数各写一遍 None 判断。
# ─────────────────────────────────────────────────────────────────────────────

def _active_root(context):
    """这些根级列表算子操作的目标 EFX_ROOT 集合。EFX_ROOT 是集合不是对象，所以不能像
    Entry/Attribute 那样直接用 context.object。"""
    return io_tree.resolve_root(context)


def _draw_uilist_row(layout, list_cls, obj, coll_name, index_name, add_op, remove_op, rows=3):
    """"列表 + 右侧 ADD/REMOVE 竖排按钮"这个组合在本文件里出现七八次，抽出来。
    增删按钮的可用性完全交给算子自己的 poll()（姊妹项目的"poll 自动灰"习惯），这里不重复判断。"""
    row = layout.row()
    row.template_list(list_cls, "", obj, coll_name, obj, index_name, rows=rows)
    col = row.column(align=True)
    col.operator(add_op, icon="ADD", text="")
    col.operator(remove_op, icon="REMOVE", text="")


def _draw_root_content(layout, context, obj) -> None:
    """EFX_ROOT 的文件级数据：骨骼表 / 场参数 / Uvar 组 / Expression 参数。"""
    layout.label(text=T("root.bones"), translate=False)
    _draw_uilist_row(
        layout, "EFX_RE_UL_bones", obj, "efx_bones", "efx_bones_active_index",
        "efx_re.bone_add", "efx_re.bone_remove",
    )

    layout.label(text=T("root.field_parameters"), translate=False)
    _draw_uilist_row(
        layout, "EFX_RE_UL_field_parameters", obj, "efx_field_parameters",
        "efx_field_parameters_active_index",
        "efx_re.field_parameter_add", "efx_re.field_parameter_remove",
    )
    active_index = obj.efx_field_parameters_active_index
    if 0 <= active_index < len(obj.efx_field_parameters):
        box = layout.box()
        for node in obj.efx_field_parameters[active_index].fields:
            draw_node(box, node)

    layout.label(text=T("root.uvar_groups"), translate=False)
    _draw_uilist_row(
        layout, "EFX_RE_UL_uvar_groups", obj, "efx_uvar_groups", "efx_uvar_groups_active_index",
        "efx_re.uvar_group_add", "efx_re.uvar_group_remove", rows=2,
    )
    uvar_index = obj.efx_uvar_groups_active_index
    if 0 <= uvar_index < len(obj.efx_uvar_groups):
        uvar_item = obj.efx_uvar_groups[uvar_index]
        box = layout.box()
        box.prop(uvar_item, "uvar_type")
        if uvar_item.uvar_type == "2":
            box.prop(uvar_item, "path")
            box.prop(uvar_item, "group")

    layout.label(text=T("root.expression_parameters"), translate=False)
    _draw_uilist_row(
        layout, "EFX_RE_UL_expression_parameters", obj, "efx_expression_parameters",
        "efx_expression_parameters_active_index",
        "efx_re.expression_parameter_add", "efx_re.expression_parameter_remove",
    )
    expr_index = obj.efx_expression_parameters_active_index
    if 0 <= expr_index < len(obj.efx_expression_parameters):
        expr_item = obj.efx_expression_parameters[expr_index]
        box = layout.box()
        box.prop(expr_item, "name")
        box.prop(expr_item, "param_type")
        if expr_item.param_type == "Color":
            box.prop(expr_item, "color_value", text="Color")
        elif expr_item.param_type == "Range":
            box.prop(expr_item, "value1")
            box.prop(expr_item, "value2")
            box.prop(expr_item, "value3")
        elif expr_item.param_type == "Float2":
            box.prop(expr_item, "value1")
            box.prop(expr_item, "value2")
        else:
            box.prop(expr_item, "value1")


def _draw_name_row(layout, obj) -> None:
    """Entry/Action 的游戏侧名字。**不是 Blender 对象名**——对象名全局唯一、撞名会被加 `.001`，
    而 EFX 里两个 entry 完全可以同名，见 model.py `Object.efx_name` 的说明。"""
    layout.prop(obj, "efx_name", text=T("name.label"))


def _draw_entry_content(layout, context, obj) -> None:
    """EFX_ENTRY 的数据：名称 + Entry Assignment + EffectGroups 标签。"""
    _draw_name_row(layout, obj)
    layout.separator(factor=0.5)
    layout.prop(obj, "efx_entry_assignment")
    layout.label(text=T("entry.effect_groups"), translate=False)
    _draw_uilist_row(
        layout, "EFX_RE_UL_groups", obj, "efx_groups", "efx_groups_active_index",
        "efx_re.group_add", "efx_re.group_remove",
    )
    # entryAssignment == NoAssignment（"2"）时 Groups 标签不生效，是 2026-09-10 才确认的
    # 真实 bug 模式——复制/粘贴出来的 Entry 容易带着这个错误值，Groups 标签看着挂对了但
    # 游戏里不生效，界面上不提示的话完全看不出问题在哪。
    if len(obj.efx_groups) > 0 and obj.efx_entry_assignment == "2":
        warn = layout.row()
        warn.alert = True
        warn.label(text=T("entry.no_assignment_warning"), icon="ERROR", translate=False)


def _attr_type_label(attr_type: str) -> str:
    """attribute 类型显示成什么。中文界面下，知识表里有中文名就画成 `发射器形状 (EmitterShape3D)`
    ——括号里的英文短名不能省，它是这个类型在 RE-Engine-Lib / 010 模板 / 社区讨论里的检索词。
    英文界面或查不到中文名时就只有短名本身。"""
    short = io_tree.short_attr_name(attr_type)
    if i18n.get_lang() != "ZH":
        return short
    entry = semantics.get_type_entry(attr_type)
    label = (entry or {}).get("label_zh")
    return f"{label} ({short})" if label else short


def _draw_action_content(layout, context, obj) -> None:
    """EFX_ACTION 的数据：目前只有名称（其余字段还在 opaque 里）。"""
    _draw_name_row(layout, obj)


def _draw_attribute_content(layout, context, obj) -> None:
    """EFX_ATTRIBUTE 的元信息（只读）。Clip/Expression/字段各自是独立子面板。"""
    box = layout.box()
    box.label(
        text=f"{T('attribute.type')}: {_attr_type_label(obj.efx_attr_type)}",
        translate=False,
    )
    row = box.row(align=True)
    row.label(text=f"UniqueID {obj.efx_unique_id}", translate=False)
    row.label(text=f"Version {obj.efx_version}", translate=False)
    row = box.row(align=True)
    row.label(text=f"type id {obj.efx_type_id}", translate=False)
    row.label(text=f"IsTypeAttribute {obj.efx_is_type_attribute}", translate=False)


def _draw_clip_content(layout, context, obj) -> None:
    """EFX_ATTRIBUTE 的 Clip 动画曲线（IClipAttribute 才有）。"""
    layout.label(
        text=f"{T('attribute.bit_count')}: {obj.efx_clip_bit_count}", translate=False,
    )
    layout.prop(obj, "efx_clip_loop_type", text=T("attribute.loop_type"))
    _draw_uilist_row(
        layout, "EFX_RE_UL_clip_curves", obj, "efx_clip_curves", "efx_clip_curves_active_index",
        "efx_re.clip_curve_add", "efx_re.clip_curve_remove",
    )

    curve = _active_clip_curve(obj)
    if curve is None:
        return
    box = layout.box()
    box.prop(curve, "bit_index")
    box.label(text=T("attribute.keyframes"), translate=False)
    _draw_uilist_row(
        box, "EFX_RE_UL_clip_keyframes", curve, "keyframes", "keyframes_active_index",
        "efx_re.clip_keyframe_add", "efx_re.clip_keyframe_remove",
    )

    kf_index = curve.keyframes_active_index
    if not (0 <= kf_index < len(curve.keyframes)):
        return
    kf = curve.keyframes[kf_index]
    kf_box = box.box()
    kf_box.prop(kf, "frame_time")
    kf_box.prop(kf, "interp_type")
    kf_box.prop(kf, "value")
    if kf.interp_type == "5":  # Bezier
        row = kf_box.row(align=True)
        row.prop(kf, "tangent_out_x")
        row.prop(kf, "tangent_out_y")
        row = kf_box.row(align=True)
        row.prop(kf, "tangent_in_x")
        row.prop(kf, "tangent_in_y")


def _draw_expression_content(layout, context, obj) -> None:
    """EFX_ATTRIBUTE 的 Expression 公式（IExpressionAttribute 才有）。"""
    layout.label(
        text=f"{T('attribute.bit_count')}: {obj.efx_expression_bit_count}", translate=False,
    )
    _draw_uilist_row(
        layout, "EFX_RE_UL_expression_curves", obj, "efx_expression_curves",
        "efx_expression_curves_active_index",
        "efx_re.expression_curve_add", "efx_re.expression_curve_remove",
    )

    curve = _active_expression_curve(obj)
    if curve is None:
        return
    box = layout.box()
    box.prop(curve, "bit_index")
    row = box.row(align=True)
    row.prop(curve, "formula", text="")
    row.operator("efx_re.expression_formula_check", icon="CHECKMARK", text="")
    if curve.formula_error:
        box.label(text=curve.formula_error, icon="ERROR", translate=False)


# ─────────────────────────────────────────────────────────────────────────────
# 虚拟轴向分组：部分 attribute 类型把同一个概念的 X/Y/(Z) 分量存成独立的 via.Range 字段
# （不是真正的 Vector3 复合类型），逐个画成整行的话，"X 轴旋转"/"Y 轴旋转"/"Z 轴旋转"
# 三行各自重复一遍完整的 Static/Random 表头，认知负担大。这里在展示层把它们重新拼成跟
# 真正 XYZ 复合字段（draw_node 里的 xyz_order 分支）一致的"标题行 + 逐轴行"——纯展示层
# 分组，不改字段树结构，导出仍按各自原字段写出。对齐姊妹项目 EFX-Editor 的 AXIS_GROUPS
# （blender_efx/layout_model.py）。
#
# type_name -> [ (label_zh, label_en, [(axis_label, base_field_name), ...]), ... ]
_AXIS_GROUPS: dict = {
    "ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape3D": [
        ("范围", "Range", [("X", "RangeX"), ("Y", "RangeY"), ("Z", "RangeZ")]),
    ],
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshV2": [
        ("旋转", "Rotation", [("X", "RotationX"), ("Y", "RotationY"), ("Z", "RotationZ")]),
        ("缩放", "Scale", [("X", "ScaleX"), ("Y", "ScaleY"), ("Z", "ScaleZ")]),
    ],
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3D": [
        ("大小", "Size", [("X", "SizeX"), ("Y", "SizeY")]),
    ],
    "ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity3D": [
        ("运动方向", "Direction", [("X", "DirectionVectorX"), ("Y", "DirectionVectorY"), ("Z", "DirectionVectorZ")]),
    ],
    "ReeLib.Efx.Structs.Transforms.EFXAttributeRotateAnim": [
        ("旋转速度", "Rotation Speed", [("X", "RotationAddX"), ("Y", "RotationAddY"), ("Z", "RotationAddZ")]),
        ("旋转加速度", "Rotation Accel", [("X", "RotationCoefX"), ("Y", "RotationCoefY"), ("Z", "RotationCoefZ")]),
    ],
    "ReeLib.Efx.Structs.Transforms.EFXAttributeScaleAnim": [
        ("缩放变化速率", "Size Change Rate", [("X", "SizeXAdd"), ("Y", "SizeYAdd"), ("Z", "SizeZAdd")]),
        ("缩放变化加速度", "Size Change Accel", [("X", "SizeXAddCoef"), ("Y", "SizeYAddCoef"), ("Z", "SizeZAddCoef")]),
    ],
}


def _resolve_axis_groups(attr_type: str | None, node_by_key: dict):
    """把 `_AXIS_GROUPS` 里该类型的分组规格解析成可绘制的形式；缺字段（版本裁剪掉的变体
    没有全部轴）的分组整体跳过，退回逐字段正常显示。返回 (组首字段名 -> 分组规格 字典，
    被该分组消费掉的全部字段名 set)。"""
    group_at: dict = {}
    consumed: set = set()
    if not attr_type:
        return group_at, consumed
    for label_zh, label_en, axes in _AXIS_GROUPS.get(attr_type, []):
        names = [base for _axis, base in axes]
        if not all(n in node_by_key for n in names):
            continue
        group_at[names[0]] = (label_zh, label_en, axes)
        consumed.update(names)
    return group_at, consumed


def _draw_axis_group(layout, attr_type: str, label_zh: str, label_en: str, axes, node_by_key: dict) -> None:
    """绘制一个虚拟轴向分组：标题行 + 逐轴行。每根轴按字段实际形状画（目前全部是
    via.Range，Static/Random 并排；留了标量分支给以后可能出现的非 Range 轴字段）。"""
    title = label_en if i18n.get_lang() == "EN" else label_zh
    layout.row(align=True).label(text=title, icon="ORIENTATION_GLOBAL", translate=False)
    for axis_label, base in axes:
        node = node_by_key[base]
        entry = semantics.get_field_entry(attr_type, base)
        row = layout.row(align=True)
        split = row.split(factor=_FIELD_SPLIT_FACTOR, align=True)
        _draw_label(split, axis_label)
        cols = split.row(align=True)
        if model.is_static_random_node(node):
            by_key = {c.key: c for c in node.children}
            _draw_scalar_prop(cols, by_key["s"], text="Static")
            _draw_scalar_prop(cols, by_key["r"], text="Random")
        else:
            _draw_scalar_prop(cols, node, text="")
        _draw_field_help_icon(row, entry)


def _draw_fields_content(layout, context, obj) -> None:
    """EFX_ATTRIBUTE 的内容字段树。包在 box + column(align=True) 里（姊妹项目的字段区风格），
    比上一版直接往面板根上平铺更容易看出"这一坨是一个整体"。"""
    if len(obj.efx_fields) == 0:
        layout.label(text=T("attribute.no_fields"), icon="INFO", translate=False)
        return
    root_obj = io_tree.find_root(obj)
    box = layout.box()
    col = box.column(align=True)
    node_by_key = {n.key: n for n in obj.efx_fields}
    group_at, consumed = _resolve_axis_groups(obj.efx_attr_type, node_by_key)
    for node in obj.efx_fields:
        if node.key in group_at:
            label_zh, label_en, axes = group_at[node.key]
            _draw_axis_group(col, obj.efx_attr_type, label_zh, label_en, axes, node_by_key)
            continue
        if node.key in consumed:
            continue
        draw_node(col, node, attr_type=obj.efx_attr_type, root_obj=root_obj, attr_owner=obj)


# ─────────────────────────────────────────────────────────────────────────────
# 面板
# ─────────────────────────────────────────────────────────────────────────────

_CATEGORY = "Wilds EFX"
# 能被 Edit 面板操作的对象类型。**不含 EFX_ROOT**——它是集合不是对象（见 io_tree 头部说明），
# 整个文件的删除走 Outliner 的 Delete Hierarchy。
_EFX_TYPES = (model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE)


class EFX_RE_PT_main(Panel):
    """工具面板：语言、导入导出、当前 EFX、刷新摆位、校验。"""

    bl_idname = "EFX_RE_PT_main"
    bl_label = "MHWs EFX"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = -4  # 固定顺序：MHWs EFX > 各 ~TYPE 数据面板 > Edit

    def draw(self, context):
        layout = self.layout

        i18n.draw_language_toggle(layout)
        layout.separator(factor=0.5)

        row = layout.row(align=True)
        row.operator("efx_re.import", text=T("main.import"), icon="IMPORT", translate=False)
        row.operator("efx_re.export", text=T("main.export"), icon="EXPORT", translate=False)

        layout.prop(context.scene, "efx_re_active_root", text=T("main.active_efx"))

        row = layout.row(align=True)
        row.operator(
            "efx_re.sync_transform3d_to_view", text=T("main.sync_transform"),
            icon="ORIENTATION_GLOBAL", translate=False,
        )
        row.operator("efx_re.validate", text=T("main.validate"), icon="CHECKMARK", translate=False)

        layout.prop(context.scene, "efx_re_angle_degrees", text=T("main.angle_degrees"))


class EFX_RE_PT_edit(Panel):
    """工具面板：复制/粘贴。按活动对象的 ~TYPE 给出对应按钮，可用性交给算子 poll 自动灰。

    放 N 面板而不是属性编辑器，是因为这些是"对对象做的操作"而不是"对象自身的数据"
    （姊妹项目 CLAUDE.md §4 的分工判据）。"""

    bl_idname = "EFX_RE_PT_edit"
    bl_label = "Copy & Paste"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = -1
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") in _EFX_TYPES

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.operator("efx_re.object_copy", text=T("edit.copy_object"), icon="COPYDOWN", translate=False)
        row.operator("efx_re.object_paste", text=T("edit.paste_object"), icon="PASTEDOWN", translate=False)
        hint = layout.row()
        hint.enabled = False
        clip_label = copy_paste.describe_object_clipboard()
        hint.label(
            text=T("edit.clipboard_prefix") + (clip_label or T("edit.clipboard_empty")),
            translate=False,
        )

        layout.separator()

        row = layout.row(align=True)
        row.operator("efx_re.properties_copy", text=T("edit.copy_properties"), icon="COPYDOWN", translate=False)
        row.operator("efx_re.properties_paste", text=T("edit.paste_properties"), icon="PASTEDOWN", translate=False)
        hint = layout.row()
        hint.enabled = False
        clip_label = copy_paste.describe_properties_clipboard()
        hint.label(
            text=T("edit.clipboard_prefix") + (clip_label or T("edit.clipboard_empty")),
            translate=False,
        )

        # efx_re.delete 暂时隐藏：原生 Blender 删除（X / Delete 键）已经能覆盖这个场景，
        # 保留算子本体（structure_ops.py）不动，只是不在这里画出来。


def _draw_add_entry_tab(layout, context) -> None:
    """Entry 标签页：只有预设系统——原来的"空白 Entry"按钮已经内置成一个不可删除的预设
    （entry_presets.BUILTIN_NAME），跟用户自己攒的预设混在同一个下拉框里，对齐姊妹项目
    EFX-Editor 的 Entry 预设面板布局（`__archetypes__/` 内置预设 + 用户预设合并一个下拉，
    下拉框 + 独立 Add 按钮的两步流程，不是点了就立刻建）。"""
    wm = context.window_manager

    row = layout.row(align=True)
    row.prop(wm, "efx_re_entry_preset", text="")
    row.operator("efx_re.entry_preset_delete", text="", icon="REMOVE")
    layout.operator("efx_re.entry_preset_new", text=T("add.entry_from_preset"), icon="ADD", translate=False)

    layout.separator(factor=0.5)

    obj = context.object
    save_target = obj if obj is not None and obj.get("~TYPE") == model.TYPE_ENTRY else None
    hint = layout.row()
    hint.enabled = False
    if save_target is None:
        hint.label(text=T("add.save_preset_no_target"), icon="INFO", translate=False)
    else:
        hint.label(
            text=T("add.save_preset_prefix") + (save_target.efx_name or save_target.name),
            icon="FILE_TICK", translate=False,
        )
    layout.operator("efx_re.entry_preset_save", text=T("add.save_entry_preset"), icon="FILE_TICK", translate=False)


def _draw_add_action_tab(layout, context) -> None:
    """Action 标签页：目前只有一种新建方式，没有预设系统这一说，就一个按钮。"""
    layout.operator("efx_re.action_add", text=T("add.action"), icon="PLAY", translate=False)


def _draw_add_attribute_tab(layout, context) -> None:
    """Attribute 标签页：分类下拉 + 点了就立刻新增的类型菜单，不再需要单独的"确认新增"按钮
    ——对齐姊妹项目 EFX-Editor 的 attribute 选择器交互（`EFX_MT_attribute_preset_picker`：
    点预设行直接新增）。这里能这样简化，是因为同一个 Entry 一般不会连续加好几个同类型
    attribute、也不会来回给几个不同 Entry 反复加同一个类型——"选中类型再点确认"这个中间态
    在实际操作习惯里就是多余的一次点击。"""
    target = structure_ops._resolve_attribute_parent(context)
    row = layout.row()
    if target is None:
        row.enabled = False
        row.label(text=T("add.target_prefix") + T("add.no_target"), icon="INFO", translate=False)
    else:
        row.label(text=T("add.target_prefix") + target.name, icon="PLUS", translate=False)

    wm = context.window_manager
    layout.prop(wm, "efx_re_attr_category", text=T("add.category"))
    layout.menu("EFX_RE_MT_attribute_type_picker", text=T("add.attribute"), icon="ADD")

    sub = layout.row()
    sub.enabled = False
    sub.label(text=T("add.order_hint"), translate=False)


class EFX_RE_MT_attribute_type_picker(Menu):
    """点一行直接新增对应类型的 attribute，不经过"先选中、再点 Add 确认"的中间态——
    `attribute_types.readable_types()` 按当前分类过滤，跟原来给 `efx_re_attr_type` 下拉喂
    条目的是同一份数据源，只是这里换成点击即触发。"""

    bl_idname = "EFX_RE_MT_attribute_type_picker"
    bl_label = "Attribute Type"

    def draw(self, context):
        layout = self.layout
        category = getattr(context.window_manager, "efx_re_attr_category", "ALL")
        items = attribute_types.readable_types(category)
        if not items:
            layout.label(text=T("add.no_types_in_category"), translate=False)
            return
        for item in items:
            label = _attr_type_label(item["type"]) if item.get("type") else item["name"]
            op = layout.operator("efx_re.attribute_add", text=label, translate=False)
            op.attr_type = item["name"]


class EFX_RE_PT_add(Panel):
    """工具面板：新增 Entry / Action / Attribute，用一个类似语言切换的三段式标签页
    （`efx_re_add_tab`）在同一个面板里切换，而不是三个各自可折叠的子面板——三者是互斥的
    "我现在想加哪一种东西"，同时只会看其中一种，标签页比"同时摆着、各自折叠"更贴近这个
    互斥关系，也少一层嵌套折叠。
    """

    bl_idname = "EFX_RE_PT_add"
    bl_label = "Add"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = -2
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.prop(wm, "efx_re_add_tab", expand=True)
        layout.separator()

        tab = wm.efx_re_add_tab
        if tab == "ENTRY":
            _draw_add_entry_tab(layout, context)
        elif tab == "ACTION":
            _draw_add_action_tab(layout, context)
        else:
            _draw_add_attribute_tab(layout, context)


def _poll_type(type_tag: str):
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") == type_tag
    return classmethod(poll)


@classmethod
def _poll_root(cls, context):
    """EFX File 面板什么时候显示：能解析出一个 EFX_ROOT 集合就显示。

    比其它面板宽松——它们要求"活动对象正好是那个类型"，这里只要求"当前在某个 efx 里"
    （活动对象在树里 / 活动集合是根 / 或者「当前 EFX」选择器指着一个），因为文件级数据
    在编任何一个 entry 的时候都可能要看一眼（比如往骨骼表里补个名字）。"""
    return io_tree.resolve_root(context) is not None


@classmethod
def _poll_clip(cls, context):
    obj = getattr(context, "object", None)
    return obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE and obj.efx_is_clip_attribute


@classmethod
def _poll_expression(cls, context):
    obj = getattr(context, "object", None)
    return (
        obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE
        and obj.efx_is_expression_attribute
    )


# 数据面板清单。每一项生成两个 Panel 类：N 面板一份 + 属性编辑器 Object Data 标签一份，
# 两份 draw() 调的是同一个 content 函数。
#
# (key, bl_label, content 函数, poll, 父面板 key 或 None, bl_order, 默认折叠, target)
#
# target 决定 draw 时把什么喂给 content 函数、以及属性编辑器镜像挂在哪个标签页：
#   "object"     -> context.object，属性编辑器 Object Data 标签（bl_context="data"）
#   "collection" -> 当前 EFX_ROOT 集合，属性编辑器 Collection 标签（bl_context="collection"）
# EFX_ROOT 是集合不是对象，所以它这一行是 "collection"。
# Entry/Attribute 的 bl_order 是 1（EFX_RE_PT_add=-2、EFX_RE_PT_edit=-1 之后）——这两个是内容
# 最重的数据面板，排到 Add / Copy & Paste 这两个工具面板下面：construction 顺序是先用工具面板
# "造"出东西，再往下滚看/改造出来那个对象的实际内容，这个先后关系值得让面板顺序体现出来。
# Root/Action 内容单薄（Root 是文件级参数表，Action 目前只有个名字），留在原来靠前的位置。
_DATA_PANELS = (
    ("root",       "EFX File",   _draw_root_content,       _poll_root,                       None,        -3, False, "collection"),
    ("entry",      "Entry",      _draw_entry_content,      _poll_type(model.TYPE_ENTRY),     None,         1, False, "object"),
    ("action",     "Action",     _draw_action_content,     _poll_type(model.TYPE_ACTION),    None,        -3, False, "object"),
    ("attribute",  "Attribute",  _draw_attribute_content,  _poll_type(model.TYPE_ATTRIBUTE), None,         2, False, "object"),
    # Clip / Expression 默认折叠：只有一部分 attribute 类型有，而且属于"要动动画曲线时才展开"
    # 的深水区；字段树是选中一个 attribute 后最常看的东西，默认展开。
    ("clip",       "Clip",       _draw_clip_content,       _poll_clip,                       "attribute",  0, True,  "object"),
    ("expression", "Expression", _draw_expression_content, _poll_expression,                 "attribute",  0, True,  "object"),
    ("fields",     "Fields",     _draw_fields_content,     _poll_type(model.TYPE_ATTRIBUTE), "attribute",  0, False, "object"),
)


def _make_panel(key: str, label: str, content_fn, poll, parent_key, order, closed, target: str, space: str):
    """按 space（"VIEW_3D" / "PROPERTIES"）造一个数据面板类。

    用工厂而不是手写两遍：这两份除了 bl_space_type/bl_region_type/bl_category/bl_context 之外
    完全一样，手写的话每加一个面板就要复制粘贴一次，迟早漏改一边。
    """
    if space == "VIEW_3D":
        suffix = ""
        extra = {
            "bl_space_type": "VIEW_3D",
            "bl_region_type": "UI",
            "bl_category": _CATEGORY,
            "bl_label": label,
        }
    else:
        suffix = "_props"
        # 属性编辑器里我们的面板和 Blender 自己的挤在一起，标题得自带 "EFX" 才认得出是谁的；
        # 本身已经以 EFX 开头的（"EFX File"）不再重复加前缀。
        # 根面板挂 Collection 标签（EFX_ROOT 是集合），其余挂 Empty 的 Object Data 标签。
        extra = {
            "bl_space_type": "PROPERTIES",
            "bl_region_type": "WINDOW",
            "bl_context": "collection" if target == "collection" else "data",
            "bl_label": label if label.startswith("EFX") else f"EFX {label}",
        }

    idname = f"EFX_RE_PT_{key}{suffix}"
    namespace = {
        "__doc__": f"{label}（{'N 面板' if space == 'VIEW_3D' else '属性编辑器 Object Data'}）",
        "bl_idname": idname,
        "bl_order": order,
        "poll": poll,
        "draw": (
            (lambda self, context: content_fn(self.layout, context, io_tree.resolve_root(context)))
            if target == "collection"
            else (lambda self, context: content_fn(self.layout, context, context.object))
        ),
        **extra,
    }
    if parent_key is not None:
        namespace["bl_parent_id"] = f"EFX_RE_PT_{parent_key}{suffix}"
    if closed:
        namespace["bl_options"] = {"DEFAULT_CLOSED"}
    return type(idname, (Panel,), namespace)


_GENERATED_PANELS = tuple(
    _make_panel(key, label, fn, poll, parent, order, closed, target, space)
    for space in ("VIEW_3D", "PROPERTIES")
    for key, label, fn, poll, parent, order, closed, target in _DATA_PANELS
)


_CLASSES = (
    EFX_RE_UL_groups,
    EFX_RE_UL_bones,
    EFX_RE_UL_field_parameters,
    EFX_RE_UL_uvar_groups,
    EFX_RE_UL_expression_parameters,
    EFX_RE_UL_clip_curves,
    EFX_RE_UL_clip_keyframes,
    EFX_RE_UL_expression_curves,
    EFX_RE_OT_field_info,
    EFX_RE_OT_group_add,
    EFX_RE_OT_group_remove,
    EFX_RE_OT_bone_add,
    EFX_RE_OT_bone_remove,
    EFX_RE_OT_field_parameter_add,
    EFX_RE_OT_field_parameter_remove,
    EFX_RE_OT_uvar_group_add,
    EFX_RE_OT_uvar_group_remove,
    EFX_RE_OT_expression_parameter_add,
    EFX_RE_OT_expression_parameter_remove,
    EFX_RE_OT_clip_curve_add,
    EFX_RE_OT_clip_curve_remove,
    EFX_RE_OT_clip_keyframe_add,
    EFX_RE_OT_clip_keyframe_remove,
    EFX_RE_OT_expression_curve_add,
    EFX_RE_OT_expression_curve_remove,
    EFX_RE_OT_expression_formula_check,
    EFX_RE_PT_main,
    *_GENERATED_PANELS,
    EFX_RE_MT_attribute_type_picker,
    EFX_RE_PT_add,
    EFX_RE_PT_edit,
)


def _active_root_poll(self, col):
    """"当前 EFX"选择器的候选：只列带 EFX_ROOT 标记的集合。"""
    return col.get("~TYPE") == model.TYPE_ROOT


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # 纯 UI 开关：弧度制角度字段（知识表 unit == "angle_radians"）在面板里按度显示/编辑，
    # 不改变 efx_fields 里存储的弧度原值。默认关——对齐姊妹项目 EFX-Editor
    # Scene.efx_blender_coords 同类开关的默认状态（默认显示原始存储值，不做单位转换）。
    bpy.types.Scene.efx_re_angle_degrees = BoolProperty(
        name="Angle fields in degrees",
        description="把已知是弧度制的角度字段（目前只有 Transform3D 的 LocalRotation）"
                    "按度显示/编辑，不影响实际存储的弧度值",
        default=False,
    )
    # "当前 EFX"：活动对象不属于任何 EFX 树时，导出/粘贴退到这里指定的根，见
    # io_tree.resolve_root()。导入时自动指向刚建好的那棵树。
    # "新增 Attribute" 的分类过滤器。放 WindowManager 而不是 Scene：这是纯粹的界面临时状态，
    # 不该被存进 .blend 文件跟着场景走。选中类型不再单独存一份属性——点 EFX_RE_MT_attribute_
    # type_picker 菜单里的一行就直接新增，不经过"先选中、再确认"的中间态，所以不需要
    # efx_re_attr_type 这种"当前选了哪个"的持久状态，也不需要切分类时重置它的 update 回调。
    bpy.types.WindowManager.efx_re_attr_category = EnumProperty(
        name="Category",
        description="按来源文件分组过滤 attribute 类型",
        items=attribute_types.category_items,
    )
    # "新增"面板的三段式标签页（Entry/Action/Attribute），三者互斥、同时只看一种，用 EnumProperty
    # 的 expand=True 画成横排切换按钮（同 i18n.draw_language_toggle() 的视觉效果），不用三个各自
    # 折叠的子面板——那样会多一层嵌套，也不如标签页贴近"互斥选择"这个语义。
    bpy.types.WindowManager.efx_re_add_tab = EnumProperty(
        name="Add",
        description="切换新增面板要看哪一类",
        items=[
            ("ENTRY", "Entry", "从预设新建 Entry，或把当前选中的 Entry 另存为新预设"),
            ("ACTION", "Action", "新增一个空 Action"),
            ("ATTRIBUTE", "Attribute", "给当前 Entry/Action 新增一个指定类型的 Attribute"),
        ],
        default="ENTRY",
    )
    # EFX_ROOT 是集合，所以这里指向 Collection 而不是 Object。
    bpy.types.Scene.efx_re_active_root = PointerProperty(
        type=bpy.types.Collection,
        name="Active EFX",
        description="当前操作的目标 EFX 文件树。活动对象已经在某棵 EFX 树里时优先用那棵，"
                    "这里只在活动对象不属于任何 EFX 树时兜底",
        poll=_active_root_poll,
    )


def unregister():
    for prop in ("efx_re_angle_degrees", "efx_re_active_root"):
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
    for prop in ("efx_re_add_tab", "efx_re_attr_category"):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
