"""blender_efx_re/panels.py —— Phase 1 最小 N 面板：import/export 按钮 + JSON 文本块选择"""

from __future__ import annotations

import bpy
from bpy.types import Panel


class EFX_PT_main(Panel):
    bl_idname = "EFX_PT_main"
    bl_label = "MHWs EFX (Phase 1 scaffold)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "EFX"

    def draw(self, context):
        layout = self.layout
        layout.operator("efx_re.import", icon="IMPORT")

        box = layout.box()
        box.label(text="Export from JSON text block:")
        json_texts = [t.name for t in bpy.data.texts if t.name.endswith(".json")]
        op = box.operator("efx_re.export", icon="EXPORT")
        # text_name 是 ExportHelper 弹出文件浏览器时侧栏里的一个属性；这里预填最近一个
        # JSON 文本块的名字作默认值，弹窗侧栏里仍可改成别的文本块名。
        op.text_name = json_texts[-1] if json_texts else ""
        if not json_texts:
            box.label(text="(先用上面的 Import 生成一个)")


_CLASSES = (EFX_PT_main,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
