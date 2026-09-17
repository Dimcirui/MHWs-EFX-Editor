"""
blender_efx_re/__init__.py —— MHWs EFX 编辑器 Blender 胶水层子包入口

对齐姊妹项目 EFX-Editor 的 blender_efx/ 子包角色，但没有 efx_format/ 编解码兄弟包——
本项目的编解码完全外包给 tools/EfxBridge（C#，调用 vendor/RE-Engine-Lib），
bridge.py 只做 subprocess + JSON 的薄封装。见仓库根 __init__.py 顶部说明。
"""

from . import bridge
from . import i18n
from . import preferences
from . import semantics
from . import model
from . import coords
from . import tex_image
from . import io_tree
from . import attribute_types
from . import bitfield
# expr_edit 在 model 之后、panels 之前：它的算子被 panels 的 draw 引用，
# 而它自己只依赖 model 里已注册好的 EFXExpressionNodeItem。
from . import expr_edit
# expr_preview 在 expr_edit 之后：panels 的 Expression 那一段先画结构、再画数值。
from . import expr_preview
from . import transform3d_view
from . import bone_binding
from . import mdf_catalog
# asset_link 是纯胶水（没有要 register 的类），但要在 operators 之前 import——
# 导入算子上那两个联动开关的实现全在它里面。
from . import asset_link
from . import operators
from . import copy_paste
from . import structure_ops
from . import entry_presets
from . import panels
from . import sim_preview
# es3d_overlay 在 sim_preview 之后：它模块级 import sim_preview（复用选择解析、宿主矩阵、
# 坐标换算），反过来 sim_preview 不 import 它。
from . import es3d_overlay
from . import asset_index
from . import asset_browser
from . import uvs_model
from . import uvs_io
from . import uvs_operators
from . import uvs_panels
from . import uvs_image_editor
from . import wilds_vecfield_io
from . import wilds_vecfield_ops
from . import wilds_vecfield_visualizer
from . import file_menu

__all__ = [
    "bridge", "i18n", "preferences", "semantics", "model", "coords", "tex_image", "io_tree",
    "transform3d_view",
    "bone_binding", "attribute_types", "bitfield", "mdf_catalog", "asset_link", "operators",
    "copy_paste", "structure_ops",
    "entry_presets",
    "panels", "sim_preview", "es3d_overlay", "asset_index", "asset_browser",
    "uvs_model", "uvs_io", "uvs_operators", "uvs_panels", "uvs_image_editor",
    "wilds_vecfield_io", "wilds_vecfield_ops", "wilds_vecfield_visualizer",
    "file_menu",
]


def register():
    semantics.reload_tables()
    attribute_types.reload_catalogue()
    i18n.register()
    preferences.register()
    model.register()
    bitfield.register()
    expr_edit.register()
    expr_preview.register()
    transform3d_view.register()
    bone_binding.register()
    operators.register()
    copy_paste.register()
    structure_ops.register()
    entry_presets.register()
    panels.register()
    sim_preview.register()
    es3d_overlay.register()
    asset_browser.register()
    # UVS（Phase 2，PLAN.md）：独立的数据模型 + 侧栏标签页，不依赖上面的 EFX ~TYPE 对象树，
    # 但共用同一个 bridge.py（EfxBridge.dll 同时桥接 .efx 和 .uvs 两种格式）。
    uvs_model.register()
    uvs_operators.register()
    uvs_panels.register()
    uvs_image_editor.register()
    # MHWilds VecField（独立侧栏标签页）：读写游戏原生向量场 .tex，
    # 和上面 EFX/UVS 两套完全独立，不共用 bridge.py（不经过 C# 桥接，
    # 纯 Python 做 GDeflate+BC1）。
    wilds_vecfield_ops.register()
    # File > Import/Export 菜单项，挂在最后：只在 draw 时按 bl_idname 找算子，
    # 这时候上面几个 register() 都跑完了，三个算子肯定都已经注册。
    file_menu.register()


def unregister():
    file_menu.unregister()
    wilds_vecfield_ops.unregister()
    uvs_image_editor.unregister()
    uvs_panels.unregister()
    uvs_operators.unregister()
    uvs_model.unregister()
    asset_browser.unregister()
    es3d_overlay.unregister()
    sim_preview.unregister()
    panels.unregister()
    entry_presets.unregister()
    structure_ops.unregister()
    copy_paste.unregister()
    operators.unregister()
    bone_binding.unregister()
    transform3d_view.unregister()
    expr_preview.unregister()
    expr_edit.unregister()
    bitfield.unregister()
    model.unregister()
    preferences.unregister()
    i18n.unregister()
