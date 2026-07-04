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
        # 和 Clip 反过来：Clip 是"Clip/ClipBits 只读别名，clipData/clipBits 才是真字段"，
        # Expression 是"Expression/ExpressionBits 是真字段（`EFXAttributeXxxExpression` 类的
        # 属性，Expression 甚至带 setter），expressions/expressionBits 才是小写的实际
        # 后备字段"——两者在 JSON 里内容完全相同（已用真实样本核对：
        # attr["Expression"] == attr["expressions"]、attr["ExpressionBits"] ==
        # attr["expressionBits"]），只是 System.Text.Json 把公开字段和公开属性都当成独立成员
        # 各序列化一份。四个键都要从通用树里剔除，否则 Fields 列表里会重复显示一遍
        # 一模一样的内容。
        content.pop("Expression", None)
        content.pop("ExpressionBits", None)
        content.pop("expressions", None)
        content.pop("expressionBits", None)
        _populate_expression_attribute(obj, attr_dict)
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

    if obj.efx_is_clip_attribute:
        clip_data, clip_bits = _export_clip_attribute(obj)
        attr_dict["clipData"] = clip_data
        attr_dict["clipBits"] = clip_bits

    if obj.efx_is_expression_attribute:
        expression_dict, expression_bits = _export_expression_attribute(obj)
        attr_dict["Expression"] = expression_dict
        attr_dict["ExpressionBits"] = expression_bits

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
    tag = obj.get("~TYPE")
    if tag == model.TYPE_ATTRIBUTE:
        issues.extend(_clip_bit_issues(obj))
    for child in obj.children:
        if child.get("~TYPE") in (model.TYPE_ROOT, model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE):
            issues.extend(_walk_clip_issues(child))
    return issues


def check_clip_bits(root_obj: Object) -> None:
    """导出前校验：见 ClipBitError 的说明。"""
    issues = _walk_clip_issues(root_obj)
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
    tag = obj.get("~TYPE")
    if tag == model.TYPE_ATTRIBUTE:
        issues.extend(_expression_bit_issues(obj))
    for child in obj.children:
        if child.get("~TYPE") in (model.TYPE_ROOT, model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE):
            issues.extend(_walk_expression_issues(child))
    return issues


def check_expression_bits(root_obj: Object) -> None:
    """导出前校验：见 ExpressionBitError 的说明。"""
    issues = _walk_expression_issues(root_obj)
    if issues:
        raise ExpressionBitError(
            "以下 Expression attribute 的公式 bit_index 有问题（越界或重复），会导致导出出错或"
            "静默丢数据，请先修正：\n" + "\n".join(f"  {m}" for m in issues)
        )
