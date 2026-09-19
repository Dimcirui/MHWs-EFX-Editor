# -*- coding: utf-8 -*-
"""
`efx_sim/expr_text.py`（vendor 记法 ⇄ 规范记法中转层）的回归。

上游 `a96e1d9` 已经把 `BinaryExpressionOperator` / `EfxExpressionFunction` 按真实语义
重命名了，所以中转层缩小成两件事：

1. **四个操作数顺序还是反的**（`/` `-` `Mod(` `PowOp(`）——`ToString()` 打印
   `(left OP right)`，而引擎的顺序是 `right OP left`。乘和加可交换，正好蒙对。
2. **16 号仍然叫 `InvLerp`，而它是真 `clamp`**（2026-09-17 实机），规范侧显示 `Clamp`
   并把参数重排成人人预期的 `(value, lo, hi)`。

`PowOp` 这个字面量来自本仓的 vendor 补丁 0007：上游把操作码 0 也叫 `Pow`，和函数表里的
`Pow`（操作码 20）在文本上撞名，而解析器先试 `BinaryExpressionOperator`——于是每次
dump/load 都把操作码 20 静默改写成 0（字节级实测确认）。

## ⚠ 往返自洽性在这里是**不够的**

`_CANONICAL_TO_VENDOR` 是从 `_VENDOR_TO_CANONICAL` **推导**出来的，所以"正向忘了交换
操作数、反向也忘了"这类错误在往返里会互相抵消——实测把 `swap` 逐个改成 `False`，文本
往返一条都不报错。这正是「六个运算符全标错」那个坑的同一类：**双向一致的错误对往返验证
完全免疫**。

所以本文件的主判据是 `_eval_canonical()`：一个**独立写出来**的规范记法求值器，函数语义
直接照实机结论手写，**不复用 `expr._apply_call()` / `_eval_binary_operator()`**。它和
`expr.evaluate()` 对同一棵树给出的数必须逐点相同——两条互不共享代码的路径同时对上，
交换操作数那类错误才无处可藏。
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


def _lerp(t, a, b):
    return b + (a - b) * _saturate(t)


def _smoothstep(value, hi, lo):
    if hi == lo:
        return 0.0
    u = _saturate((value - lo) / (hi - lo))
    return u * u * (3.0 - 2.0 * u)


def _remap(a, b, hi, lo, t):
    if hi == lo:
        return 0.0
    return b + (a - b) * _saturate((t - lo) / (hi - lo))


def _guarded(fn, ok):
    """定义域外一律返回 0.0——和 `expr._eval_known_unary()` 一样的兜底约定。

    ⚠ 这条兜底**不是本文件要测的东西**（它是我们这层的约定，不是实机观察到的引擎行为），
    这里复刻只是为了让两条路径在定义域外也可比；真正被对拍的是定义域内的语义。
    """
    return lambda x: float(fn(x)) if ok(x) else 0.0


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
    # 操作码 16 是真 clamp。规范记法把参数重排成人人预期的 `Clamp(value, lo, hi)`，
    # 所以这里的形参顺序和 vendor 侧的 `(hi, lo, value)` 相反。
    "Clamp": lambda value, lo, hi: max(lo, min(hi, value)),
    "SmoothStep": _smoothstep,
    "Remap": _remap,
    "Min": min, "Max": max,
    # 规范侧也重排过：vendor 的 `Pow(指数, 底)` -> 规范 `Pow(底, 指数)`
    "Pow": lambda base, exponent: float(base) ** float(exponent),
}


def _eval_canonical(text, variables):
    """规范记法文本 -> float。`%` 按 **C 的 `fmod`** 算（符号跟被除数），不是 Python 的 `%`。"""
    tree = ast.parse(expr._sanitize_identifiers(text), mode="eval")

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
                try:
                    return float(a) ** float(b)
                except (ValueError, OverflowError, ZeroDivisionError):
                    return 0.0
            raise AssertionError("规范记法里不该有这个运算符：%r" % (node.op,))
        if isinstance(node, ast.Call):
            return _CANON_FUNCS[node.func.id](*[go(a) for a in node.args])
        raise AssertionError("不支持的节点：%r" % (type(node).__name__,))

    return go(tree.body)


#: 覆盖全部六个操作码、全部三种 arity、负号折叠、嵌套结合性、以及每一类已确认函数。
#: 这批是从 2026-09-16/17 实机验证用的那些公式翻过来的（旧记法 -> a96e1d9 新记法）。
VENDOR_SAMPLES = [
    # 基准与恒等式（实机验证用的那一批）
    "((40 / TIMER) - 1)",
    "((2 * (60 / TIMER)) - ((60 / TIMER) + (60 / TIMER)))",
    "((4 / (60 / TIMER)) - (0.25 * (60 / TIMER)))",
    "Mod(TIMER, (3 * TIMER))",
    "((60 / TIMER) - Log(Exp((60 / TIMER))))",
    "(Floor((12 / TIMER)) + Ceil(-((12 / TIMER))))",
    "(Min(Max((1 - (30 / TIMER)), 0), 1) - Saturate((1 - (30 / TIMER))))",
    "((PowOp(2, (60 / TIMER)) * ((2 * (60 / TIMER)) - 3)) - SmoothStep(TIMER, 60, 0))",
    "((60 / TIMER) - Remap(1, 0, 60, 0, TIMER))",
    "(Remap(4, 1, 15, 0, TIMER) - Lerp((15 / TIMER), 4, 1))",
    # 结合性：嵌套在**左**子树上的同优先级运算（交换之后会落到右操作数，最容易漏括号）
    "((1 - TIMER) - 2)",
    "((TIMER / 2) / 3)",
    "(TIMER / (2 / 3))",
    "PowOp(2, PowOp(3, TIMER))",
    "PowOp(PowOp(2, 3), TIMER)",
    "Mod(Mod(1, 2), TIMER)",
    "Mod(1, Mod(2, TIMER))",
    "((1 * 2) * TIMER)",
    "((1 + 2) + TIMER)",
    # 一元负号、语料里的真实写法
    "(45 * -(Sin((PI * SmoothStep(TIMER, 30, 0)))))",
    "(1.5 / Length)",
    "SinDeg(Remap(90, 0, 15, 0, TIMER))",
    "-1",
    "-TIMER",
    "InvLerp(3, 5, Saturate(TIMER))",
    "InvLerp(90, 0, (45 + TIMER))",
    "Pow(2, TIMER)",
    "Asin(Saturate((60 / TIMER)))",
    "Log10(Abs((1 / TIMER)))",
    "CosDeg(Remap(90, 0, 15, 0, TIMER))",
    # a96e1d9 之后才写得出来的：操作码 3 = Acos（旧解析器不认这个名字）
    "Acos(Saturate((60 / TIMER)))",
]

#: 求值用的变量。`TIMER` 扫 `[-3, 90]`，覆盖负值/零/大值三档（输入只喂 `[0, 1]` 会让
#: 好几组候选语义互相全等，见 docs/EXPRESSION_RULES.md）。
_SWEEP = [float(k) for k in range(-3, 91)]
_EXTRA_VARS = {"PI": math.pi, "Length": 2.0}


def _vendor_canonical_form(text):
    """vendor 文本 -> vendor 的**规范排版**（无条件加括号那一套）。

    直接拿手写的原文当往返基线会得到假红：排版差异是 vendor `ToString()` 本来就有的
    行为，不是本层的事。
    """
    return expr.emit_parsed(expr.parse(text))


class TestNotationRoundTrip(unittest.TestCase):
    """记法互转必须是**逐字**的双射（在 vendor 规范排版上）。"""

    def test_every_sample_round_trips_verbatim(self):
        for raw in VENDOR_SAMPLES:
            base = _vendor_canonical_form(raw)
            with self.subTest(formula=base):
                canon = expr_text.vendor_to_canonical(base)
                self.assertEqual(expr_text.canonical_to_vendor(canon), base)

    def test_second_root_value_branch_survives(self):
        """`a | b` 的第二支语义没证实，但不许在转换里丢掉（铁律 #1）。"""
        base = (_vendor_canonical_form("((40 / TIMER) - 1)")
                + expr._ROOT_VALUE_SEPARATOR + "TIMER")
        canon = expr_text.vendor_to_canonical(base)
        self.assertIn("TIMER", canon.split(expr._ROOT_VALUE_SEPARATOR)[1])
        self.assertEqual(expr_text.canonical_to_vendor(canon), base)

    def test_unknown_names_pass_through_untouched(self):
        """认不出来的函数名原样保留，不装作知道（不把猜测当事实）。

        13 / 14 号引擎没实现、枚举里也没有，是"真未知"的现成例子。
        """
        self.assertEqual(expr_text.canonical_function_name("Func13"), "Func13")
        self.assertEqual(expr_text.vendor_function_name("Func13"), "Func13")
        base = _vendor_canonical_form("Func13(TIMER)")
        self.assertEqual(
            expr_text.canonical_to_vendor(expr_text.vendor_to_canonical(base)), base)


class TestCanonicalMeansWhatItSays(unittest.TestCase):
    """**本文件的主判据**：规范文本按真实数学语义算出来的数，必须等于 vendor 文本
    经 `efx_sim.expr` 算出来的数。

    两条路径不共享任何求值代码，所以"正反两边一起错"在这里藏不住——而那恰恰是文本
    往返抓不到的那一类（见模块 docstring）。
    """

    def _assert_agrees(self, vendor_text):
        base = _vendor_canonical_form(vendor_text)
        canon = expr_text.vendor_to_canonical(base)
        parsed = expr.parse(base)
        for timer in _SWEEP:
            variables = dict(_EXTRA_VARS, TIMER=timer)
            mine = expr.evaluate(parsed, expr.EvalContext(variables))
            theirs = _eval_canonical(canon, variables)
            if math.isnan(mine) or math.isnan(theirs):
                self.assertTrue(math.isnan(mine) and math.isnan(theirs))
                continue
            scale = max(1.0, abs(mine), abs(theirs))
            self.assertLess(abs(mine - theirs), 1e-9 * scale,
                            "TIMER=%g\n  vendor : %s -> %r\n  规范   : %s -> %r"
                            % (timer, base, mine, canon, theirs))

    def test_all_samples_agree_pointwise(self):
        for raw in VENDOR_SAMPLES:
            with self.subTest(formula=raw):
                self._assert_agrees(raw)

    def test_each_operator_maps_to_its_real_semantics(self):
        """六个操作码逐个单独钉一次，连操作数顺序一起钉死。

        a96e1d9 之后**乘和加已经不用动了**（可交换，vendor 写对了），剩下四个仍然反着。
        """
        expected = {
            "(A * B)": "A * B",         # 操作码 1，名字对、顺序无关
            "(A + B)": "A + B",         # 操作码 4，同上
            "(A / B)": "B / A",         # 操作码 2，**换操作数**
            "(A - B)": "B - A",         # 操作码 5，**换操作数**
            "Mod(A, B)": "B % A",       # 操作码 3，换操作数 + 变中缀
            "PowOp(A, B)": "B ** A",    # 操作码 0，换操作数 + 变中缀
        }
        for vendor_text, canonical_text in expected.items():
            with self.subTest(op=vendor_text):
                self.assertEqual(expr_text.vendor_to_canonical(vendor_text), canonical_text)
                self.assertEqual(expr_text.canonical_to_vendor(canonical_text),
                                 _vendor_canonical_form(vendor_text))

    def test_only_four_of_six_operators_still_need_swapping(self):
        """把"还需要转换"这件事本身钉住——上游哪天把操作数也翻过来，这条会提醒改表。"""
        swapped = {name for name, (_sym, swap) in expr.CANONICAL_OPERATORS.items() if swap}
        self.assertEqual(swapped, {"/", "-", "Mod", "PowOp"})
        kept = {name for name, (_sym, swap) in expr.CANONICAL_OPERATORS.items() if not swap}
        self.assertEqual(kept, {"*", "+"})

    def test_pow_function_and_pow_operator_read_the_same_way_round(self):
        """规范记法里 `a ** b` 和 `Pow(a, b)` 必须是同一个意思。

        vendor 侧两者的参数顺序都是 `(指数, 底)`，而规范侧的 `**` 是"底在左"。函数那个
        因此在本层做了参数重排（`_FUNC_ARG_ORDER`）——不重排的话同一套记法里会有两种
        相反的 pow 读法。
        """
        self.assertEqual(expr_text.vendor_to_canonical("PowOp(3, 2)"), "2 ** 3")
        self.assertEqual(expr_text.vendor_to_canonical("Pow(3, 2)"), "Pow(2, 3)")
        for text in ("PowOp(3, TIMER)", "Pow(3, TIMER)"):
            self._assert_agrees(text)

    def test_lerp_family_arguments_are_not_reordered(self):
        """`Lerp` / `SmoothStep` / `Remap` 的参数顺序**保持 vendor 一侧**。

        它们的顺序反直觉归反直觉，界面上由 `expr.CALL_ARG_ROLES` 逐槽位标出来；在本层
        再重排一次，公式文本就会和行视图/参数角色名对不上。只有 `Pow` 和 `InvLerp`
        例外，理由各自写在 `_FUNC_ARG_ORDER` 的注释里。
        """
        for vendor_name in ("Lerp", "SmoothStep", "Remap"):
            self.assertNotIn(vendor_name, expr_text._FUNC_ARG_ORDER)
        self.assertEqual(expr_text.vendor_to_canonical("Lerp(1, 2, 3)"), "Lerp(1, 2, 3)")
        self.assertEqual(expr_text.vendor_to_canonical("SmoothStep(1, 2, 3)"),
                         "SmoothStep(1, 2, 3)")


class TestSixteenIsClampNotInvLerp(unittest.TestCase):
    """操作码 16 是**唯一**还和 vendor 命名不一致的：vendor 叫 `InvLerp`，实为真 `clamp`。

    2026-09-17 实机确认（五条读数唯一确定），上游还没改。等上游改了，
    `CALL_DISPLAY_NAMES` 里这一条会变成恒等、整套别名机制可以删掉。
    """

    def test_sixteen_displays_as_clamp(self):
        self.assertEqual(expr_text.canonical_function_name("InvLerp"), "Clamp")
        self.assertEqual(expr_text.vendor_function_name("Clamp"), "InvLerp")

    def test_it_is_the_only_non_identity_display_name(self):
        """其余全是恒等——这条是"UI 已经和 enum 对齐"的机器判据。"""
        non_identity = {v: d for v, d in expr.CALL_DISPLAY_NAMES.items() if v != d}
        self.assertEqual(non_identity, {"InvLerp": "Clamp"})

    def test_seventeen_needs_no_translation_any_more(self):
        """17 号上游已经叫 `SmoothStep` 了，两边同名、原样透传。"""
        self.assertEqual(expr_text.canonical_function_name("SmoothStep"), "SmoothStep")
        self.assertEqual(expr_text.vendor_function_name("SmoothStep"), "SmoothStep")

    def test_canonical_clamp_puts_value_first_like_everyone_expects(self):
        """vendor 侧是 `(hi, lo, value)`；一个叫 `Clamp` 的函数把 value 放在最后，照字面
        读必错，所以规范记法重排成 `Clamp(value, lo, hi)`。"""
        self.assertEqual(expr_text.vendor_to_canonical("InvLerp(90, 0, 45)"),
                         "Clamp(45, 0, 90)")
        self.assertEqual(expr_text.canonical_to_vendor("Clamp(45, 0, 90)"),
                         "InvLerp(90, 0, 45)")

    def test_node_sockets_follow_the_same_reorder(self):
        """节点视口的插槽顺序走 `display_arg_order()`，必须和文本一致——两处各写一张表
        就会漂，而漂了之后文本往返照样全绿。"""
        self.assertEqual(expr_text.display_arg_order("InvLerp", 3), [2, 1, 0])
        self.assertEqual(expr_text.display_arg_order("SmoothStep", 3), [0, 1, 2])


class TestMixingNotationsIsRejected(unittest.TestCase):
    """规范文本里出现 vendor 字面量 -> **直接拒绝**，不静默透传。

    ⚠ 真事故（2026-09-17）：把 vendor 写法粘进只认规范记法的公式栏。名字被当成"不认识
    的名字"原样透传，**而它在 `_FUNC_ARG_ORDER` 里有重排条目，参数被悄悄倒过来**，
    得到一条语法合法、能求值、含义完全不同的公式（实机表现是粒子飞到几十米外）。

    「认不出来的名字原样透传」只该覆盖**语义真未知**的名字（`Func13` / 将来的新操作码）。
    已知语义、只是写了 vendor 那一侧名字的，一律报错并告诉用户规范名——静默改含义比
    报错糟得多。
    """

    def test_the_only_rejected_literal_is_invlerp(self):
        """a96e1d9 之后名字基本对齐，这道拦截只剩 16 号一个目标。"""
        with self.assertRaises(expr.ExprError) as cm:
            expr_text.canonical_to_vendor("InvLerp(60, 0, TIMER)")
        self.assertIn("Clamp", str(cm.exception))
        self.assertIn("value, lo, hi", str(cm.exception))

    def test_the_real_accident_is_caught(self):
        """事故现场：vendor 写法 `(0.01 * InvLerp(60, 0, TIMER))` 粘进规范栏。"""
        with self.assertRaises(expr.ExprError):
            expr_text.canonical_to_vendor("(0.01 * InvLerp(60, 0, TIMER))")
        # 正确写法的峰值是 0.6 米；参数被倒过来的话会是 60 米量级
        good = expr_text.canonical_to_vendor("0.01 * Clamp(TIMER, 0, 60)")
        parsed = expr.parse(good)
        peak = max(expr.evaluate(parsed, expr.EvalContext({"TIMER": float(t)}))
                   for t in range(120))
        self.assertAlmostEqual(peak, 0.6, places=9)

    def test_names_that_match_both_sides_pass_through(self):
        for text in ("0.01 * Clamp(TIMER, 0, 60)", "Min(1, TIMER)", "Max(1, TIMER)",
                     "SmoothStep(TIMER, 60, 0)", "Lerp(0.5, 4, 1)",
                     "Remap(4, 1, 15, 0, TIMER)", "Pow(2, 3)", "Sin(TIMER)",
                     "Acos(0.5)", "Func13(TIMER)"):
            with self.subTest(text=text):
                expr_text.canonical_to_vendor(text)

    def test_the_guard_does_not_break_the_round_trip(self):
        """`vendor_to_canonical()` 只产规范名，所以回转永远过得了这道拦截。"""
        for raw in VENDOR_SAMPLES:
            base = _vendor_canonical_form(raw)
            with self.subTest(formula=base):
                canon = expr_text.vendor_to_canonical(base)
                self.assertEqual(expr_text.canonical_to_vendor(canon), base)


class TestModFunctionAlias(unittest.TestCase):
    """规范记法接受 `Mod(a, b)` 的函数写法（`%` 不是人人第一反应会打的符号）。

    ⚠ **两边同名、参数顺序相反**：vendor 的 `Mod(a, b)` 是 `fmod(b, a)`，规范侧
    `Mod(a, b)` 是 `fmod(a, b)`（和 C 一致）。所以它不能走"名字一样就透传"，必须走
    `_CANONICAL_FUNCTION_ALIASES` 里那条带 `swap` 的映射。
    """

    def test_mod_call_means_the_same_as_the_percent_operator(self):
        self.assertEqual(expr_text.canonical_to_vendor("Mod(3 * TIMER, TIMER)"),
                         expr_text.canonical_to_vendor("3 * TIMER % TIMER"))

    def test_mod_puts_the_modulus_on_the_right_like_c(self):
        """规范侧 `Mod(a, b)` == `fmod(a, b)`，模数在右。搞反了这条会红。"""
        vendor = expr_text.canonical_to_vendor("Mod(TIMER, 7)")
        parsed = expr.parse(vendor)
        for timer in (0.0, 3.0, 7.0, 10.0, 18.0):
            got = expr.evaluate(parsed, expr.EvalContext({"TIMER": timer}))
            self.assertAlmostEqual(got, math.fmod(timer, 7.0), places=12)

    def test_emitting_still_uses_the_operator_not_the_alias(self):
        self.assertEqual(expr_text.vendor_to_canonical("Mod(TIMER, (3 * TIMER))"),
                         "3 * TIMER % TIMER")

    def test_the_alias_swaps_because_the_vendor_side_is_reversed(self):
        self.assertEqual(expr_text._CANONICAL_FUNCTION_ALIASES["Mod"], ("Mod", True))


class TestPoisonedMappingsAreCaught(unittest.TestCase):
    """把中转表改错，`TestCanonicalMeansWhatItSays` 的判据必须真的报错（整文件拒绝导入原则1）。

    这里顺带把"往返抓不到"这件事本身钉死：同一组投毒下文本往返**全绿**，只有数值对拍
    会红。哪天有人把主判据简化成往返，这条测试会提醒他为什么不行。
    """

    def _agrees(self, vendor_text):
        base = _vendor_canonical_form(vendor_text)
        canon = expr_text.vendor_to_canonical(base)
        parsed = expr.parse(base)
        for timer in (-2.0, 0.5, 3.0, 17.0):
            variables = dict(_EXTRA_VARS, TIMER=timer)
            try:
                mine = expr.evaluate(parsed, expr.EvalContext(variables))
                theirs = _eval_canonical(canon, variables)
            except Exception:                           # noqa: BLE001
                return False
            if abs(mine - theirs) > 1e-9 * max(1.0, abs(mine)):
                return False
        return True

    def _round_trips(self, vendor_text):
        base = _vendor_canonical_form(vendor_text)
        return expr_text.canonical_to_vendor(expr_text.vendor_to_canonical(base)) == base

    def test_dropping_an_operand_swap_is_caught_by_values_but_not_by_round_trip(self):
        probes = {"/": "(7 / TIMER)", "Mod": "Mod(3, TIMER)",
                  "-": "(2 - TIMER)", "PowOp": "PowOp(3, TIMER)"}
        original = dict(expr_text._VENDOR_TO_CANONICAL)
        try:
            for vendor_op, probe in probes.items():
                symbol, _swap = original[vendor_op]
                expr_text._VENDOR_TO_CANONICAL[vendor_op] = (symbol, False)
                expr_text._CANONICAL_TO_VENDOR[symbol] = (vendor_op, False)
                with self.subTest(op=vendor_op):
                    self.assertFalse(self._agrees(probe),
                                     "数值对拍没抓到 %s 的顺序错误" % vendor_op)
                    self.assertTrue(self._round_trips(probe),
                                    "%s：往返居然抓到了——那本模块 docstring 的结论要改"
                                    % vendor_op)
                expr_text._VENDOR_TO_CANONICAL[vendor_op] = (symbol, _swap)
                expr_text._CANONICAL_TO_VENDOR[symbol] = (vendor_op, _swap)
        finally:
            expr_text._VENDOR_TO_CANONICAL.clear()
            expr_text._VENDOR_TO_CANONICAL.update(original)
            expr_text._CANONICAL_TO_VENDOR.clear()
            expr_text._CANONICAL_TO_VENDOR.update(
                {c: (v, s) for v, (c, s) in original.items()})

    def test_mapping_an_operator_to_the_wrong_symbol_is_caught(self):
        """反方向的投毒：可交换的乘/加加不加 `swap` 都一样，但**换成别的符号**必须红
        ——这条防的是"顺手把六个都设成同一种处理"。"""
        original = dict(expr_text._VENDOR_TO_CANONICAL)
        try:
            expr_text._VENDOR_TO_CANONICAL["*"] = ("/", False)
            self.assertFalse(self._agrees("(3 * TIMER)"))
            expr_text._VENDOR_TO_CANONICAL.clear()
            expr_text._VENDOR_TO_CANONICAL.update(original)
            expr_text._VENDOR_TO_CANONICAL["+"] = ("-", False)
            self.assertFalse(self._agrees("(3 + TIMER)"))
        finally:
            expr_text._VENDOR_TO_CANONICAL.clear()
            expr_text._VENDOR_TO_CANONICAL.update(original)

    def test_ignoring_associativity_when_parenthesising_is_caught(self):
        """括号规则漏掉结合性会静默改语义，往返和数值都得红。"""
        original = expr_text._wrap
        try:
            expr_text._wrap = lambda text, cp, pp, is_right: (
                text if cp >= pp else "(" + text + ")")
            self.assertFalse(self._agrees("((1 - TIMER) - 2)"))
            self.assertFalse(self._round_trips("((1 - TIMER) - 2)"))
        finally:
            expr_text._wrap = original


class TestCanonicalIsReadable(unittest.TestCase):
    """记法存在的意义就是"照着读能照着写"，所以排版本身也钉几条。"""

    def test_the_time_baseline_reads_as_plain_maths(self):
        self.assertEqual(expr_text.vendor_to_canonical("((40 / TIMER) - 1)"),
                         "1 - TIMER / 40")

    def test_redundant_parentheses_are_dropped(self):
        """vendor 侧是无条件加括号；规范侧按优先级省，不然照样没法读。"""
        self.assertEqual(
            expr_text.vendor_to_canonical(
                "((2 * (60 / TIMER)) - ((60 / TIMER) + (60 / TIMER)))"),
            "TIMER / 60 + TIMER / 60 - 2 * (TIMER / 60)")

    def test_names_already_match_the_engine_enum(self):
        """UI 用的名字和上游枚举对齐之后，绝大多数调用一个字都不用变。"""
        self.assertEqual(expr_text.vendor_to_canonical("SinDeg(Remap(90, 0, 15, 0, TIMER))"),
                         "SinDeg(Remap(90, 0, 15, 0, TIMER))")
        self.assertEqual(expr_text.vendor_to_canonical("Min(1, TIMER)"), "Min(1, TIMER)")


class DisplayArgOrderTests(unittest.TestCase):
    """节点视口的插槽顺序（`display_arg_order()`）必须和规范文本的参数顺序一致。"""

    def test_commutative_operators_keep_vendor_order(self):
        for name in ("*", "+"):
            with self.subTest(op=name):
                self.assertEqual(expr_text.display_arg_order(name, 2), [0, 1])

    def test_non_commutative_operators_swap(self):
        for name in ("/", "-", "Mod", "PowOp"):
            with self.subTest(op=name):
                self.assertEqual(expr_text.display_arg_order(name, 2), [1, 0])

    def test_order_matches_the_canonical_text_for_binary_operators(self):
        """两处不能各写一张表：这里拿文本反过来验插槽顺序。"""
        self.assertEqual(expr_text.vendor_to_canonical("(TIMER - 1)"), "1 - TIMER")
        self.assertEqual(expr_text.display_arg_order("-", 2), [1, 0])
        self.assertEqual(expr_text.vendor_to_canonical("(TIMER + 1)"), "TIMER + 1")
        self.assertEqual(expr_text.display_arg_order("+", 2), [0, 1])

    def test_unknown_names_fall_back_to_identity(self):
        self.assertEqual(expr_text.display_arg_order("Func13", 3), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
