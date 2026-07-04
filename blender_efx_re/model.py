"""
blender_efx_re/model.py —— ~TYPE 对象模型的数据结构定义

设计背景见 PLAN.md "Blender 对象模型草案" 一节。核心思路（对照姊妹项目 EFX-Editor 的
blender_efx/fields.py）：EFX-Editor 面对的是字节级 spec，字段形状提前被拍平成标量/定长数组，
可以用一张 spec→data_type 映射表 + 扁平的 EFXFieldItem 覆盖所有 block 类型。这个项目的字段来自
EfxBridge dump 出的 JSON，形状是 C# 类字段的直译（`IncludeFields=true`），嵌套深度不固定
（`Vector3`→`{X,Y,Z}`、`via.Range`→`{s,r}` 等真正的嵌套对象，不是提前拍平过的），所以用一个
自引用的递归 PropertyGroup（EFXValueNode）替代扁平表——不用为 ~150 个 EFXAttribute 子类各写一份
schema，vendor 升级新增字段类型也不用改代码。

四种 ~TYPE 对象各自的"结构性字段"（Groups 标签、attr_type、bookkeeping 标量）直接建成 Blender
Object 上的具名属性，只有"内容"字段（即 EFXAttribute 除 $type/UniqueID/Version/IsTypeAttribute/
type/efxrData/efxrSize 之外的其余字段）才走 EFXValueNode 通用树。哪些字段算"结构性"、哪些算
"内容"，两边（io_tree.py 的 import/export）必须共用同一份判断依据，所以相关键名常量集中放在这里。

命名对齐 RE-Engine-Lib（vendor 的 `EfxFile.Entries: List<EFXEntry>`）：这里统一叫 Entry，不叫
姊妹项目 EFX-Editor（MHWI）用的 Body——两边指的是同一层概念，但各自命名习惯不同，本项目跟随
vendor 的实际类名走。
"""

from __future__ import annotations

import json

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Object, PropertyGroup

# ---------------------------------------------------------------------------
# ~TYPE 常量
# ---------------------------------------------------------------------------

TYPE_ROOT = "EFX_ROOT"
TYPE_ENTRY = "EFX_ENTRY"
TYPE_ACTION = "EFX_ACTION"
TYPE_ATTRIBUTE = "EFX_ATTRIBUTE"

# EFXAttribute 字典里，不进入通用 EFXValueNode 树、而是映射到 Object 具名属性的键。
# efxrData/efxrSize 是 PlayEmitter 类内嵌完整 EfxFile 的特殊情况，靠"字典里有没有 efxrData 键"
# 这个结构信号识别（见 io_tree.py），不靠 $type 类名单——efxrSize 是内嵌数据的字节长度，
# 大概率和 Header 里那些 xxxCount 字段一样由后端在 Write() 时重算，但没有实测验证过，
# 保守起见原样透传进 efx_opaque_text，不主动丢弃。
ATTRIBUTE_BOOKKEEPING_KEYS = frozenset({
    "$type", "UniqueID", "Version", "IsTypeAttribute", "type",
})
ATTRIBUTE_NESTED_ROOT_KEYS = frozenset({"efxrData", "efxrSize"})

# EFXEntry 字典里，Attributes 单独按子对象处理，Groups 单独做成可编辑标签列表，其余键原样存进
# efx_opaque_text，不建编辑 UI（当前阶段的结构骨架不覆盖）。
# index 曾经单独排除、导出时按数组位置重新赋值，理由是"EFXEntry.DoWrite() 原样写字段值，
# 不像 EffectGroups 那样反推重算，删除 Entry 后会错位"——这个假设已用真实 MHWs 样本证伪
# （2026-07-03，Blender 5.1 实测）：11_guide_110 的 11 个顶层 Entries，index 字段值是
# {1,32,28,29,27,33,10,9,8,7,31}，与数组位置 0-10 完全不对应；EffectGroups.efxEntryIndexes
# （如 [9,8,7,6,3,2,1,4,5]）实测才是真正按数组位置引用，说明 index 字段是某种独立于数组位置的
# 标识（推测是权威制作工具的创建序号，语义未知），按数组位置强行重算反而会在完全没有编辑的
# 往返里就篡改这个字段。按决策 9"不确定就别自作主张改写"的精神，改为和其余未知字段一样原样
# 透传，不在导出时重算。删除 Entry 后 index 是否需要重新分配，等确认其真实语义后再决定。
ENTRY_STRUCTURAL_KEYS = frozenset({"Attributes", "Groups"})
ACTION_STRUCTURAL_KEYS = frozenset({"Attributes"})

# EfxFile 顶层字典里，Entries/Actions 单独按子对象处理，EffectGroups 整体不透传
# （导出时固定输出空数组，靠 C# 后端 UpdateEffectGroups() 从各 Entry 的 Groups 反向重建，
# 见 PLAN.md 验证记录），Bones 建成 EFX_ROOT.efx_bones 列表 UI，BoneRelations 和
# EffectGroups 一样整体不透传（导出时固定输出空数组，靠 C# 后端从每个 attribute 的
# ParentBone + Bones 表反向重建下标，见 docs/TOPLEVEL_STRUCTURE.md "Bones / BoneRelations
# 结构调研"），其余键原样存进 EFX_ROOT 的 efx_opaque_text。
ROOT_STRUCTURAL_KEYS = frozenset({"Entries", "Actions", "EffectGroups", "Bones", "BoneRelations"})


# ---------------------------------------------------------------------------
# EFXValueNode —— 通用递归字段树
# ---------------------------------------------------------------------------

_DATA_TYPE_ITEMS = (
    ("FLOAT", "Float", "JSON number with a fractional part or exponent"),
    ("INT", "Int", "JSON integer that fits Blender's 32-bit signed IntProperty"),
    ("BIGINT", "Big Int", "JSON integer outside 32-bit signed range, stored as decimal string"),
    ("BOOL", "Bool", "JSON true/false"),
    ("STRING", "String", "JSON string"),
    ("NULL", "Null", "JSON null"),
    ("OBJECT", "Object", "JSON object; fields live in .children"),
    ("ARRAY", "Array", "JSON array; elements live in .children"),
)

_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_UINT32_MAX = 2**32 - 1


def _rgba_child(node: "EFXValueNode"):
    """一个 OBJECT 节点如果恰好是 `via.Color` 的序列化形状（唯一子键 "rgba"，一个打包
    uint32），返回那个子节点，否则返回 None。见 io_tree.py/panels.py 对这个形状的识别和
    颜色轮 UI，以及 PLAN.md 里对 via.Color 序列化形状的说明（R/G/B/A 是 C# 端的
    [JsonIgnore] 计算属性，不会出现在 JSON 里，真正落盘的只有 rgba 这一个打包字段）。"""
    if node.data_type != "OBJECT" or len(node.children) != 1:
        return None
    child = node.children[0]
    return child if child.key == "rgba" else None


def _get_rgba_color(self) -> tuple:
    child = _rgba_child(self)
    if child is None:
        return (0.0, 0.0, 0.0, 1.0)
    raw = int(child.uint_str) if child.data_type == "BIGINT" else child.int_value
    raw &= _UINT32_MAX
    r = raw & 0xFF
    g = (raw >> 8) & 0xFF
    b = (raw >> 16) & 0xFF
    a = (raw >> 24) & 0xFF
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def _set_rgba_color(self, value) -> None:
    child = _rgba_child(self)
    if child is None:
        return
    r, g, b, a = (max(0, min(255, round(c * 255))) for c in value)
    raw = r | (g << 8) | (b << 16) | (a << 24)
    if raw > _INT32_MAX:
        child.data_type = "BIGINT"
        child.uint_str = str(raw)
    else:
        child.data_type = "INT"
        child.int_value = raw


class EFXValueNode(PropertyGroup):
    """一个 JSON 值的通用容器：标量存对应类型的 slot，OBJECT/ARRAY 递归存 children。"""

    key: StringProperty(
        name="Key",
        description="JSON 属性名（OBJECT 的子节点）或数组下标的字符串形式（ARRAY 的子节点）",
    )
    data_type: EnumProperty(name="Type", items=_DATA_TYPE_ITEMS)
    ui_expand: BoolProperty(
        name="Expand",
        default=True,
        description="仅影响面板显示的折叠状态，不参与导出",
    )

    float_value: FloatProperty(name="Value")
    int_value: IntProperty(name="Value")
    uint_str: StringProperty(name="Value")
    bool_value: BoolProperty(name="Value")
    string_value: StringProperty(name="Value")
    # children 在类体外挂（见下），因为类体内还不能引用 EFXValueNode 自己。

    # 只在这个节点是 via.Color 的序列化形状（见 _rgba_child）时才有意义，面板据此判断要不要
    # 画颜色轮而不是普通的标量 prop() 行——不额外存副本，get/set 直接读写唯一子节点 "rgba"
    # 的打包 uint32，保持"字段树是唯一数据源"（export 仍然只读 children，不读这个属性本身）。
    color_value: FloatVectorProperty(
        name="Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        get=_get_rgba_color, set=_set_rgba_color,
    )


# Blender 递归 PropertyGroup 的标准写法：CollectionProperty(type=...) 需要引用一个已存在的类，
# 不能在类体内自引用，所以先定义类本身，再把递归属性补进去，最后统一注册。必须写进
# __annotations__（而不是普通类属性赋值 EFXValueNode.children = ...）——register_class 只扫描
# __annotations__ 来决定注册哪些 RNA 属性，普通类属性赋值会让 .children 永远停留在
# _PropertyDeferred 占位对象上，实例访问拿到的不是真正的 collection，.add() 直接 AttributeError。
# 已在 Blender 5.1 实测确认。
EFXValueNode.__annotations__["children"] = CollectionProperty(type=EFXValueNode)


def is_rgba_color_node(node: EFXValueNode) -> bool:
    """供 panels.py 判断要不要把这个 OBJECT 节点画成颜色轮而不是普通折叠框。"""
    return _rgba_child(node) is not None


_XYZ_LOWER = ("x", "y", "z")
_XYZ_UPPER = ("X", "Y", "Z")


def xyz_child_order(node: EFXValueNode):
    """一个 OBJECT 节点如果恰好是三分量向量的序列化形状（`Vector3`→大写 X/Y/Z，或
    `Int3`/`PaddedVec3` 这类→小写 x/y/z，见 vendor `RszValueType.cs`），返回按 X/Y/Z 顺序
    排好的三个键名 tuple；否则返回 None。供 panels.py 画成三列并排（对齐姊妹项目 EFX-Editor
    的 XYZ 展示风格），不画成"3 items"折叠框。"""
    if node.data_type != "OBJECT" or len(node.children) != 3:
        return None
    keys = {c.key for c in node.children}
    if keys == set(_XYZ_LOWER):
        return _XYZ_LOWER
    if keys == set(_XYZ_UPPER):
        return _XYZ_UPPER
    return None


def is_static_random_node(node: EFXValueNode) -> bool:
    """一个 OBJECT 节点如果恰好是 `via.Range{s,r}` 的序列化形状（vendor `RszValueType.cs`），
    返回 True。`s`=Static（静态值）、`r`=Random（随机值）——用 REE 惯例命名，不是姊妹项目
    EFX-Editor（MHWI）社区习惯用的 Value/Jitter（这套 REE 命名以后计划回哺到 EFX-Editor，
    是两边统一的方向）。供 panels.py 画成两列并排，不画成"2 items"折叠框。"""
    if node.data_type != "OBJECT" or len(node.children) != 2:
        return False
    return {c.key for c in node.children} == {"s", "r"}


def is_bone_reference_field(node: EFXValueNode, attr_type: str | None) -> bool:
    """一个字符串叶子字段是不是"骨骼父级引用"（vendor `IBoneRelationAttribute.ParentBone`）。

    只按字段 key 结构性判断（key == "ParentBone"），不维护一份硬编码的 attribute 类型清单：
    这个属性名是 C# 接口 `IBoneRelationAttribute` 统一定义的，任何实现了这个接口的 attribute
    类在 JSON 里都会出现这个键，以后 vendor 升级新增实现类也自动覆盖，不用改这里的代码。
    `attr_type` 只用来确认调用方是在画 attribute 的顶层内容字段（不是某个嵌套子对象的
    子字段——理论上不会有别的嵌套结构恰好也叫这个名字，但保持和知识表查询一致的"只在顶层
    生效"约束）。见 docs/TOPLEVEL_STRUCTURE.md "Bones / BoneRelations 结构调研"一节：MHWilds
    实际生效的 4 个实现类分别叫 `EFXAttributeParentOptions`/`Attractor`/`VanishArea3D`/
    `TypeLightning3D`，但字段 key 统一都是 `ParentBone`。
    """
    return attr_type is not None and node.key == "ParentBone" and node.data_type == "STRING"


def _json_scalar_data_type(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT" if _INT32_MIN <= value <= _INT32_MAX else "BIGINT"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, str):
        return "STRING"
    raise TypeError(f"不是标量 JSON 值: {value!r}")


def populate_node(node: EFXValueNode, key: str, value) -> None:
    """把一个 JSON 值填进一个已经 add() 出来的 EFXValueNode 实例（递归处理 dict/list）。"""
    node.key = key
    if isinstance(value, dict):
        node.data_type = "OBJECT"
        for sub_key, sub_value in value.items():
            child = node.children.add()
            populate_node(child, sub_key, sub_value)
    elif isinstance(value, list):
        node.data_type = "ARRAY"
        for index, sub_value in enumerate(value):
            child = node.children.add()
            populate_node(child, str(index), sub_value)
    else:
        dtype = _json_scalar_data_type(value)
        node.data_type = dtype
        if dtype == "FLOAT":
            node.float_value = value
        elif dtype == "INT":
            node.int_value = value
        elif dtype == "BIGINT":
            node.uint_str = str(value)
        elif dtype == "BOOL":
            node.bool_value = value
        elif dtype == "STRING":
            node.string_value = value
        # NULL 不需要任何 slot。


def node_to_value(node: EFXValueNode):
    """把一个 EFXValueNode（含其 children）还原成 Python 原生 dict/list/标量。"""
    dtype = node.data_type
    if dtype == "OBJECT":
        return {child.key: node_to_value(child) for child in node.children}
    if dtype == "ARRAY":
        return [node_to_value(child) for child in node.children]
    if dtype == "FLOAT":
        return node.float_value
    if dtype == "INT":
        return node.int_value
    if dtype == "BIGINT":
        return int(node.uint_str)
    if dtype == "BOOL":
        return node.bool_value
    if dtype == "STRING":
        return node.string_value
    if dtype == "NULL":
        return None
    raise ValueError(f"未知 data_type: {dtype}")


def populate_dict_as_children(collection, mapping: dict) -> None:
    """把一个 dict 的每个键值对，作为顶层子节点填进一个 CollectionProperty（不建外层包装节点）。

    用于 EFX_ATTRIBUTE.efx_fields：attribute 字典本身就是"内容字段的集合"，不需要额外包一层
    OBJECT 根节点。
    """
    for key, value in mapping.items():
        child = collection.add()
        populate_node(child, key, value)


def children_to_dict(collection) -> dict:
    """populate_dict_as_children 的反函数。"""
    return {child.key: node_to_value(child) for child in collection}


# ---------------------------------------------------------------------------
# EFXGroupTag —— Entry 的 Subselect 标签列表
# ---------------------------------------------------------------------------

class EFXGroupTag(PropertyGroup):
    name: StringProperty(name="Group Name")


# ---------------------------------------------------------------------------
# EFXBoneItem —— EFX_ROOT 的文件级命名骨骼表（对应 EfxFile.Bones）
# ---------------------------------------------------------------------------

class EFXBoneItem(PropertyGroup):
    """对应 vendor `EFXBone { name, value }`（`EfxFile.cs:590-596`）。`value` 语义未知
    （不是 nameHash——nameHash 是导出时用 MurMur3 对 name 现算的，value 是独立存的另一个量，
    见 docs/TOPLEVEL_STRUCTURE.md），按"结构性 UI 先做，标注后补"的原则存成十进制字符串而不是
    IntProperty——vendor 声明是 uint32，IntProperty 是有符号 32 位，为了不因为某个样本恰好
    取值超过 2^31-1 就静默截断/报错，用字符串存全量精度，和 EFXValueNode 的 BIGINT 处理是
    同一个考量。"""

    name: StringProperty(name="Bone Name")
    value: StringProperty(name="Value", default="0")


# ---------------------------------------------------------------------------
# 不透明剩余字段 —— 存成 bpy.data.texts 文本块，import/export 两边共用
# ---------------------------------------------------------------------------

def save_opaque(obj: Object, mapping: dict) -> None:
    """把一个 dict 原样存成一个文本块，obj.efx_opaque_text 记录文本块名字。"""
    text_name = f"{obj.name}.opaque.json"
    text = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
    text.clear()
    text.write(json.dumps(mapping, ensure_ascii=False))
    obj.efx_opaque_text = text.name


def load_opaque(obj: Object) -> dict:
    """save_opaque 的反函数。obj.efx_opaque_text 为空则视为没有剩余字段。"""
    if not obj.efx_opaque_text:
        return {}
    text = bpy.data.texts.get(obj.efx_opaque_text)
    if text is None:
        return {}
    return json.loads(text.as_string())


# ---------------------------------------------------------------------------
# Object 级属性注册（挂在 bpy.types.Object 上，四种 ~TYPE 对象按需使用其中一部分）
# ---------------------------------------------------------------------------

_CLASSES = (EFXValueNode, EFXGroupTag, EFXBoneItem)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # EFX_ROOT / EFX_ENTRY / EFX_ACTION / EFX_ATTRIBUTE 通用：原样透传、未建编辑 UI 的剩余
    # 字段，存成一个 bpy.data.texts 文本块，这里只存文本块名字。
    Object.efx_opaque_text = StringProperty(
        name="Opaque JSON",
        description="未建字段级 UI 的剩余键值，原样存成文本块，导出时原样塞回去",
    )

    # EFX_ENTRY/EFX_ACTION/EFX_ATTRIBUTE 通用：记录 import 时在所属列表（Entries/Actions/
    # Attributes）里的原始下标，导出时按这个值排序还原顺序——不依赖 Blender children/collection
    # 的迭代顺序（未必稳定），沿用 EFX-Editor build_local_index_map 的做法。当前阶段没有做
    # 拖拽重排 UI，这个下标只反映 import 时的原始顺序。
    Object.efx_index = IntProperty(name="Original Index")

    # EFX_ENTRY 专属：Subselect 标签（对应 EFXEntry.Groups）。
    Object.efx_groups = CollectionProperty(type=EFXGroupTag)
    Object.efx_groups_active_index = IntProperty()

    # EFX_ROOT 专属：文件级命名骨骼表（对应 EfxFile.Bones）。任何 attribute 的 ParentBone
    # 字段都靠名字引用这里的条目（见 is_bone_reference_field()/panels.py 的 prop_search），
    # 不是裸下标——真正的裸下标表 BoneRelations 完全由 C# 后端导出时重算，见
    # ROOT_STRUCTURAL_KEYS 的说明。
    Object.efx_bones = CollectionProperty(type=EFXBoneItem)
    Object.efx_bones_active_index = IntProperty()

    # EFX_ATTRIBUTE 专属：bookkeeping 标量 + 内容字段树。
    Object.efx_attr_type = StringProperty(
        name="Attribute Type",
        description="原样保存 JSON 的 $type（完整 C# 类名），导出时原样吐回去",
    )
    Object.efx_unique_id = IntProperty(name="UniqueID")
    Object.efx_version = IntProperty(name="Version")
    Object.efx_type_id = IntProperty(name="Type ID")
    Object.efx_is_type_attribute = BoolProperty(name="Is Type Attribute")
    Object.efx_fields = CollectionProperty(type=EFXValueNode)


def unregister():
    del Object.efx_fields
    del Object.efx_is_type_attribute
    del Object.efx_type_id
    del Object.efx_version
    del Object.efx_unique_id
    del Object.efx_attr_type
    del Object.efx_bones_active_index
    del Object.efx_bones
    del Object.efx_groups_active_index
    del Object.efx_groups
    del Object.efx_index
    del Object.efx_opaque_text

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
