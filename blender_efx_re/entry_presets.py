"""
blender_efx_re/entry_presets.py —— Entry 预设（内置 Basic + 用户自定义）

架构决策 6 的"预设"那一半（另一半——复制/粘贴——早就在 copy_paste.py 里做完了）。范围明确
收窄到**"另存为预设 / 从预设新建 Entry"**：不做"把预设的 attribute 套到一个已经存在的 Entry
上"——那属于合并语义，需要决定"已经有的同类型 attribute 要跳过还是要重复"这类没人问过的问题，
YAGNI（2026-09-10 跟用户确认过，见 CLAUDE.md 22）。也不做 Attribute 级别的预设——粒度只到
Entry。

**内置的 `BUILTIN_NAME` 预设永远存在、不进用户的 JSON 文件、不能删除、也不能被同名覆盖**：
原来"新增空白 Entry"那个按钮（自动带 Transform3D+Spawn+Life+ParentOptions）现在收进了同一个
下拉框，跟用户自己攒的预设摆在一起——对齐姊妹项目 EFX-Editor 的 `__archetypes__/`（内置只读）
+ `__entries__/`（用户可写）合并进同一个下拉的做法。选中它新建时不读取任何存好的 dict，而是
直接调用 `bpy.ops.efx_re.entry_add()`——那个算子本来就是"new_entry() + 套四个基础
attribute"的真实实现，这里复用它而不是把同一份逻辑再拷一份存成 JSON 预设（拷一份的话，以后
`ENTRY_BASIC_PRESET_ATTRS` 改了，JSON 快照不会跟着变，两处会悄悄分叉）。

**用户预设存 Blender 用户配置目录，不放插件目录、也不放 Scene 属性**：
- 不放插件目录：同 i18n.py 语言文件、semantics/ 用户标注表的理由——插件目录在扩展升级时会被
  整体替换，放这儿的话每次更新都会把用户攒的预设库清空。
- 不放 Scene 属性（不随 .blend 走）：预设是"这个人在这台机器上攒的素材库"，不是某个具体场景
  的数据，换一个新场景/新 .blend 文件也应该能用同一份预设库，不该被绑死在某一个文件里。

存的是 `io_tree.export_entry_object()` 原样产出的 dict——跟 copy_paste.py 的 Copy Object
走的是同一条导出路径，`io_tree.build_entry_object()` 直接能吃，不需要另写一套序列化/
反序列化，也不需要为"预设"单独定义一份 dict 形状。
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from . import io_tree, model

BUILTIN_NAME = "Basic"

_cache: list[dict] | None = None


def _presets_file() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_entry_presets.json"


def load_presets() -> list[dict]:
    """`[{"name": str, "data": dict}, ...]`，按保存顺序。首次调用从磁盘读一次，之后走内存
    缓存；`_write_presets()` 之类的写操作会同步刷新缓存，不需要每次都读文件。"""
    global _cache
    if _cache is not None:
        return _cache
    try:
        loaded = json.loads(_presets_file().read_text(encoding="utf-8"))
        _cache = loaded if isinstance(loaded, list) else []
    except (OSError, json.JSONDecodeError):
        _cache = []
    return _cache


def _write_presets(presets: list[dict]) -> None:
    global _cache
    _cache = presets
    try:
        _presets_file().write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as ex:
        # 同 i18n.py set_lang() 的态度：写不进去不该拦住这一次操作本身，只是下次开 Blender
        # 时这份预设不见了。
        print(f"[MHWs EFX Editor] Entry 预设写入失败，本次会话仍然生效：{ex}")


def _find_preset(name: str) -> dict | None:
    for preset in load_presets():
        if preset.get("name") == name:
            return preset
    return None


def _preset_items(self, context):
    builtin = (BUILTIN_NAME, f"{BUILTIN_NAME} (built-in)", "Transform3D + Spawn + Life + ParentOptions")
    user_items = [(p.get("name", ""), p.get("name", ""), "") for p in load_presets()]
    return [builtin, *user_items]


class EFX_RE_OT_entry_preset_save(Operator):
    """把当前选中的 Entry 另存为一个具名预设。同名直接覆盖——这是"另存为"语义，不是追加，
    重名也不警告（用户自己的预设库，自己覆盖自己不需要二次确认）。"""

    bl_idname = "efx_re.entry_preset_save"
    bl_label = "Save Entry as Preset"
    bl_description = "把当前选中的 Entry 另存为具名预设；同名预设会被直接覆盖"
    bl_options = {"REGISTER"}

    preset_name: StringProperty(name="Name")

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.get("~TYPE") == model.TYPE_ENTRY

    def invoke(self, context, event):
        obj = context.object
        self.preset_name = obj.efx_name or obj.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        name = self.preset_name.strip()
        if not name:
            self.report({"ERROR"}, "预设名字不能为空")
            return {"CANCELLED"}
        if name == BUILTIN_NAME:
            self.report({"ERROR"}, f"'{BUILTIN_NAME}' 是内置预设的名字，换一个")
            return {"CANCELLED"}

        data = io_tree.export_entry_object(context.object)
        presets = [p for p in load_presets() if p.get("name") != name]
        presets.append({"name": name, "data": data})
        _write_presets(presets)
        self.report({"INFO"}, f"已把 Entry 另存为预设 '{name}'")
        return {"FINISHED"}


class EFX_RE_OT_entry_preset_new(Operator):
    """从 `WindowManager.efx_re_entry_preset` 选中的预设新建一个 Entry（追加到当前 EFX 树
    末尾）。选中内置的 `BUILTIN_NAME` 时直接转调 `efx_re.entry_add`（同一份"套基础骨架"的
    实现，不再拷贝一份），选中用户自己的预设时才走存好的 dict。"""

    bl_idname = "efx_re.entry_preset_new"
    bl_label = "New Entry from Preset"
    bl_description = "从选中的预设新建一个 Entry，追加到当前 EFX 树末尾"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        name = getattr(context.window_manager, "efx_re_entry_preset", "")
        return bool(name) and io_tree.resolve_root(context) is not None

    def execute(self, context):
        name = context.window_manager.efx_re_entry_preset
        if name == BUILTIN_NAME:
            return bpy.ops.efx_re.entry_add()

        preset = _find_preset(name)
        if preset is None:
            self.report({"ERROR"}, f"预设 '{name}' 不存在（可能已被删除）")
            return {"CANCELLED"}

        root_col = io_tree.resolve_root(context)
        entries_collection, _ = io_tree.root_collections(root_col)
        siblings = io_tree.root_entries(root_col)
        new_index = io_tree.next_sibling_index(siblings)
        new_obj = io_tree.build_entry_object(preset["data"], new_index, entries_collection)
        self.report({"INFO"}, f"已从预设 '{name}' 新建 Entry '{new_obj.name}'")
        return {"FINISHED"}


class EFX_RE_OT_entry_preset_delete(Operator):
    """删除 `WindowManager.efx_re_entry_preset` 选中的预设。内置的 `BUILTIN_NAME` 不在
    `poll()` 允许的范围内——它不是用户存进 JSON 文件的东西，没有"删除"这个操作可谈。"""

    bl_idname = "efx_re.entry_preset_delete"
    bl_label = "Delete Entry Preset"
    bl_description = "删除当前选中的 Entry 预设（内置的 Basic 预设不能删）"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        name = getattr(context.window_manager, "efx_re_entry_preset", "")
        return bool(name) and name != BUILTIN_NAME

    def execute(self, context):
        name = context.window_manager.efx_re_entry_preset
        presets = [p for p in load_presets() if p.get("name") != name]
        _write_presets(presets)
        self.report({"INFO"}, f"已删除预设 '{name}'")
        return {"FINISHED"}


_CLASSES = (EFX_RE_OT_entry_preset_save, EFX_RE_OT_entry_preset_new, EFX_RE_OT_entry_preset_delete)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    # WindowManager 而不是 Scene：跟 panels.py 的 efx_re_attr_category 同一个理由——纯粹的界面
    # 临时状态（"当前选中哪个预设"），不该被存进 .blend 文件跟着场景走。
    bpy.types.WindowManager.efx_re_entry_preset = EnumProperty(
        name="Preset",
        description="已保存的 Entry 预设",
        items=_preset_items,
    )


def unregister():
    del bpy.types.WindowManager.efx_re_entry_preset
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
