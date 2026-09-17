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
from mathutils import Matrix, Vector

from . import asset_paths, bridge, coords, i18n, io_tree, model, semantics, tex_image

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
    #
    # `PtLife` 召唤出来的 track 额外带 `spawn_depth`（>0）/`origin_offset`（召唤那一刻
    # 的世界位置，`Matrix.Translation`）——见 `_spawn_action_tracks()`。
    "tracks": [],
    "playing": False,
    "acc": 0.0,          # 帧累加器（浮点，只走整数帧）
    "last_t": 0.0,       # 上次 tick 的墙钟
    "duration": 0,       # "播放一次"的长度（帧）= 各 track 里最长的那个
    "handler": None,
    "timer": None,
    "dirty": False,      # 属性被编辑过 -> 下个 tick 重建
    "error": "",
    "spawned_count": 0,  # 本次播放里 PtLife 已召唤出的 track 总数，见 _MAX_SPAWNED_TRACKS_PER_SESSION
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


#: `efx_re_sim_group` 动态选项的缓存列表——Blender 要求动态 enum 的 items 在下次重算前保持
#: 存活，每次都返回一个新建的列表有崩溃的已知先例，所以原地更新同一个列表对象。
_GROUP_ITEMS_CACHE = []


def _group_names(root_col):
    """`root_col`（EFX_ROOT 集合）下全部 Entry 用过的 `efx_groups` 标签名，去重保序。"""
    seen = set()
    names = []
    for entry in io_tree.root_entries(root_col):
        for tag in entry.efx_groups:
            if tag.name and tag.name not in seen:
                seen.add(tag.name)
                names.append(tag.name)
    return names


def _group_enum_items(self, context):
    """`efx_re_sim_group` 的动态选项：固定第一项"全部"，其余是当前 Active EFX 用过的分组名。"""
    root = io_tree.resolve_root(context)
    names = _group_names(root) if root is not None else []
    items = [("ALL", "All Entries", "不按分组过滤，当前 EFX 下的全部 Entry")]
    items.extend((n, n, "") for n in names)
    _GROUP_ITEMS_CACHE[:] = items
    return _GROUP_ITEMS_CACHE


def active_entries(context):
    """按当前范围模式（`efx_re_sim_scope`）解析出要预览的 entry 列表。

    - `SELECTION`（默认）：视口里选中的对象各自所属的 entry，即 `selected_entries()` 原有行为。
    - `GROUP`：不看视口选择，取当前 Active EFX（`io_tree.resolve_root()`，与选中该 EFX_ROOT
      集合、或场景顶部的 Active EFX 选择器共用同一套解析）下的全部 Entry，按 `efx_re_sim_group`
      过滤到某一个 `efx_groups` 标签；选 `ALL Entries` 就是整个 EFX。`io_tree.root_entries()`
      本来就只收 Entry 对象，Action 从不在返回值里——不会被这个开关意外触发。
    """
    scene = context.scene
    if getattr(scene, "efx_re_sim_scope", "SELECTION") == "GROUP":
        root = io_tree.resolve_root(context)
        if root is None:
            return []
        entries = io_tree.root_entries(root)
        group = getattr(scene, "efx_re_sim_group", "ALL")
        if group == "ALL":
            return entries
        return [e for e in entries if group in {t.name for t in e.efx_groups}]
    return selected_entries(context)


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


#: vendor `ExpressionAssignType`（`EfxCommon.cs:8`）没查到值时的默认——`Assign`（直接替换）
#: 是这五个里对下游影响最好预测的一个，不会因为找不到这个字段就让曲线的效果叠加/相乘出离谱
#: 的数值。正常情况下这个分支不会走到：vendor 的"...Expression"类里 `bit_name` 对应的字段
#: 一定声明为 `ExpressionAssignType`，见 EfxBasics.cs/EfxTypeBillboard.cs 等的
#: `public ExpressionAssignType <bitName>;`。
_EXPR_ASSIGN_DEFAULT = 4


def collect_expressions(entry_obj):
    """一个 entry -> `[(base_type_name, bit_name, formula, assign_type), ...]`，喂给
    `efx_sim.Simulator(expressions=...)`。

    **只读**：只读 `efx_is_expression_attribute`/`efx_expression_curves`/`efx_fields`，
    不写任何东西——同 `build_blocks()`。

    "IExpressionAttribute 是独立的 attribute 类型"这件事，来自 vendor 源码本身（比如
    `EFXAttributeSpawnExpression` 和 `EFXAttributeSpawn` 是两个不同的 `EfxAttributeType`，
    见 `EfxBasics.cs`），不是猜测——`base_type_name` 靠"去掉短类型名结尾的 'Expression'"
    还原出它驱动哪个 sibling attribute，这条命名规则在全部 `IExpressionAttribute` 类型上
    检查过、没有反例（`ATTRIBUTE_TYPES.md`）。`bit_name` 对应的字段是一个
    `ExpressionAssignType` 枚举值（同一个 "...Expression" 对象自己的 `efx_fields` 里，
    键名就是 `bit_name` 本身，如 `"spawnNum"`），决定公式结果和 sibling 字段的现有值怎么
    合成（Add/Subtract/Multiply/Divide/Assign）——不是公式结果本身。
    """
    attrs = [o for o in entry_obj.children if o.get("~TYPE") == model.TYPE_ATTRIBUTE]
    by_short_name = {model.short_attr_name(o.efx_attr_type): o for o in attrs}

    out = []
    for obj in attrs:
        if not obj.efx_is_expression_attribute:
            continue
        short_name = model.short_attr_name(obj.efx_attr_type)
        if not short_name.endswith("Expression"):
            continue
        base_name = short_name[: -len("Expression")]
        if base_name not in by_short_name:
            continue  # 找不到 sibling attribute——efx_sim 自己会 note 并跳过，这里不重复判断

        try:
            own_fields = model.children_to_dict(obj.efx_fields)
        except Exception:
            own_fields = {}

        sibling_obj = by_short_name[base_name]
        for curve in obj.efx_expression_curves:
            if not curve.bit_name:
                continue  # vendor 自己都没猜出这一位驱动哪个字段，见 model.py 的
                          # EFXExpressionCurveItem 说明——无法定位目标，不瞎猜
            assign_type = own_fields.get(curve.bit_name)
            if isinstance(assign_type, bool) or not isinstance(assign_type, (int, float)):
                assign_type = _EXPR_ASSIGN_DEFAULT

            # 这条曲线的目标字段是不是确认过的弧度制角度字段——**不看**"角度显示"开关
            # （那是纯 UI 偏好），这里要的是引擎/文件格式层面的事实：全语料实测公式驱动
            # 角度字段时字面量按度写，`efx_sim.Simulator` 要据此把公式结果转成弧度再合成，
            # 见 `efx_sim/simulator.py::_ExprCurve.is_angle_degrees` 的说明。
            field_name = _sim().resolve_expr_field_name(base_name, curve.bit_name)
            entry = semantics.get_field_entry(sibling_obj.efx_attr_type, field_name)
            is_angle_degrees = semantics.is_angle_radians_field(entry)

            out.append((base_name, curve.bit_name, curve.formula, int(assign_type),
                       is_angle_degrees))
    return out


def config_from_scene(scene):
    """场景属性 -> SimConfig。待标定项全在这儿落地成开关。"""
    return _sim().SimConfig(
        seed=int(getattr(scene, "efx_re_sim_seed", 0)),
        fps=int(getattr(scene, "efx_re_sim_fps", 60)),
        random_dist=getattr(scene, "efx_re_sim_random_dist", "onesided"),
        life_model=getattr(scene, "efx_re_sim_life_model", "sum"),
        keep_hold_frame=getattr(scene, "efx_re_sim_keep_hold", "ignore"),
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
    """贴图标识 -> `gpu.types.GPUTexture`；拿不到返回 None（调用方退回纯色）。

    两种 key 都认：
    - **游戏内部路径**（`.uvs` 的贴图表给的），走 `asset_paths.resolve()` + 解码；
    - **`bpy.data.images` 里的名字**（网格材质上已经加载好的那张，见
      `_resolve_mesh_tris()`）——场景里已经有了，直接用，不再过一遍路径解析。
    先查图像数据块：内部路径不可能同时是一个已存在的图像名，不会认错。
    """
    if not tex_key:
        return None
    existing = bpy.data.images.get(tex_key)
    if existing is not None:
        try:
            return gpu.texture.from_image(existing)
        except Exception:   # noqa: BLE001
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


def _mesh_objects_under(obj, accum):
    """递归收集 `obj` 底下**没有 `~TYPE` 标记**的网格对象——那些是 `asset_link.py`
    （"一并导入引用的网格"）用 RE Mesh Editor 导进来、挂在 Entry 下面的，不是 EFX 自己的
    树节点。返回 `[(mesh_data, 相对 entry 的局部矩阵), ...]`。

    `accum` 是从 entry 累积下来的局部矩阵——RE Mesh Editor 可能建出多层子对象（LOD 组之类），
    每一层各自的 `matrix_local` 只相对**它自己的父**，要一路乘下来才是"相对 entry"的变换。
    """
    out = []
    for child in obj.children:
        if child.get("~TYPE") is not None:
            continue   # EFX 自己的对象（Entry/Attribute），不是导入的网格
        child_matrix = accum @ child.matrix_local
        if child.type == "MESH" and child.data is not None:
            out.append((child.data, child_matrix))
        out.extend(_mesh_objects_under(child, child_matrix))
    return out


def _resolve_mesh_tris(entry_obj):
    """entry 下面绑定的网格对象（们）的三角形，转换到"相对 entry"的坐标系，缓存供逐粒子
    复用（只在 track 重建时算一次——网格顶点数可能上千，逐帧重算划不来）。

    找不到就返回空列表，`TypeMeshV2` 未绑定网格 / 没装 RE Mesh Editor 是正常情况，胶水层
    据此画占位框，不是这里的错误。
    """
    tris = []
    for mesh, local in _mesh_objects_under(entry_obj, Matrix.Identity(4)):
        try:
            mesh.calc_loop_triangles()
        except Exception:   # noqa: BLE001 —— 拿不到三角化数据就跳过这一份，不拖垮整条预览
            continue
        verts = [local @ v.co for v in mesh.vertices]
        uv_layer = mesh.uv_layers.active
        uvs = uv_layer.data if uv_layer is not None else None
        looks = [_material_preview_look(m) for m in mesh.materials] or [(None, (1.0, 1.0, 1.0))]
        for lt in mesh.loop_triangles:
            a, b, c = lt.vertices
            if uvs is not None:
                l0, l1, l2 = lt.loops
                uv = (tuple(uvs[l0].uv), tuple(uvs[l1].uv), tuple(uvs[l2].uv))
            else:
                uv = ((0.0, 0.0),) * 3
            look = looks[lt.material_index] if lt.material_index < len(looks) else looks[0]
            tris.append((verts[a], verts[b], verts[c], uv[0], uv[1], uv[2]) + look)
    return tris


def _material_preview_look(material):
    """一个材质在预览里长什么样：`(贴图名, 染色 RGB)`。

    **染色必须从材质上取，不能只靠模拟层的 `Color`/`EmissiveColor`**：实测这个 mod 的全部
    24 个 `TypeMeshV2`，两个字段都是纯白 `(1,1,1)`——EFX 侧压根没有颜色信息，真正的颜色在
    材质的 `EmissiveParam` 里（`asset_link._wire_emission()` 把它放进了 `EFX Emissive Tint`
    节点）。不取它，预览就只能是"白 × 白"，怎么调都是一块白。

    取值顺序：自发光染色（`EFX Emissive Tint`）-> `ColorParam` -> 白。

    贴图取的是 **`AlphaMap`（遮罩）优先**，不是 `BaseMap`：`_mesh_shader()` 只拿它当遮罩用
    （形状），颜色走顶点色。VFX 网格的镂空全在遮罩里，拿 `BaseMap` 会画出一堆实心方片。
    没有遮罩槽的材质才退回 `BaseMap`/`EmissiveMap`——那种材质本来就是实心的。

    优先 `BaseMap`、其次 `EmissiveMap`——节点的 `label` 就是 mdf2 里的贴图槽名
    （`asset_link.py` 换覆盖贴图时认的也是它）。**预览不求还原材质**：它只有一个
    "贴图 × 顶点色"的 shader，没有节点图求值，所以取主贴图是能拿到的最接近的东西。

    不取图的后果不是"少个细节"，是**整片纯白**：`_draw_inner()` 拿不到贴图就退回
    FLAT_COLOR，而 `TypeMeshV2` 的 `Color` 绝大多数是白色（真正的颜色在材质里），
    于是每个网格都糊成一块白。
    """
    white = (1.0, 1.0, 1.0)
    if material is None or material.node_tree is None:
        return None, white

    tint = white
    for label, socket in (("EFX Emissive Tint", "Color2"), ("ColorParam", "Color")):
        node = next((n for n in material.node_tree.nodes if n.label == label), None)
        if node is not None and socket in node.inputs:
            value = node.inputs[socket].default_value
            tint = (value[0], value[1], value[2])
            break

    nodes = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    for want in ("AlphaMap", "BaseMap", "EmissiveMap"):
        for node in nodes:
            if node.label == want:
                return node.image.name, tint
    return (nodes[0].image.name if nodes else None), tint


def _make_track(entry_obj, scene):
    blocks = build_blocks(entry_obj)
    # 具名参数表从 EFX_ROOT 上取，和面板读数走同一个采集函数（expr_preview），否则同一条
    # 公式在面板和预览里会给出两个数
    from . import expr_preview
    sim = _sim().Simulator(blocks, config_from_scene(scene),
                           resources=_resources_for(entry_obj),
                           expressions=collect_expressions(entry_obj),
                           expr_parameters=expr_preview.collect_expr_parameters(
                               io_tree.find_root(entry_obj)))
    return {"sim": sim, "name": entry_obj.name, "obj": entry_obj,
            "items": [], "outline": [], "mesh_tris": _resolve_mesh_tris(entry_obj),
            "spawn_depth": 0, "origin_offset": None}


def rebuild_tracks(context, keep_frame=True):
    """按当前选中的 entry 重建全部 track。返回 track 数。"""
    scene = context.scene
    old_frame = _P["tracks"][0]["sim"].em.frame if _P["tracks"] else -1

    fresh = []
    for entry in active_entries(context):
        try:
            fresh.append(_make_track(entry, scene))
        except Exception as exc:   # noqa: BLE001 —— 失败的 entry 单独跳过并报出来
            _P["error"] = "%s: %s" % (entry.name, exc)
    _P["tracks"] = fresh
    _P["duration"] = _resolve_duration(scene)
    _P["spawned_count"] = 0   # 重建整批丢弹掉所有召唤出的 track，计数跟着清零

    if keep_frame and old_frame > 0:
        # 快进回原来那一帧：不快进的话，拖一下开关画面就跳回第 0 帧，调参时没法比较前后。
        # 确定性重放保证快进结果与连续播放一致。
        target = min(old_frame, _REBUILD_CATCHUP_MAX)
        for tr in fresh:
            tr["sim"].run_to(target)
            # 快进期间死亡触发的 PtLife 召唤请求原样丢弃，不补播——这条捷径本来就是
            # "跳过这些帧的画面"，没道理反而把跳过期间召唤的效果从第 0 帧原样重放一遍。
            del tr["sim"].em.spawn_requests[:]
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
# PtLife 召唤 Action -> 动态 track
# ---------------------------------------------------------------------------

#: 递归上限：`Actions[i].PlayEmitter` 内嵌完整子树，真实文件里存在循环/深嵌套引用
#: （见 `efx_sim.state.SpawnRequest` 类文档），不设上限会卡死预览。
_MAX_ACTION_SPAWN_DEPTH = 4
#: 一次播放里最多展开这么多个召唤出的 track（不管深度），双重上限一起兜底。
_MAX_SPAWNED_TRACKS_PER_SESSION = 32


def _action_nested_entries(source_entry_obj, action_index):
    """`Actions[action_index]` 的 `PlayEmitter` 内嵌的全部 Entry；没有就是空列表。

    `action_index` 是相对 `source_entry_obj` 自己所在那棵 EFX_ROOT 的 `Actions` 顺序——
    嵌套 `efxrData` 子树自己也有一张独立的 `Actions` 列表，`io_tree.find_root()` 按"离这个
    对象最近的 EFX_ROOT"解析，嵌套场景下天然对齐，不需要额外传"当前在哪一层"。
    """
    root = io_tree.find_root(source_entry_obj)
    if root is None:
        return []
    actions = io_tree.root_actions(root)
    if not (0 <= action_index < len(actions)):
        return []
    action_obj = actions[action_index]
    out = []
    for attr in action_obj.children:
        if attr.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if model.short_attr_name(attr.efx_attr_type) != "PlayEmitter":
            continue
        nested_root = attr.efx_nested_root
        if nested_root is not None and nested_root.get("~TYPE") == model.TYPE_ROOT:
            out.extend(io_tree.root_entries(nested_root))
    return out


def _spawn_action_tracks(tr, scene):
    """把 `tr` 这一步新产出的 `SpawnRequest`（`PtLife` 死亡时召唤）翻译成新的 track，
    直接接进 `_P["tracks"]`，让它们和其余 track 共用同一个时钟继续往下播。

    只处理 `kind == "action"`（`PtLife` 唯一产出的种类，见 `efx_sim/behaviors/ptlife.py`）。
    召唤点是**召唤那一刻的世界位置的静态快照**——不跟着任何东西继续走，语料/实机都没有
    证据说明被召唤的效果应该跟随死掉的粒子，就近似成最简单的"钉在那个点"。
    """
    em = tr["sim"].em
    reqs = list(em.spawn_requests)
    del em.spawn_requests[:]      # 已经消化，不管展开成不成功都不留给下一帧重复处理
    if not reqs:
        return
    entry_obj = tr.get("obj")
    if entry_obj is None:
        return
    depth = tr.get("spawn_depth", 0)
    if depth >= _MAX_ACTION_SPAWN_DEPTH:
        em.note("PtLife 召唤链超过 %d 层，本预览不再继续展开（防止循环/深嵌套卡死）"
                % _MAX_ACTION_SPAWN_DEPTH)
        return

    base_matrix = _entry_matrix(entry_obj)
    for req in reqs:
        if req.kind != "action":
            continue
        nested_entries = _action_nested_entries(entry_obj, req.target)
        if not nested_entries:
            continue
        origin = Matrix.Translation(_to_world(base_matrix, req.pos))
        for nested_entry in nested_entries:
            if _P["spawned_count"] >= _MAX_SPAWNED_TRACKS_PER_SESSION:
                em.note("本次预览召唤的 Action 已达上限（%d 个 track），其余不再展开"
                        % _MAX_SPAWNED_TRACKS_PER_SESSION)
                return
            try:
                new_tr = _make_track(nested_entry, scene)
            except Exception:
                continue
            new_tr["spawn_depth"] = depth + 1
            new_tr["origin_offset"] = origin
            _P["tracks"].append(new_tr)
            _P["spawned_count"] += 1


# ---------------------------------------------------------------------------
# 坐标换算
# ---------------------------------------------------------------------------

def _entry_matrix(entry_obj):
    """entry 的世界矩阵。

    用**完整矩阵**而不只是位置：`Transform3D` 的位置/旋转/缩放已经由
    `transform3d_view.py` 烘进了这个矩阵，多层嵌套 entry 的叠加也由 Blender 自己算好了
    ——乘上去就全部继承，模拟层因此完全不必知道 `Transform3D`、骨骼绑定这些事
    （见 docs/SIM_PORT_PLAN.md §5.1）。

    **这里只用静态烘焙矩阵，不叠 `Transform3D` 的逐帧旋转/缩放增量**——那条路已经试过、
    被真实场景推翻：`RIBBON`（`TypeRibbonFollow`）这类渲染体的几何是跨越多帧的历史轨迹
    （`p.trail`），如果在渲染时把"当前这一帧"的旋转/缩放矩阵统一叠给全部历史点，整条尾迹
    会跟着当前朝向刚体转动，而不是被粒子自己逐帧的运动"甩"出一条弧线——本末倒置。正确的
    地方是 `efx_sim/behaviors/parentoptions.py`：把旋转/缩放**增量**逐帧烘进 `p.pos`
    本身（和位置漂移一直以来的做法对称），这样 `p.trail` 里的历史点天然就是"那一刻真实
    在哪"，这里只需要套一次性的静态矩阵。见 parentoptions.py 模块说明。
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


_MESH_SHADER = None


def _mesh_shader():
    """网格专用 shader：**颜色来自顶点色，透明度来自贴图的遮罩**。

    和 billboard 那个 `texture * v_col` 不同，不能直接复用——VFX 网格的形状**全靠遮罩**：
    那些环、弧、光条在几何上就是一整张方片，镂空是贴图给的。照 billboard 那样只乘上去，
    贴图自己的 alpha 恒为 1，方片就整块实心画出来，一堆方片叠在一起就是一坨不透明的块
    （实测截图：预览里整个特效糊成一团淡紫，而视口里是有镂空的剑+环）。

    `mask = max(r, g, b) * a` 同时吃两种存法，不用管遮罩到底在哪个通道：VFX 的遮罩贴图
    总有一边是常数 1（`01_ring_alpha000` 是 alpha 恒 1、形状在 R；`base9.tex` 反过来是
    RGB 恒白、形状在 alpha），乘起来正好取到有信息的那个。

    颜色只取顶点色、不取贴图 RGB：遮罩贴图的 RGB 是**遮罩本身**（那张环是纯红的），
    拿它当颜色会画出一个红环。真正的颜色在顶点色里（材质染色，见
    `_material_preview_look()`）。
    """
    global _MESH_SHADER
    if _MESH_SHADER is not None:
        return _MESH_SHADER
    iface = gpu.types.GPUStageInterfaceInfo("efx_re_sim_mesh_iface")
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
        "  vec4 t = texture(image, v_uv);"
        "  float mask = max(max(t.r, t.g), t.b) * t.a;"
        "  FragColor = vec4(v_col.rgb, mask * v_col.a);"
        "}")
    _MESH_SHADER = gpu.shader.create_from_info(info)
    return _MESH_SHADER


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


def _camera_forward(rv3d):
    """视图矩阵第三行——只用来给 RIBBON 求"段方向 × 它"的横向，符号无所谓（叉乘定横向时
    整体反向只会让两侧顶点互换，三角形本身不变）。"""
    vm = rv3d.view_matrix
    return Vector((vm[2][0], vm[2][1], vm[2][2]))


def _to_world_dir(matrix, v):
    """方向向量（不带位移）：entry 矩阵只取旋转/缩放的 3x3 部分，再归一化丢掉缩放。

    `PLANE`（`TypePolygon`）的 `axis_u`/`axis_v` 走这条，不能像 `_to_world` 那样把位置也
    加上去；也不能直接照搬 `it.size` 那条"位置过矩阵、尺寸不过"的先例——朝向必须跟着 entry
    转，只是转完要丢掉矩阵里的缩放分量，否则非等比缩放会把正交的 u/v 拉斜。
    """
    d = matrix.to_3x3() @ coords.game_pos_to_blender(v.x, v.y, v.z)
    return d.normalized() if d.length > 1e-9 else Vector((1.0, 0.0, 0.0))


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


def _collect_ribbon(it, matrix, fwd, buckets):
    """`RIBBON`（`TypeRibbonLength`）：把 `it.points`（局部坐标，base→tip）摊成三角带。

    每一段的横向 = 段方向 × 相机视线，条带的宽面永远转向相机——Trail Renderer 的标准做法，
    仿姊妹项目 EFX-Editor `blender_efx/sim_preview.py::_emit_ribbon()`（本仓没有它的 numpy
    整批版本，粒子数还没到需要那条快路的规模）。没有贴图，恒落进 `tex_key=None` 那一桶，
    和纯色 billboard 三角形共用同一条绘制路径。
    """
    pts = it.points
    n = len(pts)
    world = [_to_world(matrix, q) for q, _hw, _a in pts]
    col = tuple(it.color)
    bucket = buckets.setdefault(it.tex_key, {"pos": [], "col": [], "uv": []})

    sides = [None] * n
    for i in range(n):
        a = world[i - 1] if i else world[0]
        b = world[i + 1] if i < n - 1 else world[n - 1]
        s = (b - a).cross(fwd)
        if s.length_squared > 1e-12:
            sides[i] = s.normalized()

    for i in range(n - 1):
        s0, s1 = sides[i], sides[i + 1]
        if s0 is None or s1 is None:
            continue
        _q0, hw0, a0 = pts[i]
        _q1, hw1, a1 = pts[i + 1]
        l0, r0 = world[i] - s0 * hw0, world[i] + s0 * hw0
        l1, r1 = world[i + 1] - s1 * hw1, world[i + 1] + s1 * hw1
        c0 = (col[0], col[1], col[2], col[3] * a0)
        c1 = (col[0], col[1], col[2], col[3] * a1)
        bucket["pos"].extend((tuple(l0), tuple(r0), tuple(r1),
                              tuple(l0), tuple(r1), tuple(l1)))
        bucket["col"].extend((c0, c0, c1, c0, c1, c1))
        bucket["uv"].extend(((0.0, 0.0),) * 6)


def _collect_mesh(it, matrix, mesh_tris, buckets):
    """`MESH`（`TypeMeshV2`）：把 track 缓存的三角形（相对 entry 局部坐标）实例化到这个
    粒子的位置/旋转/缩放上，再过 entry 矩阵落到世界坐标。

    `coords.local_matrix_to_blender()` 已经把 game 坐标系的 pos/rot/scale 转成一个
    Blender 矩阵（Transform3D 用的就是它）——这里直接复用，不重新发明一遍轴变换。
    `EmissiveColor`（已乘 `EmissiveRate`）按加法叠在底色上，近似"自发光让网格更亮"，
    不是真正的加法混合通道（预览没有第二条渲染 pass），足够看出"这里该发光"。
    """
    pos = it.pos
    rx, ry, rz = it.extra.get("rot", (0.0, 0.0, 0.0))
    rot_order = it.extra.get("rot_order", 0)
    size = it.size
    inst = coords.local_matrix_to_blender(
        (pos.x, pos.y, pos.z), (rx, ry, rz), (size.x, size.y, size.z), rot_order)
    world = matrix @ inst

    er, eg, eb = it.extra.get("emissive", (0.0, 0.0, 0.0))
    col = it.color
    final = (min(1.0, col[0] + er), min(1.0, col[1] + eg), min(1.0, col[2] + eb), col[3])

    # 按**每个三角形自己的**贴图分桶：一份网格里不同段可以是不同材质，而且这里的 key 是
    # `bpy.data.images` 的名字（`_resolve_mesh_tris()` 从材质节点上取的），不是 `.uvs` 那种
    # 游戏内部路径——`_gpu_texture()` 两种都认。
    for a, b, c, uv_a, uv_b, uv_c, tex_key, tint in mesh_tris:
        # `("MESH", key)` 这个 key 形状既做分桶又做路由：绘制时按它挑 `_mesh_shader()`，
        # billboard 那条路（key 是裸字符串）完全不受影响。
        bucket = buckets.setdefault(("MESH", tex_key or it.tex_key),
                                    {"pos": [], "col": [], "uv": []})
        # 材质的染色**乘**进来：EFX 侧的 Color/EmissiveColor 常常是纯白，颜色全在材质里
        # （见 `_material_preview_look()`）。加法叠完再乘，两边的信息都留住。
        shaded = (final[0] * tint[0], final[1] * tint[1], final[2] * tint[2], final[3])
        bucket["pos"].extend((tuple(world @ a), tuple(world @ b), tuple(world @ c)))
        bucket["col"].extend((shaded, shaded, shaded))
        bucket["uv"].extend((uv_a, uv_b, uv_c))


#: 占位框（没绑定网格 / 没装 RE Mesh Editor 时）的 12 条棱，用 ±0.5 的单位立方体归一化坐标
#: 表示，画的时候按 `it.size` 缩放——同 `EmitterShape3D` 线框走 `_OUTLINE_COLOR` 那条素材。
_BOX_EDGES = [(a, b) for a in range(8) for b in range(a + 1, 8)
             if sum(1 for t in range(3)
                    if ((a >> t) & 1) != ((b >> t) & 1)) == 1]
_BOX_CORNERS = [(-0.5 if not (i & 1) else 0.5,
                -0.5 if not (i & 2) else 0.5,
                -0.5 if not (i & 4) else 0.5) for i in range(8)]


def _collect_mesh_placeholder(it, matrix, lines, line_cols):
    """没有绑定网格（未装 RE Mesh Editor / `asset_link.py` 没跑过 / 网格引用解析失败）时的
    占位框，同 EFX-Editor MESH 的约定："未绑定时预览只画一个占位框"，不是不画。

    不叠旋转——占位框只是"这里有个东西、大概这么大"的提示，不用假装知道朝向。
    """
    center = _to_world(matrix, it.pos)
    s = it.size
    scale = Vector((max(1e-4, abs(s.x)), max(1e-4, abs(s.y)), max(1e-4, abs(s.z))))
    corners = [center + Vector((cx * scale.x, cy * scale.y, cz * scale.z))
              for cx, cy, cz in _BOX_CORNERS]
    for a, b in _BOX_EDGES:
        lines.append(tuple(corners[a]))
        lines.append(tuple(corners[b]))
        line_cols.append(_OUTLINE_COLOR)
        line_cols.append(_OUTLINE_COLOR)


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
        base = _entry_matrix(tr["obj"]) if tr["obj"] else None
        offset = tr.get("origin_offset")
        # `origin_offset`：`PtLife` 召唤出的 track——被召唤的 Entry 是嵌套 efxrData 子树里
        # 悬空的对象，`matrix_world` 只有它自己的静态烘焙、不知道自己是在哪个世界位置被
        # 召唤的，召唤点这层平移必须在外面叠一次（见 _spawn_action_tracks()）。
        tr["matrix"] = (offset @ base) if (base is not None and offset is not None) else base


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
    fwd = _camera_forward(rv3d)

    mesh_tris = tr.get("mesh_tris")
    for it in tr["items"]:
        if it.kind == "RIBBON":
            if it.points:
                _collect_ribbon(it, matrix, fwd, buckets)
            continue

        if it.kind == "MESH":
            if mesh_tris:
                _collect_mesh(it, matrix, mesh_tris, buckets)
            else:
                _collect_mesh_placeholder(it, matrix, lines, line_cols)
            continue

        center = _to_world(matrix, it.pos)
        col = tuple(it.color)
        if it.kind == "POINT":
            hw = hh = max(1e-4, it.size.x)
            r, u = _spin(right, up, getattr(it, "rot", 0.0))
        else:
            hw = max(1e-4, it.size.x * 0.5)
            hh = max(1e-4, it.size.y * 0.5)
            if it.axis_u is not None and it.axis_v is not None:
                # 固定朝向（`TypePolygon`）：用属性给的横/纵轴，不朝相机现算
                r, u = _to_world_dir(matrix, it.axis_u), _to_world_dir(matrix, it.axis_v)
            else:
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
        is_mesh = isinstance(key, tuple)
        tex_key = key[1] if is_mesh else key
        tex = _gpu_texture(tex_key) if (tex_key and use_tex) else None
        if tex is None:
            # 拿不到贴图就画纯色，**不跳过**——粒子还在那儿，只是没贴图；
            # 直接不画会让人以为模拟出错了。
            batch_for_shader(flat, "TRIS",
                             {"pos": b["pos"], "color": b["col"]}).draw(flat)
            continue
        shader = _mesh_shader() if is_mesh else _tex_shader()
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
    # `PtLife` 召唤出的 track 是这一轮播放专属的——直接丢掉，下一轮播到同一个死亡点时
    # 会重新召唤，不需要（也不该）保留身份跨轮复用。
    _P["tracks"] = [tr for tr in _P["tracks"] if not tr.get("spawn_depth")]
    _P["spawned_count"] = 0
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
        # 用快照迭代：新召唤出的 track 从下一次 step 才开始跑，不在诞生的这一步就被
        # 提前推进——这一帧的粒子数/死亡判定不该受"这一帧还召唤了别的东西"影响。
        for tr in list(_P["tracks"]):
            tr["sim"].step()
            _spawn_action_tracks(tr, scene)
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
    bl_description = "播放当前范围内 Entry 的粒子预览。预览是近似，不是游戏画面"
    bl_options = {"REGISTER"}

    _timer = None

    @classmethod
    def poll(cls, context):
        return bool(active_entries(context))

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
        scene = context.scene
        for tr in list(_P["tracks"]):
            tr["sim"].step()
            _spawn_action_tracks(tr, scene)
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

        # 生成区域线框：不依赖播放，所以画在播放按钮之外、始终可见（见 es3d_overlay.py）
        from . import es3d_overlay
        es3d_overlay.draw_button(layout, context)

        scene = context.scene
        scope_row = layout.row(align=True)
        scope_row.prop(scene, "efx_re_sim_scope", text="")
        if scene.efx_re_sim_scope == "GROUP":
            scope_row.prop(scene, "efx_re_sim_group", text="")

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
            n = len(active_entries(context))
            key = "sim.group_entries" if scene.efx_re_sim_scope == "GROUP" else "sim.selected_entries"
            layout.label(text=i18n.T(key) % n, translate=False)
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
    "sim.group_entries": {"ZH": "该分组命中 %d 个 Entry", "EN": "%d entries matched"},
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
    # 标定开关（rot_applied 等）同样决定线框的形状，独立叠加层也要一起重建
    from . import es3d_overlay
    es3d_overlay.invalidate()


def register():
    i18n.add_strings(_STRINGS)

    bpy.types.Scene.efx_re_sim_scope = EnumProperty(
        name="Scope",
        items=[("SELECTION", "Selection", ""), ("GROUP", "Group", "")],
        default="SELECTION", update=_on_knob_changed,
        description="预览目标 Entry 的来源：视口里选中的对象，还是按当前 Active EFX 的分组批量指定")
    bpy.types.Scene.efx_re_sim_group = EnumProperty(
        name="Group", items=_group_enum_items, update=_on_knob_changed,
        description="Scope 为 Group 时按 efx_groups 标签筛选 Entry，选 All Entries 就是整个 EFX")

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

    for name in ("efx_re_sim_scope", "efx_re_sim_group",
                 "efx_re_sim_speed", "efx_re_sim_duration", "efx_re_sim_mode",
                 "efx_re_sim_seed", "efx_re_sim_fps", "efx_re_sim_max_particles",
                 "efx_re_sim_show_outline", "efx_re_sim_use_textures",
                 "efx_re_sim_uvs_speed_unit", "efx_re_sim_uvs_playback",
                 "efx_re_sim_uvs_once_span",
                 "efx_re_sim_velocity_unit",
                 "efx_re_sim_random_dist", "efx_re_sim_life_model",
                 "efx_re_sim_keep_hold", "efx_re_sim_es3d_range",
                 "efx_re_sim_rot_applied"):   # es3d_range 已废弃，留着好清掉旧场景里的残留
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
