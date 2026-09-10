"""
blender_efx_re/uvs_operators.py —— Import/Export：.uvs <-> ~TYPE(EFX_UVS) 集合

结构对齐 operators.py（EFX 的 import/export），但目标格式更小、字段完全已知，不需要
collect_issues()/校验三连那一套。版本号后缀处理是同一个坑但成因不同——见
`_ensure_uvs_version_suffix()` 和 bridge.dump_uvs()/load_uvs() 的说明。
"""

from __future__ import annotations

import os
import re

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import bridge, uvs_io, uvs_model

_DIGITS_RE = re.compile(r"[0-9]+")


def _summarize(data: dict) -> str:
    textures = data.get("textures", []) or []
    sequences = data.get("sequences", []) or []
    pattern_count = sum(len(s.get("patterns", []) or []) for s in sequences)
    return f"{len(textures)} textures, {len(sequences)} sequences, {pattern_count} patterns"


def _parsed_file_version(filepath: str) -> int:
    """同 operators._parsed_file_version()：照抄 vendor `PathUtils.ParseFileFormat()` 的版本号
    提取规则，返回 `FileHandler.FileVersion` 读这个路径时会得到的值（取不到是 -1）。"""
    basename = filepath.replace("\\", "/").rsplit("/", 1)[-1]
    segments = basename.split(".")
    if len(segments) < 3:
        return -1
    version_segment = segments[2]
    return int(version_segment) if _DIGITS_RE.fullmatch(version_segment) else -1


def _ensure_uvs_version_suffix(filepath: str, data: dict) -> tuple[str, str | None, bool]:
    """UVS 版本的 operators._ensure_version_suffix()。和 EFX 版本逻辑完全一样，只是版本号
    来源不同：EFX 从 `data["Header"]["Version"]` 取，UVS 从 `data["fileVersion"]` 取（见
    bridge.dump_uvs() 说明——UVS Header 本身不存 Version 字段）。"""
    file_version = data.get("fileVersion")
    if not isinstance(file_version, int) or file_version <= 0:
        return filepath, None, False

    parsed = _parsed_file_version(filepath)
    if parsed == file_version:
        return filepath, None, False
    if parsed != -1:
        return filepath, (
            f"文件名里的版本号（{parsed}）和文件本身的版本号（{file_version}）不一致，"
            "读回来会按文件名那个版本解析布局，八成会读崩——建议改名后重新导出。"
        ), False

    basename = filepath.replace("\\", "/").rsplit("/", 1)[-1]
    candidates = [f"{filepath}.{file_version}"]
    if "." not in basename:
        candidates.append(f"{filepath}.uvs.{file_version}")
    for candidate in candidates:
        if _parsed_file_version(candidate) == file_version:
            return candidate, (
                "文件名缺版本号后缀（不带后缀的 .uvs 谁都读不回来），已自动补齐："
                f"{candidate}"
            ), False

    return filepath, (
        "这个文件名带不了版本号后缀：RE Engine 的版本号必须紧跟文件名主干后的第一个扩展名"
        f"（`名字.uvs.{file_version}`），主干里不能有别的点。请把 '{basename}' "
        "里多余的点去掉再导出。"
    ), True


class EFX_UVS_OT_import(Operator, ImportHelper):
    """通过 EfxBridge 读取一个或多个 .uvs 文件，建成 EFX_UVS 集合。"""

    bl_idname = "efx_uvs.import"
    bl_label = "Import UVS"
    bl_description = "读取一个或多个 .uvs 文件，在场景里建成 EFX_UVS 集合"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".uvs"
    filter_glob: StringProperty(default="*.uvs;*.uvs.*", options={"HIDDEN"})

    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"},
    )

    def invoke(self, context, event):
        # 拖入时直接执行，不弹文件浏览器——同 EFX_RE_OT_import.invoke() 的理由。
        if self.directory:
            return self.execute(context)
        return super().invoke(context, event)

    def _paths(self) -> list[str]:
        if self.files and self.directory:
            names = [f.name for f in self.files if f.name]
            if names:
                return [os.path.join(self.directory, n) for n in names]
        return [self.filepath] if self.filepath else []

    def execute(self, context):
        paths = self._paths()
        if not paths:
            self.report({"ERROR"}, "没有选中任何文件")
            return {"CANCELLED"}

        imported, failed = [], []
        for path in paths:
            try:
                data = bridge.dump_uvs(path)
            except bridge.BridgeError as ex:
                failed.append((bpy.path.basename(path), str(ex).strip().split("\n")[0]))
                continue

            # 这个插件只支持 MHWilds，语料里也只见过版本号 8——别的版本号大概率是别的游戏，
            # 字段布局不保证一样，硬导进来风险比价值大，直接拒绝。
            if data.get("fileVersion") != uvs_model.MHWILDS_UVS_FILE_VERSION:
                failed.append((
                    bpy.path.basename(path),
                    f"文件版本号是 {data.get('fileVersion')}，这个插件只支持 MHWilds 的版本号 "
                    f"{uvs_model.MHWILDS_UVS_FILE_VERSION}，拒绝导入",
                ))
                continue

            name = bpy.path.basename(path)
            root_col = uvs_io.build_uvs_root(data, context.scene.collection, name)
            root_col.efx_uvs_source_filename = name
            context.scene.efx_uvs_active_root = root_col
            imported.append((root_col, data))

        level = {"ERROR"} if not imported else {"WARNING"}
        for basename, first_line in failed:
            self.report(level, f"EfxBridge uvsdump 失败，拒绝导入 '{basename}'：{first_line}")
        if not imported:
            return {"CANCELLED"}

        if len(imported) == 1:
            root_col, data = imported[0]
            self.report({"INFO"}, f"已导入 '{root_col.name}'：{_summarize(data)}")
        else:
            self.report({"INFO"}, f"已导入 {len(imported)} 个 UVS 文件（{len(failed)} 个失败）")
        return {"FINISHED"}


class EFX_UVS_FH_import(bpy.types.FileHandler):
    """把 .uvs 文件直接拖进 Blender 就导入。

    只列出目前唯一实测确认过的版本号 `8`（见 PLAN.md "已确认的事实"）——语料还没批量解包
    过（Step 0 未完成），不排除存在别的版本号。以后确认更多版本号时在这里加。
    """

    bl_idname = "EFX_UVS_FH_import"
    bl_label = "Import MHWs UVS"
    bl_import_operator = "efx_uvs.import"
    bl_file_extensions = ".8"

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        return area is not None and area.type in {"VIEW_3D", "OUTLINER"}


class EFX_UVS_OT_export(Operator, ExportHelper):
    """从当前 EFX_UVS 集合导出，通过 EfxBridge 写回 .uvs。"""

    bl_idname = "efx_uvs.export"
    bl_label = "Export UVS"
    bl_description = "把当前 EFX_UVS 集合写回 .uvs 文件"
    bl_options = {"REGISTER"}

    filename_ext = ".uvs"
    filter_glob: StringProperty(default="*.uvs;*.uvs.*", options={"HIDDEN"})
    check_extension = None  # 同 EFX_RE_OT_export：别让 ExportHelper 吃掉版本号后缀。

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def invoke(self, context, event):
        root_col = uvs_io.resolve_uvs_root(context)
        if root_col is not None and not self.filepath and root_col.efx_uvs_source_filename:
            self.filepath = root_col.efx_uvs_source_filename
        return super().invoke(context, event)

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        if root_col is None:
            self.report({"ERROR"}, "没有可导出的 UVS——选中它所在的集合，或在面板的「当前 UVS」里指定一个")
            return {"CANCELLED"}

        data = uvs_io.export_uvs_root(root_col)
        out_path, notice, fatal = _ensure_uvs_version_suffix(self.filepath, data)
        if fatal:
            self.report({"ERROR"}, notice)
            return {"CANCELLED"}

        try:
            bridge.load_uvs(data, out_path)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge uvsload 失败，拒绝导出：\n{ex}")
            return {"CANCELLED"}

        if notice is not None:
            self.report({"WARNING"}, notice)
        self.report({"INFO"}, f"已从 '{root_col.name}' 导出到 {out_path}")
        return {"FINISHED"}


class EFX_UVS_OT_texture_add(Operator):
    bl_idname = "efx_uvs.texture_add"
    bl_label = "Add Texture"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        item = root_col.efx_uvs_textures.add()
        item.path = ""
        index = len(root_col.efx_uvs_textures) - 1
        # 新建贴图默认按"最常见的样子"填：state_holder 等于它自己的下标（91% 的官方样本是这样，
        # 见 PLAN.md），tex_handle1/2/3 已经在 PropertyGroup 层面默认成 "-1" 了（485/486 的
        # 官方样本是这个值），这里不用重复设置。
        item.state_holder = str(index)
        root_col.efx_uvs_textures_active_index = index
        return {"FINISHED"}


class EFX_UVS_OT_texture_remove(Operator):
    bl_idname = "efx_uvs.texture_remove"
    bl_label = "Remove Texture"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root_col = uvs_io.resolve_uvs_root(context)
        return root_col is not None and len(root_col.efx_uvs_textures) > 0

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        index = root_col.efx_uvs_textures_active_index
        root_col.efx_uvs_textures.remove(index)
        root_col.efx_uvs_textures_active_index = min(index, len(root_col.efx_uvs_textures) - 1)
        return {"FINISHED"}


class EFX_UVS_OT_sequence_add(Operator):
    bl_idname = "efx_uvs.sequence_add"
    bl_label = "Add Sequence"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        item = root_col.efx_uvs_sequences.add()
        item.name = f"Sequence {len(root_col.efx_uvs_sequences) - 1}"
        root_col.efx_uvs_sequences_active_index = len(root_col.efx_uvs_sequences) - 1
        return {"FINISHED"}


class EFX_UVS_OT_sequence_remove(Operator):
    bl_idname = "efx_uvs.sequence_remove"
    bl_label = "Remove Sequence"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root_col = uvs_io.resolve_uvs_root(context)
        return root_col is not None and len(root_col.efx_uvs_sequences) > 0

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        index = root_col.efx_uvs_sequences_active_index
        root_col.efx_uvs_sequences.remove(index)
        root_col.efx_uvs_sequences_active_index = min(index, len(root_col.efx_uvs_sequences) - 1)
        return {"FINISHED"}


class EFX_UVS_OT_pattern_add(Operator):
    bl_idname = "efx_uvs.pattern_add"
    bl_label = "Add Pattern"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return uvs_io.active_sequence(context) is not None

    def execute(self, context):
        seq = uvs_io.active_sequence(context)
        item = seq.patterns.add()
        item.left, item.top, item.right, item.bottom = 0.0, 0.0, 1.0, 1.0
        seq.patterns_active_index = len(seq.patterns) - 1
        return {"FINISHED"}


class EFX_UVS_OT_pattern_remove(Operator):
    bl_idname = "efx_uvs.pattern_remove"
    bl_label = "Remove Pattern"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        seq = uvs_io.active_sequence(context)
        return seq is not None and len(seq.patterns) > 0

    def execute(self, context):
        seq = uvs_io.active_sequence(context)
        index = seq.patterns_active_index
        seq.patterns.remove(index)
        seq.patterns_active_index = min(index, len(seq.patterns) - 1)
        return {"FINISHED"}


class EFX_UVS_OT_pattern_generate_grid(Operator):
    """按行列数把当前序列的 pattern 铺满一个规整网格，覆盖式重建（PLAN.md Step 3
    "网格生成器"——实测样本的 pattern 都是规整 16x4 网格，如 `0.0625 = 1/16`）。

    清空当前序列已有的全部 pattern，按 `rows` x `cols` 重新生成——不是"追加"，是"替换"，
    避免网格大小改了之后新旧 pattern 混在一起分不清。`texture_index` 统一用当前活动
    pattern（重建前）的值，没有就用 0；`flags`/`cutout_points` 一律清空成默认值——网格
    生成器生成的是全新数据，不存在"沿用旧值"的语义。
    """

    bl_idname = "efx_uvs.pattern_generate_grid"
    bl_label = "Generate Grid"
    bl_description = "按行列数把当前序列铺满规整网格。会清空该序列已有的全部 pattern，是替换不是追加"
    bl_options = {"REGISTER", "UNDO"}

    rows: IntProperty(name="Rows", min=1, default=4)
    cols: IntProperty(name="Columns", min=1, default=16)
    texture_index: IntProperty(name="Texture Index", min=0, default=0)

    @classmethod
    def poll(cls, context):
        return uvs_io.active_sequence(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        seq = uvs_io.active_sequence(context)
        seq.patterns.clear()
        cell_w = 1.0 / self.cols
        cell_h = 1.0 / self.rows
        for row in range(self.rows):
            for col in range(self.cols):
                item = seq.patterns.add()
                item.left = col * cell_w
                item.top = row * cell_h
                item.right = (col + 1) * cell_w
                item.bottom = (row + 1) * cell_h
                item.texture_index = self.texture_index
        seq.patterns_active_index = 0
        return {"FINISHED"}


class EFX_UVS_OT_pattern_cutout_point_add(Operator):
    bl_idname = "efx_uvs.pattern_cutout_point_add"
    bl_label = "Add Cutout Point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return uvs_io.active_pattern(context) is not None

    def execute(self, context):
        pat = uvs_io.active_pattern(context)
        point = pat.cutout_points.add()
        point.x, point.y = pat.left, pat.top
        pat.cutout_points_active_index = len(pat.cutout_points) - 1
        return {"FINISHED"}


class EFX_UVS_OT_pattern_cutout_point_remove(Operator):
    bl_idname = "efx_uvs.pattern_cutout_point_remove"
    bl_label = "Remove Cutout Point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        pat = uvs_io.active_pattern(context)
        return pat is not None and len(pat.cutout_points) > 0

    def execute(self, context):
        pat = uvs_io.active_pattern(context)
        index = pat.cutout_points_active_index
        pat.cutout_points.remove(index)
        pat.cutout_points_active_index = min(index, len(pat.cutout_points) - 1)
        return {"FINISHED"}


class EFX_UVS_OT_pattern_cutout_apply_to_sequence(Operator):
    """把当前 pattern 的裁剪形状套到同一个 sequence 里的其它所有 pattern——按各自矩形的
    比例映射（源点相对源矩形的比例不变，换算到目标矩形上），不是原样搬运绝对坐标，因为
    同一序列里不同 pattern 的矩形大小/位置通常不一样（比如网格生成器铺出来的每格）。"""

    bl_idname = "efx_uvs.pattern_cutout_apply_to_sequence"
    bl_label = "Apply Cutout to All Patterns in Sequence"
    bl_description = "把当前 pattern 的裁剪形状按比例套到同一序列的其它 pattern 上"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        pat = uvs_io.active_pattern(context)
        return pat is not None and len(pat.cutout_points) > 0

    def execute(self, context):
        seq = uvs_io.active_sequence(context)
        src = uvs_io.active_pattern(context)
        src_w = src.right - src.left
        src_h = src.bottom - src.top
        fractions = [
            ((p.x - src.left) / src_w if src_w else 0.0, (p.y - src.top) / src_h if src_h else 0.0)
            for p in src.cutout_points
        ]

        for pat in seq.patterns:
            if pat == src:
                continue
            pat.cutout_points.clear()
            for fx, fy in fractions:
                point = pat.cutout_points.add()
                point.x = pat.left + fx * (pat.right - pat.left)
                point.y = pat.top + fy * (pat.bottom - pat.top)

        return {"FINISHED"}


_CLASSES = (
    EFX_UVS_OT_import, EFX_UVS_FH_import, EFX_UVS_OT_export,
    EFX_UVS_OT_texture_add, EFX_UVS_OT_texture_remove,
    EFX_UVS_OT_sequence_add, EFX_UVS_OT_sequence_remove,
    EFX_UVS_OT_pattern_add, EFX_UVS_OT_pattern_remove, EFX_UVS_OT_pattern_generate_grid,
    EFX_UVS_OT_pattern_cutout_point_add, EFX_UVS_OT_pattern_cutout_point_remove,
    EFX_UVS_OT_pattern_cutout_apply_to_sequence,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
