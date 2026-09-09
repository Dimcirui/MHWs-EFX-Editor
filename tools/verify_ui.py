"""
tools/verify_ui.py —— UI 层冒烟检查：图标名 + "往每个列表里加一条"

    <blender> --background --factory-startup --python tools/verify_ui.py [-- --sample <efx 文件>]

这两项针对的是同一类问题：**UI 代码里的错误只有在那条路径真的被执行到时才会炸**，而很多路径
平时根本走不到，冒烟测试全绿也说明不了什么。已经栽过两次：

1. `EFX_RE_UL_groups.draw_item` 用了不存在的图标 `BOOKMARK`（正确拼写是复数 `BOOKMARKS`）。
   `template_list` 在集合为空时**根本不调 draw_item**，而所有样本文件的 entry 都没有
   Subselect 组，所以面板绘制的冒烟测试一路全绿，直到用户手动加了第一个组才炸。
2. `EFX_RE_OT_uvar_group_add` 给枚举赋了不存在的值 `"0"`（`uvar_type` 只有 `'1'`/`'2'`）。
   这个算子在样本流程里从没被点过，同样一直潜伏着。

## 检查一：图标名（纯静态，不执行 UI）

把 blender_efx_re/*.py 里所有 `icon="XXX"` 字面量抠出来，对着 Blender 自己的图标枚举查一遍。
跑得快，覆盖所有代码路径，不依赖"这段 UI 有没有被画到"。只认字面量，`icon=variable` 这种
动态取值扫不到。

## 检查二：把每个列表都加一条

挨个跑所有 `*_add` / `*_remove` 算子。这类算子的 bug（给枚举赋非法值、属性名写错）在无头模式
下就能抓到，不需要真实 UI——真正需要 UI 的只有 `draw_item` 本身，那部分靠检查一兜住。
"""
from __future__ import annotations

import pathlib
import re
import sys

import bpy

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_ADDON_DIR = _REPO_ROOT / "blender_efx_re"

# `icon="XXX"` / `icon='XXX'`，只取全大写下划线数字的合法枚举形状
_ICON_RE = re.compile(r"""icon\s*=\s*["']([A-Z0-9_]+)["']""")


def valid_icons() -> set[str]:
    """Blender 认识的全部图标名。从 `UILayout.prop` 的 icon 参数枚举取——所有接受 icon 的
    UI 函数共用同一套枚举，随版本增删，不硬编码清单。"""
    param = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"]
    return {item.identifier for item in param.enum_items}


def check_icons() -> int:
    """返回有问题的处数。"""
    icons = valid_icons()
    bad: list[tuple[str, int, str]] = []
    total = 0
    for path in sorted(_ADDON_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for name in _ICON_RE.findall(line):
                total += 1
                if name not in icons:
                    bad.append((str(path.relative_to(_REPO_ROOT)), lineno, name))

    print("[图标] 扫描到 %d 处字面量，Blender %s 认识 %d 个图标名"
          % (total, bpy.app.version_string, len(icons)))
    if not bad:
        print("[图标] 全部合法")
        return 0

    import difflib
    print("[图标] %d 处用了不存在的图标名：" % len(bad))
    for rel, lineno, name in bad:
        near = difflib.get_close_matches(name, sorted(icons), n=3, cutoff=0.5)
        hint = ("   （是不是想写 " + " / ".join(near) + "？）") if near else ""
        print("    %s:%d  %s%s" % (rel, lineno, name, hint))
    return len(bad)


# (算子名, 目标对象怎么挑)
_ADD_OPS = (
    ("group_add", "ENTRY"),
    ("bone_add", "ENTRY"),               # 根级算子只看 resolve_root，给树里任意对象即可
    ("field_parameter_add", "ENTRY"),
    ("uvar_group_add", "ENTRY"),
    ("expression_parameter_add", "ENTRY"),
    ("clip_curve_add", "CLIP"),
    ("clip_keyframe_add", "CLIP"),
    ("expression_curve_add", "EXPR"),
)


def check_add_ops(samples: list[str]) -> int:
    """挨个跑所有列表新增算子，返回失败数。

    这类算子的 bug（给枚举赋非法值、属性名写错）在无头模式下就能抓到，不需要真实 UI——
    真正需要 UI 的只有 `UIList.draw_item` 本身，那部分靠上面的图标静态扫描兜住。
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import blender_efx_re
    blender_efx_re.register()
    from blender_efx_re import io_tree, model

    # 把所有样本都导进来：单个文件未必同时含 Clip 和 Expression 两种 attribute，
    # 全导一遍才能把八个算子都覆盖到（少覆盖一个就等于少一道防线）。
    for sample in samples:
        if getattr(bpy.ops.efx_re, "import")(filepath=sample) != {"FINISHED"}:
            print("[算子] 导入样本失败：%s" % sample)
            return 1

    root = bpy.context.scene.efx_re_active_root
    attrs = [o for o in bpy.data.objects if o.get("~TYPE") == model.TYPE_ATTRIBUTE]
    targets = {
        "ENTRY": io_tree.root_entries(root)[0],
        "CLIP": next((o for o in attrs if o.efx_is_clip_attribute), None),
        "EXPR": next((o for o in attrs if o.efx_is_expression_attribute), None),
    }

    failed = 0
    for opname, want in _ADD_OPS:
        target = targets.get(want)
        if target is None:
            print("[算子] %-26s SKIP（样本里没有 %s 类型的 attribute）" % (opname, want))
            continue
        bpy.context.view_layer.objects.active = target
        try:
            result = getattr(bpy.ops.efx_re, opname)()
            ok = result == {"FINISHED"}
            print("[算子] %-26s %s" % (opname, "OK" if ok else result))
            failed += 0 if ok else 1
        except Exception as ex:
            detail = str(ex).strip().splitlines()[-1][:120]
            print("[算子] %-26s FAIL  %s: %s" % (opname, type(ex).__name__, detail))
            failed += 1
    return failed


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--sample" in argv:
        samples = [argv[argv.index("--sample") + 1]]
    else:
        samples = [str(p) for p in sorted((_REPO_ROOT / "diag").glob("*.orig"))]

    bad = check_icons()
    print()
    if not samples:
        print("[算子] SKIP（diag/ 下没有样本，可用 --sample 指定）")
    else:
        bad += check_add_ops(samples)

    print()
    print("===== ALL PASS" if bad == 0 else "===== %d 处问题" % bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
