#!/usr/bin/env python3
"""
tools/mine_btx_hashes.py —— 从 010 Editor 模板抽"名字哈希 → 原名"对照表，生成
`blender_efx_re/semantics/mhws_name_hashes.json`。

RE Engine 到处用 MurMur3(UTF-8) 哈希代替字符串存名字：材质属性名、贴图槽名、Expression
参数名，落到文件里全是裸 uint32。面板上直接画 `3292093210` 对使用者毫无意义，画成
`BaseColor` 就能对上 mdf 编辑器里看到的东西。

010 模板（MHWs-EFX-Template / RE_EFX_ENUMS.btx）里攒了三张这样的表：
`MdfPropertyName`（1279 条）、`TexPropertyName`（214 条）、`ExpressionValueHash`（4 条）。

**每一条都要复算哈希验过才收。** 这一点和字段注释那边（tools/mine_btx_semantics.py）性质
完全不同：那边是"社区推测的语义"，只能标 confidence=guess；这边是**可证明的事实**——把名字
拿 MurMur3-UTF8 跑一遍，等于表里那个数字就说明这个名字一定对，不等于就说明表里写错了。
实测 MdfPropertyName / TexPropertyName 是 1279/1279、214/214 全对，ExpressionValueHash
有 1 条对不上（模板自己写错了），那条直接丢掉。

因为验过，查表就没有"猜错"的问题，也不需要限定只在某些字段上用：任何 uint32 只要能在表里
命中，就说明它确实是那个名字的哈希（误命中要求 32 位碰撞，约 1500/2^32）。

用法：
    python tools/mine_btx_hashes.py <RE_EFX_ENUMS.btx 路径>
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

OUT_PATH = (pathlib.Path(__file__).resolve().parent.parent
            / "blender_efx_re" / "semantics" / "mhws_name_hashes.json")

# 模板里这几个 enum 是"名字 -> 哈希"，其余的（BlendType 之类）是普通取值枚举，不在此列
HASH_TABLES = ("MdfPropertyName", "TexPropertyName", "ExpressionValueHash")

_U32 = 0xFFFFFFFF


def _rotl32(x: int, r: int) -> int:
    return ((x << r) | (x >> (32 - r))) & _U32


def murmur3(data: bytes) -> int:
    """照抄 vendor 的 `MurMur3HashUtils.MurMur3Hash`（REE-Lib/Common/MurMur3HashUtils.cs）。

    和教科书版 MurmurHash3 x86_32 有两处不一样，照抄时别"顺手修正"：
      - 种子是 0xffffffff，不是 0
      - 尾块（不足 4 字节的部分）异或进 hash 之后**没有**再做一次 rotl/乘法收尾
    """
    c1, c2 = 0xCC9E2D51, 0x1B873593
    h = 0xFFFFFFFF
    n = len(data)

    for i in range(0, n - (n & 3), 4):
        k = int.from_bytes(data[i:i + 4], "little")
        h ^= (_rotl32((k * c1) & _U32, 15) * c2) & _U32
        h &= _U32
        h = (_rotl32(h, 13) * 5 + 0xE6546B64) & _U32

    rem = n & 3
    if rem:
        tail = data[n - rem:]
        k = int.from_bytes(tail + b"\0" * (4 - rem), "little")
        h ^= (_rotl32((k * c1) & _U32, 15) * c2) & _U32
        h &= _U32

    h ^= n
    h = ((h ^ (h >> 16)) * 0x85EBCA6B) & _U32
    h = ((h ^ (h >> 13)) * 0xC2B2AE35) & _U32
    return (h ^ (h >> 16)) & _U32


def utf8_hash(text: str) -> int:
    return murmur3(text.encode("utf-8"))


def grab_enum(source: str, enum_name: str) -> dict[str, int]:
    """从 btx 文本里抠出 `typedef enum <uint> { A=1, B=2 } EnumName;` 的成员表。"""
    idx = source.find("}%s;" % enum_name)
    if idx < 0:
        idx = source.find("} %s;" % enum_name)
    if idx < 0:
        return {}
    start = source.rfind("typedef enum", 0, idx)
    body = source[start:idx]
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r'^\s*(\w+)\s*=\s*(\d+)\s*,?\s*$', body, re.M)}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    btx = pathlib.Path(argv[1])
    if not btx.exists():
        print(f"找不到模板：{btx}")
        return 1
    source = btx.read_text(encoding="utf-8", errors="replace")

    # 自检：先确认这套 MurMur3 实现和 vendor 一致，不然下面的"验证"本身就是错的
    for name, expect in (("BaseColor", 3292093210), ("BaseMap", 3072153074),
                         ("Metallic", 4178020993)):
        got = utf8_hash(name)
        if got != expect:
            print(f"[ABORT] MurMur3 自检失败：{name} 算出 {got}，应为 {expect}")
            return 1

    table: dict[str, str] = {}
    rejected: list[tuple[str, str, int, int]] = []
    per_table = {}
    for enum_name in HASH_TABLES:
        entries = grab_enum(source, enum_name)
        ok = 0
        for name, declared in entries.items():
            actual = utf8_hash(name)
            if actual != declared:
                rejected.append((enum_name, name, declared, actual))
                continue
            table[str(declared)] = name
            ok += 1
        per_table[enum_name] = (ok, len(entries))

    payload = {
        "game": "MHWS",
        "_generated_by": "tools/mine_btx_hashes.py",
        "_source": "MHWs-EFX-Template / RE_EFX_ENUMS.btx",
        "_note": ("MurMur3(UTF-8) 名字哈希 -> 原名。每条都复算验证过，是事实不是推测；"
                  "整份可重跑覆盖。"),
        "hashes": dict(sorted(table.items(), key=lambda kv: int(kv[0]))),
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"写出 {OUT_PATH}")
    for enum_name, (ok, total) in per_table.items():
        print(f"  {enum_name:<22} 验过 {ok}/{total}")
    print(f"  合计可用条目          {len(table)}")
    if rejected:
        print(f"  哈希对不上、已丢弃    {len(rejected)}")
        for enum_name, name, declared, actual in rejected:
            print(f"     {enum_name}.{name}: 表里写 {declared}，实际是 {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
