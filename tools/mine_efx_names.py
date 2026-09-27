#!/usr/bin/env python3
"""
tools/mine_efx_names.py —— 从官方语料收集全部 Entry/Action 名字，生成
`blender_efx_re/semantics/mhws_efx_names.json`。

用途：导入的文件里 Entry/Action 的 nameHash 和它自己的 name 对不上时（被别的工具改过名字、
没跟着改哈希），导出会按 name 重算 nameHash（vendor 行为），游戏如果按哈希找它就找不到了。
面板要告诉用户"原来那个哈希是哪个名字"，才能一键改回去——哈希不可逆，只能拿已知名字表反查。

**只收复算验过的名字。** 每个名字都拿 MurMur3-UTF8 跑一遍，和文件里存的 nameHash 比，不等就
不收（实测 2026-09-26：9221 个文件、100107 个实例，0 例不等，官方文件里两者永远一致）。所以
表里存名字列表就够了，哈希加载时现算，不另存一份可能写错的数字。包括嵌套 PlayEmitter
efxrData 里的 Entry/Action。

用法（仓库根目录，先 `dotnet build tools/EfxBridge -p:LangVersion=preview`）：
    python tools/mine_efx_names.py <语料目录>
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import pathlib
import subprocess
import sys
import tempfile

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "tools"))
from mine_btx_hashes import utf8_hash  # noqa: E402

DLL = _REPO / "tools" / "EfxBridge" / "bin" / "Debug" / "net8.0" / "EfxBridge.dll"
OUT_PATH = _REPO / "blender_efx_re" / "semantics" / "mhws_efx_names.json"


def _walk(data: dict):
    for kind in ("Entries", "Actions"):
        for item in data.get(kind) or []:
            yield item.get("name"), item.get("nameHash")
            for attr in item.get("Attributes") or []:
                if attr.get("efxrData"):
                    yield from _walk(attr["efxrData"])


def _dump(path: str, tmpdir: str, slot: int):
    out = os.path.join(tmpdir, f"{slot}.json")
    result = subprocess.run(["dotnet", str(DLL), "dump", path, out], capture_output=True, text=True)
    if result.returncode:
        return None
    with open(out, encoding="utf-8") as fp:
        return list(_walk(json.load(fp)))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    files = sorted(str(p) for p in pathlib.Path(argv[1]).rglob("*.efx.*"))
    if not files:
        print(f"[ERROR] {argv[1]} 下没有 *.efx.* 文件")
        return 1

    names, mismatched, failed, instances = set(), [], 0, 0
    with tempfile.TemporaryDirectory() as tmpdir, cf.ThreadPoolExecutor(16) as pool:
        # 每个任务用自己的输出槽位（下标），线程之间不会撞文件
        for path, items in zip(files, pool.map(lambda i: _dump(files[i], tmpdir, i), range(len(files)))):
            if items is None:
                failed += 1
                continue
            for name, stored in items:
                instances += 1
                if stored != utf8_hash(name or ""):
                    mismatched.append((os.path.basename(path), name, stored))
                elif name:
                    names.add(name)

    OUT_PATH.write_text(json.dumps({
        "game": "MHWS",
        "_generated_by": "tools/mine_efx_names.py",
        "_note": "官方语料里出现过的 Entry/Action 名字（含嵌套 efxrData），每个都和文件里存的 "
                 "nameHash 复算比对过。哈希加载时现算，见 semantics.lookup_efx_name_hash()。",
        "names": sorted(names),
    }, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(files)} 个文件（{failed} 个 dump 失败），{instances} 个实例，"
          f"{len(mismatched)} 个哈希对不上（已丢弃），收 {len(names)} 个名字 -> {OUT_PATH}")
    for row in mismatched[:20]:
        print("  mismatch:", row)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
