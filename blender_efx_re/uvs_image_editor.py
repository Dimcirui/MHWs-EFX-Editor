"""
blender_efx_re/uvs_image_editor.py —— UVS 图形编辑界面（PLAN.md Phase 2 Step 4/"MHW UVS 同款"）

姊妹项目 EFX-Editor 的 UVS 系统有一个弹出 Image Editor 窗口、拿 GPU 画 pattern 矩形叠在参考图
上的编辑器（`blender_efx/uvs_io.py` 的 `EFX_OT_uvs_edit` + `EFX_PT_uvs_editor`）。这里做同样
形态的东西，但不弹独立窗口——直接在用户当前打开的 Image Editor 里画，少一层窗口管理复杂度，
效果一样（用户自己把某个区域切成 Image Editor 就行，跟 UV 编辑工作流一致）。

比姊妹项目多一样东西：cutout 多边形也画出来了（MHWI 的 UVS 格式压根没有这个概念，见
docs/MHWI_LABEL_CANDIDATES.md 之外的那次结构对比调研）。

V 轴方向：Blender 的 Image Editor 是 V=0 在下、V=1 在上（标准 OpenGL/Blender UV 约定），
游戏贴图数据存的方向相反，所以 `_flip()` 固定翻转——2026-09-09 之前这里留过一个
`Scene.efx_uvs_flip_v` 开关防止猜错，后来用真实贴图核对过叠加框确实对得上，已经去掉这个
开关，不再暴露成 UI 选项。

2026-09-09 去掉了"游戏解包根目录 + 按贴图 path 通配符找文件"那一套——每次都要求用户先填对一个
目录、还得赌贴图相对路径能在那目录下解析出来，不如让 `Load Texture Preview` 直接弹文件选择框
省事。同时把"画 pattern 矩形叠加"这件事和"是否通过本插件加载过预览图"彻底解耦：叠加图现在只
认"当前选中的贴图下标"（`efx_uvs_textures_active_index`），不管 Image Editor 里当前那张图是
用 `Load Texture Preview` 转进来的，还是用户自己拿 Image Editor 头部的原生 `Open` 直接打开的
——甚至完全没加载图也照样画（正好对应"直接打开图片加载"这种不经过本插件转换环节的用法）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import bpy
import gpu
from bpy.props import PointerProperty, StringProperty
from bpy.types import Operator, Panel, UIList
from bpy_extras.io_utils import ImportHelper
from gpu_extras.batch import batch_for_shader

from . import bridge, uvs_io, uvs_model
from .i18n import T

_ACTIVE_COLOR = (1.0, 0.95, 0.1, 1.0)
_INACTIVE_COLOR = (0.15, 0.85, 1.0, 0.55)
_CUTOUT_ACTIVE_COLOR = (1.0, 0.35, 1.0, 1.0)
_CUTOUT_INACTIVE_COLOR = (1.0, 0.35, 1.0, 0.45)
_DRAWING_COLOR = (0.2, 1.0, 0.3, 1.0)

# 正在用 EFX_UVS_OT_pattern_cutout_draw 画的、还没提交的点——None 表示当前没在画。模态
# 操作符和 _draw_callback() 都要读写它，放模块级最简单，反正同时只可能有一个画图模态在跑。
_drawing_points: list[tuple[float, float]] | None = None


def _flip(y: float) -> float:
    return 1.0 - y


def _visible_patterns(context):
    """当前活动 UVS 根的活动 Sequence 里的**全部** pattern，按 (下标, item, 是否活动) 产出。
    故意不看"预览图有没有加载"——叠加图只关心当前选中的是哪个 Sequence，不关心 Image Editor
    里实际显示的是什么内容。

    2026-09-10 之前按"贴图下标匹配当前选中贴图"过滤过一轮，结果表现很怪：一个 Sequence 里
    只要有 pattern 引用了别的贴图，它们的边框就彻底不画，只有活动 pattern（专门强制放行过）
    看得见——用户观察到的现象是"只有最后一个 Sequence 边框全显示，前面几个只显示选中的
    pattern"，根因就是这个过滤条件。改成只按 Sequence 分组、不管 `texture_index`，同一个
    Sequence 里的所有 pattern 边框都画出来（活动的亮黄色，其它暗蓝色）。
    """
    root_col = uvs_io.resolve_uvs_root(context)
    if root_col is None:
        return
    seq_idx = root_col.efx_uvs_sequences_active_index
    if not (0 <= seq_idx < len(root_col.efx_uvs_sequences)):
        return
    seq = root_col.efx_uvs_sequences[seq_idx]
    active_idx = seq.patterns_active_index
    for i, pat in enumerate(seq.patterns):
        yield i, pat, (i == active_idx)


def _draw_callback():
    context = bpy.context
    space = context.space_data
    if space is None or space.type != "IMAGE_EDITOR":
        return
    if uvs_io.resolve_uvs_root(context) is None:
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(2.0)

    for _i, pat, is_active in _visible_patterns(context):
        rect = [
            (pat.left, _flip(pat.top)),
            (pat.right, _flip(pat.top)),
            (pat.right, _flip(pat.bottom)),
            (pat.left, _flip(pat.bottom)),
        ]
        batch = batch_for_shader(shader, "LINE_LOOP", {"pos": rect})
        shader.uniform_float("color", _ACTIVE_COLOR if is_active else _INACTIVE_COLOR)
        batch.draw(shader)

        if pat.cutout_points:
            poly = [(p.x, _flip(p.y)) for p in pat.cutout_points]
            batch2 = batch_for_shader(shader, "LINE_LOOP", {"pos": poly})
            shader.uniform_float(
                "color", _CUTOUT_ACTIVE_COLOR if is_active else _CUTOUT_INACTIVE_COLOR
            )
            batch2.draw(shader)

    if _drawing_points:
        # 画到一半、还没收尾的形状——LINE_STRIP（不闭合），跟已经提交的洋红色 LINE_LOOP
        # 区分开，颜色也不一样，一眼能看出这条是正在画的。存的是跟 cutout_points 一致的
        # 数据空间坐标，画之前要跟提交后的叠加图一样过一遍 _flip()。
        strip = [(x, _flip(y)) for x, y in _drawing_points]
        batch3 = batch_for_shader(shader, "LINE_STRIP", {"pos": strip})
        shader.uniform_float("color", _DRAWING_COLOR)
        batch3.draw(shader)

    gpu.state.blend_set("NONE")


_draw_handle = None


class EFX_UVS_OT_load_texture_preview(Operator, ImportHelper):
    """弹出文件选择框加载预览图。`.tex` 走 EfxBridge 转成 `.dds` 再加载（游戏原生格式）；
    其余扩展名（.png/.tga/.dds/...）是 Blender 自己认得的格式，直接 `bpy.data.images.load()`，
    不经过 tex->dds 转换那条链路——2026-09-09 发现这条转换链路对某些贴图会转花（`.tex` 内部
    格式/mipmap 处理跟这条转换路径没有完整对应过），让用户自己拿 DDS/PNG 之类的原图绕开它。
    """

    bl_idname = "efx_uvs.load_texture_preview"
    bl_label = "Load Texture Preview"
    bl_description = "加载一张预览图（.tex 会自动转成 .dds）。转换对某些贴图会失真，可以直接选 PNG/DDS 原图绕开"
    bl_options = {"REGISTER"}

    filename_ext = ".png"
    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(
        default="*.tex;*.png;*.tga;*.dds;*.jpg;*.jpeg;*.bmp;*.exr;*.tif;*.tiff",
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)
        src_path = Path(self.filepath)
        if not src_path.is_file():
            self.report({"ERROR"}, f"文件不存在：{src_path}")
            return {"CANCELLED"}

        if src_path.suffix.lower() == ".tex":
            with tempfile.TemporaryDirectory(prefix="mhws_uvs_preview_") as tmpdir:
                dds_path = Path(tmpdir) / "preview.dds"
                try:
                    bridge.convert_tex_to_dds(src_path, dds_path)
                except bridge.BridgeError as ex:
                    self.report({"ERROR"}, f"贴图转换失败，拒绝加载：\n{ex}")
                    return {"CANCELLED"}
                img = bpy.data.images.load(str(dds_path))
                # 加载用的临时文件这个 with 块结束就没了，必须 pack 进 .blend，不然 Blender
                # 下次想重新读像素数据时找不到源文件，图会变红叉。
                img.pack()
        else:
            # Blender 原生支持的格式，不经过 tex->dds 转换，直接加载并 pack（同上，避免临时
            # 目录之外的路径变了/文件被删了导致后续找不到源文件）。
            img = bpy.data.images.load(str(src_path))
            img.pack()

        img.name = src_path.name
        root_col.efx_uvs_preview_image = img
        context.space_data.image = img
        self.report({"INFO"}, f"已加载预览：{img.name}（{img.size[0]}x{img.size[1]}）")
        return {"FINISHED"}


class EFX_UVS_OT_pick_pattern(Operator):
    """点一下 Image Editor 里的图，按点击位置选中对应的 pattern（同姊妹项目"点选帧"的手感，
    但这里是即点即选，不用先进一个专门的编辑模式）。不要求先加载预览图——叠加矩形只认当前
    选中的贴图下标，坐标系是固定的 0-1 归一化 UV 空间，没图也能点。"""

    bl_idname = "efx_uvs.pick_pattern"
    bl_label = "Pick Pattern (Click)"
    bl_description = "点击图上的位置选中对应的 pattern；不需要先加载预览图"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            x, y = region.view2d.region_to_view(event.mouse_region_x, event.mouse_region_y)
            y_data = _flip(y)

            root_col = uvs_io.resolve_uvs_root(context)
            seq_idx = root_col.efx_uvs_sequences_active_index
            if 0 <= seq_idx < len(root_col.efx_uvs_sequences):
                seq = root_col.efx_uvs_sequences[seq_idx]
                for i, pat, _is_active in _visible_patterns(context):
                    lo_y, hi_y = sorted((pat.top, pat.bottom))
                    lo_x, hi_x = sorted((pat.left, pat.right))
                    if lo_x <= x <= hi_x and lo_y <= y_data <= hi_y:
                        seq.patterns_active_index = i
                        break
            for area in context.screen.areas:
                area.tag_redraw()
            return {"FINISHED"}
        if event.type in {"RIGHTMOUSE", "ESC"}:
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


class EFX_UVS_OT_pattern_cutout_draw(Operator):
    """进入"画裁剪多边形"模态：在图上依次左键点 8 个点，点满 8 个自动收尾写入当前 pattern；
    3~7 个点时按 Enter 提前收尾，收尾时用最后一个点补齐到 8 个（跟导出时
    `uvs_model.pad_cutout_points_to_8()` 是同一套补齐规则）；点数 <=2 时不允许收尾，
    Esc/右键放弃即可，不会写入任何东西。

    每个点落笔时会被夹到当前 pattern 自己的矩形范围内——扫过 3008 个官方非退化 8 点裁剪
    多边形，100% 完全落在自己 pattern 的矩形内部（没有一个点跑到矩形外面），这不是"大部分
    情况"而是硬性约束；不夹住的话，格子挨得近、图标又长得像时很容易点出跨格子的形状（2026-
    09-10 实测过），夹住之后从操作上就不可能画出这种跨格子的错误形状。
    """

    bl_idname = "efx_uvs.pattern_cutout_draw"
    bl_label = "Draw Cutout"
    bl_description = "在图上依次点 8 个点画裁剪多边形；点满自动收尾，3~7 个点可按 Enter 提前收尾，Esc/右键放弃。落点会被限制在当前 pattern 的矩形内"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return uvs_io.active_pattern(context) is not None

    def _stop(self, context, commit):
        global _drawing_points
        if commit:
            pat = uvs_io.active_pattern(context)
            pat.cutout_points.clear()
            for x, y in uvs_model.pad_cutout_points_to_8(_drawing_points):
                point = pat.cutout_points.add()
                point.x, point.y = x, y
        _drawing_points = None
        for area in context.screen.areas:
            area.tag_redraw()

    def modal(self, context, event):
        global _drawing_points
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = context.region
            x, y = region.view2d.region_to_view(event.mouse_region_x, event.mouse_region_y)
            y = _flip(y)

            pat = uvs_io.active_pattern(context)
            lo_x, hi_x = sorted((pat.left, pat.right))
            lo_y, hi_y = sorted((pat.top, pat.bottom))
            x = min(max(x, lo_x), hi_x)
            y = min(max(y, lo_y), hi_y)

            _drawing_points.append((x, y))
            for area in context.screen.areas:
                area.tag_redraw()
            if len(_drawing_points) >= 8:
                self._stop(context, commit=True)
                return {"FINISHED"}
            return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if len(_drawing_points) >= 3:
                self._stop(context, commit=True)
                return {"FINISHED"}
            self.report({"WARNING"}, "至少要 3 个点才能收尾，已放弃")
            self._stop(context, commit=False)
            return {"CANCELLED"}

        if event.type in {"RIGHTMOUSE", "ESC"}:
            self._stop(context, commit=False)
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        global _drawing_points
        _drawing_points = []
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


class EFX_UVS_OT_advanced_edit(Operator):
    """"进阶编辑"一键跳转：把当前区域切成 Image Editor 并打开侧栏，不强制要求预览图已加载
    ——叠加矩形本来就不依赖预览图状态，用户想接着用原生 `Open` 或 `Load Texture Preview`
    随便选一张图都行。"""

    bl_idname = "efx_uvs.advanced_edit"
    bl_label = "Advanced Edit"
    bl_description = "把当前区域切换成 Image Editor 并打开 UVS 侧栏；不需要先加载预览图"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return uvs_io.resolve_uvs_root(context) is not None

    def execute(self, context):
        root_col = uvs_io.resolve_uvs_root(context)

        area = context.area
        # 记住跳转前的区域类型（这个按钮本身只出现在 VIEW_3D 侧栏，实际上恒为
        # "VIEW_3D"，但存实际值而不是硬编码，防止以后这个按钮被挪到别的编辑器里就不对了
        # ——见 EFX_UVS_OT_exit_advanced_edit）。存在 WindowManager 上：这是"这次切换要
        # 切回哪"的会话态，不是要保存进 .blend 的数据。
        context.window_manager.efx_uvs_advanced_edit_prev_type = area.type
        area.type = "IMAGE_EDITOR"
        space = area.spaces.active
        space.show_region_ui = True
        if root_col.efx_uvs_preview_image is not None:
            space.image = root_col.efx_uvs_preview_image

        def _activate_category():
            # 刚切换 area.type 那一帧，Region 的候选分类列表还没跑完一次绘制生成
            # （文档原话："these categories are generated at runtime... before any
            # drawing took place"），这时候写 active_panel_category 会被判定成只读属性，
            # 直接 AttributeError——实机验证过同一帧内设置必现，用 timer 延后一帧再设置
            # 就不会。这里不能用 modal/延时 0 秒之外的别的手段替代：改成先 tag_redraw()
            # 再同步设置试过，redraw 请求本身也是异步排队，不会在当前 Python 调用内生效。
            for region in area.regions:
                if region.type == "UI":
                    region.active_panel_category = EFX_UVS_PT_image_editor.bl_category
                    break
            return None

        bpy.app.timers.register(_activate_category)
        return {"FINISHED"}


class EFX_UVS_OT_exit_advanced_edit(Operator):
    """退出"进阶编辑"：把当前区域切回跳转前的类型。全靠切 area.type 实现的"进阶编辑"没有
    原生退出路径，用户只能手动去点 Editor Type 下拉切回去——加这个按钮省一步，也让"这是个
    临时模式"这件事更直白。"""

    bl_idname = "efx_uvs.exit_advanced_edit"
    bl_label = "Exit Advanced Edit"
    bl_description = "切回进入进阶编辑之前的编辑器类型"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prev_type = context.window_manager.efx_uvs_advanced_edit_prev_type or "VIEW_3D"
        context.area.type = prev_type
        return {"FINISHED"}


class EFX_UVS_PT_image_editor(Panel):
    """Image Editor 侧栏里的 UVS 面板——3D 视口那套字段编辑面板的镜像子集 + 图形编辑专属的
    加载预览/点选按钮，方便直接对着贴图改，不用来回切侧栏。"""

    bl_idname = "EFX_UVS_PT_image_editor"
    bl_label = "MHWilds UVS"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "UVS"

    def draw(self, context):
        layout = self.layout

        layout.operator(
            "efx_uvs.exit_advanced_edit", text=T("uvs.exit_advanced_edit"), icon="LOOP_BACK",
            translate=False,
        )

        root_col = uvs_io.resolve_uvs_root(context)
        if root_col is None:
            layout.label(text="没有当前 UVS", translate=False)
            return

        row = layout.row(align=True)
        row.operator("efx_uvs.load_texture_preview", icon="IMAGE_DATA")
        row.operator("efx_uvs.pick_pattern", icon="RESTRICT_SELECT_OFF")

        layout.prop(root_col, "efx_uvs_cutout_related")

        # 比 3D 视口那套字段编辑面板多的"更多设置"：贴图/Sequence 都能在这里直接切换，不用
        # 跳回 MHWilds UVS 侧栏——图形编辑器里想改哪张图、哪条 Sequence 都是一站式的。基础
        # 侧栏有的增删按钮这里也要有一份，不然贴图/Sequence 列表在这个面板上只能看不能改。
        layout.separator()
        layout.label(text=T("uvs.textures"), translate=False)
        row = layout.row()
        row.template_list(
            "EFX_UVS_UL_textures", "", root_col, "efx_uvs_textures",
            root_col, "efx_uvs_textures_active_index", rows=3,
        )
        col = row.column(align=True)
        col.operator("efx_uvs.texture_add", icon="ADD", text="")
        col.operator("efx_uvs.texture_remove", icon="REMOVE", text="")

        layout.separator()
        layout.label(text=T("uvs.sequences"), translate=False)
        row = layout.row()
        row.template_list(
            "EFX_UVS_UL_sequences", "", root_col, "efx_uvs_sequences",
            root_col, "efx_uvs_sequences_active_index", rows=3,
        )
        col = row.column(align=True)
        col.operator("efx_uvs.sequence_add", icon="ADD", text="")
        col.operator("efx_uvs.sequence_remove", icon="REMOVE", text="")

        seq_idx = root_col.efx_uvs_sequences_active_index
        if not (0 <= seq_idx < len(root_col.efx_uvs_sequences)):
            return
        seq = root_col.efx_uvs_sequences[seq_idx]

        layout.separator()
        layout.label(text=T("uvs.patterns"), translate=False)
        row = layout.row()
        row.template_list(
            "EFX_UVS_UL_patterns", "", seq, "patterns", seq, "patterns_active_index", rows=8,
        )
        col = row.column(align=True)
        col.operator("efx_uvs.pattern_add", icon="ADD", text="")
        col.operator("efx_uvs.pattern_remove", icon="REMOVE", text="")
        layout.operator(
            "efx_uvs.pattern_generate_grid", text=T("uvs.generate_grid"), icon="MESH_GRID",
            translate=False,
        )

        pat_idx = seq.patterns_active_index
        if not (0 <= pat_idx < len(seq.patterns)):
            return
        pat = seq.patterns[pat_idx]
        box = layout.box()
        row = box.row(align=True)
        row.prop(pat, "left")
        row.prop(pat, "top")
        row = box.row(align=True)
        row.prop(pat, "right")
        row.prop(pat, "bottom")
        box.prop(pat, "texture_index")
        tex_list = root_col.efx_uvs_textures
        if 0 <= pat.texture_index < len(tex_list):
            hint = box.row()
            hint.enabled = False
            hint.label(text=tex_list[pat.texture_index].path, translate=False, icon="TEXTURE")
        else:
            hint = box.row()
            hint.alert = True
            hint.label(text=T("uvs.texture_index_out_of_range"), translate=False, icon="ERROR")
        box.prop(pat, "flags", text=T("uvs.flags"))

        # 裁剪多边形编辑放在这里而不是 3D 视口那套侧栏——没有叠加图形实时反馈的话，手改一串
        # x/y 数字完全看不出改出来是什么形状，编辑体验等于没有；这里有 _draw_callback() 画的
        # 洋红色多边形叠加，改一个点马上能在图上看到效果。外层只在 cutout_related（文件级）
        # 开着的时候露出来；pattern 自己的 use_cutout（帧级）决定这一帧导出是 0 还是 8 点，
        # 关掉时下面这些点编辑控件跟着灰掉——不是不能编，是编了也不会被导出用到。
        if root_col.efx_uvs_cutout_related:
            box.prop(pat, "use_cutout")
            sub = box.column()
            sub.enabled = pat.use_cutout
            sub.operator("efx_uvs.pattern_cutout_draw", icon="GREASEPENCIL")
            sub.template_list(
                "EFX_UVS_UL_cutout_points", "", pat, "cutout_points",
                pat, "cutout_points_active_index", rows=4,
            )
            row = sub.row(align=True)
            row.operator("efx_uvs.pattern_cutout_point_add", icon="ADD", text="")
            row.operator("efx_uvs.pattern_cutout_point_remove", icon="REMOVE", text="")
            sub.operator("efx_uvs.pattern_cutout_apply_to_sequence", icon="DUPLICATE")


class EFX_UVS_UL_cutout_points(UIList):
    bl_idname = "EFX_UVS_UL_cutout_points"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=str(index), translate=False)
        row.prop(item, "x", text="X")
        row.prop(item, "y", text="Y")


_CLASSES = (
    EFX_UVS_OT_load_texture_preview, EFX_UVS_OT_pick_pattern, EFX_UVS_OT_pattern_cutout_draw,
    EFX_UVS_OT_advanced_edit, EFX_UVS_OT_exit_advanced_edit, EFX_UVS_UL_cutout_points,
    EFX_UVS_PT_image_editor,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # 记住最近一次加载/使用过的预览贴图，方便"进阶编辑"跳转时顺手把它摆上——不参与叠加矩形
    # 要画哪些 pattern 的判断（那个只认 efx_uvs_textures_active_index，见 _visible_patterns()）。
    bpy.types.Collection.efx_uvs_preview_image = PointerProperty(
        type=bpy.types.Image,
        name="Preview Image",
        description="最近一次加载的预览贴图",
    )

    # "进阶编辑"跳转前的区域类型，供 EFX_UVS_OT_exit_advanced_edit 退出时切回——会话态，
    # 不进 .blend。
    bpy.types.WindowManager.efx_uvs_advanced_edit_prev_type = StringProperty(
        name="Advanced Edit Previous Area Type",
        description="进入进阶编辑前的区域类型，用于退出时还原",
        default="VIEW_3D",
    )

    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_callback, (), "WINDOW", "POST_VIEW",
        )


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceImageEditor.draw_handler_remove(_draw_handle, "WINDOW")
        _draw_handle = None

    del bpy.types.WindowManager.efx_uvs_advanced_edit_prev_type
    del bpy.types.Collection.efx_uvs_preview_image

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
