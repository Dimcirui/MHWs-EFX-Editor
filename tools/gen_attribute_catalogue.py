#!/usr/bin/env python3
"""
tools/gen_attribute_catalogue.py —— 生成 `blender_efx_re/semantics/mhws_attribute_types.json`

把 `EfxBridge types` 吐出来的原始类型清单，加上一列 `category`（分类），写成插件用的清单。

**分类直接用 vendor 自己的源文件分组，不自己发明一套分类学。** RE-Engine-Lib 的作者把
`EFXAttribute*` 按语义拆在 `EfxTypeBillboard.cs` / `EfxTransform.cs` / `EfxPtBehavior.cs`
这些文件里，那就是他对这些类型的理解，比我们照着名字猜靠谱。

**为什么不用命名空间**：试过了，太糙——238 个可读写类型里 `ReeLib.Efx.Structs.Main` 占 77 个、
`Misc` 占 45 个，"Main"/"Misc" 对着面板选类型的人毫无意义。源文件分组细得多也具体得多。

**为什么不给 Clip/Expression 变体单独分类**：`TypeBillboard3D` / `TypeBillboard3DClip` /
`TypeBillboard3DExpression` 名字共享前缀，列表按字母排就自然聚在一起了，再切一刀反而要在两个
维度之间跳。238 个里有 88 个是这类变体（Clip 18 / Expression 53 / MaterialClip 8 /
MaterialExpression 9）。

用法：
    dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll types /tmp/types_raw.json
    python tools/gen_attribute_catalogue.py /tmp/types_raw.json
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
EFX_SRC = REPO / "vendor" / "RE-Engine-Lib" / "REE-Lib" / "OtherFiles" / "EFX"
OUT_PATH = REPO / "blender_efx_re" / "semantics" / "mhws_attribute_types.json"

# vendor 源文件名 -> 分类 id。文案在 blender_efx_re/i18n.py 里按 `category.<id>` 取，
# 这样跟着界面语言切换走。
FILE_CATEGORY = {
    "EfxTypeBillboard":      "render_billboard",
    "EfxTypeMesh":           "render_mesh",
    "EfxTypeRibbon":         "render_ribbon",
    "EfxTypePolygon":        "render_polygon",
    "EfxTypeStrain":         "render_strain",
    "EfxTypeLightning":      "render_lightning",
    "EfxTypeGeneralStructs": "render_other",
    "EfxTransform":          "transform",
    "EfxEmitter":            "emitter",
    "EfxVelocity":           "velocity",
    "EfxPtBehavior":         "particle",
    "EfxFade":               "fade",
    "EfxFluid":              "fluid",
    "EfxVortexel":           "vortexel",
    "EfxFieldTypes":         "field",
    "EfxBasics":             "basic",
    "EfxMiscStructs":        "misc",
    "EfxUnknowns":           "misc",
}

FALLBACK_CATEGORY = "misc"


def class_to_file() -> dict[str, str]:
    """`EFXAttributeTransform3D` -> `EfxTransform`（定义它的源文件名，不含扩展名）。"""
    mapping: dict[str, str] = {}
    for path in sorted(EFX_SRC.glob("*.cs")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'class\s+(EFXAttribute\w+)', source):
            mapping.setdefault(m.group(1), path.stem)
    return mapping


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    raw_path = pathlib.Path(argv[1])
    if not raw_path.exists():
        print(f"找不到原始清单：{raw_path}（先跑 EfxBridge types）")
        return 1
    if not EFX_SRC.exists():
        print(f"找不到 vendor 源码目录：{EFX_SRC}（submodule 拉了吗）")
        return 1

    data = json.loads(raw_path.read_text(encoding="utf-8"))
    mapping = class_to_file()

    counts: dict[str, int] = {}
    unmapped: list[str] = []
    for item in data.get("types") or []:
        full = item.get("type")
        if not full:
            # 没有读写实现类的类型（KNOWN_UPSTREAM_ISSUES #4），选择器里本来就不列
            item["category"] = FALLBACK_CATEGORY
            continue
        cls = full.rsplit(".", 1)[-1]
        stem = mapping.get(cls)
        if stem is None:
            unmapped.append(cls)
        category = FILE_CATEGORY.get(stem, FALLBACK_CATEGORY)
        if stem is not None and stem not in FILE_CATEGORY:
            unmapped.append(f"{cls}（源文件 {stem} 未登记分类）")
        item["category"] = category
        if item.get("readable"):
            counts[category] = counts.get(category, 0) + 1

    data["_generated_by"] = "tools/gen_attribute_catalogue.py"
    data["_note"] = ("category 来自 vendor 自己的源文件分组（EfxTypeBillboard.cs 等），"
                     "不是我们发明的分类学。vendor 升级后重新生成。")
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"写出 {OUT_PATH}")
    print(f"  类型总数 {data.get('count')}，可读写 {sum(counts.values())}")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {cat:<20} {n}")
    if unmapped:
        print(f"  没对上分类、落到 {FALLBACK_CATEGORY} 的：{len(unmapped)}")
        for u in unmapped[:10]:
            print(f"     {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
