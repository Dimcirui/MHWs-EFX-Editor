"""
blender_efx_re/__init__.py —— MHWs EFX 编辑器 Blender 胶水层子包入口

对齐姊妹项目 EFX-Editor 的 blender_efx/ 子包角色，但没有 efx_format/ 编解码兄弟包——
本项目的编解码完全外包给 tools/EfxBridge（C#，调用 vendor/RE-Engine-Lib），
bridge.py 只做 subprocess + JSON 的薄封装。见仓库根 __init__.py 顶部说明。
"""

from . import bridge
from . import semantics
from . import model
from . import coords
from . import io_tree
from . import transform3d_view
from . import operators
from . import copy_paste
from . import panels

__all__ = [
    "bridge", "semantics", "model", "coords", "io_tree", "transform3d_view",
    "operators", "copy_paste", "panels",
]


def register():
    semantics.reload_tables()
    model.register()
    transform3d_view.register()
    operators.register()
    copy_paste.register()
    panels.register()


def unregister():
    panels.unregister()
    copy_paste.unregister()
    operators.unregister()
    transform3d_view.unregister()
    model.unregister()
