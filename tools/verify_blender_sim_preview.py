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

import blender_efx_re  # noqa: E402
from blender_efx_re import (asset_paths, bridge, io_tree, model,  # noqa: E402
                            operators, sim_preview)

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
    if "--sample" in argv:
        return [pathlib.Path(argv[argv.index("--sample") + 1])]
    root = pathlib.Path(
        r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
        r"\EFX\natives\STM\Art\VFX")
    if root.is_dir():
        return sorted(root.rglob("*.efx.5571972"))[:2]
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


def _entries():
    """场景里所有 `EFX_RE_ENTRY` 对象。

    ⚠ 不能从 root 往下 `.children` 走：`EFX_RE_ROOT` 是一个 **Collection**（见 model.py），
    Collection 的 `.children` 是**子集合**不是对象。直接按 `~TYPE` 扫 `bpy.data.objects`。
    """
    return [o for o in bpy.data.objects if o.get("~TYPE") == model.TYPE_ENTRY]


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
    n_entries = n_unsupported_ok = n_render_stable = 0
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
                sim = sim_preview._sim().Simulator(
                    blocks, sim_preview.config_from_scene(scene))
                peak = 0
                for _ in range(120):
                    em = sim.step()
                    peak = max(peak, len(em.particles))
                em = sim.em
                total_spawned += em.spawned_total
                ran += 1

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
                        # 同一批粒子年龄不同 -> 应当停在不同的序列帧上
                        if len(rects) <= 1:
                            _check(False, f"{entry.name} 序列帧没有推进",
                                   f"只有 {len(rects)} 个不同 UV 矩形")
                        if asset_paths.resolve(sorted(keys)[0]) is None:
                            _check(False, f"{entry.name} 贴图路径解析不到",
                                   sorted(keys)[0])

            # 4. **只读**：预览跑完之后重新导出，必须逐字节相同
            after_bytes = _export_bytes(root_obj, tmpdir, "after")
            _check(before == after_bytes, f"{sample.name} 预览前后导出字节一致",
                   f"{len(before)} -> {len(after_bytes)} 字节")

    _check(total_spawned > 0, "整轮下来确实生成过粒子", f"共 {total_spawned} 个")
    _check(n_unsupported_ok > 0, "未模拟属性如实上报", f"{n_unsupported_ok}/{n_entries} 个 Entry")
    _check(n_render_stable == n_entries, "build_render 不改状态且可重复",
           f"{n_render_stable}/{n_entries}")
    if asset_paths.search_roots():
        _check(n_uvs > 0, "解析出了 .uvs 帧表", f"{n_uvs} 个 Entry")
        _check(n_textured > 0, "序列帧 + 贴图标识写进了 RenderItem",
               f"{n_textured} 个 Entry")
    else:
        print("  INFO  没配解包/游戏目录，跳过序列帧链路检查")

    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
