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
    PointerProperty,
    StringProperty,
)
from bpy.types import Collection, Object, PropertyGroup

from . import i18n

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

# 新建空白 EFX 时 Header 需要的两个字段。只有这两个——2026-09-10 拿语料里最小的真实空文件
# （11_evc0023_50_039.efx.5571972，56 字节，Entries/Actions/... 全空）跟纯手写的裸 JSON 逐字节
# 比对过：Version 之外，`dimensionType` 不会被 C# 侧 `UpdateHeaderData()` 重算（entryCount 等
# 计数字段会），C# 默认值是 0，但 MHWs 语料恒为 1，漏填不会报错、会静默产出语义错误的文件
# （vendor 注释：`1 = 3D, 0 = 2D`）。别的 Header 字段全部由 DoWrite() 按内容重算，不需要在这里
# 补。见 vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EfxFile.cs `EfxHeader.dimensionType` 声明处的
# 原始注释。
MHWILDS_EFX_VERSION = 5571972  # = vendor EfxVersion.MHWilds
MHWILDS_EFX_DIMENSION_TYPE = 1


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
    current = _read_packed_int(self)
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
        # 下拉里带上原始数值（"1 跟随玩家移动"）——转成下拉之后裸数字不再直接可见了，
        # 但导出的还是这个数字，社区文档/010 模板对照的也是这个数字，不能让它彻底消失。
        built.append((str(value), f"{value} {label}", "", value))
        seen.add(value)
    if current not in seen:
        # 当前值不在列举范围内（语料里没见过的组合）：临时插一条"原值"，绝不静默改掉它
        # ——和 bitfield.py 弹窗里同样的兜底。
        built.append((str(current), f"{current}（原值）", "语料里没见过这个取值，原样保留", current))
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

    float_value: FloatProperty(name="Value")
    int_value: IntProperty(name="Value")
    uint_str: StringProperty(name="Value")
    bool_value: BoolProperty(name="Value")
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
        get=_read_packed_int, set=_write_packed_int,
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
    是两边统一的方向）。供 panels.py 画成两列并排，不画成"2 items"折叠框。

    `SequenceNo`/`PatternNo` 走 `is_sr_index_node()`/`is_sr_min_max_node()`，不算在这里——
    见那两个函数的说明。"""
    if node.data_type != "OBJECT" or len(node.children) != 2:
        return False
    if node.key in _SR_INDEX_FIELD_NAMES or node.key in _SR_MIN_MAX_FIELD_NAMES:
        return False
    return {c.key for c in node.children} == {"s", "r"}


# 2026-09-10 用户实机测试 + EfxBridge relstats 全语料复核（详细证据见
# mhws_field_labels.json 里这两个字段各自的 evidence）：`SequenceNo`/`PatternNo` 序列化形状
# 跟 `via.Range{s,r}` 一样，但都不是 static/random 语义。
# - `SequenceNo`：全语料 66146 例 s 恒等于 r+1（或 r+4，4 例），随机实际只在 [0,r] 里选，
#   s 疑似只是配套的计数字段——画成 Index(r)/UnknIndex(s)，不是 Static/Random。
# - `PatternNo`：全语料 s>r 恒成立但差值自由变化（不像 SequenceNo 钉死在 1），是真正的
#   min/max 范围，只是 s/r 顺序和 `is_min_max_node()` 的 x/y 相反——画成 Max(s)/Min(r)。
# `PlaySpeed` 反过来 s<=r 恒成立、顺序跟 x/y 一致，画成 Min(s)/Max(r)。
_SR_INDEX_FIELD_NAMES = frozenset({"SequenceNo"})
_SR_MIN_MAX_FIELD_NAMES = frozenset({"PatternNo", "PlaySpeed"})


def is_sr_index_node(node: EFXValueNode) -> bool:
    """`SequenceNo` 专用：形状和 `is_static_random_node()` 一样是 `{s,r}`，但 s/r 不是
    静态/随机，是"配套计数(s)/实际生效的随机上限索引(r)"。供 panels.py 画成
    UnknIndex(s)/Index(r) 两列。"""
    if node.data_type != "OBJECT" or len(node.children) != 2:
        return False
    if node.key not in _SR_INDEX_FIELD_NAMES:
        return False
    return {c.key for c in node.children} == {"s", "r"}


def is_sr_min_max_node(node: EFXValueNode) -> bool:
    """`PatternNo`/`PlaySpeed` 专用：形状和 `is_static_random_node()` 一样是 `{s,r}`，但实测
    是 min/max 范围而不是静态/随机。`PatternNo` 是 s=Max/r=Min（顺序和 `is_min_max_node()`
    的 x/y 相反），`PlaySpeed` 是 s=Min/r=Max（顺序本来就对）——具体顺序在 panels.py 按字段名
    分别处理，这个函数只负责结构判定。"""
    if node.data_type != "OBJECT" or len(node.children) != 2:
        return False
    if node.key not in _SR_MIN_MAX_FIELD_NAMES:
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
    bits 键），不会和这两个键撞名，本轮不处理，继续走通用树透传。
    """
    return "Expression" in attr_dict and "ExpressionBits" in attr_dict


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


class EFXExpressionCurveItem(PropertyGroup):
    """对应 `IExpressionAttribute` 的一条公式（`ExpressionBits` 里的一个置位 + 它驱动的一个
    `EFXExpressionObject`）。和 `EFXClipCurveItem` 是同一个 BitSet 家族——`bit_index` 的
    0-based 语义、"子曲线数组下标和排序后的置位 bit 下标一一对应"的约定完全相同（见
    `EFXClipCurveItem` 的说明），已用真实样本验证（`11_guide_006` 里 `bit_name == "color"`
    的那条公式是 `Lerp(IsBlue, colorR_N, color_N)`，语义吻合）。

    公式本身不存成后缀栈（`EFXExpressionObject.components`），存成 vendor 自带的文本表示
    （`formula`，如 `"min(1, clamp(TIMER, 30, 150))"`）——`EfxExpressionStringParser`/
    `EFXExpressionTree.ToString()` 已经是现成、经过测试的双向转换（`EfxExpressionParser.cs`），
    没有必要在 Python 这边再实现一遍递归下降解析器和优先级规则；后缀栈↔树↔文本的转换全部交给
    EfxBridge（dump 时调用 `EfxFile.ParseExpressions()`，load 时调用
    `EfxFile.FlattenExpressionTrees()`，见 tools/EfxBridge/Program.cs）。`formula_error` 是
    纯 UI 态（"Validate" 按钮的校验结果），不参与导出。
    """

    bit_index: IntProperty(name="Bit Index", min=0)
    bit_name: StringProperty(name="Bit Name")
    formula: StringProperty(name="Formula", default="0")
    formula_error: StringProperty(name="Error")


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
    EFXExpressionParamItem, EFXClipKeyframeItem, EFXClipCurveItem, EFXExpressionCurveItem,
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
    Object.efx_expression_curves_active_index = IntProperty()


def unregister():
    _INLINE_ENUM_CONTEXT.clear()
    _INLINE_ENUM_ITEMS_CACHE.clear()
    del Object.efx_expression_curves_active_index
    del Object.efx_expression_curves
    del Object.efx_expression_bit_count
    del Object.efx_is_expression_attribute
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
