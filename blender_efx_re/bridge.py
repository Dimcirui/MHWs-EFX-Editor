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
        # 防御性兜底：EfxBridge 现在显式钉死 Console.OutputEncoding = UTF8（见
        # Program.cs 顶部说明），正常情况下不会再触发这个分支。但 stdout/stderr 是纯日志/
        # 报错文本，不是 JSON 数据交换通道（那条路走的是临时文件），这里从严解码没有任何
        # 好处，反而在极端情况下会在 subprocess 内部的 reader 线程里炸出 UnicodeDecodeError
        # ——那个线程没有 try/except，异常不会传回主线程，只会把吓人的 traceback 打印到控制台，
        # 看着像插件崩了。改成 replace，容忍不了的字节显示成 “?” 就行，不为了日志文本的完整性
        # 冒着崩线程的风险。
        errors="replace",
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


def dump_uvs(uvs_path: str | Path) -> dict:
    """读取一个 .uvs 文件，返回 UvsFile 对象图的 JSON 中间表示（dict）。

    形状是 `{fileVersion, header: {attributes}, textures: [...], sequences: [...]}`——
    `fileVersion` 是读取时 `FileHandler.FileVersion`（从文件名 `.uvs.8` 的版本号段解析出来的），
    UVS 的版本号处理方式和 EFX 不同（UVS Header 本身不存 Version 字段，门控直接查
    `handler.FileVersion`），见 tools/EfxBridge/Program.cs "uvsdump / uvsload 子命令"一节。
    `load_uvs()` 需要原样带回这个值，不能指望从输出路径的文件名重新解析。
    """
    with tempfile.TemporaryDirectory(prefix="mhws_uvs_dump_") as tmpdir:
        json_path = Path(tmpdir) / "dump.json"
        _run("uvsdump", str(uvs_path), str(json_path))
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)


def load_uvs(data: dict, uvs_out_path: str | Path) -> None:
    """把 JSON 中间表示（dict，形状同 dump_uvs()）写回一个 .uvs 文件。"""
    with tempfile.TemporaryDirectory(prefix="mhws_uvs_load_") as tmpdir:
        json_path = Path(tmpdir) / "load.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        _run("uvsload", str(json_path), str(uvs_out_path))


def convert_tex_to_dds(tex_path: str | Path, dds_out_path: str | Path) -> None:
    """把一个 .tex 文件转成 Blender 原生能读的 .dds，供 UVS 图形编辑界面把 pattern 矩形画在
    真实贴图上（PLAN.md Phase 2 Step 4）。vendor 自带 `TexFile.SaveAsDDS()`，不需要我们自己
    解压/转换 GPU 纹理格式。"""
    _run("tex2dds", str(tex_path), str(dds_out_path))


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

    这里吐出来的默认值就是 C# 的字段默认值（数值全 0），不是"游戏里好看的默认值"——比如
    Transform3D 新建出来 LocalScale 是 (0,0,0) 而不是 (1,1,1)。这是有意的：本函数只做
    "调 CLI、原样转发"，不解释字段含义（本文件开头的架构约束）。全语料统计出来的"合理默认值"
    （置信度不够的字段仍然留着这份零值）在上一层合并进来，见
    `structure_ops.add_attribute()` / `semantics.get_attribute_defaults()`。
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


def build_attr_index(corpus_dir: str | Path, out_path: str | Path) -> dict:
    """扫一遍语料目录，建一份"attribute 类型 -> 出现过它的文件（相对路径）列表"的反查索引。

    跟 `_run_json()` 的临时目录模式不同：`out_path` 是调用方指定的持久化位置（资产库面板
    要把这份索引存到 Blender 用户配置目录、下次启动接着用），不是用完即丢。这也是第一个
    跑全语料批处理（而不是单文件 request/response）的 Python 调用点，语料上千个文件、耗时
    以分钟计，不设超时（`_run()` 本来就没有 timeout 参数）——调用方（资产库的 Rebuild 算子）
    自己负责给用户一个"正在扫描，请稍候"的等待反馈。
    """
    _run("attrindex", str(corpus_dir), str(out_path))
    with open(out_path, "r", encoding="utf-8") as f:
        return json.load(f)
