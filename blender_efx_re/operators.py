"""
blender_efx_re/operators.py —— Import/Export：.efx <-> ~TYPE 对象树

替换了此前"存成 JSON 文本块查看"的占位实现（见 io_tree.py 头部注释）。导入失败（EfxBridge dump
抛异常）按 PLAN.md 架构决策第 9 点整文件拒绝，不吞异常塞半成品对象树进场景。

⚠ RE Engine 的格式版本号不在文件内容里，而在**文件名**里（`xxx.efx.5571972`）：
`FileHandler.FileVersion` 是拿 `PathUtils.ParseFileFormat(FilePath).version` 从路径算出来的
（REE-Lib/FileHandler.cs），`EfxHeader.DoRead()` 又直接
`Version = (EfxVersion)handler.FileVersion`。所以导出到一个不带版本号后缀的路径（`out.efx`）时，
写出的**字节完全正确**（写出侧的版本号来自 JSON 里的 Header/Entry 字段，不看输出路径——已实测：
同一份 JSON 写到带后缀和不带后缀的路径，产物逐字节相同），但任何人再读它都只能拿到
EfxVersion = -1，在 `EFXEntry.DoRead()` 里报 `Unknown -1 EFX attribute type ...`；游戏本体同理，
pak 里的路径必须带版本号后缀。

这件事之前一直在坑我们，因为 `ExportHelper` **会主动把版本号后缀吃掉**：它的 `check()`（文件
浏览器里每次路径变化都调）无条件跑
`bpy.path.ensure_ext(os.path.splitext(filepath)[0], filename_ext)`，`os.path.splitext()` 把
`out.efx.5571972` 砍成 `out.efx`，`ensure_ext` 看它已经以 `.efx` 结尾就不再补——净效果是用户不管
填什么，版本号后缀都会被静默删掉，导出的文件谁都读不回来。`filename_ext` 这套单段扩展名的假设
配不上 RE Engine 的"扩展名 + 版本号"多段形状，所以本操作符 `check_extension = None`（"什么都
别做"），改由 `_ensure_version_suffix()` 自己按 Header.Version 补齐/校验。
"""

from __future__ import annotations

import re

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import bridge, i18n, io_tree, transform3d_view

_DIGITS_RE = re.compile(r"[0-9]+")


def _summarize(data: dict) -> str:
    entries = data.get("Entries", []) or []
    actions = data.get("Actions", []) or []
    attr_count = sum(len(e.get("Attributes", []) or []) for e in entries)
    return f"{len(entries)} entries, {len(actions)} actions, {attr_count} entry-level attributes"


def _parsed_file_version(filepath: str) -> int:
    """照抄 vendor `PathUtils.ParseFileFormat()` 的版本号提取，返回 `FileHandler.FileVersion`
    读这个路径时会得到的值（取不到是 -1）。

    规则比"文件名里出现过 `.efx.<数字>`"严格得多：扩展名从 basename 里**第一个**点开始算
    （`PathUtils.GetFilenameExtensionStartIndex()`），版本号必须是紧跟其后的那一段。所以
    `a.b.efx.5571972` 取到的"版本号段"是 `efx`，解析失败，一样是 -1——文件名主干里多一个点
    就够毁掉整个文件，这也是 _ensure_version_suffix() 只补后缀不够、还得回头校验的原因。"""
    basename = filepath.replace("\\", "/").rsplit("/", 1)[-1]
    segments = basename.split(".")
    if len(segments) < 3:
        return -1  # 连"扩展名 + 版本号"两段都凑不出
    version_segment = segments[2]
    return int(version_segment) if _DIGITS_RE.fullmatch(version_segment) else -1


def _ensure_version_suffix(filepath: str, data: dict) -> tuple[str, str | None, bool]:
    """返回 `(实际输出路径, 给用户的提醒或 None, 这个提醒是不是致命的)`。路径已经能解析出正确
    版本号就原样放过；只是缺后缀就补上 `.<Header.Version>`；补了也解析不出来（文件名主干里有
    多余的点）就标成致命，由调用方拒绝导出——写一个注定读不回来的文件比不写更糟。"""
    header_version = (data.get("Header") or {}).get("Version")
    if not isinstance(header_version, int) or header_version <= 0:
        # Header 里拿不到合法版本号（理论上不该发生）：不瞎猜一个写进文件名，原样交给用户。
        return filepath, None, False

    parsed = _parsed_file_version(filepath)
    if parsed == header_version:
        return filepath, None, False
    if parsed != -1:
        return filepath, (
            f"文件名里的版本号（{parsed}）和文件本身的版本号（{header_version}）不一致，"
            "读回来会按文件名那个版本解析布局，八成会读崩——建议改名后重新导出。"
        ), False

    basename = filepath.replace("\\", "/").rsplit("/", 1)[-1]
    # 只补版本号（用户填了 `out.efx`）；文件名压根没有扩展名（填了 `out`）时连 `.efx` 一起补，
    # 因为 check_extension = None 之后 ExportHelper 不再帮忙补扩展名了。
    candidates = [f"{filepath}.{header_version}"]
    if "." not in basename:
        candidates.append(f"{filepath}.efx.{header_version}")
    for candidate in candidates:
        if _parsed_file_version(candidate) == header_version:
            return candidate, (
                "文件名缺版本号后缀（不带后缀的 .efx 谁都读不回来，见 operators.py 模块说明），"
                f"已自动补齐：{candidate}"
            ), False

    return filepath, (
        "这个文件名带不了版本号后缀：RE Engine 的版本号必须紧跟文件名主干后的第一个扩展名"
        f"（`名字.efx.{header_version}`），主干里不能有别的点。请把 '{basename}' "
        "里多余的点去掉再导出。"
    ), True


class EFX_RE_OT_import(Operator, ImportHelper):
    """通过 EfxBridge 读取一个 .efx 文件，建成 ~TYPE 对象树"""

    bl_idname = "efx_re.import"
    bl_label = "Import EFX"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    def execute(self, context):
        try:
            data = bridge.dump_efx(self.filepath)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge dump 失败，拒绝导入：\n{ex}")
            return {"CANCELLED"}

        name = bpy.path.basename(self.filepath)
        root_col = io_tree.build_root_from_efxfile(data, context.scene.collection, name)
        # 记住带版本号后缀的原始文件名，给 Export 当默认文件名用（见模块头部说明）。
        root_col.efx_source_filename = name
        transform3d_view.sync_all_transform3d(root_col)
        # 刚导入的这棵树就是用户接下来要动的那棵——直接设成"当前 EFX"，省得还要手动去选
        # （对齐姊妹项目 EFX-Editor 导入后自动指向新根的行为）。见 io_tree.resolve_root()。
        context.scene.efx_re_active_root = root_col

        self.report({"INFO"}, f"已导入 '{root_col.name}'：{_summarize(data)}")
        return {"FINISHED"}


class EFX_RE_OT_export(Operator, ExportHelper):
    """从当前 EFX_ROOT 对象树导出，通过 EfxBridge 写回 .efx。目标树按 io_tree.resolve_root()
    解析：活动对象所在的树优先，没有就用面板上的「当前 EFX」选择器。"""

    bl_idname = "efx_re.export"
    bl_label = "Export EFX"
    bl_options = {"REGISTER"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})
    # 别让 ExportHelper.check() 拿单段 filename_ext 去"规整"路径——它会把版本号后缀吃掉，
    # 见模块头部说明。None 表示"什么都别做"（io_utils.py:`if check_extension is not None`）。
    check_extension = None

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def invoke(self, context, event):
        # 默认文件名沿用导入时的原始文件名（连版本号后缀一起），让最常见的"导入→改→导出"
        # 流程不需要用户自己记得手打 `.5571972`。ExportHelper.invoke() 只在 filepath 为空时
        # 才按 blend 文件名 + filename_ext 兜底，所以先填上再交给它。
        root_col = io_tree.resolve_root(context)
        if root_col is not None and not self.filepath and root_col.efx_source_filename:
            self.filepath = root_col.efx_source_filename
        return super().invoke(context, event)

    def execute(self, context):
        root_col = io_tree.resolve_root(context)
        if root_col is None:
            self.report({"ERROR"}, "没有可导出的 EFX 树——选中树里的任意对象，或在面板的「当前 EFX」里指定一个")
            return {"CANCELLED"}

        try:
            io_tree.check_bone_references(root_col)
            io_tree.check_clip_bits(root_col)
            io_tree.check_expression_bits(root_col)
        except (io_tree.BoneReferenceError, io_tree.ClipBitError, io_tree.ExpressionBitError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        data = io_tree.export_root_to_efxfile(root_col)
        out_path, notice, fatal = _ensure_version_suffix(self.filepath, data)
        if fatal:
            # 补不出合法后缀：拒绝导出，别留一个注定读不回来的文件。
            self.report({"ERROR"}, notice)
            return {"CANCELLED"}

        try:
            bridge.load_efx(data, out_path)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge load 失败，拒绝导出：\n{ex}")
            return {"CANCELLED"}

        if notice is not None:
            self.report({"WARNING"}, notice)
        self.report({"INFO"}, f"已从 '{root_col.name}' 导出到 {out_path}")
        return {"FINISHED"}


class EFX_RE_OT_validate(Operator):
    """把导出前那三项校验主动跑一遍，不导出任何文件。

    上一版这三项只在导出路径上被动跑，用户要发现"这棵树现在有问题"必须真的走一遍导出弹窗；
    姊妹项目 EFX-Editor 主面板上一直有个 Validate 按钮，这里补齐。判据完全复用
    io_tree.collect_issues()，不另写一套——两边结论不一致的话比没有这个按钮更糟。
    """

    bl_idname = "efx_re.validate"
    bl_label = "Validate"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def execute(self, context):
        root_col = io_tree.resolve_root(context)
        if root_col is None:
            self.report({"ERROR"}, i18n.T("validate.no_root"))
            return {"CANCELLED"}

        issues = io_tree.collect_issues(root_col)
        if not issues:
            self.report({"INFO"}, f"'{root_col.name}'：{i18n.T('validate.ok')}")
            return {"FINISHED"}

        # 全部问题都进 report，让用户在信息栏/Info 编辑器里能一次看完；同时打到控制台，
        # 条数多时状态栏那一行放不下。
        text = "\n".join(f"  {m}" for m in issues)
        print(f"[MHWs EFX Editor] '{root_col.name}' 校验发现 {len(issues)} 个问题：\n{text}")
        self.report({"ERROR"}, f"'{root_col.name}'：发现 {len(issues)} 个问题\n{text}")
        return {"FINISHED"}


_CLASSES = (EFX_RE_OT_import, EFX_RE_OT_export, EFX_RE_OT_validate)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
