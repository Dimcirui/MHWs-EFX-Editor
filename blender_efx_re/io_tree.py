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
    if content.get("ParentBone") is None and "ParentBone" in content:
        # C# 侧 ParentBone 是 string?，无绑定时可能是 null，也可能压根不存在（老结构体没有
        # 这个属性）——只在真的存在这个键时才规整。规整成 "" 而不是保留 null：C# 写出逻辑用
        # string.IsNullOrEmpty(ParentBone) 判断"无父骨骼"，null 和 "" 语义完全等价
        # （EfxFile.cs:984），但 EFXValueNode 的 NULL data_type 没有可编辑的 slot，画不出
        # prop_search 控件，所以统一存成空字符串，导出行为不变。见
        # model.is_bone_reference_field()/panels.py 的骨骼搜索控件。
        content["ParentBone"] = ""
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

    for bone_dict in efxfile_dict.get("Bones", []) or []:
        item = root_obj.efx_bones.add()
        item.name = bone_dict.get("name", "") or ""
        item.value = str(int(bone_dict.get("value", 0) or 0))

    for fp_dict in efxfile_dict.get("FieldParameterValues", []) or []:
        item = root_obj.efx_field_parameters.add()
        item.name = fp_dict.get("name", "") or ""
        content = {key: value for key, value in fp_dict.items() if key != "name"}
        if content.get("filePath") is None and "filePath" in content:
            # 同 build_attribute_object() 里 ParentBone 的规整：C# 侧 filePath 是 string?，
            # 无效 type 时是 null，写出时也是 filePath ??= "" 兜底（EfxFile.cs:556/571）——
            # null 和 "" 语义等价，规整成 "" 是为了让 EFXValueNode 有可编辑的 STRING slot
            # （NULL data_type 没有对应控件）。
            content["filePath"] = ""
        model.populate_dict_as_children(item.fields, content)

    for uvar_dict in efxfile_dict.get("UvarGroups", []) or []:
        item = root_obj.efx_uvar_groups.add()
        item.uvar_type = str(int(uvar_dict.get("uvarType", 2) or 2))
        item.path = uvar_dict.get("path") or ""
        item.group = uvar_dict.get("group") or ""

    for expr_dict in efxfile_dict.get("ExpressionParameters", []) or []:
        item = root_obj.efx_expression_parameters.add()
        item.name = expr_dict.get("name", "") or ""
        item.param_type = str(int(expr_dict.get("type", 0) or 0))
        item.value1 = model.json_float_in(expr_dict.get("value1", 0.0))
        item.value2 = model.json_float_in(expr_dict.get("value2", 0.0))
        item.value3 = model.json_float_in(expr_dict.get("value3", 0.0))

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
    efxfile_dict["Bones"] = [
        {"name": item.name, "value": int(item.value or "0")} for item in root_obj.efx_bones
    ]
    # BoneRelations 和 EffectGroups 同一个模式：C# 后端 DoWrite() 按每个 attribute 当前的
    # ParentBone 对 Bones 表重新 FindIndex，完整重算下标数组，传空数组即可，见
    # docs/TOPLEVEL_STRUCTURE.md "Bones / BoneRelations 结构调研"（EfxFile.cs:982-989）。
    efxfile_dict["BoneRelations"] = []
    efxfile_dict["FieldParameterValues"] = [
        {"name": item.name, **model.children_to_dict(item.fields)}
        for item in root_obj.efx_field_parameters
    ]
    # UvarGroups 最多 2 项，超出的会在 vendor 写出逻辑里被静默忽略（只处理下标 0/1，见
    # docs/TOPLEVEL_STRUCTURE.md "UvarGroups 结构调研"）——UI 侧的 Add 按钮已经拦住了超过
    # 2 项的情况（EFX_OT_uvar_group_add），这里不需要重复校验。
    efxfile_dict["UvarGroups"] = [
        {"uvarType": int(item.uvar_type), "path": item.path, "group": item.group}
        for item in root_obj.efx_uvar_groups
    ]
    # 两个具名哈希固定填 0：vendor 导出前会无条件用 MurMur3 从 name 重新计算
    # （EfxFile.cs:966-967），改名字天然保持同步，不需要 Python 侧维护，见
    # EFXExpressionParamItem 的说明。
    efxfile_dict["ExpressionParameters"] = [
        {
            "expressionParameterNameUTF16Hash": 0,
            "expressionParameterNameUTF8Hash": 0,
            "type": int(item.param_type),
            "value1": model.json_float_out(item.value1),
            "value2": model.json_float_out(item.value2),
            "value3": model.json_float_out(item.value3),
            "name": item.name,
        }
        for item in root_obj.efx_expression_parameters
    ]
    return efxfile_dict


class BoneReferenceError(Exception):
    """check_bone_references() 校验失败时抛出：某个 attribute 的 ParentBone 引用了不在
    efx_bones 列表里的名字。不在这里静默放行——见 check_bone_references() 的说明。"""


def _missing_bone_refs(parent_obj: Object, known_names: set) -> list:
    missing = []
    for attr_obj in typed_children(parent_obj, model.TYPE_ATTRIBUTE):
        for node in attr_obj.efx_fields:
            if (
                node.key == "ParentBone"
                and node.data_type == "STRING"
                and node.string_value
                and node.string_value not in known_names
            ):
                missing.append(f'{attr_obj.name}: "{node.string_value}"')
    return missing


def check_bone_references(root_obj: Object) -> None:
    """导出前校验：任何 attribute 的 ParentBone 字段只要非空，必须能在 root_obj.efx_bones
    里找到同名条目。C# 后端写出时用 Bones.FindIndex(name) 反查下标，找不到会静默写成 -1
    （"无父骨骼"），不报任何异常或警告（见 docs/TOPLEVEL_STRUCTURE.md "风险 2"）——这正是
    架构决策 9 想避免的"错误结构骗过用户"，只是这次是我们自己的 Python 胶水层要对齐这个纪律，
    不是 C# 解析失败那种情况。找到不一致就直接拒绝导出，不做自动同步/静默降级——用户没有
    确认过"骨骼在游戏里到底怎么工作"之前，宁可让用户手动维护 efx_bones 列表。

    只检查顶层文件自己的 Entries/Actions，不递归进嵌套 PlayEmitter.efxrData 子树：vendor 源码
    读时用 `parentFile?.Bones ?? Bones` 解析嵌套文件里的骨骼引用（用外层文件的 Bones 表），
    但写时用的是当前文件自己的 `Bones`（不查 parentFile），读写不对称——嵌套树的骨骼引用重新
    导出后大概率会失效，这是 vendor 自身的行为、不是这个校验函数能堵上的，范围先收在顶层，
    等有真实带嵌套骨骼绑定的样本确认这条路径实际行为后再决定要不要处理。
    """
    known_names = {item.name for item in root_obj.efx_bones}
    missing = []
    for entry_obj in typed_children(root_obj, model.TYPE_ENTRY):
        missing.extend(_missing_bone_refs(entry_obj, known_names))
    for action_obj in typed_children(root_obj, model.TYPE_ACTION):
        missing.extend(_missing_bone_refs(action_obj, known_names))
    if missing:
        raise BoneReferenceError(
            "以下 attribute 的 ParentBone 引用了不在 Bones 列表里的骨骼名字，"
            "导出会静默丢失绑定，请先在 Root 面板的 Bones 列表里添加对应名字：\n"
            + "\n".join(f"  {m}" for m in missing)
        )
