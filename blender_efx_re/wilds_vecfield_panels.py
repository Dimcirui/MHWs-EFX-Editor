"""MHWilds VecField 侧栏的"场信息"小面板。

从姊妹项目 blender_tfa_importer 的 ui_panels.py 移植过来，只改了
bl_idname / bl_category 和场景数据 key，避免和同一个 Blender 会话里
可能同时启用的 blender_tfa_importer 撞名。
"""
import bpy
from bpy.types import Panel
import numpy as np


class VIEW3D_PT_wilds_vecfield_field_info(Panel):
    bl_label = "Field Information"
    bl_idname = "VIEW3D_PT_wilds_vecfield_field_info"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MHWilds VecField"
    bl_context = "objectmode"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return 'wilds_vecfield_data' in context.scene

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        if 'wilds_vecfield_data' in scene:
            field_data = scene['wilds_vecfield_data']
            dims = field_data['dimensions']

            box = layout.box()
            box.label(text="Field Properties", icon='INFO')
            box.label(text=f"Dimensions: {dims[0]}×{dims[1]}×{dims[2]}")

            try:
                vectors = np.array(field_data['vectors'])
                magnitude = np.linalg.norm(vectors, axis=3)

                box.label(text=f"Average Magnitude: {magnitude.mean():.3f}")
                box.label(text=f"Max Magnitude: {magnitude.max():.3f}")

                box.label(text="Vector Components:")
                row = box.row()
                col = row.column()
                col.label(text=f"X: [{vectors[..., 0].min():.3f}, {vectors[..., 0].max():.3f}]")
                col.label(text=f"Y: [{vectors[..., 1].min():.3f}, {vectors[..., 1].max():.3f}]")
                col.label(text=f"Z: [{vectors[..., 2].min():.3f}, {vectors[..., 2].max():.3f}]")
            except Exception:
                box.label(text="Statistics unavailable")


def register():
    bpy.utils.register_class(VIEW3D_PT_wilds_vecfield_field_info)


def unregister():
    bpy.utils.unregister_class(VIEW3D_PT_wilds_vecfield_field_info)
