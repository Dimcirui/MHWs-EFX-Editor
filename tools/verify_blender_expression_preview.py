# -*- coding: utf-8 -*-
"""
tools/verify_blender_expression_preview.py —— Expression 公式数值可视化（L2）的回归防护

必须在 Blender 里跑（要真 bpy：场景树、活动对象、draw handler 注册），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_expression_preview.py

可选参数放在 `--` 之后：`--diag <样本目录>`（默认 `<仓库根>/diag`，收 `*.orig`）、
`--out <输出目录>`、`--dll <EfxBridge.dll>`，含义同 `verify_blender_roundtrip.py`。

门禁边界：这条能测到什么、测不到什么
------------------------------------
可视化走的是 3D 视口 HUD（`gpu` + `blf`），而 **`--background` 下没有 GPU 上下文**
（CLAUDE.md 验证纪律），所以 `_draw_hud()` 本身跑不到。代码为此按 `sim_preview` 的
分法拆了两层，这条门禁测的是**数据那一层**：

| 能测 | 测不到 |
|---|---|
| 采样值、自动缩放边界、刻度取整、断点分段、归一化坐标 | 线真的画出来了没有 |
| 逐节点实时值（结构树那一列的数据源） | HUD 里字和线有没有重叠 |
| 选中哪一级就画哪一级（子树切片 + 标题标注） | |
| 置信度分档、note 透传 | 颜色/字号/位置好不好看 |
| 变量表的三层来源和优先级 | `blf` 文字有没有被 HUD 边框裁掉 |
| 面板读数 == `efx_sim` 求值 | |
| `sim_preview` 真的把具名参数传进了 `Simulator` | |
| 整条预览路径不改任何导出数据（字节对照） | |

几何层的细节（退化区间、刻度整数、`None` 断开）在 `tests/test_sim_plot.py` 里用纯 Python
单测覆盖，这里只验"接到真实场景数据上仍然对"。**HUD 好不好看只能在有界面的 Blender 里
实测**，改了 `_draw_hud()` 的布局就去实机看一眼。

按验证纪律，下面每条都注入过对应 bug 确认会 FAIL：
`build_variables()` 去掉具名参数那层 -> "文件级具名参数在"红；
`_make_track()` 去掉 `expr_parameters=` -> "sim_preview 建 track 时传了具名参数"红
（⚠ "面板读数 == efx_sim 求值"那条**抓不到**变量表漂移——它给两边喂同一个 dict，
只能证明求值器是同一个，别指望它）；
`hud_series()` 把算不出来的帧填 0 -> "算不出来的帧保持断开"红；
`curve_confidence()` 恒返回 confirmed -> "置信度取最差的那一档"红；
采样路径里误写 `formula` -> "预览不改公式文本"红。

⚠ **几何退化那一类注入这条门禁抓不到**（实测：`nice_bounds()` 去掉"常量序列撑开跨度"
那一步，这里全绿、`tests/test_sim_plot.py` 红 3 条）。原因**不是**样本里没有常量公式——
恰恰相反，实测 50 条里有 46 条是常量（大量公式压根不引用 `TIMER`，画出来就是一条平线，
这是对的）。真正的原因是这里的判据只要求"纵轴跨度 > 0"，而那个性质由
`nice_bounds()` 末尾另一道独立的保险（`if y0 == y1: y1 = y0 + step`）兜住了；
**"常量的线不该贴在边框上"这个更强的性质只在单测里断言**。
教训是这条门禁的几何断言是"不崩"级别的，形状质量归单测——别把单测里的几何用例删了
挪到这儿来。下面会打印样本实际覆盖到的形态，缺哪类一眼能看见。

退出码：全绿 0，有失败 1。⚠ `blender --background --python` 在脚本抛未捕获异常时退出码
仍是 0（实测），所以入口自己加一层捕获，见文件末尾。
"""

from __future__ import annotations

import math
import pathlib
import shutil
import sys
import tempfile
import traceback

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import (bridge, expr_preview, io_tree, model,  # noqa: E402
                            operators, sim_preview, transform3d_view)
import efx_sim  # noqa: E402
from efx_sim import expr as _expr, plot as _plot  # noqa: E402


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


def _expression_objects(root_obj):
    return [o for o in bpy.data.objects
            if o.get("~TYPE") == model.TYPE_ATTRIBUTE
            and getattr(o, "efx_is_expression_attribute", False)
            and len(o.efx_expression_curves)
            and io_tree.find_root(o) is root_obj]


def verify_preview_is_read_only(orig: pathlib.Path, workdir: pathlib.Path,
                                report: Report, plotted: list) -> int:
    """整条预览路径（变量表 + 采样 + 几何）跑一遍，导出字节必须不变。

    HUD 本身不往 .blend 写东西（这是它比 F-Curve 烘录省掉的一整类风险），但采样要**读**
    `efx_fields`、`efx_expression_curves`，一个手滑的赋值就是预览污染导出。这种错对
    roundtrip / expression_edit 两个门禁完全免疫。
    """
    stem = orig.name.split(".efx.")[0]
    print(f"\n=== {stem}")

    src = workdir / orig.name.replace(".orig", "")
    shutil.copy(orig, src)

    data = bridge.dump_efx(src)
    root_obj = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, src.name)
    root_obj.efx_source_filename = src.name
    transform3d_view.sync_all_transform3d(root_obj)

    def export_to(path):
        out_data = io_tree.export_root_to_efxfile(root_obj)
        out_path, notice, fatal = operators._ensure_version_suffix(str(path), out_data)
        if fatal:
            raise RuntimeError(notice or "导出路径拿不到合法版本号后缀")
        bridge.load_efx(out_data, out_path)
        return pathlib.Path(out_path)

    before = export_to(workdir / f"{stem}_before.efx.5571972")

    attrs = _expression_objects(root_obj)
    print(f"  带公式的 attribute {len(attrs)} 个")
    formulas_before = {o.name: [c.formula for c in o.efx_expression_curves] for o in attrs}

    # 逐个 attribute、逐条公式都过一遍完整的采样 + 几何，正是 HUD 每次重绘做的事
    drawable = 0
    for obj in attrs:
        bpy.context.view_layer.objects.active = obj
        for index in range(len(obj.efx_expression_curves)):
            obj.efx_expression_curves_active_index = index
            plot = expr_preview.hud_plot(bpy.context, obj=obj, frames=24)
            if plot is not None:
                drawable += 1
                plotted.append(plot)

    # 只在这个样本真的带公式时才要求采样出东西——`diag/` 里有几个文件一条 Expression
    # 都没有，对它们断言 drawable>0 是假失败。"整批一条都没有"由 main() 里的 total==0 兜。
    if attrs:
        report.check("真实样本上采样出了可画的几何", drawable > 0, f"drawable={drawable}")

    formulas_after = {o.name: [c.formula for c in o.efx_expression_curves] for o in attrs}
    report.check("预览不改公式文本", formulas_before == formulas_after,
                 "有 attribute 的 formula 被改了")

    after = export_to(workdir / f"{stem}_after.efx.5571972")
    report.check(
        "跑完预览路径后导出字节不变",
        before.read_bytes() == after.read_bytes(),
        f"{before}（{before.stat().st_size} 字节） != {after}（{after.stat().st_size} 字节）",
    )
    return drawable


def verify_geometry_invariants(report: Report, plots: list) -> None:
    """真实样本上算出来的几何必须满足这些不变量（细节单测在 tests/test_sim_plot.py）。"""
    print("\n=== 几何不变量（真实样本）")
    bad_norm = []
    bad_bounds = []
    for plot in plots:
        for segment in plot.segments:
            for nx, ny in segment:
                if not (-1e-6 <= nx <= 1 + 1e-6 and -1e-6 <= ny <= 1 + 1e-6):
                    bad_norm.append((plot.label, nx, ny))
        if not (plot.y1 > plot.y0 and plot.x1 > plot.x0):
            bad_bounds.append((plot.label, plot.y0, plot.y1))
        if not all(math.isfinite(t) for t in plot.y_ticks):
            bad_bounds.append((plot.label, "non-finite tick"))
    report.check("归一化坐标全部落在 [0,1]", not bad_norm,
                 f"{len(bad_norm)} 个越界，首例 {bad_norm[:1]}")
    report.check("边界跨度恒大于 0（除零防护）", not bad_bounds,
                 f"{len(bad_bounds)} 条不合格，首例 {bad_bounds[:1]}")


def verify_variables_and_agreement(report: Report):
    print("\n=== 变量表 / 与 Simulator 一致")
    scene_col = bpy.context.scene.collection
    data = {"Header": {"Version": 5571972}, "Entries": [], "Actions": [], "Bones": [],
            "FieldParameterValues": [], "UvarGroups": [],
            "ExpressionParameters": [], "EffectGroups": []}
    root = io_tree.build_root_from_efxfile(data, scene_col, "expr_preview_probe")

    param = root.efx_expression_parameters.add()
    param.name = "Length"
    param.param_type = "Float"
    param.value1 = 10.0
    colour = root.efx_expression_parameters.add()
    colour.name = "TintOnly"
    colour.param_type = "Color"

    # 探针对象必须挂在 root 自己的集合里——真实数据就是这个形状，而且
    # `build_variables()` 是从对象往上找根的（不是看活动选择）
    entries_col, _actions_col = io_tree.root_collections(root)
    entry = bpy.data.objects.new("probe_entry", None)
    entries_col.objects.link(entry)
    entry["~TYPE"] = model.TYPE_ENTRY

    attr = bpy.data.objects.new("probe_attr", None)
    entries_col.objects.link(attr)
    attr.parent = entry
    attr["~TYPE"] = model.TYPE_ATTRIBUTE
    attr.efx_is_expression_attribute = True
    curve = attr.efx_expression_curves.add()
    curve.formula = "Lerp(-30, 190, SmoothStep(0, 12, TIMER))"
    attr.efx_expression_curves_active_index = 0
    bpy.context.view_layer.objects.active = attr

    variables = expr_preview.build_variables(bpy.context, attr, 6.0)
    report.check("内置变量在", math.isclose(variables.get("PI", 0), math.pi)
                 and variables.get("TIMER") == 6.0
                 and variables.get("PLAY_SPEED") == 1.0, str(sorted(variables)[:8]))
    report.check("文件级具名参数在（Float 取 value1）", variables.get("Length") == 10.0,
                 str(variables.get("Length")))
    report.check("Color 型参数不当标量收进来（没有证据，不许编一个数）",
                 "TintOnly" not in variables, str(variables.get("TintOnly")))

    value, notes = expr_preview.evaluate_curve(curve, variables)
    report.check("读数正确（TIMER=6 时 190 -> 80）", value == 80.0, str(value))
    report.check("没有多余的 note", notes == [], str(notes))

    ctx = _expr.EvalContext(variables, "identity", [])
    sim_value = _expr.evaluate(_expr.parse(curve.formula), ctx)
    report.check("面板读数 == efx_sim 求值", sim_value == value, f"{sim_value} != {value}")

    sim = efx_sim.Simulator([], efx_sim.SimConfig(), expr_parameters={"Length": 10.0})
    report.check("Simulator 收 expr_parameters", sim._expr_parameters == {"Length": 10.0},
                 str(sim._expr_parameters))
    report.check("采集函数本身对",
                 expr_preview.collect_expr_parameters(root) == {"Length": 10.0},
                 str(expr_preview.collect_expr_parameters(root)))
    # **端到端**：真的走一遍 sim_preview 建 track 的那条路。只检查上面两条不够——
    # `_make_track()` 里少写一个 `expr_parameters=` 两条都还是绿的，而那正是
    # "面板说 80、粒子预览按 0 在动"这个不一致的来源。
    track = sim_preview._make_track(entry, bpy.context.scene)
    report.check("sim_preview 建 track 时传了具名参数",
                 track["sim"]._expr_parameters == {"Length": 10.0},
                 str(track["sim"]._expr_parameters))

    return attr, curve


def verify_series_and_confidence(report: Report, attr, curve) -> None:
    print("\n=== 采样序列 / 置信度")
    series = expr_preview.hud_series(bpy.context, obj=attr, frames=24)
    report.check("采样点数 == 帧数 + 1", len(series.values) == 25, str(len(series.values)))
    report.check("采样值对（0 帧 -30、12 帧 190、24 帧饱和仍是 190，"
                 "Lerp 方向+Clamp 饱和均为 2026-09-16 实机确认）",
                 series.values[0] == -30.0 and series.values[12] == 190.0
                 and abs(series.values[24] - 190.0) < 1e-6,
                 str([series.values[0], series.values[12], series.values[24]]))
    report.check("曲线名取 bit_name（没有就退回 bit 下标）",
                 series.label in (curve.bit_name, "bit %d" % curve.bit_index), series.label)
    # 2026-09-16 收尾后整套语义全部实机确认，`Clamp` 也从 `corpus` 升到 `confirmed`
    # （最后补的是下界饱和）。这条现在验"真实样本里的公式算确认档"。
    report.check("真实样本的 Lerp/Clamp 公式算语义明确档",
                 series.confidence == _expr.CONFIDENCE_CONFIRMED, str(series.confidence))

    # 置信度取**最差**的那一档。⚠ **已经没有任何未确认的调用可当样本了**：
    # 2026-09-16 那一轮把六个运算符、12 个 `Unary*`、`Func18`~`Func21`、`InvLerp` 全部
    # 实机测出语义，`_UNKNOWN_FUNC_ARGC` 空了、`InvLerp` 也升到确认档。这个样本换过
    # 四次（`Unary10` -> `Unary2` -> `Func18` -> `Func20`），现在只能**临时注入一个
    # 假函数名**。这条代码路径要留着：下次 vendor 升级冒出新函数（或给枚举补上
    # 3/13/14）时它就是第一道防线。权威名单是 `efx_sim/expr.py::_UNKNOWN_FUNC_ARGC`。
    _expr._UNKNOWN_FUNC_ARGC["FuncNew"] = 1
    _expr.CALL_SIGNATURES["FuncNew"] = (1, _expr.CONFIDENCE_UNKNOWN)
    try:
        curve.formula = "Lerp(-30, 190, FuncNew(SmoothStep(0, 12, TIMER)))"
        series2 = expr_preview.hud_series(bpy.context, obj=attr, frames=8)
        report.check("置信度取最差的那一档（注入的未知函数 -> unknown）",
                     series2.confidence == _expr.CONFIDENCE_UNKNOWN, str(series2.confidence))
        report.check("未确认语义函数会 note 出来",
                     any("FuncNew" in n for n in series2.notes), str(series2.notes))
    finally:
        del _expr._UNKNOWN_FUNC_ARGC["FuncNew"]
        del _expr.CALL_SIGNATURES["FuncNew"]

    # 分档的偏序关系还是要钉住（机制得留着——vendor 升级冒出新函数时就靠它），
    # 但现在没有非确认档的真样本了，所以直接验 `_CONFIDENCE_ORDER` 本身。
    order = expr_preview._CONFIDENCE_ORDER
    report.check("置信度偏序：confirmed < corpus < undecided < unknown",
                 (order.index(_expr.CONFIDENCE_CONFIRMED)
                  < order.index(_expr.CONFIDENCE_CORPUS)
                  < order.index(_expr.CONFIDENCE_UNDECIDED)
                  < order.index(_expr.CONFIDENCE_UNKNOWN)), str(order))

    # 反向检查：已经测出语义的函数**不能**被当成未知（否则 UI 会永远挂着"语义未确认"）。
    # 2026-09-16 那一轮把 12 个 `Unary*` + `Func18`~`Func21` 全部定了下来。
    curve.formula = "Lerp(-30, Remap(TIMER, 0, 12, 0, 1), Saturate(SmoothStep(0, 12, TIMER)))"
    series2b = expr_preview.hud_series(bpy.context, obj=attr, frames=8)
    report.check("已实机确认的 Unary10（saturate）/ Func21 不再算未知档",
                 series2b.confidence != _expr.CONFIDENCE_UNKNOWN, str(series2b.confidence))

    # HUD 的求值上下文必须和粒子模拟同源（`SimConfig`），不能各自用默认值——
    # 两边默认值"恰好一样"是巧合，`expr_clamp_mode` 一旦接到场景属性上就会静默漂移。
    cfg = sim_preview.config_from_scene(bpy.context.scene)
    probe_ctx = expr_preview._eval_context({}, [], bpy.context)
    report.check("HUD 的 clamp 读法跟着 SimConfig",
                 probe_ctx.clamp_mode == cfg.expr_clamp_mode,
                 "%s vs %s" % (probe_ctx.clamp_mode, cfg.expr_clamp_mode))
    report.check("HUD 的未知函数策略也跟着 SimConfig",
                 probe_ctx.unknown_func_policy == cfg.expr_unknown_func_policy,
                 "%s vs %s" % (probe_ctx.unknown_func_policy, cfg.expr_unknown_func_policy))
    # 拿不到 context 时要能退回默认值而不是炸
    fallback = expr_preview._eval_context({}, [], None)
    report.check("拿不到 context 时退回默认值", fallback.clamp_mode is not None,
                 str(fallback.clamp_mode))

    # 除零：求值器的约定是 note + 0.0
    curve.formula = "(TIMER + (5 / TIMER))"
    series3 = expr_preview.hud_series(bpy.context, obj=attr, frames=8)
    report.check("除零那一帧有 note", any("除零" in n for n in series3.notes),
                 str(series3.notes))

    # 语法错：每一帧都算不出来 -> 全 None
    curve.formula = "Min(1, "
    series4 = expr_preview.hud_series(bpy.context, obj=attr, frames=8)
    report.check("算不出来的帧保持断开（None，不填 0）",
                 all(v is None for v in series4.values), str(series4.values[:3]))
    report.check("整条都算不出来时几何返回 None（不画一条平在 0 的假线）",
                 _plot.build(series4) is None)

    curve.formula = "Lerp(-30, 190, SmoothStep(0, 12, TIMER))"


def verify_subtree_values_and_plot(report: Report, attr, curve) -> None:
    """逐节点实时值（结构树那一列）+ 选中哪一级 HUD 就画哪一级。

    这两条是"结构太抽象"那轮反馈的正面解法，判据都落在数据上：
    - `subtree_values()` 必须给出**每一级各自**的值，不是整条公式的值；
    - 选中非根节点时 `hud_series()` 必须换成那棵子树的采样，而且标题写明是哪一级
      （否则"面板读数是整条、HUD 是子树"会看着像算错了）。
    """
    print("\n=== 逐节点值 / 子树曲线")
    from blender_efx_re import expr_edit

    curve.formula = "Lerp(-30, 190, SmoothStep(0, 12, TIMER))"
    expr_edit.rebuild_rows(curve)
    bpy.context.scene.frame_current = 6
    rows = expr_edit.read_rows(curve)
    # 7 行：`-30` 在建行时就折成了一个带符号常量（`expr._collect_rows()`），
    # 不再是"NEG + 常量"两行——界面上因此没有游离的负号
    report.check("行结构是 7 行（-30 折成一个带符号常量）", len(rows) == 7, str(len(rows)))
    report.check("第 1 行是 -30 这个带符号常量",
                 rows[1]["kind"] == "CONST" and rows[1]["value"] == -30.0, str(rows[1]))

    values = expr_preview.subtree_values(bpy.context, curve, rows)
    # 0 Lerp / 1 -30 / 2 190 / 3 SmoothStep / 4 0 / 5 12 / 6 TIMER
    want = {0: 80.0, 1: -30.0, 2: 190.0, 3: 0.5, 4: 0.0, 5: 12.0, 6: 6.0}
    bad = {k: (values.get(k), v) for k, v in want.items()
           if values.get(k) is None or abs(values[k] - v) > 1e-6}
    report.check("每一级子树各自的值都对（TIMER=6：SmoothStep=0.5、Lerp=80）", not bad, str(bad))

    # 选中根 -> 画整条公式
    curve.nodes_active_index = 0
    text, is_root = expr_preview.active_subtree(bpy.context, curve)
    report.check("选中根时画整条公式", is_root and text == curve.formula, text)
    root_series = expr_preview.hud_series(bpy.context, obj=attr, frames=24)
    report.check("根的曲线是 -30 -> 190（Lerp 方向 2026-09-16 实机确认）",
                 root_series.values[0] == -30.0 and root_series.values[12] == 190.0,
                 str(root_series.values[:1] + root_series.values[12:13]))

    # 选中 SmoothStep -> 画它自己（0 -> 1 的斜坡，上界饱和所以 24 帧仍是 1，2026-09-16 实机确认）
    curve.nodes_active_index = 3
    text, is_root = expr_preview.active_subtree(bpy.context, curve)
    report.check("选中 SmoothStep 时子公式文本正确",
                 (not is_root) and text == "SmoothStep(0, 12, TIMER)", text)
    sub_series = expr_preview.hud_series(bpy.context, obj=attr, frames=24)
    report.check("子树曲线是 SmoothStep 自己（0 -> 1 -> 饱和在 1），不是整条公式",
                 sub_series.values[0] == 0.0 and abs(sub_series.values[12] - 1.0) < 1e-6
                 and abs(sub_series.values[24] - 1.0) < 1e-6,
                 str([sub_series.values[0], sub_series.values[12], sub_series.values[24]]))
    report.check("HUD 标题写明画的是哪一级", ">" in sub_series.label, sub_series.label)

    # 选中一个叶子也要能画（常量 -> 一条平线，且几何不退化）
    curve.nodes_active_index = 5
    leaf_plot = expr_preview.hud_plot(bpy.context, obj=attr, frames=24)
    report.check("选中常量叶子也画得出来（平线，跨度不为 0）",
                 leaf_plot is not None and leaf_plot.y1 > leaf_plot.y0,
                 str(leaf_plot))

    curve.nodes_active_index = 0


def verify_handler_and_toggle(report: Report) -> None:
    """HUD 的 draw handler 注册了、开关在、而且绘制回调**不会把异常抛出去**。"""
    print("\n=== HUD handler / 开关")
    report.check("POST_PIXEL draw handler 已注册", len(expr_preview._HANDLERS) == 1,
                 str(expr_preview._HANDLERS))
    report.check("场景开关存在且默认关",
                 hasattr(bpy.context.scene, "efx_re_expr_hud")
                 and bpy.context.scene.efx_re_expr_hud is False)
    report.check("采样帧数属性存在",
                 getattr(bpy.context.scene, "efx_re_expr_preview_frames", 0) > 0)

    # 绘制回调在 --background 下必然走不完（没有 region / GPU 上下文），但**绝不能抛**
    # ——draw handler 里抛异常会把视口刷屏报错。开着开关直接调一次。
    bpy.context.scene.efx_re_expr_hud = True
    detail = ""
    try:
        expr_preview._draw_hud()
        raised = False
    except BaseException as exc:                        # noqa: BLE001
        raised = True
        detail = str(exc)
    report.check("绘制回调不往外抛异常", not raised, detail)
    bpy.context.scene.efx_re_expr_hud = False


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
        tempfile.mkdtemp(prefix="efx_expr_preview_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"样本目录: {diag}\n输出目录: {workdir}（跑完不删）")

    blender_efx_re.register()

    report = Report()
    plots = []
    total = 0
    for orig in samples:
        total += verify_preview_is_read_only(orig, workdir, report, plots)
    if total == 0:
        print(f"\n[ERROR] {len(samples)} 个样本里一条能采样的公式都没有，核心断言等于没跑。"
              "换一个带 IExpressionAttribute 的样本。")
        return 1
    print(f"\n真实样本上采样了 {total} 条公式")

    # 样本实际覆盖到哪些形态。**不是失败条件**（用户的 diag/ 里有什么不归这个脚本管），
    # 但"某一类形态这批样本一条都没有"必须说出来——否则针对那一类的回归在这儿是隐形的。
    constant = sum(1 for p in plots if len(p.y_ticks) and p.y_step and
                   all(abs(y - p.segments[0][0][1]) < 1e-9
                       for seg in p.segments for _x, y in seg))
    with_gaps = sum(1 for p in plots if p.gap_count)
    multi_seg = sum(1 for p in plots if len(p.segments) > 1)
    print(f"\n=== 样本覆盖到的形态：可画 {len(plots)} 条，其中常量 {constant} 条、"
          f"含算不出来的帧 {with_gaps} 条、被断成多段 {multi_seg} 条")
    for label, count in (("常量公式", constant), ("含断点", with_gaps)):
        if not count:
            print(f"  [NOTE] 样本里没有{label}，那一类只由 tests/test_sim_plot.py 覆盖。")

    verify_geometry_invariants(report, plots)
    attr, curve = verify_variables_and_agreement(report)
    verify_series_and_confidence(report, attr, curve)
    verify_subtree_values_and_plot(report, attr, curve)
    verify_handler_and_toggle(report)

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # `blender --background --python x.py` 抛未捕获异常时退出码仍然是 0（实测），自己兜一层
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:                            # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
