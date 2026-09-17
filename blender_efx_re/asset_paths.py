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

**解包目录首先顺着「这个 efx 自己在哪」往上找**（`roots_from()` / `search_roots()`）
------------------------------------------------------------------------------
一个 `.efx` 引用的 `.mesh` / `.uvs` / `.tex` 绝大多数情况就躺在它自己那棵 `natives/STM/`
树里——官方解包目录如此，用户的 mod 工程目录更是如此（那里只有他自己新做的那几个文件，
而那几个正是他想看的）。所以根目录的第一来源是**被导入的那个 efx 路径向上回溯**，
Asset Browser 的语料目录只是**兜底**：它是"随便一堆官方 efx 放哪儿"的设置，和当前这个
文件没有必然关系，拿它当首选会在 mod 工程场景下静默加载错文件（同名不同内容，界面上
完全看不出来）。

版本号后缀
----------
按扩展名固定（全语料一致）：`.uvs` -> 8，`.tex` -> 241106027，`.mesh` -> 241111606。
⚠ 这是**从现有语料归纳的**，不是从文件里读的——游戏更新换了版本号的话这里要跟着改，
所以留成一张可覆盖的表而不是写死在调用点。

`.tex` 有两份，要的是 `streaming/` 那份
---------------------------------------
同一张贴图在游戏里存两遍：`natives/STM/<内部路径>` 是**降采样过的小图**，
`natives/STM/streaming/<内部路径>` 才是全分辨率。2026-09-13 实测
`Art/VFX/Texture/Common/Sequence/11_glow_000_ALPG.tex`：非 streaming 那份 128x128 / 1 mip
（16448 字节），streaming 那份 512x512 / 3 mip（344176 字节）。两份都是结构完整的 TEX、
都能解码成功，**光看解码结果发现不了自己拿错了**，只是序列帧会糊——所以 `.tex` 一律
streaming 优先。其它扩展名只有一份。

搜索根目录全部**自动推导**，不新增一堆配置项：从 efx 自己的位置（以及场景里已导入的
其它 efx、Asset Browser 的语料目录）往上走，找包含 `natives` 的那一层。都推导不出来时
才轮到用户填的游戏安装目录 + pak 现捞。

pak 捞出来的东西按 `natives/STM/` 原样镜像
-----------------------------------------
缓存目录里保持和游戏一样的目录结构，不拍平成一个文件名。理由不只是好看：RE Mesh Editor
是拿 `.mdf2` 的路径里那段 `.../natives/<平台>` 反推贴图根目录的（`splitNativesPath()`），
拍平之后它反推不出来，材质会全部丢贴图。
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
    "mesh": 241111606,
}

_INTERNAL_PREFIX = "natives/STM"
#: `natives/STM/` 之下、全分辨率贴图那一份多出来的一层（见模块说明）
_STREAMING_SEGMENT = "streaming"


def _config_file(name: str) -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / name


def _cache_dir() -> Path:
    d = Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_asset_cache"
    d.mkdir(parents=True, exist_ok=True)
    # 旧版把 pak 产物拍平成 `Art__VFX__…__x.tex.241106027` 直接扔在这一层；改成
    # `natives/STM/` 镜像之后那些文件谁也不会再读到（新逻辑只看 natives/ 子目录）。
    # 顺手清掉，别留一堆谁也不认的孤儿——镜像本身从不往这一层放文件，判据不会误伤。
    for stale in d.iterdir():
        if stale.is_file():
            try:
                stale.unlink()
            except OSError:
                pass
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


def roots_from(path) -> list[Path]:
    """从一个文件/目录一路往上走，收集所有"下面有 `natives/` 的那一层"，**近的在前**。

    这是资源解析的**首选**依据：一个 `.efx` 引用的 `.mesh` / `.uvs` / `.tex` 绝大多数情况
    就躺在它自己那棵 `natives/STM/` 树里——不管那是解包目录还是用户的 mod 工程目录。
    传 `.efx` 本身或它所在目录都行。

    走到盘符根为止，不设层数上限：`natives/STM/Art/VFX/EffectEditor/Common/guide` 这种
    深度就已经 7 层了，再深一点的目录用固定上限会静默漏掉（漏掉的表现是"引用的资源找不到"，
    很难联想到是搜索深度的问题）。每层只做一次 `is_dir()`，代价可以忽略。

    一层目录同时是"`natives` 的父目录"和别的东西没关系——多命中几个根只是多几次
    `is_file()`，比漏掉强。
    """
    text = str(path or "").strip()
    if not text:
        return []
    cur = Path(text)
    if not cur.is_dir():
        cur = cur.parent   # 传的是文件（或者已经不存在的路径），从它所在目录起步
    roots: list[Path] = []
    while True:
        try:
            if (cur / _INTERNAL_PREFIX.split("/")[0]).is_dir():
                roots.append(cur)
        except OSError:
            pass
        if cur.parent == cur:
            return roots
        cur = cur.parent


def _loaded_efx_roots() -> list[Path]:
    """场景里已经导入的每个 EFX_ROOT 各自向上推出来的根（见 `Collection.efx_source_dir`）。

    让"顺着当前这个 efx 自己那棵树找资源"这件事对**所有**消费者都成立，而不只是导入算子
    ——粒子预览、UVS 预览图走的也是 `resolve()`，它们手上只有一个 attribute 对象，没有
    文件路径可传。
    """
    roots: list[Path] = []
    for collection in bpy.data.collections:
        # getattr 带默认值：`efx_source_dir` 是注册在 Collection 上的 RNA 属性，
        # 没注册（单测/未 register）或旧场景没这个值时都该安静地跳过，不是错误。
        source_dir = getattr(collection, "efx_source_dir", "") or ""
        if source_dir:
            roots.extend(roots_from(source_dir))
    return roots


def search_roots(near=None) -> list[Path]:
    """所有可能包含 `natives/STM/` 的根目录，**按优先级排**：

    1. `near`（正在处理的那个 `.efx` 的路径）向上推出来的——最贴近"这个文件引用的东西"；
    2. 场景里已导入的各个 EFX_ROOT 向上推出来的；
    3. Asset Browser 的语料目录向上推出来的——它是"随便一堆官方 efx 放哪儿"的设置，
       和当前这个文件没有必然关系，所以排在后面而不是前面；
    4. 用户填的游戏安装目录（它本身含 `natives/` 时才算，通常不含——那条路走 pak 现捞）。
    """
    roots: list[Path] = []
    roots.extend(roots_from(near))
    roots.extend(_loaded_efx_roots())
    roots.extend(roots_from(asset_index.get_corpus_dir()))
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
    ext = internal_extension(internal)
    ver = version if version is not None else DEFAULT_VERSIONS.get(ext)
    tail = f"{internal}.{ver}" if ver is not None else internal
    return f"{_INTERNAL_PREFIX}/{tail}"


def internal_extension(internal_path: str) -> str:
    """`Art/VFX/UVS/a.uvs` -> `uvs`（小写，没有扩展名时空串）。内部路径不带版本号后缀，
    所以就是最后一个点之后那一段。"""
    internal = str(internal_path).replace("\\", "/")
    name = internal.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _relative_candidates(rel: str, ext: str) -> list[str]:
    """`natives/STM/` 之下该按什么顺序找这个文件（相对 `natives/STM/` 的路径）。

    `.tex` 两份，全分辨率那份在 `streaming/` 下，优先（见模块说明）；其它扩展名只有一份。
    """
    if ext == "tex":
        return [f"{_STREAMING_SEGMENT}/{rel}", rel]
    return [rel]


def cache_natives_root() -> Path:
    """pak 捞出来的东西镜像在哪个 `natives/STM` 下。给需要把这个根交给别的插件的调用方用
    （RE Mesh Editor 就是拿 `.mdf2` 路径里这一段反推贴图根的）。"""
    return _cache_dir().joinpath(*_INTERNAL_PREFIX.split("/"))


def resolve(internal_path: str, version: int | None = None, near=None) -> Path | None:
    """游戏内部路径 -> 本地文件。找不到返回 `None`（调用方负责 note，别编占位资源）。

    `near`：正在处理的那个 `.efx` 的路径。给了就**优先**在它自己那棵 `natives/` 树里找
    （见 `search_roots()` 的优先级），这是"一个 efx 引用的东西通常就在它旁边"这条常识。
    """
    if not internal_path:
        return None
    full = internal_with_suffix(internal_path, version)
    rel = full[len(_INTERNAL_PREFIX) + 1:]
    return _resolve_candidates(
        _relative_candidates(rel, internal_extension(internal_path)), near)


def natives_root_of(main_local, internal_path: str,
                    version: int | None = None) -> Path | None:
    """一个已解析出来的本地文件，它自己躺在哪个 `.../natives/STM` 下面。

    不是靠"路径里找 `natives` 这一段"猜的，是按内部路径的段数从文件往上数——同一个词
    在路径主干里再出现一次也不会认错。别的插件要的贴图根目录就是这个值（RE Mesh Editor
    的 `splitNativesPath()` 算的是同一个东西）。
    """
    if not internal_path:
        return None
    full = internal_with_suffix(internal_path, version)
    rel = full[len(_INTERNAL_PREFIX) + 1:]
    try:
        return Path(main_local).resolve().parents[len(rel.split("/")) - 1]
    except (OSError, IndexError):
        return None


def ensure_streaming_companion(main_local, internal_path: str,
                               version: int | None = None) -> Path | None:
    """保证主文件**自己那个** natives 根下的 `streaming/<相对路径>` 伴生文件存在，返回它。

    `.mesh` 需要这个：MHWs 的网格**顶点缓冲在 streaming 那一份里**，主文件只有头和骨架。
    RE Mesh Editor 读主文件时按 `<natives 根>/streaming/<相对路径>` **自己去拼**那一份
    （`file_re_mesh.readREMesh()`），我们没法替它传路径——所以伴生文件必须和主文件躺在
    同一个 natives 根下。实测（2026-09-13）：`11_fulgurite_01.mesh` 缺伴生文件直接抛
    "Streaming mesh file is missing" 导入失败；`11_plane.mesh` 这种没有 streaming 份的
    小静态网格不受影响。

    主文件在用户自己的解包目录里、伴生份却不在：返回 `None`，**不往别人的解包目录里写东西**
    （那种情况该由用户自己补解包，我们只如实说）。主文件是我们从 pak 捞进缓存镜像的，
    才顺手把伴生那份也捞进来。
    """
    if not internal_path:
        return None
    full = internal_with_suffix(internal_path, version)
    rel = full[len(_INTERNAL_PREFIX) + 1:]
    segments = rel.split("/")
    root = natives_root_of(main_local, internal_path, version)
    if root is None:
        return None
    if root.name.lower() == _STREAMING_SEGMENT:
        return None   # 传进来的本来就是伴生文件，没有"伴生的伴生"

    companion = root.joinpath(_STREAMING_SEGMENT, *segments)
    if companion.is_file():
        return companion
    if root != cache_natives_root().resolve():
        return None

    game = get_game_dir().strip()
    if not game or not Path(game).is_dir():
        return None
    try:
        companion.parent.mkdir(parents=True, exist_ok=True)
        bridge._run("pakextract", game,
                    f"{_INTERNAL_PREFIX}/{_STREAMING_SEGMENT}/{rel}", str(companion))
    except Exception:
        # 没有 streaming 份是正常的（小网格就没有），不是错误
        return None
    return companion if companion.is_file() else None


def _resolve_candidates(candidates: list[str], near=None) -> Path | None:
    """按"解包目录 -> 已捞过的缓存 -> pak 现捞"依次试一组候选相对路径。"""
    # 1. 解包目录镜像（根的优先级见 search_roots()）
    for root in search_roots(near):
        for cand_rel in candidates:
            cand = root.joinpath(*_INTERNAL_PREFIX.split("/"), *cand_rel.split("/"))
            if cand.is_file():
                return cand

    # 2. 之前捞过的缓存（同样按 natives/STM 镜像存，见模块说明）
    natives_root = cache_natives_root()
    for cand_rel in candidates:
        cached = natives_root.joinpath(*cand_rel.split("/"))
        if cached.is_file():
            return cached

    # 3. 从 pak 现捞
    game = get_game_dir().strip()
    if not game or not Path(game).is_dir():
        return None
    for cand_rel in candidates:
        cached = natives_root.joinpath(*cand_rel.split("/"))
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            bridge._run("pakextract", game, f"{_INTERNAL_PREFIX}/{cand_rel}", str(cached))
        except Exception:
            # 捞不到是常态（这个候选路径不在 pak 里 / 没装游戏），换下一个候选，
            # 都失败才返回 None——不该往上抛打断预览/导入。
            continue
        if cached.is_file():
            return cached
    return None


def clear_cache() -> int:
    """清掉 pak 捞出来的缓存文件，返回删了几个。"""
    d = _cache_dir()
    n = sum(1 for p in d.rglob("*") if p.is_file())
    shutil.rmtree(d, ignore_errors=True)
    return n
