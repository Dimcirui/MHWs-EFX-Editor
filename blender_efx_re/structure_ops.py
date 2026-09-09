"""
blender_efx_re/structure_ops.py —— 新增 / 删除 Entry、Action、Attribute

这是 C 层的核心：上一版插件**完全没有结构编辑能力**，只能导入现成文件改字段，连"新建一个
Entry"都做不到。

空白对象不是我们攒的模板，是 C# 侧 `new` 出来的真实实例（见 bridge.new_*）——每个 attribute
类型在 vendor 里都是一个具体的 C# 类，new 出来就带正确的默认值和字段结构，序列化规则和 dump
完全一致，直接喂给现成的 `io_tree.build_*_object()` 就行。姊妹项目 EFX-Editor 需要一整套预设
文件来做同一件事，是因为它没有类型化对象模型。

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
from bpy.props import EnumProperty
from bpy.types import Object, Operator

from . import attribute_types, bridge, io_tree, model

# 能承载 attribute 的父类型
_ATTRIBUTE_PARENTS = (model.TYPE_ENTRY, model.TYPE_ACTION)


def _renumber(siblings: list[Object]) -> None:
    """按当前列表顺序把 efx_index 重排成 0..n-1。导出顺序只看 efx_index，不看 Blender 自己的
    children 迭代顺序（见 io_tree.typed_children）。"""
    for i, obj in enumerate(siblings):
        obj.efx_index = i


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


def _activate(context, obj: Object) -> None:
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class EFX_RE_OT_entry_add(Operator):
    """在当前 EFX 树里新增一个空 Entry（追加到末尾）"""

    bl_idname = "efx_re.entry_add"
    bl_label = "Add Entry"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def execute(self, context):
        root_obj = io_tree.resolve_root(context)
        if root_obj is None:
            self.report({"ERROR"}, "没有当前 EFX——先导入一个文件，或在「当前 EFX」里选一个")
            return {"CANCELLED"}
        try:
            data = bridge.new_entry()
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"新建 Entry 失败：\n{ex}")
            return {"CANCELLED"}

        entries_collection, _ = io_tree.root_collections(root_obj)
        siblings = io_tree.typed_children(root_obj, model.TYPE_ENTRY)
        data["name"] = f"Entry_{len(siblings)}"
        new_obj = io_tree.build_entry_object(data, len(siblings), root_obj, entries_collection)
        _renumber(siblings + [new_obj])
        _activate(context, new_obj)
        self.report({"INFO"}, f"已新增 Entry '{new_obj.name}'")
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
        root_obj = io_tree.resolve_root(context)
        if root_obj is None:
            self.report({"ERROR"}, "没有当前 EFX——先导入一个文件，或在「当前 EFX」里选一个")
            return {"CANCELLED"}
        try:
            data = bridge.new_action()
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"新建 Action 失败：\n{ex}")
            return {"CANCELLED"}

        _, actions_collection = io_tree.root_collections(root_obj)
        siblings = io_tree.typed_children(root_obj, model.TYPE_ACTION)
        data["name"] = f"Action_{len(siblings)}"
        new_obj = io_tree.build_action_object(data, len(siblings), root_obj, actions_collection)
        _renumber(siblings + [new_obj])
        _activate(context, new_obj)
        self.report({"INFO"}, f"已新增 Action '{new_obj.name}'")
        return {"FINISHED"}


class EFX_RE_OT_attribute_add(Operator):
    """给当前 Entry/Action 新增一个指定类型的空 Attribute，插到 itemTypeId 排序位"""

    bl_idname = "efx_re.attribute_add"
    bl_label = "Add Attribute"
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
            data = bridge.new_attribute(self.attr_type)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"新建 Attribute 失败：\n{ex}")
            return {"CANCELLED"}

        siblings = io_tree.typed_children(parent_obj, model.TYPE_ATTRIBUTE)
        insert_at = sorted_insert_index(parent_obj, info["itemTypeId"])
        collection = parent_obj.users_collection[0]
        # 先按末位建出来，再挪到排序位上重排 efx_index——build_attribute_object 只认
        # "建在哪个 collection、挂在哪个 parent"，插入位置是我们这边的事。
        new_obj = io_tree.build_attribute_object(data, len(siblings), parent_obj, collection)
        ordered = siblings[:insert_at] + [new_obj] + siblings[insert_at:]
        _renumber(ordered)
        _activate(context, new_obj)
        self.report(
            {"INFO"},
            f"已新增 {self.attr_type}（插在第 {insert_at} 位，itemTypeId {info['itemTypeId']}）",
        )
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
        for o in doomed:
            bpy.data.objects.remove(o, do_unlink=True)
        # 顺手清掉只被这些对象引用的 opaque 文本块，不然场景里会攒一堆无主文本
        for text_name in opaque_texts:
            text = bpy.data.texts.get(text_name)
            if text is not None and text.users == 0:
                bpy.data.texts.remove(text)

        if parent_obj is not None:
            _renumber(io_tree.typed_children(parent_obj, tag))
            _activate(context, parent_obj)

        self.report({"INFO"}, f"已删除 '{name}'（含 {len(doomed) - 1} 个子对象）")
        return {"FINISHED"}


_CLASSES = (
    EFX_RE_OT_entry_add,
    EFX_RE_OT_action_add,
    EFX_RE_OT_attribute_add,
    EFX_RE_OT_delete,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
