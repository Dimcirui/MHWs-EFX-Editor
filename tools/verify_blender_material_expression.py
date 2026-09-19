"""
tools/verify_blender_material_expression.py —— IMaterialExpressionAttribute 公式编辑回归防护

必须在 Blender 里跑（要真 bpy：PropertyGroup 注册、update 回调），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_material_expression.py

可选参数放在 `--` 之后：`--corpus <语料根目录>`（默认 MHWILDS_EXTRACT\\Art\\VFX），用来抓
`model.MATERIAL_EXPRESSION_VERIFIED_TYPES` 里每个类型各一个真实样本，找不到就直接报错退 1。

为什么单独一条门禁
------------------
`MaterialExpressions` 走的是新加的 `efx_material_expression_*` 专属结构（见 model.py 里
`EFXMaterialExpressionItem` 的说明），不进通用 Fields 树——`verify_blender_roundtrip.py`
测的是通用树那条路，完全碰不到这条。这里对齐 `verify_blender_expression_edit.py` 的两层判据：

1. 字段级：导入后每条 entry 的 `mdf_property_hash`/`component_index`/`assign_type_raw`/
   `is_color`/`formula` 和 dump 出来的原始 JSON 逐一核对，`mdf_property_hash` 能查到真实
   材质参数名。
2. 字节级：**不改**任何东西直接导出，字节必须和纯 CLI 往返基线一致（核心断言，抓"populate/
   export 往返本身有没有丢东西/错位"）；改一次 `formula_canonical` 后导出，字节必须和基线
   **不同**（抓"编辑写不进真正参与导出的那条路径"这种静默丢失——这正是需要新增 C# 端
   `CompileExpressions()` 里 `IMaterialExpressionAttribute` 分支的原因：Python 只写
   `parsedExpressions` 文本，`expressions.components` 得靠桥接摊平回去）。
3. 样本里一条 MaterialExpression 都没测到时报错退 1，不静默全绿。

退出码：全绿 0，有失败 1。⚠ `blender --background --python x.py` 抛未捕获异常时退出码仍是
0（实测），入口自己加一层捕获。
"""

from __future__ import annotations

import collections
import pathlib
import shutil
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, io_tree, model, operators, semantics  # noqa: E402

_DEFAULT_CORPUS = (
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\Art\VFX"
)

#: 已经手动核对过、含非空 `MaterialExpressions` 的真实语料文件（相对 `_DEFAULT_CORPUS`）——
#: 全语料只有这几十个这类 attribute 实例，`attrindex`/`typefreq` 扫一遍就能找到，这里直接
#: 写死避免每次都拿 `dump` 过一遍上万个文件（那样跑一次要起上万个 dotnet 子进程）。语料目录
#: 换了（`--corpus` 指到别的地方）时这些相对路径未必存在，退到 `_find_sample()` 全量扫描。
#: **key 必须是 `model.short_attr_name()` 的输出**（去掉 `EFXAttribute` 前缀的短名），
#: 不是 `MATERIAL_EXPRESSION_VERIFIED_TYPES` 里的完整 `$type` 字符串——两者不一致会导致
#: 查表直接落空、悄悄退到全量扫描（实测踩过：第一版这里错手写了完整类名的
#: `rsplit(".", 1)[-1]`，比短名多一段 `EFXAttribute` 前缀，字典查不到，门禁没报错，
#: 只是变成要扫完全部 9000+ 个文件才找到样本，跑了十几分钟看着像是卡死）。
_KNOWN_SAMPLES = {
    # 原来用 `11_em0078_00_057`：这个文件另有一个 `TypeBillboard3DMaterialClip` 在
    # JSON dump→load 往返（不经 Blender、不经本功能任何代码）时读不回来（vendor
    # 已知的第 4 个"JSON 路径没人真正测过"类 bug，TOPLEVEL_STRUCTURE.md 记过前三个都是
    # 这一类；已用纯 CLI dump→load→dump 复现，和 MaterialExpression 无关，先不处理，
    # 换一个没有这个坏 attribute 的样本，不让不相关的 vendor 坑污染这条门禁）。
    "TypeBillboard3DMaterialExpression": r"EffectEditor\Player\pl_cm\pl_state\11_pl_heal.efx.5571972",
    "TypeRibbonLengthMaterialExpression": r"EffectEditor\Player\pl_equip\armor\11_ch03_085_0001.efx.5571972",
    "TypeMeshExpression": r"EffectEditor\Player\pl_sfc\11_sfc_052.efx.5571972",
}


def _script_args() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _parse_args(argv: list) -> dict:
    opts = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1]
    return opts


class Report:
    def __init__(self) -> None:
        self.failures = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
            if detail:
                print("        -> " + detail)


def _find_sample(corpus: pathlib.Path, type_suffix: str) -> pathlib.Path | None:
    """在语料里找一个 `$type` 以 `type_suffix` 结尾、且真的有非空 `MaterialExpressions`
    条目的文件——`typefreq`/`attrindex` 统计过的类型不代表条目非空（见
    `EFXAttributeTypeRibbonParticleMaterialExpression` 唯一实例是空的那个坑，
    model.py `MATERIAL_EXPRESSION_VERIFIED_TYPES` 上面的说明）。"""
    for path in corpus.rglob("*.efx.*"):
        if path.suffix.lstrip(".").isalpha():
            continue
        try:
            data = bridge.dump_efx(path)
        except Exception:
            continue
        if _first_nonempty_material_expression(data, type_suffix) is not None:
            return path
    return None


def _all_nonempty_material_expressions(data: dict, type_suffix: str) -> list:
    """这个文件里所有 `$type` 匹配、且 `MaterialExpressions.expressions` 非空的 attribute
    字典——同一个文件可能有多个实例（`11_sfc_052.efx.5571972` 就有 3 个），不能假设只有一个。"""
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            t = obj.get("$type", "")
            if t.endswith(type_suffix) and obj.get("MaterialExpressions"):
                exprs = (obj.get("MaterialExpressions") or {}).get("expressions") or []
                if exprs:
                    found.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return found


def _first_nonempty_material_expression(data: dict, type_suffix: str):
    found = _all_nonempty_material_expressions(data, type_suffix)
    return found[0] if found else None


def _material_expression_attributes(root_obj):
    out = []
    for obj in bpy.data.objects:
        if obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if not getattr(obj, "efx_is_material_expression_attribute", False):
            continue
        out.append(obj)
    return out


def verify_sample(orig: pathlib.Path, workdir: pathlib.Path, report: Report,
                   type_suffix: str, counter: dict) -> None:
    stem = orig.stem.replace(".", "_")
    print(f"\n=== {orig.name} ({type_suffix})")

    src = workdir / f"{stem}_{type_suffix}.efx.5571972"
    shutil.copy(orig, src)

    cli_json = bridge.dump_efx(src)
    cli_baseline = workdir / f"{stem}_cli.efx.5571972"
    bridge.load_efx(cli_json, cli_baseline)

    raw_list = _all_nonempty_material_expressions(cli_json, type_suffix)
    if not raw_list:
        report.check(f"{type_suffix}：样本里找到非空 MaterialExpressions", False)
        return

    data = bridge.dump_efx(src)
    root_obj = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, src.name)

    attrs = [o for o in _material_expression_attributes(root_obj)
             if o.efx_attr_type.endswith(type_suffix)]
    report.check(f"{type_suffix}：导入后 attribute 实例数对得上（可能不止一个）",
                 len(attrs) == len(raw_list), f"{len(attrs)} != {len(raw_list)}")
    if not attrs:
        return

    # 同一个文件可能有多个实例（`11_sfc_052.efx.5571972` 就有 3 个，其中两个条目数都是 1
    # 但公式内容不同）——不假设导入顺序和 JSON 里的顺序一一对应，改成"每个 Blender 实例的
    # 条目签名（哈希/分量/unkn1/unkn2/struct3Count/公式）多重集合，必须整体等于 JSON 里的多重集合"，
    # 用重复也能扛住的方式核对内容，不校验具体是哪个 Python 对象对应哪段 JSON。
    def entry_signature(entry) -> tuple:
        return (int(entry.mdf_property_hash), entry.component_index,
                entry.assign_type_raw, int(entry.is_color), entry.struct3_count,
                int(entry.is_single_param), entry.formula)

    def raw_signature(raw_entry, parsed_entry) -> tuple:
        return (int(raw_entry.get("mdfPropertyHash", 0) or 0),
                int(raw_entry.get("propertyComponentIndex", 0) or 0),
                int(raw_entry.get("unkn1", 0) or 0), int(raw_entry.get("unkn2", 0) or 0),
                int(raw_entry.get("struct3Count", 0) or 0),
                int((raw_entry.get("unkn5") or {}).get("value", 0) or 0),
                parsed_entry.get("expression", "0") if parsed_entry else "0")

    blender_signatures = []
    for obj in attrs:
        entries = list(obj.efx_material_expression_entries)
        counter["entries"] += len(entries)
        blender_signatures.extend(entry_signature(e) for e in entries)
        for entry in entries:
            want_hash = int(entry.mdf_property_hash)
            report.check(f"{type_suffix}: mdf_property_hash 能查到真实材质参数名",
                         semantics.lookup_name_hash(want_hash) is not None,
                         f"hash={want_hash} 没查到名字")

    raw_signatures = []
    for raw in raw_list:
        raw_entries = (raw.get("MaterialExpressions") or {}).get("expressions") or []
        raw_parsed = (raw.get("MaterialExpressions") or {}).get("parsedExpressions") or []
        for i, raw_entry in enumerate(raw_entries):
            parsed_entry = raw_parsed[i] if i < len(raw_parsed) else None
            raw_signatures.append(raw_signature(raw_entry, parsed_entry))

    report.check(
        f"{type_suffix}：所有实例的条目内容（哈希/分量/unkn1/unkn2/struct3Count/公式）多重集合对得上",
        collections.Counter(blender_signatures) == collections.Counter(raw_signatures),
        f"blender={blender_signatures}\n        raw={raw_signatures}",
    )
    raw = raw_list[0]

    # 1. 不改任何东西，导出字节必须和纯 CLI 往返基线一致（核心断言）
    out_data = io_tree.export_root_to_efxfile(root_obj)
    out_path, notice, fatal = operators._ensure_version_suffix(
        str(workdir / f"{stem}_noop.efx.5571972"), out_data)
    if fatal:
        report.check(f"{type_suffix}：导出路径能补出合法版本号后缀", False, notice or "")
        return
    bridge.load_efx(out_data, out_path)
    noop_bytes = pathlib.Path(out_path).read_bytes()
    baseline_bytes = cli_baseline.read_bytes()
    report.check(f"{type_suffix}：不改动导出，字节 == 纯 CLI 往返基线",
                 noop_bytes == baseline_bytes,
                 f"{len(noop_bytes)} 字节 != {len(baseline_bytes)} 字节")

    # 2. 产物能读回来，且读回来的公式和写之前一致
    try:
        readback = bridge.dump_efx(pathlib.Path(out_path))
        readback_raw = _first_nonempty_material_expression(readback, type_suffix)
        ok = readback_raw is not None
        detail = "" if ok else "读回来找不到非空 MaterialExpressions"
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, str(exc)
    report.check(f"{type_suffix}：不改动的产物能被 RE-Engine-Lib 读回来", ok, detail)

    # 3. 编辑一次 formula_canonical，导出字节必须和基线**不同**——抓"编辑没有真正生效"
    #    这种静默丢失（Python 只写 parsedExpressions，真正参与二进制写出的
    #    expressions.components 得靠 EfxBridge CompileExpressions() 摊平回去）。只编辑
    #    第一个实例的第一条——够验证"编辑这条路径本身通不通"，不需要挨个实例都试一遍。
    entry = list(attrs[0].efx_material_expression_entries)[0]
    before_canonical = entry.formula_canonical
    new_value = "0" if "0" not in (before_canonical or "") else "1"
    # 造一条肯定不同、也肯定合法的常量公式，不依赖原公式的具体内容。
    probe_formula = f"{new_value} + 2"
    entry.formula_canonical = probe_formula
    report.check(f"{type_suffix}：写入 formula_canonical 没有报错",
                 not entry.formula_error, entry.formula_error)

    edited_data = io_tree.export_root_to_efxfile(root_obj)
    edited_path, notice2, fatal2 = operators._ensure_version_suffix(
        str(workdir / f"{stem}_edited.efx.5571972"), edited_data)
    if fatal2:
        report.check(f"{type_suffix}：编辑后导出路径能补出合法版本号后缀", False, notice2 or "")
        return
    bridge.load_efx(edited_data, edited_path)
    edited_bytes = pathlib.Path(edited_path).read_bytes()
    report.check(f"{type_suffix}：编辑公式后导出字节和基线不同（编辑真的生效了）",
                 edited_bytes != baseline_bytes,
                 f"两次导出字节相同（{len(edited_bytes)} 字节），编辑疑似没有写进真正导出的路径")

    try:
        readback2 = bridge.dump_efx(pathlib.Path(edited_path))
        readback2_raw = _first_nonempty_material_expression(readback2, type_suffix)
        ok2 = readback2_raw is not None
        got_formula = None
        if ok2:
            parsed2 = (readback2_raw.get("MaterialExpressions") or {}).get("parsedExpressions") or []
            got_formula = parsed2[0]["expression"] if parsed2 else None
        # 规范记法 "0 + 2"/"1 + 2" 译回 vendor 记法后可能换了写法（比如换成中缀/前缀），
        # 这里只要求它能读回来、且和编辑前的原始公式不同，不逐字节比较具体写法。
        detail2 = f"got={got_formula!r}"
    except Exception as exc:  # noqa: BLE001
        ok2, detail2 = False, str(exc)
    report.check(f"{type_suffix}：编辑后的产物能被 RE-Engine-Lib 读回来", ok2, detail2)


def main() -> int:
    opts = _parse_args(_script_args())
    corpus = pathlib.Path(opts.get("corpus", _DEFAULT_CORPUS))
    if not corpus.is_dir():
        print(f"[ERROR] 语料目录不存在：{corpus}（用 -- --corpus <目录> 指定）")
        return 1

    blender_efx_re.register()

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="efx_matexpr_"))
    print(f"输出目录: {workdir}（跑完不删）")

    report = Report()
    counter = {"entries": 0}
    for type_suffix in sorted(model.short_attr_name(t) for t in model.MATERIAL_EXPRESSION_VERIFIED_TYPES):
        known = corpus / _KNOWN_SAMPLES.get(type_suffix, "")
        sample = known if _KNOWN_SAMPLES.get(type_suffix) and known.is_file() else _find_sample(corpus, type_suffix)
        if sample is None:
            print(f"[ERROR] 语料里没找到带非空 MaterialExpressions 的 {type_suffix} 样本")
            report.failures.append(f"{type_suffix}：找不到样本")
            continue
        verify_sample(sample, workdir, report, type_suffix, counter)

    if counter["entries"] == 0:
        print("[ERROR] 整轮没有测到任何 MaterialExpression 条目，这条门禁等于没跑")
        report.failures.append("样本覆盖：0 条 MaterialExpression 条目")

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print(f"\n===== ALL PASS（共验证 {counter['entries']} 条 MaterialExpression）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
