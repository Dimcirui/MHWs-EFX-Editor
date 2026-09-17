# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/gpuribbonlength.py —— `TypeGpuRibbonLength`（GPU 批量渲染的定长直条带）

字段是 `TypeRibbonLength` 的子集——`P0 只画等宽等色直条带`那批已经没消费的字段
（`LengthFlags`/`ReleaseFixEnd`/`HeadColor`/`ColorPlace1-2`/`HeadScale`/`ScalePlace1-2`/
`GhostStretch`/`ShadowMultiplier`/`FadeSide`）在这边压根不存在，几何/染色照抄
`ribbonlength.py` 的读法（`SizeScalar`/`Width`/`Length`/`ShapeDivision`/`DirectionX-Y-Z`/
`Color`/`ColorRange`）。

`ParticleNum` 不是逐粒子倍数
-----------------------------
语料实测（`fieldstats`，3161 个实例）：`ParticleNum` 取值跨度巨大——`100/128/256/512/1024/
2048/4096/8192/13000/20000` 都是高频值，一大批还是 2 的幂。这和 `TypeGpuPolygon` 那边
79% 恒为 0、其余多是个位数的分布完全不同类；两边合起来看，比"逐粒子画 N 份"更像 **GPU 侧
的粒子缓冲区容量**（预分配多大的顶点/实例缓冲，常见做法是取 2 的幂）——真实粒子数仍由
`Spawn`/`EmitterShape3D`/`Life`/`Velocity3D` 决定（同批语料里这四个属性和
`TypeGpuRibbonLength` 的文件级共现率 ≥99.8%）。**这仍然是推断，不是实机确认**，P0 不消费、
只 note。

`BasingPoint`/`Flags`/`BlendFlags`/`TextureRepeatNum` 同 `ribbonlength.py` 的处境：语义
未确认，不消费。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3

TYPE_NAME = "TypeGpuRibbonLength"

_UINT32_MAX = 0xFFFFFFFF


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
class TypeGpuRibbonLength(Behavior):
    """RENDER_BODY 阶段：产出 kind='RIBBON' 的定长直条带，几何读法同 `TypeRibbonLength`。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        for key in ("Flags", "BlendFlags"):
            if f.i(key):
                em.note("TypeGpuRibbonLength.%s=%d 未参与模拟（疑似混合/形状变体，取值语义"
                        "未确认）" % (key, f.i(key)))
        if f.i("ParticleNum"):
            em.note("TypeGpuRibbonLength.ParticleNum=%d 未参与模拟（疑似 GPU 侧缓冲区容量，"
                    "不是逐粒子实例数，见模块说明）" % f.i("ParticleNum"))
        for key in ("ColorRate", "Intensity", "AlphaRate", "EdgeBlendRange",
                    "TextureRepeatNum"):
            if f.has(key):
                em.note("TypeGpuRibbonLength.%s 未参与模拟（P0 只画等宽等色的直条带）" % key)
        if f.has("BasingPoint") and f.sr("BasingPoint") != (0.0, 0.0):
            em.note("TypeGpuRibbonLength.BasingPoint 非默认值，未参与模拟（语义未确认）")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        scalar = f.roll("SizeScalar", rng, mode, default=(1.0, 0.0))
        p.rolled["grl_length"] = f.roll("Length", rng, mode, default=(1.0, 0.0)) * scalar
        p.rolled["grl_width"] = f.roll("Width", rng, mode, default=(1.0, 0.0)) * scalar
        p.rolled["grl_dir"] = f.roll_vec3("DirectionX", "DirectionY", "DirectionZ",
                                          rng, mode).normalized(fallback=Vec3(0.0, 1.0, 0.0))
        p.rolled["grl_n"] = max(2, f.i("ShapeDivision", 2))
        p.rolled["grl_color"] = _color_of(f, "Color")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item

        length = p.rolled.get("grl_length", 0.0) * p.scale.y
        width = p.rolled.get("grl_width", 0.0) * p.scale.x
        direction = p.rolled.get("grl_dir", Vec3(0.0, 1.0, 0.0))
        n = p.rolled.get("grl_n", 2)
        col = p.rolled.get("grl_color", (1.0, 1.0, 1.0, 1.0))

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
