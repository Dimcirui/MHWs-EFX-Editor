"""
blender_efx_re/operators.py —— Import/Export：.efx <-> ~TYPE 对象树

替换了此前"存成 JSON 文本块查看"的占位实现（见 io_tree.py 头部注释）。导入失败（EfxBridge dump
抛异常）按 PLAN.md 架构决策第 9 点整文件拒绝，不吞异常塞半成品对象树进场景。
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import bridge, io_tree


def _summarize(data: dict) -> str:
    entries = data.get("Entries", []) or []
    actions = data.get("Actions", []) or []
    attr_count = sum(len(e.get("Attributes", []) or []) for e in entries)
    return f"{len(entries)} entries, {len(actions)} actions, {attr_count} entry-level attributes"


class EFX_OT_import(Operator, ImportHelper):
    """通过 EfxBridge 读取一个 .efx 文件，建成 ~TYPE 对象树"""

    bl_idname = "efx_re.import"
    bl_label = "Import EFX"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    def execute(self, context):
        try:
            data = bridge.dump_efx(self.filepath)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge dump 失败，拒绝导入：\n{ex}")
            return {"CANCELLED"}

        name = bpy.path.basename(self.filepath)
        root_obj = io_tree.build_root_from_efxfile(data, context.scene.collection, name)

        self.report({"INFO"}, f"已导入 '{root_obj.name}'：{_summarize(data)}")
        return {"FINISHED"}


class EFX_OT_export(Operator, ExportHelper):
    """从当前活动对象所在的 EFX_ROOT 对象树导出，通过 EfxBridge 写回 .efx"""

    bl_idname = "efx_re.export"
    bl_label = "Export EFX"
    bl_options = {"REGISTER"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return io_tree.find_root(context.object) is not None

    def execute(self, context):
        root_obj = io_tree.find_root(context.object)
        if root_obj is None:
            self.report({"ERROR"}, "选中一个属于某个 EFX_ROOT 对象树的对象（Entry/Action/Attribute/Root 均可）")
            return {"CANCELLED"}

        try:
            io_tree.check_bone_references(root_obj)
        except io_tree.BoneReferenceError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        data = io_tree.export_root_to_efxfile(root_obj)

        try:
            bridge.load_efx(data, self.filepath)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge load 失败，拒绝导出：\n{ex}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"已从 '{root_obj.name}' 导出到 {self.filepath}")
        return {"FINISHED"}


_CLASSES = (EFX_OT_import, EFX_OT_export)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
