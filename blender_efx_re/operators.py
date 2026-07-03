"""
blender_efx_re/operators.py —— Phase 1 最小闭环：导入（dump）→ 查看 JSON → 导出（load）

这一步只验证"Python ↔ C# 桥接"这条管线本身能跑通，不是最终 UI 形态：
    .efx --[EfxBridge dump]--> JSON --[存成 bpy.data.texts 文本块，可在文本编辑器里看]-->
    （用户在文本编辑器里看/改 JSON——这一步以后会被 PropertyGroup 字段面板取代）-->
    JSON --[EfxBridge load]--> .efx

姊妹项目 EFX-Editor 的 ~TYPE 自定义属性、PointerProperty 交叉引用、字段 PropertyGroup
面板都还没搬过来（那是下一步，需要先决定 JSON 里哪些字段映射到哪些 PropertyGroup）。
"""

from __future__ import annotations

import json

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import bridge


def _summarize(data: dict) -> str:
    entries = data.get("Entries", []) or []
    actions = data.get("Actions", []) or []
    attr_count = sum(len(e.get("Attributes", []) or []) for e in entries)
    return f"{len(entries)} entries, {len(actions)} actions, {attr_count} attributes"


class EFX_OT_import(Operator, ImportHelper):
    """通过 EfxBridge 读取一个 .efx 文件，把中间 JSON 存成文本块供查看"""

    bl_idname = "efx_re.import"
    bl_label = "Import EFX (dump JSON)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    def execute(self, context):
        try:
            data = bridge.dump_efx(self.filepath)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge dump 失败，拒绝导入：\n{ex}")
            return {"CANCELLED"}

        text_name = bpy.path.basename(self.filepath) + ".json"
        text = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
        text.clear()
        text.write(json.dumps(data, ensure_ascii=False, indent=2))

        self.report({"INFO"}, f"已导入到文本块 '{text_name}'：{_summarize(data)}")
        return {"FINISHED"}


class EFX_OT_export(Operator, ExportHelper):
    """把一个文本块里的 JSON（EFX_OT_import 产生的格式）通过 EfxBridge 写回 .efx"""

    bl_idname = "efx_re.export"
    bl_label = "Export EFX (load JSON)"
    bl_options = {"REGISTER"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    text_name: StringProperty(
        name="JSON Text Block",
        description="EFX_OT_import 生成的文本块名字",
    )

    def execute(self, context):
        text = bpy.data.texts.get(self.text_name)
        if text is None:
            self.report({"ERROR"}, f"找不到文本块 '{self.text_name}'")
            return {"CANCELLED"}

        try:
            data = json.loads(text.as_string())
        except json.JSONDecodeError as ex:
            self.report({"ERROR"}, f"文本块内容不是合法 JSON：{ex}")
            return {"CANCELLED"}

        try:
            bridge.load_efx(data, self.filepath)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge load 失败，拒绝导出：\n{ex}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"已导出到 {self.filepath}")
        return {"FINISHED"}


_CLASSES = (EFX_OT_import, EFX_OT_export)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
