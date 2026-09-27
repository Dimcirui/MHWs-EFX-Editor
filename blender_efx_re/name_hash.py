"""
blender_efx_re/name_hash.py —— Entry/Action 的 nameHash 算法（零 bpy，单测直接按文件路径加载）

vendor 写出时按 name 重算 nameHash（EfxFile.cs `EFXEntry.DoWrite` / `EFXAction.DoWrite`，
`MurMur3HashUtils.GetUTF8Hash(name)`），不管导入时文件里存的是什么。官方文件里两者永远一致
（2026-09-26 全语料 100107 个 Entry/Action 实例，0 例不一致），对不上只出现在被别的工具改过
名字、却没跟着改哈希的文件里——游戏如果按哈希找这个 Entry/Action，导出之后就找不到了。
导入时靠这里判出这种情况，见 io_tree.name_hash_drift()。
"""

from __future__ import annotations

_U32 = 0xFFFFFFFF


def _rotl32(x: int, r: int) -> int:
    return ((x << r) | (x >> (32 - r))) & _U32


def murmur3(data: bytes) -> int:
    """照抄 vendor 的 `MurMur3HashUtils.MurMur3Hash`（REE-Lib/Common/MurMur3HashUtils.cs），
    和 tools/mine_btx_hashes.py 里那份是同一个算法。

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
        h = (_rotl32(h, 13) * 5 + 0xE6546B64) & _U32

    tail = data[n - (n & 3):]
    if tail:
        k = int.from_bytes(tail, "little")
        h ^= (_rotl32((k * c1) & _U32, 15) * c2) & _U32

    h ^= n
    h = ((h ^ (h >> 16)) * 0x85EBCA6B) & _U32
    h = ((h ^ (h >> 13)) * 0xC2B2AE35) & _U32
    return h ^ (h >> 16)


def utf8_hash(text: str) -> int:
    """`MurMur3HashUtils.GetUTF8Hash`：Entry/Action 的 nameHash 就是这个。"""
    return murmur3(text.encode("utf-8"))
