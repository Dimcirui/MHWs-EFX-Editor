# -*- coding: utf-8 -*-
"""
efx_sim/plot.py —— 把一条采样序列变成"可以直接喂给 GPU 的折线几何"

`blender_efx_re/expr_preview.py` 在 3D 视口里用 `gpu` + `blf` 画 Expression 公式的曲线。
**`--background` 下没有 GPU 上下文，那条绘制路径门禁永远跑不到**（CLAUDE.md 验证纪律），
所以这里照 `sim_preview` 已有的分法把两层拆开：

- **本模块（几何层）**：采样、自动缩放、刻度选取、数值→归一化坐标映射、断点分段。
  纯数据进、纯数据出，`python -m unittest discover -s tests` 全覆盖。
- **`expr_preview` 的 `_draw_hud()`（绘制层）**：只负责"把这些点和这些字符串画出来"。
  真正测不到的就剩这十几行。

为什么放在 `efx_sim/` 而不是 `blender_efx_re/`
----------------------------------------------
和这个包本身放在仓库根的理由一样（见 `efx_sim/__init__.py`）：`blender_efx_re/__init__.py`
会 import bpy，放在它下面的模块脱离 Blender 就 import 不动，单测无从谈起。刻度取整、退化
区间（全部取值相同 / 一个有限值都没有）这类边界条件恰恰是最该单测的东西，为了能测它，
宁可让这个模块在包主题上略微出格。**它不参与模拟**，`Simulator` 不 import 它。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from __future__ import annotations

import math

#: 纵轴期望的刻度条数。只是个目标值，`nice_step()` 取整之后实际条数会在它附近浮动。
_TARGET_Y_TICKS = 4


class Series(object):
    """一条采样序列。`values` 里的 `None` 表示那一帧算不出来（**保留成空洞，不插值补上**
    ——把算不出来的地方连成一条线就是画图工具在替公式编数据）。"""

    __slots__ = ("label", "frames", "values", "notes", "confidence")

    def __init__(self, label, frames, values, notes=None, confidence=None):
        self.label = label
        self.frames = list(frames)
        self.values = list(values)
        self.notes = list(notes or [])
        #: 这条曲线里最不可信的那一档（`efx_sim.expr.CONFIDENCE_*`），绘制层按它上色。
        #: **这是 F-Curve 那条路做不到的事**：动画通道没有地方挂"这条线只是推断"。
        self.confidence = confidence


class Plot(object):
    """绘制层要的全部东西。坐标一律**归一化到 `[0, 1]²`**（左下角原点），绘制层只做
    一次线性映射到像素矩形，这样几何层不需要知道 HUD 摆在屏幕哪儿、多大。"""

    __slots__ = ("x0", "x1", "y0", "y1", "y_step", "x_ticks", "y_ticks",
                 "segments", "gap_count", "label", "confidence", "notes")

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw.get(name))

    def norm_x(self, frame):
        span = self.x1 - self.x0
        return 0.0 if span == 0 else (frame - self.x0) / span

    def norm_y(self, value):
        span = self.y1 - self.y0
        return 0.5 if span == 0 else (value - self.y0) / span


def sample(evaluate_at, frames):
    """`evaluate_at(frame) -> (值 或 None, notes)` 逐帧调一遍，收成 `(values, notes)`。

    `evaluate_at` 由调用方提供，所以这个模块不需要知道变量表、`EvalContext`、Blender
    场景这些东西——**这是它能被单测的全部原因**，别为了省事把求值搬进来。
    """
    values = []
    notes = []
    for frame in frames:
        value, frame_notes = evaluate_at(frame)
        values.append(value)
        for note in frame_notes or ():
            if note not in notes:
                notes.append(note)
    return values, notes


def nice_step(span, target_ticks=_TARGET_Y_TICKS):
    """把一个跨度切成"人看着顺眼"的刻度步长：1 / 2 / 5 × 10^n。

    `span <= 0` 或非有限值返回 `1.0`——调用方那边已经把退化区间撑开过了，这里再兜一层
    是为了任何时候都不返回 0（除以它会炸）。
    """
    if not (span > 0) or math.isinf(span) or math.isnan(span):
        return 1.0
    raw = span / max(int(target_ticks), 1)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    for mult in (1.0, 2.0, 5.0):
        if raw <= mult * magnitude:
            return mult * magnitude
    return 10.0 * magnitude


def nice_bounds(lo, hi, target_ticks=_TARGET_Y_TICKS):
    """把 `[lo, hi]` 向外扩到刻度整数倍，返回 `(y0, y1, step)`。

    三种退化情形都在这里处理掉，绘制层不用再判：
    - `lo == hi`（常量公式）：按量级撑开一圈，0 的话取 `[-1, 1]`；
    - 非有限值（inf/nan 混进来）：退回 `[-1, 1]`；
    - `lo > hi`（调用方传反了）：交换。
    """
    if lo is None or hi is None or not math.isfinite(lo) or not math.isfinite(hi):
        return -1.0, 1.0, 1.0
    if lo > hi:
        lo, hi = hi, lo
    if lo == hi:
        pad = abs(lo) * 0.1 if lo else 1.0
        lo, hi = lo - pad, hi + pad
    step = nice_step(hi - lo, target_ticks)
    y0 = math.floor(lo / step) * step
    y1 = math.ceil(hi / step) * step
    if y0 == y1:                       # 极端浮点情形，别让跨度是 0
        y1 = y0 + step
    return y0, y1, step


def ticks_between(y0, y1, step):
    """`[y0, y1]` 上的刻度值。step 不整除时按 y0 起步累加，末尾不越界。"""
    if step <= 0:
        return [y0, y1]
    out = []
    count = int(round((y1 - y0) / step))
    for i in range(count + 1):
        out.append(y0 + i * step)
    return out


def format_tick(value):
    """刻度文字。`190` 不写成 `190.000000`，`0.0025` 不写成 `0.00`。"""
    if value is None or not math.isfinite(value):
        return "?"
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1000 or magnitude < 0.001:
        return "%.3g" % value
    text = "%.4f" % value
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def build(series, target_ticks=_TARGET_Y_TICKS):
    """`Series` -> `Plot`。一个有限取值都没有时返回 `None`（绘制层据此显示"画不出来"，
    而不是画一条平在 0 上的假线）。"""
    finite = [v for v in series.values if v is not None and math.isfinite(v)]
    if not series.frames or not finite:
        return None

    x0, x1 = float(series.frames[0]), float(series.frames[-1])
    if x1 == x0:
        x1 = x0 + 1.0
    y0, y1, step = nice_bounds(min(finite), max(finite), target_ticks)

    plot = Plot(x0=x0, x1=x1, y0=y0, y1=y1, y_step=step,
                y_ticks=ticks_between(y0, y1, step),
                x_ticks=[x0, x1],
                label=series.label, confidence=series.confidence,
                notes=list(series.notes))

    segments = []
    current = []
    gap_count = 0
    for frame, value in zip(series.frames, series.values):
        if value is None or not math.isfinite(value):
            if current:
                segments.append(current)
                current = []
            gap_count += 1
            continue
        current.append((plot.norm_x(float(frame)), plot.norm_y(float(value))))
    if current:
        segments.append(current)

    plot.segments = segments
    plot.gap_count = gap_count
    return plot
