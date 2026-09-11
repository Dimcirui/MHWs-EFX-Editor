"""
blender_efx_re/uvs_panels.py —— MHWilds UVS 侧栏

独立的 N 面板标签页 `MHWilds UVS`，和 EFX 那套 `Wilds EFX` 标签页并存但分开——两者是完全
不同的文件格式/数据模型（EFX 是 ~150 种 attribute 的树，UVS 是固定形状的三级数据表），揉进
同一个标签页只会增加认知负担。UI 结构对齐 panels.py 的既有约定（UIList + 增删按钮 +
`bl_order` 用负数），但不复用它的私有辅助函数——两个标签页刻意保持互相独立，不产生跨模块
耦合。
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty
from bpy.types import Panel, UIList

from . import i18n, uvs_io, uvs_model, uvs_operators
from .i18n import T

_CATEGORY = "MHWilds UVS"


def _active_root_poll(self, col):
    return col.get("~TYPE") == uvs_model.TYPE_UVS_ROOT


def _draw_uilist_row(layout, list_cls, obj, coll_name, index_name, add_op, remove_op, rows=3):
    row = layout.row()
    row.template_list(list_cls, "", obj, coll_name, obj, index_name, rows=rows)
    col = row.column(align=True)
    col.operator(add_op, icon="ADD", text="")
    col.operator(remove_op, icon="REMOVE", text="")


class EFX_UVS_UL_textures(UIList):
    bl_idname = "EFX_UVS_UL_textures"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=str(index), translate=False)
        row.prop(item, "path", text="", emboss=False, icon="TEXTURE")


class EFX_UVS_UL_sequences(UIList):
    bl_idname = "EFX_UVS_UL_sequences"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, translate=False, icon="ANIM")
        row.label(text=f"{len(item.patterns)} {T('common.items_suffix')}", translate=False)


class EFX_UVS_UL_patterns(UIList):
    bl_idname = "EFX_UVS_UL_patterns"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=str(index), translate=False, icon="MESH_PLANE")
        row.label(
            text=f"L{item.left:.4f} T{item.top:.4f} R{item.right:.4f} B{item.bottom:.4f}"
                 f"  tex:{item.texture_index}",
            translate=False,
        )


class EFX_UVS_PT_main(Panel):
    """主面板：语言、导入导出、当前 UVS。"""

    bl_idname = "EFX_UVS_PT_main"
    bl_label = "MHWilds UVS"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = -3

    def draw(self, context):
        layout = self.layout
        i18n.draw_language_toggle(layout)
        layout.separator(factor=0.5)

        layout.operator("efx_uvs.new", text=T("uvs.new"), icon="FILE_NEW", translate=False)

        row = layout.row(align=True)
        row.operator("efx_uvs.import", text=T("uvs.import"), icon="IMPORT", translate=False)
        row.operator("efx_uvs.export", text=T("uvs.export"), icon="EXPORT", translate=False)

        layout.prop(context.scene, "efx_uvs_active_root", text=T("uvs.active_uvs"))

        root_col = uvs_io.resolve_uvs_root(context)
        if root_col is not None:
            layout.operator(
                "efx_uvs.advanced_edit", text=T("uvs.advanced_edit"), icon="IMAGE_DATA",
                translate=False,
            )
            box = layout.box()
            box.label(text=f"File Version: {uvs_model.MHWILDS_UVS_FILE_VERSION} (MHWilds)", translate=False)
            box.prop(root_col, "efx_uvs_cutout_related")
            hint = box.row()
            hint.enabled = False
            hint.label(text=T("uvs.advanced_edit_hint"), translate=False)


class EFX_UVS_PT_textures(Panel):
    bl_idname = "EFX_UVS_PT_textures"
    bl_label = "Textures"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = -2

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def draw(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        layout = self.layout
        _draw_uilist_row(
            layout, "EFX_UVS_UL_textures", root_col, "efx_uvs_textures",
            "efx_uvs_textures_active_index", "efx_uvs.texture_add", "efx_uvs.texture_remove",
            rows=5,
        )
        index = root_col.efx_uvs_textures_active_index
        if 0 <= index < len(root_col.efx_uvs_textures):
            item = root_col.efx_uvs_textures[index]
            box = layout.box()
            box.prop(item, "path")
            row = box.row(align=True)
            row.enabled = False
            row.label(text=T("uvs.texture_handles_hint"), translate=False)
            row = box.row(align=True)
            row.prop(item, "state_holder")
            row.prop(item, "tex_handle1")
            row.prop(item, "tex_handle2")
            row.prop(item, "tex_handle3")


class EFX_UVS_PT_sequences(Panel):
    bl_idname = "EFX_UVS_PT_sequences"
    bl_label = "Sequences"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = -1

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def draw(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        layout = self.layout
        _draw_uilist_row(
            layout, "EFX_UVS_UL_sequences", root_col, "efx_uvs_sequences",
            "efx_uvs_sequences_active_index", "efx_uvs.sequence_add", "efx_uvs.sequence_remove",
        )

        seq_index = root_col.efx_uvs_sequences_active_index
        if not (0 <= seq_index < len(root_col.efx_uvs_sequences)):
            return
        seq = root_col.efx_uvs_sequences[seq_index]

        layout.separator()
        layout.label(text=T("uvs.patterns"), translate=False)
        row = layout.row()
        row.template_list(
            "EFX_UVS_UL_patterns", "", seq, "patterns", seq, "patterns_active_index", rows=6,
        )
        col = row.column(align=True)
        col.operator("efx_uvs.pattern_add", icon="ADD", text="")
        col.operator("efx_uvs.pattern_remove", icon="REMOVE", text="")

        layout.operator(
            "efx_uvs.pattern_generate_grid", text=T("uvs.generate_grid"), icon="MESH_GRID",
            translate=False,
        )

        layout.separator()
        if uvs_operators._check_pillow():
            layout.operator(
                "efx_uvs.gif_to_sequence", text=T("uvs.gif_to_sequence"), icon="RENDER_ANIMATION",
                translate=False,
            )
        else:
            layout.label(text=T("uvs.need_pillow"), icon="ERROR")
        # pattern 的矩形/贴图下标/flags 字段编辑不放在这个基础侧栏——挪到「进阶编辑」（图形
        # 编辑器）那边了：矩形有叠加框实时对照，比在这里对着裸数字编辑靠谱，见
        # uvs_image_editor.EFX_UVS_PT_image_editor。


_CLASSES = (
    EFX_UVS_UL_textures, EFX_UVS_UL_sequences, EFX_UVS_UL_patterns,
    EFX_UVS_PT_main, EFX_UVS_PT_textures, EFX_UVS_PT_sequences,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.efx_uvs_active_root = PointerProperty(
        type=bpy.types.Collection,
        name="Active UVS",
        description="当前操作的目标 UVS 文件（活动集合不属于任何 EFX_UVS 树时的兜底选择器）",
        poll=_active_root_poll,
    )


def unregister():
    try:
        del bpy.types.Scene.efx_uvs_active_root
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
