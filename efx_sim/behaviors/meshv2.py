# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/meshv2.py —— `TypeMeshV2`（宿主绑定的 `.mesh`，对照 EFX-Editor 的 MESH）

分工同 EFX-Editor 的 `efx_format/sim/behaviors/mesh.py`：**核心层拿不到几何**——`.mesh` 的
顶点数据在 Blender 场景里（`blender_efx_re/asset_link.py` 的"一并导入引用的网格"选项已经把
它导进来、挂到这个 attribute 所属的 Entry 下面）。本 behavior 只产出「在这个位置、按这个
变换、用这个颜色，画绑在这个 Entry 下面的网格」，具体去哪找、怎么画交给胶水层
（`sim_preview.py`）：

    item.kind = 'MESH'
    item.pos                       出生位置（游戏坐标系，米）
    item.size                      逐轴缩放（游戏坐标系，**不是**像素/角度单位）
    item.extra['rot']              (RotationX, RotationY, RotationZ)，弧度，游戏坐标系
    item.extra['rot_order']        `RotationOrder` 的原始枚举值（未转换），胶水层直接喂给
                                    `coords.local_matrix_to_blender()`——那边已经全权处理
                                    game->Blender 的基变换，核心层不重复做一遍
    item.extra['emissive']         自发光色 RGB（已乘 EmissiveRate），胶水层按加法叠上底色

这条分界和 `billboard3d.py` 一样干净：核心只说"画什么、在哪"，胶水层知道"怎么画"。
没有绑定网格时，胶水层画一个占位框（同 EFX-Editor MESH 的约定）。

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `TypeMesh`，TypeID 30，
完整类名 `EFXAttributeTypeMeshV2`）

P0 只做刚体变换 + 单层染色
--------------------------
`MaxPartsNum`/`PartsStartNo`/`PlaySpeed`/`PlaySpeedCoef`/`PlayType`/`PlayOrder` 是一套
"网格分段播放"系统（同 `UVSequence` 但驱动的是网格的哪一段可见，而不是贴图的哪一帧），
`asset_link.py` 目前只是把整份 `.mesh` 导进来、不区分段——没有"第 N 段对应哪个 Blender
对象"这层映射，P0 不猜，画整份网格、记 note。`FrontAxis`（AxisXYZ）疑似决定
RotationX/Y/Z 作用前的基准朝向，但网格本身就有完整三轴旋转（不像 `TypePolygon` 那种只有
一个法线要摆），直接对局部坐标系整体做欧拉旋转已经是完整的三自由度，`FrontAxis` 的角色
不确定，不消费、记 note。`Flags`/`Flags2`（疑似混合/渲染模式位）、`WildsUknFloat` 同样
不消费。

`RotateAnim` 叠加
-----------------
`RotateAnim`（若存在）逐帧往 `p.rot` 上加角度（见 `rotateanim.py`）。`item.extra['rot']`
在静态 RotationX/Y/Z 上直接加 `p.rot` 的对应分量再交给胶水层——胶水层本来就是每个粒子
每帧都重新拼一次 `coords.local_matrix_to_blender()`，这里不需要 `TypePolygon` 那种
"只在有 RotateAnim 时才逐帧重算"的优化（那是为了省掉核心层自己的 `rotate_euler` 调用，
MeshV2 的旋转合成本来就在胶水层，核心层只是把两个角度加一下）。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3

TYPE_NAME = "TypeMeshV2"

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
class TypeMeshV2(Behavior):
    """RENDER_BODY 阶段：产出 kind='MESH'，几何由胶水层从绑定对象取（见模块说明）。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        em.note("TypeMeshV2 的几何来自 asset_link.py 绑定的网格；未绑定/没装 RE Mesh Editor "
                "时预览只画一个占位框")
        if f.i("MaxPartsNum") > 1:
            em.note("TypeMeshV2.MaxPartsNum=%d：网格分段播放未模拟，预览画整份网格"
                    % f.i("MaxPartsNum"))
        if f.i("Flags"):
            em.note("TypeMeshV2.Flags=%d 未参与模拟（疑似混合/渲染模式，取值语义未确认）"
                    % f.i("Flags"))
        if f.i("Flags2"):
            em.note("TypeMeshV2.Flags2=%d 未参与模拟（取值语义未确认）" % f.i("Flags2"))
        if f.has("FrontAxis"):
            em.note("TypeMeshV2.FrontAxis 未参与模拟（网格本身已有完整三轴旋转，这个字段"
                    "的具体作用未确认）")

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist

        p.rolled["mv_rot"] = (f.roll("RotationX", rng, mode), f.roll("RotationY", rng, mode),
                              f.roll("RotationZ", rng, mode))
        p.rolled["mv_rot_order"] = f.i("RotationOrder")

        scalar = f.roll("ScaleMultiplier", rng, mode, default=(1.0, 0.0))
        p.rolled["mv_scale"] = Vec3(f.roll("ScaleX", rng, mode, default=(1.0, 0.0)) * scalar,
                                    f.roll("ScaleY", rng, mode, default=(1.0, 0.0)) * scalar,
                                    f.roll("ScaleZ", rng, mode, default=(1.0, 0.0)) * scalar)

        rate = f.f("ColorRate", 1.0)
        r0, g0, b0, a0 = _color_of(f, "Color")
        p.rolled["mv_color"] = (r0 * rate, g0 * rate, b0 * rate, a0)

        erate = f.f("EmissiveRate", 1.0)
        er, eg, eb, _ea = _color_of(f, "EmissiveColor", default=(0.0, 0.0, 0.0, 0.0))
        p.rolled["mv_emissive"] = (er * erate, eg * erate, eb * erate)

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item
        rx, ry, rz = p.rolled.get("mv_rot", (0.0, 0.0, 0.0))
        scale = p.rolled.get("mv_scale", Vec3(1.0, 1.0, 1.0))
        col = p.rolled.get("mv_color", (1.0, 1.0, 1.0, 1.0))
        emissive = p.rolled.get("mv_emissive", (0.0, 0.0, 0.0))

        it = RenderItem(kind="MESH", pos=p.pos.copy(),
                        size=Vec3(scale.x * p.scale.x, scale.y * p.scale.y,
                                  scale.z * p.scale.z))
        it.extra["rot"] = (rx + p.rot.x, ry + p.rot.y, rz + p.rot.z)
        it.extra["rot_order"] = p.rolled.get("mv_rot_order", 0)
        it.extra["emissive"] = emissive
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
