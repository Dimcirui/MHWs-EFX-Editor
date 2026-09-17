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

⚠ 按 CLAUDE.md 验证纪律：每条断言都对应一个真实故障模式，且都实际注入验证过会 FAIL。
"""

import math
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from efx_sim import SimConfig, Simulator, Vec3, is_render_body_name  # noqa: E402


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


def polygon_block(width=1.0, height=1.0, up_axis=1, rgba=0xFFFFFFFF):
    return ("TypePolygon", {"Width": _range(width), "Height": _range(height),
                            "SizeScalar": _range(1.0),
                            "RotationOrder": 2, "RotationX": _range(0.0),
                            "RotationY": _range(0.0), "RotationZ": _range(0.0),
                            "OrientDirectionUpVector": up_axis,
                            "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                            "Offset": _range(0.0), "Flags": 0, "Flags2": 0})


def ribbonlength_block(length=1.0, width=1.0, division=4, direction=(0.0, 1.0, 0.0),
                       rgba=0xFFFFFFFF):
    return ("TypeRibbonLength", {"Length": _range(length), "Width": _range(width),
                                 "SizeScalar": _range(1.0), "ShapeDivision": division,
                                 "DirectionX": _range(direction[0]),
                                 "DirectionY": _range(direction[1]),
                                 "DirectionZ": _range(direction[2]),
                                 "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                                 "Flags": 0, "BlendFlags": 0, "LengthFlags": 0})


def ribbonfollow_block(width=1.0, rgba=0xFFFFFFFF):
    return ("TypeRibbonFollow", {"Width": _range(width), "SizeScalar": _range(1.0),
                                 "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                                 "Flags": 0, "BlendFlags": 0})


def polygontrail_block(length=1.0, axis=2, rgba=0xFFFFFFFF):
    return ("TypePolygonTrail", {"Length": _range(length), "Axis": axis,
                                 "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                                 "ColorRate": 1.0, "Intensity": 0.0,
                                 "EdgeBlendRate": 0.0, "AlphaRate": 0.0,
                                 "Flags": 0, "re4_unkn": 0, "sb_unkn0": 1.0,
                                 "StretchDistance": 0.0, "NumTrailDivision": 0,
                                 "NumVerticalDivision": 0, "NumSplineDivision": 0,
                                 "IntervalFrame": 1})


def gpupolygon_block(width=1.0, height=1.0, up_axis=1, rgba=0xFFFFFFFF):
    return ("TypeGpuPolygon", {"Width": _range(width), "Height": _range(height),
                               "SizeScalar": _range(1.0),
                               "RotationX": _range(0.0), "RotationY": _range(0.0),
                               "RotationZ": _range(0.0), "OrientDirectionUpVector": up_axis,
                               "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                               "Flags": 0, "BlendFlags": 0, "ParticleNum": 0})


def gpuribbonlength_block(length=1.0, width=1.0, division=4, direction=(0.0, 1.0, 0.0),
                          rgba=0xFFFFFFFF):
    return ("TypeGpuRibbonLength", {"Length": _range(length), "Width": _range(width),
                                    "SizeScalar": _range(1.0), "ShapeDivision": division,
                                    "DirectionX": _range(direction[0]),
                                    "DirectionY": _range(direction[1]),
                                    "DirectionZ": _range(direction[2]),
                                    "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                                    "Flags": 0, "BlendFlags": 0, "ParticleNum": 128})


def meshv2_block(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0), rotation_order=2,
                 max_parts=1, rgba=0xFFFFFFFF, emissive_rgba=0x00000000):
    return ("TypeMeshV2", {"RotationOrder": rotation_order,
                           "RotationX": _range(rotation[0]), "RotationY": _range(rotation[1]),
                           "RotationZ": _range(rotation[2]),
                           "ScaleX": _range(scale[0]), "ScaleY": _range(scale[1]),
                           "ScaleZ": _range(scale[2]), "ScaleMultiplier": _range(1.0),
                           "Color": {"rgba": rgba}, "ColorRange": {"rgba": rgba},
                           "ColorRate": 1.0,
                           "EmissiveColor": {"rgba": emissive_rgba},
                           "EmissiveRate": 1.0,
                           "MaxPartsNum": max_parts, "PartsStartNo": _rangei(0, 0),
                           "PlaySpeed": _range(1.0), "PlaySpeedCoef": _range(1.0),
                           "PlayType": 0, "PlayOrder": 0, "FrontAxis": 1,
                           "Flags": 0, "Flags2": 0})


def scaleanim_block(scalar_add=0.0, scalar_coef=1.0, axis_add=(0.0, 0.0, 0.0),
                    axis_coef=(1.0, 1.0, 1.0), size_delay=0):
    return ("ScaleAnim", {"SizeScalarAdd": _range(scalar_add), "SizeScalarCoef": _range(scalar_coef),
                          "SizeXAdd": _range(axis_add[0]), "SizeXAddCoef": _range(axis_coef[0]),
                          "SizeYAdd": _range(axis_add[1]), "SizeYAddCoef": _range(axis_coef[1]),
                          "SizeZAdd": _range(axis_add[2]), "SizeZAddCoef": _range(axis_coef[2]),
                          "SizeDelayFrame": _rangei(size_delay, 0)})


def scaleanim_delay_block(frame_delay=0, unkn2=0):
    return ("ScaleAnimDelayFrame", {"frameDelay": frame_delay, "unkn2": unkn2})


def rotateanim_block(add=(0.0, 0.0, 0.0), coef=(1.0, 1.0, 1.0), delay=0, flags=0):
    return ("RotateAnim", {"Flags": flags,
                           "RotationAddX": _range(add[0]), "RotationAddY": _range(add[1]),
                           "RotationAddZ": _range(add[2]),
                           "RotationCoefX": _range(coef[0]), "RotationCoefY": _range(coef[1]),
                           "RotationCoefZ": _range(coef[2]),
                           "RotationDelayFrame": _rangei(delay, 0)})


def rotateanim_delay_block(frame_delay=0, unkn2=0):
    return ("RotateAnimDelayFrame", {"frameDelay": frame_delay, "unkn2": unkn2})


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
                sh=(1.0, 0.0), sv=(1.0, 0.0), use_ext=False,
                divide_axis=0, divide_num=0, divide_h=0, divide_v=0):
    return ("EmitterShape3D", {
        "ShapeType": shape,
        "RangeX": _range(*rx), "RangeY": _range(*ry), "RangeZ": _range(*rz),
        "ScaleHorizontal": _range(*sh), "ScaleVertical": _range(*sv),
        "UseExtension": use_ext,
        "LocalRotation": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "RotationOrder": 2,
        "RangeDivideAxis": divide_axis, "RangeDivideNum": divide_num,
        "RangeDivideHorizontalNum": divide_h,
        "RangeDivideVerticalNum": divide_v, "RotationCorrect": 0,
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
        """Box 的 `RangeX/Y/Z` 是**以 0 为界的绝对值区间，符号独立随机**（2026-09-17 实机
        确认），不是旧版"逐轴 `U(lo,hi)` 独立取的实心盒子"——`rx=(0.2,0.5)` 应该在 X 轴两侧
        各出现，钳在 `±0.5`。⚠ 这里不测"避开 `(-0.2,0.2)`"：Y/Z 用默认的 `lo=0`（没有挖空），
        三轴联合挖空需要三个轴同时落进各自的洞里才算数（见
        `test_box_hollow_cube_excludes_the_joint_center`），单独一根轴有 `lo` 不构成有效
        空腔。"""
        pts = self._positions(shape_block(0, rx=(0.2, 0.5)))
        for p in pts:
            self.assertLessEqual(abs(p.x), 0.5 + 1e-9)
        self.assertTrue(any(p.x > 0.0 for p in pts), "没有粒子落在 +X 一侧")
        self.assertTrue(any(p.x < 0.0 for p in pts), "没有粒子落在 -X 一侧")

    def test_box_negative_min_clamps_to_zero(self):
        """负 `min` 不管多负都当 0——不是"允许负值的独立位置区间"（2026-09-17 实机确认：
        `(-100, .2)` 和 `(0, .2)` 表现完全一样，不会长出一个从 -100 到 .2 的巨型盒子）。"""
        far_negative = self._positions(shape_block(0, rx=(-100.0, 0.2), ry=(-100.0, 0.2),
                                                    rz=(-100.0, 0.2)))
        for p in far_negative:
            for axis in ("x", "y", "z"):
                self.assertLessEqual(abs(getattr(p, axis)), 0.2 + 1e-9,
                                     "%s 轴跑出了 [-0.2, 0.2]，负 min 没有钳到 0" % axis)

    def test_box_hollow_cube_excludes_the_joint_center(self):
        """三轴同取非零 min 时，正中间的小立方体（三轴**同时**落进各自的 `(-lo,lo)`）整个
        是空的——2026-09-17 实机确认：Box 的挖空是三轴联合判定（大盒子减去正中央的小盒子），
        不是逐轴独立钳位（后者会切出 8 个不连通的角落小盒子）。

        ⚠ 只测"不掉进中心空腔"区分不出两种读法——逐轴独立钳位下每根轴单独也**永远不会**
        落进 `(-lo,lo)`，同样能通过那条断言。真正能区分的是**单根轴自己是不是也会落进它
        自己的洞里**（只要别的轴够远、整体没掉进联合空腔就行）：联合读法下会，独立钳位读法
        下永远不会。"""
        pts = self._positions(shape_block(0, rx=(0.1, 0.2), ry=(0.1, 0.2), rz=(0.1, 0.2)))
        for p in pts:
            self.assertFalse(abs(p.x) < 0.1 - 1e-9 and abs(p.y) < 0.1 - 1e-9
                             and abs(p.z) < 0.1 - 1e-9,
                             "粒子 %r 掉进了正中间的空腔" % (p.as_tuple(),))
            for axis in ("x", "y", "z"):
                self.assertLessEqual(abs(getattr(p, axis)), 0.2 + 1e-9)
        self.assertTrue(any(abs(p.x) < 0.1 - 1e-9 for p in pts),
                        "X 轴自己从没落进过 (-0.1,0.1)——像是逐轴独立钳位，不是联合挖空")

    def test_sweep_gating_never_reads_the_neutral_default(self):
        """用不上 `Scale*` 的形状必须走整圈 / 全扫的兜底，**绝不能读那个 `(1.0, 0.0)`**。

        故障模式：照读会得到"起始角 1 弧度、跨度 0"——一个恒定的假角度。语料里 Box 的
        `ScaleHorizontal` 99.2% 是 `(1.0, 0.0)`、Cylinder 的 `ScaleVertical` 92.6% 是
        `(1.0, 0.0)`，那是"本形状用不上"的中性值，不是角度（见 SIM_PORT_PLAN §8.4）。

        ⚠ 这条**直接测 `_sweep()`**，不通过采样结果间接测：Box 分支压根不调 `_sweep()`，
        Sphere 两个字段都在门控名单里——靠采样对比的话这个门控是够不到的，测了个寂寞。
        第一版就是这么写的，注入 bug 之后测试照样全绿才发现。

        `use_ext=True` 固定传给所有调用，专测 `ShapeType` 这一层门控——`UseExtension` 那层
        门控由 `test_sweep_requires_use_extension` 单独测，两层门控揉一起测会互相遮盖。
        """
        from efx_sim.behaviors.emittershape3d import (SHAPE_BOX, SHAPE_CYLINDER,
                                                      SHAPE_SPHERE, _sweep)
        from efx_sim.shapes import FieldView

        f = FieldView({"ScaleHorizontal": _range(1.0, 0.0),
                       "ScaleVertical": _range(1.0, 0.0)}, "EmitterShape3D")

        # 用不上的组合 -> 兜底值，不是 (1.0, 0.0)
        for shape, key in ((SHAPE_BOX, "ScaleHorizontal"), (SHAPE_BOX, "ScaleVertical"),
                           (SHAPE_CYLINDER, "ScaleVertical")):
            start, span = _sweep(f, key, shape, True)
            self.assertNotEqual((start, span), (1.0, 0.0),
                                "%s/%s 读到了中性默认值" % (shape, key))
            self.assertAlmostEqual(abs(span), 2 * math.pi if key == "ScaleHorizontal"
                                   else math.pi, places=6)

        # 用得上的组合 -> 如实读字段
        for shape, key in ((SHAPE_SPHERE, "ScaleHorizontal"), (SHAPE_SPHERE, "ScaleVertical"),
                           (SHAPE_CYLINDER, "ScaleHorizontal")):
            self.assertEqual(_sweep(f, key, shape, True), (1.0, 0.0))

    def test_sweep_requires_use_extension(self):
        """`UseExtension` 关闭时，即使形状真的用得上这个字段，也必须走整圈/全扫兜底——
        2026-09-17 全语料 `condstats ShapeType,UseExtension` 联合分桶确认：`UseExtension=
        false` 时 Sphere/Cylinder 的 `ScaleHorizontal`/`ScaleVertical` 恒为中性/全扫默认值，
        无一例外。"""
        from efx_sim.behaviors.emittershape3d import SHAPE_CYLINDER, SHAPE_SPHERE, _sweep
        from efx_sim.shapes import FieldView

        f = FieldView({"ScaleHorizontal": _range(0.0, math.pi / 2),
                       "ScaleVertical": _range(0.0, math.pi / 4)}, "EmitterShape3D")
        for shape, key in ((SHAPE_SPHERE, "ScaleHorizontal"), (SHAPE_SPHERE, "ScaleVertical"),
                           (SHAPE_CYLINDER, "ScaleHorizontal")):
            start, span = _sweep(f, key, shape, False)
            self.assertAlmostEqual(abs(span), 2 * math.pi if key == "ScaleHorizontal"
                                   else math.pi, places=6,
                                   msg="%s/%s 在 UseExtension=False 时没有走全扫兜底" % (shape, key))

    def test_box_sampling_is_unaffected_by_scale_fields_when_extension_off(self):
        a = self._positions(shape_block(0, sh=(1.0, 0.0), sv=(1.0, 0.0)))
        b = self._positions(shape_block(0, sh=(0.5, 1.0), sv=(0.3, 0.7)))
        self.assertEqual([p.as_tuple() for p in a], [p.as_tuple() for p in b])

    def test_box_taper_scales_x_and_z_independently_when_extension_on(self):
        """`UseExtension` 打开后 `ScaleHorizontal`→X 轴锥度、`ScaleVertical`→Z 轴锥度
        （2026-09-17 实机双向换算测试确认，见 emittershape3d 模块说明）。`(s,r)=(1,1)` 在
        `t=1`（`+hi_y` 端）应该把该轴放大到 2 倍，`(1,0)` 的另一轴保持不变。"""
        block = shape_block(0, rx=(0.0, 1.0), ry=(1.0, 1.0), rz=(0.0, 1.0),
                            sh=(1.0, 1.0), sv=(1.0, 0.0), use_ext=True)
        for p in self._positions(block):
            self.assertLessEqual(abs(p.x), 2.0 + 1e-9, "X 轴没有按 ScaleHorizontal 放大到 2 倍")
            self.assertLessEqual(abs(p.z), 1.0 + 1e-9, "Z 轴不该受 ScaleHorizontal 影响")

    def test_height_taper_is_not_clamped_to_nonnegative(self):
        """负缩放是真实存在的效果（2026-09-17 实机确认，Box 的水平/垂直锥度取负值有对应
        视觉表现），不能钳到 `[0,+∞)`——早先钳过一版，被实机推翻。"""
        from efx_sim.behaviors.emittershape3d import _height_taper
        from efx_sim.shapes import FieldView

        f = FieldView({"ScaleHorizontal": _range(1.0, -3.0)}, "EmitterShape3D")
        scale = _height_taper(f, "ScaleHorizontal", True, 1.0)  # s=1, r=-3, t=1 -> -2
        self.assertAlmostEqual(scale, -2.0, places=6, msg="负缩放被钳成了非负数")

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
        """`RangeY` 是**有符号**的位置偏移，不是半径——语料里真的会是负的。

        夹具直接写 `(min, max)`：`(-0.2, -0.2)` = 高度钉死在 -0.2。
        """
        pts = self._positions(shape_block(2, rx=(0.0, 1.0), ry=(-0.2, -0.2), rz=(0.0, 1.0),
                                          sh=(0.0, 2 * math.pi)))
        for p in pts:
            self.assertAlmostEqual(p.y, -0.2, places=6)

    def test_cylinder_symmetric_rangey_spans_both_sides(self):
        """`(-0.5, 0.5)` 是**以原点为中心对称**的圆柱，不是只在下方的半截。

        这条钉住 `RangeX/Y/Z` 的 `(min, max)` 语义：早先按 `[s, s+r]` 读时，同一份数据会变成
        `[-0.5, 0]`——高度只剩一半、整段偏到原点下方。全语料里这种对称对出现 1584 次
        （`(-0.1,0.1)` `(-0.5,0.5)` `(-1,1)`），读错了这批全错。
        """
        pts = self._positions(shape_block(2, rx=(0.0, 1.0), ry=(-0.5, 0.5), rz=(0.0, 1.0),
                                          sh=(0.0, 2 * math.pi)))
        self.assertTrue(any(p.y > 0.1 for p in pts), "没有粒子落在原点上方")
        self.assertTrue(any(p.y < -0.1 for p in pts), "没有粒子落在原点下方")
        self.assertTrue(all(-0.5001 <= p.y <= 0.5001 for p in pts), "粒子跑出了 [-0.5, 0.5]")

    def test_horizontal_sweep_limits_azimuth(self):
        """半圈扫描时不应该出现在另外半圈里。半圈扫描要 `UseExtension` 打开才生效
        （2026-09-17 实机+全语料确认）。"""
        pts = self._positions(shape_block(2, rx=(1.0, 1.0), ry=(0.0, 0.0), rz=(1.0, 1.0),
                                          sh=(0.0, math.pi), use_ext=True))
        self.assertTrue(all(p.z > -1e-6 for p in pts), "半圈扫描漏到了 z<0")

    def test_outline_is_non_empty_for_every_shape(self):
        for shape in (0, 1, 2):
            sim = Simulator([spawn_block(), life_block(), shape_block(shape)],
                            SimConfig(seed=1))
            self.assertTrue(sim.emitter_outline(), "形状 %d 没有线框" % shape)

    def _outline(self, block, segments=28):
        sim = Simulator([spawn_block(), life_block(), block], SimConfig(seed=1))
        return sim.emitter_outline(segments)

    def test_sphere_outline_has_inner_shell_when_lo_is_nonzero(self):
        """径向幅度取 `[lo, hi]`，lo != 0 时粒子只出现在一层壳里 —— 内层必须画出来。"""
        segs = self._outline(shape_block(1, rx=(0.5, 1.0), ry=(0.5, 1.0), rz=(0.5, 1.0),
                                         sh=(0.0, 2 * math.pi), sv=(-math.pi / 2, math.pi)))
        radii = [math.sqrt(pt.x ** 2 + pt.y ** 2 + pt.z ** 2) for seg in segs for pt in seg]
        self.assertLess(min(radii), 0.6, "没有内层：最小半径应该落在 lo=0.5 附近")
        self.assertGreater(max(radii), 0.9, "没有外层：最大半径应该落在 hi=1.0 附近")

    def test_sphere_outline_connects_the_two_shells(self):
        """内外两层不连起来的话，"壳"在画面上根本不存在——径向棱不是装饰。"""
        segs = self._outline(shape_block(1, rx=(0.5, 1.0), ry=(0.5, 1.0), rz=(0.5, 1.0),
                                         sh=(0.0, 2 * math.pi), sv=(-math.pi / 2, math.pi)))

        def rad(pt):
            return math.sqrt(pt.x ** 2 + pt.y ** 2 + pt.z ** 2)

        self.assertTrue(any(abs(rad(a) - 0.5) < 0.05 and abs(rad(b) - 1.0) < 0.05
                            for a, b in segs), "没有一条棱从内层连到外层")

    def test_box_outline_is_solid_when_min_is_zero(self):
        """`lo=0` 时退化成实心盒子——对称"幅度+随机符号"模型下坐标只会落在 `±hi`。"""
        segs = self._outline(shape_block(0, rx=(0.0, 1.5), ry=(0.0, 1.5), rz=(0.0, 1.5)))
        for seg in segs:
            for pt in seg:
                for v in (pt.x, pt.y, pt.z):
                    self.assertLess(abs(abs(v) - 1.5), 1e-6,
                                    "lo=0 时线框不该有 ±1.5 以外的坐标 %r" % v)
        self.assertEqual(len(segs), 12, "实心 Box 应该正好 12 条棱")

    def test_box_outline_has_inner_shell_when_min_is_nonzero(self):
        """`lo` 非零时线框要有内层（2026-09-17 实机确认的空心方筒，见模块说明）——对称模型下
        内层落在 `±lo`，不再是旧版"Box 恒实心，没有内层"的假设。"""
        segs = self._outline(shape_block(0, rx=(0.5, 1.5), ry=(0.5, 1.5), rz=(0.5, 1.5)))
        coords = [v for seg in segs for pt in seg for v in (pt.x, pt.y, pt.z)]
        self.assertTrue(any(abs(abs(v) - 0.5) < 1e-6 for v in coords), "没有画出内层 (lo=0.5)")
        self.assertTrue(any(abs(abs(v) - 1.5) < 1e-6 for v in coords), "没有画出外层 (hi=1.5)")

    def _particles_fit_outline(self, block, n=120):
        """粒子必须全部落在线框的包围盒里 —— 线框存在的全部意义就是这个。"""
        pts = self._positions(block, n=n)
        flat = [v for seg in self._outline(block) for v in seg]
        self.assertTrue(flat, "线框是空的")
        for axis in ("x", "y", "z"):
            lo = min(getattr(v, axis) for v in flat)
            hi = max(getattr(v, axis) for v in flat)
            for p in pts:
                value = getattr(p, axis)
                self.assertGreaterEqual(value, lo - 1e-6,
                                        "%s 轴上粒子 %.4f 跑到线框 [%.4f, %.4f] 外面"
                                        % (axis, value, lo, hi))
                self.assertLessEqual(value, hi + 1e-6,
                                     "%s 轴上粒子 %.4f 跑到线框 [%.4f, %.4f] 外面"
                                     % (axis, value, lo, hi))

    def test_solid_shape_with_degenerate_sweep_still_shows_the_radial_extent(self):
        """**实心 + 扫描跨度为 0**：粒子沿半径铺成一条从原点射出的线段，线框必须画出
        这条线段，不能只剩最外端一个点。

        径向棱原来只在"空心"（内半径 != 0）时才画，于是这种组合整个塌掉：实测球
        `RangeXYZ=(0,2)`、`ScaleHorizontal=(360, 0)` 时，粒子占 `Y[0, 1.88]`，而线框
        三条零长度线段全挤在 `(0.16, 1.92, -0.54)` 一个点上——"框和粒子对不对得上"
        这个唯一用途直接失效。
        """
        for shape in (1, 2):
            with self.subTest(shape=shape):
                block = shape_block(shape, rx=(0.0, 2.0), ry=(0.0, 2.0), rz=(0.0, 2.0),
                                    sh=(0.0, 0.0), sv=(0.0, 0.0), use_ext=True)
                flat = [v for seg in self._outline(block) for v in seg]
                reach = max(math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2) for v in flat)
                near = min(math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2) for v in flat)
                self.assertGreater(reach, 1.0, "线框没画到外边界")
                self.assertLess(near, 1e-6, "线框没从原点画起（径向棱缺失）")

    def test_particles_stay_inside_the_outline_for_every_sweep(self):
        """整圈 / 半圈 / 零跨度 / 空心 都要成立，不能只在整圈那档对。"""
        TAU, PI = 2 * math.pi, math.pi
        cases = [
            ("球 实心 整球", 1, (0.0, 2.0), (0.0, TAU), (-PI / 2, PI)),
            ("球 实心 零扫描", 1, (0.0, 2.0), (360.0, 0.0), (360.0, 0.0)),
            ("球 实心 90 度扇", 1, (0.0, 2.0), (0.0, PI / 2), (-PI / 2, PI)),
            ("球 空心 整球", 1, (1.0, 2.0), (0.0, TAU), (-PI / 2, PI)),
            ("柱 实心 零扫描", 2, (0.0, 2.0), (0.0, 0.0), (1.0, 0.0)),
            ("柱 实心 90 度扇", 2, (0.0, 2.0), (0.0, PI / 2), (1.0, 0.0)),
            ("柱 空心 整圈", 2, (1.0, 2.0), (0.0, TAU), (1.0, 0.0)),
        ]
        for label, shape, span, sh, sv in cases:
            with self.subTest(case=label):
                self._particles_fit_outline(
                    shape_block(shape, rx=span, ry=span, rz=span, sh=sh, sv=sv, use_ext=True))

    def test_full_solid_shape_gets_no_radial_spokes(self):
        """整圈 + 实心时棱是噪声：外壳自己就是边界。加了棱这条会红。"""
        segs = self._outline(shape_block(1, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                                         sh=(0.0, 2 * math.pi), sv=(-math.pi / 2, math.pi)))
        origin = [seg for seg in segs
                  if min(math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2) for v in seg) < 1e-6]
        self.assertEqual(origin, [], "整圈实心球不该有从原点出发的棱")

    def test_partial_sweep_is_capped_at_both_ends(self):
        """只扫一段时，线框必须在起点和终点封口，且不越界到没有粒子的方位角上。"""
        segs = self._outline(shape_block(2, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                                         sh=(0.0, math.pi / 2), use_ext=True))
        for seg in segs:
            for pt in seg:
                if abs(pt.x) < 1e-9 and abs(pt.z) < 1e-9:
                    continue
                az = math.atan2(pt.z, pt.x)
                self.assertGreaterEqual(az, -1e-6, "线框扫到了 az<0 的地方")
                self.assertLessEqual(az, math.pi / 2 + 1e-6, "线框扫过了终点")
        # 终点那条竖棱必须存在（封口）
        self.assertTrue(any(abs(a.x) < 1e-6 and abs(a.z - 1.0) < 1e-6 and
                            abs(b.x) < 1e-6 and abs(b.z - 1.0) < 1e-6
                            for a, b in segs), "扫描终点没有封口竖棱")

    def test_box_range_divide_snaps_axis_to_discrete_planes(self):
        """`RangeDivideAxis`=X(0)、`RangeDivideNum`=3：X 不再连续取值，钉死在 3 个均分点
        `{-1, 0, 1}` 之一（用户描述，2026-09-17）；Y/Z 不受影响，照旧连续。"""
        pts = self._positions(shape_block(0, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                                          divide_axis=0, divide_num=3), n=200)
        for p in pts:
            self.assertTrue(any(abs(p.x - v) < 1e-6 for v in (-1.0, 0.0, 1.0)),
                            "X=%.4f 不在 3 个均分点上" % p.x)
        self.assertTrue(any(abs(p.x - (-1.0)) < 1e-6 for p in pts), "没有粒子落在 X=-1")
        self.assertTrue(any(abs(p.x - 0.0) < 1e-6 for p in pts), "没有粒子落在 X=0")
        self.assertTrue(any(abs(p.x - 1.0) < 1e-6 for p in pts), "没有粒子落在 X=1")
        self.assertTrue(any(abs(p.y) > 1e-6 for p in pts), "Y 也被钉死了，不该受轴选择影响")

    def test_sphere_range_divide_horizontal_snaps_azimuth(self):
        """`RangeDivideHorizontalNum`=4：方位角钉在 4 个均分点上（不含重复的收尾点，
        `0, π/2, π, 3π/2`），不是连续扫描。"""
        pts = self._positions(shape_block(1, rx=(1.0, 1.0), ry=(0.0, 0.0), rz=(1.0, 1.0),
                                          divide_h=4), n=200)
        expected = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
        for p in pts:
            az = math.atan2(p.z, p.x) % (2 * math.pi)
            self.assertTrue(any(abs(az - e) < 1e-6 for e in expected),
                            "方位角 %.4f 不在 4 个均分点上" % az)

    def test_sphere_range_divide_vertical_degenerates_as_described(self):
        """`RangeDivideVerticalNum`=3：均分点是两极 + 赤道（含两端），两极退化成穿过原点的
        竖线，赤道是 XoZ 平面上的圆盘——用户描述的特例（2026-09-17），不是猜的分支逻辑，是
        `_division_points(periodic=False)` 两端对齐后的自然结果。"""
        pts = self._positions(shape_block(1, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                                          divide_v=3), n=300)
        on_axis = [p for p in pts if abs(p.x) < 1e-6 and abs(p.z) < 1e-6]
        on_equator = [p for p in pts if abs(p.y) < 1e-6]
        self.assertTrue(on_axis, "没有粒子落在穿过原点的竖线上（两极退化）")
        self.assertTrue(on_equator, "没有粒子落在赤道圆盘上")
        self.assertEqual(len(on_axis) + len(on_equator), len(pts),
                         "n=3 时粒子应该不在竖线上就在赤道上，没有第三种位置")

    def test_cylinder_range_divide_vertical_snaps_height(self):
        """`RangeDivideVerticalNum`=3：`RangeY=(-1,1)` 均分成 3 个高度 `{-1,0,1}`（含两端），
        圆柱变成 3 片垂直于 Y 轴的圆环平面。"""
        pts = self._positions(shape_block(2, rx=(1.0, 1.0), ry=(-1.0, 1.0), rz=(1.0, 1.0),
                                          sh=(0.0, 2 * math.pi), divide_v=3), n=200)
        for p in pts:
            self.assertTrue(any(abs(p.y - v) < 1e-6 for v in (-1.0, 0.0, 1.0)),
                            "Y=%.4f 不在 3 个均分点上" % p.y)
        for v in (-1.0, 0.0, 1.0):
            self.assertTrue(any(abs(p.y - v) < 1e-6 for p in pts), "没有粒子落在 Y=%.1f" % v)

    def test_range_divide_outline_reflects_the_discrete_planes(self):
        """`RangeDivide*` 生效时线框也要跟着变——**不能只测"粒子落在包围盒里"**，没分组时
        的老线框（整个实心盒子 / 整个球面）本来就是分组情形的超集，包围盒这条对"线框根本没
        跟着分组变"完全免疫，测了等于没测（CLAUDE.md 的"门禁可以全绿但什么都没测"那条）。
        这里改成直接检查线框上真的出现了分组预期的那个中间位置——没跟着变的老线框会缺这个
        点或者点数对不上。

        Sphere 特意用 n=5（不是 3）：默认没分组时参考纬线正好也是 3 条（起点/中点/终点），
        n=3 的分组会和这个默认参考线数量巧合重合，测不出区别；n=5 才能保证"线框只有 3 条
        纬线"这种回退成默认行为的 bug 会被抓到。
        """
        box_segs = self._outline(shape_block(0, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                                             divide_axis=0, divide_num=3))
        box_xs = {pt.x for seg in box_segs for pt in seg}
        self.assertTrue(any(abs(x) < 1e-6 for x in box_xs),
                        "Box 线框缺 X=0 那个中间切面——没跟着 RangeDivideAxis/Num 变")

        sphere_segs = self._outline(shape_block(1, rx=(0.0, 1.0), ry=(0.0, 1.0), rz=(0.0, 1.0),
                                                 divide_v=5))
        sphere_ys = {round(pt.y, 4) for seg in sphere_segs for pt in seg}
        self.assertTrue(any(abs(y - math.sin(math.pi / 4)) < 1e-3 for y in sphere_ys),
                        "Sphere 线框缺 n=5 才有的中间纬线（y=sin(π/4)）——像是回退成了默认的 3 条参考线")

        cyl_segs = self._outline(shape_block(2, rx=(0.0, 1.0), ry=(-1.0, 1.0), rz=(0.0, 1.0),
                                             sh=(0.0, 2 * math.pi), divide_v=3))
        cyl_ys = {round(pt.y, 4) for seg in cyl_segs for pt in seg}
        self.assertTrue(any(abs(y) < 1e-6 for y in cyl_ys),
                        "Cylinder 线框缺 Y=0 那个中间切面——没跟着 RangeDivideVerticalNum 变")

    def test_outline_follows_local_rotation(self):
        """线框必须和粒子出生位置转一样的角度。

        不转的话，`LocalRotation` 非零时框和粒子对不上——而"框和粒子对不对得上"正是这圈线
        的全部用途，光看"线框非空"完全测不到。
        """
        block = shape_block(0, rx=(0.0, 1.0), ry=(0.0, 0.0), rz=(0.0, 0.0))
        block[1]["LocalRotation"] = {"X": 0.0, "Y": math.pi / 2, "Z": 0.0}
        sim = Simulator([spawn_block(), life_block(), block], SimConfig(seed=1))
        segs = sim.emitter_outline()
        # 绕 Y 转 90 度：+X 方向的那条棱应该整体躺到 Z 轴上去
        self.assertTrue(segs)
        self.assertTrue(all(abs(pt.x) < 1e-6 for seg in segs for pt in seg),
                        "线框还留在 X 轴上，说明 LocalRotation 没作用到线框")
        self.assertTrue(any(abs(pt.z) > 0.5 for seg in segs for pt in seg),
                        "线框没有转到 Z 轴上")

    def test_outline_matches_particle_positions_under_rotation(self):
        """同一套字段下，粒子必须落在线框的包围盒里（两条路共用同一个旋转）。"""
        block = shape_block(0, rx=(0.0, 1.0), ry=(0.0, 0.0), rz=(0.0, 0.0))
        block[1]["LocalRotation"] = {"X": 0.0, "Y": math.pi / 2, "Z": 0.0}
        sim = Simulator([spawn_block(), life_block(), block], SimConfig(seed=1))
        pts = [pt for seg in sim.emitter_outline() for pt in seg]
        lo = [min(pt[i] for pt in pts) for i in range(3)]
        hi = [max(pt[i] for pt in pts) for i in range(3)]
        for p in self._positions(block, n=20):
            for i in range(3):
                self.assertGreaterEqual(p[i], lo[i] - 1e-6)
                self.assertLessEqual(p[i], hi[i] + 1e-6)

    def test_unknown_shape_is_noted(self):
        sim = Simulator([spawn_block(), life_block(), shape_block(7)], SimConfig(seed=1))
        self.assertTrue(any("ShapeType=7" in n for n in sim.em.notes))


# ---------------------------------------------------------------------------
# Velocity3D
# ---------------------------------------------------------------------------

def vel_block(speed=1.0, coef=1.0, gravity=0.0, vtype=0, direction=(0.0, 1.0, 0.0),
              size=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0), spread=0.0):
    return ("Velocity3D", {
        "VelocityType": vtype,
        "DirectionVectorX": _range(direction[0]), "DirectionVectorY": _range(direction[1]),
        "DirectionVectorZ": _range(direction[2]),
        "Size": {"X": size[0], "Y": size[1], "Z": size[2]},
        "Offset": {"X": offset[0], "Y": offset[1], "Z": offset[2]},
        "Speed": _range(speed), "SpeedCoef": _range(coef), "GravityRate": _range(gravity),
        "SpeedDelayFrame": _rangei(0, 0), "GravityDelayFrame": _rangei(0, 0),
        "InheritRate": _range(0.0), "InheritDistance": _range(0.0),
        "Spread": _range(spread),
    })


def vel_box_block():
    """把粒子撒在一个盒子里，好让 `p.spawn_pos` 非零——Normal / Radial 两档全靠它。"""
    return shape_block(0, rx=(-1.0, 1.0), ry=(-1.0, 1.0), rz=(-1.0, 1.0))


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

    def test_positive_gravity_pulls_down_not_up(self):
        """`GravityRate` 全语料非零值正数是负数的 3.6 倍（30078 vs 8341，`fieldstats`
        实测）——"Gravity"这个名字加上"绝大多数样本是正数"，只可能是正值向下，不是向上飘。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=1000),
                         vel_block(speed=0.0, gravity=0.3)], SimConfig(seed=1))
        sim.run(30)
        self.assertLess(sim.em.particles[0].pos.y, 0.0)

    def test_negative_gravity_floats_up(self):
        """少数负值样本对应"漂浮"类特效（烟雾/羽毛），符号应该和正值相反。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=1000),
                         vel_block(speed=0.0, gravity=-0.3)], SimConfig(seed=1))
        sim.run(30)
        self.assertGreater(sim.em.particles[0].pos.y, 0.0)

    def test_unimplemented_types_get_no_velocity_and_a_note(self):
        """`ScreenSpace`(4) / `Max`(5) 全语料零样本，必须进 note 并按无初速处理，
        **不许按 Direction 近似**。"""
        for vtype, name in ((4, "ScreenSpace"), (5, "Max")):
            sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                             vel_block(speed=5.0, vtype=vtype)], SimConfig(seed=1))
            sim.run(10)
            self.assertEqual(sim.em.particles[0].pos.as_tuple(), (0.0, 0.0, 0.0),
                             "%s 档不该有位移" % name)
            self.assertTrue(any(name in n for n in sim.em.notes), "%s 档没记 note" % name)

    def test_normal_spreads_outward_when_size_exceeds_one(self):
        """Normal 档：`V_i = (Size_i-1)*生成坐标_i + Offset_i`。`Size>1` ⇒ 粒子沿自己的
        生成坐标向外飞，离原点越来越远。"""
        sim = Simulator([spawn_block(num=30, loops=1), life_block(keep=1000),
                         vel_box_block(),
                         vel_block(speed=3.0, vtype=1, size=(2.0, 2.0, 2.0))],
                        SimConfig(seed=1))
        sim.run(60)
        self.assertTrue(sim.em.particles)
        for part in sim.em.particles:
            self.assertGreater(part.pos.length(), part.spawn_pos.length() + 1.0,
                               "Size=2 应该把粒子推开，%r 却几乎没动" % (part.pos,))
            # 各向同性的 Size ⇒ 纯径向，方向和生成坐标同侧
            self.assertGreater(part.pos.dot(part.spawn_pos), 0.0)

    def test_normal_converges_when_size_below_one(self):
        """`Size<1` ⇒ `(Size-1)` 变号，粒子向内收拢并**穿过中心到对面**。"""
        sim = Simulator([spawn_block(num=20, loops=1), life_block(keep=1000),
                         vel_box_block(),
                         vel_block(speed=3.0, vtype=1, size=(0.0, 0.0, 0.0))],
                        SimConfig(seed=1))
        sim.run(60)
        self.assertTrue(sim.em.particles)
        for part in sim.em.particles:
            self.assertLess(part.pos.dot(part.spawn_pos), 0.0,
                            "Size=0 应该让粒子朝原点反向飞，%r 却还在同侧" % (part.pos,))

    def test_normal_reads_offset_not_direction_vector(self):
        """`Size` 三轴全 1 时 `(Size-1)` 项消失，方向**只**剩 `Offset`——全体粒子同向。

        这条钉的是一个具体的误读：把 `DirectionVector` 当成 Normal 档的基准方向。全语料
        55.6% 的 Normal 实例把它留在编辑器默认的 `(1,0,0)` 上，照那么读会让一半的发散型
        发射器整体往 +X 漂。这里故意给一个和 `Offset` 正交的 `DirectionVector`，它一旦
        参与进来，粒子就会拐向 +X。
        """
        sim = Simulator([spawn_block(num=10, loops=1), life_block(keep=1000),
                         vel_box_block(),
                         vel_block(speed=2.0, vtype=1, direction=(1.0, 0.0, 0.0),
                                   offset=(0.0, 1.0, 0.0))],
                        SimConfig(seed=1))
        sim.run(60)
        self.assertTrue(sim.em.particles)
        for part in sim.em.particles:
            drift = part.pos - part.spawn_pos
            self.assertAlmostEqual(drift.y, 2.0, delta=0.15)
            self.assertAlmostEqual(drift.x, 0.0, places=9)
            self.assertAlmostEqual(drift.z, 0.0, places=9)

    def test_radial_ignores_direction_size_and_offset(self):
        """Radial 档只看生成坐标，`DirectionVector`/`Size`/`Offset` 一律无效。"""
        a = Simulator([spawn_block(num=15, loops=1), life_block(keep=1000),
                       vel_box_block(), vel_block(speed=2.0, vtype=2)], SimConfig(seed=1))
        b = Simulator([spawn_block(num=15, loops=1), life_block(keep=1000),
                       vel_box_block(),
                       vel_block(speed=2.0, vtype=2, direction=(1.0, 0.0, 0.0),
                                 size=(3.0, 3.0, 3.0), offset=(0.0, -5.0, 0.0))],
                      SimConfig(seed=1))
        a.run(30)
        b.run(30)
        self.assertTrue(a.em.particles)
        self.assertEqual([part.pos.as_tuple() for part in a.em.particles],
                         [part.pos.as_tuple() for part in b.em.particles])
        for part in a.em.particles:
            self.assertGreater(part.pos.dot(part.spawn_pos), 0.0)

    def test_radial_at_the_origin_falls_back_to_random_directions(self):
        """没有 `EmitterShape3D` 时 `spawn_pos` 恒为原点，『向外』无从谈起——退回各向同性
        的随机方向，而不是让粒子原地不动。"""
        sim = Simulator([spawn_block(num=20, loops=1), life_block(keep=1000),
                         vel_block(speed=2.0, vtype=2)], SimConfig(seed=1))
        sim.run(30)
        self.assertTrue(sim.em.particles)
        dirs = {part.pos.normalized().as_tuple() for part in sim.em.particles}
        self.assertGreater(len(dirs), 10, "退化回落应该是随机方向，不是一条线")
        for part in sim.em.particles:
            self.assertAlmostEqual(part.pos.length(), 1.0, delta=0.02)  # 2 m/s x 0.5 s

    def test_spread_stays_inside_the_cone(self):
        """Spread 档：以 `DirectionVector` 为轴、`Spread` 为**全**锥角的随机锥。"""
        half = math.radians(30.0)
        sim = Simulator([spawn_block(num=40, loops=1), life_block(keep=1000),
                         vel_block(speed=2.0, vtype=3, direction=(0.0, 1.0, 0.0),
                                   spread=2.0 * half)],
                        SimConfig(seed=1))
        sim.run(30)
        self.assertTrue(sim.em.particles)
        angles = []
        for part in sim.em.particles:
            d = part.pos.normalized()
            angles.append(math.acos(max(-1.0, min(1.0, d.y))))
            self.assertLessEqual(angles[-1], half + 1e-9,
                                 "%r 跑出了半角 %.0f 度的锥" % (part.pos, math.degrees(half)))
        self.assertGreater(max(angles), 0.5 * half, "锥内取样退化成了一条直线")

    def test_spread_zero_angle_degenerates_to_direction(self):
        """`Spread=0` 应该和 Direction 档完全一致——锥角为零就是一条射线。"""
        a = Simulator([spawn_block(num=5, loops=1), life_block(keep=1000),
                       vel_block(speed=2.0, vtype=3, direction=(0.0, 1.0, 0.0), spread=0.0)],
                      SimConfig(seed=1))
        b = Simulator([spawn_block(num=5, loops=1), life_block(keep=1000),
                       vel_block(speed=2.0, vtype=0, direction=(0.0, 1.0, 0.0))],
                      SimConfig(seed=1))
        a.run(30)
        b.run(30)
        self.assertTrue(a.em.particles)
        for pa, pb in zip(a.em.particles, b.em.particles):
            for ca, cb in zip(pa.pos.as_tuple(), pb.pos.as_tuple()):
                self.assertAlmostEqual(ca, cb, places=9)

    def test_delay_frames_hold_the_particle_still(self):
        block = ("Velocity3D", dict(vel_block(speed=2.0)[1],
                                    SpeedDelayFrame=_rangei(5, 0)))  # 静态 5、不随机
        sim = Simulator([spawn_block(loops=1), life_block(keep=100), block],
                        SimConfig(seed=1))
        sim.run(5)
        self.assertEqual(sim.em.particles[0].pos.y, 0.0)
        sim.step()
        self.assertGreater(sim.em.particles[0].pos.y, 0.0)


def parentoptions_block(use_local=1, rate=1.0, const_frame=0, const_release_frame=0,
                        const_release_rate=0.0):
    return ("ParentOptions", {
        "RelationPos": {"x": 2, "y": 2, "z": 2},
        "RelationRot": {"x": 2, "y": 2, "z": 2},
        "RelationScl": {"x": 0, "y": 0, "z": 0},
        "ParticleUseLocal_re7": 0,
        "ParticleUseLocal": use_local,
        "ConstInheritRate": _range(rate, 0.0),
        "ConstFrame": _rangei(const_frame, 0),
        "ConstReleaseFrame": _rangei(const_release_frame, 0),
        "ConstInheritReleaseRate": const_release_rate,
        "PragUkn1": 0, "PragUkn2": 0, "BoneName": "",
    })


class TestParentOptions(unittest.TestCase):
    """真实故障：一个只有 `Transform3D`+`Transform3DExpression`（把 `LocalPosition.Y`
    逐帧从 -1 动到 0）、没有 `Velocity3D` 的 entry，`em.origin` 逐帧正确变化，但粒子只在
    出生那一刻拷贝了一次 `em.origin`，之后再没人碰它——这里不需要真的接 Expression，
    直接驱动 `em.host_origin` 模拟"发射器自己在动"就能复现同一件事：`em.velocity`
    是驱动源不管来自 Transform3D 的 drift 还是宿主报的 host_origin，对这个 behavior
    是同一回事。"""

    def _run(self, block=None, frames=3):
        blocks = [spawn_block(num=1, interval=0, loops=1), life_block(keep=100)]
        if block is not None:
            blocks.append(block)
        sim = Simulator(blocks, SimConfig(seed=1))
        sim.reset()
        for i in range(frames):
            sim.em.host_origin = Vec3(0.0, -float(i + 1), 0.0)
            sim.step()
        return sim

    def test_particle_use_local_tracks_emitter_motion(self):
        """`ParticleUseLocal=1` 时粒子必须跟上发射器的逐帧位移：这条断言注回"P0 之前"
        （没有这个 behavior）会 FAIL——粒子会停在出生那一刻的 -1.0，不会跟到 -3.0。"""
        sim = self._run(parentoptions_block(use_local=1))
        self.assertAlmostEqual(sim.em.particles[0].pos.y, sim.em.origin.y)
        self.assertAlmostEqual(sim.em.particles[0].pos.y, -3.0)

    def test_use_local_zero_leaves_particle_at_spawn_position(self):
        """开关关掉（或者干脆没有 `ConstInheritRate`≠1 的场景）不该跟——粒子停在出生
        时的发射器位置，不随后续帧变化。"""
        sim = self._run(parentoptions_block(use_local=0))
        self.assertAlmostEqual(sim.em.particles[0].pos.y, -1.0)

    def test_missing_attribute_defaults_to_not_tracking(self):
        """entry 压根没有 `ParentOptions` 属性时，粒子的既有行为（出生后脱手）不能变。"""
        sim = self._run(block=None)
        self.assertAlmostEqual(sim.em.particles[0].pos.y, -1.0)

    def test_partial_inherit_rate_scales_the_tracking(self):
        """`ConstInheritRate=0.5` 应该只跟一半的位移，不是全跟或全不跟。

        出生那一帧的位置本来就等于当时的 origin（`_consume_spawn()` 直接拷贝，不受
        `rate` 影响——那不是"跟踪"来的，是粒子本来就在那儿出生）；`rate` 只缩放出生
        *之后* 每帧的增量：3 帧里出生占 1 帧（-1.0），之后 2 帧每帧位移 -1 只跟一半
        （各 -0.5），合计 -1.0 - 0.5 - 0.5 = -2.0。"""
        sim = self._run(parentoptions_block(use_local=1, rate=0.5))
        self.assertAlmostEqual(sim.em.particles[0].pos.y, -2.0)

    def test_nonzero_const_frame_is_noted_not_silently_simulated(self):
        """`ConstFrame`/`ConstReleaseFrame`/`ConstInheritReleaseRate` 的释放曲线没做，
        非零时必须如实 note，不能假装模拟了。"""
        sim = self._run(parentoptions_block(use_local=1, const_frame=5))
        self.assertTrue(any("ConstFrame" in n for n in sim.em.notes))

    def test_parentoptions_no_longer_unsupported(self):
        sim = Simulator([parentoptions_block()], SimConfig(seed=1))
        self.assertNotIn("ParentOptions", sim.em.unsupported)


# ---------------------------------------------------------------------------
# TypePolygon
# ---------------------------------------------------------------------------

def _is_axis(v, axis):
    """`v` 是不是（在容差内）沿 `axis`（'x'/'y'/'z'/'-z' 等）的单位向量。"""
    want = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0),
           "-z": (0.0, 0.0, -1.0)}[axis]
    return all(abs(a - b) < 0.05 for a, b in zip(v.as_tuple(), want))


class TestPolygon(unittest.TestCase):

    def test_produces_a_plane_with_orthonormal_fixed_axes(self):
        """`axis_u`/`axis_v` 必须是单位正交对，否则面片会被拉斜或缩放走样。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         polygon_block(width=2.0, height=3.0)], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "PLANE")
        self.assertIsNotNone(it.axis_u)
        self.assertIsNotNone(it.axis_v)
        self.assertAlmostEqual(it.axis_u.length(), 1.0, places=6)
        self.assertAlmostEqual(it.axis_v.length(), 1.0, places=6)
        self.assertAlmostEqual(it.axis_u.dot(it.axis_v), 0.0, places=6)
        self.assertAlmostEqual(it.size.x, 2.0, places=6)
        self.assertAlmostEqual(it.size.y, 3.0, places=6)

    def test_does_not_face_camera_like_billboard_does(self):
        """和 `TypeBillboard3D` 的本质区别：不朝相机——`rot` 恒 0，朝向全烘进 axis_u/v。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), polygon_block()],
                        SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.rot, 0.0)

    def test_zero_rotation_faces_the_fixed_rest_normal_regardless_of_up_vector(self):
        """`OrientDirectionUpVector` 不再决定法线——无旋转时法线恒为固定静止轴（game -Z），
        换哪个 up 都一样。2026-09-13 按实机样本纠正过的模型，见 polygon.py 模块说明。"""
        for axis in (0, 1, 2):
            sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                             polygon_block(up_axis=axis)], SimConfig(seed=1))
            sim.step()
            it = sim.build_render()[0]
            n = it.axis_u.cross(it.axis_v).normalized()
            self.assertTrue(_is_axis(n, "-z"),
                            "OrientDirectionUpVector=%d 时法线不是固定静止轴：%r" % (axis, n))

    def test_rotation_x_90_matches_the_real_game_sample(self):
        """回归钉住实机样本：`[029] partical_4 (GpuPolygon)` 实测 RotationX=90°、Y=Z=0、
        OrientDirectionUpVector=1 时，游戏内法线是 game +Y——这条数据本身就是纠正模型的
        依据，绝不能再退回去。"""
        block = ("TypePolygon", dict(polygon_block(up_axis=1)[1],
                                     RotationX=_range(1.5707963267948966)))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        n = it.axis_u.cross(it.axis_v).normalized()
        self.assertTrue(_is_axis(n, "y"), "法线应该是 game +Y，实际 %r" % (n,))

    def test_up_vector_changes_in_plane_basis_not_facing(self):
        """`OrientDirectionUpVector` 只影响 axis_u/axis_v 怎么摆，不影响法线朝向。"""
        normals = []
        bases = []
        for axis in (0, 1, 2):
            sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                             polygon_block(up_axis=axis)], SimConfig(seed=1))
            sim.step()
            it = sim.build_render()[0]
            normals.append(it.axis_u.cross(it.axis_v).normalized().as_tuple())
            bases.append((it.axis_u.as_tuple(), it.axis_v.as_tuple()))
        self.assertEqual(len(set(tuple(round(c, 4) for c in n) for n in normals)), 1,
                         "法线不该跟着 up 向量变")
        self.assertGreater(len(set(bases)), 1, "up 向量不同时横/纵轴应该不一样")


# ---------------------------------------------------------------------------
# TypeRibbonLength
# ---------------------------------------------------------------------------

class TestRibbonLength(unittest.TestCase):

    def test_produces_a_straight_ribbon_of_the_right_length_and_count(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         ribbonlength_block(length=4.0, width=0.5, division=5,
                                            direction=(1.0, 0.0, 0.0))],
                        SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "RIBBON")
        self.assertEqual(len(it.points), 5)
        base = it.points[0][0]
        tip = it.points[-1][0]
        self.assertAlmostEqual((tip - base).length(), 4.0, places=5)
        for q, hw, alpha in it.points:
            self.assertAlmostEqual(hw, 0.25, places=6)   # 0.5 宽的一半
            self.assertEqual(alpha, 1.0)

    def test_base_point_is_the_particle_position(self):
        """P0 假设生成点是尾端（`points[0]`）——`BasingPoint` 语义未定前的默认读法。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         ribbonlength_block()], SimConfig(seed=1))
        sim.step()
        p = sim.em.particles[0]
        it = sim.build_render()[0]
        self.assertEqual(it.points[0][0].as_tuple(), p.pos.as_tuple())

    def test_direction_is_normalized_and_followed(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         ribbonlength_block(length=2.0, direction=(3.0, 0.0, 0.0))],
                        SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        base, tip = it.points[0][0], it.points[-1][0]
        d = tip - base
        self.assertAlmostEqual(d.y, 0.0, places=6)
        self.assertAlmostEqual(d.z, 0.0, places=6)
        self.assertAlmostEqual(d.x, 2.0, places=5)

    def test_gradient_fields_are_noted_not_silently_dropped(self):
        block = ("TypeRibbonLength", dict(ribbonlength_block()[1],
                                          HeadColor={"rgba": 0xFFFFFFFF},
                                          HeadScale=2.0))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block],
                        SimConfig(seed=1))
        sim.step()
        self.assertTrue(any("HeadColor" in n for n in sim.em.notes))
        self.assertTrue(any("HeadScale" in n for n in sim.em.notes))


# ---------------------------------------------------------------------------
# TypePolygonTrail
# ---------------------------------------------------------------------------

class TestPolygonTrail(unittest.TestCase):
    """真实故障：这个渲染体之前完全没有 behavior，退化成一个恒定不动的点（见
    `simulator._has_renderer_body`/`build_render` 的兜底分支）——只要 entry 的
    `Transform3D`/`ParentOptions` 没跟着一起被误诊，这条测试锁的是"这个类型本身现在
    产出真正的 RIBBON 几何"这件事。字段证据极薄（全语料仅 35 个实例），所以断言只覆盖
    结构上确认过的部分（Axis 枚举、Length 数值、颜色），不断言任何猜测字段的效果。"""

    def test_produces_a_ribbon_along_the_given_axis(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         polygontrail_block(length=4.0, axis=0)], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "RIBBON")
        base, tip = it.points[0][0], it.points[-1][0]
        d = tip - base
        self.assertAlmostEqual(d.length(), 4.0, places=5)
        self.assertAlmostEqual(d.y, 0.0, places=6)
        self.assertAlmostEqual(d.z, 0.0, places=6)
        self.assertAlmostEqual(d.x, 4.0, places=5)

    def test_base_point_is_the_particle_position(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         polygontrail_block()], SimConfig(seed=1))
        sim.step()
        p = sim.em.particles[0]
        it = sim.build_render()[0]
        self.assertEqual(it.points[0][0].as_tuple(), p.pos.as_tuple())

    def test_negative_axis_reverses_direction(self):
        """`Axis=5`（-Z）应该往 -Z 走，不是 +Z——枚举方向不能弄反。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         polygontrail_block(length=2.0, axis=5)], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        base, tip = it.points[0][0], it.points[-1][0]
        self.assertAlmostEqual((tip - base).z, -2.0, places=5)

    def test_guessed_fields_are_noted_not_silently_dropped(self):
        """`StretchDistance`/细分数字段没有可用依据，非零时必须 note，不能假装模拟了。"""
        block = ("TypePolygonTrail", dict(polygontrail_block()[1],
                                          StretchDistance=3.0, NumTrailDivision=5))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block],
                        SimConfig(seed=1))
        sim.step()
        self.assertTrue(any("StretchDistance" in n for n in sim.em.notes))
        self.assertTrue(any("NumTrailDivision" in n for n in sim.em.notes))

    def test_no_longer_unsupported(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         polygontrail_block()], SimConfig(seed=1))
        self.assertNotIn("TypePolygonTrail", sim.em.unsupported)


# ---------------------------------------------------------------------------
# TypeRibbonFollow
# ---------------------------------------------------------------------------

class TestRibbonFollow(unittest.TestCase):

    def test_points_follow_the_particles_motion_history(self):
        """核心区别于 `TypeRibbonLength`：几何是粒子逐帧位置的折线，不是解析式算出来的
        直线——挪动方向/速度必须原样体现在 `points` 里，而不是恒定的固定方向。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         vel_block(speed=1.0, direction=(0.0, 1.0, 0.0)),
                         ribbonfollow_block(width=0.5)], SimConfig(seed=1))
        sim.run(5)
        p = sim.em.particles[0]
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "RIBBON")
        self.assertEqual(len(it.points), len(p.trail))
        self.assertGreaterEqual(len(it.points), 2)
        # base（旧）->tip（新）：tip 必须是粒子当前位置，base 必须是它更早的位置。
        self.assertEqual(it.points[-1][0].as_tuple(), p.pos.as_tuple())
        self.assertLess(it.points[0][0].y, it.points[-1][0].y)
        for _pos, hw, alpha in it.points:
            self.assertAlmostEqual(hw, 0.25, places=6)   # 0.5 宽的一半
            self.assertEqual(alpha, 1.0)

    def test_first_frame_degenerates_to_a_two_point_stub_not_a_crash(self):
        """出生当帧只有 1 个轨迹点，不够组成一条带（至少要 base/tip 两端）——必须退化成
        零长度的两点 stub，而不是抛异常或者留一个 None 让上层猜。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         ribbonfollow_block()], SimConfig(seed=1))
        sim.step()
        p = sim.em.particles[0]
        self.assertEqual(len(p.trail), 1)
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "RIBBON")
        self.assertEqual(len(it.points), 2)
        self.assertEqual(it.points[0][0].as_tuple(), it.points[1][0].as_tuple())

    def test_gradient_and_unconfirmed_fields_are_noted_not_silently_dropped(self):
        block = ("TypeRibbonFollow", dict(ribbonfollow_block()[1],
                                          HeadColor={"rgba": 0xFFFFFFFF},
                                          HeadScale=2.0, ShapeDivision=3,
                                          StretchDistance={"X": 1e-45, "Y": 4.0}))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block],
                        SimConfig(seed=1))
        sim.step()
        self.assertTrue(any("HeadColor" in n for n in sim.em.notes))
        self.assertTrue(any("HeadScale" in n for n in sim.em.notes))
        self.assertTrue(any("ShapeDivision" in n for n in sim.em.notes))
        self.assertTrue(any("StretchDistance" in n for n in sim.em.notes))

    def test_follow_flags_common_sentinel_is_not_noted(self):
        """`FollowFlags=3212836864`（按位重解释成 float 是 -1.0）是语料里 94% 的常见档，
        不该被当成"异常配置"刷屏。"""
        block = ("TypeRibbonFollow", dict(ribbonfollow_block()[1], FollowFlags=3212836864))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block],
                        SimConfig(seed=1))
        sim.step()
        self.assertFalse(any("FollowFlags" in n for n in sim.em.notes))

    def test_follow_flags_uncommon_value_is_noted(self):
        block = ("TypeRibbonFollow", dict(ribbonfollow_block()[1], FollowFlags=123456))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block],
                        SimConfig(seed=1))
        sim.step()
        self.assertTrue(any("FollowFlags" in n for n in sim.em.notes))


# ---------------------------------------------------------------------------
# TypeGpuPolygon / TypeGpuRibbonLength
# ---------------------------------------------------------------------------

class TestGpuPolygon(unittest.TestCase):

    def test_matches_polygon_geometry(self):
        """没有 `RotationOrder` 字段、多一个 `ParticleNum`，其余几何/染色和 `TypePolygon`
        一致——这条钉住"确实复用了同一套模型"，不是两份各写各的、慢慢漂开。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         gpupolygon_block(width=2.0, height=3.0)], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "PLANE")
        self.assertAlmostEqual(it.axis_u.dot(it.axis_v), 0.0, places=6)
        self.assertAlmostEqual(it.size.x, 2.0, places=6)
        self.assertAlmostEqual(it.size.y, 3.0, places=6)
        self.assertEqual(it.rot, 0.0)

    def test_rotation_x_90_matches_the_real_game_sample(self):
        """回归钉住实机样本本身：`[029] partical_4 (GpuPolygon)` 实测 RotationX=90°、
        Y=Z=0、OrientDirectionUpVector=1，游戏内法线是 game +Y。"""
        block = ("TypeGpuPolygon", dict(gpupolygon_block(up_axis=1)[1],
                                        RotationX=_range(1.5707963267948966)))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        n = it.axis_u.cross(it.axis_v).normalized()
        self.assertTrue(_is_axis(n, "y"), "法线应该是 game +Y，实际 %r" % (n,))

    def test_particle_num_is_noted_not_treated_as_a_multiplier(self):
        """`ParticleNum` 语料实测像 GPU 侧旁路参数，不是逐粒子倍数——必须只 note，
        不能让它影响任何几何/数量。"""
        block = ("TypeGpuPolygon", dict(gpupolygon_block()[1], ParticleNum=24))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block],
                        SimConfig(seed=1))
        sim.step()
        items = sim.build_render()
        self.assertEqual(len(items), 1, "ParticleNum 非 0 不该让一个粒子画出好几份")
        self.assertTrue(any("ParticleNum" in n for n in sim.em.notes))


class TestGpuRibbonLength(unittest.TestCase):

    def test_matches_ribbonlength_geometry(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         gpuribbonlength_block(length=4.0, width=0.5, division=5,
                                               direction=(1.0, 0.0, 0.0))],
                        SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "RIBBON")
        self.assertEqual(len(it.points), 5)
        base, tip = it.points[0][0], it.points[-1][0]
        self.assertAlmostEqual((tip - base).length(), 4.0, places=5)

    def test_particle_num_is_noted_not_treated_as_a_multiplier(self):
        """语料里这个字段能到几千上万（GPU 缓冲区容量的量级），必须确认它不会被当成
        "画这么多份" 冲爆预览的粒子数上限。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         gpuribbonlength_block()], SimConfig(seed=1))
        sim.step()
        items = sim.build_render()
        self.assertEqual(len(items), 1)
        self.assertTrue(any("ParticleNum" in n for n in sim.em.notes))


# ---------------------------------------------------------------------------
# TypeMeshV2
# ---------------------------------------------------------------------------

class TestMeshV2(unittest.TestCase):

    def test_produces_a_mesh_item_with_transform_and_color(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         meshv2_block(scale=(2.0, 3.0, 4.0), rotation=(0.1, 0.2, 0.3),
                                     rotation_order=1)], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        self.assertEqual(it.kind, "MESH")
        self.assertAlmostEqual(it.size.x, 2.0, places=6)
        self.assertAlmostEqual(it.size.y, 3.0, places=6)
        self.assertAlmostEqual(it.size.z, 4.0, places=6)
        self.assertEqual(it.extra["rot"], (0.1, 0.2, 0.3))
        self.assertEqual(it.extra["rot_order"], 1)

    def test_color_rate_and_emissive_rate_are_applied(self):
        # rgba 打包低字节 R，高字节 A（见 `_unpack_rgba`）：0xFF0000FF = 纯红不透明，
        # 0x00FF0000 = 纯蓝（自发光不看 alpha）。
        block = ("TypeMeshV2", dict(meshv2_block(rgba=0xFF0000FF,
                                                 emissive_rgba=0x00FF0000)[1],
                                    ColorRate=2.0, EmissiveRate=0.5))
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), block], SimConfig(seed=1))
        sim.step()
        it = sim.build_render()[0]
        # ColorRate=2 应该把红色通道翻倍（乘法夹在导出颜色阶段前，允许 >1）
        self.assertAlmostEqual(it.color[0], 2.0, places=5)
        er, eg, eb = it.extra["emissive"]
        self.assertAlmostEqual(er, 0.0, places=5)
        self.assertAlmostEqual(eb, 0.5, places=5)   # 蓝色自发光 * 0.5

    def test_max_parts_num_is_noted_not_simulated(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         meshv2_block(max_parts=6)], SimConfig(seed=1))
        sim.step()
        sim.build_render()
        self.assertTrue(any("MaxPartsNum" in n for n in sim.em.notes))

    def test_unbound_falls_back_to_mesh_kind_not_point(self):
        """P0 没有 Blender 场景可绑定网格，这里只确认核心层老实产出 'MESH'——
        胶水层（sim_preview.py）负责在没有绑定对象时画占位框，不是核心层的事。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), meshv2_block()],
                        SimConfig(seed=1))
        sim.step()
        self.assertEqual(sim.build_render()[0].kind, "MESH")


# ---------------------------------------------------------------------------
# ScaleAnim / ScaleAnimDelayFrame
# ---------------------------------------------------------------------------

class TestScaleAnim(unittest.TestCase):

    def test_axis_add_accumulates_each_frame(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         scaleanim_block(axis_add=(-0.1, 0.0, 0.0),
                                         axis_coef=(1.0, 1.0, 1.0))],
                        SimConfig(seed=1))
        sim.run(10)
        p = sim.em.particles[0]
        self.assertAlmostEqual(p.scale.x, 1.0 - 0.1 * 10, places=5)
        self.assertAlmostEqual(p.scale.y, 1.0, places=5)

    def test_coef_decays_the_increment_not_the_scale_itself(self):
        """`AddCoef` 衰减的是"每帧加多少"这个量本身，不是直接乘 scale——
        故障模式：如果错当成"scale 本身每帧乘 coef"，量级会完全不对。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         scaleanim_block(axis_add=(0.1, 0.0, 0.0),
                                         axis_coef=(0.5, 1.0, 1.0))],
                        SimConfig(seed=1))
        sim.run(3)
        p = sim.em.particles[0]
        # 第1帧 scale.x += 0.1（增量随后变 0.05）；第2帧 += 0.05（变 0.025）；第3帧 += 0.025
        expected = 1.0 + 0.1 + 0.05 + 0.025
        self.assertAlmostEqual(p.scale.x, expected, places=5)

    def test_uniform_group_applies_to_all_three_axes(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         scaleanim_block(scalar_add=0.2, scalar_coef=1.0)], SimConfig(seed=1))
        sim.run(5)
        p = sim.em.particles[0]
        self.assertAlmostEqual(p.scale.x, 1.0 + 0.2 * 5, places=5)
        self.assertAlmostEqual(p.scale.y, 1.0 + 0.2 * 5, places=5)
        self.assertAlmostEqual(p.scale.z, 1.0 + 0.2 * 5, places=5)

    def test_size_delay_frame_only_gates_the_axis_group(self):
        """`SizeDelayFrame` 只挡逐轴组，不影响整体组（同上游 `animUpdateStart` 的先例）。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         scaleanim_block(scalar_add=0.1, axis_add=(0.3, 0.0, 0.0),
                                         size_delay=5)], SimConfig(seed=1))
        sim.run(3)
        p = sim.em.particles[0]
        self.assertAlmostEqual(p.scale.x, 1.0 + 0.1 * 3, places=5,
                               msg="逐轴组还没到 SizeDelayFrame，不该生效")
        sim.run(3)
        self.assertGreater(p.scale.x, 1.0 + 0.1 * 6, "逐轴组该生效了")

    def test_scale_anim_delay_frame_gates_both_groups(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         scaleanim_block(scalar_add=0.2), scaleanim_delay_block(frame_delay=4)],
                        SimConfig(seed=1))
        sim.run(3)
        p = sim.em.particles[0]
        self.assertAlmostEqual(p.scale.x, 1.0, places=5,
                               msg="ScaleAnimDelayFrame 期间两组都不该生效")
        sim.run(3)
        self.assertGreater(p.scale.x, 1.0)

    def test_scale_anim_delay_frame_unkn2_is_noted(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         scaleanim_block(scalar_add=0.1), scaleanim_delay_block(unkn2=7)],
                        SimConfig(seed=1))
        self.assertTrue(any("unkn2" in n for n in sim.em.notes))

    def test_scale_anim_delay_frame_alone_is_not_reported_as_unsupported(self):
        """伴生属性没有自己的钩子，但注册过，不该被误报成'未模拟'——它的数据确实被
        `ScaleAnim` 读了，只是这里单独测的时候 `ScaleAnim` 没出现。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         scaleanim_delay_block(frame_delay=3)], SimConfig(seed=1))
        self.assertNotIn("ScaleAnimDelayFrame", sim.em.unsupported)


# ---------------------------------------------------------------------------
# RotateAnim / RotateAnimDelayFrame
# ---------------------------------------------------------------------------

class TestRotateAnim(unittest.TestCase):

    def test_add_accumulates_and_coef_decays_the_increment(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         rotateanim_block(add=(0.1, 0.0, 0.0), coef=(0.5, 1.0, 1.0))],
                        SimConfig(seed=1))
        sim.run(3)
        p = sim.em.particles[0]
        expected = 0.1 + 0.05 + 0.025   # 同 ScaleAnim 的衰减模型，p.rot 从 0 起
        self.assertAlmostEqual(p.rot.x, expected, places=5)
        self.assertAlmostEqual(p.rot.y, 0.0, places=6)

    def test_coef_zero_is_treated_as_one_not_literal_zero(self):
        """`RotationCoef{X,Y,Z}`=0 是"未设置"哨兵值，实机按 1（不衰减）处理——用户拿真机
        对比过 0（恒速转到底）和 0.1（几帧内迅速停转），确认字面乘 0 的读法是错的。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         rotateanim_block(add=(0.1, 0.0, 0.0), coef=(0.0, 0.0, 0.0))],
                        SimConfig(seed=1))
        sim.run(5)
        p = sim.em.particles[0]
        self.assertAlmostEqual(p.rot.x, 0.1 * 5, places=5)   # 匀速：5 帧各加一次 0.1，没有衰减

    def test_rotation_delay_frame_gates_start(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         rotateanim_block(add=(0.2, 0.0, 0.0), delay=4)], SimConfig(seed=1))
        sim.run(3)
        self.assertEqual(sim.em.particles[0].rot.x, 0.0)
        sim.run(3)
        self.assertGreater(sim.em.particles[0].rot.x, 0.0)

    def test_rotate_anim_delay_frame_gates_start(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         rotateanim_block(add=(0.2, 0.0, 0.0)),
                         rotateanim_delay_block(frame_delay=4)], SimConfig(seed=1))
        sim.run(3)
        self.assertEqual(sim.em.particles[0].rot.x, 0.0)
        sim.run(3)
        self.assertGreater(sim.em.particles[0].rot.x, 0.0)

    def test_flags_and_unkn2_are_noted(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         rotateanim_block(flags=3), rotateanim_delay_block(unkn2=5)],
                        SimConfig(seed=1))
        self.assertTrue(any("RotateAnim.Flags" in n for n in sim.em.notes))
        self.assertTrue(any("unkn2" in n for n in sim.em.notes))

    def test_delay_frame_alone_is_not_reported_as_unsupported(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         rotateanim_delay_block(frame_delay=3)], SimConfig(seed=1))
        self.assertNotIn("RotateAnimDelayFrame", sim.em.unsupported)

    def test_billboard_gets_a_note_instead_of_a_silent_no_op(self):
        """`TypeBillboard3D` 没接 `p.rot`（缺相机空间标定）——必须明说，不能既不转
        也不吭声，那样用户会以为是模拟坏了而不是"这个没做"。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10),
                         rotateanim_block(add=(0.1, 0.0, 0.0)), billboard_block()],
                        SimConfig(seed=1))
        self.assertTrue(any("TypeBillboard3D" in n for n in sim.em.notes))

    def test_polygon_normal_rotates_with_accumulated_rot(self):
        """`TypePolygon` 接了 `p.rot`：法线应该随着累积的旋转改变，不是钉死在
        spawn 那一刻的静态朝向上。

        ⚠ 不能用绕 Z 转：`_REST_NORMAL` 就是 Z 轴（game -Z），绕自己转是零效果——
        同一个坑（"选中的那根轴自己转自己"）当初就是这么把 polygon.py 的朝向模型
        坑穿的，这条测试专门避开它，走 X 轴。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         rotateanim_block(add=(0.5, 0.0, 0.0)), polygon_block()],
                        SimConfig(seed=1))
        sim.step()
        first = sim.build_render()[0]
        n0 = first.axis_u.cross(first.axis_v).normalized()
        sim.run(5)
        later = sim.build_render()[0]
        n1 = later.axis_u.cross(later.axis_v).normalized()
        self.assertGreater((n1 - n0).length(), 0.05, "法线没有随 p.rot 转动")

    def test_meshv2_rot_extra_includes_accumulated_rot(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=100),
                         rotateanim_block(add=(0.1, 0.0, 0.0)), meshv2_block()],
                        SimConfig(seed=1))
        sim.run(3)
        it = sim.build_render()[0]
        self.assertGreater(it.extra["rot"][0], 0.0)


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
                         ("TypeMesh", {})], SimConfig(seed=1))
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


class TestSuggestedDuration(unittest.TestCase):
    """真实故障（2026-09-17，用户场景里唯一的 entry）：`Spawn.LoopNum=0`（无限循环）
    + `Life.Flags=1`（持续性）+ 一条**只有 1 帧**的 `.uvs`。

    前两个 behavior 的『无限』当时是用返回 `0` 表达的，而 `suggested_duration()` 对全部
    提示取 max 时把 `0` 当成『没有意见』——全场唯一的正数提示就是 `UVSequence` 的『一轮
    1 帧』，播放长度被定成 **1 帧**。`sim_preview.tick()` 于是每个 tick 都在第 0 帧撞线、
    重置回第 -1 帧：面板上帧数在 -1 上不停跳，视口里一个粒子都看不到。

    ⚠ 下面每条**只留一个致因**。用原始场景（无限 + 无限 + 1 帧序列）写测试是空跑的：
    两个修复互相遮蔽——`UVSequence` 改成返回 0 之后，就算『无限』的区分整个失效，
    `best` 也是 0、照样落回 default 180。注回任一 bug 都还是绿的。
    """

    #: 一条 4 帧、1 倍速的序列 —— `duration_hint()` 会报 4，短到足以暴露『无限被压掉』。
    SHORT_CYCLE = 4

    def _short_uvs(self):
        return uvs_block(speed=1.0), _resources(n_frames=self.SHORT_CYCLE)

    def test_infinite_spawn_alone_beats_a_short_cycle(self):
        """只有 `Spawn` 说无限（`Life` 不在场）——播放长度不能被 4 帧的序列周期定死。"""
        uvs, res = self._short_uvs()
        sim = Simulator([spawn_block(loops=0), uvs], SimConfig(seed=1), resources=res)
        self.assertEqual(sim.suggested_duration(), 180)

    def test_continuous_life_alone_beats_a_short_cycle(self):
        """只有 `Life` 说持续性（`Spawn` 是有限的、而且提示比序列还短）。"""
        uvs, res = self._short_uvs()
        sim = Simulator([spawn_block(loops=1), life_block(flags=1), uvs],
                        SimConfig(seed=1), resources=res)
        self.assertEqual(sim.suggested_duration(), 180)

    def test_a_one_frame_sequence_has_no_cycle_to_report(self):
        """1 帧的序列和 `PB_START_ONLY` 是一回事：画面根本不变，没有『一轮』可言。

        这条单独钉 `UVSequence.duration_hint()`，**不经过** `suggested_duration()`
        ——经过它的话『无限』那条修复会把结果一起兜住，注回 bug 也是绿的。
        """
        sim = Simulator([spawn_block(loops=1), uvs_block()], SimConfig(seed=1),
                        resources=_resources(n_frames=1))
        hint = dict((b.type_name, b.behavior.duration_hint(sim.em)) for b in sim.bound)
        self.assertEqual(hint["UVSequence"], 0)

    def test_a_real_sequence_still_reports_its_cycle(self):
        """反例对照：多帧序列照旧报『一轮多长』，这条修复没有把整个钩子关掉。"""
        sim = Simulator([spawn_block(loops=1), uvs_block(speed=1.0)], SimConfig(seed=1),
                        resources=_resources(n_frames=8))
        hint = dict((b.type_name, b.behavior.duration_hint(sim.em)) for b in sim.bound)
        self.assertEqual(hint["UVSequence"], 8)

    def test_infinite_still_loses_to_a_longer_finite_hint(self):
        """『无限』只保证**至少**放满默认长度，不该把更长的有限提示压掉——否则一个寿命
        600 帧的持续性发射器会被截成 180 帧。（`max(best, default)` 写成 `default` 就红。）"""
        sim = Simulator([spawn_block(loops=0),
                         life_block(appear=200, keep=200, vanish=200)], SimConfig(seed=1))
        self.assertEqual(sim.suggested_duration(), 600)

    def test_all_finite_keeps_the_max(self):
        """全都有限时行为不变：取最大值。"""
        sim = Simulator([spawn_block(loops=3, interval=10),
                         life_block(appear=0, keep=45, vanish=0)], SimConfig(seed=1))
        self.assertEqual(sim.suggested_duration(), 45)

    def test_nobody_has_an_opinion_falls_back_to_the_default(self):
        sim = Simulator([shape_block(0)], SimConfig(seed=1))
        self.assertEqual(sim.suggested_duration(), 180)


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

    def test_ribbon_items_are_not_textured(self):
        """真实故障：`TypeRibbonFollow` 同一个 entry 上如果也有 `UVSequence`
        （常见——序列帧贴图 + 轨迹条带经常配对），`build_render()` 会不分青红皂白地把
        `tex_key`/`uv_rect` 写上去。`_collect_ribbon()` 对 RIBBON 恒写 `uv=(0,0)`，
        于是整条带被按贴图那个固定角的像素采样成同一个颜色——贴图那个角常常是透明的，
        看起来就是"这个渲染体完全不出现"，几何/颜色/透明度全对，唯独看不见。这条断言
        钉住"RIBBON 的 tex_key/uv_rect 必须保持 UVSequence 介入前的原样"。"""
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), ribbonfollow_block(),
             uvs_block(seq=1, lo=0, hi=1)], 3, _resources())
        for it in items:
            self.assertEqual(it.kind, "RIBBON")
            self.assertIsNone(it.tex_key)
            self.assertEqual(it.uv_rect, (0.0, 0.0, 1.0, 1.0))

    def test_skipping_ribbon_is_noted(self):
        sim, items = self._items(
            [spawn_block(loops=1), life_block(keep=100), ribbonfollow_block(),
             uvs_block(seq=1, lo=0, hi=1)], 1, _resources())
        self.assertTrue(any("RIBBON" in n for n in sim.em.notes))

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


# ---------------------------------------------------------------------------
# TypeNoDraw
# ---------------------------------------------------------------------------

def nodraw_block():
    return ("TypeNoDraw", {"Flags": 0, "Color": {"rgba": 0xFFFFFFFF},
                           "ColorRange": {"rgba": 0xFFFFFFFF}, "RotationOrder": 0,
                           "Rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                           "RotationRandom": {"x": 0.0, "y": 0.0, "z": 0.0},
                           "Size": {"x": 1.0, "y": 1.0, "z": 1.0},
                           "SizeRandom": {"x": 0.0, "y": 0.0, "z": 0.0},
                           "unkn14": 0.0, "unkn15": 0.0})


class TestNoDraw(unittest.TestCase):
    """真实故障：没有这个 behavior 之前，`TypeNoDraw` 会落进"有渲染主体、只是没实现"的
    兜底分支，被画成一个假的退化点——它的名字本身就是"不画"，这是凭空捏造画面。"""

    def test_produces_no_render_item(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), nodraw_block()],
                        SimConfig(seed=1))
        sim.step()
        self.assertEqual(sim.build_render(), [])

    def test_has_renderer_body_is_still_true(self):
        """区别于"没有渲染主体"（`test_no_render_body_means_no_items`）：这里是有主体、
        主体自己说不画，两条路径都通向"不画"，但走的分支不一样，用 `unsupported` 反证——
        `TypeNoDraw` 已注册，不该出现在未模拟属性列表里。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), nodraw_block()],
                        SimConfig(seed=1))
        sim.step()
        self.assertNotIn("TypeNoDraw", sim.em.unsupported)


# ---------------------------------------------------------------------------
# PtLife
# ---------------------------------------------------------------------------

def ptlife_block(status=4, action_index=0, flags=0):
    return ("PtLife", {"Flags": flags, "Status": status, "ActionIndex": action_index})


class TestPtLife(unittest.TestCase):

    def test_death_summons_action_and_notes_it(self):
        """故障模式：`PtLife` 完全没实现的话，粒子死亡时召唤 Action 这件事在预览里
        彻彻底底没有任何反应，用户没法知道这个 Entry 其实还挂着一个召唤链。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=2), ptlife_block(
            status=4, action_index=7)], SimConfig(seed=1))
        sim.run(2)
        self.assertEqual(len(sim.em.particles), 1)
        sim.step()   # 第 3 帧粒子死亡（keep=2：age 0,1 活着，age 2 判死）
        self.assertEqual(len(sim.em.particles), 0)
        self.assertEqual(len(sim.em.spawn_requests), 1)
        req = sim.em.spawn_requests[0]
        self.assertEqual(req.kind, "action")
        self.assertEqual(req.target, 7)
        self.assertTrue(any("召唤 Action #7" in n for n in sim.em.notes))

    def test_initialize_status_summons_on_spawn(self):
        """真实样本（`11_it03_005.efx.5571972` 的 `0_PT` entry）走的正是这一档：一个只有
        `TypeNoDraw`+`Spawn`+`Life`+`PtLife` 的纯逻辑 entry，一出生就召唤 Action——
        "死亡时召唤"不是唯一常见形态，`Status=0` 必须在粒子出生的当帧就触发，不能等死亡。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), ptlife_block(
            status=0, action_index=7)], SimConfig(seed=1))
        sim.step()
        self.assertEqual(len(sim.em.particles), 1, "生成时触发不该连粒子本身都不生成")
        self.assertEqual(len(sim.em.spawn_requests), 1)
        req = sim.em.spawn_requests[0]
        self.assertEqual(req.kind, "action")
        self.assertEqual(req.target, 7)
        self.assertTrue(any("召唤 Action #7" in n for n in sim.em.notes))

    def test_unsupported_status_does_not_summon_and_is_noted(self):
        """`Status=1`（淡入时）本仓没实现（需要跟踪 `Life` 的阶段迁移），必须如实 note，
        不能悄悄按"生成时"或"死亡时"触发糊过去（那会在错误的时间点召唤 Action）。"""
        sim = Simulator([spawn_block(loops=1), life_block(keep=2), ptlife_block(
            status=1, action_index=7)], SimConfig(seed=1))
        sim.run(3)
        self.assertEqual(sim.em.spawn_requests, [])
        self.assertTrue(any("Status=1" in n and "不会召唤 Action" in n
                            for n in sim.em.notes), sim.em.notes)

    def test_terminate_status_does_not_emit_stage_note(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=2), ptlife_block(
            status=4, action_index=1)], SimConfig(seed=1))
        sim.run(3)
        self.assertFalse(any("不会召唤 Action" in n for n in sim.em.notes), sim.em.notes)

    def test_initialize_status_does_not_emit_stage_note(self):
        sim = Simulator([spawn_block(loops=1), life_block(keep=10), ptlife_block(
            status=0, action_index=1)], SimConfig(seed=1))
        sim.step()
        self.assertFalse(any("不会召唤 Action" in n for n in sim.em.notes), sim.em.notes)
