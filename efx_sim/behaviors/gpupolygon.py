# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/gpupolygon.py —— `TypeGpuPolygon`（GPU 批量渲染的固定朝向片）

字段几乎和 `TypePolygon` 一模一样（几何/染色/朝向模型照抄那边），差两处：

    没有 `RotationOrder` 字段
        全语料实测确认（`fieldstats` 对 588 个实例，字段压根不存在）。旋转顺序照
        `vecmath.DEFAULT_ROTATION_ORDER`（"ZXY"，语料里非 GPU 类型 98%+ 走这个默认档）。
    多一个 `ParticleNum`（U32）
        **不是"这一个粒子画成 N 份"**——语料证据：`TypeGpuPolygon.ParticleNum` 588 个实例里
        79%（465 个）恒为 **0**，其余多是 1/2/4/5/8/10/24/32/40 这种小数；同一批语料里这个
        entry 的 `Spawn`/`EmitterShape3D`/`Life`/`Velocity3D` 全部齐全（256/256 file 级
        共现），说明真正的粒子数量/位置/寿命/运动照旧走 CPU 侧那套管线，`ParticleNum`
        更像是 GPU 侧一个和渲染量无关的旁路参数（对照 `TypeGpuRibbonLength` 那边同名字段
        的取值规律，见 `gpuribbonlength.py` 模块说明——两边合起来看更像"GPU 缓冲区容量/
        批处理提示"而不是逐粒子倍数，但没有实机对拍，P0 不消费、只 note）。

朝向模型（法线 = 固定轴 + 欧拉旋转，`OrientDirectionUpVector` 只喂 up 参考）同 `polygon.py`
——那边模块说明记着这次纠正的实机依据（`[029] partical_4` 的真机对拍），这里不重复贴一遍，
只提示：**这条纠正对 `TypeGpuPolygon` 同样适用**，纠正前的假设就是从这个类型的真实样本
（该实体本身就是 `TypeGpuPolygon`）反推出来的，不是从 `TypePolygon` 类比过来再没验证。

其余字段（`BlendFlags`/`Color`/`ColorRange`/`ColorRate`/`Intensity`/`EdgeBlendRate`/
`AlphaRate`/`Flags`）的映射和不消费清单同 `polygon.py`（`EdgeBlendRate` 只是改了名，语义
一致）。`RotateAnim` 叠加的读法也同 `polygon.py`（静态角 + `p.rot` 逐分量相加，只是旋转
顺序固定用 `DEFAULT_ROTATION_ORDER`，因为这个类型没有自己的 `RotationOrder` 字段）。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem, Vec3
from ..vecmath import DEFAULT_ROTATION_ORDER, rotate_euler

TYPE_NAME = "TypeGpuPolygon"

_UINT32_MAX = 0xFFFFFFFF

#: 法线的静止基准（game 坐标系），同 `polygon._REST_NORMAL`。
_REST_NORMAL = Vec3(0.0, 0.0, -1.0)

#: `AxisXYZ`：0=X 1=Y 2=Z。喂给 `_oriented_basis()` 当 up 参考（不是基准法线）。
_AXIS_VECS = {0: Vec3(1.0, 0.0, 0.0), 1: Vec3(0.0, 1.0, 0.0), 2: Vec3(0.0, 0.0, 1.0)}


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


def _oriented_basis(normal, up_hint):
    """同 `polygon._oriented_basis()`：`up_hint` 优先，退化时依次回落 Z、X。"""
    n = normal.normalized(fallback=_REST_NORMAL)
    ref = up_hint.normalized(fallback=Vec3(0.0, 1.0, 0.0))
    if abs(n.dot(ref)) > 0.99:
        ref = Vec3(0.0, 0.0, 1.0)
        if abs(n.dot(ref)) > 0.99:
            ref = Vec3(1.0, 0.0, 0.0)
    u = ref.cross(n).normalized(fallback=Vec3(1.0, 0.0, 0.0))
    v = n.cross(u).normalized(fallback=Vec3(0.0, 0.0, 1.0))
    return u, v


@register(TYPE_NAME)
class TypeGpuPolygon(Behavior):
    """RENDER_BODY 阶段：产出 kind='PLANE' 的固定朝向面片，读法同 `TypePolygon`。"""

    STAGE = RENDER_BODY
    ORDER = 100

    _has_rotate = False

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        self._has_rotate = em.f("RotateAnim") is not None
        if f.i("Flags"):
            em.note("TypeGpuPolygon.Flags=%d 未参与模拟（疑似混合类型，取值语义未确认）"
                    % f.i("Flags"))
        if f.i("BlendFlags"):
            em.note("TypeGpuPolygon.BlendFlags=%d 未参与模拟（取值语义未确认）"
                    % f.i("BlendFlags"))
        if f.i("ParticleNum"):
            em.note("TypeGpuPolygon.ParticleNum=%d 未参与模拟（疑似 GPU 侧旁路参数，不是"
                    "逐粒子实例数，见模块说明）" % f.i("ParticleNum"))
        for key in ("ColorRate", "Intensity", "AlphaRate", "EdgeBlendRate"):
            if f.has(key):
                em.note("TypeGpuPolygon.%s 未参与模拟（P0 只画纯色片）" % key)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist
        scalar = f.roll("SizeScalar", rng, mode, default=(1.0, 0.0))
        p.rolled["gpg_size"] = Vec3(f.roll("Width", rng, mode, default=(1.0, 0.0)) * scalar,
                                    f.roll("Height", rng, mode, default=(1.0, 0.0)) * scalar,
                                    1.0)

        rx = f.roll("RotationX", rng, mode)
        ry = f.roll("RotationY", rng, mode)
        rz = f.roll("RotationZ", rng, mode)
        p.rolled["gpg_normal"] = rotate_euler(_REST_NORMAL, rx, ry, rz,
                                              order=DEFAULT_ROTATION_ORDER,
                                              applied=em.config.rot_order_applied)
        p.rolled["gpg_up"] = _AXIS_VECS.get(f.i("OrientDirectionUpVector", 1), _AXIS_VECS[1])
        if self._has_rotate:
            p.rolled["gpg_rot_base"] = (rx, ry, rz)

        p.rolled["gpg_color"] = _color_of(f, "Color")
        p.rolled["gpg_color_range"] = _color_of(f, "ColorRange")

    def build_render(self, p, em, view, item):
        f = em.f(TYPE_NAME)
        if f is None:
            return item
        size = p.rolled.get("gpg_size", Vec3(1.0, 1.0, 1.0))
        col = p.rolled.get("gpg_color", (1.0, 1.0, 1.0, 1.0))
        up_hint = p.rolled.get("gpg_up", Vec3(0.0, 1.0, 0.0))
        if self._has_rotate and "gpg_rot_base" in p.rolled:
            rx, ry, rz = p.rolled["gpg_rot_base"]
            normal = rotate_euler(_REST_NORMAL, rx + p.rot.x, ry + p.rot.y, rz + p.rot.z,
                                  order=DEFAULT_ROTATION_ORDER,
                                  applied=em.config.rot_order_applied)
        else:
            normal = p.rolled.get("gpg_normal", _REST_NORMAL)

        it = RenderItem(kind="PLANE", pos=p.pos.copy(),
                        size=Vec3(size.x * p.scale.x, size.y * p.scale.y, 1.0))
        it.axis_u, it.axis_v = _oriented_basis(normal, up_hint)
        it.rot = 0.0
        it.color = [col[0] * p.color[0], col[1] * p.color[1], col[2] * p.color[2],
                    col[3] * p.alpha]
        it.blend = "ALPHA"
        return it
