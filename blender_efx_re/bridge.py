"""
blender_efx_re/bridge.py —— 调用 tools/EfxBridge（C#）的薄封装

约定的 CLI 契约（见 tools/EfxBridge/Program.cs 文件头注释）：
    dotnet <dll> dump <efx 文件路径> <json 输出路径>
    dotnet <dll> load <json 文件路径> <efx 输出路径>

这一层只负责"文件 → 结构化中间表示 → 文件"的批处理调用（PLAN.md 架构决策第 3 点），
不解释 JSON 里的字段含义——那是 fields.py/operators.py 往上的事。中间表示是 EfxFile
对象图的直译 JSON（字段名来自 C# 类本身），不是精简过的 Blender schema。

2026-07-04 vendor 升级（`ebb1bc7`）已解决 EFXExpressionDataBase 的多态反序列化问题（自定义
JsonPolymorphismOptions），本文件上一版记录的"Expression 数据 load 会抛
NotSupportedException"缺口已不存在，见 docs/TOPLEVEL_STRUCTURE.md。dump/load 现在还会
调用 vendor 的 `EfxFile.ParseExpressions()`/`FlattenExpressionTrees()`，把公式在人类可读
文本和二进制后缀栈之间转换，见 tools/EfxBridge/Program.cs。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

_ADDON_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DLL = _ADDON_ROOT / "tools" / "EfxBridge" / "bin" / "Debug" / "net8.0" / "EfxBridge.dll"


class BridgeError(RuntimeError):
    """EfxBridge CLI 调用失败（非零退出码），message 是 CLI 的 stdout+stderr。"""


def get_dotnet_exe() -> str:
    """开发期假设 dotnet 在 PATH 上。以后如需支持自定义路径，加到 AddonPreferences 里。"""
    exe = shutil.which("dotnet")
    if not exe:
        raise BridgeError("找不到 dotnet 可执行文件，请确认已安装 .NET 8 SDK/Runtime 并加入 PATH。")
    return exe


def get_bridge_dll() -> Path:
    """开发期默认指向仓库内 tools/EfxBridge 的 Debug 构建产物。"""
    if not _DEFAULT_DLL.exists():
        raise BridgeError(
            f"找不到 EfxBridge.dll：{_DEFAULT_DLL}\n"
            "请先构建：dotnet build tools/EfxBridge -p:LangVersion=preview"
        )
    return _DEFAULT_DLL


def _run(*args: str) -> str:
    dotnet = get_dotnet_exe()
    dll = get_bridge_dll()
    result = subprocess.run(
        [dotnet, str(dll), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise BridgeError((result.stdout or "") + (result.stderr or ""))
    return result.stdout


def dump_efx(efx_path: str | Path) -> dict:
    """读取一个 .efx 文件，返回 EfxFile 对象图的 JSON 中间表示（dict）。"""
    with tempfile.TemporaryDirectory(prefix="mhws_efx_dump_") as tmpdir:
        json_path = Path(tmpdir) / "dump.json"
        _run("dump", str(efx_path), str(json_path))
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)


def load_efx(data: dict, efx_out_path: str | Path) -> None:
    """把 JSON 中间表示（dict）写回一个 .efx 文件。"""
    with tempfile.TemporaryDirectory(prefix="mhws_efx_load_") as tmpdir:
        json_path = Path(tmpdir) / "load.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        _run("load", str(json_path), str(efx_out_path))


def check_expression(formula: str) -> str | None:
    """校验一条 Expression 公式文本（`EfxExpressionStringParser.Parse` 的语法），合法返回
    None，否则返回错误信息。给 panels.py 的"Validate"按钮用，让用户不用跑一次完整导出就能
    知道公式写错了——真正的导出仍然靠 load_efx() 失败时抛 BridgeError 兜底，这里只是提前
    反馈，不是唯一的校验关卡。"""
    try:
        _run("exprcheck", formula)
    except BridgeError as ex:
        return str(ex)
    return None
