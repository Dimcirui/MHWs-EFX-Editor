"""
blender_efx_re/fixrandom_ops.py —— FixRandomGenerator 专属编辑控件

对齐姊妹项目 EFX-Editor 的 RANDOMFIX 界面（`blender_efx/operators.py` 的
`EFX_OT_randomize_seed` / `EFX_OT_randomfix_set_table_group`，见其 `blender_efx/panels.py`
`if type_name == "RANDOMFIX":` 那段）：

- `randomSeedTable0~7` 每个字段一个骰子按钮，点一下换成新的随机 int32，不用手打。
- `tableSelectionGroup`（8-bit 掩码，bit i = randomSeedTable{i} 是否属于这一组）用勾选框
  弹窗编辑，不逼用户心算位运算。

**不复用 `bitfield.py` 的通用分段弹窗**，两个原因：
1. 语义不同：`bitfield.py` 那套模型是"互斥的多位段值"（`UVSequence.Flags` 那种，弹窗里每段
   是一个只能挑一项的下拉），而这 8 位是**互相独立的开关**（真多选），画成下拉反而要来回切
   8 次才能拼出一个组合，checkbox 一屏看完点完。
2. 真实的溢出风险：`EfxBridge fieldstats` 全语料实测 `tableSelectionGroup` 众数是 `-1`
   （见 `semantics/mhws_field_labels.json` 该字段的 evidence），`bitfield.read_packed()`
   把它折成无符号读成 `0xFFFFFFFF`。通用弹窗的 `residual_bits`（`IntProperty`，有符号 32 位）
   会被塞进高 24 位残留 `0xFFFFFF00`——这个数比 `2**31` 大，赋值给有符号 `IntProperty` 会
   溢出。这里只处理低 8 位，高位原样保留、写回前用 `model.as_int32()` 折回有符号
   int32，不会重演这个问题。

节点定位复用 `bitfield.py` 的 `node_path()`/`resolve_node()`——下标路径是唯一能跨
`invoke()`/`execute()` 两次独立调用存活的定位方式，原因见 `bitfield.py` 头部说明。

约束：这个模块只服务 `FixRandomGenerator` 一种 attribute，不要为了"通用"把 checkbox 多选
塞回 `bitfield.py`——全语料目前只有这一个字段是真正的独立开关位，提前抽象没有第二个使用方。
"""

from __future__ import annotations

import random

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from . import bitfield, model

#: `tableSelectionGroup` 只用了低 8 位（randomSeedTable0~7 各一位），见
#: `ATTRIBUTE_TYPES.md` 的 `FixRandomGenerator` 字段表（10 个字段，8 个种子槽位）。
TABLE_SIZE = 8


class EFX_RE_OT_randomfix_randomize_seed(Operator):
    """给 FixRandomGenerator 的一个 randomSeedTable{N} 字段换一个新的随机 int32"""

    bl_idname = "efx_re.randomfix_randomize_seed"
    bl_label = "Randomize Seed"
    bl_description = "为这个随机种子槽位生成一个新的随机数值"
    bl_options = {"REGISTER", "UNDO"}

    node_path: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        obj = getattr(context, "object", None)
        if obj is None or obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            self.report({"ERROR"}, "活动对象不是 EFX_ATTRIBUTE")
            return {"CANCELLED"}
        node = bitfield.resolve_node(obj.efx_fields, self.node_path)
        if node is None or node.data_type != "INT":
            self.report({"ERROR"}, "找不到目标字段（对象树变了？）")
            return {"CANCELLED"}
        node.int_value = random.randint(-2147483648, 2147483647)
        return {"FINISHED"}


class EFX_RE_OT_randomfix_edit_table_group(Operator):
    """勾选框多选编辑 FixRandomGenerator 的 tableSelectionGroup"""

    bl_idname = "efx_re.randomfix_edit_table_group"
    bl_label = "Edit Table Selection Group"
    bl_description = "按勾选框编辑种子表选择组（勾选第 i 项 = randomSeedTable{i} 属于该组）"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    node_path: StringProperty(options={"HIDDEN"})

    # 固定数量的勾选框槽位，必须写进 __annotations__（Blender 按注解收集算子属性）——
    # 同样的写法见 bitfield.py::EFX_RE_OT_edit_bitfield 的 seg{i} 槽位池。
    for _i in range(TABLE_SIZE):
        __annotations__[f"t{_i}"] = BoolProperty(name=f"Table {_i}")
    del _i

    def _resolve(self, context):
        obj = getattr(context, "object", None)
        if obj is None or obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            return None
        return bitfield.resolve_node(obj.efx_fields, self.node_path)

    def invoke(self, context, event):
        node = self._resolve(context)
        if node is None:
            self.report({"ERROR"}, "找不到目标字段（对象树变了？）")
            return {"CANCELLED"}
        packed = bitfield.read_packed(node) or 0
        for i in range(TABLE_SIZE):
            setattr(self, f"t{i}", bool(packed & (1 << i)))
        return context.window_manager.invoke_props_dialog(self, width=200)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Table Selection Group", translate=False)
        for i in range(TABLE_SIZE):
            layout.prop(self, f"t{i}", text=f"Table {i}", translate=False)

    def execute(self, context):
        node = self._resolve(context)
        if node is None:
            self.report({"ERROR"}, "找不到目标字段（对象树变了？）")
            return {"CANCELLED"}
        # 只改低 8 位，高位（常见的 -1 哨兵折出来的全 1 高位）原样保留——不认识的位不代表
        # 可以清零，见 CLAUDE.md 铁律 #2。
        packed = bitfield.read_packed(node) or 0
        low8 = 0
        for i in range(TABLE_SIZE):
            if getattr(self, f"t{i}"):
                low8 |= (1 << i)
        new_packed = (packed & ~0xFF) | low8
        if node.data_type == "BIGINT":
            bitfield.write_packed(node, new_packed)
        else:
            # `int_value` 是有符号 32 位：`new_packed` 是 read_packed() 折出来的无符号
            # 表示，写回前要折回有符号范围（`model.as_int32()`，`enum_proxy` setter 用的
            # 同一个函数），否则残留的高位（-1 哨兵典型地全是 1）会让赋值溢出——这正是这个
            # 模块不复用 bitfield.py 通用弹窗的原因，见模块头部说明。
            bitfield.write_packed(node, model.as_int32(new_packed))
        return {"FINISHED"}


_CLASSES = (EFX_RE_OT_randomfix_randomize_seed, EFX_RE_OT_randomfix_edit_table_group)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
