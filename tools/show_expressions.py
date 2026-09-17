"""
tools/show_expressions.py —— 把一个 `.efx` 里的 Expression 公式全部打出来

    python tools/show_expressions.py <文件.efx.版本号> [--dll <EfxBridge.dll>]

逐条显示：挂在哪个 attribute 的哪个 bit（字段名）、vendor 文本、**规范记法**、以及
这棵树的参数表（`source` 决定一个标识符是引擎喂的外部变量还是文件里的具名常量）。

## 为什么需要它

进游戏之前先确认"我以为我填的"和"文件里真有的"是同一个东西。实测踩过两次：

- 在公式栏里打了字，但插件那一侧抛了异常没写进去，`formula` 还停在默认值 `0`——
  进游戏看到的是**上一次**的效果，很容易当成"这条公式的语义不对"。
- 公式里写了 `PI`，但树的参数表里没有对应的 `Constant` 条目，引擎把它读成 0。
  参数表在界面上看不见，只能从文件里看。

**不改文件**，只读。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from efx_sim import expr, expr_text  # noqa: E402

_SOURCE_NAMES = {0: "Parameter", 1: "Constant", 2: "External", -1: "Unknown"}

_DEFAULT_DLL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "EfxBridge", "bin", "Debug", "net8.0", "EfxBridge.dll")


def _dump(efx_path, dll):
    with tempfile.TemporaryDirectory(prefix="show_expr_") as tmp:
        out = os.path.join(tmp, "dump.json")
        run = subprocess.run(["dotnet", dll, "dump", efx_path, out],
                             capture_output=True, text=True)
        if run.returncode != 0 or not os.path.exists(out):
            raise SystemExit("EfxBridge dump 失败：\n%s\n%s" % (run.stdout, run.stderr))
        with open(out, encoding="utf-8") as handle:
            return json.load(handle)


def _attributes(data):
    """(路径, attribute dict) —— 含 Actions 和内嵌 efxrData 的递归。"""
    def walk(container, path):
        for i, entry in enumerate(container.get("Entries") or []):
            for j, attr in enumerate(entry.get("Attributes") or []):
                yield "%sEntries[%d]/Attributes[%d]" % (path, i, j), attr
                nested = attr.get("efxrData")
                if isinstance(nested, dict):
                    yield from walk(nested, "%sEntries[%d]/Attributes[%d]/" % (path, i, j))
        for i, action in enumerate(container.get("Actions") or []):
            for j, attr in enumerate(action.get("Attributes") or []):
                yield "%sActions[%d]/Attributes[%d]" % (path, i, j), attr
    return walk(data, "")


def _canonical(text):
    try:
        return expr_text.vendor_to_canonical(text)
    except expr.ExprError as exc:
        return "<转换失败: %s>" % exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("efx")
    parser.add_argument("--dll", default=_DEFAULT_DLL)
    args = parser.parse_args(argv)

    data = _dump(args.efx, args.dll)
    total = 0
    for path, attr in _attributes(data):
        tree = attr.get("Expression") or {}
        curves = tree.get("parsedExpressions") or []
        if not curves:
            continue
        bits = attr.get("ExpressionBits") or {}
        names = bits.get("bitNames") or []
        order = sorted(bits.get("bits") or [])
        print("%s  %s" % (path, (attr.get("$type") or "").split(".")[-1]))
        for index, entry in enumerate(curves):
            bit = order[index] if index < len(order) else None
            # bitNames 是**按 bit 下标**索引的全表，不是按曲线顺序
            field = names[bit] if (bit is not None and bit < len(names)) else "?"
            text = entry.get("expression", "")
            print("   bit %-3s %-14s %s" % (bit, field, text))
            print("   %19s= %s" % ("", _canonical(text)))
            for param in (entry.get("parameters") or []):
                source = _SOURCE_NAMES.get(param.get("source"), param.get("source"))
                # 只有 Constant 的值有意义；External 的 constantValue 恒 0（引擎运行时喂）
                note = ("  value=%s" % param.get("constantValue")) if param.get("source") == 1 else ""
                print("   %19s  %-9s hash=%s%s"
                      % ("", source, param.get("parameterNameHash"), note))
            total += 1
        print()
    if not total:
        print("这个文件里一条 Expression 公式都没有。")
    else:
        print("共 %d 条公式。" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
