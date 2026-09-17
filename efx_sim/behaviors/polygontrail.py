# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/polygontrail.py —— `TypePolygonTrail`（固定朝向的"刀光"：从粒子位置沿
entry 自身的一根固定轴伸出的直条带，**不朝相机**——这是它和 `TypeRibbonLength`/
`TypeRibbonFollow` 的本质区别，见下）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `TypePolygonTrail`，TypeID 73）。
全语料只有 **35 个实例**（`EfxBridge fieldstats`，扫了 9175 个文件），没有对应的 010
模板注释可抄（`mhws_field_labels_mined.json` 里这个类型是空的）——这是本仓迄今为止证据
最薄的一个渲染体实现，下面逐项标出"结构上能确定"和"纯粹猜的"。

结构上能确定（字段名 + 类型 + vendor 枚举，不是猜）
--------------------------------------------------
    Axis     S32(AxisType)   固定轴：0=+X 1=+Y 2=+Z 3=-X 4=-Y 5=-Z（`EFXEnums.cs`，
                             无歧义）。全语料分布 5(17)/0(7)/2(6)/1(4)/3(1)，六档里
                             五档都出现过，是个真的在用的方向选择，不是摆设。
    Length   Range           总长度（游戏单位）。`.r` 全语料 35/35 恒为 0——这个字段在
                             实践中几乎总是"静态值"，但读法仍按标准 Range 处理
                             （`roll()`），不写死成纯标量。
    Color/ColorRange         染色模型同 `TypeBillboard3D`，P0 只取 `Color`。

**"不朝相机"这一点是本仓这次唯一敢下的结构判断，依据是命名对照**：`Axis` 是一个
**固定的三维方向枚举**（entry 局部空间），不是"抽一个方向"（`TypeRibbonLength.
DirectionX/Y/Z`）也不是"跟踪历史轨迹"（`TypeRibbonFollow`）——"Polygon"（对照
`TypePolygon` 明确"不朝相机"）而不是"Ribbon"这个命名本身就在暗示这一档不走
`TypeRibbonLength`/`TypeRibbonFollow` 那套"横向 = 段方向 × 相机视线"的billboard 公式。
但当前 `RenderItem(kind="RIBBON")` 这条渲染路径（`_collect_ribbon()`）只有"billboard
朝向相机"这一种实现，**没有"固定朝向的多段带"这个渲染原语**——P0 暂时借用同一条
`RIBBON` 路径（几何退化成 2 个点、直线，不是真的多段刀光），代价是这一档目前**其实还是
朝向相机**，没有实现"不朝相机"这个结构判断，如实记在这里，不是忘了。

纯粹猜的（没有任何依据，P0 不实现，只 note）
--------------------------------------------
    NumTrailDivision / NumVerticalDivision / NumSplineDivision
        全语料都有分布（1~10 / 0~3 / 0~5），像是"沿长度切几段 / 沿宽度切几段 / 额外
        样条细分"，但没有实机数据能验证具体插值/弯曲算法，P0 只画一条直线（2 个点），
        不猜怎么用这些细分数。
    StretchDistance
        F32，取值 {1,3,6,10,20}。曾怀疑是"宽度"，但语料里它常常**大于** `Length`
        （比如 `Length=0.1` 配 `StretchDistance=3`），拿它当宽度会画出"比刀光本身还宽"
        的怪形状——不像一个正常的"trail 宽度"该有的量级关系，所以不采纳这个猜测，
        按未知处理。
    IntervalFrame
        全语料恒为 1，没有变化，无法从取值分布反推语义，不实现。
    Flags / re4_unkn / ColorRate / Intensity / EdgeBlendRate / AlphaRate
        同 `TypeRibbonLength`/`TypeRibbonFollow` 的处境：P0 只画纯色片，不做光照/
        混合模式/边缘渐变。
    HeadColor / Place1 / Place2 / Place1Ratio / Place2Ratio
        同 `TypeRibbonLength` 的沿长度渐变家族，语义未定，不实现。

**宽度没有任何字段可用**（`TypePolygonTrail` 不像 `TypeRibbonLength` 那样有独立的
`Width` 字段）。P0 用 `_FALLBACK_WIDTH_RATIO * length` 撑出一个看得见的宽度——这是纯
**显示占位**，不是从任何字段读出来的，和 `simulator.FALLBACK_SIZE`（退化点的显示尺寸）
同一个性质：没有更好的数据，先让它在预览里"看得见、形状大致对"，不假装知道真实宽度。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3

TYPE_NAME = "TypePolygonTrail"

_UINT32_MAX = 0xFFFFFFFF

#: `AxisType`（vendor `EFXEnums.cs`）：0=+X 1=+Y 2=+Z 3=-X 4=-Y 5=-Z，无歧义。
_AXIS_VECS = {
    0: Vec3(1.0, 0.0, 0.0), 1: Vec3(0.0, 1.0, 0.0), 2: Vec3(0.0, 0.0, 1.0),
    3: Vec3(-1.0, 0.0, 0.0), 4: Vec3(0.0, -1.0, 0.0), 5: Vec3(0.0, 0.0, -1.0),
}

#: 宽度没有确认字段，纯显示占位（见模块说明）：宽度 = 长度 × 这个比例。
_FALLBACK_WIDTH_RATIO = 0.15

_NOT_CONSUMED_ALWAYS = ("ColorRate", "Intensity", "EdgeBlendRate", "AlphaRate")
_NOT_CONSUMED_GRADIENT = ("HeadColor", "Place1", "Place2", "Place1Ratio", "Place2Ratio")
_NOT_CONSUMED_DIVISION = ("NumTrailDivision", "NumVerticalDivision", "NumSplineDivision")


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
class TypePolygonTrail(Behavior):
    """RENDER_BODY 阶段：产出 kind='RIBBON' 的直线刀光（几何是退化的 2 点直线，见模块
    说明的"借用 RIBBON 路径"那段——目前其实还是朝向相机，不是真正固定朝向）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        if f.i("Flags"):
            em.note("TypePolygonTrail.Flags=%d 未参与模拟（疑似混合/形状变体，取值语义"
                    "未确认）" % f.i("Flags"))
        if f.i("re4_unkn"):
            em.note("TypePolygonTrail.re4_unkn=%d 未参与模拟（语义未知）" % f.i("re4_unkn"))
        for key in _NOT_CONSUMED_ALWAYS:
            if f.has(key):
                em.note("TypePolygonTrail.%s 未参与模拟（P0 只画等宽等色的直条带）" % key)
        for key in _NOT_CONSUMED_GRADIENT:
            if f.has(key):
                em.note("TypePolygonTrail.%s 未参与模拟（沿长度的渐变未实现，语义未确认）"
                        % key)
        for key in _NOT_CONSUMED_DIVISION:
            if f.i(key):
                em.note("TypePolygonTrail.%s=%d 未参与模拟（疑似细分数，没有实机数据"
                        "验证插值/弯曲算法，P0 只画一条直线）" % (key, f.i(key)))
        if f.f("StretchDistance"):
            em.note("TypePolygonTrail.StretchDistance=%g 未参与模拟（曾疑为宽度，但常见"
                    "取值比 Length 还大，量级不对，按未知处理）" % f.f("StretchDistance"))
        em.note("TypePolygonTrail 目前借用 RIBBON 的朝相机 billboard 几何——按字段命名"
                "推断这一档本该是固定朝向（同 TypePolygon 与 TypeBillboard3D 的区别），"
                "还没实现真正的固定朝向渲染，见模块说明")
        em.note("TypePolygonTrail.宽度 没有任何字段可用，预览按 Length 的固定比例"
                "撑出一个显示用的宽度，不代表真实宽度")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        p.rolled["pt_length"] = f.roll("Length", rng, mode, default=(1.0, 0.0))
        p.rolled["pt_axis"] = _AXIS_VECS.get(f.i("Axis"), _AXIS_VECS[2])
        p.rolled["pt_color"] = _color_of(f, "Color")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item

        length = p.rolled.get("pt_length", 0.0) * p.scale.y
        axis = p.rolled.get("pt_axis", Vec3(0.0, 0.0, 1.0))
        col = p.rolled.get("pt_color", (1.0, 1.0, 1.0, 1.0))

        half = max(1e-5, 0.5 * length * _FALLBACK_WIDTH_RATIO)
        tip = p.pos + axis * length
        points = [(p.pos.copy(), half, 1.0), (tip, half, 1.0)]

        it = RenderItem(kind="RIBBON", pos=points[-1][0].copy())
        it.points = points
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
