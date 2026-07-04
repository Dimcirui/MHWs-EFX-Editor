"""blender_efx_re/panels.py —— ~TYPE 对象面板：Entry 的 Groups 标签、Attribute 的字段树。"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Panel, UIList

from . import io_tree, model, semantics

# 知识表只在"attribute $type + 顶层内容字段 key"这一级生效（见 semantics.py 说明），confidence
# 不是 "confirmed" 时在标签旁加一个问号图标，提醒这是未经游戏内实测验证的猜测，不是权威结论。
_CONFIDENCE_ICON = {"guess": "QUESTION", "likely": "QUESTION"}


class EFX_OT_field_info(bpy.types.Operator):
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


def _draw_label(layout, text: str, entry: dict | None) -> None:
    """画一个字段的标签：查到知识表条目就用 operator 按钮承载 tooltip，查不到就是普通 label。

    两处都传 translate=False：这里的 text 要么是原始 JSON 键名（如 "Saturation"），要么是
    知识表里已经写好的中文——都不该再被 Blender 自带的界面翻译表拦截替换。默认
    translate=True 时，只要这段文字碰巧和 Blender 内置词条完全相同（"Saturation" 这种常见
    颜色管理术语就撞上了），界面语言选中文时会被静默换成"饱和度"，看起来像是我们知识表标注的
    结果，实际上跟内容语义无关——在 Blender 5.1 中文界面下实测复现过。
    """
    if entry is None:
        layout.label(text=text, translate=False)
        return
    icon = _CONFIDENCE_ICON.get(entry.get("confidence"), "NONE")
    op = layout.operator("efx_re.field_info", text=text, translate=False, emboss=False, icon=icon)
    op.tooltip_text = entry.get("tooltip_zh") or ""


# data_type -> 对应存储标量值的 Object 属性名（NULL 没有对应 slot，单独处理）。
_SCALAR_PROP_ATTR = {
    "FLOAT": "float_value",
    "INT": "int_value",
    "BIGINT": "uint_str",
    "BOOL": "bool_value",
    "STRING": "string_value",
}


def _draw_scalar_prop(layout, node, text: str = "") -> None:
    """画一个标量节点自身的值控件（不画字段名标签）。XYZ/static-random 并排列布局和普通单行
    布局共用这个函数，只是传的 layout/text 不同——单行布局传 text=""（标签已经在旁边画过），
    并排列布局传 text="X"/"Value" 这类，让 Blender 把短标签内联画在数值框左边（对齐姊妹项目
    EFX-Editor `comp_row.prop(item, "int3_value", index=0, text="X")` 的做法）。"""
    attr = _SCALAR_PROP_ATTR.get(node.data_type)
    if attr is None:
        layout.label(text="null", translate=False)
        return
    layout.prop(node, attr, text=text)


def draw_node(layout, node, attr_type: str | None = None, root_obj=None) -> None:
    """递归绘制一个 EFXValueNode：标量画一行 prop()，OBJECT/ARRAY 画一个可折叠 box 递归绘制
    children。ui_expand 只影响面板显示，不参与导出——见 model.py 里 EFXValueNode 的说明。

    attr_type 只在最外层调用（EFX_PT_object.draw()）传入，用来查知识表；递归到子字段时传
    None——Vector 类型的 x/y/z 这类子字段名字本身已经够自解释，知识表不索引这一层。
    root_obj 同理只在最外层传（该 attribute 所属的 EFX_ROOT），供 ParentBone 字段画
    prop_search 时定位 efx_bones 列表；递归到子字段时不需要，因为骨骼引用字段结构上必然只出现
    在 attribute 的顶层内容字段，不会嵌套在子对象里（见 model.is_bone_reference_field()）。
    """
    entry = semantics.get_field_entry(attr_type, node.key) if attr_type else None
    label_text = (entry.get("label_zh") if entry else None) or node.key

    dtype = node.data_type
    if root_obj is not None and model.is_bone_reference_field(node, attr_type):
        # ParentBone：按名字引用 EFX_ROOT.efx_bones 里的条目，不是裸下标（C# 后端自己在
        # 读时把下标解析成名字、写时再反查回下标，见 docs/TOPLEVEL_STRUCTURE.md）。用 Blender
        # 原生 prop_search——和挑选顶点组/骨骼同一个"输入名字、自动补全校验"控件，比裸文本框
        # 更不容易手滑打错字；导出前 io_tree.check_bone_references() 还会再校验一遍防止
        # 引用了列表外的名字（那种情况 C# 后端会静默丢弃绑定，不报错）。
        row = layout.row(align=True)
        _draw_label(row, label_text, entry)
        row.prop_search(node, "string_value", root_obj, "efx_bones", text="", icon="BONE_DATA")
        return

    if dtype == "OBJECT" and model.is_rgba_color_node(node):
        # via.Color 在 JSON 里的真实形状是单键 {"rgba": <打包 uint32>}，不是 [R,G,B,A] 四个
        # 独立字段（C# 端 R/G/B/A 是 [JsonIgnore] 计算属性，不落盘）——见 model.py 的说明。
        # 画成颜色轮而不是"1 items 折叠框 + 一个巨大整数"，get/set 直接读写那个 rgba 子节点。
        row = layout.row(align=True)
        _draw_label(row, label_text, entry)
        row.prop(node, "color_value", text="")
        return

    xyz_order = model.xyz_child_order(node) if dtype == "OBJECT" else None
    if xyz_order is not None:
        # Vector3 类形状画成三列并排（对齐姊妹项目 EFX-Editor 的 XYZ 展示风格），不画成
        # "3 items" 折叠框——X/Y/Z 分量本身已经够自解释，不需要再单独折叠/查知识表。
        row = layout.row(align=True)
        _draw_label(row, label_text, entry)
        by_key = {c.key: c for c in node.children}
        cols = row.row(align=True)
        for key in xyz_order:
            _draw_scalar_prop(cols, by_key[key], text=key)
        return

    if dtype == "OBJECT" and model.is_static_random_node(node):
        # via.Range{s,r} 画成两列并排：Static（对应 s）/ Random（对应 r）。用户明确要求用这组
        # REE 惯例命名而不是 MHWI 社区惯用的 Value/Jitter——这套命名以后计划回哺到 EFX-Editor，
        # 两边统一用 REE 这边的说法（不是反过来）。
        row = layout.row(align=True)
        _draw_label(row, label_text, entry)
        by_key = {c.key: c for c in node.children}
        cols = row.row(align=True)
        _draw_scalar_prop(cols, by_key["s"], text="Static")
        _draw_scalar_prop(cols, by_key["r"], text="Random")
        return

    if dtype == "OBJECT" or dtype == "ARRAY":
        header = layout.row(align=True)
        icon = "TRIA_DOWN" if node.ui_expand else "TRIA_RIGHT"
        header.prop(node, "ui_expand", icon=icon, icon_only=True, emboss=False)
        _draw_label(header, f"{label_text}  ({len(node.children)} items)", entry)
        if node.ui_expand:
            box = layout.box()
            for child in node.children:
                draw_node(box, child)
        return

    row = layout.row(align=True)
    _draw_label(row, label_text, entry)
    _draw_scalar_prop(row, node)


class EFX_UL_groups(UIList):
    bl_idname = "EFX_UL_groups"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "name", text="", emboss=False, icon="BOOKMARK")


class EFX_OT_group_add(bpy.types.Operator):
    bl_idname = "efx_re.group_add"
    bl_label = "Add Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        tag = obj.efx_groups.add()
        tag.name = "Group"
        obj.efx_groups_active_index = len(obj.efx_groups) - 1
        return {"FINISHED"}


class EFX_OT_group_remove(bpy.types.Operator):
    bl_idname = "efx_re.group_remove"
    bl_label = "Remove Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        index = obj.efx_groups_active_index
        if 0 <= index < len(obj.efx_groups):
            obj.efx_groups.remove(index)
            obj.efx_groups_active_index = min(index, len(obj.efx_groups) - 1)
        return {"FINISHED"}


class EFX_UL_bones(UIList):
    bl_idname = "EFX_UL_bones"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="BONE_DATA")
        row.prop(item, "value", text="")


class EFX_OT_bone_add(bpy.types.Operator):
    bl_idname = "efx_re.bone_add"
    bl_label = "Add Bone"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        item = obj.efx_bones.add()
        item.name = "Bone"
        obj.efx_bones_active_index = len(obj.efx_bones) - 1
        return {"FINISHED"}


class EFX_OT_bone_remove(bpy.types.Operator):
    bl_idname = "efx_re.bone_remove"
    bl_label = "Remove Bone"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        index = obj.efx_bones_active_index
        if 0 <= index < len(obj.efx_bones):
            obj.efx_bones.remove(index)
            obj.efx_bones_active_index = min(index, len(obj.efx_bones) - 1)
        return {"FINISHED"}


class EFX_UL_field_parameters(UIList):
    bl_idname = "EFX_UL_field_parameters"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "name", text="", emboss=False, icon="PROPERTIES")


class EFX_OT_field_parameter_add(bpy.types.Operator):
    bl_idname = "efx_re.field_parameter_add"
    bl_label = "Add Field Parameter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        item = obj.efx_field_parameters.add()
        item.name = "FieldParameter"
        model.populate_dict_as_children(item.fields, model.FIELD_PARAMETER_CONTENT_DEFAULTS)
        obj.efx_field_parameters_active_index = len(obj.efx_field_parameters) - 1
        return {"FINISHED"}


class EFX_OT_field_parameter_remove(bpy.types.Operator):
    bl_idname = "efx_re.field_parameter_remove"
    bl_label = "Remove Field Parameter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.object
        index = obj.efx_field_parameters_active_index
        if 0 <= index < len(obj.efx_field_parameters):
            obj.efx_field_parameters.remove(index)
            obj.efx_field_parameters_active_index = min(index, len(obj.efx_field_parameters) - 1)
        return {"FINISHED"}


class EFX_PT_main(Panel):
    bl_idname = "EFX_PT_main"
    bl_label = "MHWs EFX"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wilds EFX"

    def draw(self, context):
        layout = self.layout
        layout.operator("efx_re.import", icon="IMPORT")
        layout.operator("efx_re.export", icon="EXPORT")


class EFX_PT_object(Panel):
    bl_idname = "EFX_PT_object"
    bl_label = "EFX Object"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wilds EFX"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("~TYPE") in (
            model.TYPE_ROOT, model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE,
        )

    def draw(self, context):
        obj = context.object
        layout = self.layout
        type_tag = obj.get("~TYPE")
        layout.label(text=f"{type_tag}: {obj.name}", translate=False)

        if type_tag == model.TYPE_ROOT:
            layout.operator("efx_re.entry_paste", icon="PASTEDOWN")

            layout.label(text="Bones:")
            row = layout.row()
            row.template_list(
                "EFX_UL_bones", "", obj, "efx_bones", obj, "efx_bones_active_index", rows=3,
            )
            col = row.column(align=True)
            col.operator("efx_re.bone_add", icon="ADD", text="")
            col.operator("efx_re.bone_remove", icon="REMOVE", text="")

            layout.label(text="Field Parameters:")
            row = layout.row()
            row.template_list(
                "EFX_UL_field_parameters", "", obj, "efx_field_parameters",
                obj, "efx_field_parameters_active_index", rows=3,
            )
            col = row.column(align=True)
            col.operator("efx_re.field_parameter_add", icon="ADD", text="")
            col.operator("efx_re.field_parameter_remove", icon="REMOVE", text="")

            active_index = obj.efx_field_parameters_active_index
            if 0 <= active_index < len(obj.efx_field_parameters):
                box = layout.box()
                for node in obj.efx_field_parameters[active_index].fields:
                    draw_node(box, node)

        elif type_tag == model.TYPE_ENTRY:
            row = layout.row(align=True)
            row.operator("efx_re.entry_copy", icon="COPYDOWN")
            row.operator("efx_re.entry_paste", icon="PASTEDOWN")

            layout.label(text="Subselect Groups:")
            row = layout.row()
            row.template_list(
                "EFX_UL_groups", "", obj, "efx_groups", obj, "efx_groups_active_index", rows=3,
            )
            col = row.column(align=True)
            col.operator("efx_re.group_add", icon="ADD", text="")
            col.operator("efx_re.group_remove", icon="REMOVE", text="")

        elif type_tag == model.TYPE_ACTION:
            layout.operator("efx_re.attribute_paste", icon="PASTEDOWN")

        elif type_tag == model.TYPE_ATTRIBUTE:
            row = layout.row(align=True)
            row.operator("efx_re.attribute_copy", icon="COPYDOWN")
            row.operator("efx_re.attribute_paste", icon="PASTEDOWN")

            box = layout.box()
            box.label(text=f"Type: {obj.efx_attr_type}", translate=False)
            row = box.row(align=True)
            row.label(text=f"UniqueID {obj.efx_unique_id}")
            row.label(text=f"Version {obj.efx_version}")
            row = box.row(align=True)
            row.label(text=f"type id {obj.efx_type_id}")
            row.label(text=f"IsTypeAttribute {obj.efx_is_type_attribute}")

            layout.label(text="Fields:")
            root_obj = io_tree.find_root(obj)
            for node in obj.efx_fields:
                draw_node(layout, node, attr_type=obj.efx_attr_type, root_obj=root_obj)


_CLASSES = (
    EFX_UL_groups,
    EFX_UL_bones,
    EFX_UL_field_parameters,
    EFX_OT_field_info,
    EFX_OT_group_add,
    EFX_OT_group_remove,
    EFX_OT_bone_add,
    EFX_OT_bone_remove,
    EFX_OT_field_parameter_add,
    EFX_OT_field_parameter_remove,
    EFX_PT_main,
    EFX_PT_object,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
