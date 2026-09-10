#!/usr/bin/env python3
"""
tools/build_attr_defaults.py —— 把 `EfxBridge fieldstatsbatch` 的直方图转成"建议默认值"。

每个字段取语料众数当默认值，但按众数占比分三档：
    >= HIGH_CONF (0.9)  直接采用，不需要人看
    [LOW_CONF, HIGH_CONF)  采用，但记进 review 列表供人工复核
    <  LOW_CONF (0.5)  **不采用**——众数本身就没有代表性（比如 Layout.layoutDataFloats
       这种大 blob 字段，最常见的取值也只占几百分之一），硬塞一个"众数"跟瞎猜没区别，
       等于是拿统计包装了一个假结论。宁可留空（沿用 vendor 零值），交给人工看 review
       列表决定要不要单独处理。

`type` / `Version` / `UniqueID` / `IsTypeAttribute` 这几个是每个 attribute 通用的记账字段
（不是"游戏效果参数"），一律不进默认值——它们该由创建逻辑自己填，不该抄语料众数。

用法：
    python tools/build_attr_defaults.py tools/fieldstats_top40.json tools/attr_defaults_top40.json
"""
from __future__ import annotations

import json
import pathlib
import sys

HIGH_CONF = 0.9
LOW_CONF = 0.5

BOOKKEEPING = {"type", "Version", "UniqueID", "IsTypeAttribute"}


def set_nested(tree: dict, path: str, value) -> None:
    parts = path.split(".")
    node = tree
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def build_type_entry(type_name: str, info: dict) -> dict:
    defaults: dict = {}
    review: list[dict] = []
    # 分母必须是这个类型的实例总数，不能用 sum(top.values())：fieldstatsbatch 每个字段只保留
    # 前 N 个高频取值（这批跑的是 80），高基数字段（比如 Layout.layoutDataFloats 有 2992 种
    # 取值）尾部会被截掉，sum(top) 远小于实例总数，拿它当分母会把置信度算得虚高。
    # 众数本身不受截断影响——OrderByDescending().Take(N) 保证真正的最大值一定在保留范围内。
    total = info["instances"]

    for field_path, field_info in info["fields"].items():
        root = field_path.split(".", 1)[0]
        if root in BOOKKEEPING:
            continue

        top = field_info["top"]
        if total == 0 or not top:
            continue
        mode_str, mode_count = max(top.items(), key=lambda kv: kv[1])
        confidence = mode_count / total

        if confidence >= HIGH_CONF:
            level = "high"
        elif confidence >= LOW_CONF:
            level = "medium"
        else:
            level = "low"

        if level != "low":
            try:
                parsed = json.loads(mode_str)
            except json.JSONDecodeError:
                # fieldstats 里数组只记了长度（"N"），不是合法的字段值本身，不能当默认值塞回去
                continue
            set_nested(defaults, field_path, parsed)

        if level != "high":
            top5 = sorted(top.items(), key=lambda kv: kv[1], reverse=True)[:5]
            review.append({
                "field": field_path,
                "confidence": round(confidence, 4),
                "level": level,
                "distinct": field_info["distinct"],
                "top": top5,
            })

    review.sort(key=lambda r: r["confidence"])

    return {
        "instances": info["instances"],
        "rank": info.get("rank"),
        "instancePercent": info.get("instancePercent"),
        "defaults": defaults,
        "review": review,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    in_path = pathlib.Path(argv[1])
    out_path = pathlib.Path(argv[2])

    data = json.loads(in_path.read_text(encoding="utf-8"))
    result = {
        name: build_type_entry(name, info)
        for name, info in data["types"].items()
    }

    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    total_review_low = sum(
        1 for t in result.values() for r in t["review"] if r["level"] == "low"
    )
    total_review_medium = sum(
        1 for t in result.values() for r in t["review"] if r["level"] == "medium"
    )
    print(f"OK: {len(result)} 种类型 -> {out_path}")
    print(f"  medium(采用但建议复核): {total_review_medium}")
    print(f"  low(未采用众数，留空待人工处理): {total_review_low}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
