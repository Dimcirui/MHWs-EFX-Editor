"""
blender_efx_re/copy_paste.py —— Entry/Attribute 复制/粘贴

架构决策 6："复制/预设：不追求与 Blender 原生 duplicate 语义对齐，走面板内复制/粘贴/预设"。
这里先做复制/粘贴（用户明确了预设系统先不用做）。走 Blender 系统剪贴板
（`window_manager.clipboard`，OS 剪贴板支持，顺带天然支持跨 .blend 文件粘贴），不是自定义
内存变量或 bpy.data.texts——复用 export/build 函数本来就有的对称性：
`export_entry_object()`/`export_attribute_object()` 产出的 dict 形状，恰好就是
`build_entry_object()`/`build_attribute_object()` 消费的输入形状（两者是互为反函数的一对，
import/export 路径早就验证过），复制/粘贴不需要另写一套序列化代码，只需要决定"粘贴到哪个
parent/collection、新对象排第几"。

粘贴对象的 efx_index 取"当前同类型兄弟对象里最大值 + 1"（没有兄弟就是 0）——不影响原有对象
的顺序，新对象排在最后；这是唯一需要在复制/粘贴路径里新写的逻辑，其余全部复用现有
import/export 代码。复制一个 Entry 时，它自己的 Attributes 会在粘贴时被
build_entry_object() 里的 for 循环用全新的 0..n-1 下标重新枚举，不会带着原 Entry 的
attribute 下标混进来。

Attribute 粘贴目标：选中 Entry/Action 时粘贴为它的新的最后一个子 attribute；选中 Attribute
时粘贴为它的兄弟（用它的 parent 当目标）——两种都支持，省得用户每次先手动点回父对象。

已知限制（不在这轮范围内）：复制一个 Entry/Attribute 时，游戏侧的 name/nameHash 等字段
（存在 opaque 数据里）原样带过去，粘贴后的对象在 Outliner 里靠 Blender 自己的 `.001` 去重
后缀区分，但游戏侧数据本身（等 Groups/字段面板暴露的那部分之外）目前没有 UI 能重新编辑
成不一样的值——这是 model.py/io_tree.py 既有的"opaque 字段没有编辑 UI"设计边界，复制/粘贴
没有让它变得更好也没有变得更差。
"""

from __future__ import annotations

import json

import bpy
from bpy.types import Operator

from . import io_tree, model

_CLIP_MARKER_ENTRY = "mhws_efx_entry"
_CLIP_MARKER_ATTRIBUTE = "mhws_efx_attribute"


def _next_index(siblings) -> int:
    return max((o.efx_index for o in siblings), default=-1) + 1


def _write_clipboard(marker: str, data: dict) -> None:
    bpy.context.window_manager.clipboard = json.dumps({"__mhws_efx_clip__": marker, "data": data})


def _read_clipboard(marker: str) -> dict | None:
    try:
        payload = json.loads(bpy.context.window_manager.clipboard)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("__mhws_efx_clip__") != marker:
        return None
    return payload.get("data")


class EFX_OT_entry_copy(Operator):
    """把当前选中 Entry（连同其全部 Attributes）复制到系统剪贴板"""

    bl_idname = "efx_re.entry_copy"
    bl_label = "Copy Entry"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("~TYPE") == model.TYPE_ENTRY

    def execute(self, context):
        data = io_tree.export_entry_object(context.object)
        _write_clipboard(_CLIP_MARKER_ENTRY, data)
        self.report({"INFO"}, f"已复制 Entry '{context.object.name}'")
        return {"FINISHED"}


class EFX_OT_entry_paste(Operator):
    """把剪贴板里的 Entry 粘贴为当前选中对象所在 EFX_ROOT 树的新 Entry（追加到末尾）"""

    bl_idname = "efx_re.entry_paste"
    bl_label = "Paste Entry"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            io_tree.find_root(context.object) is not None
            and _read_clipboard(_CLIP_MARKER_ENTRY) is not None
        )

    def execute(self, context):
        data = _read_clipboard(_CLIP_MARKER_ENTRY)
        if data is None:
            self.report({"ERROR"}, "剪贴板里没有可粘贴的 Entry（先在某个 Entry 上用 Copy Entry）")
            return {"CANCELLED"}

        root_obj = io_tree.find_root(context.object)
        entries_collection, _ = io_tree.root_collections(root_obj)
        siblings = io_tree.typed_children(root_obj, model.TYPE_ENTRY)
        new_index = _next_index(siblings)

        new_obj = io_tree.build_entry_object(data, new_index, root_obj, entries_collection)
        self.report({"INFO"}, f"已粘贴为新 Entry '{new_obj.name}'")
        return {"FINISHED"}


class EFX_OT_attribute_copy(Operator):
    """把当前选中 Attribute（含其可能嵌套的 efxrData 子树）复制到系统剪贴板"""

    bl_idname = "efx_re.attribute_copy"
    bl_label = "Copy Attribute"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE

    def execute(self, context):
        data = io_tree.export_attribute_object(context.object)
        _write_clipboard(_CLIP_MARKER_ATTRIBUTE, data)
        self.report({"INFO"}, f"已复制 Attribute '{context.object.name}'")
        return {"FINISHED"}


def _attribute_paste_target(obj):
    """选中 Entry/Action 时，粘贴目标就是它自己；选中 Attribute 时，粘贴目标是它的 parent
    （粘贴出一个兄弟 attribute）。"""
    if obj is None:
        return None
    tag = obj.get("~TYPE")
    if tag in (model.TYPE_ENTRY, model.TYPE_ACTION):
        return obj
    if tag == model.TYPE_ATTRIBUTE:
        return obj.parent
    return None


class EFX_OT_attribute_paste(Operator):
    """把剪贴板里的 Attribute 粘贴为当前选中 Entry/Action（或当前选中 Attribute 的兄弟）
    的新 attribute（追加到末尾）"""

    bl_idname = "efx_re.attribute_paste"
    bl_label = "Paste Attribute"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            _attribute_paste_target(context.object) is not None
            and _read_clipboard(_CLIP_MARKER_ATTRIBUTE) is not None
        )

    def execute(self, context):
        data = _read_clipboard(_CLIP_MARKER_ATTRIBUTE)
        if data is None:
            self.report({"ERROR"}, "剪贴板里没有可粘贴的 Attribute（先在某个 Attribute 上用 Copy Attribute）")
            return {"CANCELLED"}

        parent_obj = _attribute_paste_target(context.object)
        collection = parent_obj.users_collection[0]
        siblings = io_tree.typed_children(parent_obj, model.TYPE_ATTRIBUTE)
        new_index = _next_index(siblings)

        new_obj = io_tree.build_attribute_object(data, new_index, parent_obj, collection)
        self.report({"INFO"}, f"已粘贴为新 Attribute '{new_obj.name}'")
        return {"FINISHED"}


_CLASSES = (EFX_OT_entry_copy, EFX_OT_entry_paste, EFX_OT_attribute_copy, EFX_OT_attribute_paste)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
