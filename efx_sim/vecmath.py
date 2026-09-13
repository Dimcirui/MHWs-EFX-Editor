# -*- coding: utf-8 -*-
"""
efx_sim/vecmath.py —— 旋转与角度采样

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/vecmath.py`（见 docs/SIM_PORT_PLAN.md §4.1）。
**两处必改，别照搬**（依据见 docs/SIM_PORT_PLAN.md §8.1 / §8.2）：

1. **角度单位是弧度，不是度。** 上游 `rotate_euler()` 收度、内部 `math.radians()`；MHWs 的
   角度字段本身就是弧度（`Transform3D.LocalRotation.X` 的高频取值精确落在 π 的有理数倍上：
   1.5707964=π/2、3.1415927=π、0.5235988=π/6、0.17453294=10°），语义表已有 28 个字段标了
   `angle_radians`。所以这里直接收弧度，不做转换。

2. **旋转顺序用 vendor 枚举，不继承上游的索引表。** 上游有**两张互相矛盾**的映射表
   （`VELOCITY3D.rotOrder` 一张、`TRANSFORM3D/ES3D/RIBBON` 一张），而且它自己的 tooltip
   和 schema 在下标 2/4 上还对不上。MHWs 这边 `ReeLib.Efx.Enums.RotationOrder` 是 C# 声明，
   只有一张、且权威：

       0=XYZ  1=YZX  2=ZXY  3=ZYX  4=YXZ  5=XZY

   **语义单位是"顺序串"，不是"整数下标"** —— 跨项目搬的时候搬串，不搬下标。
   顺带：MHWs 的 `Velocity3D` 根本没有旋转顺序字段（改用 `DirectionVectorX/Y/Z` 直接给方向
   向量），上游那个"两套表"的麻烦在这边直接消失。

   这张表和 `blender_efx_re/coords.py::_ROTATION_ORDER_NAMES` 是同一份数据，由
   `tests/test_sim_core.py` 断言两边一致（`coords.py` 要 import mathutils，核心层不能碰）。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import math

from .state import Vec3

#: `ReeLib.Efx.Enums.RotationOrder`（vendor `EFXEnums.cs`），下标即枚举值。
ROTATION_ORDER = ("XYZ", "YZX", "ZXY", "ZYX", "YXZ", "XZY")

#: 语料里 98%+ 的 `RotationOrder` 都是 2（ZXY）——那是制作工具的默认档。
DEFAULT_ROTATION_ORDER = "ZXY"


def rotation_order_name(value):
    """`RotationOrder` 字段的原始值 → 顺序串。

    EfxBridge dump 出来的枚举是**纯整数**（实测 `"RotationOrder": 2`），但 `coords.py` 对
    字符串形式（`"RotationOrder_XYZ"`）也是容忍的，这里保持一致——识别不了一律退回 `"XYZ"`
    （vendor 枚举默认值同为 0）。
    """
    if isinstance(value, str):
        name = value.rsplit("_", 1)[-1].upper()
        return name if name in ROTATION_ORDER else "XYZ"
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "XYZ"
    return ROTATION_ORDER[v] if 0 <= v < len(ROTATION_ORDER) else "XYZ"


# ---------------------------------------------------------------------------
# 欧拉旋转
# ---------------------------------------------------------------------------

def _rot_x(v, c, s):
    return Vec3(v.x, v.y * c - v.z * s, v.y * s + v.z * c)


def _rot_y(v, c, s):
    return Vec3(v.x * c + v.z * s, v.y, -v.x * s + v.z * c)


def _rot_z(v, c, s):
    return Vec3(v.x * c - v.y * s, v.x * s + v.y * c, v.z)


_ROT_FN = {"X": _rot_x, "Y": _rot_y, "Z": _rot_z}


def rotate_euler(v, rx, ry, rz, order="XYZ", applied="forward"):
    """把向量 `v` 依次绕三个轴旋转。**角度是弧度。**

    `applied='forward'` → 顺序串里先写的先作用于向量。

    ⚠ 待标定：顺序串 "XYZ" 里是"先写的先作用"还是相反，没有实测——这是
    `SimConfig.rot_order_applied` 开关（上游同样留着这个未知项）。
    """
    if not rx and not ry and not rz:
        return v.copy()
    ang = {"X": float(rx), "Y": float(ry), "Z": float(rz)}
    seq = order if applied == "forward" else order[::-1]
    out = v.copy()
    for axis in seq:
        a = ang[axis]
        if a:
            out = _ROT_FN[axis](out, math.cos(a), math.sin(a))
    return out


# ---------------------------------------------------------------------------
# 角度采样
# ---------------------------------------------------------------------------

def quantize_angle(t, divisions):
    """把 [0,1) 的归一化角度量化到 `divisions` 个等分点上。`divisions <= 1` 时不量化。

    对应 `EmitterShape3D.RangeDivideHorizontalNum` / `RangeDivideVerticalNum`。
    ⚠ P0 不消费这两个字段——上游说"纵向等分三种形状都用、横向只有球/圆柱用"，而 MHWs 语料
    里正好反过来（见 docs/SIM_PORT_PLAN.md §8.5），语义未决。函数先放着。
    """
    n = int(divisions)
    if n <= 1:
        return t
    return math.floor(t * n) / float(n)


def sweep_fraction(rng, start_angle, span_angle, divisions=0):
    """在 `[start_angle, start_angle + span_angle]`（**弧度**）里取一个角度。

    对应 `EmitterShape3D.ScaleHorizontal` / `ScaleVertical` 的 `(s, r) = (起始角, 跨度)`
    读法（依据见 docs/SIM_PORT_PLAN.md §8.4：`(0, 2π)` = 水平全向、`(-π/2, π)` = 垂直全扫）。
    `span_angle` 为 0 时退化成恒定 `start_angle`。
    """
    t = quantize_angle(rng.random(), divisions)
    return float(start_angle) + t * float(span_angle)


def unit_from_spherical(azimuth, polar):
    """(方位角, 极角)（弧度）→ 单位向量。游戏坐标系 **+Y = 上**，故极角绕 Y 轴量：
    `polar = 0` → 赤道，`±π/2` → 两极。"""
    y = math.sin(polar)
    r = math.cos(polar)
    return Vec3(math.cos(azimuth) * r, y, math.sin(azimuth) * r)
