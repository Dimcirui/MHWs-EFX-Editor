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

2026-09-09 vendor 升级（`9d9b39e`）：公式文本语法多了两样东西——MHWilds 专属函数
（`Unary11`/`Unary12`/`Func18`~`Func21`）和 multi root value 分隔符 `|`（形如 `a | b`，
一条曲线带两个根值）。前者在此之前会被当成 1 参函数少读参数、后者的第二个根值会被直接
丢弃，都是静默出错，这是升级的主要动机。`Func18`/`Func19`/`Func20` 目前**写不回去**
（上游解析器 bug，见 KNOWN_UPSTREAM_ISSUES.md #6），会在 check_expression()/load_efx()
上抛出来，不会静默写坏文件。
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


def new_attribute(type_name: str) -> dict:
    """凭空造一个指定类型的空白 attribute，返回和 dump 里同一形状的 dict（含 `$type`）。

    不需要我们自己攒模板/预设：vendor 每个 attribute 类型都是真实的 C# 类，`new` 出来就是
    一份带默认值的实例，序列化规则和 dump 完全一致，直接喂给 io_tree.build_attribute_object()
    即可。姊妹项目 EFX-Editor 要靠人工攒预设字节，是因为它没有这层类型化对象模型。

    注意默认值就是 C# 的字段默认值（数值全 0），不是"游戏里好看的默认值"——比如 Transform3D
    新建出来 LocalScale 是 (0,0,0) 而不是 (1,1,1)。这是有意的：我们没有依据去替 Capcom 定
    "合理默认值"，与其猜一个，不如让用户看到真实的零值自己填。
    """
    return _run_json("new", "attribute", type_name)


def new_entry() -> dict:
    """凭空造一个空白 Entry（无 attribute）。"""
    return _run_json("new", "entry")


def new_action() -> dict:
    """凭空造一个空白 Action（无 attribute）。"""
    return _run_json("new", "action")


def _run_json(*args: str) -> dict:
    """跑一个把结果写进 JSON 文件的子命令，读回来返回 dict。"""
    with tempfile.TemporaryDirectory(prefix="mhws_efx_new_") as tmpdir:
        json_path = Path(tmpdir) / "out.json"
        _run(*args, str(json_path))
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
