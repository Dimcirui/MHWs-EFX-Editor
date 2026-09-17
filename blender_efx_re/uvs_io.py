"""
blender_efx_re/uvs_io.py —— .uvs <-> ~TYPE(EFX_UVS) 对象树互转

对应 PLAN.md "Phase 2 — UVS 编辑" Step 2。和 io_tree.py 的 EFX 树不同，这里的 JSON 形状
完全固定（见 uvs_model.py 头部说明），import/export 都是直来直去的字段搬运，不需要
EFXValueNode 那套通用递归树，也不需要区分"结构性字段 vs 内容字段"。
"""

from __future__ import annotations

import bpy
from bpy.types import Collection, Object

from . import uvs_model

_UVS_COLOR_TAG = "COLOR_04"  # 橙色：和 EFX_ROOT 的紫色（COLOR_06）区分，Outliner 里一眼分清

#: 纯数据容器，视口里不需要显眼的尺寸——同 io_tree._new_empty() 给 EFX 那些 ~TYPE 对象用的值。
_EMPTY_DISPLAY_SIZE = 0.1


def new_uvs_collection(parent_collection: Collection, name: str) -> Collection:
    """新建一个纯视觉的包裹集合（只挂颜色标签，不带 `~TYPE`——那个标记现在在 Object 上）。

    单个导入：调用方每次都新建一个，一个集合正好装一个 UVS Object（同旧版行为）。
    批量导入（手动多选、或 EFX 侧"一并导入引用的 .uvs"一次带出多个不同的 .uvs）：调用方只
    新建一次，把这批 Object 都 link 进同一个集合——不是各建各的，见 uvs_operators.py /
    asset_link.link_uvs() 里"先数一遍有几个，再决定建几个集合"的两段式流程。
    """
    col = bpy.data.collections.new(name)
    parent_collection.children.link(col)
    col.color_tag = _UVS_COLOR_TAG
    return col


def build_uvs_root(data: dict, parent_collection: Collection, name: str) -> Object:
    """把一个 uvsdump JSON dict 建成一个 `~TYPE = EFX_RE_UVS` 的 Empty Object，link 进
    `parent_collection`（调用方传入的应当已经是 `new_uvs_collection()` 建出来的包裹集合），
    返回该 Object。**不在这里建包裹集合**——单个 vs 共享由调用方决定，见本模块头部说明。
    """
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = _EMPTY_DISPLAY_SIZE
    parent_collection.objects.link(obj)
    obj["~TYPE"] = uvs_model.TYPE_UVS_ROOT

    header = data.get("header") or {}
    obj.efx_uvs_cutout_related = bool(header.get("attributes", 0) or 0)

    for tex_dict in data.get("textures", []) or []:
        item = obj.efx_uvs_textures.add()
        item.path = tex_dict.get("path") or ""
        item.state_holder = str(int(tex_dict.get("stateHolder", 0) or 0))
        item.tex_handle1 = str(int(tex_dict.get("texHandle1", 0) or 0))
        item.tex_handle2 = str(int(tex_dict.get("texHandle2", 0) or 0))
        item.tex_handle3 = str(int(tex_dict.get("texHandle3", 0) or 0))

    for seq_index, seq_dict in enumerate(data.get("sequences", []) or []):
        seq_item = obj.efx_uvs_sequences.add()
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
            # 折成 False——两者的区别完全由 efx_uvs_cutout_related 表达，pattern 自己
            # 只需要知道"裁不裁"，不需要记住原始整数是哪一种"不裁剪"。
            pat_item.use_cutout = int(pat_dict.get("cutoutUVCount", -1) or 0) > 0
            for point_dict in pat_dict.get("cutoutUVs") or []:
                point_item = pat_item.cutout_points.add()
                point_item.x = float(point_dict.get("X", 0.0) or 0.0)
                point_item.y = float(point_dict.get("Y", 0.0) or 0.0)

    return obj


def export_uvs_root(obj: Object) -> dict:
    """build_uvs_root() 的反函数：把一个 UVS Object 导出成 uvsload 需要的 JSON dict。

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
    for item in obj.efx_uvs_textures:
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

    cutout_related = obj.efx_uvs_cutout_related
    sequences = []
    for seq in obj.efx_uvs_sequences:
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


def resolve_uvs_root(context) -> Object | None:
    """当前操作该落在哪个 UVS Object 上：

    1. 活动对象本身就是一个 UVS Object——最直接的一档；
    2. 活动集合下**恰好只有一个** UVS Object 时用它——单个导入的场景（一个包裹集合正好装
       一个 Object）里，点中那个集合就该认出里面唯一的那个。批量导入时一个集合装好几个
       Object，这一档没法猜该是哪个，交给下一档；
    3. 兜底 `Scene.efx_uvs_active_root`（各算子导入/新建后自动指向，见 uvs_operators.py /
       asset_link.link_uvs()）。
    """
    obj = getattr(context, "object", None)
    if obj is not None and obj.get("~TYPE") == uvs_model.TYPE_UVS_ROOT:
        return obj

    active_col = getattr(context, "collection", None)
    if active_col is not None:
        matches = [o for o in active_col.objects if o.get("~TYPE") == uvs_model.TYPE_UVS_ROOT]
        if len(matches) == 1:
            return matches[0]

    active = getattr(context.scene, "efx_uvs_active_root", None)
    if active is not None and active.get("~TYPE") == uvs_model.TYPE_UVS_ROOT:
        return active
    return None


def active_sequence(context):
    """当前活动 UVS 根里，`efx_uvs_sequences_active_index` 指向的 Sequence，取不到返回
    `None`。给 uvs_operators.py 和 uvs_image_editor.py 共用，避免各自维护一份同样的下标判断。
    """
    root_obj = resolve_uvs_root(context)
    if root_obj is None:
        return None
    index = root_obj.efx_uvs_sequences_active_index
    if 0 <= index < len(root_obj.efx_uvs_sequences):
        return root_obj.efx_uvs_sequences[index]
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
