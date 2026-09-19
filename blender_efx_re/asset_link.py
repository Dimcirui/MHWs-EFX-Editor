"""
blender_efx_re/asset_link.py —— 导入 .efx 时顺带把它引用的 `.mesh` / `.mdf2` / `.tex` / `.uvs`
一起拉进来（`EFX_RE_OT_import` 上两个默认关的勾选项）

角色对齐姊妹项目 EFX-Editor 的 `mod3_link.py` + `uvs_link.py`（那边是 MHWI 的 mod3/mrl3），
但引擎、依赖的第三方插件、以及"载进来之后放哪"三件事都不一样：

- **mesh 交给 RE Mesh Editor**，我们只负责"把游戏内部路径解析成磁盘文件 + 把 `.mdf2` 一并
  指给它 + 把导入出来的对象挂到对应的 Entry 下面"。`.mesh` 的解码本仓一行都不写——那是
  另一个成熟插件的活，重写一份只会多一份要跟着游戏更新维护的代码。
  调用约定照抄 Modding-Toolkit 的批量导入（`games/mhws/batch_import.py`）：
  `directory` + `files` + `loadMaterials` + `loadMDFData` + `loadShellFur` + `mdfPath`，
  这组参数是那边跑了整套装备语料验过的。
- **`.uvs` 建成本仓自己的 UVS Object**（`uvs_io.build_uvs_root()`），不是像姊妹项目那样
  塞进 attribute 自己的属性里——本仓的 UVS 是独立的顶层可编辑结构（见 uvs_model.py）。
- **`.tex` 两条路**：mesh 材质的贴图由 RE Mesh Editor 自己解码（走它的贴图缓存），`.uvs` 的
  序列帧大图走本仓的 `tex_image.load_image()`（GDeflate + 块格式，见那边模块说明）。

⚠ RE Mesh Editor 的算子命名空间有两个
------------------------------------
原版（NSACloud）注册在 `re_mesh`，社区分支 REME（TrueShadow01）把**整个 mesh 算子分类**
改名成 `re_mesh_cm`（mdf/chain/clsp 那几个分类没改）。而 `hasattr(bpy.ops.re_mesh, "x")`
**永远返回 True**——`bpy.ops` 的属性访问是惰性的，任何名字都会给你一个包装器；只有
`dir(bpy.ops.<分类>)` 才列出真正注册了的算子。这两条都是 Modding-Toolkit
`core/re_mesh_compat.py` 踩出来的，照搬。

⚠ 只读 EFX 侧数据
-----------------
本模块**不写任何参与导出的字段**（`efx_fields` / `efx_opaque_text` / …）。写的只有两样：
Blender 的对象父子关系（`Object.parent`，`io_tree.export_*` 完全不看它，只按 `~TYPE` 筛），
以及 attribute 上的编辑期状态 `efx_mdf_reference` / `efx_mdf_mismatched`（同样不参与导出，
见 model.py 的属性注册说明）。门禁 `tools/verify_blender_asset_link.py` 守这条：联动跑完
再导出，字节必须与跑之前逐字节相同。

先在这个 efx 自己旁边找
----------------------
路径解析本身全交给 `asset_paths.resolve()`，但**根目录的第一来源是被导入的那个 `.efx`
自己的位置**（`Collection.efx_source_dir` 向上回溯到含 `natives/` 的那一层，见
`_source_dir()`）——不是 Asset Browser 的语料目录。mod 工程目录里那几个自制资源正是用户
想看的，拿语料目录当首选会静默加载到官方原版文件，同名不同内容、界面上看不出来。

找不到就如实说，不编占位
------------------------
每一层解析失败都进 `problems` 列表，由 `report_problems()` 统一报出来（铁律 #1）。

mesh 和 mdf2 的材质名对不上 -> 自己把材质套上去
----------------------------------------------
EFX 的 `MeshPath` 和 `MaterialPath` **不是配套的一对**：EFX 就是要"拿这个材质去渲染这个
网格"，游戏侧整份替换、不按名字对，所以两边的材质名完全可以不一样。而 RE Mesh Editor 是
**按材质名**绑的，对不上时只打一句 "Material 'xxx' is not in the MDF, cannot import"，
结果是个没有任何贴图的灰材质——界面上看不出原因。实测 52 对真实引用里 **11 对（21%）**
名字对不上（例：`11_plane.mesh` 的 `lambert1` 配 `11_cm_null_00.mdf2` 的 `lambert2`）。
`_ensure_material_applied()` 在这种情况下手动补一次，判据卡死在"双方都只有一个材质"
（52/52 的 mdf2 都是单材质），多材质不猜、如实记 problem。

导进来的网格归拢到一个集合里
--------------------------
RE Mesh Editor 默认把它建的 `xxx.mesh` 集合直接挂在场景根上。一个 efx 引用十来个网格时
大纲视图会被平铺的一堆集合淹掉，看不出哪个属于哪个 efx——所以导入产物整体挪进
`<EFX_ROOT>/<名字>_Meshes`（`_meshes_collection()`，按 `~TYPE` 标记找，不按名字找）。
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import bpy

from . import (asset_paths, bridge, i18n, io_tree, mdf_catalog, model,
               structure_ops, tex_image, uvs_io, uvs_model)

# ---------------------------------------------------------------------------
# RE Mesh Editor 在场检测（见模块头部 ⚠）
# ---------------------------------------------------------------------------

#: mesh 算子可能注册在哪些分类下。顺序只用于并列时取第一个，两个都会检查。
_MESH_OP_CATEGORIES = ("re_mesh", "re_mesh_cm")


def _category_has_op(category: str, op_name: str) -> bool:
    submodule = getattr(bpy.ops, category, None)
    if submodule is None:
        return False
    try:
        return op_name in dir(submodule)
    except Exception:   # noqa: BLE001 —— 探测第三方插件，任何异常都只意味着"它不在"
        return False


def mesh_importer_available() -> bool:
    """RE Mesh Editor（或社区分支 REME）的 `.mesh` 导入算子在不在。"""
    return any(_category_has_op(cat, "importfile") for cat in _MESH_OP_CATEGORIES)


def _call_mesh_op(op_name: str, *args, **kwargs):
    for cat in _MESH_OP_CATEGORIES:
        if _category_has_op(cat, op_name):
            return getattr(getattr(bpy.ops, cat), op_name)(*args, **kwargs)
    raise RuntimeError(
        f"找不到 RE Mesh Editor 的 '{op_name}' 算子（{' / '.join(_MESH_OP_CATEGORIES)} 都没有）"
    )


# ---------------------------------------------------------------------------
# 遍历：EFX 树里引用了外部资源的 attribute
# ---------------------------------------------------------------------------

def iter_attribute_objects(root_col):
    """一个 EFX_ROOT 集合下全部 attribute 对象，yield `(attr_obj, owner_obj)`。

    `owner_obj` 是这个 attribute 所属的 Entry/Action 对象——网格要挂到它下面才能跟着
    `Transform3D` 摆位（见 transform3d_view.py）。嵌套的 `PlayEmitter.efxrData` 子树一并
    遍历，那里的 owner 取嵌套树自己的 Entry。
    """
    for owner in io_tree.root_entries(root_col) + io_tree.root_actions(root_col):
        yield from _walk_attributes(owner, owner)


def _walk_attributes(obj, owner):
    for child in obj.children:
        tag = child.get("~TYPE")
        if tag == model.TYPE_ATTRIBUTE:
            yield child, owner
            nested = child.efx_nested_root
            if nested is not None and nested.get("~TYPE") == model.TYPE_ROOT:
                yield from iter_attribute_objects(nested)
        elif tag in (model.TYPE_ENTRY, model.TYPE_ACTION):
            # 当前建树是扁平的（Entry 都在 *_Entries 集合里），这一档是防御式的，
            # 和 transform3d_view._sync_subtree() 保持同样的走法。
            yield from _walk_attributes(child, child)


def _string_field(attr_obj, keys) -> str:
    """按一组候选 key 读第一个非空 STRING 字段（字段名在不同 attribute 变体里不同，
    见 model.MESH_PATH_KEYS 的说明）。"""
    for key in keys:
        node = model.find_field(attr_obj.efx_fields, key)
        if node is not None and node.data_type == "STRING":
            value = (node.string_value or "").strip()
            if value:
                return value
    return ""


def iter_mesh_refs(root_col):
    """yield `(attr_obj, owner_obj, mesh_path, material_path)`，只含填了 mesh 路径的。

    `MirrorMeshPath` 不跟——MHWs 语料抽样 213/213 全是空的（见 model.MESH_PATH_KEYS）。
    """
    for attr_obj, owner in iter_attribute_objects(root_col):
        mesh_path = _string_field(attr_obj, model.MESH_PATH_KEYS)
        if mesh_path:
            yield attr_obj, owner, mesh_path, _string_field(attr_obj, model.MATERIAL_PATH_KEYS)


def iter_uvs_refs(root_col):
    """yield `(attr_obj, owner_obj, uvs_path)`，只含填了 `UVSPath` 的。"""
    for attr_obj, owner in iter_attribute_objects(root_col):
        uvs_path = _string_field(attr_obj, (model.UVS_PATH_KEY,))
        if uvs_path:
            yield attr_obj, owner, uvs_path


def _sequence_no(attr_obj) -> int:
    """`UVSequence.SequenceNo` 的主值（用 `.uvs` 里的第几条序列）。读不到按 0。

    `SequenceNo` 是 `via.RangeI`，**主值是二进制首字段 `r` 不是 `s`**——一律走
    `model.sr_children_ordered()`，别自己挑 key（见 CLAUDE.md "`{s,r}` 字段的主值"）。
    """
    node = model.find_field(attr_obj.efx_fields, "SequenceNo")
    if node is None:
        return 0
    pair = model.sr_children_ordered(node)
    try:
        return int(model.node_to_value(pair[0] if pair is not None else node))
    except (TypeError, ValueError):
        return 0


def _first_line(exc) -> str:
    return str(exc).strip().split("\n")[0]


def _source_dir(root_col) -> str:
    """这棵树是从哪个目录导进来的（`Collection.efx_source_dir`，导入时记的）。

    资源解析一律把它当**首选**根：一个 efx 引用的 `.mesh` / `.uvs` / `.tex` 绝大多数就在
    它自己那棵 `natives/STM` 树里（官方解包目录如此，mod 工程目录更是如此）。拿 Asset
    Browser 的语料目录当首选会在 mod 场景下静默加载到官方原版文件——同名不同内容，
    界面上完全看不出来。见 `asset_paths.search_roots()` 的优先级说明。

    嵌套的 `efxrData` 子树没有自己的来源目录（它是内嵌在外层文件里的，不是独立文件），
    取不到就沿父集合链往上找外层那个根。
    """
    col = root_col
    seen = set()
    while col is not None and col.name not in seen:
        seen.add(col.name)
        source_dir = getattr(col, "efx_source_dir", "") or ""
        if source_dir:
            return source_dir
        col = io_tree.collection_parent(col)
    return ""


# ---------------------------------------------------------------------------
# mesh + mdf2 + tex
# ---------------------------------------------------------------------------

def link_meshes(root_col) -> tuple[int, int, list]:
    """把这棵树里 `MeshPath` 引用的网格导进来、挂到对应 Entry 下面，并把 `MaterialPath`
    指的 `.mdf2` 设成该 attribute 的参考材质。

    返回 `(网格文件数, 参考材质数, 贴图覆盖数, 自发光材质数, 按 PartsStartNo 删掉的段数, problems)`，
    `problems = [(attribute 名, 引用路径, 原因), ...]`。

    RE Mesh Editor 不在场时**只做参考材质那一半**（那一半是纯本仓功能，不依赖它），
    网格那一半整批跳过并记一条 problem——不假装成功。
    """
    near = _source_dir(root_col)
    problems: list[tuple[str, str, str]] = []
    have_importer = mesh_importer_available()
    imported: dict[tuple, list] = {}
    n_mesh = n_material = n_override = n_emissive = n_trimmed = skipped = 0

    for attr_obj, owner, mesh_path, material_path in iter_mesh_refs(root_col):
        mdf_local = None
        if material_path:
            mdf_local = asset_paths.resolve(material_path, near=near)
            if mdf_local is None:
                problems.append((attr_obj.name, material_path, "找不到这个 .mdf2"))
            elif _bind_reference_material(attr_obj, mdf_local, problems):
                n_material += 1

        if not have_importer:
            # 逐条报同一句话没用——攒个数，最后报一条。
            skipped += 1
            continue

        mesh_local = asset_paths.resolve(mesh_path, near=near)
        if mesh_local is None:
            problems.append((attr_obj.name, mesh_path, "找不到这个 .mesh"))
            continue

        # **逐 attribute 各导一份**，不按 Entry 去重：`properties` 覆盖表是挂在
        # attribute 上的，同一份 mesh+mdf2 被两个 attribute 引用时贴图可以完全不同
        # （实测 `base8_0/1/2` 三个 attribute 共用一份网格，只有 AlphaMap 不一样）。
        # 共用一份对象既会让后应用的覆盖冲掉先应用的，也会让后挂的把先挂的从原来的
        # 位置上拽走（摆位靠父子关系）。
        key = (str(mesh_local).lower(), str(mdf_local or "").lower(), attr_obj.name)
        roots = imported.get(key)
        if roots is None:
            if mdf_local is not None:
                _prefetch_material_textures(mdf_local, near)
            # 顶点缓冲在 streaming 那一份里，RE Mesh Editor 自己按路径去拼——拼不到就
            # 整个导入失败（见 asset_paths.ensure_streaming_companion）。
            asset_paths.ensure_streaming_companion(mesh_local, mesh_path)
            try:
                roots, new_objects = _import_mesh_file(mesh_local, mdf_local, root_col)
            except Exception as ex:   # noqa: BLE001 —— 第三方算子，什么都可能抛
                problems.append((attr_obj.name, mesh_path,
                                 f"RE Mesh Editor 导入失败：{_first_line(ex)}"))
                imported[key] = []
                continue
            # ⚠ 删对象会让手上的 Python 引用全部失效（再碰就是
            # `ReferenceError: StructRNA of type Object has been removed`，连 `o.name`
            # 都读不了）。所以**先把名字抄下来**，删完再按名字重新取一遍。
            root_names = [obj.name for obj in roots]
            object_names = [obj.name for obj in new_objects]
            n_trimmed += _keep_parts(new_objects, attr_obj)
            alive = bpy.data.objects
            roots = [o for o in (alive.get(n) for n in root_names) if o is not None]
            new_objects = [o for o in (alive.get(n) for n in object_names) if o is not None]
            imported[key] = roots
            if roots:
                n_mesh += 1
                if mdf_local is not None:
                    _ensure_material_applied(
                        new_objects, mdf_local, material_path, attr_obj.name, problems)
                    # 必须排在兜底之后：兜底那步会把节点树整个重建，先应用会被冲掉。
                    n_override += _apply_property_overrides(
                        new_objects, attr_obj, mdf_local, material_path, near, problems)
                    # 排在贴图覆盖之后：它要读 EmissiveMap 节点上那张**已经换好**的图。
                    n_emissive += _apply_emissive_override(
                        new_objects, attr_obj, mdf_local, problems)
            else:
                problems.append((attr_obj.name, mesh_path, "RE Mesh Editor 没产出任何对象"))
        _parent_to_owner(roots, owner)

    if skipped:
        problems.append(("", f"{skipped} 个网格引用",
                         "没装 RE Mesh Editor（或社区分支 REME），网格那一半整批跳过"))
    return n_mesh, n_material, n_override, n_emissive, n_trimmed, problems


def _import_mesh_file(mesh_local: Path, mdf_local: Path | None, root_col) -> tuple[list, list]:
    """调 RE Mesh Editor 导入一个 `.mesh`，返回 `(顶层对象, 这次新建的全部对象)`。

    "顶层对象"= 没有父对象的那些，它们是要挂到 Entry 下面的；"全部对象"给材质兜底那步用。

    `EXEC_DEFAULT` 只走算子的 `execute()`，它的 `invoke()`（会去读用户偏好里的导入默认值）
    不触发——所以这里传的就是最终值，没传的走类属性默认值（`createCollections=True`、
    `rotate90=True`、`importAllLODs=False`）。参数集合和 Modding-Toolkit 批量导入一致，
    不多传没验过的键：第三方算子多一个不存在的关键字会直接 TypeError。

    `loadMDFData=False`：那个开关是把 mdf2 的材质参数建成一堆可编辑对象，本仓已经有自己的
    材质参数覆盖表 UI（`efx_mdf_reference` + `mdf_catalog.py`），不需要第二套。

    导入产物**整体挪进这棵 EFX 树自己的网格集合**（见 `_meshes_collection()`）：
    RE Mesh Editor 默认把它建的集合挂在场景根上，一个 efx 引用十来个网格时大纲视图会被
    平铺的一堆 `xxx.mesh` 淹掉，看不出哪个属于哪个 efx。
    """
    before_objects = set(bpy.data.objects.keys())
    before_collections = set(bpy.data.collections.keys())
    _call_mesh_op(
        "importfile", "EXEC_DEFAULT",
        directory=str(mesh_local.parent) + os.sep,
        files=[{"name": mesh_local.name}],
        loadMaterials=mdf_local is not None,
        loadMDFData=False,
        loadShellFur=False,
        mdfPath=str(mdf_local) if mdf_local is not None else "",
    )
    new_objects = [bpy.data.objects[n]
                   for n in sorted(set(bpy.data.objects.keys()) - before_objects)]
    new_collections = [bpy.data.collections[n]
                       for n in sorted(set(bpy.data.collections.keys()) - before_collections)]
    _regroup(new_objects, new_collections, root_col)
    return [obj for obj in new_objects if obj.parent is None], new_objects


def _regroup(new_objects, new_collections, root_col) -> None:
    """把这次导入产出的集合/对象从场景根挪进这棵 EFX 树的网格集合下面。

    只动**直接挂在场景根上**的那些：RE Mesh Editor 自己建的子集合（LOD 之类）已经在它
    父集合里了，跟着一起走，不该单独拎出来。集合里已经装着的对象不用再管——对象跟着
    集合走。剩下"散在场景根上的新对象"（`createCollections` 被关掉之类）单独收一遍。

    ⚠ 只改集合归属，**不碰对象的父子关系**：摆位靠 `_parent_to_owner()` 挂到 Entry 上，
    那是另一码事，两者在 Blender 里互相独立。
    """
    scene_root = bpy.context.scene.collection
    target = None
    for collection in new_collections:
        if collection.name not in scene_root.children:
            continue
        target = target or _meshes_collection(root_col)
        scene_root.children.unlink(collection)
        target.children.link(collection)

    for obj in new_objects:
        if scene_root not in list(obj.users_collection):
            continue
        target = target or _meshes_collection(root_col)
        scene_root.objects.unlink(obj)
        target.objects.link(obj)


def _meshes_collection(root_col):
    """这棵 EFX 树放导入网格的集合，没有就现建一个挂在 EFX_ROOT 下面。

    按 `~TYPE` 标记找，不按名字找：Blender 的集合名全局唯一，同时导入两个 efx 时第二个的
    `xxx_Meshes` 会被自动改成 `xxx_Meshes.001`，按名字查就会落空、每次都新建一个。
    """
    for child in root_col.children:
        if child.get("~TYPE") == model.TYPE_MESH_GROUP:
            return child
    collection = bpy.data.collections.new(f"{root_col.name}_Meshes")
    root_col.children.link(collection)
    collection["~TYPE"] = model.TYPE_MESH_GROUP
    collection.color_tag = "COLOR_01"   # 和 RE Mesh Editor 自己给 mesh 集合的颜色一致
    return collection


_GROUP_NAME_RE = re.compile(r"^(?:LOD\d+_)?Group_(\d+)_Sub_")


def _parts_range(attr_obj) -> tuple[int, int] | None:
    """`PartsStartNo` 的 `[Min, Max)`，取不到返回 `None`。左闭右开，见 `_keep_parts()`。"""
    node = model.find_field(attr_obj.efx_fields, "PartsStartNo")
    pair = model.sr_children_ordered(node) if node is not None else None
    if pair is None:
        return None
    try:
        lo, hi = int(model.node_to_value(pair[0])), int(model.node_to_value(pair[1]))
    except (TypeError, ValueError):
        return None
    return (lo, hi) if hi > lo else None


def _keep_parts(objects, attr_obj) -> int:
    """只留 `PartsStartNo` 指的那几段网格，其余整段删掉，返回删了几个对象。

    **一个 `.mesh` 里装着好几段**（RE Mesh Editor 按 `Group_<N>_Sub_<M>__<材质>` 命名），
    而一个 TypeMeshV2 attribute 只用其中一段——不筛的话，24 个 attribute 会把整份网格各导
    一遍全堆在一起（实测这个 mod：18 段 × 24 份），视口里就是一坨互相盖住的东西。

    下标是**这份 mesh 里第几段**（把出现过的 `Group_<N>` 去重排序后的序号），不是 `Group_`
    后面那个数字本身：拆过的 mesh 里那个数字保留着原模型的编号（`POD042_001.mesh` 只有
    `Group_15/16/17`，而它的三个 attribute 写的是 0/1/2）。

    左闭右开 `[Min, Max)` 的判据（用户的 `58_it00_904` + POD042 全套，24 个 attribute 全中）：
    `POD042_000.mesh` 段号 0~17 连续，attribute `[base5]` 的 `PartsStartNo` 是 `(6, 7)`，
    而 `Group_6` 正是材质为 `Base5` 的那段——`[6,7)` 命中，`(6,7]` 会落到 `Group_7`（材质
    `Base6`）。`base9_7` ↔ `(7,8)` ↔ `Group_7` 同理。attribute 的名字本身就把下标写在里面，
    是独立于统计的第二份证据。

    删而不是隐藏：每个 attribute 各导一份自己的副本，用不到的段是纯粹的垃圾，留着只会让
    场景重一个数量级；要回来重新导入一次就行。
    """
    span = _parts_range(attr_obj)
    if span is None:
        return 0
    lo, hi = span

    by_group: dict[int, list] = {}
    for obj in objects:
        match = _GROUP_NAME_RE.match(obj.name)
        if match is not None:
            by_group.setdefault(int(match.group(1)), []).append(obj)
    if not by_group:
        return 0

    ordered = sorted(by_group)
    keep = {ordered[i] for i in range(lo, min(hi, len(ordered))) if i >= 0}
    if not keep:
        return 0   # 范围整个落在这份网格之外：不猜、原样全留，别把网格删空

    removed = 0
    for group, group_objects in by_group.items():
        if group in keep:
            continue
        for obj in group_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
    return removed


def _parent_to_owner(objects, owner) -> None:
    """把导入出来的顶层对象挂到 Entry/Action 对象下面，让它跟着 `Transform3D` 摆位。

    `matrix_parent_inverse` 显式置成单位阵：要的就是"网格的世界变换 = Entry 的变换 ×
    网格自己的变换"，不是 Blender "保持当前位置"那套补偿。
    """
    for obj in objects:
        if obj.parent is not None:
            continue
        obj.parent = owner
        obj.matrix_parent_inverse.identity()


def _ensure_material_applied(new_objects, mdf_local: Path, material_path: str,
                             attr_name: str, problems: list) -> bool:
    """网格的材质名和 `.mdf2` 里的材质名对不上时，手动把材质套上去。返回是否补过。

    **为什么需要这一步**：RE Mesh Editor 是**按材质名**把 mdf2 的材质绑到网格上的
    （`importMDF()` 里 `mdfMaterialDict.get(materialName)`）。而 EFX 的 `MeshPath` 和
    `MaterialPath` 根本不是配套的一对——EFX 就是要"拿这个材质去渲染这个网格"，游戏侧整份
    替换、不按名字对。实测 52 对真实引用里 **11 对（21%）名字对不上**，这些的表现是
    材质建出来了但一张贴图都没有（控制台一句
    "Material 'xxx' is not in the MDF, cannot import" 就没了，界面上只看到个灰模型）。

    补的判据是 **`.mdf2` 里只有一个材质**：EFX 的 attribute 只有一个 `MaterialPath`、一张
    `properties` 覆盖表，**没有"第几个 submesh 用哪个材质"这一维**，所以单材质 mdf2 就是
    整只网格的材质——网格侧有几个材质槽都往上套，不存在"该套哪个"的歧义。真实语料里
    52/52 的 mdf2 都是单材质；网格侧多材质是常事（实测 `POD042_000.mesh` 有 6 个材质槽
    Base3~Base8，mdf2 只有一个 `lambert1`，全不匹配——那 6 个槽原来全是空节点树，
    在视口里就是纯黑）。
    mdf2 **本身**有多个材质时才是真歧义：不猜，记一条 problem 如实说（铁律 #1/#3）。

    这一步调的是 RE Mesh Editor 的**内部函数** `importMDF()`，不是算子：它没有"把某个
    mdf2 套到某个已存在的材质上"的算子入口（`re_mdf.apply_mdf` 要的是一整套 MDF 对象集合
    + 用户设过的 mod 目录，完全是另一条流程）。调用形状照抄它自己的两个调用点。
    """
    materials = {}
    for obj in new_objects:
        for slot in getattr(obj, "material_slots", []):
            if slot.material is not None:
                # Blender 撞名会加 `.001` 后缀，比名字时要去掉——RE Mesh Editor 自己
                # 在 `re_mdf.apply_mdf` 里也是这么 split 的。
                materials.setdefault(slot.material.name.split(".")[0], slot.material)
    if not materials:
        return False

    try:
        mdf_names = [m.get("name") or "" for m in (bridge.dump_mdf(mdf_local).get("materials") or [])]
    except Exception as ex:   # noqa: BLE001
        problems.append((attr_name, material_path, f"读 .mdf2 材质名失败：{_first_line(ex)}"))
        return False

    if set(materials) & set(mdf_names):
        return False   # 名字对得上，RE Mesh Editor 已经绑好了，不用管

    if len(mdf_names) != 1:
        problems.append((attr_name, material_path, (
            f"网格材质（{'/'.join(sorted(materials))}）和 .mdf2 材质"
            f"（{'/'.join(n for n in mdf_names if n)}）名字全对不上，而这个 .mdf2 有 "
            f"{len(mdf_names)} 个材质，没法确定哪个配哪个——材质没贴图是这个原因"
        )))
        return False

    for blender_material in materials.values():
        try:
            _apply_mdf_to_material(mdf_local, material_path, mdf_names[0], blender_material)
        except Exception as ex:   # noqa: BLE001 —— 用的是第三方内部函数，什么都可能抛
            problems.append((attr_name, material_path,
                             f"材质名对不上、手动套 .mdf2 也失败了：{_first_line(ex)}"))
            return False
    return True


def _apply_property_overrides(new_objects, attr_obj, mdf_local: Path, material_path: str,
                              near, problems: list) -> int:
    """把 attribute 的 `properties` 覆盖表里的**贴图覆盖**应用到导入出来的材质上，返回应用了几张。

    **这才是"导进来的网格纯黑纯白"的真因。** VFX 的 `.mdf2` 往往是个**占位材质**——贴图槽
    全填 `systems/rendering/NullWhite.tex` / `NullBlack.tex` 之类，真正的贴图由 EFX 侧的
    `properties` 覆盖表在运行时顶上去（这正是那张表存在的意义，见 mdf_catalog.py）。只导
    mdf2 不管覆盖表，拿到的就是 NullWhite（纯白）/ NullBlack（纯黑）。
    实测一个真实 mod（`58_it00_904.efx` -> `POD042_000.mdf2`）：mdf2 的 7 个贴图槽全是 Null，
    而 attribute 的覆盖表里 7 个槽全部被换成了真实贴图。

    槽位靠 `PropertyNameUTF8Hash` 认，**不猜名字**：`mdf_catalog.candidates()` 从参考材质
    里现算每个槽的 UTF-8 哈希，查表得到槽名（`BaseMap` / `EmissiveMap` / …），再去材质节点
    树里找 `label` 等于这个槽名的贴图节点——RE Mesh Editor 建节点时就是拿槽名当 label 的，
    两边天然对齐（实测 7/7 全部命中）。

    只覆盖**已经存在的贴图节点**：`loadUnusedTextures=False` 时 RE Mesh Editor 只给它认识
    的槽建节点（一般是 Base/Emissive/Alpha），Cube/Flow/Noise/Displacement 那几个没有节点
    可落——那几个在 Blender 的简易预览里本来也不参与成像，不为它们硬造节点。

    参数（`Float`/`Range`）那部分的覆盖**没做**：要落到 RE Mesh Editor 各版本自己搭的节点组
    里，挂钩点不稳定，而且对"看一眼这个特效长什么样"的贡献远小于贴图。如实留白，不假装。
    """
    node = model.find_field(attr_obj.efx_fields, "properties")
    if node is None or node.data_type != "ARRAY" or not len(node.children):
        return 0
    try:
        slot_by_hash = {e["utf8Hash"]: e["name"]
                        for e in mdf_catalog.candidates(str(mdf_local)) if e["kind"] == "texture"}
    except mdf_catalog.CatalogError as ex:
        problems.append((attr_obj.name, material_path,
                         f"读参考材质的贴图槽失败，贴图覆盖没应用：{_first_line(ex)}"))
        return 0
    if not slot_by_hash:
        return 0

    # 槽名 -> 这次导入出来的所有同名贴图节点
    nodes_by_slot: dict[str, list] = {}
    for obj in new_objects:
        for slot in getattr(obj, "material_slots", []):
            material = slot.material
            if material is None or material.node_tree is None:
                continue
            for tex_node in material.node_tree.nodes:
                if tex_node.type == "TEX_IMAGE" and tex_node.label:
                    nodes_by_slot.setdefault(tex_node.label, []).append(tex_node)
    if not nodes_by_slot:
        return 0

    applied = 0
    for child in node.children:
        values = model.node_to_value(child)
        if values.get("parameterType") != "Texture":
            continue
        internal = (values.get("texturePath") or "").strip()
        slot_name = slot_by_hash.get(values.get("PropertyNameUTF8Hash"))
        targets = nodes_by_slot.get(slot_name or "")
        if not internal or not targets:
            continue
        local = asset_paths.resolve(internal, near=near)
        if local is None:
            problems.append((attr_obj.name, internal, f"覆盖表里的 {slot_name} 贴图找不到"))
            continue
        try:
            image = tex_image.load_image(local)
        except Exception as ex:   # noqa: BLE001 —— 解码失败一律拒绝，不交噪声图
            problems.append((attr_obj.name, internal,
                             f"{slot_name} 贴图解码失败：{_first_line(ex)}"))
            continue
        _apply_colorspace(image, slot_name, internal)
        for tex_node in targets:
            tex_node.image = image
            _retarget_mask_channel(tex_node, image)
            _soften_degenerate_alpha_test(tex_node, image)
        applied += 1
    return applied


#: RE Mesh Editor 的 albedo 槽名单拿不到时的兜底（它那份有几十个名字，这里只列真实 VFX
#: 材质里见过的）。**只在 import 失败时用**，正常路径一律读它的那份，免得两边漂开。
_FALLBACK_ALBEDO_SLOTS = frozenset({"BaseMap", "BaseAlphaMap", "BaseMetalMap",
                                    "BaseDielectricMap", "ALBD", "ALBDmap"})


#: 图像名 -> (RGB 有没有变化, Alpha 有没有变化)。采样一次几百毫秒，按名字缓存。
_CHANNEL_VARIATION: dict = {}
#: 判"这个通道是常数"的阈值。遮罩贴图的常数通道实测是**精确**的 1.0 或 0.0，
#: 给一点余量吸收块压缩的误差。
_FLAT_EPSILON = 1.0 / 255.0


def _channel_variation(image) -> tuple[bool, bool]:
    """`(RGB 有变化, Alpha 有变化)`。常数通道不带任何信息，不可能是遮罩。"""
    cached = _CHANNEL_VARIATION.get(image.name)
    if cached is not None:
        return cached
    result = (True, False)
    try:
        pixels = image.pixels[:]
        count = len(pixels) // 4
        if count:
            step = max(1, count // 4096)     # 够看出"是不是常数"，不用全采
            rgb_lo = alpha_lo = 2.0
            rgb_hi = alpha_hi = -1.0
            for i in range(0, count, step):
                o = i * 4
                v = max(pixels[o], pixels[o + 1], pixels[o + 2])
                rgb_lo, rgb_hi = min(rgb_lo, v), max(rgb_hi, v)
                a = pixels[o + 3]
                alpha_lo, alpha_hi = min(alpha_lo, a), max(alpha_hi, a)
            result = (rgb_hi - rgb_lo > _FLAT_EPSILON, alpha_hi - alpha_lo > _FLAT_EPSILON)
    except Exception:   # noqa: BLE001 —— 取不到像素就按"RGB 有效"处理，维持原行为
        pass
    _CHANNEL_VARIATION[image.name] = result
    return result


def _retarget_mask_channel(tex_node, image) -> bool:
    """遮罩在 Alpha 通道里时，把下游从 `Color` 改接到 `Alpha`，返回改没改。

    **为什么需要**：RE Mesh Editor 的遮罩链写死成 `RGBtoBW(贴图.Color)`，而 VFX 的遮罩贴图
    **遮罩存在哪个通道不固定**：实测 `base9.tex` 的 RGB 是**纯白常数**、形状全在 Alpha 里
    （99.3% 的像素 alpha < 0.5）；`01_ring_alpha000.tex` 反过来，Alpha 恒为 1、环形在 RGB。
    读错通道的后果是 `RGBtoBW(纯白) = 1 > 0.5` **恒成立 -> 整片不透明**，在视口里就是一坨
    白色实心块——这正是"网格全是白的"剩下的那一半原因。

    判据是**哪个通道真的有变化**：常数通道不携带任何信息，不可能是遮罩。这不是猜引擎，
    是挑"图在哪儿"。两个通道都有变化时保持原样（RGB），不跟 RE Mesh Editor 抢。
    """
    rgb_varies, alpha_varies = _channel_variation(image)
    if rgb_varies or not alpha_varies:
        return False

    color_out = tex_node.outputs.get("Color")
    alpha_out = tex_node.outputs.get("Alpha")
    if color_out is None or alpha_out is None:
        return False
    tree = tex_node.id_data
    # 下游可能隔着一个 RGBToBW（RE Mesh Editor 的遮罩链就是），Alpha 是标量、直接接过去，
    # 把那个去色节点跳过。
    for link in list(color_out.links):
        target, socket = link.to_node, link.to_socket
        if target.type == "RGBTOBW":
            for onward in list(target.outputs[0].links):
                tree.links.new(alpha_out, onward.to_socket)
            tree.links.remove(link)
        else:
            tree.links.remove(link)
            tree.links.new(alpha_out, socket)
    return True


#: 图像名 -> 亮度最大值（Rec.709，同 Blender 的 RGBToBW）
_MAX_LUMA: dict = {}


def _max_luma(image) -> float:
    cached = _MAX_LUMA.get(image.name)
    if cached is not None:
        return cached
    value = 1.0
    try:
        pixels = image.pixels[:]
        count = len(pixels) // 4
        if count:
            step = max(1, count // 4096)
            value = max(0.2126 * pixels[i * 4] + 0.7152 * pixels[i * 4 + 1]
                        + 0.0722 * pixels[i * 4 + 2]
                        for i in range(0, count, step))
    except Exception:   # noqa: BLE001 —— 取不到像素就按"有亮的地方"处理，维持原行为
        pass
    _MAX_LUMA[image.name] = value
    return value


def _soften_degenerate_alpha_test(tex_node, image) -> bool:
    """遮罩链的 `> 0.5` 阈值在整张贴图上**恒不成立**时，把阈值拆掉走直通 alpha。返回改没改。

    RE Mesh Editor 按 mdf 的 alpha-test 标志接了一条
    `RGBtoBW(遮罩) × … -> GREATER_THAN(0.5) -> BSDF.Alpha` 的**硬裁剪**链。VFX 的遮罩贴图
    常常是一张很淡的渐变（实测 `01_ring_alpha000` 的最大亮度只有 0.216、`04_ring_alpha000`
    只有 0.087），**整张图没有一个像素过得了 0.5** —— 这条链的输出于是恒为 0，那个 attribute
    在视口里一点都画不出来。

    这里的判据不需要解释引擎：**一条在全部输入上恒等于 0 的链不可能是作者的意图**
    （那等于这个 attribute 什么都不画）。所以只在"贴图最大亮度 < 阈值"这种**可证明退化**的
    情况下拆阈值，顺带把材质切成 `BLEND`，让 0.087 这种值老老实实画成 8.7% 的淡光。
    最大亮度过得了阈值的（实测 `03_ring_alpha000` 有 4.6% 的像素过线）**不动**——那时候
    RE Mesh Editor 的裁剪行为是有输出的，我们没有依据说它错。
    """
    if _max_luma(image) >= 0.5:
        return False

    tree = tex_node.id_data
    changed = False
    for node in list(tree.nodes):
        if node.type != "MATH" or node.operation != "GREATER_THAN":
            continue
        targets = [link.to_socket for link in node.outputs[0].links
                   if link.to_socket.name == "Alpha"]
        sources = [link.from_socket for link in node.inputs[0].links]
        if not targets or not sources:
            continue
        for socket in targets:
            tree.links.new(sources[0], socket)
        tree.nodes.remove(node)
        changed = True

    if changed:
        for material in bpy.data.materials:
            if material.node_tree is tree:
                # HASHED 是给硬裁剪用的抖动透明；拆了阈值之后要真正的混合
                material.blend_method = "BLEND"
                break
    return changed


def _apply_colorspace(image, slot_name: str, internal_path: str) -> None:
    """按**槽名**决定换上去这张图的色彩空间，判据照抄 RE Mesh Editor
    （`blender_nodes_re_mdf.addImageNode()`：槽名在 `albedoTypeSet` 里、或者贴图文件名以
    `alb…` 结尾 -> sRGB，其余 Non-Color）。

    ⚠ **别从"被替换掉的那张图"上抄色彩空间**——那是踩过的坑：被替换的是 mdf2 里的占位贴图
    （`NullWhite.tex` 之类），RE Mesh Editor 连文件都没找到、退化成了 Non-Color 的兜底图，
    把它的色彩空间抄过来等于给 BaseMap 打上 Non-Color，少一次 sRGB->线性 解码，中间调整体
    亮 2 倍多，看起来就是"贴图被洗白了"。实测这批贴图本身是 `BC7_UNORM_SRGB`，格式自己就
    写着是 sRGB。

    色彩空间是**图像数据块**的属性不是节点的：同一张 `.tex` 同时被颜色槽和数据槽引用时
    后写的那次赢。真实材质里一张贴图的角色是固定的，这里不为这种假想情况加复杂度。
    """
    albedo_slots = _FALLBACK_ALBEDO_SLOTS
    try:
        albedo_slots = _re_mesh_module("modules.mdf.blender_re_mesh_mdf").albedoTypeSet
    except Exception:   # noqa: BLE001 —— 第三方插件不在/改了结构，退回兜底名单
        pass
    tail = internal_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit("_", 1)[-1].lower()
    want = "sRGB" if (slot_name in albedo_slots or "alb" in tail) else "Non-Color"
    try:
        image.colorspace_settings.name = want
    except Exception:   # noqa: BLE001
        pass


#: VFX 材质里自发光那两个参数的拼法。RE Mesh Editor 的 `newEMINode()` 认的是
#: `Emissive_color` / `Emissive_Color` / `EmissiveColor` / `Emissive_Color1` 和
#: `Emissive_intensity` / `Emissive_Intensity` / `EmissiveIntensity` / `Emissive_Power`——
#: **VFX 材质用的 `…Param` 拼法不在里面**，所以它那条自发光通路对 VFX 材质整条静默不触发
#: （`Emission Strength` 留在 0，模型看起来就是一块白）。这里只补它漏掉的那两个名字。
#:
#: 名单是扫 40 个真实 VFX `.mdf2` 的参数名定的：`EmissiveParam`(12) /
#: `EmissiveColorParam`(1) 是 4 分量颜色，`EmissiveIntensityParam`(12) 是 1 分量强度。
#: **故意不收** `RimEmissive*` / `EmissiveMask*` / `EmissiveIntensityByDistance` /
#: `RayTrace_Emissive_*`——那些是各自独立的特性，不是主自发光，混进来会叠错。
#: `Allover_Emissive_Intensity`(9) 同样不收：名字像是全局倍率而不是主强度，没有依据。
_EMISSIVE_COLOR_PARAMS = ("EmissiveParam", "EmissiveColorParam")
_EMISSIVE_INTENSITY_PARAMS = ("EmissiveIntensityParam",)


def _resolve_emissive(attr_obj, mdf_local: Path):
    """自发光的 `((r, g, b), 强度)`。EFX 覆盖表里有就用覆盖值，没有就退回材质自己的默认值；
    取不到强度、或者强度是 0 就返回 `None`（本来就不该发光）。

    ⚠ 两边的标量藏在不同分量里，别混用：EFX 覆盖表的 `Range` 条目是 `(0, 0, min, max)`
    （见 `mdf_catalog.build_property_dict()`），标量取 `Z`；材质自己那份（`mdfdump` 出来的）
    标量在 `X`。
    """
    try:
        entries = mdf_catalog.candidates(str(mdf_local))
    except mdf_catalog.CatalogError:
        return None
    by_name = {e["name"]: e for e in entries if e["kind"] == "param"}
    by_hash = {e["utf8Hash"]: e["name"] for e in entries if e["kind"] == "param"}

    # 一个名字可能对应**多条**覆盖条目：覆盖表按 `PropertyNameUTF8Hash` 认参数，而
    # `mdfPropertyIndex` 只是快路径，mod 作者改过 mdf2 之后下标会漂（实测 POD042：两条
    # 都哈希成 `EmissiveParam`，下标一条是 3、一条是 4，而 mdf2 里 4 号其实叫
    # `RimEmissive_Color`）。所以这里按名字收成**列表**，选取规则见 `pick()`。
    overrides: dict[str, list] = {}
    node = model.find_field(attr_obj.efx_fields, "properties")
    for child in (node.children if node is not None else ()):
        values = model.node_to_value(child)
        name = by_hash.get(values.get("PropertyNameUTF8Hash"))
        if name is not None and values.get("parameterType") != "Texture":
            overrides.setdefault(name, []).append(values)

    def scalar(value: dict, is_override: bool) -> float:
        return float(value.get("Z" if is_override else "X", 0.0) or 0.0)

    def rgb(value: dict) -> tuple:
        return (float(value.get("X", 0.0)), float(value.get("Y", 0.0)),
                float(value.get("Z", 0.0)))

    def pick(names, want_color):
        """同名多条时，**取第一条"值和材质默认值不一样"的**——那是作者真正改过的那条；
        和默认值相同的条目套上去本来也等于没套，所以这个挑法不存在"选错参数"的失败模式
        （候选全都自称是同一个参数）。全都等于默认值时就用默认值。"""
        for name in names:
            base = by_name.get(name)
            if base is None:
                continue
            default = base.get("value") or {}
            candidates = overrides.get(name) or []
            for entry in candidates:
                value = entry.get("value") or {}
                if want_color:
                    if rgb(value) != rgb(default):
                        return rgb(value)
                elif scalar(value, True) != scalar(default, False):
                    return scalar(value, True)
            if candidates:
                value = candidates[0].get("value") or {}
                return rgb(value) if want_color else scalar(value, True)
            return rgb(default) if want_color else scalar(default, False)
        return None

    intensity = pick(_EMISSIVE_INTENSITY_PARAMS, False)
    if not intensity:
        return None
    return pick(_EMISSIVE_COLOR_PARAMS, True) or (1.0, 1.0, 1.0), intensity


def _apply_emissive_override(new_objects, attr_obj, mdf_local: Path, problems: list) -> int:
    """把 VFX 材质的自发光接起来，返回接了几个材质。

    **接法完全照抄 RE Mesh Editor 自己的 `newEMINode()`**（`blender_nodes_re_mdf.py:1006`），
    不是我们自己编一套 RE Engine 的 VFX 着色模型：

        Emission Color    = EmissiveMap.Color × 自发光颜色参数      (MixRGB MULTIPLY, fac=1)
        Emission Strength = RGBtoBW(EmissiveMap.Color)
                            × (自发光强度参数 × EMISSION_MULTIPLIER) -> Clamp(0, 9999)

    连 `EMISSION_MULTIPLIER`（它源码里是 0.1，注释"默认太亮了"）都是从它模块里读的，
    不抄成字面量——它调了我们跟着调。

    **只在它自己没接的时候接**：`Emission Strength` 已经有连线就说明它认得这个材质，别抢。
    它对 VFX 材质不触发的唯一原因是参数名对不上（见 `_EMISSIVE_COLOR_PARAMS`）。
    """
    resolved = _resolve_emissive(attr_obj, mdf_local)
    if resolved is None:
        return 0
    color, intensity = resolved
    try:
        multiplier = getattr(_re_mesh_module("modules.mdf.blender_nodes_re_mdf"),
                             "EMISSION_MULTIPLIER", 0.1)
    except Exception:   # noqa: BLE001 —— 第三方插件不在/改了结构，用它源码里那个值兜底
        multiplier = 0.1

    done, seen = 0, set()
    for obj in new_objects:
        for slot in getattr(obj, "material_slots", []):
            material = slot.material
            if material is None or material.node_tree is None or material.name in seen:
                continue
            seen.add(material.name)
            try:
                if _wire_emission(material.node_tree, color, intensity, multiplier):
                    done += 1
            except Exception as ex:   # noqa: BLE001
                problems.append((attr_obj.name, material.name,
                                 f"接自发光失败：{_first_line(ex)}"))
    return done


def _wire_emission(tree, color, intensity: float, multiplier: float) -> bool:
    """在一个材质的节点树上接好自发光。已经接过 / 没有 `EmissiveMap` / 没有 BSDF 返回 False。"""
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    emissive = next((n for n in tree.nodes
                     if n.type == "TEX_IMAGE" and n.label == "EmissiveMap" and n.image), None)
    if bsdf is None or emissive is None:
        return False
    strength = bsdf.inputs.get("Emission Strength")
    if strength is None or strength.is_linked:
        return False

    base = emissive.location

    tint = tree.nodes.new("ShaderNodeMixRGB")
    tint.blend_type = "MULTIPLY"
    tint.label = "EFX Emissive Tint"
    tint.location = (base[0] + 300, base[1] + 150)
    tint.inputs["Fac"].default_value = 1.0
    tint.inputs["Color2"].default_value = (color[0], color[1], color[2], 1.0)
    tree.links.new(emissive.outputs["Color"], tint.inputs["Color1"])
    color_input = bsdf.inputs.get("Emission Color")
    if color_input is not None:
        tree.links.new(tint.outputs["Color"], color_input)

    bw = tree.nodes.new("ShaderNodeRGBToBW")
    bw.location = (base[0] + 300, base[1] - 150)
    tree.links.new(emissive.outputs["Color"], bw.inputs[0])

    scale = tree.nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY"
    scale.label = "EFX Emissive Strength"
    scale.location = (base[0] + 600, base[1] - 150)
    tree.links.new(bw.outputs[0], scale.inputs[0])
    scale.inputs[1].default_value = intensity * multiplier

    clamp = tree.nodes.new("ShaderNodeClamp")   # 同它：挡住负强度
    clamp.location = (base[0] + 900, base[1] - 150)
    clamp.inputs["Max"].default_value = 9999.0
    tree.links.new(scale.outputs["Value"], clamp.inputs["Value"])
    tree.links.new(clamp.outputs["Result"], strength)
    return True


def _re_mesh_module(suffix: str):
    """按 RE Mesh Editor 的**包根**拼一个子模块 import 进来。

    包名不能写死：原版装出来叫 `RE-Mesh-Editor`，社区分支和各种"修复版"名字都不一样
    （本机这个就叫 `RE-Mesh-Editor-MeshFixes`）。从它注册的导入算子类反查包根——
    `bpy.types.<CLASS>` 拿到的是 RNA 类型、没有 `__module__`，所以走
    `bpy.types.Operator.__subclasses__()` 找 Python 类本身。
    """
    for cls in bpy.types.Operator.__subclasses__():
        if getattr(cls, "bl_idname", "") in ("re_mesh.importfile", "re_mesh_cm.importfile"):
            root = cls.__module__.split(".")[0]
            return importlib.import_module(f"{root}.{suffix}")
    raise RuntimeError("找不到 RE Mesh Editor 的包根（导入算子类不在 bpy.types.Operator 的子类里）")


def _apply_mdf_to_material(mdf_local: Path, material_path: str,
                           mdf_material_name: str, blender_material) -> None:
    """把 `.mdf2` 里那个材质的着色器图建到指定的 Blender 材质上。

    `importMDF(mdfFile, meshMaterialDict, ...)` 的 `meshMaterialDict` 是
    `{材质名: bpy 材质}`，它拿 key 去 mdf 的材质表里查——所以这里**用 mdf 侧的名字当 key**，
    值给网格那边的材质，名字对不上这件事就绕过去了。

    `chunkPath` 是贴图搜索根，形状必须是 `.../natives/<平台>`（它内部再拼
    `chunkPath/streaming/<贴图路径>`）。RE Mesh Editor 自己是拿 `splitNativesPath(mdfPath)`
    算的，我们按内部路径段数从文件往上数，结果一样、更不容易认错（见
    `asset_paths.natives_root_of()`）。
    """
    mdf_reader = _re_mesh_module("modules.mdf.file_re_mdf")
    mdf_importer = _re_mesh_module("modules.mdf.blender_re_mesh_mdf")
    chunk_root = asset_paths.natives_root_of(mdf_local, material_path)
    mdf_importer.importMDF(
        mdf_reader.readMDF(str(mdf_local)),
        {mdf_material_name: blender_material},
        False,   # loadUnusedTextures
        False,   # loadUnusedProps
        False,   # useBackfaceCulling
        False,   # reloadCachedTextures
        chunkPath=str(chunk_root) if chunk_root is not None else "",
        gameName=None,   # 让它自己按 mdf 的 fileVersion 判断
        arrangeNodes=True,
    )


def _bind_reference_material(attr_obj, mdf_local: Path, problems: list) -> bool:
    """把解析出来的 `.mdf2` 设成这个 attribute 的参考材质（`efx_mdf_reference`），顺带把
    "覆盖表里和材质对不上的条目"算出来存进 `efx_mdf_mismatched` 给面板标红。

    完全复用 `EFX_RE_OT_mdf_reference_load` 那条路的判据（`structure_ops.reference_mismatches`），
    不另写一套——两边结论不一致比没有这个自动绑定更糟。

    没有材质参数覆盖表的 attribute（`EFXAttributeTypeGpuMesh` 就没有 `properties`）返回
    False 且**不记 problem**：那不是失败，是这个类型本来就没有这张表。
    """
    properties_node, _ = structure_ops.resolve_mdf_properties(attr_obj)
    if properties_node is None:
        return False
    try:
        entries = mdf_catalog.candidates(str(mdf_local))
    except mdf_catalog.CatalogError as ex:
        problems.append((attr_obj.name, str(mdf_local), _first_line(ex)))
        return False

    attr_obj.efx_mdf_reference = str(mdf_local)
    issues = structure_ops.reference_mismatches(properties_node, entries)
    attr_obj.efx_mdf_mismatched = ",".join(str(name_hash) for name_hash, _ in issues)
    return True


def _prefetch_material_textures(mdf_local: Path, near=None) -> int:
    """材质是从 pak 现捞出来的时候，把它引用的 `.tex` 也捞到**同一个** natives 镜像下，
    返回捞到几张。

    RE Mesh Editor 找贴图的根目录是拿 `.mdf2` 路径里那段 `.../natives/<平台>` 反推的
    （`splitNativesPath()` -> `chunkPath`，再到 `chunkPath/streaming/<路径>.tex<版本>`），
    所以贴图必须和那份 mdf2 躺在同一个镜像里它才找得到——这正是
    `asset_paths.resolve()` 把 pak 产物按 `natives/STM/` 原样镜像（而不是拍平成一个文件名）
    的原因。

    mdf2 本来就在用户自己的解包目录里时**什么都不做**：那边的贴图要么已经在，要么该由用户
    自己在 RE Mesh Editor 里配的 chunk 路径解决，我们不往别人的解包目录里写东西。

    失败一律吞掉：贴图捞不到的后果是材质少一张图，不该因此中断整个导入（缺了哪张图
    RE Mesh Editor 自己会在控制台说）。
    """
    try:
        if asset_paths.cache_natives_root().resolve() not in mdf_local.resolve().parents:
            return 0
    except OSError:
        return 0
    try:
        payload = bridge.dump_mdf(mdf_local)
    except Exception:   # noqa: BLE001
        return 0

    count = 0
    seen = set()
    # 逐材质取，不走 mdf_catalog.candidates()——那个只接受单材质 mdf2（它要算参数下标，
    # 多材质时下标该按哪张表算是未知的），而这里只是把贴图文件捞到位，多材质完全无害。
    for material in payload.get("materials") or []:
        for texture in material.get("textures") or []:
            path = (texture.get("path") or "").strip()
            if not path or path.lower() in seen:
                continue
            seen.add(path.lower())
            if asset_paths.resolve(path, near=near) is not None:
                count += 1
    return count


# ---------------------------------------------------------------------------
# .uvs + 序列帧大图
# ---------------------------------------------------------------------------

def link_uvs(root_col, with_textures: bool = True, scene=None) -> tuple[int, int, list]:
    """把这棵树里 `UVSPath` 引用的 `.uvs` 建成 UVS Object（挂在这个 EFX_ROOT 集合下面新建的
    一个共享包裹集合里），并按各 attribute 的 `SequenceNo` 把那条序列用的序列帧大图解出来
    绑成预览图。

    返回 `(建了几个 UVS Object, 绑上几张预览图, problems)`。

    同一份 `.uvs` 被多个 attribute 引用时只建一个 Object（语料里很常见）；预览图按**第一个**
    解析到它的 attribute 的 `SequenceNo` 绑——一个 Object 只有一个预览图槽，后面的不覆盖前面的。

    包裹集合按"这个 EFX 最终去重后引用了几个不同的 .uvs"决定名字/是否共享：只有一个就用那个
    文件名（同旧版行为），多个就共享一个通用名的集合，不是各建各的（同
    `uvs_operators.EFX_UVS_OT_import` 的两段式流程，见 uvs_io.new_uvs_collection() 的说明）。
    """
    near = _source_dir(root_col)
    problems: list[tuple[str, str, str]] = []

    refs = list(iter_uvs_refs(root_col))
    unique_paths: list[str] = []
    seen_paths = set()
    for _attr, _owner, uvs_path in refs:
        key = uvs_path.lower()
        if key not in seen_paths:
            seen_paths.add(key)
            unique_paths.append(uvs_path)

    if not unique_paths:
        return 0, 0, problems

    if len(unique_paths) == 1:
        wrapper_name = unique_paths[0].replace("\\", "/").rsplit("/", 1)[-1]
    else:
        wrapper_name = "UVS"
    wrapper = uvs_io.new_uvs_collection(root_col, wrapper_name)

    by_path: dict[str, object] = {}
    n_uvs = n_tex = 0
    for attr_obj, _owner, uvs_path in refs:
        key = uvs_path.lower()
        if key not in by_path:
            by_path[key] = _build_uvs_root(wrapper, attr_obj, uvs_path, problems, near)
            if by_path[key] is not None:
                n_uvs += 1
        uvs_obj = by_path[key]
        if uvs_obj is None or not with_textures:
            continue
        if uvs_obj.efx_uvs_preview_image is None and _bind_uvs_preview(
                uvs_obj, _sequence_no(attr_obj), attr_obj.name, problems, near):
            n_tex += 1

    if scene is not None and by_path:
        last = [obj for obj in by_path.values() if obj is not None]
        if last:
            # 刚拉进来的这份就是用户接下来最可能要看的——直接设成"当前 UVS"，
            # 对齐 EFX_UVS_OT_import 导入后自动指向新根的行为。
            scene.efx_uvs_active_root = last[-1]
    return n_uvs, n_tex, problems


def _build_uvs_root(parent_collection, attr_obj, uvs_path: str, problems: list, near=None):
    local = asset_paths.resolve(uvs_path, near=near)
    if local is None:
        problems.append((attr_obj.name, uvs_path, "找不到这个 .uvs"))
        return None
    try:
        data = bridge.dump_uvs(local)
    except bridge.BridgeError as ex:
        problems.append((attr_obj.name, uvs_path, f"uvsdump 失败：{_first_line(ex)}"))
        return None
    if data.get("fileVersion") != uvs_model.MHWILDS_UVS_FILE_VERSION:
        # 和 EFX_UVS_OT_import 同一条判据：版本号不是 MHWilds 的那个就拒绝，
        # 别的版本字段布局不保证一样。
        problems.append((attr_obj.name, uvs_path,
                         f"文件版本号是 {data.get('fileVersion')}，不是 MHWilds 的 "
                         f"{uvs_model.MHWILDS_UVS_FILE_VERSION}，拒绝导入"))
        return None

    name = Path(local).name
    uvs_obj = uvs_io.build_uvs_root(data, parent_collection, name)
    uvs_obj.efx_uvs_source_filename = name
    return uvs_obj


def _bind_uvs_preview(uvs_obj, seq_index: int, attr_name: str, problems: list,
                      near=None) -> bool:
    """按 `SequenceNo` 指的那条序列取它第一帧用的贴图，解码成预览图绑到 UVS Object 上。"""
    sequences = uvs_obj.efx_uvs_sequences
    if not 0 <= seq_index < len(sequences):
        problems.append((attr_name, uvs_obj.name,
                         f"SequenceNo={seq_index} 超出这个 .uvs 的序列数（{len(sequences)}）"))
        return False
    uvs_obj.efx_uvs_sequences_active_index = seq_index

    patterns = sequences[seq_index].patterns
    if not len(patterns):
        problems.append((attr_name, uvs_obj.name, f"第 {seq_index} 条序列一帧都没有"))
        return False
    tex_index = patterns[0].texture_index
    if not 0 <= tex_index < len(uvs_obj.efx_uvs_textures):
        problems.append((attr_name, uvs_obj.name,
                         f"帧里的 textureIndex={tex_index} 超出贴图表长度"
                         f"（{len(uvs_obj.efx_uvs_textures)}）"))
        return False

    tex_path = (uvs_obj.efx_uvs_textures[tex_index].path or "").strip()
    local = asset_paths.resolve(tex_path, near=near)
    if local is None:
        problems.append((attr_name, tex_path or "(贴图路径为空)", "找不到这个 .tex"))
        return False
    try:
        image = tex_image.load_image(local)
    except Exception as ex:   # noqa: BLE001 —— 解码失败一律拒绝，不交噪声图
        problems.append((attr_name, tex_path, f"贴图解码失败：{_first_line(ex)}"))
        return False
    uvs_obj.efx_uvs_preview_image = image
    return True


# ---------------------------------------------------------------------------
# 统一报告
# ---------------------------------------------------------------------------

#: 状态栏一行放得下的条数；完整名单打控制台。
_REPORT_HEAD = 4


def report_problems(op, problems: list, summary: str) -> None:
    """成功计数一条 INFO、未解决的一条 WARNING——**不静默失败**（铁律 #1）。

    联动失败不该让 EFX 导入本身变成错误（`{"ERROR"}` 会让 `bpy.ops` 调用方直接收到
    RuntimeError），所以一律 WARNING。
    """
    if summary:
        op.report({"INFO"}, summary)
    if not problems:
        return
    head = "；".join((f"{name}（{reason}）" if name else reason)
                     for name, _ref, reason in problems[:_REPORT_HEAD])
    more = "……" if len(problems) > _REPORT_HEAD else ""
    op.report({"WARNING"}, f"{len(problems)} 处引用资源没能载入：{head}{more}")
    print("[MHWs EFX Editor] 资源联动未解决项：")
    for name, ref, reason in problems:
        print(f"  {name}  <- {ref}  —— {reason}")


i18n.add_strings({
    "link.import_meshes":  {"EN": "Import referenced meshes (.mesh + .mdf2)",
                            "ZH": "一并导入引用的网格（.mesh + .mdf2）"},
    "link.import_uvs":     {"EN": "Import referenced .uvs (+ sprite sheets)",
                            "ZH": "一并导入引用的 .uvs（含序列帧大图）"},
    "link.need_mesh_editor": {"EN": "Install RE Mesh Editor to import meshes",
                              "ZH": "装了 RE Mesh Editor 才能导入网格"},
    "link.asset_roots":    {"EN": "Asset lookup roots", "ZH": "资源查找根目录"},
    "link.no_roots":       {"EN": "No unpack directory found — set the game folder below, "
                                  "or an EFX root directory in the Asset Browser panel",
                            "ZH": "没找到解包目录——在下面填游戏安装目录，"
                                  "或在资产库面板里设 EFX 根目录"},
    "link.game_dir":       {"EN": "Game Folder", "ZH": "游戏安装目录"},
})
