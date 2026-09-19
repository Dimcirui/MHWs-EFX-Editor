"""
tools/verify_blender_enum_proxy.py —— 内联枚举下拉（`EFXValueNode.enum_proxy`）的门禁

    <blender> --background --factory-startup --python tools/verify_blender_enum_proxy.py

退出码 0/1。

## 它防的是什么

**给枚举字段选一个负数取值会直接崩掉 Blender**（不是抛异常，是整个进程没了）。

实测踩法：`ExpressionAssignType`（`EfxCommon.cs`）里有 `ForceWord = -1`，
`attribute_types.enum_members()` 原样把 `-1` 放进选项表；而 `_read_packed_int()` 为了
位域显示统一把负数读成**无符号**（`-1 -> 4294967295`）。两边一个有符号、一个无符号，
于是 `_enum_proxy_items()` 判定"当前值不在列举范围内"，往 items 里补了一条数值
**4294967295** 的兜底项——而 `EnumProperty` 的 items 第 4 位是 **C `int`**，越界即崩。

这类 bug 对**纯 Python 单测完全免疫**（`model.py` import bpy，那层跑不起来），也对
**逐字节往返门禁**免疫（崩溃发生在 UI 交互，文件内容压根没变）。只能在真 Blender 里
把那条 RNA 赋值真的做一遍。

## 检查项

1. `as_int32()` 把 32 位取值折进有符号 int32，且是双射（不同取值不撞车）。
2. 存储值为 `-1`、选项表里也是 `-1` 时，**不会**走"原值"兜底分支（两边表示一致）。
3. `_enum_proxy_items()` 返回的每一项，第 4 位都落在 int32 内。
4. **真的对 `enum_proxy` 赋值一遍**（这是当初崩的那个操作），并验证往返：
   `-1` 写进去能原样读回来、底层 `int_value` 也是 `-1`。
5. 无符号侧同样成立：存储 `4294967295` 时下拉能对上选项表里的 `-1`。
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
    # 从源码目录直接加载（和其他门禁一致的做法）
    sys.path.insert(0, str(_REPO_ROOT))
    import blender_efx_re
    blender_efx_re.register()


def main() -> int:
    _enable_addon()
    from blender_efx_re import model

    INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1

    print("=== as_int32() 本身")
    pairs = [(-1, -1), (0, 0), (4, 4), (4294967295, -1), (4294967294, -2),
             (2147483647, 2147483647), (2147483648, -2147483648)]
    _check(all(model.as_int32(v) == want for v, want in pairs),
           "把 32 位取值折进有符号 int32",
           str([(v, model.as_int32(v)) for v, _ in pairs]))
    folded = {model.as_int32(v) for v in range(-5, 6)} | {model.as_int32(1 << 31)}
    _check(len(folded) == 12, "折叠是双射（小范围抽样不撞车）", str(sorted(folded)))
    _check(all(INT32_MIN <= model.as_int32(v) <= INT32_MAX
               for v in (0, -1, 1 << 31, (1 << 32) - 1, (1 << 32) - 7)),
           "结果恒落在 int32 内")

    # 造一个真实的 EFXValueNode：挂在一个空物体的 efx_fields 上
    obj = bpy.data.objects.new("probe", None)
    bpy.context.scene.collection.objects.link(obj)
    node = obj.efx_fields.add()
    node.key = "translationX"
    node.data_type = "INT"

    # vendor `ExpressionAssignType` 的成员表（`EfxCommon.cs`）——`ForceWord = -1` 是关键
    items = [[0, "Add", "Add"], [1, "Subtract", "Subtract"], [2, "Multiply", "Multiply"],
             [3, "Divide", "Divide"], [4, "Assign", "Assign"], [-1, "ForceWord", "ForceWord"]]

    print("\n=== 负数枚举取值（ForceWord = -1）")
    node.int_value = -1
    model.set_inline_enum_items(node, items)
    built = model._enum_proxy_items(node, bpy.context)
    numbers = [it[3] for it in built]
    _check(all(INT32_MIN <= n <= INT32_MAX for n in numbers),
           "items 的每一项数值都在 int32 内（越界会直接崩 Blender）", str(numbers))
    _check(len(built) == len(items),
           "没有多插一条『原值』兜底项（说明两边表示一致）",
           "共 %d 项: %s" % (len(built), [it[0] for it in built]))
    _check(model._read_enum_proxy(node) in numbers,
           "getter 返回的值能在 items 里找到", str(model._read_enum_proxy(node)))

    print("\n=== 真的赋一次值（当初崩的就是这个操作）")
    model.set_inline_enum_items(node, items)
    node.enum_proxy = "-1"
    _check(node.enum_proxy == "-1", "写 -1 能原样读回", str(node.enum_proxy))
    _check(node.int_value == -1, "底层 int_value 存的是 -1", str(node.int_value))
    model.set_inline_enum_items(node, items)
    node.enum_proxy = "2"
    _check(node.int_value == 2 and node.enum_proxy == "2",
           "换成普通取值也正常", "%s / %s" % (node.int_value, node.enum_proxy))

    print("\n=== 无符号侧（存储里就是 4294967295）")
    node.int_value = -1          # int32 存储里 -1 和 0xFFFFFFFF 是同一个位模式
    model.set_inline_enum_items(node, items)
    built2 = model._enum_proxy_items(node, bpy.context)
    _check(len(built2) == len(items) and model._read_enum_proxy(node) == -1,
           "0xFFFFFFFF 的位模式能对上选项表里的 -1",
           "%d 项，getter=%s" % (len(built2), model._read_enum_proxy(node)))

    print("\n=== ForceWord 已从下拉里剔除（全语料 0 次，且它不是游戏语义）")
    from blender_efx_re import attribute_types
    members = attribute_types.enum_members(
        "ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DExpression", "translationX")
    _check(members is not None, "Transform3DExpression.translationX 认得出是枚举字段")
    if members:
        names = [m[1] for m in members]
        values = [m[0] for m in members]
        _check("ForceWord" not in names, "下拉里没有 ForceWord", str(names))
        _check(sorted(values) == [0, 1, 2, 3, 4], "只剩五个真实取值", str(sorted(values)))
    # 但文件里真存着 -1 时仍要原样保留（铁律 #1：宁可拒绝也不静默改数据）
    node.int_value = -1
    model.set_inline_enum_items(node, members or [])
    built3 = model._enum_proxy_items(node, bpy.context)
    _check(any(it[3] == -1 for it in built3),
           "文件里真存着 -1 时补一条『原值』项、不静默改掉",
           str([(it[0], it[3]) for it in built3]))
    _check(all(INT32_MIN <= it[3] <= INT32_MAX for it in built3),
           "这条兜底项本身也在 int32 内", str([it[3] for it in built3]))

    bpy.data.objects.remove(obj)
    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己捕获异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # **未捕获异常**时**退出码仍然是 0**（实测），`sys.exit(main())` 那行根本轮不到执行。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
