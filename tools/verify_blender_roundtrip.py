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

1. **Blender 对象树往返的产物 == 纯 CLI 往返的产物（逐字节，或数值容差内）**。判据不是
   "和原文件逐字节相同"——vendor 是"解码成对象模型后总是重新生成字节"的哲学，对原文件本来
   就有既有差异（见 tools/EfxBridge/Program.cs 头部）。这里要求的是更强也更贴题的东西：**过
   一遍 Blender 对象树，不引入任何额外差异**。
   ⚠ 唯一已知、已接受的例外：`clip_fcurve.py` 把 Bezier 切线句柄接进 Blender 原生 fcurve 后
   有不可修复的 float32 ULP 级精度损失（`BezTriple` 本身的存储精度，2026-09-19 实测确认，
   见 `clip_fcurve.py` 模块文档）。字节不同时退化成 `semantic_diff()` 的数值容差比对
   （`math.isclose`，`rel_tol=1e-4`），容差外才算失败——这不是放宽了整体判据，容差小到
   不会把真正的逻辑 bug 也放过去（`tools/verify_blender_clip_fcurve.py` 已经用一次真实的
   切线符号错误验证过这一点）。
2. 产物能被 RE-Engine-Lib 读回来（E1 根因 1 的回归点：版本号后缀）。
3. 二次往返稳定 `bytes1 == bytes2`（PLAN.md 第 0 阶段定的 PASS 判据，或数值容差内）。
   ⚠ 2026-09-19 `clip_fcurve.py` 加上 Hermite→Bezier 的 ÷3（导入）/×3（导出）换算之后，
   多引入了一次浮点运算，会把检查项 1 里那种 float32 ULP 级精度损失也带进这条"重复保存
   不漂移"的检查——实测 `11_guide_110` 样本上 `in_x: -98.15201` 变成 `-98.152016`，跟检查项
   1 里"98.152 存一圈变成 98.15199..."是同一量级（~1e-6 绝对误差），不是无限累积漂移
   （第二次和第三次往返之间的差异不会继续变大）。跟用户确认过，比照检查项 1 的先例，同样
   退化成 `semantic_diff()` 数值容差比对，不是新开一个判据。
4. `expressionBits` 置位全部保住（E1 根因 2 的回归点）。
5. 读回来的 JSON 与 CLI 产物语义 diff 为 0（E1 根因 3 的回归点：内嵌 `efxrData` 里的具名
   Expression 参数会不会退化成 `ext:<hash>`）。

外加 `operators._ensure_version_suffix()`/`_parsed_file_version()` 的路径形状单测（E1 根因 1）。

外加同名 EffectGroups（KNOWN_UPSTREAM_ISSUES.md #13，在带 EffectGroups 的样本上合成一个同名组）
逐组保住，以及导入时 nameHash 和名字对不上的 Entry/Action 能被报出、反查出原名、一键改回，
官方样本和"在 Blender 里改过名"都不误报（io_tree.name_hash_drift()）。

外加"公式记法版本"那道拦截（`io_tree.check_expression_notation()`，vendor bump 到 `1c2f92d`
之后旧 .blend 里的公式按旧写法存着）：新导入的树带版本号能导出；抹掉版本号模拟旧 .blend，
导出算子必须 CANCELLED 且不写文件；不带公式的旧树照常放行；Copy/Paste 和 Entry 预设这两条
能把旧公式"洗"进新树的路同样被拦住。样本里一条公式都没有时这一节报错，不静默全绿。

退出码：全绿 0，有失败 1。
"""

from __future__ import annotations

import json
import math
import pathlib
import shutil
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402  （必须在 sys.path 铺好之后再 import 本项目的包）

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, io_tree, model, operators, transform3d_view  # noqa: E402


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
    这些噪声一般不会出现——任何差异都是真实的语义差异。

    唯一的例外是 Bezier 切线句柄的 float32 ULP 级精度损失（见本文件模块文档"检查项 1"的
    说明）：float 叶子按 `math.isclose()` 容差判等，其余类型仍然要求完全相等，容差本身很小
    （`rel_tol=1e-4`），不会把真正的逻辑差异也吸收掉。"""
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
    elif isinstance(a, float) or isinstance(b, float):
        if not (isinstance(a, float) and isinstance(b, float)
                and math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-6)):
            out.append(f"VALUE {path}: {json.dumps(a)[:60]} -> {json.dumps(b)[:60]}")
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
    if cli_bytes == blender_bytes:
        bytes_ok, bytes_detail = True, ""
    else:
        # 字节不同不直接判失败——先看是不是只有 Bezier 切线句柄的 float32 ULP 级精度损失
        # （见模块文档"检查项 1"），是的话数值容差内也算过。
        tolerant_diffs = semantic_diff(bridge.dump_efx(cli_out), bridge.dump_efx(blender_out))
        bytes_ok = not tolerant_diffs
        bytes_detail = (
            f"长度 {len(cli_bytes)}/{len(blender_bytes)}，"
            f"差异字节数 {sum(1 for x, y in zip(cli_bytes, blender_bytes) if x != y)}；"
            f"两份产物留在 {workdir}；数值容差比对{'仍不通过' if tolerant_diffs else '通过'}："
            + "; ".join(tolerant_diffs[:5])
        )
    report.check(f"{stem}: Blender 产物 == 纯 CLI 产物（逐字节，或数值容差内）",
                 bytes_ok, bytes_detail)

    readback = None
    try:
        readback = bridge.dump_efx(blender_out)
        report.check(f"{stem}: 产物能被 RE-Engine-Lib 读回来", True)
    except bridge.BridgeError as ex:
        report.check(f"{stem}: 产物能被 RE-Engine-Lib 读回来", False, str(ex)[:400])

    try:
        second = blender_roundtrip(blender_out, workdir / f"{stem}_blender2.efx.5571972")
        second_bytes = second.read_bytes()
        if second_bytes == blender_bytes:
            second_ok, second_detail = True, ""
        else:
            # 同检查项 1 的理由：Hermite 切线 ÷3/×3 换算多引入一次浮点运算，字节不同时
            # 退化成数值容差比对，不是新判据（2026-09-19 用户确认，见模块文档）。
            tolerant_diffs = semantic_diff(bridge.dump_efx(blender_out), bridge.dump_efx(second))
            second_ok = not tolerant_diffs
            second_detail = "数值容差比对" + ("仍不通过：" + "; ".join(tolerant_diffs[:5])
                                              if tolerant_diffs else "通过")
        report.check(f"{stem}: 二次往返稳定（bytes1 == bytes2，或数值容差内）",
                     second_ok, second_detail)
    except (bridge.BridgeError, RuntimeError) as ex:
        report.check(f"{stem}: 二次往返稳定（bytes1 == bytes2，或数值容差内）", False, str(ex)[:400])

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


def verify_path_separators(report: Report) -> None:
    """通用字段树里手打进去的反斜杠也要被纠正，不能只纠正导入的那一份。

    导入侧 `populate_node()` 一直会规整，但用户在面板里粘贴路径走的是 `string_value` 的
    update 回调——"导入的被纠正、自己填的不纠正"这种不一致，正好在最容易犯错的场景
    （从资源管理器复制路径）下失灵，而那次 `UVSPath` 反斜杠导致游戏内报 "Invalid" 就是这么来的。
    """
    print("\n=== 路径分隔符（手填）")
    bad = r"Art\VFX\UVS\Dimcirui\ak.uvs"
    good = "Art/VFX/UVS/Dimcirui/ak.uvs"

    obj = bpy.data.objects.new("sep_probe", None)
    bpy.context.scene.collection.objects.link(obj)

    node = obj.efx_fields.add()
    model.populate_node(node, "UVSPath", "placeholder")
    node.string_value = bad
    report.check("手填的反斜杠当场被改成正斜杠", node.string_value == good, node.string_value)

    # NULL -> STRING 的转正行为不能被这次改动带坏（同一个 update 回调）
    null_node = obj.efx_fields.add()
    model.populate_node(null_node, "MaybeNull", None)
    report.check("null 字段导入后仍是 NULL 节点", null_node.data_type == "NULL",
                 null_node.data_type)
    null_node.string_value = bad
    report.check("往 NULL 节点里打字仍会转正成 STRING，并且同样纠正分隔符",
                 null_node.data_type == "STRING" and null_node.string_value == good,
                 f"{null_node.data_type} / {null_node.string_value}")


def verify_unwritable_detection(report: Report) -> None:
    """导出前那句"这棵树写不回去"的警告（KNOWN_UPSTREAM_ISSUES #6）报得准不准。

    两个方向都要验：真的导不出去的要报，导得出去的**不能**报。只报不准的警告比没有更糟——
    用户会学会无视它，等真出事那次也一起无视了。

    不依赖语料：`bridge.new_attribute()` 直接问 vendor 要一个真实实例，比手搓字典可靠。

    material 字段（原 #7）不在这里测：那是 EfxBridge 自己的 JSON 多态配置缺口，已经在
    `MaterialPolymorphismResolver`（tools/EfxBridge/Program.cs）修掉了，`_unwritable_in_attribute()`
    里也删掉了对应分支——material 现在跟其他能正常读写的字段一样，不会走到这个检测器。
    """
    print("\n=== unwritable_constructs()（导出前警告）")
    scene_col = bpy.context.scene.collection

    def build(attr_type: str, mutate=None):
        entry = bridge.new_entry()
        attr = bridge.new_attribute(attr_type)
        if mutate is not None:
            mutate(attr)
        entry["Attributes"] = [attr]
        data = {"Header": {"Version": 5571972}, "Entries": [entry], "Actions": [],
                "Bones": [], "FieldParameterValues": [], "UvarGroups": [],
                "ExpressionParameters": [], "EffectGroups": []}
        return io_tree.build_root_from_efxfile(data, scene_col, f"probe_{attr_type}")

    # 完全无关的 attribute 不该被牵连
    col = build("Transform3D")
    report.check("普通 attribute 不误报", io_tree.unwritable_constructs(col) == [],
                 str(io_tree.unwritable_constructs(col)))


def _run_op(op, **kwargs):
    """调算子，返回 `(结果集合, 报错文案)`。后台模式下算子 `report({"ERROR"})` 会让
    `bpy.ops` 直接抛 RuntimeError（结果本身是 CANCELLED），这里把两种形态收成一种。"""
    try:
        return op(**kwargs), ""
    except RuntimeError as ex:
        return {"CANCELLED"}, str(ex)


def _verify_notation_clipboard(root, report: Report, copy_paste, clip_store: dict) -> None:
    expr_attr = next(
        o for o in bpy.data.objects
        if o.get("~TYPE") == model.TYPE_ATTRIBUTE
        and getattr(o, "efx_is_expression_attribute", False)
        and io_tree.find_root(o) is root)
    bpy.context.view_layer.objects.active = expr_attr
    report.check("从旧树复制带公式的对象被拒绝",
                 _run_op(bpy.ops.efx_re.object_copy)[0] == {"CANCELLED"})
    report.check("从旧树复制带公式的属性被拒绝",
                 _run_op(bpy.ops.efx_re.properties_copy)[0] == {"CANCELLED"})

    io_tree.stamp_expression_notation(root)
    report.check("新树里复制带公式的对象放行",
                 _run_op(bpy.ops.efx_re.object_copy)[0] == {"FINISHED"})
    payload = copy_paste._read_clipboard(copy_paste._CLIP_MARKER_OBJECT) or {}
    report.check("剪贴板里记了记法版本号",
                 payload.get("expr_notation") == io_tree.EXPR_NOTATION_VERSION, str(payload.keys()))

    # 旧版插件写进系统剪贴板的内容没有版本号
    clip_store.get(copy_paste._CLIP_MARKER_OBJECT, {}).pop("expr_notation", None)
    before = len(bpy.data.objects)
    report.check("没有版本号、带公式的剪贴板内容拒绝粘贴",
                 _run_op(bpy.ops.efx_re.object_paste)[0] == {"CANCELLED"}
                 and len(bpy.data.objects) == before)


def verify_expression_notation_guard(samples: list, workdir: pathlib.Path, report: Report) -> None:
    """旧 .blend（没有记法版本号）里的公式必须拒绝导出，见 io_tree 的"公式记法版本"一节。

    走的是用户真正点的算子（`efx_re.export` / `object_copy` / `object_paste` /
    `entry_preset_save` / `entry_preset_new`），不只是直接调校验函数——算子里漏接一次
    校验，直接调函数的测试照样全绿。
    """
    print("\n=== 公式记法版本（旧 .blend 拒绝导出）")
    from blender_efx_re import copy_paste, entry_presets

    scene_col = bpy.context.scene.collection
    root = data = None
    for orig in samples:
        src = workdir / ("notation_" + orig.name.replace(".orig", ""))
        shutil.copy(orig, src)
        candidate = bridge.dump_efx(src)
        if io_tree.dict_has_expressions(candidate):
            data = candidate
            root = io_tree.build_root_from_efxfile(data, scene_col, "notation_probe")
            break
    report.check("样本里有带公式的文件（否则这一节整体空跑）", root is not None)
    if root is None:
        return

    out_data = io_tree.export_root_to_efxfile(root)
    report.check("新导入的树带记法版本号", io_tree.has_current_expression_notation(root))
    try:
        io_tree.check_expression_notation(root, out_data)
        report.check("带版本号的树放行", True)
    except io_tree.ExpressionNotationError as ex:
        report.check("带版本号的树放行", False, str(ex))

    # 模拟旧 .blend：旧版插件建的树压根没有这个 ID 属性
    del root[io_tree.EXPR_NOTATION_KEY]
    try:
        io_tree.check_expression_notation(root, out_data)
        report.check("没有版本号、带公式的树被拒绝", False, "没有抛 ExpressionNotationError")
    except io_tree.ExpressionNotationError:
        report.check("没有版本号、带公式的树被拒绝", True)

    bpy.context.view_layer.objects.active = None
    bpy.context.scene.efx_re_active_root = root
    out = workdir / "notation_probe_refused.efx.5571972"
    result, message = _run_op(bpy.ops.efx_re.export, filepath=str(out))
    report.check("导出算子对旧树返回 CANCELLED、不写文件",
                 result == {"CANCELLED"} and not out.exists(), f"{result} exists={out.exists()}")
    report.check("拒绝时告诉用户重新导入",
                 io_tree.EXPR_NOTATION_STALE_MESSAGE in message, message)

    # 不带公式的旧树照常放行：只有公式受记法影响，不能因为没版本号就一刀切
    plain = io_tree.build_root_from_efxfile(
        {"Header": {"Version": 5571972}, "Entries": [bridge.new_entry()], "Actions": [],
         "Bones": [], "FieldParameterValues": [], "UvarGroups": [],
         "ExpressionParameters": [], "EffectGroups": []}, scene_col, "notation_plain")
    del plain[io_tree.EXPR_NOTATION_KEY]
    try:
        io_tree.check_expression_notation(plain, io_tree.export_root_to_efxfile(plain))
        report.check("没有版本号、但不带公式的树放行", True)
    except io_tree.ExpressionNotationError as ex:
        report.check("没有版本号、但不带公式的树放行", False, str(ex))

    # Copy/Paste：从旧树复制带公式的 attribute 必须被拦。
    # 后台模式没有系统剪贴板（`window_manager.clipboard` 读回来恒为空串），把模块里那两个
    # 读写函数换成内存里的一份；算子本身照常走，它们是运行时按模块属性查这两个函数的。
    clip_store = {}
    saved_read, saved_write = copy_paste._read_all, copy_paste._write_clipboard
    copy_paste._read_all = lambda: json.loads(json.dumps(clip_store))

    def _fake_write(marker, payload):
        clip_store[copy_paste._CLIP_MAGIC] = True
        clip_store[marker] = json.loads(json.dumps(payload))

    copy_paste._write_clipboard = _fake_write
    try:
        _verify_notation_clipboard(root, report, copy_paste, clip_store)
    finally:
        copy_paste._read_all, copy_paste._write_clipboard = saved_read, saved_write

    # Entry 预设：别碰用户配置目录里的真文件
    entry = next(o for o in io_tree.root_entries(root)
                 if io_tree.dict_has_expressions(io_tree.export_entry_object(o)))
    written = []
    saved_write, saved_cache = entry_presets._write_presets, entry_presets._cache
    entry_presets._write_presets = lambda presets: written.append(presets)
    try:
        del root[io_tree.EXPR_NOTATION_KEY]
        bpy.context.view_layer.objects.active = entry
        result, _msg = _run_op(bpy.ops.efx_re.entry_preset_save, preset_name="notation_probe")
        report.check("旧树里带公式的 Entry 不能存成预设",
                     result == {"CANCELLED"} and not written, f"{result} written={len(written)}")
        io_tree.stamp_expression_notation(root)

        entry_presets._cache = [{"name": "notation_old",
                                 "data": io_tree.export_entry_object(entry)}]
        bpy.context.window_manager.efx_re_entry_preset = "notation_old"
        before = len(io_tree.root_entries(root))
        result, _msg = _run_op(bpy.ops.efx_re.entry_preset_new)
        report.check("没有版本号、带公式的预设拒绝新建",
                     result == {"CANCELLED"} and len(io_tree.root_entries(root)) == before,
                     str(result))
    finally:
        entry_presets._write_presets, entry_presets._cache = saved_write, saved_cache


def _sample_dumps(samples: list, workdir: pathlib.Path, prefix: str) -> list[tuple[str, dict]]:
    out = []
    for orig in samples:
        src = workdir / (prefix + orig.name.replace(".orig", ""))
        shutil.copy(orig, src)
        out.append((orig.name.split(".efx.")[0], bridge.dump_efx(src)))
    return out


def _effect_groups(data: dict) -> list:
    return [(g.get("groupName"), list(g.get("efxEntryIndexes") or [])) for g in data.get("EffectGroups") or []]


def verify_effect_group_duplicates(samples: list, workdir: pathlib.Path, report: Report) -> None:
    """同名 EffectGroups（KNOWN_UPSTREAM_ISSUES.md #13）：vendor 写出时把同名组合并进第一个、
    其余清空，桥接层 PlanEffectGroups()/ApplyEffectGroupPlan() 按位置改回去。

    diag 样本里未必有真实的同名组，所以在带 EffectGroups 的样本上合成一个：把第 0 组原样复制
    一份插在它后面，成员 entry 的 Groups 里同名标签也多出一次（vendor 读文件时就是这么填的），
    走 Blender 建树 → 导出 → load → 读回，要求 EffectGroups 逐组（名字 + 成员顺序）不变。
    """
    print("\n=== EffectGroups 同名组")
    picked = None
    for stem, data in _sample_dumps(samples, workdir, "egdup_"):
        groups = data.get("EffectGroups") or []
        if groups and groups[0].get("efxEntryIndexes"):
            picked = (stem, data)
            break
    report.check("样本里有带成员的 EffectGroups（否则这一节整体空跑）", picked is not None)
    if picked is None:
        return
    stem, data = picked

    dup = json.loads(json.dumps(data["EffectGroups"][0]))
    data["EffectGroups"].insert(1, dup)
    for index in dup["efxEntryIndexes"]:
        data["Entries"][index].setdefault("Groups", []).append(dup["groupName"])
    want = _effect_groups(data)

    root = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, "egdup_probe")
    out_path = workdir / f"{stem}_egdup.efx.5571972"
    try:
        bridge.load_efx(io_tree.export_root_to_efxfile(root), out_path)
        got = _effect_groups(bridge.dump_efx(out_path))
    except bridge.BridgeError as ex:
        report.check(f"{stem}: 合成同名组 '{dup['groupName']}' 后能导出", False, str(ex)[:400])
        return
    report.check(f"{stem}: 合成同名组 '{dup['groupName']}' 后能导出", True)
    report.check(f"{stem}: 同名组逐组保住（名字 + 成员顺序，{len(want)} 组）", got == want,
                 f"期望 {want[:3]}\n           实际 {got[:3]}")


def verify_name_hash_drift(samples: list, workdir: pathlib.Path, report: Report) -> None:
    """导入时 nameHash 和名字对不上的 Entry/Action（io_tree.name_hash_drift()）。

    1. 官方样本一个都不能报（官方文件里两者永远一致，报了就是误报）；
    2. 模拟"别的工具只改了名字"：改 name 不改 nameHash，要报出来、反查出原名；
    3. 导出字典的 nameHash 按当前名字现算；
    4. restore_hashed_name 算子改回原名后不再报；
    5. 在 Blender 里改名 → 导出字典 → 再建树（复制/粘贴、预设走的就是这条）不能误报。
    """
    print("\n=== nameHash 与名字对不上")
    from blender_efx_re import name_hash

    scene_col = bpy.context.scene.collection
    dumps = _sample_dumps(samples, workdir, "namehash_")
    false_hits = []
    for stem, data in dumps:
        root = io_tree.build_root_from_efxfile(data, scene_col, f"namehash_clean_{stem}")
        false_hits += [f"{stem}:{obj.efx_name}" for obj, _h, _k in io_tree.name_hash_drift(root)]
    report.check(f"官方样本无误报（{len(dumps)} 个样本）", not false_hits, ", ".join(false_hits[:5]))

    stem, data = next(((s, d) for s, d in dumps if d.get("Actions") and d.get("Entries")), (None, None))
    report.check("样本里有同时带 Entry 和 Action 的文件（否则这一节整体空跑）", data is not None)
    if data is None:
        return

    tampered = json.loads(json.dumps(data))
    originals = {}
    for kind in ("Entries", "Actions"):
        item = tampered[kind][0]
        originals[kind] = item["name"]
        item["name"] = f"renamed_by_other_tool_{kind}"  # nameHash 原样不动
    root = io_tree.build_root_from_efxfile(tampered, scene_col, "namehash_tampered")
    drift = {obj.efx_name: known for obj, _h, known in io_tree.name_hash_drift(root)}
    for kind, orig_name in originals.items():
        name = f"renamed_by_other_tool_{kind}"
        report.check(f"{stem}: {kind}[0] 被报出、反查出原名 '{orig_name}'", drift.get(name) == orig_name,
                     f"drift = {drift}")

    # 面板那段警告框：无头模式建不出真的 UILayout，用一个什么调用都接、只记下文字的替身把
    # panels._draw_name_row() 真跑一遍（i18n 键写错、format 占位符对不上这类错只有执行到才炸）。
    from blender_efx_re import panels

    class _FakeLayout:
        def __init__(self, texts: list):
            self.texts = texts

        def __getattr__(self, _name):
            def call(*_args, **kwargs):
                if "text" in kwargs:
                    self.texts.append(kwargs["text"])
                return self
            return call

    texts: list = []
    panels._draw_name_row(_FakeLayout(texts), io_tree.root_actions(root)[0])
    report.check(f"{stem}: 面板警告框画出原哈希和改名按钮",
                 any(str(io_tree.root_actions(root)[0].efx_orig_name_hash) in t for t in texts)
                 and any(originals["Actions"] in t for t in texts), str(texts))

    out = io_tree.export_root_to_efxfile(root)
    hashes_ok = all(item["nameHash"] == name_hash.utf8_hash(item["name"] or "")
                    for kind in ("Entries", "Actions") for item in out[kind])
    report.check(f"{stem}: 导出字典的 nameHash 按当前名字现算", hashes_ok)

    targets = [io_tree.root_entries(root)[0], io_tree.root_actions(root)[0]]
    for obj in targets:
        with bpy.context.temp_override(object=obj, active_object=obj):
            result, message = _run_op(bpy.ops.efx_re.restore_hashed_name)
        report.check(f"{stem}: restore_hashed_name 改回 '{obj.efx_name}'", result == {"FINISHED"}, message)
    report.check(f"{stem}: 改回原名后不再报", not io_tree.name_hash_drift(root),
                 str(io_tree.name_hash_drift(root)))

    clean = io_tree.build_root_from_efxfile(data, scene_col, "namehash_renamed")
    io_tree.root_entries(clean)[0].efx_name = "renamed_in_blender"
    io_tree.root_actions(clean)[0].efx_name = "renamed_in_blender"
    rebuilt = io_tree.build_root_from_efxfile(io_tree.export_root_to_efxfile(clean), scene_col, "namehash_rebuilt")
    report.check(f"{stem}: Blender 里改名后再建树不误报", not io_tree.name_hash_drift(rebuilt),
                 str([(o.efx_name, h) for o, h, _k in io_tree.name_hash_drift(rebuilt)]))


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
    verify_path_separators(report)
    verify_unwritable_detection(report)
    verify_version_suffix(report)
    verify_expression_notation_guard(samples, workdir, report)
    verify_effect_group_duplicates(samples, workdir, report)
    verify_name_hash_drift(samples, workdir, report)

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
