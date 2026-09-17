# -*- coding: utf-8 -*-
"""
tests/test_sim_core.py —— `efx_sim/` 的纯 Python 单测（**不需要 Blender**）

    python -m unittest discover -s tests

用 `unittest` 而不是 pytest：零依赖，Blender 自带的 Python 也能直接跑。

这批测试盯的是**移植最容易出错的那几处**，不是覆盖率：

- `RangeI` 的 JSON 键序和 `Range` 相反（vendor `RszValueType.cs`），按下标取会静默读反；
- `blender_efx_re/model.py` 的三张字段名单在 `efx_sim/shapes.py` 里是**镜像**，
  两边漂了没人会发现（核心层不能 import model.py，它要 bpy）；
- 旋转顺序表同理，源头是 vendor 枚举，`coords.py` 和 `vecmath.py` 各存了一份；
- 角度单位是弧度不是度（上游是度，搬过来最容易漏）。

⚠ 按 CLAUDE.md 验证纪律 #11：**新增回归防护必须把 bug 注回去、确认它真的 FAIL**，
只看它绿不算数。下面每条断言旁边都注明了它对应哪个真实故障模式。
"""

import ast
import math
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import (  # noqa: E402
    DIST_ONESIDED, DIST_SYMMETRIC, FieldShapeError, FieldView, MIN_MAX_INT2_FIELDS,
    HALF_OPEN_MAX_FIELDS,
    PAIR_MIN_MAX_FIELDS, ROTATION_ORDER, SR_INDEX_FIELDS, SR_MIN_MAX_FIELDS,
    SimConfig, Vec3,
    build_behaviors, particle_rng, rotate_euler, rotation_order_name, sweep_fraction,
    unit_from_spherical,
)
from efx_sim import registry as _registry  # noqa: E402
from efx_sim import stages as _stages  # noqa: E402
from efx_sim.registry import Behavior  # noqa: E402


# ---------------------------------------------------------------------------
# 工具：不 import bpy 的前提下从 blender_efx_re/*.py 里抠出常量
# ---------------------------------------------------------------------------

def _module_assignments(rel_path):
    """用 ast 解析一个模块，返回 {顶层变量名: ast 节点}。不执行代码，所以不会碰 bpy。"""
    path = os.path.join(_REPO_ROOT, rel_path)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
    return out


def _literal_string_set(node):
    """`frozenset({"a", "b"})` / `{"a", "b"}` / `("a", "b")` -> `set[str]`。"""
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("frozenset", "set"):
        node = node.args[0] if node.args else ast.Set(elts=[])
    return set(ast.literal_eval(node))


# ---------------------------------------------------------------------------
# 名单镜像：efx_sim/shapes.py <-> blender_efx_re/model.py
# ---------------------------------------------------------------------------

class TestFieldNameMirrors(unittest.TestCase):
    """`shapes.py` 的三张名单是 `model.py` 同名常量的镜像。

    故障模式：往 `model.py` 的例外表里加了一个字段而 `shapes.py` 没跟上 —— 面板按新语义画、
    预览按旧语义算，两边不一致且没有任何东西会报错。
    """

    @classmethod
    def setUpClass(cls):
        cls.model = _module_assignments("blender_efx_re/model.py")

    def test_sr_index_fields_match(self):
        self.assertEqual(
            _literal_string_set(self.model["_SR_INDEX_FIELD_NAMES"]),
            set(SR_INDEX_FIELDS),
            "model._SR_INDEX_FIELD_NAMES 和 shapes.SR_INDEX_FIELDS 漂了")

    def test_sr_min_max_fields_match(self):
        self.assertEqual(
            _literal_string_set(self.model["_SR_MIN_MAX_FIELD_NAMES"]),
            set(SR_MIN_MAX_FIELDS),
            "model._SR_MIN_MAX_FIELD_NAMES 和 shapes.SR_MIN_MAX_FIELDS 漂了")

    def test_half_open_max_fields_match(self):
        self.assertEqual(
            _literal_string_set(self.model["_HALF_OPEN_MAX_FIELD_NAMES"]),
            set(HALF_OPEN_MAX_FIELDS),
            "model._HALF_OPEN_MAX_FIELD_NAMES 和 shapes.HALF_OPEN_MAX_FIELDS 漂了")

    def test_half_open_is_subset_of_min_max(self):
        """半开名单必须是 min/max 名单的子集——"上界取不到"只对 min/max 有意义，
        把一个 static/random 字段写进半开名单只会让取样悄悄少一格。"""
        self.assertTrue(set(HALF_OPEN_MAX_FIELDS) <= set(SR_MIN_MAX_FIELDS),
                        f"{set(HALF_OPEN_MAX_FIELDS) - set(SR_MIN_MAX_FIELDS)} 不在 SR_MIN_MAX_FIELDS 里")

    def test_min_max_int2_fields_match(self):
        self.assertEqual(
            _literal_string_set(self.model["_MIN_MAX_FIELD_NAMES"]),
            set(MIN_MAX_INT2_FIELDS),
            "model._MIN_MAX_FIELD_NAMES 和 shapes.MIN_MAX_INT2_FIELDS 漂了")

    def test_pair_min_max_fields_match(self):
        """`(类型, 字段)` 键的那张表同样要镜像——面板按它画 Min/Max，预览按它抽区间，
        两边漂了就是"面板显示的区间"和"预览用的区间"不是一回事。"""
        self.assertEqual(
            _literal_string_set(self.model["_PAIR_MIN_MAX_FIELDS"]),
            set(PAIR_MIN_MAX_FIELDS),
            "model._PAIR_MIN_MAX_FIELDS 和 shapes.PAIR_MIN_MAX_FIELDS 漂了")


class TestRotationOrderMirror(unittest.TestCase):
    """`vecmath.ROTATION_ORDER` 和 `coords._ROTATION_ORDER_NAMES` 是同一份 vendor 枚举。

    故障模式：照搬上游 EFX-Editor 的 `ROT_ORDER_TRANSFORM`（下标 2/4 和 vendor 相反），
    `RotationOrder=2` 会被读成 YXZ 而不是 ZXY —— 语料里 98% 的值都是 2，等于全体读错。
    """

    def test_matches_coords(self):
        node = _module_assignments("blender_efx_re/coords.py")["_ROTATION_ORDER_NAMES"]
        table = ast.literal_eval(node)
        self.assertEqual([table[i] for i in range(len(table))], list(ROTATION_ORDER))

    def test_index_two_is_zxy(self):
        # 语料里 Transform3D.RotationOrder 有 98.8% 是 2，这一条读错等于全体读错
        self.assertEqual(ROTATION_ORDER[2], "ZXY")
        self.assertEqual(ROTATION_ORDER[4], "YXZ")

    def test_tolerates_string_and_out_of_range(self):
        self.assertEqual(rotation_order_name(2), "ZXY")
        self.assertEqual(rotation_order_name("RotationOrder_ZYX"), "ZYX")
        self.assertEqual(rotation_order_name(99), "XYZ")
        self.assertEqual(rotation_order_name(None), "XYZ")


# ---------------------------------------------------------------------------
# FieldView：打包形状的读法
# ---------------------------------------------------------------------------

class TestFieldViewShapes(unittest.TestCase):

    def test_primary_is_binary_first_field_per_struct(self):
        """主值是**二进制首字段**：`Range`(float) 是 `s`，`RangeI`(int) 是 `r`。

        故障模式：写死"`s` 是静态值"。那样 `Spawn.LoopNum = {"r":1,"s":0}`（全语料 55%）
        会被读成"循环 0 次"，而真实语义是"循环 1 次"——98.6% 的发射器直接不发射。
        """
        # RangeI（两个分量都是 int）→ 主值在 r
        v = FieldView({"LoopNum": {"r": 1, "s": 0}}, "Spawn")
        self.assertEqual(v.sr("LoopNum"), (1.0, 0.0))       # (static, random)

        # Range（浮点）→ 主值在 s
        v2 = FieldView({"SpeedCoef": {"s": 0.98, "r": 0.0}}, "Velocity3D")
        self.assertEqual(v2.sr("SpeedCoef"), (0.98, 0.0))

    def test_not_positional(self):
        """必须按 key 取，不能按 `values()` 顺序——两个结构体的键序本来就相反。"""
        a = FieldView({"SpeedDelayFrame": {"r": 5, "s": 0}}, "Velocity3D")
        b = FieldView({"SpeedDelayFrame": {"s": 0, "r": 5}}, "Velocity3D")
        self.assertEqual(a.sr("SpeedDelayFrame"), b.sr("SpeedDelayFrame"))
        self.assertEqual(a.sr("SpeedDelayFrame"), (5.0, 0.0))

    def test_life_fields_are_min_max(self):
        """`Life` 的四个 `RangeI` 是 (min, max)，不是 (静态值, 随机量)。

        判据：全语料 91178 个实例里 `r > s` 出现 **0 次**（同为 RangeI 的
        `Spawn.LoopNum` 有 74.7%）。`min` 即主值 `r`。
        """
        v = FieldView({"AppearFrame": {"r": 20, "s": 20},
                       "KeepFrame": {"r": 0, "s": 15},
                       "VanishFrame": {"r": 30, "s": 40}}, "Life")
        self.assertEqual(v.min_max_pair("AppearFrame"), (20.0, 20.0))
        self.assertEqual(v.min_max_pair("KeepFrame"), (0.0, 15.0))
        self.assertEqual(v.min_max_pair("VanishFrame"), (30.0, 40.0))
        # 抽出来必须落在区间内，且 min==max 时恒定
        rng = particle_rng(1, 0)
        self.assertEqual(v.roll_min_max_pair_int("AppearFrame", rng), 20)
        for i in range(50):
            got = v.roll_min_max_pair_int("VanishFrame", particle_rng(2, i))
            self.assertTrue(30 <= got <= 40, got)

    def test_sr_rejects_index_and_minmax_fields(self):
        """例外名单里的字段按 static/random 读会抛，不静默返回错误语义。"""
        v = FieldView({"SequenceNo": {"s": 5, "r": 4},
                       "PatternNo": {"s": 63, "r": 0},
                       "PlaySpeed": {"s": 1.0, "r": 2.0}}, "UVSequence")
        for key in ("SequenceNo", "PatternNo", "PlaySpeed"):
            with self.assertRaises(FieldShapeError):
                v.sr(key)

    def test_sr_rejects_life_min_max_fields(self):
        v = FieldView({"AppearFrame": {"r": 20, "s": 20}}, "Life")
        with self.assertRaises(FieldShapeError):
            v.sr("AppearFrame")

    def test_min_max_pair_is_keyed_by_type_not_bare_name(self):
        """名单按 `(类型, 字段)` 键：`VanishFrame` 在 `Life` 上是 `RangeI`、在
        `VanishArea3D` 上是 `Range`，裸字段名会误伤后者。"""
        self.assertIn(("Life", "VanishFrame"), PAIR_MIN_MAX_FIELDS)
        other = FieldView({"VanishFrame": {"s": 1.0, "r": 0.0}}, "VanishArea3D")
        self.assertEqual(other.sr("VanishFrame"), (1.0, 0.0))   # 走默认 static/random
        with self.assertRaises(FieldShapeError):
            other.min_max_pair("VanishFrame")

    def test_sr_min_max_needs_no_per_field_flip(self):
        """`PatternNo`(RangeI, 主值 r) 和 `PlaySpeed`(Range, 主值 s) 都是"主值即 min"。

        model.py 记的"两个字段 s/r 顺序相反"其实就是两个结构体声明顺序相反的表现，
        不是两套独立规则——所以这里不需要按字段名翻转。
        """
        v = FieldView({"PatternNo": {"s": 63, "r": 8},
                       "PlaySpeed": {"s": 1.0, "r": 2.0}}, "UVSequence")
        self.assertEqual(v.sr_min_max("PatternNo"), (8.0, 63.0))
        self.assertEqual(v.sr_min_max("PlaySpeed"), (1.0, 2.0))

    def test_min_max_only_for_listed_fields(self):
        v = FieldView({"SpawnNum": {"x": 1, "y": 4}, "SomeOther": {"x": 1, "y": 4}}, "Spawn")
        self.assertEqual(v.min_max("SpawnNum"), (1, 4))
        with self.assertRaises(FieldShapeError):
            v.min_max("SomeOther")          # 不在名单里的 {x,y} 不保证是 min/max
        self.assertEqual(v.xy("SomeOther"), (1, 4))

    def test_min_max_does_not_swap_reversed_range(self):
        """语料里 max < min 真实存在（面板为此有崩溃风险提示），原样交出去不静默交换。"""
        v = FieldView({"IntervalFrame": {"x": 9, "y": 2}}, "Spawn")
        self.assertEqual(v.min_max("IntervalFrame"), (9, 2))

    def test_vec3_accepts_both_key_cases(self):
        v = FieldView({"LocalPosition": {"X": 1.0, "Y": 2.0, "Z": 3.0},
                       "Something": {"x": 4.0, "y": 5.0, "z": 6.0}}, "Transform3D")
        self.assertEqual(v.vec3("LocalPosition"), Vec3(1, 2, 3))
        self.assertEqual(v.vec3("Something"), Vec3(4, 5, 6))

    def test_vec3_missing_raises_without_default(self):
        v = FieldView({}, "Transform3D")
        with self.assertRaises(FieldShapeError):
            v.vec3("LocalPosition")
        self.assertEqual(v.vec3("LocalPosition", Vec3()), Vec3())

    def test_scalar_accessors_are_type_safe(self):
        v = FieldView({"Flags": 0, "UseSpawnFrame": False, "DistancePerSpawn": 1.0,
                       "UVSPath": "Art/VFX/UVS/a.uvs"}, "Spawn")
        self.assertEqual(v.i("Flags"), 0)
        self.assertIs(v.b("UseSpawnFrame"), False)
        self.assertEqual(v.f("DistancePerSpawn"), 1.0)
        self.assertEqual(v.s("UVSPath"), "Art/VFX/UVS/a.uvs")
        self.assertEqual(v.f("NotThere", 7.0), 7.0)

    def test_emitter_shape_range_is_min_max_not_static_random(self):
        """`EmitterShape3D.RangeX/Y/Z` 是 `(min, max)`，**按 static/random 读会直接抛**。

        "`r` 可以为负"早先被当成"这不是 static/random"的旁证，现在全语料把它定死了
        （`max < min` 0/62492，而主值非零的有 3.6 万例）——所以 `sr()` 必须拒绝，
        不能让哪个 behavior 又按 `[s, s+r]` 读回去。
        """
        v = FieldView({"RangeY": {"s": -0.5, "r": 0.5}}, "EmitterShape3D")
        with self.assertRaises(FieldShapeError):
            v.sr("RangeY")
        # 对称负数对读作"以原点为中心"，不是 `[-0.5, 0]`
        self.assertEqual(v.min_max_pair("RangeY"), (-0.5, 0.5))


# ---------------------------------------------------------------------------
# 随机：确定性与分布
# ---------------------------------------------------------------------------

class TestRng(unittest.TestCase):

    def test_same_seed_same_rolls(self):
        v = FieldView({"Speed": {"s": 1.0, "r": 2.0}}, "Velocity3D")
        a = [v.roll("Speed", particle_rng(42, i)) for i in range(8)]
        b = [v.roll("Speed", particle_rng(42, i)) for i in range(8)]
        self.assertEqual(a, b)

    def test_different_particle_index_differs(self):
        v = FieldView({"Speed": {"s": 1.0, "r": 2.0}}, "Velocity3D")
        vals = {v.roll("Speed", particle_rng(42, i)) for i in range(8)}
        self.assertGreater(len(vals), 1)

    def test_zero_random_still_consumes_a_draw(self):
        """`r == 0` 仍然抽一次：把某字段的 r 从 0 改成非 0 时不会打乱其他字段的抽值。"""
        rng = particle_rng(7, 0)
        v = FieldView({"A": {"s": 5.0, "r": 0.0}, "B": {"s": 0.0, "r": 1.0}}, "X")
        self.assertEqual(v.roll("A", rng), 5.0)
        after_with_a = v.roll("B", rng)

        rng2 = particle_rng(7, 0)
        rng2.uniform(0.0, 0.0)       # 等价于 A 那一次抽取
        self.assertEqual(v.roll("B", rng2), after_with_a)

    def test_onesided_vs_symmetric_bounds(self):
        v = FieldView({"A": {"s": 10.0, "r": 2.0}}, "X")
        for i in range(200):
            one = v.roll("A", particle_rng(1, i), DIST_ONESIDED)
            sym = v.roll("A", particle_rng(1, i), DIST_SYMMETRIC)
            self.assertTrue(10.0 <= one <= 12.0, one)
            self.assertTrue(8.0 <= sym <= 12.0, sym)


# ---------------------------------------------------------------------------
# vecmath：弧度 + 顺序串
# ---------------------------------------------------------------------------

class TestVecmath(unittest.TestCase):

    def test_rotate_euler_takes_radians(self):
        """上游收的是**度**，搬过来最容易漏改这一处。

        故障模式：漏改的话 `LocalRotation.X = 1.5707964`（π/2，即 90°）会被当成 1.57 度，
        旋转几乎不可见——而语料里那正是最高频的非零取值。
        """
        got = rotate_euler(Vec3(1, 0, 0), 0.0, 0.0, math.pi / 2.0, order="XYZ")
        self.assertAlmostEqual(got.x, 0.0, places=6)
        self.assertAlmostEqual(got.y, 1.0, places=6)

        # 若按"度"解释，转 π/2 度 ≈ 1.57°，x 分量几乎不变 —— 这条正是用来钉死单位的
        self.assertLess(got.x, 0.5)

    def test_rotate_euler_order_matters(self):
        v = Vec3(1, 0, 0)
        a = rotate_euler(v, math.pi / 2, math.pi / 2, 0.0, order="XYZ")
        b = rotate_euler(v, math.pi / 2, math.pi / 2, 0.0, order="ZYX")
        self.assertNotEqual((round(a.x, 6), round(a.y, 6), round(a.z, 6)),
                            (round(b.x, 6), round(b.y, 6), round(b.z, 6)))

    def test_rotate_euler_zero_is_identity(self):
        self.assertEqual(rotate_euler(Vec3(1, 2, 3), 0, 0, 0), Vec3(1, 2, 3))

    def test_unit_from_spherical_is_unit(self):
        for az in (0.0, 1.0, math.pi, 5.0):
            for polar in (-math.pi / 2, -0.3, 0.0, 0.7, math.pi / 2):
                u = unit_from_spherical(az, polar)
                self.assertAlmostEqual(u.length(), 1.0, places=6)

    def test_unit_from_spherical_poles(self):
        self.assertAlmostEqual(unit_from_spherical(0.0, math.pi / 2).y, 1.0, places=6)
        self.assertAlmostEqual(unit_from_spherical(0.0, -math.pi / 2).y, -1.0, places=6)

    def test_sweep_fraction_stays_in_span(self):
        rng = particle_rng(3, 0)
        for _ in range(100):
            a = sweep_fraction(rng, 0.0, 2.0 * math.pi)
            self.assertTrue(0.0 <= a <= 2.0 * math.pi)
        for _ in range(100):
            a = sweep_fraction(rng, -math.pi / 2, math.pi)
            self.assertTrue(-math.pi / 2 - 1e-9 <= a <= math.pi / 2 + 1e-9)

    def test_sweep_fraction_zero_span_is_constant(self):
        rng = particle_rng(3, 0)
        self.assertEqual({sweep_fraction(rng, 1.0, 0.0) for _ in range(20)}, {1.0})


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):

    def setUp(self):
        self._saved = dict(_registry._REGISTRY)

    def tearDown(self):
        _registry._REGISTRY.clear()
        _registry._REGISTRY.update(self._saved)

    def test_missing_stage_is_rejected(self):
        """本仓不做分类回退：没声明 STAGE 就不许注册。"""
        with self.assertRaises(TypeError):
            @_registry.register("ZZTestNoStage")
            class _NoStage(Behavior):
                pass

    def test_bad_stage_is_rejected(self):
        with self.assertRaises(TypeError):
            @_registry.register("ZZTestBadStage")
            class _BadStage(Behavior):
                STAGE = 999

    def test_duplicate_registration_is_rejected(self):
        @_registry.register("ZZTestDup")
        class _A(Behavior):
            STAGE = _stages.FORCE

        with self.assertRaises(ValueError):
            @_registry.register("ZZTestDup")
            class _B(Behavior):
                STAGE = _stages.FORCE

    def test_unregistered_goes_to_unsupported(self):
        """未注册的属性不静默消失，进 unsupported —— 面板据此显示"N 个未模拟属性"。"""
        @_registry.register("ZZTestKnown")
        class _Known(Behavior):
            STAGE = _stages.FORCE

        bound, unsupported = build_behaviors(
            [("ZZTestKnown", {}), ("ZZTestNeverHeardOf", {})], SimConfig())
        self.assertEqual([b.type_name for b in bound], ["ZZTestKnown"])
        self.assertEqual(unsupported, ["ZZTestNeverHeardOf"])

    def test_disabled_goes_to_unsupported(self):
        @_registry.register("ZZTestDisabled")
        class _D(Behavior):
            STAGE = _stages.FORCE

        bound, unsupported = build_behaviors(
            [("ZZTestDisabled", {})], SimConfig(disabled=frozenset({"ZZTestDisabled"})))
        self.assertEqual(bound, [])
        self.assertEqual(unsupported, ["ZZTestDisabled"])

    def test_sorted_by_stage_then_order_then_position(self):
        @_registry.register("ZZTestLate")
        class _Late(Behavior):
            STAGE = _stages.SHADE

        @_registry.register("ZZTestEarly")
        class _Early(Behavior):
            STAGE = _stages.FORCE

        bound, _ = build_behaviors(
            [("ZZTestLate", {}), ("ZZTestEarly", {})], SimConfig())
        self.assertEqual([b.type_name for b in bound], ["ZZTestEarly", "ZZTestLate"])

    def test_order_override(self):
        @_registry.register("ZZTestOv")
        class _Ov(Behavior):
            STAGE = _stages.SHADE

        cfg = SimConfig(order_override={"ZZTestOv": (_stages.FORCE, 1)})
        bound, _ = build_behaviors([("ZZTestOv", {})], cfg)
        self.assertEqual(bound[0].stage, _stages.FORCE)

    def test_implements_detects_overrides(self):
        @_registry.register("ZZTestImpl")
        class _Impl(Behavior):
            STAGE = _stages.FORCE

            def on_particle_step(self, p, em):
                pass

        bound, _ = build_behaviors([("ZZTestImpl", {})], SimConfig())
        self.assertTrue(_registry.implements(bound[0], "on_particle_step"))
        self.assertFalse(_registry.implements(bound[0], "on_emitter_step"))


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):

    def test_unknown_kwarg_rejected(self):
        with self.assertRaises(TypeError):
            SimConfig(nonexistent=1)

    def test_describe_unknowns_covers_the_table(self):
        """`UNKNOWNS` 里的每一项都要在 SimConfig 上真有对应属性 —— 面板靠这个渲染开关。"""
        from efx_sim.config import UNKNOWNS
        desc = SimConfig().describe_unknowns()
        self.assertEqual(set(desc), set(UNKNOWNS))
        for key, (_doc, candidates, default) in UNKNOWNS.items():
            self.assertIn(default, candidates, key)
            self.assertEqual(desc[key], default, key)


if __name__ == "__main__":
    unittest.main()
