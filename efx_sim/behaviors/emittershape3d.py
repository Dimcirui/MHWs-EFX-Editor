# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/emittershape3d.py —— `EmitterShape3D`（生成位置）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `EmitterShape3D`，TypeID 97）：

    RangeX / RangeY / RangeZ    Range    逐轴的生成幅度（**以 0 为界的绝对值区间**，见下）
    ShapeType                   enum     0=Box 1=Sphere 2=Cylinder（`Shape3DType`，只有三个）
    ScaleHorizontal             Range    球/圆柱：(起始角,跨度) 弧度；Box：X 轴锥度
    ScaleVertical               Range    球：(起始角,跨度) 弧度；圆柱/Box：径向/Z 轴锥度
    UseExtension                bool     是否启用上面两个字段（见下）
    LocalRotation + RotationOrder        生成形状自身的整体旋转（**弧度**）
    RangeDivideAxis/Num         enum/int  Box：选中的轴均分成 n 个垂直平面（见下）
    RangeDivideHorizontal/VerticalNum  int  Sphere/Cylinder：方位角/张角或高度均分成 n 个点
    RotationCorrect / DivideEquidistant*   P0 不消费

`RangeX/Y/Z`：**逐轴绝对值区间，钳在 `[0, +∞)`，符号独立随机**（2026-09-17 用户实机确认，
Box 专项；与 `UseExtension` 无关，任何状态下都成立）
--------------------------------------------------------------------------
早先这里假设 Box 是"实心，`U(lo,hi)` 逐轴独立取，`lo` 可以是负的"——这是**纯语料推断，从没
实机验证过**（`max<min` 全语料 0/62492 只证明了"第二个数不小于第一个数"，不证明负 `min`
真的会被当成有符号偏移用）。实机结果推翻了它：

- **`min` 不管多负都会被钳到 0**：`RangeX/Y/Z=(-100, .2)` 和 `(0, .2)` 表现完全一样，
  不会长出一个从 -100 到 .2 的巨型盒子。
- **`min` 非零时，粒子会避开原点附近的方形空腔**：`(.1,.2)` 三轴同取，表现为一个空心的
  方形截面（"空心方筒"），不是一个从 0.1 偏到 0.2 的小实心方块。

**三轴是联合挖空，不是各自独立钳位**（2026-09-17 实机确认追加）：X/Y/Z 同取 `(0.1,0.2)`
表现为边长 0.2m 的立方体、正中间被整个挖掉一块 0.1m 立方体空间——**Y 轴和 X/Z 待遇完全
一样**，不是"圆柱那种 Y 单独是高度轴"的特例。读法是大盒子 `[-hi,hi]^3` 减去正中央的小盒子
`[-lo,lo]^3`：一个点只有在**三个轴同时**都落进 `(-lo,lo)` 时才算掉进那个洞、要重抽；
任意一个轴超出了自己的 `lo`，这个点就算数，不管另外两轴是不是还在洞里——用拒绝采样实现，
`_pick_hollow_box()`。这就是为什么之前样本区分不出"独立钳位"（每轴各自要求
`|value|>=lo`，会切出 8 个不连通的角落小盒子）和"联合挖空"（现在这条，1 个连通空腔）：
两条假设在旧样本上都吻合，直到测出以 `lo` 为界的完整立方体空腔才排除了独立钳位。

`ScaleHorizontal`/`ScaleVertical`：只在 `UseExtension` 打开时生效，且**按形状复用成完全
不同的量**（2026-09-17 实机 + 全语料 `condstats ShapeType,UseExtension` 联合分桶交叉确认）
------------------------------------------------------------------------------------------
`UseExtension` 关闭时两个字段**恒为中性默认值，形状不变**——`EfxBridge condstats` 按
`ShapeType` 分桶验证过（62477 个实例）：Box 恒 `(1.0,0.0)`、Sphere 恒 `(0,2π)`/`(-π/2,π)`、
Cylinder 恒 `(0,2π)`/`(1.0,0.0)`，且联合 `ShapeType,UseExtension` 分桶显示 `UseExtension=
false` 时全部三种形状锁死在各自唯一的默认值上，无一例外。

`UseExtension` 打开后：

- **Sphere**：两个字段都还是角度（起始角 + 跨度，弧度制），**和现有 `_sample_sphere()` 的
  `polar=sin/cos` 公式完全吻合，代码不用改**——实机确认水平角 `[0,360]` 表现为圆锥面、
  垂直角 static 是"立体角补角"（90°=竖线、0°=整圆面、±60/±120 张角相等、负值反向），
  代入现有的 `cy=sin(polar), cr=cos(polar)` 直接就是这个结果。
- **Cylinder**：水平角仍是方位角扫描（不变）；`ScaleVertical` 变成**沿高度线性插值的
  径向锥度**：`(s, r)` 在 `RangeY` 的 `[ry[0], ry[1]]` 上线性给出缩放系数，
  `t=0`（`ry[0]` 端）缩放 `s`，`t=1`（`ry[1]` 端，即 `+Y`/"底"）缩放 `s+r`，实机枚举过
  `(1,0)`→不变、`(1,1)`→圆台（底比顶粗 1 倍半径）、`(1,2)`→粗 2 倍、`(0,0)`→退化成一条
  直线、`(0,1)`→变成底半径 1 的圆锥。
- **Box**：`ScaleHorizontal`→X 轴锥度，`ScaleVertical`→Z 轴锥度（实机双向换算确认，两次
  互换测试各自只影响对应那根轴），公式同上（沿 `RangeY` 的对称幅度区间线性插值，
  `t=0` 在 `-hi_y` 端、`t=1` 在 `+hi_y` 端）。`[1,0][1,0]` 两轴都不变→普通长方体。

⚠ Box 的两根锥度轴具体是不是这套"沿 Y 线性插值"模型、和上面的"三轴联合挖空"怎么共同作用，
只测过 `RangeY` 退化成单值和 `(0,.3)` 两种情形，细节仍待更多实机样本，见
`docs/SIM_PORT_PLAN.md` §8.4 追记。

`RangeDivide*`：把连续采样离散成 n 个位置（用户描述，2026-09-17，尚未逐条语料/实机交叉
验证，按描述直接实现）
------------------------------------------------------------------------------------
- **Box**（`RangeDivideAxis`=0/1/2 选 X/Y/Z，`RangeDivideNum`=n）：选中的那根轴不再连续
  取值，改成把该轴的对称幅度区间 `[-hi,hi]` 均分成 n 个点（含两端）——"以这根轴为垂线，
  均分成 n 个面"，整个盒子变成 n 片垂直于该轴的平面。另外两根轴不受影响，继续按原来的
  幅度 + 联合空腔逻辑采样（该轴被强制到某个离散值后仍然要参与联合空腔判断，只是不再重投）。
- **Sphere**（`RangeDivideHorizontalNum`/`RangeDivideVerticalNum`）：水平方向把方位角均分
  成 n 个点（**不含重复的收尾点**——方位角是周期量，均分 n 份自然是 n 个点，像 n 片叶片/
  经线）；垂直方向把张角（从 `-Y` 到 `+Y` 的极角区间）均分成 n 个点（**含两端**——极角不是
  周期量，两端是两个真实存在的极点），每个点是一个定纬度的圆锥面。特例：n=2 时两个点正好
  落在两极，两个退化的极点直线重合成一条穿过原点的直线；n=3 时两极 + 赤道，退化直线和赤道
  圆盘同时出现（用户实机描述，`_divided_value(periodic=False)` 的两端对齐后自然得到这个
  结果，不是专门为这两个特例写的分支）。
- **Cylinder**：水平方向和 Sphere 同一套方位角离散化（周期量，不含收尾重复点）；垂直方向
  把 `RangeY` 均分成 n 个点（含两端——和 Sphere 的极角同理，`RangeY` 也不是周期量），圆柱
  变成 n 片垂直于 Y 轴的圆形/圆环平面。

`_divided_value()` 是这三种情形共用的离散化入口：字段 <= 0（默认，未启用）返回 `None`，
调用方退回原来的连续采样，两条路径不会同时生效。

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
    ("RotationCorrect", 0),
)
_UNUSED_BOOL_FIELDS = (
    "DivideEquidistant", "DivideEquidistantCalcOuterCurveData",
    "DivideEquidistantRecalcEveryFrameData",
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
        use_ext = f.has("UseExtension") and f.b("UseExtension")
        rx = _axis_range(f, "RangeX", em.config)
        ry = _axis_range(f, "RangeY", em.config)
        rz = _axis_range(f, "RangeZ", em.config)

        if shape == SHAPE_SPHERE:
            offset = self._sample_sphere(f, rng, rx, ry, rz, use_ext)
        elif shape == SHAPE_CYLINDER:
            offset = self._sample_cylinder(f, rng, rx, ry, rz, use_ext)
        else:
            offset = self._sample_box(f, rng, rx, ry, rz, use_ext)

        offset = _apply_local_rotation(f, offset, em.config)
        p.spawn_pos = offset
        p.pos = em.origin + offset

    # -- 逐形状采样 ----------------------------------------------------------
    @staticmethod
    def _sample_sphere(f, rng, rx, ry, rz, use_ext):
        h_start, h_span = _sweep(f, "ScaleHorizontal", SHAPE_SPHERE, use_ext)
        az = _divided_value(rng, f, "RangeDivideHorizontalNum", h_start, h_span, periodic=True)
        if az is None:
            az = sweep_fraction(rng, h_start, h_span)
        v_start, v_span = _sweep(f, "ScaleVertical", SHAPE_SPHERE, use_ext)
        polar = _divided_value(rng, f, "RangeDivideVerticalNum", v_start, v_span, periodic=False)
        if polar is None:
            polar = sweep_fraction(rng, v_start, v_span)
        cy = math.sin(polar)
        cr = math.cos(polar)
        # 逐轴幅度独立取 -> 椭球也能表达；方向分量和幅度分开乘，符号交给方向
        return Vec3(math.cos(az) * cr * _pick(rng, rx),
                    cy * _pick(rng, ry),
                    math.sin(az) * cr * _pick(rng, rz))

    @staticmethod
    def _sample_cylinder(f, rng, rx, ry, rz, use_ext):
        h_start, h_span = _sweep(f, "ScaleHorizontal", SHAPE_CYLINDER, use_ext)
        az = _divided_value(rng, f, "RangeDivideHorizontalNum", h_start, h_span, periodic=True)
        if az is None:
            az = sweep_fraction(rng, h_start, h_span)
        # XZ 是横截面（径向），Y 是高度（直接取区间，可以是负的——圆柱的 Y 语义不受
        # 这次 Box 的发现影响，早就用语料坐实过，见模块说明）
        y = _divided_value(rng, f, "RangeDivideVerticalNum", ry[0], ry[1] - ry[0], periodic=False)
        if y is None:
            y = _pick(rng, ry)
        scale = _height_taper(f, "ScaleVertical", use_ext, _height_fraction(y, ry))
        return Vec3(math.cos(az) * _pick(rng, rx) * scale,
                    y,
                    math.sin(az) * _pick(rng, rz) * scale)

    @staticmethod
    def _sample_box(f, rng, rx, ry, rz, use_ext):
        # `RangeDivideAxis` 选中的那根轴强制到 n 个离散位置之一（其余两轴照旧），见模块说明
        forced = {}
        axis = f.i("RangeDivideAxis") if f.has("RangeDivideAxis") else -1
        if axis in (0, 1, 2):
            _, hi = _clamped_span((rx, ry, rz)[axis])
            value = _divided_value(rng, f, "RangeDivideNum", -hi, 2.0 * hi, periodic=False)
            if value is not None:
                forced[axis] = value
        # 三轴联合挖空（见模块说明的实机结论），Y 和 X/Z 待遇完全一样
        x, y, z = _pick_hollow_box(rng, rx, ry, rz, forced)
        _, hi_y = _clamped_span(ry)
        t = 0.5 if hi_y <= 0.0 else (y + hi_y) / (2.0 * hi_y)
        scale_x = _height_taper(f, "ScaleHorizontal", use_ext, t)
        scale_z = _height_taper(f, "ScaleVertical", use_ext, t)
        return Vec3(x * scale_x, y, z * scale_z)

    # -- 线框（给预览画生成区域）--------------------------------------------
    def outline(self, em, segments=28):
        """返回成对的点 `[(a, b), ...]`，与粒子同一坐标空间（游戏系，相对发射器原点未加）。

        画法对齐姊妹项目 EFX-Editor 的 `es3d_overlay`，但**按本仓的采样语义裁剪过**，
        逐形状的依据就是上面那三个 `_sample_*`：

        - **球 / 圆柱画内外双边界 + 径向棱**：径向幅度是 `_pick(rng, r)` 在 `[lo, hi]` 里取的，
          `lo != 0` 时粒子真的只出现在一层壳里。只画内外两层而不连起来的话，"壳"这个概念在
          画面上根本不存在——所以径向棱不是装饰。`lo == 0` 时内层退化成点，自动不画。
        - **Box 现在也画内层**：`RangeX/Y/Z` 的 `lo` 非零时粒子会避开原点附近的空腔（实机
          2026-09-17 确认，见模块说明），不再是"逐轴 `U(lo,hi)` 独立取的实心盒子"那套旧假设。
        - **扫描角靠两端的经线/竖棱封口**，不画实体扇面：`_azimuths()` 在不满整圈时必定包含
          起点和终点，看得出是整圈还是只扫一段。
        - **`UseExtension` 打开时，圆柱 / Box 的外形随高度线性变化**（锥度/frustum，见模块
          说明），线框对应画出上下两端不同的宽度，不再是简单的直筒/直棱柱。

        ⚠ 出口处必须和 `on_particle_spawn()` 一样过一遍 `_apply_local_rotation()`：粒子的
        出生位置是转过的，线框不转的话，`LocalRotation` 非零时框和粒子对不上——而"框和粒子
        对不对得上"正是这圈线的全部用途。
        """
        f = em.f(TYPE_NAME)
        if f is None:
            return []
        cfg = em.config
        shape = f.i("ShapeType")
        use_ext = f.has("UseExtension") and f.b("UseExtension")
        rx = _axis_range(f, "RangeX", cfg)
        ry = _axis_range(f, "RangeY", cfg)
        rz = _axis_range(f, "RangeZ", cfg)
        n = max(6, int(segments))

        if shape == SHAPE_SPHERE:
            segs = _sphere_outline(f, rx, ry, rz, n, use_ext)
        elif shape == SHAPE_CYLINDER:
            segs = _cylinder_outline(f, rx, ry, rz, n, use_ext)
        else:
            segs = _box_outline(f, rx, ry, rz, use_ext)
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


def _clamped_span(span):
    """`(lo, hi)` -> 钳到 `[0, +∞)` 之后的 `(lo, hi)`（`lo<=hi`）。Box 的 `RangeX/Y/Z`
    专用（见模块说明的实机结论）：负 min 不管多负都当 0，不是"允许负值的独立位置区间"。"""
    lo, hi = max(0.0, span[0]), max(0.0, span[1])
    return (lo, hi) if lo <= hi else (hi, lo)


def _box_axis_value(rng, lo, hi):
    """大盒子 `[-hi, hi]` 范围内独立取一个轴的值：`lo == hi`（退化区间）钉死在 `±lo`（符号
    随机）；否则在 `[-hi, hi]` 连续取——**是否落进中心那个挖空的小盒子，交给
    `_pick_hollow_box()` 的联合判断处理，这里不管 `lo`**（`lo` 只用来判断"钉死"，不用来
    夹这个轴自己的采样范围）。"""
    if hi <= 0.0:
        return 0.0
    if lo == hi:
        return lo if rng.random() < 0.5 else -lo
    return rng.uniform(-hi, hi)


def _pick_hollow_box(rng, rx, ry, rz, forced=None, max_tries=64):
    """Box 的 `RangeX/Y/Z` 联合采样：大盒子 `[-hi,hi]^3` 挖掉正中央的小盒子
    `[-lo,lo]^3`——**2026-09-17 实机确认，三轴待遇完全一样**：X/Y/Z 同取 `(0.1,0.2)` 表现为
    边长 0.2m、正中间被挖掉 0.1m 立方体空间的盒子，不是三轴各自独立钳位（后者会切成 8 个不
    连通的角落小盒子，和实机看到的连通空腔对不上）。用拒绝采样实现：大盒子里独立取点，
    三个轴同时都落进小盒子（`|x|<lo_x and |y|<lo_y and |z|<lo_z`）才重抽；某轴 `lo=0`（没有
    挖空）时那个轴的判据恒真，等于不参与"是否在洞里"的判断——和已有语义自然衔接。

    `forced`（`{0: x值}`/`{1: y值}`/`{2: z值}`）给了某根轴的值就把那根轴钉死在这个值上、
    重抽时也不动它——`RangeDivideAxis`/`RangeDivideNum` 把某根轴离散成 n 个位置时用这个，
    离散值本身仍然要参与联合空腔判断（forced 恰好落进洞里、且另外两轴凑巧也没跳出来，一样
    会重抽另外两轴，直到满足或到 `max_tries`）。

    `max_tries` 次都没抽到有效点：极端情况下（`lo` 只比 `hi` 小一点点，洞占了几乎整个盒子）
    直接放行最后一次采样——概率上这种情形本来就该出现，不是"抽样失败"，钳成拒绝反而更像
    在骗用户说这个区域真的空了。
    """
    lo_x, hi_x = _clamped_span(rx)
    lo_y, hi_y = _clamped_span(ry)
    lo_z, hi_z = _clamped_span(rz)
    forced = forced or {}
    x = y = z = 0.0
    for _ in range(max_tries):
        x = forced[0] if 0 in forced else _box_axis_value(rng, lo_x, hi_x)
        y = forced[1] if 1 in forced else _box_axis_value(rng, lo_y, hi_y)
        z = forced[2] if 2 in forced else _box_axis_value(rng, lo_z, hi_z)
        if abs(x) >= lo_x or abs(y) >= lo_y or abs(z) >= lo_z:
            break
    return x, y, z


def _division_points(f, count_key, start, span, periodic):
    """`RangeDivide{Horizontal,Vertical}Num`/`RangeDivideNum` 生效时（字段 > 0），把
    `(start, start+span)` 均分成 n 个离散点，返回完整列表；字段 <= 0（默认值，未启用）或
    不存在时返回 `None`，调用方自己退回连续读法——两条路径互斥，见模块说明。采样和线框
    共用同一份列表：采样从里面随机挑一个（`_divided_value()`），线框把 n 个全部画出来。

    `periodic=True`（方位角这类首尾重合的周期量）：n 个点**不含重复的收尾点**
    （`start + span*i/n`，i=0..n-1）——均分一整圈自然是 n 个点，不是 n 段。
    `periodic=False`（极角/高度/Box 轴位置这类首尾不重合的线性量）：n 个点**含两端**
    （`start + span*i/(n-1)`，i=0..n-1；n<=1 时退化成 `start`）——两端是两个真实存在、
    不重合的位置，n=2 时"均分成 2 个点"就该是这两个端点本身，不是端点内缩一步。
    """
    n = f.i(count_key) if f.has(count_key) else 0
    if n <= 0:
        return None
    if periodic:
        return [start + span * i / n for i in range(n)]
    if n <= 1:
        return [start]
    return [start + span * i / (n - 1) for i in range(n)]


def _divided_value(rng, f, count_key, start, span, periodic):
    """`_division_points()` 生效时随机挑一个（等概率），不生效返回 `None`。"""
    points = _division_points(f, count_key, start, span, periodic)
    if points is None:
        return None
    return points[rng.randrange(len(points))]


def _height_fraction(y, ry):
    """圆柱专用：`y` 在 `[ry[0], ry[1]]` 上的归一化位置（`ry[0]`->0，`ry[1]`->1）。
    圆柱的 `RangeY` 是有符号位置区间，不受 Box 那条"钳位到幅度"结论影响（见模块说明）。"""
    span = ry[1] - ry[0]
    return 0.0 if span == 0.0 else (y - ry[0]) / span


def _height_taper(f, key, use_ext, t):
    """`UseExtension` 打开时的线性锥度：`t=0` 端缩放 `s`，`t=1` 端缩放 `s+r`
    （`(s,r) = f.sr(key)`），关闭时恒为 1（形状不变）。实机确认见模块说明（圆柱
    `ScaleVertical` 的圆台/圆锥枚举、Box 双轴换算测试）。**不钳到非负**——早先猜负缩放是
    "没见过的用法"才钳掉，2026-09-17 实机推翻：Box 的负缩放是真实存在、有对应视觉效果的
    取值，钳成 0 反而是拿没验证过的假设覆盖掉实测数据。"""
    if not use_ext:
        return 1.0
    s, r = f.sr(key)
    return s + r * t


def _sweep(f, key, shape, use_ext):
    """`(起始角, 跨度)`（弧度），只有球（H/V）和圆柱（H）在用——**该形状用不上这个字段、或
    `UseExtension` 关闭时都返回整圈/全扫的等价值**，绝不去读那个 `(1.0, 0.0)` 的中性默认值
    （见模块说明）。`UseExtension` 关闭时字段本身也不生效，这条和 `ShapeType` 门控是
    两层独立的闸门，任一层没打开都要走兜底。"""
    uses = _USES_SCALE_H if key == "ScaleHorizontal" else _USES_SCALE_V
    if not use_ext or shape not in uses:
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
    if abs(span) <= _ANGLE_EPS:
        # 跨度为 0：三条经线会重合成同一条，只保留一条（别往绘制层塞重复线段）
        return [start]
    return [start + span * k / 2.0 for k in range(3)]


def _arc_steps(n, span, full):
    """一段弧分多少份。只扫一小段时按比例缩，免得 20° 的扇形上堆 28 个点。"""
    if full:
        return n
    frac = abs(span) / (2.0 * math.pi)
    return max(3, int(n * max(0.08, frac)))


def _radial_spokes(hollow, full_sweep, inner, build, solid_base):
    """径向棱：从内边界（实心时从原点）连到外边界。

    **不满一圈时，这几根棱就是切面的边**——没有它们，"扇形/薄片从哪儿张开"在画面上不存在。
    早先这里只在 `hollow` 时画，于是**实心 + 窄扫描**整个塌掉：实测球 `RangeXYZ=(0,2)`、
    扫描跨度 0 时，粒子沿半径铺成一条从原点射出的线段，而线框只剩最外端一个点，
    "框和粒子对不对得上"这个唯一用途直接失效。

    整圈 + 实心时**仍然不画**：那时外壳自己就是区域边界，棱纯属噪声。

    零长度的棱（内外重合）丢掉，不往绘制层塞退化线段。
    """
    if not hollow and full_sweep:
        return []
    base = inner if hollow else solid_base
    return [(a, b) for a, b in build(base)
            if abs(a.x - b.x) > _SHELL_EPS or abs(a.y - b.y) > _SHELL_EPS
            or abs(a.z - b.z) > _SHELL_EPS]


def _sphere_pt(radius, az, polar):
    """和 `_sample_sphere()` 完全同一条参数化——改一个必须改另一个，否则框和粒子就分家了。"""
    return Vec3(math.cos(az) * math.cos(polar) * radius[0],
                math.sin(polar) * radius[1],
                math.sin(az) * math.cos(polar) * radius[2])


def _sphere_outline(f, rx, ry, rz, n, use_ext):
    """`RangeDivideHorizontalNum`/`RangeDivideVerticalNum` 生效时，`azs`/`polars` 直接就是
    实际会采到的那 n 个方位角/纬度（不再是 3~4 条参考线）——纬度环变成 n 个定纬度圆锥面的
    边界圆，经线变成 n 片"叶片"的轮廓，画法和不分组时完全共用同一段代码，只是喂进去的
    列表不一样。见模块说明。"""
    h_start, h_span = _sweep(f, "ScaleHorizontal", SHAPE_SPHERE, use_ext)
    v_start, v_span = _sweep(f, "ScaleVertical", SHAPE_SPHERE, use_ext)
    full_h = abs(abs(h_span) - 2.0 * math.pi) <= _ANGLE_EPS
    outer = (rx[1], ry[1], rz[1])
    inner = (rx[0], ry[0], rz[0])
    hollow = any(abs(c) > _SHELL_EPS for c in inner)
    shells = [outer] + ([inner] if hollow else [])

    v_points = _division_points(f, "RangeDivideVerticalNum", v_start, v_span, periodic=False)
    if v_points is not None:
        polars = v_points
    else:
        polars = [v_start, v_start + v_span * 0.5, v_start + v_span]
        if abs(v_span) <= _ANGLE_EPS:
            polars = [v_start]

    h_points = _division_points(f, "RangeDivideHorizontalNum", h_start, h_span, periodic=True)
    azs = h_points if h_points is not None else _azimuths(h_start, h_span, full_h)

    full_v = abs(abs(v_span) - math.pi) <= _ANGLE_EPS

    segs = []
    for radius in shells:
        # 纬度环（极点上 cos(polar)≈0，环退化成一个点，跳过；跨度为 0 时整圈退化，也跳过）
        if abs(h_span) > _ANGLE_EPS:
            for polar in polars:
                if abs(math.cos(polar)) <= _ANGLE_EPS:
                    continue
                steps = _arc_steps(n, h_span, full_h)
                pts = [_sphere_pt(radius, h_start + h_span * i / steps, polar)
                       for i in range(steps + 1)]
                segs.extend(zip(pts[:-1], pts[1:]))
        # 经线
        if abs(v_span) > _ANGLE_EPS:
            steps = _arc_steps(n, v_span, full_v)
            for az in azs:
                pts = [_sphere_pt(radius, az, v_start + v_span * i / steps)
                       for i in range(steps + 1)]
                segs.extend(zip(pts[:-1], pts[1:]))
    segs.extend(_radial_spokes(
        hollow, full_h and full_v, inner,
        lambda base: [(_sphere_pt(base, az, polar), _sphere_pt(outer, az, polar))
                      for az in azs for polar in polars],
        (0.0, 0.0, 0.0)))
    return segs


def _cylinder_pt(radius_x, radius_z, az, y):
    """和 `_sample_cylinder()` 同一条参数化（XZ 是横截面、Y 是高度）。"""
    return Vec3(math.cos(az) * radius_x, y, math.sin(az) * radius_z)


def _cylinder_outline(f, rx, ry, rz, n, use_ext):
    """`UseExtension` 打开时每个高度 `y` 上的半径都要乘 `_height_taper()`——圆台/圆锥这类
    锥度形状，上下两端粗细不同，画法不能再假设"同一个 `radius_x,radius_z` 贯穿全高"。

    `RangeDivideVerticalNum` 生效时 `ys` 直接是实际会采到的 n 个高度（不再只是两个端点），
    `RangeDivideHorizontalNum` 生效时 `azs` 是实际会采到的 n 个方位角（不再是参考线）——
    水平方向一旦离散化，某个高度上就只有 n 个叶片点、没有连续的一整圈，这时不画那圈弧
    （画了等于骗人说整圈都有粒子），只画"叶片脊线"（每个方位角贯穿所有采到的高度）。
    """
    h_start, h_span = _sweep(f, "ScaleHorizontal", SHAPE_CYLINDER, use_ext)
    full_h = abs(abs(h_span) - 2.0 * math.pi) <= _ANGLE_EPS
    v_points = _division_points(f, "RangeDivideVerticalNum", ry[0], ry[1] - ry[0], periodic=False)
    v_divided = v_points is not None
    # 高度是有符号区间，直接取两端；**不做 lo<=hi 规整**（`RangeY` 真的会是负的）
    ys = v_points if v_divided else ([ry[0]] if ry[0] == ry[1] else [ry[0], ry[1]])
    hollow = abs(rx[0]) > _SHELL_EPS or abs(rz[0]) > _SHELL_EPS
    h_points = _division_points(f, "RangeDivideHorizontalNum", h_start, h_span, periodic=True)
    h_divided = h_points is not None
    azs = h_points if h_divided else _azimuths(h_start, h_span, full_h)

    def taper_at(y):
        return _height_taper(f, "ScaleVertical", use_ext, _height_fraction(y, ry))

    segs = []
    if not h_divided:
        for y in ys:
            scale = taper_at(y)
            shells = [(rx[1] * scale, rz[1] * scale)] + \
                ([(rx[0] * scale, rz[0] * scale)] if hollow else [])
            for radius_x, radius_z in shells:
                if abs(h_span) > _ANGLE_EPS:
                    steps = _arc_steps(n, h_span, full_h)
                    pts = [_cylinder_pt(radius_x, radius_z, h_start + h_span * i / steps, y)
                           for i in range(steps + 1)]
                    segs.extend(zip(pts[:-1], pts[1:]))
    # 每个方位角一条"叶片脊线"：贯穿所有采到的高度，相邻高度之间连线——高度连续时就是老的
    # 两端直棱/斜棱，高度离散时是过 n 个点的折线，同一套逻辑，不用分情况。
    for az in azs:
        scales = [taper_at(y) for y in ys]
        outer_pts = [_cylinder_pt(rx[1] * s, rz[1] * s, az, y) for s, y in zip(scales, ys)]
        segs.extend(zip(outer_pts, outer_pts[1:]))
        if hollow:
            inner_pts = [_cylinder_pt(rx[0] * s, rz[0] * s, az, y) for s, y in zip(scales, ys)]
            segs.extend(zip(inner_pts, inner_pts[1:]))
    # 每个高度切面上的径向棱（空心时内->外，实心时原点->外）——两端都要画，不只是外层
    # 侧壁；否则锥度形状的端面（比如圆锥的底面）看不出"从中心张开"。
    for y in ys:
        scale = taper_at(y)
        segs.extend(_radial_spokes(
            hollow, full_h and not h_divided, (rx[0] * scale, rz[0] * scale),
            lambda base, y=y, scale=scale: [(_cylinder_pt(base[0], base[1], az, y),
                               _cylinder_pt(rx[1] * scale, rz[1] * scale, az, y))
                               for az in azs],
            (0.0, 0.0)))
    # 切面靠中轴那条边：不满一圈且实心时，这条线是"扇形从中心张开"的唯一提示
    if not full_h and not h_divided and not hollow and len(ys) == 2:
        segs.append((Vec3(0.0, ys[0], 0.0), Vec3(0.0, ys[1], 0.0)))
    return segs


def _box_outline(f, rx, ry, rz, use_ext):
    """Box 现在是"大盒子 `[-hi,hi]^3` 挖掉正中央的小盒子 `[-lo,lo]^3`"（2026-09-17 实机
    确认，见模块说明——三轴待遇一样，`RangeY` 的 `lo` 非零时也会在 Y 方向留出空腔，不只是
    X/Z）。这里画外层棱柱 + （任一轴 `lo` 非零时的）内层空腔棱柱，跟 `_sphere_outline`/
    `_cylinder_outline` 的"内外两层"画法呼应；内层的 Y 位置用 `±lo_y`，不是 `±hi_y`——两层
    锥度也分别在各自的高度上算，不是共用外层的两个端点。

    `UseExtension` 打开时 X/Z 的半宽随高度线性变化（锥度），画法对应两端不同宽度的棱柱/台，
    和 `_cylinder_outline()` 共用同一条 `_height_taper()`。

    `RangeDivideAxis`/`RangeDivideNum` 生效时切到 `_box_outline_divided()`：Y 轴被选中时
    还是这同一套"沿 Y 堆叠切面"逻辑，只是切面数从 2 变成 n，精确到每片切面各自的锥度；
    X/Z 轴被选中时切面本身会因为锥度变成梯形，这里不追求逐片精确复刻梯形——保守用锥度全程
    绝对值最大的一档画等宽矩形，只保证粒子不会跑出线框，见 `_box_outline_divided()`。
    """
    lo_x, hi_x = _clamped_span(rx)
    lo_y, hi_y = _clamped_span(ry)
    lo_z, hi_z = _clamped_span(rz)

    def taper_at(y):
        t = 0.5 if hi_y <= 0.0 else (y + hi_y) / (2.0 * hi_y)
        return (_height_taper(f, "ScaleHorizontal", use_ext, t),
                _height_taper(f, "ScaleVertical", use_ext, t))

    def ring(half_x, half_z, y):
        return [Vec3(sx * half_x, y, sz * half_z) for sx, sz in ((-1, -1), (-1, 1), (1, 1), (1, -1))]

    def prism_edges(half_x, half_z, ys):
        scales = [taper_at(y) for y in ys]
        rings = [ring(half_x * s[0], half_z * s[1], y) for s, y in zip(scales, ys)]
        segs = []
        for pts in rings:
            segs.extend(zip(pts, pts[1:] + pts[:1]))
        for a_ring, b_ring in zip(rings, rings[1:]):
            for a, b in zip(a_ring, b_ring):
                segs.append((a, b))
        return segs

    axis = f.i("RangeDivideAxis") if f.has("RangeDivideAxis") else -1
    if axis == 1:
        y_points = _division_points(f, "RangeDivideNum", -hi_y, 2.0 * hi_y, periodic=False)
        if y_points is not None:
            return prism_edges(hi_x, hi_z, y_points)
    elif axis in (0, 2):
        segs = _box_outline_divided(f, axis, hi_x, hi_y, hi_z, use_ext)
        if segs is not None:
            return segs

    segs = prism_edges(hi_x, hi_z, [-hi_y, hi_y] if hi_y > 0.0 else [0.0])
    if lo_x > _SHELL_EPS or lo_y > _SHELL_EPS or lo_z > _SHELL_EPS:
        segs.extend(prism_edges(lo_x, lo_z, [-lo_y, lo_y] if lo_y > 0.0 else [0.0]))
    return segs


def _box_outline_divided(f, axis, hi_x, hi_y, hi_z, use_ext):
    """`RangeDivideAxis`=X(0) 或 Z(2) 时的切面堆叠：切面另一个方向的半宽由锥度驱动
    （`ScaleHorizontal`→X、`ScaleVertical`→Z，见模块说明），而锥度是 Y 的函数——但 Y 在这两
    种切法下正好是切面**自身**的一根轴，不是一个能提前定下来的固定值，切面因此本该是梯形。
    这里不逐片还原梯形，直接用锥度全程（`t∈[0,1]`）绝对值最大的一档，画等宽矩形——只保证
    "粒子不会跑出线框"这条硬要求，不是像素级还原形状。返回 `None` 表示这根轴没启用切分，
    调用方退回旧的双层棱柱画法。
    """
    axis_hi = hi_x if axis == 0 else hi_z
    positions = _division_points(f, "RangeDivideNum", -axis_hi, 2.0 * axis_hi, periodic=False)
    if positions is None:
        return None
    if use_ext:
        sx, rx_ = f.sr("ScaleHorizontal")
        sz, rz_ = f.sr("ScaleVertical")
        scale_x = max(abs(sx), abs(sx + rx_))
        scale_z = max(abs(sz), abs(sz + rz_))
    else:
        scale_x = scale_z = 1.0
    half_x = hi_x * scale_x
    half_z = hi_z * scale_z

    def face(pos):
        if axis == 0:
            return [Vec3(pos, sy * hi_y, sz * half_z) for sy, sz in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
        return [Vec3(sx * half_x, sy * hi_y, pos) for sx, sy in ((-1, -1), (-1, 1), (1, 1), (1, -1))]

    faces = [face(pos) for pos in positions]
    segs = []
    for pts in faces:
        segs.extend(zip(pts, pts[1:] + pts[:1]))
    for a_face, b_face in zip(faces, faces[1:]):
        for a, b in zip(a_face, b_face):
            segs.append((a, b))
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
