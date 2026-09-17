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

区间读法：**`[min, max]`**，外边界就是第二个数
---------------------------------------------
`RangeX/Y/Z` 是 `(min, max)`，**不是** MHWI 那种 `min + offset`（外边界 = `min + offset`），
更不是 (静态值, 随机量)。全语料定的，判据是"`max < min` 出现过没有"：**0/62492**，而主值
非零的有 36590/20748/36840 例——offset 读法下第二个数是**厚度**，半径 1.0 厚 0.1 的薄壳
就该写成 `(1.0, 0.1)` 即 `max < min`，这种组合一次都没有。完整依据见
`shapes.PAIR_MIN_MAX_FIELDS`。

早先这里有个 `SimConfig.es3d_range_mode` 标定开关（默认按 static/random 读 `[s, s+r]`），
**已经删掉**——语料把它定死了，留着只会让人以为还有得选，而默认的那一档是错的：
它把 `(-0.5, 0.5)` 这种"以原点为中心对称"的圆柱读成了 `[-0.5, 0]`，高度只剩一半、整段偏到
原点下方。

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

        画法对齐姊妹项目 EFX-Editor 的 `es3d_overlay`，但**按本仓的采样语义裁剪过**，
        逐形状的依据就是上面那三个 `_sample_*`：

        - **球 / 圆柱画内外双边界 + 径向棱**：径向幅度是 `_pick(rng, r)` 在 `[lo, hi]` 里取的，
          `lo != 0` 时粒子真的只出现在一层壳里。只画内外两层而不连起来的话，"壳"这个概念在
          画面上根本不存在——所以径向棱不是装饰。`lo == 0` 时内层退化成点，自动不画。
        - **Box 只画外边界**：`on_particle_spawn()` 对 Box 是逐轴 `U(lo, hi)` 独立取，整个盒子
          是**实心**的。照搬姊妹项目的内层盒会画出一个"这里不会有粒子"的假空腔——那边的
          rangeXYZ 语义是"内边界 + 厚度"，和本仓的逐轴区间不是一回事。
        - **扫描角靠两端的经线/竖棱封口**，不画实体扇面：`_azimuths()` 在不满整圈时必定包含
          起点和终点，看得出是整圈还是只扫一段。

        ⚠ 出口处必须和 `on_particle_spawn()` 一样过一遍 `_apply_local_rotation()`：粒子的
        出生位置是转过的，线框不转的话，`LocalRotation` 非零时框和粒子对不上——而"框和粒子
        对不对得上"正是这圈线的全部用途。
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
            segs = _sphere_outline(f, rx, ry, rz, n)
        elif shape == SHAPE_CYLINDER:
            segs = _cylinder_outline(f, rx, ry, rz, n)
        else:
            segs = _box_outline(rx, ry, rz)
        return _rotated(f, segs, cfg)

    def duration_hint(self, em):
        return 0


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _axis_range(f, key, config):
    """逐轴区间 -> `(lo, hi)`，就是文件里的 `(min, max)`（见模块说明）。

    **仍然不保证 lo <= hi**：真实语料里恒成立（62492/62492），但用户可以在面板上手填出
    `max < min`，那时照 `_pick` 的 `rng.uniform` 行为处理，不静默交换也不抛。
    `config` 留着是因为调用点都传它，且以后可能还有别的标定项挂上来。
    """
    return f.min_max_pair(key)


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


#: 判"整圈"和"零跨度"的容差（弧度）
_ANGLE_EPS = 1e-6
#: 判"内层是不是退化成一个点"的容差（游戏单位）
_SHELL_EPS = 1e-9


def _azimuths(start, span, full):
    """经线 / 竖棱所在的方位角。

    整圈画 4 条（四等分，一眼看出是个回转体）；只扫一段时画 3 条，且**必定包含起点和终点**
    ——端点就是这段扫描的封口，少了它看不出扫到哪儿为止。
    """
    if full:
        return [start + 2.0 * math.pi * k / 4.0 for k in range(4)]
    return [start + span * k / 2.0 for k in range(3)]


def _arc_steps(n, span, full):
    """一段弧分多少份。只扫一小段时按比例缩，免得 20° 的扇形上堆 28 个点。"""
    if full:
        return n
    frac = abs(span) / (2.0 * math.pi)
    return max(3, int(n * max(0.08, frac)))


def _sphere_pt(radius, az, polar):
    """和 `_sample_sphere()` 完全同一条参数化——改一个必须改另一个，否则框和粒子就分家了。"""
    return Vec3(math.cos(az) * math.cos(polar) * radius[0],
                math.sin(polar) * radius[1],
                math.sin(az) * math.cos(polar) * radius[2])


def _sphere_outline(f, rx, ry, rz, n):
    h_start, h_span = _sweep(f, "ScaleHorizontal", SHAPE_SPHERE)
    v_start, v_span = _sweep(f, "ScaleVertical", SHAPE_SPHERE)
    full_h = abs(abs(h_span) - 2.0 * math.pi) <= _ANGLE_EPS
    outer = (rx[1], ry[1], rz[1])
    inner = (rx[0], ry[0], rz[0])
    hollow = any(abs(c) > _SHELL_EPS for c in inner)
    shells = [outer] + ([inner] if hollow else [])

    polars = [v_start, v_start + v_span * 0.5, v_start + v_span]
    if abs(v_span) <= _ANGLE_EPS:
        polars = [v_start]
    azs = _azimuths(h_start, h_span, full_h)

    segs = []
    for radius in shells:
        # 纬度环（极点上 cos(polar)≈0，环退化成一个点，跳过）
        for polar in polars:
            if abs(math.cos(polar)) <= _ANGLE_EPS:
                continue
            steps = _arc_steps(n, h_span, full_h)
            pts = [_sphere_pt(radius, h_start + h_span * i / steps, polar)
                   for i in range(steps + 1)]
            segs.extend(zip(pts[:-1], pts[1:]))
        # 经线
        if abs(v_span) > _ANGLE_EPS:
            steps = _arc_steps(n, v_span, abs(abs(v_span) - math.pi) <= _ANGLE_EPS)
            for az in azs:
                pts = [_sphere_pt(radius, az, v_start + v_span * i / steps)
                       for i in range(steps + 1)]
                segs.extend(zip(pts[:-1], pts[1:]))
    if hollow:
        for az in azs:
            for polar in polars:
                segs.append((_sphere_pt(inner, az, polar), _sphere_pt(outer, az, polar)))
    return segs


def _cylinder_pt(radius_x, radius_z, az, y):
    """和 `_sample_cylinder()` 同一条参数化（XZ 是横截面、Y 是高度）。"""
    return Vec3(math.cos(az) * radius_x, y, math.sin(az) * radius_z)


def _cylinder_outline(f, rx, ry, rz, n):
    h_start, h_span = _sweep(f, "ScaleHorizontal", SHAPE_CYLINDER)
    full_h = abs(abs(h_span) - 2.0 * math.pi) <= _ANGLE_EPS
    # 高度是有符号区间，直接取两端；**不做 lo<=hi 规整**（`RangeY` 真的会是负的）
    ys = [ry[0]] if ry[0] == ry[1] else [ry[0], ry[1]]
    hollow = abs(rx[0]) > _SHELL_EPS or abs(rz[0]) > _SHELL_EPS
    shells = [(rx[1], rz[1])] + ([(rx[0], rz[0])] if hollow else [])
    azs = _azimuths(h_start, h_span, full_h)

    segs = []
    for radius_x, radius_z in shells:
        for y in ys:
            steps = _arc_steps(n, h_span, full_h)
            pts = [_cylinder_pt(radius_x, radius_z, h_start + h_span * i / steps, y)
                   for i in range(steps + 1)]
            segs.extend(zip(pts[:-1], pts[1:]))
        if len(ys) == 2:
            for az in azs:
                segs.append((_cylinder_pt(radius_x, radius_z, az, ys[0]),
                             _cylinder_pt(radius_x, radius_z, az, ys[1])))
    if hollow:
        for y in ys:
            for az in azs:
                segs.append((_cylinder_pt(rx[0], rz[0], az, y),
                             _cylinder_pt(rx[1], rz[1], az, y)))
    return segs


def _box_outline(rx, ry, rz):
    """12 条棱。Box 是**实心**的（逐轴 `U(lo, hi)` 独立取），没有内层。"""
    corners = [Vec3(rx[i], ry[j], rz[k])
               for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    segs = []
    for a in range(8):
        for b in range(a + 1, 8):
            # 只有恰好差一个坐标的两个角才是棱
            diff = sum(1 for t in range(3) if corners[a][t] != corners[b][t])
            if diff == 1:
                segs.append((corners[a], corners[b]))
    return segs


def _rotated(f, segs, config):
    """把线框的每个端点过一遍 `_apply_local_rotation()`（和粒子出生位置同一条换算）。"""
    return [(_apply_local_rotation(f, a, config), _apply_local_rotation(f, b, config))
            for a, b in segs]


def _apply_local_rotation(f, offset, config):
    if not f.has("LocalRotation"):
        return offset
    rot = f.vec3("LocalRotation", Vec3())
    if rot.x == 0.0 and rot.y == 0.0 and rot.z == 0.0:
        return offset
    order = rotation_order_name(f.i("RotationOrder"))
    return rotate_euler(offset, rot.x, rot.y, rot.z, order=order,
                        applied=config.rot_order_applied)
