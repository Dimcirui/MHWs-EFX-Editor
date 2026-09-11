"""
blender_efx_re/i18n.py —— 面板文案的中英切换

对齐姊妹项目 EFX-Editor 的 `blender_efx/i18n.py`：主面板顶部一行 [English][中文] 按钮，
按下即时切换，面板正文里所有文案都走 `T("key")` 取。

**只管面板正文，不管面板标题**——`Panel.bl_label` / `Operator.bl_label` 是注册期就固定的
类属性，Blender 不支持运行时改，所以标题栏一律留英文（姊妹项目同样如此）。需要翻译的按钮
在 draw() 里用 `layout.operator(..., text=T(...))` 覆盖显示文字。

语言状态存在 Blender 用户配置目录下的独立文件里，不放插件目录——插件目录在扩展升级时会被
整体替换，放那儿的话每次更新都会把用户的选择重置回默认（同 semantics/ 用户标注表的理由）。

**不要用 Blender 自带的界面翻译**（`bpy.app.translations`）：它按 msgid 全局匹配，我们的
字段名（"Saturation" 这类）会撞上 Blender 内置词条被静默替换，见 panels.py `_draw_label()`
里 translate=False 的说明。这里是我们自己查表，不经过那套机制。
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

_DEFAULT_LANG = "ZH"
_LANG = _DEFAULT_LANG
_LOADED = False


def _lang_file() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_editor_lang.txt"


def get_lang() -> str:
    """当前语言（'EN' / 'ZH'）。首次调用时从配置文件读一次，之后走内存。"""
    global _LANG, _LOADED
    if not _LOADED:
        _LOADED = True
        try:
            val = _lang_file().read_text(encoding="utf-8").strip()
            _LANG = val if val in ("EN", "ZH") else _DEFAULT_LANG
        except OSError:
            _LANG = _DEFAULT_LANG
    return _LANG


def set_lang(lang: str) -> None:
    global _LANG, _LOADED
    _LANG = lang if lang in ("EN", "ZH") else _DEFAULT_LANG
    _LOADED = True
    try:
        _lang_file().write_text(_LANG, encoding="utf-8")
    except OSError as ex:
        # 写不进去不该拦住切换本身——这一次会话内仍然生效，只是下次开 Blender 会退回默认。
        print(f"[MHWs EFX Editor] 语言设置写入失败，本次会话仍然生效：{ex}")


def T(key: str) -> str:
    """查一条界面文案。查不到就原样返回 key——漏词条时界面上会直接看到那个 key，
    比静默回退到空字符串更容易发现。"""
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(get_lang()) or entry.get("EN") or key


def draw_language_toggle(layout) -> None:
    """画语言切换行：[English][中文]，高亮当前语言。"""
    cur = get_lang()
    row = layout.row(align=True)
    row.operator("efx_re.set_language", text="English", depress=(cur == "EN")).lang = "EN"
    row.operator("efx_re.set_language", text="中文", depress=(cur == "ZH")).lang = "ZH"


class EFX_RE_OT_set_language(Operator):
    """切换 MHWs EFX 面板的显示语言"""

    bl_idname = "efx_re.set_language"
    bl_label = "Set Language"
    bl_options = {"INTERNAL"}

    lang: EnumProperty(
        items=[("EN", "English", ""), ("ZH", "中文", "")],
        options={"HIDDEN"},
    )

    def execute(self, context):
        set_lang(self.lang)
        # 分类下拉的显示文案是缓存住的（EnumProperty items 的字符串必须被持有），切语言后要重算
        from . import attribute_types
        attribute_types.invalidate_labels()
        # 面板正文是在 draw() 里现查的，重画一次所有区域就够，不需要重注册任何类。
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {"FINISHED"}


# ─────────────────────────────────────────────────────────────────────────────
# 文案表
#
# 键名沿用姊妹项目的 "<面板>.<用途>" 分段习惯，方便两边对照。字段级的标签/tooltip **不在
# 这里**——那是 semantics/ 知识表的内容（按 attribute 类型 + 字段名索引），见
# semantics.get_field_entry() 和 panels._field_label()。
# ─────────────────────────────────────────────────────────────────────────────

_STRINGS: dict[str, dict[str, str]] = {
    # 主面板
    "main.new":                {"EN": "New EFX",             "ZH": "新建 EFX"},
    "main.import":            {"EN": "Import EFX",          "ZH": "导入 EFX"},
    "main.export":            {"EN": "Export EFX",          "ZH": "导出 EFX"},
    "main.active_efx":        {"EN": "Active EFX",          "ZH": "当前 EFX"},
    "main.sync_transform":    {"EN": "Sync Transform3D",    "ZH": "刷新特效体位置"},
    "main.validate":          {"EN": "Validate",            "ZH": "校验"},
    "main.angle_degrees":     {"EN": "Angles in degrees",   "ZH": "角度按度显示"},

    # 通用
    "common.items_suffix":    {"EN": "items",               "ZH": "项"},

    # Root（EFX 文件级）
    "root.bones":             {"EN": "Bones",               "ZH": "骨骼表"},
    "root.field_parameters":  {"EN": "Field Parameters",    "ZH": "场参数"},
    "root.uvar_groups":       {"EN": "Uvar Groups",         "ZH": "Uvar 组"},
    "root.expression_parameters": {"EN": "Expression Parameters", "ZH": "Expression 参数"},

    # Entry
    "entry.effect_groups": {"EN": "EffectGroups",    "ZH": "EffectGroups"},
    "entry.no_assignment_warning": {
        "EN": "Entry Assignment is NoAssignment — Groups tags above won't take effect in-game",
        "ZH": "Entry Assignment 是 NoAssignment——上面挂的 Groups 标签游戏里不会生效",
    },

    # Attribute
    # 注意：Clip / Expression / Fields 是**面板标题**（bl_label，注册期固定，不可运行时改），
    # 不在这张表里；这里只有面板正文里的文案。
    "attribute.type":         {"EN": "Type",                "ZH": "类型"},
    "attribute.loop_type":    {"EN": "Loop Type",           "ZH": "循环方式"},
    "attribute.bit_count":    {"EN": "bit count",           "ZH": "bit 数"},
    "attribute.keyframes":    {"EN": "Keyframes",           "ZH": "关键帧"},
    "attribute.no_fields":    {"EN": "This attribute has no editable fields.",
                               "ZH": "这个 attribute 没有可编辑字段。"},
    "attribute.min_max_crash_warning": {
        "EN": "Max is less than Min — this crashes the game",
        "ZH": "Max 小于 Min ——这个组合会让游戏崩溃",
    },
    "attribute.show_all_fields": {"EN": "Show all fields", "ZH": "显示全部字段"},

    # Add（新增结构）
    "add.action":             {"EN": "Add Action",          "ZH": "新增 Action"},
    "add.attribute":          {"EN": "Add Attribute",       "ZH": "新增 Attribute"},
    "add.search_attribute":   {"EN": "Search Attribute Type", "ZH": "搜索 Attribute 类型"},
    "add.category":           {"EN": "Category",            "ZH": "分类"},
    "add.target_prefix":      {"EN": "Add to: ",            "ZH": "加到："},
    "add.no_target":          {"EN": "(select an Entry or Action)",
                               "ZH": "（先选中一个 Entry 或 Action）"},
    "add.order_hint":         {"EN": "Order is fixed by itemTypeId.",
                               "ZH": "排列顺序由 itemTypeId 定死，不可手动调整。"},
    "add.no_types_in_category": {"EN": "(no addable types in this category)",
                               "ZH": "（该分类下没有可新建的类型）"},
    "add.entry_from_preset":  {"EN": "New Entry from Preset", "ZH": "从预设新建 Entry"},
    "add.search_entry_preset": {"EN": "Search Entry Preset", "ZH": "搜索 Entry 预设"},
    "add.save_entry_preset":  {"EN": "Save Entry as Preset",  "ZH": "另存为预设"},
    "add.save_preset_no_target": {"EN": "(select an Entry first)",
                               "ZH": "（先选中一个 Entry）"},
    "add.save_preset_prefix": {"EN": "Save from: ",           "ZH": "另存自："},

    # Attribute 分类。id 由 tools/gen_attribute_catalogue.py 按 vendor 的源文件分组打上，
    # 这里只负责文案。漏词条时 T() 会原样返回 "category.xxx"，界面上一眼能看见。
    "category.all":              {"EN": "All",               "ZH": "全部"},
    "category.render_billboard": {"EN": "Billboard",         "ZH": "渲染 · 公告板"},
    "category.render_mesh":      {"EN": "Mesh",              "ZH": "渲染 · 网格"},
    "category.render_ribbon":    {"EN": "Ribbon",            "ZH": "渲染 · 飘带"},
    "category.render_polygon":   {"EN": "Polygon",           "ZH": "渲染 · 多边形"},
    "category.render_strain":    {"EN": "Strain",            "ZH": "渲染 · 拉丝"},
    "category.render_lightning": {"EN": "Lightning",         "ZH": "渲染 · 闪电"},
    "category.render_other":     {"EN": "Other Renderers",   "ZH": "渲染 · 其它"},
    "category.transform":        {"EN": "Transform",         "ZH": "变换"},
    "category.emitter":          {"EN": "Emitter",           "ZH": "发射器"},
    "category.velocity":         {"EN": "Velocity",          "ZH": "速度"},
    "category.particle":         {"EN": "Particle Behavior", "ZH": "粒子行为"},
    "category.fade":             {"EN": "Fade",              "ZH": "淡出"},
    "category.fluid":            {"EN": "Fluid",             "ZH": "流体"},
    "category.vortexel":         {"EN": "Vortexel",          "ZH": "涡元"},
    "category.field":            {"EN": "Field",             "ZH": "场"},
    "category.basic":            {"EN": "Basic",             "ZH": "基础"},
    "category.misc":             {"EN": "Misc",              "ZH": "杂项"},

    # 材质参数覆盖表（TypeMesh 系列 attribute 的 properties）
    "mdf.add_property":       {"EN": "Add from Material",   "ZH": "从材质添加"},
    "mdf.no_material_path":   {"EN": "(no material path)",  "ZH": "（没有材质路径）"},
    "mdf.load_reference":     {"EN": "Load Reference .mdf2", "ZH": "载入参考 .mdf2"},
    "mdf.unknown_shape":      {"EN": "(expand to edit)",     "ZH": "（展开编辑）"},
    "mdf.mismatch_count":     {"EN": "{0} not in the reference material",
                               "ZH": "{0} 条和参考材质对不上"},

    # 重命名
    "name.label":             {"EN": "Name",                "ZH": "名称"},
    "name.hint":              {"EN": "Written to the EFX string table; nameHash follows automatically.",
                               "ZH": "写进 EFX 字符串表，nameHash 会自动跟着重算。"},

    # Edit（复制/粘贴这类工具操作）
    "edit.copy_object":       {"EN": "Copy Object",         "ZH": "复制对象"},
    "edit.paste_object":      {"EN": "Paste Object",        "ZH": "粘贴对象"},
    "edit.copy_properties":   {"EN": "Copy Properties",     "ZH": "复制属性"},
    "edit.paste_properties":  {"EN": "Paste Properties",    "ZH": "粘贴属性"},
    "edit.clipboard_prefix":  {"EN": "Clipboard: ",         "ZH": "剪贴板："},
    "edit.clipboard_empty":   {"EN": "(empty)",             "ZH": "（空）"},

    # 校验
    "validate.ok":            {"EN": "No problems found.",  "ZH": "没有发现问题。"},
    "validate.no_root":       {"EN": "No active EFX. Import a file or pick one in Active EFX.",
                               "ZH": "没有当前 EFX——先导入一个文件，或在「当前 EFX」里选一个。"},

    # MHWilds UVS 标签页
    "uvs.new":                 {"EN": "New UVS",             "ZH": "新建 UVS"},
    "uvs.import":             {"EN": "Import UVS",          "ZH": "导入 UVS"},
    "uvs.export":              {"EN": "Export UVS",          "ZH": "导出 UVS"},
    "uvs.active_uvs":          {"EN": "Active UVS",          "ZH": "当前 UVS"},
    "uvs.patterns":            {"EN": "Patterns",            "ZH": "Pattern 列表"},
    "uvs.generate_grid":       {"EN": "Generate Grid",       "ZH": "生成网格"},
    "uvs.texture_index_out_of_range": {
        "EN": "Texture index out of range", "ZH": "贴图下标越界",
    },
    "uvs.texture_handles_hint": {
        "EN": "Runtime handles, unknown meaning, preserved as-is",
        "ZH": "运行时句柄，语义未知，原样保留",
    },
    "uvs.advanced_edit":       {"EN": "Advanced Edit",       "ZH": "进阶编辑"},
    "uvs.advanced_edit_hint":  {
        "EN": "border visualization and cutout editing are in Advanced Edit",
        "ZH": "边框可视化和裁剪编辑需要在「进阶编辑」里设置",
    },
    "uvs.exit_advanced_edit":  {"EN": "Exit Advanced Edit",  "ZH": "退出进阶编辑"},
    "uvs.sequences":           {"EN": "Sequences",           "ZH": "Sequence 列表"},
    "uvs.textures":            {"EN": "Textures",            "ZH": "贴图列表"},
    "uvs.flags":               {"EN": "Flags",               "ZH": "标志位"},
    "uvs.gif_to_sequence":     {"EN": "GIF to Sequence",     "ZH": "GIF 转序列"},
    "uvs.need_pillow":         {"EN": "Pillow library required", "ZH": "需要 Pillow 库"},

    # Asset Browser（attribute 反查资产库）
    "asset.corpus_dir":       {"EN": "EFX Root Directory",  "ZH": "EFX 根目录"},
    "asset.rebuild_index":    {"EN": "Rebuild Index",       "ZH": "重建索引"},
    "asset.not_built":        {"EN": "(index not built — set an EFX root directory and rebuild)",
                               "ZH": "（索引尚未建立——设置 EFX 根目录后点重建）"},
    "asset.stats_prefix":     {"EN": "Indexed: ",           "ZH": "已索引："},
    "asset.types_suffix":     {"EN": "types",               "ZH": "种类型"},
    "asset.pick_type":        {"EN": "Pick Type",           "ZH": "选择类型"},
    "asset.no_type_selected": {"EN": "(no type selected)",  "ZH": "（未选择类型）"},
    "asset.no_types_in_category": {"EN": "(no indexed types in this category)",
                               "ZH": "（该分类下没有已索引的类型）"},
    "asset.no_matches":       {"EN": "(no files contain this type)",
                               "ZH": "（没有文件包含这个类型）"},
    "asset.import_selected":  {"EN": "Import Selected",     "ZH": "导入选中项"},

    # File > Import / Export 菜单（file_menu.py）
    "filemenu.efx":      {"EN": "MHWs Effect (.efx)",             "ZH": "MHWs 特效 (.efx)"},
    "filemenu.uvs":       {"EN": "MHWs UV Sequence (.uvs)",        "ZH": "MHWs UV 序列 (.uvs)"},
    "filemenu.vecfield":  {"EN": "MHWs Vector Field (.tex)",       "ZH": "MHWs 向量场 (.tex)"},
}


_CLASSES = (EFX_RE_OT_set_language,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
