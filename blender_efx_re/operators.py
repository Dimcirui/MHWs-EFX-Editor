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

import os
import re
import tempfile

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import asset_link, asset_paths, bridge, i18n, io_tree, model, preferences, transform3d_view

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


class EFX_RE_OT_new(Operator):
    """新建一个空白 EFX_ROOT，不经过 EfxBridge/文件系统。

    直接在 Python 侧拼一份验证过的最小 EfxFile dict，交给 `io_tree.build_root_from_efxfile()`
    走它原有的导入路径（各字段都是 `.get(key, []) or []`，本来就能吃空数组，不需要为"新建"
    另写一遍建树逻辑）。这份最小 dict 不是猜的——2026-09-10 拿语料里最小的真实空 `.efx`
    （56 字节）跟纯手写 JSON 逐字节比对过，确认 `Header.Version` + `Header.dimensionType`
    这两个字段之外不需要再补别的，见 `model.MHWILDS_EFX_DIMENSION_TYPE` 的说明。"""

    bl_idname = "efx_re.new"
    bl_label = "New EFX"
    bl_description = "新建一个空白 EFX，用 Add Entry / Add Action 继续填内容"
    bl_options = {"REGISTER", "UNDO"}

    root_name: StringProperty(name="Name", default="NewEFX")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "root_name")

    def execute(self, context):
        name = self.root_name.strip() or "NewEFX"
        blank = {
            "Header": {
                "Version": model.MHWILDS_EFX_VERSION,
                "dimensionType": model.MHWILDS_EFX_DIMENSION_TYPE,
            },
            "Entries": [], "Actions": [], "Bones": [], "BoneRelations": [],
            "ExpressionParameters": [], "FieldParameterValues": [],
            "EffectGroups": [], "UvarGroups": [],
        }
        root_col = io_tree.build_root_from_efxfile(blank, context.scene.collection, name)
        # 没有 Export 该沿用哪个原始文件名这回事（从没导入过），留空——
        # ExportHelper.invoke() 自己会兜底成 blend 文件名 + filename_ext。
        context.scene.efx_re_active_root = root_col
        self.report({"INFO"}, f"已新建空白 EFX '{root_col.name}'")
        return {"FINISHED"}


class EFX_RE_OT_import(Operator, ImportHelper):
    """通过 EfxBridge 读取一个或多个 .efx 文件，建成 ~TYPE 对象树"""

    bl_idname = "efx_re.import"
    bl_label = "Import EFX"
    bl_description = "读取一个或多个 .efx 文件，在场景里建成可编辑的对象树"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})

    # `directory` + `files` 有两个用处：文件浏览器里能多选，以及**拖入导入**——
    # Blender 拖文件进来时走 `wm.drop_import_file`，它就是往目标算子塞这两个属性
    # （见 EFX_RE_FH_import）。SKIP_SAVE 保证上一次的选择不会残留到下一次调用。
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})
    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"},
    )

    # 两个默认关的联动开关（对齐姊妹项目 EFX-Editor 导入算子上的 import_meshes /
    # import_uvs）。默认关的理由：两者都要跑外部进程（pak 现捞）或第三方插件，几秒到几十秒
    # 不等，而且大多数编辑场景根本不需要看网格。实现全在 asset_link.py，见那边模块说明。
    import_meshes: BoolProperty(
        name="Import referenced meshes",
        description="顺着 MeshPath 把网格导进来挂到对应的 Entry 下面，材质用 MaterialPath "
                    "指的 .mdf2（贴图跟着材质一起），并把那份 .mdf2 设成参考材质。"
                    "网格解码由 RE Mesh Editor 负责，没装就只做参考材质那一半",
        default=False,
        options={"SKIP_SAVE"},
    )
    import_uvs: BoolProperty(
        name="Import referenced .uvs",
        description="顺着每个 UVSequence 的 UVSPath 把 .uvs 建成可编辑的 UVS 对象，"
                    "并按它的 SequenceNo 把那条序列用的序列帧大图（.tex）解出来绑成预览图",
        default=False,
        options={"SKIP_SAVE"},
    )
    # 只在勾了上面任意一个时才画。资源路径解析优先用解包目录（从资产库面板的 EFX 根目录
    # 往上自动推导），推导不出来才靠这个从 pak 现捞。填了就记到用户配置里，下次不用再填。
    game_dir: StringProperty(
        name="Game Folder",
        description="MonsterHunterWilds 安装目录。解包目录里找不到的资源从这里的 pak 现捞，"
                    "捞过一次就缓存下来",
        subtype="DIR_PATH",
        default="",
        options={"SKIP_SAVE"},
    )

    def draw(self, context):
        layout = self.layout
        paths = self._paths()
        if self.directory:
            # 拖入这条路走的是属性对话框，不是文件浏览器——没有文件列表可看，
            # 所以自己列一下"这次要导入什么"，别让用户点确认时不知道点的是啥。
            if len(paths) == 1:
                layout.label(text=bpy.path.basename(paths[0]), icon="FILE")
            else:
                layout.label(text=f"{len(paths)} × .efx", icon="FILE")
        layout.prop(self, "import_meshes", text=i18n.T("link.import_meshes"))
        if self.import_meshes and not asset_link.mesh_importer_available():
            layout.label(text=i18n.T("link.need_mesh_editor"), icon="INFO")
        layout.prop(self, "import_uvs", text=i18n.T("link.import_uvs"))

        if not (self.import_meshes or self.import_uvs):
            return
        box = layout.box()
        # 用当前选中的路径算：解析优先从**这个 efx 自己的位置**向上找 natives/，
        # 所以浏览器里换个目录看到的根也会跟着变（见 asset_paths.search_roots()）。
        roots = asset_paths.search_roots(near=self.filepath or self.directory)
        if roots:
            box.label(text=f"{i18n.T('link.asset_roots')}: {len(roots)}", icon="FILE_FOLDER")
            box.label(text=str(roots[0]))
        else:
            box.label(text=i18n.T("link.no_roots"), icon="INFO")
        box.prop(self, "game_dir", text=i18n.T("link.game_dir"))

    def invoke(self, context, event):
        """拖入时弹属性对话框确认，**不要**弹文件浏览器、也不要直接闷头导入。

        ⚠ 不能沿用 `ImportHelper.invoke()`：Blender 拖文件进来时用 `INVOKE_DEFAULT` 调这个
        算子，而 `ImportHelper.invoke()` 干的事是 `fileselect_add(self)`——**打开文件浏览器**，
        压根不执行导入。表现出来就是"拖进去没反应，算子还返回 FINISHED"（实测踩过：
        FileHandler 注册正确、poll_drop 通过、扩展名也匹配，就是什么都没发生）。

        改成属性对话框（`invoke_props_dialog`）而不是直接 `execute()`：文件浏览器那条路上
        `import_meshes` / `import_uvs` 这两个联动开关是画在侧栏里的，用户点"导入"之前能看到、
        能勾；拖入这条路要是直接执行，那两个开关就永远只能是默认值，用户根本没有机会选——
        表现成"拖进来的和菜单导进来的行为不一样"，而原因完全不可见。对齐姊妹项目
        EFX-Editor 导入算子的同一处处理。

        判据用 `self.directory`：只有拖入/多选这条路会把它填上，用户从菜单点"导入"时它是空的，
        那时才该弹浏览器。
        """
        # 游戏目录记在用户配置里（不是 .blend 里），每次开面板都填回去，省得反复输。
        self.game_dir = asset_paths.get_game_dir()
        if self.directory:
            # 宽一点：勾上联动开关之后那个框里要显示解析根的完整路径，默认宽度放不下。
            return context.window_manager.invoke_props_dialog(self, width=440)
        return super().invoke(context, event)

    def _paths(self) -> list[str]:
        """这次要导入哪些文件。拖入 / 多选走 `directory` + `files`，单文件走 `filepath`。"""
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
                data = bridge.dump_efx(path)
            except bridge.BridgeError as ex:
                # 逐个文件独立处理：一个坏文件不该让同批拖进来的其它文件都白导
                # （单文件时行为和以前一样——报错 + CANCELLED）。
                failed.append((bpy.path.basename(path),
                               "EfxBridge dump 失败：" + str(ex).strip().split("\n")[0]))
                continue

            name = bpy.path.basename(path)
            # 建树之前先验骨骼绑定索引表对不对得上——对不上就整文件拒绝，别把错位的绑定
            # 塞进场景（见 io_tree.check_bone_relation_alignment() 的说明）。只有在插件首选项
            # 里显式勾了"绕过"时才放行，并把这个事实记到根上、导出时再警告一次。
            alignment_bypassed = False
            try:
                io_tree.check_bone_relation_alignment(data)
            except io_tree.BoneRelationAlignmentError as ex:
                if not preferences.bypass_bone_alignment():
                    failed.append((name, str(ex).strip().split("\n")[0]))
                    continue
                alignment_bypassed = True
                # 放行警告里不重复异常那句"已拒绝导入整个文件"的措辞，直接用逐作用域的
                # 具体问题（和 check_* 共用 bone_relation_alignment_problems()）。
                problems = io_tree.bone_relation_alignment_problems(data)
                self.report(
                    {"WARNING"},
                    f"'{name}' 骨骼绑定索引对不上，已按首选项放行导入，绑定可能已错位："
                    + "；".join(problems),
                )
            root_col = io_tree.build_root_from_efxfile(data, context.scene.collection, name)
            root_col.efx_bone_alignment_bypassed = alignment_bypassed
            # 记住带版本号后缀的原始文件名，给 Export 当默认文件名用（见模块头部说明）。
            root_col.efx_source_filename = name
            # 记住它所在的目录：它引用的 .mesh/.uvs/.tex 绝大多数就在它自己那棵
            # natives/STM 树里，资源解析优先从这里向上回溯（asset_paths.roots_from()）。
            root_col.efx_source_dir = os.path.dirname(os.path.abspath(path))
            transform3d_view.sync_all_transform3d(root_col)
            # 刚导入的这棵树就是用户接下来要动的那棵——直接设成"当前 EFX"，省得还要手动去选
            # （对齐姊妹项目 EFX-Editor 导入后自动指向新根的行为）。见 io_tree.resolve_root()。
            context.scene.efx_re_active_root = root_col
            imported.append((root_col, data))
            drift = io_tree.name_hash_drift(root_col)
            if drift:
                self.report(
                    {"WARNING"},
                    f"'{name}' 里有 {len(drift)} 个 Entry/Action 的 nameHash 和名字对不上（文件被别的"
                    f"工具改过名），导出时会按名字重算，游戏可能找不到它们：{io_tree.describe_name_hash_drift(drift)}",
                )

        # 有文件成功时失败项报 WARNING 而不是 ERROR：`self.report({"ERROR"})` 会让
        # `bpy.ops.efx_re.import(...)` 在 Python 侧直接抛 RuntimeError（Blender 把算子的
        # ERROR 报告转成异常），部分成功却抛异常，脚本调用方没法处理。全军覆没时才是真错误。
        level = {"ERROR"} if not imported else {"WARNING"}
        for basename, first_line in failed:
            # 失败原因由各个 append 点自带（dump 失败 / 骨骼索引表对不上 / ……），
            # 这里只负责拼"拒绝导入了哪个文件"。
            self.report(level, f"拒绝导入 '{basename}'：{first_line}")
        if not imported:
            return {"CANCELLED"}

        if len(imported) == 1:
            root_col, data = imported[0]
            self.report({"INFO"}, f"已导入 '{root_col.name}'：{_summarize(data)}")
        else:
            self.report({"INFO"}, f"已导入 {len(imported)} 个 EFX 文件（{len(failed)} 个失败）")

        # 两个联动开关放在 EFX 本身全部导完之后跑：它们依赖已经建好的属性树（读的是树上的
        # 路径字段，不是 dump 出来的 JSON），而且失败不该回退 EFX 导入本身——报 WARNING，
        # 不改返回值。
        self._link_referenced_assets(context, [root for root, _ in imported])
        return {"FINISHED"}

    def _link_referenced_assets(self, context, root_cols) -> None:
        """两个勾选项的执行入口。实现全在 asset_link.py，这里只管"跑不跑、怎么报"。"""
        if not (self.import_meshes or self.import_uvs):
            return
        # 用户在导入面板上填的游戏目录记进用户配置（下次开还在）。留空表示"不改"——
        # 不能拿空串去覆盖掉之前配好的目录。
        if self.game_dir.strip():
            asset_paths.set_game_dir(self.game_dir)

        problems, parts = [], []
        if self.import_meshes:
            counts = [0, 0, 0, 0, 0]
            mesh_problems = []
            for root_col in root_cols:
                *got, got_problems = asset_link.link_meshes(root_col)
                counts = [a + b for a, b in zip(counts, got)]
                mesh_problems.extend(got_problems)
            problems.extend(mesh_problems)
            n_mesh, n_material, n_override, n_emissive, n_trimmed = counts
            parts.append(f"{n_mesh} 个网格、{n_material} 份参考材质、{n_override} 张覆盖贴图、"
                         f"{n_emissive} 个材质接上自发光、按 PartsStartNo 删掉 {n_trimmed} 段")
        if self.import_uvs:
            n_uvs, n_tex, uvs_problems = 0, 0, []
            for root_col in root_cols:
                a, b, c = asset_link.link_uvs(root_col, scene=context.scene)
                n_uvs += a
                n_tex += b
                uvs_problems.extend(c)
            problems.extend(uvs_problems)
            parts.append(f"{n_uvs} 个 .uvs、{n_tex} 张序列帧大图")

        asset_link.report_problems(self, problems, "已一并载入：" + "，".join(parts))


class EFX_RE_FH_import(bpy.types.FileHandler):
    """把 .efx 文件直接拖进 Blender 就导入（Blender 4.1+ 的 FileHandler API）。

    ⚠ **`bl_file_extensions` 匹配的是最后一段扩展名，所以这里写的是版本号而不是 `.efx`。**
    RE Engine 的文件名形如 `xxx.efx.5571972`，末段是格式版本号；写 `.efx` 一个也匹配不上。
    这不是我们的怪癖——同一台机器上装的其它 RE Engine 插件全是这么干的，比如
    `MESH_FH_drag_import` 列了 20 个 mesh 版本号、`MDF_FH_drag_import` 列了 12 个 mdf 版本号。
    姊妹项目 EFX-Editor 写 `.efx` 是对的，因为 MHWI（MT Framework）的文件名就只有一段扩展名。

    这里只列 MHWs 的 efx 版本 `5571972`（= vendor `EfxVersion.MHWilds`，实测 9221 个官方文件
    无一例外）。将来 Capcom 改版本号，或者要支持别的 RE 游戏，在这儿加一段就行。
    """

    bl_idname = "EFX_RE_FH_import"
    bl_label = "Import MHWs EFX"
    bl_import_operator = "efx_re.import"
    bl_file_extensions = ".5571972"

    @classmethod
    def poll_drop(cls, context):
        """3D 视口和大纲视图里都能拖。

        除了姊妹项目那边的 3D 视口，这里多放开了大纲视图——EFX_ROOT 现在就是一个集合
        （见 io_tree 头部说明），大纲视图正是集合的主场，往那儿拖比往视口里拖更顺手。
        """
        area = getattr(context, "area", None)
        return area is not None and area.type in {"VIEW_3D", "OUTLINER"}


class EFX_RE_OT_export(Operator, ExportHelper):
    """从当前 EFX_ROOT 对象树导出，通过 EfxBridge 写回 .efx。目标树按 io_tree.resolve_root()
    解析：活动对象所在的树优先，没有就用面板上的「当前 EFX」选择器。"""

    bl_idname = "efx_re.export"
    bl_label = "Export EFX"
    bl_description = "从当前 EFX 树导出为 .efx。优先用活动对象所在的树，没有就用面板上的「当前 EFX」"
    bl_options = {"REGISTER"}

    filename_ext = ".efx"
    filter_glob: StringProperty(default="*.efx;*.efx.*", options={"HIDDEN"})
    # 别让 ExportHelper.check() 拿单段 filename_ext 去"规整"路径——它会把版本号后缀吃掉，
    # 见模块头部说明。None 表示"什么都别做"（io_utils.py:`if check_extension is not None`）。
    check_extension = None

    # 默认关闭：2026-09-09 游戏内实测证实 EffectGroups 数组本身的顺序对游戏有意义（武器动作
    # 表大概率按数组下标而不是名字/哈希引用），默认保留导入时的原始顺序。勾上这个才会传空
    # 数组给 C# 后端，让 UpdateEffectGroups() 按 Entry 下标扫描顺序重新生成整个数组——只有
    # 明确需要重排 EffectGroups 时才用得上，见 io_tree.export_root_to_efxfile() 的说明。
    reorder_effect_groups: BoolProperty(
        name="Reorder EffectGroups",
        description="重新排列 EffectGroups 的顺序（按 Entry 下标扫描顺序重新生成）。默认关闭"
                    "以保留导入时的原始顺序——顺序打乱会导致游戏内效果表现异常，只有明确"
                    "需要重排时才勾选",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return io_tree.resolve_root(context) is not None

    def draw(self, context):
        self.layout.prop(self, "reorder_effect_groups")

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

        # 这棵树是当初勾了首选项"绕过骨骼绑定对齐校验"才导进来的：导出不会拦（用户已经确认要
        # 放行），但必须再说一声——它的绑定可能已经错位，写出时还会按当前消费者数量重建
        # BoneRelations、丢掉文件原本声明的槽位。
        if getattr(root_col, "efx_bone_alignment_bypassed", False):
            self.report(
                {"WARNING"},
                f"'{root_col.name}' 导入时骨骼绑定索引对不上（已按首选项放行），"
                f"导出的绑定可能已错位、并丢掉若干绑定槽位",
            )

        try:
            io_tree.check_bone_references(root_col)
            io_tree.check_clip_bits(root_col)
            io_tree.check_clip_interpolations(root_col)
            io_tree.check_expression_bits(root_col)
        except (io_tree.BoneReferenceError, io_tree.ClipBitError, io_tree.ClipInterpolationError,
                io_tree.ExpressionBitError) as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        # 已知写不回去的构造：先说一声再照常往下走（目前 io_tree._unwritable_in_attribute()
        # 里没有已知条目，见那边的注释——这段调用留着是给以后的新条目用的）。
        # 不在这里拦——名单是我们维护的，上游修好之后硬拦截会因为名单过期继续挡着；
        # 真正的关卡是下面那两道（load 失败 / 写出来读不回来），它们看的是当场的实际结果。
        unwritable = io_tree.unwritable_constructs(root_col)
        if unwritable:
            head = "；".join(unwritable[:2]) + ("……" if len(unwritable) > 2 else "")
            self.report({"WARNING"}, f"这棵树有 {len(unwritable)} 处上游写不回去的构造：{head}")

        # 不拦（用户 2026-09-26 选的方案）：名字是用户看得见、改得了的，面板上有一键改回原名。
        drift = io_tree.name_hash_drift(root_col)
        if drift:
            self.report(
                {"WARNING"},
                f"{len(drift)} 个 Entry/Action 的 nameHash 会变（导入时就和名字对不上），游戏按原哈希"
                f"会找不到它们：{io_tree.describe_name_hash_drift(drift)}",
            )

        data = io_tree.export_root_to_efxfile(root_col, reorder_effect_groups=self.reorder_effect_groups)
        try:
            io_tree.check_expression_notation(root_col, data)
        except io_tree.ExpressionNotationError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        out_path, notice, fatal = _ensure_version_suffix(self.filepath, data)
        if fatal:
            # 补不出合法后缀：拒绝导出，别留一个注定读不回来的文件。
            self.report({"ERROR"}, notice)
            return {"CANCELLED"}

        # 写完立刻原样读一遍，读不回来就拒绝导出——不能只看 load 的退出码：语料里约 13.3%
        # 的文件带 Layout attribute（KNOWN_UPSTREAM_ISSUES.md #1），vendor 的 bug 实际触发点
        # 是"重新解析自己刚写出的字节"，不是原始文件的 Read 本身，所以 load 对这些文件退出码
        # 是 0（"成功"），却写出一个字节数不同、读不回来的坏文件，界面上完全看不出来——铁律 #1
        # 明确不允许这种静默丢数据。校验路径必须落在跟 out_path 同名的临时文件上（放在
        # 目标同目录的临时子目录里），不能随便拼后缀：版本号是从**文件名**解析的
        # （FileHandler.FileVersion，见本文件头部说明），拼后缀会把 dump_efx() 的校验本身搞错。
        export_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        if not os.path.isdir(export_dir):
            self.report({"ERROR"}, f"目标目录不存在：{export_dir}")
            return {"CANCELLED"}

        try:
            with tempfile.TemporaryDirectory(prefix="mhws_efx_export_", dir=export_dir) as tmpdir:
                tmp_path = os.path.join(tmpdir, os.path.basename(out_path))
                try:
                    bridge.load_efx(data, tmp_path)
                except bridge.BridgeError as ex:
                    # 命中已知上游缺口时，把人话解释放在最前面——否则用户看到的是一坨
                    # C# 堆栈，看不出"这个文件本来就导不出去，不是我改坏了"。
                    reason = ("\n".join(unwritable) + "\n\n") if unwritable else ""
                    self.report({"ERROR"}, f"{reason}EfxBridge load 失败，拒绝导出：\n{ex}")
                    return {"CANCELLED"}

                try:
                    bridge.dump_efx(tmp_path)
                except bridge.BridgeError as ex:
                    self.report(
                        {"ERROR"},
                        f"写出的文件读不回来，已拒绝导出（vendor 已知缺陷，见 "
                        f"KNOWN_UPSTREAM_ISSUES.md #1）：\n{ex}",
                    )
                    return {"CANCELLED"}

                os.replace(tmp_path, out_path)  # 校验通过才原子替换到真正的目标路径
        except OSError as ex:
            self.report({"ERROR"}, f"导出目录不可写，拒绝导出：{ex}")
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
    bl_description = "把导出前的三项校验主动跑一遍，不导出任何文件"
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


_CLASSES = (EFX_RE_OT_new, EFX_RE_OT_import, EFX_RE_FH_import, EFX_RE_OT_export, EFX_RE_OT_validate)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
