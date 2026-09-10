"""
blender_efx_re/asset_browser.py —— Attribute 反查资产库

用 `asset_index.py`（配套 `EfxBridge attrindex` 子命令）建好的"类型 -> 出现过它的文件"反查
索引，做成一个类似 asset library 的工具面板：设定语料路径 -> 建索引 -> 按分类筛选或直接搜索
一个 attribute 类型 -> 内嵌列表出命中的文件 -> 选中直接导入。只做文件级命中，不做 entry 级
定位（用途是"找一个带这个 attr 的参考文件"，不是"精确定位第几个 entry"）。

交互照抄 `panels.py` 的 `_draw_add_attribute_tab`/`EFX_RE_MT_attribute_type_picker`
（分类下拉 + 点选即生效的菜单 + 模糊搜索弹窗），但这里点选/搜索只是"定位"，不新增任何东西。

面板是独立工具面板（跟 `EFX_RE_PT_add` 同类，不挂在某个 `~TYPE` 对象上），排在 "Wilds EFX"
分组最下面——找参考文件是相对少用的辅助功能，不需要占据显眼位置。
"""

from __future__ import annotations

import os

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from . import asset_index, attribute_types, bridge
from .i18n import T
from .panels import _CATEGORY, _attr_type_label


# ---------------------------------------------------------------------------
# 数据（都挂在 WindowManager 上——纯界面临时状态，不该随 .blend 走，理由同
# panels.py 的 efx_re_attr_category）
# ---------------------------------------------------------------------------

class EFXAssetMatchItem(PropertyGroup):
    """反查列表里的一条命中，纯展示用。"""

    filepath: StringProperty(name="File Path", subtype="FILE_PATH")


def _refresh_matches(wm) -> None:
    """按当前选中的 efx_re_asset_attr_type 重新拉一遍命中文件，填进 efx_re_asset_matches。"""
    wm.efx_re_asset_matches.clear()
    wm.efx_re_asset_matches_active_index = 0
    type_name = wm.efx_re_asset_attr_type
    if not type_name:
        return
    for path in asset_index.files_for_type(type_name):
        item = wm.efx_re_asset_matches.add()
        item.filepath = path


def _on_corpus_dir_update(self, context) -> None:
    asset_index.set_corpus_dir(self.efx_re_asset_corpus_dir)


def _on_attr_type_update(self, context) -> None:
    _refresh_matches(context.window_manager)


# ---------------------------------------------------------------------------
# 类型搜索 / 分类点选——只对已建索引里实际出现过的类型生效，语料里从没出现过的类型
# 搜出来/列出来也是死路
# ---------------------------------------------------------------------------

# EnumProperty 的 items 回调必须自己持有返回的列表（Blender 只存字符串指针，临时对象被
# Python 回收后界面显示乱码），做法照抄 attribute_types._enum_items_cache。只用裸类型名、
# 不查语义表中文名——items 缓存跟不上语言切换，中文名放在选中之后的正文标签里显示
# （那里是 Panel.draw()，每次打开都会重新画，不存在这个缓存陈旧问题）。
_search_items_cache: list | None = None


def invalidate_search_cache() -> None:
    """索引重建之后调用，逼下次打开搜索弹窗时重新读一遍 known_types()。"""
    global _search_items_cache
    _search_items_cache = None


def _search_type_items(self, context):
    global _search_items_cache
    if _search_items_cache is None:
        types = asset_index.known_types()
        _search_items_cache = (
            [(name, name, "") for name in types]
            if types else [("", "", "")]
        )
    return _search_items_cache


class EFX_RE_OT_asset_type_search(Operator):
    """按名字模糊搜索已建索引的 attribute 类型，选中即定位（不新增任何东西）。"""

    bl_idname = "efx_re.asset_type_search"
    bl_label = "Search Indexed Attribute Type"
    bl_description = "按名字模糊搜索已建索引的 attribute 类型，选中即定位"
    bl_options = {"REGISTER"}
    bl_property = "attr_type"

    attr_type: EnumProperty(name="Type", items=_search_type_items)

    @classmethod
    def poll(cls, context):
        return asset_index.is_built()

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.window_manager.efx_re_asset_attr_type = self.attr_type
        return {"FINISHED"}


class EFX_RE_OT_asset_type_pick(Operator):
    """分类菜单点选算子：设置当前反查类型，不新增任何东西。"""

    bl_idname = "efx_re.asset_type_pick"
    bl_label = "Pick Attribute Type"
    bl_description = "选中这个类型，下方列出语料里包含它的文件"
    bl_options = {"REGISTER"}

    attr_type: StringProperty()

    def execute(self, context):
        context.window_manager.efx_re_asset_attr_type = self.attr_type
        return {"FINISHED"}


class EFX_RE_MT_asset_type_picker(Menu):
    """按分类过滤，点一行直接定位到对应类型——过滤依据是索引里实际出现过的类型
    （`asset_index.known_types()`），不是 attribute_types.readable_types() 的"能新建"
    口径：这里是浏览已有语料，跟"能不能凭空新建一个空白实例"是两回事。"""

    bl_idname = "EFX_RE_MT_asset_type_picker"
    bl_label = "Attribute Type"

    def draw(self, context):
        layout = self.layout
        category = getattr(context.window_manager, "efx_re_asset_type_category", "ALL")
        names = []
        for name in asset_index.known_types():
            item = attribute_types.by_name(name)
            cat = (item.get("category") or "misc") if item else "misc"
            if category != "ALL" and cat != category:
                continue
            names.append(name)

        if not names:
            layout.label(text=T("asset.no_types_in_category"), translate=False)
            return
        for name in names:  # known_types() 本身已按字母排序
            item = attribute_types.by_name(name)
            label = _attr_type_label(item["type"]) if item and item.get("type") else name
            op = layout.operator("efx_re.asset_type_pick", text=label, translate=False)
            op.attr_type = name


# ---------------------------------------------------------------------------
# 重建索引 / 导入选中项
# ---------------------------------------------------------------------------

class EFX_RE_OT_asset_index_rebuild(Operator):
    """扫一遍 EFX 根目录，重建 attribute 反查索引。"""

    bl_idname = "efx_re.asset_index_rebuild"
    bl_label = "Rebuild Attribute Index"
    bl_description = "扫一遍 EFX 根目录，重建 attribute 反查索引；文件较多时可能需要几分钟"
    bl_options = {"REGISTER"}

    def execute(self, context):
        wm = context.window_manager
        corpus_dir = wm.efx_re_asset_corpus_dir.strip()
        if not corpus_dir or not os.path.isdir(corpus_dir):
            self.report({"ERROR"}, "EFX 根目录不存在，请先设置一个有效的目录")
            return {"CANCELLED"}

        window = context.window
        window.cursor_set("WAIT")
        try:
            envelope = asset_index.build_index(corpus_dir)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"索引重建失败：{str(ex).strip().split(chr(10))[0]}")
            return {"CANCELLED"}
        finally:
            window.cursor_set("DEFAULT")

        invalidate_search_cache()
        _refresh_matches(wm)  # 当前选中的类型如果还在新索引里，命中列表跟着刷新
        self.report(
            {"INFO"},
            f"已扫描 {envelope.get('filesScanned', 0)}/{envelope.get('filesTotal', 0)} 个文件，"
            f"{len(envelope.get('types', {}))} 种类型",
        )
        return {"FINISHED"}


class EFX_RE_OT_asset_import_selected(Operator):
    """把反查列表里当前选中的文件转调 efx_re.import 导入，不重复写一遍导入逻辑。"""

    bl_idname = "efx_re.asset_import_selected"
    bl_label = "Import Selected Asset"
    bl_description = "导入反查列表里当前选中的文件"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        idx = wm.efx_re_asset_matches_active_index
        return 0 <= idx < len(wm.efx_re_asset_matches)

    def execute(self, context):
        wm = context.window_manager
        item = wm.efx_re_asset_matches[wm.efx_re_asset_matches_active_index]
        # "import" 是 Python 关键字，不能写成 bpy.ops.efx_re.import(...)，同 tools/verify_ui.py
        # 的做法用 getattr 绕过。
        return getattr(bpy.ops.efx_re, "import")(filepath=item.filepath)


# ---------------------------------------------------------------------------
# UIList + Panel
# ---------------------------------------------------------------------------

class EFX_RE_UL_asset_matches(UIList):
    bl_idname = "EFX_RE_UL_asset_matches"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=os.path.basename(item.filepath), icon="FILE", translate=False)


class EFX_RE_PT_asset_browser(Panel):
    """工具面板：按 attribute 类型反查语料里的文件，选中直接导入。"""

    bl_idname = "EFX_RE_PT_asset_browser"
    bl_label = "Asset Browser"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    # 显式设成比现有面板最大值（Attribute 面板的 2）更大，保证排到 "Wilds EFX" 分组最下面——
    # Clip/Expression/Fields 已经占了默认值 0，留空/用 0 排不到最后（见 panels.py:13 的说明）。
    bl_order = 5
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        layout.prop(wm, "efx_re_asset_corpus_dir", text=T("asset.corpus_dir"))
        layout.operator(
            "efx_re.asset_index_rebuild", icon="FILE_REFRESH",
            text=T("asset.rebuild_index"), translate=False,
        )

        info = asset_index.stats()
        stat_row = layout.row()
        stat_row.enabled = False
        if info is None:
            stat_row.label(text=T("asset.not_built"), translate=False)
        else:
            stat_row.label(
                text=(
                    f"{T('asset.stats_prefix')}{info['filesScanned']}/{info['filesTotal']} "
                    f"{T('common.items_suffix')}, {info['typeCount']} "
                    f"{T('asset.types_suffix')}"
                ),
                translate=False,
            )

        layout.separator()
        layout.operator(
            "efx_re.asset_type_search", text=T("add.search_attribute"),
            icon="VIEWZOOM", translate=False,
        )
        layout.prop(wm, "efx_re_asset_type_category", text=T("add.category"))
        layout.menu(
            "EFX_RE_MT_asset_type_picker", text=T("asset.pick_type"),
            icon="DOWNARROW_HLT", translate=False,
        )

        type_name = wm.efx_re_asset_attr_type
        sel_row = layout.row()
        if type_name:
            item = attribute_types.by_name(type_name)
            label = _attr_type_label(item["type"]) if item and item.get("type") else type_name
            sel_row.label(text=label, icon="CHECKMARK", translate=False)
        else:
            sel_row.label(text=T("asset.no_type_selected"), translate=False)

        layout.template_list(
            "EFX_RE_UL_asset_matches", "", wm, "efx_re_asset_matches",
            wm, "efx_re_asset_matches_active_index", rows=6,
        )
        if type_name and not wm.efx_re_asset_matches:
            box = layout.box()
            box.label(text=T("asset.no_matches"), translate=False)

        layout.operator(
            "efx_re.asset_import_selected", icon="IMPORT",
            text=T("asset.import_selected"), translate=False,
        )


_CLASSES = (
    EFXAssetMatchItem,
    EFX_RE_UL_asset_matches,
    EFX_RE_OT_asset_type_search,
    EFX_RE_OT_asset_type_pick,
    EFX_RE_MT_asset_type_picker,
    EFX_RE_OT_asset_index_rebuild,
    EFX_RE_OT_asset_import_selected,
    EFX_RE_PT_asset_browser,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.efx_re_asset_corpus_dir = StringProperty(
        name="EFX Root Directory",
        description="要建反查索引的 EFX 根目录",
        subtype="DIR_PATH",
        default=asset_index.get_corpus_dir(),
        update=_on_corpus_dir_update,
    )
    bpy.types.WindowManager.efx_re_asset_type_category = EnumProperty(
        name="Category",
        description="按来源文件分组过滤 attribute 类型",
        items=attribute_types.category_items,
    )
    bpy.types.WindowManager.efx_re_asset_attr_type = StringProperty(
        name="Type",
        description="当前反查的 attribute 类型",
        update=_on_attr_type_update,
    )
    bpy.types.WindowManager.efx_re_asset_matches = CollectionProperty(type=EFXAssetMatchItem)
    bpy.types.WindowManager.efx_re_asset_matches_active_index = IntProperty()


def unregister():
    for prop in (
        "efx_re_asset_matches_active_index", "efx_re_asset_matches",
        "efx_re_asset_attr_type", "efx_re_asset_type_category", "efx_re_asset_corpus_dir",
    ):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
