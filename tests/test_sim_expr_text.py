# -*- coding: utf-8 -*-
"""
`efx_sim/expr_text.py`（规范记法 ⇄ 行视图）的回归。

vendor `1c2f92d` 起引擎记法的名字、操作数顺序、参数顺序已经全部按真实语义写，符号和
函数这一层不再有任何转换。本层剩下的职责只有**结构怎么读**：规范记法按数学惯例
（左结合、`-2 ^ 2` = `-(2 ^ 2)`），引擎记法镜像 vendor 解析器（右结合、负号比 `^` 紧）。

## ⚠ 往返自洽性在这里仍然**不够**

读和写如果一起错（比如都忘了结合性），文本往返照样全绿——「双向一致的错误对往返
验证完全免疫」。所以本文件的主判据是 `_eval_canonical()`：一个**独立写出来**的规范
记法求值器，函数语义直接照实机结论手写，**不复用 `expr` 的求值代码**。它和
`expr.evaluate()` 对同一条公式给出的数必须逐点相同。
"""
from __future__ import annotations

import ast
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from efx_sim import expr, expr_text  # noqa: E402


# --------------------------------------------------------------------------
# 独立求值器：规范记法 -> 数。语义照实机结论手写，不碰 efx_sim.expr 的求值代码。
# --------------------------------------------------------------------------

def _saturate(x):
    return max(0.0, min(1.0, x))


def _lerp(a, b, t):
    return a + (b - a) * _saturate(t)


def _smoothstep(lo, hi, value):
    if hi == lo:
        return 0.0
    u = _saturate((value - lo) / (hi - lo))
    return u * u * (3.0 - 2.0 * u)


def _remap(t, lo, hi, a, b):
    if hi == lo:
        return 0.0
    return a + (b - a) * _saturate((t - lo) / (hi - lo))


def _guarded(fn, ok):
    """定义域外一律返回 0.0——和 `expr._eval_known_unary()` 一样的兜底约定。

    ⚠ 这条兜底**不是本文件要测的东西**（它是我们这层的约定，不是实机观察到的引擎行为），
    这里复刻只是为了让两条路径在定义域外也可比；真正被对拍的是定义域内的语义。
    """
    return lambda x: float(fn(x)) if ok(x) else 0.0


def _pow(base, exponent):
    try:
        result = float(base) ** float(exponent)
    except (ValueError, OverflowError, ZeroDivisionError):
        return 0.0
    return 0.0 if isinstance(result, complex) else result


_CANON_FUNCS = {
    "Sin": math.sin, "Cos": math.cos,
    "Asin": _guarded(math.asin, lambda x: -1.0 <= x <= 1.0),
    "Acos": _guarded(math.acos, lambda x: -1.0 <= x <= 1.0),
    "Floor": math.floor, "Ceil": math.ceil,
    "Log": _guarded(math.log, lambda x: x > 0),
    "Log10": _guarded(math.log10, lambda x: x > 0),
    "Exp": _guarded(math.exp, lambda x: x < 709),
    "Abs": abs, "Saturate": _saturate,
    "SinDeg": lambda x: math.sin(math.radians(x)),
    "CosDeg": lambda x: math.cos(math.radians(x)),
    "Lerp": _lerp,
    # 两次钳位的先后是实机测出来的：lo > hi 时 lo 赢
    "Clamp": lambda value, lo, hi: max(lo, min(hi, value)),
    "SmoothStep": _smoothstep,
    "Remap": _remap,
    "Min": min, "Max": max,
    "Pow": _pow,
}


def _eval_canonical(text, variables):
    """规范记法文本 -> float。`%` 按 **C 的 `fmod`** 算（符号跟被除数），不是 Python 的 `%`。"""
    tree = ast.parse(expr._sanitize_identifiers(text).replace("^", "**"), mode="eval")

    def go(node):
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return float(variables[expr._desanitize_identifier(node.id)])
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -go(node.operand)
            return go(node.operand)
        if isinstance(node, ast.BinOp):
            a, b = go(node.left), go(node.right)
            op = type(node.op)
            if op is ast.Mult:
                return a * b
            if op is ast.Div:
                return 0.0 if b == 0 else a / b
            if op is ast.Mod:
                return 0.0 if b == 0 else math.fmod(a, b)
            if op is ast.Add:
                return a + b
            if op is ast.Sub:
                return a - b
            if op is ast.Pow:
                return _pow(a, b)
            raise AssertionError("规范记法里不该有这个运算符：%r" % (node.op,))
        if isinstance(node, ast.Call):
            return _CANON_FUNCS[node.func.id](*[go(a) for a in node.args])
        raise AssertionError("不支持的节点：%r" % (type(node).__name__,))

    return go(tree.body)


#: 覆盖全部六个操作码、全部三种 arity、负号折叠、嵌套结合性、以及每一类已确认函数。
#: 这批是 2026-09-16/17 实机验证用的那些公式，按 vendor 自己的重排规则机械换算到
#: `1c2f92d` 记法（换算器对 618 条语料公式和 vendor 新旧两版 dump 的输出逐字一致）。
VENDOR_SAMPLES = [
    # 基准与恒等式（实机验证用的那一批）
    "(1 - (TIMER / 40))",
    "(((TIMER / 60) + (TIMER / 60)) - ((TIMER / 60) * 2))",
    "(((TIMER / 60) * 0.25) - ((TIMER / 60) / 4))",
    "((TIMER * 3) % TIMER)",
    "(Log(Exp((TIMER / 60))) - (TIMER / 60))",
    "(Ceil(-((TIMER / 12))) + Floor((TIMER / 12)))",
    "(Saturate(((TIMER / 30) - 1)) - Min(1, Max(0, ((TIMER / 30) - 1))))",
    "(SmoothStep(0, 60, TIMER) - ((3 - ((TIMER / 60) * 2)) * ((TIMER / 60) ^ 2)))",
    "(Remap(TIMER, 0, 60, 0, 1) - (TIMER / 60))",
    "(Lerp(1, 4, (TIMER / 15)) - Remap(TIMER, 0, 15, 1, 4))",
    # 结合性：同优先级嵌套在左 / 右子树上各一份
    "(2 - (TIMER - 1))",
    "((2 - TIMER) - 1)",
    "(3 / (2 / TIMER))",
    "((3 / 2) / TIMER)",
    "((TIMER ^ 3) ^ 2)",
    "(TIMER ^ (3 ^ 2))",
    "(TIMER % (2 % 1))",
    "((TIMER % 2) % 1)",
    "(TIMER * (2 * 1))",
    "(TIMER + (2 + 1))",
    # 一元负号（含负号做 `^` 的底）、语料里的真实写法
    "(-(Sin((SmoothStep(0, 30, TIMER) * PI))) * 45)",
    "(-2 ^ TIMER)",
    "-((2 ^ TIMER))",
    "(-TIMER ^ 2)",
    "(Length / 1.5)",
    "SinDeg(Remap(TIMER, 0, 15, 0, 90))",
    "-1",
    "-TIMER",
    "Clamp(Saturate(TIMER), 5, 3)",
    "Clamp((TIMER + 45), 0, 90)",
    "Pow(TIMER, 2)",
    "Asin(Saturate((TIMER / 60)))",
    "Log10(Abs((TIMER / 1)))",
    "CosDeg(Remap(TIMER, 0, 15, 0, 90))",
    "Acos(Saturate((TIMER / 60)))",
]

#: 求值用的变量。`TIMER` 扫 `[-3, 90]`，覆盖负值/零/大值三档（输入只喂 `[0, 1]` 会让
#: 好几组候选语义互相全等，见 docs/EXPRESSION_RULES.md）。
_SWEEP = [float(k) for k in range(-3, 91)]
_EXTRA_VARS = {"PI": math.pi, "Length": 2.0}


def _vendor_canonical_form(text):
    """引擎文本 -> 我们写出去的排版（二元运算无条件加括号那一套）。"""
    return expr.emit_parsed(expr.parse(text))


def _agrees(vendor_text, sweep=_SWEEP):
    """规范文本经独立求值器算出的数，是否逐点等于引擎文本经 `expr` 算出的数。"""
    base = _vendor_canonical_form(vendor_text)
    canon = expr_text.vendor_to_canonical(base)
    parsed = expr.parse(base)
    for timer in sweep:
        variables = dict(_EXTRA_VARS, TIMER=timer)
        mine = expr.evaluate(parsed, expr.EvalContext(variables))
        theirs = _eval_canonical(canon, variables)
        if abs(mine - theirs) > 1e-9 * max(1.0, abs(mine), abs(theirs)):
            return False, "TIMER=%g  引擎 %s -> %r  规范 %s -> %r" % (
                timer, base, mine, canon, theirs)
    return True, ""


class TestNotationRoundTrip(unittest.TestCase):
    """记法互转必须是**逐字**的双射（在我们写出去的排版上）。"""

    def test_every_sample_round_trips_verbatim(self):
        for raw in VENDOR_SAMPLES:
            base = _vendor_canonical_form(raw)
            with self.subTest(formula=base):
                canon = expr_text.vendor_to_canonical(base)
                self.assertEqual(expr_text.canonical_to_vendor(canon), base)

    def test_second_root_value_branch_survives(self):
        """`a | b` 的第二支语义没证实，但不许在转换里丢掉（铁律 #1）。"""
        base = (_vendor_canonical_form("(1 - (TIMER / 40))")
                + expr._ROOT_VALUE_SEPARATOR + "TIMER")
        canon = expr_text.vendor_to_canonical(base)
        self.assertIn("TIMER", canon.split(expr._ROOT_VALUE_SEPARATOR)[1])
        self.assertEqual(expr_text.canonical_to_vendor(canon), base)

    def test_unknown_names_pass_through_untouched(self):
        """认不出来的函数名原样保留，不装作知道。13 / 14 号引擎没实现，是现成的例子。"""
        base = _vendor_canonical_form("Func13(TIMER)")
        self.assertEqual(
            expr_text.canonical_to_vendor(expr_text.vendor_to_canonical(base)), base)


class TestCanonicalMeansWhatItSays(unittest.TestCase):
    """**本文件的主判据**：两条不共享求值代码的路径对同一条公式逐点给出同一个数。"""

    def test_all_samples_agree_pointwise(self):
        for raw in VENDOR_SAMPLES:
            with self.subTest(formula=raw):
                ok, why = _agrees(raw)
                self.assertTrue(ok, why)

    def test_operators_and_functions_need_no_translation(self):
        """符号、函数名、参数顺序原样透传——上游改对之后这一层就该是恒等的。"""
        for text in ("A * B", "A + B", "A / B", "A - B", "A % B", "A ^ B",
                     "Lerp(1, 2, 3)", "Clamp(1, 2, 3)", "SmoothStep(1, 2, 3)",
                     "Remap(1, 2, 3, 4, 5)", "Pow(2, 3)", "Min(1, TIMER)", "Max(1, TIMER)"):
            with self.subTest(text=text):
                vendor = expr_text.canonical_to_vendor(text)
                self.assertEqual(expr_text.vendor_to_canonical(vendor), text)

    def test_mod_is_c_fmod_not_python_percent(self):
        for text in ("(-7 % 3)", "(7 % -3)"):
            with self.subTest(text=text):
                got = expr.evaluate(expr.parse(text), expr.EvalContext({}))
                self.assertEqual(got, math.fmod(*[float(x) for x in text[1:-1].split(" % ")]))


class TestStructureIsReadTheSameWayItIsMeant(unittest.TestCase):
    """规范栏按数学惯例读，引擎文本按 vendor 的文法读——两边都写对了、而且互转时不串。"""

    def test_left_associative_in_the_canonical_field(self):
        self.assertEqual(expr_text.canonical_to_vendor("10 - 3 - 2"), "((10 - 3) - 2)")
        self.assertEqual(expr_text.canonical_to_vendor("12 / 3 * 2"), "((12 / 3) * 2)")

    def test_engine_text_is_right_associative_like_vendor(self):
        """vendor 解析器是右递归的，引擎栏里手打的无括号公式必须按它的读法预览，
        否则预览和写进文件的不是同一个东西。"""
        self.assertEqual(expr.evaluate(expr.parse("10 - 3 - 2"), expr.EvalContext({})), 9.0)
        self.assertEqual(expr_text.vendor_to_canonical("10 - 3 - 2"), "10 - (3 - 2)")

    def test_unary_minus_and_power(self):
        """规范栏：`-2 ^ 2` = `-(2 ^ 2)`；引擎栏：`-2 ^ 2` = `(-2) ^ 2`。"""
        self.assertEqual(expr_text.canonical_to_vendor("-2 ^ 2"), "-((2 ^ 2))")
        self.assertEqual(expr.evaluate(expr.parse("-2 ^ 2"), expr.EvalContext({})), 4.0)
        self.assertEqual(expr_text.vendor_to_canonical("(-2 ^ 2)"), "(-2) ^ 2")

    def test_power_is_right_associative_in_both(self):
        self.assertEqual(expr_text.canonical_to_vendor("2 ^ 3 ^ 2"), "(2 ^ (3 ^ 2))")
        self.assertEqual(expr.evaluate(expr.parse("2 ^ 3 ^ 2"), expr.EvalContext({})), 512.0)

    def test_python_power_spelling_is_accepted_but_not_emitted(self):
        self.assertEqual(expr_text.canonical_to_vendor("TIMER ** 2"), "(TIMER ^ 2)")
        self.assertEqual(expr_text.vendor_to_canonical("(TIMER ^ 2)"), "TIMER ^ 2")


class TestModFunctionAlias(unittest.TestCase):
    """规范记法接受 `Mod(a, b)` 的函数写法（`%` 不是人人第一反应会打的符号）。"""

    def test_mod_call_means_the_same_as_the_percent_operator(self):
        self.assertEqual(expr_text.canonical_to_vendor("Mod(3 * TIMER, TIMER)"),
                         expr_text.canonical_to_vendor("3 * TIMER % TIMER"))

    def test_mod_puts_the_modulus_on_the_right_like_c(self):
        vendor = expr_text.canonical_to_vendor("Mod(TIMER, 7)")
        parsed = expr.parse(vendor)
        for timer in (0.0, 3.0, 7.0, 10.0, 18.0, -4.0):
            got = expr.evaluate(parsed, expr.EvalContext({"TIMER": timer}))
            self.assertAlmostEqual(got, math.fmod(timer, 7.0), places=12)

    def test_emitting_still_uses_the_operator_not_the_alias(self):
        self.assertEqual(expr_text.vendor_to_canonical("((TIMER * 3) % TIMER)"),
                         "TIMER * 3 % TIMER")


class TestPoisonedSemanticsAreCaught(unittest.TestCase):
    """把语义或括号规则改错，主判据必须真的报错；并把"往返抓不到"本身钉死。"""

    def _round_trips(self, vendor_text):
        base = _vendor_canonical_form(vendor_text)
        return expr_text.canonical_to_vendor(expr_text.vendor_to_canonical(base)) == base

    def test_a_reversed_operand_in_the_evaluator_is_caught(self):
        original = expr._eval_binary_operator
        try:
            expr._eval_binary_operator = lambda s, a, b, ctx: (
                original(s, b, a, ctx) if s in ("-", "/") else original(s, a, b, ctx))
            for probe in ("(2 - TIMER)", "(7 / TIMER)"):
                with self.subTest(probe=probe):
                    self.assertFalse(_agrees(probe, sweep=(-2.0, 0.5, 3.0, 17.0))[0])
                    self.assertTrue(self._round_trips(probe))
        finally:
            expr._eval_binary_operator = original

    def test_a_reversed_lerp_is_caught(self):
        original = expr._eval_ternary_known
        try:
            expr._eval_ternary_known = lambda f, args, ctx: (
                original(f, [args[1], args[0], args[2]], ctx) if f == "Lerp"
                else original(f, args, ctx))
            self.assertFalse(_agrees("Lerp(1, 4, (TIMER / 15))")[0])
        finally:
            expr._eval_ternary_known = original

    def test_ignoring_associativity_when_parenthesising_is_caught(self):
        """括号规则漏掉结合性会静默改语义，往返和数值都得红。"""
        original = expr_text._wrap
        try:
            expr_text._wrap = lambda text, cp, pp, is_right: (
                text if cp >= pp else "(" + text + ")")
            self.assertFalse(_agrees("(2 - (TIMER - 1))")[0])
            self.assertFalse(self._round_trips("(2 - (TIMER - 1))"))
        finally:
            expr_text._wrap = original


class TestCanonicalIsReadable(unittest.TestCase):
    """记法存在的意义就是"照着读能照着写"，所以排版本身也钉几条。"""

    def test_the_time_baseline_reads_as_plain_maths(self):
        self.assertEqual(expr_text.vendor_to_canonical("(1 - (TIMER / 40))"),
                         "1 - TIMER / 40")

    def test_redundant_parentheses_are_dropped(self):
        self.assertEqual(
            expr_text.vendor_to_canonical(
                "(((TIMER / 60) + (TIMER / 60)) - ((TIMER / 60) * 2))"),
            "TIMER / 60 + TIMER / 60 - TIMER / 60 * 2")


if __name__ == "__main__":
    unittest.main()
