# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/billboard3d.py —— `TypeBillboard3D`（面朝相机的片，P0 唯一的渲染主体）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `TypeBillboard3D`，TypeID 25）：

    Color / ColorRange   Color   打包成 `{"rgba": <uint32>}`，低字节是 R
    SizeX / SizeY        Range   出生时的初始尺寸（米）
    SizeScalar           Range   整体尺寸倍率
    Rotation             Range   出生时的初始自转，**弧度**
    Offset               Range   P0 不消费
    ColorRate / Intensity / AlphaRate / EdgeBlendRange / Flags / ShadowType / …  P0 不消费

它占全语料渲染主体的大头（3.39%，7 个 ribbon 变体加起来才 1.49%），所以 P0 只做它一个就
能覆盖大多数文件的视觉主体。

P0 只画纯色四边形
-----------------
不贴图、不读 `Flags` 的混合模式。贴图那条链（`UVSequence` + `UVSPath` + `EfxBridge tex2dds`）
是 P1 的事；`Flags` 的取值语义标的是 guess（"疑似是混合类型 BlendType"），不猜。
`blend` 恒为 `ALPHA`，并在有非默认 `Flags` 时 note 一条。

`Color` 的解包顺序照抄 `model._get_rgba_color()`（低字节 R、高字节 A），两边必须一致——
面板上显示的颜色和预览里画出来的颜色不是一回事的话，用户没法据此调色。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3

TYPE_NAME = "TypeBillboard3D"

_UINT32_MAX = 0xFFFFFFFF


def unpack_rgba(raw):
    """`{"rgba": <uint32>}` 的那个整数 -> `(r, g, b, a)`，各 0..1。

    顺序和 `blender_efx_re/model.py::_get_rgba_color()` 一致（低字节 R）。改这里必须同步改
    那边，否则面板显示的颜色和预览画出来的不是一个颜色。
    """
    raw = int(raw) & _UINT32_MAX
    return ((raw & 0xFF) / 255.0,
            ((raw >> 8) & 0xFF) / 255.0,
            ((raw >> 16) & 0xFF) / 255.0,
            ((raw >> 24) & 0xFF) / 255.0)


def _color_of(f, key, default=(1.0, 1.0, 1.0, 1.0)):
    v = f.get(key)
    if isinstance(v, dict) and "rgba" in v:
        return unpack_rgba(v["rgba"])
    return default


@register(TYPE_NAME)
class TypeBillboard3D(Behavior):
    """RENDER_BODY 阶段：产出一个面朝相机的四边形。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        if f.i("Flags"):
            em.note("TypeBillboard3D.Flags=%d 未参与模拟（疑似混合类型，取值语义未确认）"
                    % f.i("Flags"))
        if f.sr("Offset") != (0.0, 0.0):
            em.note("TypeBillboard3D.Offset 非 0，未参与模拟")
        for key in ("ColorRate", "Intensity", "AlphaRate", "EdgeBlendRange"):
            if f.has(key):
                em.note("TypeBillboard3D.%s 未参与模拟（P0 只画纯色片）" % key)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        scalar = f.roll("SizeScalar", rng, mode, default=(1.0, 0.0))
        p.rolled["bb_size"] = Vec3(f.roll("SizeX", rng, mode, default=(1.0, 0.0)) * scalar,
                                   f.roll("SizeY", rng, mode, default=(1.0, 0.0)) * scalar,
                                   1.0)
        p.rolled["bb_rot"] = f.roll("Rotation", rng, mode)

        # ColorRange 的语义（是"另一端颜色、在两者间随机"还是别的）没有实测，P0 只用
        # Color；两个值都存着，等标定时直接拿来对拍。
        p.rolled["bb_color"] = _color_of(f, "Color")
        p.rolled["bb_color_range"] = _color_of(f, "ColorRange")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item
        size = p.rolled.get("bb_size", Vec3(1.0, 1.0, 1.0))
        col = p.rolled.get("bb_color", (1.0, 1.0, 1.0, 1.0))

        it = RenderItem(kind="BILLBOARD", pos=p.pos.copy(),
                        size=Vec3(size.x * p.scale.x, size.y * p.scale.y, 1.0),
                        rot=p.rolled.get("bb_rot", 0.0))
        # p.color / p.alpha 是别的属性（Life 的淡入淡出、将来的 RgbCommon）写的调制量，
        # 乘在渲染体自己的基色上。
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
