"""
blender_efx_re/asset_paths.py —— 游戏内部路径 -> 磁盘文件

EFX 里引用别的资源用的是**游戏内部路径**，既没有 `natives/STM/` 前缀也没有版本号后缀：

    UVSequence.UVSPath   "Art/VFX/UVS/Common/11_cm_fire_000.uvs"
    .uvs 的贴图表         "Art/VFX/Texture/Common/Sequence/11_fire_000_ALBA.tex"

真实文件是 `natives/STM/<内部路径>.<版本号>`。两条来源：

1. **解包目录**：用户用 RE-Mesh 之类解出来的 `natives/STM/...` 镜像，直接命中就用。
2. **pak 现捞**：配了游戏安装目录就用 `EfxBridge pakextract`（单次 <1 秒），结果缓存到
   用户配置目录，第二次就不用再捞。

两条都找不到 -> 返回 `None`，**调用方负责如实 note**，不要编一个占位资源。

版本号后缀
----------
按扩展名固定（全语料一致）：`.uvs` -> 8，`.tex` -> 241106027。⚠ 这是**从现有语料归纳的**，
不是从文件里读的——游戏更新换了 tex 版本号的话这里要跟着改，所以留成一张可覆盖的表而不是
写死在调用点。

搜索根目录尽量**自动推导**，不新增一堆配置项：从 Asset Browser 已有的语料目录往上走，
找包含 `natives` 的那一层。推导不出来才要用户填。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import bpy

from . import asset_index, bridge

#: 扩展名 -> 版本号后缀（见模块说明）
DEFAULT_VERSIONS = {
    "uvs": 8,
    "tex": 241106027,
    "mdf2": 45,
}

_INTERNAL_PREFIX = "natives/STM"


def _config_file(name: str) -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / name


def _cache_dir() -> Path:
    d = Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_asset_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_game_dir() -> str:
    try:
        return _config_file("mhws_efx_game_dir.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_game_dir(value: str) -> None:
    try:
        _config_file("mhws_efx_game_dir.txt").write_text(
            (value or "").strip(), encoding="utf-8")
    except OSError:
        pass


def search_roots() -> list[Path]:
    """所有可能包含 `natives/STM/` 的根目录。

    从 Asset Browser 的语料目录往上走最多 8 层找 `natives` 的父目录——用户的语料目录通常是
    `<解包根>/EFX/natives/STM/Art/VFX` 这种，往上走就能命中，不用再让他填一遍。
    """
    roots: list[Path] = []
    corpus = (asset_index.get_corpus_dir() or "").strip()
    if corpus:
        cur = Path(corpus)
        for _ in range(8):
            if (cur / "natives").is_dir():
                roots.append(cur)
            if cur.parent == cur:
                break
            cur = cur.parent
    game = get_game_dir().strip()
    if game and (Path(game) / "natives").is_dir():
        roots.append(Path(game))
    # 去重且保序
    seen, out = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def internal_with_suffix(internal_path: str, version: int | None = None) -> str:
    """`Art/VFX/UVS/a.uvs` -> `natives/STM/Art/VFX/UVS/a.uvs.8`（pak 里的完整键）。"""
    internal = str(internal_path).replace("\\", "/").lstrip("/")
    if internal.lower().startswith(_INTERNAL_PREFIX.lower() + "/"):
        internal = internal[len(_INTERNAL_PREFIX) + 1:]
    ext = internal.rsplit(".", 1)[-1].lower() if "." in internal else ""
    ver = version if version is not None else DEFAULT_VERSIONS.get(ext)
    tail = f"{internal}.{ver}" if ver is not None else internal
    return f"{_INTERNAL_PREFIX}/{tail}"


def resolve(internal_path: str, version: int | None = None) -> Path | None:
    """游戏内部路径 -> 本地文件。找不到返回 `None`（调用方负责 note，别编占位资源）。"""
    if not internal_path:
        return None
    full = internal_with_suffix(internal_path, version)
    rel = full[len(_INTERNAL_PREFIX) + 1:]

    # 1. 解包目录镜像
    for root in search_roots():
        cand = root / _INTERNAL_PREFIX.replace("/", "\\") / rel.replace("/", "\\")
        if cand.is_file():
            return cand

    # 2. 之前捞过的缓存
    cached = _cache_dir() / rel.replace("/", "__")
    if cached.is_file():
        return cached

    # 3. 从 pak 现捞
    game = get_game_dir().strip()
    if game and Path(game).is_dir():
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            bridge._run("pakextract", game, full, str(cached))
            if cached.is_file():
                return cached
        except Exception:
            # 捞不到是常态（路径不在 pak 里 / 没装游戏），不该往上抛打断预览
            return None
    return None


def clear_cache() -> int:
    """清掉 pak 捞出来的缓存文件，返回删了几个。"""
    d = _cache_dir()
    n = sum(1 for _ in d.glob("*"))
    shutil.rmtree(d, ignore_errors=True)
    return n
