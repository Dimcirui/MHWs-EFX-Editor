"""
blender_efx_re/io_tree.py —— ~TYPE 对象树 ↔ EfxFile JSON dict 互转

对齐姊妹项目 EFX-Editor 的 io_tree.py 角色：Entry/Attribute 是独立 Blender Object，Attribute 靠
parent 关系挂在 Entry/Action 下（不是 PropertyGroup 集合）。

**EFX_ROOT 是 Collection 本身，不是 Empty 对象**（结构上对齐姊妹项目的
`root_col["~TYPE"]="EFX_ROOT"`，但取值改成了 `model.TYPE_ROOT`="EFX_RE_ROOT"——两个插件的
`"~TYPE"` key 相同，取值如果也相同，同装两个插件时选中对方建的对象会被误判成自己的，
见 model.py 里 TYPE_ROOT 的说明）：
文件级数据挂在集合上，Entry/Action 的归属靠"在哪个 `*_Entries` / `*_Actions` 子集合里"表达，
它们没有父对象。Collection 没有 parent 属性、挂不到 Object 下面，所以 PlayEmitter 内嵌的那个
完整 EfxFile 反过来由 attribute 上的 `efx_nested_root` 指针指向，见 model.py 的说明。命名跟随
RE-Engine-Lib（`EfxFile.Entries: List<EFXEntry>`）叫 Entry，不叫 EFX-Editor（MHWI）习惯用的
Body——同一层概念，两个项目各自的命名习惯不同。与 EFX-Editor 不同的两点，见 PLAN.md
"Blender 对象模型草案"：

1. Action 是与 Entry 同级的顶层类型（不是 Entry 的子级），承载 PlayEmitter/PlayEfx。
2. PlayEmitter 的 efxrData 是完整内嵌的 EfxFile 对象图（组合，不是引用）——识别方式是"这个
   attribute 的字典里有没有 efxrData 键"这个结构信号，不按 $type 类名单列举，命中时递归调用
   build_root_from_efxfile 本身，建一个嵌套的子 EFX_ROOT。

顶层字段（Header/Strings/Bones/BoneRelations/FieldParameterValues/ExpressionParameters/
UvarGroups）以及 Entry/Action 里没有单独建 UI 的字段（name/nameHash/index/Version/actionUnkn0
等），一律原样存进 model.save_opaque()/load_opaque() 管理的文本块——当前阶段只对
Groups（EffectGroups 标签）、entryAssignment 和 Attribute 内容字段建了编辑 UI，其余的
"不碰"就是最安全的处理（决策 9 的精神：没能力/没打算编辑的东西，原样透传好过自作主张改写）。

Attribute 对象名带 `[父对象名]` 前缀（如 `[Emitter] Life`）：同一个 Entry/Action 下常有多个
同类型 attribute（不同 Entry 也大量共享同一批常见 attribute 类型，比如几乎每个 Entry 都有
ParentOptions），如果只用 `short_attr_name()` 裸类型名当对象名，Blender 全局对象名唯一性会
把它们批量改成 `.001`/`.002`，Outliner 里分不清谁是谁。带上父对象名前缀后碰撞概率大幅降低
（虽然理论上同一父对象下两个"同类型+同名"attribute 仍可能撞，这种情况交给 Blender 的
`.001` 后备机制兜底，纯展示，不影响导出——导出靠 parent 链和 efx_index，不靠对象名）。
"""

from __future__ import annotations

import base64
import binascii

import bpy
from bpy.types import Collection, Object

from . import model

_EMPTY_DISPLAY_SIZE = 0.1


def _new_empty(name: str, collection: Collection) -> Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = _EMPTY_DISPLAY_SIZE
    collection.objects.link(obj)
    return obj


# 重导出：定义已搬到 model.py（`_sync_object_name()`/`entry_display_suffix()` 也要用它，
# 而 model.py 是 io_tree.py 的依赖方向上游，不能反过来 import io_tree），这里留一个别名，
# panels.py 里现成的 `io_tree.short_attr_name(...)` 调用不用跟着改。
short_attr_name = model.short_attr_name


# ---------------------------------------------------------------------------
# Import：EfxFile dict -> ~TYPE 对象树
# ---------------------------------------------------------------------------

_CLIP_HEADER_SIZE = 8  # EfxClipHeader: int frameCount + int(enum) valueType
_CLIP_FRAME_SIZE = 12  # EfxClipFrame: float frameTime + int(enum) type + float value
_CLIP_TANGENT_SIZE = 16  # EfxClipInterpolationTangents: 4 个 float
_CLIP_BEZIER_TYPE = 5  # FrameInterpolationType.Bezier


def _populate_clip_attribute(obj: Object, attr_dict: dict) -> None:
    """把一个 IClipAttribute 的 clipData/clipBits 展开成 obj.efx_clip_* 系列属性——不依赖
    vendor 算好的 ParsedClip 只读便利视图，直接照抄 EfxClipData.ParseClip() 的分组逻辑：
    按 clips[] 每一项的 frameCount 依次切 frames[]，type==Bezier 的帧再顺带从
    interpolationData[] 里取一个——两个并行数组都是"遇到顺序"消费，不按下标对齐，见
    docs/TOPLEVEL_STRUCTURE.md "Clip 结构调研"。子曲线数组下标和排序后的置位 bit 下标一一
    对应（vendor BitSet.GetBitInsertIndex() 就是算这个映射用的），所以按 sorted(bits) 和
    clips[] 一起 zip 消费。"""
    clip_data = attr_dict.get("clipData") or {}
    clip_bits = attr_dict.get("clipBits") or {}

    obj.efx_is_clip_attribute = True
    obj.efx_clip_bit_count = int(clip_bits.get("bitCount", 0) or 0)
    obj.efx_clip_loop_type = str(int(clip_data.get("loopType", 0) or 0))

    bit_names = clip_bits.get("bitNames") or []
    sorted_bits = sorted(clip_bits.get("bits") or [])

    frames = clip_data.get("frames") or []
    tangents = clip_data.get("interpolationData") or []
    frame_i = 0
    tangent_i = 0

    for bit_index, header in zip(sorted_bits, clip_data.get("clips") or []):
        curve = obj.efx_clip_curves.add()
        curve.bit_index = bit_index
        curve.bit_name = (bit_names[bit_index] if bit_index < len(bit_names) else None) or ""
        value_type = int(header.get("valueType", 5) or 5)
        curve.value_type = str(value_type)

        for _ in range(int(header.get("frameCount", 0) or 0)):
            frame = frames[frame_i]
            frame_i += 1
            kf = curve.keyframes.add()
            kf.frame_time = model.json_float_in(frame.get("frameTime", 0.0))
            interp_type = int(frame.get("type", 2) or 2)
            kf.interp_type = str(interp_type)
            if value_type == 3:  # Int：IntValue 的 getter 没问题，直接读
                kf.value = float(int(frame.get("IntValue", 0) or 0))
            else:
                kf.value = model.json_float_in(frame.get("FloatValue", 0.0))
            if interp_type == _CLIP_BEZIER_TYPE:
                tangent = tangents[tangent_i]
                tangent_i += 1
                kf.tangent_out_x = model.json_float_in(tangent.get("out_x", 0.0))
                kf.tangent_out_y = model.json_float_in(tangent.get("out_y", 0.0))
                kf.tangent_in_x = model.json_float_in(tangent.get("in_x", 0.0))
                kf.tangent_in_y = model.json_float_in(tangent.get("in_y", 0.0))


def _populate_expression_attribute(obj: Object, attr_dict: dict) -> None:
    """把一个 IExpressionAttribute 的 Expression/ExpressionBits 展开成 obj.efx_expression_*
    系列属性——同 _populate_clip_attribute()，子曲线（这里是"子公式"）数组下标和排序后的置位
    bit 下标一一对应，按 sorted(bits) 和 parsedExpressions[] 一起 zip 消费。公式内容直接读
    EfxBridge（`efx.ParseExpressions()`，见 tools/EfxBridge/Program.cs）算好的
    `parsedExpressions[].expression` 文本，不在这里重新解析后缀栈 `components`——见
    EFXExpressionCurveItem 的说明。"""
    expression = attr_dict.get("Expression") or {}
    expression_bits = attr_dict.get("ExpressionBits") or {}

    obj.efx_is_expression_attribute = True
    obj.efx_expression_bit_count = int(expression_bits.get("bitCount", 0) or 0)

    bit_names = expression_bits.get("bitNames") or []
    sorted_bits = sorted(expression_bits.get("bits") or [])
    parsed = expression.get("parsedExpressions") or []

    for bit_index, entry in zip(sorted_bits, parsed):
        curve = obj.efx_expression_curves.add()
        curve.bit_index = bit_index
        curve.bit_name = (bit_names[bit_index] if bit_index < len(bit_names) else None) or ""
        curve.formula = entry.get("expression", "0") or "0"


def apply_attribute_content(obj: Object, attr_dict: dict) -> None:
    """把 attr_dict 的"内容"字段（Fields 通用树 + Clip/Expression 曲线）套到 obj 上。

    只碰内容，不碰身份（$type/UniqueID/Version/type/IsTypeAttribute/efx_index/parent）和嵌套
    efxrData 子树——后者是独立的子对象图（PlayEmitter 内嵌完整 EfxFile），不算"属性"，调用方
    若要建全新对象请在这个函数之外自己处理（见 build_attribute_object()）。

    只 `add()`，不 `clear()`：对一个已经有内容的现有对象重复调用（如
    `EFX_RE_OT_properties_paste`）之前，调用方必须自己先清空
    `obj.efx_fields`/`efx_clip_curves`/`efx_expression_curves`。
    """
    content = {
        key: value for key, value in attr_dict.items()
        if key not in model.ATTRIBUTE_BOOKKEEPING_KEYS
        and key not in model.ATTRIBUTE_NESTED_ROOT_KEYS
        and key not in model.ATTRIBUTE_CLIP_VIEW_KEYS
    }
    if content.get("ParentBone") is None and "ParentBone" in content:
        # C# 侧 ParentBone 是 string?，无绑定时可能是 null，也可能压根不存在（老结构体没有
        # 这个属性）——只在真的存在这个键时才规整。规整成 "" 而不是保留 null：C# 写出逻辑用
        # string.IsNullOrEmpty(ParentBone) 判断"无父骨骼"，null 和 "" 语义完全等价
        # （EfxFile.cs:984），但 EFXValueNode 的 NULL data_type 没有可编辑的 slot，画不出
        # prop_search 控件，所以统一存成空字符串，导出行为不变。见
        # model.is_bone_reference_field()/panels.py 的骨骼搜索控件。
        content["ParentBone"] = ""
    if model.is_clip_attribute_dict(attr_dict):
        # clipData/clipBits 走专属的 efx_clip_* 结构（见 _populate_clip_attribute()），不进
        # 通用树——IMaterialClipAttribute 实现类（is_clip_attribute_dict() 为 False）不受
        # 影响，仍然原样进通用树，本轮不处理它们额外的 mdfProperties 关联。
        content.pop("clipData", None)
        content.pop("clipBits", None)
        _populate_clip_attribute(obj, attr_dict)
    if model.is_expression_attribute_dict(attr_dict):
        # Expression/ExpressionBits 走专属的 efx_expression_* 结构（见
        # _populate_expression_attribute()），不进通用树——IMaterialExpressionAttribute
        # 暴露的是不同的键名 MaterialExpressions，不受影响，仍然原样进通用树。
        #
        # 和 Clip 同一个模式：小写的 expressions/expressionBits 才是真字段，大写的
        # Expression/ExpressionBits 是类上的属性别名（`Expression` 带 setter，
        # `ExpressionBits` 是 `=> expressionBits` 的只读属性）。两者在 JSON 里内容完全相同
        # （已用真实样本核对：attr["Expression"] == attr["expressions"]、
        # attr["ExpressionBits"] == attr["expressionBits"]），只是 System.Text.Json 把公开
        # 字段和公开属性都当成独立成员各序列化一份。四个键都要从通用树里剔除，否则 Fields
        # 列表里会重复显示一遍一模一样的内容；导出时只写小写的那两个，见
        # export_attribute_object()。
        content.pop("Expression", None)
        content.pop("ExpressionBits", None)
        content.pop("expressions", None)
        content.pop("expressionBits", None)
        _populate_expression_attribute(obj, attr_dict)
    model.populate_dict_as_children(obj.efx_fields, content)
    collapse_mdf_properties(obj)


def collapse_mdf_properties(obj: Object) -> None:
    """把材质参数覆盖表（`properties`）的每一条折起来。

    `EFXValueNode.ui_expand` 全局默认展开（通用树的其它地方都靠展开才看得见内容），但这张表
    每条只有一个值得看的值，面板已经把它压成一行了（见 panels._draw_mdf_property）——一进来
    十几条全摊开只会把整个 attribute 挤出屏幕。不改全局默认，只在这一处收起来。
    """
    for node in obj.efx_fields:
        if node.key == "properties" and node.data_type == "ARRAY":
            for child in node.children:
                child.ui_expand = False


def build_attribute_object(attr_dict: dict, index: int, parent_obj: Object, collection: Collection) -> Object:
    attr_type = attr_dict.get("$type", "")
    obj = _new_empty(f"[{parent_obj.name}] {short_attr_name(attr_type)}", collection)
    obj.parent = parent_obj
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    obj.efx_index = index
    obj.efx_attr_type = attr_type
    obj.efx_unique_id = attr_dict.get("UniqueID", 0)
    obj.efx_version = attr_dict.get("Version", 0)
    obj.efx_type_id = attr_dict.get("type", 0)
    obj.efx_is_type_attribute = bool(attr_dict.get("IsTypeAttribute", False))

    apply_attribute_content(obj, attr_dict)

    leftover = {key: attr_dict[key] for key in ("efxrSize",) if key in attr_dict}
    if leftover:
        model.save_opaque(obj, leftover)

    if "efxrData" in attr_dict:
        build_root_from_efxfile(attr_dict["efxrData"], collection, f"{obj.name}_efxrData", parent_obj=obj)

    return obj


def apply_entry_content(obj: Object, entry_dict: dict) -> None:
    """把 entry_dict 的"内容"字段（Groups/entryAssignment/未建 UI 的 opaque 字段）套到 obj 上。

    只碰内容，不碰身份（name/efx_index/子 Attribute 对象）——`entry_dict` 就算是从
    `export_entry_object()` 原样拿来的完整字典也没关系，`name`/`Attributes` 键会被
    ENTRY_STRUCTURAL_KEYS 过滤掉，这个函数根本不会碰它们。

    会先 `obj.efx_groups.clear()` 再重建——对全新对象是空操作，对已有内容的现有对象（如
    `EFX_RE_OT_properties_paste`）则是必须的，否则标签会不断累积重复项。
    """
    obj.efx_groups.clear()
    for group_name in entry_dict.get("Groups", []) or []:
        tag = obj.efx_groups.add()
        tag.name = group_name
    obj.efx_entry_assignment = str(int(entry_dict.get("entryAssignment", 0) or 0))

    leftover = {k: v for k, v in entry_dict.items() if k not in model.ENTRY_STRUCTURAL_KEYS}
    model.save_opaque(obj, leftover)


def build_entry_object(entry_dict: dict, index: int, collection: Collection) -> Object:
    """Entry 不再 parent 到任何对象——EFX_ROOT 是集合，归属靠"在哪个 *_Entries 集合里"表达。"""
    # 这里给的只是个临时占位名（在 obj.efx_index/efx_name 都赋值完之前，Blender 对象总得先有
    # 个名字）——函数末尾会调 model.refresh_entry_display_name() 按序号+名字重算一次真正的
    # 显示名，两种情况（有名字/没名字）都覆盖，这里不用费心拼对格式。
    obj = _new_empty(entry_dict.get("name") or f"Entry_{index}", collection)
    obj["~TYPE"] = model.TYPE_ENTRY
    obj.efx_index = index

    apply_entry_content(obj, entry_dict)

    for attr_index, attr_dict in enumerate(entry_dict.get("Attributes", []) or []):
        build_attribute_object(attr_dict, attr_index, obj, collection)

    # efx_name 故意放在 attribute 建完之后才赋值：它的 update 回调 model._sync_object_name()
    # 会顺带算上 entry_display_suffix()（TypeAttribute/PtLife/PtColliderAction 那个后缀，
    # " (Mesh, PtLife)" 这种），而那个回调是现场扫 `~TYPE == EFX_ATTRIBUTE` 子对象算的——提前
    # 赋值的话子对象还没建出来，算出来的后缀永远是空的（实测踩过：display_name 里手动拼好的
    # 后缀，会被这行赋值触发的回调用"当时还没有子对象"算出的空后缀覆盖掉）。
    obj.efx_name = entry_dict.get("name") or ""
    # `efx_name` 的 update 回调只在非空时才会重算显示名（见 model._sync_object_name()）——
    # 没名字的 entry 需要这里补一刀，把占位名换成带 `[{efx_index:03d}] ` 前缀的正式格式。
    model.refresh_entry_display_name(obj)

    return obj


def build_action_object(action_dict: dict, index: int, collection: Collection) -> Object:
    """同 build_entry_object()：归属靠所在的 *_Actions 集合，不靠 parent。"""
    display_name = action_dict.get("name") or f"Action_{index}"
    obj = _new_empty(display_name, collection)
    obj["~TYPE"] = model.TYPE_ACTION
    obj.efx_index = index
    obj.efx_name = action_dict.get("name") or ""

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
) -> Collection:
    """把一个 EfxFile JSON dict 建成一棵 ~TYPE 对象树，返回 **EFX_ROOT 集合**。

    EFX_ROOT 就是这个紫色集合本身，没有根 Empty——结构上对齐姊妹项目 EFX-Editor 的做法
    （`root_col["~TYPE"] = "EFX_ROOT"`，见其 root_collection.py），但 `"~TYPE"` 的取值用的是
    `model.TYPE_ROOT`（"EFX_RE_ROOT"），不是裸的 "EFX_ROOT"——避免同装两个插件时把姊妹项目
    建的 Collection 误判成自己的（见 model.py 里 TYPE_ROOT 的说明）。文件级数据
    （Bones / FieldParameterValues / UvarGroups / ExpressionParameters / 剩余 opaque）
    全部挂在集合上，见 model.py 的属性注册。

    parent_collection：新建的这一层 Collection 挂在哪个 Collection 下面（顶层文件传
    context.scene.collection；PlayEmitter 递归时传外层 attribute 所在的 collection）。
    parent_obj：仅递归场景使用。Collection 没有 parent 属性、挂不到 Object 下面，所以反过来
    在那个 PlayEmitter attribute 上记一个 `efx_nested_root` 指针指向这里，导出时靠它找回来。
    """
    own_collection = bpy.data.collections.new(name)
    parent_collection.children.link(own_collection)
    # 紫色（COLOR_06）：对齐姊妹项目 EFX-Editor 的约定（见其 CLAUDE.md §4，mrl3 用 COLOR_05 蓝、
    # EFX 用紫区分）。Outliner 里一眼能认出哪些集合是 EFX 文件——尤其是同时导入好几个、或者
    # 场景里还有别的资产的时候。子集合（Entries/Actions）不染色，留给顶层集合当唯一标识。
    own_collection.color_tag = "COLOR_06"
    entries_collection = bpy.data.collections.new(f"{name}_Entries")
    own_collection.children.link(entries_collection)
    actions_collection = bpy.data.collections.new(f"{name}_Actions")
    own_collection.children.link(actions_collection)

    own_collection["~TYPE"] = model.TYPE_ROOT
    root_obj = own_collection  # 下面这一大段原样沿用，只是承载体从 Empty 换成了集合
    if parent_obj is not None:
        parent_obj.efx_nested_root = own_collection

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
        item.param_type = expr_dict.get("type") or "Float"
        value = expr_dict.get("value")
        if item.param_type == "Float":
            item.value1 = model.json_float_in(value if value is not None else 0.0)
        elif item.param_type == "Float2":
            value = value or {}
            item.value1 = model.json_float_in(value.get("X", 0.0))
            item.value2 = model.json_float_in(value.get("Y", 0.0))
        elif item.param_type == "Range":
            value = value or {}
            item.value1 = model.json_float_in(value.get("X", 0.0))
            item.value2 = model.json_float_in(value.get("Y", 0.0))
            item.value3 = model.json_float_in(value.get("Z", 0.0))
        elif item.param_type == "Color":
            value = value or {}
            item.rgba_str = str(int(value.get("rgba", 0) or 0))

    for index, entry_dict in enumerate(efxfile_dict.get("Entries", []) or []):
        build_entry_object(entry_dict, index, entries_collection)

    for index, action_dict in enumerate(efxfile_dict.get("Actions", []) or []):
        build_action_object(action_dict, index, actions_collection)

    return own_collection


# ---------------------------------------------------------------------------
# Export：~TYPE 对象树 -> EfxFile dict
# ---------------------------------------------------------------------------

def next_sibling_index(siblings) -> int:
    """"新对象该排第几"的统一算法：当前同类型兄弟对象里 efx_index 最大值 + 1（没有兄弟就是
    0）——不影响原有对象的顺序，新对象永远排在最后。copy_paste.py 的 Paste Object、
    entry_presets.py 的"从预设新建 Entry"共用这条逻辑。"""
    return max((o.efx_index for o in siblings), default=-1) + 1


def typed_children(obj: Object, type_tag: str) -> list[Object]:
    """obj 的直接子对象里 ~TYPE 等于 type_tag 的那些，按 efx_index 排序（见 model.py 里的说明，
    不依赖 Blender children/collection 的迭代顺序）。公开给 copy_paste.py 复用（找兄弟对象、
    算新粘贴对象该排的 efx_index）。

    **只接受 Object**（找一个 Entry/Action 下的 Attribute）。传集合进来会当场报错，不静默返回
    空列表——Collection 也有 `.children`（那是子集合），拿它当参数会一条不匹配、安静地返回 []，
    调用方看到的是"这个 efx 没有 entry"而不是"你用错函数了"。EFX_ROOT 现在是集合，找它下面的
    Entry/Action 请用 root_entries() / root_actions()。
    """
    if isinstance(obj, Collection):
        raise TypeError(
            "typed_children() 只接受 Object。EFX_ROOT 是集合，"
            "找它下面的 Entry/Action 请用 root_entries() / root_actions()。"
        )
    matched = [child for child in obj.children if child.get("~TYPE") == type_tag]
    matched.sort(key=lambda o: o.efx_index)
    return matched


def collection_parent(col: Collection) -> Collection | None:
    """一个 Collection 的父集合。Blender 的 Collection 没有 `parent` 属性，只能反向找——
    扫一遍谁的 children 里有它。集合数量是场景级的（几十上百），这个代价可以忽略。"""
    for candidate in bpy.data.collections:
        if col.name in candidate.children:
            return candidate
    for scene in bpy.data.scenes:
        if col.name in scene.collection.children:
            return scene.collection
    return None


def find_root(obj: Object | None) -> Collection | None:
    """从任意一个 ~TYPE 对象找到它所属的 EFX_ROOT **集合**，找不到返回 None。

    EFX_ROOT 是集合不是对象，所以走法是两段：先沿 parent 链爬到最外层的对象（Attribute →
    Entry/Action），再从它所在的集合沿父集合链往上找带 `~TYPE == EFX_ROOT` 标记的那个。

    嵌套的 efxrData 子树也能正确解析：它的集合就 link 在外层 attribute 所在的集合下面，
    沿父集合链往上第一个撞到的 EFX_ROOT 就是这个嵌套根本身（不是外层文件），符合预期——
    "这个对象属于哪个 efx 文件"要的就是最近的那一层。
    """
    while obj is not None and obj.parent is not None:
        obj = obj.parent
    if obj is None:
        return None
    for col in obj.users_collection:
        found = _root_of_collection(col)
        if found is not None:
            return found
    return None


def _root_of_collection(col: Collection | None) -> Collection | None:
    """从一个集合沿父集合链往上找第一个 EFX_ROOT（含它自己）。"""
    seen = set()
    while col is not None and col.name not in seen:
        seen.add(col.name)
        if col.get("~TYPE") == model.TYPE_ROOT:
            return col
        col = collection_parent(col)
    return None


def resolve_root(context) -> Collection | None:
    """当前操作该落在哪个 EFX_ROOT 集合上：先看活动对象所在的树，再看活动集合，
    最后退到场景级的"当前 EFX"选择器（`Scene.efx_re_active_root`，见 panels.py register()）。

    对齐姊妹项目 EFX-Editor 主面板顶部的 Active EFX 选择器：那边所有"往某个 efx 里加东西"
    的算子都以它为目标，用户不必先在 Outliner 里点中树里的某个对象。这里保留"活动对象优先"
    是因为本项目的导出/粘贴一直是这么用的，同时开着两棵树时按选中的那棵走更符合直觉。

    中间多了一档"活动集合"：EFX_ROOT 现在就是集合，用户在 Outliner 里点中那个紫色集合是
    最自然的"我要操作这个文件"的表达，不该还要求他再点一个里面的对象。

    选择器指向的集合可能已经被删掉或者被改成别的东西了（PointerProperty 只保证指向仍存在的
    数据块，不保证它还带 EFX_ROOT 标记），所以这里再验一次 ~TYPE。"""
    root = find_root(getattr(context, "object", None))
    if root is not None:
        return root
    active_col = getattr(context, "collection", None)
    root = _root_of_collection(active_col)
    if root is not None:
        return root
    active = getattr(context.scene, "efx_re_active_root", None)
    if active is not None and active.get("~TYPE") == model.TYPE_ROOT:
        return active
    return None


def root_collections(root_col: Collection) -> tuple[Collection, Collection]:
    """返回一个 EFX_ROOT 集合的 (entries_collection, actions_collection)。按
    build_root_from_efxfile() 里固定的链接顺序取（先 link entries_collection 再 link
    actions_collection），不靠名字匹配——集合撞名时 Blender 会加 `.001` 后缀，按
    `f"{name}_Entries"` 去查会落空。"""
    return root_col.children[0], root_col.children[1]


def root_entries(root_col: Collection) -> list[Object]:
    """一个 EFX_ROOT 集合下的全部 Entry 对象，按 efx_index 排序。

    Entry 没有父对象（EFX_ROOT 是集合），归属靠"在哪个 *_Entries 子集合里"表达，
    所以这里按集合成员筛，不是按 children 筛。"""
    entries_collection, _ = root_collections(root_col)
    matched = [o for o in entries_collection.objects if o.get("~TYPE") == model.TYPE_ENTRY]
    matched.sort(key=lambda o: o.efx_index)
    return matched


def root_actions(root_col: Collection) -> list[Object]:
    """同 root_entries()，取 *_Actions 集合里的 Action 对象。"""
    _, actions_collection = root_collections(root_col)
    matched = [o for o in actions_collection.objects if o.get("~TYPE") == model.TYPE_ACTION]
    matched.sort(key=lambda o: o.efx_index)
    return matched


def _export_clip_attribute(obj: Object) -> tuple[dict, dict]:
    """_populate_clip_attribute() 的反函数——按 bit_index 升序重建扁平并行数组，复刻
    EfxClipData.SetFromClipList()/AssignFromList() 的重算逻辑。三个 *Size 字节长度字段
    vendor 写出时不会重算（不像 clipCount/frameCount/interpolationDataCount 那样能从数组
    长度自愈），必须自己算对，见 docs/TOPLEVEL_STRUCTURE.md "Clip 结构调研"。"""
    curves = sorted(obj.efx_clip_curves, key=lambda c: c.bit_index)

    clip_headers = []
    frames = []
    tangents = []
    max_frame_time = 0.0
    for curve in curves:
        value_type = int(curve.value_type)
        clip_headers.append({"frameCount": len(curve.keyframes), "valueType": value_type})
        for kf in curve.keyframes:
            interp_type = int(kf.interp_type)
            if value_type == 3:  # Int：IntValue 的 setter 是死代码，只能靠 FloatValue 位转换
                float_value = model.int_bits_to_float(int(round(kf.value)))
            else:
                float_value = model.json_float_out(kf.value)
            frames.append({
                "IntValue": 0,
                "FloatValue": float_value,
                "frameTime": model.json_float_out(kf.frame_time),
                "type": interp_type,
            })
            if interp_type == _CLIP_BEZIER_TYPE:
                tangents.append({
                    "out_x": kf.tangent_out_x, "out_y": kf.tangent_out_y,
                    "in_x": kf.tangent_in_x, "in_y": kf.tangent_in_y,
                })
            if kf.frame_time > max_frame_time:
                max_frame_time = kf.frame_time

    clip_data = {
        "loopType": int(obj.efx_clip_loop_type),
        "clipDuration": max_frame_time,
        "clipCount": len(clip_headers),
        "frameCount": len(frames),
        "interpolationDataCount": len(tangents),
        "clipDataSize": len(clip_headers) * _CLIP_HEADER_SIZE,
        "frameDataSize": len(frames) * _CLIP_FRAME_SIZE,
        "interpolationDataSize": len(tangents) * _CLIP_TANGENT_SIZE,
        "clips": clip_headers,
        "frames": frames,
        "interpolationData": tangents,
    }
    clip_bits = {"bitCount": obj.efx_clip_bit_count, "bits": [c.bit_index for c in curves]}
    return clip_data, clip_bits


def _export_expression_attribute(obj: Object) -> tuple[dict, dict]:
    """_populate_expression_attribute() 的反函数。只写 parsedExpressions（文本公式），把
    expressions（真正参与二进制写出的后缀栈）留空——EfxBridge 的 load 会在反序列化后调用
    CompileExpressions()（tools/EfxBridge/Program.cs，逐个把公式文本摊平回 expressions，
    同时规避三个 vendor bug，见 docs/TOPLEVEL_STRUCTURE.md）。parameters 留空数组：具名/
    `p:`/`ext:` 前缀的标识符不需要预先提供，只有复用一个已存在 `const:` 参数的自定义
    constantValue 时才用得上，v1 不处理这个边缘情况。"""
    curves = sorted(obj.efx_expression_curves, key=lambda c: c.bit_index)
    expression_dict = {
        "version": obj.efx_version,
        "parsedExpressions": [{"expression": c.formula, "parameters": []} for c in curves],
        "expressions": [],
    }
    expression_bits = {"bitCount": obj.efx_expression_bit_count, "bits": [c.bit_index for c in curves]}
    return expression_dict, expression_bits


# `MdfProperty.GetSize()`（vendor EfxCommon.cs:81）：RE3 起每条 32 字节，更早的 28。
_MDF_PROPERTY_SIZE_RE3 = 32
_MDF_PROPERTY_SIZE_LEGACY = 28
_EFX_VERSION_RE3 = 2228526


def _refresh_derived_sizes(attr_dict: dict, version: int) -> None:
    """重算那几个"vendor 自己不管、但确实是从别的字段推出来的"字节长度字段。

    `RszByteSizeField` 标的字段一律不进代码生成器的重算分支（`ReeLibGenerator.cs:412` 那个
    `if` 里只有 `RszArraySizeField`），各个类要么在手写的 `DoWrite()` 里自己补、要么就没人补。
    没人补的这两个必须我们算，否则写出的字节和实际内容对不上：

    - `propertiesDataSize`（TypeMesh 系列）= `properties` 条数 × 每条字节数。实测过：加一条
      property 而不改这个值，写出的文件整个读不回来（解析在这里错位之后后面全乱）。
    - `unknDataSize`（TypeGpuMesh）= `unknData` 那个字节块的长度。语料 392/392 个实例都严格
      满足这个等式，所以它是长度前缀而不是独立数据；vendor 写出时按它决定写多少字节
      （`[RszFixedSizeArray(nameof(unknDataSize))]`），和实际块长不一致就会多写/少写字节。

    只在字典里**本来就有**对应字段时才动，不给没有这些字段的 attribute 凭空加一个。
    """
    properties = attr_dict.get("properties")
    if "propertiesDataSize" in attr_dict and isinstance(properties, list):
        size = _MDF_PROPERTY_SIZE_RE3 if version >= _EFX_VERSION_RE3 else _MDF_PROPERTY_SIZE_LEGACY
        attr_dict["propertiesDataSize"] = len(properties) * size

    if "unknDataSize" in attr_dict:
        blob = attr_dict.get("unknData")
        # System.Text.Json 把 `byte[]` 序列化成 base64 字符串（不是数字数组），空块是 null。
        if blob is None:
            attr_dict["unknDataSize"] = 0
        elif isinstance(blob, str):
            try:
                attr_dict["unknDataSize"] = len(base64.b64decode(blob))
            except (ValueError, binascii.Error):
                # 解不开就别动那个数——用户把 base64 改坏了是另一回事，这里瞎算一个 0
                # 反而会把原本还能救的块长也抹掉。
                pass


def export_attribute_object(obj: Object) -> dict:
    # $type 必须是字典的第一个键：C# 侧 EfxJsonTypeResolver 是流式读取多态判别字段来选定具体
    # EFXAttribute 子类的 JsonTypeInfo，不像 System.Text.Json 内置的 [JsonPolymorphic] 那样会
    # 缓冲整个对象再重放——$type 出现在其他字段之后会导致反序列化直接退回基类 EFXAttribute
    # （抽象/无无参构造函数），抛 NotSupportedException。已在 Blender 5.1 实测复现确认。
    attr_dict = {"$type": obj.efx_attr_type}
    attr_dict.update(model.children_to_dict(obj.efx_fields))
    _refresh_derived_sizes(attr_dict, obj.efx_version)
    attr_dict.update(model.load_opaque(obj))  # 目前只可能有 efxrSize
    attr_dict["UniqueID"] = obj.efx_unique_id
    attr_dict["Version"] = obj.efx_version
    attr_dict["type"] = obj.efx_type_id
    attr_dict["IsTypeAttribute"] = obj.efx_is_type_attribute

    if obj.efx_is_clip_attribute:
        clip_data, clip_bits = _export_clip_attribute(obj)
        attr_dict["clipData"] = clip_data
        attr_dict["clipBits"] = clip_bits

    if obj.efx_is_expression_attribute:
        expression_dict, expression_bits = _export_expression_attribute(obj)
        # 必须写小写的后备字段名，不能写 Expression/ExpressionBits：`ExpressionBits` 在每个
        # IExpressionAttribute 实现类上都是 `=> expressionBits` 这种无 setter 的只读属性，
        # System.Text.Json 反序列化时直接跳过（PreferredPropertyObjectCreationHandling
        # =Populate 只在 EfxJsonTypeResolver 里给 EFXAttribute 基类和 EfxFile/EFXEntry/
        # EFXAction 挂了，具体 attribute 子类的 JsonTypeInfo 走不到那个分支），置位信息会被
        # 静默丢掉、按 BitSet 默认值（全 0）写出。`Expression` 恰好带 setter
        # （`{ get => expressions; set => expressions = value; }`）所以能进去，但同一处用两套
        # 命名只会让下一个人再踩一次——两个都统一写小写，和 clipData/clipBits 那条路对齐。
        attr_dict["expressions"] = expression_dict
        attr_dict["expressionBits"] = expression_bits

    # 嵌套的 efxrData：Collection 挂不到 Object 下面，所以由 attribute 拿指针指向它，
    # 见 model.py `Object.efx_nested_root` 的说明。
    nested_root = obj.efx_nested_root
    if nested_root is not None and nested_root.get("~TYPE") == model.TYPE_ROOT:
        attr_dict["efxrData"] = export_root_to_efxfile(nested_root)

    return attr_dict


def _apply_name(target: dict, obj: Object) -> None:
    """把 efx_name 写回导出字典。

    `efx_name` 为空时**保留 opaque 里原有的 name 不动**：`name` 是这一版才从 opaque 挪进
    专属属性的，早先导入、存在 .blend 里的对象没有 efx_name，直接覆盖会把它们的名字清空。
    新导入的对象一定有值（build_* 里赋的），所以这条兼容分支只影响老场景。
    """
    if obj.efx_name:
        target["name"] = obj.efx_name


def export_entry_object(obj: Object) -> dict:
    entry_dict = model.load_opaque(obj)  # index 已随其余 opaque 字段原样透传，见 model.py 说明。
    _apply_name(entry_dict, obj)
    entry_dict["Groups"] = [tag.name for tag in obj.efx_groups]
    entry_dict["entryAssignment"] = int(obj.efx_entry_assignment)
    entry_dict["Attributes"] = [
        export_attribute_object(attr_obj) for attr_obj in typed_children(obj, model.TYPE_ATTRIBUTE)
    ]
    return entry_dict


def export_action_object(obj: Object) -> dict:
    action_dict = model.load_opaque(obj)
    _apply_name(action_dict, obj)
    action_dict["Attributes"] = [
        export_attribute_object(attr_obj) for attr_obj in typed_children(obj, model.TYPE_ATTRIBUTE)
    ]
    return action_dict


def export_root_to_efxfile(root_col: Collection, reorder_effect_groups: bool = False) -> dict:
    """`reorder_effect_groups`：`EffectGroups` 数组的顺序处理方式。

    默认 False——保留导入时的原始顺序（`model.load_opaque()` 已经把它当普通字段带出来了）。
    C# 后端 `DoWrite()` 里的 `UpdateEffectGroups()`（EfxFile.cs:1302）仍然会按当前
    Entry.Groups 标签更新每个已匹配组的 `efxEntryIndexes`、把新增的组追加到末尾、把不再被
    引用的组清空成员但保留原位置——这些都是"数组顺序不变、内容跟着当前状态更新"，安全。

    True——传空数组，让 `UpdateEffectGroups()` 从 Entry 下标扫描顺序整个重新生成数组本身
    （老行为）。**2026-09-09 游戏内实测证实这个顺序对游戏有意义**（武器动作表大概率按数组
    下标而不是按名字/哈希引用 EffectGroups 组），默认关掉；只有明确需要把 EffectGroups 组
    重新排列时才勾 `EFX_RE_OT_export.reorder_effect_groups`。见 model.ROOT_STRUCTURAL_KEYS
    的说明。
    """
    root_obj = root_col  # 下面沿用旧名字，承载体是集合
    efxfile_dict = model.load_opaque(root_obj)
    efxfile_dict["Entries"] = [export_entry_object(obj) for obj in root_entries(root_col)]
    efxfile_dict["Actions"] = [export_action_object(obj) for obj in root_actions(root_col)]
    if reorder_effect_groups:
        efxfile_dict["EffectGroups"] = []
    else:
        efxfile_dict.setdefault("EffectGroups", [])
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
    # 2 项的情况（EFX_RE_OT_uvar_group_add），这里不需要重复校验。
    efxfile_dict["UvarGroups"] = [
        {"uvarType": int(item.uvar_type), "path": item.path, "group": item.group}
        for item in root_obj.efx_uvar_groups
    ]
    # 新版本 JSON 形状只有 3 个键（type/name/value），两个具名哈希字段 vendor 自定义的
    # JsonConverter 读 name 时就地算好，写的时候压根不输出，不需要 Python 侧提供，见
    # EFXExpressionParamItem 的说明。
    efxfile_dict["ExpressionParameters"] = [
        _export_expression_param(item) for item in root_obj.efx_expression_parameters
    ]
    return efxfile_dict


def _export_expression_param(item) -> dict:
    if item.param_type == "Float":
        value = model.json_float_out(item.value1)
    elif item.param_type == "Float2":
        value = {"X": model.json_float_out(item.value1), "Y": model.json_float_out(item.value2)}
    elif item.param_type == "Range":
        value = {
            "X": model.json_float_out(item.value1),
            "Y": model.json_float_out(item.value2),
            "Z": model.json_float_out(item.value3),
        }
    else:  # "Color"
        value = {"rgba": int(item.rgba_str or "0")}
    return {"type": item.param_type, "name": item.name, "value": value}


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


def check_bone_references(root_col: Collection) -> None:
    """导出前校验：任何 attribute 的 ParentBone 字段只要非空，必须能在 root_col.efx_bones
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
    known_names = {item.name for item in root_col.efx_bones}
    missing = []
    for entry_obj in root_entries(root_col):
        missing.extend(_missing_bone_refs(entry_obj, known_names))
    for action_obj in root_actions(root_col):
        missing.extend(_missing_bone_refs(action_obj, known_names))
    if missing:
        raise BoneReferenceError(
            "以下 attribute 的 ParentBone 引用了不在 Bones 列表里的骨骼名字，"
            "导出会静默丢失绑定，请先在 Root 面板的 Bones 列表里添加对应名字：\n"
            + "\n".join(f"  {m}" for m in missing)
        )


class ClipBitError(Exception):
    """check_clip_bits() 校验失败时抛出：某个 Clip attribute 的曲线 bit_index 越界（超出
    efx_clip_bit_count）或重复（两条曲线用了同一个 bit）。不在这里静默截断/去重——越界会让
    C# 侧 `BitSet.SetBit()` 在 load 阶段直接抛数组越界异常（不是理论风险，`Bits[bitIndex >>
    5]` 直接访问底层 int 数组），重复会让两条曲线的数据在写出时对同一个 bit 位互相覆盖，两种
    情况都是"看起来正常但实际出错/丢数据"，按架构决策 9 直接拒绝导出，不做自动修复。"""


def _clip_bit_issues(attr_obj: Object) -> list:
    if not attr_obj.efx_is_clip_attribute:
        return []
    bit_count = attr_obj.efx_clip_bit_count
    issues = []
    seen = set()
    for curve in attr_obj.efx_clip_curves:
        if not (0 <= curve.bit_index < bit_count):
            issues.append(f"{attr_obj.name}: bit_index {curve.bit_index} 超出范围 [0, {bit_count})")
        elif curve.bit_index in seen:
            issues.append(f"{attr_obj.name}: bit_index {curve.bit_index} 被多条曲线重复使用")
        seen.add(curve.bit_index)
    return issues


def _walk_clip_issues(obj: Object) -> list:
    """递归遍历一个 ~TYPE 对象树下所有 EFX_ATTRIBUTE（含嵌套 PlayEmitter.efxrData 子树里的），
    收集 Clip bit 校验问题。和 check_bone_references() 不同，这里不需要排除嵌套子树——Clip
    的 bit_count/bits 校验是纯粹局部的（不依赖任何文件级共享表，不像 Bones 那样有已知的嵌套
    读写不对称问题），直接沿 Blender parent-child 关系整棵树走一遍即可。"""
    issues = []
    if obj.get("~TYPE") == model.TYPE_ATTRIBUTE:
        issues.extend(_clip_bit_issues(obj))
        # 嵌套的 efxrData 是一个集合，不在 children 里，走指针下去
        nested = obj.efx_nested_root
        if nested is not None and nested.get("~TYPE") == model.TYPE_ROOT:
            issues.extend(_walk_clip_issues_root(nested))
    for child in obj.children:
        if child.get("~TYPE") in (model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE):
            issues.extend(_walk_clip_issues(child))
    return issues


def _walk_clip_issues_root(root_col: Collection) -> list:
    issues = []
    for obj in root_entries(root_col) + root_actions(root_col):
        issues.extend(_walk_clip_issues(obj))
    return issues


def check_clip_bits(root_col: Collection) -> None:
    """导出前校验：见 ClipBitError 的说明。"""
    issues = _walk_clip_issues_root(root_col)
    if issues:
        raise ClipBitError(
            "以下 Clip attribute 的曲线 bit_index 有问题（越界或重复），会导致导出出错或"
            "静默丢数据，请先修正：\n" + "\n".join(f"  {m}" for m in issues)
        )


class ExpressionBitError(Exception):
    """check_expression_bits() 校验失败时抛出：某个 Expression attribute 的公式 bit_index
    越界或重复。和 ClipBitError 是同一个 BitSet 家族的同一类风险（越界让 C# 侧
    `BitSet.SetBit()` 数组越界，重复让两条公式在写出时互相覆盖），按架构决策 9 直接拒绝导出，
    不做自动修复。"""


def _expression_bit_issues(attr_obj: Object) -> list:
    if not attr_obj.efx_is_expression_attribute:
        return []
    bit_count = attr_obj.efx_expression_bit_count
    issues = []
    seen = set()
    for curve in attr_obj.efx_expression_curves:
        if not (0 <= curve.bit_index < bit_count):
            issues.append(f"{attr_obj.name}: bit_index {curve.bit_index} 超出范围 [0, {bit_count})")
        elif curve.bit_index in seen:
            issues.append(f"{attr_obj.name}: bit_index {curve.bit_index} 被多条公式重复使用")
        seen.add(curve.bit_index)
    return issues


def _walk_expression_issues(obj: Object) -> list:
    """递归遍历一个 ~TYPE 对象树下所有 EFX_ATTRIBUTE（含嵌套 PlayEmitter.efxrData 子树里的），
    收集 Expression bit 校验问题。和 _walk_clip_issues() 一样是纯局部校验，直接沿 Blender
    parent-child 关系整棵树走一遍即可。"""
    issues = []
    if obj.get("~TYPE") == model.TYPE_ATTRIBUTE:
        issues.extend(_expression_bit_issues(obj))
        nested = obj.efx_nested_root
        if nested is not None and nested.get("~TYPE") == model.TYPE_ROOT:
            issues.extend(_walk_expression_issues_root(nested))
    for child in obj.children:
        if child.get("~TYPE") in (model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE):
            issues.extend(_walk_expression_issues(child))
    return issues


def _walk_expression_issues_root(root_col: Collection) -> list:
    issues = []
    for obj in root_entries(root_col) + root_actions(root_col):
        issues.extend(_walk_expression_issues(obj))
    return issues


def check_expression_bits(root_col: Collection) -> None:
    """导出前校验：见 ExpressionBitError 的说明。"""
    issues = _walk_expression_issues_root(root_col)
    if issues:
        raise ExpressionBitError(
            "以下 Expression attribute 的公式 bit_index 有问题（越界或重复），会导致导出出错或"
            "静默丢数据，请先修正：\n" + "\n".join(f"  {m}" for m in issues)
        )


def collect_issues(root_col: Collection) -> list[str]:
    """把导出前那三项校验各跑一遍，收集**全部**问题，返回人类可读的一行一条；空列表 = 没问题。

    和上面三个 check_*() 的分工：那三个是导出路径上的关卡，发现问题直接抛异常拦下导出（架构
    决策 9，不静默降级）；这个是给面板 Validate 按钮用的，用户主动点一下想知道"现在这棵树能
    不能导出"，所以要一次把所有问题都列出来，不能第一条就中断。判据完全复用，不另写一套——
    两边结论不一致的话，Validate 说"没问题"、导出却失败，比没有 Validate 更糟。
    """
    known_names = {item.name for item in root_col.efx_bones}
    issues: list[str] = []
    for entry_obj in root_entries(root_col):
        issues.extend(f"ParentBone 不在骨骼表里 — {m}" for m in _missing_bone_refs(entry_obj, known_names))
    for action_obj in root_actions(root_col):
        issues.extend(f"ParentBone 不在骨骼表里 — {m}" for m in _missing_bone_refs(action_obj, known_names))
    issues.extend(f"Clip bit — {m}" for m in _walk_clip_issues_root(root_col))
    issues.extend(f"Expression bit — {m}" for m in _walk_expression_issues_root(root_col))
    return issues
