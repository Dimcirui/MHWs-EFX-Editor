"""
blender_efx_re/preferences.py —— 插件首选项（Edit > Preferences > Add-ons）

目前只有一项：**绕过骨骼绑定索引对齐校验**（默认关）。出厂状态是导入时对齐对不上就整文件
拒绝（细则见 docs/PITFALLS.md #17），这里给一个显式的逃生口——用户在首选项里主动勾上之后，
导入算子会放行并逐文件警告，导出一个曾被放行的树时再警告一次。

⚠ 这是**全仓库唯一一处**允许带着已知损坏的结构继续往下走的地方，而且必须由用户自己开。
不是把默认行为改掉：拿不到首选项（例如没作为插件加载、只是 `import blender_efx_re` 的测试
环境）一律按"关闭"处理，保持硬拦。

放行之后这棵树上的骨骼绑定是错的（见铁律 #1：这属于静默丢数据，只是这里改成了显式告知），
所以放行和导出两个时点都要警告，不能只警告一次就当用户记住了。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty
from bpy.types import AddonPreferences

from . import i18n


def _addon_module() -> str:
    """外层的 addon 包名，也就是 `AddonPreferences.bl_idname` 该填的值。

    本模块位于 `<addon>/blender_efx_re/` 下，剥掉最后一层就是 addon 根：作为扩展安装时是
    `bl_ext.<repo>.<pkg>`，从仓库根直接 import 时是根包名。不写死，免得两种加载方式对不上。
    """
    return __package__.rsplit(".", 1)[0]


class EFX_RE_AddonPreferences(AddonPreferences):
    """屏蔽骨骼绑定索引对齐校验的全局开关。"""

    bl_idname = _addon_module()

    bypass_bone_alignment_check: BoolProperty(
        name="Bypass bone binding alignment check",
        description="允许导入/导出骨骼绑定索引对不上的文件。这类文件的绑定可能已经错位，"
                    "导出还会静默丢掉绑定槽位",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text=i18n.T("prefs.bypass_bone_warn"), icon="ERROR")
        box.prop(self, "bypass_bone_alignment_check", text=i18n.T("prefs.bypass_bone"))


def bypass_bone_alignment() -> bool:
    """当前是否勾了「绕过骨骼绑定索引对齐校验」。

    拿不到首选项时返回 False（保持出厂硬拦）——测试环境里往往只是 `import` 了子包、没有把
    它作为插件启用，这时 `context.preferences.addons` 里没有对应条目，不能因此放行。
    """
    entry = bpy.context.preferences.addons.get(_addon_module())
    prefs = getattr(entry, "preferences", None) if entry is not None else None
    if prefs is None:
        return False
    return bool(getattr(prefs, "bypass_bone_alignment_check", False))


_CLASSES = (EFX_RE_AddonPreferences,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
