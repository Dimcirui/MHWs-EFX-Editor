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
import re
import struct

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    IntVectorProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Collection, Object, PropertyGroup

from . import attribute_types, i18n

# ---------------------------------------------------------------------------
# ~TYPE 常量
# ---------------------------------------------------------------------------

# 带 `EFX_RE_` 前缀，不能再叫裸的 "EFX_ROOT"/"EFX_ENTRY"/...——`"~TYPE"` 是 Blender 的裸
# ID-property key，不按插件分命名空间，姊妹项目 EFX-Editor（MHWI）用的就是这几个一模一样的
# 裸字符串（`root_collection.py`/`io_tree.py` 等）。两个插件同时装着时，选中姊妹项目建的对象，
# 这边的 `obj.get("~TYPE") == model.TYPE_ENTRY` 之类判断会因为值刚好相等而误判成自己的对象
# （2026-09-10 用户实测复现）。加前缀是唯一花小代价就能修的办法——所有调用点都经过这几个
# 常量（没有裸写字面量的），改这里就够。故意不改 `"~TYPE"` 这个 key 本身：两个插件的 `"~TYPE"`
# key 相同但值不同之后就不会再撞，键名再加前缀是锦上添花，不是必须。
TYPE_ROOT = "EFX_RE_ROOT"
TYPE_ENTRY = "EFX_RE_ENTRY"
TYPE_ACTION = "EFX_RE_ACTION"
TYPE_ATTRIBUTE = "EFX_RE_ATTRIBUTE"
# 导入时一并拉进来的网格放的那个集合（`asset_link._meshes_collection()`）。不是 EFX 数据的
# 一部分，只是大纲视图里的归拢；导出完全不看它（`export_root_to_efxfile()` 只走
# `root_entries()` / `root_actions()`）。
TYPE_MESH_GROUP = "EFX_RE_MESHES"

# 新建空白 EFX 时 Header 需要的两个字段。只有这两个——2026-09-10 拿语料里最小的真实空文件
# （11_evc0023_50_039.efx.5571972，56 字节，Entries/Actions/... 全空）跟纯手写的裸 JSON 逐字节
# 比对过：Version 之外，`dimensionType` 不会被 C# 侧 `UpdateHeaderData()` 重算（entryCount 等
# 计数字段会），C# 默认值是 0，但 MHWs 语料恒为 1，漏填不会报错、会静默产出语义错误的文件
# （vendor 注释：`1 = 3D, 0 = 2D`）。别的 Header 字段全部由 DoWrite() 按内容重算，不需要在这里
# 补。见 vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EfxFile.cs `EfxHeader.dimensionType` 声明处的
# 原始注释。
MHWILDS_EFX_VERSION = 5571972  # = vendor EfxVersion.MHWilds
MHWILDS_EFX_DIMENSION_TYPE = 1

# attribute 里引用外部资源的路径字段名。同一件事在不同 attribute 变体里叫法不同：
# `EFXAttributeTypeMeshV2`/`TypeGpuMesh` 用大写开头的 `MeshPath`/`MaterialPath`
# （EfxTypeMesh.cs:125/127、:400/402），更老的 `EFXAttributeTypeMesh`/`TypeGpuMeshTrail`
# 用小写的 `meshPath`/`mdfPath`（同文件 :52/:53、:537/:539）。**按字段名判断，不按类名**
# ——同一套路径字段挂在好几个类上，写死类名只会漏。
#
# MHWs 实测（2026-09-13，语料里 3089 个引用 mesh 的文件中随机抽 70 个 / 213 个实例）：
# 命中的 key 只有 `MeshPath`，类型只有 `EFXAttributeTypeMeshV2`（152）和
# `EFXAttributeTypeGpuMesh`（61），`MaterialPath` 213/213 全部非空，而
# `MirrorMeshPath` 213/213 全部为空——所以 asset_link.py 只跟主 mesh 路径，不跟镜像那条。
MESH_PATH_KEYS = ("MeshPath", "meshPath")
MATERIAL_PATH_KEYS = ("MaterialPath", "mdfPath")
UVS_PATH_KEY = "UVSPath"


def short_attr_name(attr_type: str) -> str:
    """`ReeLib.Efx.Structs.Main.EFXAttributeUnitCulling` -> `UnitCulling`（纯展示用，不影响
    导出）。定义在这里（不是 io_tree.py）是因为 `_sync_object_name()` 也要用它——model.py 是
    io_tree.py 的依赖方向上游，不能反过来 import io_tree。"""
    short = attr_type.rsplit(".", 1)[-1]
    if short.startswith("EFXAttribute"):
        short = short[len("EFXAttribute"):]
    return short or attr_type


# ---------------------------------------------------------------------------
# Entry 显示名后缀——对齐姊妹项目 EFX-Editor 的 renderer_suffix()（其 efx_format/
# categories.py），"不展开子对象即可看出 entry 的表现风格"，如 " (Mesh)" / " (Mesh, PtLife)"。
#
# 和姊妹项目的关键差异：MHWI 没有类型化对象模型，只能手工维护一份 SUFFIX_DISPLAY_TYPES 白名单
# （渲染 Body 的具体类型名逐个列出来）。MHWs 这边 vendor 自己算出了 `IsTypeAttribute`
# （`EFXAttribute.IsTypeAttribute => type.ToString().StartsWith("Type") && 不是 Clip/Expression
# 变体`，见 EfxFile.cs:181，一个 Entry 至多一个），已经原样存在 `Object.efx_is_type_attribute`
# 上（见下方 register()），suffix 的"渲染主体"那部分直接读这个字段就行，不需要重新维护一份类型名
# 白名单。
#
# PtLife/PtColliderAction 是"触发类" attribute（对应姊妹项目 SUFFIX_DISPLAY_TYPES 里的
# "Action Trigger" 分组：PTCOLLISION/PTLIFE），本轮只加这两个——MHWs vendor 下同族还有
# PtCollision/PtLightningColliderAction/PtBehavior 等，语义/取舍未逐一核实，先按需加，不为了
# "看齐姊妹项目"就把整个 Pt* 家族一次性搬过来。
ENTRY_SUFFIX_PT_TYPES = frozenset({"PtLife", "PtColliderAction"})


def entry_display_suffix(attrs) -> str:
    """`attrs`：按 entry 内原始顺序排列的 `(short_type_name, is_type_attribute)` 二元组序列
    （`short_type_name` 已经过 `short_attr_name()` 处理）。返回形如 `" (Mesh, PtLife)"` 的后缀，
    一个都不命中时返回空串。

    `is_type_attribute` 命中时去掉字面量前缀 `"Type"`（`"TypeMesh"` -> `"Mesh"`），因为这个前缀
    只是 vendor 用来标记"这是类型判定属性"的命名约定，不是要展示给用户看的类型名本身
    （姊妹项目对应显示的也是 `"Mesh"`，不是 `"TypeMesh"`）。
    """
    names = []
    for short_name, is_type_attr in attrs:
        if is_type_attr:
            names.append(short_name[len("Type"):] if short_name.startswith("Type") else short_name)
        elif short_name in ENTRY_SUFFIX_PT_TYPES:
            names.append(short_name)
    return " (%s)" % ", ".join(names) if names else ""


def _entry_attribute_suffix_pairs(entry_obj: Object):
    """从一个 EFX_ENTRY 对象现存的 EFX_ATTRIBUTE 子对象里，按 `efx_index` 排序读出
    `entry_display_suffix()` 要的 `(short_type_name, is_type_attribute)` 序列。供
    `refresh_entry_display_name()`/`_sync_object_name()` 在结构编辑（增删 attribute）或改名后
    重新计算后缀用——不能像 io_tree.build_entry_object() 那样直接读 JSON dict（那时子对象还没
    建出来，或者已经不是刚导入时的那一批了），只能改成扫当前场景里真实存在的子对象。"""
    children = [o for o in entry_obj.children if o.get("~TYPE") == TYPE_ATTRIBUTE]
    children.sort(key=lambda o: o.efx_index)
    return [(short_attr_name(o.efx_attr_type), o.efx_is_type_attribute) for o in children]


def refresh_entry_display_name(entry_obj: Object | None) -> None:
    """按 `entry_obj` 当前的 `efx_index`/`efx_name`/attribute 子对象重新计算并写回它的显示名：
    `[三位序号] {efx_name}{后缀}`（未命名 entry 就是 `[三位序号] Entry`，不算后缀——后缀本来
    就是给"看得出类型"用的，没名字的占位 entry 强调类型意义不大）。方括号而不是下划线拼接，
    是为了不让人误以为序号是 `efx_name` 本身的一部分（2026-09-10 改）。

    只对 `~TYPE == EFX_ENTRY` 生效，其余类型（包括 None）直接跳过——调用方（structure_ops.py/
    copy_paste.py 的增删/粘贴 attribute 算子、`_renumber()`）不需要先判断父对象是 Entry 还是
    Action 再决定要不要调用这个函数。

    序号前缀是 2026-09-10 加的：Blender Outliner 按对象名字母序排列，不看 `efx_index`，Entry
    一多、或者用户自己把某个 entry 改了名字，Outliner 里看到的顺序就跟真实导出顺序（只认
    `efx_index`）对不上，容易让人误以为"entry 顺序乱了"。固定宽度数字前缀 + `_renumber()`
    每次重排后都调这个函数刷新，保证 Outliner 顺序始终等于真实顺序——不管 entry 叫什么名字、
    有没有名字。
    """
    if entry_obj is None or entry_obj.get("~TYPE") != TYPE_ENTRY:
        return
    prefix = f"[{entry_obj.efx_index:03d}] "
    if entry_obj.efx_name:
        target = f"{prefix}{entry_obj.efx_name}{entry_display_suffix(_entry_attribute_suffix_pairs(entry_obj))}"
    else:
        target = f"{prefix}Entry"
    if entry_obj.name != target:
        entry_obj.name = target


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

# EFXEntry 字典里，Attributes 单独按子对象处理，Groups 单独做成可编辑标签列表，entryAssignment
# 单独做成下拉框（见下方 ENTRY_ASSIGNMENT_ITEMS），其余键原样存进 efx_opaque_text，不建编辑 UI
# （当前阶段的结构骨架不覆盖）。
# index 曾经单独排除、导出时按数组位置重新赋值，理由是"EFXEntry.DoWrite() 原样写字段值，
# 不像 EffectGroups 那样反推重算，删除 Entry 后会错位"——这个假设已用真实 MHWs 样本证伪
# （2026-07-03，Blender 5.1 实测）：11_guide_110 的 11 个顶层 Entries，index 字段值是
# {1,32,28,29,27,33,10,9,8,7,31}，与数组位置 0-10 完全不对应；EffectGroups.efxEntryIndexes
# （如 [9,8,7,6,3,2,1,4,5]）实测才是真正按数组位置引用，说明 index 字段是某种独立于数组位置的
# 标识（推测是权威制作工具的创建序号，语义未知），按数组位置强行重算反而会在完全没有编辑的
# 往返里就篡改这个字段。按决策 9"不确定就别自作主张改写"的精神，改为和其余未知字段一样原样
# 透传，不在导出时重算。删除 Entry 后 index 是否需要重新分配，等确认其真实语义后再决定。
ENTRY_STRUCTURAL_KEYS = frozenset({"Attributes", "Groups", "entryAssignment", "name"})
ACTION_STRUCTURAL_KEYS = frozenset({"Attributes", "name"})

# EfxEntryEnum（EfxFile.cs:169-174）——2026-09-10 实测确认这是"Groups 标签能不能生效"的真正
# 开关：一个真实样本（11_it11_030.efx.5571972）里，用户手动新建/复制出来的 3 个 Entry 虽然
# `Groups` 标签和 `EffectGroups[].efxEntryIndexes` 都正确指向它们，但 `entryAssignment` 是
# `NoAssignment`（2）——跟同组里所有正常生效的兄弟 Entry（清一色 `AssignToCollisionEffect`，
# 0）不一样，游戏侧大概率是靠这个字段决定"这个 Entry 到底要不要参与 EffectGroups 分组逻辑"，
# 单纯挂 Groups 标签不够。这个字段之前完全没有编辑 UI（落在 opaque 透传里，用户在面板上根本
# 看不见、改不了），是真正的产品缺陷，不只是"语义未知不建 UI"那种保守策略——3 个取值都有
# vendor 自己给的明确名字，不是靠猜的，值得建成下拉框。`bridge.new_entry()` 造出来的空白
# Entry 默认就是 0（AssignToCollisionEffect），跟其它能正常生效的 Entry 一致，不用改
# EFX_RE_OT_entry_add；这个下拉框主要是给"通过复制/粘贴得到、又不小心继承了错误值"的 Entry
# 一个能看见、能改回来的地方。
ENTRY_ASSIGNMENT_ITEMS = (
    ("0", "AssignToCollisionEffect", "参与 EffectGroups/Groups 逻辑——正常生效的 Entry 都是这个值"),
    ("1", "Root", "根 Entry（文件里通常只有一个）"),
    ("2", "NoAssignment", "不参与任何分组逻辑——即使挂了 Groups 标签也不会生效"),
)

# EfxFile 顶层字典里，Entries/Actions 单独按子对象处理，Bones 建成 EFX_ROOT.efx_bones 列表
# UI，BoneRelations 整体不透传（导出时固定输出空数组，靠 C# 后端从每个 attribute 的
# ParentBone + Bones 表反向重建下标，见 docs/TOPLEVEL_STRUCTURE.md "Bones / BoneRelations
# 结构调研"），FieldParameterValues 建成 EFX_ROOT.efx_field_parameters 列表 UI（见
# EFXFieldParameterItem 的说明），UvarGroups 建成 EFX_ROOT.efx_uvar_groups 列表 UI（见
# EFXUvarGroupItem 的说明），ExpressionParameters 建成 EFX_ROOT.efx_expression_parameters
# 列表 UI（见 EFXExpressionParamItem 的说明），其余键原样存进 EFX_ROOT 的 efx_opaque_text。
#
# **EffectGroups 不在这个排除集合里**——2026-09-09 实测证伪了"整体不透传、导出时传空数组让
# C# 后端从 Entry.Groups 反向全量重建"这个此前的既定做法：`UpdateEffectGroups()`
# （EfxFile.cs:1302）按 Entry 下标扫描顺序重建 EffectGroups 数组，这个顺序和原文件里的存储
# 顺序未必一致（原作者的排列顺序看起来和 Entry 下标无关），而游戏内实测证实**这个数组的
# 顺序本身是有意义的**——武器动作表大概率按数组下标（不是按名字/哈希）引用 EffectGroups，
# 顺序一变引用就指错。所以 EffectGroups 现在放行到 leftover，跟着走 `save_opaque()` 原样
# 存一份"导入时的原始顺序"；导出时 io_tree.export_root_to_efxfile() 默认保留这个原始顺序，
# 只靠 C# 后端更新每个已匹配组的 efxEntryIndexes 内容（这部分是无序的成员集合，重排安全，
# 已有先例——Phase 0 验证过 CollisionEffect.efxEntryIndex[] 同类重排语义等价），新增的组
# 追加在末尾，删空的组保留原位置但 efxEntryIndexes 清空——都是 C# 后端 UpdateEffectGroups()
# 自己已有的行为，我们只是不再用空数组去触发它的"全量重建顺序"分支。
# `EFX_RE_OT_export.reorder_effect_groups`（默认关闭）是逃生舱：万一以后真的需要恢复"按
# Entry 下标重新排列"这个老行为，勾上它、导出时传空数组即可，不用改代码。
ROOT_STRUCTURAL_KEYS = frozenset({
    "Entries", "Actions", "Bones", "BoneRelations", "FieldParameterValues",
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


_FLOAT4_KEYS = ("X", "Y", "Z", "W")


def float4_children(node: "EFXValueNode"):
    """一个 OBJECT 节点如果恰好是 `Vector4` 的序列化形状（X/Y/Z/W 四个浮点子键），返回
    `{键: 子节点}`，否则 None。目前只有 `MdfProperty.value` 用得上（材质参数那个 float4）。"""
    if node.data_type != "OBJECT" or len(node.children) != 4:
        return None
    by_key = {child.key: child for child in node.children}
    if set(by_key) != set(_FLOAT4_KEYS):
        return None
    if any(by_key[key].data_type != "FLOAT" for key in _FLOAT4_KEYS):
        return None
    return by_key


def _get_float4_color(self) -> tuple:
    by_key = float4_children(self)
    if by_key is None:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(by_key[key].float_value for key in _FLOAT4_KEYS)


def _set_float4_color(self, value) -> None:
    by_key = float4_children(self)
    if by_key is None:
        return
    for key, component in zip(_FLOAT4_KEYS, value):
        by_key[key].float_value = component


# PtBehaviorVariable 里 vendor 自己的 PtBehaviorPropType 枚举不认识的 dataType，落进
# `PtBehaviorVariableDataPrefabUnknown` 的兜底形状：一个不透明字节块，JSON 里序列化成
# `variable.data`（base64 字符串）。这几个 get/set 不是猜出来的——2026-09-19 用
# `EfxBridge ptbehaviorcatalog` 的 `byRawDataType` 统计扫过全语料（9175/9221 个文件），
# 按 dataType 数值分组看 `variable.size`（字节数）和实际数值分布，只对**全语料字节数恒定
# 且解出来的数值明显合理**（小整数、或者按 int32 读会是天文数字但按 float32 读是正常范围）
# 的几个数值开放紧凑编辑；`_UNKNOWN_DATATYPE_SHAPES`（panels.py）记着每一条的取证依据。
def _unknown_data_child(node: "EFXValueNode"):
    """一个 OBJECT 节点如果是 `PtBehaviorVariableDataPrefabUnknown` 的序列化形状（含 `data`
    这个 base64 字符串子键），返回那个子节点，否则 None。"""
    if node.data_type != "OBJECT":
        return None
    return find_field(node.children, "data")


def unknown_data_byte_length(node: "EFXValueNode") -> int | None:
    """`variable.data` 解码之后的字节数；解不出来（不是这个形状/不是合法 base64）返回
    `None`。panels.py 用它核对"这条数据的实际长度是不是正好等于某个已知形状需要的字节数"
    ——长度对不上就不提供紧凑编辑，回退到通用展开区，不猜、不截断、不补零。
    """
    import base64

    child = _unknown_data_child(node)
    if child is None or child.data_type not in ("STRING", "NULL"):
        return None
    try:
        return len(base64.b64decode(child.string_value or ""))
    except (ValueError, TypeError):
        return None


def _get_unknown_packed(node: "EFXValueNode", fmt: str) -> tuple:
    import base64
    import struct

    child = _unknown_data_child(node)
    count = len(fmt)
    if child is None or child.data_type not in ("STRING", "NULL"):
        return (0,) * count
    try:
        raw = base64.b64decode(child.string_value or "")
    except (ValueError, TypeError):
        return (0,) * count
    needed = struct.calcsize("<" + fmt)
    if len(raw) != needed:
        # 长度对不上：面板侧本来就已经用 unknown_data_byte_length() 核对过才会画出这个
        # 控件，这里只是双重保险，不该发生——发生了就返回全零而不是拿越界字节猜，不伪造数据。
        return (0,) * count
    return struct.unpack("<" + fmt, raw)


def _set_unknown_packed(node: "EFXValueNode", values, fmt: str) -> None:
    import base64
    import struct

    child = _unknown_data_child(node)
    if child is None:
        return
    packed = struct.pack("<" + fmt, *values)
    if child.data_type == "NULL":
        child.data_type = "STRING"
    child.string_value = base64.b64encode(packed).decode("ascii")


def _get_unknown_int32(self) -> int:
    return _get_unknown_packed(self, "i")[0]


def _set_unknown_int32(self, value: int) -> None:
    _set_unknown_packed(self, (value,), "i")


def _get_unknown_int16(self) -> int:
    return _get_unknown_packed(self, "h")[0]


def _set_unknown_int16(self, value: int) -> None:
    _set_unknown_packed(self, (max(-32768, min(32767, value)),), "h")


def _get_unknown_uint8(self) -> int:
    return _get_unknown_packed(self, "B")[0]


def _set_unknown_uint8(self, value: int) -> None:
    _set_unknown_packed(self, (max(0, min(255, value)),), "B")


def _get_unknown_int32x2(self) -> tuple:
    return _get_unknown_packed(self, "ii")


def _set_unknown_int32x2(self, value) -> None:
    _set_unknown_packed(self, tuple(value), "ii")


def _get_unknown_float32x4(self) -> tuple:
    return _get_unknown_packed(self, "ffff")


def _set_unknown_float32x4(self, value) -> None:
    _set_unknown_packed(self, tuple(value), "ffff")


def _get_unknown_float32(self) -> float:
    return _get_unknown_packed(self, "f")[0]


def _set_unknown_float32(self, value: float) -> None:
    _set_unknown_packed(self, (value,), "f")


def _get_unknown_float32x2(self) -> tuple:
    return _get_unknown_packed(self, "ff")


def _set_unknown_float32x2(self, value) -> None:
    _set_unknown_packed(self, tuple(value), "ff")


def _get_unknown_float32x9(self) -> tuple:
    return _get_unknown_packed(self, "fffffffff")


def _set_unknown_float32x9(self, value) -> None:
    _set_unknown_packed(self, tuple(value), "fffffffff")


# `PropWstring2`（dataType=21）：不透明字节实际是 UTF-16LE、以单个 `\x00\x00` 结尾的宽字符串
# （和 vendor 自己实现的 `PtBehaviorVariableDataWString.str` 同一种编码，只是 vendor 没把
# PropWstring2 接到那个类上）。跟上面几个固定字节数的类型不一样：编辑会改变 `data` 的字节数，
# 而 `PtBehaviorVariable.varSize` 完全没有 `[RszByteSizeField]` 标注、不会被 vendor 自愈
# （docstring 见 ptbehavior_catalog.py），所以这三个 get/set 挂在**外层 PtBehaviorVariable
# 节点**（不是 variable 子节点）上，改字符串的同时手动同步 `variable.size` 和外层 `varSize`
# ——公式 `varSize = size + len(behaviorProperty 的 UTF-8 字节数) + 21` 是拿全部候选目录模板
# （所有 behaviorString、所有字段名、所有 dataType）反过来验证过的，零例外（21 这个常数应该
# 对应 PtBehaviorVariable 自己的固定字段开销，没有继续往下拆到具体是哪几个字段，公式本身
# 已经用穷举验证过，不需要知道"为什么是 21"就能安全使用）。这条公式与 dataType 无关，
# dataType=25/26（下面的 ASCII 类名字符串）复用同一个常数。
_PTBEHAVIOR_VARSIZE_FIXED_OVERHEAD = 21


def is_unknown_wstring_shape(node: "EFXValueNode") -> bool:
    """`node`（`variable` 子节点）的 `data` 解出来是不是一个合法的、以 `\\x00\\x00` 结尾的
    UTF-16LE 宽字符串（偶数字节数、末尾正好一个 null 终止符、能无损解码）。给 `PropWstring2`
    的紧凑编辑判断能不能画，不满足就回退到通用展开区，不硬套（铁律 #1）。
    """
    import base64

    child = _unknown_data_child(node)
    if child is None or child.data_type not in ("STRING", "NULL"):
        return False
    try:
        raw = base64.b64decode(child.string_value or "")
    except (ValueError, TypeError):
        return False
    if len(raw) < 2 or len(raw) % 2 != 0 or raw[-2:] != b"\x00\x00":
        return False
    try:
        raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return False
    return True


# dataType=25/26：全语料 12208+1895 个实例逐条核对过，`data` 全部是单个 `\x00` 结尾的纯
# ASCII 类名字符串（如 `via.effect.script.EffectDecal2.EffectDecal_V2.cOtherMaterialParamater`），
# 跟 21 号是同一类问题、只是字符集/结尾不同（ASCII 单 `\x00` vs UTF-16LE 双 `\x00`）。之前一版
# 把这两个值判成"结构太复杂、结构性排除"是被字段名（`OtherMaterialParamList[N]`）和字节数
# 波动误导——字节数波动纯粹是不同类名字符串本身长短不同，跟"数组套数组"无关，见
# `distinctDataHex` 的取证（`tools/ptbehavior_catalog_raw.json` 的 `byRawDataType['25']`/
# `['26']`，每个字节长度桶的实例数加总正好等于该 dataType 的总实例数，没有第三种形状）。
def is_unknown_astring_shape(node: "EFXValueNode") -> bool:
    """`node`（`variable` 子节点）的 `data` 解出来是不是一个合法的、以单个 `\\x00` 结尾的
    ASCII 字符串（末尾正好一个 null 终止符、中间不含 null、能无损解码）。给 dataType=25/26
    的紧凑编辑判断能不能画，不满足就回退到通用展开区，不硬套（铁律 #1）。
    """
    import base64

    child = _unknown_data_child(node)
    if child is None or child.data_type not in ("STRING", "NULL"):
        return False
    try:
        raw = base64.b64decode(child.string_value or "")
    except (ValueError, TypeError):
        return False
    if len(raw) < 1 or raw[-1:] != b"\x00" or raw.count(b"\x00") != 1:
        return False
    try:
        raw[:-1].decode("ascii")
    except UnicodeDecodeError:
        return False
    return True


def _prefab_string_variable_and_data(node: "EFXValueNode"):
    """`node` 是 PtBehaviorVariable 本体（含 varSize/dataType/variable/varHash/
    behaviorProperty 五个直接子节点），返回 `(variable 节点, data 节点)`，形状不对返回
    `(None, None)`。给 `PropWstring2`（21，UTF-16LE）和 dataType=25/26（ASCII）共用——两者都是
    "编辑会改变 data 字节数、需要连 varSize 一起重算"的字符串形状，区别只在编码。"""
    variable = find_field(node.children, "variable")
    if variable is None or variable.data_type != "OBJECT":
        return None, None
    data_child = find_field(variable.children, "data")
    if data_child is None or data_child.data_type not in ("STRING", "NULL"):
        return None, None
    return variable, data_child


def _sync_prefab_string_varsize(self, variable: "EFXValueNode", raw: bytes) -> None:
    """写完 `data` 新字节后同步 `variable.size` 和外层 `varSize`，`_set_unknown_wstring()`/
    `_set_unknown_astring()` 共用（公式见 `_PTBEHAVIOR_VARSIZE_FIXED_OVERHEAD` 的说明）。"""
    inner_size_node = find_field(variable.children, "size")
    if inner_size_node is not None and inner_size_node.data_type == "INT":
        inner_size_node.int_value = len(raw)

    varsize_node = find_field(self.children, "varSize")
    behavior_prop_node = find_field(self.children, "behaviorProperty")
    if (varsize_node is not None and varsize_node.data_type == "INT"
            and behavior_prop_node is not None):
        prop_name = node_to_value(behavior_prop_node) or ""
        varsize_node.int_value = (
            len(raw) + len(prop_name.encode("utf-8")) + _PTBEHAVIOR_VARSIZE_FIXED_OVERHEAD
        )


def _get_unknown_wstring(self) -> str:
    import base64

    _variable, data_child = _prefab_string_variable_and_data(self)
    if data_child is None:
        return ""
    try:
        raw = base64.b64decode(data_child.string_value or "")
    except (ValueError, TypeError):
        return ""
    try:
        text = raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return ""
    return text.rstrip("\x00")


def _set_unknown_wstring(self, value: str) -> None:
    import base64

    variable, data_child = _prefab_string_variable_and_data(self)
    if data_child is None:
        return
    raw = (value + "\x00").encode("utf-16-le")
    if data_child.data_type == "NULL":
        data_child.data_type = "STRING"
    data_child.string_value = base64.b64encode(raw).decode("ascii")
    _sync_prefab_string_varsize(self, variable, raw)


def _get_unknown_astring(self) -> str:
    import base64

    _variable, data_child = _prefab_string_variable_and_data(self)
    if data_child is None:
        return ""
    try:
        raw = base64.b64decode(data_child.string_value or "")
    except (ValueError, TypeError):
        return ""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return ""
    return text.rstrip("\x00")


def _set_unknown_astring(self, value: str) -> None:
    import base64

    variable, data_child = _prefab_string_variable_and_data(self)
    if data_child is None:
        return
    try:
        raw = (value + "\x00").encode("ascii")
    except UnicodeEncodeError:
        # 铁律 #1：这条字段全语料只见过 ASCII 类名，编不进的非 ASCII 输入拒绝这次编辑，
        # 不静默丢字符、不换编码悄悄改变字节形状。
        return
    if data_child.data_type == "NULL":
        data_child.data_type = "STRING"
    data_child.string_value = base64.b64encode(raw).decode("ascii")
    _sync_prefab_string_varsize(self, variable, raw)


# `IBoneRelationAttribute` 各实现类里"内联存的那份骨骼名"字段名（`ParentOptions.BoneName` /
# `Attractor.boneName` / `VanishArea3D.JointName` / `TypeLightning3D.boneName` /
# `TypeStrainRibbonV3.boneName`）。它和 `ParentBone` 是**同一个值的两种编码**：一个内联在
# attribute 自己的字节里，一个走文件级 `Bones`/`BoneRelations` 索引表，官方文件里两者永远一致
# （见 docs/TOPLEVEL_STRUCTURE.md 的订正段）。按名字判断，不维护"类型 -> 字段名"硬编码表。
_INLINE_BONE_NAME_KEYS = frozenset({"BoneName", "boneName", "JointName"})

# 批量填充字段树时抑制 update 回调里的联动写入（见 suppress_field_updates()）。
_suppress_field_updates = False


class suppress_field_updates:
    """上下文管理器：期间 `string_value` 的 update 回调不做任何**联动写入**（目前只有
    ParentBone -> 内联骨骼名这一处）。

    ⚠ 这不是性能优化，是正确性要求。Blender 的 update 回调在 Python 赋值时同样会触发，
    导入/粘贴/新建时 `populate_node()` 逐个写 `string_value` 会把联动一起带起来——那等于
    "只是打开了一个文件，字节就被我们改了"。官方语料里确实存在一个两者不一致的文件
    （`11_em0162_00_063`，Capcom 自己改了一边没改另一边），它过一遍 Blender 就会产生额外
    字节差异，直接违反"和纯 CLI 往返产物逐字节相同"这条判据。联动只在**用户真的在面板里改
    ParentBone**时发生。
    """

    def __enter__(self):
        global _suppress_field_updates
        self._prev = _suppress_field_updates
        _suppress_field_updates = True
        return self

    def __exit__(self, *exc):
        global _suppress_field_updates
        _suppress_field_updates = self._prev
        return False


def _mirror_parent_bone_to_inline(node: "EFXValueNode") -> None:
    """把 `ParentBone` 的新值同步写进同一个 attribute 的内联骨骼名字段。

    面板上 `ParentBone` 是唯一的编辑入口（骨骼选择器），内联字段画成只读——两处都是真实存储、
    都会写进文件，让用户分别编辑只会造出官方文件里从不出现的不一致状态，其中"只改内联名"
    那种还特别坑：看着像重新绑定了，实际绑定完全没变（写出侧只认 `ParentBone`）。
    """
    fields = getattr(node.id_data, "efx_fields", None)
    if fields is None:
        return
    for sibling in fields:
        if sibling.key in _INLINE_BONE_NAME_KEYS and sibling.data_type in ("STRING", "NULL"):
            if sibling.data_type == "NULL":
                sibling.data_type = "STRING"
            if sibling.string_value != node.string_value:
                sibling.string_value = node.string_value
            return


def _apply_ptbehavior_default(node: "EFXValueNode") -> None:
    """`behaviorString` 被改写成一个候选目录里收录的类名，就把 `properties` 整个替换成
    这个类在全语料里出现次数最多的那一套字段组合（`ptbehavior_catalog.default_instance()`，
    取自同一个真实实例）——不管改之前 `properties` 里有什么。这不是候选目录 `candidates()`
    的全量并集——那是"这个类见过的所有字段"，用来支持手动增删，不代表任何一个真实文件真的
    长这样。

    **无条件替换，不是只在为空时才填**（2026-09-19 改，推翻了第一版"已有内容就不碰"的判断）：
    `behaviorProperty`（字段名）在 PtBehavior 里不是全局唯一 ID，同一个名字在不同 behaviorString
    下可以对应完全不同的 `dataType`/取值语义——engine 侧按 `(behaviorString, behaviorProperty)`
    这一对去查怎么解读这条数据，换了 `behaviorString` 之后原来那些字段名即使字面上还留着，
    对新的类来说也是要么查不到、要么查到但语义完全不对，运行时至少是无效覆盖，往坏了说会报错/
    崩溃。留着旧字段"看起来没丢数据"，实际上是留着一堆在新语境下已经失效甚至有害的垃圾——
    这种情况下"替换"比"保留"更接近"不丢数据"的本意，铁律 #1 保护的是"用户认得出来、有意义
    的数据"，不是"字面上还在但已经对不上号的字节"。

    `default_entries` 为空（这个类的众数用法就是"什么都不覆盖"，如 `EffectPassThrough`）时，
    替换的结果就是清空——这同样是正确行为，不是"没找到默认值所以什么也不做"。
    """
    fields = getattr(node.id_data, "efx_fields", None)
    if fields is None:
        return
    properties_node = find_field(fields, "properties")
    if properties_node is None or properties_node.data_type != "ARRAY":
        return
    from . import ptbehavior_catalog
    default_entries = ptbehavior_catalog.default_instance(node.string_value)
    with suppress_field_updates():
        properties_node.children.clear()
        for entry in default_entries:
            child = properties_node.children.add()
            populate_node(child, str(len(properties_node.children) - 1), entry["template"])
            # 每条都已经有紧凑主行了（见 panels._draw_ptbehavior_property），跟
            # io_tree.collapse_mdf_properties() 对导入路径的处理一致，默认折起来，
            # 不要一次性摊开一整块字段把 attribute 挤出屏幕。
            child.ui_expand = False
    properties_node.ui_expand = True


def _promote_null_to_string(self, context) -> None:
    """`string_value` 的 `update` 回调：`data_type == "NULL"` 的节点被用户往里面打字，就地
    转正成 `STRING`。

    2026-09-10 实机发现：`bridge.new_attribute()`/`new_entry()` 吐出来的空白 attribute，
    C# 侧 `string?` 字段的默认值是 `null`（不是 `""`），JSON 里对应字面 `null`，
    `populate_node()` 建出来的节点是 `data_type == "NULL"`——而 `panels.py::_draw_scalar_prop()`
    对 NULL 节点只画一行 `label(text="null")`，没有任何控件，用户没法把新建的
    `UVSequence.UVSPath` 这类路径字段填上任何值。扫过 vendor 全部 EFX attribute 类源码：
    可空字段只有 `string?` 一种（没有 `int?`/`float?`/`bool?`），所以"NULL 节点等于一个还没
    填的字符串"这个假设覆盖了全部已知情形，不是针对某个字段名的特判。

    只处理"转正"，不处理反向（清空文本框不会退回 NULL）——`??=  ""` 那种 C# 写出侧本来就把
    `null` 和 `""` 当同一回事（见 `_normalize_path_separators()` 头部说明的 `filePath` 先例），
    保持 `STRING("")` 更简单，不需要再造一个"用户主动清空 vs 从没填过"的状态区分。

    顺带把反斜杠规整成正斜杠：导入路径上 `populate_node()` 已经对**每个** STRING 节点做过
    一次，但用户在面板里手打/粘贴进来的不经过那里——"导入的被纠正、自己填的不纠正"这种不一致
    正好会在最容易犯错的场景（从资源管理器复制路径）下失灵，而那次 `UVSPath` 反斜杠导致游戏内
    报 "Invalid" 就是这么来的。判据和导入侧完全一致，不另立一套。
    """
    if self.data_type == "NULL":
        self.data_type = "STRING"
    fixed = _normalize_path_separators(self.string_value)
    if fixed != self.string_value:
        self.string_value = fixed
    if self.key == "ParentBone" and not _suppress_field_updates:
        _mirror_parent_bone_to_inline(self)
    if self.key == "behaviorString" and not _suppress_field_updates:
        _apply_ptbehavior_default(self)
    _on_field_edited(self, context)


def _on_field_edited(self, context) -> None:
    """`float_value` / `int_value` / `bool_value` 的 update 回调：字段被**用户**改过之后，
    把依赖它的纯视觉产物重算一遍。三件事：Transform3D -> 所属 Entry 的 `matrix_basis`，
    EmitterShape3D -> 生成区域线框叠加层标脏，任意字段 -> 粒子预览（`sim_preview`）标脏。

    没有这一步的话，视口和粒子预览摆的是**上一次 `sync_all_transform3d()` 时的**姿态——
    导入之后除非用户手动点 Refresh Transform3D View，改 LocalPosition 在视口里完全没反应，
    而 `sim_preview` 的宿主矩阵正是读这个 `matrix_world`（见 `sim_preview._entry_matrix()`），
    于是"本地位置明明是 1，粒子还在原点"。对齐姊妹项目 EFX-Editor 的实时联动行为。

    只写 object transform（`matrix_basis`，不参与导出，见 transform3d_view.py 头部说明），
    不碰任何字段数据——所以它不可能污染导出字节。

    不是 Transform3D 形状的 attribute 直接返回：`apply_transform3d()` 内部靠
    `transform3d_field_values()` 的四键结构判断，不命中就什么都不做，不需要在这里再维护一份
    类型名单。批量填充（导入/粘贴/新建）期间由 `suppress_field_updates()` 关掉——那条路上
    每个标量都会触发一次，而调用方在填完之后自己会烘一遍（见
    `io_tree.apply_attribute_content()`）。

    `sim_preview.mark_dirty()` 同样在这一并调用：`Velocity3D.Offset`/`Size` 这类普通内容
    字段之前只有 `sim_preview.py` 自己的预览面板旋钮（种子/帧率/距离等）会触发
    `_on_knob_changed()` -> `mark_dirty()`，编辑 attribute 树里的任何字段值都不会——这就是
    "Normal 档的 Offset/Size 明明已经实装，播放中调数值却看不到变化"的根因：正在跑的预览
    读的是上一次 `rebuild_tracks()` 时的快照，dirty 标脏之前不会重建。这里不按字段类型/
    attribute 类型区分（不止 Velocity3D 一个受影响），一律标脏——`mark_dirty()` 本身只是
    置一个布尔位，`tick()` 没在跑（没在播放）时置了也没有开销。
    """
    if _suppress_field_updates:
        return
    obj = getattr(self, "id_data", None)
    if obj is None or obj.get("~TYPE") != TYPE_ATTRIBUTE:
        return
    from . import sim_preview
    sim_preview.mark_dirty()
    if short_attr_name(obj.efx_attr_type) == "EmitterShape3D":
        # ⚠ 不要在这儿列字段白名单：RangeX/Y/Z、ScaleHorizontal/Vertical、LocalRotation*、
        # RotationOrder 全都进线框，漏一个就是"改了参数框不动"。整个 attribute 一律标脏。
        from . import es3d_overlay
        es3d_overlay.invalidate()
    if obj.parent is None:
        return
    from . import transform3d_view
    transform3d_view.apply_transform3d(obj)


def _read_packed_int(node: "EFXValueNode") -> int:
    """INT/BIGINT 节点当前的无符号整数值。BIGINT 存在 `uint_str`（十进制字符串），INT 存在
    `int_value`（有符号）——统一换算成无符号读出，供 `enum_proxy` 和位域弹窗（bitfield.py）
    共用，两边不重复写一份同样的换算逻辑。"""
    if node.data_type == "BIGINT":
        raw = node.uint_str
    else:
        raw = node.int_value
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    return value + (1 << 32) if value < 0 else value


def _write_packed_int(node: "EFXValueNode", value: int) -> None:
    if node.data_type == "BIGINT":
        node.uint_str = str(value)
    else:
        node.int_value = value


_INT32_SPAN = 1 << 32
_INT32_BIAS = 1 << 31


def as_int32(value: int) -> int:
    """把一个 32 位整数折进**有符号** int32 的范围。

    `EnumProperty` 的 items 第 4 位（以及 get/set 交换的那个数）是 **C `int`**，
    塞一个 > 2^31-1 的值进去会**直接崩掉 Blender**——不是抛异常，是整个进程没了。

    实测踩法：`ExpressionAssignType` 这类枚举字段，vendor 的成员表里有
    `ForceWord = -1`（`EfxCommon.cs`），而 `_read_packed_int()` 为了位域显示统一把负数
    读成无符号（-1 -> 4294967295）。两边一个用有符号、一个用无符号，于是
    `_enum_proxy_items()` 认为"当前值不在列举范围内"，往 items 里补了一条数值
    4294967295 的兜底项——越界，崩。

    折叠是 32 位上的双射，所以不会让两个不同的取值撞到同一个枚举数值
    （真正 >32 位的枚举字段不存在；万一有，`_enum_proxy_items()` 会跳过并记一笔）。
    """
    return ((int(value) + _INT32_BIAS) % _INT32_SPAN) - _INT32_BIAS


def _read_enum_proxy(node: "EFXValueNode") -> int:
    """`enum_proxy` 的 getter：读出来的值必须和 items 里的数值同一套表示，见 `as_int32()`。"""
    return as_int32(_read_packed_int(node))


def _write_enum_proxy(node: "EFXValueNode", value: int) -> None:
    """`enum_proxy` 的 setter：Blender 给的是有符号 int32，按存储槽的约定写回去
    （`int_value` 本来就是有符号；`uint_str` 存的是无符号十进制，负数要加回 2^32）。"""
    if node.data_type == "BIGINT" and value < 0:
        value += _INT32_SPAN
    _write_packed_int(node, value)


# ─────────────────────────────────────────────────────────────────────────────
# enum_proxy —— "整个字段就是一个单选枚举"的内联下拉代理
#
# RotationOrder、`EFXAttributeLife.Flags`（持续开关）这类字段本质上是"退化成单选项的位域"
# （整个 32 位就是一段，见 bitfield.py 的说明），比起弹窗多一次点击，直接内联画一个下拉更省事
# 也更显眼——对齐姊妹项目 EFX-Editor 的做法（真正的多值位域才弹窗，见 bitfield.py 顶部说明）。
#
# EnumProperty 的 items 需要是回调（每个字段的选项表都不一样），但 EFXValueNode 是所有字段共用
# 的通用节点类型，没法在类体里为每个具体字段单独声明一个 EnumProperty。做法：draw_node() 在画
# 这一行之前，把这个节点这一次该用的选项表存进 `_INLINE_ENUM_CONTEXT`（键是
# `(node.id_data, node.path_from_id())`，同一次 draw 调用栈内 items 回调同步读出）——不写节点
# 自身的任何数据槽，不产生撤销栈记录、不标记文件已改动。
# ─────────────────────────────────────────────────────────────────────────────

_INLINE_ENUM_CONTEXT: dict = {}
# EnumProperty 动态 items 必须被 Python 侧持有（Blender 只存指向字符串的指针，不复制内容，
# 回调返回的临时元组被回收后界面就是乱码，官方文档明写的坑，bitfield.py 也有同样的缓存）。
# 按"选项表内容 + 语言"缓存，不需要按节点区分——同样的选项表无论挂在哪个节点上，构造出来的
# EnumProperty items 都完全一样。
_INLINE_ENUM_ITEMS_CACHE: dict = {}


def set_inline_enum_items(node: "EFXValueNode", items: list) -> None:
    """供 panels.py 在画一个内联枚举下拉前调用：`items` 形如 `[[值, 中文, 英文], ...]`。"""
    _INLINE_ENUM_CONTEXT[(node.id_data, node.path_from_id())] = items


def _enum_proxy_items(self, context):
    items = _INLINE_ENUM_CONTEXT.get((self.id_data, self.path_from_id())) or []
    # 全程用 `as_int32()` 的表示——items 的数值和 getter 返回值必须是同一套，
    # 不然会走下面"当前值不在列举范围内"的兜底、插进一条越界的枚举数值把 Blender 崩掉。
    current = _read_enum_proxy(self)
    cache_key = (tuple(tuple(it) for it in items), i18n.get_lang(), current)
    cached = _INLINE_ENUM_ITEMS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    lang_en = i18n.get_lang() == "EN"
    built = []
    seen = set()
    for it in items:
        value = it[0]
        zh = it[1] if len(it) > 1 else str(value)
        en = it[2] if len(it) > 2 else ""
        label = (en or zh) if lang_en else zh
        number = as_int32(value)
        if number != int(value) and int(value) != as_int32(int(value)):
            # 超过 32 位的枚举取值（现实里不存在）——跳过而不是折叠，折叠可能撞车
            continue
        # 下拉里带上原始数值（"1 跟随玩家移动"）——转成下拉之后裸数字不再直接可见了，
        # 但导出的还是这个数字，社区文档/010 模板对照的也是这个数字，不能让它彻底消失。
        # 标签和标识符用**原样的值**（`-1` 就显示 -1），只有第 4 位那个给 Blender 的数值
        # 走 `as_int32()`。
        built.append((str(value), f"{value} {label}", "", number))
        seen.add(number)
    if current not in seen:
        # 当前值不在列举范围内（语料里没见过的组合）：临时插一条"原值"，绝不静默改掉它
        # ——和 bitfield.py 弹窗里同样的兜底。**数值必须也走 `as_int32()`**，这里曾经
        # 直接用无符号原值，给 `ForceWord = -1` 这种负数枚举插出一条 4294967295 的项，
        # 直接崩 Blender（见 `as_int32()` 的说明）。
        built.append((str(current), f"{current}（原值）", "语料里没见过这个取值，原样保留",
                      current))
    if not built:
        built = [("0", "-", "", 0)]
    _INLINE_ENUM_ITEMS_CACHE[cache_key] = built
    return built


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

    # update：字段改了要立刻反映到纯视觉产物上（Transform3D -> Entry 的 matrix_basis、
    # EmitterShape3D -> 生成区域线框）
    # （见 _on_field_edited()）。`degrees_value` / `enum_proxy` 两个代理属性的 set
    # 都是 setattr 回这两个槽，所以角度显示模式、RotationOrder 下拉一并覆盖到。
    float_value: FloatProperty(name="Value", update=_on_field_edited)
    int_value: IntProperty(name="Value", update=_on_field_edited)
    uint_str: StringProperty(name="Value")
    bool_value: BoolProperty(name="Value", update=_on_field_edited)
    string_value: StringProperty(name="Value", update=_promote_null_to_string)
    # children 在类体外挂（见下），因为类体内还不能引用 EFXValueNode 自己。

    # 只在这个节点是 via.Color 的序列化形状（见 _rgba_child）时才有意义，面板据此判断要不要
    # 画颜色轮而不是普通的标量 prop() 行——不额外存副本，get/set 直接读写唯一子节点 "rgba"
    # 的打包 uint32，保持"字段树是唯一数据源"（export 仍然只读 children，不读这个属性本身）。
    color_value: FloatVectorProperty(
        name="Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        get=_get_rgba_color, set=_set_rgba_color,
    )

    # 只在这个节点是 `MdfProperty.value` 的 float4 形状、且参数名看着是个颜色时才有意义
    # （判据见 panels.is_color_param_name()）。和上面 via.Color 那个的区别：那边底层是打包成
    # uint32 的 0-255 分量，天然就在 0-1 内；这里底层是四个裸 float，**不设硬上下限**——材质
    # 里的颜色可以超出 0-1（HDR），钉死 max=1.0 会让 Blender 在调用 set 之前就把值夹掉，
    # 等于用户点一下颜色轮就静默改坏了原始数据。soft_min/soft_max 只影响滑条手感，不夹值。
    float4_color_value: FloatVectorProperty(
        name="Color", subtype="COLOR", size=4, soft_min=0.0, soft_max=1.0,
        get=_get_float4_color, set=_set_float4_color,
    )

    # 只在这个节点是 PtBehaviorVariable 的 `variable`、且 `data` 的字节数正好等于对应形状
    # 需要的字节数时才有意义（见 panels._PTBEHAVIOR_UNKNOWN_DATATYPE_SHAPES 的取证依据）。
    # get/set 直接读写 `data` 这个 base64 字符串子节点，字段树仍然是唯一数据源。
    unknown_int32_value: IntProperty(
        name="Value", get=_get_unknown_int32, set=_set_unknown_int32,
    )
    unknown_int16_value: IntProperty(
        name="Value", min=-32768, max=32767,
        get=_get_unknown_int16, set=_set_unknown_int16,
    )
    unknown_uint8_value: IntProperty(
        name="Value", min=0, max=255,
        get=_get_unknown_uint8, set=_set_unknown_uint8,
    )
    unknown_int32x2_value: IntVectorProperty(
        name="Value", size=2, get=_get_unknown_int32x2, set=_set_unknown_int32x2,
    )
    unknown_float32x4_value: FloatVectorProperty(
        name="Value", size=4, get=_get_unknown_float32x4, set=_set_unknown_float32x4,
    )
    unknown_float32_value: FloatProperty(
        name="Value", get=_get_unknown_float32, set=_set_unknown_float32,
    )
    unknown_float32x2_value: FloatVectorProperty(
        name="Value", size=2, get=_get_unknown_float32x2, set=_set_unknown_float32x2,
    )
    unknown_float32x9_value: FloatVectorProperty(
        name="Value", size=9, get=_get_unknown_float32x9, set=_set_unknown_float32x9,
    )
    # 挂在 PtBehaviorVariable 本体（不是 variable 子节点）上——get/set 要连外层 varSize 一起
    # 同步，见 _set_unknown_wstring() 的说明。
    unknown_wstring_value: StringProperty(
        name="Value", get=_get_unknown_wstring, set=_set_unknown_wstring,
    )
    # dataType=25/26 专属：ASCII 单 `\x00` 结尾的类名字符串，同样挂在 PtBehaviorVariable 本体
    # 上、同样要连外层 varSize 一起重算，见 _set_unknown_astring() 的说明。
    unknown_astring_value: StringProperty(
        name="Value", get=_get_unknown_astring, set=_set_unknown_astring,
    )

    # 只在这个节点是弧度制角度字段的标量子节点时才有意义——覆盖三种形状：Transform3D.
    # LocalRotation 这类 Vector3 的 X/Y/Z、TypeMeshV2.RotationX 这类 via.Range 的 s/r、
    # Transform3DModifier.unkn7 这类孤立标量。纯 UI 层的角度显示代理，get/set 直接读写
    # float_value 本身（原始存储值不变，弧度），subtype="ANGLE" 让 Blender 的属性控件自动
    # 按度显示/接受输入、内部仍以弧度传给 get/set，不需要手动 math.degrees()/radians() 转换。
    # 是否使用这个属性而不是 float_value 由 panels.py 按 Scene.efx_re_angle_degrees 开关 +
    # 字段知识表的 unit == "angle_radians" 标注决定，见 panels.py _wants_degrees() 的说明。
    degrees_value: FloatProperty(
        name="Value", subtype="ANGLE",
        get=lambda self: self.float_value,
        set=lambda self, value: setattr(self, "float_value", value),
    )

    # 只在这个节点是"单选枚举"（RotationOrder、持续开关这类退化成单段的位域，或 C# 侧
    # 声明成枚举的 INT/BIGINT 字段）时才有意义——draw_node()/panels.py 画之前用
    # `set_inline_enum_items()` 把这次要用的选项表存进 `_INLINE_ENUM_CONTEXT`，
    # `_enum_proxy_items()` 在同一次 draw 调用栈内读出。get/set 直接读写 int_value/uint_str
    # 本身（原始存储值不变），"number" 字段就是原始整数值，不是数组下标——见本文件上面
    # enum_proxy 相关函数的说明。
    enum_proxy: EnumProperty(
        name="Value", items=_enum_proxy_items,
        get=_read_enum_proxy, set=_write_enum_proxy,
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


def is_sr_shaped(node: EFXValueNode) -> bool:
    """一个 OBJECT 节点是不是 `{s, r}` 这个序列化形状（`via.Range` 或 `via.RangeI`，
    vendor `RszValueType.cs`）。**只判形状，不判语义**——语义分四种，见
    `sr_children_ordered()` / `is_static_random_node()` / `is_pair_min_max_node()` /
    `is_sr_index_node()` / `is_sr_min_max_node()`。"""
    if node.data_type != "OBJECT" or len(node.children) != 2:
        return False
    return {c.key for c in node.children} == {"s", "r"}


def sr_children_ordered(node: EFXValueNode):
    """`{s,r}` 节点 -> `(主值子节点, 副值子节点)`。形状不对时返回 `None`。

    **主值是二进制首字段，不是固定的 `s`。** vendor 的两个结构体字段声明顺序相反
    （`RszValueType.cs:226` / `:264`）：`Range`(float) 是 `{s, r}`、`RangeI`(int) 是
    `{r, s}`，而全语料证据表明**首字段恒为主值**（静态值 / min），第二个是副值
    （随机量 / max）：

    - `Spawn.LoopNum`（RangeI）：高频对 `(r=1,s=0)` 占 55%，`s != 0` 只占 1.4%——主值在 `r`。
      若按 `s` 当主值，98.6% 的发射器都成了"循环 0 次"。
    - `Velocity3D.SpeedCoef`（Range）：高频对 `(s=1,r=0)` / `(s=0.99,r=0)`——主值在 `s`。

    这条规律还统一了下面三个"例外"：`PatternNo`(RangeI, 主值 r = Min) 和
    `PlaySpeed`(Range, 主值 s = Min) 的"s/r 顺序相反"其实就是两个结构体声明顺序相反的
    表现，**主值恒为 min**，不是两套独立规则；`SequenceNo`(RangeI) 的"`r` 才是实际生效的
    索引"同样自洽。详细数据见 docs/SIM_PORT_PLAN.md §8.6。

    类型判定看子节点的 `data_type`：两个都是 `INT` 就是 `RangeI`。**不能看 key 集合**
    ——`Range` 和 `RangeI` 的 key 集合完全相同，这正是这个 bug 藏了这么久的原因。
    """
    if not is_sr_shaped(node):
        return None
    by_key = {c.key: c for c in node.children}
    s_child, r_child = by_key["s"], by_key["r"]
    is_ranged_int = s_child.data_type == "INT" and r_child.data_type == "INT"
    return (r_child, s_child) if is_ranged_int else (s_child, r_child)


#: `{s,r}` 但语义是 **(min, max)** 而不是 (静态值, 随机量) 的字段，键是 `(短类型名, 字段名)`。
#:
#: 必须按 (类型, 字段) 而不是裸字段名——`VanishFrame` 在 `Life` 上是 `RangeI`、在
#: `VanishArea3D` 上是 `Range`，裸名会误伤后者。
#:
#: 语料判据（`EfxBridge condstats`，91178 个 `Life` 实例）：四个字段**全部 100% 满足
#: `r <= s`，`r > s` 出现 0 次**。而同为 `RangeI` 的 `Spawn.LoopNum` 有 74.7% 是 `r > s`、
#: `Velocity3D.GravityDelayFrame` 9.6%、`Spawn.SpawnFrame` 11.5%——所以这不是 `RangeI` 的
#: 通性，是 `Life` 独有的硬不变式，只有 min/max 语义能强制它。非相等的取值对也长得像区间
#: 而不像"基值+浮动"：`VanishFrame` 的 `(30,40) (60,80) (80,100) (100,120)`、`KeepFrame`
#: 的 `(150,200)`，而 `r==s`（两端填一样 = 不随机）占 71~99.8%。
#:
#: ⚠ **同概念不等于同语义**：`RgbCommon.*AppearFrame/KeepFrame/VanishFrame` 全族看着和 `Life`
#: 那四个一模一样，实测却是 static/random——`副值<主值` 大量出现（1 万~2 万例），高频组合
#: `(5,0)` `(10,0)` `(30,0)` 就是"值 5、不随机"。`VanishArea3D.VanishFrame` 同理
#: （1018/1319 副值<主值）。所以这张表只收**逐个查过**的，不按名字外推。
#:
#: 镜像在 `efx_sim/shapes.py::PAIR_MIN_MAX_FIELDS`，由 `tests/test_sim_core.py` 钉住一致。
_PAIR_MIN_MAX_FIELDS = frozenset({
    ("Life", "AppearFrame"),
    ("Life", "KeepFrame"),
    ("Life", "VanishFrame"),
    ("Life", "KeepHoldFrame"),
    # --- `EmitterShape3D` 的三个逐轴区间。2026-09-13 全语料定的，判据是**外边界是 `q`
    # 还是 `p+q`**（min+max vs MHWI 那种 min+offset），不是 static/random：
    #   `q < p` 0/62492，而主值非零的有 36590/20748/36840 例（58.6%/33.2%/59.0%）——
    #   min+offset 下 `q` 是**厚度**，半径 1.0 厚 0.1 的薄壳就该写成 `(1.0, 0.1)` 即 `q < p`，
    #   这种组合一次都没出现，等于说"从来没人做过半径大于厚度的壳"，讲不通。
    #   反过来看"厚度"：读作 min+max 时 `q-p == 0`（粒子正好落在壳面上）占 69.2%/33.3%/60.0%，
    #   是最常见的写法；读作 min+offset 时 `q == 0` 占 0.0%/11.1%/0.0%——没人做过纯表面
    #   发射器，每个都非得有个中位 0.5~1.0 的厚度，不成立。
    #   另有 Y 轴的对称负数对 `(-0.1,0.1)×588` `(-0.5,0.5)×507` `(-1,1)×489`：min+max 读作
    #   "以原点为中心上下对称"，min+offset 则要求作者恰好挑一个等于 |min| 的 offset，挑了 1584 次。
    ("EmitterShape3D", "RangeX"),
    ("EmitterShape3D", "RangeY"),
    ("EmitterShape3D", "RangeZ"),
    # --- 以下 13 个是 2026-09-13 用 `EfxBridge pairstats` + `tools/audit_range_fields.py`
    # 全语料排查出来的（223 个二元字段扫了一遍），此前一直被当成 (静态值, 随机量) 读。
    # 共同判据：**副值 < 主值 0 例**（min/max 的必要条件），且**"副值==主值且主值≠0"占比高**
    # ——static/random 下那等于"浮动幅度恰好等于基值"，不可能成规模。括号里是那个占比。
    #
    # ⚠ **必须按 (类型, 字段) 键**，这批里真有撞名的：`AngularVelocity3D.Radius`（1796 例）
    # 和 `PtVortexelPhysics.BounceRate`（2192 例）都是**确证的 static/random**，用裸字段名会
    # 把它们一起误伤。
    ("PtCollision", "Radius"),                       # 94.7%  (0.1,0.1)×869
    ("PtCollision", "BounceNum"),                    # 81.4%  (2,2) (1,1) (3,3) (2,3)
    ("PtCollision", "BounceRate"),                   # 70.0%  (0.1,0.1) (0.1,0.2)
    ("PlaneCollider", "BounceNum"),                  # 54.0%  (1,1) (1,2) (2,3)
    ("PlaneCollider", "BounceRate"),                 # 16.1%  (0.4,0.5) (0.5,0.8)
    ("PlaneCollider", "IdleTime"),                   # 12.6%  (10,10) (60,60) (500,500)
    ("UVSequenceModifier", "PlaySpeedInit"),         # 83.4%  (1,1) (2,2) (1.5,1.5)
    ("UVSequenceModifier", "PlaySpeedFinal"),        # 74.5%  (0.5,0.5) (0.3,0.3)
    ("UVSequenceModifier", "PlaySpeedChangeTimeCoef"),  # 93.4%  (0.97,0.97) (0.98,0.98)
    ("EmitterHSV", "Range1"),                        # 77.5%  (100,100) (100,650)
    ("EmitterHSV", "Range3"),                        # 75.0%  (100,100) (240,650)
    ("TexelChannelOperator", "Keep"),                # 26.3%  (20,60) (100,100) (0,5)
    ("TexelChannelOperator", "Vanish"),              # 73.7%  (80,80) (20,20)
    # --- `EFXAttributeAttractor.ShapeRangeX/Y/Z`（2026-09-18，用户实机测试）：给三轴各自的
    # 主值设置不同数值，观测到的是形状沿该轴伸缩到"主值±副值"这个区间，不是"主值+随机抖动"。
    # 语料复核（`EfxBridge pairstats`）不是教科书式的零违例：`secondLtFirst` 分别是 4/1105、
    # 5/1105、0/1105——个别文件副值小于主值，比 `_PAIR_MIN_MAX_FIELDS` 其余条目噪声大，
    # 参考 `boneName` 95204 次里 1 次不一致仍判 confirmed 的先例，判定是语料里的个别脏数据，
    # 不是模型错误，但比表里其余条目的证据弱，标注置信度时要如实体现。
    ("Attractor", "ShapeRangeX"),
    ("Attractor", "ShapeRangeY"),
    ("Attractor", "ShapeRangeZ"),
})


def is_pair_min_max_node(node: EFXValueNode, attr_type: str | None) -> bool:
    """`{s,r}` 形状但语义是 (min, max) 的字段（见 `_PAIR_MIN_MAX_FIELDS`）。
    供 panels.py 画成 Min/Max 两列而不是 Static/Random。"""
    if not is_sr_shaped(node) or not attr_type:
        return False
    return (short_attr_name(attr_type), node.key) in _PAIR_MIN_MAX_FIELDS


def is_static_random_node(node: EFXValueNode, attr_type: str | None = None) -> bool:
    """一个 OBJECT 节点是不是"(静态值, 随机量)"语义的 `{s,r}`。供 panels.py 画成两列并排，
    不画成"2 items"折叠框。

    Static/Random 是 REE 惯例命名，不是姊妹项目 EFX-Editor（MHWI）社区习惯用的 Value/Jitter
    （这套 REE 命名以后计划回哺到 EFX-Editor，是两边统一的方向）。

    ⚠ **哪个子节点是 Static 不是固定的**，走 `sr_children_ordered()`，别写死 `s`。

    三类例外不算在这里：`SequenceNo` 走 `is_sr_index_node()`、`PatternNo`/`PlaySpeed` 走
    `is_sr_min_max_node()`、`Life` 的四个 Frame 走 `is_pair_min_max_node()`。
    `attr_type` 省略时不做最后那一类的排除（那类必须知道属性类型才能判）。
    """
    if not is_sr_shaped(node):
        return False
    if node.key in _SR_INDEX_FIELD_NAMES or node.key in _SR_MIN_MAX_FIELD_NAMES:
        return False
    if is_pair_min_max_node(node, attr_type) or is_sr_start_span_node(node, attr_type):
        return False
    return True


# 2026-09-10 用户实机测试 + EfxBridge relstats 全语料复核（详细证据见
# mhws_field_labels.json 里这两个字段各自的 evidence）：`SequenceNo`/`PatternNo` 序列化形状
# 跟 `via.Range{s,r}` 一样，但都不是 static/random 语义。
# - `SequenceNo`：全语料 66146 例 s 恒等于 r+1（或 r+4，4 例），随机实际只在 [0,r] 里选，
#   s 疑似只是配套的计数字段——画成 Index(r)/UnknIndex(s)，不是 Static/Random。
# - `PatternNo`：全语料 s>r 恒成立但差值自由变化（不像 SequenceNo 钉死在 1），是真正的
#   min/max 范围，只是 s/r 顺序和 `is_min_max_node()` 的 x/y 相反——画成 Max(s)/Min(r)。
# `PlaySpeed` 反过来 s<=r 恒成立、顺序跟 x/y 一致，画成 Min(s)/Max(r)。
# - `PartsStartNo`（`TypeMesh`/`TypeGpuMesh`，`RangeI`，主值 `r`）：全语料 10886 个实例
#   （TypeMesh 7366 + TypeGpuMesh 3520）里 **`s <= r` 0 例、`s == 0` 0 例**——静态/随机语义
#   下"随机量=0"本该是多数（大部分实例不随机），一例都没有直接把那条假说排除掉。
#   另有 `s <= MaxPartsNum` 7361/7366 成立（唯一的越界是 `MaxPartsNum=44, s=45`，5 例），
#   说明 `s` 跟的是部件总数、是**左闭右开的上界**，不是一个和静态值无关的随机幅度。
#   高频组合 `(0,1)` / `(0,4)` / `(2,3)` / `(12,15)` 读作"用第 0 个部件"/"用第 0~3 个"
#   /"用第 2 个"/"用第 12~14 个"，和 `PatternNo` 完全同构。
# `{s,r}` 形状、语义是 **(起始角, 扫描跨度)** 的字段（弧度）。
#
# `EmitterShape3D.ScaleHorizontal/ScaleVertical` 的两个数不是 static/random，也不是
# min/max：全语料按 `ShapeType` 分桶，球的 `ScaleHorizontal` 96.7% 是 `(0, 2π)`、
# `ScaleVertical` 63.4% 是 `(-π/2, π)`。`(0, 2π)` 两种读法都讲得通，但 `(-π/2, π)` 只有
# 读成"从 -90° 起、扫 180°"才是完整的纵向全扫；读成 min/max 会得到 -90°~+180° 这种
# 270° 的怪区间。逐条依据见 `efx_sim/behaviors/emittershape3d.py` 的模块说明。
#
# ⚠ **标成 Static/Random 会直接把人带沟里**：实测有人想要"水平 360 度"，于是把 360
# 填进了 Static 那一格——那是**起始角**，而跨度留在 0，扫描范围为零，整个形状塌成一条
# 辐条。标成 Start/Span 之后这个误填不可能发生。
_SR_START_SPAN_FIELD_NAMES = frozenset({"ScaleHorizontal", "ScaleVertical"})


#: 这两个字段只在 `EmitterShape3D` 上是 (起始角, 跨度)；别的属性上同名字段不适用
_SR_START_SPAN_ATTR = "EmitterShape3D"


def is_sr_start_span_node(node, attr_type: str = "") -> bool:
    """`{s,r}` 形状但语义是 (起始角, 扫描跨度) 的字段（见 `_SR_START_SPAN_FIELD_NAMES`）。"""
    if not is_sr_shaped(node) or node.key not in _SR_START_SPAN_FIELD_NAMES:
        return False
    return short_attr_name(attr_type) == _SR_START_SPAN_ATTR


_SR_INDEX_FIELD_NAMES = frozenset({"SequenceNo"})
_SR_MIN_MAX_FIELD_NAMES = frozenset({"PatternNo", "PlaySpeed", "PartsStartNo"})

# min/max 字段里**上界取不到**（左闭右开 `[Min, Max)`）的那些。
#
# 判据是"`Max == Min` 在语料里出现过没有"——闭区间里 `Max == Min` 是"固定一个值"的常规写法，
# 半开区间里它恰好是**空区间**，作者永远不会写。全语料（`EfxBridge pairstats` +
# `tools/audit_range_fields.py`）两边没有灰带：
#
#     PatternNo      66165 例   Max==Min 0 例      Max==Min+1 23085 例  -> 半开
#     PartsStartNo   10886 例   Max==Min 0 例      Max==Min+1  5943 例  -> 半开
#     Life.*Frame    91248 例   Max==Min 65051~91026 例                 -> 闭
#     Spawn.*        91147 例   Max==Min 80160~89813 例                 -> 闭
#
# **只对整数字段有意义**：`PlaySpeed` 这种浮点区间的开闭是零测度，不进这张名单。
#
# 这张名单同时供三处用，别在别处再算一遍：面板按它提示"Max 取不到"、
# `efx_sim/shapes.py` 的 `roll_sr_min_max_int()` 按它决定取样上界、镜像由单测钉住。
_HALF_OPEN_MAX_FIELD_NAMES = frozenset({"PatternNo", "PartsStartNo"})


def is_half_open_max_node(node: EFXValueNode) -> bool:
    """这个 min/max 节点的上界是不是**取不到**（`[Min, Max)`）。

    只对 `is_sr_min_max_node()` 为真的节点有意义；别的形状一律 False。
    """
    return is_sr_min_max_node(node) and node.key in _HALF_OPEN_MAX_FIELD_NAMES


def is_sr_index_node(node: EFXValueNode) -> bool:
    """`SequenceNo` 专用：形状和 `is_static_random_node()` 一样是 `{s,r}`，但 s/r 不是
    静态/随机，是"配套计数(s)/实际生效的随机上限索引(r)"。供 panels.py 画成
    Index / UnknIndex 两列——它是 `RangeI`，主值正好也是 `r`，和 `sr_children_ordered()`
    的统一规律自洽，所以画的时候照样走主值在左。"""
    if not is_sr_shaped(node):
        return False
    return node.key in _SR_INDEX_FIELD_NAMES


def is_sr_min_max_node(node: EFXValueNode) -> bool:
    """`PatternNo`/`PlaySpeed` 专用：形状和 `is_static_random_node()` 一样是 `{s,r}`，但实测
    是 min/max 范围而不是静态/随机。

    **哪个是 Min 不需要按字段名分别处理**：`PatternNo` 是 `RangeI`（主值 `r`）、`PlaySpeed`
    是 `Range`（主值 `s`），走 `sr_children_ordered()` 取主值即 Min。早先记的"两个字段 s/r
    顺序相反"其实就是这两个结构体声明顺序相反的表现，不是两套独立规则。"""
    if not is_sr_shaped(node):
        return False
    return node.key in _SR_MIN_MAX_FIELD_NAMES


def is_inline_bone_name_field(node: EFXValueNode, attr_type: str | None, attr_obj) -> bool:
    """一个字符串叶子字段是不是"内联存的那份骨骼名"（`BoneName`/`boneName`/`JointName`）。

    只有在**同一个 attribute 上还存在 `ParentBone` 字段**时才算——这是结构性判据，不是类型
    名单：`ParentBone` 只由 `IBoneRelationAttribute` 实现类产生，两个字段同时在场才构成
    "同一个值的两种编码"这种关系。反过来，万一以后有哪个 attribute 只有内联名、没有索引表
    绑定，它就该保持普通可编辑字符串字段，不该被这条规则锁住。
    """
    if attr_type is None or node.data_type not in ("STRING", "NULL"):
        return False
    if node.key not in _INLINE_BONE_NAME_KEYS:
        return False
    fields = getattr(attr_obj, "efx_fields", None)
    if fields is None:
        return False
    return any(sibling.key == "ParentBone" for sibling in fields)


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


def node_scalar(node: EFXValueNode) -> float:
    if node.data_type == "FLOAT":
        return node.float_value
    if node.data_type == "INT":
        return float(node.int_value)
    return 0.0


def read_xyz_node(node: EFXValueNode):
    """按 `xyz_child_order()` 探测到的键序，读出一个三分量向量节点的 `(x, y, z)` 标量值；
    不是三分量向量形状时返回 `None`。供 `transform3d_field_values()` 复用。"""
    order = xyz_child_order(node)
    if order is None:
        return None
    by_key = {c.key: c for c in node.children}
    return tuple(node_scalar(by_key[k]) for k in order)


# `EFXAttributeSpawn`（vendor EfxBasics.cs）里三个 `via.Int2`（序列化形状跟普通二维向量
# 一模一样，都是 {x, y}）字段——2026-09-10 用户实测确认：这几个字段的第二个值（max）比第
# 一个值（min）小时游戏会崩溃，是 min/max 范围，不是随便的二维数值对。结构上跟"普通二维
# 向量"完全没区别，唯一能分辨的只有字段名本身，所以按名单硬判断（同 is_bone_reference_field()
# 的做法），不是结构判定。EFXAttributeLife 的计时字段已经是正经的 `via.RangeI`（S/R 那一套），
# 不在这个问题里；vendor 里其它 Vector2 字段（EmitterShape 的尺寸、UV 偏移等）看起来是正经
# 二维量，没有跟这三个一样的"min/max"证据，先不动它们，避免瞎猜挂错标签。
_MIN_MAX_FIELD_NAMES = frozenset({"SpawnNum", "IntervalFrame", "EmitterDelayFrame"})


def is_min_max_node(node: EFXValueNode) -> bool:
    """一个 OBJECT 节点如果恰好是 `_MIN_MAX_FIELD_NAMES` 里那几个字段的 `{x, y}` 形状，
    返回 True。供 panels.py 画成 Min/Max 两列（而不是通用的 x/y），并在 max < min 时给出
    崩溃风险提示。"""
    if node.data_type != "OBJECT" or len(node.children) != 2:
        return False
    if {c.key for c in node.children} != {"x", "y"}:
        return False
    return node.key in _MIN_MAX_FIELD_NAMES


# vendor EfxCommon.cs 的 `MdfProperty`（TypeMesh/TypeMeshExpression 等结构体 `properties`
# 数组的元素类型：材质贴图/数值属性表）。不是多态的 `EFXAttribute` 子类，JSON 里没有 `$type`
# 判别字段，只能按子键集合的形状识别——这三个键是所有版本都稳定存在的子集：
# `mdfPropertyIndex` 有版本门控、`value` 的子键形状随 `parameterType`（Texture/Range/...）
# 变化，都不能当判据。
_MDF_PROPERTY_KEYS = frozenset({"PropertyNameUTF8Hash", "parameterType", "flags"})


def is_mdf_property_node(node: EFXValueNode) -> bool:
    """一个 OBJECT 节点如果是材质属性数组（TypeMesh 系列 attribute 的 `properties` 字段）里的
    单个元素，返回 True。供 panels.py 递归绘制它的子字段（`PropertyNameUTF8Hash`/
    `mdfPropertyIndex`/`parameterType` 等）时，把知识表查询的 `attr_type` 换成合成类型名
    `"MdfProperty"`——这个名字不对应任何真实 C# `$type` 字符串，只是知识表里复用的一个键，
    因为这批字段在所有引用 `MdfProperty` 的 attribute 类型间是完全相同的物理布局，不需要
    按外层 attribute 类型分别标注。"""
    if node.data_type != "OBJECT":
        return False
    return _MDF_PROPERTY_KEYS <= {c.key for c in node.children}


def find_field(fields, key: str):
    """在一个 `EFXValueNode` collection（如 `obj.efx_fields`）里按顶层 `key` 找第一个匹配的
    节点，找不到返回 `None`。"""
    for node in fields:
        if node.key == key:
            return node
    return None


_TRANSFORM3D_KEYS = ("LocalPosition", "LocalRotation", "LocalScale", "RotationOrder")


def transform3d_field_values(obj: Object):
    """从一个 attribute 对象的 `efx_fields` 里探测并读出 `EFXAttributeTransform3D`
    （`EfxTransform.cs:104-116`）的 `(pos_xyz, rot_xyz, scale_xyz, rotation_order_raw)`——
    只按字段 key 结构性判断（`LocalPosition`+`LocalRotation`+`LocalScale`+`RotationOrder`
    四键同时存在且都是三分量向量/标量形状），不用 `$type` 精确字符串匹配，原因同
    `is_clip_attribute_dict()`。四键有一个不存在或形状不对就返回 `None`——已核对同样带
    `LocalRotation`+`RotationOrder`（+`LocalScale`）组合的其它 attribute 类型
    （`EmitterShape3D`、`MeshEmitter`/`V2`、`Fade` 系列）均没有 `LocalPosition`，四键齐全
    目前只有 `EFXAttributeTransform3D` 一个类型命中。`rotation_order_raw` 原样返回该节点的
    标量值（`str` 枚举名或 `int` 下标），换算交给 `coords.rotation_order_to_euler_order()`。
    只读，不写——供 `transform3d_view.py` 算视口变换用，不参与导出。"""
    nodes = [find_field(obj.efx_fields, key) for key in _TRANSFORM3D_KEYS]
    if any(node is None for node in nodes):
        return None
    pos_node, rot_node, scale_node, order_node = nodes
    pos = read_xyz_node(pos_node)
    rot = read_xyz_node(rot_node)
    scale = read_xyz_node(scale_node)
    if pos is None or rot is None or scale is None:
        return None
    if order_node.data_type == "STRING":
        order_raw = order_node.string_value
    elif order_node.data_type == "INT":
        order_raw = order_node.int_value
    else:
        order_raw = 0
    return pos, rot, scale, order_raw


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


def is_expression_attribute_dict(attr_dict: dict) -> bool:
    """一个 attribute 字典是不是 `IExpressionAttribute`（vendor `EfxFile.cs:993`，同一个
    BitSet 家族的公式版本——`ExpressionBits` 选中哪些位由公式驱动，每个置位对应一条
    `EFXExpressionObject`）。只按字段 key 结构性判断（`Expression`+`ExpressionBits` 同时
    存在），不维护硬编码类型清单，原因同 `is_clip_attribute_dict()`。

    不需要 `is_clip_attribute_dict()` 那种"减去 IMaterialXxxAttribute"的排除逻辑——
    `IMaterialExpressionAttribute` 暴露的是完全不同的键名 `MaterialExpressions`（没有配对的
    bits 键），不会和这两个键撞名，两个检测函数可以在同一个 attribute 上同时命中（见
    `is_material_expression_attribute_dict()`）。
    """
    return "Expression" in attr_dict and "ExpressionBits" in attr_dict


#: `IMaterialExpressionAttribute` 里**语料验证过、真的见过非空条目**的三个类型：
#: `TypeBillboard3DMaterialExpression` 14 例、`TypeRibbonLengthMaterialExpression` 12 例
#: （`Art\VFX` 9175 个文件扫描），`TypeMeshExpression`（`11_sfc_052.efx.5571972`，3 个实例，
#: 含一条 2 条目的——`OpacityPower`/`Opacity` 两个分量各一条公式）。均已核对 `mdfPropertyHash`
#: 能查到真实材质参数名（EmissiveParam/ChromaColor/OpacityPower/Opacity 等）。
#:
#: 结构上 `IMaterialExpressionAttribute` 还有 8 个同形状的实现类，本函数**故意不做纯结构判断**
#: （不像 `is_clip_attribute_dict()`），只认这几个具体 `$type`——按决定，先只覆盖语料里验证过的。
#: 另外还发现一个真实的坑：`EFXAttributeTypeRibbonParticleMaterialExpression`
#: （`EfxTypeRibbon.cs:1182`）字段上确实有 `materialExpressions`，但类声明**没有**实现
#: `IMaterialExpressionAttribute` 接口——vendor `EfxFile.ParseExpressions()` 的
#: `attr is IMaterialExpressionAttribute` 判断会跳过它，`MaterialExpressions.parsedExpressions`
#: 永远解析不出来。语料里这个类型唯一的一个实例 `materialExpressionCount == 0`（空），没有
#: 真实数据能验证这条路径，先排除在外，等遇到真样本再处理这个额外的 vendor 不一致。
MATERIAL_EXPRESSION_VERIFIED_TYPES = frozenset({
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3DMaterialExpression",
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLengthMaterialExpression",
    "ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshExpression",
})


def is_material_expression_attribute_dict(attr_dict: dict) -> bool:
    """一个 attribute 字典是不是我们已经建了专属 UI 的 `IMaterialExpressionAttribute`
    （`MaterialExpressions`，每条额外带 `mdfPropertyHash`/`propertyComponentIndex`——驱动
    一个 mdf2 材质参数的某个分量，用的是和 `mesh.properties`/`PropertyNameUTF8Hash`
    完全同一张 UTF-8 MurMur3 名字哈希表，见 `semantics.lookup_name_hash()`）。

    按 `$type` 精确匹配 `MATERIAL_EXPRESSION_VERIFIED_TYPES`，不是结构判断——其余 9 个同形状
    的实现类继续走通用树透传，见该常量上面的说明。
    """
    return (
        attr_dict.get("$type", "") in MATERIAL_EXPRESSION_VERIFIED_TYPES
        and "MaterialExpressions" in attr_dict
        and attr_dict.get("MaterialExpressions") is not None
    )


#: vendor 源码里"没起真名，只是编号占位"的字段一律长这个形状：`unkn1`、`unkn5`、`ukn1_7`……
#: （见 EfxCommon.cs/EfxTransform.cs 等），用来把 bit 显示名里的这类占位名和真正有意义的名字
#: （`rotationX` 这种）区分开——见 bit_display_label()。
_PLACEHOLDER_FIELD_NAME_RE = re.compile(r"^(?:unkn|ukn|unk)\d", re.IGNORECASE)


def resolve_expression_bit_name(attr_type: str, bit_index: int) -> str:
    """给一个 `IExpressionAttribute` 的 (`$type`, 0-based bit_index) 查它在 vendor 源码里的
    真实字段名——`EfxBridge bitnames` 反射出的静态表（`semantics/mhws_bit_names.json`），
    覆盖面比单个文件 dump 出的 `ExpressionBits.bitNames`（只包含 vendor 手写进
    `BitNameDict` 的那部分）更全：没起过别名的字段（`ukn1_7` 这种）依然是真实声明的字段，
    这张表按声明顺序把它们也收了进来。查不到（这个类型没实现 `IExpressionAttribute`，或
    bit_index 超出这个类型的字段数）返回空字符串——和 `EFXExpressionCurveItem.bit_name`
    "查不到就留空"的既有约定一致，`sim_preview.collect_expressions()` 靠这个空串跳过没法
    定位目标字段的曲线，不能返回编出来的占位名。"""
    from . import semantics
    names = semantics.get_expression_bit_names(attr_type)
    if not names or bit_index < 0 or bit_index >= len(names):
        return ""
    return names[bit_index] or ""


def resolve_clip_bit_name(attr_type: str, bit_index: int) -> str:
    """同 resolve_expression_bit_name()，查 `IClipAttribute`。Clip 的曲线数据全部挤在同一个
    共享的 `clipData` 里，没有 per-bit 具名字段可反射，绝大多数类型这里永远查不到——如实反映
    vendor 源码里确实没给这些 bit 起过名字（例外见 `EfxBridge bitnames` 的说明），不是我们
    没查到就该编一个。"""
    from . import semantics
    names = semantics.get_clip_bit_names(attr_type)
    if not names or bit_index < 0 or bit_index >= len(names):
        return ""
    return names[bit_index] or ""


def bit_display_label(bit_index: int, bit_name: str) -> str:
    """把 (bit_index, bit_name) 变成面板/下拉菜单里给人看的一行文字。`EFXClipCurveItem`/
    `EFXExpressionCurveItem` 的 `bit_name` 字段本身必须保持"真实字段名或空串"（`sim_preview.
    collect_expressions()` 拿它去精确匹配 sibling attribute 的字段名，不能是装饰过的文本），
    这个函数只用于展示，不回写到 `bit_name` 上。

    三种情况：没有任何名字来源（多数 Clip 类型）-> 裸 `"bit{N}"`；vendor 自己也只给了个占位名
    （`unkn5`/`ukn1_7` 这种）-> `"bit{N} ({name})"`，光看名字分不清彼此时把编号带上；其余
    情况直接显示名字本身，比"第几位"更能说明这一位驱动的是哪个字段。"""
    if not bit_name:
        return f"bit{bit_index}"
    if _PLACEHOLDER_FIELD_NAME_RE.match(bit_name):
        return f"bit{bit_index} ({bit_name})"
    return bit_name


def expression_bit_index_for_field(attr_type: str, field_key: str) -> "int | None":
    """`resolve_expression_bit_name()` 的反函数：给一个字段名，反查它在这个
    `IExpressionAttribute` 类型里对应哪个 bit。bit 和字段是反射验证过的 1:1（全语料核查
    58 个类型，54 个完全对应，见 docs/EXPRESSION_SEMANTICS.md §7.1），所以字段那一行可以
    直接画一个"加/减这条公式"的按钮，不需要再单独维护一份"选哪个字段"的下拉——bit_index
    只是这份数据在文件里的存储位置，不是用户需要关心的另一个身份。

    按**声明顺序做位置匹配**（`attribute_types.expression_assign_field_order()`），不比较
    任何名字——原来这里查的是 `semantics.get_expression_bit_names()`，那张表在某个 bit 有
    `BitNameDict`（vendor 手写的"友好名字"）覆盖时，存的是那个友好名字而不是字段自己的
    C# 名字，字段名找不到就查不到 bit，明明有 bit 却不出现 [+]（已用真实样本
    `EFXAttributeRgbCommonExpression` 复现：`particleColor` 被 `BitNameDict` 起名
    `"GreenChColor"`，找 `"particleColor"` 永远找不到）。换成位置匹配后不再依赖任何
    人工写的名字表，友好名字只在**显示**时（`resolve_expression_bit_name()`）还会用到。

    查不到（这个类型没有反射记录，或这个字段名不是声明成 `ExpressionAssignType` 的字段——
    多数 `TextureUnitExpression` 这类数组形态）返回 `None`，调用方据此判断要不要退回按
    bit_index 操作的旧列表 UI（见 `panels._draw_expression_bit_toggle()` /
    `EFX_RE_UL_expression_curves.filter_items()`）。"""
    from . import attribute_types
    names = attribute_types.expression_assign_field_order(attr_type)
    if not names:
        return None
    try:
        return names.index(field_key)
    except ValueError:
        return None


def find_expression_curve(obj, bit_index: int):
    """`obj.efx_expression_curves` 里 `bit_index` 匹配的那一条，没有则 `None`。"""
    for curve in obj.efx_expression_curves:
        if curve.bit_index == bit_index:
            return curve
    return None


def find_expression_curve_index(obj, bit_index: int) -> "int | None":
    """同 `find_expression_curve()`，返回下标而不是对象——`efx_expression_curves_active_index`
    要的是下标，`collection.remove()` 也要下标，找对象再反查下标容易踩 bpy_struct 相等性的坑，
    不如按 `bit_index` 直接扫一遍拿下标。"""
    for i, curve in enumerate(obj.efx_expression_curves):
        if curve.bit_index == bit_index:
            return i
    return None


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


def _normalize_path_separators(value: str) -> str:
    """RE Engine 的资源路径哈希（`MurMur3HashUtils.GetPakFilepathHash`，vendor
    `Common/MurMur3HashUtils.cs:52`）只对大小写做归一化，**不处理路径分隔符**——`\\` 和 `/`
    会算出两个完全不同的哈希。而 EFX 里但凡是路径形状的字符串字段（`UVSequence.UVSPath` 这种，
    实测过官方语料清一色 `/`），游戏引擎按这个哈希去资源表里查，一旦某个字段被写成反斜杠
    （常见于 Windows 资源管理器复制路径、外部工具误用 `os.path.join` 之类的产物），哈希对不上
    实际打包路径，引用直接失效——真实命中过一次：某 mod 的 `UVSPath` 写成
    `Art\\VFX\\UVS\\Dimcirui\\ak.uvs`，游戏内报"Invalid"，而这个 .uvs 文件本身完好、
    EfxBridge 往返也完全干净，唯一的异常就是这一个字段的分隔符方向。

    两个入口都规整、都在**用户看得见的时候**就改掉，不留到导出时偷偷改（那样会出现"面板里
    看着是对的、导出后又被改写"的困惑）：

    - 导入时 `populate_node()` 对每个 STRING 节点过一遍，对绝大多数官方文件是无操作
      （本来就是正斜杠）；
    - 用户在面板里手打/粘贴时 `string_value` 的 update 回调（`_promote_null_to_string()`）
      再过一遍——只管导入那一次盖不住最容易犯错的场景（从资源管理器复制路径）。

    不作用于 entry/action/bone 名字等其它字符串字段——那些走各自专属的 `StringProperty`
    （`efx_name`/`EFXBoneItem.name` 等），根本不经过这个函数，这个规整只覆盖资源路径可能出现
    的通用内容字段树。UVS 的贴图路径是同一类字段但走的是另一套 PropertyGroup，规整在
    `uvs_model._normalize_texture_path()`。"""
    return value.replace("\\", "/") if "\\" in value else value


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
            node.string_value = _normalize_path_separators(value)
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
    with suppress_field_updates():
        for key, value in mapping.items():
            child = collection.add()
            populate_node(child, key, value)


def children_to_dict(collection) -> dict:
    """populate_dict_as_children 的反函数。"""
    return {child.key: node_to_value(child) for child in collection}


# ---------------------------------------------------------------------------
# EFXGroupTag —— Entry 的 EffectGroups 标签列表
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
    # Range：vendor 注释推测 value1/2/3 是 {初始值, 最小值, 最大值}（样本里初始值总是落在
    # 最小-最大区间内），未证实，tooltip 只保留"可能是什么"，不铺开举证过程（用户文案规则）。
    # Float2：vendor 注释里样本只见过 0.0/1.0，疑似布尔语义，同样未证实。
    ("Range", "Range", "type == Range：value1/value2/value3 三个浮点值都生效，"
                        "可能是{初始值, 最小值, 最大值}（未证实）"),
    ("Float2", "Float2", "type == Float2：value1/value2 两个浮点值生效，value3 未用，"
                          "可能是布尔值（未证实）"),
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
# EFXClipCurveItem —— IClipAttribute 的动画曲线编辑（挂在 EFX_ATTRIBUTE 对象上，不是
# EFX_ROOT——每个 Clip attribute 有自己独立的一份，不是文件级共享表）
#
# 关键帧数据（frame/value/插值选择/Hermite 切线句柄）**不**存在这里，活在 `clip_fcurve.py`
# 建的原生 Blender fcurve 里——用户直接在 Dope Sheet / Graph Editor 里编辑，`io_tree.py`
# 导入/导出时调 `clip_fcurve.import_curve()`/`export_curve()` 在 fcurve 和字节之间搬运。
# `EFXClipCurveItem` 只保留"这条曲线是什么"的结构性字段：驱动哪个 bit、按 Int 还是 Float
# 读取、这条曲线的 fcurve 定位 key。
#
# `FrameInterpolationType` 导入能接受 `{0,1,2,3,4,5,6,8,9,10,11,12,13}`（`7` 除外），但只有
# `{1=Discrete, 2=Linear, 5=Hermite}` 能直接导出，`3=Event` 借的占位名字必须先转成这三种
# 之一才能导出，剩下 9 个"非标准"值（语料从没用过，实机测出大多恒为 0/9 飞天）导入后能在
# Blender 原生下拉框里改成任何类型，但导出前也必须先转成标准三种之一——见 `clip_fcurve.py`
# 模块文档"插值类型语义"一节的完整证据链和分类。`5`（Hermite）借用 Blender 唯一支持自由
# 切线的 `BEZIER` 插值标识符表示（切线要过 ÷3/×3 换算，不是字面 Bezier）。`7`（真 Bezier）
# 是唯一仍然硬拒绝导入的值——不是证据不够，是它会消费 `interpolationData[]` 里的切线槽位，
# 猜错消费顺序会连锁腐蚀同一条曲线里其它 Hermite 帧的数据，属于铁律 #1 要拒绝的风险，跟
# 其它 9 个"纯值+位置，不摸切线数组"的非标准值不是同一类问题。仍未证实的只剩一处：
# `Transform3DClip`/`PtTransform3DClip` 的 bit 顺序（哪个 bit 是位移/旋转/缩放的哪个分量）。
# 详见 `docs/PITFALLS.md` 对应条目和 `clip_fcurve.py` 模块文档。
# ---------------------------------------------------------------------------

# EfxClipPlaybackType（ClipSubstructs.cs:7-12）。vendor 注释原文只是猜测（"might be coded as
# a Playback / loop trigger flag enum"），结构上 4 个取值完全确认，游戏侧真正含义不确认——
# 分开标注，不写进下拉框标签本身。-1/2 的具体猜测（"全部触发循环"/"都不触发循环，手动控制？"）
# 就是 vendor 那句注释的直接转述，tooltip 只留结论，不重复举证过程（用户文案规则）。
_CLIP_LOOP_TYPE_ITEMS = (
    ("-1", "Looping", "loopType == -1：可能是'全部触发循环'（未证实）"),
    ("0", "Unknown", "loopType == 0：语义未知"),
    ("2", "NonLooping", "loopType == 2：可能是'都不触发循环'（未证实）"),
    ("4", "Type4", "loopType == 4：语义未知"),
)

# FrameInterpolationType（ClipSubstructs.cs:33-44）。vendor 注释坦承"这是不是插值方式本身都是
# 猜的"，2026-09-19 语料统计+实机测试确认它和 kagenocookie/RE-Engine-Lib 独立 .clip/.tml 格式
# 共用同一套命名枚举（Unknown/Discrete/Linear/Event/Slerp/Hermite/AutoHermite/Bezier/
# AutoBezier/OffsetFrame/OffsetSec/PassEvent/Bezier3D/Range/...）；真实 MHWS 文件只用到
# `{1=Discrete, 2=Linear, 3=Event, 5=Hermite}`，其余的不是没见过就是实机测出会崩/飞天/恒零。
# 具体的映射表 + 证据链挪到了 clip_fcurve.py（`_INTERP_MHWS_TO_BLENDER`），这里不再维护
# 一份平行的 EnumProperty items——旧的 EFXClipKeyframeItem 删除后，插值类型现在是 Blender 原生
# fcurve 的 `interpolation` 属性，不是这份表驱动的下拉框了。

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
    #: `clip_fcurve.add_channel()` 分配的自定义 ID 属性 key（`obj["efx_clip_ch_<id>"]`），
    #: 这条曲线的 fcurve data_path 就钉在这个 key 上，终身不变、删除后不回收——不用集合下标
    #: 寻址是为了不让"删中间一条曲线，后面的下标全部位移"把别的曲线的 fcurve 挪到错误位置上
    #: （见 model.py 顶部 EFXClipCurveItem 说明和 clip_fcurve.py 模块文档）。
    channel_key: StringProperty(name="Channel Key")


def _expression_node_changed(self, context) -> None:
    """节点行改了值/名字 -> 立刻把整条公式重新拼回 `formula`。

    行视图是文本的视图，不是第二份数据（见 `efx_sim/expr.py` 的结构化编辑一节）：
    每次编辑都全量重拼，不做增量、不留脏标志。"""
    from . import expr_edit
    expr_edit.on_node_edited(self)


class EFXExpressionNodeItem(PropertyGroup):
    """`EFXExpressionCurveItem.formula` 那条公式的**一行**——整棵表达式树按前序摊平成
    这个列表（编码规则和重建逻辑全在 `efx_sim/expr.py` 的 `to_rows()`/`from_rows()`，
    这里只是它那份 dict 的 Blender 容器）。

    为什么摊平：`CollectionProperty` 装不了递归类型，Blender 里表达"树"只能靠线性编码 +
    `depth` 缩进画。`arity`（子节点个数）才是结构的真相，`depth` 是派生的显示量。

    **不参与导出**。导出只读 `formula` 字符串（`io_tree._export_expression_attribute()`），
    这些行任何时候坏掉，最坏也只是拼出一段不同的**文本**——会被桥接的解析器或字节门禁
    抓住，而不是绕过文本偷改二进制。
    """

    kind: EnumProperty(
        name="Kind",
        items=[
            ("CONST", "Constant", "浮点字面量"),
            ("VAR", "Variable", "具名参数或内置外部变量"),
            ("NEG", "Negate", "一元负号"),
            ("CALL", "Call", "中缀运算符或函数调用"),
        ],
        default="CONST",
    )
    depth: IntProperty(name="Depth", min=0)
    arity: IntProperty(name="Arity", min=0)
    #: CALL 行存运算符符号（`+ - * /`）或函数名；VAR 行存变量名；其余为空
    name: StringProperty(name="Name", update=_expression_node_changed)
    #: CONST 行的值。文本形式最多 6 位小数（vendor `ExpressionFloat.ToString()` 的 F6），
    #: 但**全语料 9066 个常量里最多只用到 4 位**（1044 个文件实测：0 位 6685、1 位 1574、
    #: 2 位 633、3 位 132、4 位 42，5/6 位一个都没有），所以 precision 给 4——既不会把
    #: `0.0025` 这种真实取值显示成 `0.003`，又不用让 68% 的整数常量顶着 `15.000000`
    #: 那一串零（用户反馈的"数字占满整行、像一张数字表"里的一半原因）。
    value: FloatProperty(name="Value", precision=4, update=_expression_node_changed)

    # 同 `EFXValueNode.degrees_value`（同一个 `subtype="ANGLE"` 技巧：Blender 的属性控件
    # 自动按度显示/接受输入，get/set 原样传回弧度，不需要手动 math.degrees()/radians()）。
    # 只在这个 CONST 槽位被 `expr_edit._curve_wants_degrees()` 判定"和这条曲线的目标字段
    # 同一个单位（角度）"时才画它而不是裸的 `value`——**不是**"这条曲线里的每个常量都换算"，
    # `Lerp(-30, 190, SmoothStep(0, 120, TIMER))` 的 `0`/`120` 是帧数阈值，被当角度换算会把
    # `SmoothStep` 的重映射区间整个改坏，见 `efx_sim/expr.py::propagate_same_unit_as_root()`。
    degrees_value: FloatProperty(
        name="Value", subtype="ANGLE",
        get=lambda self: self.value,
        set=lambda self, value: setattr(self, "value", value),
    )


def _active_expression_curve_changed(self, context) -> None:
    """曲线列表切了一条 -> 节点视口跟着切（没打开过节点视口就是个空操作）。

    放在这里而不是在 `EFX_RE_OT_expression_curve_activate` 里：切换活动曲线有好几个
    入口（列表点选、字段行内嵌的单选点、增删曲线之后的 index 重定位），逐个入口加一行
    迟早漏一个，属性值本身的 update 回调是唯一盖得全的挂钩点。
    """
    from . import expr_nodes
    expr_nodes.on_active_curve_changed(self)


def _expression_formula_changed(self, context) -> None:
    """公式文本改了（用户手打、导入、结构化编辑以外的任何来源）-> 重新解析成节点行。

    解析失败不清空文本、也不静默放过：记进 `formula_error`、把行清空，面板据此只显示
    错误和原始文本框（铁律 #1：宁可让用户看见一条炸了的公式，也不给他一棵半成品的树）。
    """
    from . import expr_edit
    expr_edit.on_formula_edited(self)


# 两种加载方式都要能跑，理由同 `expr_edit.py` 顶部那段：装成扩展时 `efx_sim` 是**叔叔包**，
# 门禁脚本把仓库根塞进 sys.path 直接 `import blender_efx_re` 时 `..` 已经越界。
# ⚠ **必须在模块级 import**，别挪进函数体里：挪进去之后 `ImportError` 会被下面那个
# 兜底 `except` 吞掉，表现是"公式栏整栏空白"，而且一条错误都不报——实测踩过。
try:
    from ..efx_sim import expr as _expr_mod, expr_text as _expr_text
except ImportError:  # pragma: no cover - 只在门禁/单测的顶层包布局下走到
    from efx_sim import expr as _expr_mod, expr_text as _expr_text


def _read_formula_canonical(self) -> str:
    """`formula`（vendor 记法）-> 规范记法，供界面显示/编辑。

    **纯派生量，不存**——`formula` 始终是唯一权威（`expr_edit` 模块 docstring 的第 1 条）。

    转换失败返回空串：这时 `formula_error` 已经在说话了，再塞一段坏文本只会更乱。
    ⚠ **只吞 `ExprError`**。这里原来是 `except Exception`，结果把上面那条 import 的
    `ImportError` 一起吞了——整个公式栏空白、日志里一个字都没有。面板 getter 里的宽
    `except` 就是这么变成隐形故障的。
    """
    try:
        return _expr_text.vendor_to_canonical(self.formula)
    except _expr_mod.ExprError:
        return ""


def _write_formula_canonical(self, value) -> None:
    """规范记法 -> `formula`，随后由 `formula` 自己的 update 回调重建行。

    转换失败**不动 `formula`**，只把原因写进 `formula_error`——和 `write_formula()`
    同一条纪律（铁律 #1：宁可让用户看见报错，也不静默写一条内容不对的公式）。
    """
    try:
        self.formula = _expr_text.canonical_to_vendor(value)
    except _expr_mod.ExprError as exc:
        self.formula_error = str(exc)


class EFXExpressionCurveItem(PropertyGroup):
    """对应 `IExpressionAttribute` 的一条公式（`ExpressionBits` 里的一个置位 + 它驱动的一个
    `EFXExpressionObject`）。和 `EFXClipCurveItem` 是同一个 BitSet 家族——`bit_index` 的
    0-based 语义、"子曲线数组下标和排序后的置位 bit 下标一一对应"的约定完全相同（见
    `EFXClipCurveItem` 的说明），已用真实样本验证（`11_guide_006` 里 `bit_name == "color"`
    的那条公式是 `Lerp(color_N, colorR_N, IsBlue)`，语义吻合）。

    公式本身不存成后缀栈（`EFXExpressionObject.components`），存成 vendor 自带的文本表示
    （`formula`，如 `"Min(1, Clamp(TIMER, 30, 150))"`）——`EfxExpressionStringParser`/
    `EFXExpressionTree.ToString()` 已经是现成、经过测试的双向转换（`EfxExpressionParser.cs`），
    没有必要在 Python 这边再实现一遍递归下降解析器和优先级规则；后缀栈↔树↔文本的转换全部交给
    EfxBridge（dump 时调用 `EfxFile.ParseExpressions()`，load 时调用
    `EfxFile.FlattenExpressionTrees()`，见 tools/EfxBridge/Program.cs）。`formula_error` 是
    纯 UI 态（"Validate" 按钮的校验结果），不参与导出。
    """

    bit_index: IntProperty(name="Bit Index", min=0)
    bit_name: StringProperty(name="Bit Name")
    formula: StringProperty(name="Formula", default="0",
                            update=_expression_formula_changed)
    formula_error: StringProperty(name="Error")
    #: `formula` 的**规范记法**视图（`efx_sim/expr_text.py`）：符号和函数与引擎记法相同，
    #: 但按数学惯例读结构（左结合、少括号）——vendor 的解析器是右结合的，`10 - 3 - 2`
    #: 直接交给它会读成 `10 - (3 - 2)`。派生量，不存、不参与导出。
    formula_canonical: StringProperty(
        name="Formula", description="按数学惯例读写的公式",
        get=_read_formula_canonical, set=_write_formula_canonical)
    #: `formula` 的结构化视图，见 `EFXExpressionNodeItem`。派生量，不参与导出。
    nodes: CollectionProperty(type=EFXExpressionNodeItem)
    #: **当前选中的那个槽位**（= 该槽位内容所在的行下标）。界面纵向展开的那条链、
    #: 检查器编辑谁、视口 HUD 画哪一级曲线，全由它一个整数决定（按钮不逐行摆，
    #: 理由见 `expr_edit.draw_nodes()`）。纯 UI 态。
    nodes_active_index: IntProperty(name="Active Node")
    #: `a  |  b` 第二根值的原始文本（vendor `ExpressionRootValueOption`，语义未证实）。
    #: 结构化编辑只动第一支，这一支原样存着、拼回去时原样带上——没证实语义不是丢数据的
    #: 理由（铁律 #1）。
    second_branch: StringProperty(name="Second Root Value")
    #: 这棵树的参数表（`EFXExpressionTree.parameters`）原样存成 JSON，**不透传就丢数据**。
    #:
    #: 公式文本里一个普通标识符（`PI`、`Length`…）到底是"引擎运行时喂进来的外部变量"还是
    #: "值存在文件里的具名常量"，**文本上完全看不出来**——两者都写成那个名字。真相在这张
    #: 表的 `source` 字段（0=Parameter / 1=Constant / 2=External）和 `constantValue` 上。
    #:
    #: 这里原来写死成空数组，后果是**导入任何用了 `PI` 的官方特效再导出，π 就变成 0**：
    #: 语料里 `PI` 一律是 `source=1, constantValue=3.1415927`（6 个文件 110 处，无一例外），
    #: 表丢了之后解析器只能按名字回退成 `source=2`（External），而引擎没有东西绑给它。
    #: 实测确认过这条链（铁律 #1：宁可拒绝也不静默丢数据）。
    tree_parameters: StringProperty(name="Tree Parameters", default="[]")


def _material_expr_assign_type_items(self, context):
    """`EFXMaterialExpressionItem.assign_type` 的下拉选项——复用普通 Expression 那套
    `ExpressionAssignType`（`attribute_types.expression_assign_type_members()`），见字段
    定义处的说明。当前值如果不在这五个成员里（语料里没见过，防御性处理，铁律 #1：
    宁可多出一条看不懂的选项，也不能让 EnumProperty 校验失败把这个值悄悄丢掉）就补一条
    原样数值的兜底项。"""
    items = attribute_types.expression_assign_type_members()
    out = [(str(value), label, "", 0, value) for value, label in items]
    known = {value for value, _ in items}
    current = self.assign_type_raw
    if current not in known:
        out.append((str(current), str(current), "", 0, current))
    return out


def _read_material_expr_assign_type(self):
    return self.assign_type_raw


def _write_material_expr_assign_type(self, value):
    self.assign_type_raw = value


class EFXMaterialExpressionItem(PropertyGroup):
    """对应 `IMaterialExpressionAttribute` 的一条公式（`MaterialExpressions.expressions` 里
    的一个 `EFXMaterialExpression`）——结构上是 `EFXExpressionCurveItem` 的近亲（同一棵
    `EFXExpressionObject` 树、同一套 vendor 记法/规范记法双向转换），少了 `bit_index`/
    `bit_name`（这里没有 bits，条目就是平铺数组，导入顺序即导出顺序），多了几个字段：
    `mdf_property_hash`/`component_index`（这条公式驱动哪个 mdf2 材质参数的哪个分量）+
    `assign_type`/`is_color`/`struct3_count`/`is_single_param`（原 `unkn1`/`unkn2`/
    `unkn5`——2026-09-18 全语料 720 条相关性排查后拟的名字，`struct3_count` 仍然是纯未知
    字段，必须原样透传，见各自字段上面的说明——`is_single_param` 那条记录了一次真实踩过
    的静默丢数据）。见
    `model.is_material_expression_attribute_dict()` 上面关于验证范围的说明。

    `formula`/`formula_error`/`formula_canonical`/`nodes`/`nodes_active_index`/
    `second_branch`/`tree_parameters` 复用和 `EFXExpressionCurveItem` 完全相同的字段名 +
    完全相同的模块级函数（`_expression_formula_changed`/`_read_formula_canonical`/
    `_write_formula_canonical`）——`expr_edit.py` 的结构化编辑器（`draw_nodes()`/
    `on_formula_edited()`/`unknown_variable_names()`）全部只按这几个字段名读写、不认
    具体类型，两边免费共用一套。**没有复用**的只是 `expr_nodes.py` 的独立节点视口（那边
    硬编码了 `obj.efx_expression_curves`/`efx_expression_curves_active_index`，v1 范围
    不含增删条目、只有单条/极少条目，划不来为这一个视口再抽一层）——面板内嵌的行视图
    （`expr_edit.draw_nodes()`）已经是完整的结构化编辑能力，只是没有独立弹窗。

    增删只开放"复制/删除已有条目"这一半（`structure_ops.EFX_RE_OT_material_expression_
    duplicate`/`_remove`）：`MaterialExpressionList.indices`（容器级，`uint[]`，语义未证实——
    docs/TOPLEVEL_STRUCTURE.md 记过同形状的 Clip 版本 `indices` 一样没解出来）原样存成
    `Object.efx_material_expression_indices` 的 JSON 字符串、导出原样写回。2026-09-18 拿
    504 个真实实例 + 各自引用的 .mdf2 交叉核对过：`indices` 的**长度**几乎总是等于列表里
    "去重后的材质参数个数"（487/498 吻合），但具体**数值**既不是 mdf2 参数表下标、也不是
    文件级连续计数器，没解出来——复制/删除已有条目不改变"去重后的参数集合"，这个操作是
    安全的；引入一个列表里全新的材质参数需要往 `indices` 里加一项，不知道该填什么，所以
    "新增指向全新参数的条目"还是不支持（铁律 #1/#3）。
    """

    #: mdf2 材质参数名的 MurMur3(UTF-8) 哈希，十进制字符串存储（同 `EFXValueNode.uint_str`
    #: 的 BIGINT 约定）——不能用裸 `IntProperty`：Blender `IntProperty` 是有符号 32 位，
    #: 这里的真实取值（如 `2961540764`）超过 `2^31-1`，赋值会被静默截断/钳位（不是崩溃，
    #: 是悄悄变成另一个数——比 `model.as_int32()` 文档里那个 EnumProperty 崩溃案例更隐蔽）。
    #: 显示名靠 `semantics.lookup_name_hash()` 查（和 `panels._mdf_property_name()` 同一张表，
    #: 已用真实语料核对：`EmissiveParam`/`EmissiveIntensityParam`/`ChromaColor` 三个哈希全部
    #: 命中）。
    mdf_property_hash: StringProperty(name="Mdf Property Hash", default="0")
    #: 这条公式驱动目标属性的哪个分量（vendor 原话"e.g. 0/1/2 for the X/Y/Z of a Vector3
    #: property"，`ExpressionData.cs:171`）——显示裸下标，不编 X/Y/Z/W 标签：`Range` 形状的
    #: mdf 属性分量顺序另有一套约定（`_draw_mdf_property_value()` 的 Z/W 说明），没有交叉
    #: 验证过这里是否是同一套顺序。
    component_index: IntProperty(name="Param Index", min=0)
    #: `EFXMaterialExpression.unkn1`（vendor 声明是裸 `uint`），2026-09-18 全语料 720 条
    #: `IMaterialExpressionAttribute` 条目排查：取值只出现过 0/2/3/4，落在
    #: `ExpressionAssignType`（`EfxCommon.cs`：Add=0/Subtract=1/Multiply=2/Divide=3/
    #: Assign=4）的合法范围内，且和普通 Expression 的 `translationX` 等字段是同一个 C#
    #: 枚举——**这是取值范围/语义家族的强相关性，不是实机确认**，仍然只是
    #: 拟定的字段名，不是坐实的结论。真正的存储槽是 `assign_type_raw`（原始 uint，防御性
    #: 兜底见 `_material_expr_assign_type_items()`），`assign_type` 是画下拉用的
    #: EnumProperty 代理。
    assign_type_raw: IntProperty(name="Assign Type (raw)", default=4)
    assign_type: EnumProperty(
        name="Assign Mode", description="公式结果与原属性值的合并方式",
        items=_material_expr_assign_type_items,
        get=_read_material_expr_assign_type, set=_write_material_expr_assign_type,
    )
    #: `EFXMaterialExpression.unkn2`，2026-09-18 全语料排查：取值 0/1 且和
    #: `propertyComponentIndex==0` 完全重合，勾选（=1）的实例公式里大量出现
    #: `GREEN`/`RED`/`WHITE`/`Aka`(赤)/`Kuro`(黒)/`Shiro`(白) 这类具名颜色常量——很像
    #: "这条公式在算颜色"的标记，但同样**只是相关性，不是实机确认**（不把猜测当事实），字段名
    #: 按用户 2026-09-18 拍板拟定，问号提醒这是猜测不是定论。
    is_color: BoolProperty(name="isColor?", description="公式输出颜色值（未验证）")
    #: `EFXExpressionObject.struct3Count`（`ExpressionData.cs:126`，vendor 自己的 TODO 是
    #: "seems to affect the struct somehow if != 0; maybe it reads type info from the header
    #: parameter list directly"）——原样透传，不能让它悄悄变成 0：`EfxBridge` 的
    #: `FlattenExpressionTree()` 造的是一个全新 `EFXExpressionObject()`，默认值就是 0，不会
    #: 自己带回原来的值。语料实测（720 条）这个字段恒为 0（不是下面 `is_single_param` 那种
    #: 真的踩过非零值的情况），但结构上和它是同一类风险，一起补上、不单独放过。真正未知，
    #: 不拟名字。
    struct3_count: IntProperty(name="struct3Count", default=0)
    #: `EFXMaterialExpression.unkn5`（`ExpressionData.cs:175`），`[RszVersion(EfxVersion.RE4)]`
    #: ——**别被这个名字骗了**：`RszVersion(X)` 在生成器里翻译成 `Version >= X`（不是"只在
    #: 等于 X 时"），MHWs 的版本号远大于 RE4，这个字段对 MHWs **是真实存在、会读写的**。
    #: 已用真实样本踩过（`11_sfc_052.efx.5571972` 的 3 条 `TypeMeshExpression` 条目原始值是
    #: 1）：第一版实现误判成"RE4 专属、MHWs 用不到"完全没处理，结果编辑任意一条公式都会把
    #: 同一个 attribute 上其它条目的这个字段静默清成 0（逐字节门禁抓到的，铁律 #1）。
    #: `UndeterminedFieldType` 就是一个裸 32 位值（`EfxStructInfo.cs:103`，可能是 int/uint/
    #: float 的位模式，不确定）。2026-09-18 全语料排查：取值 0/1 且和
    #: `propertyComponentIndex==1` 完全重合（`SandEffectRate` 那个"反例"拆开分量看之后其实
    #: 完全符合，不是真反例，见 docs/EXPRESSION_SEMANTICS.md），猜想是"这个 mdf 参数是否
    #: 独占寄存器、可以广播到全部分量" vs "打包共享寄存器、必须定向写某个分量"——同样只是
    #: 相关性，`RoughnessParam` 那个标量但仍需定向写的反例已经推翻过"标量就是它"这个更早的
    #: 简单假说，问号提醒这是猜测不是定论。
    is_single_param: BoolProperty(
        name="isSingleParam?", description="语料统计推测：参数独占寄存器（未验证）"
    )
    #: 面板展开状态，纯 UI 态，不参与导出。
    ui_expand: BoolProperty(name="Expand", default=True)

    formula: StringProperty(name="Formula", default="0", update=_expression_formula_changed)
    formula_error: StringProperty(name="Error")
    formula_canonical: StringProperty(
        name="Formula", description="按数学惯例读写的公式",
        get=_read_formula_canonical, set=_write_formula_canonical)
    nodes: CollectionProperty(type=EFXExpressionNodeItem)
    nodes_active_index: IntProperty(name="Active Node")
    second_branch: StringProperty(name="Second Root Value")
    tree_parameters: StringProperty(name="Tree Parameters", default="[]")


# ---------------------------------------------------------------------------
# 不透明剩余字段 —— 存成 bpy.data.texts 文本块，import/export 两边共用
# ---------------------------------------------------------------------------

def save_opaque(obj, mapping: dict) -> None:
    """把一个 dict 原样存成一个文本块，obj.efx_opaque_text 记录文本块名字。

    `obj` 可以是 Object 也可以是 Collection（EFX_ROOT 是集合）——只用到 `.name` 和
    `.efx_opaque_text`，两边都有。"""
    text_name = f"{obj.name}.opaque.json"
    text = bpy.data.texts.get(text_name) or bpy.data.texts.new(text_name)
    text.clear()
    text.write(json.dumps(mapping, ensure_ascii=False))
    obj.efx_opaque_text = text.name


def load_opaque(obj) -> dict:
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
    EFXExpressionParamItem, EFXClipCurveItem,
    # EFXExpressionNodeItem 必须排在 EFXExpressionCurveItem/EFXMaterialExpressionItem 前面：
    # 两者的 `nodes: CollectionProperty(type=...)` 在注册时都要求前者已经注册过。
    EFXExpressionNodeItem, EFXExpressionCurveItem, EFXMaterialExpressionItem,
)


def _sync_object_name(self, context) -> None:
    """改了 efx_name 就顺手把 Blender 对象也改名，不然 Outliner 里还是旧名字。

    对象名撞名时 Blender 会自己加 `.001`，那只影响显示、不影响导出（导出走 efx_name 和
    parent 链，不看对象名）。子 attribute 的对象名带着父级名前缀（`[Entry] Life`），这里
    **不**跟着重命名——那只是导入时生成的一次性显示名，跟着改反而会让正在看的列表跳来跳去。

    `~TYPE == EFX_ENTRY` 时目标名还要带上 `entry_display_suffix()` 那个后缀（" (Mesh, PtLife)"
    这种）以及 `[{efx_index:03d}] ` 序号前缀（见 `refresh_entry_display_name()` 的说明：Outliner
    按字母序排、不看 `efx_index`，前缀保证显示顺序永远等于真实顺序）——不然用户一改名字，
    刚导入时带着的后缀/前缀就被这里悄悄抹掉了，比"从来没有"更容易让人以为是 bug。Action 没有
    这个概念（同姊妹项目："action/extern 无渲染主体概念"），照旧只用 efx_name 本身。
    """
    if not self.efx_name:
        return
    try:
        target = self.efx_name
        if self.get("~TYPE") == TYPE_ENTRY:
            target = f"[{self.efx_index:03d}] {target}{entry_display_suffix(_entry_attribute_suffix_pairs(self))}"
        if self.name != target:
            self.name = target
    except Exception:  # 对象正被删除等边缘情况，改名失败不该拖垮属性赋值
        pass


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # EFX_ROOT / EFX_ENTRY / EFX_ACTION / EFX_ATTRIBUTE 通用：原样透传、未建编辑 UI 的剩余
    # 字段，存成一个 bpy.data.texts 文本块，这里只存文本块名字。
    Object.efx_opaque_text = StringProperty(
        name="Opaque JSON",
        description="未建字段级 UI 的剩余键值，原样存成文本块，导出时原样塞回去",
    )
    # EFX_ROOT 是集合，它的剩余字段也要有地方放——save_opaque()/load_opaque() 只用到
    # `.name` 和 `.efx_opaque_text`，Object 和 Collection 都满足，同一套函数通用。
    Collection.efx_opaque_text = StringProperty(
        name="Opaque JSON",
        description="未建字段级 UI 的剩余键值，原样存成文本块，导出时原样塞回去",
    )

    # EFX_ATTRIBUTE 专属：PlayEmitter 内嵌的那个完整 EfxFile 对应的根集合。
    #
    # 这是"根改成集合"之后唯一需要新加的机制：MHWs 的 PlayEmitter **内嵌一整个 EfxFile**
    # （组合，不是引用），以前靠 `nested_root_obj.parent = attribute_obj` 表达归属，但
    # Collection 根本没有 parent 属性、挂不到 Object 下面。所以反过来，让 attribute 拿一个
    # 指针指向它的嵌套根集合。姊妹项目 EFX-Editor 没这个问题——MHWI 的对应物 EFX_EXTERN 是
    # 对外部文件的*引用*，不是嵌进来的完整文件。
    Object.efx_nested_root = PointerProperty(
        type=Collection,
        name="Nested EFX",
        description="PlayEmitter 内嵌的 efxrData 对应的根集合",
    )

    # EFX_ATTRIBUTE 专属（只对 TypeMesh 系列有意义）：参考 .mdf2 的磁盘路径。
    # `properties` 是一张"覆盖了材质第几号参数"的稀疏表，能加哪些、下标填几只有材质本身知道
    # （见 mdf_catalog.py），所以增删这张表之前要先指一个参考材质。挂在 attribute 上而不是做成
    # 全局设置：不同 mesh attribute 引用的是不同材质。**不参与导出**——
    # `io_tree.export_attribute_object()` 只读 efx_fields 那几样，这里纯粹是编辑期状态。
    Object.efx_mdf_reference = StringProperty(
        name="Reference Material",
        description="参考 .mdf2 的路径，决定这张覆盖表能加哪些参数",
        subtype="FILE_PATH",
    )
    # 载入参考材质时算出来的"和材质对不上的条目"，存成逗号分隔的参数名哈希，供面板逐行标红。
    # 存结果而不是每次画的时候现算：现算要解析 .mdf2，而 draw() 里不能跑子进程。同样不参与导出。
    Object.efx_mdf_mismatched = StringProperty(
        name="Mismatched Properties",
        description="和参考材质对不上的条目（参数名哈希），载入参考材质时算出来",
    )

    # EFX_ENTRY/EFX_ACTION/EFX_ATTRIBUTE 通用：记录 import 时在所属列表（Entries/Actions/
    # Attributes）里的原始下标，导出时按这个值排序还原顺序——不依赖 Blender children/collection
    # 的迭代顺序（未必稳定），沿用 EFX-Editor build_local_index_map 的做法。当前阶段没有做
    # 拖拽重排 UI，这个下标只反映 import 时的原始顺序。
    # EFX_ENTRY / EFX_ACTION 的游戏侧名字。**不复用 Blender 的对象名**：Blender 对象名全局
    # 唯一，撞名会被自动加 `.001` 后缀，而 EFX 里两个 entry 完全可以同名——拿对象名当数据会
    # 静默改掉用户的名字。这里单独存一份，对象名只作显示用。
    #
    # 改名是安全的：写出时 C# 侧会按 name 重算 nameHash（EfxFile.cs `EFXEntry.DoWrite` /
    # `EFXAction.DoWrite`），文件头的字符串表也按 Entries/Actions 的 name 整体重建
    # （`Strings.EfxNames = Entries.Select(e => e.name ...)`），不存在改了名字对不上哈希的问题。
    Object.efx_name = StringProperty(
        name="EFX Name",
        description="这个 Entry/Action 在 EFX 文件里的名字",
        update=_sync_object_name,
    )

    Object.efx_index = IntProperty(name="Original Index")

    # EFX_ENTRY 专属：EffectGroups 标签（对应 EFXEntry.Groups）。
    Object.efx_groups = CollectionProperty(type=EFXGroupTag)
    Object.efx_groups_active_index = IntProperty()

    # EFX_ENTRY 专属：EfxEntryEnum（见 ENTRY_ASSIGNMENT_ITEMS 的说明）——决定这个 Entry 的
    # Groups 标签是否真的生效，2026-09-10 之前完全没有编辑 UI，是复制/粘贴出来的 Entry
    # 悄悄带着错误值、EffectGroups 不生效却查不出原因的根源。
    Object.efx_entry_assignment = EnumProperty(
        name="Entry Assignment", items=ENTRY_ASSIGNMENT_ITEMS, default="0",
        description="决定 Groups 标签会不会生效，不是纯展示字段——新建 Entry 默认就是"
                    "正确值，只有从别处复制/粘贴来的 Entry 才可能需要手动改这个",
    )

    # EFX_ROOT 专属：import 时的原始文件名（含 `.efx.5571972` 版本号后缀）。RE Engine 的
    # 格式版本号只存在于文件名里，不在文件内容里，导出时必须带上，否则谁都读不回来——见
    # operators.py 模块头部说明。这里记住它，好让 Export 的默认文件名直接沿用。
    # 挂在 Collection 上：EFX_ROOT 是集合。Object 上那份留着，给以后可能需要的场景
    # （目前只有根用得上）。
    Collection.efx_source_filename = StringProperty(
        name="Source Filename",
        description="导入时的原始文件名（含版本号后缀），导出时作为默认文件名",
    )
    Object.efx_source_filename = StringProperty(
        name="Source Filename",
        description="导入时的原始文件名（含版本号后缀），导出时作为默认文件名",
    )
    # EFX_ROOT 专属：导入时这个文件所在的**目录**。给资源解析用——它引用的 .mesh/.uvs/.tex
    # 绝大多数就在它自己那棵 natives/STM 树里，从这里向上回溯就能找到那棵树的根
    # （见 asset_paths.roots_from()）。不参与导出，纯编辑期状态。
    Collection.efx_source_dir = StringProperty(
        name="Source Directory",
        description="导入时这个 EFX 所在的目录，用来在它旁边的 natives 树里找引用的资源",
        subtype="DIR_PATH",
    )
    # EFX_ROOT 专属：导入时是**在首选项里勾了"绕过骨骼绑定对齐校验"**的情况下放行的
    # （正常出厂行为是直接拒绝导入，见 preferences.py / io_tree.check_bone_relation_alignment()）。
    # 只用来在导出这个树时再警告一次"绑定可能已错位、导出会丢槽位"，不参与导出字节。
    Collection.efx_bone_alignment_bypassed = BoolProperty(
        name="Bone Alignment Bypassed",
        description="这个树导入时骨骼绑定索引对不上、是按设置放行的，导出前请确认绑定是否正确",
    )

    # 以下四组挂在 **Collection** 上而不是 Object：EFX_ROOT 就是那个紫色集合本身
    # （见 io_tree.build_root_from_efxfile），没有根 Empty。
    #
    # EFX_ROOT 专属：文件级命名骨骼表（对应 EfxFile.Bones）。任何 attribute 的 ParentBone
    # 字段都靠名字引用这里的条目（见 is_bone_reference_field()/panels.py 的 prop_search），
    # 不是裸下标——真正的裸下标表 BoneRelations 完全由 C# 后端导出时重算，见
    # ROOT_STRUCTURAL_KEYS 的说明。
    Collection.efx_bones = CollectionProperty(type=EFXBoneItem)
    Collection.efx_bones_active_index = IntProperty()

    # EFX_ROOT 专属：文件级具名参数表（对应 EfxFile.FieldParameterValues），见
    # EFXFieldParameterItem 的说明。
    Collection.efx_field_parameters = CollectionProperty(type=EFXFieldParameterItem)
    Collection.efx_field_parameters_active_index = IntProperty()

    # EFX_ROOT 专属：外部 .uvar 引用表（对应 EfxFile.UvarGroups），最多 2 项，见
    # EFXUvarGroupItem 的说明。
    Collection.efx_uvar_groups = CollectionProperty(type=EFXUvarGroupItem)
    Collection.efx_uvar_groups_active_index = IntProperty()

    # EFX_ROOT 专属：公式引擎具名参数表（对应 EfxFile.ExpressionParameters），见
    # EFXExpressionParamItem 的说明。
    Collection.efx_expression_parameters = CollectionProperty(type=EFXExpressionParamItem)
    Collection.efx_expression_parameters_active_index = IntProperty()

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
    # 曲线（对应 clipData/clipBits），见 EFXClipCurveItem 的说明。关键帧数据本身活在
    # clip_fcurve.py 建的原生 fcurve 里，不在这几个属性里。
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
    # `clip_fcurve.add_channel()` 分配 `EFXClipCurveItem.channel_key` 用的单调计数器——只增不减、
    # 用过的编号即使曲线被删也不回收，保证每条曲线的 fcurve data_path 终身唯一稳定（见
    # EFXClipCurveItem.channel_key 的说明）。
    Object.efx_clip_next_channel_id = IntProperty()

    # EFX_ATTRIBUTE 专属，只在 is_expression_attribute_dict() 命中时有意义：
    # IExpressionAttribute 的公式列表（对应 Expression/ExpressionBits），见
    # EFXExpressionCurveItem 的说明。efx_is_expression_attribute 同 efx_is_clip_attribute，
    # 持久标记，不靠"curves 是不是空"判断。
    Object.efx_is_expression_attribute = BoolProperty(name="Is Expression Attribute")
    Object.efx_expression_bit_count = IntProperty(
        name="Bit Count",
        description="ExpressionBits 的总位数，由 attribute 类型固定，导入时原样记录，不可编辑",
    )
    Object.efx_expression_curves = CollectionProperty(type=EFXExpressionCurveItem)
    Object.efx_expression_curves_active_index = IntProperty(
        update=_active_expression_curve_changed)

    # EFX_ATTRIBUTE 专属，只在 is_material_expression_attribute_dict() 命中时有意义：
    # IMaterialExpressionAttribute 的公式列表（对应 MaterialExpressions），见
    # EFXMaterialExpressionItem 的说明。增删只开放复制/删除已有条目那一半（见类文档字符串），
    # efx_material_expression_indices 是容器级 `indices` 数组的原样透传（JSON 字符串，
    # 语义未证实，见该属性说明）。
    Object.efx_is_material_expression_attribute = BoolProperty(name="Is Material Expression Attribute")
    Object.efx_material_expression_entries = CollectionProperty(type=EFXMaterialExpressionItem)
    Object.efx_material_expression_indices = StringProperty(
        name="Material Expression Indices",
        description="MaterialExpressionList.indices 原样透传，无编辑 UI",
        default="[]",
    )


def unregister():
    _INLINE_ENUM_CONTEXT.clear()
    _INLINE_ENUM_ITEMS_CACHE.clear()
    del Object.efx_material_expression_indices
    del Object.efx_material_expression_entries
    del Object.efx_is_material_expression_attribute
    del Object.efx_expression_curves_active_index
    del Object.efx_expression_curves
    del Object.efx_expression_bit_count
    del Object.efx_is_expression_attribute
    del Object.efx_clip_next_channel_id
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
    del Collection.efx_expression_parameters_active_index
    del Collection.efx_expression_parameters
    del Collection.efx_uvar_groups_active_index
    del Collection.efx_uvar_groups
    del Collection.efx_field_parameters_active_index
    del Collection.efx_field_parameters
    del Collection.efx_bones_active_index
    del Collection.efx_bones
    del Collection.efx_bone_alignment_bypassed
    del Collection.efx_source_dir
    del Object.efx_source_filename
    del Collection.efx_source_filename
    del Object.efx_entry_assignment
    del Object.efx_groups_active_index
    del Object.efx_groups
    del Object.efx_index
    del Object.efx_name
    del Object.efx_mdf_mismatched
    del Object.efx_mdf_reference
    del Object.efx_nested_root
    del Collection.efx_opaque_text
    del Object.efx_opaque_text

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
