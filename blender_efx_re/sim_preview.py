"""
blender_efx_re/sim_preview.py —— 粒子预览播放器（modal 时钟 + gpu 绘制，**零场景对象**）

`efx_sim/`（零 bpy）负责算，本模块只负责三件事：

1. **喂数据**：从**正在编辑的属性树**拼 `[(短类型名, fields_dict)]`——不是从上次保存的文件
   读，否则预览看到的不是你刚改的值。走的是 `model.children_to_dict()`，也就是
   `io_tree.export_attribute_object()` 用的那个函数：预览和导出读同一份数据、同一条路径。
2. **时钟**：modal + `wm.event_timer_add`，自带播放/循环/倍速，**不碰 `scene.frame_current`**，
   与时间轴完全解耦。
3. **绘制**：`SpaceView3D.draw_handler_add(POST_VIEW)` 直接画，**不建任何场景对象**——没有
   标记、没有孤儿、不污染 undo 栈。

铁律级不变量：**只读**
----------------------
本模块**绝不写 `efx_fields` / `efx_opaque_text` / 任何参与导出的数据**。预览误写会变成
"看起来只是看了一眼、实际改了文件"，而现有的往返门禁中间不经过预览，对这种错完全免疫。
`tools/verify_blender_sim_preview.py` 专门守这条：跑完预览再导出，字节必须与跑之前逐字节相同。

模块级 dict 存播放器状态是**合理的**：本模块不产生任何场景数据，没有"场景里的残留物要清理"
的问题。真相源就是 draw handler 在不在、modal 在不在——两者都由这个 dict 持有、由算子成对管理。

⚠ 骨架照搬姊妹项目 EFX-Editor 的 `blender_efx/sim_preview.py`，但那份文件的 docstring 自己
写着"尚未在 Blender 里跑过"。本仓这条路是新的（已有的 gpu 先例只有 `uvs_image_editor.py` 的
2D `SpaceImageEditor`，没有 3D `POST_VIEW`），所以 P0 的目标就是把它在真 Blender 里跑通，
见 docs/SIM_PORT_PLAN.md §1。

约束：bpy 稳定子集；**纯胶水层，不改 `efx_sim/`**。
"""

from __future__ import annotations

import math
import time

import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator, Panel
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import asset_paths, bridge, coords, i18n, model, tex_image

_CATEGORY = "Wilds EFX"


def _sim():
    """拿到零 bpy 的模拟核心 `efx_sim`。

    两种加载方式都要能跑：
    - 装成 Blender 扩展时，本模块是 `bl_ext.…mhws_efx_editor.blender_efx_re.sim_preview`，
      核心是它的叔叔包 -> `from ..efx_sim import ...`；
    - 门禁脚本把**仓库根**塞进 `sys.path` 再 `import blender_efx_re` 时，`blender_efx_re`
      是顶层包，`..` 已经越界 -> 退回绝对 import。
    一次 import 之后 Python 自己缓存在 `sys.modules`，这里不另设缓存。
    """
    try:
        from .. import efx_sim
    except ImportError:
        import efx_sim
    return efx_sim

# ---------------------------------------------------------------------------
# 播放器状态
# ---------------------------------------------------------------------------

_P = {
    # 每个被选中的 entry 一条 track：{"sim", "name", "matrix", "items", "outline"}
    # 一条 track 自带宿主矩阵和渲染产物——多个 entry 各自摆在自己的位置上，共享的只有
    # 时钟（同一个累加器 -> 天然同步，不会各跑各的帧）。
    "tracks": [],
    "playing": False,
    "acc": 0.0,          # 帧累加器（浮点，只走整数帧）
    "last_t": 0.0,       # 上次 tick 的墙钟
    "duration": 0,       # "播放一次"的长度（帧）= 各 track 里最长的那个
    "handler": None,
    "timer": None,
    "dirty": False,      # 属性被编辑过 -> 下个 tick 重建
    "error": "",
}

_HANDLERS = []


def tracks():
    return _P["tracks"]


def is_active():
    return _P["handler"] is not None


def is_playing():
    return _P["playing"] and is_active()


def mark_dirty():
    """属性树被改过 -> 下个 tick 用新参数重建。面板/算子改完值调一下即可。"""
    _P["dirty"] = True


# ---------------------------------------------------------------------------
# 属性树 -> 模拟器输入
# ---------------------------------------------------------------------------

def resolve_entry(obj):
    """从一个对象往上找它所属的 `EFX_RE_ENTRY`；找不到返回 None。"""
    cur = obj
    while cur is not None:
        if cur.get("~TYPE") == model.TYPE_ENTRY:
            return cur
        cur = cur.parent
    return None


def selected_entries(context):
    """当前选中的对象各自所属的 entry（去重，保持选中顺序）。"""
    out = []
    seen = set()
    for obj in list(context.selected_objects) + [context.active_object]:
        if obj is None:
            continue
        entry = resolve_entry(obj)
        if entry is not None and entry.name not in seen:
            seen.add(entry.name)
            out.append(entry)
    return out


def build_blocks(entry_obj):
    """一个 entry -> `[(短类型名, fields_dict), ...]`，按 `efx_index` 排序（= 文件里的顺序）。

    **只读**：`children_to_dict()` 只遍历 `EFXValueNode` 取值，不写任何东西。
    """
    attrs = [o for o in entry_obj.children if o.get("~TYPE") == model.TYPE_ATTRIBUTE]
    attrs.sort(key=lambda o: o.efx_index)
    out = []
    for obj in attrs:
        try:
            fields = model.children_to_dict(obj.efx_fields)
        except Exception:
            # 单个属性读不出来不该拖垮整条预览——记成空块，registry 会把它算进"未模拟"。
            fields = {}
        out.append((model.short_attr_name(obj.efx_attr_type), fields))
    return out


def config_from_scene(scene):
    """场景属性 -> SimConfig。待标定项全在这儿落地成开关。"""
    return _sim().SimConfig(
        seed=int(getattr(scene, "efx_re_sim_seed", 0)),
        fps=int(getattr(scene, "efx_re_sim_fps", 60)),
        random_dist=getattr(scene, "efx_re_sim_random_dist", "onesided"),
        life_model=getattr(scene, "efx_re_sim_life_model", "sum"),
        keep_hold_frame=getattr(scene, "efx_re_sim_keep_hold", "ignore"),
        es3d_range_mode=getattr(scene, "efx_re_sim_es3d_range", "static_random"),
        velocity_unit=getattr(scene, "efx_re_sim_velocity_unit", "per_second"),
        rot_order_applied=getattr(scene, "efx_re_sim_rot_applied", "forward"),
        uvs_speed_unit=getattr(scene, "efx_re_sim_uvs_speed_unit", "per_frame"),
        uvs_playback=getattr(scene, "efx_re_sim_uvs_playback", "flags"),
        uvs_once_span=getattr(scene, "efx_re_sim_uvs_once_span", "to_end"),
        max_particles=int(getattr(scene, "efx_re_sim_max_particles", 4000)),
    )


#: `.uvs` 内部路径 -> SimResources；解析一次就缓存（多个 entry 常引用同一个 .uvs）
_UVS_CACHE: dict = {}
#: 贴图内部路径 -> bpy.types.Image 名字（None = 试过但拿不到，别反复重试）
_TEX_CACHE: dict = {}


def clear_asset_caches():
    _UVS_CACHE.clear()
    _TEX_CACHE.clear()


def _uvs_path_of(entry_obj):
    """entry 里 `UVSequence` 的 `UVSPath`（全语料一个 entry 至多一个 UVSequence）。"""
    for obj in entry_obj.children:
        if obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if model.short_attr_name(obj.efx_attr_type) != "UVSequence":
            continue
        node = model.find_field(obj.efx_fields, "UVSPath")
        if node is not None and node.data_type == "STRING":
            return node.string_value
    return ""


def _resources_for(entry_obj):
    """entry -> `efx_sim.SimResources`（序列帧表）。拿不到就交空资源，**不编占位帧表**。"""
    path = (_uvs_path_of(entry_obj) or "").strip()
    if not path:
        return _sim().SimResources()
    if path in _UVS_CACHE:
        return _UVS_CACHE[path]

    res = _sim().SimResources()
    local = asset_paths.resolve(path)
    if local is not None:
        try:
            data = bridge.dump_uvs(local)
            res = _sim().from_uvs_dict(data, source=path)
        except Exception as exc:   # noqa: BLE001
            _P["error"] = "读 .uvs 失败（%s）：%s" % (path, exc)
    _UVS_CACHE[path] = res
    return res


def _gpu_texture(tex_key):
    """贴图内部路径 -> `gpu.types.GPUTexture`；拿不到返回 None（调用方退回纯色）。"""
    if not tex_key:
        return None
    name = _TEX_CACHE.get(tex_key, False)
    if name is False:
        name = None
        local = asset_paths.resolve(tex_key)
        if local is not None:
            try:
                img = tex_image.load_image(local)
                name = img.name
            except Exception as exc:   # noqa: BLE001
                _P["error"] = "贴图解码失败（%s）：%s" % (tex_key, exc)
        _TEX_CACHE[tex_key] = name
    if not name:
        return None
    img = bpy.data.images.get(name)
    if img is None:
        return None
    try:
        return gpu.texture.from_image(img)
    except Exception:
        return None


def _make_track(entry_obj, scene):
    blocks = build_blocks(entry_obj)
    sim = _sim().Simulator(blocks, config_from_scene(scene),
                           resources=_resources_for(entry_obj))
    return {"sim": sim, "name": entry_obj.name, "obj": entry_obj,
            "items": [], "outline": []}


def rebuild_tracks(context, keep_frame=True):
    """按当前选中的 entry 重建全部 track。返回 track 数。"""
    scene = context.scene
    old_frame = _P["tracks"][0]["sim"].em.frame if _P["tracks"] else -1

    fresh = []
    for entry in selected_entries(context):
        try:
            fresh.append(_make_track(entry, scene))
        except Exception as exc:   # noqa: BLE001 —— 失败的 entry 单独跳过并报出来
            _P["error"] = "%s: %s" % (entry.name, exc)
    _P["tracks"] = fresh
    _P["duration"] = _resolve_duration(scene)

    if keep_frame and old_frame > 0:
        # 快进回原来那一帧：不快进的话，拖一下开关画面就跳回第 0 帧，调参时没法比较前后。
        # 确定性重放保证快进结果与连续播放一致。
        target = min(old_frame, _REBUILD_CATCHUP_MAX)
        for tr in fresh:
            tr["sim"].run_to(target)
    _rebuild_items()
    return len(fresh)


#: 重建后最多快进多少帧（防手滑设了个巨大的 duration 之后每改一个字段都卡一下）
_REBUILD_CATCHUP_MAX = 600


def _resolve_duration(scene):
    """"播放一次"多长。0 = 自动（按各 behavior 的 `duration_hint()`）。

    多 track 时取**最长**的那个：短的那些循环几轮等长的跑完，比"谁先结束谁就整体重置"
    更符合"同时看几个效果"的意图。
    """
    d = int(getattr(scene, "efx_re_sim_duration", 0))
    if d > 0:
        return d
    best = 0
    for tr in _P["tracks"]:
        try:
            best = max(best, int(tr["sim"].suggested_duration()))
        except Exception:
            pass
    return best or 180


# ---------------------------------------------------------------------------
# 坐标换算
# ---------------------------------------------------------------------------

def _entry_matrix(entry_obj):
    """entry 的世界矩阵。

    用**完整矩阵**而不只是位置：`Transform3D` 的位置/旋转/缩放已经由
    `transform3d_view.py` 烘进了这个矩阵，多层嵌套 entry 的叠加也由 Blender 自己算好了
    ——乘上去就全部继承，模拟层因此完全不必知道 `Transform3D`、骨骼绑定这些事
    （见 docs/SIM_PORT_PLAN.md §5.1）。
    """
    try:
        return entry_obj.matrix_world.copy()
    except Exception:
        from mathutils import Matrix
        return Matrix.Identity(4)


def _to_world(matrix, v):
    """游戏坐标（entry 局部）-> Blender 世界坐标。

    `coords.game_pos_to_blender()` 做 1:1 + Rx(+90°) 基变换（**不除 100**，那是姊妹项目
    MT Framework 的系数，照抄会把一切缩小 100 倍），再过 entry 的世界矩阵。
    """
    return matrix @ coords.game_pos_to_blender(v.x, v.y, v.z)


# ---------------------------------------------------------------------------
# 渲染项 -> GPU 顶点
# ---------------------------------------------------------------------------

def _builtin(name):
    """builtin shader 取名的跨版本包装：4.0 起是 'FLAT_COLOR' 这样的短名，3.x 是
    '3D_FLAT_COLOR'。先试新名、失败再试旧名。

    ⚠ **不要**用 `gpu.types.GPUShader(vert_src, frag_src)` 字符串构造器：3.4 起废弃、5.0
    移除，且 Vulkan 后端（5.x 默认）下不工作。真要自定义 shader 走
    `gpu.shader.create_from_info`。
    """
    try:
        return gpu.shader.from_builtin(name)
    except Exception:
        return gpu.shader.from_builtin("3D_" + name)


_TEX_SHADER = None


def _tex_shader():
    """贴图 + **逐顶点颜色**的 shader。

    builtin 的 `IMAGE_COLOR` 只有一个全局 color uniform，没法逐粒子调制颜色/alpha——
    按 (贴图, 颜色) 分桶会炸成成百上千个 batch。所以自建一个。

    走 `gpu.shader.create_from_info`，**不是** `gpu.types.GPUShader(vert, frag)` 那个字符串
    构造器：后者 3.4 起废弃、5.0 移除，且 Vulkan 后端（5.x 默认）下不工作。
    `ModelViewProjectionMatrix` 这个名字是约定的，gpu 模块按当前矩阵栈自动填。
    """
    global _TEX_SHADER
    if _TEX_SHADER is not None:
        return _TEX_SHADER
    iface = gpu.types.GPUStageInterfaceInfo("efx_re_sim_iface")
    iface.smooth("VEC2", "v_uv")
    iface.smooth("VEC4", "v_col")

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "ModelViewProjectionMatrix")
    info.sampler(0, "FLOAT_2D", "image")
    info.vertex_in(0, "VEC3", "pos")
    info.vertex_in(1, "VEC2", "texCoord")
    info.vertex_in(2, "VEC4", "color")
    info.vertex_out(iface)
    info.fragment_out(0, "VEC4", "FragColor")
    info.vertex_source(
        "void main() {"
        "  v_uv = texCoord;"
        "  v_col = color;"
        "  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);"
        "}")
    info.fragment_source(
        "void main() {"
        "  FragColor = texture(image, v_uv) * v_col;"
        "}")
    _TEX_SHADER = gpu.shader.create_from_info(info)
    return _TEX_SHADER


def _quad_uvs(rect):
    """`.uvs` 的 (left, top, right, bottom) -> 四角 UV，序同 `_quad_tris`（BL,BR,TR,TL）。

    ⚠ **v 轴翻转**：`.uvs` 里 v 向下（图像坐标系，top < bottom），Blender/OpenGL 的纹理
    坐标 v 向上。`uvs_image_editor.py` 画叠加框时翻的是同一个方向，两处保持一致。
    """
    left, top, right, bottom = rect
    return ((left, 1.0 - bottom), (right, 1.0 - bottom),
            (right, 1.0 - top), (left, 1.0 - top))


def _camera_axes(rv3d):
    """视图矩阵前两行 = 世界空间下的相机右 / 上向量（面向相机用）。"""
    vm = rv3d.view_matrix
    return (Vector((vm[0][0], vm[0][1], vm[0][2])),
            Vector((vm[1][0], vm[1][1], vm[1][2])))


def _spin(right, up, radians_):
    """把一对屏幕轴在屏幕平面内转 `radians_`（`RenderItem.rot` 是**弧度**）。"""
    if not radians_:
        return right, up
    c, s = math.cos(radians_), math.sin(radians_)
    return (right * c + up * s, up * c - right * s)


def _quad_tris(center, right, up, hw, hh):
    """两个三角形拼一个面片。顶点序 BL, BR, TR / BL, TR, TL。"""
    rx, ux = right * hw, up * hh
    a = center - rx - ux
    b = center + rx - ux
    c = center + rx + ux
    d = center - rx + ux
    return (a, b, c, a, c, d)


def _rebuild_items():
    """重跑各 track 的渲染 pass（与 step 解耦，转视角时可以只重跑这里）。"""
    for tr in _P["tracks"]:
        sim = tr["sim"]
        try:
            tr["items"] = sim.build_render()
        except Exception as exc:   # noqa: BLE001
            tr["items"] = []
            _P["error"] = "build_render: %s" % exc
        try:
            tr["outline"] = sim.emitter_outline()
        except Exception:
            tr["outline"] = []
        tr["matrix"] = _entry_matrix(tr["obj"]) if tr["obj"] else None


def _collect(tr, rv3d, buckets, lines, line_cols):
    """把一条 track 的渲染项摊进**按贴图分的桶** + 线段顶点。

    `buckets[tex_key] = {"pos": [...], "col": [...], "uv": [...]}`；`tex_key is None`
    那一桶是纯色的（没有序列帧或贴图拿不到）。分桶是为了一张贴图一次 draw call，
    而不是一个粒子一次。
    """
    matrix = tr.get("matrix")
    if matrix is None:
        return
    right, up = _camera_axes(rv3d)

    for it in tr["items"]:
        center = _to_world(matrix, it.pos)
        col = tuple(it.color)
        if it.kind == "POINT":
            hw = hh = max(1e-4, it.size.x)
        else:
            hw = max(1e-4, it.size.x * 0.5)
            hh = max(1e-4, it.size.y * 0.5)
        r, u = _spin(right, up, getattr(it, "rot", 0.0))
        # ⚠ 只有**位置**过 entry 矩阵，粒子自身的尺寸不跟着 entry 的 scale 缩放。
        # 语料里 Transform3D.LocalScale 94.3% 是 1.0，区分不出来；真遇到非 1 的再定。
        tris = _quad_tris(center, r, u, hw, hh)

        key = it.tex_key if it.kind != "POINT" else None
        bucket = buckets.setdefault(key, {"pos": [], "col": [], "uv": []})
        if key is not None:
            c = _quad_uvs(it.uv_rect)
            uvs = (c[0], c[1], c[2], c[0], c[2], c[3])   # 顶点序同 _quad_tris
        else:
            uvs = ((0.0, 0.0),) * 6
        for v, uv in zip(tris, uvs):
            bucket["pos"].append(tuple(v))
            bucket["col"].append(col)
            bucket["uv"].append(uv)

    for a, b in tr["outline"]:
        lines.append(tuple(_to_world(matrix, a)))
        lines.append(tuple(_to_world(matrix, b)))
        line_cols.append(_OUTLINE_COLOR)
        line_cols.append(_OUTLINE_COLOR)


_OUTLINE_COLOR = (0.25, 0.65, 1.0, 0.45)


def _draw():
    """`POST_VIEW` 绘制回调。**不抛异常**——draw handler 里抛会把整个视口刷屏报错。"""
    try:
        _draw_inner()
    except Exception as exc:   # noqa: BLE001
        _P["error"] = "draw: %s" % exc


def _draw_inner():
    if not _P["tracks"]:
        return
    ctx = bpy.context
    rv3d = getattr(ctx, "region_data", None)
    if rv3d is None:
        return
    scene = ctx.scene

    buckets, lines, line_cols = {}, [], []
    show_outline = bool(getattr(scene, "efx_re_sim_show_outline", True))
    for tr in _P["tracks"]:
        _collect(tr, rv3d, buckets,
                 lines if show_outline else [], line_cols if show_outline else [])

    flat = _builtin("FLAT_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)     # 半透明粒子不写深度，避免互相切块

    if lines:
        gpu.state.line_width_set(1.0)
        batch_for_shader(flat, "LINES", {"pos": lines, "color": line_cols}).draw(flat)

    use_tex = bool(getattr(scene, "efx_re_sim_use_textures", True))
    for key, b in buckets.items():
        if not b["pos"]:
            continue
        tex = _gpu_texture(key) if (key and use_tex) else None
        if tex is None:
            # 拿不到贴图就画纯色，**不跳过**——粒子还在那儿，只是没贴图；
            # 直接不画会让人以为模拟出错了。
            batch_for_shader(flat, "TRIS",
                             {"pos": b["pos"], "color": b["col"]}).draw(flat)
            continue
        shader = _tex_shader()
        shader.bind()
        shader.uniform_sampler("image", tex)
        batch_for_shader(shader, "TRIS",
                         {"pos": b["pos"], "texCoord": b["uv"],
                          "color": b["col"]}).draw(shader)

    gpu.state.depth_mask_set(True)
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------------------
# handler / 时钟
# ---------------------------------------------------------------------------

def _remove_handlers():
    while _HANDLERS:
        h = _HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except Exception:
            pass
    _P["handler"] = None


def _add_handler():
    _remove_handlers()
    h = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    _HANDLERS.append(h)
    _P["handler"] = h
    return h


def _redraw_viewports():
    wm = bpy.context.window_manager
    for win in getattr(wm, "windows", ()):
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _reset_all():
    for tr in _P["tracks"]:
        try:
            tr["sim"].reset()
        except Exception:
            pass


def tick(context):
    """一次定时器滴答：按墙钟推进整数帧（所有 track 共用这一个时钟 -> 天然同步）。

    倍速不靠改定时器间隔（那会丢整数帧语义），靠浮点累加器：0.25 倍速 = 每 4 个 tick 走
    一帧，2 倍速 = 每 tick 走两帧。逐帧乘法递推在任何倍速下都精确。
    """
    scene = context.scene
    if _P["dirty"]:
        _P["dirty"] = False
        clear_asset_caches()     # UVSPath / 贴图路径可能被改过
        rebuild_tracks(context, keep_frame=True)
        _redraw_viewports()
    if not _P["tracks"] or not _P["playing"]:
        return

    now = time.perf_counter()
    dt = now - _P["last_t"]
    _P["last_t"] = now
    if dt <= 0.0 or dt > 0.5:
        dt = min(max(dt, 0.0), 1.0 / 30.0)    # 卡顿/切后台后不要一次补几百帧

    fps = float(getattr(scene, "efx_re_sim_fps", 60))
    speed = float(getattr(scene, "efx_re_sim_speed", 1.0))
    _P["acc"] += dt * fps * speed

    steps = 0
    while _P["acc"] >= 1.0 and steps < 240:    # 单 tick 步数上限，防卡死
        for tr in _P["tracks"]:
            tr["sim"].step()
        _P["acc"] -= 1.0
        steps += 1
        frame = _P["tracks"][0]["sim"].em.frame
        if _P["duration"] > 0 and frame >= _P["duration"]:
            if getattr(scene, "efx_re_sim_mode", "LOOP") == "LOOP":
                _reset_all()
                _P["acc"] = 0.0
            else:
                _P["playing"] = False
            break

    if steps:
        _rebuild_items()
        _redraw_viewports()


def current_frame():
    return _P["tracks"][0]["sim"].em.frame if _P["tracks"] else -1


def aggregate_status():
    """(粒子数, 未模拟属性数, notes)。面板要如实显示这些——**预览不静默撒谎**。"""
    particles = 0
    unsupported = 0
    notes = []
    for tr in _P["tracks"]:
        em = tr["sim"].em
        particles += len(em.particles)
        unsupported += len(em.unsupported)
        for n in em.notes:
            if n not in notes:
                notes.append(n)
    return particles, unsupported, notes


# ---------------------------------------------------------------------------
# 算子
# ---------------------------------------------------------------------------

class EFX_RE_OT_sim_play(Operator):
    """开始播放（自带时钟，不动时间轴；选中多个 Entry 就同时播）"""

    bl_idname = "efx_re.sim_play"
    bl_label = "Play"
    bl_description = "播放选中 Entry 的粒子预览。预览是近似，不是游戏画面"
    bl_options = {"REGISTER"}

    _timer = None

    @classmethod
    def poll(cls, context):
        return bool(selected_entries(context))

    def invoke(self, context, event):
        if is_active():
            # 已经在跑 -> 这次点击当"继续播放"
            _P["playing"] = True
            _P["last_t"] = time.perf_counter()
            return {"FINISHED"}

        n = rebuild_tracks(context, keep_frame=False)
        if not n:
            self.report({"ERROR"}, "没有可预览的 Entry")
            return {"CANCELLED"}

        _P["playing"] = True
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _P["error"] = ""
        _add_handler()

        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 120.0, window=context.window)
        _P["timer"] = self._timer
        wm.modal_handler_add(self)
        _redraw_viewports()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not is_active():
            return self._finish(context)
        if event.type == "TIMER":
            tick(context)
        return {"PASS_THROUGH"}

    def _finish(self, context):
        wm = context.window_manager
        if self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        _P["timer"] = None
        _redraw_viewports()
        return {"FINISHED"}


class EFX_RE_OT_sim_stop(Operator):
    """停止预览并清掉绘制（不留任何场景对象）"""

    bl_idname = "efx_re.sim_stop"
    bl_label = "Stop"
    bl_description = "停止预览并移除绘制"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        _P["playing"] = False
        _P["tracks"] = []
        _P["error"] = ""
        _remove_handlers()
        _redraw_viewports()
        return {"FINISHED"}


class EFX_RE_OT_sim_pause(Operator):
    """暂停 / 继续"""

    bl_idname = "efx_re.sim_pause"
    bl_label = "Pause"
    bl_description = "暂停或继续播放。暂停时仍可转视角，画面会跟着重画"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        _P["playing"] = not _P["playing"]
        _P["last_t"] = time.perf_counter()
        _redraw_viewports()
        return {"FINISHED"}


class EFX_RE_OT_sim_restart(Operator):
    """回到第 0 帧重新播（按当前属性值重建）"""

    bl_idname = "efx_re.sim_restart"
    bl_label = "Restart"
    bl_description = "按当前属性值从头重建并播放"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        rebuild_tracks(context, keep_frame=False)
        _P["acc"] = 0.0
        _P["last_t"] = time.perf_counter()
        _redraw_viewports()
        return {"FINISHED"}


class EFX_RE_OT_sim_step(Operator):
    """手动走一帧（暂停时逐帧看）"""

    bl_idname = "efx_re.sim_step"
    bl_label = "Step"
    bl_description = "手动推进一帧"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        for tr in _P["tracks"]:
            tr["sim"].step()
        _rebuild_items()
        _redraw_viewports()
        return {"FINISHED"}


class EFX_RE_OT_sim_refresh(Operator):
    """按当前属性值重建（保留当前帧）"""

    bl_idname = "efx_re.sim_refresh"
    bl_label = "Refresh"
    bl_description = "改完属性后按新值重建预览，并快进回当前帧"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return is_active()

    def execute(self, context):
        rebuild_tracks(context, keep_frame=True)
        _redraw_viewports()
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 面板
# ---------------------------------------------------------------------------

class EFX_RE_PT_sim(Panel):
    bl_label = "Particle Preview"
    bl_idname = "EFX_RE_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_order = 8

    def draw(self, context):
        layout = self.layout
        layout.label(text=i18n.T("sim.approximation_warning"), icon="INFO", translate=False)

        row = layout.row(align=True)
        if not is_active():
            row.operator(EFX_RE_OT_sim_play.bl_idname, text=i18n.T("sim.play"), icon="PLAY")
        else:
            icon = "PAUSE" if is_playing() else "PLAY"
            row.operator(EFX_RE_OT_sim_pause.bl_idname,
                         text=i18n.T("sim.pause") if is_playing() else i18n.T("sim.resume"),
                         icon=icon)
            row.operator(EFX_RE_OT_sim_step.bl_idname, text="", icon="FRAME_NEXT")
            row.operator(EFX_RE_OT_sim_restart.bl_idname, text="", icon="LOOP_BACK")
            row.operator(EFX_RE_OT_sim_refresh.bl_idname, text="", icon="FILE_REFRESH")
            row.operator(EFX_RE_OT_sim_stop.bl_idname, text="", icon="X")

        if not is_active():
            n = len(selected_entries(context))
            layout.label(text=i18n.T("sim.selected_entries") % n, translate=False)
            return

        particles, unsupported, notes = aggregate_status()
        box = layout.box()
        col = box.column(align=True)
        col.label(text=i18n.T("sim.frame") % (current_frame(), _P["duration"]),
                  translate=False)
        col.label(text=i18n.T("sim.particles") % particles, translate=False)
        if unsupported:
            col.label(text=i18n.T("sim.unsupported") % unsupported, icon="ERROR",
                      translate=False)
        if _P["error"]:
            col.label(text=_P["error"], icon="CANCEL", translate=False)

        if notes:
            sub = layout.box()
            sub.label(text=i18n.T("sim.notes"), icon="INFO", translate=False)
            ncol = sub.column(align=True)
            for n in notes[:12]:
                ncol.label(text=n, translate=False)
            if len(notes) > 12:
                ncol.label(text="… +%d" % (len(notes) - 12), translate=False)


class EFX_RE_PT_sim_playback(Panel):
    bl_label = "Playback"
    bl_idname = "EFX_RE_PT_sim_playback"
    bl_parent_id = "EFX_RE_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene = context.scene
        col = self.layout.column(align=True)
        col.prop(scene, "efx_re_sim_speed")
        col.prop(scene, "efx_re_sim_duration")
        col.prop(scene, "efx_re_sim_mode")
        col.prop(scene, "efx_re_sim_seed")
        col.prop(scene, "efx_re_sim_fps")
        col.prop(scene, "efx_re_sim_max_particles")
        col.prop(scene, "efx_re_sim_show_outline")
        col.prop(scene, "efx_re_sim_use_textures")


class EFX_RE_PT_sim_unknowns(Panel):
    """待标定开关。**面板必须如实显示它们**——预览按哪套假设算的，用户要看得见。"""

    bl_label = "Calibration"
    bl_idname = "EFX_RE_PT_sim_unknowns"
    bl_parent_id = "EFX_RE_PT_sim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = _CATEGORY
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        layout.label(text=i18n.T("sim.calibration_hint"), icon="QUESTION", translate=False)
        col = layout.column(align=True)
        col.prop(scene, "efx_re_sim_velocity_unit")
        col.prop(scene, "efx_re_sim_random_dist")
        col.prop(scene, "efx_re_sim_life_model")
        col.prop(scene, "efx_re_sim_keep_hold")
        col.prop(scene, "efx_re_sim_es3d_range")
        col.prop(scene, "efx_re_sim_rot_applied")
        col.prop(scene, "efx_re_sim_uvs_speed_unit")
        col.prop(scene, "efx_re_sim_uvs_playback")
        col.prop(scene, "efx_re_sim_uvs_once_span")


_CLASSES = (
    EFX_RE_OT_sim_play, EFX_RE_OT_sim_stop, EFX_RE_OT_sim_pause,
    EFX_RE_OT_sim_restart, EFX_RE_OT_sim_step, EFX_RE_OT_sim_refresh,
    EFX_RE_PT_sim, EFX_RE_PT_sim_playback, EFX_RE_PT_sim_unknowns,
)

_STRINGS = {
    "sim.approximation_warning": {
        "ZH": "预览是近似，不是游戏画面", "EN": "Preview is an approximation, not the game"},
    "sim.play": {"ZH": "播放", "EN": "Play"},
    "sim.pause": {"ZH": "暂停", "EN": "Pause"},
    "sim.resume": {"ZH": "继续", "EN": "Resume"},
    "sim.selected_entries": {"ZH": "已选中 %d 个 Entry", "EN": "%d entries selected"},
    "sim.frame": {"ZH": "帧 %d / %d", "EN": "Frame %d / %d"},
    "sim.particles": {"ZH": "粒子 %d 个", "EN": "%d particles"},
    "sim.unsupported": {"ZH": "未模拟属性 %d 个", "EN": "%d attributes not simulated"},
    "sim.notes": {"ZH": "本次预览跳过或假设了这些", "EN": "Skipped or assumed in this preview"},
    "sim.calibration_hint": {
        "ZH": "这些语义未确认，改开关对拍即可标定",
        "EN": "These semantics are unconfirmed; toggle and compare to calibrate"},
}


def _on_knob_changed(self, context):
    mark_dirty()


def register():
    i18n.add_strings(_STRINGS)

    bpy.types.Scene.efx_re_sim_speed = FloatProperty(
        name="Speed", default=1.0, min=0.05, max=8.0,
        description="播放倍速。模拟仍逐帧精确，只是走帧的快慢不同")
    bpy.types.Scene.efx_re_sim_duration = IntProperty(
        name="Duration", default=0, min=0, soft_max=1200,
        description="播放一次的长度（帧）。0 = 按属性自动估算")
    bpy.types.Scene.efx_re_sim_mode = EnumProperty(
        name="Mode", items=[("LOOP", "Loop", ""), ("ONCE", "Once", "")], default="LOOP",
        description="放到头之后循环还是停住")
    bpy.types.Scene.efx_re_sim_seed = IntProperty(
        name="Seed", default=0, min=0, update=_on_knob_changed,
        description="随机种子。换一个就换一批粒子形态，其余完全可复现")
    bpy.types.Scene.efx_re_sim_fps = IntProperty(
        name="FPS", default=60, min=1, max=240, update=_on_knob_changed,
        description="一帧算多少秒。游戏不锁帧，这是预览的假设，不是文件里的值")
    bpy.types.Scene.efx_re_sim_max_particles = IntProperty(
        name="Max Particles", default=4000, min=1, soft_max=20000,
        update=_on_knob_changed,
        description="预览的粒子数硬上限。超出会截断并在上面列出来")
    bpy.types.Scene.efx_re_sim_show_outline = BoolProperty(
        name="Emitter Shape", default=True,
        description="画出生成区域的线框")
    bpy.types.Scene.efx_re_sim_use_textures = BoolProperty(
        name="Textures", default=True,
        description="用序列帧贴图绘制。关掉画纯色片，排查形状和运动时更清楚")
    bpy.types.Scene.efx_re_sim_uvs_speed_unit = EnumProperty(
        name="Sequence Speed",
        items=[("per_frame", "Per Frame", ""), ("per_second", "Per Second", "")],
        default="per_frame", update=_on_knob_changed,
        description="序列帧播放速度的时间基")
    bpy.types.Scene.efx_re_sim_uvs_playback = EnumProperty(
        name="Sequence Playback",
        items=[("flags", "From Flags", ""), ("loop", "Force Loop", ""),
               ("hold", "Force Hold", "")],
        default="flags", update=_on_knob_changed,
        description="播放模式按 UVSequence.Flags 读，还是全体强制循环 / 定格")
    bpy.types.Scene.efx_re_sim_uvs_once_span = EnumProperty(
        name="Play Once Span",
        items=[("to_end", "To Last Frame", ""), ("full_cycle", "Full Sequence", "")],
        default="to_end", update=_on_knob_changed,
        description="播一次走几格：从起始帧到末帧，还是不论起点都走满整条序列")

    bpy.types.Scene.efx_re_sim_velocity_unit = EnumProperty(
        name="Velocity Unit",
        items=[("per_second", "Per Second", ""), ("per_frame", "Per Frame", "")],
        default="per_second", update=_on_knob_changed,
        description="速度与重力的时间基。逐帧衰减系数不受它影响")
    bpy.types.Scene.efx_re_sim_random_dist = EnumProperty(
        name="Random Spread",
        items=[("onesided", "s + [0, r]", ""), ("symmetric", "s + [-r, r]", ""),
               ("gaussian", "s + N(0, r/2)", "")],
        default="onesided", update=_on_knob_changed,
        description="随机量怎么叠加到静态值上")
    bpy.types.Scene.efx_re_sim_life_model = EnumProperty(
        name="Lifetime",
        items=[("sum", "Appear+Keep+Vanish", ""), ("keep", "Keep is total", "")],
        default="sum", update=_on_knob_changed,
        description="总寿命是三段相加，还是 Keep 本身就是总长")
    bpy.types.Scene.efx_re_sim_keep_hold = EnumProperty(
        name="Keep Hold",
        items=[("ignore", "Ignore", ""), ("add", "Add to lifetime", "")],
        default="ignore", update=_on_knob_changed,
        description="作用未知的 Keep Hold 帧数参不参与寿命")
    bpy.types.Scene.efx_re_sim_es3d_range = EnumProperty(
        name="Shape Range",
        items=[("static_random", "s + [0, r]", ""), ("min_max", "[s, r]", "")],
        default="static_random", update=_on_knob_changed,
        description="生成形状的逐轴区间怎么读")
    bpy.types.Scene.efx_re_sim_rot_applied = EnumProperty(
        name="Rotation Order",
        items=[("forward", "First listed first", ""), ("reverse", "First listed last", "")],
        default="forward", update=_on_knob_changed,
        description="旋转顺序串里先写的那根轴先作用还是后作用")

    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    # 先把绘制和时钟停掉：类注销之后 draw handler 还挂着的话，下一次重绘就是崩溃。
    _P["playing"] = False
    _P["tracks"] = []
    _remove_handlers()

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    for name in ("efx_re_sim_speed", "efx_re_sim_duration", "efx_re_sim_mode",
                 "efx_re_sim_seed", "efx_re_sim_fps", "efx_re_sim_max_particles",
                 "efx_re_sim_show_outline", "efx_re_sim_use_textures",
                 "efx_re_sim_uvs_speed_unit", "efx_re_sim_uvs_playback",
                 "efx_re_sim_uvs_once_span",
                 "efx_re_sim_velocity_unit",
                 "efx_re_sim_random_dist", "efx_re_sim_life_model",
                 "efx_re_sim_keep_hold", "efx_re_sim_es3d_range",
                 "efx_re_sim_rot_applied"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
