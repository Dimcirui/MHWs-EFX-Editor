"""blender_efx_re/file_menu.py —— 外部文件的统一入口层：File > Import / Export

本模块不定义任何新的算子逻辑，只把已有的导入/导出算子挂到 Blender 的标准入口上，
对齐姊妹项目 efx_editor 的 blender_efx/file_menu.py 那套做法：

  File > Import >  MHWs Effect (.efx)         → efx_re.import
                   MHWs UV Sequence (.uvs)    → efx_uvs.import
                   MHWs Vector Field (.tex)   → wilds_vecfield.load_tex
  File > Export >  同三条 → efx_re.export / efx_uvs.export / wilds_vecfield.save_tex

拖入 3D 视口的 FileHandler（.efx/.uvs）已经在 operators.py / uvs_operators.py
自己的 _CLASSES 里注册过了，这里不重复注册——MHWilds VecField 目前没有拖入支持
（.tex.<version> 这种双重后缀不适合走 FileHandler 的 bl_file_extensions 匹配，
且它是三方读写里最新、验证最少的一块，先只走菜单/侧栏手动选择文件）。
"""

import bpy

from .i18n import T


def _menu_func_import(self, context):
    layout = self.layout
    layout.operator("efx_re.import", text=T("filemenu.efx"))
    layout.operator("efx_uvs.import", text=T("filemenu.uvs"))
    layout.operator("wilds_vecfield.load_tex", text=T("filemenu.vecfield"))


def _menu_func_export(self, context):
    layout = self.layout
    layout.operator("efx_re.export", text=T("filemenu.efx"))
    layout.operator("efx_uvs.export", text=T("filemenu.uvs"))
    layout.operator("wilds_vecfield.save_tex", text=T("filemenu.vecfield"))


def register():
    bpy.types.TOPBAR_MT_file_import.append(_menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_func_export)


def unregister():
    try:
        bpy.types.TOPBAR_MT_file_export.remove(_menu_func_export)
    except Exception:
        pass
    try:
        bpy.types.TOPBAR_MT_file_import.remove(_menu_func_import)
    except Exception:
        pass
