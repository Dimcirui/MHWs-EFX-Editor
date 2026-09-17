# -*- coding: utf-8 -*-
"""
`blender_efx_re/` 里每一处 `efx_sim` 导入都必须是"相对优先、绝对兜底"的双写法。

## 它防的是什么

插件有**两种加载布局**：

- 装成扩展（`bl_ext.user_default.mhws_efx_editor`）时，`efx_sim` 是 `blender_efx_re`
  的**叔叔包**，只有 `from ..efx_sim import ...` 能找到它；
- 门禁脚本/单测把仓库根塞进 `sys.path` 后直接 `import blender_efx_re`，这时 `..`
  已经越界，只有 `from efx_sim import ...` 能用。

写死任一种，**另一种布局下直接 `ImportError`**。而这类错在真机上的表现往往不是
"报错"，是**静默降级**：`model.py` 的 `formula_canonical` 曾经把 import 放在函数体里、
外面套一个 `except Exception`，装成扩展之后整条公式栏空白、日志里一个字都没有
（2026-09-16 实测踩到）。

## 为什么是纯 Python 静态检查

- `blender_efx_re/*.py` 全都 `import bpy`，**单测里根本 import 不了**；
- Blender 门禁跑的是仓库根布局，**它永远走绝对导入那一支**，扩展布局那条路测不到。

所以只能读源码判形。判据有两条，缺一不可：**成对出现**、**在模块级**（放进函数体里
就可能被调用点的宽 `except` 吞掉）。
"""
from __future__ import annotations

import ast
import os
import unittest

_ADDON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blender_efx_re")


def _module_level_efx_sim_imports(tree):
    """返回 (相对导入的模块级行号, 绝对导入的模块级行号, 函数体内导入的行号)。

    "模块级"包含 `try:`/`except ImportError:` 这一层——双写法本来就长这样。
    """
    relative, absolute, nested = [], [], []

    def scan(body, at_module_level):
        for node in body:
            if isinstance(node, ast.ImportFrom):
                if node.level and node.module == "efx_sim":
                    (relative if at_module_level else nested).append(node.lineno)
                elif not node.level and (node.module or "").split(".")[0] == "efx_sim":
                    (absolute if at_module_level else nested).append(node.lineno)
            elif isinstance(node, ast.Try):
                scan(node.body, at_module_level)
                for handler in node.handlers:
                    scan(handler.body, at_module_level)
                scan(node.orelse, at_module_level)
                scan(node.finalbody, at_module_level)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scan(node.body, False)
            elif isinstance(node, (ast.If, ast.For, ast.While, ast.With)):
                scan(node.body, at_module_level)
                scan(getattr(node, "orelse", []), at_module_level)

    scan(tree.body, True)
    return relative, absolute, nested


class TestAddonEfxSimImports(unittest.TestCase):
    def _sources(self):
        for name in sorted(os.listdir(_ADDON_DIR)):
            if name.endswith(".py"):
                path = os.path.join(_ADDON_DIR, name)
                with open(path, encoding="utf-8") as handle:
                    yield name, ast.parse(handle.read(), filename=path)

    def test_every_import_site_has_both_spellings_at_module_level(self):
        checked = 0
        for name, tree in self._sources():
            relative, absolute, nested = _module_level_efx_sim_imports(tree)
            if not (relative or absolute or nested):
                continue
            checked += 1
            with self.subTest(module=name):
                self.assertFalse(
                    nested,
                    "%s 第 %s 行把 efx_sim 导入放进了函数体——ImportError 会被调用点的 "
                    "except 吞掉，表现成静默降级而不是报错" % (name, nested))
                self.assertTrue(
                    relative and absolute,
                    "%s 只写了一种 efx_sim 导入（相对 %s / 绝对 %s），另一种加载布局下会 "
                    "ImportError" % (name, relative, absolute))
        # 门禁"什么都没测到也全绿"的另一半（验证纪律）：一个导入点都没扫到肯定是路走错了
        self.assertGreaterEqual(checked, 3, "没扫到足够的 efx_sim 导入点，检查 _ADDON_DIR")


if __name__ == "__main__":
    unittest.main()
