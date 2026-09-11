"""
tools/scan_derived_fields.py —— 普查"哪些字段是记账量（改了不算数）、哪些是真实数据"

    python tools/scan_derived_fields.py [抽样文件数，默认 25]

产出 `derived_report.txt` / `.json`（写在本脚本同目录）。`panels._DERIVED_FIELD_KEYS`
（面板上一律不画的记账字段名单）就是照这份报告定的。

**为什么不能照 vendor 的 `[Rsz*Field]` 标注直接抄**：那些标注不等于"写出时会重算"。
`RszByteSizeField` 压根没进代码生成器的重算分支（`ReeLibGenerator.cs:412` 那个 `if` 里只有
`RszArraySizeField`），有的字段靠各自手写的 `DoWrite()` 重建，有的干脆没人管
（`EFXAttributeTypeMeshV2.propertiesDataSize` 就是这么栽的，见 CLAUDE.md 已知机关）。所以
候选名单从源码标注来，**结论一律靠投毒实测**：往真实语料的 dump JSON 里塞一个错值，写出再
读回来，看谁的值赢。

每个落点（attribute 类型 + JSON 路径）三种判定：
  自愈        投毒值被覆盖回原值 -> 记账量，界面上藏掉不损失任何东西
  投毒残留    投毒值原样留着     -> 真实数据，**不能藏**（`unknDataSize` 就是这么被抓出来的）
  写坏        写出/读回失败      -> 没人重算，改了就烂（除非我们自己算）

同一个字段名在不同 attribute 上可能判定不同（`mdfPropertyIndex`：贴图那条被强制成 -1、
其余原样保留），所以按名字隐藏之前必须确认它**每一个**落点都是"自愈"。

**vendor 升级后要重跑**（CLAUDE.md 铁律 #6 的同一个理由：上游行为变了，我们照着它定的结论
就得重新确认）。跑之前先 `dotnet build tools/EfxBridge -p:LangVersion=preview`，还要有
`tools/attrindex_full.json`（`EfxBridge attrindex` 产出）。
"""
import json, os, re, subprocess, collections, copy, random, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DLL = os.path.join(REPO, r"tools\EfxBridge\bin\Debug\net8.0\EfxBridge.dll")
EFX_DIR = os.path.join(REPO, r"vendor\RE-Engine-Lib\REE-Lib\OtherFiles\EFX")
# 中间文件和报告都写临时目录，不往仓库里拉屎（这脚本会产生几百个一次性的 dump/写出产物）。
SP = tempfile.mkdtemp(prefix="efx_derived_")

MARKERS = ("RszArraySizeField", "RszByteSizeField", "RszStringLengthField",
           "RszStringHash", "RszStringAsciiHash", "RszStringUTF8Hash")
FIELD_RE = re.compile(r"public\s+[\w\.\?<>\[\]]+\s+(\w+)\s*(?:=|;)")
ASSIGN_RE = re.compile(r"^\s*(?:this\.)?(\w+)\s*=", re.M)

# ---- step 1: candidate field NAMES from source ---------------------------
marker_of: dict[str, str] = {}
for name in sorted(os.listdir(EFX_DIR)):
    if not name.endswith(".cs"):
        continue
    text = open(os.path.join(EFX_DIR, name), encoding="utf-8").read()
    for line in text.splitlines():
        for marker in MARKERS:
            if marker in line:
                m = FIELD_RE.search(line)
                if m:
                    marker_of.setdefault(m.group(1), marker)
    for dw in re.finditer(r"protected override bool DoWrite\(.*?\n\s*\{(.*?)\n\s{4}\}", text, re.S):
        for m in ASSIGN_RE.finditer(dw.group(1)):
            marker_of.setdefault(m.group(1), "DoWrite()")

print(f"源码候选字段名：{len(marker_of)} 个\n")

# ---- step 2: collect distinct sites from a corpus sample -----------------
idx = json.load(open(os.path.join(REPO, "tools/attrindex_full.json"), encoding="utf-8"))
root = idx["corpusRoot"]
all_files = sorted({f for files in idx["types"].values() for f in files})
random.seed(11)
sample = random.sample(all_files, int(sys.argv[1]) if len(sys.argv) > 1 else 25)


def run(*args):
    return subprocess.run(["dotnet", DLL, *args], capture_output=True, text=True)


def walk(node, attr_type, path, hits):
    if isinstance(node, dict):
        this_type = node.get("$type", attr_type)
        for key, value in node.items():
            if key in marker_of and isinstance(value, (int, float, str, list)) \
                    and not isinstance(value, bool):
                hits.append((this_type, path + "/" + key, key))
            walk(value, this_type, path + "/" + key, hits)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            walk(value, attr_type, path + "[]", hits)


sites = {}       # (attrType, generic path, field) -> (file, concrete path)
for rel in sample:
    src = os.path.join(root, rel.replace("/", os.sep))
    out = os.path.join(SP, "_ds_base.json")
    if run("dump", src, out).returncode != 0:
        continue
    data = json.load(open(out, encoding="utf-8"))
    hits = []
    walk(data, "", "", hits)
    for attr_type, path, field in hits:
        key = (attr_type.split(".")[-1], re.sub(r"\[\]", "[]", path), field)
        sites.setdefault(key, rel)

print(f"语料抽样 {len(sample)} 个文件，找到 {len(sites)} 个不同的字段落点\n")

# ---- step 3: poison each site --------------------------------------------
def poison_value(value):
    if isinstance(value, int):
        return value + 7 if value != 0 else 4242
    if isinstance(value, float):
        return value + 7.0
    if isinstance(value, str):
        return "zz_poison"
    if isinstance(value, list):
        return []
    return None


def nodes_at(data, attr_type, field):
    """所有 $type 匹配、且直接含有这个字段的字典。"""
    found = []

    def rec(node, current):
        if isinstance(node, dict):
            this_type = node.get("$type", current)
            if this_type.split(".")[-1] == attr_type and field in node:
                found.append(node)
            for value in node.values():
                rec(value, this_type)
        elif isinstance(node, list):
            for value in node:
                rec(value, current)

    rec(data, "")
    return found


results = []
for (attr_type, path, field), rel in sorted(sites.items()):
    src = os.path.join(root, rel.replace("/", os.sep))
    base_json = os.path.join(SP, "_ds_b.json")
    if run("dump", src, base_json).returncode != 0:
        continue
    base = json.load(open(base_json, encoding="utf-8"))
    targets = nodes_at(base, attr_type, field)
    if not targets:
        continue
    original = targets[0][field]
    bad = poison_value(original)
    if bad is None or bad == original:
        continue

    data = copy.deepcopy(base)
    nodes_at(data, attr_type, field)[0][field] = bad
    in_json = os.path.join(SP, "_ds_in.json")
    out_efx = os.path.join(SP, "_ds_out.efx.5571972")
    re_json = os.path.join(SP, "_ds_re.json")
    json.dump(data, open(in_json, "w", encoding="utf-8"), ensure_ascii=False)
    if run("load", in_json, out_efx).returncode != 0:
        results.append((attr_type, field, marker_of[field], "写坏", "写出失败"))
        continue
    if run("dump", out_efx, re_json).returncode != 0:
        results.append((attr_type, field, marker_of[field], "写坏", "读不回来"))
        continue
    back_nodes = nodes_at(json.load(open(re_json, encoding="utf-8")), attr_type, field)
    if not back_nodes:
        results.append((attr_type, field, marker_of[field], "写坏", "结构变了"))
        continue
    back = back_nodes[0][field]
    if back == original:
        results.append((attr_type, field, marker_of[field], "自愈", ""))
    else:
        results.append((attr_type, field, marker_of[field], "投毒残留",
                        f"{original!r} -> {back!r}"))

by_verdict = collections.defaultdict(list)
for attr_type, field, marker, verdict, detail in results:
    by_verdict[verdict].append((attr_type, field, marker, detail))

lines = []
for verdict in ("自愈", "投毒残留", "写坏"):
    rows = by_verdict.get(verdict) or []
    lines.append(f"===== {verdict}（{len(rows)} 个落点）")
    for attr_type, field, marker, detail in sorted(rows):
        lines.append(f"   {attr_type:30s} {field:26s} {marker:22s} {detail}")
    lines.append("")

report = "\n".join(lines)
open(os.path.join(SP, "derived_report.txt"), "w", encoding="utf-8").write(report)
json.dump([{"attrType": a, "field": f, "marker": m, "verdict": v, "detail": d}
           for a, f, m, v, d in results],
          open(os.path.join(SP, "derived_report.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"报告写到 {SP}\\derived_report.txt / .json")
