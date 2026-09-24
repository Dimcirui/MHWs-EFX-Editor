# -*- coding: utf-8 -*-
"""
tests/test_sim_expr.py —— `efx_sim/expr.py`（Expression 公式求值）+ `Simulator` 接入的单测

    python -m unittest discover -s tests

按 CLAUDE.md 验证纪律：每条断言都对应一个真实故障模式，且都实际注入过验证会 FAIL：

- `Clamp` 假设参数顺序是 `(x, min, max)` 而不是 `min()/max()` 夹紧——全语料的
  `Clamp(x, 6, 3)` 这种"大的在前"写法会直接夹出空区间；
- `ExpressionAssignType` 的合成如果拿"上一帧被改过的值"当基准而不是导入时的原始值，
  `Add`/`Multiply` 会逐帧发散；
- 未知函数（`Unary10` 等）如果不做 note，UI 没法如实展示"这条曲线语义未确认"。
"""

import math
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import (EvalContext, ExprError, SimConfig, Simulator, Vec3,  # noqa: E402
                     expr_evaluate, expr_parse)
from efx_sim import expr as expr  # noqa: E402
from efx_sim.expr import call_confidence as expr_call_confidence  # noqa: E402
from efx_sim.simulator import _pick_primary_secondary_key, _resolve_expr_target  # noqa: E402


def _ev(formula, variables=None, policy="identity"):
    notes = []
    ctx = EvalContext(variables or {}, policy, notes)
    result = expr_evaluate(expr_parse(formula), ctx)
    return result, notes


class TestSelfConsistencyIdentities(unittest.TestCase):
    """**用已确认的语义搭恒等式，正确时必须恒为 0。**

    这是整张语义表的交叉校验网：每条恒等式同时用到好几个运算/函数，**任何一个读法被改
    动，至少有一条会破**。而且这些公式是可以直接拿进游戏跑的——实机画出一条死平在 0
    的线，就等于一次端到端确认（单测这边只能证明"文本构造和我们的表自洽"）。

    放大系数 20（`20 + <差>` 就是 ×20）是为了实机判读：0.01 的偏差会变成 0.2 米。
    这个"放大残差"的手法最早是为了定 `Func21` 的插值方式引入的，见
    `expr._eval_func21()`。

    ⚠ 一条恒等式**同时**覆盖多个语义，所以它只能证伪、不能定位——某条不为 0 时要拆开
    逐项测。反过来，全部为 0 是很强的联合证据。
    """

    #: 从 -1 线性扫到 +1（实机时 Z 轴放 `-Lerp(Clamp(TIMER, 60, 0), 2, -1)` 当横轴）
    SWEEP = "Lerp(-1, 1, SmoothStep(0, 60, TIMER))"

    def _assert_flat_zero(self, formula, places=5):
        for i in range(13):
            got, _ = _ev(formula, {"TIMER": 60.0 * i / 12.0})
            self.assertAlmostEqual(got, 0.0, places=places,
                                   msg="%s @ 采样点 %d/12" % (formula, i))

    def test_pow_of_pow_cancels_against_abs(self):
        """`pow(pow(x, 2), 1/2) == |x|`。覆盖：`Func20`=pow、`Max(`=pow（操作码 0）、
        `-`=除（用来写 1/2）、`Unary9`=abs、`Min(`=减、`+`=乘。

        **这条是"两个 pow 入口互相抵消"**：操作码 0（中缀幂）和 `Func20`（函数幂）
        算的是同一件事，一个平方、一个开平方，抵消回 `|x|`。"""
        self._assert_flat_zero(
            "(20 * ((Pow(%s, 2) ^ (1 / 2)) - Abs(%s)))" % (self.SWEEP, self.SWEEP))

    def test_pythagorean_identity(self):
        """`sin² + cos² == 1`。覆盖：`Unary0`=sin、`Unary1`=cos（**弧度**）、
        `Max(`=pow（平方）、`/`=加、`Min(`=减。一条公式验五个读法。"""
        self._assert_flat_zero(
            "(20 * (((Sin(%s) ^ 2) + (Cos(%s) ^ 2)) - 1))"
            % (self.SWEEP, self.SWEEP))

    def test_log_exp_are_inverses(self):
        """`ln(e^x) == x`。覆盖 `Unary6`=ln、`Unary8`=exp。"""
        self._assert_flat_zero(
            "(20 * (Log(Exp(%s)) - %s))" % (self.SWEEP, self.SWEEP))

    def test_log10_base_against_exp(self):
        """`log10(e^x) == x·log10(e)`。覆盖 `Unary7`=log10、`Unary8`=exp、`+`=乘。
        这条同时钉住 log 的**底数**（换成 ln 会差 2.303 倍）。"""
        self._assert_flat_zero(
            "(20 * (Log10(Exp(%s)) - (0.4342945 * %s)))" % (self.SWEEP, self.SWEEP))

    def test_floor_and_ceil_are_reflections(self):
        """`floor(x) + ceil(-x) == 0`。覆盖 `Unary4`=floor、`Unary5`=ceil、`/`=加、
        一元负号。`trunc` 读法在这条下**不成立**（`trunc(x) + trunc(-x)` 也是 0，
        但 `floor` 和 `ceil` 配对才在负半段对得上）。"""
        self._assert_flat_zero(
            "(20 * (Floor(%s) + Ceil(-%s)))" % (self.SWEEP, self.SWEEP))

    def test_saturate_equals_min_max_composition(self):
        """`saturate(x) == min(max(x, 0), 1)`。覆盖 `Unary10`=saturate、`Func18`=min、
        `Func19`=max。"""
        self._assert_flat_zero(
            "(20 * (Saturate(%s) - Min(Max(%s, 0), 1)))" % (self.SWEEP, self.SWEEP))

    def test_degree_and_radian_sin_agree(self):
        """`sin°(x) == sin(x · π/180)`。覆盖 `Unary11`=角度制 sin、`Unary0`=弧度 sin、
        `+`=乘。"""
        self._assert_flat_zero(
            "(20 * (SinDeg(%s) - Sin((0.0174533 * %s))))" % (self.SWEEP, self.SWEEP))

    def test_asin_undoes_sin(self):
        """`asin(sin(x)) == x`（x 在 ±π/2 内）。覆盖 `Unary2`=asin、`Unary0`=sin。"""
        sweep = "Lerp(-1.5, 1.5, SmoothStep(0, 60, TIMER))"
        self._assert_flat_zero(
            "(20 * (Asin(Sin(%s)) - %s))" % (sweep, sweep))

    def test_func21_is_the_un_eased_twin_of_lerp_clamp(self):
        """⚠ **`Func21` 和写开的 `Lerp(Clamp(...))` 不相等**——这条恒等式在 2026-09-16
        之前是按"相等"写的，实机跑出来是个单周期正弦，追下去发现 **`Clamp` 带 smoothstep
        缓动、`Func21` 的重映射是线性的**（`expr._eval_func21()` 的判据表）。
        两者之差**就是**那层缓动，所以正确的恒等式是"差 == smoothstep 残差"：

            Lerp(Clamp(t,hi,lo),a,b) - Func21(a,b,hi,lo,t) == (a-b) * (smoothstep(x) - x)

        这条同时覆盖 `Func21`（线性）、`Clamp`（smoothstep）、`Lerp`（线性）三个读法，
        任何一个改了它都会破。"""
        # 参考：smoothstep(x) - x，用已确认语义搭（x = TIMER/60）
        # smoothstep(x) = x^2*(3-2x) -> `(PowOp(2, x) * ((2 * x) - 3))`
        residual = "((((TIMER / 60) ^ 2) * (3 - (2 * (TIMER / 60)))) - (TIMER / 60))"
        formula = ("(20 * ((Lerp(0, 1, SmoothStep(0, 60, TIMER)) - "
                   "Remap(TIMER, 0, 60, 0, 1)) - %s))" % residual)
        self._assert_flat_zero(formula)

    def test_lerp_and_clamp_are_linear_and_eased_respectively(self):
        """把两者分别对**不经过任何待测函数**的线性基准（`TIMER/100`）对拍——
        这是 2026-09-16 那一轮把悬案解开的关键：以前 `Lerp(Clamp(..))` 要么当时间轴、
        要么和自己比，缓动整项抵消，所以一直测不出来。

        `Lerp` 纹丝不动（线性）、`Clamp` 是 S 形摆动（带缓动）。"""
        # Lerp 对线性基准：恒等
        self._assert_flat_zero("(20 * (Lerp(0, 1, (TIMER / 100)) - (TIMER / 100)))")
        # Clamp 对线性基准：**不为 0**，差值正好是 smoothstep 残差
        for i in range(1, 12):
            timer = 100.0 * i / 12.0
            x = timer / 100.0
            got, _ = _ev("(SmoothStep(0, 100, TIMER) - (TIMER / 100))", {"TIMER": timer})
            self.assertAlmostEqual(got, x * x * (3 - 2 * x) - x, places=6,
                                   msg="TIMER=%.1f" % timer)
        # 偏离最大的地方在四分位点（±0.096），**中点和两端是 smoothstep 的不动点、
        # 残差本来就是 0**——只在四分位点断言"确实不为 0"，不然会误判
        for timer, want in ((25.0, -0.09375), (75.0, 0.09375)):
            got, _ = _ev("(SmoothStep(0, 100, TIMER) - (TIMER / 100))", {"TIMER": timer})
            self.assertAlmostEqual(got, want, places=6, msg="TIMER=%.1f" % timer)


class TestBinaryOperatorSemantics(unittest.TestCase):
    """六个二元操作码的实机语义。**名字上游 `a96e1d9` 已经改对了**（我们提的 issue），
    但 `ToString()` 的**操作数顺序仍然是反的**，所以 `/` `-` `Mod(` `PowOp(` 四个的
    左右和数学写法相反。下面的读数是 2026-09-16 用旧记法测的，已换算成新记法：

    ======  ============  ===========  =====================
    操作码  文本写法      vendor       真实语义
    ======  ============  ===========  =====================
    0       ``Max(a,b)``  Max          ``pow(b, a)``
    1       ``a + b``     Add          ``a * b``
    2       ``a - b``     Sub          ``b / a``
    3       ``a * b``     Mul          ``fmod(b, a)``
    4       ``a / b``     Div          ``a + b``
    5       ``Min(a,b)``  Min          ``b - a``
    ======  ============  ===========  =====================

    测法：Y 轴 `Lerp(Clamp(TIMER, 15, 0), 0.5, -1)` 当时间轴、Z 轴填被测公式、单粒子
    `TypeRibbonFollow` 的轨迹当示波器，读数靠"直接填常量"对照校准。下面每条测试用的
    都是实机读数原值。逐条依据见 `expr._eval_binary_operator()` 和
    docs/EXPRESSION_SEMANTICS.md 第 9 节。

    vendor 在 `BinaryExpressionOperator`（`ExpressionTree.cs:11`）上原话是 "Am not 100%
    sure on the exact operators for 1-4 but they seem reasonable"——实际连它没打问号的
    0（Max）和 5（Min）也错了。
    """

    def test_opcode1_plus_is_multiplication(self):
        """实机 `(a, b) -> 结果`：``(1,0)->0``、``(0,1)->0``、``(1,1)->1``、
        ``(1,2)->2``、``(2,1)->2``。对称，加法在 ``(1,0)`` 就该给 1。"""
        for (a, b), want in (((1, 0), 0.0), ((0, 1), 0.0), ((1, 1), 1.0),
                             ((1, 2), 2.0), ((2, 1), 2.0)):
            self.assertEqual(_ev("(%d * %d)" % (a, b))[0], want, "(%d * %d)" % (a, b))

    def test_opcode2_is_division(self):
        """实机：``2/1->2`` 而 ``1/2->0.5``（非交换），``1/1->1``，``0/1->0``；
        ``1/0->0`` 说明**除零按 0**——这是引擎实测行为，不只是我们兜底。"""
        for (a, b), want in (((2, 1), 2.0), ((1, 2), 0.5), ((1, 1), 1.0),
                             ((0, 1), 0.0), ((1, 0), 0.0)):
            self.assertEqual(_ev("(%d / %d)" % (a, b))[0], want, "(%d / %d)" % (a, b))

    def test_opcode4_is_addition(self):
        """实机：``(1,0)->1``、``(1,1)->2``、``(2,0)->2``、``(0,2)->2``。对称。"""
        for (a, b), want in (((1, 0), 1.0), ((1, 1), 2.0), ((2, 0), 2.0), ((0, 2), 2.0)):
            self.assertEqual(_ev("(%d + %d)" % (a, b))[0], want, "(%d + %d)" % (a, b))

    def test_opcode5_is_subtraction(self):
        """实机：``0-1->-1``、``1-0->1``、``1-1->0``、``2-1->1``、``1-2->-1``。"""
        for (a, b), want in (((0, 1), -1.0), ((1, 0), 1.0), ((1, 1), 0.0),
                             ((2, 1), 1.0), ((1, 2), -1.0)):
            self.assertEqual(_ev("(%d - %d)" % (a, b))[0], want, "(%d - %d)" % (a, b))

    def test_opcode0_is_power(self):
        """实机 ``0^1->0``、``1^0->1``、``1^1->1``、``2^1->2``、``1^2->1``。这五点
        ``pow`` 和"直接返回底数"都满足，后来靠 `Max(2, <扫描>)`（当时的写法）画出 U 形
        抛物线排掉了后者（docs/EXPRESSION_SEMANTICS.md 11.6）。"""
        for (a, b), want in (((0, 1), 0.0), ((1, 0), 1.0), ((1, 1), 1.0),
                             ((2, 1), 2.0), ((1, 2), 1.0)):
            self.assertEqual(_ev("(%d ^ %d)" % (a, b))[0], want, "(%d ^ %d)" % (a, b))
        # 底在左：这一对把 `pow(a,b)` 和 `pow(b,a)` 分开
        self.assertEqual(_ev("(3 ^ 2)")[0], 9.0)
        self.assertEqual(_ev("(2 ^ 3)")[0], 8.0)
        # U 形：负底数平方后非负
        self.assertEqual(_ev("(-1 ^ 2)")[0], 1.0)

    def test_unary_negation_is_the_only_one_vendor_got_right(self):
        """实机：``-0 -> 0``、``-1 -> -1``、``-2 -> -2``。"""
        self.assertEqual(_ev("-0")[0], 0.0)
        self.assertEqual(_ev("-1")[0], -1.0)
        self.assertEqual(_ev("-2")[0], -2.0)

    def test_is_not_commutative(self):
        """第一个把"基础算术运算"整类排除掉的观察：乘/加/`Min`/`Max` 全是交换的。"""
        self.assertAlmostEqual(_ev("(0.5 % 0.4)")[0], 0.1, places=6)
        self.assertAlmostEqual(_ev("(0.4 % 0.5)")[0], 0.4, places=6)

    def test_live_confirmed_non_monotonic_table(self):
        """决定性的一组定量实测：`X * 1` == `fmod(1, X)`，随 X 变化是**非单调**锯齿。
        实机跑了 X=0.6/0.5/0.4/0.3 四个点，读数 0.4/0/0.2/0.1 全中——任何单调的二元运算
        （含乘法：0.6/0.5/0.4/0.3）都给不出"降到 0 再升回 0.2 再降到 0.1"这个形状。"""
        for modulus, expected in ((0.6, 0.4), (0.5, 0.0), (0.4, 0.2), (0.3, 0.1)):
            self.assertAlmostEqual(_ev("(1 %% %r)" % modulus)[0], expected, places=6,
                                   msg="X=%r" % modulus)

    def test_same_operands_give_zero(self):
        """`0.5 * 0.5` 实机是一条 Z 恒定的竖直线，值 0。"""
        self.assertEqual(_ev("(0.5 % 0.5)")[0], 0.0)

    def test_sign_follows_dividend_like_c_fmod_not_python_modulo(self):
        """必须用 `math.fmod`（余数符号跟被除数），**不能用 Python 的 `%`**（向下取整、
        余数符号跟模数）。实机判据：`2 * sweep` 里 `sweep` 从 -1 扫到 0.5，轨迹和"不加这
        一项"完全一样（斜率 -1 的直线），即负半段原样透传；Python 的 `%` 会把 -1 折成
        +1，轨迹中途会跳一下，实测没有。"""
        self.assertAlmostEqual(_ev("(-1 % 2)")[0], -1.0, places=6)
        self.assertAlmostEqual(_ev("(-0.25 % 2)")[0], -0.25, places=6)
        self.assertAlmostEqual(-1.0 % 2, 1.0, places=6)   # 对照：Python `%` 的答案是错的

    def test_passthrough_when_dividend_is_smaller_than_modulus(self):
        """`|B| < A` 时原样返回 B。这条解释了最早那组 Func21 测试为什么什么都没测到：
        `Func21(...) * 0.01` 是 `fmod(0.01, F)`，F 只要大于 0.01 就恒等于 0.01，
        Func21 的信息一个字节都没进到结果里。"""
        self.assertAlmostEqual(_ev("(0.01 % 90)")[0], 0.01, places=6)
        self.assertAlmostEqual(_ev("(1 % 90)")[0], 1.0, places=6)

    def test_zero_modulus_is_noted_not_nan(self):
        """模数为 0 时 `fmod` 是 NaN——NaN 会顺着位置字段传进视口/导出，按 0 处理并记 note
        （和除零那条同一套处理）。"""
        value, notes = _ev("(1 % 0)")
        self.assertEqual(value, 0.0)
        self.assertTrue(any("取模" in n for n in notes), notes)

    def test_real_corpus_examples_translate_to_textbook_idioms(self):
        """整张表最强的旁证：按新读法把真实公式翻译成常规记法，全是教科书写法。

        - `Min(30, (45 * TIMER))` = ``fmod(TIMER, 45) - 30``：每 45 帧循环一次的
          -30→15 锯齿（配对的 `Min(15, ...)` 是同一个锯齿减 15），喂给 `Unary10` 做
          周期颜色脉冲。
        - `Min(Clamp(TIMER, 100, 20), 1)` = ``1 - Clamp(TIMER, 100, 20)``：全语料出现
          95 次，真身是最常见的**淡出** ``1 - t``（以前被当成"防御性封顶"，还当过
          "Clamp 上界不钳"的证据）。
        - `(1 / (0.1 + X))` = ``1 + 0.1*X``：基准值加一个小扰动。
        """
        for timer, want in ((0, -30.0), (10, -20.0), (44, 14.0), (45, -30.0), (55, -20.0)):
            got, _ = _ev("((TIMER % 45) - 30)", {"TIMER": float(timer)})
            self.assertAlmostEqual(got, want, places=6, msg="TIMER=%d" % timer)
        # 1 - Clamp(...)：TIMER 在 lo 处是 1（完全不透明），到 hi 处降到 0
        self.assertAlmostEqual(
            _ev("(1 - SmoothStep(20, 100, TIMER))", {"TIMER": 20.0})[0], 1.0, places=6)
        self.assertAlmostEqual(
            _ev("(1 - SmoothStep(20, 100, TIMER))", {"TIMER": 100.0})[0], 0.0, places=6)
        self.assertAlmostEqual(
            _ev("(1 - SmoothStep(20, 100, TIMER))", {"TIMER": 60.0})[0], 0.5, places=6)
        # 1 + 0.1*X
        self.assertAlmostEqual(_ev("(1 + (0.1 * X))", {"X": 2.0})[0], 1.2, places=6)


class TestKnownUnaryFunctions(unittest.TestCase):
    """`Unary0/1/4/5/6/8/9/10` 的语义，2026-09-16 实机测出来（`vendor` 只给了编号和一句
    "unary potential candidates: sin/cos/tan/atan2/inverse/…"）。

    **测法的关键是输入要扫 `[-2, 2]`**：只喂 `[0, 1]` 的话 `identity`/`abs`/`saturate`
    三者全等、`floor`/`trunc` 全等、`ceil`/`sign` 全等，前一轮就是卡在这儿。
    逐条原始读数见 `expr._KNOWN_UNARY_EVIDENCE` 和 `_eval_known_unary()` 的 docstring。
    """

    def test_unary0_is_sin_and_unary1_is_cos_in_radians(self):
        """圆测试：`Y = Unary0(6.28319 + Clamp(TIMER,120,0))` / `Z = Unary1(同)`
        （`+` 是乘法 -> `sin/cos(2*pi*t)`）实机画出**半径 1 米的整圆、起点在侧面**。
        起点在侧面 => `Unary0(0) = 0` => `Unary0` 是 sin。圆能闭合还同时证明了吃弧度
        （角度制下 2pi 度只有 6°，只会画出一个点）。"""
        self.assertAlmostEqual(_ev("Sin(0)")[0], 0.0, places=6)
        self.assertAlmostEqual(_ev("Cos(0)")[0], 1.0, places=6)
        self.assertAlmostEqual(_ev("Sin(1.5707963)")[0], 1.0, places=6)
        self.assertAlmostEqual(_ev("Cos(3.1415927)")[0], -1.0, places=6)
        # [-2,2] 宽扫实机读到的两端值（"谷前面一点 / 峰后面一点"）
        self.assertAlmostEqual(_ev("Sin(-2)")[0], -0.9093, places=4)
        self.assertAlmostEqual(_ev("Sin(2)")[0], 0.9093, places=4)
        self.assertAlmostEqual(_ev("Cos(-2)")[0], -0.4161, places=4)
        self.assertAlmostEqual(_ev("Cos(2)")[0], -0.4161, places=4)

    def test_unary4_is_floor_and_unary5_is_ceil(self):
        """实机 `[-2,2]` 宽扫：`Unary4` 的阶梯**第一个完整台阶在 -2**、`Unary5` 在 -1。
        `trunc` 的第一个完整台阶也在 -1（`trunc(-1.9) = -1`），所以"从 -2 起"把
        `Unary4` 的 `trunc` 候选排掉了。"""
        self.assertEqual(_ev("Floor(-1.9)")[0], -2.0)   # trunc 会给 -1
        self.assertEqual(_ev("Floor(-0.5)")[0], -1.0)
        self.assertEqual(_ev("Floor(1.9)")[0], 1.0)
        self.assertEqual(_ev("Ceil(-1.9)")[0], -1.0)
        self.assertEqual(_ev("Ceil(0.1)")[0], 1.0)
        self.assertEqual(_ev("Ceil(1.9)")[0], 2.0)

    def test_unary6_is_ln_and_unary8_is_exp_same_base(self):
        """`Unary8` 的宽扫起点实机是 **0.14** == `e^-2` = 0.1353（`10^-2`=0.01、
        `2^-2`=0.25 都不对）。底数靠复合测试钉死：`Unary6(Unary8(t))` 实机是一条终点
        **恰好 1.0** 的直线 => 两者同底互逆 => `Unary6` 是 `ln`（若 `Unary6` 是 log10
        终点会是 0.434、log2 会是 1.443）。"""
        self.assertAlmostEqual(_ev("Exp(-2)")[0], 0.1353, places=4)
        self.assertAlmostEqual(_ev("Exp(1)")[0], 2.71828, places=5)
        self.assertAlmostEqual(_ev("Log(2.7182818)")[0], 1.0, places=6)
        # 复合恒等：这就是③那次实机测的东西
        for t in (0.25, 0.5, 1.0):
            self.assertAlmostEqual(_ev("Log(Exp(%r))" % t)[0], t, places=6)

    def test_unary6_negative_input_is_noted_not_nan(self):
        value, notes = _ev("Log(-1)")
        self.assertEqual(value, 0.0)
        self.assertTrue(any("Log" in n for n in notes), notes)

    def test_unary9_is_abs(self):
        """实机宽扫画出**直线 V 字**（两段直边）——`abs` 是唯一的直边 V
        （`max(|x|,1)` 是平底 U、`x²`/`cosh` 是曲线）。"""
        self.assertEqual(_ev("Abs(-2)")[0], 2.0)
        self.assertEqual(_ev("Abs(-0.5)")[0], 0.5)
        self.assertEqual(_ev("Abs(2)")[0], 2.0)

    def test_unary10_is_saturate(self):
        """实机宽扫呈 `_/‾`：负半段贴 0、`[0,1]` 线性上升、超过 1 之后停在 1。
        **全语料最高频的未知函数（2063 次）**，语料里 `saturate(0.016*TIMER)`
        （文本 `Unary10((0.016 + TIMER))`）就是"62 帧内淡入"的标准写法，
        同族的 0.032/0.064 正好是 31/16 帧。"""
        self.assertEqual(_ev("Saturate(-2)")[0], 0.0)
        self.assertEqual(_ev("Saturate(-0.001)")[0], 0.0)
        self.assertEqual(_ev("Saturate(0.25)")[0], 0.25)
        self.assertEqual(_ev("Saturate(1)")[0], 1.0)
        self.assertEqual(_ev("Saturate(2)")[0], 1.0)

    def test_corpus_fade_in_idiom(self):
        """`Unary10((0.016 + TIMER))` = `saturate(0.016 * TIMER)`：第 62.5 帧到 1。"""
        f = "Saturate((0.016 * TIMER))"
        self.assertAlmostEqual(_ev(f, {"TIMER": 0.0})[0], 0.0, places=6)
        self.assertAlmostEqual(_ev(f, {"TIMER": 31.25})[0], 0.5, places=6)
        self.assertAlmostEqual(_ev(f, {"TIMER": 62.5})[0], 1.0, places=6)
        self.assertAlmostEqual(_ev(f, {"TIMER": 200.0})[0], 1.0, places=6)

    def test_unary7_is_log10_and_unary11_12_are_degree_trig(self):
        """`Unary7` 的底数靠复合定：`Unary7(Unary8(t))` 实机终点 **0.434** ==
        `log10(e)`（`ln` 会是 1.0、`log2` 会是 1.443）。

        `Unary11`/`Unary12` 是**角度制**的 sin/cos：`[-2,2]` 宽扫时恒 0 / 恒 1
        （`sin(2°)=0.035`、`cos(2°)=0.9994`），把扫描放到 `[-180,180]` 之后实机画出
        完整三角波。语料佐证：`Unary11` 被喂的正是 `Func21(90, 0, hi, 0, TIMER)`
        —— `90` 是**度数**。"""
        self.assertAlmostEqual(_ev("Log10(10)")[0], 1.0, places=6)
        self.assertAlmostEqual(_ev("Log10(Exp(1))")[0], 0.4343, places=4)
        self.assertAlmostEqual(_ev("SinDeg(0)")[0], 0.0, places=6)
        self.assertAlmostEqual(_ev("SinDeg(90)")[0], 1.0, places=6)
        self.assertAlmostEqual(_ev("SinDeg(180)")[0], 0.0, places=6)
        self.assertAlmostEqual(_ev("CosDeg(0)")[0], 1.0, places=6)
        self.assertAlmostEqual(_ev("CosDeg(180)")[0], -1.0, places=6)
        # [-2,2] 宽扫时"看着恒 0 / 恒 1"的原因
        self.assertAlmostEqual(_ev("SinDeg(2)")[0], 0.0349, places=4)
        self.assertAlmostEqual(_ev("CosDeg(2)")[0], 0.9994, places=4)

    def test_unary2_is_asin(self):
        """靠**定量的消失点**定下来的：输入扫 `0 -> 1.4`、Y 整体下移 1 米，实机"升到
        +0.4~0.5 时粒子直接消失"。`asin` 在 x>1 无定义 -> 第 86/120 帧消失、消失前最后
        一个值 1.4416（显示 +0.4416），落在读数区间里。其余候选和现象矛盾：`tan` 第 95
        帧先冲出画面上边界、`atanh` 第 83 帧冲出、`atan` 根本不消失、`acos` 往下走到
        -0.87 才消失。"""
        self.assertAlmostEqual(_ev("Asin(0)")[0], 0.0, places=6)
        self.assertAlmostEqual(_ev("Asin(1)")[0], 1.5708, places=4)
        self.assertAlmostEqual(_ev("Asin(0.5)")[0], 0.5236, places=4)
        # 消失前最后一帧的值（第 85/120 帧，x = 1.4*85/120 = 0.9917）
        self.assertAlmostEqual(_ev("Asin(0.99167)")[0], 1.4416, places=4)
        value, notes = _ev("Asin(1.2)")   # 定义域外：note + 0.0
        self.assertEqual(value, 0.0)
        self.assertTrue(any("Asin" in n for n in notes), notes)

    def test_func20_is_power_with_the_base_on_the_right(self):
        """`Func20(a, b)` == `pow(b, a)` = `b^a`：底数是**右**操作数、指数是**左**操作数
        （和其他非对称运算一致——引擎的第一操作数 = vendor 文本的第二个参数）。

        判据：`Func20(x, 0.5)` 随 `x` 增大单调下降，且把 `x` 扫到 -4 时起点跑到画面外
        很高处（`0.5^-4 = 16`）。**无界**排掉 `atan2(b,a)`（有界 <= pi）；起点为正、
        中途无极点排掉 `b / a`（起点在轴下方、x=0 有极点）。

        ⚠ 它和 `Max(a, b)`（操作码 0）现在读法完全相同，那是个**未解决的疑点**，
        见 `expr._eval_known_binary_func()` 的 docstring。"""
        self.assertAlmostEqual(_ev("Pow(0.5, 2)")[0], 0.25, places=6)
        self.assertAlmostEqual(_ev("Pow(0.5, -4)")[0], 16.0, places=6)
        self.assertAlmostEqual(_ev("Pow(2, 3)")[0], 8.0, places=6)     # 2^3
        self.assertAlmostEqual(_ev("Pow(3, 2)")[0], 9.0, places=6)     # 3^2
        # 语料：Func20(0.01*TIMER, 3) = 3^(0.01*TIMER)，平缓的指数上升
        f = "Pow(3, (0.01 * TIMER))"
        self.assertAlmostEqual(_ev(f, {"TIMER": 0.0})[0], 1.0, places=6)
        self.assertAlmostEqual(_ev(f, {"TIMER": 100.0})[0], 3.0, places=6)

    def test_func18_is_min_and_func19_is_max(self):
        """**真正的 min/max 不在二元操作码里，在函数里**（二元操作码 0~5 是
        幂/乘/除/模/加/减，见 `TestBinaryOperatorsAreAllMislabeled`）。
        别和文本里的 `Min(`/`Max(` 搞混——那两个名字是 vendor 给操作码 5/0 起的，
        实际是减法和幂。

        实机判据：把第一个参数换成从 -1 扫到 +1 的量、第二参固定 0.5，看形状——
        `Func18` 是"斜线升到 +0.5 后变平"（`/‾`）、`Func19` 是"先平在 +0.5、
        后半段继续升到 +1"（`_/`），正好是 min/max 的镜像对；交换两个参数结果不变
        （排掉全部非对称候选）。"""
        self.assertEqual(_ev("Min(0.8, 1.5)")[0], 0.8)
        self.assertEqual(_ev("Min(1.5, 0.8)")[0], 0.8)
        self.assertEqual(_ev("Max(0.8, 1.5)")[0], 1.5)
        self.assertEqual(_ev("Max(1.5, 0.8)")[0], 1.5)
        # 形状：min 在 sweep 越过 0.5 之后变平、max 在之前是平的。
        # ⚠ 扫描量用的 `Clamp` **带 smoothstep 缓动**（2026-09-16 实机，见
        # `expr._eval_clamp()`），所以中间点的数值不是线性插值出来的那几个。
        f18 = "Min(Lerp(-1, 1, SmoothStep(0, 60, TIMER)), 0.5)"
        f19 = "Max(Lerp(-1, 1, SmoothStep(0, 60, TIMER)), 0.5)"
        for timer, sw in ((0, -1.000000), (15, -0.687500), (45, 0.687500), (60, 1.000000)):
            self.assertAlmostEqual(_ev(f18, {"TIMER": float(timer)})[0],
                                   min(sw, 0.5), places=6, msg="TIMER=%d" % timer)
            self.assertAlmostEqual(_ev(f19, {"TIMER": float(timer)})[0],
                                   max(sw, 0.5), places=6, msg="TIMER=%d" % timer)
        # 语料：max(Length, 0) 是"钳到非负"的标准写法
        self.assertEqual(_ev("Max(Length, 0)", {"Length": -3.0})[0], 0.0)
        self.assertEqual(_ev("Max(Length, 0)", {"Length": 7.0})[0], 7.0)

    def test_func21_is_a_linear_clamp_lerp_not_the_eased_one(self):
        """`Func21(a, b, hi, lo, t)`：把 `t` 从 `[lo,hi]` 重映射到 `[0,1]`（两端饱和、
        **线性**），再在 `b`（lo 端）和 `a`（hi 端）之间线性插值。

        ⚠ **它不等于写开的 `Lerp(Clamp(t, hi, lo), a, b)`**——`Clamp` 带 smoothstep
        缓动、`Func21` 的重映射不带，两者的差就是那层缓动。这也是 `Func21` 存在的理由。
        判据是拿 `TIMER/100` 当不经过任何待测函数的线性基准分别对拍，见
        `expr._eval_func21()` 的判据表。"""
        f = "Remap(TIMER, 0, 60, 0, 90)"
        for timer, want in ((0, 0.0), (15, 22.5), (30, 45.0), (60, 90.0), (120, 90.0)):
            self.assertAlmostEqual(_ev(f, {"TIMER": float(timer)})[0], want, places=6,
                                   msg="TIMER=%d" % timer)
        # **和写开的 Lerp(Clamp(...)) 逐点不同**，差值正好是 (a-b)*(smoothstep(x)-x)
        for timer in (7, 15, 23, 41, 45):
            x = timer / 60.0
            fused, _ = _ev(f, {"TIMER": float(timer)})
            spelled, _ = _ev("Lerp(0, 90, SmoothStep(0, 60, TIMER))", {"TIMER": float(timer)})
            self.assertAlmostEqual(spelled - fused, 90.0 * (x * x * (3 - 2 * x) - x),
                                   places=6, msg="TIMER=%d" % timer)
        # 端点仍然一致（缓动只改中段）——这正是它藏这么久的原因
        for timer in (0, 60, 120):
            fused, _ = _ev(f, {"TIMER": float(timer)})
            spelled, _ = _ev("Lerp(0, 90, SmoothStep(0, 60, TIMER))", {"TIMER": float(timer)})
            self.assertAlmostEqual(fused, spelled, places=6, msg="TIMER=%d" % timer)
        # 端点方向：t 在 lo 端取第 2 参 b、在 hi 端取第 1 参 a（同 Lerp 的方向）
        self.assertAlmostEqual(_ev("Remap(2, 2, 10, 1, 5)")[0], 1.0, places=6)
        self.assertAlmostEqual(_ev("Remap(10, 2, 10, 1, 5)")[0], 5.0, places=6)
        # 语料高频写法：Unary11(Func21(90, 0, hi, 0, TIMER)) = sin(角度)，0°->90°
        corpus = "SinDeg(Remap(TIMER, 0, 60, 0, 90))"
        self.assertAlmostEqual(_ev(corpus, {"TIMER": 0.0})[0], 0.0, places=6)
        self.assertAlmostEqual(_ev(corpus, {"TIMER": 30.0})[0], 0.7071, places=4)
        self.assertAlmostEqual(_ev(corpus, {"TIMER": 60.0})[0], 1.0, places=6)

    def test_all_thirteen_unary_functions_are_decided(self):
        """操作码 0~12 里引擎实现的 13 个全部已定，未知表是空的。

        ⚠ **`Acos`（操作码 3）是 `a96e1d9` 之后才写得出来的**：旧解析器的枚举跳过了 3，
        文本里写不出这个名字，语义当初是靠改字节测的。13 / 14 引擎没实现，枚举里至今
        没有——那两个是"真未知"的现成例子。"""
        for name in ("Sin", "Cos", "Asin", "Acos", "Floor", "Ceil", "Log", "Log10",
                     "Exp", "Abs", "Saturate", "SinDeg", "CosDeg"):
            self.assertEqual(expr_call_confidence(name), "confirmed", name)
        self.assertEqual(expr._UNKNOWN_FUNC_ARGC, {})
        for name in ("Min", "Max", "Pow", "Remap"):
            self.assertEqual(expr_call_confidence(name), "confirmed", name)
        self.assertEqual(expr_call_confidence("Clamp"), "confirmed")
        self.assertEqual(expr_call_confidence("InvLerp"), "unknown")    # 旧名字不再认
        # `Acos` 现在是**能求值**的（a96e1d9 把它加进了 FunctionArgCounts）——这正是
        # bump submodule 换来的新能力，所以这里改成正面断言。
        self.assertAlmostEqual(_ev("Acos(1)")[0], 0.0, places=9)
        self.assertAlmostEqual(_ev("Acos(0)")[0], 1.5708, places=4)
        # 引擎真没实现的 13 / 14 仍然求值不了（我们不给未知操作码编语义，不把猜测当事实）
        with self.assertRaises(ExprError):
            _ev("Func13(1)")


class TestExprEvaluate(unittest.TestCase):
    def test_arithmetic(self):
        """`2 + 3` 是 2*3=6；`6 / 2` 是 6+2=8；`8 - 2` 是 2/8=0.25。"""
        self.assertEqual(_ev("(2 * 3)")[0], 6.0)
        self.assertEqual(_ev("(6 + 2)")[0], 8.0)
        self.assertEqual(_ev("(2 / 8)")[0], 0.25)

    def test_operator_precedence_is_the_texts_not_the_semantics(self):
        """优先级仍然按文本语法那套（`ast` 和 vendor 的
        `ParseBinaryOperationAddSub`/`MulDiv` 一致：`* /` 比 `+ -` 结合得紧），
        **这次改的只有"算什么"**。所以 `2 + 4 * 3` 先算 `4 * 3`（=`fmod(3,4)`=3）
        再算 `2 + 3`（=乘=6）——注意这时候"先算的"反而是取模、"后算的"是乘法，
        优先级和真实语义已经对不上了，这是 vendor 文本形式自带的性质，不是 bug。"""
        self.assertEqual(_ev("(2 * (3 % 4))")[0], 6.0)

    def test_unary_negation(self):
        """一元负号是唯一没被 vendor 标错的运算符。`-(1 + 2)` = `-(1*2)` = -2。"""
        result, _ = _ev("-((1 * 2))")
        self.assertEqual(result, -2.0)
        self.assertEqual(_ev("-0")[0], 0.0)
        self.assertEqual(_ev("-2")[0], -2.0)

    def test_min_is_subtraction_and_max_is_power(self):
        """`Min(a, b)` = `b - a`（操作码 5，实机确认）、`Max(a, b)` = `pow(b, a)`
        （操作码 0，语料推断）。真正的 min/max 在这套表达式里不存在。"""
        self.assertEqual(_ev("(7 - 3)")[0], 4.0)
        self.assertEqual(_ev("(3 - 7)")[0], -4.0)
        self.assertEqual(_ev("(3 ^ 2)")[0], 9.0)
        self.assertEqual(_ev("(2 ^ 3)")[0], 8.0)

    def test_clamp_is_a_remap_with_both_ends_saturated(self):
        """`Clamp(value, hi, lo)` 是把 value 从 `[lo, hi]` 重映射到 `[0, 1]`，**不是**
        夹到 `[lo, hi]` 之间，而且**两端都饱和**。上界这一半是 2026-09-16 实机对拍确认的：
        同一个 `Lerp(Clamp(TIMER, hi, 0), -1, 0.5)`，`hi` 翻倍只让到达终点的时间翻倍、
        终点位置不变，直接证明超过 `hi` 之后结果饱和在 1，不会继续线性上冲（那次测试恒用
        `lo=0`、`TIMER≥0`，没有覆盖到下界，下界饱和仍是语料间接推断，依据见
        `expr._eval_clamp()` 的 docstring 和 docs/EXPRESSION_SEMANTICS.md）。

        注回"夹住"实现（`min(max(x, lo), hi)`）时 x=4.5 会 FAIL 得到 4.5 而不是 0.5；
        注回旧的"上界不钳"实现时 x=9.0 会 FAIL 得到 2.0 而不是 1.0。
        """
        self.assertEqual(_ev("SmoothStep(3, 6, x)", {"x": 3.0})[0], 0.0)
        self.assertEqual(_ev("SmoothStep(3, 6, x)", {"x": 6.0})[0], 1.0)
        self.assertEqual(_ev("SmoothStep(3, 6, x)", {"x": 4.5})[0], 0.5)
        # 上界饱和：越过 hi 之后恒为 1（实机确认，见上）
        self.assertEqual(_ev("SmoothStep(3, 6, x)", {"x": 9.0})[0], 1.0)
        # 下界饱和在 0（仍是语料推断，这条测试没有独立实机证据）
        self.assertEqual(_ev("SmoothStep(3, 6, x)", {"x": 0.0})[0], 0.0)

    def test_clamp_mode_switch(self):
        """四档读法都能选到。`remap_saturate_low`/`remap_unclamped`/`bounds_clamp` 是
        被推翻或旧的读法，保留下来对拍用。"""
        def ev(mode, x):
            notes = []
            ctx = EvalContext({"x": x}, "identity", notes, mode)
            return expr_evaluate(expr_parse("SmoothStep(3, 6, x)"), ctx)

        self.assertEqual(ev("remap_saturate_both", 0.0), 0.0)
        self.assertEqual(ev("remap_saturate_both", 9.0), 1.0)   # 两端都饱和（默认，已实机确认）
        self.assertEqual(ev("remap_saturate_low", 0.0), 0.0)
        self.assertEqual(ev("remap_saturate_low", 9.0), 2.0)    # 旧默认：上界不钳
        self.assertEqual(ev("remap_unclamped", 0.0), -1.0)      # 不钳下界就是负的
        self.assertEqual(ev("bounds_clamp", 0.0), 3.0)          # 旧读法
        self.assertEqual(ev("bounds_clamp", 4.5), 4.5)

    def test_clamp_degenerate_bounds_are_noted(self):
        result, notes = _ev("SmoothStep(5, 5, x)", {"x": 1.0})
        self.assertEqual(result, 0.0)
        self.assertTrue(any("SmoothStep" in n for n in notes))

    def test_lerp_clamps_its_factor_and_does_not_extrapolate(self):
        """`Lerp(t, a, b)` 的 `t` **钳在 `[0, 1]`**，而且是线性的、方向是 t=0 取第 3 参。

        三件事 2026-09-17 由**一条**零差探针一次钉死（参考用 `Func21`，它的线性和钳位
        已独立确认，而且不含 `Lerp` 自己）::

            clip(20 * (Lerp(TIMER/15, 4, 1) - Func21(4, 1, 15, 0, TIMER)))   实测死平

        三种替代读法都不平：**不钳位**在第 16 帧上跳、削平在 +0.4；**带 smoothstep
        缓动**前半段 −0.4、后半段 +0.4、第 15 帧后归 0；**方向反**则开头 +0.4、之后
        全程 −0.4。正对照（参考端点 1 改成 2）画出预期的"前 0.25 m 在 −0.4、之后归 0"。

        ⚠ **原来那条"直接证据"已经作废**（留着当教训）：它说"`InvLerp` 是同一个函数、
        系数在末位，而 `InvLerp(1, 0, x)` 两端饱和"。16 号其实是 `clamp`
        （见 `test_invlerp_is_the_real_clamp`），那条推理连同前提一起没了——好在上面
        这条零差探针不依赖它。

        注回"不钳"会 FAIL：`Lerp(2, 7, 3)` 会给 11 而不是 7。"""
        self.assertEqual(_ev("Lerp(3, 7, 0)")[0], 3.0)
        self.assertEqual(_ev("Lerp(3, 7, 1)")[0], 7.0)
        self.assertEqual(_ev("Lerp(3, 7, 0.5)")[0], 5.0)
        self.assertEqual(_ev("Lerp(3, 7, -1)")[0], 3.0)     # 不外推
        self.assertEqual(_ev("Lerp(3, 7, 2)")[0], 7.0)      # 不外推

    def test_invlerp_is_the_real_clamp(self):
        """**操作码 16（vendor 叫 `InvLerp`）是真正的 `clamp`**：
        `InvLerp(hi, lo, value)` == `max(lo, min(hi, value))`（2026-09-17 实机）。

        不是 lerp、也不是反向插值。名字和 17 号基本对调了——17 号叫 `Clamp` 却是
        smoothstep 重映射。

        ⚠ **2026-09-16 曾判成"就是 `Lerp`、系数挪到末位"，错了。** 当时两条探针用
        `a=1, b=0`，恰好让 lerp、钳位反向插值、真 clamp 三者全部退化成 `saturate(x)`
        ——上游 review 时质疑的正是这一点。端点换成 `4/1` 之后三者立刻分开。

        五条实机读数（横轴 `1 - TIMER/40`、纵轴限幅 ±0.4 的零差探针）唯一确定了它：

        ====  ==================================================  ====================
        探针  内容                                                实测
        ====  ==================================================  ====================
        P1    ``InvLerp(x, 1, 0)``，x 扫 −1→2                     恒定 1、纹丝不动
        P2    ``InvLerp(1, 0, x)``，同上                          两端饱和的 0→1 斜坡
        S1    ``clip(20*(F16(4,1,T/15) - F21(4,1,15,0,T)))``      第 60 帧从负值上跳
        S2    同 S1，两处 15 换成 30                              第 120 帧上跳
        P     同 S1，参考端点 1 改成 2                            跳变位置**不变**
        N     把 F16 换成参考自己                                 死平（排掉固定帧假象）
        ====  ==================================================  ====================

        S1/S2 的跳变发生在 `value` 涨到 `hi` 的那一刻（不是 `t` 涨到 1），P 的跳变位置
        不随参考端点动——两条一起说明跳变由 `hi` 支配。逐读法对照见
        docs/EXPRESSION_SEMANTICS.md 第 3 节。
        """
        self.assertEqual(_ev("Clamp(0.5, 1, 4)")[0], 1.0)     # 低于 lo -> lo
        self.assertEqual(_ev("Clamp(2.5, 1, 4)")[0], 2.5)     # 区间内 -> 原值
        self.assertEqual(_ev("Clamp(9, 1, 4)")[0], 4.0)       # 高于 hi -> hi
        for x in (-1.0, -0.5, 0.0, 0.5, 0.9, 1.0, 1.5, 2.0):
            self.assertEqual(_ev("Clamp(0, 1, %r)" % x)[0], 1.0, "P1 x=%r" % x)
        for x, want in ((-1.0, 0.0), (0.3, 0.3), (0.9, 0.9), (2.0, 1.0)):
            self.assertEqual(_ev("Clamp(%r, 0, 1)" % x)[0], want, "P2 x=%r" % x)
        # **它不是 Lerp**：同一组参数下两者必须给出不同的数
        self.assertNotEqual(_ev("Clamp(0.5, 1, 4)")[0], _ev("Lerp(1, 4, 0.5)")[0])

    def test_invlerp_applies_min_before_max_so_lo_wins(self):
        """引擎是 `max(lo, min(hi, value))` —— **`lo > hi` 时 `lo` 赢**。

        判据是探针 P1（`InvLerp(x, 1, 0)`，x 扫 −1→2）实测恒定 1：那里 `lo=1` 在 x<1
        的那一段一直大于 `hi=x`，而另一种写法 `min(hi, max(lo, value))` 会给出 `x`、
        画出斜线。这个先后**是测出来的，不是我们挑的约定**——别"顺手规范化成
        `min<=max`"，那样下面两条会 FAIL（会给 0）。
        """
        self.assertEqual(_ev("Clamp(3, 5, 0)")[0], 5.0)       # lo=5 > hi=0 -> lo 赢
        self.assertEqual(_ev("Clamp(0, 1, -2)")[0], 1.0)

    def test_lerp_is_still_a_lerp(self):
        self.assertEqual(_ev("Lerp(8, 0, 0.5)")[0], 4.0)
        self.assertEqual(_ev("Lerp(8, 0, 0)")[0], 8.0)
        self.assertEqual(_ev("Lerp(8, 0, 1)")[0], 0.0)

    def test_real_corpus_example(self):
        """照抄真实语料的公式（`11_pl_slinger_037.efx.5571972` 的 SpawnExpression），只是
        把未解出名字的外部哈希换成一个测试变量。

        **这条曾经是一条"量级对不上"的证据**：`Clamp` 还按"夹住"读的时候，`speed` 在
        `[3, 6]` 内取值算出来是 `[24, 48]`，比外层 `Lerp` 自己写的输出边界 `[0, 8]` 大
        3~6 倍。`Clamp` 改成重映射之后这个矛盾消失——输出正好落在 `[0, 8]`，也反过来
        印证了 `Lerp(t, a, b)` 的第一个参数确实是插值系数（`t` 是插值系数这一点不受下面
        这条影响）。

        ⚠ 2026-09-16 实机确认 `Lerp(t, a, b)` 的方向是**反过来**的：`t=0` 时取第 3 参
        `b`、`t=1` 时取第 2 参 `a`（不是"`t=0` 取 `a`"）。依据：两条对照粒子轨迹分别用
        `Lerp(Clamp(TIMER,15,0),-1,0.5)` 和 `Lerp(Clamp(TIMER,15,0),0.5,-1)`，实机观察到
        的运动方向和"`t=0`→第 2 参"这个读法两次都对不上、和"`t=0`→第 3 参"两次都对得上
        （`ExpressionAssignType` 确认用的是 `Assign`，排除了基准值叠加的混淆）。这条测试
        原来断言 `speed=3.0`(`t=0`) 得 `0.0`、`speed=6.0`(`t=1`) 得 `8.0`，现在反过来。"""
        self.assertEqual(_ev("Lerp(8, 0, SmoothStep(3, 6, speed))", {"speed": 3.0})[0], 8.0)
        self.assertEqual(_ev("Lerp(8, 0, SmoothStep(3, 6, speed))", {"speed": 4.5})[0], 4.0)
        result, notes = _ev("Lerp(8, 0, SmoothStep(3, 6, speed))", {"speed": 6.0})
        self.assertEqual(result, 0.0)
        self.assertEqual(notes, [])

    def test_transform3d_rotation_example(self):
        """用户报告的那条：`Transform3DExpression` 的 rotationX（assign 方式 = Assign）。
        12 帧内从 -30 线性扫到 190，超过 12 帧后饱和在 190 不再变化（方向已按 2026-09-16
        实机确认的 `Lerp` 读法更正，见 `test_real_corpus_example` 的说明）。"""
        f = "Lerp(-30, 190, SmoothStep(0, 12, TIMER))"
        self.assertEqual(_ev(f, {"TIMER": 0.0})[0], -30.0)
        self.assertEqual(_ev(f, {"TIMER": 6.0})[0], 80.0)
        self.assertEqual(_ev(f, {"TIMER": 12.0})[0], 190.0)

    def test_unknown_variable_notes_and_defaults_zero(self):
        result, notes = _ev("(TIMER + 1)", {})   # `/` 是加法，未知变量按 0 -> 0+1
        self.assertEqual(result, 1.0)
        self.assertTrue(any("TIMER" in n for n in notes))

    def test_unknown_function_identity_policy(self):
        """未确认语义的函数按 identity 策略原样透传第一个参数，并且必须 note——面板要能
        如实展示"这条曲线用到未确认语义的函数"。

        ⚠ **现在已经没有真样本了**：2026-09-16 那一轮把 12 个 `Unary*` 和
        `Func18`~`Func21` 全部测出语义，`_UNKNOWN_FUNC_ARGC` 是空的。这条测试的样本
        换过四次（`Unary10` -> `Unary2` -> `Func18` -> `Func20`），现在改成**临时往
        未知表里注入一个假名字**——这条代码路径要留着，下次 vendor 升级冒出新函数
        （或者给枚举补上 3/13/14）时它就是第一道防线。"""
        expr._UNKNOWN_FUNC_ARGC["FuncNew"] = 1
        try:
            result, notes = _ev("(FuncNew(5) + 1)")   # `/` 是加法
        finally:
            del expr._UNKNOWN_FUNC_ARGC["FuncNew"]
        self.assertEqual(result, 6.0)
        self.assertTrue(any("FuncNew" in n for n in notes), notes)

    def test_unknown_multi_arg_function_returns_first_arg(self):
        """identity 策略对多参函数返回第一个参数。同样只能靠注入假名字了，
        原因见 `test_unknown_function_identity_policy`。"""
        expr._UNKNOWN_FUNC_ARGC["FuncNew"] = 3
        try:
            result, notes = _ev("FuncNew(1, 2, 3)")
        finally:
            del expr._UNKNOWN_FUNC_ARGC["FuncNew"]
        self.assertEqual(result, 1.0)
        self.assertTrue(any("FuncNew" in n for n in notes), notes)

    def test_root_value_option_uses_first_branch_and_notes(self):
        result, notes = _ev("(1 * 1)  |  999")   # `1 + 1` = 1*1 = 1
        self.assertEqual(result, 1.0)
        self.assertTrue(any("第二根值" in n for n in notes))

    def test_division_by_zero_notes_and_returns_zero(self):
        """除法的文本符号是 `-`，而且**除数是左操作数**（`a - b` == `b / a`）。
        `0 - 1` 就是 `1 / 0`——实机测到的正是"按 0"（`(0,1) -> 0`，不是 inf/NaN），
        所以这里的兜底和引擎行为一致，不只是我们自己的防御。"""
        result, notes = _ev("(1 / 0)")
        self.assertEqual(result, 0.0)
        self.assertTrue(any("除零" in n for n in notes))

    def test_external_hash_placeholder_identifier(self):
        """`ext:302732036` 这种未解析出名字的占位形式（含冒号）必须能解析、能按原样查表。"""
        result, notes = _ev("(ext:302732036 + 1)", {"ext:302732036": 4.0})  # `/` 是加
        self.assertEqual(result, 5.0)
        self.assertEqual(notes, [])

    def test_syntax_error_raises_exprerror(self):
        with self.assertRaises(ExprError):
            expr_parse("Lerp(1, 2")  # 缺右括号


def _life_block(flags=0):
    return ("Life", {
        "AppearFrame": {"r": 0, "s": 0}, "KeepFrame": {"r": 10, "s": 10},
        "VanishFrame": {"r": 0, "s": 0}, "KeepHoldFrame": {"r": 0, "s": 0},
        "Flags": flags,
    })


class TestSimulatorExpressionIntegration(unittest.TestCase):
    def test_assign_replaces_field(self):
        """assign_type=4（Assign）：目标字段直接替换成公式结果，不管原始值是什么。"""
        blocks = [_life_block(flags=0)]
        expressions = [("Life", "flags", "41", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Life").raw["Flags"], 41.0)

    def test_add_is_relative_to_original_value_not_previous_frame(self):
        """assign_type=0（Add）：每帧都是"原始值 + 公式结果"，不是"上一帧结果 + 公式结果"——
        后者会逐帧发散。这条断言注回"用当前 raw 值当基准"会 FAIL：连跑 3 帧会变成
        0+1, 1+1=2, 2+1=3 而不是恒定的 0+1=1。"""
        blocks = [_life_block(flags=0)]
        expressions = [("Life", "flags", "1", 0)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        first = sim.em.f("Life").raw["Flags"]
        sim.step()
        second = sim.em.f("Life").raw["Flags"]
        sim.step()
        third = sim.em.f("Life").raw["Flags"]
        self.assertEqual(first, 1.0)
        self.assertEqual(second, 1.0)
        self.assertEqual(third, 1.0)

    def test_multiply_and_subtract(self):
        blocks = [_life_block(flags=10)]
        expressions = [("Life", "flags", "2", 2)]  # 10 * 2
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Life").raw["Flags"], 20.0)

        blocks2 = [_life_block(flags=10)]
        expressions2 = [("Life", "flags", "3", 1)]  # 10 - 3
        sim2 = Simulator(blocks2, SimConfig(seed=1), expressions=expressions2)
        sim2.step()
        self.assertEqual(sim2.em.f("Life").raw["Flags"], 7.0)

    def test_missing_target_attribute_notes_and_does_not_crash(self):
        blocks = [_life_block()]
        expressions = [("NoSuchType", "whatever", "1", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertTrue(any("expr:" in n for n in sim.em.notes))

    def test_non_scalar_target_field_is_skipped(self):
        """`{s,r}`/`{x,y}` 形状的字段（如 `KeepFrame`）不是标量，patch_field 不知道该改
        哪个子键——必须跳过 + note，不能瞎猜。"""
        blocks = [_life_block()]
        expressions = [("Life", "KeepFrame", "1", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Life").raw["KeepFrame"], {"r": 10, "s": 10})
        self.assertTrue(any("标量" in n for n in sim.em.notes))

    def test_timer_advances_with_frame(self):
        blocks = [_life_block(flags=0)]
        expressions = [("Life", "flags", "TIMER", 4)]
        sim = Simulator(blocks, SimConfig(seed=1, expr_timer_unit="frames"), expressions=expressions)
        sim.step()
        first = sim.em.f("Life").raw["Flags"]
        sim.step()
        second = sim.em.f("Life").raw["Flags"]
        self.assertEqual(second, first + 1.0)

    def test_cross_attribute_variable_lookup(self):
        """公式引用**另一个属性**的字段名（vendor `KnownExternalHashes` 里 `SpawnNum`/`Wide`
        这类名字本身就是别的 attribute 的字段名，见 efx_sim/simulator.py 的说明）。"""
        blocks = [_life_block(flags=0), ("Spawn", {"MaxParticles": 99, "SpawnNum": {"x": 1, "y": 1},
                                                    "IntervalFrame": {"x": 0, "y": 0},
                                                    "EmitterDelayFrame": {"x": 0, "y": 0},
                                                    "LoopNum": {"r": 1, "s": 0},
                                                    "ExtraScalar": 7.0})]
        expressions = [("Life", "flags", "(ExtraScalar + 1)", 4)]   # `/` 是加法
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Life").raw["Flags"], 8.0)


def _velocity3d_raw(speed=(0.5, 0.2), direction=(0.0, 1.0, 0.0)):
    """`Velocity3D` 的原始字段 dict。字段必须齐全——`_resolve_expr_target()` 只在 sibling
    的 dict 里真找得到字段时才定位成功，缺字段的假 raw 会让断言"因为错的理由"通过。"""
    return {
        "VelocityType": 0,
        "DirectionVectorX": {"s": direction[0], "r": 0.0},
        "DirectionVectorY": {"s": direction[1], "r": 0.0},
        "DirectionVectorZ": {"s": direction[2], "r": 0.25},
        "Size": {"X": 1.0, "Y": 1.0, "Z": 1.0},
        "Offset": {"X": 0.0, "Y": 0.0, "Z": 0.0},
        "Speed": {"s": speed[0], "r": speed[1]},
        "SpeedCoef": {"s": 1.0, "r": 0.0},
        "GravityRate": {"s": 0.0, "r": 0.0},
        "SpeedDelayFrame": {"r": 0, "s": 0},
        "GravityDelayFrame": {"r": 0, "s": 0},
        "InheritRate": {"s": 0.0, "r": 0.0},
        "InheritDistance": {"s": 0.0, "r": 0.0},
        "Spread": {"s": 0.0, "r": 0.0},
    }


def _velocity3d_block(**kwargs):
    return ("Velocity3D", _velocity3d_raw(**kwargs))


class TestExprFieldOverrides(unittest.TestCase):
    """`_EXPR_FIELD_OVERRIDES`（bit_name -> 真实字段+子键）——照抄 vendor 源码的字段声明，
    不是"去 Expression 后缀 + 首字母大写"这个只对少数类型碰巧成立的启发式。这批断言对应的
    真实故障模式：真机冒烟测试里 `11_pl_slinger_037.efx.5571972` 的 5 条 Expression 曲线
    在改用这张表之前**一条都没能定位到目标字段**（`appearLife` 找不到 `AppearLife`，实际
    字段叫 `AppearFrame`）。"""

    def test_pick_primary_secondary_key_rangei_prefers_r(self):
        self.assertEqual(_pick_primary_secondary_key({"s": 10, "r": 10}, "primary"), "r")
        self.assertEqual(_pick_primary_secondary_key({"s": 10, "r": 10}, "secondary"), "s")

    def test_pick_primary_secondary_key_range_prefers_s(self):
        self.assertEqual(_pick_primary_secondary_key({"s": 1.0, "r": 0.0}, "primary"), "s")
        self.assertEqual(_pick_primary_secondary_key({"s": 1.0, "r": 0.0}, "secondary"), "r")

    def test_pick_primary_secondary_key_int2_prefers_x(self):
        self.assertEqual(_pick_primary_secondary_key({"x": 1, "y": 2}, "primary"), "x")
        self.assertEqual(_pick_primary_secondary_key({"x": 1, "y": 2}, "secondary"), "y")

    def test_life_appear_life_maps_to_appear_frame_primary(self):
        raw = {"AppearFrame": {"r": 5, "s": 5}, "KeepFrame": {"r": 10, "s": 10}}
        target = _resolve_expr_target("Life", "appearLife", raw)
        self.assertEqual(target, ("AppearFrame", "r", 5))

    def test_spawn_spawn_num_range_maps_to_secondary(self):
        raw = {"SpawnNum": {"x": 1, "y": 3}}
        target = _resolve_expr_target("Spawn", "spawnNumRange", raw)
        self.assertEqual(target, ("SpawnNum", "y", 3))

    def test_transform3d_rotation_y_maps_to_vector_component(self):
        raw = {"LocalRotation": {"X": 0.0, "Y": 1.5, "Z": 0.0}}
        target = _resolve_expr_target("Transform3D", "rotationY", raw)
        self.assertEqual(target, ("LocalRotation", "Y", 1.5))

    def test_velocity3d_speed_maps_to_speed_primary(self):
        target = _resolve_expr_target("Velocity3D", "speed", _velocity3d_raw())
        self.assertEqual(target, ("Speed", "s", 0.5))

    def test_velocity3d_speed_rand_maps_to_speed_secondary(self):
        target = _resolve_expr_target("Velocity3D", "speedRand", _velocity3d_raw())
        self.assertEqual(target, ("Speed", "r", 0.2))

    def test_velocity3d_velocity_axis_maps_to_direction_vector(self):
        """`velocityY` -> `DirectionVectorY` 的主值。落点靠字段形状定（带 `…Random` 变体的
        bit 必须落在有主/副值的 `via.Range` 上，`Velocity3D` 上只有 `DirectionVector*`
        是逐轴 Range），依据和反证都记在 `_EXPR_FIELD_OVERRIDES` 的注释里。"""
        raw = _velocity3d_raw()
        self.assertEqual(_resolve_expr_target("Velocity3D", "velocityY", raw),
                         ("DirectionVectorY", "s", 1.0))
        self.assertEqual(_resolve_expr_target("Velocity3D", "velocityZRandom", raw),
                         ("DirectionVectorZ", "r", 0.25))

    def test_noise_placeholder_bits_map_to_the_four_range_fields(self):
        """`NoiseExpression` 的 8 位全是占位名，但本体恰好只有 4 个 `via.Range`，
        8 = 4 × 主/副值、没有多余候选（判据见 `_EXPR_FIELD_OVERRIDES` 里那段注释）。
        `11_guide_006.efx` 实际置位的 bit2/bit6 落在两个 Width 上——噪声**振幅**淡出，
        不是频率淡出。"""
        raw = {"LowFrequency": {"s": 1.0, "r": 0.3},
               "LowFrequencyWidth": {"s": 0.05, "r": 0.0},
               "HighFrequency": {"s": 0.5, "r": 0.2},
               "HighFrequencyWidth": {"s": 0.1, "r": 0.0}}
        self.assertEqual(_resolve_expr_target("Noise", "unkn3", raw),
                         ("LowFrequencyWidth", "s", 0.05))
        self.assertEqual(_resolve_expr_target("Noise", "unkn7", raw),
                         ("HighFrequencyWidth", "s", 0.1))
        self.assertEqual(_resolve_expr_target("Noise", "unkn2", raw),
                         ("LowFrequency", "r", 0.3))
        self.assertEqual(_resolve_expr_target("Noise", "unkn5", raw),
                         ("HighFrequency", "s", 0.5))

    def test_velocity3d_placeholder_bit_names_stay_unresolved(self):
        """`unkn3`/`unkn5`/`unkn6` 是反射表按声明顺序补的**占位名**，vendor 自己没认出它们
        指哪个字段——全语料分别用过 34/198/75 次，但**不许猜**（不把猜测当事实）。定位不到就该返回
        None 让调用方 note 出来，不能退回启发式凑一个 `Unkn5` 上去。"""
        raw = _velocity3d_raw()
        for bit_name in ("unkn3", "unkn5", "unkn6", "unkn19"):
            self.assertIsNone(_resolve_expr_target("Velocity3D", bit_name, raw), bit_name)

    def test_unmapped_type_falls_back_to_capitalized_heuristic(self):
        raw = {"Wide": 2.0}
        target = _resolve_expr_target("SomeUnmappedType", "wide", raw)
        self.assertEqual(target, ("Wide", None, 2.0))

    def test_empty_bit_name_never_resolves(self):
        self.assertIsNone(_resolve_expr_target("Life", "", {"AppearFrame": {"r": 1, "s": 1}}))


class TestSimulatorExpressionFieldOverrideIntegration(unittest.TestCase):
    def test_life_appear_life_curve_patches_appear_frame_primary_in_place(self):
        """回归防护：这条断言在改用 `_EXPR_FIELD_OVERRIDES` 之前会 FAIL——旧的启发式会去找
        不存在的 `AppearLife` 字段，曲线整条不生效。"""
        blocks = [_life_block(flags=0)]
        expressions = [("Life", "appearLife", "9", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Life").raw["AppearFrame"], {"r": 9.0, "s": 0})

    def test_spawn_spawn_num_curve_patches_primary_leaves_secondary(self):
        blocks = [("Spawn", {"MaxParticles": 99, "SpawnNum": {"x": 1, "y": 5},
                              "IntervalFrame": {"x": 0, "y": 0},
                              "EmitterDelayFrame": {"x": 0, "y": 0},
                              "LoopNum": {"r": 1, "s": 0}})]
        expressions = [("Spawn", "spawnNum", "3", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Spawn").raw["SpawnNum"], {"x": 3.0, "y": 5})

    def test_velocity3d_speed_curve_patches_speed_primary_in_place(self):
        """回归防护：加这张表之前 `speed` 走启发式找 `Speed`，字段确实存在但是个 `{s,r}`
        dict、拿不到 sub_key，`_resolve_expr_target()` 直接返回 None，整条曲线静默失效。"""
        blocks = [_velocity3d_block()]
        expressions = [("Velocity3D", "speed", "7", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Velocity3D").raw["Speed"], {"s": 7.0, "r": 0.2})

    def test_velocity3d_velocity_y_curve_patches_direction_vector_primary(self):
        blocks = [_velocity3d_block()]
        expressions = [("Velocity3D", "velocityY", "0.25", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.f("Velocity3D").raw["DirectionVectorY"], {"s": 0.25, "r": 0.0})


class TestVelocity3DExpressionIsPerSpawnNotGlobal(unittest.TestCase):
    """`Velocity3DExpression` 的公式每帧改的是**字段**，而 `velocity3d.py` 只在
    `on_particle_spawn` 读这个字段（`f.roll("Speed", ...)`）——所以一条 `speed` 曲线的含义是
    "**按出生帧**给速度"，不是"实时调所有粒子的速度"。已经出生的粒子拿到的是它出生那一刻
    的值，之后只有 `SpeedCoef`/`GravityRate` 还能改它。

    这一条钉住的是**语义**而不是接线：接线（上面那张表）正确、但如果哪天有人把速度改成
    逐帧重读字段，粒子就会集体跟着曲线变速，画面上看着"更动感"、其实和引擎不是一回事。"""

    @staticmethod
    def _sim():
        blocks = [
            ("Spawn", {"MaxParticles": 99, "SpawnNum": {"x": 1, "y": 1},
                       "IntervalFrame": {"x": 1, "y": 1},
                       "EmitterDelayFrame": {"x": 0, "y": 0},
                       "LoopNum": {"r": 8, "s": 0}}),
            ("Life", {"AppearFrame": {"r": 0, "s": 0}, "KeepFrame": {"r": 999, "s": 999},
                      "VanishFrame": {"r": 0, "s": 0}, "KeepHoldFrame": {"r": 0, "s": 0},
                      "Flags": 0}),
            _velocity3d_block(speed=(0.0, 0.0), direction=(0.0, 1.0, 0.0)),
        ]
        # `speed = TIMER`：出生帧号直接当速度，于是"每个粒子的速度"可以逐个读出来
        return Simulator(blocks, SimConfig(seed=1),
                         expressions=[("Velocity3D", "speed", "TIMER", 4)])

    def test_later_born_particles_get_the_later_curve_value(self):
        sim = self._sim()
        sim.run(5)
        speeds = [p.vel.y for p in sim.em.particles]
        self.assertGreater(len(speeds), 2, "样本里一个粒子都没生出来，这条断言什么都没测到")
        self.assertEqual(speeds, sorted(speeds),
                         "出生越晚速度应该越大（speed=TIMER），实际 %r" % (speeds,))
        self.assertGreater(speeds[-1], speeds[0], "所有粒子速度相同 = 曲线没按出生帧生效")

    def test_already_born_particle_keeps_its_spawn_time_speed(self):
        sim = self._sim()
        sim.run(3)   # `IntervalFrame=1` 是隔一帧发一个，跑 3 帧才有 2 个粒子
        # 取第 2 个粒子：第 1 个出生在 `TIMER == 0` 那一帧，`speed = TIMER` 正好是 0，
        # 拿它当被观察对象会让下面的正对照失去意义
        first = sim.em.particles[1]
        at_spawn = first.vel.y
        # ⚠ 正对照：没有这一条时，接线断开（速度恒 0）也能让下面的"没变"白过——
        # 那正是"门禁全绿但什么都没测"的形态
        self.assertGreater(at_spawn, 0.0, "出生速度是 0，下面那条断言会因为『谁都没动』白过")
        sim.run(4)
        self.assertEqual(first.vel.y, at_spawn,
                         "已出生粒子的速度被后来的曲线值改掉了——那是『实时全局调速』，"
                         "不是 Velocity3D 的语义")


def _transform3d_block(pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0),
                       rotation_order=2):
    return ("Transform3D", {
        "LocalPosition": {"X": pos[0], "Y": pos[1], "Z": pos[2]},
        "LocalRotation": {"X": rot[0], "Y": rot[1], "Z": rot[2]},
        "LocalScale": {"X": scale[0], "Y": scale[1], "Z": scale[2]},
        "RotationOrder": rotation_order,
    })


class TestTransform3DBehavior(unittest.TestCase):
    """`efx_sim/behaviors/transform3d.py`——`Transform3D` 之前故意不注册（位置/旋转/缩放
    整个交给 Blender 端烘进 entry 的 matrix_basis），Expression 接入后这里补三条**增量**
    路径（位置/旋转/缩放各一条）。核心风险是"重复叠加"：矩阵已经把导入时的静态值算过
    一次，这里如果直接把当前值整个塞进去就会在没有曲线驱动的普通情况下也产生一个虚假
    偏移/旋转/缩放。"""

    def test_static_position_produces_zero_drift(self):
        """没有 Expression 曲线时（最常见的情况），字段值从不变化，drift 必须恒为零——
        这条断言注回"drift = 当前值"（不算增量）会 FAIL：非零的 LocalPosition 会让粒子
        凭空多移动一次，和已经烘进矩阵的偏移重复叠加。"""
        blocks = [_transform3d_block(pos=(5.0, 6.0, 7.0))]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertEqual(tuple(sim.em.drift), (0.0, 0.0, 0.0))
        sim.step()
        sim.step()
        self.assertEqual(tuple(sim.em.drift), (0.0, 0.0, 0.0))

    def test_expression_driven_position_becomes_drift_delta(self):
        """Expression 把 `LocalPosition.X` 从基准 5.0 改写成 8.0 时，drift 应该是增量 3.0，
        不是绝对值 8.0（矩阵里已经烘了 5.0）。"""
        blocks = [_transform3d_block(pos=(5.0, 0.0, 0.0))]
        expressions = [("Transform3D", "translationX", "8", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 3.0)
        self.assertEqual(sim.em.drift.y, 0.0)
        self.assertEqual(sim.em.drift.z, 0.0)

    def test_static_rotation_and_scale_produce_identity_drift(self):
        """没有曲线驱动时，`rotation_drift` 恒为零、`scale_drift` 恒为 (1,1,1)——
        这条断言注回"drift = 当前值"会 FAIL：非零的 `LocalRotation`/非 1 的 `LocalScale`
        会让渲染矩阵凭空多转/多缩一次，和已经烘进 `matrix_basis` 的值重复叠加。"""
        blocks = [_transform3d_block(rot=(0.3, 0.0, 0.0), scale=(2.0, 2.0, 2.0))]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertEqual(tuple(sim.em.rotation_drift), (0.0, 0.0, 0.0))
        self.assertEqual(tuple(sim.em.scale_drift), (1.0, 1.0, 1.0))

    def test_expression_driven_rotation_becomes_drift_delta(self):
        """`LocalRotation.X` 从基准 0.3 改写成 0.5，`rotation_drift.x` 应该是增量 0.2，
        不是绝对值 0.5。"""
        blocks = [_transform3d_block(rot=(0.3, 0.0, 0.0))]
        expressions = [("Transform3D", "rotationX", "0.5", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.rotation_drift.x, 0.2)
        self.assertEqual(sim.em.rotation_drift.y, 0.0)

    def test_expression_driven_scale_becomes_ratio_delta(self):
        """`LocalScale.Y` 从基准 2.0 改写成 3.0，`scale_drift.y` 应该是比值 1.5
        （3.0/2.0），不是绝对值 3.0——矩阵里已经烘了 2.0 那份。"""
        blocks = [_transform3d_block(scale=(1.0, 2.0, 1.0))]
        expressions = [("Transform3D", "scaleY", "3.0", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.scale_drift.y, 1.5)
        self.assertEqual(sim.em.scale_drift.x, 1.0)
        self.assertEqual(sim.em.scale_drift.z, 1.0)

    def test_rotation_and_scale_velocity_are_per_frame_deltas_not_cumulative(self):
        """`em.rotation_velocity`/`em.scale_velocity`（`Simulator.step()` 派生，同
        `em.velocity` 之于 `em.origin`）必须是**这一帧相对上一帧**的增量，不是相对
        基准的累计量——`rotation_drift`/`scale_drift` 本身已经是累计量了，`ParentOptions`
        如果拿累计量当"这一帧转了多少"直接用，每帧都会把从头到现在的全部旋转/缩放
        重新转一遍，指数级发散。这里用等速旋转（每帧固定增量 0.1 弧度）钉住：
        3 帧后 velocity 应该还是恒定的 0.1，不是 0.1/0.2/0.3 递增。"""
        blocks = [_transform3d_block(rot=(0.0, 0.0, 0.0))]
        # 每帧 +0.1 的等速斜坡，真实语义是 `0.1 * TIMER`——而乘法的文本符号是 `+`
        # （`TestBinaryOperatorsAreAllMislabeled`），所以这里写 `0.1 + TIMER`。
        expressions = [("Transform3D", "rotationX", "(0.1 * TIMER)", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        vels = []
        for _ in range(4):
            sim.step()
            vels.append(sim.em.rotation_velocity.x)
        # frame0: TIMER=0 -> drift 0.0，velocity 相对初始 prev(0.0) 也是 0.0
        # frame1..3: 每帧 drift 多 0.1，velocity 恒为 0.1
        self.assertAlmostEqual(vels[1], 0.1)
        self.assertAlmostEqual(vels[2], 0.1)
        self.assertAlmostEqual(vels[3], 0.1)

    def test_scale_velocity_is_ratio_between_consecutive_frames(self):
        """`em.scale_velocity` 是"这一帧比上一帧多缩放了多少倍"，不是"相对基准的总倍数"
        ——用倍增的缩放（1, 2, 4, 8...）钉住：每帧的 velocity 应该恒为 2.0，不是
        2/4/8 递增。直接改 `raw` 字段（不经过 Expression 引擎，公式引擎没有幂运算符）：
        `transform3d.py` 只关心当前值和上一帧值，不关心值是怎么变的。"""
        blocks = [_transform3d_block(scale=(1.0, 1.0, 1.0))]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.reset()
        drifts = [1.0, 2.0, 4.0, 8.0]
        vels = []
        for d in drifts:
            sim.em.f("Transform3D").raw["LocalScale"]["X"] = d
            sim.step()
            vels.append(sim.em.scale_velocity.x)
        self.assertAlmostEqual(vels[0], 1.0)   # 第一帧：相对"上一帧"默认值 1.0，无变化
        self.assertAlmostEqual(vels[1], 2.0)
        self.assertAlmostEqual(vels[2], 2.0)
        self.assertAlmostEqual(vels[3], 2.0)

    def test_zero_base_scale_falls_back_to_one_and_is_noted(self):
        """基准 `LocalScale` 有分量为 0 时，比例算不出来（除零），退回 1.0 并 note，
        不能抛异常或算出 inf/nan。"""
        blocks = [_transform3d_block(scale=(0.0, 1.0, 1.0))]
        expressions = [("Transform3D", "scaleX", "5.0", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertEqual(sim.em.scale_drift.x, 1.0)
        self.assertTrue(any("LocalScale" in n and "0" in n for n in sim.em.notes))

    def test_non_identity_base_produces_no_spurious_note(self):
        """基准本身非恒等（比如已经有一个静态旋转/缩放）不该单独触发 note——增量的逐帧
        计算对基准是否恒等无感（`(cur-base)-(prev-base) == cur-prev`，基准抵消掉了），
        这条 note 曾经存在过、后来发现描述的是已经被移除的旧消费路径（渲染时叠加*累计*
        矩阵），留着就是在吓唬用户一个不再存在的问题。"""
        blocks = [_transform3d_block(rot=(0.3, 0.0, 0.0), scale=(2.0, 2.0, 2.0))]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertFalse(any("偏差" in n for n in sim.em.notes))

    def test_transform3d_no_longer_unsupported(self):
        blocks = [_transform3d_block()]
        sim = Simulator(blocks, SimConfig(seed=1))
        self.assertNotIn("Transform3D", sim.em.unsupported)


def _t3dm_block(**fields):
    """`Transform3DModifier` 的 55 个字段全是顶层标量（不是 `{s,r}` 复合类型），
    默认全 0——语料众数就是 0，也是"这组子功能没人用"的中性值（见
    semantics/mhws_field_labels.json 对应 evidence）。传关键字覆盖要测的那几个。"""
    raw = {"unkn%d" % i: 0.0 for i in range(55)}
    raw["unkn0"] = 0
    raw.update(fields)
    return ("Transform3DModifier", raw)


class TestTransform3DModifierBehavior(unittest.TestCase):
    """`efx_sim/behaviors/transform3dmodifier.py`——全部字段 confidence 只有 guess，
    这里不测语义对不对（测不了，没有游戏内数据），只测"运算规则本身自洽"：静态量不随时间
    重复叠加、速度按 Velocity3D.SpeedCoef 同款逐帧乘法模型累积、和 Transform3D 共存时的
    合成顺序不出错。"""

    def test_note_always_fires(self):
        """每次只要挂了这个属性就要提醒"未经验证"，不能让用户误以为这是确认过的效果。"""
        sim = Simulator([_t3dm_block()], SimConfig(seed=1))
        sim.step()
        self.assertTrue(any("Transform3DModifier" in n and "验证" in n for n in sim.em.notes))

    def test_static_position_delta_does_not_compound_without_transform3d(self):
        """真实故障：早期实现里 `on_emitter_step` 无条件 `em.drift += pos_delta`，
        entry 没有 `Transform3D`（没人重置 em.drift）时静态位移会逐帧重复叠加、线性发散。
        这条断言注回那版实现会 FAIL：3 帧后 drift 应该还是同一个静态值，不是它的 3 倍。"""
        blocks = [_t3dm_block(unkn1=5.0)]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 5.0)
        sim.step()
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 5.0)

    def test_static_rotation_delta_composes_additively_with_transform3d(self):
        """和 `Transform3D` 共存时：`Transform3D` 每帧整体重算 `rotation_drift`
        （非曲线驱动时恒为 0），这个 Modifier 的静态旋转增量应该在它之上叠加一次，
        不重复也不丢失。"""
        blocks = [_transform3d_block(rot=(0.3, 0.0, 0.0)), _t3dm_block(unkn7=0.2)]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertAlmostEqual(sim.em.rotation_drift.x, 0.2)
        sim.step()
        self.assertAlmostEqual(sim.em.rotation_drift.x, 0.2)

    def test_velocity_accumulates_with_default_neutral_coefficient(self):
        """变动系数字段语料默认恒为 0，不是 1——按字面读会让第一帧就把速度乘成 0。
        这里钉住"0 按 1（不变）处理"：`unkn21`（X 位移速度变动系数）留默认 0，
        速度应该保持 `unkn19` 原值逐帧累加，不是从第一帧起就归零。"""
        blocks = [_t3dm_block(unkn19=2.0)]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 2.0)
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 4.0)
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 6.0)

    def test_velocity_coefficient_multiplies_speed_each_frame(self):
        """显式设了变动系数（非 0）时按 `Velocity3D.SpeedCoef` 同款模型：系数每帧对速度
        自乘一次，再累加位移——系数 2.0、初速 1.0，三帧后速度序列是 2/4/8，
        累计位移是 2/6/14，不是等差的 2/4/6。"""
        blocks = [_t3dm_block(unkn19=1.0, unkn21=2.0)]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 2.0)
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 6.0)
        sim.step()
        self.assertAlmostEqual(sim.em.drift.x, 14.0)

    def test_scale_delta_is_additive_to_one_not_multiplicative(self):
        """`unkn13` 这组语料众数是 0（不是 1）——改判为"叠加在 1.0 基准上的增量"，
        0.5 应该产生 1.5 倍缩放，不是 0.5 倍（那会让粒子缩小一半，和"0=默认"的直觉相反）。"""
        blocks = [_t3dm_block(unkn13=0.5)]
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.step()
        self.assertAlmostEqual(sim.em.scale_drift.x, 1.5)
        sim.step()
        self.assertAlmostEqual(sim.em.scale_drift.x, 1.5)  # 静态量不随时间继续放大

    def test_scale_composes_multiplicatively_with_transform3d(self):
        """`Transform3D.LocalScale` 已经把静态缩放（比如 2.0）烘进矩阵、`scale_drift`
        恒为 1.0；这个 Modifier 的缩放增量应该在这个比例基础上再乘一次，不是相加、
        也不该覆盖掉 Transform3D 的比例。"""
        blocks = [_transform3d_block(scale=(2.0, 1.0, 1.0)), _t3dm_block(unkn13=1.0)]
        expressions = [("Transform3D", "scaleX", "3.0", 4)]  # 2.0 -> 3.0，ratio=1.5
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.scale_drift.x, 1.5 * 2.0)


class TestExpressionAngleDegreesConversion(unittest.TestCase):
    """用户报告的真实故障：`Transform3DExpression.rotationX` 的公式
    `Lerp(Clamp(TIMER, 120, 0), 190, -30)`（实际方向是"0~120 帧从 -30° 到 190°"——
    2026-09-16 实机确认 `Lerp` 的方向，见 `test_real_corpus_example` 的说明；这条故障的
    重点是单位换算，方向对不对不影响这条结论），但
    `LocalRotation` 的**静态存储**已经字节级确认是弧度——不转换的话 190 被直接当成
    190 弧度（≈30 圈），转出每帧 105° 的"疯狂旋转"。全语料实测（`EfxBridge
    exprrotationstats`）：560 条真实绑定的 `rotationX/Y/Z` 公式，227 个"和公式根节点
    同单位"的字面量常量 0 个落在弧度制常见值附近，众数是 360/10/5/30——公式字面量按度写
    是文件格式层面的事实，见 `efx_sim/simulator.py::_ExprCurve.is_angle_degrees`。
    这条不是 UI 展示问题，是 `Simulator` 求值本身要转换。"""

    def test_assign_type_degrees_converted_to_radians(self):
        blocks = [_transform3d_block(rot=(0.0, 0.0, 0.0))]
        expressions = [("Transform3D", "rotationX", "190", 4, True)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.f("Transform3D").raw["LocalRotation"]["X"],
                               math.radians(190))

    def test_add_type_degrees_also_converted(self):
        blocks = [_transform3d_block(rot=(math.radians(10), 0.0, 0.0))]
        expressions = [("Transform3D", "rotationX", "20", 0, True)]  # Add
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.f("Transform3D").raw["LocalRotation"]["X"],
                               math.radians(10) + math.radians(20))

    def test_multiply_type_is_not_converted(self):
        """Multiply/Divide 的公式结果是无量纲倍率（"转速乘 2 倍"），不是角度本身，不该
        被当角度换算——全语料 560 条真实绑定的公式里这两档一次都没出现，但核心层的判据
        不能只靠"语料里没见过"就假设它不会发生。"""
        blocks = [_transform3d_block(rot=(math.radians(10), 0.0, 0.0))]
        expressions = [("Transform3D", "rotationX", "2", 2, True)]  # Multiply
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.f("Transform3D").raw["LocalRotation"]["X"],
                               math.radians(10) * 2)

    def test_missing_flag_defaults_to_not_angle_for_backward_compatible_4_tuples(self):
        """旧的 4 元组调用点（没有第 5 个元素）必须继续按"不是角度"处理，不强制迁移。"""
        blocks = [_transform3d_block(rot=(0.0, 0.0, 0.0))]
        expressions = [("Transform3D", "rotationX", "190", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.step()
        self.assertAlmostEqual(sim.em.f("Transform3D").raw["LocalRotation"]["X"], 190.0)

    def test_reproduces_the_reported_bug_scenario(self):
        """精确复现用户报告的公式。总行程应该是 220°（从 -30 扫到 190，方向是正的——
        2026-09-16 实机确认的 `Lerp` 方向），不是原来把弧度当度数的那个量级。
        这条断言注回"不转换"会 FAIL（220 弧度 vs 220 度差 57 倍）。

        ⚠ **不能断言"每帧恒定 1.83°"**：`Clamp` 带 smoothstep 缓动（同日实机确认），
        逐帧增量在两端接近 0、中点最大（约线性速率的 1.5 倍）。这条测试原来就是按
        "每帧恒定"写的，缓动确认之后改成断言端点总量 + 单调性。"""
        blocks = [_transform3d_block(rot=(0.0, 0.0, 0.0))]
        expressions = [("Transform3D", "rotationX",
                        "Lerp(-30, 190, SmoothStep(0, 120, TIMER))", 4, True)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        drifts = []
        for _ in range(122):
            sim.step()
            drifts.append(math.degrees(sim.em.rotation_drift.x))
        self.assertAlmostEqual(drifts[0], -30.0, places=2)      # 起点
        self.assertAlmostEqual(drifts[-1], 190.0, places=2)     # 终点，总行程 220°
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(drifts, drifts[1:])),
                        "必须单调递增")
        # smoothstep 的中点速率是线性速率的 1.5 倍（缓动的招牌）
        mid_rate = drifts[61] - drifts[60]
        self.assertAlmostEqual(mid_rate, 1.5 * 220.0 / 120.0, places=1)


def _parentoptions_block(use_local=1, rate=1.0):
    return ("ParentOptions", {
        "RelationPos": {"x": 2, "y": 2, "z": 2},
        "RelationRot": {"x": 2, "y": 2, "z": 2},
        "RelationScl": {"x": 0, "y": 0, "z": 0},
        "ParticleUseLocal_re7": 0,
        "ParticleUseLocal": use_local,
        "ConstInheritRate": {"s": rate, "r": 0.0},
        "ConstFrame": {"r": 0, "s": 0},
        "ConstReleaseFrame": {"r": 0, "s": 0},
        "ConstInheritReleaseRate": 0.0,
        "PragUkn1": 0, "PragUkn2": 0, "BoneName": "",
    })


def _spawn_one_block():
    return ("Spawn", {"MaxParticles": 10, "SpawnNum": {"x": 1, "y": 1},
                      "IntervalFrame": {"x": 0, "y": 0},
                      "EmitterDelayFrame": {"x": 0, "y": 0},
                      "LoopNum": {"r": 1, "s": 0}})


def _life_forever_block():
    return ("Life", {"AppearFrame": {"r": 0, "s": 0}, "KeepFrame": {"r": 200, "s": 200},
                     "VanishFrame": {"r": 0, "s": 0}, "KeepHoldFrame": {"r": 0, "s": 0},
                     "Flags": 0})


class TestReplayIsIdempotent(unittest.TestCase):
    """用户报告的真实故障："第一次播放会歪掉一些，从第二次开始就正常了"。

    根因：`Simulator.reset()` 每次都调 `registry.build_behaviors(self.blocks, cfg)`，
    但 `self.blocks` 是 `__init__` 时存的**同一份**引用，跨多次 `reset()` 复用；
    `_eval_expressions()` -> `patch_field()` 会直接在 `FieldView.raw` 上原地写。如果
    `build_behaviors()` 不深拷贝 `fields` 就塞进 `FieldView`，第一次播放最后一帧改过的值
    会永久残留在 `blocks` 自己的字典里——第二次 `reset()` 时 `Transform3D.
    on_emitter_init()` 快照的"基准值"读到的不是导入时的原始值，而是上一轮播放的残留值，
    `em.drift`/`em.origin` 从第二次起就和第一次不一样，而且从第二次起会一直卡在这个被
    污染的状态（第三次、第四次都和第二次相同，只有第一次是"孤例"）——这条测试同时钉住
    这两点：连续两次 `reset()`+跑完全程，结果必须逐帧相同；用真正独立的 `Simulator`
    重新构造一遍（模拟"重新导入"）也必须得到同一个结果，证明第一次和第二次里**只有
    一个**是对的，不能靠"多播放几次就稳定了"蒙混过去。"""

    def _run_once(self, blocks, expressions, steps=5):
        sim = Simulator(list(blocks), SimConfig(seed=1), expressions=list(expressions))
        sim.reset()
        log = []
        for _ in range(steps):
            sim.step()
            log.append((sim.em.origin.y, sim.em.drift.y))
        return log

    def test_second_reset_on_the_same_simulator_matches_the_first(self):
        blocks = [_transform3d_block(pos=(0.0, 0.0, 0.0))]
        expressions = [("Transform3D", "translationY", "Lerp(0, -1, SmoothStep(0, 12, TIMER))", 4)]
        sim = Simulator(list(blocks), SimConfig(seed=1), expressions=list(expressions))

        def play():
            sim.reset()
            return [(sim.step().origin.y, sim.em.drift.y) for _ in range(5)]

        first_play = play()
        second_play = play()
        third_play = play()
        self.assertEqual(first_play, second_play,
                         "第二次播放和第一次不一样——blocks 字典被上一轮播放污染了")
        self.assertEqual(second_play, third_play)

    def test_matches_a_freshly_constructed_simulator(self):
        """不只是"重播稳定"，第一次播放的结果必须和**另起一个全新 Simulator**（模拟重新
        导入文件）完全一致——排除"其实是第二次才对、第一次才是异常"这种可能性。"""
        blocks = [_transform3d_block(pos=(0.0, 0.0, 0.0))]
        expressions = [("Transform3D", "translationY", "Lerp(0, -1, SmoothStep(0, 12, TIMER))", 4)]

        first = self._run_once(blocks, expressions)
        fresh = self._run_once(blocks, expressions)
        self.assertEqual(first, fresh)


class TestTransform3DExpressionDrivesTrackedParticles(unittest.TestCase):
    """用户报告的真实场景：`234_PLG_trail (PolygonTrail)`——`Transform3DExpression` 用
    `Lerp(Clamp(TIMER,12,0),-1,0)` 把 `LocalPosition.Y` 从 0 逐帧动到 -1（assign 方式；
    方向按 2026-09-16 实机确认的 `Lerp` 读法更正，见 `test_real_corpus_example` 的说明），
    entry 的 `ParentOptions.ParticleUseLocal=1`。在真实场景里粒子被观察成"焊死不动"：
    `em.origin.y` 逐帧正确地往 -1 走，但只有 `Transform3D`（写 `em.drift`/`em.origin`）
    没有 `ParentOptions`（把 `em.velocity` 转给粒子）时，`Spawn` 生成的粒子只在出生那一刻
    拷贝了一次 `em.origin`，之后再没人碰它。这条测试钉住"两者接起来之后粒子跟得上"，
    单独测 `Transform3DBehavior`（上面那个类）或单独测 `ParentOptions`
    （`test_sim_behaviors.py::TestParentOptions`）都不会触发这个组合故障。"""

    def _run(self, with_parentoptions, steps=13):
        # 真实文件里 Transform3D.LocalPosition 的导入值是 (0,0,0)——entry 没有绑父级，
        # 静态位置就是原点，运动完全靠这条 Expression 曲线（drift）产生。
        blocks = [_transform3d_block(pos=(0.0, 0.0, 0.0)), _spawn_one_block(),
                 _life_forever_block()]
        if with_parentoptions:
            blocks.append(_parentoptions_block(use_local=1))
        expressions = [("Transform3D", "translationY", "Lerp(0, -1, SmoothStep(0, 12, TIMER))", 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.reset()
        origin_at_spawn = None
        for _ in range(steps):
            sim.step()
            if origin_at_spawn is None and sim.em.particles:
                origin_at_spawn = sim.em.origin.y
        return sim, origin_at_spawn

    def test_without_parentoptions_particle_is_frozen_at_spawn_position(self):
        """复现故障：没有 `ParentOptions` 时粒子焊死在出生那一刻的 origin，尽管
        `em.origin.y` 之后已经继续往 -1 走了（TIMER 从 0 到 12，`Lerp` 让 Y 从 0 变到 -1，
        13 步之后二者应该有明显差距，不然这条断言测不出"没跟上"）。"""
        sim, origin_at_spawn = self._run(with_parentoptions=False)
        self.assertAlmostEqual(origin_at_spawn, 0.0)
        self.assertAlmostEqual(sim.em.origin.y, -1.0)
        self.assertAlmostEqual(sim.em.particles[0].pos.y, origin_at_spawn)

    def test_with_parentoptions_particle_tracks_the_moving_origin(self):
        """接上 `ParentOptions.ParticleUseLocal=1` 之后粒子应该跟上 `em.origin`，
        而不是停在出生位置。"""
        sim, origin_at_spawn = self._run(with_parentoptions=True)
        self.assertAlmostEqual(origin_at_spawn, 0.0)
        self.assertAlmostEqual(sim.em.origin.y, -1.0)
        self.assertAlmostEqual(sim.em.particles[0].pos.y, sim.em.origin.y)


class TestParentOptionsTracksRotationAsAnArc(unittest.TestCase):
    """用户报告的第二个真实场景：entry 的 `Transform3DExpression` 在转圈
    （`LocalRotation` 逐帧变化）、`ParentOptions.ParticleUseLocal=1` 时，一个已经出生、
    偏离原点的粒子应该被这个旋转**甩出一段圆弧**（半径不变、角度渐变）——不是被"焊"在
    某个偏移量上跟着整体平移，也不是（旧的渲染时方案，已移除）让粒子的历史轨迹在渲染
    时被按"现在的朝向"整体重新转一遍。这里直接验证粒子在模拟层的位置轨迹本身就是一段
    圆弧：`RibbonFollow` 的尾迹只是把这些点连起来画出来，不需要、也不应该在渲染层再对
    历史点做任何旋转（见 `efx_sim/behaviors/parentoptions.py` 和
    `blender_efx_re/sim_preview.py::_entry_matrix()` 的说明）。"""

    def test_particle_traces_an_arc_of_constant_radius(self):
        step_angle = math.radians(30)
        blocks = [_transform3d_block(rot=(0.0, 0.0, 0.0)), _spawn_one_block(),
                 _life_forever_block(), _parentoptions_block(use_local=1)]
        # `step_angle * TIMER` 的文本写法是 `step_angle + TIMER`（`+` 是乘法，
        # 见 `TestBinaryOperatorsAreAllMislabeled`）。
        expressions = [("Transform3D", "rotationZ", "(%r * TIMER)" % step_angle, 4)]
        sim = Simulator(blocks, SimConfig(seed=1), expressions=expressions)
        sim.reset()
        sim.step()   # frame 0：粒子在原点出生（LocalPosition 恒为 0，没有平移驱动）
        p = sim.em.particles[0]
        p.pos = Vec3(2.0, 0.0, 0.0)   # 手动挪到偏离原点 2 米处，模拟"已经出生、离开了原点"

        angles = []
        for _ in range(6):
            sim.step()
            self.assertAlmostEqual(p.pos.length(), 2.0, places=4,
                                   msg="半径必须不变——这是圆弧而不是被整体平移/重新定位")
            angles.append(math.atan2(p.pos.y, p.pos.x))
        diffs = [abs(b - a) for a, b in zip(angles, angles[1:])]
        for d in diffs:
            # 角必须每帧真的转过 step_angle（弧度），不是原地不动，也不是每帧累计越转
            # 越多（那是把累计量当增量用的旧 bug）。
            self.assertAlmostEqual(d, step_angle, places=3)


if __name__ == "__main__":
    unittest.main()
