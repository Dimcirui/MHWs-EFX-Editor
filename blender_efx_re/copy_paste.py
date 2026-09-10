"""
blender_efx_re/copy_paste.py —— Entry/Attribute 复制/粘贴

架构决策 6："复制/预设：不追求与 Blender 原生 duplicate 语义对齐，走面板内复制/粘贴/预设"。
这里先做复制/粘贴（用户明确了预设系统先不用做）。走 Blender 系统剪贴板
（`window_manager.clipboard`，OS 剪贴板支持，顺带天然支持跨 .blend 文件粘贴），不是自定义
内存变量或 bpy.data.texts——复用 export/build 函数本来就有的对称性：
`export_entry_object()`/`export_attribute_object()` 产出的 dict 形状，恰好就是
`build_entry_object()`/`build_attribute_object()` 消费的输入形状（两者是互为反函数的一对，
import/export 路径早就验证过），复制/粘贴不需要另写一套序列化代码。

**两类复制，对应两个独立剪贴板槽位（互不覆盖）：**

1. Copy/Paste Object（`_CLIP_MARKER_OBJECT`）——复制整个 Entry 或 Attribute（含身份、含子
   内容），粘贴出一个新对象。Entry/Attribute 共用一对算子，不用像以前那样分别记
   Copy Entry / Copy Attribute：复制时把"这是哪种类型"存进剪贴板 payload 的 `kind` 字段，
   粘贴时按它自动分派到 `build_entry_object()`/`build_attribute_object()`，面板上再把这个
   `kind`/`label` 画出来（仿 RE Mesh Editor："当前剪贴板里是什么类型"一眼可见），不需要用户
   自己记住上次复制的是哪一种。

2. Copy/Paste Properties（`_CLIP_MARKER_PROPERTIES`）——只复制"内容"（Entry:
   Groups/entryAssignment/未建 UI 的 opaque 字段；Attribute: Fields 通用树 +
   Clip/Expression 曲线），不含身份（name/efx_index/UniqueID/parent/子对象）和嵌套 efxrData
   子树，套到**已经存在**的同类型目标对象上（原地覆盖内容，不新建对象）。Attribute 额外要求
   `$type` 完全一致——不同 $type 的字段结构不兼容，贴错了要么静默丢字段要么读回来直接崩，属于
   铁律 2"宁可拒绝不要静默丢数据"，在 poll() 里就拦掉，不让按钮亮起来。

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
from bpy.types import Object, Operator

from . import io_tree, model

_CLIP_MARKER_OBJECT = "mhws_efx_object"
_CLIP_MARKER_PROPERTIES = "mhws_efx_properties"


def _object_label(obj: Object, tag: str) -> str:
    if tag == model.TYPE_ENTRY:
        return "Entry"
    return io_tree.short_attr_name(obj.efx_attr_type)


_CLIP_MAGIC = "__mhws_efx_clip__"

# window_manager.clipboard 是**唯一一份**系统剪贴板字符串，不是"每个 marker 一个独立槽位"——
# 两个槽位（Object/Properties）都要落在这同一根字符串上才能保持"系统剪贴板、天然支持跨 .blend
# 粘贴"这个初衷，所以两个槽位的 payload 一起打包进同一个 JSON blob 的不同键下面。以前
# `_write_clipboard()` 曾经是整根字符串直接被单个 marker 的 payload 覆盖——这样 Copy Properties
# 会把刚 Copy Object 存的东西冲掉，反过来也一样，2026-09-10 用真实 Blender GUI 实测复现确认
# （`describe_object_clipboard()` 在 Copy Properties 之后变回 None）。现在改成"读旧 blob、
# 只更新自己这个 marker 的键、写回整个 blob"，两个槽位互不覆盖。
# 如果剪贴板内容是外部程序写入的无关文本（连 `_CLIP_MAGIC` 都没有），`_read_all()` 老老实实
# 返回空 dict——那不是 bug，是系统剪贴板真的已经被外部内容替换了，我们这边记的两个槽位本来就
# 应该跟着"消失"（数据不在了，不是记录丢了）。


def _read_all() -> dict:
    try:
        payload = json.loads(bpy.context.window_manager.clipboard)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(payload, dict) or _CLIP_MAGIC not in payload:
        return {}
    return payload


def _write_clipboard(marker: str, payload: dict) -> None:
    blob = _read_all()
    blob[_CLIP_MAGIC] = True
    blob[marker] = payload
    bpy.context.window_manager.clipboard = json.dumps(blob)


def _read_clipboard(marker: str) -> dict | None:
    """读回 `_write_clipboard(marker, ...)` 存的那个槽位的完整 payload（含 kind/label/data），
    不影响另一个槽位。"""
    return _read_all().get(marker)


def describe_clipboard(marker: str) -> str | None:
    """给面板画"当前剪贴板里存的是什么类型"用（仿 RE Mesh Editor 的复制提示）。返回 None
    表示这个槽位里没有可粘贴的东西。"""
    payload = _read_clipboard(marker)
    if payload is None:
        return None
    return payload.get("label") or payload.get("kind") or "?"


def describe_object_clipboard() -> str | None:
    return describe_clipboard(_CLIP_MARKER_OBJECT)


def describe_properties_clipboard() -> str | None:
    return describe_clipboard(_CLIP_MARKER_PROPERTIES)


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


# ---------------------------------------------------------------------------
# Copy/Paste Object：整个 Entry/Attribute，粘贴出一个新对象
# ---------------------------------------------------------------------------

class EFX_RE_OT_object_copy(Operator):
    """把当前选中的 Entry 或 Attribute（连同其全部子内容）整体复制到系统剪贴板"""

    bl_idname = "efx_re.object_copy"
    bl_label = "Copy Object"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("~TYPE") in (model.TYPE_ENTRY, model.TYPE_ATTRIBUTE)

    def execute(self, context):
        obj = context.object
        tag = obj.get("~TYPE")
        data = io_tree.export_entry_object(obj) if tag == model.TYPE_ENTRY else io_tree.export_attribute_object(obj)
        label = _object_label(obj, tag)
        _write_clipboard(_CLIP_MARKER_OBJECT, {"kind": tag, "label": label, "data": data})
        self.report({"INFO"}, f"已复制 {label} '{obj.name}'")
        return {"FINISHED"}


class EFX_RE_OT_object_paste(Operator):
    """把剪贴板里的 Entry/Attribute 粘贴为一个新对象——按复制时记下的类型自动分派：
    Entry 粘贴到当前 EFX 树的末尾（目标树按 io_tree.resolve_root() 解析：活动对象所在的树
    优先，没有就用面板上的「当前 EFX」选择器）；Attribute 粘贴为当前选中 Entry/Action 的新子
    attribute，或当前选中 Attribute 的新兄弟 attribute。"""

    bl_idname = "efx_re.object_paste"
    bl_label = "Paste Object"
    bl_description = "把剪贴板里的 Entry/Attribute 粘贴成新对象：Entry 追加到树末尾，Attribute 挂到当前选中的 Entry/Action 下"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        payload = _read_clipboard(_CLIP_MARKER_OBJECT)
        if payload is None:
            return False
        kind = payload.get("kind")
        if kind == model.TYPE_ENTRY:
            return io_tree.resolve_root(context) is not None
        if kind == model.TYPE_ATTRIBUTE:
            return _attribute_paste_target(context.object) is not None
        return False

    def execute(self, context):
        payload = _read_clipboard(_CLIP_MARKER_OBJECT)
        if payload is None:
            self.report({"ERROR"}, "剪贴板里没有可粘贴的对象（先在某个 Entry/Attribute 上用 Copy Object）")
            return {"CANCELLED"}

        kind = payload.get("kind")
        data = payload.get("data")
        label = payload.get("label") or kind

        if kind == model.TYPE_ENTRY:
            root_col = io_tree.resolve_root(context)
            entries_collection, _ = io_tree.root_collections(root_col)
            siblings = io_tree.root_entries(root_col)
            new_index = io_tree.next_sibling_index(siblings)
            new_obj = io_tree.build_entry_object(data, new_index, entries_collection)
        else:
            parent_obj = _attribute_paste_target(context.object)
            collection = parent_obj.users_collection[0]
            siblings = io_tree.typed_children(parent_obj, model.TYPE_ATTRIBUTE)
            new_index = io_tree.next_sibling_index(siblings)
            new_obj = io_tree.build_attribute_object(data, new_index, parent_obj, collection)
            # 同 structure_ops.EFX_RE_OT_attribute_add：粘贴进来的 attribute 可能是
            # TypeAttribute 或 PtLife/PtColliderAction，父 Entry 的显示名后缀要跟着更新。
            model.refresh_entry_display_name(parent_obj)

        self.report({"INFO"}, f"已粘贴为新 {label} '{new_obj.name}'")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Copy/Paste Properties：只覆盖内容，不新建对象
# ---------------------------------------------------------------------------

class EFX_RE_OT_properties_copy(Operator):
    """只复制当前选中 Entry/Attribute 的"内容"（不含身份、不含嵌套 efxrData 子树），
    留着套到另一个已经存在的同类型对象上"""

    bl_idname = "efx_re.properties_copy"
    bl_label = "Copy Properties"
    bl_description = "只复制当前 Entry/Attribute 的字段内容（不含子对象），用来套到另一个同类型对象上"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("~TYPE") in (model.TYPE_ENTRY, model.TYPE_ATTRIBUTE)

    def execute(self, context):
        obj = context.object
        tag = obj.get("~TYPE")
        # 复用整对象导出：apply_entry_content()/apply_attribute_content() 只挑内容相关的键，
        # 身份字段（name/Attributes/$type/UniqueID/...）混在同一个 dict 里传过去也没关系，
        # 会被原样忽略，不需要单独写一套"只导出内容"的序列化。
        data = io_tree.export_entry_object(obj) if tag == model.TYPE_ENTRY else io_tree.export_attribute_object(obj)
        label = _object_label(obj, tag)
        _write_clipboard(_CLIP_MARKER_PROPERTIES, {"kind": tag, "label": label, "data": data})
        self.report({"INFO"}, f"已复制 {label} 的属性")
        return {"FINISHED"}


def _properties_paste_ok(context) -> bool:
    obj = context.object
    if obj is None:
        return False
    payload = _read_clipboard(_CLIP_MARKER_PROPERTIES)
    if payload is None:
        return False
    tag = obj.get("~TYPE")
    if tag != payload.get("kind"):
        return False
    if tag == model.TYPE_ATTRIBUTE:
        data = payload.get("data") or {}
        return data.get("$type") == obj.efx_attr_type
    return tag == model.TYPE_ENTRY


class EFX_RE_OT_properties_paste(Operator):
    """把剪贴板里的属性套到当前选中对象上，原地覆盖内容，不新建对象。Entry 只能贴到 Entry，
    Attribute 只能贴到 $type 完全相同的 Attribute——类型不匹配时字段结构对不上，贴进去要么
    静默丢字段要么读回来直接崩，所以在 poll() 里就拦掉，不新写一条"类型不匹配"的运行时校验
    也能生效（铁律 2）。"""

    bl_idname = "efx_re.properties_paste"
    bl_label = "Paste Properties"
    bl_description = "把剪贴板里的字段内容原地覆盖到当前选中对象上（Entry 对 Entry，Attribute 对同类型 Attribute）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _properties_paste_ok(context)

    def execute(self, context):
        obj = context.object
        payload = _read_clipboard(_CLIP_MARKER_PROPERTIES)
        if payload is None:
            self.report({"ERROR"}, "剪贴板里没有可粘贴的属性（先在某个 Entry/Attribute 上用 Copy Properties）")
            return {"CANCELLED"}

        tag = obj.get("~TYPE")
        data = payload.get("data")
        if tag == model.TYPE_ENTRY:
            io_tree.apply_entry_content(obj, data)
        else:
            # poll() 已经拦过一次 $type，这里防的是"poll 通过之后、execute 跑之前剪贴板内容
            # 被换掉"这种理论上存在的时间窗，双保险不吃性能（就是个字符串比较）。
            if data.get("$type") != obj.efx_attr_type:
                self.report({"ERROR"}, "类型不匹配，已取消（Attribute 属性只能贴到同类型的 Attribute 上）")
                return {"CANCELLED"}
            obj.efx_fields.clear()
            obj.efx_clip_curves.clear()
            obj.efx_expression_curves.clear()
            io_tree.apply_attribute_content(obj, data)

        self.report({"INFO"}, f"已把属性贴到 '{obj.name}'")
        return {"FINISHED"}


_CLASSES = (
    EFX_RE_OT_object_copy, EFX_RE_OT_object_paste,
    EFX_RE_OT_properties_copy, EFX_RE_OT_properties_paste,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
