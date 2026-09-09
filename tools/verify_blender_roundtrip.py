"""
tools/verify_blender_roundtrip.py —— Blender 往返逐字节验证（E1 的回归防护）

必须在 Blender 里跑（要真 bpy），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_roundtrip.py

可选参数放在 `--` 之后：

    ... --python tools/verify_blender_roundtrip.py -- --diag <样本目录> --out <输出目录> --dll <EfxBridge.dll>

`--diag` 默认 `<仓库根>/diag`，收 `*.orig` 当样本（`diag/` 是 untracked 的游戏资产，见
.gitignore）；`--out` 默认建一个临时目录，跑完不删，方便失败时拿 hexdump/010 对比；`--dll`
默认走 `bridge.get_bridge_dll()`（仓库内的 Debug 构建），在 worktree 里没有构建产物时要么先
`git submodule update --init vendor/RE-Engine-Lib && dotnet build tools/EfxBridge -p:LangVersion=preview`，
要么用 `--dll` 指到别处（注意那样 vendor 版本可能和本分支 gitlink 不一致）。

`--factory-startup` 顺带把姊妹插件 `efx_editor` 隔离掉——它和本项目的 Panel/UIList idname
是全局命名空间，会真撞（见 io_tree.py 头部说明）。

**为什么是脚本而不是 pytest**：整条链路要真 bpy（PropertyGroup 注册、Object 自定义属性）
和真样本（Capcom 原始 EFX，不可分发、不在版本控制里），做不成纯单元测试。PLAN.md E1 那三个
缺陷之所以一直没被发现，就是因为往返验证只在 CLI 层（`EfxBridge roundtrip`）做过，从没打到
Blender 这条用户真正会走的路径上——这个脚本就是补那一刀。

每个样本的检查项：

1. **Blender 对象树往返的产物 == 纯 CLI 往返的产物（逐字节）**。判据不是"和原文件逐字节
   相同"——vendor 是"解码成对象模型后总是重新生成字节"的哲学，对原文件本来就有既有差异
   （见 tools/EfxBridge/Program.cs 头部）。这里要求的是更强也更贴题的东西：**过一遍 Blender
   对象树，不引入任何额外差异**。
2. 产物能被 RE-Engine-Lib 读回来（E1 根因 1 的回归点：版本号后缀）。
3. 二次往返稳定 `bytes1 == bytes2`（PLAN.md 第 0 阶段定的 PASS 判据）。
4. `expressionBits` 置位全部保住（E1 根因 2 的回归点）。
5. 读回来的 JSON 与 CLI 产物语义 diff 为 0（E1 根因 3 的回归点：内嵌 `efxrData` 里的具名
   Expression 参数会不会退化成 `ext:<hash>`）。

外加 `operators._ensure_version_suffix()`/`_parsed_file_version()` 的路径形状单测（E1 根因 1）。

退出码：全绿 0，有失败 1。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402  （必须在 sys.path 铺好之后再 import 本项目的包）

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, io_tree, operators, transform3d_view  # noqa: E402


def _script_args() -> list[str]:
    """Blender 会把自己的参数也塞进 sys.argv，脚本参数约定在 `--` 之后。"""
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
    """递归比对两份 dump 出来的 JSON。两边都是同一个 vendor 读出来的，所以浮点表示、键序
    这些噪声不会出现——任何差异都是真实的语义差异。"""
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


def expression_bits(data: dict) -> dict:
    """所有 entry 级 attribute 的 expressionBits 置位，按 (entry 下标, attribute 下标) 索引。"""
    return {
        (ei, ai): (attr["expressionBits"]["bitCount"], sorted(attr["expressionBits"]["bits"]))
        for ei, entry in enumerate(data.get("Entries") or [])
        for ai, attr in enumerate(entry.get("Attributes") or [])
        if attr.get("expressionBits")
    }


def blender_roundtrip(src: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """走 Import 算子 + Export 算子的数据路径（不含文件浏览器 UI），返回实际写出的路径。"""
    data = bridge.dump_efx(src)
    root_obj = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, src.name)
    root_obj.efx_source_filename = src.name
    transform3d_view.sync_all_transform3d(root_obj)

    out_data = io_tree.export_root_to_efxfile(root_obj)
    out_path, notice, fatal = operators._ensure_version_suffix(str(out), out_data)
    if fatal:
        raise RuntimeError(notice or "导出路径拿不到合法版本号后缀")
    bridge.load_efx(out_data, out_path)
    return pathlib.Path(out_path)


def verify_sample(orig: pathlib.Path, workdir: pathlib.Path, report: Report) -> None:
    stem = orig.name.split(".efx.")[0]
    print(f"\n=== {stem}")

    src = workdir / orig.name.replace(".orig", "")
    shutil.copy(orig, src)

    # 纯 CLI 往返基线：完全不经过 Blender 对象树。
    cli_json = bridge.dump_efx(src)
    cli_out = workdir / f"{stem}_cli.efx.5571972"
    bridge.load_efx(cli_json, cli_out)

    blender_out = blender_roundtrip(src, workdir / f"{stem}_blender.efx.5571972")

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
        readback = bridge.dump_efx(blender_out)
        report.check(f"{stem}: 产物能被 RE-Engine-Lib 读回来", True)
    except bridge.BridgeError as ex:
        report.check(f"{stem}: 产物能被 RE-Engine-Lib 读回来", False, str(ex)[:400])

    try:
        second = blender_roundtrip(blender_out, workdir / f"{stem}_blender2.efx.5571972")
        report.check(
            f"{stem}: 二次往返稳定（bytes1 == bytes2）",
            second.read_bytes() == blender_bytes,
        )
    except (bridge.BridgeError, RuntimeError) as ex:
        report.check(f"{stem}: 二次往返稳定（bytes1 == bytes2）", False, str(ex)[:400])

    if readback is None:
        return

    want, got = expression_bits(cli_json), expression_bits(readback)
    report.check(
        f"{stem}: expressionBits 置位全部保住（{len(want)} 个 attribute）",
        want == got,
        f"期望 {want}\n           实际 {got}",
    )

    diffs = semantic_diff(bridge.dump_efx(cli_out), readback)
    report.check(
        f"{stem}: 读回来的 JSON 与 CLI 产物语义 diff 为 0",
        not diffs,
        f"{len(diffs)} 处差异，前 10 处：\n           " + "\n           ".join(diffs[:10]),
    )


def verify_version_suffix(report: Report) -> None:
    """E1 根因 1 的单测：版本号后缀的补齐/校验规则（照抄 vendor PathUtils.ParseFileFormat）。"""
    print("\n=== _ensure_version_suffix() / _parsed_file_version()")
    header = {"Header": {"Version": 5571972}}
    cases = [
        # (输入路径, 期望输出路径, 是否致命, 说明)
        (r"C:\x\out.efx", r"C:\x\out.efx.5571972", False, "缺后缀 -> 自动补齐"),
        (r"C:\x\out.efx.5571972", r"C:\x\out.efx.5571972", False, "已带 -> 原样"),
        (r"C:\x\out.efx.5571972.x64", r"C:\x\out.efx.5571972.x64", False, "pak 多后缀 -> 原样"),
        (r"C:\ver.2\out.efx", r"C:\ver.2\out.efx.5571972", False, "目录名里的点不算"),
        (r"C:\x\out", r"C:\x\out.efx.5571972", False, "连扩展名都没有 -> 一起补"),
        (r"C:\x\out.efx.20", r"C:\x\out.efx.20", False, "版本号不匹配 -> 只警告，不改名"),
        (r"C:\x\my.effect.efx", r"C:\x\my.effect.efx", True, "主干里有点 -> 补不出来，致命"),
    ]
    for path, want_path, want_fatal, note in cases:
        got_path, _notice, fatal = operators._ensure_version_suffix(path, header)
        report.check(
            f"{path}  （{note}）",
            (got_path, fatal) == (want_path, want_fatal),
            f"得到 {(got_path, fatal)}，期望 {(want_path, want_fatal)}",
        )

    report.check(
        "补齐后的路径真的能解析出版本号",
        operators._parsed_file_version(r"C:\x\out.efx.5571972") == 5571972,
    )
    report.check(
        "主干多一个点就解析不出版本号（这就是上面那条致命的原因）",
        operators._parsed_file_version(r"C:\x\my.effect.efx.5571972") == -1,
    )
    report.check(
        "Header 里没有 Version 时不瞎猜一个写进文件名",
        operators._ensure_version_suffix(r"C:\x\out.efx", {}) == (r"C:\x\out.efx", None, False),
    )
    report.check(
        "EFX_RE_OT_export.check_extension is None（否则 ExportHelper 会砍掉版本号后缀）",
        operators.EFX_RE_OT_export.check_extension is None,
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

    diag = pathlib.Path(opts.get("diag", _REPO_ROOT / "diag"))
    samples = sorted(diag.glob("*.orig"))
    if not samples:
        print(f"[ERROR] {diag} 下没有 *.orig 样本。diag/ 是 untracked 的游戏资产（见 .gitignore），"
              "需要自己放一份原始 .efx 并以 .orig 结尾，或用 --diag 指到别处。")
        return 1

    workdir = pathlib.Path(opts["out"]) if "out" in opts else pathlib.Path(
        tempfile.mkdtemp(prefix="efx_roundtrip_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"样本目录: {diag}\n输出目录: {workdir}（跑完不删，失败时拿去 hexdump 对比）")

    blender_efx_re.register()

    report = Report()
    for orig in samples:
        verify_sample(orig, workdir, report)
    verify_version_suffix(report)

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
