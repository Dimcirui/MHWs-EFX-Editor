"""
blender_efx_re/tex_image.py —— RE Engine `.tex` -> `bpy.types.Image`

为什么不用 `bridge.convert_tex_to_dds()`
----------------------------------------
**MHWs 的 `.tex` 载荷是 GDeflate 压缩的**（`TexSerializerVersion.GDeflate`，
vendor `TexFile.cs:212` 就是这么登记 MHWILDS 的），而 `ConvertToDDS()` 把**压缩字节**
原样套一个 DDS 头写出来——产物是纯噪声。

⚠ **这不是 vendor 的缺陷**：`TexFile` 自己有 `MustBeCompressed` / `IsCompressed` /
`DecompressGDeflate(DecompressionCallback)`（`TexFile.cs:381`），只是它不自带 GDeflate
实现、要调用方传回调，而我们的 `tools/EfxBridge/Program.cs` 从来没传过。所以这不该记进
KNOWN_UPSTREAM_ISSUES，是我们自己的路子没走完。

修在 Python 侧而不是 C# 侧，因为解压那套本仓**已经有了且验过**：
`wilds_vecfield_io.py` 的 TEX 头部解析 + `GDeflateWrapper.dll` 调用是对照 RE-Mesh-Editor
和 Modding-Toolkit 两份独立实现、再用真实游戏文件逐字节验证敲定的，DLL 也已经打进发行包。
这里只是把它从"BC1 专用"泛化到任意块格式。

⚠ **噪声和正确图像在统计上分不开**
---------------------------------
转坏的那张：非零 97.9%、均值 0.5166、最大 1.0。
转对的那张：非零 100%、均值 0.5570、最大 0.9686。
**没有任何统计量能区分**——判断解码对不对**只能看图**。门禁
（`tools/verify_blender_tex_image.py`）因此不查统计量，查的是"解压后的字节数恰好等于该
格式该尺寸的理论紧凑大小"这种结构性等式。

只解 mip0
---------
预览只需要最高一级。游戏用 streaming 管其余 mip，文件里内嵌的那几级对预览没用。

格式覆盖（1534 个真实样本的分布）
---------------------------------
    BC7 (98/99) 68%   BC1 (71/72) 30%   其余 7 种合计 1.4%
全部 `imageCount == 1`、`depth == 1`。**不认识的格式直接抛**，不猜块大小——猜错的后果
正是上面那种"看起来像图、其实是噪声"。

约束：只读；失败一律抛 `TexDecodeError`，不返回半成品。
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import bpy

from . import wilds_vecfield_io as _wvf

TEX_MAGIC = b"TEX\0"

#: DXGI format -> (块宽, 块高, 每块字节数)。非块压缩格式按 1x1 的"块"算，即每像素字节数。
#: 只列真实语料里出现过的（见模块说明）——**不认识的一律抛**。
_FORMAT_INFO = {
    71: (4, 4, 8),    # BC1_UNORM
    72: (4, 4, 8),    # BC1_UNORM_SRGB
    74: (4, 4, 16),   # BC2_UNORM
    75: (4, 4, 16),   # BC2_UNORM_SRGB
    77: (4, 4, 16),   # BC3_UNORM
    78: (4, 4, 16),   # BC3_UNORM_SRGB
    80: (4, 4, 8),    # BC4_UNORM
    81: (4, 4, 8),    # BC4_SNORM
    83: (4, 4, 16),   # BC5_UNORM
    84: (4, 4, 16),   # BC5_SNORM
    95: (4, 4, 16),   # BC6H_UF16
    96: (4, 4, 16),   # BC6H_SF16
    98: (4, 4, 16),   # BC7_UNORM
    99: (4, 4, 16),   # BC7_UNORM_SRGB
    28: (1, 1, 4),    # R8G8B8A8_UNORM
    29: (1, 1, 4),    # R8G8B8A8_UNORM_SRGB
    87: (1, 1, 4),    # B8G8R8A8_UNORM
    49: (1, 1, 2),    # R8G8_UNORM
    61: (1, 1, 1),    # R8_UNORM
    10: (1, 1, 8),    # R16G16B16A16_FLOAT
}

_FORMAT_NAMES = {
    71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 74: "BC2_UNORM", 75: "BC2_UNORM_SRGB",
    77: "BC3_UNORM", 78: "BC3_UNORM_SRGB", 80: "BC4_UNORM", 81: "BC4_SNORM",
    83: "BC5_UNORM", 84: "BC5_SNORM", 95: "BC6H_UF16", 96: "BC6H_SF16",
    98: "BC7_UNORM", 99: "BC7_UNORM_SRGB", 28: "R8G8B8A8_UNORM",
    29: "R8G8B8A8_UNORM_SRGB", 87: "B8G8R8A8_UNORM", 49: "R8G8_UNORM",
    61: "R8_UNORM", 10: "R16G16B16A16_FLOAT",
}

_GDEFLATE_MAGIC = b"\x04\xfb"


class TexDecodeError(Exception):
    """`.tex` 解不出来。**一律抛，不返回半成品**——半成品在界面上就是一张噪声图，
    而噪声和正确图像在统计上分不开，用户没法自己发现。"""


def _ceil_div(a, b):
    return -(-a // b)


def is_tex_data(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == TEX_MAGIC


def is_tex_file(path) -> bool:
    """按**魔数**判断，不看扩展名。

    真实游戏文件叫 `xxx.tex.241106027`，`Path.suffix` 是 `.241106027`——按后缀判断的话
    `.tex` 这条分支对真实文件永远不触发（这正是 `uvs_image_editor` 之前的第二个 bug）。
    """
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == TEX_MAGIC
    except OSError:
        return False


def format_name(fmt: int) -> str:
    return _FORMAT_NAMES.get(int(fmt), "DXGI_%d" % fmt)


# ---------------------------------------------------------------------------
# TEX -> DDS
# ---------------------------------------------------------------------------

def version_from_path(path) -> int | None:
    """从文件名后缀取格式版本号，**照抄 `PathUtils.ParseFileFormat()` 的严格规则**
    （铁律 #4）：扩展名从 basename 的**第一个**点算起，版本号必须紧跟其后。

    `a.tex.241106027` -> 241106027；`a.b.tex.241106027` -> None（第一个点后面是 `b`，
    不是 `tex`）。宽松判断（"文件名里出现过 .tex.<数字>"）在这个项目里是明令禁止的。
    """
    name = Path(path).name
    parts = name.split(".")
    if len(parts) < 3 or parts[1].lower() != "tex" or not parts[2].isdigit():
        return None
    return int(parts[2])


def extract_mip0(data: bytes, version: int | None = None) -> tuple[bytes, dict]:
    """取出 image0/mip0 的**紧凑**像素数据（去掉 GDeflate 压缩和 capcom 的 scanline 补齐）。

    返回 `(payload, header)`。头部解析复用 `wilds_vecfield_io._read_tex_header()`——那份是
    对照两个独立实现、用真实文件逐字节验过的，另抄一份只会让两处慢慢漂开。

    `version` 给了就**用它**决定头部布局分支，而不是用文件里那个字段——**铁律 #13：
    RE Engine 的格式版本号在文件名里，不在文件内容里**（vendor 的 `FileHandler.FileVersion`
    同样从路径算）。真实命中过：RE-Mesh 解包出来的 `#UNKN#….tex.241106027` 头里的 version
    字段是 `1`，照它走会把 `imageCount/mipCount` 读成 `192/1`（真值是 `1/12`）而拒绝加载。
    实现上把路径版本号拼回字节再交给同一个解析器，不另抄一份分支逻辑。
    """
    if not is_tex_data(data):
        raise TexDecodeError("不是 .tex 文件（magic 不是 'TEX\\0'）")
    if version is not None:
        header_bytes = data[:4] + struct.pack("<I", int(version)) + data[8:64]
    else:
        header_bytes = data[:64]
    try:
        header = _wvf._read_tex_header(header_bytes)
    except Exception as exc:
        raise TexDecodeError("TEX 头部解析失败：%s" % exc) from exc

    fmt = header["format"]
    if fmt not in _FORMAT_INFO:
        raise TexDecodeError(
            "不支持的贴图格式 DXGI=%d —— 拒绝按猜出来的块大小解码"
            "（猜错的产物是一张看起来像图的噪声，用户发现不了）" % fmt)
    if header["image_count"] != 1:
        raise TexDecodeError(
            "imageCount=%d（数组/cubemap），真实语料里没有这种样本，拒绝猜测其布局"
            % header["image_count"])

    bw, bh, bpb = _FORMAT_INFO[fmt]
    width, height = header["width"], header["height"]
    mip_count = header["mip_count"]

    mip_table_start = header["header_end"]
    n = mip_count * header["image_count"]
    image_header_table_start = mip_table_start + n * 16
    image_data_start = image_header_table_start + n * 8

    # mip 表每项 16 字节：<Q mipOffset><I scanlineLength><I uncompressedSize>
    _mip_offset, scanline_length, _uncomp = struct.unpack_from(
        "<QII", data, mip_table_start)
    # image header 表每项 8 字节：<I size><I offset>
    img_size, img_offset = struct.unpack_from("<II", data, image_header_table_start)

    start = image_data_start + img_offset
    raw = data[start:start + img_size]
    if len(raw) != img_size:
        raise TexDecodeError("mip0 数据被截断（要 %d 字节，只有 %d）"
                             % (img_size, len(raw)))

    if raw[:2] == _GDEFLATE_MAGIC:
        try:
            payload = _wvf.gdeflate_decompress(raw)
        except Exception as exc:
            raise TexDecodeError("GDeflate 解压失败：%s" % exc) from exc
    else:
        # MHWs 版本按 vendor 的登记就该是压缩的；不是的话八成是我们找错了偏移，
        # 与其交一张噪声图，不如说清楚。
        payload = raw

    line_bytes = _ceil_div(width, bw) * bpb
    rows = _ceil_div(height, bh)
    compact = line_bytes * rows

    if len(payload) == compact:
        return payload, header
    # capcom 的 scanline 补齐：每行按 scanline_length 对齐，裁掉尾部 padding
    if scanline_length >= line_bytes and len(payload) >= scanline_length * rows:
        out = bytearray()
        for r in range(rows):
            off = r * scanline_length
            out += payload[off:off + line_bytes]
        if len(out) == compact:
            return bytes(out), header

    raise TexDecodeError(
        "mip0 解出来 %d 字节，但 %dx%d 的 %s 紧凑布局应该是 %d 字节"
        "（scanline=%d）——布局和已验证的样本对不上，拒绝继续"
        % (len(payload), width, height, format_name(fmt), compact, scanline_length))


def tex_to_dds(data: bytes, version: int | None = None) -> bytes:
    """`.tex` 字节 -> 只含 mip0 的 DX10 DDS 字节。**BC7 之类的解码交给 Blender**，
    这里只负责把正确的载荷用正确的头包好。`version` 见 `extract_mip0()`。"""
    payload, header = extract_mip0(data, version)
    fmt = header["format"]
    bw, _bh, bpb = _FORMAT_INFO[fmt]
    width, height = header["width"], header["height"]
    compressed = bw > 1

    DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH = 0x1, 0x2, 0x4
    DDSD_PITCH, DDSD_PIXELFORMAT, DDSD_LINEARSIZE = 0x8, 0x1000, 0x80000
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if compressed:
        flags |= DDSD_LINEARSIZE
        pitch_or_linear = len(payload)
    else:
        flags |= DDSD_PITCH
        pitch_or_linear = _ceil_div(width, bw) * bpb

    buf = bytearray(148)
    buf[0:4] = b"DDS "
    struct.pack_into("<7I", buf, 4, 124, flags, height, width, pitch_or_linear, 1, 1)
    struct.pack_into("<2I", buf, 76, 32, 0x4)          # ddspf.size, DDPF_FOURCC
    buf[84:88] = b"DX10"
    struct.pack_into("<I", buf, 108, 0x1000)           # caps: DDSCAPS_TEXTURE
    # DDS_HEADER_DXT10: dxgiFormat, D3D10_RESOURCE_DIMENSION_TEXTURE2D, misc, arraySize, misc2
    struct.pack_into("<5I", buf, 128, fmt, 3, 0, 1, 0)
    return bytes(buf) + payload


# ---------------------------------------------------------------------------
# -> bpy.types.Image
# ---------------------------------------------------------------------------

def load_image(path, name: str | None = None, reuse: bool = True) -> bpy.types.Image:
    """把一个文件加载成 `bpy.types.Image`。

    `.tex`（按魔数判断）走上面那条链路；其余扩展名交给 Blender 自己读。
    产物一律 `pack()` 进 .blend——DDS 是写在临时目录里的，不 pack 的话下次要像素数据时
    找不到源文件，图会变红叉。

    `reuse=True` 时同名图直接复用，避免反复加载同一张贴图堆出一堆 `.001` 数据块。
    """
    path = Path(path)
    if not path.is_file():
        raise TexDecodeError("文件不存在：%s" % path)
    img_name = name or path.name

    if reuse:
        existing = bpy.data.images.get(img_name)
        # ⚠ 不能只看 `has_data`：它是"像素缓冲**此刻**在内存里"，而不是"这张图有内容"。
        # 刚 pack 进 .blend、还没有人真正取过像素的图，`has_data` 是 False——只按它判断的话
        # 复用永远不命中，同一张贴图会堆出一串 `.001/.002/...` 数据块（实测一个 mod 的 24 个
        # 网格把 7 张贴图复制成了 64 份，.blend 直接胖几十倍）。`packed_file` 在则内容一定在。
        if existing is not None and (existing.has_data or existing.packed_file is not None):
            return existing

    if is_tex_file(path):
        dds = tex_to_dds(path.read_bytes(), version_from_path(path))
        with tempfile.TemporaryDirectory(prefix="mhws_tex_") as tmpdir:
            tmp = Path(tmpdir) / "mip0.dds"
            tmp.write_bytes(dds)
            img = bpy.data.images.load(str(tmp))
            img.pack()
    else:
        img = bpy.data.images.load(str(path))
        img.pack()

    img.name = img_name
    return img


def describe(path) -> dict:
    """只读元信息（给面板/报错用），不解码。版本号同样以**文件名**为准（铁律 #13）。"""
    data = Path(path).read_bytes()[:64]
    if not is_tex_data(data):
        return {}
    ver = version_from_path(path)
    if ver is not None:
        data = data[:4] + struct.pack("<I", ver) + data[8:]
    try:
        h = _wvf._read_tex_header(data)
    except Exception:
        return {}
    return {"width": h["width"], "height": h["height"], "format": h["format"],
            "format_name": format_name(h["format"]), "mip_count": h["mip_count"],
            "image_count": h["image_count"], "version": h["version"]}
