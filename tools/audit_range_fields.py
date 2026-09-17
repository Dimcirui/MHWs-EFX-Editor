# -*- coding: utf-8 -*-
"""
tools/audit_range_fields.py —— 全语料排查每个二元字段到底是 (min,max) 还是 (静态值,随机量)

    dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll pairstats <语料目录> pairstats.json
    python3 tools/audit_range_fields.py pairstats.json [--all]

`pairstats` 只吐**原始计数**，判据全在这里——改判据不用重新编译 C#，而且"依据"和"结论"
分开看得见。退出码：有"和现有名单不一致"的字段 -> 1，全一致 -> 0。

## 为什么要排查

`via.Range`/`via.RangeI` 在文件里都是两个数 `{s,r}`，**同一个二进制形状承载三种语义**：

    (静态值, 随机量)    第二个数是**相对量**，叠在第一个数上（默认，绝大多数字段）
    (min, max)          第二个数是**绝对上界**
    (索引, 配套计数)     SequenceNo 专用

判错的后果是静默的：面板把两列标签标反、预览把区间读成"基值+浮动"，数值全错但什么都不报。
名单现在是逐个字段人工加进 `model.py` 的，**没人系统查过还有多少漏网的**。

## 判据（只用联合分布，不看字段名）

记主值 `p`（二进制首字段）、副值 `q`。

1. **`p` 恒为 0 -> 两种读法数值上完全等价**（`uniform(0,q)` 和 `0 + uniform(0,q)` 是同一件
   事），无从区分，也**不需要**区分。单独归一类，不算"待定"。
2. **`q < p` 出现过（任意量）-> 默认回退 static/random。** 这不只是"max<min 讲不通"的
   语义论证，更是**界面诚实性**的要求：把两列标成 Min/Max 会让用户默认 `Min <= Max` 恒成立，
   而语料里真有反例时那个标签本身就在骗人。回退到 static/random 的代价只是"少解释一层语义"，
   标错 Min/Max 的代价是用户照着一个错的心智模型去填数。
   ⚠ 注意 `q < p` 已经把"值 v、不随机"那种写法 `(v, 0)`（v>0）包含在内了，**不需要**再单独
   统计 `q == 0`——而且单独统计还会误伤：`p < 0` 时 `(-0.25, 0)` 是个完全正常的区间
   `[-0.25, 0]`，不是"不随机"。
   ⚠ 这条同时也是 **min+offset vs min+max** 的判据（外边界是 `p+q` 还是 `q`）：
   min+offset 下 `q` 是**厚度**，没有任何理由 >= 内边界 `p`（半径 1.0、厚 0.1 的薄壳就是
   `(1.0, 0.1)`，即 `q < p`）。所以 `q < p` 一次都没有 + **主值大量非零** = 外边界是 `q`。
   报告里 `副值<主值` 后面跟着"主值非零 N 例"就是给这条用的——主值恒为 0 时 `p <= q` 是
   白捡的，那个 0 说明不了任何事。
3. `q < p` **一次都没有**时，看 **MM 招牌**：`q == p` 且 `p != 0`，读作"固定为 p"（区间退化
   成一个点），是 min/max 语义下写死一个值的标准姿势。占比过 `_IDIOM_MIN` 就判 min/max。
   **必须排掉 `p == 0`**：`(0, 0)` 两种读法都满足，那是"没填"的默认值，零信息量——早先只看
   `q == p` 就是栽在这儿。
4. 第 2 条回退掉、但 MM 招牌**同时也成规模**的，额外标成**有争议**：结论仍取 static/random
   （安全默认），但把两边的数字摆出来，等人拿字段语义或实机验证再定。
5. min/max 的**开闭**（只对整数字段有意义，浮点是零测度）：
   - `q == p` 一次都没有、且 `q == p+1` 是主流 -> **左闭右开 `[p, q)`**
     （半开区间里 `q == p` 恰好是空区间，作者永远不会写）
   - `q == p` 占相当比例 -> **闭区间 `[p, q]`**（那是"固定一个值"的写法）
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 已知但**故意先不改**的字段：`(类型, 字段) -> 为什么先不改`。它们照常列在报告里，
#: 但不让退出码变红——否则这个脚本永远是红的，没人会再跑它。改判了就从这儿删掉。
_DEFERRED = {
    ("Velocity3D", "InheritDistance"): "「固定为非零值」只有 5.1%，刚过阈值，证据不够硬",
}

#: MM 招牌（`q == p` 且 `p != 0`）占比超过它才算**成规模**（不是个别巧合）。全语料 223 个
#: 字段的实际分布里这个位置很空：要么 0~2%（噪声级），要么 10% 以上（惯用写法级）。
_IDIOM_MIN = 0.05
#: `q == p` 低于这个比例才考虑"半开"。半开区间下 `q == p` 是空区间，应当是 0。
_EQ_TOLERANCE = 0.001


def _parse_model_lists() -> dict:
    """从 `model.py` 里抠出四张名单。**按文本解析**，不 import——这个脚本要能脱离 Blender 跑
    （`model.py` 顶上就 `import bpy`）。同 `tests/test_sim_core.py` 的镜像检查的做法。"""
    text = (_REPO_ROOT / "blender_efx_re" / "model.py").read_text(encoding="utf-8")

    def names(const: str) -> set:
        # `(?<![A-Za-z0-9_])` 不能省：`_MIN_MAX_FIELD_NAMES` 会先匹配到
        # `_SR_MIN_MAX_FIELD_NAMES` 的后半截，静默读到另一张名单（踩过）。
        m = re.search(r"(?<![A-Za-z0-9_])" + const + r"\s*=\s*frozenset\(\{(.*?)\}\)",
                      text, re.S)
        return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

    pair = set()
    m = re.search(r"_PAIR_MIN_MAX_FIELDS\s*=\s*frozenset\(\{(.*?)\}\)", text, re.S)
    if m:
        pair = {(a, b) for a, b in re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', m.group(1))}
    return {
        "index": names("_SR_INDEX_FIELD_NAMES"),
        "sr_min_max": names("_SR_MIN_MAX_FIELD_NAMES"),
        "pair_min_max": pair,
        "int2_min_max": names("_MIN_MAX_FIELD_NAMES"),
    }


def _declared(lists: dict, type_name: str, field: str) -> str:
    """这个字段现在被归成什么。"""
    if field in lists["index"]:
        return "index"
    if field in lists["sr_min_max"]:
        return "min_max"
    if (type_name, field) in lists["pair_min_max"]:
        return "min_max"
    if field in lists["int2_min_max"]:
        return "min_max"
    return "static_random"


def _verdict(st: dict) -> tuple[str, str, str]:
    """`(判定, 开闭, 一句话依据)`。判定取值：
    `static_random` / `min_max` / `ambiguous` / `undetermined` / `equivalent`。"""
    n = st["n"]
    if n == 0:
        return "unknown", "", "没有实例"
    if st["firstNonZero"] == 0:
        return ("equivalent", "", f"主值恒为 0（{n} 例）—— 两种读法数值等价，无从区分")

    # 开闭：只对整数字段有意义
    integral = st["allIntegral"] == n
    if not integral:
        bound = "closed"   # 浮点，开闭是零测度，标成闭只是取个默认
    elif st["secondEqFirst"] / n <= _EQ_TOLERANCE and st["secondEqFirstPlus1"] > 0:
        bound = "half_open"
    else:
        bound = "closed"

    # MM 招牌 =「区间退化成一个点」，闭区间和半开区间写法不同：
    #   闭   `[p, p]`   -> `q == p`（且排掉 p==0 的"没填"默认值）
    #   半开 `[p, p+1)` -> `q == p + 1`（`q == p` 在半开下是空区间，结构上恒为 0——
    #                      不分开算的话 PatternNo/PartsStartNo 会被误判成"没有证据"）
    mm_n = (st["secondEqFirstPlus1"] if bound == "half_open"
            else st.get("secondEqFirstNonZero", 0))
    lt_n = st["secondLtFirst"]                      # q < p：max < min
    mm, lt = mm_n / n, lt_n / n
    # 主值非零的实例数**必须一起报**：`副值<主值 0 例`这条证据的力度全看它。主值恒为 0 时
    #「p <= q」是白捡的（q>=0 自然成立），那条 0 说明不了任何事；主值大量非零时才是真结论。
    tally = (f"副值<主值 {lt_n}/{n}（{lt * 100:.1f}%，其中主值非零 {st['firstNonZero']} 例）、"
             f"MM招牌{'(q==p+1)' if bound == 'half_open' else ''} "
             f"{mm_n}/{n}（{mm * 100:.1f}%）")
    mm_strong = mm >= _IDIOM_MIN

    if lt_n > 0:
        # 用户定的安全默认：Min/Max 标签暗示 `Min <= Max` 恒成立，语料里有反例就不能这么标。
        if mm_strong:
            return ("ambiguous", "",
                    f"回退 static/random（副值<主值 有反例），但 MM 招牌也成规模：{tally}")
        return ("static_random", "", tally)
    if mm_strong:
        return ("min_max", bound, tally)
    return ("undetermined", bound,
            f"副值<主值 0 例（min/max 的必要条件成立），但 MM 招牌不成规模：{tally}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().split("\n\n")[1])
        return 1
    data = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))
    show_all = "--all" in argv
    lists = _parse_model_lists()

    print(f"语料：扫描 {data['filesScanned']}/{data['filesTotal']} 个文件"
          f"（失败 {data['filesFailed']}）")
    print(f"现有名单：index {len(lists['index'])} / sr_min_max {len(lists['sr_min_max'])}"
          f" / pair_min_max {len(lists['pair_min_max'])} / int2_min_max {len(lists['int2_min_max'])}")

    rows = []
    for type_name, tdata in data["types"].items():
        for path, st in tdata["fields"].items():
            field = path.split(".")[-1].replace("[]", "")
            verdict, bound, why = _verdict(st)
            rows.append((type_name, path, field, st, verdict, bound, why))

    # 1. 真正的冲突：现有名单和语料结论对不上
    conflicts = []
    for type_name, path, field, st, verdict, bound, why in rows:
        declared = _declared(lists, type_name, field)
        if declared == "index" or verdict in ("equivalent", "unknown"):
            continue
        if verdict == "static_random" and declared == "min_max":
            conflicts.append(("判成 min/max 但语料说不是", type_name, path, st, why,
                              _DEFERRED.get((type_name, field))))
        elif verdict == "min_max" and declared == "static_random":
            conflicts.append(("按 static/random 读但语料说是 min/max", type_name, path, st, why,
                              _DEFERRED.get((type_name, field))))

    unresolved = [c for c in conflicts if c[5] is None]
    print(f"\n{'=' * 78}\n[1] 和现有名单冲突的字段：{len(conflicts)} 个"
          f"（其中 {len(conflicts) - len(unresolved)} 个是已知待办）\n{'=' * 78}")
    for tag, type_name, path, st, why, deferred in sorted(conflicts, key=lambda r: -r[3]["n"]):
        print(f"  {tag}" + (f"  [已知待办：{deferred}]" if deferred else ""))
        print(f"      {type_name}.{path}  n={st['n']}  {why}")
        print(f"      高频组合: {_top(st)}")

    # 2. 已经判成 min/max 的，把开闭列出来（面板要按它提示 min==max）
    print(f"\n{'=' * 78}\n[2] min/max 字段的开闭\n{'=' * 78}")
    for type_name, path, field, st, verdict, bound, why in sorted(rows, key=lambda r: -r[3]["n"]):
        if _declared(lists, type_name, field) != "min_max":
            continue
        integral = "int" if st["allIntegral"] == st["n"] else "float"
        print(f"  {bound:<10} {integral:<6} {type_name}.{path}  n={st['n']}  "
              f"副值==主值 {st['secondEqFirst']}  ==主值+1 {st['secondEqFirstPlus1']}")

    # 3. 存疑：两种招牌写法都成规模，只凭分布定不了，交人判
    candidates = [r for r in rows if r[4] == "ambiguous"]
    print(f"\n{'=' * 78}\n[3] 有争议：已按安全默认回退 static/random，但 MM 招牌也成规模"
          f"：{len(candidates)} 个\n{'=' * 78}")
    for type_name, path, field, st, verdict, bound, why in sorted(
            candidates, key=lambda r: -r[3]["n"])[:40 if not show_all else None]:
        print(f"  {type_name}.{path}  n={st['n']}  {bound}  {why}")
        print(f"      高频组合: {_top(st)}")

    equivalent = [r for r in rows if r[4] == "equivalent"]
    print(f"\n{'=' * 78}\n[4] 主值恒为 0，两种读法等价（不用管）：{len(equivalent)} 个字段"
          f"\n{'=' * 78}")
    if show_all:
        for type_name, path, field, st, *_ in sorted(equivalent, key=lambda r: -r[3]["n"]):
            print(f"  {type_name}.{path}  n={st['n']}")

    undetermined = [r for r in rows if r[4] == "undetermined"]
    print(f"\n{'=' * 78}\n[5] 证据不足（两种招牌都不成规模）：{len(undetermined)} 个"
          f"\n{'=' * 78}")
    for type_name, path, field, st, verdict, bound, why in sorted(
            undetermined, key=lambda r: -r[3]["n"])[:20 if not show_all else None]:
        print(f"  {type_name}.{path}  n={st['n']}  现判 {_declared(lists, type_name, field)}")
        print(f"      {why}")

    total = len(rows)
    static_random = sum(1 for r in rows if r[4] == "static_random")
    print(f"\n汇总：{total} 个二元字段 | 确证 static/random {static_random}"
          f" | 确证 min/max {sum(1 for r in rows if r[4] == 'min_max')}"
          f" | 有争议 {len(candidates)} | 证据不足 {len(undetermined)} | 等价 {len(equivalent)}")
    return 1 if unresolved else 0


def _top(st: dict, k: int = 5) -> str:
    return ", ".join(f"({a})×{b}" for a, b in list(st["topPairs"].items())[:k])


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
