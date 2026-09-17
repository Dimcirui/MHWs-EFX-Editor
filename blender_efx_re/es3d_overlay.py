# -*- coding: utf-8 -*-
"""
blender_efx_re/es3d_overlay.py —— `EmitterShape3D` 生成区域的独立线框叠加层

和 `sim_preview.py` 里那个 `Emitter Shape` 复选框的区别：**这一层不用播放粒子**。开着的时候
只画**选中**的那几个 Entry 的生成区域，专门给"调 RangeX/Y/Z、扫描角、LocalRotation"用——
改一个字段线框立刻重画。

几何完全复用 `efx_sim` 那份
------------------------------
线框来自 `Simulator.emitter_outline()` -> `EmitterShape3D.outline()`，和粒子出生位置是同一份
区间读法（`(min, max)`，见 `emittershape3d` 模块说明）、同一条旋转换算。**绝不在这里另算一套形状**：
姊妹项目 EFX-Editor 曾经有过一个用 Geometry Nodes 生成真实网格的版本，就是因为它对 range 字段
的读法和模拟层不一致，画出来的形状和粒子实际落点互相矛盾，最后整个删掉。所以这里只画 GPU 线，
**不建任何场景对象**——没有标记、没有孤儿、不进大纲、不可能污染导出字节。

刷新时机
--------
两个失效源，都不走 depsgraph handler（那东西每次场景变动都跑，代价比这里的重建还大）：

1. **签名比对**（选中了谁 + 各自的 `matrix_world`）在 `_draw()` 里做，所以拖动 Entry、改
   Transform3D 导致的位移都会自动跟上。
2. **字段编辑标脏**：`model.py` 的字段 update 回调里，只要被改的 attribute 是 `EmitterShape3D`
   就 `invalidate()`。⚠ **别在那儿列字段白名单**——`RangeX/Y/Z`、`ScaleHorizontal/Vertical`、
   `LocalRotation*`、`RotationOrder` 全都进线框，漏一个就是"改了参数框不动"。

开关状态存模块级 dict、不存 .blend：真相源就是 draw handler 在不在，和 `sim_preview.py` 同一个
理由（本模块不产生任何场景数据，没有"残留物要清理"的问题）。重开文件默认关。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatVectorProperty
from bpy.types import Operator

from . import i18n, sim_preview

#: 一次最多画多少个 Entry。选中一整棵树时几百个形状叠在一起既看不清也拖慢视口。
_MAX_ENTRIES = 64

_STATE = {
    "handler": None,
    "lines": [],      # 已经换算到 Blender 世界坐标的顶点，成对（LINES 图元）
    "sig": None,      # 选中了谁 + 摆在哪
    "dirty": False,
}

_HANDLERS: list = []


def is_active() -> bool:
    return _STATE["handler"] is not None


def invalidate() -> None:
    """形状字段被改过 -> 下一次绘制时重建。叠加层没开着就什么都不做。"""
    if not is_active():
        return
    _STATE["dirty"] = True
    sim_preview._redraw_viewports()


# ---------------------------------------------------------------------------
# 线框构建
# ---------------------------------------------------------------------------

def selected_entries(context):
    """当前范围模式下要画的 Entry（去重、保序、封顶）。

    直接复用 `sim_preview.active_entries()`——`SELECTION`/`GROUP` 这条解析规则两边必须一致，
    否则同一个范围在预览里和叠加层里画的不是同一批东西。
    """
    return sim_preview.active_entries(context)[:_MAX_ENTRIES]


def build_lines(entries, scene):
    """`[Blender 世界坐标顶点, ...]`，成对。没有 `EmitterShape3D` 的 Entry 自然是空的。

    单个 Entry 出错只跳过它自己，不拖垮整层——同 `sim_preview` 的做法。
    """
    sim_mod = sim_preview._sim()
    config = sim_preview.config_from_scene(scene)
    out = []
    for obj in entries:
        try:
            sim = sim_mod.Simulator(sim_preview.build_blocks(obj), config)
            segs = sim.emitter_outline()
        except Exception:   # noqa: BLE001
            continue
        if not segs:
            continue
        matrix = sim_preview._entry_matrix(obj)
        for a, b in segs:
            out.append(tuple(sim_preview._to_world(matrix, a)))
            out.append(tuple(sim_preview._to_world(matrix, b)))
    return out


def _signature(entries):
    """选中了谁 + 各自摆在哪。矩阵进签名 -> 拖动 Entry 时线框自动跟着走。"""
    sig = []
    for obj in entries:
        m = obj.matrix_world
        sig.append((obj.name, tuple(m[i][j] for i in range(4) for j in range(4))))
    return tuple(sig)


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------

def _draw():
    """`POST_VIEW` 绘制回调。**不抛异常**——draw handler 里抛会把整个视口刷屏报错。"""
    try:
        _draw_inner()
    except Exception:   # noqa: BLE001
        pass


def refresh(context):
    """按需重建缓存，返回当前的顶点列表。

    单独拎出来是为了**能被门禁跑到**：`--background` 下没有 GPU 上下文，`_draw_inner()` 里
    那几行 gpu 调用一句都执行不了，而"线框算得对不对"恰恰全在这一段里。
    """
    entries = selected_entries(context)
    sig = _signature(entries)
    if _STATE["dirty"] or sig != _STATE["sig"]:
        _STATE["lines"] = build_lines(entries, context.scene)
        _STATE["sig"] = sig
        _STATE["dirty"] = False
    return _STATE["lines"]


def _draw_inner():
    import gpu
    from gpu_extras.batch import batch_for_shader

    context = bpy.context
    scene = context.scene
    lines = refresh(context)
    if not lines:
        return

    color = tuple(getattr(scene, "efx_re_es3d_overlay_color", _DEFAULT_COLOR))
    shader = sim_preview._builtin("FLAT_COLOR")
    batch = batch_for_shader(shader, "LINES",
                             {"pos": lines, "color": [color] * len(lines)})
    behind = bool(getattr(scene, "efx_re_es3d_overlay_depth", True))
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL" if behind else "NONE")
    try:
        batch.draw(shader)
    finally:
        # 状态不复位会漏给后面的叠加层（粒子预览就画在同一批回调里）
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")


_DEFAULT_COLOR = (0.35, 0.75, 1.0, 0.7)


def _remove_handler():
    while _HANDLERS:
        h = _HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except Exception:
            pass
    _STATE["handler"] = None
    _STATE["lines"] = []
    _STATE["sig"] = None


def _add_handler():
    _remove_handler()
    h = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    _HANDLERS.append(h)
    _STATE["handler"] = h
    return h


# ---------------------------------------------------------------------------
# 算子 / UI
# ---------------------------------------------------------------------------

class EFX_RE_OT_es3d_overlay_toggle(Operator):
    """开关生成区域线框叠加层。

    做成 toggle 而不是"开"/"关"两个算子：面板上就一个按钮位，`depress=` 直接表达当前状态。
    """

    bl_idname = "efx_re.es3d_overlay_toggle"
    bl_label = "Emitter Shape Overlay"
    bl_description = "画出选中 Entry 的生成区域线框，不用播放粒子预览"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if is_active():
            _remove_handler()
        else:
            _add_handler()
            _STATE["dirty"] = True
            if not selected_entries(context):
                self.report({"WARNING"}, i18n.T("es3do.no_entry"))
        sim_preview._redraw_viewports()
        return {"FINISHED"}


def draw_button(layout, context):
    """面板上的一行。颜色/穿透两个设置只在开着时才显示，关着时不占地方。"""
    on = is_active()
    row = layout.row(align=True)
    row.operator(EFX_RE_OT_es3d_overlay_toggle.bl_idname,
                 text=i18n.T("es3do.hide") if on else i18n.T("es3do.show"),
                 icon="MESH_UVSPHERE", depress=on, translate=False)
    if on:
        sub = layout.row(align=True)
        sub.prop(context.scene, "efx_re_es3d_overlay_color", text="")
        sub.prop(context.scene, "efx_re_es3d_overlay_depth", toggle=True, icon="XRAY")


_STRINGS = {
    "es3do.show": {"ZH": "显示生成区域", "EN": "Show Emitter Shape"},
    "es3do.hide": {"ZH": "隐藏生成区域", "EN": "Hide Emitter Shape"},
    "es3do.no_entry": {"ZH": "没有命中任何 Entry（选中一个，或检查 Scope/Group 设置）",
                       "EN": "No entries matched (select one, or check Scope/Group settings)"},
}

_CLASSES = (EFX_RE_OT_es3d_overlay_toggle,)


def register():
    i18n.add_strings(_STRINGS)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.efx_re_es3d_overlay_color = FloatVectorProperty(
        name="Outline Color", subtype="COLOR", size=4, min=0.0, max=1.0,
        default=_DEFAULT_COLOR,
        description="生成区域线框的颜色和不透明度")
    bpy.types.Scene.efx_re_es3d_overlay_depth = BoolProperty(
        name="Behind Geometry", default=True,
        description="让场景物体挡住线框。关掉则线框整条都能透过遮挡物看见")


def unregister():
    # 先把绘制停掉：类注销之后 draw handler 还挂着的话，下一次重绘就是崩溃。
    _remove_handler()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    for name in ("efx_re_es3d_overlay_color", "efx_re_es3d_overlay_depth"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
