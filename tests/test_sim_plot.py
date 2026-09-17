# -*- coding: utf-8 -*-
"""
tests/test_sim_plot.py —— `efx_sim/plot.py`（公式曲线的绘制几何）单测

    python -m unittest discover -s tests

这一层是视口 HUD 曲线图的几何来源。**HUD 的 `gpu`/`blf` 绘制在 `--background` 下跑不到**
（CLAUDE.md 验证纪律），所以把"算成什么形状"全部挤到这个零 bpy 模块里，让门禁盲区
只剩"把点交给 shader"那十几行。

按验证纪律，每条断言都对应一个真实故障模式，且都注入过确认会 FAIL：

- 退化区间不撑开（常量公式 `lo == hi`）-> 纵轴跨度是 0，归一化时除零 / 整条线画在边框上；
- 算不出来的帧被当成 0 连进折线 -> 图上凭空多一段公式根本没有的线（铁律 #2 的画图版）；
- 刻度不取整（直接 `span / n`）-> 轴标签变成 `63.3333`、`126.667` 这种没法读的数；
- `format_tick` 用 `%f` -> `190` 显示成 `190.000000`，HUD 那点宽度立刻不够。
"""

import math
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import plot  # noqa: E402


def _series(values, label="probe", **kw):
    return plot.Series(label, list(range(len(values))), values, **kw)


class TestNiceStep(unittest.TestCase):
    def test_picks_1_2_5_decades(self):
        self.assertEqual(plot.nice_step(4.0, 4), 1.0)
        self.assertEqual(plot.nice_step(8.0, 4), 2.0)
        self.assertEqual(plot.nice_step(20.0, 4), 5.0)
        self.assertEqual(plot.nice_step(40.0, 4), 10.0)
        self.assertEqual(plot.nice_step(0.4, 4), 0.1)

    def test_never_returns_zero(self):
        """返回 0 的话归一化就会除零。跨度非法时必须给一个能用的值。"""
        for span in (0.0, -1.0, float("inf"), float("nan")):
            self.assertEqual(plot.nice_step(span), 1.0)


class TestNiceBounds(unittest.TestCase):
    def test_expands_to_tick_multiples(self):
        y0, y1, step = plot.nice_bounds(-30.0, 190.0)
        self.assertLessEqual(y0, -30.0)
        self.assertGreaterEqual(y1, 190.0)
        self.assertEqual(y0 % step, 0.0)
        self.assertEqual(y1 % step, 0.0)

    def test_constant_series_gets_a_real_span(self):
        """常量公式（`lo == hi`）必须撑开——不撑开的话跨度是 0，线会贴在边框上。"""
        y0, y1, _s = plot.nice_bounds(5.0, 5.0)
        self.assertLess(y0, 5.0)
        self.assertGreater(y1, 5.0)

    def test_constant_zero_series(self):
        y0, y1, _s = plot.nice_bounds(0.0, 0.0)
        self.assertLess(y0, 0.0)
        self.assertGreater(y1, 0.0)

    def test_non_finite_falls_back(self):
        for lo, hi in ((float("nan"), 1.0), (0.0, float("inf")), (None, 1.0)):
            y0, y1, step = plot.nice_bounds(lo, hi)
            self.assertTrue(math.isfinite(y0) and math.isfinite(y1) and step > 0)

    def test_reversed_input_is_swapped(self):
        self.assertEqual(plot.nice_bounds(190.0, -30.0)[:2],
                         plot.nice_bounds(-30.0, 190.0)[:2])


class TestFormatTick(unittest.TestCase):
    def test_no_trailing_zeros(self):
        self.assertEqual(plot.format_tick(190.0), "190")
        self.assertEqual(plot.format_tick(-30.0), "-30")
        self.assertEqual(plot.format_tick(0.0), "0")
        self.assertEqual(plot.format_tick(0.5), "0.5")
        self.assertEqual(plot.format_tick(0.0025), "0.0025")

    def test_extremes_use_exponent(self):
        self.assertEqual(plot.format_tick(1e6), "1e+06")
        self.assertEqual(plot.format_tick(1e-9), "1e-09")

    def test_non_finite(self):
        self.assertEqual(plot.format_tick(float("nan")), "?")
        self.assertEqual(plot.format_tick(None), "?")


class TestBuild(unittest.TestCase):
    def test_real_formula_shape(self):
        """用户报告的那条 rotationX：12 帧内 190 -> -30，之后继续外推。"""
        values = [190.0 - 220.0 * (f / 12.0) for f in range(25)]
        p = plot.build(_series(values))
        self.assertIsNotNone(p)
        self.assertEqual((p.x0, p.x1), (0.0, 24.0))
        self.assertLessEqual(p.y0, min(values))
        self.assertGreaterEqual(p.y1, max(values))
        self.assertEqual(len(p.segments), 1)
        self.assertEqual(len(p.segments[0]), 25)
        # 归一化边界：最大值贴上沿、最小值贴下沿之间
        xs = [x for x, _y in p.segments[0]]
        ys = [y for _x, y in p.segments[0]]
        self.assertAlmostEqual(min(xs), 0.0)
        self.assertAlmostEqual(max(xs), 1.0)
        self.assertTrue(all(-1e-9 <= y <= 1.0 + 1e-9 for y in ys))

    def test_gaps_break_the_polyline(self):
        """算不出来的帧必须**断开**，不能连成一条线——那等于替公式编数据。"""
        p = plot.build(_series([1.0, 2.0, None, None, 3.0, 4.0]))
        self.assertEqual(len(p.segments), 2)
        self.assertEqual([len(s) for s in p.segments], [2, 2])
        self.assertEqual(p.gap_count, 2)

    def test_non_finite_values_count_as_gaps(self):
        p = plot.build(_series([1.0, float("nan"), float("inf"), 2.0]))
        self.assertEqual(p.gap_count, 2)
        self.assertEqual(len(p.segments), 2)

    def test_all_unevaluable_returns_none(self):
        """一个有限值都没有 -> 返回 None，绘制层显示"画不出来"而不是一条平在 0 的假线。"""
        self.assertIsNone(plot.build(_series([None, None, None])))
        self.assertIsNone(plot.build(_series([])))

    def test_constant_series_is_drawable(self):
        p = plot.build(_series([7.0] * 5))
        self.assertIsNotNone(p)
        self.assertGreater(p.y1, p.y0)
        ys = [y for _x, y in p.segments[0]]
        self.assertTrue(all(0.0 < y < 1.0 for y in ys))     # 不贴边框

    def test_single_sample_does_not_divide_by_zero(self):
        p = plot.build(_series([3.0]))
        self.assertIsNotNone(p)
        self.assertGreater(p.x1, p.x0)

    def test_ticks_are_inside_bounds(self):
        p = plot.build(_series([190.0 - 220.0 * (f / 12.0) for f in range(25)]))
        self.assertTrue(all(p.y0 - 1e-9 <= t <= p.y1 + 1e-9 for t in p.y_ticks))
        self.assertGreaterEqual(len(p.y_ticks), 2)

    def test_metadata_is_carried_through(self):
        """置信度和 note 必须传到绘制层——那是 F-Curve 那条路做不到、GPU 这条路的理由。"""
        s = _series([1.0, 2.0], label="rotationX",
                    notes=["公式用到未确认语义的函数 Unary10"], confidence="unknown")
        p = plot.build(s)
        self.assertEqual(p.label, "rotationX")
        self.assertEqual(p.confidence, "unknown")
        self.assertEqual(p.notes, ["公式用到未确认语义的函数 Unary10"])


class TestSample(unittest.TestCase):
    def test_collects_values_and_dedupes_notes(self):
        def evaluate_at(frame):
            return (frame * 2.0, ["note A"] if frame else ["note A", "note B"])

        values, notes = plot.sample(evaluate_at, [0, 1, 2])
        self.assertEqual(values, [0.0, 2.0, 4.0])
        self.assertEqual(notes, ["note A", "note B"])

    def test_none_values_pass_through(self):
        values, notes = plot.sample(lambda f: (None, []), [0, 1])
        self.assertEqual(values, [None, None])
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
