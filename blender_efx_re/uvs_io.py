"""
blender_efx_re/uvs_io.py —— .uvs <-> ~TYPE(EFX_UVS) 对象树互转

对应 PLAN.md "Phase 2 — UVS 编辑" Step 2。和 io_tree.py 的 EFX 树不同，这里的 JSON 形状
完全固定（见 uvs_model.py 头部说明），import/export 都是直来直去的字段搬运，不需要
EFXValueNode 那套通用递归树，也不需要区分"结构性字段 vs 内容字段"。
"""

from __future__ import annotations

import bpy
from bpy.types import Collection

from . import io_tree, uvs_model

_UVS_COLOR_TAG = "COLOR_04"  # 橙色：和 EFX_ROOT 的紫色（COLOR_06）区分，Outliner 里一眼分清


def build_uvs_root(data: dict, parent_collection: Collection, name: str) -> Collection:
    """把一个 uvsdump JSON dict 建成一个 `~TYPE = EFX_UVS` 集合，返回该集合。"""
    col = bpy.data.collections.new(name)
    parent_collection.children.link(col)
    col.color_tag = _UVS_COLOR_TAG
    col["~TYPE"] = uvs_model.TYPE_UVS_ROOT

    header = data.get("header") or {}
    col.efx_uvs_cutout_related = bool(header.get("attributes", 0) or 0)

    for tex_dict in data.get("textures", []) or []:
        item = col.efx_uvs_textures.add()
        item.path = tex_dict.get("path") or ""
        item.state_holder = str(int(tex_dict.get("stateHolder", 0) or 0))
        item.tex_handle1 = str(int(tex_dict.get("texHandle1", 0) or 0))
        item.tex_handle2 = str(int(tex_dict.get("texHandle2", 0) or 0))
        item.tex_handle3 = str(int(tex_dict.get("texHandle3", 0) or 0))

    for seq_index, seq_dict in enumerate(data.get("sequences", []) or []):
        seq_item = col.efx_uvs_sequences.add()
        seq_item.name = f"Sequence {seq_index}"
        for pat_dict in seq_dict.get("patterns", []) or []:
            pat_item = seq_item.patterns.add()
            pat_item.left = float(pat_dict.get("left", 0.0) or 0.0)
            pat_item.top = float(pat_dict.get("top", 0.0) or 0.0)
            pat_item.right = float(pat_dict.get("right", 0.0) or 0.0)
            pat_item.bottom = float(pat_dict.get("bottom", 0.0) or 0.0)
            pat_item.texture_index = int(pat_dict.get("textureIndex", 0) or 0)
            pat_item.flags = str(int(pat_dict.get("flags", 0) or 0))
            # -1（cutout_related 关闭）和 0（cutout_related 开启但这一帧不裁剪）在这里统一
            # 折成 False——两者的区别完全由集合级 efx_uvs_cutout_related 表达，pattern 自己
            # 只需要知道"裁不裁"，不需要记住原始整数是哪一种"不裁剪"。
            pat_item.use_cutout = int(pat_dict.get("cutoutUVCount", -1) or 0) > 0
            for point_dict in pat_dict.get("cutoutUVs") or []:
                point_item = pat_item.cutout_points.add()
                point_item.x = float(point_dict.get("X", 0.0) or 0.0)
                point_item.y = float(point_dict.get("Y", 0.0) or 0.0)

    return col


def export_uvs_root(col: Collection) -> dict:
    """build_uvs_root() 的反函数：把一个 EFX_UVS 集合导出成 uvsload 需要的 JSON dict。

    `patternCount`/`patternTableOffset`/`cutoutUVCount`/Header 的各种 count/offset 字段一律
    不写——vendor `UvsFile.DoWrite()` 按列表实际内容重新计算，写了也会被覆盖（见
    uvs_model.py 模块头说明），省得两边各算一份可能对不上。

    `efx_uvs_cutout_related` 关掉时不管 pattern 各自的 `use_cutout`/`cutout_points` 编辑成
    什么样，`cutoutUVs` 一律按空数组导出（vendor 自然写成 `-1`）；开着时才轮到每个 pattern
    自己的 `use_cutout`：`True` 导出成恰好 8 个点——已经画了点的用
    `uvs_model.pad_cutout_points_to_8()` 补/截到 8 个，完全没画的用
    `uvs_model.default_cutout_rect_points()` 顶上；`False` 需要导出字面 `0`（不是 `-1`）——
    vendor 的 `DoWrite()` 对空列表只会写 `-1`，没有路径能产出字面 0（见 uvs_model.py 模块头
    `Header.attributes` 一节），所以这里显式带上 `"cutoutUVCount": 0` 这个额外字段，交给
    `tools/EfxBridge/Program.cs` 的 `uvsload` 在写完之后做二次字节 patch。
    """
    textures = []
    for item in col.efx_uvs_textures:
        textures.append({
            "stateHolder": int(item.state_holder or "0"),
            "texHandle1": int(item.tex_handle1 or "0"),
            "texHandle2": int(item.tex_handle2 or "0"),
            "texHandle3": int(item.tex_handle3 or "0"),
            # 再规整一次分隔符：`EFXUvsTextureItem.path` 的 update 回调已经在编辑/导入时改过了
            # （见 uvs_model._normalize_texture_path），但**打开旧 .blend 不触发 update 回调**
            # ——这个改动之前存下来的场景里可能还留着反斜杠，那种路径写进文件游戏就查不到贴图。
            "path": (item.path or "").replace("\\", "/"),
        })

    cutout_related = col.efx_uvs_cutout_related
    sequences = []
    for seq in col.efx_uvs_sequences:
        patterns = []
        for pat in seq.patterns:
            pattern_dict = {
                "flags": int(pat.flags or "0"),
                "left": pat.left,
                "top": pat.top,
                "right": pat.right,
                "bottom": pat.bottom,
                "textureIndex": pat.texture_index,
            }
            if cutout_related and pat.use_cutout:
                if len(pat.cutout_points) > 0:
                    raw_points = [(point.x, point.y) for point in pat.cutout_points]
                    points = uvs_model.pad_cutout_points_to_8(raw_points)
                else:
                    points = uvs_model.default_cutout_rect_points(
                        pat.left, pat.top, pat.right, pat.bottom,
                    )
                pattern_dict["cutoutUVs"] = [{"X": x, "Y": y} for x, y in points]
            elif cutout_related and not pat.use_cutout:
                # cutout_related 开着但这一帧选择不裁剪——字面 0，vendor 自己写不出这个值，
                # 靠 EfxBridge 认出这个显式字段做二次 patch（见本函数上面的说明）。
                pattern_dict["cutoutUVs"] = []
                pattern_dict["cutoutUVCount"] = 0
            else:
                # cutout_related 关着：整个文件都不裁剪，vendor 自然把空列表写成 -1。
                pattern_dict["cutoutUVs"] = []
            patterns.append(pattern_dict)
        sequences.append({"patterns": patterns})

    return {
        "fileVersion": uvs_model.MHWILDS_UVS_FILE_VERSION,
        "header": {"attributes": int(cutout_related)},
        "textures": textures,
        "sequences": sequences,
    }


def resolve_uvs_root(context) -> Collection | None:
    """当前操作该落在哪个 EFX_UVS 集合上：先看活动集合沿父集合链网上找带 EFX_UVS 标记的那个，
    找不到就退到 `Scene.efx_uvs_active_root`（同 io_tree.resolve_root() 对 EFX_ROOT 的处理，
    见 panels.py register()）。EFX_UVS 下面没有 Object（纯数据表，见 uvs_model.py 模块头
    说明），所以不像 io_tree.resolve_root() 那样需要"活动对象所在的树"这一档。
    """
    active_col = getattr(context, "collection", None)
    if active_col is not None:
        col = _root_of_collection(active_col)
        if col is not None:
            return col

    active = getattr(context.scene, "efx_uvs_active_root", None)
    if active is not None and active.get("~TYPE") == uvs_model.TYPE_UVS_ROOT:
        return active
    return None


def active_sequence(context):
    """当前活动 UVS 根里，`efx_uvs_sequences_active_index` 指向的 Sequence，取不到返回
    `None`。给 uvs_operators.py 和 uvs_image_editor.py 共用，避免各自维护一份同样的下标判断。
    """
    root_col = resolve_uvs_root(context)
    if root_col is None:
        return None
    index = root_col.efx_uvs_sequences_active_index
    if 0 <= index < len(root_col.efx_uvs_sequences):
        return root_col.efx_uvs_sequences[index]
    return None


def active_pattern(context):
    """`active_sequence()` 里 `patterns_active_index` 指向的 Pattern，取不到返回 `None`。"""
    seq = active_sequence(context)
    if seq is None:
        return None
    index = seq.patterns_active_index
    if 0 <= index < len(seq.patterns):
        return seq.patterns[index]
    return None


def _root_of_collection(col: Collection | None) -> Collection | None:
    """从一个集合沿父集合链往上找第一个 EFX_UVS（含它自己）。复用
    io_tree.collection_parent()，不重新实现一遍父集合反查。"""
    seen = set()
    while col is not None and col.name not in seen:
        seen.add(col.name)
        if col.get("~TYPE") == uvs_model.TYPE_UVS_ROOT:
            return col
        col = io_tree.collection_parent(col)
    return None
