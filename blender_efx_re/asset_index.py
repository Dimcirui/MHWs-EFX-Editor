"""
blender_efx_re/asset_index.py —— "attribute 类型 -> 出现过它的语料文件"反查索引加载器

配套 `tools/EfxBridge/Program.cs` 的 `attrindex` 子命令：跑一遍语料目录，产出一份
`{类型名: [相对路径, ...]}` 的 JSON，供资产库面板（`asset_browser.py`）按类型反查文件、
直接导入。只做文件级命中，不记录具体是哪个 entry——找一个"带这个 attr 的参考文件"就够用，
不需要精确定位。

索引文件和语料路径设置都存在 Blender 用户配置目录下（`bpy.utils.user_resource("CONFIG")`），
不放插件目录——理由同 `semantics/__init__.py` / `i18n.py`：插件目录在扩展升级时会被整体替换，
放那儿会导致每次更新都要重新指语料路径、重新跑一遍全量扫描。

加载防御式：索引文件不存在/损坏时返回空索引，不向上抛、不拖垮面板——但用"索引文件存不存在"
（`is_built()`）区分"从没建过索引"和"建过但这个类型确实没有命中"，避免用户以为工具坏了。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import bpy


def _index_path() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_attr_index.json"


def _corpus_dir_file() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_attr_index_corpus_dir.txt"


_index_cache: Optional[dict] = None


def invalidate_cache() -> None:
    """索引文件在磁盘上被重新写过之后（`build_index()` 跑完）调用，逼下次访问重新读盘。"""
    global _index_cache
    _index_cache = None


def is_built() -> bool:
    """索引文件是否存在——区分"从没建过"和"建过但某个类型查不到"，面板要分别提示。"""
    return _index_path().exists()


def _load_index() -> dict:
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    path = _index_path()
    if not path.exists():
        _index_cache = {}
        return _index_cache
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as ex:
        print(f"[MHWs EFX Editor] attr 反查索引加载失败，跳过：{path} ({ex})")
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("types"), dict):
        print(f"[MHWs EFX Editor] attr 反查索引格式不对（缺 \"types\"），跳过：{path}")
        data = {}
    _index_cache = data
    return _index_cache


def stats() -> Optional[dict]:
    """索引的整体统计（扫描文件数/失败数/类型数），从没建过索引时返回 None。"""
    data = _load_index()
    if not data:
        return None
    types = data.get("types") or {}
    return {
        "filesTotal": data.get("filesTotal", 0),
        "filesScanned": data.get("filesScanned", 0),
        "filesFailed": data.get("filesFailed", 0),
        "typeCount": len(types),
    }


def known_types() -> list[str]:
    """索引里实际出现过的 attribute 类型名（`EfxAttributeType` 枚举名），按字母排序。"""
    return sorted((_load_index().get("types") or {}).keys())


def files_for_type(type_name: str) -> list[str]:
    """某个类型命中的文件绝对路径列表，按当前配置的语料根拼回去，并过滤掉已经不存在的
    （语料被移走/改名的兜底）。语料根用的是**当前设置**，不是索引文件里记的
    `corpusRoot`——索引没重建过、语料目录被用户重新指定时，仍然按新设置解析。"""
    rel_paths = (_load_index().get("types") or {}).get(type_name) or []
    corpus_dir = get_corpus_dir()
    if not corpus_dir:
        return []
    out = []
    for rel in rel_paths:
        abs_path = os.path.join(corpus_dir, rel)
        if os.path.isfile(abs_path):
            out.append(abs_path)
    return out


def get_corpus_dir() -> str:
    """当前配置的语料根目录，从没设置过时返回空字符串。"""
    try:
        return _corpus_dir_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_corpus_dir(path: str) -> None:
    try:
        _corpus_dir_file().write_text(path or "", encoding="utf-8")
    except OSError as ex:
        # 写不进去不该拦住这次设置本身——本次会话内 wm 属性仍然生效，只是下次开 Blender 会丢。
        print(f"[MHWs EFX Editor] 语料路径设置写入失败，本次会话仍然生效：{ex}")


def build_index(corpus_dir: str) -> dict:
    """跑一遍 EfxBridge 的 `attrindex`，重建索引文件并刷新内存缓存，返回这次扫描的统计信息。

    真正的批处理调用见 `bridge.build_attr_index()`——这里只负责"存哪、缓存怎么刷新"，
    不重复实现调用 CLI 的逻辑。"""
    from . import bridge  # 延迟导入，避免和 bridge.py 之间出现模块级循环依赖

    envelope = bridge.build_attr_index(corpus_dir, _index_path())
    invalidate_cache()
    return envelope
