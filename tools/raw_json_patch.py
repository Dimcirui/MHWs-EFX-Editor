# -*- coding: utf-8 -*-
"""
tools/raw_json_patch.py —— 绕过 Blender 插件全部校验/映射表，直接改一个 EfxBridge dump 出来的
JSON 字段再 load 回 .efx

用途：实机排查 `FrameInterpolationType` 等未confirm字段的语义时，要测的原始整数值（比如
Sinusoidal/Elastic 对应的 6/12 之类）往往不在 `clip_fcurve._INTERP_MHWS_TO_BLENDER` 的 6 个
已知值里——Blender 的 `kp.interpolation` 下拉框本身选不出这些值，插件的导出闸门
（`io_tree.check_clip_interpolations`）和 `clip_fcurve.export_curve()` 内部防线也会拦掉任何
不在映射表里的值。这些防线都是故意的，保护的是"正常导出流程"，不该为了实验临时松动。

这个脚本走完全独立的另一条路：从 Blender 正常导出一份能通过闸门的 .efx，用它当"载体"，
在纯 JSON 层面把某个字段改成任意想测的原始值，再用 EfxBridge 的 `load` 直接转回 .efx——
全程不经过 clip_fcurve.py/io_tree.py 的任何校验或映射，改出来的值就是原始整数本身。
不需要 bpy（`blender_efx_re.bridge` 只是个子进程壳子），命令行直接跑。

用法
----
    python tools/raw_json_patch.py <输入 .efx> <输出 .efx> <路径> <新值>

`路径`是点号分隔的键/下标序列，数字段当数组下标，例如：

    Entries.4.Attributes.1.clipData.frames.0.type

先用 `--dump` 只导出 JSON 看看结构，不必每次都猜路径：

    python tools/raw_json_patch.py <输入 .efx> --dump out.json

`新值`按 JSON 字面量解析（`5`/`5.0`/`true`/`"字符串"`），不是原始整数类型时会报错说明。

⚠ 这个脚本产出的文件只用来喂给游戏/EfxBridge 做实机观察，**不要**当成插件本身该支持的
导出路径——插件那边的映射表要等实机确认之后才回去改，改的方式是更新
`clip_fcurve._INTERP_MHWS_TO_BLENDER`，不是把这个脚本的绕过能力搬进正式导出流程。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# 不能 `from blender_efx_re import bridge`——`blender_efx_re/__init__.py` 是 Blender 插件包
# 入口，无条件把 i18n.py/model.py 等一整串会 `import bpy` 的模块都拉进来，在没有 bpy 的纯
# Python 环境（这个脚本就是给这种环境用的）里会直接炸。bridge.py 本身没有 bpy 依赖（只是个
# subprocess+JSON 壳子），绕开包 `__init__.py` 直接按文件路径加载它这一个模块。
_spec = importlib.util.spec_from_file_location(
    "efx_bridge_standalone", _REPO_ROOT / "blender_efx_re" / "bridge.py")
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw  # 解析不出 JSON 字面量就当裸字符串，比报错拒绝更实用


def _walk(data, segments: list[str], for_write: bool):
    """按路径走到倒数第二层，返回 (容器, 最后一段 key/下标)。"""
    cursor = data
    for seg in segments[:-1]:
        if isinstance(cursor, list):
            cursor = cursor[int(seg)]
        else:
            cursor = cursor[seg]
    last = segments[-1]
    if isinstance(cursor, list):
        return cursor, int(last)
    return cursor, last


def patch_json(data: dict, path: str, value) -> None:
    segments = path.split(".")
    container, key = _walk(data, segments, for_write=True)
    old = container[key]
    container[key] = value
    print(f"[patch] {path}: {old!r} -> {value!r}")


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) >= 3 and argv[1] == "--dump":
        src, out = pathlib.Path(argv[0]), pathlib.Path(argv[2])
        data = bridge.dump_efx(src)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"已导出 {out}")
        return 0

    if len(argv) != 4:
        print(__doc__)
        return 1

    src_path, out_path, json_path, raw_value = argv
    src = pathlib.Path(src_path)
    value = _parse_value(raw_value)

    data = bridge.dump_efx(src)
    patch_json(data, json_path, value)
    bridge.load_efx(data, pathlib.Path(out_path))
    print(f"已写出 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
