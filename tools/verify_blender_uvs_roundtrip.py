"""
tools/verify_blender_uvs_roundtrip.py —— UVS Blender 往返逐字节验证

对应 verify_blender_roundtrip.py（EFX 那边）的 UVS 版本。必须在 Blender 里跑（要真 bpy）：

    <blender> --background --factory-startup --python tools/verify_blender_uvs_roundtrip.py \
        -- --sample <某个 .uvs.N 文件>

`--sample` 默认指向本机唯一已知的样本（见 PLAN.md "已确认的事实"——语料还没批量解包，
Step 0 未完成，目前只有这一个文件）。`--dll` 同 EFX 版本，默认走 `bridge.get_bridge_dll()`。

判据同 EFX 版本的第 1/3 条（UVS 没有 expressionBits/内嵌 efxrData 这类概念，不适用第 4/5 条）：

1. Blender 对象树往返的产物 == 纯 CLI 往返的产物（逐字节）。
2. 产物能被 RE-Engine-Lib 读回来。
3. 二次往返稳定 `bytes1 == bytes2`。
4. 读回来的 JSON 与 CLI 产物语义 diff 为 0。

外加 uvs_operators._ensure_uvs_version_suffix()/_parsed_file_version() 的路径形状单测。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import types

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, uvs_io, uvs_model, uvs_operators  # noqa: E402

_DEFAULT_SAMPLE = pathlib.Path(
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\natives\STM\Art\VFX"
    r"\UVS\Common\11_cm_fire_000.uvs.8"
)


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


def semantic_diff(a, b, path: str = "", out: list[str] | None = None) -> list[str]:
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a:
            if key not in b:
                out.append(f"MISSING {path}.{key}")
            else:
                semantic_diff(a[key], b[key], f"{path}.{key}", out)
        for key in b:
            if key not in a:
                out.append(f"EXTRA {path}.{key}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"LEN {path}: {len(a)} -> {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            semantic_diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"VALUE {path}: {json.dumps(a)[:60]} -> {json.dumps(b)[:60]}")
    return out


def blender_roundtrip(src: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """走 Import 算子 + Export 算子的数据路径（不含文件浏览器 UI），返回实际写出的路径。"""
    data = bridge.dump_uvs(src)
    root_col = uvs_io.build_uvs_root(data, bpy.context.scene.collection, src.name)
    root_col.efx_uvs_source_filename = src.name

    out_data = uvs_io.export_uvs_root(root_col)
    out_path, notice, fatal = uvs_operators._ensure_uvs_version_suffix(str(out), out_data)
    if fatal:
        raise RuntimeError(notice or "导出路径拿不到合法版本号后缀")
    bridge.load_uvs(out_data, out_path)
    return pathlib.Path(out_path)


def verify_sample(orig: pathlib.Path, workdir: pathlib.Path, report: Report) -> None:
    stem = orig.name.split(".uvs.")[0]
    print(f"\n=== {stem}")

    src = workdir / orig.name
    shutil.copy(orig, src)

    cli_json = bridge.dump_uvs(src)
    cli_out = workdir / f"{stem}_cli.uvs.8"
    bridge.load_uvs(cli_json, cli_out)

    blender_out = blender_roundtrip(src, workdir / f"{stem}_blender.uvs.8")

    cli_bytes, blender_bytes = cli_out.read_bytes(), blender_out.read_bytes()
    report.check(
        f"{stem}: Blender 产物 == 纯 CLI 产物（逐字节）",
        cli_bytes == blender_bytes,
        f"长度 {len(cli_bytes)}/{len(blender_bytes)}，"
        f"差异字节数 {sum(1 for x, y in zip(cli_bytes, blender_bytes) if x != y)}；"
        f"两份产物留在 {workdir}",
    )

    readback = None
    try:
        readback = bridge.dump_uvs(blender_out)
        report.check(f"{stem}: 产物能被 RE-Engine-Lib 读回来", True)
    except bridge.BridgeError as ex:
        report.check(f"{stem}: 产物能被 RE-Engine-Lib 读回来", False, str(ex)[:400])

    try:
        second = blender_roundtrip(blender_out, workdir / f"{stem}_blender2.uvs.8")
        report.check(
            f"{stem}: 二次往返稳定（bytes1 == bytes2）",
            second.read_bytes() == blender_bytes,
        )
    except (bridge.BridgeError, RuntimeError) as ex:
        report.check(f"{stem}: 二次往返稳定（bytes1 == bytes2）", False, str(ex)[:400])

    if readback is None:
        return

    diffs = semantic_diff(bridge.dump_uvs(cli_out), readback)
    report.check(
        f"{stem}: 读回来的 JSON 与 CLI 产物语义 diff 为 0",
        not diffs,
        f"{len(diffs)} 处差异，前 10 处：\n           " + "\n           ".join(diffs[:10]),
    )


def verify_texture_path_separators(report: Report) -> None:
    """贴图路径里的反斜杠必须被规整成正斜杠。

    RE Engine 的资源路径哈希不处理分隔符方向，`\\` 和 `/` 算出来是两个不同的哈希，游戏按哈希
    查资源表，方向错了引用直接失效（EFX 侧那次 `UVSPath` 反斜杠就是这么在游戏内报 "Invalid"
    的）。这个字段**经常是用户从资源管理器复制来的**，也可能是 GIF 转序列帧算子直接塞进来的
    Windows 路径，所以三条路都要验。
    """
    print("\n=== 贴图路径分隔符")
    bad = r"Art\VFX\Texture\Common\Sequence\11_flame_002_ALBA.tex"
    good = "Art/VFX/Texture/Common/Sequence/11_flame_002_ALBA.tex"
    scene_col = bpy.context.scene.collection

    col = uvs_io.build_uvs_root({}, scene_col, "sep_probe")
    item = col.efx_uvs_textures.add()
    item.path = bad
    report.check("手填/算子写入的反斜杠当场就被改成正斜杠", item.path == good, item.path)

    exported = uvs_io.export_uvs_root(col)
    report.check("导出时也是正斜杠", exported["textures"][0]["path"] == good,
                 exported["textures"][0]["path"])

    imported = uvs_io.build_uvs_root({"textures": [{"path": bad}], "sequences": []},
                                     scene_col, "sep_probe2")
    report.check("导入带反斜杠的文件时被纠正", imported.efx_uvs_textures[0].path == good,
                 imported.efx_uvs_textures[0].path)


def verify_version_suffix(report: Report) -> None:
    print("\n=== _ensure_uvs_version_suffix() / _parsed_file_version()")
    data = {"fileVersion": 8}
    cases = [
        (r"C:\x\out.uvs", r"C:\x\out.uvs.8", False, "缺后缀 -> 自动补齐"),
        (r"C:\x\out.uvs.8", r"C:\x\out.uvs.8", False, "已带 -> 原样"),
        (r"C:\x\out.uvs.8.x64", r"C:\x\out.uvs.8.x64", False, "pak 多后缀 -> 原样"),
        (r"C:\ver.2\out.uvs", r"C:\ver.2\out.uvs.8", False, "目录名里的点不算"),
        (r"C:\x\out", r"C:\x\out.uvs.8", False, "连扩展名都没有 -> 一起补"),
        (r"C:\x\out.uvs.20", r"C:\x\out.uvs.20", False, "版本号不匹配 -> 只警告，不改名"),
        (r"C:\x\my.atlas.uvs", r"C:\x\my.atlas.uvs", True, "主干里有点 -> 补不出来，致命"),
    ]
    for path, want_path, want_fatal, note in cases:
        got_path, _notice, fatal = uvs_operators._ensure_uvs_version_suffix(path, data)
        report.check(
            f"{path}  （{note}）",
            (got_path, fatal) == (want_path, want_fatal),
            f"得到 {(got_path, fatal)}，期望 {(want_path, want_fatal)}",
        )

    report.check(
        "补齐后的路径真的能解析出版本号",
        uvs_operators._parsed_file_version(r"C:\x\out.uvs.8") == 8,
    )
    report.check(
        "fileVersion 缺失时不瞎猜一个写进文件名",
        uvs_operators._ensure_uvs_version_suffix(r"C:\x\out.uvs", {}) == (r"C:\x\out.uvs", None, False),
    )
    report.check(
        "EFX_UVS_OT_export.check_extension is None（否则 ExportHelper 会砍掉版本号后缀）",
        uvs_operators.EFX_UVS_OT_export.check_extension is None,
    )


def verify_wrapper_collection_grouping(sample: pathlib.Path, workdir: pathlib.Path,
                                       report: Report) -> None:
    """UVS 根从 Collection 改成 Empty Object 之后新加的机制：单个导入一个 Object 配一个专属
    包裹集合，批量导入（含 EFX 侧"一并导入引用的 .uvs"）一批 Object 共享同一个集合。

    直接测底层的 `uvs_io.new_uvs_collection()` + `build_uvs_root()` 协作（第一段），再测真正
    会被用户触发的 `efx_uvs.import` 算子在单文件/多文件两条路各自建了几个包裹集合（第二段）
    ——两段都要过，只测底层函数会漏掉算子里"先数一遍、再决定建几个集合"那段两段式逻辑本身
    的 bug。
    """
    print("\n=== 包裹集合：单个 vs 批量共享")
    scene_col = bpy.context.scene.collection
    data = bridge.dump_uvs(sample)

    wrapper = uvs_io.new_uvs_collection(scene_col, "UVS Batch Probe")
    obj1 = uvs_io.build_uvs_root(data, wrapper, "probe_a")
    obj2 = uvs_io.build_uvs_root(data, wrapper, "probe_b")
    report.check("共享包裹集合装下了两个 UVS Object",
                 set(wrapper.objects) == {obj1, obj2})
    report.check("两个 Object 都带 ~TYPE 标记，集合本身不带",
                 obj1.get("~TYPE") == uvs_model.TYPE_UVS_ROOT
                 and obj2.get("~TYPE") == uvs_model.TYPE_UVS_ROOT
                 and wrapper.get("~TYPE") is None)

    wrapper_single = uvs_io.new_uvs_collection(scene_col, "probe_single")
    obj_single = uvs_io.build_uvs_root(data, wrapper_single, "probe_single")
    report.check("单个导入的包裹集合只装了这一个 Object",
                 list(wrapper_single.objects) == [obj_single])

    prev_active = bpy.context.scene.efx_uvs_active_root
    bpy.context.scene.efx_uvs_active_root = None

    ctx_batch = types.SimpleNamespace(object=None, collection=wrapper, scene=bpy.context.scene)
    report.check("批量集合下 resolve_uvs_root 不瞎猜（返回 None）",
                 uvs_io.resolve_uvs_root(ctx_batch) is None)

    ctx_single = types.SimpleNamespace(object=None, collection=wrapper_single,
                                       scene=bpy.context.scene)
    report.check("单个集合下 resolve_uvs_root 能唯一确定",
                 uvs_io.resolve_uvs_root(ctx_single) is obj_single)
    bpy.context.scene.efx_uvs_active_root = prev_active

    print("--- efx_uvs.import 算子：单文件 vs 多文件")
    a = workdir / "grp_a.uvs.8"
    b = workdir / "grp_b.uvs.8"
    shutil.copy(sample, a)
    shutil.copy(sample, b)

    def _uvs_objs():
        return {o.name for o in bpy.data.objects if o.get("~TYPE") == uvs_model.TYPE_UVS_ROOT}

    import_op = getattr(bpy.ops.efx_uvs, "import")  # "import" 是 Python 关键字，只能 getattr

    before = _uvs_objs()
    import_op(directory=str(workdir) + "\\", files=[{"name": a.name}])
    new_names = _uvs_objs() - before
    new_objs = [bpy.data.objects[n] for n in new_names]
    report.check("单文件导入产出恰好 1 个 UVS Object", len(new_objs) == 1, str(new_names))
    if new_objs:
        cols = new_objs[0].users_collection
        report.check("单文件导入：这个 Object 的包裹集合里只有它自己",
                     len(cols) == 1 and list(cols[0].objects) == [new_objs[0]])

    before2 = _uvs_objs()
    import_op(directory=str(workdir) + "\\", files=[{"name": a.name}, {"name": b.name}])
    new_names2 = _uvs_objs() - before2
    new_objs2 = [bpy.data.objects[n] for n in new_names2]
    report.check("多文件导入产出恰好 2 个 UVS Object", len(new_objs2) == 2, str(new_names2))
    if len(new_objs2) == 2:
        cols2 = [tuple(o.users_collection) for o in new_objs2]
        report.check(
            "多文件导入：两个 Object 共享同一个包裹集合（不是各建各的）",
            len(cols2[0]) == 1 and cols2[0] == cols2[1],
            str(cols2),
        )
        report.check(
            "共享包裹集合里正好是这两个 Object（没有多建/漏建）",
            set(cols2[0][0].objects) == set(new_objs2),
        )


def main() -> int:
    opts = _parse_args(_script_args())

    if "dll" in opts:
        bridge._DEFAULT_DLL = pathlib.Path(opts["dll"])
    try:
        print(f"EfxBridge: {bridge.get_bridge_dll()}")
    except bridge.BridgeError as ex:
        print(f"[ERROR] {ex}")
        return 1

    sample = pathlib.Path(opts.get("sample", _DEFAULT_SAMPLE))
    if not sample.exists():
        print(f"[ERROR] 样本不存在: {sample}（本机目前只解包了这一个 .uvs，见 PLAN.md Step 0；"
              "用 --sample 指到别处）")
        return 1

    workdir = pathlib.Path(opts["out"]) if "out" in opts else pathlib.Path(
        tempfile.mkdtemp(prefix="uvs_roundtrip_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"样本: {sample}\n输出目录: {workdir}（跑完不删，失败时拿去 hexdump 对比）")

    blender_efx_re.register()

    report = Report()
    verify_sample(sample, workdir, report)
    verify_texture_path_separators(report)
    verify_version_suffix(report)
    verify_wrapper_collection_grouping(sample, workdir, report)

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己捕获异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
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
