# -*- coding: utf-8 -*-
"""
`blender_efx_re/name_hash.py` 的哈希必须和 vendor `MurMur3HashUtils.GetUTF8Hash` 逐位一致。

期望值不是拿同一份实现算出来的：`FlowerAction`/`NewAction` 两个是 vendor 写出时自己重算、
再从产物里 dump 出来的 nameHash（2026-09-26，用户问题文件 vfx_it02_01 导出后），`ACT_PT`
是官方语料里 52 个文件原样存着的 Action nameHash——都不经过我们的代码。三个名字的 UTF-8
长度分别是 12/9/6，覆盖了尾块 0/1/2 字节；尾块 3 字节和"一个整块都没有"用官方语料里
名为 `Act` 的 Action 存的 nameHash。

插件包 `blender_efx_re/__init__.py` 要 import bpy，所以这里按文件路径直接加载模块。
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "blender_efx_re" / "name_hash.py"
_spec = importlib.util.spec_from_file_location("name_hash", _PATH)
name_hash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(name_hash)


class TestUtf8Hash(unittest.TestCase):
    def test_matches_vendor_written_values(self):
        cases = {
            "FlowerAction": 1595030427,
            "NewAction": 1569522483,
            "ACT_PT": 1190428671,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(name_hash.utf8_hash(text), expected)

    def test_tail_of_three_bytes(self):
        # "Act" 3 字节：只有尾块、没有整块
        self.assertEqual(name_hash.utf8_hash("Act"), 880260563)


if __name__ == "__main__":
    unittest.main()
