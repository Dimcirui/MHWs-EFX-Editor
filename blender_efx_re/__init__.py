"""
blender_efx_re/__init__.py —— MHWs EFX 编辑器 Blender 胶水层子包入口

对齐姊妹项目 EFX-Editor 的 blender_efx/ 子包角色，但没有 efx_format/ 编解码兄弟包——
本项目的编解码完全外包给 tools/EfxBridge（C#，调用 vendor/RE-Engine-Lib），
bridge.py 只做 subprocess + JSON 的薄封装。见仓库根 __init__.py 顶部说明。
"""

from . import bridge
from . import i18n
from . import semantics
from . import model
from . import coords
from . import io_tree
from . import attribute_types
from . import bitfield
from . import transform3d_view
from . import operators
from . import copy_paste
from . import structure_ops
from . import entry_presets
from . import panels
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
    "bridge", "i18n", "semantics", "model", "coords", "io_tree", "transform3d_view",
    "attribute_types", "bitfield", "operators", "copy_paste", "structure_ops", "entry_presets",
    "panels", "asset_index", "asset_browser",
    "uvs_model", "uvs_io", "uvs_operators", "uvs_panels", "uvs_image_editor",
    "wilds_vecfield_io", "wilds_vecfield_ops", "wilds_vecfield_visualizer",
    "file_menu",
]


def register():
    semantics.reload_tables()
    attribute_types.reload_catalogue()
    i18n.register()
    model.register()
    bitfield.register()
    transform3d_view.register()
    operators.register()
    copy_paste.register()
    structure_ops.register()
    entry_presets.register()
    panels.register()
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
    panels.unregister()
    entry_presets.unregister()
    structure_ops.unregister()
    copy_paste.unregister()
    operators.unregister()
    transform3d_view.unregister()
    bitfield.unregister()
    model.unregister()
    i18n.unregister()
