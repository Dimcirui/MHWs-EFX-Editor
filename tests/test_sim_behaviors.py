# -*- coding: utf-8 -*-
"""
tests/test_sim_behaviors.py —— P0 五个 behavior + Simulator 的单测（**不需要 Blender**）

    python -m unittest discover -s tests

盯的是**这批 behavior 里真正会出错的地方**，不是覆盖率：

- `Life` 的四个字段是 (min,max) 而不是 (静态值,随机量)，读错寿命就全错；
- `EmitterShape3D` 的 `Scale*` 在用不上它的形状上是中性默认值 `(1.0, 0.0)`，
  照读会得到一个 1 弧度的假起始角；
- `Velocity3D` 的 `Speed`/`GravityRate` 按秒、`SpeedCoef` 按帧，混一起就是量级灾难；
- 未实现的 `VelocityType` 必须进 note 而不是按 Direction 糊过去。

⚠ 按 CLAUDE.md 验证纪律 #11：每条断言都对应一个真实故障模式，且都实际注入验证过会 FAIL。
"""

import math
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import SimConfig, Simulator, is_render_body_name  # noqa: E402


def _rangei(primary, secondary):
    """`RangeI` 的 JSON 形状：`{r, s}`，**主值在 `r`**。

    副值是"随机量"还是"max"**逐字段不同**（`Life` 的四个 Frame 是 max，`Spawn.LoopNum` /
    `Velocity3D.SpeedDelayFrame` 是随机量），所以这里只按主值/副值命名，不写死语义——
    写死了就会像第一版那样把 `SpeedDelayFrame=(5,5)` 当成"延迟 5 帧"，实际是"5 加上 0..5"。
    """
    return {"r": int(primary), "s": int(secondary)}


def _range(static, random_amount=0.0):
    """`Range` 的 JSON 形状：`{s, r}`，**主值 s 在前**。"""
    return {"s": float(static), "r": float(random_amount)}


def _int2(x, y):
    return {"x": int(x), "y": int(y)}


def life_block(appear=0, keep=10, vanish=0, hold=0, flags=0):
    return ("Life", {"AppearFrame": _rangei(appear, appear),
                     "KeepFrame": _rangei(keep, keep),
                     "VanishFrame": _rangei(vanish, vanish),
                     "KeepHoldFrame": _rangei(hold, hold),
                     "Flags": flags})


def spawn_block(num=1, interval=0, loops=1, delay=0, cap=100):
    return ("Spawn", {"MaxParticles": cap,
                      "SpawnNum": _int2(num, num),
                      "IntervalFrame": _int2(interval, interval),
                      "EmitterDelayFrame": _int2(delay, delay),
                      "LoopNum": _rangei(loops, 0)})


def billboard_block(size=1.0, rgba=0xFFFFFFFF):
    return ("TypeBillboard3D", {"SizeX": _range(size), "SizeY": _range(size),
                                "SizeScalar": _range(1.0), "Rotation": _range(0.0),
                                "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                                "Offset": _range(0.0), "Flags": 0})


# ---------------------------------------------------------------------------
# Life
# ---------------------------------------------------------------------------

class TestLife(unittest.TestCase):

    def test_total_is_sum_of_three(self):
        sim = Simulator([spawn_block(loops=1), life_block(appear=2, keep=5, vanish=3)],
                        SimConfig(seed=1))
        sim.step()
        self.assertEqual(sim.em.particles[0].life, 10)

    def test_keep_model(self):
        sim = Simulator([spawn_block(loops=1), life_block(appear=2, keep=5, vanish=3)],
                        SimConfig(seed=1, life_model="keep"))
        sim.step()
        self.assertEqual(sim.em.particles[0].life, 5)

    def test_particle_dies_at_total(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=4)], SimConfig(seed=1))
        sim.run(4)
        self.assertEqual(len(sim.em.particles), 1)   # 出生当帧就算 age=0，活满 4 帧
        sim.step()
        self.assertEqual(len(sim.em.particles), 0)

    def test_alpha_fades_in_and_out(self):
        sim = Simulator([spawn_block(loops=1), life_block(appear=4, keep=2, vanish=4)],
                        SimConfig(seed=1))
        seen = []
        for _ in range(10):
            sim.step()
            seen.append(sim.em.particles[0].alpha if sim.em.particles else 0.0)
        self.assertLess(seen[0], seen[2])            # 淡入
        self.assertAlmostEqual(max(seen), 1.0, places=5)
        self.assertLess(seen[-2], max(seen))         # 淡出

    def test_min_max_is_a_range_not_static_plus_random(self):
        """`(r=10, s=20)` 是"10 到 20"，不是"10 加上 0..20"。

        故障模式：按 (静态值,随机量) 读的话寿命会是 10..30，上界差 50%。
        """
        block = ("Life", {"AppearFrame": _rangei(0, 0), "KeepFrame": _rangei(10, 20),
                          "VanishFrame": _rangei(0, 0), "KeepHoldFrame": _rangei(0, 0),
                          "Flags": 0})
        lifes = set()
        for seed in range(30):
            sim = Simulator([spawn_block(loops=1), block], SimConfig(seed=seed))
            sim.step()
            lifes.add(sim.em.particles[0].life)
        self.assertTrue(lifes, "一个粒子都没生出来")
        self.assertGreaterEqual(min(lifes), 10)
        self.assertLessEqual(max(lifes), 20)

    def test_keep_hold_frame_ignored_by_default_and_noted(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=5, hold=7)],
                        SimConfig(seed=1))
        sim.step()
        self.assertEqual(sim.em.particles[0].life, 5)
        self.assertTrue(any("KeepHoldFrame" in n for n in sim.em.notes))

    def test_flags_one_is_continuous_lifetime(self):
        """`Flags=1` = 持续开关打开 = 无限寿命（010 模板 `ContinuesSwitch`：「0关闭1特效
        变为持续性」；MHWI 那边是独立的 `indefiniteLifespan` 字段）。

        故障模式：当成普通寿命的话，全语料 15.7% 的 Life 实例会在几十帧后集体消失，
        而它们本该一直存在（环境类持续特效）。
        """
        sim = Simulator([spawn_block(loops=1), life_block(keep=4, flags=1)],
                        SimConfig(seed=1))
        sim.run(50)
        self.assertEqual(len(sim.em.particles), 1, "持续性粒子不该被寿命判死")
        self.assertEqual(sim.em.particles[0].life, 0)

    def test_flags_one_has_fade_in_but_no_fade_out(self):
        sim = Simulator([spawn_block(loops=1), life_block(appear=4, keep=4, vanish=4,
                                                          flags=1)], SimConfig(seed=1))
        alphas = []
        for _ in range(30):
            sim.step()
            alphas.append(sim.em.particles[0].alpha)
        self.assertLess(alphas[0], alphas[3])            # 淡入照常
        self.assertAlmostEqual(alphas[-1], 1.0, places=6)  # 之后一直满，不淡出
        self.assertTrue(any("VanishFrame" in n for n in sim.em.notes))

    def test_flags_zero_is_normal_lifetime(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=4, flags=0)],
                        SimConfig(seed=1))
        sim.run(5)
        self.assertEqual(len(sim.em.particles), 0)

    def test_unknown_flags_falls_back_to_normal_and_notes(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=4, flags=2)],
                        SimConfig(seed=1))
        sim.run(5)
        self.assertEqual(len(sim.em.particles), 0)
        self.assertTrue(any("Flags=2" in n for n in sim.em.notes))

    def test_zero_total_does_not_kill(self):
        """三段都是 0 -> 不按寿命判死（该 entry 没给寿命），不是立刻消失。"""
        sim = Simulator([spawn_block(loops=1), life_block(appear=0, keep=0, vanish=0)],
                        SimConfig(seed=1))
        sim.run(20)
        self.assertEqual(len(sim.em.particles), 1)


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------

class TestSpawn(unittest.TestCase):

    def test_loop_count_limits_bursts(self):
        sim = Simulator([spawn_block(num=2, interval=1, loops=3), life_block(keep=100)],
                        SimConfig(seed=1))
        sim.run(60)
        self.assertEqual(sim.em.spawned_total, 6)     # 3 批 × 2 个

    def test_loop_zero_is_infinite(self):
        """`LoopNum` 主值为 0 = 无限发。

        故障模式：把 `{r:1, s:0}` 按 s 读成 0，55% 的发射器会被当成无限循环；
        反过来把 `{r:0,s:0}` 读成"发 0 批"则什么都不生成。
        """
        sim = Simulator([spawn_block(num=1, interval=1, loops=0), life_block(keep=1000)],
                        SimConfig(seed=1))
        sim.run(40)
        self.assertGreater(sim.em.spawned_total, 15)

    def test_emitter_delay(self):
        sim = Simulator([spawn_block(num=1, loops=1, delay=5), life_block(keep=100)],
                        SimConfig(seed=1))
        sim.run(5)
        self.assertEqual(sim.em.spawned_total, 0)
        sim.step()
        self.assertEqual(sim.em.spawned_total, 1)

    def test_max_particles_is_a_live_cap(self):
        """`MaxParticles` 是**同时存活**上限，不是终身总量。"""
        sim = Simulator([spawn_block(num=5, interval=0, loops=0, cap=3),
                         life_block(keep=1000)], SimConfig(seed=1))
        sim.run(30)
        self.assertEqual(len(sim.em.particles), 3)

    def test_interval_zero_spawns_every_frame(self):
        sim = Simulator([spawn_block(num=1, interval=0, loops=0), life_block(keep=1000)],
                        SimConfig(seed=1))
        sim.run(10)
        self.assertEqual(sim.em.spawned_total, 10)

    def test_unused_fields_are_noted(self):
        block = ("Spawn", dict(spawn_block()[1], RingBufferMode=True,
                               DistancePerSpawn=2.5))
        sim = Simulator([block, life_block()], SimConfig(seed=1))
        notes = " ".join(sim.em.notes)
        self.assertIn("RingBufferMode", notes)
        self.assertIn("DistancePerSpawn", notes)


# ---------------------------------------------------------------------------
# EmitterShape3D
# ---------------------------------------------------------------------------

def shape_block(shape, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                sh=(1.0, 0.0), sv=(1.0, 0.0)):
    return ("EmitterShape3D", {
        "ShapeType": shape,
        "RangeX": _range(*rx), "RangeY": _range(*ry), "RangeZ": _range(*rz),
        "ScaleHorizontal": _range(*sh), "ScaleVertical": _range(*sv),
        "LocalRotation": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "RotationOrder": 2,
        "RangeDivideNum": 0, "RangeDivideHorizontalNum": 0,
        "RangeDivideVerticalNum": 0, "RotationCorrect": 0,
    })


class TestEmitterShape3D(unittest.TestCase):

    def _positions(self, block, n=80):
        out = []
        for seed in range(n):
            sim = Simulator([spawn_block(loops=1), life_block(keep=100), block],
                            SimConfig(seed=seed))
            sim.step()
            out.append(sim.em.particles[0].pos)
        return out

    def test_box_samples_inside_the_interval(self):
        for p in self._positions(shape_block(0, rx=(0.2, 0.5))):
            self.assertGreaterEqual(p.x, 0.2 - 1e-9)
            self.assertLessEqual(p.x, 0.7 + 1e-9)      # static_random -> [s, s+r]

    def test_sweep_gating_never_reads_the_neutral_default(self):
        """用不上 `Scale*` 的形状必须走整圈 / 全扫的兜底，**绝不能读那个 `(1.0, 0.0)`**。

        故障模式：照读会得到"起始角 1 弧度、跨度 0"——一个恒定的假角度。语料里 Box 的
        `ScaleHorizontal` 99.2% 是 `(1.0, 0.0)`、Cylinder 的 `ScaleVertical` 92.6% 是
        `(1.0, 0.0)`，那是"本形状用不上"的中性值，不是角度（见 SIM_PORT_PLAN §8.4）。

        ⚠ 这条**直接测 `_sweep()`**，不通过采样结果间接测：Box 分支压根不调 `_sweep()`，
        Sphere 两个字段都在门控名单里——靠采样对比的话这个门控是够不到的，测了个寂寞。
        第一版就是这么写的，注入 bug 之后测试照样全绿才发现。
        """
        from efx_sim.behaviors.emittershape3d import (SHAPE_BOX, SHAPE_CYLINDER,
                                                      SHAPE_SPHERE, _sweep)
        from efx_sim.shapes import FieldView

        f = FieldView({"ScaleHorizontal": _range(1.0, 0.0),
                       "ScaleVertical": _range(1.0, 0.0)}, "EmitterShape3D")

        # 用不上的组合 -> 兜底值，不是 (1.0, 0.0)
        for shape, key in ((SHAPE_BOX, "ScaleHorizontal"), (SHAPE_BOX, "ScaleVertical"),
                           (SHAPE_CYLINDER, "ScaleVertical")):
            start, span = _sweep(f, key, shape)
            self.assertNotEqual((start, span), (1.0, 0.0),
                                "%s/%s 读到了中性默认值" % (shape, key))
            self.assertAlmostEqual(abs(span), 2 * math.pi if key == "ScaleHorizontal"
                                   else math.pi, places=6)

        # 用得上的组合 -> 如实读字段
        for shape, key in ((SHAPE_SPHERE, "ScaleHorizontal"), (SHAPE_SPHERE, "ScaleVertical"),
                           (SHAPE_CYLINDER, "ScaleHorizontal")):
            self.assertEqual(_sweep(f, key, shape), (1.0, 0.0))

    def test_box_sampling_is_unaffected_by_scale_fields(self):
        a = self._positions(shape_block(0, sh=(1.0, 0.0), sv=(1.0, 0.0)))
        b = self._positions(shape_block(0, sh=(0.0, 2 * math.pi), sv=(-math.pi / 2, math.pi)))
        self.assertEqual([p.as_tuple() for p in a], [p.as_tuple() for p in b])

    def test_sphere_is_bounded_by_outer_radius(self):
        pts = self._positions(shape_block(1, rx=(0.0, 2.0), ry=(0.0, 2.0), rz=(0.0, 2.0),
                                          sh=(0.0, 2 * math.pi), sv=(-math.pi / 2, math.pi)))
        for p in pts:
            self.assertLessEqual(p.length(), 2.0 + 1e-6)

    def test_sphere_fills_both_hemispheres_on_full_sweep(self):
        pts = self._positions(shape_block(1, rx=(0.0, 2.0), ry=(0.0, 2.0), rz=(0.0, 2.0),
                                          sh=(0.0, 2 * math.pi), sv=(-math.pi / 2, math.pi)))
        self.assertTrue(any(p.y > 0.3 for p in pts))
        self.assertTrue(any(p.y < -0.3 for p in pts))

    def test_cylinder_height_follows_rangey_sign(self):
        """`RangeY` 是**有符号**的位置偏移，不是半径——语料里真的会是负的。"""
        pts = self._positions(shape_block(2, rx=(0.0, 1.0), ry=(-0.2, 0.0), rz=(0.0, 1.0),
                                          sh=(0.0, 2 * math.pi)))
        for p in pts:
            self.assertAlmostEqual(p.y, -0.2, places=6)

    def test_horizontal_sweep_limits_azimuth(self):
        """半圈扫描时不应该出现在另外半圈里。"""
        pts = self._positions(shape_block(2, rx=(1.0, 0.0), ry=(0.0, 0.0), rz=(1.0, 0.0),
                                          sh=(0.0, math.pi)))
        self.assertTrue(all(p.z > -1e-6 for p in pts), "半圈扫描漏到了 z<0")

    def test_outline_is_non_empty_for_every_shape(self):
        for shape in (0, 1, 2):
            sim = Simulator([spawn_block(), life_block(), shape_block(shape)],
                            SimConfig(seed=1))
            self.assertTrue(sim.emitter_outline(), "形状 %d 没有线框" % shape)

    def test_unknown_shape_is_noted(self):
        sim = Simulator([spawn_block(), life_block(), shape_block(7)], SimConfig(seed=1))
        self.assertTrue(any("ShapeType=7" in n for n in sim.em.notes))


# ---------------------------------------------------------------------------
# Velocity3D
# ---------------------------------------------------------------------------

def vel_block(speed=1.0, coef=1.0, gravity=0.0, vtype=0, direction=(0.0, 1.0, 0.0)):
    return ("Velocity3D", {
        "VelocityType": vtype,
        "DirectionVectorX": _range(direction[0]), "DirectionVectorY": _range(direction[1]),
        "DirectionVectorZ": _range(direction[2]),
        "Speed": _range(speed), "SpeedCoef": _range(coef), "GravityRate": _range(gravity),
        "SpeedDelayFrame": _rangei(0, 0), "GravityDelayFrame": _rangei(0, 0),
        "InheritRate": _range(0.0), "InheritDistance": _range(0.0), "Spread": _range(0.0),
    })


class TestVelocity3D(unittest.TestCase):

    def test_per_second_is_the_default_and_moves_metres_not_hundreds(self):
        """`Speed=2.2`（全语料中位）一秒应该走 ~2.2 米，不是 132 米。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=1000), vel_block(speed=2.2)],
                        SimConfig(seed=1))
        sim.run(61)
        self.assertAlmostEqual(sim.em.particles[0].pos.y, 2.2, delta=0.1)

    def test_per_frame_switch_still_works(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=1000), vel_block(speed=2.2)],
                        SimConfig(seed=1, velocity_unit="per_frame"))
        sim.run(10)
        self.assertAlmostEqual(sim.em.particles[0].pos.y, 2.2 * 10, delta=0.01)

    def test_speed_coef_is_per_frame_regardless_of_unit(self):
        """`SpeedCoef` 是无量纲逐帧乘数，**不受 velocity_unit 影响**。

        故障模式：把它也按秒缩放，0.99 的衰减会几乎不起作用，而语料里 99.7% 的文件都设了它。
        """
        a = Simulator([spawn_block(loops=1), life_block(keep=1000),
                       vel_block(speed=1.0, coef=0.9)], SimConfig(seed=1))
        a.run(10)
        # 10 帧后速度应该是 0.9^10 ≈ 0.349（按秒缩放的话会是 ~0.998）
        self.assertAlmostEqual(a.em.particles[0].vel.y, 0.9 ** 10, places=5)

    def test_gravity_sign_is_added_not_subtracted(self):
        """`GravityRate` 语料里本身就是负数，代码里是**加**，别再取一次负号。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=1000),
                         vel_block(speed=0.0, gravity=-0.3)], SimConfig(seed=1))
        sim.run(30)
        self.assertLess(sim.em.particles[0].pos.y, 0.0)

    def test_non_direction_types_get_no_velocity_and_a_note(self):
        """其余四档必须进 note 并按无初速处理，**不许按 Direction 近似**。"""
        for vtype, name in ((1, "Normal"), (2, "Radial"), (3, "Spread")):
            sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                             vel_block(speed=5.0, vtype=vtype)], SimConfig(seed=1))
            sim.run(10)
            self.assertEqual(sim.em.particles[0].pos.as_tuple(), (0.0, 0.0, 0.0),
                             "%s 档不该有位移" % name)
            self.assertTrue(any(name in n for n in sim.em.notes), "%s 档没记 note" % name)

    def test_delay_frames_hold_the_particle_still(self):
        block = ("Velocity3D", dict(vel_block(speed=2.0)[1],
                                    SpeedDelayFrame=_rangei(5, 0)))  # 静态 5、不随机
        sim = Simulator([spawn_block(loops=1), life_block(keep=100), block],
                        SimConfig(seed=1))
        sim.run(5)
        self.assertEqual(sim.em.particles[0].pos.y, 0.0)
        sim.step()
        self.assertGreater(sim.em.particles[0].pos.y, 0.0)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class TestSimulator(unittest.TestCase):

    def test_render_body_name_follows_vendor_rule(self):
        self.assertTrue(is_render_body_name("TypeBillboard3D"))
        self.assertTrue(is_render_body_name("TypeMeshV2"))
        self.assertFalse(is_render_body_name("TypeBillboard3DClip"))
        self.assertFalse(is_render_body_name("TypeBillboard3DExpression"))
        self.assertFalse(is_render_body_name("Velocity3D"))

    def test_no_render_body_means_no_items(self):
        """没有渲染主体的 entry 不画退化点——本来就不该有画面，画了是凭空捏造。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10)], SimConfig(seed=1))
        sim.step()
        self.assertEqual(sim.build_render(), [])

    def test_unimplemented_render_body_falls_back_to_point(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         ("TypeRibbonLength", {})], SimConfig(seed=1))
        sim.step()
        items = sim.build_render()
        self.assertEqual([it.kind for it in items], ["POINT"])

    def test_billboard_produces_items_and_modulates_by_alpha(self):
        sim = Simulator([spawn_block(loops=1), life_block(appear=4, keep=4),
                         billboard_block()], SimConfig(seed=1))
        sim.step()
        first = sim.build_render()[0]
        self.assertEqual(first.kind, "BILLBOARD")
        self.assertAlmostEqual(first.color[3], 0.0, places=5)   # 淡入第 0 帧
        sim.run(3)
        self.assertGreater(sim.build_render()[0].color[3], 0.5)

    @staticmethod
    def _snapshot(em):
        """粒子的**全部**可变状态。只抓 pos 不够——碰了 `age`/`alpha` 当帧看不出差别。"""
        return (em.frame, [(p.pos.as_tuple(), p.vel.as_tuple(), p.scale.as_tuple(),
                            p.rot.as_tuple(), tuple(p.color), p.alpha, p.age,
                            p.life, p.alive, p.delay_left)
                           for p in em.particles])

    def test_build_render_does_not_advance_state(self):
        """渲染 pass 与 step 解耦：重复调用不改**任何**粒子状态（暂停转视角要靠这条）。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), billboard_block()],
                        SimConfig(seed=1))
        sim.run(3)
        before = self._snapshot(sim.em)
        for _ in range(3):
            sim.build_render()
        self.assertEqual(self._snapshot(sim.em), before)

    def test_same_seed_reproduces_exactly(self):
        def run(seed):
            sim = Simulator([spawn_block(num=3, interval=2, loops=5),
                             life_block(keep=200), shape_block(1), vel_block(speed=2.0),
                             billboard_block()], SimConfig(seed=seed))
            sim.run(40)
            return [p.pos.as_tuple() for p in sim.em.particles]
        self.assertTrue(run(7), "没有粒子存活，这条测试什么也没验到")
        self.assertEqual(run(7), run(7))
        self.assertNotEqual(run(7), run(8))

    def test_reset_returns_to_start(self):
        sim = Simulator([spawn_block(loops=2), life_block(keep=10)], SimConfig(seed=1))
        sim.run(5)
        sim.reset()
        self.assertEqual(sim.em.frame, -1)
        self.assertEqual(sim.em.spawned_total, 0)
        self.assertEqual(sim.em.particles, [])

    def test_unsupported_attributes_are_reported(self):
        sim = Simulator([spawn_block(), ("PtVortexelWind", {}), ("ShaderSettings", {})],
                        SimConfig(seed=1))
        self.assertEqual(sorted(sim.em.unsupported), ["PtVortexelWind", "ShaderSettings"])
        self.assertEqual(sum(1 for n in sim.em.notes if n.startswith("未模拟属性")), 2)

    def test_strict_mode_catches_out_of_stage_writes(self):
        from efx_sim import FORCE, Behavior
        from efx_sim import registry as _registry

        saved = dict(_registry._REGISTRY)
        try:
            @_registry.register("ZZTestBadWriter")
            class _Bad(Behavior):
                STAGE = FORCE          # 只允许写 vel
                def on_particle_step(self, p, em):
                    p.pos.x += 1.0     # 越界

            sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                             ("ZZTestBadWriter", {})], SimConfig(seed=1, strict=True))
            with self.assertRaises(AssertionError):
                sim.run(3)
        finally:
            _registry._REGISTRY.clear()
            _registry._REGISTRY.update(saved)

    def test_hard_particle_cap_is_noted(self):
        sim = Simulator([spawn_block(num=50, interval=0, loops=0, cap=0),
                         life_block(keep=1000)], SimConfig(seed=1, max_particles=10))
        sim.run(5)
        self.assertLessEqual(len(sim.em.particles), 10)
        self.assertTrue(any("max_particles" in n for n in sim.em.notes))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# UVSequence
# ---------------------------------------------------------------------------

def uvs_block(seq=0, lo=0, hi=1, speed=1.0, flags=1):
    """`SequenceNo` 是 RangeI 索引语义（主值 r = 实际下标，副值 s 恒为 r+1）；
    `PatternNo` 是 RangeI 的**起始帧号范围**（左闭右开 `[lo, hi)`）；
    `PlaySpeed` 是 **Range**(float) min/max。

    `flags` 默认 1 = 循环（`Flags` bit0-1 的播放模式）。**默认不能用 0**——0 是
    “只显示起始帧”，那样每个动画测试都会静止，反而看不出回归。"""
    return ("UVSequence", {"SequenceNo": _rangei(seq, seq + 1),
                           "PatternNo": _rangei(lo, hi),
                           "PlaySpeed": _range(speed, speed),
                           "Flags": flags, "UVSPath": "Art/VFX/UVS/x.uvs"})


def _resources(n_seq=2, n_frames=4, n_tex=2):
    from efx_sim import SimResources
    seqs = {}
    for s in range(n_seq):
        seqs[s] = []
        for i in range(n_frames):
            from efx_sim import Frame
            seqs[s].append(Frame(i / n_frames, 0.0, (i + 1) / n_frames, 1.0,
                                 texture_index=s % n_tex))
    return SimResources(seqs, ["texA", "texB"][:n_tex], source="x.uvs")


class TestUVSequence(unittest.TestCase):

    def _items(self, blocks, frames, resources=None, cfg=None):
        sim = Simulator(blocks, cfg or SimConfig(seed=1), resources=resources)
        out = []
        for _ in range(frames):
            sim.step()
            items = sim.build_render()
            out.append(items[0] if items else None)
        return sim, out

    def test_plays_whole_sequence_from_fixed_start(self):
        """`PatternNo` 是**起始帧号**，不是播放区间。

        故障模式（真的发出去过）：把 `[Min, Max)` 当成“只在这几帧之间播”，于是全语料
        21435 个 `Max=1` 的实例（“全体从第 0 帧起手”）被读成“只播第 0 帧”，整片 UVS
        静止不动。这里用最典型的 `[0, 1)` 钉死：它必须走完整条 4 帧序列并回绕。
        """
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=0, hi=1, speed=1.0)], 6, _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items],
                         [0, 1, 2, 3, 0, 1])

    def test_start_frame_shifts_the_whole_cycle(self):
        """起手帧非 0 时整条序列跟着平移，播的仍然是全部 4 帧。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=2, hi=3, speed=1.0)], 5, _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items],
                         [2, 3, 0, 1, 2])

    def test_start_frame_rolls_within_half_open_range(self):
        """`[0, 4)` 能抽到 0~3，**抽不到 4**；抽定之后播放期间不重抽。"""
        sim = Simulator([spawn_block(num=40, loops=1), life_block(keep=100),
                         billboard_block(), uvs_block(lo=0, hi=4, speed=0.0)],
                        SimConfig(seed=3), resources=_resources())
        sim.step()
        starts = {p.rolled["uvs_start"] for p in sim.em.particles}
        self.assertTrue(starts.issubset({0, 1, 2, 3}), starts)
        self.assertGreater(len(starts), 1, "起手帧应该逐粒子抽，不是全体同一个值")

    def test_start_only_mode_freezes_on_start_frame(self):
        """`Flags` 播放模式 0：只显示起始帧。全语料 12241 个实例走这条。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=1, hi=2, speed=1.0, flags=0)], 4, _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items], [1, 1, 1, 1])

    def test_once_hold_mode_stops_at_last_frame(self):
        """播放模式 3：播一次后定格在末帧。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=0, hi=1, speed=1.0, flags=3)], 6, _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items],
                         [0, 1, 2, 3, 3, 3])

    def test_once_vanish_mode_kills_the_particle(self):
        """播放模式 2：走完一轮把粒子杀掉——`UVSequence` 唯一影响寿命的地方。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=0, hi=1, speed=1.0, flags=2)], 6, _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items[:4]],
                         [0, 1, 2, 3])
        self.assertEqual(sim.em.alive_count, 0, "走完一轮之后粒子应该没了")

    def test_reverse_direction_plays_backwards(self):
        """`Flags` bit6-7 = 1：倒放。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=0, hi=1, speed=1.0, flags=1 | (1 << 6))], 5,
            _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items],
                         [0, 3, 2, 1, 0])

    def test_forced_loop_overrides_flags(self):
        """标定开关：uvs_playback=loop 不看 `Flags`，全体强制循环。"""
        cfg = SimConfig(seed=1, uvs_playback="loop")
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=0, hi=1, speed=1.0, flags=0)], 5, _resources(), cfg)
        self.assertEqual([it.extra["uvs_frame"] for it in items],
                         [0, 1, 2, 3, 0])

    def test_writes_uv_rect_and_texture_key(self):
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(seq=1, lo=0, hi=1)], 1, _resources())
        it = items[0]
        self.assertEqual(it.uv_rect, (0.0, 0.0, 0.25, 1.0))
        self.assertEqual(it.tex_key, "texB")      # 序列 1 -> textureIndex 1

    def test_sequence_index_uses_primary_not_companion(self):
        """`SequenceNo {r:1, s:2}` 是第 1 条，不是第 2 条。

        故障模式：读成副值 s 的话全语料每个 UVSequence 都会取到**下一条**序列
        （s 恒等于 r+1），画出来是另一段动画——看着正常，其实全错。
        """
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(seq=1)], 1, _resources())
        self.assertEqual(items[0].tex_key, "texB")
        sim2, items2 = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(seq=0)], 1, _resources())
        self.assertEqual(items2[0].tex_key, "texA")

    def test_no_resources_leaves_uv_alone_and_notes(self):
        """拿不到帧表就什么都不写，并 note——不编一个 0~1 的矩形冒充。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block()], 1, None)
        self.assertEqual(items[0].uv_rect, (0.0, 0.0, 1.0, 1.0))
        self.assertIsNone(items[0].tex_key)
        self.assertTrue(any("没有帧表" in n for n in sim.em.notes))

    def test_out_of_range_sequence_is_noted_not_silently_remapped(self):
        """序列下标越界不退回第 0 条——那会画出另一段动画且没人发现。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(seq=9)], 1, _resources())
        self.assertIsNone(items[0].tex_key)
        self.assertTrue(any("不存在" in n for n in sim.em.notes))

    def test_unsimulated_flip_bits_are_noted(self):
        """翻转/朝向位没实现就说出来——预览不静默按“不翻”糊过去。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(flags=1 | (2 << 2))], 1, _resources())
        self.assertTrue(any("未模拟" in n for n in sim.em.notes), sim.em.notes)

    def test_speed_scales_advance_rate(self):
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), billboard_block(),
             uvs_block(lo=0, hi=1, speed=0.5)], 4, _resources())
        self.assertEqual([it.extra["uvs_frame"] for it in items], [0, 0, 1, 1])

    def test_render_age_matches_shade_age(self):
        """`build_render()` 看到的 age 必须和 SHADE 阶段刚算过的那一帧一致。

        故障模式（真的写出来过）：`p.age += 1` 放在 step 末尾的话，`Life` 按 age=N 写的
        alpha 和 `UVSequence` 按 age=N+1 取的序列帧会画在同一个 RenderItem 上，却不是同
        一帧——画面看着正常，序列帧整体超前一帧，没人会发现。

        这里用“出生当帧的序列帧必须是起手帧本身”来钉：age=0 时 advanced=0，取 lo。
        """
        sim = Simulator([spawn_block(loops=1), life_block(appear=4, keep=100),
                         billboard_block(), uvs_block(lo=2, hi=3, speed=1.0)],
                        SimConfig(seed=1), resources=_resources(n_frames=8))
        sim.step()
        p = sim.em.particles[0]
        item = sim.build_render()[0]
        self.assertEqual(p.age, 0, "出生当帧 age 应为 0")
        self.assertEqual(item.extra["uvs_frame"], 2, "出生当帧应取起手帧")
        # alpha 也应是 age=0 的淡入起点
        self.assertAlmostEqual(item.color[3], 0.0, places=6)
