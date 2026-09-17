"""
tools/verify_blender_ptbehavior_property.py —— PtBehavior 候选目录增删门禁

必须在 Blender 里跑（要真 bpy），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_ptbehavior_property.py

可选参数放在 `--` 之后：

    ... -- --efx <样本 .efx 路径>

不给 `--efx` 时按 `_DEFAULT_EFX_CANDIDATES` 试固定样本（真实语料，含
`app.EffectPlEmissiveControl` 这个已收录进候选目录的 behaviorString）。找不到样本、或样本里
一个「收录进候选目录的 PtBehavior」都没有，**报错退 1，不静默全绿**（同其它门禁脚本的约定）。

检查项：

1. `ptbehavior_catalog.candidates()` 能读到目录，候选列表**恰好**排除掉已经覆盖过的属性名。
2. `efx_re.ptbehavior_property_add` 加出来的那条，`behaviorProperty` 就是选中的候选名，
   模板字段（`varSize`/`dataType`/`variable`/`varHash`）原样带过去（不是我们手工拼的）。
3. **新增按候选目录的规范顺序插入，不是简单追加**——加完之后 `properties` 里全部
   `behaviorProperty` 的相对顺序必须是候选目录规范顺序的一个子序列。
4. 加完之后走 Export 算子写出来的文件**能被 RE-Engine-Lib 读回来**，条数、每条的名字/顺序
   都和 Blender 里的状态一致。
5. `efx_re.ptbehavior_property_remove` 删掉之后同样能读回来，条数、内容都回到加之前的状态
   （加了又删 = 无操作，字节应该和从没加过时的导出完全一样）。
6. 面板绘制（`panels._draw_ptbehavior_property`）不崩，主行画出属性名 + 删除按钮。
7. **把"保序插入"这个改动临时注回去，确认它真的 FAIL**（CLAUDE.md 验证纪律）：
   把新增强制改成"总是追加到末尾"，再验一次"相对顺序是候选目录子序列"，必须失败——这条是
   整个功能里唯一"我们自己算的行为"（克隆真实样本本身不会错，插入位置算法才会）。

退出码：全绿 0，有失败 1。
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
from blender_efx_re import bridge, io_tree, model, operators, ptbehavior_catalog, structure_ops  # noqa: E402

#: 解包根换过一次（`MHWILDS_EXTRACT/EFX/natives/STM/...` -> `MHWILDS_EXTRACT/Art/VFX/...`），
#: 都试一遍，全落空仍然报错退 1。这个样本含 `app.EffectPlEmissiveControl`（已收录进候选目录）。
_DEFAULT_EFX_CANDIDATES = (
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\Art\VFX\EffectEditor\Weapon\it00\11_it00_000.efx.5571972",
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\natives\STM\Art\VFX\EffectEditor\Weapon\it00\11_it00_000.efx.5571972",
)
_DEFAULT_EFX = next((p for p in _DEFAULT_EFX_CANDIDATES if pathlib.Path(p).is_file()),
                    _DEFAULT_EFX_CANDIDATES[0])


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


class _FakeLayout:
    """无头 Blender 没有区域可以真画面板，用它把 draw 跑一遍：既验证不抛异常，也能断言
    主行上画出来的确实是"名字 + 删除按钮"。照抄 `verify_blender_mdf_property.py` 的写法。"""

    def __init__(self, log: list, enabled: bool = True) -> None:
        self.log = log
        self.enabled = enabled

    def _child(self, *args, **kwargs):
        return _FakeLayout(self.log, self.enabled)

    row = column = split = box = _child

    def prop(self, data, prop_name, **kwargs):
        self.log.append(("prop", getattr(data, "key", ""), prop_name, self.enabled))

    def label(self, **kwargs):
        self.log.append(("label", kwargs.get("text", ""), self.enabled, kwargs.get("icon", "")))

    def operator(self, idname, **kwargs):
        self.log.append(("operator", idname, self.enabled))
        return type("Op", (), {})()

    def __getattr__(self, name):
        return self._child


def _find_ptbehavior_attribute():
    """场景里第一个「命中候选目录」的 PtBehavior attribute 对象。"""
    for obj in bpy.data.objects:
        node, behavior_string = structure_ops.resolve_ptbehavior_properties(obj)
        if node is not None:
            return obj, node, behavior_string
    return None, None, None


def _export(root_col, out_path: pathlib.Path) -> pathlib.Path:
    data = io_tree.export_root_to_efxfile(root_col)
    resolved, notice, fatal = operators._ensure_version_suffix(str(out_path), data)
    if fatal:
        raise RuntimeError(notice or "导出路径拿不到合法版本号后缀")
    bridge.load_efx(data, resolved)
    return pathlib.Path(resolved)


def _read_back_ptbehavior(path: pathlib.Path):
    """读回写出的文件，返回第一个 `EFXAttributePtBehavior` 的 `properties` 列表。"""
    data = bridge.dump_efx(path)
    for entry in data.get("Entries") or []:
        for attr in entry.get("Attributes") or []:
            if str(attr.get("$type", "")).endswith("EFXAttributePtBehavior"):
                return attr.get("properties")
    return None


def _names_in_order(properties_node) -> list[str]:
    names = []
    for child in properties_node.children:
        for sub in child.children:
            if sub.key == "behaviorProperty":
                names.append(model.node_to_value(sub))
    return names


def _is_subsequence(sub: list[str], full: list[str]) -> bool:
    it = iter(full)
    return all(x in it for x in sub)  # 依赖 iter 状态推进，逐个按顺序找


def verify(efx_path: pathlib.Path, workdir: pathlib.Path, report: Report) -> None:
    data = bridge.dump_efx(efx_path)
    root_col = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, efx_path.name)
    root_col.efx_source_filename = efx_path.name

    obj, node, behavior_string = _find_ptbehavior_attribute()
    if obj is None:
        report.check(
            f"{efx_path.name}: 找到收录进候选目录的 PtBehavior attribute", False,
            "样本里没有命中 `ptbehavior_catalog` 的 behaviorString，换一个 --efx",
        )
        return
    print(f"  样本 {efx_path.name}：behaviorString = {behavior_string}，"
          f"现有 {len(node.children)} 条属性")

    bpy.context.view_layer.objects.active = obj
    before = len(node.children)
    before_names = structure_ops._present_ptbehavior_names(node)

    catalog_entries = ptbehavior_catalog.candidates(behavior_string)
    order = [e["name"] for e in catalog_entries]
    report.check("候选目录非空", bool(catalog_entries), f"behaviorString={behavior_string}")

    free = [e["name"] for e in catalog_entries if e["name"] not in before_names]
    report.check(
        "候选列表排除掉已经覆盖过的属性",
        len(free) == len(catalog_entries) - len(before_names & set(order)),
    )
    if not free:
        report.check("样本还有没被覆盖的候选可以加", False, "这个类的候选已经全覆盖，换一个样本")
        return

    pick = free[0]
    bpy.ops.efx_re.ptbehavior_property_add(candidate=pick)
    report.check("Add 算子加出一条", len(node.children) == before + 1,
                 f"{before} -> {len(node.children)}")

    added_names = structure_ops._present_ptbehavior_names(node) - before_names
    report.check(f"新增的是选中的候选 '{pick}'", added_names == {pick}, str(added_names))

    names_now = _names_in_order(node)
    report.check(
        "保序插入：新增后 properties 的相对顺序是候选目录规范顺序的子序列",
        _is_subsequence(names_now, order),
        f"实际顺序 {names_now}\n规范顺序 {order}",
    )

    out_path = _export(root_col, workdir / "added.efx")
    props = _read_back_ptbehavior(out_path)
    report.check("加完之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("读回来的条数对", len(props) == before + 1, f"{len(props)} != {before + 1}")
        readback_names = [p.get("behaviorProperty") for p in props]
        report.check("读回来的顺序和 Blender 里一致", readback_names == names_now,
                     f"{readback_names} != {names_now}")

    # ---- 面板绘制：不崩，主行画出名字 + 删除按钮 -------------------------------
    from blender_efx_re import panels

    new_child = next(c for c in node.children
                      if any(sub.key == "behaviorProperty" and model.node_to_value(sub) == pick
                             for sub in c.children))
    new_child.ui_expand = False
    index = list(node.children).index(new_child)
    log: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log), new_child, index)
    report.check(f"面板主行画出属性名 '{pick}'",
                 any(e[0] == "label" and e[1] == pick for e in log), str(log))
    report.check("面板主行有删除按钮",
                 any(e[0] == "operator" and e[1] == "efx_re.ptbehavior_property_remove"
                     for e in log))

    # ---- 删除，回到加之前的状态 --------------------------------------------
    bpy.ops.efx_re.ptbehavior_property_remove(index=index)
    report.check("Remove 算子删掉一条", len(node.children) == before,
                 f"{len(node.children)} != {before}")
    out_path = _export(root_col, workdir / "removed.efx")
    props = _read_back_ptbehavior(out_path)
    report.check("删完之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("删完读回来的条数对", len(props) == before, f"{len(props)} != {before}")
        readback_names = [p.get("behaviorProperty") for p in props]
        report.check("删完读回来的名字和加之前完全一致（加了又删=无操作）",
                     set(readback_names) == before_names, str(readback_names))

    # ---- 把"保序插入"注回去，确认它真的 FAIL（验证纪律）--------------------
    pick2 = next((n for n in free if n != pick), None)
    if pick2 is None:
        print("  （这个类候选只有 1 条，跳过保序插入的回归防护验证）")
        return

    import blender_efx_re.structure_ops as so
    original_add = so.EFX_RE_OT_ptbehavior_property_add.execute

    def _broken_execute(self, context):
        # 模拟"忘了按规范顺序插入、直接追加到末尾"这个 bug：跳过 move()，只 add() + populate。
        properties_node, behavior_string = so.resolve_ptbehavior_properties(context.object)
        catalog_entries = ptbehavior_catalog.candidates(behavior_string)
        entry = next(e for e in catalog_entries if e["name"] == self.candidate)
        child = properties_node.children.add()
        model.populate_node(child, str(len(properties_node.children) - 1), entry["template"])
        so._renumber_array_keys(properties_node)
        return {"FINISHED"}

    so.EFX_RE_OT_ptbehavior_property_add.execute = _broken_execute
    try:
        bpy.ops.efx_re.ptbehavior_property_add(candidate=pick2)
        broken_names = _names_in_order(node)
        broken_ok = _is_subsequence(broken_names, order)
    finally:
        so.EFX_RE_OT_ptbehavior_property_add.execute = original_add
        bpy.ops.efx_re.ptbehavior_property_remove(index=len(node.children) - 1)

    report.check(
        "注回「总是追加到末尾」的 bug 之后，保序检查必须 FAIL（不能一直绿）",
        not broken_ok,
        f"防护无效：追加到末尾的结果仍然被判定为子序列，说明这条检查测不到顺序问题。"
        f"broken_names={broken_names}",
    )


def main() -> int:
    opts = _parse_args(_script_args())
    efx_path = pathlib.Path(opts.get("efx", _DEFAULT_EFX))

    if not efx_path.is_file():
        print(f"[ERROR] 样本不存在：{efx_path}（用 -- --efx <文件> 指定）")
        return 1

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="efx_ptbehavior_"))
    print(f"输出目录: {workdir}（跑完不删）")

    blender_efx_re.register()

    report = Report()
    verify(efx_path, workdir, report)

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己兜住异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # 未捕获异常时退出码仍然是 0（实测），`sys.exit(main())` 那行根本轮不到执行。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
