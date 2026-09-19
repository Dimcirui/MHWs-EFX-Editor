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
    "main.armature":          {"EN": "Armature",            "ZH": "骨架"},
    "main.sync_bone":         {"EN": "Sync Bone Binding",   "ZH": "刷新骨骼绑定"},
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
    "attribute.half_open_empty_warning": {
        "EN": "Max is exclusive — Max == Min selects nothing, use Min + 1",
        "ZH": "Max 取不到——Max == Min 等于一个都不选，要填 Min + 1",
    },
    "attribute.show_all_fields": {"EN": "Show all fields", "ZH": "显示全部字段"},
    "attribute.bit_field":    {"EN": "Field",              "ZH": "字段"},
    "attribute.no_free_bits": {"EN": "No free bits left",  "ZH": "没有空闲的 bit 了"},
    "attribute.clip_edit_hint": {
        "EN": "Edit this curve's keyframes in the Dope Sheet / Graph Editor "
              "(select this object, insert/move keyframes there — changes are live).",
        "ZH": "在 Dope Sheet / Graph Editor 里编辑这条曲线的关键帧（选中这个对象，直接插入/"
              "拖动关键帧——改动即时生效）。",
    },
    "attribute.clip_interp_unverified": {
        "EN": "Import accepts most raw types (real files only ever use Discrete/Linear/Event/"
              "Hermite, but a few placeholder types import too) — you can freely change any "
              "keyframe's interpolation after import. Only Constant/Linear/Bezier can be "
              "exported though; anything else (including Event's placeholder \"Sine\" label) "
              "must be changed to one of those three first. Blender's own \"Bezier\" label "
              "here is really Hermite (tangents are /3-converted) — not literal Bezier; "
              "Blender has no separate Hermite identifier so this is the closest native fit.",
        "ZH": "导入接受大部分原始类型（真实文件只会用到 Discrete/Linear/Event/Hermite，但少数"
              "占位类型也能导入）——导入后可以在原生下拉框里随意改任何关键帧的插值。不过只有 "
              "Constant/Linear/Bezier 能导出，其它的（包括 Event 借用的\"正弦\"占位名字）都要"
              "先改成这三种之一才能导出。这里 Blender 自己显示的\"Bezier\"其实是 Hermite（切线"
              "已按 ÷3 换算），不是字面贝塞尔——Blender 没有单独的 Hermite 标识符，借用这个名字"
              "只是最接近的原生选项。",
    },
    "attribute.clip_select_special": {
        "EN": "Select Event/Hermite Keyframes",
        "ZH": "选中 Event/Hermite 关键帧",
    },
    "attribute.clip_xform_channel": {
        "EN": "Keyframes for this curve live on the parent object's native transform "
              "(select it in the Dope Sheet, not this attribute):",
        "ZH": "这条曲线的关键帧挂在父对象的原生变换上（去 Dope Sheet 里选它，不是选这个"
              "attribute）：",
    },

    # Expression 公式的结构化编辑（blender_efx_re/expr_edit.py）
    "expr.structure":         {"EN": "Structure",           "ZH": "结构"},
    "expr.raw_text":          {"EN": "Formula text",        "ZH": "公式文本"},
    "expr.unknown_var":       {"EN": "Unknown variable (reads as 0)",
                               "ZH": "未知变量（按 0 求值）"},
    "expr.reparse":           {"EN": "Reparse from text",   "ZH": "按文本重新解析"},
    "expr.no_rows":           {"EN": "No structure view for this formula yet.",
                               "ZH": "这条公式还没有结构视图。"},
    "expr.second_branch":     {"EN": "Second root value (kept as-is, not editable here)",
                               "ZH": "第二根值（原样保留，这里不编辑）"},
    # 槽位设计的文案。措辞演进：「换成/包一层/提一层」-> 「替换/内嵌/删除」->
    # 现在只剩「槽位类型」这一个入口（选常量/变量/表达式）+ 该类型的具体值。
    # 「内嵌」不再是独立操作——把槽位类型切成表达式时原内容自动成为第一个参数。
    # 「删除这一层」保留：它和"切成变量/常量"不是一回事（后者丢掉整棵子树）。
    "expr.slot.kind":         {"EN": "Slot",                "ZH": "槽位类型"},
    "expr.slot.value":        {"EN": "Value",               "ZH": "常量值"},
    "expr.slot.var":          {"EN": "Pick variable",       "ZH": "挑一个变量"},
    "expr.slot.func":         {"EN": "Function",            "ZH": "函数类型"},
    "expr.slot.delete_layer": {"EN": "Drop this layer",     "ZH": "删除这一层"},
    "expr.kind.const":        {"EN": "Constant",            "ZH": "常量"},
    "expr.kind.var":          {"EN": "Variable",            "ZH": "变量"},
    "expr.kind.expr":         {"EN": "Expression",          "ZH": "表达式"},
    "expr.wrap.negate":       {"EN": "Negate",              "ZH": "取负"},
    "expr.op.desc":           {"EN": "Arithmetic operator", "ZH": "四则运算"},
    # 三档的措辞一律写**未知状态本身**，不写验证状态（docs/PITFALLS.md #25：不写"尚未实机确认"
    # 这类出处/过程；出处在 efx_sim/expr.py 的模块 docstring 里）
    "expr.conf.confirmed":    {"EN": "Known meaning",       "ZH": "语义明确"},
    "expr.conf.corpus":       {"EN": "Meaning inferred",    "ZH": "语义为推断"},
    "expr.conf.undecided":    {"EN": "Reading undecided",   "ZH": "读法未定"},
    "expr.conf.unknown":      {"EN": "Meaning unknown",     "ZH": "语义未知"},
    "expr.preview":           {"EN": "Value at current frame", "ZH": "当前帧的值"},
    "expr.preview.failed":    {"EN": "cannot evaluate",     "ZH": "算不出来"},
    "expr.preview.frames":    {"EN": "Frames",              "ZH": "采样帧数"},
    "expr.preview.notes_disclaimer": {
        "EN": "Below only affects this preview, not the exported formula",
        "ZH": "以下提示只影响这里的预览，不影响导出的公式文本"},
    "expr.hud.toggle":        {"EN": "Curve in viewport",   "ZH": "视口显示曲线"},
    "expr.hud.gaps":          {"EN": "%d frames cannot be evaluated (line is broken there)",
                               "ZH": "%d 帧算不出来（曲线在那里断开）"},
    # 节点视口
    "exprnode.open":          {"EN": "Edit in node editor", "ZH": "在节点编辑器里编辑"},
    "exprnode.unbound":       {"EN": "No formula bound. Open one from the Expression panel.",
                               "ZH": "还没绑定公式。从 Expression 面板点「在节点编辑器里编辑」。"},
    "exprnode.rejected":      {"EN": "This edit was rejected, the formula is unchanged",
                               "ZH": "这次改动没被接受，公式没有变"},
    "expr.var.file_params":   {"EN": "This file's parameters", "ZH": "本文件的具名参数"},
    "expr.var.builtins":      {"EN": "Built-in variables",  "ZH": "内置变量"},
    "expr.note.unknown_func": {
        "EN": "This formula uses functions whose meaning is unknown.",
        "ZH": "这条公式用到了语义未知的函数。",
    },

    # IMaterialExpressionAttribute 的公式列表（blender_efx_re/panels.py _draw_material_expression_content）
    "matexpr.none":           {"EN": "No material expressions.", "ZH": "没有材质参数公式。"},
    "matexpr.component":      {"EN": "Component",          "ZH": "分量下标"},

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

    # PtBehavior 属性候选目录
    "ptbehavior.add_property": {"EN": "Add from Catalog",  "ZH": "从候选目录添加"},
    "ptbehavior.add_all_properties": {"EN": "Add All",     "ZH": "全部添加"},
    "ptbehavior.unknown_shape": {"EN": "(unknown data type, expand to inspect)",
                                  "ZH": "（未知数据类型，展开查看）"},
    "ptbehavior.obb_hint": {"EN": "(T/R/S below)", "ZH": "（T/R/S 见下方）"},

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

    # 插件首选项（Edit > Preferences > Add-ons）
    "prefs.bypass_bone": {
        "EN": "Bypass bone binding alignment check",
        "ZH": "绕过骨骼绑定索引对齐校验",
    },
    "prefs.bypass_bone_warn": {
        "EN": "Bypassing lets files with a mismatched bone binding table be imported and "
              "exported. Their bindings may already be shifted, and export silently drops slots.",
        "ZH": "绕过之后，骨骼绑定索引对不上的文件也能导入和导出。这类文件的绑定可能已经错位，"
              "导出还会静默丢掉绑定槽位。",
    },

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
    "asset.behaviors_suffix": {"EN": "PtBehavior classes",  "ZH": "种 PtBehavior"},
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


def add_strings(mapping: dict) -> None:
    """往文案表里补一批词条（给独立子模块用，避免所有词条都堆在这个文件里）。

    重名直接覆盖并不报错——同一个 key 在两处定义本来就是 bug，但界面文案不值得为它
    拖垮加载；真撞了会在界面上看到后注册的那份，比抛异常让整个插件装不上强。
    """
    _STRINGS.update(mapping)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
