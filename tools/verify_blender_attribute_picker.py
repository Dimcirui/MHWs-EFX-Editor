"""
tools/verify_blender_attribute_picker.py —— 新增 Attribute 的分类过滤 / 搜索入口

    <blender> --background --factory-startup --python tools/verify_blender_attribute_picker.py

退出码 0/1。

## 它防的是什么

**"当前浏览哪个分类"是个 UI 过滤状态，不许长成算子的参数校验。**

`EnumProperty` 的取值由 items 校验：items 里没有的字符串，无论是
`bpy.ops.efx_re.attribute_add(attr_type=X)` 传进来、还是 `op.attr_type = X` 赋进去，都会
直接抛 `enum "X" not found in (...)`。`EFX_RE_OT_attribute_add.attr_type` 原来用的是按
分类过滤的 `attribute_types.enum_items`，于是：

    分类下拉选了某个具体分类
      -> 用搜索弹窗（`efx_re.attribute_add_search`，按设计覆盖全部 ~150+ 种类型）
      -> 选一个不属于该分类的类型
      -> 转调 `efx_re.attribute_add` 直接报错

搜索的全部意义就是"不用先猜对分类"，被分类挡住等于这个功能不存在。

## 为什么必须在真 Blender 里跑

抛错的是 **RNA 层的枚举校验**，不是我们的 Python 代码——`blender_efx_re/*.py` 全都
`import bpy`，纯 Python 单测连 import 都做不到，更谈不上触发这条校验。

## 检查项

1. 分类设成某个具体分类时，`attribute_add` 仍然接受**别的分类**里的类型（就是当初炸的那条）。
2. 搜索算子的候选覆盖全部类型，且是任一分类的超集。
3. **分类过滤没被一起删掉**：菜单那一层（`readable_types(category)`）仍然只给该分类的类型。
4. 分类下拉本身还在，且第一项是"全部"。
"""
from __future__ import annotations

import sys
import traceback
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


def main() -> int:
    _enable_addon()
    from blender_efx_re import attribute_types, io_tree, model

    wm = bpy.context.window_manager

    # 找一个"有类型可新建"的分类，以及一个**不在它里面**的类型
    categories = [c for c in attribute_types.categories()
                  if attribute_types.readable_types(c)]
    all_types = [i["name"] for i in attribute_types.readable_types("ALL")]
    if len(categories) < 2 or len(all_types) < 2:
        # 门禁"没测到东西也会全绿"的另一半：素材不够就退 1，别假装过了
        print(f"[ERROR] 分类 {len(categories)} 个、可新建类型 {len(all_types)} 个，"
              "不足以构造'跨分类'这个场景")
        return 1

    category = categories[0]
    inside = {i["name"] for i in attribute_types.readable_types(category)}
    outside = next((n for n in all_types if n not in inside), None)
    if outside is None:
        print(f"[ERROR] 分类 {category} 囊括了全部类型，构造不出跨分类场景")
        return 1
    print(f"分类 {len(categories)} 个 / 可新建类型 {len(all_types)} 个")
    print(f"用分类 {category}（{len(inside)} 种），跨分类类型取 {outside}")

    # 造一个最小的根 + 一个 Entry 当新增目标
    data = {"Header": {"Version": 5571972},
            "Entries": [{"name": "e0", "index": 0, "Attributes": []}],
            "Actions": [], "Bones": [], "FieldParameterValues": [], "UvarGroups": [],
            "ExpressionParameters": [], "EffectGroups": []}
    io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, "picker_probe")
    entry = next(o for o in bpy.data.objects if o.get("~TYPE") == model.TYPE_ENTRY)
    bpy.context.view_layer.objects.active = entry

    print("\n=== 分类过滤不该限制算子能接受的类型")
    wm.efx_re_attr_category = category
    before = len(entry.children)
    try:
        result = bpy.ops.efx_re.attribute_add(attr_type=outside)
        error = ""
    except Exception as exc:                            # noqa: BLE001
        result, error = None, str(exc)
    _check(result == {"FINISHED"},
           f"分类={category} 时仍能新增别的分类的 {outside}",
           error or str(result))
    _check(len(entry.children) == before + 1,
           "真的挂上了一个新 attribute", f"{before} -> {len(entry.children)}")

    # 逐分类各挑一个类型，全都要能在"分类设成 category"的情况下加进去。
    # ⚠ **不要靠反射算子的枚举候选来验这件事**：`get_rna_type().properties[...].enum_items`
    #    对**动态 items 回调**读出来是**空的**（实测 0 项）——那正是报错信息里
    #    `enum "X" not found in ()` 那对空括号的来源。只能真的调一次算子。
    added = 0
    for other in categories[1:6]:
        pick = attribute_types.readable_types(other)
        if not pick:
            continue
        name = pick[0]["name"]
        if name in inside:
            continue
        try:
            ok = bpy.ops.efx_re.attribute_add(attr_type=name) == {"FINISHED"}
            why = ""
        except Exception as exc:                        # noqa: BLE001
            ok, why = False, str(exc)
        _check(ok, f"分类={category} 时能新增 {other} 里的 {name}", why)
        added += 1
    _check(added >= 1, "至少真的跨分类加了一次（不然上面几条等于没测）", str(added))

    print("\n=== 但分类过滤本身不许被删掉")
    _check(bool(inside) and len(inside) < len(all_types),
           f"readable_types({category}) 仍然只给该分类的类型",
           f"{len(inside)} / {len(all_types)}")
    _check(outside not in inside, "跨分类的类型确实不在该分类里")
    # 菜单那一层喂的就是这个回调，它必须仍然跟着分类走
    filtered = attribute_types.enum_items(None, bpy.context)
    _check(len(filtered) == len(inside),
           "enum_items() 仍然按当前分类过滤（菜单那一层）",
           f"{len(filtered)} vs {len(inside)}")
    items = attribute_types.category_items(None, bpy.context)
    _check(bool(items) and items[0][0] == "ALL",
           "分类下拉第一项是『全部』", str(items[:2]))

    print("\n=== 搜索入口覆盖全部类型")
    every = attribute_types.all_enum_items(None, bpy.context)
    _check(len(every) == len(all_types),
           "all_enum_items() 不受分类影响", f"{len(every)} vs {len(all_types)}")
    _check({n for n, _l, _d in every} >= inside, "全部候选是任一分类的超集")
    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # `blender --background --python x.py` 在脚本抛未捕获异常时退出码仍然是 0（实测），
    # 入口必须自己捕获。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
