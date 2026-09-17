# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/ribbonlength.py —— `TypeRibbonLength`（定长面片：从粒子位置沿固定方向
伸出的直条带，**不跟踪运动轨迹**）

姊妹项目 EFX-Editor（MHWI）把"条带"按来源分三档（`ribbonMode` 0=轨迹跟随/1=定长面片/
2=柔体链），MHWs 这边同一个概念被拆成了不同的属性类型；`TypeRibbonLength` 对应的正是
"定长面片"那一档——没有 `Life`/运动历史输入，几何完全由自身字段解析式给出：

    DirectionX/Y/Z   Range   伸展方向的分量（无量纲），读法同 `Velocity3D.DirectionVectorX/Y/Z`
                             （各自独立 roll 再合成向量，不是一次性的三维 Range）
    Length           Range   总长度（游戏单位）
    Width            Range   宽度（游戏单位）
    SizeScalar       Range   总体倍率，同时乘 Length 和 Width（同 `TypeBillboard3D.SizeScalar`）
    ShapeDivision    U32     条带的顶点数（同 EFX-Editor `subdivisionCount`："N 个顶点分
                             N-1 段"），P0 直接当顶点数用，不做 +1/-1 的猜测
    Color/ColorRange Color   染色模型同 `TypeBillboard3D`，P0 只取 `Color`

条带从粒子位置沿 `Direction` 伸出，**P0 假设生成点是尾端**（`points[0]`），头部在
`+Direction` 方向；长度/宽度乘 `p.scale.y`/`p.scale.x`——同 EFX-Editor `ribbon.py::_dims()`
的 X=width/Y=length 约定（`ScaleAnim` 还没实现，现在恒为 1，先接好这个乘法，等它上线就是
现成的）。

P0 只画等宽等色的直条带
-----------------------
下面这些字段都还没有语料/实机验证过读法，猜错了比"没做"更容易误导人，P0 不猜、只记 note：

    HeadColor / ColorPlace1 / ColorPlace2 / ColorPlace1Ratio / ColorPlace2Ratio
        看名字像沿长度的颜色渐变（头部色 + 两个中间锚点色 + 各自的位置比例），但具体怎么
        插值、Ratio 的取值范围是不是 [0,1]，没有依据，不实现。
    HeadScale / ScalePlace1 / ScalePlace2 / ScalePlace1Ratio / ScalePlace2Ratio
        同上，疑似沿长度的宽度渐变（锥形/纺锤形条带）。
    BasingPoint / ReleaseFixEnd / GhostStretch
        疑似生成点锚位 / 脱离时定住末端 / 拉伸相关，语义未定。
    ColorRate / Intensity / AlphaRate / EdgeBlendRange / ShadowMultiplier / FadeSide /
    TextureRepeatNum
        同 `TypeBillboard3D` 的处境：P0 只画纯色片，不做光照/边缘渐变/贴图重复。
    Flags / BlendFlags / LengthFlags
        疑似混合模式/形状变体位标，取值语义未确认，`blend` 恒为 `ALPHA`。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3

TYPE_NAME = "TypeRibbonLength"

_UINT32_MAX = 0xFFFFFFFF

#: 语料/实机都没验过 Ratio 到底怎么读，但几何（direction/length/width/division）已经足够
#: 确定，先把定长直条带接上——不consumed 的字段名单见模块说明。
_NOT_CONSUMED_ALWAYS = ("ColorRate", "Intensity", "AlphaRate", "EdgeBlendRange",
                        "ShadowMultiplier", "FadeSide", "TextureRepeatNum")
_NOT_CONSUMED_GRADIENT = ("HeadColor", "ColorPlace1", "ColorPlace2",
                          "HeadScale", "ScalePlace1", "ScalePlace2")


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
class TypeRibbonLength(Behavior):
    """RENDER_BODY 阶段：产出 kind='RIBBON' 的定长直条带（几何见模块说明；不消费颜色/宽度
    渐变，两端等宽等色）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        for key in ("Flags", "BlendFlags", "LengthFlags"):
            if f.i(key):
                em.note("TypeRibbonLength.%s=%d 未参与模拟（疑似混合/形状变体，取值语义"
                        "未确认）" % (key, f.i(key)))
        for key in _NOT_CONSUMED_ALWAYS:
            if f.has(key):
                em.note("TypeRibbonLength.%s 未参与模拟（P0 只画等宽等色的直条带）" % key)
        for key in _NOT_CONSUMED_GRADIENT:
            if f.has(key):
                em.note("TypeRibbonLength.%s 未参与模拟（沿长度的渐变未实现，语义未确认）"
                        % key)
        for key in ("BasingPoint", "ReleaseFixEnd", "GhostStretch"):
            if f.has(key) and f.sr(key) != (0.0, 0.0):
                em.note("TypeRibbonLength.%s 非默认值，未参与模拟（语义未确认）" % key)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        scalar = f.roll("SizeScalar", rng, mode, default=(1.0, 0.0))
        p.rolled["rl_length"] = f.roll("Length", rng, mode, default=(1.0, 0.0)) * scalar
        p.rolled["rl_width"] = f.roll("Width", rng, mode, default=(1.0, 0.0)) * scalar
        p.rolled["rl_dir"] = f.roll_vec3("DirectionX", "DirectionY", "DirectionZ",
                                         rng, mode).normalized(fallback=Vec3(0.0, 1.0, 0.0))
        p.rolled["rl_n"] = max(2, f.i("ShapeDivision", 2))
        p.rolled["rl_color"] = _color_of(f, "Color")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item

        length = p.rolled.get("rl_length", 0.0) * p.scale.y
        width = p.rolled.get("rl_width", 0.0) * p.scale.x
        direction = p.rolled.get("rl_dir", Vec3(0.0, 1.0, 0.0))
        n = p.rolled.get("rl_n", 2)
        col = p.rolled.get("rl_color", (1.0, 1.0, 1.0, 1.0))

        half = max(1e-5, 0.5 * width)
        step = direction * (length / (n - 1))
        base = p.pos
        points = [(base + step * i, half, 1.0) for i in range(n)]

        it = RenderItem(kind="RIBBON", pos=points[-1][0].copy())
        it.points = points
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
