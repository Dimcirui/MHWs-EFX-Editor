#!/usr/bin/env python3
"""
tools/gen_ptbehavior_catalog.py —— 生成 `blender_efx_re/semantics/mhws_ptbehavior_catalog.json`

`EFXAttributePtBehavior.properties`（`PtBehaviorVariable` 数组）是一张按 `behaviorString`
（游戏原生类名）区分的稀疏覆盖表：每个类有一张固定的属性词汇表，实例只存被覆盖的子集。
这个类词汇表只能靠全语料扫描得到——`behaviorString` 只是个类名，不像 `EFXAttributeTypeMeshV2.
properties` 那样能现查一个外部 `.mdf2` 文件（见 `mdf_catalog.py`）。

输入是 `EfxBridge ptbehaviorcatalog` 的原始扫描结果（每个 behaviorString 下每个属性名的
freq/dataTypes/varHashes，外加**第一次遇到时原样捕获的完整 `PtBehaviorVariable` JSON**），
这里做两件事：

1. **自动判定哪个 behaviorString 能收进目录**：`PtBehaviorVariable.varSize` 没有
   `[RszByteSizeField]`/`[RszArraySizeField]` 标注，不会被 vendor 自愈，所以"新增一条"
   不手工拼字段，而是克隆语料里真实出现过的完整实例当模板——这就要求这个类的属性顺序
   必须有一个全局一致的规范序（否则"插到哪"没有依据）。用 `sequences`（每个实例属性名
   序列的出现次数）两两建有向图查环：查出环就说明这个类的属性顺序在语料里自相矛盾。
   常见原因之一是把"数组套数组"拍平进了同一张表（如 `EffectVolumetricFog` 的
   `MaterialParamWrapperList[N]`、`EffectDecal2.EffectDecal_V2` 的 `OtherMaterialParamList[N]`
   分组，同一个下标区间内的子字段跟着分组走，不是全局固定位置）——这种情况先剔掉分组头
   本身和分组内部字段（`_recover_top_level_names()`），只用剩下的顶层字段重新查一遍环，
   顶层字段本身顺序一致的话照样收录，分组那部分字段继续走通用树透传，不提供增删入口；
   顶层字段剔完之后还冲突，或者混了两套互斥 schema（如 `EffectGroundDeforme` 的
   `_Manual`/`_Preset` 两条分支）——这两种才整类排除。
   同一个 key 在单实例里合法重复（如 `EffectMeshClusterMotoin` 的 `SandBlend`）**不算
   这种冲突**：建图时每个实例只取每个名字第一次出现的位置，重复出现本身不提供任何顺序
   证据，也不该被当成矛盾——它只是"这个属性被同一份数据覆盖了两遍"，不影响其余属性的
   相对顺序，见 `_pairwise_edges()`。
   不手写排除名单——语料/vendor 升级后重跑这个脚本，结论自动更新。
2. 通过判定的类，用查环时建的有向图做拓扑排序，得到规范顺序；每个属性名配上它的模板
   （第一次见到时捕获的完整实例），写成插件运行时直接能用的候选目录。

用法：
    dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll ptbehaviorcatalog <语料目录> /tmp/ptbehavior_raw.json
    python tools/gen_ptbehavior_catalog.py /tmp/ptbehavior_raw.json
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "blender_efx_re" / "semantics" / "mhws_ptbehavior_catalog.json"


def _pairwise_edges(sequences: dict[str, int]) -> set[tuple[str, str]]:
    """从"属性名序列 -> 出现次数"里收集全部观测到的两两先后关系（去重）。

    同一个实例里合法重复的 key（如 `EffectMeshClusterMotoin` 的 `SandBlend`）会在两次
    出现之间夹着的属性上制造自相矛盾的先后关系——第一次出现之前的属性"在 SandBlend 之前"，
    第二次出现之后的属性又"在 SandBlend 之后"，中间那些属性则两头都沾。这不是真的顺序
    冲突，只是同一条覆盖被写了两遍；每个实例只取每个名字**第一次出现的位置**参与建图，
    重复出现本身不提供顺序证据，也不产生任何冲突。
    """
    edges: set[tuple[str, str]] = set()
    for seq_key in sequences:
        if not seq_key:
            continue
        seen: set[str] = set()
        names: list[str] = []
        for n in seq_key.split("|"):
            if n and n not in seen:
                seen.add(n)
                names.append(n)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                edges.add((names[i], names[j]))
    return edges


def _has_conflict(edges: set[tuple[str, str]]) -> bool:
    """(a,b) 和 (b,a) 同时出现 = 两个实例给出了互相矛盾的先后关系。"""
    return any((b, a) in edges for (a, b) in edges)


def _topological_order(names: list[str], edges: set[tuple[str, str]]) -> list[str]:
    """Kahn 算法，入度并列时按字母序取，保证同一份语料重新生成时结果稳定。"""
    succ: dict[str, set[str]] = {n: set() for n in names}
    indeg: dict[str, int] = {n: 0 for n in names}
    for a, b in edges:
        if b not in succ[a]:
            succ[a].add(b)
            indeg[b] += 1

    ready = sorted(n for n in names if indeg[n] == 0)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        newly_ready = []
        for m in succ[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                newly_ready.append(m)
        ready = sorted(ready + newly_ready)
    # 有环的话通不过 _has_conflict 那道闸，走不到这里；这行只是防御一下万一漏判，
    # 把没排上的名字按字母序补在末尾，不静默丢属性。
    if len(order) != len(names):
        order.extend(sorted(set(names) - set(order)))
    return order


# 人工拍板的顺序覆盖：某个 behaviorString 里两个属性的相对顺序在语料里有**真实分歧**
# （不是同 key 重复造成的假象——那种 `_pairwise_edges()` 已经自动排除了），两个方向都被
# 真实游戏文件用过，自动判定拿不出结论，需要人工选一个方向。**范围严格限定到这一对具名
# 属性**，不是"这个类整体顺序不可靠所以放宽判据"——`EffectDecal2`/`EffectGroundDeforme`
# 那种数组套数组/多套互斥 schema 的真实结构问题，不受这张表影响，继续被自动判据拦下来。
#
# {behaviorString: {(在前, 在后): "人工判断的依据"}}
_MANUAL_ORDER_OVERRIDES: dict[str, dict[tuple[str, str], str]] = {
    "app.EffectMeshClusterMotoin": {
        ("MeshSettingParam", "SandBlend"): (
            "语料里 62/90 个实例（69%）是 MeshSettingParam 在前，28/90 相反——两个方向都被"
            "真实文件用过，不是自相矛盾的假象；人工选定 MeshSettingParam 在前（多数方向）。"
        ),
    },
}


def _apply_manual_overrides(behavior_string: str, edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """按 `_MANUAL_ORDER_OVERRIDES` 丢掉与人工选定方向相反的那条边。"""
    overrides = _MANUAL_ORDER_OVERRIDES.get(behavior_string)
    if not overrides:
        return edges
    resolved = set(edges)
    for before, after in overrides:
        resolved.discard((after, before))
    return resolved


_ARRAY_GROUP_NAME_RE = re.compile(r"\[\d+\]$")
_ARRAY_GROUP_HEADER_RE = re.compile(r"^(.+)\[\d+\]$")


def _has_array_group_names(names) -> bool:
    """有没有 `Xxx[N]` 这种带下标的分组头名字。

    这是"数组套数组被拍平进同一张表"的信号，跟"同一个 key 在单实例里合法重复"
    （如 `EffectMeshClusterMotoin` 的 `SandBlend`）是两回事，`_pairwise_edges()`
    的去重解决不了它：实测过 `EffectVolumetricFog` 的 `MaterialParamWrapperList[0]`，
    它的值解码出来是 `via.effect.script.EffectVolumetricFog.VolumetricFogMaterialParam`
    ——这个"属性"根本不是一个数据值，是一个**嵌套子 behavior 的类名**，紧跟在它后面的
    `VariableName`/`ValueF4`/`ValueF` 等字段属于**那个嵌套类**，每个下标一份，不是
    `EffectVolumetricFog` 自己的顶层属性。把它们摊平当成"这个类有名为 VariableName 的
    属性"会丢掉"属于第几个分组"这个维度，候选目录会失真（例如"新增 ValueF"这个操作
    在真实语义里应该是"往第 N 个分组里加"，而不是给类本身加一个孤立的 ValueF）。
    去重能让 `_has_conflict()` 不再报错，但没法把这个维度找回来，所以单独拦。
    """
    return any(_ARRAY_GROUP_NAME_RE.search(n) for n in names)


def _array_group_header_base(name: str) -> str | None:
    """`"Xxx[3]"` -> `"Xxx"`；不是分组头返回 `None`。"""
    m = _ARRAY_GROUP_HEADER_RE.match(name)
    return m.group(1) if m else None


def _strict_interior_names(sequences: dict[str, int]) -> set[str]:
    """收集"严格夹在同一 family 两个连续分组头之间"的字段名——这些不是这个类自己的顶层
    属性，是每个数组下标各自嵌套对象的字段（`EffectDecal_V2` 的 `OtherMaterialParamList[N]`
    后面跟的 `ValueType`/`VariableName`/`VariableNameHash`/`ValueF`/... 就是这种）。

    只取"连续两个同 family 分组头之间"这一段，不取"最后一个分组头到序列末尾"这一段——
    实测过后者会掺进真正的顶层字段（数组元素数量不固定，最后一个下标后面紧跟的可能已经是
    下一个顶层属性），把它当成分组内部会把顶层字段误判成嵌套字段。用"两个分组头夹住"这个
    更严格的条件换取零假阳性：语料里验证过 `EffectDecal_V2` 用这个条件选出的 6 个名字
    （`ValueType`/`VariableName`/`VariableNameHash`/`ValueF`/`ValueTexture`/`ValueVec4`）
    从不在任何序列的"分组外"位置出现过。
    """
    interior: set[str] = set()
    for seq_key in sequences:
        if not seq_key:
            continue
        names = seq_key.split("|")
        header_idxs = [i for i, n in enumerate(names) if _array_group_header_base(n)]
        for pos in range(len(header_idxs) - 1):
            i, j = header_idxs[pos], header_idxs[pos + 1]
            if _array_group_header_base(names[i]) == _array_group_header_base(names[j]):
                interior.update(names[i + 1:j])
    return interior


def _recover_top_level_names(names: list[str], sequences: dict[str, int]):
    """`_has_array_group_names` 命中的类不再直接整类排除，先尝试"挖掉数组分组、剩下的顶层
    字段还能不能排出一致的顺序"。

    分组头本身（`Xxx[N]`）、裸的分组名标记（`Xxx`，数组自己的计数/存在标记）、以及
    `_strict_interior_names()` 挑出的嵌套字段，三类一起从候选名单和用来建图的序列里剔除——
    不是"看着像"就猜漏了什么，是这三类字段本来就不属于这个类自己的顶层覆盖表，留着只会让
    候选目录失真（`_has_array_group_names` 的 docstring 有完整论证）。

    返回 `(remaining_names, edges)`；`remaining_names` 为空或者剔除之后顶层顺序仍然冲突，
    调用方按老办法整类排除（原因单独区分，不跟"没试过"混在一起）。
    """
    header_bases = {_array_group_header_base(n) for n in names if _array_group_header_base(n)}
    interior_names = _strict_interior_names(sequences)
    drop_names = {n for n in names if _array_group_header_base(n)} | header_bases | interior_names
    remaining_names = [n for n in names if n not in drop_names]

    cleaned_sequences: dict[str, int] = {}
    for seq_key, freq in sequences.items():
        if not seq_key:
            continue
        cleaned = [n for n in seq_key.split("|") if n not in drop_names]
        cleaned_key = "|".join(cleaned)
        cleaned_sequences[cleaned_key] = cleaned_sequences.get(cleaned_key, 0) + freq

    edges = _pairwise_edges(cleaned_sequences)
    edges = {(a, b) for (a, b) in edges if a in remaining_names and b in remaining_names}
    return remaining_names, edges


def build_catalog(raw: dict) -> dict:
    behaviors: dict[str, list[dict]] = {}
    defaults: dict[str, list[dict]] = {}
    excluded: list[tuple[str, str]] = []

    for behavior_string, bucket in raw.get("byBehavior", {}).items():
        if not behavior_string:
            continue
        properties = bucket.get("properties") or {}
        names = [n for n in properties if n]
        if not names:
            excluded.append((behavior_string, "没有任何属性"))
            continue
        sequences = bucket.get("sequences") or {}
        if _has_array_group_names(names):
            names, edges = _recover_top_level_names(names, sequences)
            if not names:
                excluded.append((
                    behavior_string,
                    "属性名里有 Xxx[N] 这种带下标的分组头，剔除分组本身和分组内部字段后"
                    "不剩任何顶层属性——是嵌套子结构的数组被拍平进了同一张表，不是扁平覆盖表"
                    "（详见 _has_array_group_names 的说明）",
                ))
                continue
            edges = _apply_manual_overrides(behavior_string, edges)
            if _has_conflict(edges):
                excluded.append((
                    behavior_string,
                    "属性名里有 Xxx[N] 这种带下标的分组头，剔除分组本身和分组内部字段之后，"
                    "剩下的顶层属性顺序在语料里仍然自相矛盾（详见 _has_array_group_names 的"
                    "说明；分组本身继续走通用树透传，不提供增删入口）",
                ))
                continue
        else:
            edges = _apply_manual_overrides(behavior_string, _pairwise_edges(sequences))
            if _has_conflict(edges):
                excluded.append((behavior_string, "属性顺序在语料里自相矛盾（数组套数组/同key合法重复/多套互斥schema）"))
                continue

        order = _topological_order(names, edges)
        entries = []
        for name in order:
            template = properties[name].get("template")
            if template is None:
                # 理论上不会发生（每条属性至少来自一个实例，扫描时必然捕获过模板），
                # 但没有模板就没法安全新增——跳过这一条，不编一个假模板出来。
                continue
            entries.append({"name": name, "template": template})
        if entries:
            behaviors[behavior_string] = entries
        else:
            excluded.append((behavior_string, "没有任何带模板的属性"))
            continue

        # 众数默认字段块：EfxBridge 已经在原始扫描里选出了出现次数最多的字段组合
        # （`defaultSequenceKey`），并存了那一个真实实例的完整 properties 数组
        # （`defaultTemplate`）——每个字段的值都来自同一个文件，不是东拼西凑。
        default_template = bucket.get("defaultTemplate")
        if isinstance(default_template, list) and default_template:
            default_entries = []
            for var in default_template:
                name = var.get("behaviorProperty") if isinstance(var, dict) else None
                if not name:
                    continue
                default_entries.append({"name": name, "template": var})
            if default_entries:
                defaults[behavior_string] = default_entries

    return {
        "_generated_by": "tools/gen_ptbehavior_catalog.py",
        "_note": (
            "PtBehavior 属性候选目录：只收录属性顺序在全语料里全局一致的 behaviorString。"
            "`behaviors[cls]` 每条候选的 template 是语料里真实出现过的完整"
            " PtBehaviorVariable，新增时整个克隆，不手工拼字段（varSize 等记账字段没有自愈"
            "标注）。`defaults[cls]` 是这个类在全语料里出现次数最多的那一套字段组合，取自"
            "同一个真实实例（不是把各字段各自「第一次见到」的模板拼起来）——新建/改写"
            " behaviorString 时用它当默认字段块，不是把 behaviors[cls] 全部塞进去。"
        ),
        "behaviors": behaviors,
        "defaults": defaults,
        "_excluded": [{"behaviorString": b, "reason": r} for b, r in excluded],
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    raw_path = pathlib.Path(argv[1])
    if not raw_path.exists():
        print(f"找不到原始扫描结果：{raw_path}（先跑 EfxBridge ptbehaviorcatalog）")
        return 1

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    catalog = build_catalog(raw)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")

    behaviors = catalog["behaviors"]
    defaults = catalog["defaults"]
    excluded = catalog["_excluded"]
    print(f"写出 {OUT_PATH}")
    print(f"  收录 {len(behaviors)} 个 behaviorString，排除 {len(excluded)} 个")
    for b, r in [(e["behaviorString"], e["reason"]) for e in excluded]:
        print(f"    排除：{b}  ({r})")
    for b, entries in behaviors.items():
        default_count = len(defaults.get(b, []))
        print(f"    {b}: {len(entries)} 条候选，默认字段块 {default_count} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
