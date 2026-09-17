"""
tools/verify_blender_sim_preview.py —— 粒子预览的 Blender 侧门禁（P0 §7.2）

    <blender> --background --factory-startup --python tools/verify_blender_sim_preview.py \
        [-- --sample <efx 文件>]

退出码 0/1。找不到样本 -> 报错退 1，不静默全绿。

## 它防的是什么

**第 4 条是这条路上唯一真正危险的失效模式**：预览若误写 `efx_fields`，就变成"用户以为只是
看了一眼、实际改了文件"，而现有的 `verify_blender_roundtrip.py` 是"导入 -> 导出"、中间不经过
预览，对这种错**完全免疫**。

前三条是"管道通不通"：P0 的目标是验证基础设施，不是验证物理。

## 检查项

1. 从**真实属性树**拼 blocks（不是从 bridge dump 的 JSON），跑 N 帧，确实生成过粒子。
2. `unsupported` 非空——一个真实 entry 必然有没模拟的属性。**这是在测"预览会承认自己不懂"，
   不是在测它懂。**
3. 渲染 pass 与 step 解耦：重复 `build_render()` 不改状态；生成区域线框能算出来。
4. **只读**：跑完预览之后重新导出，字节必须与跑之前**逐字节相同**。
5. **ES3D 线框叠加层**（`es3d_overlay.py`）：开关成对、线框和粒子落点用的是同一条换算
   （粒子必须落在线框的包围盒里）、改 `EmitterShape3D` 的字段会标脏、移动 Entry 会重建，
   并且整段跑完导出字节照样不变。⚠ 真正的 `gpu` 绘制同样跑不到，被测的是
   `es3d_overlay.refresh()` 那段纯计算（它就是为此从 `_draw_inner()` 里拎出来的）。

## 不覆盖的部分

`--background` 下没有 GPU 上下文，**真正的 `gpu` 绘制调用跑不到**。本脚本会试一次
`gpu.shader.from_builtin()` 并把结果打出来（能跑就顺带验了 shader 取名的跨版本兼容），
但 `draw_handler` 里那条路只能靠**有界面的 Blender** 实测。这是 P0 剩下的唯一未验证环节，
见 docs/SIM_PORT_PLAN.md §7。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import (asset_paths, bridge, es3d_overlay, io_tree,  # noqa: E402
                            model, operators, sim_preview)

_FAILED = 0


def _check(ok: bool, label: str, detail: str = "") -> None:
    global _FAILED
    if ok:
        print(f"  PASS  {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}" + (f"  —— {detail}" if detail else ""))


def _script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _samples() -> list[pathlib.Path]:
    argv = _script_args()
    if "-(-sample)" in argv:
        return [pathlib.Path(argv[argv.index("-(-sample)") + 1])]
    # 解包根换过一次（`MHWILDS_EXTRACT/EFX/natives/STM/...` -> `.../natives/STM/...`），两条都试。
    for root in (pathlib.Path(r"E:\Program\Steam\steamapps\common\MonsterHunterWilds"
                              r"\MHWILDS_EXTRACT\natives\STM\Art\VFX"),
                 pathlib.Path(r"E:\Program\Steam\steamapps\common\MonsterHunterWilds"
                              r"\MHWILDS_EXTRACT\EFX\natives\STM\Art\VFX")):
        if root.is_dir():
            found = sorted(root.rglob("*.efx.5571972"))[:2]
            if found:
                return found
    return []


def _export_bytes(root_obj, tmpdir: pathlib.Path, tag: str) -> bytes:
    """走导出算子的数据路径写一份文件，读回字节。判据是"预览前后一致"，不是"和原文件一致"。"""
    data = io_tree.export_root_to_efxfile(root_obj)
    out = tmpdir / f"{tag}.efx"
    path, _notice, fatal = operators._ensure_version_suffix(str(out), data)
    if fatal:
        raise RuntimeError(f"补不出版本号后缀: {fatal}")
    bridge.load_efx(data, path)
    return pathlib.Path(path).read_bytes()


def _particle_snapshot(em):
    """粒子的**全部**可变状态。

    ⚠ 只抓 pos 是不够的：`build_render` 若碰了 `age`/`alpha`/`vel`，位置当帧看不出差别，
    下一帧才炸。第一版就是只抓 (frame, 粒子数, pos)，注入"build_render 里 age += 1"之后
    门禁照样全绿才发现——和 CLAUDE.md #11 说的"只看它绿不算数"是同一个坑。
    """
    return (em.frame, [(p.pos.as_tuple(), p.vel.as_tuple(), p.scale.as_tuple(),
                        p.rot.as_tuple(), tuple(p.color), p.alpha, p.age,
                        p.life, p.alive, p.delay_left)
                       for p in em.particles])


def _replay_signature(em):
    """一帧的"这次播放和上次播放是不是同一个结果"指纹——**必须包含 `em` 自己的状态**
    （`origin`/`drift`/`rotation_drift`/`scale_drift`），不能只看粒子：`registry.
    build_behaviors()` 不拷贝 `blocks` 那次回归，粒子的**相对**运动其实没变（drift 照样
    从 -1 走到某个值），只是**起点**偏了——纯看粒子位置差不出来，起点偏移会被"粒子跟着
    origin 走"这件事本身悄悄吸收掉。"""
    return (em.frame, tuple(em.origin), tuple(em.drift), tuple(em.rotation_drift),
            tuple(em.scale_drift), _particle_snapshot(em))


def _entries():
    """场景里所有 `EFX_RE_ENTRY` 对象。

    ⚠ 不能从 root 往下 `.children` 走：`EFX_RE_ROOT` 是一个 **Collection**（见 model.py），
    Collection 的 `.children` 是**子集合**不是对象。直接按 `~TYPE` 扫 `bpy.data.objects`。
    """
    return [o for o in bpy.data.objects if o.get("~TYPE") == model.TYPE_ENTRY]


def _select_only(obj):
    """只选中 obj 并设为活动对象（背景模式下 `context.selected_objects` 同样有效）。"""
    for o in bpy.data.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _bbox(points):
    return ([min(pt[i] for pt in points) for i in range(3)],
            [max(pt[i] for pt in points) for i in range(3)])


def verify_es3d_overlay(entries, scene) -> None:
    """ES3D 线框叠加层：开关、线框与粒子同源、标脏、随 Entry 移动。"""
    target = shape_attr = None
    for entry in entries:
        for attr in entry.children:
            if (attr.get("~TYPE") == model.TYPE_ATTRIBUTE
                    and model.short_attr_name(attr.efx_attr_type) == "EmitterShape3D"):
                target, shape_attr = entry, attr
                break
        if target is not None:
            break
    if target is None:
        print("  INFO  这个样本里没有 EmitterShape3D，跳过叠加层检查")
        return

    _select_only(target)
    was_active = es3d_overlay.is_active()
    if was_active:
        bpy.ops.efx_re.es3d_overlay_toggle()

    bpy.ops.efx_re.es3d_overlay_toggle()
    _check(es3d_overlay.is_active(), "toggle 打开后 draw handler 挂上了")

    lines = es3d_overlay.refresh(bpy.context)
    _check(bool(lines), "选中带 EmitterShape3D 的 Entry 后算出了线框")
    _check(len(lines) % 2 == 0, "线框顶点成对（LINES 图元）", f"{len(lines)} 个顶点")

    # 线框和粒子必须同源：粒子的世界坐标应当落在线框的包围盒里。
    # 这条才是这层叠加层的全部意义——两边各算一套形状的话，看到的框是骗人的。
    if lines:
        sim = sim_preview._sim().Simulator(sim_preview.build_blocks(target),
                                           sim_preview.config_from_scene(scene))
        for _ in range(60):
            sim.step()
        matrix = sim_preview._entry_matrix(target)
        pts = [tuple(sim_preview._to_world(matrix, p.spawn_pos)) for p in sim.em.particles]
        if not pts:
            print("  INFO  这个 Entry 没生成粒子，跳过'粒子落在线框里'的比对")
        else:
            lo, hi = _bbox(lines)
            tol = 1e-4 + 1e-3 * max(hi[i] - lo[i] for i in range(3))
            bad = [p for p in pts
                   if any(p[i] < lo[i] - tol or p[i] > hi[i] + tol for i in range(3))]
            _check(not bad, "粒子出生位置全部落在线框包围盒内（线框与采样同源）",
                   f"{len(bad)}/{len(pts)} 个出界，例如 {bad[0] if bad else ''}")

    # 改 EmitterShape3D 的任何字段都要标脏（**不能**列字段白名单，见 model._on_field_edited）
    node = next((n for n in shape_attr.efx_fields if n.data_type == "FLOAT"), None)
    if node is None:
        for parent in shape_attr.efx_fields:
            node = next((c for c in parent.children if c.data_type == "FLOAT"), None)
            if node is not None:
                break
    if node is None:
        _check(False, "EmitterShape3D 里找得到一个 FLOAT 字段")
    else:
        es3d_overlay._STATE["dirty"] = False
        before = list(lines)
        # ⚠ 存原值再写回，**不要**用 +3 再 -3 还原：float32 下那不是恒等变换，
        # 下面"导出字节不变"那条会因此假红（第一版就是这么红的）。
        origin = node.float_value
        node.float_value = origin + 3.0
        _check(es3d_overlay._STATE["dirty"], "改 EmitterShape3D 的字段把叠加层标脏了")
        _check(es3d_overlay.refresh(bpy.context) != before, "标脏后线框真的变了")
        node.float_value = origin
        es3d_overlay.refresh(bpy.context)

    # 移动 Entry -> 签名变化 -> 线框跟着走（矩阵进签名的全部理由）
    lines = list(es3d_overlay.refresh(bpy.context))
    target.matrix_basis.translation.x += 5.0
    bpy.context.view_layer.update()
    moved = es3d_overlay.refresh(bpy.context)
    ok = (len(moved) == len(lines)
          and all(abs((moved[i][0] - lines[i][0]) - 5.0) < 1e-4 for i in range(len(lines))))
    _check(ok, "移动 Entry 后线框跟着平移了同样的量")
    target.matrix_basis.translation.x -= 5.0
    bpy.context.view_layer.update()

    bpy.ops.efx_re.es3d_overlay_toggle()
    _check(not es3d_overlay.is_active(), "再 toggle 一次把 draw handler 摘干净了")
    _check(not es3d_overlay._HANDLERS, "handler 列表没有残留")
    if was_active:
        bpy.ops.efx_re.es3d_overlay_toggle()


def verify_group_scope(entries, scene) -> None:
    """`efx_re_sim_scope` = GROUP：`active_entries()` 不看视口选择，只按
    `io_tree.root_entries()` + `efx_groups` 标签过滤；`ALL Entries` 命中整个 EFX；
    从不返回 Action（`root_actions()`/`root_entries()` 本来就是两个不同的列表）。
    """
    if len(entries) < 2:
        print("  INFO  这个样本 Entry 不够 2 个，跳过分组范围检查")
        return

    root_col = io_tree.find_root(entries[0])
    if root_col is None:
        _check(False, "分组范围检查：解析不到 EFX_ROOT")
        return
    scene.efx_re_active_root = root_col

    tagged, plain = entries[0], entries[1]
    tag = tagged.efx_groups.add()
    tag.name = "__verify_group__"

    for o in bpy.data.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = None

    prev_scope = scene.efx_re_sim_scope
    prev_group = scene.efx_re_sim_group
    try:
        scene.efx_re_sim_scope = "GROUP"

        scene.efx_re_sim_group = "ALL"
        all_names = {o.name for o in sim_preview.active_entries(bpy.context)}
        expected_names = {o.name for o in io_tree.root_entries(root_col)}
        _check(all_names == expected_names,
               "GROUP + All Entries 命中当前 EFX 下全部 Entry，不依赖视口选择",
               f"{all_names} != {expected_names}")

        action_names = {o.name for o in io_tree.root_actions(root_col)}
        _check(not (all_names & action_names), "GROUP 模式从不返回 Action")

        scene.efx_re_sim_group = "__verify_group__"
        filtered_names = [o.name for o in sim_preview.active_entries(bpy.context)]
        _check(filtered_names == [tagged.name],
               "GROUP + 具体分组名只命中带该标签的 Entry", str(filtered_names))
    finally:
        tagged.efx_groups.remove(len(tagged.efx_groups) - 1)
        scene.efx_re_sim_scope = prev_scope
        scene.efx_re_sim_group = prev_group


def verify_loop_clock(entries, scene) -> None:
    """`sim_preview.tick()` 那条真实时钟路径：**循环撞线时最后一帧要能被看见**。

    真实故障（2026-09-17）：一个 `Spawn.LoopNum=0` + `Life.Flags=持续性` + 只有 1 帧
    `.uvs` 的 entry，`suggested_duration()` 算出播放长度 = 1 帧，`tick()` 每次都在第 0 帧
    撞线、**就地** `_reset_all()` 然后 `break`——而 `_rebuild_items()` 排在循环后面，于是
    视口里画的永远是重置后的空场景，面板上帧号一直是 -1。

    ⚠ 这条门禁**不经过** `suggested_duration()`：直接把 `_P["duration"]` 压到 2 帧来逼出
    同一个时序。播放长度算错和"撞线那帧被吞掉"是两个独立的 bug，共用一条判据的话，修好
    任一个另一个就测不到了（CLAUDE.md：门禁可以全绿的同时什么都没测）。
    """
    target = next((e for e in entries if sim_preview.build_blocks(e)), None)
    if target is None:
        _check(False, "循环时钟：样本里找不到能建 track 的 Entry")
        return

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    n = sim_preview.rebuild_tracks(bpy.context, keep_frame=False)
    if not n:
        _check(False, "循环时钟：rebuild_tracks 一个 track 都没建出来")
        return
    try:
        scene.efx_re_sim_mode = "LOOP"
        # ⬇ 必须排在 `efx_re_sim_mode` 赋值**之后**：那个属性的 `update=` 会
        # `mark_dirty()`，而 `tick()` 的第一件事就是“脏了就 rebuild_tracks”——rebuild 里
        # 会把 `_P["duration"]` 重新算成 `suggested_duration()`，把这里压的 2 盖掉。
        # （第一版就是这么写的，帧序列一路递增到 11，根本没撞线。）
        sim_preview._P["dirty"] = False
        sim_preview._P["duration"] = 2
        sim_preview._P["playing"] = True
        sim_preview._P["acc"] = 0.0
        sim_preview._P["pending_reset"] = False

        seen_frames = []
        for _ in range(12):
            sim_preview._P["acc"] += 1.0     # 每次恰好走一帧，不依赖墙钟
            sim_preview._P["last_t"] = __import__("time").perf_counter()
            sim_preview.tick(bpy.context)
            seen_frames.append(sim_preview.current_frame())

        _check(-1 not in seen_frames,
               "循环撞线后不会把第 -1 帧（重置后的空场景）画出来",
               f"看到的帧序列 {seen_frames}")
        # 撞线判据是“步进完之后 `frame >= duration`”，duration=2 因此走 0/1/2 三帧。
        # 这个 off-by-one 是旧有行为（不是本次改动引入的），这里只如实钉住周期。
        _check(sorted(set(seen_frames)) == [0, 1, 2],
               "duration=2 的循环在第 0~2 帧之间周期滑动",
               f"看到的帧序列 {seen_frames}")
        _check(seen_frames.count(0) >= 2, "12 个 tick 里确实循环回绕过不止一次",
               f"看到的帧序列 {seen_frames}")
    finally:
        sim_preview._P["playing"] = False
        sim_preview._P["pending_reset"] = False
        sim_preview.rebuild_tracks(bpy.context, keep_frame=False)


def verify_field_edit_marks_dirty(entries, scene) -> None:
    """`model._on_field_edited()` 对**任意**内容字段都要标脏 `sim_preview`（不止 EmitterShape3D）。

    真实故障（2026-09-17 用户实机报告）：`Velocity3D.Offset`/`Size` 这类字段已经在
    `efx_sim/behaviors/velocity3d.py` 里实装（Normal 档 `方向 = normalize((Size-1)×生成
    坐标+Offset)`），但播放中调它们的数值看不到变化——因为在这次修复之前，只有
    `sim_preview.py` 自己的预览面板旋钮（种子/帧率/距离等，走 `_on_knob_changed()`）会
    `mark_dirty()`，属性树里的普通内容字段编辑完全不会，正在播放的预览读的是上一次
    `rebuild_tracks()` 时的快照。这里刻意优先挑一个和 `EmitterShape3D`/`Transform3D` 都
    无关的 `Velocity3D` 字段，证明这不是 `verify_es3d_overlay()` 那条专用路径顺带盖住的
    ——`_on_field_edited()` 本身也确实不区分字段/attribute 类型，一律标脏。
    """
    def _find_leaf(entry, prefer_type):
        for attr in entry.children:
            if attr.get("~TYPE") != model.TYPE_ATTRIBUTE:
                continue
            if prefer_type is not None and model.short_attr_name(attr.efx_attr_type) != prefer_type:
                continue
            for node in attr.efx_fields:
                if node.data_type in ("FLOAT", "INT"):
                    return node
                for child in node.children:
                    if child.data_type in ("FLOAT", "INT"):
                        return child
        return None

    leaf = None
    for entry in entries:
        leaf = _find_leaf(entry, "Velocity3D")
        if leaf is not None:
            break
    if leaf is None:
        for entry in entries:
            leaf = _find_leaf(entry, None)
            if leaf is not None:
                break
    if leaf is None:
        _check(False, "字段编辑标脏检查：样本里找不到一个 FLOAT/INT 叶子字段")
        return

    sim_preview._P["dirty"] = False
    if leaf.data_type == "FLOAT":
        origin = leaf.float_value
        leaf.float_value = origin + 1.0
        leaf.float_value = origin
    else:
        origin = leaf.int_value
        leaf.int_value = origin + 1
        leaf.int_value = origin
    _check(sim_preview._P["dirty"],
           "编辑任意 attribute 字段值都会把粒子预览标脏（不止 EmitterShape3D）")


def check_mesh_look() -> None:
    """网格在预览里的取图/分桶：必须取**遮罩**、必须走网格专用 shader 的桶。

    防的是"预览里网格糊成一坨实心块"：VFX 网格的镂空全在遮罩贴图里，几何上就是一整张方片。
    取 `BaseMap`（实测那张是 100% 不透明的纯色）就会把每张方片整块画出来，叠起来就是一坨。
    `--background` 下建不了 GPU shader，所以这里验的是**选图和分桶**这两个 CPU 侧决定，
    真正的绘制只能在有界面的 Blender 里看。
    """
    print("\n[网格取图 / 分桶]")
    from blender_efx_re import sim_preview as sp

    def make_material(name, labels):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        mat.node_tree.nodes.clear()
        for label in labels:
            node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.label = label
            node.image = bpy.data.images.new(name + "_" + label, 4, 4)
        tint = mat.node_tree.nodes.new("ShaderNodeMixRGB")
        tint.label = "EFX Emissive Tint"
        tint.inputs["Color2"].default_value = (0.7, 0.84, 0.97, 1.0)
        return mat

    both = make_material("probe_look_both", ("BaseMap", "AlphaMap"))
    key, tint = sp._material_preview_look(both)
    _check(key == "probe_look_both_AlphaMap",
           "有 AlphaMap 时取遮罩，不取 BaseMap", str(key))
    _check([round(v, 3) for v in tint] == [0.7, 0.84, 0.97],
           "染色取自材质的 EFX Emissive Tint", str(tint))

    base_only = make_material("probe_look_base", ("BaseMap",))
    key2, _ = sp._material_preview_look(base_only)
    _check(key2 == "probe_look_base_BaseMap",
           "反例对照：没有 AlphaMap 时退回 BaseMap", str(key2))

    _check(sp._material_preview_look(None) == (None, (1.0, 1.0, 1.0)),
           "反例对照：没有材质时返回 (None, 白)")

    # 分桶：网格必须落进 ("MESH", key)，绘制时才会挑到 _mesh_shader()
    class _It:
        kind = "MESH"
        pos = Vector((0.0, 0.0, 0.0))
        size = Vector((1.0, 1.0, 1.0))
        color = [1.0, 1.0, 1.0, 1.0]
        tex_key = None
        extra = {"rot": (0.0, 0.0, 0.0), "rot_order": 0, "emissive": (0.0, 0.0, 0.0)}

    tris = [(Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((0, 1, 0)),
             (0.0, 0.0), (1.0, 0.0), (0.0, 1.0), "probe_img", (0.5, 0.6, 0.7))]
    buckets = {}
    sp._collect_mesh(_It(), Matrix.Identity(4), tris, buckets)
    keys = list(buckets)
    _check(keys == [("MESH", "probe_img")],
           "网格落进 (\"MESH\", 贴图) 的桶（绘制时据此挑遮罩 shader）", str(keys))
    col = buckets[keys[0]]["col"][0]
    _check([round(v, 3) for v in col[:3]] == [0.5, 0.6, 0.7],
           "材质染色乘进了顶点色", str(col))


def main() -> int:
    global _FAILED

    blender_efx_re.register()

    # GPU 可用性探针（背景模式下通常没有上下文，失败不算 FAIL，只是如实报告）
    try:
        sim_preview._builtin("FLAT_COLOR")
        print("  INFO  gpu.shader.from_builtin('FLAT_COLOR') 可用")
    except Exception as exc:   # noqa: BLE001
        print(f"  INFO  背景模式下 gpu 不可用（预期内）: {type(exc).__name__}")

    samples = _samples()
    if not samples:
        print("[ERROR] 找不到任何 .efx 样本——门禁不能因为没样本就算过")
        return 1

    scene = bpy.context.scene
    total_spawned = 0
    # 汇总计数：通过的检查也要有 PASS 行，否则看不出门禁到底验了什么
    n_entries = n_unsupported_ok = n_render_stable = n_replay_stable = 0
    n_uvs = n_textured = 0

    with tempfile.TemporaryDirectory() as td:
        tmpdir = pathlib.Path(td)
        for sample in samples:
            print(f"=== {sample.name}")
            bpy.ops.wm.read_factory_settings(use_empty=True)
            scene = bpy.context.scene
            data = bridge.dump_efx(sample)
            root_obj = io_tree.build_root_from_efxfile(
                data, bpy.context.scene.collection, sample.name)
            root_obj.efx_source_filename = sample.name

            before = _export_bytes(root_obj, tmpdir, "before")

            entries = _entries()
            _check(bool(entries), "样本里有 Entry")

            ran = 0
            for entry in entries:
                blocks = sim_preview.build_blocks(entry)
                if not blocks:
                    continue
                # `expressions=` 必须传——`_make_track()`（真实预览路径）恒传，这里不传的话
                # Expression 曲线永远不求值、`patch_field()` 永远不触发，下面的"reset()+
                # 重播幂等"检查就测不到它要测的东西（验证纪律：CLI/门禁层绿不代表真实路径绿）。
                sim = sim_preview._sim().Simulator(
                    blocks, sim_preview.config_from_scene(scene),
                    expressions=sim_preview.collect_expressions(entry))
                peak = 0
                first_run_signature = []
                for _ in range(120):
                    em = sim.step()
                    peak = max(peak, len(em.particles))
                    first_run_signature.append(_replay_signature(em))
                em = sim.em
                total_spawned += em.spawned_total
                ran += 1

                # 1b. 重播必须是幂等的：同一个 Simulator 对象连续 reset()+重跑两遍，结果要
                #     逐帧相同。真实故障：`registry.build_behaviors()` 以前直接把 `blocks`
                #     的字段 dict 塞进 FieldView，不拷贝——Expression 曲线的 patch_field()
                #     在上面原地写，第一次播放留下的残留值会污染 blocks 本身，第二次
                #     reset() 时 Transform3D.on_emitter_init() 快照的"基准值"就不是导入
                #     时的原始值了（第一次播放正常、第二次开始永久跑偏，用户反馈原话是
                #     "第一次播放会歪掉一些，从第二次开始就正常了"——实际是反过来，第一次
                #     才是对的）。
                sim.reset()
                second_run_signature = []
                for _ in range(120):
                    em = sim.step()
                    second_run_signature.append(_replay_signature(em))
                if first_run_signature != second_run_signature:
                    _check(False, f"{entry.name} 重播不是幂等的",
                           "第二次 reset()+重跑和第一次结果不一样"
                           "（blocks 字典可能被上一轮播放污染了）")
                else:
                    n_replay_stable += 1

                # 2. 未模拟属性要如实上报（一个真实 entry 必然有）
                if len(blocks) > 3:
                    if em.unsupported:
                        n_unsupported_ok += 1
                    else:
                        _check(False, f"{entry.name} 一个未模拟属性都没报",
                               f"属性 {len(blocks)} 个")

                # 3. 渲染 pass 不改状态
                snap = _particle_snapshot(em)
                items_a = sim.build_render()
                items_b = sim.build_render()
                after = _particle_snapshot(em)
                if snap != after:
                    _check(False, f"{entry.name} build_render 改了状态")
                elif len(items_a) != len(items_b):
                    _check(False, f"{entry.name} build_render 两次结果不一致")
                else:
                    n_render_stable += 1

                if peak:
                    sim.emitter_outline()   # 形状属性存在时不该抛

            _check(ran > 0, "至少跑通了一个 Entry")
            n_entries += ran

            # 5. 序列帧链路：UVSPath -> .uvs -> 帧表 -> UV 矩形 + 贴图标识
            #    只在路径解析器有可用根目录时跑（没配游戏/解包目录是常态，不该让门禁红）
            if asset_paths.search_roots():
                for entry in entries:
                    path = sim_preview._uvs_path_of(entry)
                    if not path:
                        continue
                    res = sim_preview._resources_for(entry)
                    if res.empty:
                        continue
                    n_uvs += 1
                    blocks = sim_preview.build_blocks(entry)
                    sim = sim_preview._sim().Simulator(
                        blocks, sim_preview.config_from_scene(scene), resources=res)
                    for _ in range(30):
                        sim.step()
                    items = sim.build_render()
                    rects = {it.uv_rect for it in items}
                    keys = {it.tex_key for it in items if it.tex_key}
                    if keys:
                        n_textured += 1
                        # 同一批粒子年龄不同 -> 应当停在不同的序列帧上。
                        # ⚠ 只在"确实有可能推进"时才检查：只有 1 个粒子、或者这个粒子选中的
                        # 序列本身只有 1 帧（`.uvs` 里就是张静态图，不是每个序列都是动画），
                        # 两种情况下 rects 恒为 1 个是正确行为，不是没推进——第一次跑到
                        # TypeGpuRibbonLength（PointCloudEmitter 一次只养 1 个粒子）时就被
                        # 这条误伤过，见 CLAUDE.md #11：门禁本身也要经得起真实语料的检验。
                        max_frames = max((it.extra.get("uvs_n", 0) for it in items), default=0)
                        if len(items) > 1 and max_frames > 1 and len(rects) <= 1:
                            _check(False, f"{entry.name} 序列帧没有推进",
                                   f"只有 {len(rects)} 个不同 UV 矩形"
                                   f"（{len(items)} 个粒子，序列共 {max_frames} 帧）")
                        if asset_paths.resolve(sorted(keys)[0]) is None:
                            _check(False, f"{entry.name} 贴图路径解析不到",
                                   sorted(keys)[0])

            # 5. ES3D 线框叠加层。放在导出比对**之前**跑：它的副作用（选中、标脏、
            #    临时挪动 Entry）因此一并被"字节必须不变"那条判据盖住。
            print(f"--- ES3D 叠加层 / {sample.name}")
            verify_es3d_overlay(entries, scene)

            print(f"--- 分组范围（efx_re_sim_scope=GROUP） / {sample.name}")
            verify_group_scope(entries, scene)

            print(f"--- 循环时钟（sim_preview.tick） / {sample.name}")
            verify_loop_clock(entries, scene)

            print(f"--- 字段编辑标脏（Velocity3D 优先） / {sample.name}")
            verify_field_edit_marks_dirty(entries, scene)

            # 4. **只读**：预览跑完之后重新导出，必须逐字节相同
            after_bytes = _export_bytes(root_obj, tmpdir, "after")
            _check(before == after_bytes, f"{sample.name} 预览前后导出字节一致",
                   f"{len(before)} -> {len(after_bytes)} 字节")

    _check(total_spawned > 0, "整轮下来确实生成过粒子", f"共 {total_spawned} 个")
    _check(n_unsupported_ok > 0, "未模拟属性如实上报", f"{n_unsupported_ok}/{n_entries} 个 Entry")
    _check(n_render_stable == n_entries, "build_render 不改状态且可重复",
           f"{n_render_stable}/{n_entries}")
    _check(n_replay_stable == n_entries, "reset()+重播是幂等的（不会一次比一次歪）",
           f"{n_replay_stable}/{n_entries}")
    if asset_paths.search_roots():
        _check(n_uvs > 0, "解析出了 .uvs 帧表", f"{n_uvs} 个 Entry")
        _check(n_textured > 0, "序列帧 + 贴图标识写进了 RenderItem",
               f"{n_textured} 个 Entry")
    else:
        print("  INFO  没配解包/游戏目录，跳过序列帧链路检查")

    check_mesh_look()

    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
