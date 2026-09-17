"""
tools/verify_blender_sr_pair.py —— `{s,r}` 字段的"主值是哪个子节点"在真实属性树上的门禁

    <blender> --background --factory-startup --python tools/verify_blender_sr_pair.py \
        [-- --sample <efx 文件>]

退出码 0/1。找不到样本 -> 报错退 1，不静默全绿。

## 它防的是什么

`via.Range`(float) 的 C# 声明顺序是 `{s, r}`，`via.RangeI`(int) 是 `{r, s}`（vendor
`RszValueType.cs:226` / `:264`），而**二进制首字段恒为主值**（静态值 / min）。
两个结构体的 **key 集合完全相同**，所以 `model.is_static_random_node()` 这种按 key 集合
判形状的做法分不出它们——这正是"面板把全部 46 个 `RangeI` 字段的两列标签画反了"这个 bug
能藏住的原因（`Spawn.LoopNum` 的 `(r=1,s=0)` 被显示成"静态 0 / 随机 1"，真实语义是
"循环 1 次、不随机"）。

纯 Python 单测（`tests/test_sim_core.py`）已经在**手搓的 dict** 上盖住了同一套规则，但那边
的 int/float 是 Python 字面量；这里要验的是**真实属性树**——`EFXValueNode.data_type` 由
`io_tree` 从 EfxBridge 的 JSON 填进来，类型信息是不是真的能一路活到面板层，只有在真 Blender
里跑一遍才知道。这是验证纪律 那条"CLI 层绿不代表 Blender 层绿"在只读侧的对应物。

## 检查项

1. 语料里真实出现的 `Life.AppearFrame` 等四个字段被判成 (min, max)，不是 static/random。
2. `Spawn.LoopNum`（`RangeI`）的主值子节点是 `r`；`Velocity3D.SpeedCoef`（`Range`）是 `s`。
3. 扫过的每个 `{s,r}` 节点都能被 `sr_children_ordered()` 定出主值，且主值就是该结构体的
   二进制首字段（按子节点 `data_type` 判类型）。
4. 四类语义谓词互斥：一个节点不会同时被判成 static/random 和 min/max。
5. `PartsStartNo`（`TypeMesh`/`TypeGpuMesh`）判成 min/max 而不是 static/random，且 Max > Min。
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FAILED = 0


def _check(ok: bool, label: str) -> None:
    global _FAILED
    if ok:
        print(f"  PASS  {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}")


def _sample_paths() -> list[Path]:
    """命令行给了就用给的；否则从语料目录里挑几个。"""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--sample" in argv:
        return [Path(argv[argv.index("--sample") + 1])]
    # 解包根换过一次（`MHWILDS_EXTRACT/EFX/natives/STM/...` -> `.../natives/STM/...`），两条都试。
    roots = [
        Path(r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
              r"\natives\STM\Art\VFX"),
        Path(r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
              r"\EFX\natives\STM\Art\VFX"),
    ]
    for root in roots:
        if root.is_dir():
            found = sorted(root.rglob("*.efx.5571972"))[:3]
            # 额外钉一个带 TypeMeshV2 的文件：`PartsStartNo` 只在 mesh 类 attribute 上出现，
            # 前 3 个文件里不一定有，少了它下面那条断言就等于没测。
            mesh_sample = root / "EffectEditor" / "Weapon" / "it13" / "11_it13_400.efx.5571972"
            if mesh_sample.is_file() and mesh_sample not in found:
                found.append(mesh_sample)
            if found:
                return found
    return []


def main() -> int:
    global _FAILED

    import blender_efx_re
    from blender_efx_re import bridge, io_tree, model

    blender_efx_re.register()

    samples = _sample_paths()
    if not samples:
        print("[ERROR] 找不到任何 .efx 样本——门禁不能因为没样本就算过")
        return 1

    seen_pair_min_max = 0
    seen_start_span = 0
    seen_parts_start = 0
    seen_rangei = 0
    seen_range = 0
    checked_nodes = 0

    for sample in samples:
        print(f"=== {sample.name}")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        try:
            # 走 Import 算子的数据路径（不含文件浏览器 UI），和 verify_blender_roundtrip 一致
            data = bridge.dump_efx(sample)
            io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, sample.name)
        except Exception as exc:   # noqa: BLE001 —— 门禁要把失败原因打出来，不吞
            print(f"[ERROR] 导入失败: {exc}")
            return 1

        for obj in bpy.data.objects:
            if obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
                continue
            attr_type = obj.efx_attr_type
            short = model.short_attr_name(attr_type)
            for node in obj.efx_fields:
                if not model.is_sr_shaped(node):
                    continue
                checked_nodes += 1
                ordered = model.sr_children_ordered(node)

                # 3. 主值必须能定出来，且等于该结构体的二进制首字段
                if ordered is None:
                    _check(False, f"{short}.{node.key} 定不出主值")
                    continue
                primary, secondary = ordered
                by_key = {c.key: c for c in node.children}
                is_int = (by_key["s"].data_type == "INT"
                          and by_key["r"].data_type == "INT")
                want = "r" if is_int else "s"
                if primary.key != want:
                    _check(False,
                           f"{short}.{node.key}（{'RangeI' if is_int else 'Range'}）"
                           f"主值应是 {want}，实得 {primary.key}")
                if is_int:
                    seen_rangei += 1
                else:
                    seen_range += 1

                # 4. 语义谓词互斥。⚠ **新增一类语义就要加进这个元组**——漏了的话那个
                #    字段会"一个谓词都不命中"，面板上什么都不画。
                flags = (model.is_static_random_node(node, attr_type),
                         model.is_pair_min_max_node(node, attr_type),
                         model.is_sr_min_max_node(node),
                         model.is_sr_index_node(node),
                         model.is_sr_start_span_node(node, attr_type))
                if sum(1 for f in flags if f) != 1:
                    _check(False, f"{short}.{node.key} 的语义谓词命中 {sum(flags)} 个，应恰好 1 个")

                # EmitterShape3D 的两个扫描角是 (起始角, 跨度)，不是 static/random。
                # 标错的代价不是"少解释一层语义"，是用户把"我要 360 度"填进起始角那格、
                # 跨度留 0、整个形状塌成一条辐条（实测踩过）。
                if short == "EmitterShape3D" and node.key in ("ScaleHorizontal",
                                                              "ScaleVertical"):
                    seen_start_span += 1
                    if not model.is_sr_start_span_node(node, attr_type):
                        _check(False, f"EmitterShape3D.{node.key} 没被判成 (起始角, 跨度)")
                    if model.is_static_random_node(node, attr_type):
                        _check(False, f"EmitterShape3D.{node.key} 仍被判成 static/random")

                # 1. Life 的四个字段是 (min, max)
                if short == "Life" and node.key in ("AppearFrame", "KeepFrame",
                                                    "VanishFrame", "KeepHoldFrame"):
                    seen_pair_min_max += 1
                    if not model.is_pair_min_max_node(node, attr_type):
                        _check(False, f"Life.{node.key} 没被判成 (min,max)")
                    if model.is_static_random_node(node, attr_type):
                        _check(False, f"Life.{node.key} 仍被判成 static/random")
                    if primary.key != "r":
                        _check(False, f"Life.{node.key} 的 min 应是 r，实得 {primary.key}")

                # 2. 两个标杆字段
                if short == "Spawn" and node.key == "LoopNum":
                    _check(primary.key == "r", "Spawn.LoopNum（RangeI）主值是 r")
                if short == "Velocity3D" and node.key == "SpeedCoef":
                    _check(primary.key == "s", "Velocity3D.SpeedCoef（Range）主值是 s")

                # 5. `PartsStartNo` 是 min/max，**不是** static/random。全语料 10886 个实例
                #    里 s<=r 和 s==0 各 0 例（后者在 static/random 语义下本该是多数），
                #    见 model._SR_MIN_MAX_FIELD_NAMES 上面的说明。判错不会报任何错，
                #    只会让面板把两列标反、预览把区间读成"静态值+随机量"。
                if node.key == "PartsStartNo":
                    seen_parts_start += 1
                    _check(model.is_sr_min_max_node(node),
                           f"{short}.PartsStartNo 判成 min/max")
                    _check(not model.is_static_random_node(node, attr_type),
                           f"{short}.PartsStartNo 没被判成 static/random")
                    _check(primary.key == "r",
                           f"{short}.PartsStartNo（RangeI）的 Min 是 r")
                    values = (model.node_to_value(primary), model.node_to_value(secondary))
                    _check(values[1] > values[0],
                           f"{short}.PartsStartNo 的 Max > Min（实得 {values}）")

    print()
    print(f"=== 扫过 {checked_nodes} 个 {{s,r}} 节点"
          f"（RangeI {seen_rangei} / Range {seen_range}），"
          f"其中 Life 的 (min,max) 字段 {seen_pair_min_max} 个、扫描角 {seen_start_span} 个")

    # 样本里必须真的出现过两类结构体，否则这个门禁什么也没验到
    _check(seen_rangei > 0, "样本里出现过 RangeI 字段")
    _check(seen_range > 0, "样本里出现过 Range 字段")
    _check(seen_pair_min_max > 0, "样本里出现过 Life 的 (min,max) 字段")
    _check(seen_parts_start > 0, "样本里出现过 PartsStartNo（不然那几条断言等于没测）")
    _check(seen_start_span > 0, "样本里出现过 EmitterShape3D 的扫描角字段")

    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己兜住异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # **未捕获异常**时**退出码仍然是 0**（实测），`sys.exit(main())` 那行根本轮不到执行——
    # 净效果是"门禁崩在第一行"和"门禁全过"对调用方长得一模一样，正是静默全绿。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
