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
import math
import struct

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

# IClipAttribute/IMaterialClipAttribute 接口在具体 attribute 类上暴露的只读计算属性
# （`Clip => clipData`/`ClipBits => clipBits`/`MaterialClip => clipData`），纯粹是对同一份
# 数据的只读视图，没有独立内容，也没有 setter（JSON 反序列化用不到它们）。永远从内容字典里
# 剔除，不管这个 attribute 这一轮有没有专属编辑 UI（`is_clip_attribute_dict()` 为 False 的
# IMaterialClipAttribute 实现类走通用树时，也不需要在树里看到这三个键的重复内容）。
ATTRIBUTE_CLIP_VIEW_KEYS = frozenset({"Clip", "ClipBits", "MaterialClip"})

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
# 结构调研"），FieldParameterValues 建成 EFX_ROOT.efx_field_parameters 列表 UI（见
# EFXFieldParameterItem 的说明），UvarGroups 建成 EFX_ROOT.efx_uvar_groups 列表 UI（见
# EFXUvarGroupItem 的说明），ExpressionParameters 建成 EFX_ROOT.efx_expression_parameters
# 列表 UI（见 EFXExpressionParamItem 的说明），其余键原样存进 EFX_ROOT 的 efx_opaque_text。
ROOT_STRUCTURAL_KEYS = frozenset({
    "Entries", "Actions", "EffectGroups", "Bones", "BoneRelations", "FieldParameterValues",
    "UvarGroups", "ExpressionParameters",
})


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


def is_clip_attribute_dict(attr_dict: dict) -> bool:
    """一个 attribute 字典是不是"纯 `IClipAttribute`"（vendor `EfxFile.cs` 里的
    `IClipAttribute`/`IMaterialClipAttribute` 接口，~24 个 `*Clip`/`*MaterialClip` 后缀的
    attribute 类实现，见 docs/TOPLEVEL_STRUCTURE.md "Clip 结构调研"）。只按字段 key 结构性
    判断（`clipData`+`clipBits` 同时存在），不维护硬编码类型清单——原因同
    `is_bone_reference_field()`。

    `IMaterialClipAttribute` 实现类（~9 个）额外带 `mdfProperties`（材质属性哈希关联，本轮
    暂不处理，继续走通用树透传），字段名同样叫 `clipData`/`clipBits`，用
    `clipData` 里有没有 `mdfProperties` 键排除——只有纯 `IClipAttribute`（不是
    `IMaterialClipAttribute`）才会命中这个函数，对应 `EFXClipCurveItem` 编辑 UI。
    """
    if "clipData" not in attr_dict or "clipBits" not in attr_dict:
        return False
    clip_data = attr_dict.get("clipData") or {}
    return "mdfProperties" not in clip_data


def json_float_in(value) -> float:
    """把 EfxBridge dump 出来的一个浮点字段转成真正的 Python float，用于需要真数值控件
    （而不是 EFXValueNode 通用树里那种"当字符串存"）的场景——目前只有 EFXExpressionParamItem
    的 value1/2/3 用到。EfxBridge 用 `JsonNumberHandling.AllowNamedFloatingPointLiterals`
    把 NaN/Infinity/-Infinity 序列化成**带引号的 JSON 字符串**（不是裸 token），
    `json.load` 出来是 Python `str`，不能直接塞进 `FloatProperty`，这里统一转换
    （`float()` 内置支持 "NaN"/"Infinity"/"-Infinity" 这几个词，大小写不敏感）。"""
    return float(value)


def json_float_out(value: float):
    """`json_float_in` 的反函数，导出时用。不能简单指望 Python `json.dump` 处理非有限浮点数——
    它默认给 NaN/Infinity/-Infinity 写裸 token（`allow_nan=True` 的默认行为），但已经用
    `EfxBridge load` 实测证实 C# 端的 `System.Text.Json`（即使开了
    `AllowNamedFloatingPointLiterals`）拒绝裸 token 形式（`'N' is an invalid start of a
    value`），只认带引号的字符串形式——**这不是理论风险，是真实命中过的问题**：vendor
    2026-07-04 升级（`ebb1bc7`）之前，`ExpressionParameter.Color` 把 RGBA 按位重新解释成
    浮点数，`alpha≈255`（最常见的不透明色）叠加 `blue>=128` 就会落进 NaN 的位模式区间，真实
    样本（`11_guide_110` 的好几个 `type=Color` 记录）当时确实命中过。vendor 升级后 `Color`
    改用干净的打包 `rgba` 整数（`EFXExpressionParamItem.rgba_str`），不再触发这个坑，但
    `value1/2/3`（`Float`/`Range`/`Float2` 类型）仍是普通浮点数，理论上仍可能是
    NaN/Infinity，这两个函数继续作为防御性处理保留。"""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


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
# EFXFieldParameterItem —— EFX_ROOT 的文件级具名参数表（对应 EfxFile.FieldParameterValues）
# ---------------------------------------------------------------------------

# EFXFieldParameterValue 除 name 外的其余字段（EfxFile.cs:512-578）。JSON 里这些键始终
# 全部存在——type 只决定二进制读写时走哪个分支、哪些字段真正有意义，不影响 JSON 形状（反射
# 序列化按字段当前值原样落盘，不会因为某个分支没碰到某个字段就在 JSON 里省略它）。
FIELD_PARAMETER_CONTENT_DEFAULTS = {
    "unkn0": 0,
    "fieldParameterNameHash": 0,
    "unkn2": 0,
    "type": 0,
    "unkn4": 0,
    "value_ukn1": 0,
    "value_ukn2": 0,
    "value_ukn3": 0,
    "value_ukn4": 0.0,
    "value_ukn5": 0.0,
    "value_ukn6": 0.0,
    "wilds_unkn0": 0.0,
    "filePath": "",
}


class EFXFieldParameterItem(PropertyGroup):
    """对应 vendor `EFXFieldParameterValue`（`EfxFile.cs:512-578`）。除 `name` 外的其余 13
    个字段（unkn0/fieldParameterNameHash/unkn2/type/unkn4/value_ukn1~6/wilds_unkn0/filePath）
    绝大多数语义未确认——已确认的只有 `type` 决定 `filePath` 是否是一个真实使用的外部资源
    路径（`type in {110,144,183,184,196,202,194,215,217}` 时是矢量场纹理这类资源引用，见
    docs/TOPLEVEL_STRUCTURE.md "FieldParameterValues" 一节），其余数值字段含义不明。

    和 attribute 内容字段一样重用通用 EFXValueNode 树（`fields`），不手写 13 个具名
    PropertyGroup 字段：字段太多、大半语义未知，手写 schema 只会把"不确定"伪装成"确定"，
    通用树才如实反映现状（决策 9）。

    `fieldParameterNameHash` 尤其需要注意：不像同一个文件里 Entry/Action/Bones/
    ExpressionParameter 的 nameHash 那样在导出时被 vendor 用 MurMur3 自动重算（已通读
    EfxFile.cs 全部 MurMur3 调用点确认——`FieldParameterValues.Write()` 只是逐项调用
    DefaultWrite，没有任何 hash 重算逻辑），改了 `name` 必须手动同步这个哈希，本项目目前
    不替用户猜哈希算法（决策 9，同 EFXBoneItem.value 的处理原则），保持完全手动可编辑。
    """

    name: StringProperty(name="Name")
    fields: CollectionProperty(type=EFXValueNode)


# ---------------------------------------------------------------------------
# EFXUvarGroupItem —— EFX_ROOT 的外部 .uvar 引用表（对应 EfxFile.UvarGroups）
# ---------------------------------------------------------------------------

# uvarType 只有两个能在导入后存活的取值——read 阶段对 >2 的值直接 throw（决策 9 的整文件拒绝
# 已经覆盖，不会有第三种值流进 Blender），结构上完全确认（EfxFile.cs:758-776 的
# RszConditional(uvarType == 2) 门控），只是游戏侧真正用途仍是猜测（见
# docs/TOPLEVEL_STRUCTURE.md）。用 EnumProperty 而不是裸 IntProperty，把这个已确认的结构性
# 区分直接体现在下拉框标签上。
_UVAR_TYPE_ITEMS = (
    ("1", "Marker Only", "uvarType == 1：纯标记位，不带 path/group 数据（DD2 见过，"
                          "RE4/DMC5/RERT 恒为 0，MHWilds 未在样本中见过）"),
    ("2", "Named Uvar Reference", "uvarType == 2：引用一个外部 .uvar 文件——path 是文件路径，"
                                   "group 是该文件内的变量组名"),
)


class EFXUvarGroupItem(PropertyGroup):
    """对应 vendor `EFXUvarGroup`（`EfxFile.cs:598-605`）。不是变长列表的自然序列化——vendor
    读时是固定两个 `int` 槽位（`uvarType1`/`uvarType2`），每个非 0 时才追加一条；写时
    `UvarGroups[0]`/`UvarGroups[1]` 对应"槽位 1"/"槽位 2"（`EfxFile.cs:1001-1011`），完全按
    列表下标而不是按 `uvarType` 取值配对——如果原文件"槽位 1 为空、槽位 2 有值"，读出来的
    `UvarGroups` 列表只有一条（下标 0），vendor 自己写回时会把它归到"槽位 1"，原始槽位归属信息
    在 vendor 自己的读写往返里就已经丢失（和 EfxBridge.Program.cs 头部注释里 CollisionEffect
    下标重排是同一类"解码成干净模型、总是重新生成字节"的哲学，语义等价、字节不同，不是
    bug）——所以 Blender 侧不需要，也不可能，保留"槽位 1 vs 槽位 2"这个身份，只需要维护一个
    最多 2 项的有序列表，交给 vendor 写出时按下标重新分配槽位。

    `path`/`group` 是 `RszConditional(uvarType == 2)` 门控字段，`uvarType == 1` 时 vendor
    压根不读/不写它们（值是多少不影响导出字节），Blender 侧不做特殊清空，只在面板上按
    `uvar_type` 隐藏这两行输入框，减少误导（免得用户以为"标记位"槽位也能填路径）。
    """

    uvar_type: EnumProperty(name="Type", items=_UVAR_TYPE_ITEMS, default="2")
    path: StringProperty(name="Path")
    group: StringProperty(name="Group")


# ---------------------------------------------------------------------------
# EFXExpressionParamItem —— EFX_ROOT 的公式引擎具名参数表
# （对应 EfxFile.ExpressionParameters）
# ---------------------------------------------------------------------------

# EfxFile.cs:69-87 的 EfxExpressionParameterType 枚举，四个取值语义均已由 vendor 注释+真实
# 样本确认到"数据形状"这一层（哪几个字段生效），游戏侧真正用途仍是猜测（Range/Float2 的具体
# 含义见下方 tooltip，不确定的部分只放在 tooltip 里，不写进下拉框标签）。标识符直接用 vendor
# 枚举成员的字面量名字（"Float"/"Color"/"Range"/"Float2"）而不是数字下标——2026-07-04 vendor
# 升级（`ebb1bc7`）后 JSON 的 `type` 键本身就是这个字符串（`Enum.ToString()`/`Enum.Parse<T>`），
# 标识符和 JSON 值完全一致，import/export 不需要在数字下标和字符串之间来回换算。
_EXPR_PARAM_TYPE_ITEMS = (
    ("Float", "Float", "type == Float：单个浮点值，value1 生效，value2/value3 未用"),
    ("Color", "Color", "type == Color：value 是一个打包 uint32 RGBA（`via.Color.rgba`，"
                        "存进 rgba_str），不占用 value1/2/3"),
    ("Range", "Range", "type == Range：value1/value2/value3 三个浮点值都生效。vendor 注释"
                        "推测是{初始值, 最小值, 最大值}（X 总是落在 Y-Z 区间内），未证实"),
    ("Float2", "Float2", "type == Float2：value1/value2 两个浮点值生效，value3 未用。"
                          "vendor 注释里样本只见过 0.0/1.0，疑似布尔语义，未证实"),
)

_UINT32_MASK = 2**32 - 1


def _get_expr_param_color(self) -> tuple:
    raw = int(self.rgba_str or "0") & _UINT32_MASK
    r = raw & 0xFF
    g = (raw >> 8) & 0xFF
    b = (raw >> 16) & 0xFF
    a = (raw >> 24) & 0xFF
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def _set_expr_param_color(self, value) -> None:
    r, g, b, a = (max(0, min(255, round(c * 255))) for c in value)
    raw = r | (g << 8) | (b << 16) | (a << 24)
    self.rgba_str = str(raw)


class EFXExpressionParamItem(PropertyGroup):
    """对应 vendor `EFXExpressionParameter`（`EfxFile.cs:400-448`，2026-07-04 vendor 升级到
    `ebb1bc7` 后 JSON 形状整个变了，这份 docstring 对应新形状——旧形状的调研过程和踩坑记录见
    `docs/TOPLEVEL_STRUCTURE.md` "vendor 升级"一节，不在这里重复）。

    新形状只有 3 个键：`type`（字符串，`"Float"`/`"Color"`/`"Range"`/`"Float2"`）、`name`、
    `value`（形状由 `type` 决定：`Float` 是裸数字；`Float2` 是 `{X, Y}`；`Range` 是
    `{X, Y, Z}`；`Color` 是 `{rgba: uint32}`，和 `via.Color` 完全一样的打包整数，不再是旧版本
    那种"把浮点数值按位重新解释成 RGBA"的猜谜手法）。两个具名哈希字段
    （`expressionParameterNameUTF16Hash`/`expressionParameterNameUTF8Hash`）在新版本里连 JSON
    都不出现了——vendor 自定义的 `EFXExpressionParameterJsonConverter` 读到 `name` 时就地用
    MurMur3 算好存进内存对象，写的时候压根不输出这两个键，Blender 侧不需要处理，也不需要像
    旧版本那样占位填 0。

    `value1`/`value2`/`value3` 继续用真正的 `FloatProperty`（不是 `EFXValueNode` 通用树）——
    形状简单固定、语义已知，值得做成真数值控件。`Color` 类型改用 `rgba_str`（十进制字符串，
    同 `EFXBoneItem.value` 的 BIGINT-safe 惯例）而不是复用 `value1`：新版本的 `rgba` 已经是
    一个干净的打包 uint32，不再需要"浮点数按位重新解释"这个技巧，也就不再有旧版本那个真实
    命中过的坑——RGBA 按位重解释成浮点数时，`alpha≈255` 叠加 `blue>=128` 就会落进 NaN 位模式
    区间（`11_guide_110` 的 `colorR_N/P/D/T` 四条记录当时就是这样），而 EfxBridge 把 NaN 存成
    带引号字符串、Python `json.dump` 默认写裸 token 两者不兼容，是上一版本必须用
    `model.json_float_in/out` 显式转换的唯一原因。新版本 `Color` 完全不经过浮点数，`rgba_str`
    只是一个整数的字符串表示，天然没有这个问题；`json_float_in/out` 仍然保留，供
    `value1`/`value2`/`value3`（`Float`/`Range`/`Float2` 类型）使用——这几个字段本质上还是
    普通浮点数，理论上仍可能是 NaN/Infinity（只是目前的真实样本没有命中过），继续做防御性处理
    符合决策 9"不确定就别自作主张排除"的精神。
    """

    name: StringProperty(name="Name")
    param_type: EnumProperty(name="Type", items=_EXPR_PARAM_TYPE_ITEMS, default="Float")
    value1: FloatProperty(name="Value 1")
    value2: FloatProperty(name="Value 2")
    value3: FloatProperty(name="Value 3")
    rgba_str: StringProperty(name="RGBA", default="0")
    color_value: FloatVectorProperty(
        name="Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        get=_get_expr_param_color, set=_set_expr_param_color,
    )


# ---------------------------------------------------------------------------
# EFXClipCurveItem / EFXClipKeyframeItem —— IClipAttribute 的动画曲线编辑（挂在 EFX_ATTRIBUTE
# 对象上，不是 EFX_ROOT——每个 Clip attribute 有自己独立的一份，不是文件级共享表）
# ---------------------------------------------------------------------------

# EfxClipPlaybackType（ClipSubstructs.cs:7-12）。vendor 注释原文只是猜测（"might be coded as
# a Playback / loop trigger flag enum"），结构上 4 个取值完全确认，游戏侧真正含义不确认——
# 分开标注，不写进下拉框标签本身。
_CLIP_LOOP_TYPE_ITEMS = (
    ("-1", "Looping", "loopType == -1：vendor 注释推测『一切都触发循环』，未证实"),
    ("0", "Unknown", "loopType == 0：语义未知"),
    ("2", "NonLooping", "loopType == 2：vendor 注释推测『都不触发循环』（手动控制？），未证实"),
    ("4", "Type4", "loopType == 4：语义未知"),
)

# FrameInterpolationType（ClipSubstructs.cs:33-44）。vendor 注释坦承"这是不是插值方式本身都是
# 猜的"，只有 Bezier（5）有强证据支持（带额外的切线数据段）。
_CLIP_INTERP_TYPE_ITEMS = (
    ("0", "Unknown", "type == 0：语义未知"),
    ("1", "Type1", "vendor 注释：只在关键帧列表末尾出现过"),
    ("2", "Type2", "vendor 注释：在首/中/末帧都出现过，也见过全 2 的列表；EfxClipFrame 的"
                    "默认构造值"),
    ("3", "Type3", "type == 3：语义未知"),
    ("5", "Bezier", "大概率是贝塞尔曲线插值——带独立的切线数据段（interpolationData），是唯一"
                     "有结构性证据支持插值方式这个猜测的取值"),
    ("13", "Type13", "type == 13：仅在 DMC5 样本见过"),
)

# ClipValueType（ClipSubstructs.cs:14-18）。
_CLIP_VALUE_TYPE_ITEMS = (
    ("3", "Int", "关键帧数值按整数存取（EfxClipFrame.IntValue）"),
    ("5", "Float", "关键帧数值按浮点数存取（EfxClipFrame.FloatValue），目前样本里唯一见过的"
                    "取值"),
)


def int_bits_to_float(value: int) -> float:
    """把一个 int 的位模式重新解释成 float。`EfxClipFrame`（`ClipSubstructs.cs:46-76`）只有
    一个私有字段 `value`，`IntValue`/`FloatValue` 是对同一份存储的两种视图——但
    `IntValue` 的 setter 有一个真实的 vendor 侧 bug：`set => BitConverter.
    Int32BitsToSingle(value)`，C# 属性 setter 的隐式参数刚好也叫 `value`，和私有字段同名，
    这行代码算出了转换结果却忘了赋值回私有字段（应该是 `this.value = ...`），是一个纯粹的
    no-op——**通过 `IntValue` 赋值完全不生效**。导出 `ClipValueType.Int` 类型的关键帧时，
    只能自己做这个位转换，写进 `FloatValue`（它的 setter 是对的：`this.value = value`）。
    `IntValue` 的 getter 本身没问题，导入时直接读没问题。"""
    return struct.unpack("<f", struct.pack("<i", value))[0]


class EFXClipKeyframeItem(PropertyGroup):
    """对应 `EfxClipFrame`（一个关键帧）+ 命中 `Bezier` 插值时的
    `EfxClipInterpolationTangents`（切线，`ClipSubstructs.cs:81-89`，只在
    `interp_type == "5"` 时才在文件里真实存在，见 `EfxClipData.ParseClip()`——按 frame 出现
    顺序和"是不是 Bezier"筛出的并行数组，不是按下标对齐）。

    `value` 统一用 `FloatProperty` 存（不管 `ClipValueType` 是 Int 还是 Float）——Int 类型时
    存整数的浮点表示（如 `1.0`），导出时四舍五入取整再按位转换成 `FloatValue`
    （见 `int_bits_to_float()`），没有必要为了一个大概率是小整数/布尔语义的字段单独维护一个
    `IntProperty`。
    """

    frame_time: FloatProperty(name="Time")
    interp_type: EnumProperty(name="Interpolation", items=_CLIP_INTERP_TYPE_ITEMS, default="2")
    value: FloatProperty(name="Value")
    tangent_out_x: FloatProperty(name="Out X")
    tangent_out_y: FloatProperty(name="Out Y")
    tangent_in_x: FloatProperty(name="In X")
    tangent_in_y: FloatProperty(name="In Y")


class EFXClipCurveItem(PropertyGroup):
    """对应 `EfxClipData` 里的一条子曲线（`clips[]` 里的一项 + 它自己的一段 `frames[]`）。
    子曲线的身份是"驱动 `ClipBits` 里的哪一位"（`bit_index`，0-based，和 JSON `clipBits.bits`
    数组、`BitSet.HasBit()`/`SetBit()` 的下标语义完全一致——vendor 源码里 `BitNameDict` 初始化
    语法虽然是 1-based（`[1] = nameof(field)`），那只是给 C# 代码作者的书写便利，内部存储
    (`BitSet.BitNames[i]`）和这里的 `bit_index` 都是 0-based，不要和 `BitNameDict` 的 key
    弄混）。子曲线数组下标和排序后的置位 bit 下标一一对应（vendor `BitSet.
    GetBitInsertIndex()`就是算这个映射用的），所以 Blender 侧不单独维护一份"启用哪些 bit"的
    勾选列表——加一条曲线就是启用一个 bit，删一条曲线就是关闭它，两者是同一件事，见
    `io_tree.py` 的说明。

    `bit_name` 纯展示用，不参与导出——`BitNames` 是 vendor C# 类字段初始化时硬编码的常量
    （比如 `expressionBits = new BitSet(6) { BitNameDict = {...} }`），不是文件自己的数据，
    `BitSet` 的二进制读写（`DoRead`/`DoWrite`）也只处理 `Bits` 这个整数数组，`BitNames`
    对导出字节没有任何影响，纯粹是给人看的标签，能拿到就存，拿不到就空着。
    """

    bit_index: IntProperty(name="Bit Index", min=0)
    bit_name: StringProperty(name="Bit Name")
    value_type: EnumProperty(name="Value Type", items=_CLIP_VALUE_TYPE_ITEMS, default="5")
    keyframes: CollectionProperty(type=EFXClipKeyframeItem)
    keyframes_active_index: IntProperty()


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

_CLASSES = (
    EFXValueNode, EFXGroupTag, EFXBoneItem, EFXFieldParameterItem, EFXUvarGroupItem,
    EFXExpressionParamItem, EFXClipKeyframeItem, EFXClipCurveItem,
)


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

    # EFX_ROOT 专属：文件级具名参数表（对应 EfxFile.FieldParameterValues），见
    # EFXFieldParameterItem 的说明。
    Object.efx_field_parameters = CollectionProperty(type=EFXFieldParameterItem)
    Object.efx_field_parameters_active_index = IntProperty()

    # EFX_ROOT 专属：外部 .uvar 引用表（对应 EfxFile.UvarGroups），最多 2 项，见
    # EFXUvarGroupItem 的说明。
    Object.efx_uvar_groups = CollectionProperty(type=EFXUvarGroupItem)
    Object.efx_uvar_groups_active_index = IntProperty()

    # EFX_ROOT 专属：公式引擎具名参数表（对应 EfxFile.ExpressionParameters），见
    # EFXExpressionParamItem 的说明。
    Object.efx_expression_parameters = CollectionProperty(type=EFXExpressionParamItem)
    Object.efx_expression_parameters_active_index = IntProperty()

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

    # EFX_ATTRIBUTE 专属，只在 is_clip_attribute_dict() 命中时有意义：IClipAttribute 的动画
    # 曲线（对应 clipData/clipBits），见 EFXClipCurveItem/EFXClipKeyframeItem 的说明。
    # efx_is_clip_attribute 是持久标记，不靠"curves 是不是空"判断——bit 全部关闭（0 条曲线）
    # 也是合法状态，导出时仍需要正确写出空的 clipData/clipBits，不能被误判成"这不是 Clip
    # attribute，直接走通用树"。
    Object.efx_is_clip_attribute = BoolProperty(name="Is Clip Attribute")
    Object.efx_clip_bit_count = IntProperty(
        name="Bit Count",
        description="ClipBits 的总位数，由 attribute 类型固定（如 Transform3DClip 是 9），"
                    "导入时原样记录，不可编辑",
    )
    Object.efx_clip_loop_type = EnumProperty(
        name="Loop Type", items=_CLIP_LOOP_TYPE_ITEMS, default="0",
    )
    Object.efx_clip_curves = CollectionProperty(type=EFXClipCurveItem)
    Object.efx_clip_curves_active_index = IntProperty()


def unregister():
    del Object.efx_clip_curves_active_index
    del Object.efx_clip_curves
    del Object.efx_clip_loop_type
    del Object.efx_clip_bit_count
    del Object.efx_is_clip_attribute
    del Object.efx_fields
    del Object.efx_is_type_attribute
    del Object.efx_type_id
    del Object.efx_version
    del Object.efx_unique_id
    del Object.efx_attr_type
    del Object.efx_expression_parameters_active_index
    del Object.efx_expression_parameters
    del Object.efx_uvar_groups_active_index
    del Object.efx_uvar_groups
    del Object.efx_field_parameters_active_index
    del Object.efx_field_parameters
    del Object.efx_bones_active_index
    del Object.efx_bones
    del Object.efx_groups_active_index
    del Object.efx_groups
    del Object.efx_index
    del Object.efx_opaque_text

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
