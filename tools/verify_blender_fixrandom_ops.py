"""
tools/verify_blender_fixrandom_ops.py —— FixRandomGenerator 专属编辑控件（fixrandom_ops.py）门禁

    <blender> --background --factory-startup --python tools/verify_blender_fixrandom_ops.py

退出码 0/1。

## 它防的是什么

1. `efx_re.randomfix_randomize_seed`：能找到目标 `randomSeedTable{N}` 节点、写入一个合法
   的有符号 int32，并且（复用同一套 `EFXValueNode.int_value` 的 `update=` 回调）把粒子预览
   标脏——这是同一次会话里刚修的 `model._on_field_edited()` live-update 链路，这里顺手钉住
   别被后续改动悄悄断开。
2. `efx_re.randomfix_edit_table_group`：**真实的溢出坑**——`tableSelectionGroup` 全语料众数
   是 `-1`，`bitfield.read_packed()` 把它折成无符号读成 `0xFFFFFFFF`。如果直接把编辑后的
   无符号值写回有符号 32 位的 `int_value`（`bitfield.py` 通用弹窗那条路的写法），赋值会抛
   `ValueError`，整个属性面板对这个字段直接罢工。`fixrandom_ops.py` 改成只碰低 8 位、
   写回前折回有符号范围（`model.as_int32()`），这里验证：不崩、低 8 位如预期、
   不认识的高位原样保留（铁律 #2：宁可拒绝也不静默改数据）。

## 为什么必须在真 Blender 里跑

`int_value` 是 RNA `IntProperty`（有符号 C `int32`），越界赋值抛的是 RNA 层的
`ValueError`，不是我们的 Python 代码——纯 Python 单测（`efx_sim/`）不 import bpy，
这层校验根本跑不到。
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FAILED = 0


def _check(ok: bool, label: str, detail: str = "") -> None:
    global _FAILED
    if ok:
        print(f"  PASS  {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}" + (f"\n        -> {detail}" if detail else ""))


def _enable_addon() -> None:
    import addon_utils
    for mod in ("blender_efx_re", "bl_ext.user_default.mhws_efx_editor"):
        try:
            addon_utils.enable(mod, default_set=False, persistent=False)
            return
        except Exception:
            continue
    import blender_efx_re
    blender_efx_re.register()


def _make_probe_attribute():
    """一个最小的 `~TYPE=EFX_ATTRIBUTE` 空物体，挂着 FixRandomGenerator 的两个目标字段。
    不走完整的 Entry/Root 层级——两个算子只认 `obj.get("~TYPE")` 和 `obj.efx_fields`。"""
    from blender_efx_re import model
    obj = bpy.data.objects.new("probe_fixrandom", None)
    bpy.context.scene.collection.objects.link(obj)
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    obj.efx_attr_type = "ReeLib.Efx.Structs.Misc.EFXAttributeFixRandomGenerator"
    bpy.context.view_layer.objects.active = obj

    seed_node = obj.efx_fields.add()
    seed_node.key = "randomSeedTable0"
    seed_node.data_type = "INT"
    seed_node.int_value = 12345

    group_node = obj.efx_fields.add()
    group_node.key = "tableSelectionGroup"
    group_node.data_type = "INT"
    group_node.int_value = -1
    return obj, seed_node, group_node


def main() -> int:
    _enable_addon()
    from blender_efx_re import bitfield, model, sim_preview

    INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1

    print("=== efx_re.randomfix_randomize_seed")
    obj, seed_node, group_node = _make_probe_attribute()
    seed_path = bitfield.node_path(obj.efx_fields, seed_node)
    origin = seed_node.int_value
    sim_preview._P["dirty"] = False
    result = bpy.ops.efx_re.randomfix_randomize_seed(node_path=seed_path)
    _check(result == {"FINISHED"}, "算子执行成功", str(result))
    _check(INT32_MIN <= seed_node.int_value <= INT32_MAX,
           "写入的新种子落在有符号 int32 内", str(seed_node.int_value))
    _check(sim_preview._P["dirty"], "换种子也会把粒子预览标脏（同一条 _on_field_edited 链路）")
    # 2**-32 概率会撞上原值，可忽略；真出现就换个种子重跑一次，不当稳定失败处理。
    if seed_node.int_value == origin:
        print("  INFO  新种子恰好和原值相同（概率 ~1/2^32），不视为失败")

    print("\n=== efx_re.randomfix_edit_table_group（-1 哨兵值的溢出坑）")
    group_path = bitfield.node_path(obj.efx_fields, group_node)
    origin_packed = bitfield.read_packed(group_node)
    _check(origin_packed == 0xFFFFFFFF, "起始值 -1 折成无符号是全 32 位 1（复现众数场景）",
           hex(origin_packed))

    try:
        result = bpy.ops.efx_re.randomfix_edit_table_group(
            node_path=group_path, t0=True, t3=True)
        error = ""
    except Exception as exc:  # noqa: BLE001 —— 这里就是要抓 RNA 层可能抛出的 ValueError
        result = None
        error = repr(exc)
    _check(result == {"FINISHED"},
           "对 -1 哨兵值执行多选编辑不会溢出崩溃（这是本模块存在的全部理由）", error)

    if result == {"FINISHED"}:
        new_packed = bitfield.read_packed(group_node)
        _check(new_packed & 0xFF == 0b0000_1001,
               "低 8 位如预期（勾了 Table 0 + Table 3 = 0x09）", bin(new_packed & 0xFF))
        _check(new_packed & ~0xFF == origin_packed & ~0xFF,
               "不认识的高位原样保留，没被静默清零（铁律 #2）",
               f"{hex(new_packed & ~0xFF)} vs {hex(origin_packed & ~0xFF)}")
        _check(INT32_MIN <= group_node.int_value <= INT32_MAX,
               "折回去的 int_value 落在有符号 int32 内", str(group_node.int_value))

    print("\n=== 全部勾掉 -> 低 8 位清零，高位仍保留")
    result = bpy.ops.efx_re.randomfix_edit_table_group(node_path=group_path)
    _check(result == {"FINISHED"}, "全部不勾也能正常执行", str(result))
    cleared = bitfield.read_packed(group_node)
    _check(cleared & 0xFF == 0, "低 8 位清零", bin(cleared & 0xFF))
    _check(cleared & ~0xFF == origin_packed & ~0xFF, "高位仍然原样保留",
           f"{hex(cleared & ~0xFF)} vs {hex(origin_packed & ~0xFF)}")

    bpy.data.objects.remove(obj)
    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己兜住异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # **未捕获异常**时**退出码仍然是 0**（实测），`sys.exit(main())` 那行根本轮不到执行。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
