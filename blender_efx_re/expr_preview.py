# -*- coding: utf-8 -*-
"""
blender_efx_re/expr_preview.py —— Expression 公式的数值可视化（读数 + 视口 HUD 曲线图）

结构化编辑（`expr_edit.py`）解决的是"这条公式长什么样"，这一层解决"它算出来是多少、
什么形状"。两件事：

1. **当前帧读数**：面板上显示活动公式在 `scene.frame_current` 这一帧的值。
2. **视口 HUD 曲线图**：在 3D 视口左下角用 `gpu` + `blf` 画活动公式在 `0..N` 帧上的曲线，
   横纵轴边界标出数值。和粒子预览叠在同一个视口里，不用切编辑器。

**一次只画活动那一条。** 一个 attribute 可以挂好几条公式，全画在一张图上又杂乱、又和
"公式是一条条编辑的"这个操作逻辑冲突。选中哪条画哪条，和上面结构编辑器的行为一致。

为什么是 GPU HUD 而不是烘成 F-Curve
-----------------------------------
上一版烘过 F-Curve（让用户去 Graph Editor 看），换掉的理由：

- **免费拿到的交互是过度功能**：为了看一眼形状要点按钮、切编辑器、再按 Normalize，三步。
  HUD 直接在眼前，而"横纵轴边界标好"就足够判断形状了。
- **F-Curve 是快照**：改完公式图还是旧的，得重新烘。HUD 每次重绘都从活数据算。
- **F-Curve 装不下语义**：动画通道没有地方挂"这条曲线用到语义未知的函数、不可信"。
  HUD 可以直接用颜色和角标画出来——全语料 35.3% 的公式含未确认语义，这恰恰是最该看见的
  信息。
- **F-Curve 看着能拖**：用户在 Graph Editor 里拖一个关键帧，图就和公式脱钩了，界面上没有
  任何提示。HUD 不存在这个误导。
- 代价是**没有缩放平移**，也不再往 .blend 里写自定义属性和 Action（连带不再需要"烘完
  导出字节不变"那条门禁）。

门禁边界（CLAUDE.md 验证纪律）
----------------------------------
`--background` 下没有 GPU 上下文，`_draw_hud()` 门禁跑不到。所以照 `sim_preview` 的分法
拆两层：**几何全在 `efx_sim/plot.py`**（零 bpy，`python -m unittest` 覆盖：自动缩放、
刻度取整、断点分段、退化区间），本模块的 `hud_series()` / `hud_plot()` 也是纯数据出口、
由 Blender 门禁覆盖；`_draw_hud()` 只剩"把点和字符串画出来"。改动时**别把求值搬进绘制
函数**，那等于把已经测到的东西重新推回盲区。

变量表从哪来（三个来源，优先级从高到低）
----------------------------------------
1. **内置外部变量**：`PI`/`TIMER`/`RAND`/`EM_INIRAND`/`EM_INIRAND_SHARED`/`PLAY_SPEED`。
2. **本文件的具名参数**（`EfxFile.ExpressionParameters`）：`Length`/`Color_A`/`BombRate`
   这类名字就是从这张表来的，值也在表里。
3. **同 Entry 里其他 attribute 的标量字段**（按字段名）。

这个优先级和 `efx_sim.Simulator._eval_expressions()` **必须一致**，否则面板读数和粒子
预览会对同一条公式给出两个数——那比两边都不显示更坏。粒子预览那边原来漏了来源 ②
（`Length`/`Color_A` 全部落成"未知变量 -> 0"），这一层加进来的时候一起补上了。
"""

from __future__ import annotations

import math

import blf
import bpy
import gpu
from bpy.props import BoolProperty, IntProperty
from gpu_extras.batch import batch_for_shader

from . import expr_edit, io_tree, model
from .i18n import T

try:
    from ..efx_sim import expr as _expr, plot as _plot
except ImportError:  # pragma: no cover - 只在门禁/单测的顶层包布局下走到
    from efx_sim import expr as _expr, plot as _plot

#: 预览里给不出真值的随机类变量取的固定值。**固定而不是真随机**：曲线图必须可复现，
#: 拖一下滑块就换一条形状的图没法用来判断公式对不对。取 0.5 是 `[0, 1)` 的中点。
_FIXED_RANDOM = 0.5

#: 置信度 -> 曲线颜色（RGBA）。**这是选 GPU 而不是 F-Curve 的主要理由之一**，别在重构里
#: 顺手简化成一个颜色。
_CONFIDENCE_COLOR = {
    _expr.CONFIDENCE_CONFIRMED: (0.45, 0.85, 1.00, 1.0),   # 青
    _expr.CONFIDENCE_CORPUS: (0.55, 0.90, 0.55, 1.0),      # 绿
    _expr.CONFIDENCE_UNDECIDED: (1.00, 0.80, 0.35, 1.0),   # 琥珀
    _expr.CONFIDENCE_UNKNOWN: (1.00, 0.45, 0.40, 1.0),     # 红
}
_CONFIDENCE_KEY = {
    _expr.CONFIDENCE_CONFIRMED: "expr.conf.confirmed",
    _expr.CONFIDENCE_CORPUS: "expr.conf.corpus",
    _expr.CONFIDENCE_UNDECIDED: "expr.conf.undecided",
    _expr.CONFIDENCE_UNKNOWN: "expr.conf.unknown",
}

#: HUD 的像素尺寸和边距（会乘 UI 缩放）
_HUD_W, _HUD_H, _HUD_MARGIN, _HUD_PAD = 300.0, 150.0, 16.0, 30.0

_HANDLERS = []
#: 绘制回调里抛出来的最后一条错误。**不往上抛**（draw handler 里抛会刷屏），存下来由面板
#: 显示——静默失败会让人以为"这条公式画不出来"是公式本身的问题。
_DRAW_ERROR = [""]


# ---------------------------------------------------------------------------
# 变量表
# ---------------------------------------------------------------------------

def collect_expr_parameters(root_col) -> dict:
    """EFX_ROOT 的具名参数表 -> `{名字: 标量值}`。

    `Float`/`Range`/`Float2` 取 `value1`（`Range` 的 vendor 注释推测是
    `{初始值, 最小值, 最大值}`，初始值就是 `value1`）。`Color` **不收**——公式里把它当
    标量用的读法我们没有证据，收进来等于编一个数（铁律 #6）。
    """
    out = {}
    if root_col is None:
        return out
    for item in getattr(root_col, "efx_expression_parameters", ()) or ():
        if not item.name:
            continue
        if item.param_type == "Color":
            continue
        out[item.name] = float(item.value1)
    return out


def _sibling_scalar_fields(obj) -> dict:
    """同一个 Entry 下所有 attribute 的标量字段（字段名 -> 值）。和
    `Simulator._eval_expressions()` 里那一圈 `view.raw` 是同一个意思。"""
    out = {}
    entry = obj.parent if obj is not None else None
    if entry is None:
        return out
    for sib in bpy.data.objects:
        if sib.parent is not entry or sib.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        for node in sib.efx_fields:
            _collect_scalars(node, out)
    return out


def _collect_scalars(node, out) -> None:
    if len(node.children):
        for child in node.children:
            _collect_scalars(child, out)
        return
    if node.data_type == "FLOAT":
        out.setdefault(node.key or "", float(node.float_value))
    elif node.data_type == "INT":
        out.setdefault(node.key or "", float(node.int_value))


def _root_for(context, obj):
    """取"这个 attribute 属于哪个 efx 文件"。

    **先从对象自己往上找根，找不到才退回活动选择**（`io_tree.resolve_root()`）。反过来写
    会在同时开着两棵树时静默读到**另一个文件**的具名参数表，界面上完全看不出来——和
    CLAUDE.md 里"引用资源的搜索根首选被导入的那个 efx 自己的位置、资产库只是兜底"
    是同一类错。这条被门禁抓过一次。
    """
    root = io_tree.find_root(obj)
    if root is not None:
        return root
    return io_tree.resolve_root(context)


def build_variables(context, obj, timer: float, formula: str | None = None) -> dict:
    """求值用的变量表。优先级见模块 docstring（内置 > 具名参数 > 兄弟字段）。

    给了 `formula` 时**只在公式真的引用了未覆盖的名字时才去扫兄弟属性**——那一步要遍历
    `bpy.data.objects`（真实文件里有上百个 attribute 对象），而 HUD 是每次视口重绘都要
    算的。大多数公式只用内置变量和具名参数，这一跳能省掉整个扫描。
    """
    variables = {
        "PI": math.pi,
        "TIMER": float(timer),
        "RAND": _FIXED_RANDOM,
        "EM_INIRAND": _FIXED_RANDOM,
        "EM_INIRAND_SHARED": _FIXED_RANDOM,
        "PLAY_SPEED": 1.0,
    }
    for name, value in collect_expr_parameters(_root_for(context, obj)).items():
        variables.setdefault(name, value)

    if formula is not None:
        wanted = _referenced_names(formula)
        if wanted and wanted.issubset(set(variables)):
            return variables
        if not wanted:
            return variables

    for name, value in _sibling_scalar_fields(obj).items():
        variables.setdefault(name, value)
    return variables


def _referenced_names(formula: str) -> set:
    """公式里引用到的标识符（函数名不算）。解析不了就返回 `None`——调用方据此照"要扫"
    处理，宁可多做一次扫描，不要因为解析失败少给变量。"""
    try:
        parsed = _expr.parse(formula)
    except _expr.ExprError:
        return None
    names = set()
    for row in _expr.to_rows(parsed):
        if row["kind"] == _expr.KIND_VAR and row["name"]:
            names.add(row["name"])
    return names


def _eval_context(variables, notes, context=None):
    """建 `EvalContext`——**标定开关必须和粒子模拟走同一个来源**（`SimConfig`）。

    以前这里是硬写 `EvalContext(variables, "identity", notes)`，靠 `EvalContext` 自己的
    默认值和 `SimConfig` 的默认值"恰好一样"来保持一致。那是**巧合**：`expr_clamp_mode`
    是个标定开关（`efx_sim/config.py` 的 UNKNOWNS），一旦有人把它接到场景属性上，
    HUD 曲线就会静默偏离模拟层的读数，而两边都不报错——正是
    `tools/verify_blender_expression_preview.py` docstring 里点出的那个盲区
    （「面板读数 == efx_sim 求值」这条检查喂的是同一个 dict，抓不到配置漂移）。
    """
    cfg = None
    if context is not None:
        try:
            from . import sim_preview
            cfg = sim_preview.config_from_scene(context.scene)
        except Exception:
            cfg = None
    if cfg is None:
        return _expr.EvalContext(variables, "identity", notes)
    return _expr.EvalContext(variables, cfg.expr_unknown_func_policy, notes,
                             cfg.expr_clamp_mode)


def evaluate_curve(curve, variables, context=None) -> tuple:
    """一条曲线在给定变量表下的值，返回 `(值 或 None, notes)`。

    解析/求值失败返回 `None` 而不是 0.0——面板要显示"算不出来"，不能显示一个看起来像
    结果的 0（铁律 #2 在只读侧的对应物）。
    """
    notes = []
    ctx = _eval_context(variables, notes, context)
    try:
        return _expr.evaluate(_expr.parse(curve.formula), ctx), notes
    except _expr.ExprError as exc:
        notes.append(str(exc))
        return None, notes


#: 置信度从"最可信"到"最不可信"。`curve_confidence()` 取一条公式里最差的那一档。
_CONFIDENCE_ORDER = (_expr.CONFIDENCE_CONFIRMED, _expr.CONFIDENCE_CORPUS,
                     _expr.CONFIDENCE_UNDECIDED, _expr.CONFIDENCE_UNKNOWN)


def curve_confidence(curve) -> str:
    """这条公式里最不可信的那一档。只有常量/变量/四则的公式是"语义明确"。"""
    worst = _expr.CONFIDENCE_CONFIRMED
    for node in curve.nodes:
        if node.kind != "CALL":
            continue
        level = _expr.call_confidence(node.name)
        if _CONFIDENCE_ORDER.index(level) > _CONFIDENCE_ORDER.index(worst):
            worst = level
    return worst


# ---------------------------------------------------------------------------
# HUD 的数据出口（纯数据，门禁覆盖得到）
# ---------------------------------------------------------------------------

def subtree_values(context, curve, rows=None) -> dict:
    """这条公式每一级子树在当前帧的值：`{行下标: 值 或 None}`。

    **这是"结构树变调试器"的数据来源**（`expr_edit._node_values()` 用它）：每一行都能显示
    自己那一支算出多少，`Clamp` 给 0.4、外层 `Lerp` 给 -0.1 一眼看到。

    变量表只建一次、所有子树共用——建表要扫具名参数表（可能还要扫兄弟属性），逐行重建
    在深公式上会把面板绘制拖慢。
    """
    if rows is None:
        from . import expr_edit
        rows = expr_edit.read_rows(curve)
    if not rows:
        return {}
    obj = getattr(context, "object", None)
    frame = float(getattr(context.scene, "frame_current", 0))
    variables = build_variables(context, obj, frame, curve.formula)

    # **一次遍历算完所有子树**（`_expr.evaluate_rows`），不要逐行"重建子树文本 -> 重新
    # 解析 -> 求值"——那是 O(N²)，实测 225 行 8 ms / 449 行 18 ms / 897 行 48 ms，而完整
    # 求值一次只要 0.45 ms。这个函数每次面板重绘都跑，公式一复杂界面就肉眼可见地卡
    # （实机用傅里叶级数压到 64 阶时发现的）。
    try:
        parsed = _expr.parse(curve.formula)
    except _expr.ExprError:
        return {index: None for index in range(len(rows))}
    values = _expr.evaluate_rows(parsed, _eval_context(variables, [], context))
    return {index: (values[index] if index < len(values) else None)
            for index in range(len(rows))}


def active_subtree(context, curve, rows=None):
    """活动节点那棵子树的 `(公式文本, 是不是整条公式)`。

    HUD 画的就是这个——**选中哪一级就画那一级**，这样每一层各自是什么形状都能单独看到
    （`Clamp(TIMER, 15, 0)` 是一条 0->1 的斜坡，外层 `Lerp` 才把它映到 190 -> -30）。
    拿不到行（解析失败）就退回整条公式文本。
    """
    if rows is None:
        from . import expr_edit
        rows = expr_edit.read_rows(curve)
    index = getattr(curve, "nodes_active_index", 0)
    if not rows or not (0 <= index < len(rows)):
        return curve.formula, True
    try:
        return _expr.subtree_text(rows, index), index == 0
    except _expr.ExprError:
        return curve.formula, True


def hud_series(context, obj=None, curve=None, frames=None):
    """活动公式的采样序列（`efx_sim.plot.Series`），拿不到就返回 `None`。

    **这是 HUD 的全部输入**。`_draw_hud()` 除了把它画出来不做任何别的事——门禁测的就是
    这个函数和 `hud_plot()`。
    """
    if obj is None:
        obj = getattr(context, "object", None)
    if curve is None:
        curve = expr_edit.active_curve(context)
    if obj is None or curve is None:
        return None
    if frames is None:
        frames = int(getattr(context.scene, "efx_re_expr_preview_frames", 120))
    frames = max(int(frames), 1)

    text, is_root = active_subtree(context, curve)
    base = build_variables(context, obj, 0.0, text)
    frame_list = list(range(0, frames + 1))

    def evaluate_at(frame):
        base["TIMER"] = float(frame)
        notes = []
        ctx = _eval_context(base, notes, context)
        try:
            return _expr.evaluate(_expr.parse(text), ctx), notes
        except _expr.ExprError as exc:
            notes.append(str(exc))
            return None, notes

    values, notes = _plot.sample(evaluate_at, frame_list)
    label = curve.bit_name or ("bit %d" % curve.bit_index)
    if not is_root:
        # 标题必须写明画的是哪一级——不然"面板读数是整条公式、HUD 是子树"会看着像算错了
        label = "%s  >  %s" % (label, _head_of(text))
    return _plot.Series(label, frame_list, values, notes, curve_confidence(curve))


def _head_of(text) -> str:
    """子公式的"头"：函数名或者叶子本身，给 HUD 标题用。"""
    head = text.split("(", 1)[0].strip()
    return head if head else text[:16]


def hud_plot(context, obj=None, curve=None, frames=None):
    """`hud_series()` -> `efx_sim.plot.Plot`（归一化几何）。`None` = 画不出来。"""
    series = hud_series(context, obj, curve, frames)
    return None if series is None else _plot.build(series)


# ---------------------------------------------------------------------------
# 绘制（门禁盲区，只允许"把数据画出来"）
# ---------------------------------------------------------------------------

def _builtin_shader(name):
    """同 `sim_preview._builtin()`：4.0 起是短名，3.x 带 `2D_` 前缀。"""
    try:
        return gpu.shader.from_builtin(name)
    except Exception:                                  # noqa: BLE001
        return gpu.shader.from_builtin("2D_" + name)


def _hud_enabled(context) -> bool:
    scene = getattr(context, "scene", None)
    return bool(scene is not None and getattr(scene, "efx_re_expr_hud", False))


def _draw_hud():
    """`POST_PIXEL` 绘制回调。**不抛异常**——draw handler 里抛会把整个视口刷屏报错
    （同 `sim_preview._draw()`）。"""
    try:
        _draw_hud_inner()
        _DRAW_ERROR[0] = ""
    except Exception as exc:                            # noqa: BLE001
        _DRAW_ERROR[0] = "draw: %s" % exc


def _draw_hud_inner() -> None:
    context = bpy.context
    if not _hud_enabled(context):
        return
    region = getattr(context, "region", None)
    if region is None or region.type != "WINDOW":
        return
    plot = hud_plot(context)
    if plot is None:
        return

    scale = getattr(context.preferences.system, "ui_scale", 1.0) or 1.0
    pad, margin = _HUD_PAD * scale, _HUD_MARGIN * scale
    width, height = _HUD_W * scale, _HUD_H * scale
    x0, y0 = margin + pad, margin + pad
    x1, y1 = x0 + width, y0 + height

    shader = _builtin_shader("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")

    def rect(ax, ay, bx, by, colour):
        shader.bind()
        shader.uniform_float("color", colour)
        batch_for_shader(shader, "TRI_FAN", {
            "pos": [(ax, ay), (bx, ay), (bx, by), (ax, by)]}).draw(shader)

    def lines(coords, colour, thickness=1.0):
        if len(coords) < 2:
            return
        gpu.state.line_width_set(thickness)
        shader.bind()
        shader.uniform_float("color", colour)
        batch_for_shader(shader, "LINE_STRIP", {"pos": coords}).draw(shader)

    # 底板 + 左下两条轴
    rect(x0 - pad * 0.5, y0 - pad * 0.7, x1 + pad * 0.5, y1 + pad * 0.8,
         (0.05, 0.05, 0.06, 0.82))
    lines([(x0, y0), (x1, y0)], (0.55, 0.55, 0.58, 1.0))
    lines([(x0, y0), (x0, y1)], (0.55, 0.55, 0.58, 1.0))

    # 横向刻度线。**y == 0 那条画亮一点**：正负分界是看形状时最重要的参考
    for tick in plot.y_ticks:
        ty = y0 + plot.norm_y(tick) * height
        zero = abs(tick) < 1e-9
        lines([(x0, ty), (x1, ty)],
              (0.45, 0.45, 0.50, 0.9) if zero else (0.22, 0.22, 0.25, 0.9))

    # 曲线本身。逐段画（`None` 处断开——算不出来的地方不连线）
    colour = _CONFIDENCE_COLOR.get(
        plot.confidence, _CONFIDENCE_COLOR[_expr.CONFIDENCE_CONFIRMED])
    for segment in plot.segments:
        lines([(x0 + nx * width, y0 + ny * height) for nx, ny in segment],
              colour, 2.0 * scale)

    # 当前帧游标：面板读数用的就是 `frame_current`，两处指同一个 TIMER
    frame = context.scene.frame_current
    if plot.x0 <= frame <= plot.x1:
        cx = x0 + plot.norm_x(frame) * width
        lines([(cx, y0), (cx, y1)], (1.0, 1.0, 1.0, 0.35))

    gpu.state.blend_set("NONE")
    gpu.state.line_width_set(1.0)

    _draw_hud_text(plot, x0, y0, x1, y1, pad, scale, colour)


def _draw_hud_text(plot, x0, y0, x1, y1, pad, scale, colour) -> None:
    """轴标签 + 曲线名 + 置信度角标。**横纵轴的边界数值必须标出来**——HUD 没有缩放平移，
    这些数字就是判断量级的唯一依据。"""
    font = 0
    blf.size(font, 11 * scale)

    def text(tx, ty, content, rgba=(0.82, 0.82, 0.85, 1.0)):
        blf.color(font, *rgba)
        blf.position(font, tx, ty, 0)
        blf.draw(font, content)

    text(x0, y1 + pad * 0.25, plot.label, colour)
    conf_key = _CONFIDENCE_KEY.get(plot.confidence)
    if conf_key and plot.confidence != _expr.CONFIDENCE_CONFIRMED:
        text(x0 + blf.dimensions(font, plot.label)[0] + 8 * scale,
             y1 + pad * 0.25, "[%s]" % T(conf_key), colour)

    text(x1 + 4 * scale, y1 - 4 * scale, _plot.format_tick(plot.y1))
    text(x1 + 4 * scale, y0, _plot.format_tick(plot.y0))
    text(x0, y0 - pad * 0.6, "TIMER %s" % _plot.format_tick(plot.x0))
    right = _plot.format_tick(plot.x1)
    text(x1 - blf.dimensions(font, right)[0], y0 - pad * 0.6, right)

    if plot.gap_count:
        text(x0, y0 - pad * 1.2,
             T("expr.hud.gaps") % plot.gap_count, (1.0, 0.55, 0.45, 1.0))


# ---------------------------------------------------------------------------
# 面板
# ---------------------------------------------------------------------------

def draw_preview(layout, context, obj) -> None:
    """公式数值那一段：活动公式的当前帧读数 + HUD 开关 + 实况提示。

    **只看活动那一条**（和结构编辑器一致）。要对比同一个 attribute 的两条公式，切一下
    上面那个列表的选中项。
    """
    curve = expr_edit.active_curve(context)
    if curve is None:
        return
    box = layout.box()
    frame = context.scene.frame_current
    variables = build_variables(context, obj, float(frame), curve.formula)
    value, notes = evaluate_curve(curve, variables, context)

    row = box.row(align=True)
    row.label(text="%s (TIMER = %d)" % (T("expr.preview"), frame), translate=False)
    if value is None:
        row.label(text=T("expr.preview.failed"), icon="ERROR", translate=False)
    else:
        row.label(text="%.4f" % value, translate=False)

    row = box.row(align=True)
    row.prop(context.scene, "efx_re_expr_hud", text=T("expr.hud.toggle"), toggle=True)
    row.prop(context.scene, "efx_re_expr_preview_frames", text=T("expr.preview.frames"))

    if _DRAW_ERROR[0]:
        box.label(text=_DRAW_ERROR[0], icon="ERROR", translate=False)
    for note in notes:
        box.label(text=note, icon="ERROR", translate=False)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def _remove_handlers() -> None:
    while _HANDLERS:
        handle = _HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except Exception:                               # noqa: BLE001
            pass


def register():
    bpy.types.Scene.efx_re_expr_preview_frames = IntProperty(
        name="Frames", default=120, min=1, max=3600,
        description="曲线图采样多少帧（TIMER 从 0 走到这个值）",
    )
    bpy.types.Scene.efx_re_expr_hud = BoolProperty(
        name="Curve HUD", default=False,
        description="在 3D 视口左下角画当前公式的曲线图",
    )
    _remove_handlers()
    _HANDLERS.append(bpy.types.SpaceView3D.draw_handler_add(
        _draw_hud, (), "WINDOW", "POST_PIXEL"))


def unregister():
    _remove_handlers()
    del bpy.types.Scene.efx_re_expr_hud
    del bpy.types.Scene.efx_re_expr_preview_frames
