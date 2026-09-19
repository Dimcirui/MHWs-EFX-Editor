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
   逐字节相同"，不是"和原文件相同"（验证纪律）。

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

按验证纪律，五种注入都实测过会让这条门禁退 1（都注在 `efx_sim/expr.py` 的
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
仍是 0（实测），所以入口自己加一层捕获，见文件末尾。
"""

from __future__ import annotations

import json
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
from blender_efx_re import bridge, expr_edit, io_tree, model, operators, semantics, transform3d_view  # noqa: E402
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

    # 纯 CLI 往返基线：完全不经过 Blender 对象树（验证纪律）
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
    curve.formula = "Lerp(SmoothStep(TIMER, 180, 90), -0.5, 0)"
    expr_edit.rebuild_rows(curve)
    holder.efx_expression_curves_active_index = 0

    # 7 行不是 8：`-0.5` 在建行时折成一个带符号常量（expr._collect_rows()）
    report.check("文本 -> 行：节点个数对得上", len(curve.nodes) == 7, str(len(curve.nodes)))

    # 改一个常量 -> formula 立刻跟着变（走的是 model.py 上的 update 回调）
    curve.nodes[3].value = 120.0
    report.check("改常量节点会重拼 formula",
                 curve.formula == "Lerp(SmoothStep(TIMER, 120, 90), -0.5, 0)", curve.formula)

    # 改变量名 -> 同上
    curve.nodes[2].name = "Speed"
    report.check("改变量节点会重拼 formula",
                 curve.formula == "Lerp(SmoothStep(Speed, 120, 90), -0.5, 0)", curve.formula)

    # 反方向：手打文本 -> 行跟着重建
    curve.formula = "(1 - TIMER)"
    report.check("改 formula 文本会重建行",
                 [n.kind for n in curve.nodes] == ["CALL", "CONST", "VAR"],
                 str([n.kind for n in curve.nodes]))

    # 非法文本：报错 + 清空行，但**不动用户打的字**
    curve.formula = "Min(1, "
    report.check("非法文本不被吃掉", curve.formula == "Min(1, ", curve.formula)
    report.check("非法文本会报错并清空行",
                 bool(curve.formula_error) and len(curve.nodes) == 0,
                 f"error={curve.formula_error!r} rows={len(curve.nodes)}")

    curve.formula = "Lerp(SmoothStep(TIMER, 180, 90), -0.5, 0)"
    report.check("改回合法文本后错误清掉、行恢复",
                 not curve.formula_error and len(curve.nodes) == 7,
                 f"error={curve.formula_error!r} rows={len(curve.nodes)}")

    # 三个结构算子
    bpy.context.view_layer.objects.active = holder
    # 槽位设计里「内嵌」不再是独立算子：把一个**叶子**槽位替换成函数时，原内容自动
    # 成为新函数的第一个参数（`expr.convert_node()` 对叶子的处理），这就是内嵌。
    # 下面第 2、3 条就是在验这件事，以及「删除这一层」是它的逆操作。
    cases = [
        # 表达式槽位换函数：保留原有参数（SmoothStep 的三个参数留给 `-` 前两个）
        ("efx_re.expression_node_replace", {"node_index": 1, "target": "-"},
         "Lerp((TIMER - 180), -0.5, 0)"),
        # 叶子槽位换成取负 = 内嵌：原内容 TIMER 成了第一个（唯一的）参数
        ("efx_re.expression_node_replace", {"node_index": 2, "target": _expr.KIND_NEG},
         "Lerp((-TIMER - 180), -0.5, 0)"),
        # 删除这一层 = 内嵌的逆：去掉负号、TIMER 顶回来
        ("efx_re.expression_node_delete", {"node_index": 2},
         "Lerp((TIMER - 180), -0.5, 0)"),
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
    curve.formula = "Lerp(SmoothStep(TIMER, 12, 0), -1, 0)"
    with expr_edit._Suspended():
        curve.nodes.clear()          # 模拟"老 .blend 里存下来的状态"
    report.check("模拟出了'有公式没有行'的状态",
                 len(curve.nodes) == 0 and not curve.formula_error, str(len(curve.nodes)))
    fixed = expr_edit.rebuild_missing_rows()
    report.check("rebuild_missing_rows() 把空的行补回来了",
                 fixed >= 1 and len(curve.nodes) == 7,
                 f"fixed={fixed} rows={len(curve.nodes)}")
    report.check("补行不碰 formula",
                 curve.formula == "Lerp(SmoothStep(TIMER, 12, 0), -1, 0)", curve.formula)

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
    curve.formula = "Lerp(SmoothStep(TIMER, 12, 0), 190, -30)"
    expr_edit.rebuild_rows(curve)

    # `Mod(a, b)` 的函数写法（规范记法唯一没有中缀孪生兄弟的那个操作码）
    curve.formula_canonical = "Mod(3 * TIMER, TIMER)"
    report.check("规范记法认 Mod(a, b) 的函数写法",
                 curve.formula == "Mod(TIMER, (3 * TIMER))", curve.formula)
    report.check("Mod 读回来发的是 % 运算符，不是别名",
                 curve.formula_canonical == "3 * TIMER % TIMER", curve.formula_canonical)

    # 未知变量：求值成 0、公式看起来仍然合理，必须在公式框旁边报出来
    curve.formula = "(Cos((60 + TIMER)) / Sin(((60 + TIMER) * (2 + pi))))"
    expr_edit.rebuild_rows(curve)
    unknown = expr_edit.unknown_variable_names(bpy.context, curve)
    report.check("小写 pi 被认出是未知变量", unknown == ["pi"], str(unknown))
    curve.formula = "(Cos((60 + TIMER)) / Sin(((60 + TIMER) * (2 + PI))))"
    expr_edit.rebuild_rows(curve)
    report.check("大写 PI 是内置外部变量、不报",
                 expr_edit.unknown_variable_names(bpy.context, curve) == [],
                 str(expr_edit.unknown_variable_names(bpy.context, curve)))
    curve.formula = "Sin(ext:302732036)"
    expr_edit.rebuild_rows(curve)
    report.check("ext:<hash> 占位不算拼错",
                 expr_edit.unknown_variable_names(bpy.context, curve) == [],
                 str(expr_edit.unknown_variable_names(bpy.context, curve)))

    # ⚠ 还原：后面的检查共用这条曲线，留着上面的探针公式会让它们全体假红
    curve.formula = "Lerp(SmoothStep(TIMER, 12, 0), 190, -30)"
    expr_edit.rebuild_rows(curve)
    srows = expr_edit.read_rows(curve)
    # 函数槽位显示的是**规范名**（`Clamp` 其实是 smoothstep 重映射），行数据里存的还是
    # vendor 字面量 —— 下面紧跟着一条就是查这个，两者混起来会把"显示层改名"
    # 和"文本被改坏"看成同一件事。
    report.check("根节点的槽位是 [SmoothStep, 190, -30]",
                 [_expr.node_summary(srows, i)
                  for i in _expr.child_indices(srows, 0)] == ["SmoothStep", "190", "-30"],
                 str([_expr.node_summary(srows, i)
                      for i in _expr.child_indices(srows, 0)]))
    report.check("显示改名不碰公式文本",
                 curve.formula == "Lerp(SmoothStep(TIMER, 12, 0), 190, -30)", curve.formula)
    report.check("SmoothStep 的槽位是 [TIMER, 12, 0]",
                 [_expr.node_summary(srows, i)
                  for i in _expr.child_indices(srows, 1)] == ["TIMER", "12", "0"],
                 str([_expr.node_summary(srows, i)
                      for i in _expr.child_indices(srows, 1)]))
    report.check("从 TIMER 回根的链是 [0, 1, 2]（界面就画这三行）",
                 _expr.path_to_root(srows, 2) == [0, 1, 2],
                 str(_expr.path_to_root(srows, 2)))
    report.check("从 -30 回根的链是 [0, 6]",
                 _expr.path_to_root(srows, 6) == [0, 6], str(_expr.path_to_root(srows, 6)))

    # 参数角色名：只有语义已定的两个函数有，其余留空（不把猜测当事实）
    curve.formula = "Lerp(SmoothStep(TIMER, 12, 0), 190, -30)"
    roles = _expr.arg_roles(expr_edit.read_rows(curve))
    # 7 行：`-30` 在建行时就折成一个带符号常量，角色名直接落在它身上
    report.check("Clamp/Lerp 的参数角色名标出来了",
                 roles == ["", "t", "value", "hi", "lo", "to", "from"], str(roles))
    curve.formula = "Saturate(TIMER)"
    report.check("语义未确认的函数不编参数名",
                 all(r == "" for r in _expr.arg_roles(expr_edit.read_rows(curve))))
    curve.formula = "Lerp(SmoothStep(TIMER, 12, 0), 190, -30)"
    verify_canonical_notation(report, curve)


def verify_canonical_notation(report: Report, curve) -> None:
    """公式面板上那条"规范记法"栏（`EFXExpressionCurveItem.formula_canonical`）。

    它是 **RNA get/set 派生属性**，所以纯 Python 单测碰不到这条路——
    `efx_sim/expr_text.py` 那层由 `tests/test_sim_expr_text.py` 覆盖，这里测的是
    "接进 Blender 属性之后还对不对"：读得出、写得回、写进去之后行视图跟着重建、
    以及**坏输入不许动 `formula`**（铁律 #1）。
    """
    print("\n=== 规范记法栏")
    from efx_sim import expr_text

    curve.formula = "((40 / TIMER) - 1)"
    expr_edit.rebuild_rows(curve)
    report.check("vendor 文本读成规范记法",
                 curve.formula_canonical == "1 - TIMER / 40", curve.formula_canonical)

    # 按真实语义写进去 -> `formula` 变成 vendor 记法，行视图跟着重建
    curve.formula_canonical = "1 - TIMER / 30"
    report.check("按规范记法写回去，formula 是 vendor 记法",
                 curve.formula == "((30 / TIMER) - 1)", curve.formula)
    report.check("写规范记法之后行视图跟着重建", len(curve.nodes) == 5, str(len(curve.nodes)))
    report.check("再读回来还是同一串", curve.formula_canonical == "1 - TIMER / 30",
                 curve.formula_canonical)

    # 用户当初踩的那一脚：把规范记法原样打进 vendor 那一栏，读出来必须**不是**同一个式子
    curve.formula = "((60 / TIMER) - 1)"
    report.check("两套记法确实不同（同一串文本两边含义不一样）",
                 curve.formula_canonical != "(1 + (TIMER * 60))", curve.formula_canonical)

    # 坏输入：不许静默改掉 formula
    curve.formula = "((40 + TIMER) / 1)"
    before = curve.formula
    curve.formula_canonical = "1 - / TIMER"
    report.check("规范记法写坏了不动 formula", curve.formula == before, curve.formula)
    report.check("坏输入会留下错误说明", bool(curve.formula_error), curve.formula_error)

    # `formula` 解析不了时，规范栏返回空串而不是抛异常（面板每帧都会读它）
    curve.formula = "Min(40 - TIMER"
    report.check("formula 本身坏掉时规范栏不抛异常、返回空串",
                 curve.formula_canonical == "", repr(curve.formula_canonical))

    # 树视图的符号必须和上面那条规范文本同一套（否则又回到"两边对不上"）。
    # a96e1d9 之后 `*` / `+` 两边同形，能看出差别的是 `Mod` -> `%` 和 `PowOp` -> `**`。
    curve.formula = "PowOp(2, Mod(TIMER, 3))"
    expr_edit.rebuild_rows(curve)
    rows = expr_edit.read_rows(curve)
    heads = [_expr.node_summary(rows, i) for i in range(len(rows))]
    report.check("树里的中缀符号是规范符号（`PowOp` 画成 `**`、`Mod` 画成 `%`）",
                 heads[0] == "**" and "%" in heads, str(heads))

    # 中转层和 `efx_sim` 只能有一张表，漂了就会静默两套读法
    report.check("中转表就是 expr.CANONICAL_OPERATORS 那一张",
                 expr_text._VENDOR_TO_CANONICAL == dict(_expr.CANONICAL_OPERATORS))

    curve.formula = "Lerp(SmoothStep(TIMER, 12, 0), 190, -30)"
    expr_edit.rebuild_rows(curve)


def verify_tree_parameters(report: Report) -> None:
    """公式树的参数表（`EFXExpressionTree.parameters`）必须原样透传。

    ## 它防的是什么

    公式文本里一个普通标识符是"引擎运行时喂的外部变量"还是"值存在文件里的具名常量"，
    **文本上完全看不出来**——两者都写成那个名字。真相只在这张表的 `source`
    （0=Parameter / 1=Constant / 2=External）和 `constantValue` 上。

    导出侧原来写死 `"parameters": []`，后果实测过：导入用了 `PI` 的官方特效再导出，
    `source` 从 1(Constant) 退成 2(External)、值从 3.1415927 变成 0，游戏里那段效果
    静默改掉（铁律 #1）。

    ⚠ **逐字节往返门禁对它免疫**——`diag/` 的样本里一个 `PI` 都没有，"门禁没测到东西
    也会全绿"。所以这里**自己造**一条带 Constant 参数的公式，不依赖样本里恰好有。
    """
    print("\n=== 公式树的参数表")
    scene_col = bpy.context.scene.collection
    PI_HASH, PI_VALUE = 4068760923, 3.1415927
    # ⚠ 大小写两个键都要给：导入侧读大写 `Expression`（`_populate_expression_attribute()`），
    #   只给小写的话一条曲线都建不出来，而 opaque 透传又会让检查"看起来过了"。
    tree = {"version": 5571972, "expressions": [], "parsedExpressions": [{
        "expression": "Sin(Mod(PI, SmoothStep(TIMER, 30, 0)))",
        "parameters": [
            {"parameterNameHash": 2589222962, "constantValue": 0.0, "source": 2},
            {"parameterNameHash": PI_HASH, "constantValue": PI_VALUE, "source": 1},
        ]}]}
    bits = {"bitCount": 8, "bits": [2], "bitNames": None}
    attr = {
        "$type": "ReeLib.Efx.Structs.Misc.EFXAttributeNoiseExpression",
        "Version": 5571972, "UniqueID": 0, "IsTypeAttribute": False, "type": 0,
        "Expression": tree, "expressions": tree,
        "ExpressionBits": bits, "expressionBits": bits,
    }
    data = {"Header": {"Version": 5571972},
            "Entries": [{"name": "e0", "index": 0, "Attributes": [attr]}],
            "Actions": [], "Bones": [], "FieldParameterValues": [], "UvarGroups": [],
            "ExpressionParameters": [], "EffectGroups": []}
    root = io_tree.build_root_from_efxfile(data, scene_col, "tree_param_probe")

    def same(entries, want_source, want_value):
        """float32 存储会把 3.1415927 变成 3.1415927410125732，比较必须带容差。"""
        return (len(entries) == 1 and entries[0][0] == want_source
                and abs(entries[0][1] - want_value) < 1e-6)

    def pi_entries(blob):
        found = []
        def walk(o):
            if isinstance(o, dict):
                if "expression" in o:
                    for entry in (o.get("parameters") or []):
                        if entry.get("parameterNameHash") == PI_HASH:
                            found.append((entry.get("source"), entry.get("constantValue")))
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(blob)
        return found

    out = io_tree.export_root_to_efxfile(root)
    got = pi_entries(out)
    report.check("导入再导出，PI 仍是 Constant=3.1415927（不写死空数组）",
                 same(got, 1, PI_VALUE), str(got))

    # 用户新打一个 `PI`：表里本来没有，要靠 expr.NAMED_CONSTANTS 补出常量条目，
    # 否则解析器按名字回退成 External、实机读成 0（用户实测踩过）
    curve = None
    for obj in bpy.data.objects:
        for c in getattr(obj, "efx_expression_curves", []):
            if "PI" in c.formula:
                curve = c
                break
        if curve: break
    if curve is None:
        report.check("找得到那条 PI 公式", False, "没找到")
        return
    curve.tree_parameters = "[]"          # 模拟"新打的公式，表里什么都没有"
    out2 = io_tree.export_root_to_efxfile(root)
    got2 = pi_entries(out2)
    report.check("新打的 PI 也会补出 Constant 条目",
                 same(got2, 1, PI_VALUE), str(got2))

    # 表里已经有的不许被覆盖：文件里写的值优先于我们的默认值
    curve.tree_parameters = json.dumps(
        [{"parameterNameHash": PI_HASH, "constantValue": 2.5, "source": 1}])
    got3 = pi_entries(io_tree.export_root_to_efxfile(root))
    report.check("文件里已有的值不被默认值覆盖", same(got3, 1, 2.5), str(got3))

    # 公式里没引用的具名常量不许硬塞进去
    curve.tree_parameters = "[]"
    curve.formula = "SmoothStep(TIMER, 30, 0)"
    expr_edit.rebuild_rows(curve)
    got4 = pi_entries(io_tree.export_root_to_efxfile(root))
    report.check("公式没引用就不补条目", got4 == [], str(got4))

def verify_bit_field_positional_matching(report: Report) -> None:
    """`model.expression_bit_index_for_field()` 按**声明顺序**匹配 bit，不比较名字——
    见 docs/EXPRESSION_SEMANTICS.md §7.1c。用真实类型 `EFXAttributeRgbCommonExpression`
    （`EfxMiscStructs.cs:681`）复现：`BitNameDict` 给 bit0/2/3/5/7/8/9 起的友好名字
    （`GreenChColor`/`GreenChIntensity`/…）和这些 bit 真正对应的 C# 字段名
    （`particleColor`/`colorIntensityGreen`/…）完全不一样，旧版按名字反查
    `mhws_bit_names.json` 会在这几个字段上失败（面板上字段那一行的 [+] 不出现，
    即使 bit 真实存在）。

    不需要真实 .efx 样本——这是纯类型元数据层面的问题，内存里造一个只含
    `expressionBits`/`expressions`/`expressionBits` 三个必需键的最小 dict 就够触发
    `is_expression_attribute_dict()`，其余字段走通用树也不影响这条检查。
    """
    print("\n=== bit-字段位置匹配（不认 BitNameDict 的友好名字）")
    scene_col = bpy.context.scene.collection
    tree = {"version": 5571972, "expressions": [], "parsedExpressions": []}
    bits = {"bitCount": 22, "bits": [], "bitNames": None}
    attr = {
        "$type": "ReeLib.Efx.Structs.Misc.EFXAttributeRgbCommonExpression",
        "Version": 5571972, "UniqueID": 0, "IsTypeAttribute": False, "type": 0,
        "Expression": tree, "expressions": tree,
        "ExpressionBits": bits, "expressionBits": bits,
    }
    data = {"Header": {"Version": 5571972},
            "Entries": [{"name": "e0", "index": 0, "Attributes": [attr]}],
            "Actions": [], "Bones": [], "FieldParameterValues": [], "UvarGroups": [],
            "ExpressionParameters": [], "EffectGroups": []}
    root = io_tree.build_root_from_efxfile(data, scene_col, "bit_field_probe")
    obj = next(
        o for o in bpy.data.objects
        if o.get("~TYPE") == model.TYPE_ATTRIBUTE
        and o.efx_attr_type.endswith("EFXAttributeRgbCommonExpression")
    )
    attr_type = obj.efx_attr_type

    # 7 个"友好名字 != 字段名"的字段，声明顺序里的下标是已知的（见 docstring）
    want = {
        "particleColor": 0, "colorIntensityGreen": 2, "colorSaturate": 3,
        "particleColor2": 5, "colorIntensityRed": 7, "alpha1": 8, "alpha2": 9,
    }
    got = {name: model.expression_bit_index_for_field(attr_type, name) for name in want}
    report.check(
        "7 个友好名字被覆盖的字段，按声明顺序都能正确反查到 bit",
        got == want, f"{got} != {want}",
    )

    # 旧实现（按名字去 mhws_bit_names.json 反查）在这 7 个字段上必须失败——用来确认这条
    # 检查真的是在测"新旧两种匹配方式的差异"，不是凑巧一直都对（验证纪律：新回归防护
    # 必须证明把 bug 注回去会 FAIL）。
    old_names = semantics.get_expression_bit_names(attr_type)
    old_would_find = {name: (name in old_names) for name in want}
    report.check(
        "旧的按名字匹配方式确实找不到这 7 个字段（证明这条检查测的是真问题）",
        not any(old_would_find.values()), str(old_would_find),
    )

    # 没有名字冲突的普通字段（unkn2 本身就没被 BitNameDict 覆盖）新旧两种方式结果一致，
    # 确认这次改动没有把简单情况改坏。
    report.check(
        "没有被 BitNameDict 覆盖的字段（unkn2）新旧匹配方式结果一致",
        model.expression_bit_index_for_field(attr_type, "unkn2") == 1
        and old_names.index("unkn2") == 1,
    )


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
    verify_tree_parameters(report)
    verify_bit_field_positional_matching(report)

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
    # "崩在第一行"和"全过"对调用方长得一模一样，所以自己加一层捕获（验证纪律）。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:                            # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
