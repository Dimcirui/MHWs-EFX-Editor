# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/ribbonfollow.py —— `TypeRibbonFollow`（轨迹跟随条带：由粒子历史位置连成
的折线，姊妹项目 EFX-Editor（MHWI）"条带"三档——ribbonMode 0=轨迹跟随/1=定长面片/2=柔体链
——里的第一档，见 `ribbonlength.py` 模块说明。MHWs 这边同一个概念拆成了不同的属性类型：
`TypeRibbonFollow` 对应"轨迹跟随"，`TypeRibbonLength` 对应"定长面片"。

几何取自 `Particle.trail`（`Simulator` 逐帧记录，旧→新，见 `state.py`/`simulator.py`），
不是解析式算出来的——这是它和 `TypeRibbonLength` 唯一的本质区别，其余字段读法基本照抄
（`Width`/`SizeScalar`/`Color` 同 `ribbonlength.py`）。声明 `NEEDS_TRAIL = True` 打开
全局轨迹记录（见 `registry.Behavior.NEEDS_TRAIL` 的说明）。

字段判据（`EfxBridge fieldstats`，MHWs 全语料 1431 个实例）
------------------------------------------------------------
    SizeScalar/Width   Range   同 `TypeRibbonLength`：总体倍率 + 宽度，乘 `p.scale.x`
    Color/ColorRange   Color   染色模型同 `TypeBillboard3D`，P0 只取 `Color`

P0 只画等宽等色的原始折线
--------------------------
下面这些字段都还没有语料/实机验证过读法，猜错了比"没做"更容易误导人，P0 不猜、只记 note：

    ShapeDivision / SplineDivision
        实测两者**在 MHWilds 二进制里真的都会被读**——不是互斥的版本分支（`RszVersion
        (EfxVersion.RE3)` 生成的条件是 `>=` 不是 `==`，`SplineDivision` 的 `> RE3` 条件
        嵌在 `ShapeDivision` 的条件里面，两个字段紧挨着占用不同字节，都会落进 MHWilds 的
        二进制布局）。`ShapeDivision` 有丰富分布（0/1/2/3/5/6/8/10/20，0 占比 57%），
        `SplineDivision` 几乎恒为 0（1423/1431）。取值形状更像"每段之间插几个细分点"
        （0=不插值，直接用原始逐帧折线）而不是 `TypeRibbonLength` 那种"总顶点数"，但没有
        实机确认具体插值算法，不猜、不消费。
    StretchDistance
        `Vec2`。`.X` 的取值全部是次正规浮点数（`1E-45`/`3E-45`/…），和下面
        `TextureRepeatNum` 同一种指纹——大概率是整数按位重解释成了 float（vendor 声明
        类型和实际写入类型不一致）；`.Y` 取值倒像正常距离（1/2/4/5/8/10/20…），但两者的
        关联和各自具体语义都没有依据，整体不消费。
    FollowFlags
        字段名叫 Flags，但最常见取值 `3212836864` 按位重解释成 float 正好是 `-1.0`
        （`0xBF800000`，占 94%），少数样本是 `0.5`/`1.0`/`0.35`/`0.8` 的 float 位模式——
        声明成 `uint` 但实际按 float 写入，是另一处 vendor 声明/实际类型不一致（同
        `StretchDistance.X`）。语义未定，只在取值跳出最常见两档（`0`/`3212836864`）时 note。
    GhostStretch
        同 `TypeRibbonLength` 的处境：语义未定，只在非默认值（`(1.0, 0.0)`）时 note。
    HeadColor / ColorPlace1 / ColorPlace2 / ColorPlace1Ratio / ColorPlace2Ratio
    HeadScale / ScalePlace1 / ScalePlace2 / ScalePlace1Ratio / ScalePlace2Ratio
        同 `TypeRibbonLength` 的沿长度渐变家族，语义未定，不实现。
    FadeByTwistMin / FadeByTwistMax
        名字暗示按扭转角衰减透明度，`TypeRibbonLength` 没有这两个字段（RE3 才加，MHWs
        独有）。默认值 1.0（不衰减），非默认时 note。
    Unkn（RE8+ 新增，vendor 自己标了 `// TODO Check this`）
        语义完全未知，非零时 note。
    ColorRate / Intensity / AlphaRate / EdgeBlendRange / ShadowMultiplier / FadeSide /
    TextureRepeatNum / Flags / BlendFlags
        同 `TypeRibbonLength` 的处境：P0 只画纯色片，不做光照/边缘渐变/贴图重复/混合模式。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem

TYPE_NAME = "TypeRibbonFollow"

_UINT32_MAX = 0xFFFFFFFF

#: `FollowFlags` 按位重解释成 float 后最常见的两档（见模块说明）：`0` 和
#: `-1.0`（`0xBF800000` = `3212836864`）。只在取值跳出这两档时 note，否则 94%+4% 的
#: "正常"样本会把 note 面板刷屏。
_FOLLOW_FLAGS_COMMON = (0, 3212836864)

_NOT_CONSUMED_ALWAYS = ("ColorRate", "Intensity", "AlphaRate", "EdgeBlendRange",
                        "ShadowMultiplier", "FadeSide", "TextureRepeatNum")
_NOT_CONSUMED_GRADIENT = ("HeadColor", "ColorPlace1", "ColorPlace2",
                          "ColorPlace1Ratio", "ColorPlace2Ratio",
                          "HeadScale", "ScalePlace1", "ScalePlace2",
                          "ScalePlace1Ratio", "ScalePlace2Ratio")


def _unpack_rgba(raw):
    """同 `billboard3d.unpack_rgba`：`{"rgba": <uint32>}` -> `(r, g, b, a)`，低字节 R。"""
    raw = int(raw) & _UINT32_MAX
    return ((raw & 0xFF) / 255.0,
            ((raw >> 8) & 0xFF) / 255.0,
            ((raw >> 16) & 0xFF) / 255.0,
            ((raw >> 24) & 0xFF) / 255.0)


def _color_of(f, key, default=(1.0, 1.0, 1.0, 1.0)):
    v = f.get(key)
    if isinstance(v, dict) and "rgba" in v:
        return _unpack_rgba(v["rgba"])
    return default


@register(TYPE_NAME)
class TypeRibbonFollow(Behavior):
    """RENDER_BODY 阶段：产出 kind='RIBBON' 的轨迹跟随条带（几何取自 `p.trail`，见模块
    说明；不消费颜色/宽度渐变，全程等宽等色）。"""

    STAGE = RENDER_BODY
    ORDER = 100
    NEEDS_TRAIL = True

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        for key in ("Flags", "BlendFlags"):
            if f.i(key):
                em.note("TypeRibbonFollow.%s=%d 未参与模拟（疑似混合/形状变体，取值语义"
                        "未确认）" % (key, f.i(key)))
        for key in _NOT_CONSUMED_ALWAYS:
            if f.has(key):
                em.note("TypeRibbonFollow.%s 未参与模拟（P0 只画等宽等色的折线）" % key)
        for key in _NOT_CONSUMED_GRADIENT:
            if f.has(key):
                em.note("TypeRibbonFollow.%s 未参与模拟（沿长度的渐变未实现，语义未确认）"
                        % key)
        for key in ("ShapeDivision", "SplineDivision"):
            if f.i(key):
                em.note("TypeRibbonFollow.%s=%d 未参与模拟（疑似逐段细分数，语义未确认，"
                        "见模块说明）" % (key, f.i(key)))
        if f.has("StretchDistance"):
            em.note("TypeRibbonFollow.StretchDistance 未参与模拟（.X 疑似整数位模式被误读"
                    "成 float，语义未确认，见模块说明）")
        if f.has("FollowFlags") and f.i("FollowFlags") not in _FOLLOW_FLAGS_COMMON:
            em.note("TypeRibbonFollow.FollowFlags=%d 未参与模拟（疑似按位重解释成 float，"
                    "取值跳出常见两档，语义未确认）" % f.i("FollowFlags"))
        if f.has("GhostStretch") and f.sr("GhostStretch") != (1.0, 0.0):
            em.note("TypeRibbonFollow.GhostStretch 非默认值，未参与模拟（语义未确认）")
        for key in ("FadeByTwistMin", "FadeByTwistMax"):
            if f.has(key) and f.f(key, 1.0) != 1.0:
                em.note("TypeRibbonFollow.%s 非默认值，未参与模拟（语义未确认）" % key)
        if f.i("Unkn"):
            em.note("TypeRibbonFollow.Unkn=%d 未参与模拟（vendor 自己标了 TODO，语义"
                    "未知）" % f.i("Unkn"))

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        scalar = f.roll("SizeScalar", rng, mode, default=(1.0, 0.0))
        p.rolled["rf_width"] = f.roll("Width", rng, mode, default=(1.0, 0.0)) * scalar
        p.rolled["rf_color"] = _color_of(f, "Color")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item

        width = p.rolled.get("rf_width", 0.0) * p.scale.x
        col = p.rolled.get("rf_color", (1.0, 1.0, 1.0, 1.0))
        half = max(1e-5, 0.5 * width)

        #: `p.trail` 由 `Simulator` 每帧末尾追加，旧→新；新生成的粒子在它出生的这一帧
        #: 就已经有 1 个点（同一帧内先 spawn 后追加轨迹，见 simulator.py::step()）。少于
        #: 2 个点没法组成一条带（至少要有 base/tip 两端），复制当前点垫成零长度的退化条带，
        #: 不是留一个 None 让上层猜要不要画。
        trail = p.trail if len(p.trail) >= 2 else [p.pos, p.pos]
        points = [(pos.copy(), half, 1.0) for pos in trail]

        it = RenderItem(kind="RIBBON", pos=points[-1][0].copy())
        it.points = points
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
