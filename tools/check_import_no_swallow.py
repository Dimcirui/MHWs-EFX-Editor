# -*- coding: utf-8 -*-
"""tools/check_import_no_swallow.py —— 导入路径不许吞异常

    python tools/check_import_no_swallow.py

退出码 0/1。不需要 Blender，也不需要 bpy——只做 AST 分析。

## 它防的是什么

以前 CLAUDE.md 里有一条铁律叫"解析失败就整文件拒绝导入"：绝不吞掉异常、塞一个半成品结构
进 Blender 场景。用户在错误结构上改完再导出，比"根本没导入成功"难排查得多。

这条规则现在不在 CLAUDE.md 里了，因为它能被机械检查——这个脚本就是那个检查。当时删掉它的
依据是：导入路径上一个宽异常捕获都没有，所以任何异常都会一路抛穿，整文件失败是结构性的。
但"现在没有"不等于"以后不会有"，所以要把这个状态钉住。

## 判据

`_GUARDED` 里那几个模块中，凡是满足下面两条的 `except` 子句都算违规：

1. 捕获面是宽的——裸 `except:`、`except Exception`、`except BaseException`；
2. 处理体里**没有重新抛出**（任意深度找不到 `raise`）。

捕获了又原样抛出去的不算吞——那是加上下文，不是咽下去。窄捕获（`except KeyError` 之类）
也不算：那说明作者知道自己在处理哪一种具体情况。

## 真要加一个怎么办

先想清楚这个异常被吃掉之后，用户拿到的是不是一棵不完整的树。如果是，那就不该吃。

确实需要（比如可选的第三方插件没装、读一个纯装饰性的缩略图失败），在那一行结尾写上
`# allow-swallow: <一句话说明为什么这不会产出半成品结构>`，这个脚本就会放过它。注释是给
下一个人看的，别写空话。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: 导入路径上的模块——文件字节变成 Blender 场景要经过的每一层。
_GUARDED = (
    "blender_efx_re/bridge.py",      # 调 EfxBridge，把 .efx 变成 JSON
    "blender_efx_re/io_tree.py",     # JSON -> Blender 数据块
    "blender_efx_re/operators.py",   # 导入/导出算子本身
    "blender_efx_re/uvs_io.py",      # .uvs 的同一条路
)

_BROAD = {"Exception", "BaseException"}

_ALLOW = "allow-swallow:"


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True  # 裸 except:
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(n, ast.Name) and n.id in _BROAD for n in names)


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def main() -> int:
    violations: list[str] = []
    missing: list[str] = []
    checked = 0

    for rel in _GUARDED:
        path = _REPO_ROOT / rel
        if not path.exists():
            missing.append(rel)
            continue
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        for handler in (n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ExceptHandler)):
            checked += 1
            if not _is_broad(handler) or _reraises(handler):
                continue
            line = lines[handler.lineno - 1]
            if _ALLOW in line:
                continue
            violations.append(f"{rel}:{handler.lineno}: {line.strip()}")

    # 门禁"什么都没测到"也会全绿——这里的目标结构是 except 子句本身。一条都没有反而可疑
    # （文件被重命名了、_GUARDED 写错了），所以要能分辨"确实没有"和"根本没找到文件"。
    if missing:
        print("FAIL 这些被守护的模块找不到，_GUARDED 该更新了：")
        for rel in missing:
            print(f"  {rel}")
        return 1

    if violations:
        print("FAIL 导入路径上有吞掉异常的宽捕获：")
        for v in violations:
            print(f"  {v}")
        print()
        print("解析失败必须整文件拒绝导入，不能塞一个半成品结构进场景。")
        print("确实需要吃掉这个异常的话，在那一行加 `# allow-swallow: <为什么>`。")
        return 1

    print(f"PASS 导入路径无吞异常的宽捕获（{len(_GUARDED)} 个模块，扫过 {checked} 个 except 子句）")
    return 0


if __name__ == "__main__":
    # 未捕获异常必须变成非零退出码，不能让门禁"抛完还退 0"。
    try:
        code = main()
    except Exception:
        import traceback

        traceback.print_exc()
        code = 1
    sys.exit(code)
