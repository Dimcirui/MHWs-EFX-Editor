# -*- coding: utf-8 -*-
"""
tests/test_sim_expr_edit.py —— `efx_sim/expr.py` 的结构化编辑支持（emit / 行视图 / 变换）

    python -m unittest discover -s tests

这一层是 Blender 侧结构化公式编辑器（`blender_efx_re/expr_edit.py`）的地基：面板上每一次
点击最终都变成"读行 -> 变换 -> 拼文本 -> 写回 `formula`"，而导出只认那段文本。文本一旦和
原来不同，产物字节就跟着不同——所以最要紧的断言只有一条：**没动过的公式，拆开再拼回去必须
一字不差**。

按 CLAUDE.md 验证纪律，每条断言都对应一个真实故障模式，且都注入过确认会 FAIL：

- `_emit_rows()` 按优先级省略括号（vendor 那套 `AppendString()` 的规则）-> 和语料文本对不上，
  这里 `(Length / 1.5)` 一类的用例立刻红；
- 负号规范化成 `0 - x` -> `-0.5` 用例红（二进制里那是两种不同的组件序列）；
- 浮点改用 `repr()` -> `20`/`0.1` 这些用例变成 `20.0`/`0.1` 之外的写法，红。

`_REAL_FORMULAS` 是从官方语料抽样扫出来的真实公式，按 vendor `1c2f92d` 的排版换算过
（换算器对 618 条语料公式和 vendor 新旧两版 dump 的输出逐字一致）。语料本身不可分发、
不在版本控制里，所以把代表样本当字面量钉在这儿。
"""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import expr  # noqa: E402


#: 真实语料里的公式，覆盖：单变量、单常量、四则、嵌套四则、负号（字面量/子树两种写法）、
#: 幂、三元函数、5 参函数、未解析出名字的 `ext:` 占位。
_REAL_FORMULAS = (
    "BloodColor",
    "0",
    "Length",
    "(BloodColor * 0.5)",
    "(Length / 1.5)",
    "(Length / 20)",
    "(Current_Len / Initial_Len)",
    "(Length - 5)",
    "(GLength ^ 0.2)",
    "Remap(TIMER, 0, 10, 20, 2)",
    "Lerp(0, -0.5, SmoothStep(90, 180, TIMER))",
    "Lerp(-0.025, -0.1, SmoothStep(0, 8, TIMER))",
    "Lerp(8, 0, SmoothStep(3, 6, ext:302732036))",
    "Lerp(0, -1, SinDeg(Remap(TIMER, 0, 20, 0, 90)))",
    "(-(Sin((SmoothStep(0, 30, TIMER) * PI))) * 45)",
    "Lerp(Lerp(Lerp(RED_P, WHITE_P, Saturate(Color_A)), YELLOW_P, "
    "Saturate((Color_A - 1))), GREEN_P, Saturate((Color_A - 2)))",
    "(SmoothStep(0.2, 0.3, ukn:1017435601) - SmoothStep(0.6, 0.7, ukn:1017435601))",
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
        """`a  |  b` 的第二支语义没证实，但不能丢（铁律 #1）。连接符是两边各两个空格。"""
        text = "TIMER  |  (TIMER - 1)"
        parsed = expr.parse(text)
        self.assertEqual(parsed.second_branch, "(TIMER - 1)")
        self.assertEqual(expr.emit_parsed(parsed), text)
        self.assertEqual(expr.from_rows(expr.to_rows(parsed), parsed.second_branch), text)

    def test_trailing_garbage_is_rejected_not_dropped(self):
        """vendor 解析完一个表达式就停，`1 2` 会被它静默读成 `1`。我们这边宁可拒绝。"""
        for text in ("1 2", "(TIMER - 1))", "Lerp(1, 2, 3) TIMER"):
            with self.subTest(text=text):
                with self.assertRaises(expr.ExprError):
                    expr.parse(text)


class TestNegationFolding(unittest.TestCase):
    """`-1` 折叠成一行带符号常量（`_collect_rows()`），以及它带出来的那个坑。"""

    def test_negative_literal_is_one_row(self):
        rows = expr.to_rows(expr.parse("Lerp(-30, 190, SmoothStep(0, 12, TIMER))"))
        self.assertEqual([r["kind"] for r in rows],
                         ["CALL", "CONST", "CONST", "CALL", "CONST", "CONST", "VAR"])
        self.assertEqual(rows[1]["value"], -30.0)
        self.assertEqual(expr.from_rows(rows), "Lerp(-30, 190, SmoothStep(0, 12, TIMER))")

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

    def test_negative_base_of_a_power_keeps_its_meaning(self):
        """vendor 的负号只吃一个原子：`(-2 ^ 2)` 是 `(-2) ^ 2`。折叠成 `CONST -2` 再拼回去
        必须还是这个意思。"""
        rows = expr.to_rows(expr.parse("(-2 ^ 2)"))
        self.assertEqual([r["kind"] for r in rows], ["CALL", "CONST", "CONST"])
        self.assertEqual(expr.from_rows(rows), "(-2 ^ 2)")
        self.assertEqual(expr.evaluate(expr.parse(expr.from_rows(rows)),
                                       expr.EvalContext({})), 4.0)

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


#: 结构测试共用的一条公式。行序：
#:   0 Lerp / 1 `0`(from) / 2 `-0.5`(to) / 3 SmoothStep(t) / 4 `90`(lo) / 5 `180`(hi) / 6 TIMER(value)
_SRC = "Lerp(0, -0.5, SmoothStep(90, 180, TIMER))"


class TestRowEncoding(unittest.TestCase):
    def test_depth_and_arity(self):
        # `-0.5` 折叠成一行带符号常量，所以是 7 行（见 TestNegationFolding）
        rows = expr.to_rows(expr.parse(_SRC))
        self.assertEqual([r["kind"] for r in rows],
                         ["CALL", "CONST", "CONST", "CALL", "CONST", "CONST", "VAR"])
        self.assertEqual([r["depth"] for r in rows], [0, 1, 1, 1, 2, 2, 2])
        self.assertEqual([r["arity"] for r in rows], [3, 0, 0, 3, 0, 0, 0])

    def test_subtree_span_and_parent(self):
        rows = expr.to_rows(expr.parse(_SRC))
        self.assertEqual(expr.subtree_span(rows, 0), 7)
        self.assertEqual(expr.subtree_span(rows, 3), 4)
        self.assertEqual(expr.subtree_span(rows, 2), 1)
        self.assertEqual([expr.parent_index(rows, i) for i in range(len(rows))],
                         [None, 0, 0, 0, 3, 3, 3])

    def test_arity_mismatch_is_rejected_not_padded(self):
        """行结构坏了就抛，不补零凑合——静默凑出一条合法但内容不对的公式正是铁律 #1 要防的。"""
        rows = expr.to_rows(expr.parse("(1 - 2)"))
        rows[0]["arity"] = 3
        with self.assertRaises(expr.ExprError):
            expr.from_rows(rows)
        rows = expr.to_rows(expr.parse("(1 - 2)"))
        rows[0]["arity"] = 1
        with self.assertRaises(expr.ExprError):
            expr.from_rows(rows)

    def test_empty_names_are_rejected(self):
        rows = expr.to_rows(expr.parse("TIMER"))
        rows[0]["name"] = ""
        with self.assertRaises(expr.ExprError):
            expr.from_rows(rows)


class TestMutations(unittest.TestCase):
    SRC = _SRC

    def _rows(self):
        return expr.to_rows(expr.parse(self.SRC))

    def test_convert_keeps_children_when_node_has_them(self):
        """`SmoothStep(a,b,c)` -> `-` 留下前两个参数，不会把整棵子树塞进第一个参数。"""
        rows = expr.convert_node(self._rows(), 3, "-")
        self.assertEqual(expr.from_rows(rows), "Lerp(0, -0.5, (90 - 180))")

    def test_convert_pads_missing_arguments(self):
        rows = expr.convert_node(self._rows(), 3, "Remap")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(0, -0.5, Remap(90, 180, TIMER, 0, 0))")

    def test_convert_leaf_keeps_itself_in_the_primary_slot(self):
        """叶子换成函数时把自己放进主输入那个槽位——手滑点错不会把已经填好的值弄丢，
        而且 `Lerp` 的主输入是 `t`（最后一个），不是端点。"""
        rows = expr.convert_node(self._rows(), 6, "Saturate")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(0, -0.5, SmoothStep(90, 180, Saturate(TIMER)))")
        rows = expr.convert_node(self._rows(), 6, "Lerp")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(0, -0.5, SmoothStep(90, 180, Lerp(0, 0, TIMER)))")
        rows = expr.convert_node(self._rows(), 6, "Clamp")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(0, -0.5, SmoothStep(90, 180, Clamp(TIMER, 0, 0)))")

    def test_convert_to_leaf_drops_the_subtree(self):
        rows = expr.convert_node(self._rows(), 3, expr.KIND_CONST)
        self.assertEqual(expr.from_rows(rows), "Lerp(0, -0.5, 0)")
        rows = expr.convert_node(self._rows(), 3, expr.KIND_VAR)
        self.assertEqual(expr.from_rows(rows), "Lerp(0, -0.5, TIMER)")

    def test_convert_rejects_unknown_target(self):
        with self.assertRaises(expr.ExprError):
            expr.convert_node(self._rows(), 0, "NoSuchFunction")

    def test_nest_with_negation(self):
        rows = expr.wrap_node(self._rows(), 3, expr.KIND_NEG)
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(0, -0.5, -(SmoothStep(90, 180, TIMER)))")
        rows = expr.wrap_node(self._rows(), 0, "*")
        self.assertEqual(expr.from_rows(rows),
                         "(Lerp(0, -0.5, SmoothStep(90, 180, TIMER)) * 0)")
        rows = expr.wrap_node(self._rows(), 6, "Lerp")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(0, -0.5, SmoothStep(90, 180, Lerp(0, 0, TIMER)))")

    def test_delete_removes_one_layer_and_keeps_the_primary_argument(self):
        """删除 = 去掉这一层、主输入顶上来。删掉 `SmoothStep` -> 它的 `value`（`TIMER`）
        接到 `Lerp` 的 `t` 上。

        上一版这里是"用选中节点替换掉它的父节点"（`promote_node`），语义是"删掉我爸"，
        同一个操作会把外层 `Lerp` 整个干掉——按用户意见改成了现在这个。
        """
        rows = expr.delete_node(self._rows(), 3)
        self.assertEqual(expr.from_rows(rows), "Lerp(0, -0.5, TIMER)")

    def test_delete_root_layer(self):
        rows = expr.delete_node(self._rows(), 0)
        self.assertEqual(expr.from_rows(rows), "SmoothStep(90, 180, TIMER)")

    def test_delete_is_the_inverse_of_nest(self):
        """内嵌和删除必须互为逆——用户点错了原地能撤回来。"""
        base = self._rows()
        for index in (3, 6):
            for target in ("-", "Lerp", "SmoothStep", "Clamp", "Saturate", "*", expr.KIND_NEG):
                with self.subTest(index=index, target=target):
                    nested = expr.wrap_node(base, index, target)
                    self.assertEqual(expr.from_rows(expr.delete_node(nested, index)),
                                     expr.from_rows(base))

    def test_delete_is_unavailable_on_leaves(self):
        """叶子不是"一层"，里面没有东西能顶上来。清空叶子走"替换成常量"——
        一个按钮两种行为正是要避免的含混。"""
        rows = self._rows()
        self.assertFalse(expr.can_delete_node(rows, 6))     # VAR
        self.assertFalse(expr.can_delete_node(rows, 4))     # CONST
        self.assertFalse(expr.can_delete_node(rows, 2))     # 折叠后的带符号常量也是叶子
        self.assertTrue(expr.can_delete_node(rows, 0))      # CALL
        # NEG 只在折不掉的时候才单独成行（`-TIMER`），那种是"一层"，可以删
        neg_rows = expr.to_rows(expr.parse("(-TIMER - 1)"))
        self.assertEqual(neg_rows[1]["kind"], "NEG")
        self.assertTrue(expr.can_delete_node(neg_rows, 1))
        self.assertEqual(expr.from_rows(expr.delete_node(neg_rows, 1)), "(TIMER - 1)")
        # 不可用时是空操作，不是抛异常（界面上按钮本来就是灰的）
        self.assertEqual(expr.from_rows(expr.delete_node(rows, 6)), self.SRC)

    def test_delete_drops_the_other_arguments(self):
        """删掉一层就是丢掉主输入之外的参数——这是它和"替换成常量"的区别。"""
        rows = expr.to_rows(expr.parse("(Lerp(1, 2, TIMER) - 5)"))
        self.assertEqual(expr.from_rows(expr.delete_node(rows, 1)), "(TIMER - 5)")

    def test_every_mutation_leaves_a_reparsable_formula(self):
        """任何一次结构操作的产物都必须还能被自己解析回来——否则用户点一下就把公式
        点成解析不了的状态，下一次打开面板只剩一条错误。"""
        base = self._rows()
        targets = [expr.KIND_CONST, expr.KIND_VAR, "*", "-", "^", "%", "Lerp", "Saturate", "Remap"]
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
    """参数角色名。只给**语义已定的多参函数**标——对称运算、一元函数、中缀运算符
    （按字面读）标了没有信息量。"""

    def test_lerp_and_smoothstep(self):
        rows = expr.to_rows(expr.parse(_SRC))
        self.assertEqual(expr.arg_roles(rows),
                         ["", "from", "to", "t", "lo", "hi", "value"])

    def test_every_multi_arg_function_is_labelled(self):
        cases = {
            "Clamp(TIMER, 0, 1)": ["", "value", "lo", "hi"],
            "Pow(TIMER, 2)": ["", "base", "exponent"],
            "Remap(TIMER, 1, 2, 3, 4)": ["", "t", "lo", "hi", "from", "to"],
        }
        for formula, want in cases.items():
            with self.subTest(formula=formula):
                self.assertEqual(expr.arg_roles(expr.to_rows(expr.parse(formula))), want)

    def test_symmetric_unary_and_operators_get_no_names(self):
        for formula in ("Saturate(TIMER)", "Sin(TIMER)", "Min(1, TIMER)", "Max(1, TIMER)",
                        "(1 - TIMER)", "(TIMER / 2)", "(TIMER ^ 2)", "(TIMER % 2)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertTrue(all(r == "" for r in expr.arg_roles(rows)),
                                expr.arg_roles(rows))

    def test_role_table_is_exactly_the_multi_arg_functions(self):
        self.assertEqual(set(expr.CALL_ARG_ROLES),
                         {"Lerp", "Clamp", "SmoothStep", "Remap", "Pow"})
        for name, roles in expr.CALL_ARG_ROLES.items():
            self.assertEqual(len(roles), expr.call_arity(name), name)

    def test_only_calls_whose_name_is_not_enough_carry_semantics(self):
        """"名字不够用"的才写一条 `CALL_SEMANTICS`：弧度/角度、`Log` 的底、`%` 的符号规则、
        插值类的公式。`Min`/`Floor`/`-` 这种"名字就是全部信息"的不写——那属于
        docs/PITFALLS.md #25 要防的冗余文案。"""
        for name in ("%", "Sin", "Cos", "Asin", "Acos", "SinDeg", "CosDeg", "Log",
                     "Saturate", "Remap", "Lerp", "SmoothStep", "Clamp"):
            self.assertTrue(expr.call_semantics(name), name)
        for name in ("Min", "Max", "Floor", "Ceil", "Abs", "Exp", "Log10", "Pow",
                     "*", "+", "-", "/", "^"):
            self.assertFalse(expr.call_semantics(name), name)


class TestPropagateSameUnitAsRoot(unittest.TestCase):
    """`propagate_same_unit_as_root()`——给"角度显示"开关判断哪些常量槽位可以安全按度
    换算。真实故障：`Lerp(-30, 190, SmoothStep(0, 120, TIMER))` 驱动一个弧度制字段，用户
    以为 `190`/`-30` 是度数、实际按弧度存进了公式，结果转出一个疯狂旋转（190 弧度 ≈ 30 圈）。
    "角度显示"开关要能安全地只换算 `190`/`-30` 这两个真正对应角度的槽位，**绝不能**碰
    `SmoothStep` 的 `0`/`120`——那是帧数阈值，被当角度换算会把重映射区间整个改坏。"""

    def test_lerp_from_to_share_root_unit_smoothstep_bounds_do_not(self):
        rows = expr.to_rows(expr.parse("Lerp(-30, 190, SmoothStep(0, 120, TIMER))"))
        same_unit = expr.propagate_same_unit_as_root(rows)
        # 行序：0 Lerp / 1 -30 / 2 190 / 3 SmoothStep / 4 0 / 5 120 / 6 TIMER
        self.assertEqual(rows[1]["value"], -30.0)
        self.assertEqual(rows[2]["value"], 190.0)
        self.assertTrue(same_unit[1], "Lerp 的 from（-30）必须和根同单位")
        self.assertTrue(same_unit[2], "Lerp 的 to（190）必须和根同单位")
        self.assertFalse(same_unit[3], "SmoothStep 本身输出无量纲，不是角度")
        self.assertFalse(same_unit[4], "SmoothStep 的 lo（0，帧数阈值）绝不能被当角度")
        self.assertFalse(same_unit[5], "SmoothStep 的 hi（120，帧数阈值）绝不能被当角度")
        self.assertFalse(same_unit[6], "SmoothStep 的 value（TIMER）不是角度")

    def test_root_itself_is_always_same_unit(self):
        rows = expr.to_rows(expr.parse("190"))
        self.assertEqual(expr.propagate_same_unit_as_root(rows), [True])

    def test_unit_preserving_ops_propagate_both_sides(self):
        """两个操作数都和根节点同单位：加、减、取模、min、max。

        `TIMER` 在这里被标成"和根同单位"不是 bug：它是 `VAR` 行，不会被"角度显示"
        开关换算（那个开关只改 `CONST` 的 `value`），标不标都不影响界面行为。"""
        for formula in ("(90 + TIMER)", "(90 - TIMER)", "(90 % TIMER)",
                        "Min(90, TIMER)", "Max(90, TIMER)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertEqual(expr.propagate_same_unit_as_root(rows),
                                 [True, True, True])

    def test_negation_propagates_to_its_single_child(self):
        rows = expr.to_rows(expr.parse("-TIMER"))  # 变量取负，折叠不了，两行
        self.assertEqual(expr.propagate_same_unit_as_root(rows), [True, True])

    def test_abs_floor_ceil_propagate_to_their_single_child(self):
        """`abs`/`floor`/`ceil` 逐点保持单位。"""
        for formula in ("Abs(TIMER)", "Floor(TIMER)", "Ceil(TIMER)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertEqual(expr.propagate_same_unit_as_root(rows), [True, True])

    def test_multiply_divide_power_do_not_propagate(self):
        """**乘 / 除 / 幂都不保持单位**，一律截断。

        乘法：哪个操作数是"无量纲系数"哪个是"物理量"没法只从结构分辨
        （`angle * 2` 和 `2 * angle` 长得一样），宁可不换算。
        除法：结果单位 = 被除数/除数，压根不是同一个量。
        幂：指数无量纲，底数的单位也不守恒（`x²` 是单位²）。"""
        for formula in ("(90 * 2)", "(90 / 2)", "(90 ^ 2)", "Pow(90, 2)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                self.assertEqual(expr.propagate_same_unit_as_root(rows),
                                 [True, False, False])

    def test_remap_propagates_to_its_endpoints_only(self):
        """`Remap(t, lo, hi, from, to)`：输出和 `from`/`to` 同单位，`t`/`lo`/`hi` 自成一个
        单位组（通常是帧计数），不能被当成角度换算。"""
        rows = expr.to_rows(expr.parse("Remap(TIMER, 0, 120, 0, 90)"))
        self.assertEqual(expr.propagate_same_unit_as_root(rows),
                         [True, False, False, False, True, True])

    def test_clamp_propagates_to_all_three_arguments(self):
        """`Clamp(value, lo, hi)` 是真 `clamp`，**三个参数全部**和输出同单位——不像
        `Lerp` 那样有一个无量纲的系数槽。"""
        rows = expr.to_rows(expr.parse("Clamp(45, 0, 90)"))
        self.assertEqual(expr.propagate_same_unit_as_root(rows),
                         [True, True, True, True])

    def test_smoothstep_and_trig_and_log_do_not_propagate(self):
        """输出是无量纲的那些一律截断：`SmoothStep` 重映射到 `[0,1]`、`saturate` 拿 0/1 当
        边界、三角/对数/指数的输入都必须是别的单位体系。"""
        for formula in ("SmoothStep(0, 120, 90)", "Saturate(90)", "Sin(90)", "Log(90)"):
            with self.subTest(formula=formula):
                rows = expr.to_rows(expr.parse(formula))
                same_unit = expr.propagate_same_unit_as_root(rows)
                self.assertEqual(same_unit, [True] + [False] * (len(rows) - 1))


class TestSubtree(unittest.TestCase):
    def test_subtree_text(self):
        rows = expr.to_rows(expr.parse(_SRC))
        self.assertEqual(expr.subtree_text(rows, 0), _SRC)
        self.assertEqual(expr.subtree_text(rows, 3), "SmoothStep(90, 180, TIMER)")
        self.assertEqual(expr.subtree_text(rows, 6), "TIMER")
        self.assertEqual(expr.subtree_text(rows, 2), "-0.5")
        self.assertEqual(expr.subtree_text(rows, 1), "0")

    def test_subtree_rows_depths_are_rebased(self):
        rows = expr.to_rows(expr.parse(_SRC))
        sub = expr.subtree_rows(rows, 3)
        self.assertEqual([r["depth"] for r in sub], [0, 1, 1, 1])

    def test_subtree_out_of_range(self):
        rows = expr.to_rows(expr.parse("TIMER"))
        with self.assertRaises(expr.ExprError):
            expr.subtree_text(rows, 5)


class TestSlots(unittest.TestCase):
    """槽位视角——界面按"一个节点 + 它的全部槽位"画，这几个函数是它的数据来源。

    为什么不按内容类型分画法：语料实测每个槽位都能装字面量/变量/子表达式三种，
    依据见 `efx_sim/expr.py` 的槽位视角一节。
    """

    SRC = "Lerp(-30, 190, SmoothStep(0, 12, TIMER))"

    def _rows(self):
        return expr.to_rows(expr.parse(self.SRC))

    def test_child_indices(self):
        rows = self._rows()
        self.assertEqual(expr.child_indices(rows, 0), [1, 2, 3])
        self.assertEqual(expr.child_indices(rows, 3), [4, 5, 6])
        self.assertEqual(expr.child_indices(rows, 6), [])

    def test_node_summary(self):
        rows = self._rows()
        self.assertEqual([expr.node_summary(rows, i) for i in (0, 3, 6, 5, 2, 1)],
                         ["Lerp", "SmoothStep", "TIMER", "12", "190", "-30"])

    def test_negation_summary(self):
        rows = expr.to_rows(expr.parse("(-TIMER - 1)"))
        self.assertEqual(expr.node_summary(rows, 1), "-")

    def test_operator_summary_is_the_symbol(self):
        rows = expr.to_rows(expr.parse("((TIMER ^ 2) % 3)"))
        self.assertEqual([expr.node_summary(rows, i) for i in (0, 1)], ["%", "^"])

    def test_path_to_root(self):
        rows = self._rows()
        self.assertEqual(expr.path_to_root(rows, 0), [0])
        self.assertEqual(expr.path_to_root(rows, 6), [0, 3, 6])
        self.assertEqual(expr.path_to_root(rows, 1), [0, 1])

    def test_path_out_of_range(self):
        with self.assertRaises(expr.ExprError):
            expr.path_to_root(self._rows(), 99)

    def test_switching_a_leaf_slot_to_a_function_keeps_it_in_the_primary_slot(self):
        """「内嵌」不再是独立操作：把叶子槽位换成函数时原内容自动进主输入槽位。
        手滑改错了，换回变量类型还能把它拿回来。"""
        rows = expr.convert_node(self._rows(), 6, "-")
        self.assertEqual(expr.from_rows(rows),
                         "Lerp(-30, 190, SmoothStep(0, 12, (TIMER - 0)))")

    def test_negation_is_available_as_a_function_target(self):
        """取负在界面上就是「函数类型」里的一项，所以 convert_node 得认它。"""
        rows = expr.convert_node(self._rows(), 6, expr.KIND_NEG)
        self.assertEqual(expr.from_rows(rows), "Lerp(-30, 190, SmoothStep(0, 12, -TIMER))")
        self.assertEqual(expr.from_rows(expr.delete_node(rows, 6)), self.SRC)


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
        "Lerp(-1, 0.5, SmoothStep(0, 15, TIMER))",
        "(1 - SmoothStep(20, 100, TIMER))",
        "(Sin(((TIMER / 100) + (PI / 2))) / 6)",
        "SinDeg(Remap(TIMER, 0, 60, 0, 90))",
        "(Lerp(1, 0, Saturate((TIMER * 0.008))) ^ 2)",
        "(-2.5 + -TIMER)",                      # 一元负号两种形态都覆盖
        "(Asin(0.5) + Pow(2, 1))",
        "((TIMER % 45) - 30)",
        "(-2 ^ Clamp(TIMER, 0, 3))",            # 负号只吃一个原子
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
        parsed = expr.parse("Lerp(Nope(1), 0.5, SmoothStep(0, 15, TIMER))")
        rows = expr.to_rows(parsed)
        vals = expr.evaluate_rows(parsed, expr.EvalContext({"TIMER": 7.0}, "identity", []))
        self.assertEqual(len(vals), len(rows))
        self.assertIsNone(vals[0])                       # 根受牵连
        smooth_row = next(i for i, r in enumerate(rows) if r["name"] == "SmoothStep")
        self.assertIsNotNone(vals[smooth_row])           # 好的那支照常


class TestSignatures(unittest.TestCase):
    def test_arity_table_matches_evaluator(self):
        """`CALL_SIGNATURES` 和求值器用的 `_UNKNOWN_FUNC_ARGC` 是同一批未确认函数——
        两张表漂了，下拉里能选出求值器当场拒绝的参数个数。"""
        for name, argc in expr._UNKNOWN_FUNC_ARGC.items():
            self.assertEqual(expr.call_arity(name), argc)
            self.assertEqual(expr.call_confidence(name), expr.CONFIDENCE_UNKNOWN)
        for name in ("Min", "Max", "Pow"):
            self.assertEqual(expr.call_arity(name), 2)
        for name in ("Lerp", "Clamp", "SmoothStep"):
            self.assertEqual(expr.call_arity(name), 3)
        self.assertEqual(expr.call_arity("Remap"), 5)
        for symbol in expr.BINARY_OPERATORS:
            self.assertEqual(expr.call_arity(symbol), 2)
        # 整套语义全部实机确认。分层机制照旧保留（vendor 升级冒出新函数时还得靠它）。
        self.assertEqual(
            [n for n in expr.CALL_SIGNATURES
             if expr.call_confidence(n) != expr.CONFIDENCE_CONFIRMED], [],
            "没有非确认档的调用了；如果这条 FAIL，说明新增了未确认的东西——"
            "记得回去看 tools/verify_blender_expression_preview.py 里那段注入假函数名的注释")

    def test_legacy_names_are_not_recognised(self):
        """`a96e1d9` 那一版的写法（`InvLerp(`、`PowOp(`、`Mod(`）vendor 现在直接拒绝，
        我们这边也不能悄悄认——认了就会按新的参数顺序去读一条旧顺序写的公式。"""
        for name in ("InvLerp", "PowOp", "Mod"):
            with self.subTest(name=name):
                self.assertIsNone(expr.call_arity(name))
                with self.assertRaises(expr.ExprError):
                    expr.evaluate(expr.parse("%s(1, 2, 3)" % name), expr.EvalContext({}))

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

    def test_resolved_external_variable_hashes_correctly(self):
        """`EM_SPEED`/`WIND_SPEED` 和 vendor 自己那 22 个地位相同——都是"这个字面量的
        MurMur3 ASCII 哈希对得上"，唯一区别是 vendor 自己的 `ToString()` 不认识这两个
        哈希，从文件读出来的公式文本永远是 `ext:<hash>` 占位，所以还需要一层显示/存盘
        转换。"""
        self.assertNotIn("EM_SPEED", expr.KNOWN_EXTERNAL_VARIABLES)
        self.assertIn("EM_SPEED", expr.RESOLVED_EXTERNAL_VARIABLES)
        self.assertEqual(expr.display_var_name("ext:302732036"), "EM_SPEED")
        self.assertEqual(expr.vendor_var_name("EM_SPEED"), "ext:302732036")
        self.assertNotIn("WIND_SPEED", expr.KNOWN_EXTERNAL_VARIABLES)
        self.assertIn("WIND_SPEED", expr.RESOLVED_EXTERNAL_VARIABLES)
        self.assertEqual(expr.display_var_name("ext:213419702"), "WIND_SPEED")
        self.assertEqual(expr.vendor_var_name("WIND_SPEED"), "ext:213419702")
        # 不认识的字面量原样透传。
        self.assertEqual(expr.display_var_name("TIMER"), "TIMER")
        self.assertEqual(expr.vendor_var_name("ext:1017435601"), "ext:1017435601")

    def test_unresolved_external_var_literals_have_no_name(self):
        """这两个哈希连名字都没解出来——占位本身就是它们在选择器里出现的样子，
        不该意外进了 `RESOLVED_EXTERNAL_VARIABLES`（那张表只放真的解出名字的）。"""
        for literal in expr.UNRESOLVED_EXTERNAL_VAR_LITERALS:
            self.assertTrue(literal.startswith("ext:"), literal)
            self.assertNotIn(literal, expr.RESOLVED_EXTERNAL_VARIABLES)

    def test_variable_picker_choices_covers_all_three_tiers(self):
        choices = expr.variable_picker_choices()
        self.assertIn("TIMER", choices)                  # vendor 自己解出的真名
        self.assertIn("EM_SPEED", choices)                # 我们自己解出的名字，同等地位
        self.assertIn("WIND_SPEED", choices)              # 同上，第二个自己解出的名字
        self.assertIn("ext:1017435601", choices)          # 连名字都没有的占位
        self.assertEqual(
            len(choices),
            len(expr.KNOWN_EXTERNAL_VARIABLES) + len(expr.RESOLVED_EXTERNAL_VARIABLES)
            + len(expr.UNRESOLVED_EXTERNAL_VAR_LITERALS))


if __name__ == "__main__":
    unittest.main()
