"""
blender_efx_re/structure_ops.py —— 新增 / 删除 Entry、Action、Attribute

这是 C 层的核心：上一版插件**完全没有结构编辑能力**，只能导入现成文件改字段，连"新建一个
Entry"都做不到。

空白对象不是我们攒的模板，是 C# 侧 `new` 出来的真实实例（见 bridge.new_*）——每个 attribute
类型在 vendor 里都是一个具体的 C# 类，new 出来就带正确的字段结构，序列化规则和 dump 完全一致，
直接喂给现成的 `io_tree.build_*_object()` 就行。姊妹项目 EFX-Editor 需要一整套预设文件来做
同一件事，是因为它没有类型化对象模型。

`add_attribute()` 在 `bridge.new_attribute()` 的零值结构上再合并一层 `semantics.
get_attribute_defaults()`——全语料众数统计出来的"合理默认值"（`tools/build_attr_defaults.py`），
只覆盖置信度够高的字段，目前覆盖语料里最常见的 40 种 attribute 类型（见
`tools/typefreq_report.json`）。没覆盖到的类型/字段照样是 vendor 零值。

两条硬约束：

1. **Attribute 在 entry 内必须按 itemTypeId 升序**。`EFXEntry.DoRead` 有
   `typeId < lastAttributeTypeId` 的断言，而 `DoWrite` 只是按列表顺序写、**不会替我们排**
   （`EFXEntryBase.ReorderEntries()` 存在但写出路径没人调它）。所以新增时必须插到正确位置，
   见 `sorted_insert_index()`。也正因为顺序是被 itemTypeId 定死的，这里**不提供**手动上移/
   下移 attribute 的操作——那种交互在这个格式里根本不成立。
2. **不做整层级联删除**。架构决策 5 定了：整棵子树的删除引导用户用 Blender 原生 Outliner 的
   "Delete Hierarchy"（天然递归，不需要我们自己写）。这里的删除只处理"删一个 Entry/Action/
   Attribute 及其子对象"这种明确范围，并且拒绝删 EFX_ROOT。
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Object, Operator
from bpy_extras.io_utils import ImportHelper

from . import attribute_types, bridge, io_tree, mdf_catalog, model, semantics

# 能承载 attribute 的父类型
_ATTRIBUTE_PARENTS = (model.TYPE_ENTRY, model.TYPE_ACTION)

# 新 Entry 该有的基本骨架，写死在代码里的唯一一份——vendor 格式本身不要求任何 attribute 组合
# （EFXEntryBase.AddAttribute 只挡重复 Type*/孤儿 Expression 这类局部约束，不检查"entry 必须有
# 什么"），这纯粹是"空白 Entry 在实践里几乎总要手动补这四个，干脆新建时就带上"的经验性约定。
# 只有 EFX_RE_OT_entry_add 用，不提供"给已存在 Entry 补齐"的入口——那属于用户自定义预设系统
# （entry_presets.py）的地盘，不在这个写死列表的范围内。
ENTRY_BASIC_PRESET_ATTRS = ("Transform3D", "Spawn", "Life", "ParentOptions")


def _renumber(siblings: list[Object]) -> None:
    """按当前列表顺序把 efx_index 重排成 0..n-1。导出顺序只看 efx_index，不看 Blender 自己的
    children 迭代顺序（见 io_tree.typed_children）。

    顺手对 Entry 刷新一遍显示名（`refresh_entry_display_name()` 对非 Entry 直接 no-op，不用
    先判断 `siblings` 装的是哪种类型）——序号一变，名字里那个 `[{efx_index:03d}] ` 前缀就跟着
    过时了，不刷新的话 Outliner 顺序会跟真实的 efx_index 对不上，等于白加了这个前缀。
    """
    for i, obj in enumerate(siblings):
        obj.efx_index = i
        model.refresh_entry_display_name(obj)


def sorted_insert_index(parent_obj: Object, item_type_id: int) -> int:
    """新 attribute 该插在第几位：按 itemTypeId 升序找第一个比它大的位置。

    相同 itemTypeId 的插在同类的最后（稳定插入，不打乱已有同类之间的相对顺序）。
    查不到 itemTypeId 的既有 attribute 当作 -1，排在最前——这种情况只会出现在类型清单和
    实际文件对不上时，让它靠前总比插到未知位置安全。
    """
    existing = io_tree.typed_children(parent_obj, model.TYPE_ATTRIBUTE)
    for i, obj in enumerate(existing):
        other = attribute_types.item_type_id(obj.efx_attr_type)
        if other is None:
            continue
        if other > item_type_id:
            return i
    return len(existing)


def _resolve_attribute_parent(context) -> Object | None:
    """新 attribute 挂到哪：选中 Entry/Action 就是它；选中 Attribute 就是它的父对象
    （连续新增免得每次切回父级，同姊妹项目的做法）。"""
    obj = getattr(context, "object", None)
    if obj is None:
        return None
    tag = obj.get("~TYPE")
    if tag in _ATTRIBUTE_PARENTS:
        return obj
    if tag == model.TYPE_ATTRIBUTE:
        parent = obj.parent
        if parent is not None and parent.get("~TYPE") in _ATTRIBUTE_PARENTS:
            return parent
    return None


def _remove_collection_tree(col) -> None:
    """递归删掉一个集合及其子集合里剩下的对象和集合本身。删嵌套 efxrData 根时用。"""
    if col is None:
        return
    for child in list(col.children):
        _remove_collection_tree(child)
    for obj in list(col.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.data.collections.remove(col)
    except Exception:
        pass


def _activate(context, obj: Object) -> None:
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _merge_suggested_defaults(base: dict, overlay: dict) -> None:
    """把语料众数默认值（overlay）原地合并进 `bridge.new_attribute()` 吐出来的零值结构（base）。

    只覆盖 overlay 里实际出现的叶子字段——overlay 本来就已经把置信度不够的字段剔掉了
    （见 tools/build_attr_defaults.py），没出现的字段照样保留 vendor 的零值，不是这份表
    没考虑到，是统计上没有把握替 Capcom 猜。
    """
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_suggested_defaults(base[key], value)
        else:
            base[key] = value


def add_attribute(parent_obj: Object, attr_name: str) -> Object:
    """给 parent_obj（Entry/Action）新增一个 attr_name 类型的 attribute，插到 itemTypeId 排序
    位，返回新建的 Object。`EFX_RE_OT_attribute_add`、`EFX_RE_OT_entry_add` 的自动套预设、
    `EFX_RE_OT_apply_basic_preset` 共用这份逻辑，不各写一份。

    类型清单里没有 `attr_name` 时抛 `KeyError`；C# 侧新建失败时抛 `bridge.BridgeError`——两种
    都不在这里 catch，调用方各自决定怎么报错（单独新增一个 vs 批量套预设时某一个失败要不要
    影响其它几个）。
    """
    info = attribute_types.by_name(attr_name)
    if info is None:
        raise KeyError(f"类型清单里没有 '{attr_name}'")

    data = bridge.new_attribute(attr_name)
    defaults = semantics.get_attribute_defaults(attr_name)
    if defaults:
        _merge_suggested_defaults(data, defaults)

    siblings = io_tree.typed_children(parent_obj, model.TYPE_ATTRIBUTE)
    insert_at = sorted_insert_index(parent_obj, info["itemTypeId"])
    collection = parent_obj.users_collection[0]
    # 先按末位建出来，再挪到排序位上重排 efx_index——build_attribute_object 只认
    # "建在哪个 collection、挂在哪个 parent"，插入位置是我们这边的事。
    new_obj = io_tree.build_attribute_object(data, len(siblings), parent_obj, collection)
    ordered = siblings[:insert_at] + [new_obj] + siblings[insert_at:]
    _renumber(ordered)
    # 新增的这个 attribute 如果是 TypeAttribute 或 PtLife/PtColliderAction，父 Entry 的显示名
    # 后缀要跟着更新——no-op（对 Action 或没起名的 Entry）由函数自己判断，调用方不用先分辨。
    model.refresh_entry_display_name(parent_obj)
    return new_obj


class EFX_RE_OT_entry_add(Operator):
    """在当前 EFX 树里新增一个 Entry（追加到末尾），自动带上基础预设
    （`ENTRY_BASIC_PRESET_ATTRS`：Transform3D + Spawn + Life + ParentOptions）——空白 Entry
    没有任何 attribute 没法用，让用户每次手动补这四个纯粹是重复劳动。
    """

    bl_idname = "efx_re.entry_add"
    bl_label = "Add Entry"
    bl_description = "在当前 EFX 树末尾新增一个 Entry，自动带上 Transform3D / Spawn / Life / ParentOptions 四个基础 attribute"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def execute(self, context):
        root_col = io_tree.resolve_root(context)
        if root_col is None:
            self.report({"ERROR"}, "没有当前 EFX——先导入一个文件，或在「当前 EFX」里选一个")
            return {"CANCELLED"}
        try:
            data = bridge.new_entry()
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"新建 Entry 失败：\n{ex}")
            return {"CANCELLED"}

        entries_collection, _ = io_tree.root_collections(root_col)
        siblings = io_tree.root_entries(root_col)
        data["name"] = f"Entry_{len(siblings)}"
        new_obj = io_tree.build_entry_object(data, len(siblings), entries_collection)
        _renumber(siblings + [new_obj])

        failed = []
        for attr_name in ENTRY_BASIC_PRESET_ATTRS:
            try:
                add_attribute(new_obj, attr_name)
            except (bridge.BridgeError, KeyError):
                failed.append(attr_name)

        _activate(context, new_obj)
        if failed:
            self.report(
                {"WARNING"},
                f"已新增 Entry '{new_obj.name}'，但基础预设里的 {failed} 没加上",
            )
        else:
            self.report({"INFO"}, f"已新增 Entry '{new_obj.name}'（已带基础预设）")
        return {"FINISHED"}


class EFX_RE_OT_action_add(Operator):
    """在当前 EFX 树里新增一个空 Action（追加到末尾）"""

    bl_idname = "efx_re.action_add"
    bl_label = "Add Action"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def execute(self, context):
        root_col = io_tree.resolve_root(context)
        if root_col is None:
            self.report({"ERROR"}, "没有当前 EFX——先导入一个文件，或在「当前 EFX」里选一个")
            return {"CANCELLED"}
        try:
            data = bridge.new_action()
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"新建 Action 失败：\n{ex}")
            return {"CANCELLED"}

        _, actions_collection = io_tree.root_collections(root_col)
        siblings = io_tree.root_actions(root_col)
        data["name"] = f"Action_{len(siblings)}"
        new_obj = io_tree.build_action_object(data, len(siblings), actions_collection)
        _renumber(siblings + [new_obj])
        _activate(context, new_obj)
        self.report({"INFO"}, f"已新增 Action '{new_obj.name}'")
        return {"FINISHED"}


class EFX_RE_OT_attribute_add(Operator):
    """给当前 Entry/Action 新增一个指定类型的空 Attribute，插到 itemTypeId 排序位"""

    bl_idname = "efx_re.attribute_add"
    bl_label = "Add Attribute"
    bl_description = "给当前 Entry/Action 新增一个指定类型的空 Attribute，按类型顺序插入"
    bl_options = {"REGISTER", "UNDO"}

    attr_type: EnumProperty(
        name="Type",
        description="要新增的 attribute 类型",
        items=attribute_types.enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _resolve_attribute_parent(context) is not None

    def execute(self, context):
        parent_obj = _resolve_attribute_parent(context)
        if parent_obj is None:
            self.report({"ERROR"}, "先选中一个 Entry 或 Action（选中它下面的 Attribute 也行）")
            return {"CANCELLED"}

        info = attribute_types.by_name(self.attr_type)
        if info is None:
            self.report({"ERROR"}, f"类型清单里没有 '{self.attr_type}'")
            return {"CANCELLED"}

        try:
            new_obj = add_attribute(parent_obj, self.attr_type)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"新建 Attribute 失败：\n{ex}")
            return {"CANCELLED"}

        _activate(context, new_obj)
        self.report({"INFO"}, f"已新增 {self.attr_type}（itemTypeId {info['itemTypeId']}）")
        return {"FINISHED"}


class EFX_RE_OT_attribute_add_search(Operator):
    """按名字模糊搜索 attribute 类型并直接新增，不用先猜它归在哪个分类。

    ~150+ 种类型分类浏览效率太低——这里走 Blender 原生的
    `WindowManager.invoke_search_popup()`（键盘打字模糊过滤，官方文档"Enum Search Popup"
    那个标准写法），条目用 `attribute_types.all_enum_items()`（不受分类下拉过滤，覆盖全部
    类型）。选中之后不重复一遍新增逻辑，直接转调 `efx_re.attribute_add`，同一份
    `add_attribute()` 只写一次。"""

    bl_idname = "efx_re.attribute_add_search"
    bl_label = "Search Attribute Type"
    bl_description = "按名字模糊搜索 attribute 类型，选中即新增"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "attr_type"

    attr_type: EnumProperty(
        name="Type",
        description="要新增的 attribute 类型",
        items=attribute_types.all_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return _resolve_attribute_parent(context) is not None

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        return bpy.ops.efx_re.attribute_add(attr_type=self.attr_type)


# ---------------------------------------------------------------------------
# MdfProperty —— TypeMesh 系列 attribute 的 `properties` 数组（材质参数覆盖表）
# ---------------------------------------------------------------------------

# 材质路径字段在不同 TypeMesh 变体里叫法不同：V2 是 `MaterialPath`（EfxTypeMesh.cs:127），
# 老的那几个叫 `mdfPath`（同文件 :53 / :643）。
_MATERIAL_PATH_KEYS = ("MaterialPath", "mdfPath")


def resolve_mdf_properties(obj: Object):
    """一个 attribute 对象如果是"带材质参数覆盖表"的那种，返回 `(properties 节点, 材质路径)`，
    否则 `(None, None)`。

    判据是"同时有 `properties` 数组字段和材质路径字段"，不按 `$type` 精确匹配——同一套
    `List<MdfProperty>` 挂在好几个 TypeMesh 变体上（语料里实际用到的只有
    `EFXAttributeTypeMeshV2`，但没必要把判断写死在那一个类名上）。**空数组也要能命中**，
    否则"一条 property 都还没有"的 attribute 就永远加不了第一条，所以不能靠
    `model.is_mdf_property_node()` 认子节点形状。
    """
    if obj is None or obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
        return None, None
    node = model.find_field(obj.efx_fields, "properties")
    if node is None or node.data_type != "ARRAY":
        return None, None
    for key in _MATERIAL_PATH_KEYS:
        path_node = model.find_field(obj.efx_fields, key)
        if path_node is not None and path_node.data_type == "STRING":
            return node, path_node.string_value
    return None, None


def _present_hashes(properties_node) -> set:
    """`properties` 里已经有的 `PropertyNameUTF8Hash`——同一个参数覆盖两遍没有意义，
    候选列表里要过滤掉。"""
    present = set()
    for child in properties_node.children:
        for sub in child.children:
            if sub.key == "PropertyNameUTF8Hash":
                present.add(model.node_to_value(sub))
    return present


def reference_mismatches(properties_node, entries: list) -> list[tuple[int, str]]:
    """拿覆盖表里**已经有的**条目去核对参考材质，返回 `[(参数名哈希, 说明), ...]`。

    检查的是**结构**：这个参数在参考材质里存不存在、下标和分量数对不对得上。数值差异不算
    ——覆盖表的存在意义就是"把材质的默认值改掉"，值不一样才是正常的。

    指错材质的典型后果就是下标错，而下标错不会有任何报错，只会让游戏改到另一个参数上。比对
    文件名没用（用户从 pak 里捞出来的文件想叫什么叫什么），比对真实数据才有意义。

    覆盖表是空的（一条都还没有）时返回空列表：这时候没有任何可核对的证据，不能因此就声称
    材质是对的，但也没有理由拦——直接放行，别编造结论（铁律 #7）。
    """
    by_hash = {e["utf8Hash"]: e for e in entries}
    issues: list[tuple[int, str]] = []
    for child in properties_node.children:
        values = model.node_to_value(child)
        name_hash = values.get("PropertyNameUTF8Hash")
        if not isinstance(name_hash, int):
            continue
        entry = by_hash.get(name_hash)
        known = semantics.lookup_name_hash(name_hash) or str(name_hash)
        if entry is None:
            issues.append((name_hash, f"'{known}' 在参考材质里不存在"))
            continue
        # 贴图类型的 mdfPropertyIndex 恒为 -1（vendor 写死），没有可比的下标。
        if entry["kind"] == "param" and values.get("mdfPropertyIndex") != entry["index"]:
            issues.append((name_hash, (
                f"'{known}' 的下标对不上（表里 {values.get('mdfPropertyIndex')}，"
                f"参考材质里 {entry['index']}）"
            )))
        elif values.get("mdfParameterValueCount") != entry["componentCount"]:
            issues.append((name_hash, (
                f"'{known}' 的分量数对不上（表里 {values.get('mdfParameterValueCount')}，"
                f"参考材质里 {entry['componentCount']}）"
            )))
    return issues


def mismatched_hashes(obj: Object) -> set:
    """`Object.efx_mdf_mismatched` 存的那串哈希，解析成集合供面板逐行标记。

    为什么存下来而不是画的时候现算：现算要拿到解析好的材质，而 draw() 里绝不能跑
    EfxBridge 子进程（每次重绘都会跑）。载入参考材质时算一次、存成字符串，之后画多少次都
    不花钱，还能跟着 .blend 一起存下来。新加的条目按定义就是对得上的（就是从这份材质里挑
    出来的），删条目也不影响别人，所以这份结果不会因为增删而过时。
    """
    raw = getattr(obj, "efx_mdf_mismatched", "")
    return {int(part) for part in raw.split(",") if part}


def _renumber_array_keys(node) -> None:
    """ARRAY 节点的子项 key 是它的下标字符串（见 model.populate_node）。导出只看顺序、不看
    key，但面板上是照 key 画标签的，增删之后要重排，否则显示的序号会和实际位置对不上。"""
    for index, child in enumerate(node.children):
        child.key = str(index)


# EnumProperty 的 items 回调返回的元组必须由 Python 侧持有（Blender 只存指针，见
# attribute_types.py 里同一个坑的说明）。按材质路径缓存。
_candidate_items_cache: dict = {}


def _candidate_enum_items(self, context):
    obj = getattr(context, "object", None)
    properties_node, _ = resolve_mdf_properties(obj)
    if properties_node is None:
        return [("", "（当前不是带材质参数表的 attribute）", "")]

    try:
        entries = mdf_catalog.candidates(obj.efx_mdf_reference)
    except mdf_catalog.CatalogError as ex:
        # 下拉里塞不下多行错误，这里只给一条能看出"为什么是空的"的占位；真正完整的报错在
        # execute() 里 report 出来。
        return [("", str(ex)[:120], "")]

    present = _present_hashes(properties_node)
    items = []
    for entry in entries:
        if entry["utf8Hash"] in present:
            continue
        if entry["kind"] == "texture":
            label = f"{entry['name']}  (贴图)"
            desc = entry.get("path") or ""
        else:
            label = f"{entry['name']}  ({entry['componentCount']} 分量)"
            desc = f"mdfPropertyIndex {entry['index']}"
        items.append((str(entry["utf8Hash"]), label, desc))

    if not items:
        items = [("", "（这个材质的参数已经全部覆盖了）", "")]
    _candidate_items_cache[obj.efx_mdf_reference or ""] = items
    return items


class EFX_RE_OT_mdf_reference_load(Operator, ImportHelper):
    """给当前 attribute 指一个参考 .mdf2。

    路径存在 attribute 自己身上（`Object.efx_mdf_reference`），不做成全局设置——同一个文件里
    不同 mesh attribute 引用的是不同材质。这里顺手解析一遍：解析不了就不记路径，免得用户以为
    指好了、点添加才发现是空的。
    """

    bl_idname = "efx_re.mdf_reference_load"
    bl_label = "Load Reference Material"
    bl_description = "指一个参考 .mdf2，之后添加参数时只列这个材质里真实存在的那些"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.mdf2;*.mdf2.*", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        node, _ = resolve_mdf_properties(getattr(context, "object", None))
        return node is not None

    def execute(self, context):
        obj = context.object
        node, _ = resolve_mdf_properties(obj)
        if node is None:
            self.report({"ERROR"}, "当前 attribute 没有材质参数覆盖表")
            return {"CANCELLED"}

        try:
            entries = mdf_catalog.candidates(self.filepath)
        except mdf_catalog.CatalogError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        obj.efx_mdf_reference = self.filepath
        params = sum(1 for e in entries if e["kind"] == "param")
        message = f"已载入参考材质（{params} 个参数 + {len(entries) - params} 个贴图槽）"

        # 拿已有条目核对一遍，对不上的记下来给面板逐行标红。只警告不拦——用户完全可能是在给一个
        # 还没写进 MaterialPath 的新材质配参数。但"指错材质"的后果（下标算错、游戏改到另一个
        # 参数上）不会有任何其它提示，必须在这里说出来。
        issues = reference_mismatches(node, entries)
        obj.efx_mdf_mismatched = ",".join(str(name_hash) for name_hash, _ in issues)
        if issues:
            detail = "；".join(text for _, text in issues[:3]) + ("……" if len(issues) > 3 else "")
            self.report({"WARNING"}, f"{message}，{len(issues)} 条和材质对不上：{detail}")
        else:
            self.report({"INFO"}, message)
        return {"FINISHED"}


class EFX_RE_OT_mdf_reference_clear(Operator):
    """清掉当前 attribute 的参考 .mdf2"""

    bl_idname = "efx_re.mdf_reference_clear"
    bl_label = "Clear Reference Material"
    bl_description = "清掉参考材质，清掉之后就不能再往覆盖表里加参数了"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and bool(getattr(obj, "efx_mdf_reference", ""))

    def execute(self, context):
        context.object.efx_mdf_reference = ""
        # 标记是"相对某个参考材质"才成立的结论，材质一撤这些红点就没有依据了。
        context.object.efx_mdf_mismatched = ""
        return {"FINISHED"}


class EFX_RE_OT_mdf_property_add(Operator):
    """从参考 .mdf2 里挑一个参数/贴图槽，作为新的一条 MdfProperty 加进 `properties`。

    候选和初值全部来自那个 .mdf2（见 mdf_catalog.py 的说明）——不让用户手填
    `mdfPropertyIndex`，那个下标填错不会报错，只会静默改到另一个参数上。
    """

    bl_idname = "efx_re.mdf_property_add"
    bl_label = "Add Material Property"
    bl_description = "从参考材质里挑一个参数加进覆盖表，下标和初值按材质自动填"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "candidate"

    candidate: EnumProperty(
        name="Property",
        description="要新增的材质参数",
        items=_candidate_enum_items,
    )

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        node, _ = resolve_mdf_properties(obj)
        if node is None:
            return False
        if not obj.efx_mdf_reference:
            try:
                cls.poll_message_set("先用「载入参考材质」指一个 .mdf2——能加哪些参数只有材质本身知道")
            except Exception:
                pass
            return False
        return True

    def invoke(self, context, event):
        # 单个材质的参数表可以有一百多条（语料里见过 156 条），分类浏览没意义，直接上
        # 模糊搜索弹窗——同 EFX_RE_OT_attribute_add_search 的理由。
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        obj = context.object
        properties_node, _ = resolve_mdf_properties(obj)
        if properties_node is None:
            self.report({"ERROR"}, "当前 attribute 没有材质参数覆盖表")
            return {"CANCELLED"}
        if not self.candidate:
            self.report({"ERROR"}, "没有选中任何参数")
            return {"CANCELLED"}

        try:
            entries = mdf_catalog.candidates(obj.efx_mdf_reference)
        except mdf_catalog.CatalogError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        wanted = int(self.candidate)
        entry = next((e for e in entries if e["utf8Hash"] == wanted), None)
        if entry is None:
            self.report({"ERROR"}, f"参考材质里没有哈希为 {wanted} 的参数")
            return {"CANCELLED"}
        if wanted in _present_hashes(properties_node):
            self.report({"ERROR"}, f"'{entry['name']}' 已经在覆盖表里了")
            return {"CANCELLED"}

        new_dict = mdf_catalog.build_property_dict(entry, obj.efx_version)
        child = properties_node.children.add()
        model.populate_node(child, str(len(properties_node.children) - 1), new_dict)
        properties_node.ui_expand = True

        self.report({"INFO"}, f"已新增材质属性 '{entry['name']}'")
        return {"FINISHED"}


class EFX_RE_OT_mdf_property_remove(Operator):
    """从 `properties` 覆盖表里删掉一条"""

    bl_idname = "efx_re.mdf_property_remove"
    bl_label = "Remove Material Property"
    bl_description = "把这一条材质参数从覆盖表里删掉（材质本身的默认值会重新生效）"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="Index", default=-1, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        node, _ = resolve_mdf_properties(getattr(context, "object", None))
        return node is not None and len(node.children) > 0

    def execute(self, context):
        properties_node, _ = resolve_mdf_properties(context.object)
        if properties_node is None:
            self.report({"ERROR"}, "当前 attribute 没有材质参数覆盖表")
            return {"CANCELLED"}
        if not (0 <= self.index < len(properties_node.children)):
            self.report({"ERROR"}, f"下标越界：{self.index}")
            return {"CANCELLED"}

        properties_node.children.remove(self.index)
        _renumber_array_keys(properties_node)
        self.report({"INFO"}, "已删除一条材质属性")
        return {"FINISHED"}


class EFX_RE_OT_delete(Operator):
    """删除当前选中的 Entry / Action / Attribute（连同它的子对象）"""

    bl_idname = "efx_re.delete"
    bl_label = "Delete"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return obj is not None and obj.get("~TYPE") in (
            model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE,
        )

    def execute(self, context):
        obj = context.object
        tag = obj.get("~TYPE")
        if tag == model.TYPE_ROOT:
            # 架构决策 5：整棵树的删除交给 Outliner 的 Delete Hierarchy，不在这里重造一遍
            self.report({"ERROR"}, "删整个 EFX 请在 Outliner 里用 Delete Hierarchy")
            return {"CANCELLED"}
        if tag not in (model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE):
            self.report({"ERROR"}, "选中一个 Entry / Action / Attribute")
            return {"CANCELLED"}

        parent_obj = obj.parent
        root_col = io_tree.find_root(obj)
        name = obj.name

        # 收集整棵子树。Attribute 底下可能还挂着嵌套的 EFX_ROOT（PlayEmitter.efxrData），
        # 一并删掉——留着会变成没有父级的孤儿，导出时按 parent 链过滤会被静默丢弃。
        doomed: list[Object] = []
        stack = [obj]
        while stack:
            cur = stack.pop()
            doomed.append(cur)
            stack.extend(cur.children)

        opaque_texts = [o.efx_opaque_text for o in doomed if getattr(o, "efx_opaque_text", "")]
        # 被删掉的 attribute 如果带着嵌套的 efxrData 根集合，集合也要一起删——它不在
        # children 里（Collection 挂不到 Object 下面），只靠 efx_nested_root 指针关联，
        # 光删对象会留下一堆没人引用的空集合。
        nested_roots = [o.efx_nested_root for o in doomed if getattr(o, "efx_nested_root", None)]
        for o in doomed:
            bpy.data.objects.remove(o, do_unlink=True)
        for col in nested_roots:
            _remove_collection_tree(col)
        # 顺手清掉只被这些对象引用的 opaque 文本块，不然场景里会攒一堆无主文本
        for text_name in opaque_texts:
            text = bpy.data.texts.get(text_name)
            if text is not None and text.users == 0:
                bpy.data.texts.remove(text)

        # 重排兄弟：Attribute 靠父对象找兄弟；Entry/Action 没有父对象（EFX_ROOT 是集合），
        # 靠所在的 *_Entries / *_Actions 集合找。
        if tag == model.TYPE_ATTRIBUTE and parent_obj is not None:
            _renumber(io_tree.typed_children(parent_obj, tag))
            # 删掉的可能正是撑起父 Entry 显示名后缀的那个 TypeAttribute/PtLife/PtColliderAction，
            # 删完要重新算一遍——no-op（对 Action）由函数自己判断。
            model.refresh_entry_display_name(parent_obj)
            _activate(context, parent_obj)
        elif root_col is not None:
            _renumber(io_tree.root_entries(root_col) if tag == model.TYPE_ENTRY
                      else io_tree.root_actions(root_col))

        self.report({"INFO"}, f"已删除 '{name}'（含 {len(doomed) - 1} 个子对象）")
        return {"FINISHED"}


_CLASSES = (
    EFX_RE_OT_entry_add,
    EFX_RE_OT_action_add,
    EFX_RE_OT_attribute_add,
    EFX_RE_OT_attribute_add_search,
    EFX_RE_OT_mdf_reference_load,
    EFX_RE_OT_mdf_reference_clear,
    EFX_RE_OT_mdf_property_add,
    EFX_RE_OT_mdf_property_remove,
    EFX_RE_OT_delete,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
