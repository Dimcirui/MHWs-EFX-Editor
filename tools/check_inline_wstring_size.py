"""
tools/check_inline_wstring_size.py —— 查"内联宽字符串长度前缀写错了"的复核工具

    python tools/check_inline_wstring_size.py <语料目录> [抽样数量] [--dll <EfxBridge.dll>]

## 它查什么

`.efx` 里的内联宽字符串是 `u32 长度前缀 + UTF-16 内容`，而**长度前缀有两种约定**：

- **单元数**：`字符数 + 1`（含终止符）—— 例：`UVSequence.UVSPath`
- **字节数**：`(字符数 + 1) * 2` —— 例：`Layout.layoutName`、`PlayEfx.efxPath`

哪个字段用哪种是**逐字段固定**的。vendor 用 `[RszInlineWString(ByteSize = true)]` 区分，
但一开始只有两个 uvar 字段标了，其余 18 个该标的全漏了——写出去的前缀是原来的一半，
**游戏直接判文件 Invalid**（实机确认）。

⚠ **所有既有门禁对它免疫**：`roundtrip` 是同一条路跑两遍（两次都写错，`bytes1 == bytes2`
照样成立），Blender 产物和纯 CLI 产物也逐字节相同（两边都经这条路），而"和原文件相同"
按判据本来就不要求。只有把文件放回游戏里、或者像这个脚本一样**和原文件比**才看得见。

## 判据

`dump` -> `load` -> 和原文件逐字节比。凡是差异处的 u32 恰好满足 `原值 == 产物值 * 2`，
就是这类错误；脚本顺带把那个字符串解出来、去 JSON 里反查是哪个字段，直接给出该标
`ByteSize = true` 的名单。

**只读，不改任何文件。**
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import struct
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_DEFAULT_DLL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "EfxBridge", "bin", "Debug", "net8.0", "EfxBridge.dll")


def _owners(node, want, owner=None):
    """在 dump 出来的 JSON 里反查"哪个属性的哪个字段等于这个字符串"。"""
    if isinstance(node, dict):
        current = node.get("$type") or owner
        for key, value in node.items():
            if key == "$type":
                continue
            if isinstance(value, str) and value == want:
                yield (current or "?").split(".")[-1], key
            else:
                yield from _owners(value, want, current)
    elif isinstance(node, list):
        for value in node:
            yield from _owners(value, want, owner)


def _byte_size_prefixes(original: bytes, rebuilt: bytes, load_json):
    """返回 [(偏移, 原值, 产物值, 字符串)]。只收"原值恰好是产物值两倍"的那些。"""
    if len(original) != len(rebuilt) or original == rebuilt:
        return []
    out, seen = [], set()
    for i in (k for k in range(len(original)) if original[k] != rebuilt[k]):
        # 差异字节可能落在 u32 的任何一位上，四种对齐都试一遍
        for back in range(4):
            base = i - back
            if base < 0 or base in seen:
                continue
            a = struct.unpack_from("<I", original, base)[0]
            b = struct.unpack_from("<I", rebuilt, base)[0]
            if a and a == b * 2 and a < 8192:
                seen.add(base)
                text = original[base + 4: base + 4 + a].decode("utf-16-le", "replace")
                out.append((base, a, b, text.rstrip("\x00")))
                break
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus")
    parser.add_argument("count", nargs="?", type=int, default=150,
                        help="抽样文件数（默认 150；给 0 表示全扫）")
    parser.add_argument("--dll", default=_DEFAULT_DLL)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    files = [os.path.join(root, name)
             for root, _dirs, names in os.walk(args.corpus)
             for name in names if ".efx." in name]
    if not files:
        print("[ERROR] %s 下没有 .efx 文件" % args.corpus)
        return 1
    random.seed(args.seed)
    random.shuffle(files)
    if args.count:
        files = files[:args.count]

    tmp = tempfile.mkdtemp(prefix="wstr_check_")
    js = os.path.join(tmp, "d.json")
    out = os.path.join(tmp, "rt.efx.5571972")
    hits = collections.Counter()
    examples = collections.defaultdict(set)
    scanned = affected = 0

    for src in files:
        if subprocess.run(["dotnet", args.dll, "dump", src, js],
                          capture_output=True).returncode != 0:
            continue
        if subprocess.run(["dotnet", args.dll, "load", js, out],
                          capture_output=True).returncode != 0:
            continue
        scanned += 1
        found = _byte_size_prefixes(open(src, "rb").read(), open(out, "rb").read(), js)
        if not found:
            continue
        affected += 1
        data = json.load(open(js, encoding="utf-8"))
        for _base, _a, _b, text in found:
            owners = sorted(set(_owners(data, text)))
            if len(owners) == 1:
                key = "%s.%s" % owners[0]
                examples[key].add(text[:40])
            else:
                # 空串在一个文件里可能对应好几个字段，定不下来就如实说"歧义"，不猜
                key = "<歧义> " + " / ".join("%s.%s" % o for o in owners)
            hits[key] += 1

    print("扫了 %d 个文件，受影响 %d 个" % (scanned, affected))
    if not hits:
        print("没有发现长度前缀写错的字段。")
        return 0
    print("\n该标 ByteSize = true 的字段（出现次数）")
    for key, count in hits.most_common():
        note = ("  例: %s" % sorted(examples[key])[:2]) if key in examples else ""
        print("  %-6d %s%s" % (count, key, note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
