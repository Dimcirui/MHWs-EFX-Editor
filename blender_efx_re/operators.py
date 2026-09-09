"""
blender_efx_re/operators.py —— Import/Export：.efx <-> ~TYPE 对象树

替换了此前"存成 JSON 文本块查看"的占位实现（见 io_tree.py 头部注释）。导入失败（EfxBridge dump
抛异常）按 PLAN.md 架构决策第 9 点整文件拒绝，不吞异常塞半成品对象树进场景。
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import bridge, i18n, io_tree, transform3d_view


def _summarize(data: dict) -> str:
    entries = data.get("Entries", []) or []
    actions = data.get("Actions", []) or []
    attr_count = sum(len(e.get("Attributes", []) or []) for e in entries)
    return f"{len(entries)} entries, {len(actions)} actions, {attr_count} entry-level attributes"


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
        root_obj = io_tree.build_root_from_efxfile(data, context.scene.collection, name)
        transform3d_view.sync_all_transform3d(root_obj)
        # 刚导入的这棵树就是用户接下来要动的那棵——直接设成"当前 EFX"，省得还要手动去选
        # （对齐姊妹项目 EFX-Editor 导入后自动指向新根的行为）。见 io_tree.resolve_root()。
        context.scene.efx_re_active_root = root_obj

        self.report({"INFO"}, f"已导入 '{root_obj.name}'：{_summarize(data)}")
        return {"FINISHED"}


class EFX_RE_OT_export(Operator, ExportHelper):
    """从当前 EFX_ROOT 对象树导出，通过 EfxBridge 写回 .efx。目标树按 io_tree.resolve_root()
    解析：活动对象所在的树优先，没有就用面板上的「当前 EFX」选择器。"""

    bl_idname = "efx_re.export"
    bl_label = "Export EFX"
    bl_options = {"REGISTER"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def execute(self, context):
        root_obj = io_tree.resolve_root(context)
        if root_obj is None:
            self.report({"ERROR"}, "没有可导出的 EFX 树——选中树里的任意对象，或在面板的「当前 EFX」里指定一个")
            return {"CANCELLED"}

        try:
            io_tree.check_bone_references(root_obj)
            io_tree.check_clip_bits(root_obj)
            io_tree.check_expression_bits(root_obj)
        except (io_tree.BoneReferenceError, io_tree.ClipBitError, io_tree.ExpressionBitError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        data = io_tree.export_root_to_efxfile(root_obj)

        try:
            bridge.load_efx(data, self.filepath)
        except bridge.BridgeError as ex:
            self.report({"ERROR"}, f"EfxBridge load 失败，拒绝导出：\n{ex}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"已从 '{root_obj.name}' 导出到 {self.filepath}")
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
        root_obj = io_tree.resolve_root(context)
        if root_obj is None:
            self.report({"ERROR"}, i18n.T("validate.no_root"))
            return {"CANCELLED"}

        issues = io_tree.collect_issues(root_obj)
        if not issues:
            self.report({"INFO"}, f"'{root_obj.name}'：{i18n.T('validate.ok')}")
            return {"FINISHED"}

        # 全部问题都进 report，让用户在信息栏/Info 编辑器里能一次看完；同时打到控制台，
        # 条数多时状态栏那一行放不下。
        text = "\n".join(f"  {m}" for m in issues)
        print(f"[MHWs EFX Editor] '{root_obj.name}' 校验发现 {len(issues)} 个问题：\n{text}")
        self.report({"ERROR"}, f"'{root_obj.name}'：发现 {len(issues)} 个问题\n{text}")
        return {"FINISHED"}


_CLASSES = (EFX_RE_OT_import, EFX_RE_OT_export, EFX_RE_OT_validate)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
