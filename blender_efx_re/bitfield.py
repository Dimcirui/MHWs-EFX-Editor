"""
blender_efx_re/bitfield.py —— 位域字段的分段编辑器

有些整数字段其实是**位域**：几个互斥的小字段挤在一个 uint 里。面板上画成一个裸数字，用户
根本没法编（`UVSequence.Flags` 的众数是 41，谁看得出那是"循环 + 水平随机翻 + 垂直随机翻 +
正向"）。

对齐姊妹项目 EFX-Editor 的形态（`blender_efx/bitmask_ops.py`）：面板上一个按钮显示解码摘要，
点开弹窗逐段选，**段外的残留位单独用整数框暴露**——保证未定义位零丢失、能精确还原。

位段规格来自 semantics 知识表里字段条目的 `bits` 键，形如：

    "bits": [
      {"mask": 3,  "label_zh": "播放模式", "label_en": "Playback Mode",
       "items": [[0, "只显示起始帧", "Start Frame Only"], [1, "循环", "Loop"], ...]},
      ...
    ]

`mask` 决定这一段占哪几位，移位量由 mask 的最低置位自动推出，不用另写。段的取值如果超出
`items` 列举的范围（语料里没见过的组合），下拉会临时插一条"原值"合成项，绝不静默改掉它。

**为什么走弹窗而不是内联画一排下拉**：内联需要给每个位段一个 EnumProperty，而位段数量和选项
都是按字段动态变的，PropertyGroup 上没法声明动态数量的属性。弹窗算子的属性是每次调用独立的，
可以用固定数量的槽位池（`_MAX_SEGMENTS`）配合动态 items 回调撑起来。
"""

from __future__ import annotations

import json

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from . import i18n, model

# 槽位池上限。目前最多的是 UVSequence.Flags 的 6 段，留点余量。
_MAX_SEGMENTS = 10

# 动态 EnumProperty 的 items 必须被 Python 侧持有：Blender 只存指向字符串的指针、不复制内容，
# 回调返回的临时元组被回收后界面就是乱码（官方文档明写的坑）。按 (spec_json, 段序号) 缓存。
_ITEMS_CACHE: dict = {}


def shift_of(mask: int) -> int:
    """mask 的最低置位是第几位。`0x30` -> 4。mask 为 0 时返回 0（调用方应先排除）。"""
    if mask == 0:
        return 0
    return (mask & -mask).bit_length() - 1


def segments(entry: dict | None) -> list[dict]:
    """知识表条目里的位段列表；没有就是空列表（该字段不是位域）。"""
    if not entry:
        return []
    bits = entry.get("bits")
    return bits if isinstance(bits, list) else []


def _seg_label(seg: dict) -> str:
    if i18n.get_lang() == "EN":
        return seg.get("label_en") or seg.get("label_zh") or ""
    return seg.get("label_zh") or seg.get("label_en") or ""


def _item_label(item: list) -> str:
    # item = [值, 中文, 英文]；英文缺失时退回中文
    if i18n.get_lang() == "EN" and len(item) >= 3 and item[2]:
        return item[2]
    return item[1] if len(item) >= 2 else str(item[0])


def decode(packed: int, segs: list[dict]) -> list[int]:
    """把打包值拆成每一段的子值。"""
    return [(packed & seg["mask"]) >> shift_of(seg["mask"]) for seg in segs]


def residual(packed: int, segs: list[dict]) -> int:
    """所有段之外的残留位。这部分我们不认识，原样保留。"""
    covered = 0
    for seg in segs:
        covered |= seg["mask"]
    return packed & ~covered


def encode(sub_values: list[int], residual_bits: int, segs: list[dict]) -> int:
    """把每段的子值和残留位重新打包。子值超出段宽会被 mask 截断（防御性，正常路径不会发生）。"""
    packed = residual_bits
    for value, seg in zip(sub_values, segs):
        mask = seg["mask"]
        packed |= (value << shift_of(mask)) & mask
    return packed


def summary(packed: int, segs: list[dict]) -> str:
    """面板按钮上显示的一行摘要：`循环 · 随机翻转 · 随机翻转 · 正向`。

    某段取值不在 items 里时显示成 `标签=原值`，让人一眼看出这里有个没见过的值，
    而不是被静默显示成第一项。
    """
    parts = []
    for value, seg in zip(decode(packed, segs), segs):
        match = next((it for it in seg.get("items", []) if it[0] == value), None)
        parts.append(_item_label(match) if match else f"{_seg_label(seg)}={value}")
    left = residual(packed, segs)
    if left:
        parts.append(f"+0x{left:X}")
    return " · ".join(parts) if parts else str(packed)


# ─────────────────────────────────────────────────────────────────────────────
# 节点定位
#
# 算子拿不到 PropertyGroup 的指针，只能靠"下标路径"回头找：`"2.0.1"` 表示
# obj.efx_fields[2].children[0].children[1]。弹窗的 invoke 和 execute 是两次独立调用，
# 用路径字符串比 context_pointer_set 稳（后者活不过弹窗）。
# ─────────────────────────────────────────────────────────────────────────────

def node_path(root_collection, node) -> str:
    """在一棵 EFXValueNode 树里找到 node，返回下标路径；找不到返回空串。"""
    def walk(items, prefix):
        for i, item in enumerate(items):
            here = f"{prefix}{i}"
            if item == node:
                return here
            found = walk(item.children, here + ".")
            if found:
                return found
        return ""
    return walk(root_collection, "")


def resolve_node(root_collection, path: str):
    """node_path() 的反函数。路径对不上（树结构变了）返回 None。"""
    node = None
    items = root_collection
    for part in path.split("."):
        if not part.isdigit():
            return None
        index = int(part)
        if index >= len(items):
            return None
        node = items[index]
        items = node.children
    return node


def read_packed(node) -> int | None:
    """位域字段的当前打包值。只有整数节点才有意义。"""
    if node.data_type == "BIGINT":
        raw = node.uint_str
    elif node.data_type == "INT":
        raw = node.int_value
    else:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value + (1 << 32) if value < 0 else value


def write_packed(node, value: int) -> None:
    if node.data_type == "BIGINT":
        node.uint_str = str(value)
    else:
        node.int_value = value


# ─────────────────────────────────────────────────────────────────────────────
# 弹窗算子
# ─────────────────────────────────────────────────────────────────────────────

def _make_items_getter(index: int):
    def items(self, context):
        key = (self.spec_json, index, i18n.get_lang(), self.current_value)
        cached = _ITEMS_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            segs = json.loads(self.spec_json)
        except (ValueError, TypeError):
            segs = []
        if index >= len(segs):
            built = [("0", "-", "")]
        else:
            seg = segs[index]
            built = [(str(it[0]), _item_label(it), "") for it in seg.get("items", [])]
            # 当前值不在列举范围内时临时插一条，避免弹窗一开就把它改成第一项
            here = (self.current_value & seg["mask"]) >> shift_of(seg["mask"])
            if not any(int(v) == here for v, _, _ in built):
                built.append((str(here), f"{here}（原值）", "语料里没见过这个取值，原样保留"))
        _ITEMS_CACHE[key] = built
        return built
    return items


class EFX_RE_OT_edit_bitfield(Operator):
    """分段编辑一个位域整数字段"""

    bl_idname = "efx_re.edit_bitfield"
    bl_label = "Edit Bit Field"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    node_path: StringProperty(options={"HIDDEN"})
    spec_json: StringProperty(options={"HIDDEN"})
    current_value: IntProperty(options={"HIDDEN"})
    field_label: StringProperty(options={"HIDDEN"})
    residual_bits: IntProperty(name="Other Bits", description="不属于任何已知位段的残留位，原样保留")

    # 固定数量的槽位池：位段数量按字段变化，Operator 没法声明动态数量的属性。
    # 用不到的槽在 draw() 里跳过。
    #
    # **必须写进 `__annotations__`，不能往 `locals()` 里塞**：Blender 是按注解收集算子属性的
    # （`name: Property(...)` 那套语法本质就是往 __annotations__ 里写），普通类属性赋值它压根
    # 不看，表现出来就是调用算子时报 `keyword "seg0" unrecognized`。上面那几个属性用了注解
    # 语法，所以这里 __annotations__ 一定已经存在。
    for _i in range(_MAX_SEGMENTS):
        __annotations__[f"seg{_i}"] = bpy.props.EnumProperty(
            name=f"Segment {_i}", items=_make_items_getter(_i),
        )
    del _i

    def _segments(self) -> list[dict]:
        try:
            return json.loads(self.spec_json)
        except (ValueError, TypeError):
            return []

    def invoke(self, context, event):
        segs = self._segments()
        if not segs:
            self.report({"ERROR"}, "这个字段没有位段定义")
            return {"CANCELLED"}
        for i, value in enumerate(decode(self.current_value, segs)):
            if i < _MAX_SEGMENTS:
                setattr(self, f"seg{i}", str(value))
        self.residual_bits = residual(self.current_value, segs)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        segs = self._segments()
        if self.field_label:
            layout.label(text=self.field_label, translate=False)
        for i, seg in enumerate(segs[:_MAX_SEGMENTS]):
            layout.prop(self, f"seg{i}", text=_seg_label(seg))
        # 残留位只在真的有的时候才画——正常文件里恒 0，平时露出来只会让人以为哪儿出问题了
        if self.residual_bits:
            layout.separator()
            layout.prop(self, "residual_bits")

    def execute(self, context):
        obj = getattr(context, "object", None)
        if obj is None or obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            self.report({"ERROR"}, "活动对象不是 EFX_ATTRIBUTE")
            return {"CANCELLED"}
        node = resolve_node(obj.efx_fields, self.node_path)
        if node is None:
            self.report({"ERROR"}, "找不到目标字段（对象树变了？）")
            return {"CANCELLED"}

        segs = self._segments()
        values = []
        for i in range(len(segs)):
            raw = getattr(self, f"seg{i}", "0") if i < _MAX_SEGMENTS else "0"
            values.append(int(raw) if str(raw).lstrip("-").isdigit() else 0)
        write_packed(node, encode(values, self.residual_bits, segs))
        return {"FINISHED"}


_CLASSES = (EFX_RE_OT_edit_bitfield,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    _ITEMS_CACHE.clear()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
