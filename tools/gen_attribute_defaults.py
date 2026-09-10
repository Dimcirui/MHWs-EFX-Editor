#!/usr/bin/env python3
"""
tools/gen_attribute_defaults.py —— 把 `build_attr_defaults.py` 的分析结果蒸馏成插件要发行的
`blender_efx_re/semantics/mhws_attribute_defaults.json`。

`tools/attr_defaults_top40.json` 是分析产物，带 `review`/`instances`/`rank` 这些调研元数据，
只给人看、不随插件分发。这里只抽 `defaults` 这一层，键是 EfxAttributeType 枚举短名（`new
attribute <name>` 用的就是这个名字，见 attribute_types.py），供 `bridge.new_attribute()`
在创建时合并进 vendor 吐出的零值实例。

`defaults` 为空的类型（这批分析里全部字段众数置信度都不够）直接不写进去——查不到就是"没有
可信默认值，沿用 vendor 零值"，跟这张表里"类型压根没跑过分析"是同一种回退路径，不需要区分。

用法：
    python tools/gen_attribute_defaults.py tools/attr_defaults_top40.json
"""
from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT_PATH = REPO / "blender_efx_re" / "semantics" / "mhws_attribute_defaults.json"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    in_path = pathlib.Path(argv[1])
    data = json.loads(in_path.read_text(encoding="utf-8"))

    out = {
        "game": "MHWS",
        "defaults": {
            name: entry["defaults"]
            for name, entry in data.items()
            if entry.get("defaults")
        },
    }

    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(out['defaults'])}/{len(data)} 种类型有非空默认值 -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
