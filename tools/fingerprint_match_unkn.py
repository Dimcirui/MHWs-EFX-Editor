#!/usr/bin/env python3
"""
tools/fingerprint_match_unkn.py —— 给全是 unkn/ukn 占位名的 attribute 结构体，用真实语料的
取值分布指纹去对齐 010 Editor 模板（RE_EFX_STRUCTS.btx）里已经起了名字/写了注释的字段。

背景：C# 侧（REE-Lib）和模板是两条独立的逆向路线，字段名对不上、字段数量也不一定对得上
（见 semantics/__init__.py 和 mine_btx_semantics.py 的说明——按声明顺序整体对齐已经证实会
张冠李戴）。但两边各自都对同一批真实游戏语料做过统计：模板作者把 `//Values:[...]` 直接写
进了 .btx；我们自己可以用 `EfxBridge fieldstats` 对同一批语料做同样的统计。如果 C# 侧某个
`unknN` 字段的实测取值分布和模板某个具名字段的 `//Values:` 高度重合（尤其是不那么常见的
"特征值"，比如 π 的整数分之一、2 的幂次组合），那这俩大概率是同一个物理字段——不需要靠
名字或声明顺序，也不需要打开 010 Editor GUI。

**局部对齐，不是整体对齐**：脚本按贪心最大权匹配在结构体内部找对应，允许错位（两边字段
数量不一致时很常见），但不假设"第 i 个 = 第 i 个"。全 0 或全常量的字段信息量太低，权重
被打压，避免把一堆"平时不用、恒为 0"的字段互相乱配。

产出仅供人工复核，不直接写入 mhws_field_labels.json——这是它和 mine_btx_semantics.py
的分工区别：后者是确定性规则（同名才收），这个脚本是概率性证据，需要人看一眼取值是否真的
"长得像"再决定要不要采纳。

用法：
    python tools/fingerprint_match_unkn.py <RE_EFX_STRUCTS.btx 路径> <语料目录> \
        <EfxBridge.dll 路径> [--min-unkn-ratio 0.5] [--out report.json] [结构体名 ...]

    不给结构体名时，自动扫描 efx_types.json（先用 EfxBridge types 生成）里 unkn/ukn 占比
    达标的全部结构体。
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

BOOKKEEPING = {"IsTypeAttribute", "type", "UniqueID", "Version"}
UNKN_RE = re.compile(r'^(unkn|ukn|null)\d*(_\d+)?$', re.I)
COMMENT_RE = re.compile(r'comment\s*=\s*"([^"]*)"')
VALUES_RE = re.compile(r'//\s*Values:\s*(\[[^\]]*\])')
FIELD_RE = re.compile(r'^\s*([A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(<[^>]*>)?\s*;')

# 匹配 fieldstats 里 top 值字符串（"3.1415927"/"128"/"0.0"）转 float 时的容差
ROUND_NDIGITS = 4
TRIVIAL_VALUES = {0.0}  # 单独出现时信息量太低，不足以支撑匹配


def parse_btx_ordered(path: pathlib.Path) -> dict[str, list[dict]]:
    """{结构体名: [{"name", "type", "comment", "values": set[float] | None}, ...]}，保持物理顺序。"""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: dict[str, list[dict]] = {}
    i = 0
    while i < len(lines):
        if not re.match(r'^\s*typedef\s+struct\b', lines[i]):
            i += 1
            continue
        depth = 0
        started = False
        j = i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if "{" in lines[j]:
                started = True
            if started and depth == 0:
                break
            j += 1
        end = lines[j] if j < len(lines) else ""
        m = re.match(r'^\s*\}\s*(\w+)', end)
        if not m:
            i = j + 1
            continue

        ordered: list[dict] = []
        for ln in lines[i:j]:
            stripped = ln.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("local "):
                continue
            if re.match(r'^\s*(if|else|while|for)\b', stripped):
                continue
            fm = FIELD_RE.match(ln)
            if not fm:
                continue
            ftype, fname = fm.group(1), fm.group(2)
            if fname in ("itemType", "currentAttributeIndex"):
                continue
            values = None
            vm = VALUES_RE.search(ln)
            if vm:
                try:
                    raw = json.loads(vm.group(1))
                    values = {round(float(v), ROUND_NDIGITS) for v in raw if isinstance(v, (int, float))}
                except (ValueError, TypeError):
                    values = None
            comment = None
            cm = COMMENT_RE.search(fm.group(4) or "")
            if cm:
                comment = cm.group(1).strip()
            ordered.append({"name": fname, "type": ftype, "comment": comment, "values": values})
        out[m.group(1)] = ordered
        i = j + 1
    return out


def parse_top_values(top: dict) -> set[float]:
    vals = set()
    for k in top:
        try:
            vals.add(round(float(k), ROUND_NDIGITS))
        except (ValueError, TypeError):
            continue
    return vals


def jaccard_nontrivial(a: set[float], b: set[float]) -> float:
    a2 = a - TRIVIAL_VALUES
    b2 = b - TRIVIAL_VALUES
    if not a2 or not b2:
        return 0.0
    inter = len(a2 & b2)
    union = len(a2 | b2)
    if union == 0:
        return 0.0
    return inter / union


def run_fieldstats(dll: pathlib.Path, corpus: pathlib.Path, struct_name: str) -> dict | None:
    with tempfile.TemporaryDirectory() as td:
        out_path = pathlib.Path(td) / "stats.json"
        proc = subprocess.run(
            ["dotnet", str(dll), "fieldstats", str(corpus), struct_name, str(out_path), "80"],
            capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace",
        )
        if not out_path.exists():
            print(f"  [跳过] {struct_name}: fieldstats 没产出（{proc.stdout.strip()[-200:]}）", file=sys.stderr)
            return None
        return json.loads(out_path.read_text(encoding="utf-8"))


ANCHOR_MIN_SCORE = 0.15
MAX_OFFSET_SPAN = 6  # 锚点和待推断字段之间隔太远，本地 offset 不一定还成立，超过就不推断


def match_struct(struct_name: str, csharp_fields: list[str], btx_fields: list[dict],
                  stats: dict) -> dict:
    """两阶段：① 锚点——两边都有实测取值统计的字段，用非平凡值的 Jaccard 重合度贪心配对
    （不要求 bt 字段有没有名字/注释，纯粹是"两边统计出来的数字长得像不像"）。
    ② 传播——bt 里有名字/注释但自己没有 `//Values:`（人工标注后统计注释被替换掉了）的字段，
    如果它两侧最近的锚点指向同一个 C# 字段偏移量（bt 下标 - C# 下标 恒定），就按这个偏移量
    推断它对应哪个 C# 字段，标成"inferred"，置信度明显低于直接匹配的锚点。
    """
    field_stats = stats.get("fields", {})
    c_val_cache: dict[int, set[float]] = {}
    for ci, cname in enumerate(csharp_fields):
        top = field_stats.get(cname, {}).get("top")
        if top:
            c_val_cache[ci] = parse_top_values(top)

    candidates = []
    for ci, c_vals in c_val_cache.items():
        for bi, bf in enumerate(btx_fields):
            if bf["values"] is None:
                continue
            score = jaccard_nontrivial(c_vals, bf["values"])
            if score > 0:
                candidates.append((score, ci, bi))
    candidates.sort(key=lambda t: -t[0])

    used_c, used_b = set(), set()
    anchors = []  # (ci, bi, score)
    for score, ci, bi in candidates:
        if ci in used_c or bi in used_b or score < ANCHOR_MIN_SCORE:
            continue
        used_c.add(ci)
        used_b.add(bi)
        anchors.append((ci, bi, score))
    anchors.sort(key=lambda a: a[1])  # 按 bt 物理顺序

    matches = []
    for ci, bi, score in anchors:
        matches.append({
            "csharp_field": csharp_fields[ci],
            "btx_field": btx_fields[bi]["name"],
            "btx_comment": btx_fields[bi]["comment"],
            "score": round(score, 3),
            "btx_type": btx_fields[bi]["type"],
            "method": "value_match",
        })

    # 传播：找左右最近的锚点，offset 一致才推断
    for bi, bf in enumerate(btx_fields):
        if bi in used_b or bf["comment"] is None:
            continue  # 只关心"有名字/注释但没统计"的字段——这才是真正想标注的目标
        left = max((a for a in anchors if a[1] < bi), key=lambda a: a[1], default=None)
        right = min((a for a in anchors if a[1] > bi), key=lambda a: a[1], default=None)
        if left is None or right is None:
            continue
        left_offset = left[1] - left[0]
        right_offset = right[1] - right[0]
        if left_offset != right_offset:
            continue
        if (bi - left[1]) > MAX_OFFSET_SPAN or (right[1] - bi) > MAX_OFFSET_SPAN:
            continue
        ci = bi - left_offset
        if ci < 0 or ci >= len(csharp_fields) or ci in used_c:
            continue
        used_c.add(ci)
        used_b.add(bi)
        matches.append({
            "csharp_field": csharp_fields[ci],
            "btx_field": bf["name"],
            "btx_comment": bf["comment"],
            "score": round(min(left[2], right[2]), 3),
            "btx_type": bf["type"],
            "method": "inferred_by_offset",
            "anchor_left": btx_fields[left[1]]["name"],
            "anchor_right": btx_fields[right[1]]["name"],
        })

    matches.sort(key=lambda m: (m["method"] != "value_match", -m["score"]))
    return {"struct": struct_name, "matches": matches, "csharp_field_count": len(csharp_fields),
            "btx_field_count": len(btx_fields), "anchor_count": len(anchors)}


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 1
    btx_path = pathlib.Path(argv[1])
    corpus_path = pathlib.Path(argv[2])
    dll_path = pathlib.Path(argv[3])
    rest = argv[4:]
    min_ratio = 0.5
    out_path = pathlib.Path(__file__).resolve().parent / "fingerprint_matches_report.json"
    explicit_structs = []
    i = 0
    while i < len(rest):
        if rest[i] == "--min-unkn-ratio":
            min_ratio = float(rest[i + 1]); i += 2
        elif rest[i] == "--out":
            out_path = pathlib.Path(rest[i + 1]); i += 2
        else:
            explicit_structs.append(rest[i]); i += 1

    types_path = pathlib.Path(tempfile.gettempdir()) / "efx_types_for_fingerprint.json"
    subprocess.run(["dotnet", str(dll_path), "types", str(types_path)], check=True,
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
    catalogue = json.loads(types_path.read_text(encoding="utf-8"))["types"]
    by_name = {item["name"]: item for item in catalogue}

    if explicit_structs:
        target_names = explicit_structs
    else:
        target_names = []
        for item in catalogue:
            fields = [f for f in item["fields"] if f not in BOOKKEEPING]
            if len(fields) < 4:
                continue
            unkn = [f for f in fields if UNKN_RE.match(f)]
            if len(unkn) / len(fields) >= min_ratio:
                target_names.append(item["name"])

    btx = parse_btx_ordered(btx_path)
    report = {"_note": "概率性证据，需要人工复核 btx_comment 是否真的符合 C# 字段的实际行为，"
                        "不要不看直接写进 mhws_field_labels.json", "structs": []}

    for name in target_names:
        item = by_name.get(name)
        if item is None:
            print(f"[跳过] {name}: 不在 C# 类型目录里", file=sys.stderr)
            continue
        btx_fields = btx.get(name)
        if not btx_fields:
            print(f"[跳过] {name}: 模板里没有同名结构体", file=sys.stderr)
            continue
        csharp_fields = [f for f in item["fields"] if f not in BOOKKEEPING]
        print(f"扫描 {name}（{len(csharp_fields)} 个 C# 字段 / {len(btx_fields)} 个模板字段）...",
              file=sys.stderr)
        stats = run_fieldstats(dll_path, corpus_path, name)
        if stats is None:
            continue
        result = match_struct(name, csharp_fields, btx_fields, stats)
        if result["matches"]:
            report["structs"].append(result)

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    total_matches = sum(len(s["matches"]) for s in report["structs"])
    print(f"写出 {out_path}：{len(report['structs'])} 个结构体，共 {total_matches} 条候选匹配")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
