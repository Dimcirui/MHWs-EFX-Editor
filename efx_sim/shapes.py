# -*- coding: utf-8 -*-
"""
efx_sim/shapes.py —— 字段值的读取层（`Range` / `RangeI` / `Int2` / `Vec3` / 枚举）

**behavior 不许直接读原始字段 dict，一律走 `em.f(TYPE_NAME, p)` 拿到的 `FieldView`。**
这条规矩是为"语义待补"准备的：`Range.r` 到底怎么参与抽取、`Int2` 是不是 min/max——这些
现在还是开关，如果让 behavior 直接读 dict，等标定出答案要改几十个文件。

这个文件是本仓**新写**的（上游没有对应物）：MHWI 的字段在字节层就被拍平成标量，
`值 + 抖动` 是两个独立字段；MHWs 的字段是 C# 类字段的直译，`(静态值, 随机量)` 打包在一个
`via.Range` 里，形状不一样，读法也不一样。

打包形状与语义（依据见 `blender_efx_re/model.py` 的同名谓词，那是全语料定下来的）
-------------------------------------------------------------------------------
⚠ **主值是哪个键，取决于结构体类型，不是固定的 `s`。** `Range`(float) 的 C# 声明顺序是
`{s, r}`，`RangeI`(int) 是 `{r, s}` —— 两者二进制布局真的相反（vendor
`RszValueType.cs:226` / `:264`，实测 dump 出来的 JSON 键序也确实相反）。全语料证据表明
**二进制首字段恒为"主值"**（静态值 / min），第二个是"副值"（随机量 / max）：

- `Spawn.LoopNum`（RangeI）：`s != 0` 只占 1.4%，高频对是 `(r=1,s=0)` 55%、`(r=2,s=0)`、
  `(r=3,s=0)`……主值显然在 `r` 上。若按 `s` 当主值，98.6% 的发射器都是"循环 0 次"。
- `Velocity3D.SpeedCoef`（Range）：高频对是 `(s=1,r=0)`、`(s=0.99,r=0)`、`(s=0.98,r=0)`……
  主值显然在 `s` 上。

所以 `_primary_secondary()` 按值类型（int=RangeI / float=Range）选主键。**禁止按下标 /
`values()` 顺序取，也不要写死 `s` 是主值。**

副值是"随机量"还是"max"是**逐字段**的（不是逐类型）：

| JSON 形状        | 语义                              | 判定                              |
|------------------|-----------------------------------|-----------------------------------|
| `{"s":…,"r":…}`  | **(静态值, 随机量)**              | 默认                              |
| `{"s":…,"r":…}`  | (min, max)                        | `PAIR_MIN_MAX_FIELDS`             |
| `{"s":…,"r":…}`  | s=配套计数, r=实际随机上限索引     | `SR_INDEX_FIELDS`（SequenceNo）   |
| `{"s":…,"r":…}`  | min/max，**且 s/r 顺序逐字段不同** | `SR_MIN_MAX_FIELDS`               |
| `{"x":…,"y":…}`  | **min/max**                       | `MIN_MAX_INT2_FIELDS`             |
| `{"x":…,"y":…}`  | 普通二元组                        | 其余                              |
| `{"X":…,"Y":…,"Z":…}` 或小写 | 三维向量               | `vec3()`                          |

⚠ 下面三张名单是 `blender_efx_re/model.py` 里同名常量的**镜像**——核心层不能 import 那个
文件（它要 import bpy）。`tests/test_sim_core.py` 有一条测试解析 `model.py` 断言两边一致；
将来往 `model.py` 的例外表里加字段而这边没跟上，那条测试会红。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from . import rng as _rng
from .state import Vec3

# -- 名单镜像（源头：blender_efx_re/model.py，由单测钉住一致性）--------------

#: `{s,r}` 但 s/r 不是静态/随机，是"配套计数(s) / 实际生效的随机上限索引(r)"。
SR_INDEX_FIELDS = frozenset({"SequenceNo"})

#: `{s,r}` 但实测是 min/max 范围。⚠ 两个字段的 s/r 顺序**相反**：
#: `PatternNo` / `PartsStartNo` 是 s=Max / r=Min，`PlaySpeed` 是 s=Min / r=Max。
#: （名单按字段名，不按类型——`PartsStartNo` 在 TypeMesh 和 TypeGpuMesh 里语义相同。）
SR_MIN_MAX_FIELDS = frozenset({"PatternNo", "PlaySpeed", "PartsStartNo"})

#: `SR_MIN_MAX_FIELDS` 里**上界取不到**（`[Min, Max)`）的那些，判据见 model.py 同名常量。
#: 只对整数字段有意义（浮点区间的开闭是零测度）。
HALF_OPEN_MAX_FIELDS = frozenset({"PatternNo", "PartsStartNo"})

#: `Int2{x,y}` 是 min/max 的那几个字段（其余 `{x,y}` 是普通二元组）。
MIN_MAX_INT2_FIELDS = frozenset({"SpawnNum", "IntervalFrame", "EmitterDelayFrame"})

#: `{s,r}` 但语义是 **(min, max)** 而不是 (静态值, 随机量) 的字段，键是 `(类型短名, 字段名)`。
#:
#: 必须按 (类型, 字段) 而不是裸字段名——`VanishFrame` 在 `Life` 上是 `RangeI`、在
#: `VanishArea3D` 上是 `Range`，裸名会误伤。
#:
#: 语料判据（`EfxBridge condstats`，91178 个 `Life` 实例）：四个字段**全部 100% 满足
#: `r <= s`，`r > s` 出现 0 次**。而同为 `RangeI` 的 `Spawn.LoopNum` 有 74.7% 是 `r > s`、
#: `Velocity3D.GravityDelayFrame` 有 9.6%——所以这不是 `RangeI` 的通性，是 `Life` 独有。
#: 非相等的取值对也长得像区间而不像"基值+浮动"：VanishFrame 的 `(30,40) (60,80) (80,100)
#: (100,120)`、KeepFrame 的 `(150,200)`。
#:
#: ⚠ **同概念不等于同语义**：`RgbCommon.*AppearFrame/KeepFrame/VanishFrame` 全族实测是
#: static/random（副值<主值 1 万~2 万例），`VanishArea3D.VanishFrame` 同理。这张表只收
#: 逐个查过的，不按名字外推。完整依据见 `model.py` 同名常量。
PAIR_MIN_MAX_FIELDS = frozenset({
    ("Life", "AppearFrame"),
    ("Life", "KeepFrame"),
    ("Life", "VanishFrame"),
    ("Life", "KeepHoldFrame"),
    # --- `EmitterShape3D` 的三个逐轴区间。2026-09-13 全语料定的，判据是**外边界是 `q`
    # 还是 `p+q`**（min+max vs MHWI 那种 min+offset），不是 static/random：
    #   `q < p` 0/62492，而主值非零的有 36590/20748/36840 例（58.6%/33.2%/59.0%）——
    #   min+offset 下 `q` 是**厚度**，半径 1.0 厚 0.1 的薄壳就该写成 `(1.0, 0.1)` 即 `q < p`，
    #   这种组合一次都没出现，等于说"从来没人做过半径大于厚度的壳"，讲不通。
    #   反过来看"厚度"：读作 min+max 时 `q-p == 0`（粒子正好落在壳面上）占 69.2%/33.3%/60.0%，
    #   是最常见的写法；读作 min+offset 时 `q == 0` 占 0.0%/11.1%/0.0%——没人做过纯表面
    #   发射器，每个都非得有个中位 0.5~1.0 的厚度，不成立。
    #   另有 Y 轴的对称负数对 `(-0.1,0.1)×588` `(-0.5,0.5)×507` `(-1,1)×489`：min+max 读作
    #   "以原点为中心上下对称"，min+offset 则要求作者恰好挑一个等于 |min| 的 offset，挑了 1584 次。
    ("EmitterShape3D", "RangeX"),
    ("EmitterShape3D", "RangeY"),

    ("EmitterShape3D", "RangeZ"),
    # --- 以下 13 个是 2026-09-13 用 `EfxBridge pairstats` + `tools/audit_range_fields.py`
    # 全语料排查出来的（223 个二元字段扫了一遍），此前一直被当成 (静态值, 随机量) 读。
    # 共同判据：**副值 < 主值 0 例**（min/max 的必要条件），且**"副值==主值且主值≠0"占比高**
    # ——static/random 下那等于"浮动幅度恰好等于基值"，不可能成规模。括号里是那个占比。
    #
    # ⚠ **必须按 (类型, 字段) 键**，这批里真有撞名的：`AngularVelocity3D.Radius`（1796 例）
    # 和 `PtVortexelPhysics.BounceRate`（2192 例）都是**确证的 static/random**，用裸字段名会
    # 把它们一起误伤。
    ("PtCollision", "Radius"),                       # 94.7%  (0.1,0.1)×869
    ("PtCollision", "BounceNum"),                    # 81.4%  (2,2) (1,1) (3,3) (2,3)
    ("PtCollision", "BounceRate"),                   # 70.0%  (0.1,0.1) (0.1,0.2)
    ("PlaneCollider", "BounceNum"),                  # 54.0%  (1,1) (1,2) (2,3)
    ("PlaneCollider", "BounceRate"),                 # 16.1%  (0.4,0.5) (0.5,0.8)
    ("PlaneCollider", "IdleTime"),                   # 12.6%  (10,10) (60,60) (500,500)
    ("UVSequenceModifier", "PlaySpeedInit"),         # 83.4%  (1,1) (2,2) (1.5,1.5)
    ("UVSequenceModifier", "PlaySpeedFinal"),        # 74.5%  (0.5,0.5) (0.3,0.3)
    ("UVSequenceModifier", "PlaySpeedChangeTimeCoef"),  # 93.4%  (0.97,0.97) (0.98,0.98)
    ("EmitterHSV", "Range1"),                        # 77.5%  (100,100) (100,650)
    ("EmitterHSV", "Range3"),                        # 75.0%  (100,100) (240,650)
    ("TexelChannelOperator", "Keep"),                # 26.3%  (20,60) (100,100) (0,5)
    ("TexelChannelOperator", "Vanish"),              # 73.7%  (80,80) (20,20)
    # --- `Attractor.ShapeRangeX/Y/Z`，2026-09-18 用户实机测试（依据见 model.py 同名常量）。
    ("Attractor", "ShapeRangeX"),
    ("Attractor", "ShapeRangeY"),
    ("Attractor", "ShapeRangeZ"),
})

_XYZ_UPPER = ("X", "Y", "Z")
_XYZ_LOWER = ("x", "y", "z")


def _primary_secondary(v):
    """`{s,r}` -> `(主值, 副值)`。主键按结构体类型选：`RangeI`(int) 是 `r`，`Range`(float)
    是 `s`（见模块说明）。

    类型判定：两个分量都是 `int` 就当 `RangeI`。走 Blender 那条路时类型来自
    `EFXValueNode.data_type`（`INT` -> Python int、`FLOAT` -> Python float），是权威的；
    走 JSON 那条路时靠 EfxBridge 把浮点写成 `1.0` 这种带小数点的形式来区分。
    """
    s, r = v["s"], v["r"]
    is_ranged_int = (isinstance(s, int) and isinstance(r, int)
                     and not isinstance(s, bool) and not isinstance(r, bool))
    return (r, s) if is_ranged_int else (s, r)


class FieldShapeError(ValueError):
    """字段的实际形状和调用方要求的读法对不上。

    **故意抛而不是静默退回默认值**：形状对不上说明 behavior 的假设错了（vendor 升级改了
    字段类型、或者抄错了字段名），静默容忍只会产出一个看起来正常、数值全错的预览。
    """


class FieldView(object):
    """一个 attribute 的字段 dict 的只读视图。

    `raw` 就是 `model.children_to_dict(attr_obj.efx_fields)` 的产物（也就是导出时喂给
    EfxBridge 的那份 dict，去掉 `$type`/`UniqueID`/`Version`/`type`/`IsTypeAttribute`）。
    """

    __slots__ = ("raw", "type_name")

    def __init__(self, raw, type_name=""):
        self.raw = raw or {}
        self.type_name = type_name

    # -- 基础 --------------------------------------------------------------
    def has(self, key):
        return key in self.raw

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def _need(self, key):
        v = self.raw.get(key)
        if v is None:
            raise FieldShapeError("%s 没有字段 %r" % (self.type_name or "<attr>", key))
        return v

    # -- 标量 --------------------------------------------------------------
    def f(self, key, default=0.0):
        """浮点标量。字段缺失或不是数值 → `default`。"""
        v = self.raw.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return float(default)
        return float(v)

    def i(self, key, default=0):
        """整数 / 枚举。枚举在 JSON 里是纯整数（实测），但对 `"RotationOrder_XYZ"` 这种
        字符串形式也容忍——取下划线后的部分解析不了就退回 `default`。"""
        v = self.raw.get(key)
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return int(default)
        return int(default)

    def b(self, key, default=False):
        v = self.raw.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        return bool(default)

    def s(self, key, default=""):
        v = self.raw.get(key)
        return v if isinstance(v, str) else default

    # -- 向量 --------------------------------------------------------------
    def vec3(self, key, default=None):
        """`{X,Y,Z}`（Vector3）或 `{x,y,z}`（Int3/PaddedVec3）→ `Vec3`。"""
        v = self.raw.get(key)
        if not isinstance(v, dict):
            if default is not None:
                return default.copy()
            raise FieldShapeError("%s.%s 不是三维向量: %r" % (self.type_name, key, v))
        for order in (_XYZ_UPPER, _XYZ_LOWER):
            if all(k in v for k in order):
                return Vec3(v[order[0]], v[order[1]], v[order[2]])
        if default is not None:
            return default.copy()
        raise FieldShapeError("%s.%s 的键不是 XYZ/xyz: %r" % (self.type_name, key, sorted(v)))

    # -- Range / RangeI ----------------------------------------------------
    def sr(self, key, default=(0.0, 0.0)):
        """`Range`/`RangeI` → `(static, random)`（**主值在前**，见 `_primary_secondary`）。

        字段在 `PAIR_MIN_MAX_FIELDS` / `SR_INDEX_FIELDS` / `SR_MIN_MAX_FIELDS` 里时**直接抛**
        ——那几类的 `{s,r}` 不是静态/随机，走 `min_max_pair()` / `sr_index()` / `sr_min_max()`。
        宁可炸也不静默按错误语义读。
        """
        if (self.type_name, key) in PAIR_MIN_MAX_FIELDS:
            raise FieldShapeError(
                "%s.%s 是 (min, max) 语义（全语料 r<=s 恒成立），不能按 static/random 读，"
                "用 min_max_pair()" % (self.type_name, key))
        if key in SR_INDEX_FIELDS:
            raise FieldShapeError(
                "%s.%s 是索引语义（s=配套计数 / r=随机上限索引），不能按 static/random 读，"
                "用 sr_index()" % (self.type_name, key))
        if key in SR_MIN_MAX_FIELDS:
            raise FieldShapeError(
                "%s.%s 是 min/max 语义，不能按 static/random 读，用 sr_min_max()"
                % (self.type_name, key))
        return self._sr_raw(key, default)

    def min_max_pair(self, key, default=(0.0, 0.0)):
        """`PAIR_MIN_MAX_FIELDS` 里的 `{s,r}` → `(min, max)`。主值即 min。"""
        if (self.type_name, key) not in PAIR_MIN_MAX_FIELDS:
            raise FieldShapeError(
                "%s.%s 不在 PAIR_MIN_MAX_FIELDS 里，`{s,r}` 默认是 (静态值, 随机量)，用 sr()"
                % (self.type_name, key))
        return self._sr_raw(key, default)

    def _sr_raw(self, key, default=(0.0, 0.0)):
        v = self.raw.get(key)
        if not isinstance(v, dict) or "s" not in v or "r" not in v:
            return (float(default[0]), float(default[1]))
        primary, secondary = _primary_secondary(v)
        return (float(primary), float(secondary))

    def sr_index(self, key):
        """`SequenceNo` 专用 → `(实际生效的随机上限索引, 配套计数)`。

        `SequenceNo` 是 `RangeI`，主值在 `r`——而 `model.py` 记的正是"`r` 才是实际生效的
        索引、`s` 疑似只是配套计数（全语料恒等于 `r+1`）"。和"主值 = 二进制首字段"自洽。
        """
        if key not in SR_INDEX_FIELDS:
            raise FieldShapeError("%s.%s 不在 SR_INDEX_FIELDS 里" % (self.type_name, key))
        return self._sr_raw(key)

    def roll_sr_min_max_int(self, key, rng):
        """`SR_MIN_MAX_FIELDS` 里的整数区间 -> 抽一个整数值，**上界开闭由名单说了算**。

        存在的意义就是不让"开闭"这件事散落到各个 behavior 里：`PatternNo` 的左闭右开原本是
        `uvsequence.py` 里一句光秃秃的 `hi - 1`，`PartsStartNo` 是同样的约定却还没有消费者
        ——下一个实现它的人拿 `sr_min_max()` 得到的是裸 `(min, max)`，几乎必然当闭区间用，
        静默偏一位。约定写在名单里、取样只此一条路，才不会再漂。
        """
        lo, hi = self.sr_min_max(key)
        lo = int(lo)
        hi = int(hi)
        if key in HALF_OPEN_MAX_FIELDS:
            hi -= 1          # `[lo, hi)` -> 闭区间取样器要的 `[lo, hi-1]`
        if hi <= lo:
            return lo        # 空区间 / 单值区间：退回下界，不抛
        return _rng.roll_uniform_int(lo, hi, rng)

    def sr_min_max(self, key):
        """`PatternNo` / `PlaySpeed` 专用 → `(min, max)`。

        **不需要逐字段翻转。** `model.py` 记的"`PatternNo` 是 s=Max/r=Min，`PlaySpeed` 是
        s=Min/r=Max，两者顺序相反"——那其实就是 `PatternNo` 是 `RangeI`（主值在 `r`）、
        `PlaySpeed` 是 `Range`（主值在 `s`）的表现，不是两套独立规则。**主值恒为 min。**
        已知的三个例外字段（`SequenceNo`/`PatternNo`/`PlaySpeed`）全部符合这条统一规律。
        """
        if key not in SR_MIN_MAX_FIELDS:
            raise FieldShapeError("%s.%s 不在 SR_MIN_MAX_FIELDS 里" % (self.type_name, key))
        return self._sr_raw(key)

    # -- Int2 --------------------------------------------------------------
    def xy(self, key, default=(0, 0)):
        """`Int2{x,y}` → `(x, y)`，不解释语义。"""
        v = self.raw.get(key)
        if not isinstance(v, dict) or "x" not in v or "y" not in v:
            return (default[0], default[1])
        return (v["x"], v["y"])

    def min_max(self, key, default=(0, 0)):
        """`Int2{x,y}` → `(min, max)`。只对 `MIN_MAX_INT2_FIELDS` 里的字段合法。

        ⚠ **不保证 `min <= max`**：语料里 max < min 真实存在（面板为此有崩溃风险提示），
        原样交出去，由调用方/`rng.roll_uniform_int` 处理，这里不静默交换。
        """
        if key not in MIN_MAX_INT2_FIELDS:
            raise FieldShapeError(
                "%s.%s 不在 MIN_MAX_INT2_FIELDS 里，`{x,y}` 不一定是 min/max，用 xy()"
                % (self.type_name, key))
        return self.xy(key, default)

    # -- 抽取（把 Range 变成一个具体值）-------------------------------------
    def roll(self, key, rng, mode=_rng.DIST_SYMMETRIC, default=(0.0, 0.0)):
        """`Range` → 抽一个浮点值。"""
        s, r = self.sr(key, default)
        return _rng.roll_static_random(s, r, rng, mode)

    def roll_int(self, key, rng, mode=_rng.DIST_SYMMETRIC, default=(0, 0)):
        """`RangeI` → 抽一个整数值。"""
        s, r = self.sr(key, default)
        return _rng.roll_static_random_int(s, r, rng, mode)

    def roll_min_max_int(self, key, rng, default=(0, 0)):
        """`Int2{x,y}` min/max → 抽一个整数值。"""
        lo, hi = self.min_max(key, default)
        return _rng.roll_uniform_int(lo, hi, rng)

    def roll_min_max_pair(self, key, rng, default=(0.0, 0.0)):
        """`PAIR_MIN_MAX_FIELDS` 里的 `{s,r}` min/max → 抽一个浮点值。"""
        lo, hi = self.min_max_pair(key, default)
        return _rng.roll_uniform(lo, hi, rng)

    def roll_min_max_pair_int(self, key, rng, default=(0, 0)):
        """`PAIR_MIN_MAX_FIELDS` 里的 `{s,r}` min/max → 抽一个整数值（`Life` 的帧数用这个）。"""
        lo, hi = self.min_max_pair(key, default)
        return _rng.roll_uniform_int(lo, hi, rng)

    def roll_vec3(self, key_x, key_y, key_z, rng, mode=_rng.DIST_SYMMETRIC):
        """三个 `Range` 字段合成一个向量（`Velocity3D.DirectionVectorX/Y/Z` 那种）。"""
        return Vec3(self.roll(key_x, rng, mode),
                    self.roll(key_y, rng, mode),
                    self.roll(key_z, rng, mode))

    def __repr__(self):
        return "<FieldView %s %d fields>" % (self.type_name or "?", len(self.raw))
