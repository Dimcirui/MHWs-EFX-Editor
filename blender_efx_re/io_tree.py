"""
blender_efx_re/io_tree.py —— ~TYPE 对象树 ↔ EfxFile JSON dict 互转

对齐姊妹项目 EFX-Editor 的 io_tree.py 角色：Entry/Attribute 是独立 Blender Object，靠 parent
关系组织归属（不是 PropertyGroup 集合），Collection 只做 Outliner 视觉分组。命名跟随
RE-Engine-Lib（`EfxFile.Entries: List<EFXEntry>`）叫 Entry，不叫 EFX-Editor（MHWI）习惯用的
Body——同一层概念，两个项目各自的命名习惯不同。与 EFX-Editor 不同的两点，见 PLAN.md
"Blender 对象模型草案"：

1. Action 是与 Entry 同级的顶层类型（不是 Entry 的子级），承载 PlayEmitter/PlayEfx。
2. PlayEmitter 的 efxrData 是完整内嵌的 EfxFile 对象图（组合，不是引用）——识别方式是"这个
   attribute 的字典里有没有 efxrData 键"这个结构信号，不按 $type 类名单列举，命中时递归调用
   build_root_from_efxfile 本身，建一个嵌套的子 EFX_ROOT。

顶层字段（Header/Strings/Bones/BoneRelations/FieldParameterValues/ExpressionParameters/
UvarGroups）以及 Entry/Action 里没有单独建 UI 的字段（name/nameHash/index/entryAssignment/
Version/actionUnkn0 等），一律原样存进 model.save_opaque()/load_opaque() 管理的文本块——当前阶段
只对 Groups（Subselect 标签）和 Attribute 内容字段建了编辑 UI，其余的"不碰"就是最安全的处理
（决策 9 的精神：没能力/没打算编辑的东西，原样透传好过自作主张改写）。

Attribute 对象名带 `[父对象名]` 前缀（如 `[Emitter] Life`）：同一个 Entry/Action 下常有多个
同类型 attribute（不同 Entry 也大量共享同一批常见 attribute 类型，比如几乎每个 Entry 都有
ParentOptions），如果只用 `_short_attr_name()` 裸类型名当对象名，Blender 全局对象名唯一性会
把它们批量改成 `.001`/`.002`，Outliner 里分不清谁是谁。带上父对象名前缀后碰撞概率大幅降低
（虽然理论上同一父对象下两个"同类型+同名"attribute 仍可能撞，这种情况交给 Blender 的
`.001` 后备机制兜底，纯展示，不影响导出——导出靠 parent 链和 efx_index，不靠对象名）。
"""

from __future__ import annotations

import bpy
from bpy.types import Collection, Object

from . import model

_EMPTY_DISPLAY_SIZE = 0.1


def _new_empty(name: str, collection: Collection) -> Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = _EMPTY_DISPLAY_SIZE
    collection.objects.link(obj)
    return obj


def _short_attr_name(attr_type: str) -> str:
    """`ReeLib.Efx.Structs.Main.EFXAttributeUnitCulling` -> `UnitCulling`（纯展示用，不影响导出）。"""
    short = attr_type.rsplit(".", 1)[-1]
    if short.startswith("EFXAttribute"):
        short = short[len("EFXAttribute"):]
    return short or attr_type


# ---------------------------------------------------------------------------
# Import：EfxFile dict -> ~TYPE 对象树
# ---------------------------------------------------------------------------

def build_attribute_object(attr_dict: dict, index: int, parent_obj: Object, collection: Collection) -> Object:
    attr_type = attr_dict.get("$type", "")
    obj = _new_empty(f"[{parent_obj.name}] {_short_attr_name(attr_type)}", collection)
    obj.parent = parent_obj
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    obj.efx_index = index
    obj.efx_attr_type = attr_type
    obj.efx_unique_id = attr_dict.get("UniqueID", 0)
    obj.efx_version = attr_dict.get("Version", 0)
    obj.efx_type_id = attr_dict.get("type", 0)
    obj.efx_is_type_attribute = bool(attr_dict.get("IsTypeAttribute", False))

    content = {
        key: value for key, value in attr_dict.items()
        if key not in model.ATTRIBUTE_BOOKKEEPING_KEYS and key not in model.ATTRIBUTE_NESTED_ROOT_KEYS
    }
    model.populate_dict_as_children(obj.efx_fields, content)

    leftover = {key: attr_dict[key] for key in ("efxrSize",) if key in attr_dict}
    if leftover:
        model.save_opaque(obj, leftover)

    if "efxrData" in attr_dict:
        build_root_from_efxfile(attr_dict["efxrData"], collection, f"{obj.name}_efxrData", parent_obj=obj)

    return obj


def build_entry_object(entry_dict: dict, index: int, parent_obj: Object, collection: Collection) -> Object:
    display_name = entry_dict.get("name") or f"Entry_{index}"
    obj = _new_empty(display_name, collection)
    obj.parent = parent_obj
    obj["~TYPE"] = model.TYPE_ENTRY
    obj.efx_index = index

    for group_name in entry_dict.get("Groups", []) or []:
        tag = obj.efx_groups.add()
        tag.name = group_name

    leftover = {k: v for k, v in entry_dict.items() if k not in model.ENTRY_STRUCTURAL_KEYS}
    model.save_opaque(obj, leftover)

    for attr_index, attr_dict in enumerate(entry_dict.get("Attributes", []) or []):
        build_attribute_object(attr_dict, attr_index, obj, collection)

    return obj


def build_action_object(action_dict: dict, index: int, parent_obj: Object, collection: Collection) -> Object:
    display_name = action_dict.get("name") or f"Action_{index}"
    obj = _new_empty(display_name, collection)
    obj.parent = parent_obj
    obj["~TYPE"] = model.TYPE_ACTION
    obj.efx_index = index

    leftover = {k: v for k, v in action_dict.items() if k not in model.ACTION_STRUCTURAL_KEYS}
    model.save_opaque(obj, leftover)

    for attr_index, attr_dict in enumerate(action_dict.get("Attributes", []) or []):
        build_attribute_object(attr_dict, attr_index, obj, collection)

    return obj


def build_root_from_efxfile(
    efxfile_dict: dict,
    parent_collection: Collection,
    name: str,
    parent_obj: Object | None = None,
) -> Object:
    """把一个 EfxFile JSON dict 建成一棵 ~TYPE 对象树，返回 EFX_ROOT 对象。

    parent_collection：新建的这一层 Collection 挂在哪个 Collection 下面（顶层文件传
    context.scene.collection；PlayEmitter 递归时传外层 attribute 所在的 collection）。
    parent_obj：仅递归场景使用，把嵌套 EFX_ROOT parent 到外层 PlayEmitter attribute 对象上，
    使导出时能通过 parent-child 关系找到它（不依赖 collection 归属）。
    """
    own_collection = bpy.data.collections.new(name)
    parent_collection.children.link(own_collection)
    main_collection = bpy.data.collections.new(f"{name}_Main")
    own_collection.children.link(main_collection)
    actions_collection = bpy.data.collections.new(f"{name}_Actions")
    own_collection.children.link(actions_collection)

    root_obj = _new_empty(name, own_collection)
    root_obj["~TYPE"] = model.TYPE_ROOT
    if parent_obj is not None:
        root_obj.parent = parent_obj

    leftover = {k: v for k, v in efxfile_dict.items() if k not in model.ROOT_STRUCTURAL_KEYS}
    model.save_opaque(root_obj, leftover)

    for index, entry_dict in enumerate(efxfile_dict.get("Entries", []) or []):
        build_entry_object(entry_dict, index, root_obj, main_collection)

    for index, action_dict in enumerate(efxfile_dict.get("Actions", []) or []):
        build_action_object(action_dict, index, root_obj, actions_collection)

    return root_obj


# ---------------------------------------------------------------------------
# Export：~TYPE 对象树 -> EfxFile dict
# ---------------------------------------------------------------------------

def typed_children(obj: Object, type_tag: str) -> list[Object]:
    """obj 的直接子对象里 ~TYPE 等于 type_tag 的那些，按 efx_index 排序（见 model.py 里的说明，
    不依赖 Blender children/collection 的迭代顺序）。公开给 copy_paste.py 复用（找兄弟对象、
    算新粘贴对象该排的 efx_index）。"""
    matched = [child for child in obj.children if child.get("~TYPE") == type_tag]
    matched.sort(key=lambda o: o.efx_index)
    return matched


def find_root(obj: Object | None) -> Object | None:
    """从任意一个 ~TYPE 对象往 parent 链上找 EFX_ROOT，找不到返回 None。
    operators.py（Export）和 copy_paste.py（Paste）共用。"""
    while obj is not None:
        if obj.get("~TYPE") == model.TYPE_ROOT:
            return obj
        obj = obj.parent
    return None


def root_collections(root_obj: Object) -> tuple[Collection, Collection]:
    """返回一个 EFX_ROOT 对象的 (main_collection, actions_collection)。按
    build_root_from_efxfile() 里固定的链接顺序取（先 link main_collection 再 link
    actions_collection），不靠名字匹配——Collection 和 Object 各自的去重命名空间是独立的，
    root_obj.name 撞名被 Blender 加 .001 后缀时，不代表它的 own_collection 名字也跟着变，
    反过来也一样，所以不能假设两者同名。供 copy_paste.py 的 Paste Entry 找粘贴目标用。"""
    own_collection = root_obj.users_collection[0]
    return own_collection.children[0], own_collection.children[1]


def export_attribute_object(obj: Object) -> dict:
    # $type 必须是字典的第一个键：C# 侧 EfxJsonTypeResolver 是流式读取多态判别字段来选定具体
    # EFXAttribute 子类的 JsonTypeInfo，不像 System.Text.Json 内置的 [JsonPolymorphic] 那样会
    # 缓冲整个对象再重放——$type 出现在其他字段之后会导致反序列化直接退回基类 EFXAttribute
    # （抽象/无无参构造函数），抛 NotSupportedException。已在 Blender 5.1 实测复现确认。
    attr_dict = {"$type": obj.efx_attr_type}
    attr_dict.update(model.children_to_dict(obj.efx_fields))
    attr_dict.update(model.load_opaque(obj))  # 目前只可能有 efxrSize
    attr_dict["UniqueID"] = obj.efx_unique_id
    attr_dict["Version"] = obj.efx_version
    attr_dict["type"] = obj.efx_type_id
    attr_dict["IsTypeAttribute"] = obj.efx_is_type_attribute

    nested_root = next(
        (child for child in obj.children if child.get("~TYPE") == model.TYPE_ROOT), None
    )
    if nested_root is not None:
        attr_dict["efxrData"] = export_root_to_efxfile(nested_root)

    return attr_dict


def export_entry_object(obj: Object) -> dict:
    entry_dict = model.load_opaque(obj)  # index 已随其余 opaque 字段原样透传，见 model.py 说明。
    entry_dict["Groups"] = [tag.name for tag in obj.efx_groups]
    entry_dict["Attributes"] = [
        export_attribute_object(attr_obj) for attr_obj in typed_children(obj, model.TYPE_ATTRIBUTE)
    ]
    return entry_dict


def export_action_object(obj: Object) -> dict:
    action_dict = model.load_opaque(obj)
    action_dict["Attributes"] = [
        export_attribute_object(attr_obj) for attr_obj in typed_children(obj, model.TYPE_ATTRIBUTE)
    ]
    return action_dict


def export_root_to_efxfile(root_obj: Object) -> dict:
    efxfile_dict = model.load_opaque(root_obj)
    efxfile_dict["Entries"] = [
        export_entry_object(obj) for obj in typed_children(root_obj, model.TYPE_ENTRY)
    ]
    efxfile_dict["Actions"] = [
        export_action_object(obj) for obj in typed_children(root_obj, model.TYPE_ACTION)
    ]
    # EffectGroups 整体不透传：C# 后端 DoWrite() 里的 UpdateEffectGroups() 会在写入前从
    # 每个 Entry 的 Groups 反向重建 efxEntryIndexes + 两个哈希字段，传空数组即可，
    # 见 PLAN.md 验证记录（读 vendor EfxFile.cs:893 UpdateEffectGroups() 的结论）。
    efxfile_dict["EffectGroups"] = []
    return efxfile_dict
