# -*- coding: utf-8 -*-
"""
tests/test_sim_expr_edit.py —— `efx_sim/expr.py` 的结构化编辑支持（emit / 行视图 / 变换）

    python -m unittest discover -s tests

这一层是 Blender 侧结构化公式编辑器（`blender_efx_re/expr_edit.py`）的地基：面板上每一次
点击最终都变成"读行 -> 变换 -> 拼文本 -> 写回 `formula`"，而导出只认那段文本。文本一旦和
原来不同，产物字节就跟着不同——所以最要紧的断言只有一条：**没动过的公式，拆开再拼回去必须
一字不差**。

按 CLAUDE.md 验证纪律 #11，每条断言都对应一个真实故障模式，且都注入过确认会 FAIL：

- `_emit_rows()` 按优先级省略括号（vendor 那套 `AppendString()` 的规则）-> 和语料文本对不上，
  这里 `(1.5 - Length)` 一类的用例立刻红；
- 负号规范化成 `0 - x` -> `-0.5` 用例红（二进制里那是两种不同的组件序列）；
- 浮点改用 `repr()` -> `20`/`0.1` 这些用例变成 `20.0`/`0.1` 之外的写法，红；
- `Min`/`Max` 当成中缀运算符发（它在 vendor 那边确实是 `BinaryExpressionOperator`）->
  `Min(5, Length)` 变成 `(5 Min Length)`，红。

`_REAL_FORMULAS` 是从官方语料抽样扫出来的真实公式（1044 个 `.efx.5571972` 里 898 条不同
公式，全部通过；这里挑的是覆盖各种节点形态的代表）。语料本身不可分发、不在版本控制里，
所以把代表样本当字面量钉在这儿。
"""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import expr  # noqa: E402


#: 真实语料里的公式，覆盖：单变量、单常量、四则、嵌套四则、负号（字面量/子树两种写法）、
#: 二元函数、三元函数、未确认语义函数、5 参函数、未解析出名字的 `ext:` 占位。
_REAL_FORMULAS = (
    "BloodColor",
    "0",
    "Length",
    "(0.5 + BloodColor)",
    "(1.5 - Length)",
    "(20 - Length)",
    "(Initial_Len - Current_Len)",
    "Min(5, Length)",
    "Max(0.2, GLength)",
    "Func21(2, 20, 10, 0, TIMER)",
    "Lerp(Clamp(TIMER, 180, 90), -0.5, 0)",
    "Lerp(Clamp(TIMER, 8, 0), -0.1, -0.025)",
    "Lerp(Clamp(ext:302732036, 6, 3), 0, 8)",
    "Lerp(Unary11(Func21(90, 0, 20, 0, TIMER)), -1, 0)",
    "(45 + -(Unary0((PI + Clamp(TIMER, 30, 0)))))",
    "Lerp(Unary10(Min(2, Color_A)), GREEN_P, Lerp(Unary10(Min(1, Color_A)), YELLOW_P, "
    "Lerp(Unary10(Color_A), WHITE_P, RED_P)))",
    "Min(Clamp(ukn:1017435601, 0.7, 0.6), Clamp(ukn:1017435601, 0.3, 0.2))",
)


class TestRoundTrip(unittest.TestCase):
    """拆开再拼回去必须一字不差——这是整个结构化编辑器能不能碰真文件的前提。"""

    def test_emit_reproduces_source_text(self):
        for text in _REAL_FORMULAS:
            with self.subTest(formula=text):
                self.assertEqual(expr.emit_parsed(expr.parse(text)), text)

    def test_rows_round_trip(self):
        for text in _REAL_FORMULAS:
            with self.subTest(formula=text):
                parsed = expr.parse(text)
                rows = expr.to_rows(parsed)
                self.assertEqual(expr.from_rows(rows, parsed.second_branch), text)

    def test_second_branch_is_carried_through(self):
        """`a  |  b` 的第二支语义没证实，但不能丢（铁律 #2）。连接符是两边各两个空格。"""
        text = "TIMER  |  Min(1, TIMER)"
        parsed = expr.parse(text)
        self.assertEqual(parsed.second_branch, "Min(1, TIMER)")
        self.assertEqual(expr.emit_parsed(parsed), text)
        self.assertEqual(expr.from_rows(expr.to_rows(parsed), parsed.second_branch), text)


class TestNegationFolding(unittest.TestCase):
    """`-1` 折叠成一行带符号常量（`_collect_rows()`），以及它带出来的那个坑。"""

    def test_negative_literal_is_one_row(self):
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 12, 0), 190, -30)"))
        self.assertEqual([r["kind"] for r in rows],
                         ["CALL", "CALL", "VAR", "CONST", "CONST", "CONST", "CONST"])
        self.assertEqual(rows[-1]["value"], -30.0)
        self.assertEqual(expr.from_rows(rows), "Lerp(Clamp(TIMER, 12, 0), 190, -30)")

    def test_negated_variable_stays_two_rows(self):
        """`-TIMER` 折不了（没有"带符号的变量"这种东西），仍然是 NEG + VAR。"""
        rows = expr.to_rows(expr.parse("-TIMER"))
        self.assertEqual([r["kind"] for r in rows], ["NEG", "VAR"])
        self.assertEqual(expr.from_rows(rows), "-TIMER")

    def test_negated_negative_literal_needs_parens(self):
        """`-(-1)`：折叠之后变成"NEG 套负常量"，不加括号会拼成 `--1`（语法非法）。
        这是折叠**引入**的情形，vendor 自己产不出来。"""
        rows = expr.to_rows(expr.parse("-(-1)"))
        self.assertEqual([r["kind"] for r in rows], ["NEG", "CONST"])
        self.assertEqual(rows[1]["value"], -1.0)
        text = expr.from_rows(rows)
        self.assertEqual(text, "-(-1)")
        # 最要紧的：拼出来的东西必须还能解析回来
        self.assertEqual(expr.from_rows(expr.to_rows(expr.parse(text))), text)

    def test_folding_does_not_change_any_corpus_text(self):
        """折叠是**纯行结构**的事，文本形式一个字都不许变（导出字节因此不变）。"""
        for text in _REAL_FORMULAS:
            with self.subTest(formula=text):
                parsed = expr.parse(text)
                self.assertEqual(
                    expr.from_rows(expr.to_rows(parsed), parsed.second_branch), text)


class TestFloatFormat(unittest.TestCase):
    """`format_float()` 是 vendor `ExpressionFloat.ToString()` 的镜像（F6 + 去尾零）。"""

    def test_matches_vendor_format(self):
        cases = [
            (0.0, "0"), (-0.0, "-0"), (1.0, "1"), (20.0, "20"), (100.0, "100"),
            (0.5, "0.5"), (0.1, "0.1"), (-0.025, "-0.025"), (1.5, "1.5"),
            (0.0000001, "0"),   # F6 之外的精度在文本形式里本来就存不下
        ]
        for value, want in cases:
            with self.subTest(value=value):
                self.assertEqual(expr.format_float(value), want)


class TestRowEncoding(unittest.TestCase):
    def test_depth_and_arity(self):
        # `-0.5` 折叠成一行带符号常量，所以是 7 行（见 TestNegationFolding）
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"))
        self.assertEqual([r["kind"] for r in rows],
                         ["CALL", "CALL", "VAR", "CONST", "CONST", "CONST", "CONST"])
        self.assertEqual([r["depth"] for r in rows], [0, 1, 2, 2, 2, 1, 1])
        self.assertEqual([r["arity"] for r in rows], [3, 3, 0, 0, 0, 0, 0])

    def test_subtree_span_and_parent(self):
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"))
        self.assertEqual(expr.subtree_span(rows, 0), 7)
        self.assertEqual(expr.subtree_span(rows, 1), 4)
        self.assertEqual(expr.subtree_span(rows, 5), 1)
        self.assertEqual([expr.parent_index(rows, i) for i in range(len(rows))],
                         [None, 0, 1, 1, 1, 0, 0])

    def test_arity_mismatch_is_rejected_not_padded(self):
        """行结构坏了就抛，不补零凑合——静默凑出一条合法但内容不对的公式正是铁律 #2 要防的。"""
        rows = expr.to_rows(expr.parse("Min(1, 2)"))
        rows[0]["arity"] = 3
        with self.assertRaises(expr.ExprError):
            expr.from_rows(rows)
        rows = expr.to_rows(expr.parse("Min(1, 2)"))
        rows[0]["arity"] = 1
        with self.assertRaises(expr.ExprError):
            expr.from_rows(rows)

    def test_empty_names_are_rejected(self):
        rows = expr.to_rows(expr.parse("TIMER"))
        rows[0]["name"] = ""
        with self.assertRaises(expr.ExprError):
            expr.from_rows(rows)


class TestMutations(unittest.TestCase):
    SRC = "Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"

    def _rows(self):
        return expr.to_rows(expr.parse(self.SRC))

    def test_convert_keeps_children_when_node_has_them(self):
        """`Clamp(a,b,c)` -> `Min` 留下前两个参数，不会把整棵子树塞进第一个参数。"""
        rows = expr.convert_node(self._rows(), 1, "Min")
        self.assertEqual(expr.from_rows(rows), "Lerp(Min(TIMER, 180), -0.5, 0)")

    def test_convert_pads_missing_arguments(self):
        rows = expr.convert_node(self._rows(), 1, "Func21")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(Func21(TIMER, 180, 90, 0, 0), -0.5, 0)")

    def test_convert_leaf_keeps_itself_as_first_argument(self):
        """叶子换成函数时把自己留成第一个参数——手滑点错不会把已经填好的值弄丢。"""
        rows = expr.convert_node(self._rows(), 2, "Unary10")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(Clamp(Unary10(TIMER), 180, 90), -0.5, 0)")

    def test_convert_to_leaf_drops_the_subtree(self):
        rows = expr.convert_node(self._rows(), 1, expr.KIND_CONST)
        self.assertEqual(expr.from_rows(rows), "Lerp(0, -0.5, 0)")
        rows = expr.convert_node(self._rows(), 1, expr.KIND_VAR)
        self.assertEqual(expr.from_rows(rows), "Lerp(TIMER, -0.5, 0)")

    def test_convert_rejects_unknown_target(self):
        with self.assertRaises(expr.ExprError):
            expr.convert_node(self._rows(), 0, "NoSuchFunction")

    def test_nest_with_negation(self):
        rows = expr.wrap_node(self._rows(), 1, expr.KIND_NEG)
        self.assertEqual(expr.from_rows(rows), "Lerp(-(Clamp(TIMER, 180, 90)), -0.5, 0)")
        rows = expr.wrap_node(self._rows(), 0, "+")
        self.assertEqual(expr.from_rows(rows),
                         "(Lerp(Clamp(TIMER, 180, 90), -0.5, 0) + 0)")
        rows = expr.wrap_node(self._rows(), 2, "Lerp")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(Clamp(Lerp(TIMER, 0, 0), 180, 90), -0.5, 0)")

    def test_delete_removes_one_layer_and_keeps_the_first_argument(self):
        """删除 = 去掉这一层、第 0 参顶上来。`Lerp(Clamp(TIMER, 180, 90), -0.5, 0)` 里
        删掉 `Clamp` -> `Lerp(TIMER, -0.5, 0)`。

        上一版这里是"用选中节点替换掉它的父节点"（`promote_node`），语义是"删掉我爸"，
        同一个操作在 `Clamp` 上会把外层 `Lerp` 整个干掉——按用户意见改成了现在这个。
        """
        rows = expr.delete_node(self._rows(), 1)
        self.assertEqual(expr.from_rows(rows), "Lerp(TIMER, -0.5, 0)")

    def test_delete_root_layer(self):
        rows = expr.delete_node(self._rows(), 0)
        self.assertEqual(expr.from_rows(rows), "Clamp(TIMER, 180, 90)")

    def test_delete_is_the_inverse_of_nest(self):
        """内嵌和删除必须互为逆——用户点错了原地能撤回来。"""
        base = self._rows()
        for target in ("Min", "Lerp", "Unary10", "+", expr.KIND_NEG):
            with self.subTest(target=target):
                nested = expr.wrap_node(base, 1, target)
                self.assertEqual(expr.from_rows(expr.delete_node(nested, 1)),
                                 expr.from_rows(base))

    def test_delete_is_unavailable_on_leaves(self):
        """叶子不是"一层"，里面没有东西能顶上来。清空叶子走"替换成常量"——
        一个按钮两种行为正是要避免的含混。"""
        rows = self._rows()
        self.assertFalse(expr.can_delete_node(rows, 2))     # VAR
        self.assertFalse(expr.can_delete_node(rows, 3))     # CONST
        self.assertFalse(expr.can_delete_node(rows, 5))     # 折叠后的带符号常量也是叶子
        self.assertTrue(expr.can_delete_node(rows, 0))      # CALL
        # NEG 只在折不掉的时候才单独成行（`-TIMER`），那种是"一层"，可以删
        neg_rows = expr.to_rows(expr.parse("Min(-TIMER, 1)"))
        self.assertEqual(neg_rows[1]["kind"], "NEG")
        self.assertTrue(expr.can_delete_node(neg_rows, 1))
        self.assertEqual(expr.from_rows(expr.delete_node(neg_rows, 1)), "Min(TIMER, 1)")
        # 不可用时是空操作，不是抛异常（界面上按钮本来就是灰的）
        self.assertEqual(expr.from_rows(expr.delete_node(rows, 2)), self.SRC)

    def test_delete_drops_the_other_arguments(self):
        """删掉一层就是丢掉它除第 0 参之外的参数——这是它和"替换成常量"的区别。"""
        rows = expr.to_rows(expr.parse("Min(Lerp(TIMER, 1, 2), 5)"))
        self.assertEqual(expr.from_rows(expr.delete_node(rows, 1)), "Min(TIMER, 5)")

    def test_every_mutation_leaves_a_reparsable_formula(self):
        """任何一次结构操作的产物都必须还能被自己解析回来——否则用户点一下就把公式
        点成解析不了的状态，下一次打开面板只剩一条错误。"""
        base = self._rows()
        targets = [expr.KIND_CONST, expr.KIND_VAR, "+", "Min", "Lerp", "Unary10", "Func21"]
        for index in range(len(base)):
            for target in targets:
                for mutate in (expr.convert_node, expr.wrap_node):
                    with self.subTest(index=index, target=target, op=mutate.__name__):
                        if mutate is expr.wrap_node and target == expr.KIND_CONST:
                            continue        # 常量没法当"包一层"的目标
                        if mutate is expr.wrap_node and target == expr.KIND_VAR:
                            continue
                        rows = mutate(base, index, target)
                        text = expr.from_rows(rows)
                        self.assertEqual(expr.from_rows(expr.to_rows(expr.parse(text))), text)
            with self.subTest(index=index, op="delete"):
                text = expr.from_rows(expr.delete_node(base, index))
                self.assertEqual(expr.from_rows(expr.to_rows(expr.parse(text))), text)


class TestArgRoles(unittest.TestCase):
    """参数角色名。**只有语义已定、而且参数顺序有意义的调用才有名字**——给没确认的
    东西编个名字就是把猜测画成确定（铁律 #7/#29）。

    2026-09-16 那一轮把语义全测出来之后，这张表从 2 条扩到 6 条。**扩的依据是"参数
    顺序反直觉、不标会写错"**，不是"反正已经确认了就都标上"：

    - `Min(a, b)` = `b - a`、`Max(a, b)`/`Func20(a, b)` = `pow(b, a)` —— 顺序和名字
      相反，不标角色名用户一定按字面写错。
    - `Func21(a, b, hi, lo, t)` —— 5 个槽位，不标根本记不住。
    - `Func18`/`Func19`（min/max）**故意不标**：对称运算，标了也没有信息量。
    - 一元函数**故意不标**：只有一个参数，没有"哪个槽位"的问题。
    - `InvLerp` 仍然没定，照旧不标。
    """

    def test_clamp_and_lerp(self):
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"))
        self.assertEqual(expr.arg_roles(rows),
                         ["", "t", "value", "hi", "lo", "to", "from"])

    def test_the_counterintuitive_orders_are_all_labelled(self):
        """这几个的参数顺序和名字相反，角色名是用户最需要看到的东西。"""
        rows = expr.to_rows(expr.parse("Min(1, TIMER)"))
        self.assertEqual(expr.arg_roles(rows), ["", "subtract", "from"])
        rows = expr.to_rows(expr.parse("Max(2, TIMER)"))
        self.assertEqual(expr.arg_roles(rows), ["", "exponent", "base"])
        rows = expr.to_rows(expr.parse("Func20(2, TIMER)"))
        self.assertEqual(expr.arg_roles(rows), ["", "exponent", "base"])
        rows = expr.to_rows(expr.parse("Func21(1, 2, 3, 4, TIMER)"))
        self.assertEqual(expr.arg_roles(rows),
                         ["", "to", "from", "hi", "lo", "t"])

    def test_symmetric_and_unary_and_undecided_get_no_names(self):
        """对称运算（min/max）、一元函数、以及仍未定的 `InvLerp` 一律不标。"""
        for formula in ("Unary10(TIMER)", "Unary0(TIMER)",
                        "Func18(1, TIMER)", "Func19(1, TIMER)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertTrue(all(r == "" for r in expr.arg_roles(rows)),
                                expr.arg_roles(rows))

    def test_roles_only_cover_semantically_settled_calls(self):
        self.assertEqual(set(expr.CALL_ARG_ROLES),
                         {"Clamp", "Lerp", "InvLerp", "Min", "Max", "Func20", "Func21"})
        for name in ("Unary10", "Func18", "Func19"):
            self.assertNotIn(name, expr.CALL_ARG_ROLES)

    def test_every_settled_call_has_a_semantics_string(self):
        """**名字全是错的，所以界面必须显示真实语义**（`CALL_SEMANTICS`）。
        每个语义已定的调用都要有一条，否则菜单里只剩一个纯编号。"""
        for name in expr.CALL_SIGNATURES:
            if expr.call_confidence(name) == expr.CONFIDENCE_UNKNOWN:
                continue
            self.assertTrue(expr.call_semantics(name), name)
        for symbol in expr.BINARY_OPERATORS:
            self.assertTrue(expr.call_semantics(symbol), symbol)


class TestPropagateSameUnitAsRoot(unittest.TestCase):
    """`propagate_same_unit_as_root()`——给"角度显示"开关判断哪些常量槽位可以安全按度
    换算。真实故障：`Lerp(Clamp(TIMER, 120, 0), 190, -30)` 驱动一个弧度制字段，用户以为
    `190`/`-30` 是度数、实际按弧度存进了公式，结果转出一个疯狂旋转（190 弧度 ≈ 30 圈）。
    "角度显示"开关要能安全地只换算 `190`/`-30` 这两个真正对应角度的槽位，**绝不能**碰
    `Clamp` 的 `120`/`0`——那是帧数阈值，被当角度换算会把 Clamp 的重映射区间整个改坏。"""

    def test_lerp_from_to_share_root_unit_clamp_bounds_do_not(self):
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 120, 0), 190, -30)"))
        same_unit = expr.propagate_same_unit_as_root(rows)
        # 行序：0 Lerp / 1 Clamp / 2 TIMER / 3 120 / 4 0 / 5 190 / 6 -30
        names_or_values = [(r.get("name"), r.get("value")) for r in rows]
        self.assertEqual(names_or_values[5][1], 190.0)
        self.assertEqual(names_or_values[6][1], -30.0)
        self.assertTrue(same_unit[5], "Lerp 的 from（190）必须和根同单位")
        self.assertTrue(same_unit[6], "Lerp 的 to（-30）必须和根同单位")
        self.assertFalse(same_unit[1], "Clamp 本身输出无量纲，不是角度")
        self.assertFalse(same_unit[3], "Clamp 的 hi（120，帧数阈值）绝不能被当角度")
        self.assertFalse(same_unit[4], "Clamp 的 lo（0，帧数阈值）绝不能被当角度")
        self.assertFalse(same_unit[2], "Clamp 的 value（TIMER）不是角度")

    def test_root_itself_is_always_same_unit(self):
        rows = expr.to_rows(expr.parse("190"))
        self.assertEqual(expr.propagate_same_unit_as_root(rows), [True])

    def test_unit_preserving_ops_propagate_both_sides(self):
        """两个操作数都和根节点同单位。⚠ **认的是真实语义，不是 vendor 的名字**
        （铁律 #32）：`/` 是加法、`Min(a,b)` 是减法、`*` 是取模、`Func18`/`Func19` 是
        真正的 min/max —— 这几个才保持单位。

        `TIMER` 在这里被标成"和根同单位"不是 bug：它是 `VAR` 行，不会被"角度显示"
        开关换算（那个开关只改 `CONST` 的 `value`），标不标都不影响界面行为。"""
        for formula in ("90 / TIMER", "Min(90, TIMER)", "90 * TIMER",
                        "Func18(90, TIMER)", "Func19(90, TIMER)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertEqual(expr.propagate_same_unit_as_root(rows),
                                 [True, True, True])

    def test_negation_propagates_to_its_single_child(self):
        rows = expr.to_rows(expr.parse("-TIMER"))  # 变量取负，折叠不了，两行
        self.assertEqual(expr.propagate_same_unit_as_root(rows), [True, True])

    def test_abs_floor_ceil_propagate_to_their_single_child(self):
        """`abs`/`floor`/`ceil` 逐点保持单位。"""
        for formula in ("Unary9(TIMER)", "Unary4(TIMER)", "Unary5(TIMER)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertEqual(expr.propagate_same_unit_as_root(rows), [True, True])

    def test_multiply_divide_power_do_not_propagate(self):
        """**乘 / 除 / 幂都不保持单位**，一律截断。文本符号分别是 `+`、`-`、`Max(`。

        乘法：哪个操作数是"无量纲系数"哪个是"物理量"没法只从结构分辨
        （`angle * 2` 和 `2 * angle` 长得一样），宁可不换算。
        除法：结果单位 = 被除数/除数，压根不是同一个量。
        幂：指数无量纲，底数的单位也不守恒（`x²` 是单位²）。

        ⚠ 旧表按 vendor 的名字把 `+`/`-`/`Max` 当成加/减/max 收进了传播集合——
        那会让"角度显示"开关去换算一个其实是无量纲系数的常量，**静默改坏语义不相关的
        数值**。2026-09-16 运算符语义翻案后修掉。"""
        for formula in ("90 + 2", "90 - 2", "Max(2, 90)", "Func20(2, 90)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertEqual(expr.propagate_same_unit_as_root(rows),
                                 [True, False, False])

    def test_func21_propagates_to_its_endpoints_only(self):
        """`Func21(a, b, hi, lo, t)` = `Lerp(Clamp(t,hi,lo), a, b)`：输出和 `a`/`b`
        同单位，`hi`/`lo`/`t` 自成一个单位组（通常是帧计数），不能被当成角度换算。"""
        rows = expr.to_rows(expr.parse("Func21(90, 0, 120, 0, TIMER)"))
        self.assertEqual(expr.propagate_same_unit_as_root(rows),
                         [True, True, True, False, False, False])

    def test_invlerp_propagates_to_its_endpoints_only(self):
        """`InvLerp(a, b, t)` 2026-09-16 测出就是 `Lerp`（系数在最后一个参数），所以
        输出和 `a`/`b` 同单位、`t` 是无量纲系数——和 `Lerp` 一样的传播规则，只是位置
        换了（`Lerp` 是 {1,2}、`InvLerp` 是 {0,1}）。"""
        rows = expr.to_rows(expr.parse("InvLerp(90, 0, 0.5)"))
        self.assertEqual(expr.propagate_same_unit_as_root(rows),
                         [True, True, True, False])

    def test_remap_and_trig_and_log_do_not_propagate(self):
        """输出是无量纲的那些一律截断：`Clamp` 重映射到 `[0,1]`、`saturate` 拿 0/1 当
        边界、三角/对数/指数的输入都必须是别的单位体系。"""
        for formula in ("Clamp(90, 120, 0)", "Unary10(90)", "Unary0(90)", "Unary6(90)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                same_unit = expr.propagate_same_unit_as_root(rows)
                self.assertEqual(same_unit, [True] + [False] * (len(rows) - 1))


class TestSubtree(unittest.TestCase):
    def test_subtree_text(self):
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"))
        self.assertEqual(expr.subtree_text(rows, 0), "Lerp(Clamp(TIMER, 180, 90), -0.5, 0)")
        self.assertEqual(expr.subtree_text(rows, 1), "Clamp(TIMER, 180, 90)")
        self.assertEqual(expr.subtree_text(rows, 2), "TIMER")
        self.assertEqual(expr.subtree_text(rows, 5), "-0.5")
        self.assertEqual(expr.subtree_text(rows, 6), "0")

    def test_subtree_rows_depths_are_rebased(self):
        rows = expr.to_rows(expr.parse("Lerp(Clamp(TIMER, 180, 90), -0.5, 0)"))
        sub = expr.subtree_rows(rows, 1)
        self.assertEqual([r["depth"] for r in sub], [0, 1, 1, 1])

    def test_subtree_out_of_range(self):
        rows = expr.to_rows(expr.parse("TIMER"))
        with self.assertRaises(expr.ExprError):
            expr.subtree_text(rows, 5)


class TestSlots(unittest.TestCase):
    """槽位视角——界面按"一个节点 + 它的全部槽位"画，这几个函数是它的数据来源。

    为什么不按内容类型分画法：语料实测每个槽位都能装字面量/变量/子表达式三种
    （`Lerp.to` 常量 1729 / 变量 483 / 子表达式 24），依据见
    `efx_sim/expr.py` 的槽位视角一节。
    """

    SRC = "Lerp(Clamp(TIMER, 12, 0), 190, -30)"

    def _rows(self):
        return expr.to_rows(expr.parse(self.SRC))

    def test_child_indices(self):
        rows = self._rows()
        self.assertEqual(expr.child_indices(rows, 0), [1, 5, 6])
        self.assertEqual(expr.child_indices(rows, 1), [2, 3, 4])
        self.assertEqual(expr.child_indices(rows, 2), [])

    def test_node_summary(self):
        rows = self._rows()
        self.assertEqual([expr.node_summary(rows, i) for i in (0, 1, 2, 3, 5, 6)],
                         ["Lerp", "Clamp", "TIMER", "12", "190", "-30"])

    def test_negation_summary(self):
        rows = expr.to_rows(expr.parse("Min(-TIMER, 1)"))
        self.assertEqual(expr.node_summary(rows, 1), "-")

    def test_path_to_root(self):
        rows = self._rows()
        self.assertEqual(expr.path_to_root(rows, 0), [0])
        self.assertEqual(expr.path_to_root(rows, 2), [0, 1, 2])
        self.assertEqual(expr.path_to_root(rows, 6), [0, 6])

    def test_path_out_of_range(self):
        with self.assertRaises(expr.ExprError):
            expr.path_to_root(self._rows(), 99)

    def test_switching_a_leaf_slot_to_a_function_keeps_it_as_first_arg(self):
        """「内嵌」不再是独立操作：把叶子槽位换成函数时原内容自动成为第一个参数。
        手滑改错了，换回变量类型还能把它拿回来（因为它就在第 0 参上）。"""
        rows = expr.convert_node(self._rows(), 2, "Min")
        self.assertEqual(expr.from_rows(rows), "Lerp(Clamp(Min(TIMER, 0), 12, 0), 190, -30)")

    def test_negation_is_available_as_a_function_target(self):
        """取负在界面上就是「函数类型」里的一项，所以 convert_node 得认它。"""
        rows = expr.convert_node(self._rows(), 2, expr.KIND_NEG)
        self.assertEqual(expr.from_rows(rows), "Lerp(Clamp(-TIMER, 12, 0), 190, -30)")
        self.assertEqual(expr.from_rows(expr.delete_node(rows, 2)), self.SRC)


class TestEvaluateRows(unittest.TestCase):
    """`evaluate_rows()` 一次遍历算出每一行子树的值，必须和"逐行重建子树文本再求值"
    **逐行完全一致**。

    为什么要有这条：面板的"结构树变调试器"原来就是逐行重建文本 + 重新解析，那是
    **O(N²)**——实测 225 行 8.8 ms / 449 行 16 ms / 897 行 36 ms / 1793 行 88 ms，而且
    每次面板重绘都跑一遍，公式复杂时界面肉眼可见地卡（实机用傅里叶级数压到 64 阶时
    发现的）。改成一次遍历后提速 47~64 倍、复杂度回到线性。

    **这条测试真正防的是遍历顺序漂移**：`_eval_collect()` 必须和 `_collect_rows()`
    逐字同序（前序 + `-字面量` 折叠成一行），差一个节点，面板上每一行显示的值就会
    错位到隔壁子树上——那种错不报任何异常，只是**安静地显示错的数**。
    """

    FORMULAS = (
        "Lerp(Clamp(TIMER, 15, 0), 0.5, -1)",
        "Min(Clamp(TIMER, 100, 20), 1)",
        "(6 - Unary0(((2 - PI) / (100 - TIMER))))",
        "Unary11(Func21(90, 0, 60, 0, TIMER))",
        "Max(2, Lerp(Unary10((0.008 + TIMER)), 0, 1))",
        "-TIMER / -2.5",                      # 一元负号两种形态都覆盖
        "Func20(1, 2) / Unary2(0.5)",         # 未确认函数 + 会记 note 的
        "Min(30, (45 * TIMER))",
    )

    def _vars(self):
        return {"TIMER": 37.0, "PI": 3.14159265}

    def test_matches_per_subtree_evaluation(self):
        for text in self.FORMULAS:
            parsed = expr.parse(text)
            rows = expr.to_rows(parsed)
            fast = expr.evaluate_rows(
                parsed, expr.EvalContext(self._vars(), "identity", []))
            self.assertEqual(len(fast), len(rows), text)
            for i in range(len(rows)):
                try:
                    slow = expr.evaluate(
                        expr.parse(expr.subtree_text(rows, i)),
                        expr.EvalContext(self._vars(), "identity", []))
                except expr.ExprError:
                    slow = None
                if slow is None:
                    self.assertIsNone(fast[i], (text, i, rows[i]))
                else:
                    self.assertAlmostEqual(fast[i], slow, places=9,
                                           msg="%s 第 %d 行 %r" % (text, i, rows[i]))

    def test_row_zero_is_the_whole_formula(self):
        """第 0 行是根，值必须等于整条公式的求值结果。"""
        for text in self.FORMULAS:
            parsed = expr.parse(text)
            whole = expr.evaluate(parsed, expr.EvalContext(self._vars(), "identity", []))
            fast = expr.evaluate_rows(
                parsed, expr.EvalContext(self._vars(), "identity", []))
            self.assertAlmostEqual(fast[0], whole, places=9, msg=text)

    def test_a_broken_branch_does_not_poison_the_others(self):
        """某一支算不出来只让那一行是 `None`，别的行照常有值——调试器要能显示
        "这支坏了、那支还好"。"""
        parsed = expr.parse("Lerp(Clamp(TIMER, 15, 0), 0.5, Nope(1))")
        rows = expr.to_rows(parsed)
        vals = expr.evaluate_rows(parsed, expr.EvalContext({"TIMER": 7.0}, "identity", []))
        self.assertEqual(len(vals), len(rows))
        self.assertIsNone(vals[0])                       # 根受牵连
        clamp_row = next(i for i, r in enumerate(rows) if r["name"] == "Clamp")
        self.assertIsNotNone(vals[clamp_row])            # 好的那支照常


class TestSignatures(unittest.TestCase):
    def test_arity_table_matches_evaluator(self):
        """`CALL_SIGNATURES` 和求值器用的 `_UNKNOWN_FUNC_ARGC` 是同一批未确认函数——
        两张表漂了，下拉里能选出求值器当场拒绝的参数个数。"""
        for name, argc in expr._UNKNOWN_FUNC_ARGC.items():
            self.assertEqual(expr.call_arity(name), argc)
            self.assertEqual(expr.call_confidence(name), expr.CONFIDENCE_UNKNOWN)
        # `Min`/`Max` 的名字都是错的（实为 `b-a` / `pow(b,a)`），两个都实机确认过
        # ——`Max` 是靠 `Max(2, <从 -1 到 +1 的扫描>)` 画出 **U 形抛物线**定的
        # （"直接返回 b" 那个候选会给一条穿过轴的直线）。
        for name in ("Min", "Max"):
            self.assertEqual(expr.call_arity(name), 2)
            self.assertEqual(expr.call_confidence(name), expr.CONFIDENCE_CONFIRMED)
        for name in ("Lerp", "InvLerp", "Clamp"):
            self.assertEqual(expr.call_arity(name), 3)
        # `InvLerp` 2026-09-16 实机测出就是 `Lerp`（系数在最后一个参数），已升到确认档
        self.assertEqual(expr.call_confidence("InvLerp"), expr.CONFIDENCE_CONFIRMED)
        # 2026-09-16 收尾之后**整套语义全部实机确认**：`Lerp` 四点（方向/线性/t 在第 1
        # 位/t 两端饱和）、`InvLerp` 就是 `Lerp`、`Clamp` 的两端饱和 + 中段 smoothstep。
        # 分层机制照旧保留（vendor 升级冒出新函数时还得靠它），但现在没有非确认档的调用了。
        for name in ("Lerp", "Clamp", "InvLerp"):
            self.assertEqual(expr.call_confidence(name), expr.CONFIDENCE_CONFIRMED, name)
        self.assertEqual(
            [n for n in expr.CALL_SIGNATURES
             if expr.call_confidence(n) != expr.CONFIDENCE_CONFIRMED], [],
            "没有非确认档的调用了；如果这条 FAIL，说明新增了未确认的东西——"
            "记得回去看 tools/verify_blender_expression_preview.py 里那段注入假函数名的注释")


    def test_unknown_name_is_not_pretended_to_be_known(self):
        self.assertIsNone(expr.call_arity("Nope"))
        self.assertEqual(expr.call_confidence("Nope"), expr.CONFIDENCE_UNKNOWN)

    def test_known_external_variable_mirror(self):
        """`KNOWN_EXTERNAL_VARIABLES` 是 vendor `KnownExternalHashes` 的镜像。vendor 升级
        后这条会提醒去对一遍（22 个已解出名字 + 4 个仍未解出、不进这张表）。"""
        self.assertEqual(len(expr.KNOWN_EXTERNAL_VARIABLES), 22)
        self.assertEqual(len(set(expr.KNOWN_EXTERNAL_VARIABLES)), 22)
        for name in ("TIMER", "PI", "RAND", "EM_INIRAND", "EM_INIRAND_SHARED",
                     "PLAY_SPEED", "SpawnNum"):
            self.assertIn(name, expr.KNOWN_EXTERNAL_VARIABLES)
        self.assertIn(expr.DEFAULT_VARIABLE, expr.KNOWN_EXTERNAL_VARIABLES)


if __name__ == "__main__":
    unittest.main()
