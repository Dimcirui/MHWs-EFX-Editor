# -*- coding: utf-8 -*-
"""
tools/scan_version_excluded_fields.py —— 扫出"版本条件对 MHWilds 恒 False"的字段

    python tools/scan_version_excluded_fields.py

解析 vendor `EFX/*.cs` 里每个字段的 `RszVersion`/`RszVersionExact` 条件，还原
`REE-Lib.Generators/ReeLibGenerator.cs` 的拼接规则（单参数 → `Version >= X`；双参数
比较符 → `Version 运算符 X`；`RszVersionExact` → 多个 `== X` 用 `||` 连；同一字段身上或
被外层 `EndAt` 范围罩住的多个条件按生成器的嵌套 if 语义用 `&&` 连），代入
`Version = EfxVersion.MHWilds` 求值。条件恒为 False 的字段 = 读写代码里那个 `if` 分支对
MHWilds 文件永远进不去，字段值只可能是 C# 默认值——不是语料统计巧合，是结构性证据。

同一个 `EfxAttributeType` 有时有多个版本专属实现类（`TypeGpuMeshTrail` 的 V1/V2、
`TypeStrainRibbon` 的 V1/V2/V3……），必须用 `mhws_attribute_types.json`
（`EfxBridge types` 实际按 MHWilds 解析出来的类名）核对候选字段所在的类是不是 MHWilds
真正用的那个——本脚本天然会把同一枚举名下所有历史实现类的字段都收进候选，靠这一步筛掉
"属于旧类、MHWilds 根本不用这个类"的假阳性。

产出 `version_excluded_fields_report.json`（写在本脚本同目录，不进版本控制）：
`verified`（可以直接抄进 `field_visibility.VERSION_EXCLUDED_FIELDS` 的最终名单，按完整
类名分组）、`wrong_class`（假阳性，字段所在类不是 MHWilds 实际解析出来的类）、
`parse_failures`（条件文本没解析出来，需要人工看一眼源码）。

**vendor 升级后要重跑**（CLAUDE.md 铁律 #5 同一个理由：字段的版本条件、类版本映射都可能变）。
跑之前先 `dotnet build tools/EfxBridge -p:LangVersion=preview` 生成新的
`blender_efx_re/semantics/mhws_attribute_types.json`（`EfxBridge types <路径>`）。
"""
import os
import re
import json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EFX_DIR = os.path.join(REPO, "vendor", "RE-Engine-Lib", "REE-Lib", "OtherFiles", "EFX")
SCHEMA_PATH = os.path.join(REPO, "blender_efx_re", "semantics", "mhws_attribute_types.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "version_excluded_fields_report.json")

EFX_VERSION = {
    "Unknown": 0, "RE7": 1179750, "RE2": 1769669, "DMC5": 1769672, "RE3": 2228526,
    "MHRise": 2621987, "RE8": 2621998, "RERT": 2818689, "MHRiseSB": 2818730,
    "SF6": 3474371, "RE4": 3539837, "DD2": 4064419, "MHWilds": 5571972,
    "RE9": 5899767, "Pragmata": 5965300, "OniWS": 5834247, "DD2New": 5965310,
}
TARGET_VERSION = EFX_VERSION["MHWilds"]

FIELD_RE = re.compile(
    r"((?:\[(?:[^\[\]])*\]\s*)*)"          # 前置注解簇（不支持嵌套方括号，本代码库不需要）
    r"public\s+(?!partial\b|class\b)"
    r"[\w\.\?<>\[\],]+\s+(\w+)\s*(?:=[^;]*)?;"
)
RSZVER_RE = re.compile(r"(RszVersion|RszVersionExact)\s*\(((?:[^()]|\([^()]*\))*)\)")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _find_classes(text: str):
    """yield (attr_type_name, class_name, body_text)，只挑 EFXAttribute 派生、
    带 EfxStruct(EfxAttributeType.X, ...) 的类。"""
    for m in re.finditer(
        r"\[([^\]]*?EfxStruct\(EfxAttributeType\.(\w+)[^\]]*?)\]\s*"
        r"public\s+partial\s+class\s+(\w+)\s*:\s*EFXAttribute\b[^{]*\{",
        text,
    ):
        attr_type, class_name, start = m.group(2), m.group(3), m.end() - 1
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield attr_type, class_name, text[start:i + 1]


def _split_args(argtext: str) -> list[str]:
    """按顶层逗号切参数，尊重 nameof(...) 括号。"""
    args, depth, cur = [], 0, ""
    for ch in argtext:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def _eval_condition(cond_text: str, version_val: int):
    py = re.sub(r"EfxVersion\.(\w+)", lambda m: str(EFX_VERSION[m.group(1)]), cond_text)
    py = py.replace("Version", str(version_val)).replace("&&", " and ").replace("||", " or ")
    try:
        return bool(eval(py, {"__builtins__": {}}, {}))
    except Exception:
        return None  # 解析失败，人工复核


def _parse_condition(attr_name: str, argtext: str):
    """还原生成器逻辑（ReeLibGenerator.cs HandleMember）：
    join(' ', positional) 再按 argCount 套模板；EndAt 单独摘出来。"""
    positional, endat = [], None
    for a in _split_args(argtext):
        m = re.match(r"EndAt\s*=\s*nameof\(\s*(\w+)\s*\)", a)
        if m:
            endat = m.group(1)
        else:
            positional.append(a)

    def norm(tok: str) -> str:
        tok = tok.strip()
        m = re.match(r"nameof\(\s*(\w+)\s*\)", tok)
        if m:
            return m.group(1)
        m2 = re.match(r"^['\"](.+)['\"]$", tok)
        return m2.group(1) if m2 else tok

    toks = [norm(a) for a in positional]
    joined = " ".join(toks)

    if attr_name == "RszVersion":
        if len(toks) == 1:
            cond = f"Version >= {toks[0]}"
        elif len(toks) == 2 and re.match(r"^(<|>|=|!)", joined):
            cond = f"Version {joined}"
        else:
            cond = joined
    else:  # RszVersionExact
        cond = " || ".join(f"Version == {t}" for t in toks)
    return cond, endat


def _analyze_class(body: str):
    """返回 [(field_name, combined_condition_text, satisfied_for_mhwilds_or_None)]，
    只含身上（或被外层 EndAt 范围罩住）带版本条件的字段。"""
    results = []
    open_conditions: list[tuple[str, str]] = []  # (cond_text, endat_field_name)
    for m in FIELD_RE.finditer(body):
        attrs_blob, field_name = m.group(1), m.group(2)
        for am in RSZVER_RE.finditer(attrs_blob):
            cond, endat = _parse_condition(am.group(1), am.group(2))
            open_conditions.append((cond, endat or field_name))
        if open_conditions:
            combined = " and ".join(f"({c})" for c, _ in open_conditions)
            results.append((field_name, combined, _eval_condition(combined, TARGET_VERSION)))
        open_conditions = [(c, e) for c, e in open_conditions if e != field_name]
    return results


def scan_source() -> tuple[dict, list]:
    """全量扫描，返回 (按 EfxAttributeType 短名分组的候选 {field, class, file, condition}, 解析失败列表)。"""
    candidates: dict[str, list[dict]] = {}
    parse_failures = []
    for fname in sorted(os.listdir(EFX_DIR)):
        if not fname.endswith(".cs"):
            continue
        text = _strip_comments(open(os.path.join(EFX_DIR, fname), encoding="utf-8").read())
        for attr_type, class_name, body in _find_classes(text):
            for field_name, cond, ok in _analyze_class(body):
                if ok is None:
                    parse_failures.append({
                        "file": fname, "attrType": attr_type, "class": class_name,
                        "field": field_name, "condition": cond,
                    })
                elif ok is False:
                    candidates.setdefault(attr_type, []).append({
                        "field": field_name, "class": class_name, "file": fname, "condition": cond,
                    })
    return candidates, parse_failures


def cross_check(candidates: dict) -> tuple[dict, list]:
    """用 mhws_attribute_types.json 核对候选字段所在类是不是 MHWilds 实际解析出来的类，
    返回 (verified：{完整类名: [(field, condition)]}，wrong_class：假阳性列表)。"""
    schema = json.load(open(SCHEMA_PATH, encoding="utf-8"))
    type_by_name = {item["name"]: item for item in schema["types"] if isinstance(item, dict)}

    verified: dict[str, list] = {}
    wrong_class = []
    for attr_type, fields in candidates.items():
        entry = type_by_name.get(attr_type)
        if entry is None:
            for f in fields:
                wrong_class.append({**f, "attrType": attr_type, "reason": "attrType 不在 schema 里"})
            continue
        actual_class = entry["type"].rsplit(".", 1)[-1]
        actual_fields = set(entry["fields"])
        for f in fields:
            if f["class"] != actual_class:
                wrong_class.append({
                    **f, "attrType": attr_type,
                    "reason": f"scanner 类={f['class']!r}，MHWilds 实际用的类={actual_class!r}",
                })
            elif f["field"] not in actual_fields:
                wrong_class.append({**f, "attrType": attr_type, "reason": "类对得上但字段不在 schema fields 里，蹊跷"})
            else:
                verified.setdefault(entry["type"], []).append((f["field"], f["condition"]))
    return verified, wrong_class


def main() -> None:
    candidates, parse_failures = scan_source()
    verified, wrong_class = cross_check(candidates)

    total_fields = sum(len(v) for v in verified.values())
    print(f"=== 通过核对的版本性排除字段（{total_fields} 个，{len(verified)} 种类型）===\n")
    for full_type in sorted(verified):
        print(f"[{full_type}]")
        for field, cond in verified[full_type]:
            print(f"  {field:30s} {cond}")

    if wrong_class:
        print(f"\n=== 假阳性，类对不上被剔除（{len(wrong_class)} 条）===")
        for w in wrong_class:
            print(f"  {w['attrType']}.{w['field']}: {w['reason']}")

    if parse_failures:
        print(f"\n=== 解析失败，需人工复核（{len(parse_failures)} 条）===")
        for pf in parse_failures:
            print(f"  {pf['attrType']}.{pf['field']}  条件文本: {pf['condition']!r}  ({pf['file']})")

    json.dump(
        {
            "verified": {k: [{"field": f, "condition": c} for f, c in v] for k, v in verified.items()},
            "wrong_class": wrong_class,
            "parse_failures": parse_failures,
        },
        open(OUT_PATH, "w", encoding="utf-8"),
        ensure_ascii=False, indent=2,
    )
    print(f"\n写入 {OUT_PATH}")


if __name__ == "__main__":
    main()
