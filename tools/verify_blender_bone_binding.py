"""
tools/verify_blender_bone_binding.py —— 骨骼绑定（`bone_binding.py`）的门禁

必须在 Blender 里跑（要真 bpy + 真 depsgraph 求值约束），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_bone_binding.py

可选参数放在 `--` 之后：`--diag <样本目录>`（默认 `<仓库根>/diag`）、`--dll <EfxBridge.dll>`。

**为什么要一个单独的门禁脚本**：`bone_binding.py` 里那个 `inverse_matrix = Rx(-90°)` 是从
"RE-Mesh-Editor 的 `bone.matrix_local == M @ BoneWorld_game`" + "Child Of 的求值式" 两头推出
来的，推错了的表现是特效体整体绕 X 转 90°——在视口里未必一眼看得出来（很多特效是球对称的
烟雾/光斑），但绑到手臂、刀刃上时就是彻底错位。所以这里不目测，直接按**独立算出来的**
`M @ BoneWorld_game @ L_game @ M⁻¹` 对矩阵。

**样本**：`diag/` 下现有的 8 个样本全都没有真实骨骼绑定（`ParentBone` 全是 null），所以这里
不是"找一个带绑定的文件读进来"，而是走用户真正会走的那条路：导入真实文件 → 在某个 Entry 的
`ParentOptions.ParentBone` 字段里填一个骨骼名（等价于用户在面板里敲）→ 选骨架。被测的是
摆位数学和约束管理，不是文件解析，所以注入骨骼名不影响结论的有效性。

检查项：

1. 选择器一设就绑上：Child Of 约束建出来了，target/subtarget/inverse_matrix 都对。
2. **落点正确**：约束求值后的 `matrix_world` == 独立算出来的期望矩阵。
3. 骨架摆 pose 后特效体跟着走（这是选约束而不是烘 `matrix_world` 的全部理由）。
4. 骨架里找不到同名骨骼时**不留半吊子绑定**（宁可回到原点，也不要绑到错的骨头上）。
5. 选择器清空 → 约束被移除干净。
6. **绑定不污染导出字节**：绑定前后 `export_root_to_efxfile()` 的结果完全相同。
7. 作用域只认 `ParentOptions`：别的 attribute 上的 `ParentBone` 不参与摆位（那三个类型的
   骨骼是各自效果自己的目标点，不是父级变换，见 `bone_binding.py` 模块说明）。

9. **Transform3D 编辑实时生效**：在字段树里改 LocalPosition/LocalRotation/RotationOrder，
   不调 `sync_all_transform3d()`，所属 Entry 的 `matrix_basis` 必须立刻跟上；导入/粘贴建出来的
   attribute 也必须一出生就摆好。这一条护的是 `sim_preview` 的宿主矩阵——预览读的是
   `matrix_world`，矩阵不刷新的表现是“本地位置明明是 1，粒子还在原点”，而前面所有门禁
   （判据都是导出字节）对它完全免疫：这条联动根本不写字段数据。

8. `check_bone_relation_alignment()`：真实文件必须通过；把 `BoneRelations` 长度改成和消费者
   数量对不上时必须拒绝（含嵌套 `efxrData` 作用域），并且真的能拦住 `bpy.ops.efx_re.import`。
   这道校验是 `KNOWN_UPSTREAM_ISSUES.md` #9 的回归防护：索引流错位会把特效绑到错骨头上、
   导出时还静默丢槽位，而前三个门禁全都看不见它（判据是"和纯 CLI 往返产物逐字节相同"，
   两边错得一模一样）。另半边：首选项里勾了「绕过骨骼绑定索引对齐校验」之后，同一个错位文件
   必须能导进来并在根上留下 `efx_bone_alignment_bypassed` 标记（`verify_alignment_bypass()`）。

退出码：全绿 0，有失败 1。
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402
from mathutils import Euler, Matrix  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import (  # noqa: E402
    bone_binding, bridge, coords, io_tree, model, preferences, transform3d_view,
)

# 游戏 Y-up -> Blender Z-up 的基变换，和 coords._G2B_BASIS 同一个量（这里独立写一份，
# 免得门禁和被测代码共用同一个常量、一起错还一起绿）。
_M = Matrix.Rotation(math.radians(90), 4, "X")

_TOL = 1e-5

# 故意挑一个平移/旋转都不平凡、且各轴互不相等的骨骼世界矩阵：轴换错、旋转顺序搞反、
# 只取 translation 丢掉朝向，三种错法都会被它抓出来。
_BONE_WORLD_GAME = (
    Matrix.Translation((1.5, 0.4, -2.0))
    @ Euler((math.radians(20), math.radians(30), math.radians(-15)), "XYZ").to_matrix().to_4x4()
)

_BONE_NAME = "Spine0"


def _script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _parse_args(argv: list[str]) -> dict[str, str]:
    opts: dict[str, str] = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1]
    return opts


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
            if detail:
                print("        -> " + detail)


def _matrix_close(a: Matrix, b: Matrix) -> bool:
    return all(abs(a[r][c] - b[r][c]) <= _TOL for r in range(4) for c in range(4))


def _matrix_str(m: Matrix) -> str:
    return " | ".join(", ".join(f"{v:+.5f}" for v in row) for row in m)


def _evaluated_matrix(obj):
    """约束是 depsgraph 求值出来的，原始对象上的 `matrix_world` 不保证同步（尤其
    `--background`），一律读 evaluated 副本。"""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(depsgraph).matrix_world.copy()


def _find_attribute(entry_obj, short_name: str):
    for child in entry_obj.children:
        if child.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if model.short_attr_name(child.efx_attr_type) == short_name:
            return child
    return None


def _pick_entry(root_col):
    """找一个同时带 Transform3D 和 ParentOptions 的 Entry —— 前者决定本地变换，后者承载
    骨骼名，两个都在才测得到完整的合成。"""
    for entry in io_tree.root_entries(root_col):
        t3d = _find_attribute(entry, "Transform3D")
        parent_opts = _find_attribute(entry, "ParentOptions")
        if t3d is None or parent_opts is None:
            continue
        if model.transform3d_field_values(t3d) is None:
            continue
        if model.find_field(parent_opts.efx_fields, "ParentBone") is None:
            continue
        return entry, t3d, parent_opts
    return None, None, None


def _local_matrix_game(t3d_attr) -> Matrix:
    """从 Transform3D 的字段值独立搭出**游戏空间**的本地 TRS 矩阵（不经过 coords.py——
    那是被测代码的一部分）。"""
    pos, rot, scale, order_raw = model.transform3d_field_values(t3d_attr)
    order = coords.rotation_order_to_euler_order(order_raw)
    return (
        Matrix.Translation(pos)
        @ Euler(rot, order).to_matrix().to_4x4()
        @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0)).to_4x4()
    )


def _build_armature(scene) -> object:
    """建一具只有一根骨头的骨架，骨骼 rest 矩阵按 RE-Mesh-Editor 的约定摆
    （`bone.matrix_local == M @ BoneWorld_game`，见 bone_binding.py 模块说明）。"""
    arm_data = bpy.data.armatures.new("VerifyArm")
    arm_obj = bpy.data.objects.new("VerifyArm", arm_data)
    scene.collection.objects.link(arm_obj)
    # 骨架对象自己也挪开：验证 armature.matrix_world 那一段也被正确计入。
    arm_obj.location = (0.3, -0.7, 1.1)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bone = arm_data.edit_bones.new(_BONE_NAME)
    edit_bone.head = (0.0, 0.0, 0.0)
    edit_bone.tail = (0.0, 0.1, 0.0)   # 长度非零，否则 Blender 会丢掉这根骨头
    edit_bone.matrix = _M @ _BONE_WORLD_GAME
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return arm_obj


def verify(root_col, entry, t3d_attr, parent_opts, report: Report) -> None:
    before_export = json.dumps(io_tree.export_root_to_efxfile(root_col), sort_keys=True)

    arm_obj = _build_armature(bpy.context.scene)
    bone_node = model.find_field(parent_opts.efx_fields, "ParentBone")
    bone_node.string_value = _BONE_NAME

    # —— 1. 选择器一设就绑上 ——（走 PointerProperty 的 update 回调，不手动调 sync）
    root_col.efx_re_armature = arm_obj
    con = entry.constraints.get(bone_binding.CONSTRAINT_NAME)
    report.check("设置骨架选择器后建出了 Child Of 约束", con is not None and con.type == "CHILD_OF")
    if con is None:
        return
    report.check("约束 target/subtarget 正确", con.target is arm_obj and con.subtarget == _BONE_NAME,
                 f"target={con.target}, subtarget={con.subtarget!r}")
    report.check(
        "约束 inverse_matrix == Rx(-90°)",
        _matrix_close(con.inverse_matrix.copy(), Matrix.Rotation(math.radians(-90), 4, "X")),
        _matrix_str(con.inverse_matrix),
    )

    # —— 2. 落点正确：期望矩阵独立推导，不复用 coords.py ——
    local_game = _local_matrix_game(t3d_attr)
    expected = arm_obj.matrix_world @ _M @ _BONE_WORLD_GAME @ local_game @ _M.inverted()
    actual = _evaluated_matrix(entry)
    report.check(
        "绑定后的 matrix_world == M @ BoneWorld_game @ L_game @ M⁻¹",
        _matrix_close(actual, expected),
        f"期望 {_matrix_str(expected)}\n            实际 {_matrix_str(actual)}",
    )

    # —— 3. 骨架摆 pose 后跟着走 ——
    rest_world = actual.copy()
    pose_bone = arm_obj.pose.bones[_BONE_NAME]
    pose_bone.location = (0.0, 0.25, 0.0)   # 沿骨骼自身 +Y（Blender 骨骼空间）挪一截
    bpy.context.view_layer.update()
    posed_world = _evaluated_matrix(entry)
    report.check("骨架摆 pose 后特效体跟着动了", not _matrix_close(posed_world, rest_world))
    expected_posed = (
        arm_obj.matrix_world @ pose_bone.matrix @ Matrix.Rotation(math.radians(-90), 4, "X")
        @ coords.local_matrix_to_blender(*model.transform3d_field_values(t3d_attr))
    )
    report.check("pose 下的落点 == bone pose 矩阵 @ Rx(-90°) @ L_blender",
                 _matrix_close(posed_world, expected_posed),
                 f"期望 {_matrix_str(expected_posed)}\n            实际 {_matrix_str(posed_world)}")
    pose_bone.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()

    # —— 4. 骨骼名在骨架里找不到 → 不留半吊子绑定 ——
    bone_node.string_value = "NoSuchBone"
    bound, _cleared, missing = bone_binding.sync_all_bone_bindings(root_col, arm_obj)
    report.check("骨骼名找不到时不建约束",
                 entry.constraints.get(bone_binding.CONSTRAINT_NAME) is None and bound == 0,
                 f"bound={bound}")
    report.check("骨骼名找不到时被报出来", "NoSuchBone" in missing, f"missing={missing}")
    bone_node.string_value = _BONE_NAME
    bone_binding.sync_all_bone_bindings(root_col, arm_obj)

    # —— 5. 选择器清空 → 约束移除干净 ——
    root_col.efx_re_armature = None
    report.check("清空骨架选择器后约束被移除",
                 entry.constraints.get(bone_binding.CONSTRAINT_NAME) is None)
    root_col.efx_re_armature = arm_obj

    # —— 5b. "刷新骨骼绑定"算子：走 io_tree.resolve_root()，和面板取当前 EFX 是同一条路 ——
    entry.constraints.remove(entry.constraints[bone_binding.CONSTRAINT_NAME])
    bpy.context.scene.efx_re_active_root = root_col
    bpy.ops.efx_re.sync_bone_binding()
    report.check("刷新骨骼绑定算子把约束重建了出来",
                 entry.constraints.get(bone_binding.CONSTRAINT_NAME) is not None)

    # —— 6. 绑定不碰导出字节 ——
    after_export = json.dumps(io_tree.export_root_to_efxfile(root_col), sort_keys=True)
    # ParentBone 是被这个脚本改过的（第 1 步写进去的骨骼名），比对时抹平它——要证明的是
    # "建/删约束本身不改导出数据"，不是"字段编辑不改导出数据"。
    report.check(
        "建立绑定不改变导出数据（除被脚本改过的 ParentBone 外）",
        after_export.replace(f'"{_BONE_NAME}"', '""') == before_export,
        "导出 JSON 在绑定前后出现了差异——约束不该碰任何导出数据",
    )

    # —— 7. 作用域只认 ParentOptions ——
    bone_node.string_value = ""
    other = next(
        (c for c in entry.children
         if c.get("~TYPE") == model.TYPE_ATTRIBUTE and c is not parent_opts),
        None,
    )
    if other is None:
        report.check("找到一个非 ParentOptions 的兄弟 attribute", False)
    else:
        node = other.efx_fields.add()
        node.key = "ParentBone"
        node.data_type = "STRING"
        node.string_value = _BONE_NAME
        report.check("非 ParentOptions 上的 ParentBone 不参与摆位",
                     bone_binding.parent_bone_name(entry) == "",
                     f"误取到了 {bone_binding.parent_bone_name(entry)!r}")


def verify_alignment_check(sample: pathlib.Path, nested_candidates, report: Report) -> None:
    """check_bone_relation_alignment()：真文件放行、错位文件拒绝。

    错位样本用"把 BoneRelations 截短一格"造——这正是 #9 那个 bug 在文件层面的形状
    （声明的槽位数比实际消费者多/少），不是随便搓一个非法值。"""
    data = bridge.dump_efx(sample)
    try:
        io_tree.check_bone_relation_alignment(data)
        report.check("真实样本通过对齐校验", True)
    except io_tree.BoneRelationAlignmentError as ex:
        report.check("真实样本通过对齐校验", False, str(ex))
        return

    consumers = io_tree._bone_relation_consumers(data)
    report.check("样本里有至少一个骨骼引用 attribute（否则下面的注入测不到东西）",
                 consumers > 0, f"consumers={consumers}")

    # —— 把 bug 注回去：顶层作用域少一个槽位 ——
    broken = json.loads(json.dumps(data))
    broken["BoneRelations"] = (broken.get("BoneRelations") or [])[:-1]
    try:
        io_tree.check_bone_relation_alignment(broken)
        report.check("BoneRelations 长度对不上时拒绝", False, "没报错，校验形同虚设")
    except io_tree.BoneRelationAlignmentError:
        report.check("BoneRelations 长度对不上时拒绝", True)

    # —— 嵌套 efxrData 作用域也要被覆盖 ——
    # 另找一个带"嵌套子树里有骨骼槽位"的样本：顶层那个样本未必有，而这条分支
    # （递归进 efxrData）正是容易写漏的地方，不能因为没样本就跳过。
    nested_sample = None
    for cand in nested_candidates:
        cand_data = bridge.dump_efx(cand)
        for path, scope in io_tree._bone_relation_scopes(cand_data, ""):
            if path and scope.get("BoneRelations"):
                nested_sample = (cand, cand_data)
                break
        if nested_sample:
            break
    if nested_sample is None:
        report.check("找到一个嵌套子树里带骨骼槽位的样本", False,
                     "没有这种样本，嵌套作用域的分支没被测到")
    else:
        cand, cand_data = nested_sample
        try:
            io_tree.check_bone_relation_alignment(cand_data)
            report.check(f"嵌套样本 {cand.name} 本身通过对齐校验", True)
        except io_tree.BoneRelationAlignmentError as ex:
            report.check(f"嵌套样本 {cand.name} 本身通过对齐校验", False, str(ex))
        broken2 = json.loads(json.dumps(cand_data))
        for path, scope in io_tree._bone_relation_scopes(broken2, ""):
            if path and scope.get("BoneRelations"):
                scope["BoneRelations"] = scope["BoneRelations"][:-1]
                break
        try:
            io_tree.check_bone_relation_alignment(broken2)
            report.check("嵌套 efxrData 作用域的错位也被拒绝", False, "没报错")
        except io_tree.BoneRelationAlignmentError:
            report.check("嵌套 efxrData 作用域的错位也被拒绝", True)

    # —— 真的能拦住 Import 算子（不只是函数会抛）——
    before = len(bpy.data.collections)
    real_dump = bridge.dump_efx

    def poisoned(path):
        d = real_dump(path)
        d["BoneRelations"] = (d.get("BoneRelations") or [])[:-1]
        return d

    bridge.dump_efx = poisoned
    try:
        getattr(bpy.ops.efx_re, "import")(filepath=str(sample))
    except RuntimeError:
        pass          # 全军覆没时算子报 ERROR，Blender 会转成 RuntimeError
    finally:
        bridge.dump_efx = real_dump
    report.check("对齐对不上时 Import 算子不建任何集合",
                 len(bpy.data.collections) == before,
                 f"集合数 {before} -> {len(bpy.data.collections)}")


def verify_bone_name_mirror(sample: pathlib.Path, report: Report) -> None:
    """`ParentBone` <-> 内联骨骼名的联动：用户编辑时同步，导入透传时绝不同步。

    后一半比前一半重要：官方语料里确实存在一个两者不一致的文件，若导入时就把它"修好"了，
    那个文件过一遍 Blender 就会多出字节差异，直接违反"和纯 CLI 往返产物逐字节相同"。
    """
    data = bridge.dump_efx(sample)

    # 造一个"两者不一致"的输入（照官方语料里 11_em0162_00_063 的形状）
    target = None
    for entry in data.get("Entries") or []:
        for attr in entry.get("Attributes") or []:
            if "ParentBone" in attr and "BoneName" in attr:
                target = attr
                break
        if target:
            break
    if target is None:
        report.check("样本里有带 ParentBone + BoneName 的 attribute", False)
        return
    # 两件事一起造：值不一致 + **把内联字段排到 ParentBone 前面**。
    #
    # 键序是关键：vendor 当前吐出来的 JSON 里 ParentBone 恰好在 BoneName 前面，填到
    # ParentBone 时兄弟节点还没建出来，联动自然打空——换句话说，按原键序测不出
    # suppress_field_updates() 到底有没有生效。而键序并不是我们能依赖的东西（vendor 一次
    # 升级就可能变），所以这里主动把顺序倒过来，打在保护真正要防的那个条件上。
    # （ParentOptions 没有像 MdfProperty 那样的键序敏感转换器，重排安全）
    reordered = {"BoneName": "BoneFromInlineField"}
    for key, value in target.items():
        if key != "BoneName":
            reordered[key] = value
    reordered["ParentBone"] = "BoneFromIndexTable"
    target.clear()
    target.update(reordered)

    col = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, "mirror_test.efx.5571972")
    attr_obj = None
    for entry in io_tree.root_entries(col):
        cand = _find_attribute(entry, "ParentOptions")
        if cand is not None and model.find_field(cand.efx_fields, "ParentBone") is not None:
            node = model.find_field(cand.efx_fields, "ParentBone")
            if node.string_value == "BoneFromIndexTable":
                attr_obj = cand
                break
    if attr_obj is None:
        report.check("找得到刚建出来的那个 attribute", False)
        return

    pb = model.find_field(attr_obj.efx_fields, "ParentBone")
    inline = model.find_field(attr_obj.efx_fields, "BoneName")

    # —— 导入透传不得联动 ——
    report.check("导入时不把不一致的两个字段悄悄改成一致",
                 pb.string_value == "BoneFromIndexTable" and inline.string_value == "BoneFromInlineField",
                 f"ParentBone={pb.string_value!r} 内联={inline.string_value!r}")

    out = io_tree.export_root_to_efxfile(col)
    exported = None
    for entry in out.get("Entries") or []:
        for attr in entry.get("Attributes") or []:
            if attr.get("ParentBone") == "BoneFromIndexTable":
                exported = attr
                break
        if exported:
            break
    report.check("导出时内联字段原样写回",
                 exported is not None and exported.get("BoneName") == "BoneFromInlineField",
                 f"exported={exported.get('BoneName')!r}" if exported else "没找到")

    # —— 用户编辑 ParentBone 时必须联动 ——
    pb.string_value = "Spine0"
    report.check("编辑 ParentBone 后内联字段跟着变",
                 inline.string_value == "Spine0", f"内联={inline.string_value!r}")

    # —— 面板判据：有 ParentBone 兄弟才锁，没有就不锁 ——
    report.check("内联字段被认出来（面板会画成只读）",
                 model.is_inline_bone_name_field(inline, attr_obj.efx_attr_type, attr_obj))
    other = next((c for c in io_tree.root_entries(col)[0].children
                  if c.get("~TYPE") == model.TYPE_ATTRIBUTE
                  and model.find_field(c.efx_fields, "ParentBone") is None), None)
    if other is None:
        report.check("找得到一个没有 ParentBone 的 attribute 做反例", False)
    else:
        fake = other.efx_fields.add()
        fake.key = "BoneName"
        fake.data_type = "STRING"
        fake.string_value = "x"
        report.check("没有 ParentBone 兄弟时不锁（保持普通可编辑字段）",
                     not model.is_inline_bone_name_field(fake, other.efx_attr_type, other))


def verify_live_transform3d_sync(sample: pathlib.Path, report: Report) -> None:
    """改 Transform3D 的字段 -> 所属 Entry 的 `matrix_basis` 立刻跟上（不手动调 sync）。

    被测的是 `model.EFXValueNode.float_value`/`int_value` 上的 update 回调
    （`model._on_field_edited()`）和 `io_tree.apply_attribute_content()` 末尾那次补烘。
    没有它们，视口和粒子预览摆的是上一次 `sync_all_transform3d()` 时的姿态，用户改完
    LocalPosition 什么都不会发生——而判据是导出字节的那几个门禁对此完全免疫。
    """
    data = bridge.dump_efx(sample)
    col = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection,
                                          sample.name + "_live")
    col.efx_source_filename = sample.name
    entry = t3d = None
    for candidate in io_tree.root_entries(col):
        attr = _find_attribute(candidate, "Transform3D")
        if attr is not None and model.transform3d_field_values(attr) is not None:
            entry, t3d = candidate, attr
            break
    if t3d is None:
        report.check("样本里有 Transform3D attribute", False)
        return

    # 建出来就该是烘好的：这里**不**调 sync_all_transform3d()，导入/粘贴路径自己要摆好
    report.check("导入建出来的 Entry 一出生就按 Transform3D 摆好（不用手动 Refresh）",
                 _matrix_close(entry.matrix_basis, transform3d_view.compute_local_matrix(t3d)),
                 _matrix_str(entry.matrix_basis))

    pos_node = model.find_field(t3d.efx_fields, "LocalPosition")
    y_node = next((c for c in pos_node.children if c.key in ("y", "Y")), None)
    if y_node is None:
        report.check("LocalPosition 有 y 子节点", False)
        return

    before_export = json.dumps(io_tree.export_root_to_efxfile(col), sort_keys=True)
    origin = (y_node.float_value, )

    y_node.float_value = 7.5
    expected = transform3d_view.compute_local_matrix(t3d)
    report.check("改 LocalPosition.y 后 matrix_basis 立刻跟上（全程没调 sync_all_transform3d）",
                 _matrix_close(entry.matrix_basis, expected),
                 "实际 " + _matrix_str(entry.matrix_basis) + " / 期望 " + _matrix_str(expected))
    # 这才是用户看到的那条链：粒子预览的宿主矩阵是 matrix_world（sim_preview._entry_matrix()）
    bpy.context.view_layer.update()
    report.check("matrix_world 跟着变（sim_preview 读的就是它，游戏 Y -> Blender Z）",
                 abs(entry.matrix_world.translation.z - 7.5) <= _TOL,
                 str(tuple(entry.matrix_world.translation)))

    rot_node = model.find_field(t3d.efx_fields, "LocalRotation")
    rx_node = next((c for c in rot_node.children if c.key in ("x", "X")), None) if rot_node else None
    if rx_node is not None:
        rx_before = rx_node.float_value
        rx_node.float_value = math.radians(30.0)
        report.check("改 LocalRotation.x 后 matrix_basis 立刻跟上",
                     _matrix_close(entry.matrix_basis, transform3d_view.compute_local_matrix(t3d)))
        rx_node.float_value = rx_before

    order_node = model.find_field(t3d.efx_fields, "RotationOrder")
    if order_node is not None and order_node.data_type == "INT":
        order_before = order_node.int_value
        order_node.int_value = (order_before + 1) % 6
        report.check("改 RotationOrder（int_value，也是 enum_proxy 下拉写进来的那个槽）后立刻跟上",
                     _matrix_close(entry.matrix_basis, transform3d_view.compute_local_matrix(t3d)))
        order_node.int_value = order_before

    # 实时联动只写 object transform，不许碰字段数据——否则就成了"看了一眼视口，导出字节变了"
    y_node.float_value = origin[0]
    report.check("字段改回原值后导出字节完全回到原样（联动没写进任何数据）",
                 json.dumps(io_tree.export_root_to_efxfile(col), sort_keys=True) == before_export)

    # 反例对照组：非 Transform3D 的 attribute 上改 float，不许动任何 Entry 的 matrix_basis
    other = None
    for candidate in io_tree.root_entries(col):
        for attr in io_tree.typed_children(candidate, model.TYPE_ATTRIBUTE):
            if model.transform3d_field_values(attr) is None:
                node = next((n for n in attr.efx_fields if n.data_type == "FLOAT"), None)
                if node is not None:
                    other = node
                    break
        if other is not None:
            break
    if other is None:
        report.check("找得到一个非 Transform3D 的 FLOAT 字段做反例", False)
    else:
        snapshot = [(e, e.matrix_basis.copy()) for e in io_tree.root_entries(col)]
        other.float_value = other.float_value + 1.0
        report.check("改非 Transform3D 的字段不会动任何 Entry 的 matrix_basis",
                     all(_matrix_close(e.matrix_basis, m) for e, m in snapshot))
        other.float_value = other.float_value - 1.0


def verify_alignment_bypass(sample: pathlib.Path, report: Report) -> None:
    """首选项里勾了「绕过骨骼绑定索引对齐校验」之后，同一个错位文件必须能导进来，并在根上留下
    `efx_bone_alignment_bypassed` 标记（导出时会据此再警告一次）。

    这是 `verify_alignment_check()` 的另一半：那半边钉住"默认硬拦"，这半边钉住"开关打开后确实
    放行"——只测硬拦的话，开关写坏成永远返回 False 也没人发现。逐文件 WARNING 由算子发出，
    这里拿不到 report 内容，只核落点（建了根 + 打了标记）。"""
    real_dump = bridge.dump_efx
    real_bypass = preferences.bypass_bone_alignment

    def poisoned(path):
        d = real_dump(path)
        d["BoneRelations"] = (d.get("BoneRelations") or [])[:-1]
        return d

    before = set(bpy.data.collections)
    bridge.dump_efx = poisoned
    preferences.bypass_bone_alignment = lambda: True
    try:
        getattr(bpy.ops.efx_re, "import")(filepath=str(sample))
    except RuntimeError as ex:
        report.check("绕过开关打开时错位文件能导入", False, f"仍抛 RuntimeError: {ex}")
    finally:
        bridge.dump_efx = real_dump
        preferences.bypass_bone_alignment = real_bypass

    new_roots = [
        col for col in bpy.data.collections
        if col not in before and getattr(col, "efx_bone_alignment_bypassed", False)
    ]
    report.check("绕过放行时建出根并留下 efx_bone_alignment_bypassed 标记",
                 len(new_roots) == 1, f"带标记的新根数 = {len(new_roots)}")
    # 清掉这次导入建的集合，别污染同一批次后续（或将来追加）的检查。
    for col in list(bpy.data.collections):
        if col not in before:
            bpy.data.collections.remove(col)


def main() -> int:
    opts = _parse_args(_script_args())
    if "dll" in opts:
        bridge._DEFAULT_DLL = pathlib.Path(opts["dll"])
    try:
        print(f"EfxBridge: {bridge.get_bridge_dll()}")
    except bridge.BridgeError as ex:
        print(f"[ERROR] {ex}")
        return 1

    diag = pathlib.Path(opts.get("diag", _REPO_ROOT / "diag"))
    samples = sorted(diag.glob("*.orig"))
    if not samples:
        print(f"[ERROR] {diag} 下没有 *.orig 样本。diag/ 是 untracked 的游戏资产（见 .gitignore），"
              "需要自己放一份原始 .efx 并以 .orig 结尾，或用 --diag 指到别处。")
        return 1

    blender_efx_re.register()

    report = Report()
    # 一个样本足够：被测的是摆位数学，不是逐文件的解析差异。挑第一个带
    # Transform3D + ParentOptions 的样本，全都不合格才算门禁失败。
    for sample in samples:
        data = bridge.dump_efx(sample)
        root_col = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, sample.name)
        root_col.efx_source_filename = sample.name
        # 和 Import 算子同一条路：Transform3D 先落到 Entry 的 matrix_basis 上，骨骼绑定叠在
        # 它之上（不调这一步的话 matrix_basis 是单位阵，测出来的只是骨骼位置本身）。
        transform3d_view.sync_all_transform3d(root_col)
        entry, t3d_attr, parent_opts = _pick_entry(root_col)
        if entry is not None:
            print(f"\n=== {sample.name} / Entry {entry.name}")
            verify(root_col, entry, t3d_attr, parent_opts, report)
            print(f"\n=== 导入对齐校验 / {sample.name}")
            verify_alignment_check(sample, samples, report)
            print(f"\n=== ParentBone / 内联骨骼名联动 / {sample.name}")
            verify_bone_name_mirror(sample, report)
            print(f"\n=== Transform3D 编辑实时生效 / {sample.name}")
            verify_live_transform3d_sync(sample, report)
            print(f"\n=== 绕过对齐校验首选项 / {sample.name}")
            verify_alignment_bypass(sample, report)
            break
    else:
        print("[ERROR] 所有样本里都没有同时带 Transform3D 和 ParentOptions 的 Entry")
        return 1

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
