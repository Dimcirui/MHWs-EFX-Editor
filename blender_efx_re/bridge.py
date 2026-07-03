"""
blender_efx_re/bridge.py —— 调用 tools/EfxBridge（C#）的薄封装

约定的 CLI 契约（见 tools/EfxBridge/Program.cs 文件头注释）：
    dotnet <dll> dump <efx 文件路径> <json 输出路径>
    dotnet <dll> load <json 文件路径> <efx 输出路径>

这一层只负责"文件 → 结构化中间表示 → 文件"的批处理调用（PLAN.md 架构决策第 3 点），
不解释 JSON 里的字段含义——那是 fields.py/operators.py 往上的事。中间表示是 EfxFile
对象图的直译 JSON（字段名来自 C# 类本身），不是精简过的 Blender schema。

已知缺口：EFXExpressionDataBase（Expression 公式引擎子系统用到的表达式节点树）目前
无法反序列化——RE-Engine-Lib 自带的 EfxJsonTypeResolver 只给 EFXAttribute 注册了
多态 $type 判别，没有覆盖这一层嵌套的多态类型。带 Expression 数据的 attribute 在
dump（读→序列化）阶段没问题，但 load（反序列化→写）会抛
System.NotSupportedException。这与 PLAN.md 架构决策第 8 点一致——Expression 是独立
子系统，可以放到后面阶段做，不卡其他功能。当前调用方应预期这类文件在完整改动往返时
可能失败，捕获 BridgeError 后按第 9 点原则整文件拒绝，不做半成品处理。
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
