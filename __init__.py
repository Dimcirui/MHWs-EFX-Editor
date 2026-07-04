"""
MHWs-EFX-Editor/__init__.py —— MHWs EFX 编辑器 Blender 扩展根入口

此文件与 blender_manifest.toml 同级，是 Blender 4.2+ 扩展系统识别的入口。
Blender 加载时此目录被视为包 bl_ext.user_default.mhws_efx_editor。

结构（对齐姊妹项目 EFX-Editor 的形状，见 PLAN.md 目录结构一节）：
  MHWs-EFX-Editor/
  ├── __init__.py             ← 本文件（扩展入口，委托给 blender_efx_re）
  ├── blender_manifest.toml
  ├── blender_efx_re/         ← Blender 胶水层（bridge / model / io_tree / operators / panels）
  │   └── __init__.py
  └── tools/EfxBridge/        ← C# 桥接 CLI（不是 Python 包，subprocess 调用）

与 EFX-Editor 的关键差异：没有 efx_format/ 纯 Python 编解码层——解析/回写完全外包给
tools/EfxBridge（调用 vendor/RE-Engine-Lib），blender_efx_re/bridge.py 只是 subprocess
+ JSON 的薄封装，不含任何字节级编解码逻辑（见 PLAN.md 架构决策第 3 点）。
"""

bl_info = {
    "name": "MHWs EFX Editor",
    "author": "Dimcirui",
    "version": (0, 0, 1),
    "blender": (4, 3, 0),
    "location": "View3D > Sidebar > EFX",
    "description": "Import and export Monster Hunter Wilds EFX effect files",
    "category": "Import-Export",
}

from . import blender_efx_re


def register():
    """注册扩展（Blender 扩展系统入口）。"""
    blender_efx_re.register()


def unregister():
    """注销扩展（Blender 扩展系统入口）。"""
    blender_efx_re.unregister()
