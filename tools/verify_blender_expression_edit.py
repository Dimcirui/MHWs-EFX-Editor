# -*- coding: utf-8 -*-
"""
tools/verify_blender_expression_edit.py —— Expression 公式结构化编辑的回归防护

必须在 Blender 里跑（要真 bpy：PropertyGroup 注册、update 回调、算子），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_expression_edit.py

可选参数放在 `--` 之后：`--diag <样本目录>`（默认 `<仓库根>/diag`，收 `*.orig`）、
`--out <输出目录>`、`--dll <EfxBridge.dll>`，含义同 `verify_blender_roundtrip.py`。

为什么单独一条门禁
------------------
结构化编辑器（`blender_efx_re/expr_edit.py`）把公式文本拆成可点的树再拼回去。这条路
`verify_blender_roundtrip.py` 一步都走不到——它走的是"导入 -> 导出"，中间没人碰过
`formula`。所以这里做的是它做不了的：**在导入和导出之间，把每一条公式都过一遍完整的
"拆开 -> 重建行 -> 重拼文本"**，然后同时查两件事。

**两层判据，覆盖的是两类不同的回归**（不要合并，也不要以为其中一条能顶另一条）：

1. `行重拼出来的文本 == 导入时的公式文本`——抓**文本层**的改动。这一层比字节严，因为
   公式文本经桥接重新解析建树，纯排版差异（少一对括号、`Min(a,b)` 写成 `(a Min b)`）
   **产出的二进制完全相同**，字节比对对它免疫。实测：把 `_emit_rows()` 改成省括号、
   或把 `Min` 当中缀发，字节检查照样全绿，只有这条红。
2. `全量拆开再拼回之后导出，字节 == 纯 CLI 往返基线`——抓**结构层**的改动（树形真的
   变了：负号规范化成 `0 - x`、浮点精度掉了、参数顺序反了）。判据是"和纯 CLI 往返产物
   逐字节相同"，不是"和原文件相同"（验证纪律 #9）。

检查项
------
1. 导入后每条公式都真的建出了结构化行，且行重新拼出来的文本 == 导入时的文本；
2. 全量"拆开再拼回"之后导出，字节 == 纯 CLI 往返基线（核心断言）；
3. 产物能被 RE-Engine-Lib 读回来；
4. 结构算子（替换 / 内嵌 / 删除）真的改到了 `formula`，且改完仍能被桥接的解析器接受。
   含「内嵌和删除互为逆」「叶子上删除是空操作」，以及参数角色名只标语义已定的
   两个函数（`Clamp`/`Lerp`），未确认语义的一律留空；
4b. "有公式、没有行"（老 .blend / 导入后才热加载新代码）会被 `rebuild_missing_rows()`
   自动补上，且补的过程不碰 `formula`、不重建已经有行的曲线；
5. 文本 -> 行 -> 文本 两个方向的 update 回调不互相打架（改文本行跟着变、改行文本跟着变），
   也不会把用户手打的非法文本悄悄吃掉；
6. 样本里没有任何 Expression attribute 时**报错退 1**，不静默全绿（否则这条门禁等于没跑）。

按验证纪律 #11，五种注入都实测过会让这条门禁退 1（都注在 `efx_sim/expr.py` 的
`_emit_rows()` / `format_float()` 上，纯 Python 层在 `tests/test_sim_expr_edit.py` 也各有
对应用例）。**实测到的红点分布，别凭直觉改**：

| 注入 | 检查项 1（文本） | 检查项 2（字节） | 算子那一节 |
|---|---|---|---|
| `_emit_rows()` 省括号 | 红 | 绿 | 绿 |
| `Min` 当中缀发 | 红 | 绿 | 绿 |
| 浮点换 `repr()` | 红 | 绿 | 红 |
| 负号规范化成 `0 - x` | 绿 | 绿 | 红 |
| 三参函数前两参对调 | 红 | **红** | 红 |

前三种只改排版/写法，桥接重新解析出来的树一模一样，**字节本来就不该变**——这不是漏网，
是这两层判据分工不同。负号那一行绿是**样本覆盖问题**：`diag/` 现有样本的 13 条公式里
一个一元负号都没有（唯一的 `-` 是二元减法 `- 100`），所以只有算子那一节（用内存里造的
`-0.5` 公式）能抓到它。下面会打印样本覆盖到的节点种类，缺哪种一眼能看见。

退出码：全绿 0，有失败 1。⚠ `blender --background --python` 在脚本抛未捕获异常时退出码
仍是 0（实测），所以入口自己兜一层，见文件末尾。
"""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import traceback

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402  （必须在 sys.path 铺好之后再 import 本项目的包）

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, expr_edit, io_tree, model, operators, transform3d_view  # noqa: E402
from efx_sim import expr as _expr  # noqa: E402


def _script_args() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _parse_args(argv: list) -> dict:
    opts = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1]
    return opts


class Report:
    def __init__(self) -> None:
        self.failures = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
            if detail:
                print("        -> " + detail)


def _expression_attributes(root_obj):
    """这棵对象树里所有 IExpressionAttribute 对象（含嵌套 efxrData 子树里的）。"""
    out = []
    for obj in bpy.data.objects:
        if obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if not getattr(obj, "efx_is_expression_attribute", False):
            continue
        if _root_of(obj) is root_obj:
            out.append(obj)
    return out


def _root_of(obj):
    for col in obj.users_collection:
        cursor = col
        while cursor is not None:
            if cursor.get("~TYPE") == model.TYPE_ROOT:
                return cursor
            cursor = next((c for c in bpy.data.collections
                           if cursor.name in c.children), None)
    return None


def _structural_no_op(attrs) -> int:
    """把每条公式都过一遍"拆成行 -> 从行重拼文本"。这正是用户在面板上点任何一下之后
    走的那条路（只是不改内容），返回过了多少条。"""
    count = 0
    for obj in attrs:
        for curve in obj.efx_expression_curves:
            expr_edit.rebuild_rows(curve)
            expr_edit.write_formula(curve)
            count += 1
    return count


def verify_sample(orig: pathlib.Path, workdir: pathlib.Path, report: Report,
                  kinds_seen: set) -> int:
    """返回这个样本里过了多少条公式（给"一条都没有就报错"用）。`kinds_seen` 收集样本
    覆盖到的节点种类，用来告诉调用方"这批样本压根没测到某一类节点"。"""
    stem = orig.name.split(".efx.")[0]
    print(f"\n=== {stem}")

    src = workdir / orig.name.replace(".orig", "")
    shutil.copy(orig, src)

    # 纯 CLI 往返基线：完全不经过 Blender 对象树（验证纪律 #9）
    cli_json = bridge.dump_efx(src)
    cli_out = workdir / f"{stem}_cli.efx.5571972"
    bridge.load_efx(cli_json, cli_out)

    data = bridge.dump_efx(src)
    root_obj = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, src.name)
    root_obj.efx_source_filename = src.name
    transform3d_view.sync_all_transform3d(root_obj)

    attrs = _expression_attributes(root_obj)
    curves = [(o, c) for o in attrs for c in o.efx_expression_curves]
    print(f"  Expression attribute {len(attrs)} 个，公式 {len(curves)} 条")

    # 1. 导入就该有结构化行，且行拼回去 == 导入时的文本
    missing_rows = [c.formula for _o, c in curves if not c.nodes and not c.formula_error]
    report.check("导入后每条公式都建出了结构化行", not missing_rows,
                 f"{len(missing_rows)} 条没有行：{missing_rows[:3]}")

    mismatched = []
    for _obj, curve in curves:
        kinds_seen.update(n.kind for n in curve.nodes)
        rebuilt = _expr.from_rows(expr_edit.read_rows(curve), curve.second_branch or None)
        if rebuilt != curve.formula:
            mismatched.append((curve.formula, rebuilt))
    report.check("行重拼出来的文本 == 导入时的公式文本", not mismatched,
                 f"{len(mismatched)} 条不同，首例：{mismatched[:1]}")

    # 2. 全量"拆开再拼回"之后导出，字节必须和基线一致（核心断言）
    passed = _structural_no_op(attrs)
    out_data = io_tree.export_root_to_efxfile(root_obj)
    out_path, notice, fatal = operators._ensure_version_suffix(
        str(workdir / f"{stem}_structured.efx.5571972"), out_data)
    if fatal:
        report.check("导出路径能补出合法版本号后缀", False, notice or "")
        return passed
    bridge.load_efx(out_data, out_path)
    blender_out = pathlib.Path(out_path)

    report.check(
        "全量拆开再拼回之后导出，字节 == 纯 CLI 往返基线",
        blender_out.read_bytes() == cli_out.read_bytes(),
        f"{blender_out}（{blender_out.stat().st_size} 字节） != "
        f"{cli_out}（{cli_out.stat().st_size} 字节）",
    )

    # 3. 产物能读回来
    try:
        readback = bridge.dump_efx(blender_out)
        ok = int(readback.get("Header", {}).get("Version", -1)) > 0
        detail = ""
    except Exception as exc:                        # noqa: BLE001 - 门禁要把任何失败记下来
        ok, detail = False, str(exc)
    report.check("结构化过一遍的产物能被 RE-Engine-Lib 读回来", ok, detail)

    return passed


def verify_editing_operations(report: Report) -> None:
    """结构算子真的改到了 `formula`，且产物仍是桥接解析器认的语法。

    用内存里造的曲线，不依赖样本——这几条是编辑器自身的行为，和具体文件无关。
    """
    print("\n=== 结构算子")
    scene_col = bpy.context.scene.collection
    data = {"Header": {"Version": 5571972}, "Entries": [], "Actions": [], "Bones": [],
            "FieldParameterValues": [], "UvarGroups": [], "ExpressionParameters": [],
            "EffectGroups": []}
    io_tree.build_root_from_efxfile(data, scene_col, "expr_ops_probe")

    holder = bpy.data.objects.new("expr_probe", None)
    scene_col.objects.link(holder)
    holder["~TYPE"] = model.TYPE_ATTRIBUTE
    holder.efx_is_expression_attribute = True
    curve = holder.efx_expression_curves.add()
    curve.formula = "Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"
    expr_edit.rebuild_rows(curve)
    holder.efx_expression_curves_active_index = 0

    # 7 行不是 8：`-0.5` 在建行时折成一个带符号常量（expr._collect_rows()）
    report.check("文本 -> 行：节点个数对得上", len(curve.nodes) == 7, str(len(curve.nodes)))

    # 改一个常量 -> formula 立刻跟着变（走的是 model.py 上的 update 回调）
    curve.nodes[3].value = 120.0
    report.check("改常量节点会重拼 formula",
                 curve.formula == "Lerp(Clamp(TIMER, 120, 90), -0.5, 0)", curve.formula)

    # 改变量名 -> 同上
    curve.nodes[2].name = "Speed"
    report.check("改变量节点会重拼 formula",
                 curve.formula == "Lerp(Clamp(Speed, 120, 90), -0.5, 0)", curve.formula)

    # 反方向：手打文本 -> 行跟着重建
    curve.formula = "Min(1, TIMER)"
    report.check("改 formula 文本会重建行",
                 [n.kind for n in curve.nodes] == ["CALL", "CONST", "VAR"],
                 str([n.kind for n in curve.nodes]))

    # 非法文本：报错 + 清空行，但**不动用户打的字**
    curve.formula = "Min(1, "
    report.check("非法文本不被吃掉", curve.formula == "Min(1, ", curve.formula)
    report.check("非法文本会报错并清空行",
                 bool(curve.formula_error) and len(curve.nodes) == 0,
                 f"error={curve.formula_error!r} rows={len(curve.nodes)}")

    curve.formula = "Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"
    report.check("改回合法文本后错误清掉、行恢复",
                 not curve.formula_error and len(curve.nodes) == 7,
                 f"error={curve.formula_error!r} rows={len(curve.nodes)}")

    # 三个结构算子
    bpy.context.view_layer.objects.active = holder
    # 槽位设计里「内嵌」不再是独立算子：把一个**叶子**槽位替换成函数时，原内容自动
    # 成为新函数的第一个参数（`expr.convert_node()` 对叶子的处理），这就是内嵌。
    # 下面第 2、3 条就是在验这件事，以及「删除这一层」是它的逆操作。
    cases = [
        # 表达式槽位换函数：保留原有参数（Clamp 的三个参数留给 Min 前两个）
        ("efx_re.expression_node_replace", {"node_index": 1, "target": "Min"},
         "Lerp(Min(TIMER, 180), -0.5, 0)"),
        # 叶子槽位换成取负 = 内嵌：原内容 TIMER 成了第一个（唯一的）参数
        ("efx_re.expression_node_replace", {"node_index": 2, "target": _expr.KIND_NEG},
         "Lerp(Min(-TIMER, 180), -0.5, 0)"),
        # 删除这一层 = 内嵌的逆：去掉负号、TIMER 顶回来
        ("efx_re.expression_node_delete", {"node_index": 2},
         "Lerp(Min(TIMER, 180), -0.5, 0)"),
        # 再删一次：把 Min 这一层也去掉
        ("efx_re.expression_node_delete", {"node_index": 1},
         "Lerp(TIMER, -0.5, 0)"),
    ]
    for op_id, kwargs, want in cases:
        getattr(bpy.ops.efx_re, op_id.split(".", 1)[1])(**kwargs)
        report.check(f"{op_id} {kwargs} -> {want}", curve.formula == want, curve.formula)

    # 存盘/热加载留下的"有公式、没有行"必须被自动补上——这一条是真实用户报告的回归：
    # 在这个功能存在之前导入的场景，面板上只剩一个"按文本重新解析"按钮，看起来像功能
    # 根本没做出来。load_post handler 和启用插件时的延后一遍都走 rebuild_missing_rows()。
    curve.formula = "Lerp(Clamp(TIMER, 12, 0), -1, 0)"
    with expr_edit._Suspended():
        curve.nodes.clear()          # 模拟"老 .blend 里存下来的状态"
    report.check("模拟出了'有公式没有行'的状态",
                 len(curve.nodes) == 0 and not curve.formula_error, str(len(curve.nodes)))
    fixed = expr_edit.rebuild_missing_rows()
    report.check("rebuild_missing_rows() 把空的行补回来了",
                 fixed >= 1 and len(curve.nodes) == 7,
                 f"fixed={fixed} rows={len(curve.nodes)}")
    report.check("补行不碰 formula",
                 curve.formula == "Lerp(Clamp(TIMER, 12, 0), -1, 0)", curve.formula)

    # 已经有行的不该被重建（用户可能正在编辑；而且重建会把活动行重置）
    curve.nodes_active_index = 3
    again = expr_edit.rebuild_missing_rows()
    report.check("已经有行的曲线不会被重复重建",
                 again == 0 and curve.nodes_active_index == 3,
                 f"again={again} active={curve.nodes_active_index}")

    # `@persistent` 只是给函数挂一个 `_bpy_persistent` 属性，**值是 None 不是 True**
    # （实测），所以只能 hasattr 判，不能判真假值。少了这个装饰器的后果是：第一次打开
    # .blend 还好，之后 Blender 会把非 persistent 的 handler 清空，补行就永久失效了。
    report.check("load_post handler 已挂上且是 persistent",
                 expr_edit._on_load_post in bpy.app.handlers.load_post
                 and hasattr(expr_edit._on_load_post, "_bpy_persistent"),
                 str(bpy.app.handlers.load_post))

    # 算子产物必须是桥接解析器认的语法（不是"我们自己能解析"就算数）
    error = bridge.check_expression(curve.formula)
    report.check("算子产物能过 EfxBridge exprcheck", error is None, str(error))

    # 叶子上删除是空操作（按钮在界面上本来就是灰的），不该把公式弄没
    before = curve.formula
    leaf = next(i for i, n in enumerate(curve.nodes) if n.arity == 0)
    bpy.ops.efx_re.expression_node_delete(node_index=leaf)
    report.check("叶子上删除是空操作", curve.formula == before, curve.formula)
    report.check("叶子上 can_delete_node() 为假",
                 not _expr.can_delete_node(expr_edit.read_rows(curve), leaf))

    # 槽位视角：界面就是按这几个函数画的（一行一个节点 + 它的全部槽位）
    curve.formula = "Lerp(Clamp(TIMER, 12, 0), 190, -30)"
    expr_edit.rebuild_rows(curve)
    srows = expr_edit.read_rows(curve)
    report.check("根节点的槽位是 [Clamp, 190, -30]",
                 [_expr.node_summary(srows, i)
                  for i in _expr.child_indices(srows, 0)] == ["Clamp", "190", "-30"],
                 str([_expr.node_summary(srows, i)
                      for i in _expr.child_indices(srows, 0)]))
    report.check("Clamp 的槽位是 [TIMER, 12, 0]",
                 [_expr.node_summary(srows, i)
                  for i in _expr.child_indices(srows, 1)] == ["TIMER", "12", "0"],
                 str([_expr.node_summary(srows, i)
                      for i in _expr.child_indices(srows, 1)]))
    report.check("从 TIMER 回根的链是 [0, 1, 2]（界面就画这三行）",
                 _expr.path_to_root(srows, 2) == [0, 1, 2],
                 str(_expr.path_to_root(srows, 2)))
    report.check("从 -30 回根的链是 [0, 6]",
                 _expr.path_to_root(srows, 6) == [0, 6], str(_expr.path_to_root(srows, 6)))

    # 参数角色名：只有语义已定的两个函数有，其余留空（铁律 #7）
    curve.formula = "Lerp(Clamp(TIMER, 12, 0), 190, -30)"
    roles = _expr.arg_roles(expr_edit.read_rows(curve))
    # 7 行：`-30` 在建行时就折成一个带符号常量，角色名直接落在它身上
    report.check("Clamp/Lerp 的参数角色名标出来了",
                 roles == ["", "t", "value", "hi", "lo", "to", "from"], str(roles))
    curve.formula = "Unary10(TIMER)"
    report.check("语义未确认的函数不编参数名",
                 all(r == "" for r in _expr.arg_roles(expr_edit.read_rows(curve))))
    curve.formula = "Lerp(Clamp(TIMER, 12, 0), 190, -30)"


def main() -> int:
    opts = _parse_args(_script_args())

    if "dll" in opts:
        bridge._DEFAULT_DLL = pathlib.Path(opts["dll"])
    try:
        print(f"EfxBridge: {bridge.get_bridge_dll()}")
    except bridge.BridgeError as ex:
        print(f"[ERROR] {ex}")
        return 1

    diag = pathlib.Path(opts.get("diag", _REPO_ROOT / "diag"))
    samples = sorted(diag.glob("*.orig"))
    if not samples:
        print(f"[ERROR] {diag} 下没有 *.orig 样本。diag/ 是 untracked 的游戏资产（见 .gitignore），"
              "需要自己放一份原始 .efx 并以 .orig 结尾，或用 --diag 指到别处。")
        return 1

    workdir = pathlib.Path(opts["out"]) if "out" in opts else pathlib.Path(
        tempfile.mkdtemp(prefix="efx_expr_edit_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"样本目录: {diag}\n输出目录: {workdir}（跑完不删，失败时拿去 hexdump 对比）")

    blender_efx_re.register()

    report = Report()
    total_curves = 0
    kinds_seen = set()
    for orig in samples:
        total_curves += verify_sample(orig, workdir, report, kinds_seen)
    verify_editing_operations(report)

    # 样本覆盖到哪些节点种类。**不是失败条件**（用户的 diag/ 里有什么不归这个脚本管），
    # 但"某一类节点这批样本一条都没有"必须说出来——否则针对那一类的回归在这儿是隐形的。
    all_kinds = {"CONST", "VAR", "NEG", "CALL"}
    print("\n=== 样本覆盖到的节点种类: " + ", ".join(sorted(kinds_seen) or ["（无）"]))
    for kind in sorted(all_kinds - kinds_seen):
        print(f"  [NOTE] 样本里没有 {kind} 节点——这一类只由下面「结构算子」那一节"
              f"（内存里造的公式）覆盖。想让样本层也测到，往 diag/ 放一个带这类节点的 .orig。")

    if total_curves == 0:
        # 找不到可测的东西要报错，不静默全绿（同"找不到样本退 1"的理由）
        print(f"\n[ERROR] {len(samples)} 个样本里一条 Expression 公式都没有，这条门禁等于没跑。"
              "换一个带 IExpressionAttribute 的样本（diag/11_guide_006.efx.5571972.orig 就有）。")
        return 1
    print(f"\n过了 {total_curves} 条公式")

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # `blender --background --python x.py` 在脚本抛未捕获异常时退出码仍然是 0（实测），
    # "崩在第一行"和"全过"对调用方长得一模一样，所以自己兜一层（验证纪律 #11）。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:                            # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
