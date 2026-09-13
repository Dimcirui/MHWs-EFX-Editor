# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/emittershape3d.py —— `EmitterShape3D`（生成位置）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `EmitterShape3D`，TypeID 97）：

    RangeX / RangeY / RangeZ    Range    逐轴的生成区间
    ShapeType                   enum     0=Box 1=Sphere 2=Cylinder（`Shape3DType`，只有三个）
    ScaleHorizontal             Range    **(起始角, 扫描跨度)**，弧度 —— 球 + 圆柱用
    ScaleVertical               Range    同上 —— **只有球用**
    LocalRotation + RotationOrder        生成形状自身的整体旋转（**弧度**）
    RangeDivide* / RotationCorrect / DivideEquidistant* / UseExtension   P0 不消费

`Scale*` 是 (起始角, 跨度)，并且按形状门控（全语料坐实）
------------------------------------------------------
`EfxBridge condstats` 按 `ShapeType` 分桶，62477 个实例：

    Box       ScaleHorizontal (1.0, 0.0) 99.2/98.4%   ScaleVertical (1.0, 0.0) 99.8/99.2%
    Sphere    ScaleHorizontal (0.0, 2π)  96.7/91.6%   ScaleVertical (-π/2, π)  63.4/61.1%
    Cylinder  ScaleHorizontal (0.0, 2π)  90.3/79.0%   ScaleVertical (1.0, 0.0) 92.6/88.1%

`(0, 2π)` = 水平全向、`(-π/2, π)` = 垂直全扫；`(1.0, 0.0)` 是**"本形状用不上"的中性默认值，
不是角度**——所以 Box 两个都不能读、圆柱不能读 ScaleVertical，照读会得到一个 1 弧度的假
起始角。门控与上游 EFX-Editor 依特效教程给的说法逐字吻合（"横向只有球/圆柱用、纵向只有
球用"）。数据见 docs/SIM_PORT_PLAN.md §8.4。

区间读法：`SimConfig.es3d_range_mode`
-------------------------------------
`Range{s,r}` 默认按 (静态值, 随机量) 读 -> 区间 `[s, s+r]`；`min_max` 按 `[s, r]` 读。
**两种读法在 `r` 为正的厚度时数值接近**（上游那边依教程给的"内边界 + 厚度"就等价于前者），
但语料里 `r` 会出现负值（`RangeY = {s:-0.2, r:-0.2}`），那批样本 `min_max` 更自洽。
P0 默认 `static_random`，标定时拖开关对拍。

⚠ 逐轴的区间是**有符号位置偏移**，不是"半径"——`RangeY` 真的会是负的。所以 Box 直接按
`U(lo, hi)` 逐轴取，**不做 ± 对称翻转**；球/圆柱把它当成沿该轴的径向幅度。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import math

from ..registry import Behavior, register
from ..stages import FORCE
from ..state import Vec3
from ..vecmath import rotate_euler, rotation_order_name, sweep_fraction

TYPE_NAME = "EmitterShape3D"

SHAPE_BOX = 0
SHAPE_SPHERE = 1
SHAPE_CYLINDER = 2

SHAPE_NAMES = {SHAPE_BOX: "Box", SHAPE_SPHERE: "Sphere", SHAPE_CYLINDER: "Cylinder"}

#: 哪些形状真的用 `ScaleHorizontal` / `ScaleVertical`（见模块说明的分桶数据）
_USES_SCALE_H = frozenset({SHAPE_SPHERE, SHAPE_CYLINDER})
_USES_SCALE_V = frozenset({SHAPE_SPHERE})

#: P0 不消费的字段 -> 默认值。非默认就 note 一条。
_UNUSED_INT_FIELDS = (
    ("RangeDivideNum", 0),
    ("RangeDivideHorizontalNum", 0),
    ("RangeDivideVerticalNum", 0),
    ("RotationCorrect", 0),
)
_UNUSED_BOOL_FIELDS = (
    "DivideEquidistant", "DivideEquidistantCalcOuterCurveData",
    "DivideEquidistantRecalcEveryFrameData", "UseExtension",
)


@register(TYPE_NAME)
class EmitterShape3D(Behavior):
    """决定粒子的出生位置。跑在 spawn 钩子里，阶段随便挑一个（不参与逐帧 step），
    但 `ORDER` 要小于 `Velocity3D`——后者的初速方向要读 `p.spawn_pos`。"""

    STAGE = FORCE
    ORDER = 10

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        shape = f.i("ShapeType")
        if shape not in SHAPE_NAMES:
            em.note("EmitterShape3D.ShapeType=%d 不是已知的三个形状之一，按 Box 处理" % shape)
        for key, default in _UNUSED_INT_FIELDS:
            if f.has(key) and f.i(key) != default:
                em.note("EmitterShape3D.%s=%d 未参与模拟" % (key, f.i(key)))
        for key in _UNUSED_BOOL_FIELDS:
            if f.has(key) and f.b(key):
                em.note("EmitterShape3D.%s 已开启但未参与模拟" % key)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        shape = f.i("ShapeType")
        rx = _axis_range(f, "RangeX", em.config)
        ry = _axis_range(f, "RangeY", em.config)
        rz = _axis_range(f, "RangeZ", em.config)

        if shape == SHAPE_SPHERE:
            offset = self._sample_sphere(f, rng, rx, ry, rz)
        elif shape == SHAPE_CYLINDER:
            offset = self._sample_cylinder(f, rng, rx, ry, rz)
        else:
            offset = Vec3(_pick(rng, rx), _pick(rng, ry), _pick(rng, rz))

        offset = _apply_local_rotation(f, offset, em.config)
        p.spawn_pos = offset
        p.pos = em.origin + offset

    # -- 逐形状采样 ----------------------------------------------------------
    @staticmethod
    def _sample_sphere(f, rng, rx, ry, rz):
        az = sweep_fraction(rng, *_sweep(f, "ScaleHorizontal", SHAPE_SPHERE))
        polar = sweep_fraction(rng, *_sweep(f, "ScaleVertical", SHAPE_SPHERE))
        cy = math.sin(polar)
        cr = math.cos(polar)
        # 逐轴幅度独立取 -> 椭球也能表达；方向分量和幅度分开乘，符号交给方向
        return Vec3(math.cos(az) * cr * _pick(rng, rx),
                    cy * _pick(rng, ry),
                    math.sin(az) * cr * _pick(rng, rz))

    @staticmethod
    def _sample_cylinder(f, rng, rx, ry, rz):
        az = sweep_fraction(rng, *_sweep(f, "ScaleHorizontal", SHAPE_CYLINDER))
        # XZ 是横截面（径向），Y 是高度（直接取区间，可以是负的）
        return Vec3(math.cos(az) * _pick(rng, rx),
                    _pick(rng, ry),
                    math.sin(az) * _pick(rng, rz))

    # -- 线框（给预览画生成区域）--------------------------------------------
    def outline(self, em, segments=28):
        """返回成对的点 `[(a, b), ...]`，与粒子同一坐标空间（游戏系，相对发射器原点未加）。

        画的是**外边界**（区间的 hi 端）。P0 的验收标准之一就是"看到粒子按形状分布"，
        有这圈线框才看得出分布对不对。
        """
        f = em.f(TYPE_NAME)
        if f is None:
            return []
        cfg = em.config
        shape = f.i("ShapeType")
        rx = _axis_range(f, "RangeX", cfg)
        ry = _axis_range(f, "RangeY", cfg)
        rz = _axis_range(f, "RangeZ", cfg)
        n = max(6, int(segments))

        if shape == SHAPE_SPHERE:
            start, span = _sweep(f, "ScaleHorizontal", shape)
            pts = [_ring(rx[1], rz[1], start + span * i / n, ry_val=0.0) for i in range(n + 1)]
            segs = list(zip(pts[:-1], pts[1:]))
            # 再加一圈子午线，光有赤道看不出是球
            for i in range(n):
                a = -math.pi / 2 + math.pi * i / n
                b = -math.pi / 2 + math.pi * (i + 1) / n
                segs.append((Vec3(math.cos(a) * rx[1], math.sin(a) * ry[1], 0.0),
                             Vec3(math.cos(b) * rx[1], math.sin(b) * ry[1], 0.0)))
            return segs

        if shape == SHAPE_CYLINDER:
            start, span = _sweep(f, "ScaleHorizontal", shape)
            segs = []
            for y in (ry[0], ry[1]):
                pts = [_ring(rx[1], rz[1], start + span * i / n, ry_val=y)
                       for i in range(n + 1)]
                segs.extend(zip(pts[:-1], pts[1:]))
            for i in range(4):
                a = start + span * i / 4.0
                segs.append((_ring(rx[1], rz[1], a, ry_val=ry[0]),
                             _ring(rx[1], rz[1], a, ry_val=ry[1])))
            return segs

        # Box：12 条棱
        xs, ys, zs = rx, ry, rz
        corners = [Vec3(xs[i], ys[j], zs[k])
                   for i in (0, 1) for j in (0, 1) for k in (0, 1)]
        segs = []
        for a in range(8):
            for b in range(a + 1, 8):
                # 只有恰好差一个坐标的两个角才是棱
                diff = sum(1 for t in range(3) if corners[a][t] != corners[b][t])
                if diff == 1:
                    segs.append((corners[a], corners[b]))
        return segs

    def duration_hint(self, em):
        return 0


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _axis_range(f, key, config):
    """逐轴区间 -> `(lo, hi)`。**不保证 lo <= hi**（`r` 可以是负的），交给 `_pick` 处理。"""
    s, r = f.sr(key)
    return (s, r) if config.es3d_range_mode == "min_max" else (s, s + r)


def _pick(rng, span):
    lo, hi = span
    if lo == hi:
        return lo
    return rng.uniform(lo, hi)


def _sweep(f, key, shape):
    """`(起始角, 跨度)`（弧度）。**该形状用不上这个字段时返回整圈/全扫的等价值**，
    绝不去读那个 `(1.0, 0.0)` 的中性默认值（见模块说明）。"""
    uses = _USES_SCALE_H if key == "ScaleHorizontal" else _USES_SCALE_V
    if shape not in uses:
        return (0.0, 2.0 * math.pi) if key == "ScaleHorizontal" else (-math.pi / 2, math.pi)
    return f.sr(key)


def _ring(radius_x, radius_z, angle, ry_val=0.0):
    return Vec3(math.cos(angle) * radius_x, ry_val, math.sin(angle) * radius_z)


def _apply_local_rotation(f, offset, config):
    if not f.has("LocalRotation"):
        return offset
    rot = f.vec3("LocalRotation", Vec3())
    if rot.x == 0.0 and rot.y == 0.0 and rot.z == 0.0:
        return offset
    order = rotation_order_name(f.i("RotationOrder"))
    return rotate_euler(offset, rot.x, rot.y, rot.z, order=order,
                        applied=config.rot_order_applied)
