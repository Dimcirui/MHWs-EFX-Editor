"""
blender_efx_re/bone_binding.py —— ParentOptions.ParentBone -> 骨架骨骼（视口可视化，不参与导出）

`transform3d_view.py` 只把 Transform3D 算成 Entry/Action 的**本地**变换，基准是世界原点。
真实特效几乎都是挂在骨骼上的：`EFXAttributeParentOptions.ParentBone` 存的就是父骨骼名字
（语料抽样 40 个文件里 11 个带非空值，共 141 处）。这个模块把那个名字接到用户选的 Blender
骨架上，让特效体落到它在游戏里真正的位置。

对齐姊妹项目 EFX-Editor 的 `transform_sync.py` 里的骨骼部分，但三处不同：

1. **不需要名字映射层。** MHWI 那边 `PARENTOPTIONS.jointNo` 是数字，要按
   `MhBone_<jointNo:03d>` 拼出骨骼名才能查；这里 `ParentBone` 本身就是骨骼名字符串
   （语料里是 `Chest` / `Head` / `Spine0` / `R_BladeU8` / `_j001` / `root` 这种），
   和 RE-Mesh-Editor 导入出来的骨架骨骼名逐字相同，直接 `armature.data.bones.get(name)`。
2. **继承骨骼的完整朝向，不是只取 head 位置。** MHWI 那边的 `MhBone_*` 是沿 +Y 的假骨，
   rest 矩阵里混了一个 +90°X 的伪旋转，整体继承会让特效体平白多转 90°，所以那边只取
   translation。这里 RE-Mesh-Editor 建骨时是 `editBone.matrix = bone.worldMatrix`
   （游戏 joint 的世界矩阵本身），之后才把 Rx(+90°) 烘进骨架数据
   （`modules/mesh/blender_re_mesh.py` 的 `editBone.matrix = ...` + `transform_apply`），
   即 `bone.matrix_local == M @ BoneWorld_game`（`M` = Rx(+90°)，同 `coords._G2B_BASIS`）
   ——骨骼的 rest 朝向就是游戏 joint 的真实朝向，可以（也应该）整体继承。
3. **用 Child Of 约束，不烘 `matrix_world`。** 骨架摆 pose / 播动画时特效体跟着走，且每个
   Entry 的 `matrix_basis` 仍然只放 Transform3D 的本地矩阵，`transform3d_view.py` 一行
   不用改。**不能用 Blender 原生父子关系**（`obj.parent = armature`）：
   `io_tree.find_root()` 是沿 `obj.parent` 一路爬到最顶层对象、再看它在哪个集合里
   （`io_tree.py:446`），Entry 一旦认骨架当父对象，爬上去就落到骨架身上，面板/导出全都
   找不到 EFX_ROOT 了。约束不碰 `.parent`，绕开这个问题。

**约束的 `inverse_matrix` 取 Rx(-90°)，是推导出来的常量，不是调出来的魔数**：
Child Of 的求值是 `world = target_world @ inverse_matrix @ owner_world_before`，其中
`target_world = arm.matrix_world @ pose_bone.matrix`（rest 位姿下 `pose_bone.matrix ==
bone.matrix_local`），`owner_world_before` 就是 Entry 的 `matrix_basis`（根 Entry 没有父
对象）= `coords.local_matrix_to_blender()` 算出来的 `L_blender = M @ L_game @ M⁻¹`。
要的结果是游戏里的 `BoneWorld_game @ L_game` 再整体换基到 Blender：

    M @ BoneWorld_game @ L_game @ M⁻¹
  = (M @ BoneWorld_game) @ M⁻¹ @ (M @ L_game @ M⁻¹)
  = bone.matrix_local @ M⁻¹ @ L_blender

对上 Child Of 的式子，`inverse_matrix` 就是 `M⁻¹` = Rx(-90°)，且与 pose 无关（它是骨骼
空间里的一个常量偏移），所以骨架动起来也不用重算。

⚠ 前提是骨架按 RE-Mesh-Editor 的默认选项（"Convert Z Up To Y Up" 开）导入。关掉那个选项
导进来的骨架整体还是 Y-up，和本插件 `coords.py` 全程假定的换基约定对不上，这里不做探测、
也不做补偿。

⚠ 全模块只写 `Object.constraints`，**不碰 `efx_fields` / `efx_opaque_text` 等导出数据**
（导出只读那些，见 `io_tree.export_attribute_object()`），算错了也不会污染导出字节。

**只认 `ParentOptions` 一个 attribute 类型。** MHWilds 下实现 `IBoneRelationAttribute`
的一共 4 个（另有 `Attractor` / `VanishArea3D` / `TypeLightning3D`，见
docs/TOPLEVEL_STRUCTURE.md "Bones / BoneRelations 结构调研"），但那三个的骨骼是各自效果
自己的目标/作用点（吸引子往哪吸、消隐区在哪），不是"这个 Entry 挂在哪根骨头上"——没有样本
证据支持把它们也当成父级变换（不把猜测当事实），所以不碰。
"""

from __future__ import annotations

from math import radians

import bpy
from bpy.props import PointerProperty
from bpy.types import Collection, Object, Operator
from mathutils import Matrix

from . import model

# 约束名，也是"这条约束是本插件建的"的唯一标记：重新绑定时按名字找回来复用/删除，不会误伤
# 用户自己给特效体加的其它约束。
CONSTRAINT_NAME = "EFX Bone Bind"

# Child Of 的 inverse_matrix 常量，= coords._G2B_BASIS 的逆（Rx(-90°)），推导见模块说明。
_BASIS_FIX = Matrix.Rotation(radians(-90), 4, "X")

# 承载"这个 Entry 挂在哪根骨头上"的 attribute 类型（short_attr_name() 之后的短名）。
_PARENT_ATTR_NAME = "ParentOptions"


def parent_bone_name(obj: Object) -> str:
    """一个 Entry/Action 对象绑定的父骨骼名；没有 `ParentOptions` 子 attribute、或它的
    `ParentBone` 是空串时返回空串（= 不绑骨骼）。"""
    for child in obj.children:
        if child.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if model.short_attr_name(child.efx_attr_type) != _PARENT_ATTR_NAME:
            continue
        node = model.find_field(child.efx_fields, "ParentBone")
        if node is not None and node.data_type == "STRING" and node.string_value:
            return node.string_value
    return ""


def _remove_binding(obj: Object) -> bool:
    """删掉这个对象上本插件建的绑定约束；返回是否真的删了一条。"""
    con = obj.constraints.get(CONSTRAINT_NAME)
    if con is None:
        return False
    obj.constraints.remove(con)
    return True


def apply_bone_binding(obj: Object, armature: Object | None) -> str:
    """给一个 Entry/Action 对象建立/更新/清除骨骼绑定约束。返回：

      - `"BOUND"`   —— 已绑到骨架上的对应骨骼
      - `"MISSING"` —— 该对象有 `ParentBone`，但选中的骨架里没有同名骨骼（已清除旧绑定）
      - `"NONE"`    —— 该对象本来就不绑骨骼（已清除旧绑定）
    """
    bone = parent_bone_name(obj)
    if not bone:
        _remove_binding(obj)
        return "NONE"
    if armature is None or armature.type != "ARMATURE" or bone not in armature.data.bones:
        _remove_binding(obj)
        return "MISSING"

    con = obj.constraints.get(CONSTRAINT_NAME)
    if con is not None and con.type != "CHILD_OF":
        # 同名但不是 Child Of（用户手动改过 / 老版本留下的），整条换掉，别就地改类型——
        # Blender 的约束类型是建的时候定死的，改不了。
        obj.constraints.remove(con)
        con = None
    if con is None:
        con = obj.constraints.new("CHILD_OF")
        con.name = CONSTRAINT_NAME
    con.target = armature
    con.subtarget = bone
    con.inverse_matrix = _BASIS_FIX
    # 通过 UI 建的 Child Of 会挂起"等用户按 Set Inverse"的标记，脚本已经把 inverse_matrix
    # 算好了，挂着这个标记反而会在下次求值时被覆盖成自动值。
    if hasattr(con, "set_inverse_pending"):
        con.set_inverse_pending = False
    return "BOUND"


def sync_all_bone_bindings(root_col: Collection, armature: Object | None) -> tuple[int, int, list[str]]:
    """把一个 EFX_ROOT 集合下所有 Entry/Action 的骨骼绑定刷一遍（含内嵌
    `PlayEmitter.efxrData` 子树）。返回 `(绑上的数量, 清掉的数量, 找不到的骨骼名列表)`。

    嵌套子树用**同一个**骨架：vendor 读嵌套文件里的骨骼引用时用的是外层文件的 `Bones` 表
    （`parentFile?.Bones ?? Bones`，见 docs/TOPLEVEL_STRUCTURE.md），名字空间是同一个骨架。

    `armature` 传 `None`（或非骨架对象）时等于"解绑全部"。"""
    from . import io_tree

    bound = cleared = 0
    missing: list[str] = []
    for obj in io_tree.root_entries(root_col) + io_tree.root_actions(root_col):
        had = obj.constraints.get(CONSTRAINT_NAME) is not None
        result = apply_bone_binding(obj, armature)
        if result == "BOUND":
            bound += 1
        else:
            if had:
                cleared += 1
            if result == "MISSING":
                missing.append(parent_bone_name(obj))
        for nested in _nested_roots(obj):
            n_bound, n_cleared, n_missing = sync_all_bone_bindings(nested, armature)
            bound += n_bound
            cleared += n_cleared
            missing.extend(n_missing)
    return bound, cleared, missing


def _nested_roots(obj: Object):
    """一个 Entry/Action 底下所有 attribute 的内嵌 EFX_ROOT 子集合（PlayEmitter.efxrData）。"""
    for child in obj.children:
        if child.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        nested = child.efx_nested_root
        if nested is not None and nested.get("~TYPE") == model.TYPE_ROOT:
            yield nested


# ---------------------------------------------------------------------------
# 骨架选择器（挂在 EFX_ROOT 集合上，每个 efx 文件各绑各的）
# ---------------------------------------------------------------------------


def _armature_poll(self, obj: Object) -> bool:
    return obj.type == "ARMATURE"


def _on_armature_update(self, context):
    """选择器一改就立刻重绑，省掉"选完还得记得按一下刷新"这一步。改成 None 即全部解绑。"""
    if self.get("~TYPE") != model.TYPE_ROOT:
        return
    sync_all_bone_bindings(self, self.efx_re_armature)


class EFX_RE_OT_sync_bone_binding(Operator):
    """按每个 Entry 的 ParentOptions.ParentBone 重建骨骼绑定约束。

    选择器的 update 回调已经覆盖了"换骨架"这一步，这个算子是给另外两种情况用的：用户手改了
    某个 ParentBone 字段值，或者骨架那边补了/改了骨骼名字——两者都不会触发选择器回调。
    """

    bl_idname = "efx_re.sync_bone_binding"
    bl_label = "Sync Bone Binding"
    bl_description = "按每个 Entry 的 ParentOptions 父骨骼名重新绑定到所选骨架（仅可视化，不影响导出数据）"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import io_tree

        root = io_tree.resolve_root(context)
        if root is None:
            self.report({"ERROR"}, "未找到 EFX_ROOT（请先选中一个 EFX 对象）")
            return {"CANCELLED"}
        armature = root.efx_re_armature
        bound, cleared, missing = sync_all_bone_bindings(root, armature)
        if missing:
            unique = sorted(set(missing))
            shown = "、".join(unique[:5]) + ("…" if len(unique) > 5 else "")
            self.report(
                {"WARNING"},
                f"已绑定 {bound} 个，{len(unique)} 个骨骼名在所选骨架里找不到：{shown}",
            )
        else:
            self.report({"INFO"}, f"已绑定 {bound} 个，解绑 {cleared} 个")
        return {"FINISHED"}


_CLASSES = (EFX_RE_OT_sync_bone_binding,)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    Collection.efx_re_armature = PointerProperty(
        name="Armature",
        description="按每个 Entry 的父骨骼名把特效体摆到这具骨架上；留空则以世界原点为基准",
        type=Object,
        poll=_armature_poll,
        update=_on_armature_update,
    )


def unregister():
    try:
        del Collection.efx_re_armature
    except AttributeError:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
