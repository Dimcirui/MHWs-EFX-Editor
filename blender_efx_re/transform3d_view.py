"""
blender_efx_re/transform3d_view.py —— Transform3D -> 视口可视化（单向代理，不参与导出）

对齐姊妹项目 EFX-Editor 的 `transform_sync.py` 角色，但换算结论不同（见 `coords.py`
模块说明：1:1 不除 100），落点机制也不同：

  - EFX-Editor（MHWI）的 body 是扁平列表，靠 `PARENTOPTIONS.bone_lim` 显式绑定骨骼才能
    确定基准位置，需要一整套骨骼映射/锚定机制。
  - 本项目的 `EFX_ENTRY`/`EFX_ACTION` 对象本来就用 Blender 原生 parent-child 关系组织
    （见 `io_tree.py` 头部说明），和游戏侧 Entry 树天然一一对应——`Transform3D` attribute
    定义的是"它所属 Entry/Action 的本地变换"，直接把算出来的矩阵写到**它的父对象**
    （Entry/Action，不是 attribute 对象自己）的 `matrix_basis` 上，多层嵌套 Entry 的变换
    叠加完全交给 Blender 自己的 `matrix_world` 计算，不需要像 EFX-Editor 那样手动维护
    基准矩阵/锚定拓扑序。

⚠ object transform（`matrix_basis`/`matrix_world`）**不参与导出**——导出只读
`efx_fields`/`efx_opaque_text` 等数据属性（见 `io_tree.export_attribute_object()`），
整个模块纯可视，写错了也不会污染导出字节。

范围：只处理纯 `EFXAttributeTransform3D`（`model.transform3d_field_values()` 探测的四键
形状）。`Transform3DClip`/`Transform3DExpression` 的姿态是按帧/按公式动态算出来的，不是
静态的 Local Position/Rotation/Scale 三元组，这里不处理——留给以后需要时再做。
"""

from __future__ import annotations

import bpy
from bpy.types import Object, Operator

from . import coords, model


def compute_local_matrix(attr_obj: Object):
    """算一个 Transform3D attribute 对象对应的 Blender 本地变换矩阵；不是 Transform3D
    形状（`model.transform3d_field_values()` 返回 `None`）时同样返回 `None`。"""
    values = model.transform3d_field_values(attr_obj)
    if values is None:
        return None
    pos, rot, scale, order_raw = values
    return coords.local_matrix_to_blender(pos, rot, scale, order_raw)


def apply_transform3d(attr_obj: Object) -> bool:
    """把 `attr_obj`（一个 Transform3D attribute 对象）的值算成 Blender 本地变换，写到它的
    父对象（该 Transform3D 所属的 `EFX_ENTRY`/`EFX_ACTION`）的 `matrix_basis` 上。返回是否
    成功写入。"""
    parent = attr_obj.parent
    if parent is None:
        return False
    matrix = compute_local_matrix(attr_obj)
    if matrix is None:
        return False
    parent.matrix_basis = matrix
    parent.empty_display_type = "ARROWS"
    return True


_WALK_TYPES = (model.TYPE_ROOT, model.TYPE_ENTRY, model.TYPE_ACTION, model.TYPE_ATTRIBUTE)


def sync_all_transform3d(root_obj: Object) -> int:
    """递归遍历 `root_obj` 下所有 `EFX_ATTRIBUTE`（含嵌套 `PlayEmitter.efxrData` 子树里的，
    走法同 `io_tree._walk_clip_issues()`），命中 Transform3D 形状的都应用到其父对象。
    返回成功应用的数量。"""
    count = 0
    for child in root_obj.children:
        if child.get("~TYPE") == model.TYPE_ATTRIBUTE and apply_transform3d(child):
            count += 1
        if child.get("~TYPE") in _WALK_TYPES:
            count += sync_all_transform3d(child)
    return count


class EFX_OT_sync_transform3d(Operator):
    """按选中对象所属 EFX_ROOT 下所有 Transform3D attribute 的当前字段值，重新计算并摆放
    对应 Entry/Action 的位置/旋转/缩放（仅视口可视化，不写入导出数据）"""

    bl_idname = "efx_re.sync_transform3d_to_view"
    bl_label = "Refresh Transform3D View"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import io_tree

        root = io_tree.find_root(context.object)
        if root is None:
            self.report({"ERROR"}, "未找到 EFX_ROOT（请先选中一个 EFX 对象）")
            return {"CANCELLED"}
        n = sync_all_transform3d(root)
        self.report({"INFO"}, f"已刷新 {n} 个 Transform3D 变换")
        return {"FINISHED"}


_CLASSES = (EFX_OT_sync_transform3d,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
