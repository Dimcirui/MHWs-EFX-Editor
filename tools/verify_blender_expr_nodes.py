# -*- coding: utf-8 -*-
"""
tools/verify_blender_expr_nodes.py —— Expression 节点视口的回归防护

必须在 Blender 里跑（要真 bpy：`NodeTree` / `Node` / `NodeSocket` 注册、连线、
`update()` 回调），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_expr_nodes.py

可选参数放在 `--` 之后：`--diag <样本目录>`（默认 `<仓库根>/diag`，收 `*.orig`）、
`--out <输出目录>`、`--dll <EfxBridge.dll>`，含义同 `verify_blender_roundtrip.py`。

为什么单独一条门禁
------------------
`verify_blender_expression_edit.py` 走的是**行视图**那条路（`formula` -> 行 -> `formula`），
节点图这条路它一步都走不到：行 -> 节点+连线 -> 行 这一段是全新的，而且中间多了两个
行视图没有的东西——**插槽的显示顺序**（规范记法下六个操作码里四个操作数顺序是反的）和
**叶子存在插槽上而不是独立节点上**。这两处各自都能单独错，而且都错得很隐蔽。

⚠ **这里的核心判据不是"图能画出来"，是往返恒等 + 独立对拍。**
`build_graph` 和 `read_graph` 共用 `expr_text.display_arg_order()` 这一张顺序表，
所以"摆错顺序"这种错误是**双向一致**的：建图时按错的顺序摆、读回时按同样错的顺序读，
`formula` 一个字符都不会变，逐字节门禁、文本重拼门禁、往返恒等**会一起绿**（CLAUDE.md
验证纪律最后那条）。所以检查项 3 专门**不走 `display_arg_order()`**，改用一条独立的
路径对拍：拿 `expr_text.rows_to_canonical()`（规范记法文本，另一套代码）解析出来的
运算符/操作数顺序，和图上插槽实际摆的顺序逐个比。

检查项
------
1. 每条公式：`行 -> 图 -> 行` 恒等（行列表逐字段相同），且从图重拼的文本 == 原文本；
2. 全量"过一遍节点图"之后导出，字节 == 纯 CLI 往返基线（判据是 CLI 往返产物，
   不是原文件——验证纪律）；
3. **独立对拍**：图上第一层插槽的摆放顺序，和规范记法文本里那一层的操作数顺序一致
   （不共用 `display_arg_order()`，见上面那段）；
4. 叶子真的在插槽上：图里的节点数 == 行里 arity>0 的行数（叶子一个节点都不该造）；
5. 编辑能力：改插槽常量 / 改插槽变量名 / 换节点函数 / 断开连线退回叶子 / 重新连线，
   五种都真的改到了 `formula`，且改完仍能被桥接的解析器接受；
6. 非法形状被**拒绝**且 `formula` 不变：一个输出接两个插槽（DAG）、连线成环；
7. 样本里没有任何 Expression attribute 时**报错退 1**，不静默全绿。

按验证纪律，每一条防护都实测过"把 bug 注回去会 FAIL"，注入点和红点分布见
`_INJECTION_MATRIX`（跑的时候会打印出来，改这个文件之前先照着重跑一遍）。

退出码：全绿 0，有失败 1。⚠ `blender --background --python` 在脚本抛未捕获异常时退出码
仍是 0（实测），所以入口自己加一层捕获，见文件末尾。
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
from blender_efx_re import (  # noqa: E402
    bridge, expr_edit, expr_nodes, io_tree, model, operators, transform3d_view,
)
from efx_sim import expr as _expr, expr_text as _expr_text  # noqa: E402


#: 注入 -> 预期红点。**改这个文件之前照着重跑一遍**：只看它绿不算回归防护
#: （CLAUDE.md 验证纪律第三条）。
_INJECTION_MATRIX = """\n| # | 注入                                                    | 1 往返 | 2 字节 | 3 对拍 | 4 叶子 | 5 编辑 | 6 拒绝 |
|---|---------------------------------------------------------|--------|--------|--------|--------|--------|--------|
| 1 | `display_arg_order()` 对二元操作码一律不 swap            | 绿     | 绿     | **红** | 绿     | 绿     | 绿     |
| 2 | `_build_into()` 按 vendor 顺序摆插槽（跳过 order 映射）  | **红** | **红** | **红** | 绿     | **红** | 绿     |
| 3 | `_emit_node()` 读回时不按 order 还原                     | **红** | **红** | 绿     | 绿     | **红** | 绿     |
| 4 | 叶子额外造一个独立节点                                   | 绿     | 绿     | 绿     | **红** | 绿     | 绿     |
| 5 | `_emit_node()` 去掉 `seen`（允许 DAG）                   | 绿     | 绿     | 绿     | 绿     | 绿     | **红** |
| 6 | `rebuild_sockets()` 参数变少时不裁插槽                   | 绿     | 绿     | 绿     | 绿     | **红** | 绿     |

六条全部实测过，每条都 exit=1 且有具名 FAIL 行。**这是测出来的，不是推出来的**，
改代码之后重跑一遍才算数。三处反直觉的地方，别凭直觉改回去：

- **第 1 行只有对拍红。** 建图和读回共用同一张顺序表，一起错 -> 往返恒等、文本重拼、
  逐字节**全绿**。这就是这条门禁存在的理由（CLAUDE.md 验证纪律最后那条的又一个实例），
  也是检查项 3 必须绕开 `display_arg_order()` 自己算一遍的原因。
- **第 3 行对拍反而绿。** 只坏读回那一侧时，检查项 3 用来给插槽认领子树的规范文本
  自己也被搅乱了，认不出来就跳过（`count(text) != 1` -> None）。它由往返和字节兜住。
- **第 2/3 行的字节红是有条件的**：`verify_sample()` 必须把读回的行 `apply_rows()`
  写回曲线，导出才会真的经过节点图这条路。写回之前这两行的字节是**绿**的（实测），
  那时候这条判据是空跑。"""


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


# ---------------------------------------------------------------------------
# 定位
# ---------------------------------------------------------------------------

def _root_of(obj):
    for col in obj.users_collection:
        cursor = col
        while cursor is not None:
            if cursor.get("~TYPE") == model.TYPE_ROOT:
                return cursor
            cursor = next((c for c in bpy.data.collections
                           if cursor.name in c.children), None)
    return None


def _expression_attributes(root_obj):
    return [
        obj for obj in bpy.data.objects
        if obj.get("~TYPE") == model.TYPE_ATTRIBUTE
        and getattr(obj, "efx_is_expression_attribute", False)
        and _root_of(obj) is root_obj
    ]


def _rows_equal(a, b) -> bool:
    """行列表逐字段比。`value` 用精确相等——公式文本的浮点是 F6 定点，
    建图/读回**不该**引入任何数值误差；容差会把"插槽存成 float32 掉精度"这类
    真实回归放过去。"""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if (x["kind"], x["arity"], x["name"]) != (y["kind"], y["arity"], y["name"]):
            return False
        if x["kind"] == _expr.KIND_CONST and float(x["value"]) != float(y["value"]):
            return False
    return True


def _graph_roundtrip(tree, obj, curve_index):
    """把一条公式过一遍节点图，返回 (原行, 读回的行)。这正是用户打开节点编辑器、
    什么都不改就关掉时走的那条路。

    ⚠ 写回（`apply_rows`）是**调用方**在做完图上的检查之后才调的，不在这里：
    `apply_rows` 会经 `ON_ROWS_CHANGED` 触发 `build_graph()` 把图整个重建一遍，
    之后再去看"插槽是怎么摆的"，看到的已经是**按新公式重建出来的图**，不是当初
    从原公式建出来那张——实测过，顺序对拍会因此漏掉「建图时按 vendor 顺序摆」那个注入。
    """
    expr_nodes.bind(tree, obj, curve_index)
    expr_nodes.build_graph(tree, bpy.context)
    curve = obj.efx_expression_curves[curve_index]
    before = expr_edit.read_rows(curve)
    after = expr_nodes.read_graph(tree)
    return before, after


# ---------------------------------------------------------------------------
# 检查项 3：独立对拍（**不共用 display_arg_order()**）
# ---------------------------------------------------------------------------

def _canonical_operand_order(rows):
    """根节点在**规范记法**下的操作数顺序：返回 `[vendor 参数下标, ...]`，
    第 i 项是"规范文本里第 i 个操作数"对应的 vendor 参数下标。

    实现上刻意绕开 `expr_text.display_arg_order()`——那是被测代码。这里改用
    `rows_to_canonical()` 生成整条规范文本，再把每个子树各自的规范文本拿出来，
    按它们在根的规范文本里**出现的先后**排序。两条路径唯一共享的只有
    `rows_to_canonical()` 本身，而它有 `tests/test_sim_expr_text.py` 的独立覆盖。

    根不是调用、或者子树规范文本有重复（分不出先后）时返回 None，调用方跳过。
    """
    if not rows or int(rows[0].get("arity", 0)) == 0:
        return None
    arity = int(rows[0]["arity"])
    whole = _expr_text.rows_to_canonical(rows)
    positions = []
    for vendor_pos in range(arity):
        child = _expr.subtree_rows(rows, _child_index(rows, vendor_pos))
        text = _expr_text.rows_to_canonical(child)
        if whole.count(text) != 1:
            return None                 # 两个子树长得一样，定不出先后
        positions.append((whole.index(text), vendor_pos))
    positions.sort()
    return [vendor_pos for _at, vendor_pos in positions]


def _child_index(rows, nth):
    return _expr.child_indices(rows, 0)[nth]


def _graph_socket_order(tree, rows):
    """图上根节点的插槽实际摆放顺序，同样表示成 `[vendor 参数下标, ...]`。

    做法是把每个插槽背后的子树读回成行、再转成规范文本，然后和 `rows` 里各个
    vendor 参数的规范文本对上号——**读的是图的实际形状**，不问 `display_arg_order()`。
    """
    output = next((n for n in tree.nodes if n.bl_idname == expr_nodes._OUTPUT_NODE_ID), None)
    root = expr_nodes._source_node(output.inputs[0]) if output else None
    if root is None:
        return None
    arity = int(rows[0]["arity"])
    if len(root.inputs) != arity:
        return None
    vendor_texts = []
    for vendor_pos in range(arity):
        child = _expr.subtree_rows(rows, _child_index(rows, vendor_pos))
        vendor_texts.append(_expr_text.rows_to_canonical(child))
    order = []
    for socket in root.inputs:
        sub = []
        expr_nodes._emit_socket(socket, sub, frozenset(), set())
        text = _expr_text.rows_to_canonical(_expr.recompute_depths(sub))
        if vendor_texts.count(text) != 1:
            return None
        order.append(vendor_texts.index(text))
    return order


# ---------------------------------------------------------------------------
# 样本层
# ---------------------------------------------------------------------------

def verify_sample(orig: pathlib.Path, workdir: pathlib.Path, report: Report,
                  stats: dict) -> int:
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
    pairs = [(o, i) for o in attrs for i in range(len(o.efx_expression_curves))]
    print(f"  Expression attribute {len(attrs)} 个，公式 {len(pairs)} 条")

    tree = expr_nodes.get_tree(create=True)

    bad_roundtrip, bad_text, bad_order, bad_leaf, skipped_order = [], [], [], [], 0
    crashed = []
    for obj, index in pairs:
        curve = obj.efx_expression_curves[index]
        if curve.formula_error or not curve.nodes:
            continue
        # 一条公式把建图/读回搞崩了，不该连带让整条门禁只剩一个 traceback、
        # 一行 PASS/FAIL 都没有（实测：`rebuild_sockets()` 不裁插槽那个注入就是这样，
        # 退出码虽然是 1，但输出里看不出是哪一项坏了）。逐条捕获，记成一个具名 FAIL。
        # ⚠ 原文本要在过节点图**之前**存下来：`_graph_roundtrip()` 会把读回的行写回
        # 曲线（字节判据需要），写回之后再拿 `curve.formula` 当基准，这条检查就变成
        # 自己和自己比、永远绿。
        original = curve.formula
        try:
            before, after = _graph_roundtrip(tree, obj, index)
        except Exception as exc:                        # noqa: BLE001
            crashed.append((original, f"{type(exc).__name__}: {exc}"))
            continue

        # 1. 行 -> 图 -> 行 恒等 + 文本恒等
        if not _rows_equal(before, after):
            bad_roundtrip.append(original)
        text = _expr.from_rows(after, curve.second_branch or None)
        if text != original:
            bad_text.append((original, text))

        # 4. 叶子在插槽上，不该造成节点
        call_rows = sum(1 for r in before if int(r.get("arity", 0)) > 0)
        graph_calls = sum(1 for n in tree.nodes
                          if n.bl_idname == expr_nodes._CALL_NODE_ID)
        if graph_calls != call_rows:
            bad_leaf.append((original, graph_calls, call_rows))
        stats["calls"] = max(stats["calls"], graph_calls)

        # 3. 独立对拍：插槽摆放顺序 vs 规范记法里的操作数顺序
        expected = _canonical_operand_order(before)
        actual = _graph_socket_order(tree, before)
        if expected is None or actual is None:
            skipped_order += 1
        else:
            stats["order_checked"] += 1
            if int(before[0].get("arity", 0)) == 2 and before[0]["name"] in _expr.CANONICAL_OPERATORS:
                stats["order_checked_swappable"] += 1
            if expected != actual:
                bad_order.append((original, expected, actual))

        # 图上的检查都做完了，这时才写回。**必须写回**，否则后面那条字节判据是空跑：
        # 导出只读 `formula`，不写回的话 `formula` 还是导入时那一份，节点图这条路压根
        # 没进到导出产物里——实测过，「按 vendor 顺序摆插槽」那个注入在写回之前字节全绿。
        expr_edit.apply_rows(curve, after)

    report.check(f"[{stem}] 建图/读回不抛异常", not crashed,
                 f"{len(crashed)} 条炸了：{crashed[:2]}")
    report.check(f"[{stem}] 行 -> 图 -> 行 恒等", not bad_roundtrip,
                 f"{len(bad_roundtrip)} 条不等：{bad_roundtrip[:3]}")
    report.check(f"[{stem}] 从图重拼的文本 == 原文本", not bad_text,
                 f"{len(bad_text)} 条不等：{bad_text[:2]}")
    report.check(f"[{stem}] 插槽顺序对拍（不共用 display_arg_order）", not bad_order,
                 f"{len(bad_order)} 条顺序不对：{bad_order[:2]}")
    report.check(f"[{stem}] 叶子在插槽上、没造成独立节点", not bad_leaf,
                 f"{len(bad_leaf)} 条节点数对不上：{bad_leaf[:2]}")
    if skipped_order:
        print(f"  [NOTE] {skipped_order} 条公式跳过了顺序对拍"
              "（根是叶子，或两个子树的规范文本一样、定不出先后）")

    # 2. 全量过一遍节点图之后导出，字节 == 纯 CLI 往返基线
    out_data = io_tree.export_root_to_efxfile(root_obj)
    out_path, notice, fatal = operators._ensure_version_suffix(
        str(workdir / f"{stem}_nodes.efx.5571972"), out_data)
    if fatal:
        report.check(f"[{stem}] 导出路径能补出合法版本号后缀", False, notice or "")
        return len(pairs)
    bridge.load_efx(out_data, out_path)
    out = pathlib.Path(out_path)
    same = out.read_bytes() == cli_out.read_bytes()
    report.check(f"[{stem}] 过一遍节点图后导出，字节 == 纯 CLI 往返基线", same,
                 f"{out}（{out.stat().st_size} 字节） != "
                 f"{cli_out}（{cli_out.stat().st_size} 字节）")
    if same:
        try:
            bridge.dump_efx(out)
            report.check(f"[{stem}] 产物能被 RE-Engine-Lib 读回来", True)
        except bridge.BridgeError as ex:
            report.check(f"[{stem}] 产物能被 RE-Engine-Lib 读回来", False, str(ex))

    return len(pairs)


# ---------------------------------------------------------------------------
# 编辑能力（检查项 5 / 6）—— 用内存里造的公式，不依赖 diag/ 里恰好有什么
# ---------------------------------------------------------------------------

def _scratch_curve(formula):
    """造一个挂着一条公式的 attribute 对象，返回 (obj, curve)。"""
    obj = bpy.data.objects.new("scratch_expr_attr", None)
    bpy.context.scene.collection.objects.link(obj)
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    obj.efx_is_expression_attribute = True
    curve = obj.efx_expression_curves.add()
    curve.bit_index = 0
    curve.formula = formula
    expr_edit.rebuild_rows(curve)
    return obj, curve


def _root_node(tree):
    output = next(n for n in tree.nodes if n.bl_idname == expr_nodes._OUTPUT_NODE_ID)
    return expr_nodes._source_node(output.inputs[0])


def verify_editing(report: Report) -> None:
    print("\n=== 编辑能力（内存里造的公式）")
    tree = expr_nodes.get_tree(create=True)

    # --- 改插槽常量 -------------------------------------------------------
    obj, curve = _scratch_curve("(5 / TIMER)")
    expr_nodes.bind(tree, obj, 0)
    expr_nodes.build_graph(tree, bpy.context)
    root = _root_node(tree)
    const_socket = next(s for s in root.inputs
                        if not s.is_linked and s.leaf_kind == "CONST")
    const_socket.value = 12.0
    ok = expr_nodes.sync_to_formula(bpy.context)
    report.check("改插槽常量 -> formula 跟着变",
                 ok and "12" in curve.formula, curve.formula)
    report.check("改完的公式桥接能解析", _bridge_accepts(curve.formula), curve.formula)

    # --- 改插槽变量名 -----------------------------------------------------
    root = _root_node(tree)
    var_socket = next(s for s in root.inputs if not s.is_linked and s.leaf_kind == "VAR")
    var_socket.var_name = "PLAY_SPEED"
    expr_nodes.sync_to_formula(bpy.context)
    report.check("改插槽变量名 -> formula 跟着变",
                 "PLAY_SPEED" in curve.formula, curve.formula)

    # --- 换节点函数（参数变多：补常量 0；再变少：裁掉） -------------------
    obj2, curve2 = _scratch_curve("(5 / TIMER)")
    expr_nodes.bind(tree, obj2, 0)
    expr_nodes.build_graph(tree, bpy.context)
    _root_node(tree).call_name = "Lerp"              # 2 参 -> 3 参
    expr_nodes.sync_to_formula(bpy.context)
    grew = curve2.formula.startswith("Lerp(") and len(expr_edit.read_rows(curve2)) == 4
    report.check("换成参数更多的函数 -> 补常量 0，原参数留在原位", grew, curve2.formula)
    _root_node(tree).call_name = "Abs"            # 3 参 -> 1 参
    expr_nodes.sync_to_formula(bpy.context)
    shrank = (curve2.formula.startswith("Abs(")
              and len(expr_edit.read_rows(curve2)) == 2)
    report.check("换成参数更少的函数 -> 多的插槽被裁掉", shrank, curve2.formula)
    report.check("换函数后的公式桥接能解析", _bridge_accepts(curve2.formula), curve2.formula)

    # --- 断开连线 -> 退回插槽上的叶子 -------------------------------------
    obj3, curve3 = _scratch_curve("(Abs(TIMER) / 3)")
    expr_nodes.bind(tree, obj3, 0)
    expr_nodes.build_graph(tree, bpy.context)
    root = _root_node(tree)
    linked = next(s for s in root.inputs if s.is_linked)
    for link in list(linked.links):
        tree.links.remove(link)
    expr_nodes.sync_to_formula(bpy.context)
    dropped = "Abs" not in curve3.formula and len(expr_edit.read_rows(curve3)) == 3
    report.check("断开连线 -> 那一支退回插槽上的叶子", dropped, curve3.formula)

    # --- 重新连线 ---------------------------------------------------------
    root = _root_node(tree)
    new_node = tree.nodes.new(expr_nodes._CALL_NODE_ID)
    new_node.call_name = "Floor"                    # Floor
    new_node.rebuild_sockets()
    tree.links.new(new_node.outputs[0], root.inputs[0])
    expr_nodes.sync_to_formula(bpy.context)
    report.check("连上一个新节点 -> 进入公式", "Floor" in curve3.formula, curve3.formula)
    report.check("连线后的公式桥接能解析", _bridge_accepts(curve3.formula), curve3.formula)

    # --- 检查项 6：DAG 被拒绝，formula 不变 -------------------------------
    obj4, curve4 = _scratch_curve("(Abs(TIMER) / 3)")
    expr_nodes.bind(tree, obj4, 0)
    expr_nodes.build_graph(tree, bpy.context)
    before = curve4.formula
    root = _root_node(tree)
    shared = expr_nodes._source_node(next(s for s in root.inputs if s.is_linked))
    free = next(s for s in root.inputs if not s.is_linked)
    tree.links.new(shared.outputs[0], free)          # 一个输出接两个插槽
    rejected = not expr_nodes.sync_to_formula(bpy.context)
    report.check("一个输出接两个插槽 -> 拒绝，formula 不变",
                 rejected and curve4.formula == before,
                 f"{before} -> {curve4.formula}")
    report.check("拒绝时给出了原因", bool(expr_nodes._LAST_ERROR),
                 expr_nodes._LAST_ERROR)
    report.check("拒绝之后图按 formula 重建了（那根非法连线消失）",
                 expr_nodes.sync_to_formula(bpy.context) is True,
                 "重建后应当能正常读回")

    # --- 检查项 6：成环被拒绝 ---------------------------------------------
    obj5, curve5 = _scratch_curve("(Abs(TIMER) / 3)")
    expr_nodes.bind(tree, obj5, 0)
    expr_nodes.build_graph(tree, bpy.context)
    before = curve5.formula
    root = _root_node(tree)
    inner = expr_nodes._source_node(next(s for s in root.inputs if s.is_linked))
    link = tree.links.new(root.outputs[0], inner.inputs[0])  # 根接回自己的子节点 -> 环
    # Blender 自己会把制造环的连线标成 `is_valid == False`（实测），所以用户可见的
    # 契约是"环连不上、公式不变"，不是"我们报一条错"。这里钉的是**那个契约**——
    # 断言"必须由我们拒绝"的话，等于把上游的行为写死进门禁，上游一改就假红。
    #
    # ⚠ `is_valid` 必须在同步**之前**读：`sync_to_formula()` 里的 `build_graph()` 会
    # `tree.nodes.clear()`，之后这个 link 句柄就悬空了，读出来的是垃圾值
    # （实测读到 True，看起来像"Blender 没挡住"）。
    cycle_blocked = not link.is_valid
    expr_nodes.sync_to_formula(bpy.context)
    report.check("连线成环 -> 连不上（Blender 标成 invalid），formula 不变",
                 cycle_blocked and curve5.formula == before,
                 f"blocked={cycle_blocked}  {before} -> {curve5.formula}")

    # --- 面板那一侧改了，图要跟上 -----------------------------------------
    obj6, curve6 = _scratch_curve("(5 / TIMER)")
    expr_nodes.bind(tree, obj6, 0)
    expr_nodes.build_graph(tree, bpy.context)
    curve6.formula = "Abs((7 / TIMER))"          # 模拟用户在文本框里手打
    root = _root_node(tree)
    followed = root is not None and root.call_name == "Abs"
    report.check("面板改了公式 -> 节点图跟着重建", followed,
                 root.call_name if root else "图是空的")


def _bridge_accepts(formula) -> bool:
    try:
        return not bridge.check_expression(formula)
    except bridge.BridgeError:
        return False


# ---------------------------------------------------------------------------

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
        print(f"[ERROR] {diag} 下没有 *.orig 样本。diag/ 是 untracked 的游戏资产"
              "（见 .gitignore），需要自己放一份原始 .efx 并以 .orig 结尾，或用 --diag 指到别处。")
        return 1

    workdir = pathlib.Path(opts["out"]) if "out" in opts else pathlib.Path(
        tempfile.mkdtemp(prefix="efx_expr_nodes_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"样本目录: {diag}\n输出目录: {workdir}（跑完不删，失败时拿去 hexdump 对比）")

    blender_efx_re.register()

    report = Report()
    total = 0
    stats = {"calls": 0, "order_checked": 0, "order_checked_swappable": 0}
    for orig in samples:
        total += verify_sample(orig, workdir, report, stats)
    verify_editing(report)

    print("\n=== 样本覆盖")
    print(f"  最大图规模（调用节点数）: {stats['calls']}")
    print(f"  做了顺序对拍的公式: {stats['order_checked']} 条，"
          f"其中根是**操作数会翻转**的二元操作码的: {stats['order_checked_swappable']} 条")

    if total == 0:
        print(f"\n[ERROR] {len(samples)} 个样本里一条 Expression 公式都没有，这条门禁等于没跑。"
              "换一个带 IExpressionAttribute 的样本（diag/11_guide_006.efx.5571972.orig 就有）。")
        return 1
    if stats["order_checked_swappable"] == 0:
        # 顺序对拍是这条门禁存在的主要理由（见模块 docstring）。一条会翻转的都没测到时，
        # 检查项 3 实质上是空跑——必须说出来并退 1，不静默全绿（验证纪律第二条）。
        print("\n[ERROR] 顺序对拍一条「操作数会翻转的二元操作码」都没测到"
              f"（`-` `*` `Min` `Max` 这四个，见 expr.CANONICAL_OPERATORS）。"
              "检查项 3 是这条门禁的核心，样本覆盖不到它等于没跑。"
              "往 diag/ 放一个根是这四个操作码之一的公式样本。")
        return 1

    print(f"\n过了 {total} 条公式")
    print("\n=== 注入矩阵（改这个文件之前照着重跑一遍）\n" + _INJECTION_MATRIX)

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
