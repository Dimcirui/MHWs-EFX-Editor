"""读写 Monster Hunter Wilds 原生向量场贴图（.tex.<version>）。

只覆盖用真实语料字节级验证过的那一种情况：
  - version == 241106027 (VERSION_MHWILDS)
  - format  == 71 (DXGI BC1_UNORM)
  - imageCount == 1（单张 Texture3D，不是数组/cubemap）
  - mipCount == 1（只有一级 mip 内嵌在文件里，游戏用 streaming 管其余 mip）

TEX 头部字段布局、mip 表/压缩块表的偏移算法，以及 GDeflate 是"没识别出来的
神秘压缩"这件事本身，都是靠对照 RE-Mesh-Editor 的 modules/tex/file_re_tex.py
（NSA Cloud & AsteriskAmpersand）和 Modding-Toolkit 的 core/tex_file.py /
core/gdeflate_native.py 两份独立实现，再用真实游戏文件（tex_capcom_vectorfield_
0006/0007_MSK4）做字节级往返验证敲定的——不是凭 hex dump 猜出来的。压缩算法是
GDeflate（NVIDIA/DirectStorage 那个），不是 zlib/deflate。

写出侧（BC1 编码 + GDeflate 压缩 + 重新打包 TEX 容器）目前只验证到
"自己写出的文件能被自己的读取器读回、和编码前的体数据一致"这一步，
**没有在游戏里实机验证过写出的体积贴图能被正确加载**——遇到需要确认这一点的
场景，务必先说清楚这个边界，不要断言"已经能用在游戏里"。

BC1 是有损压缩：write 之后再 read 回来，数值会有 (-128,+44) 量级的量化误差，
这是格式本身的固有行为，不是这份实现的 bug。
"""
import ctypes
import struct
from ctypes import c_bool, c_uint8, c_uint32, c_uint64, POINTER, byref
from pathlib import Path

import numpy as np

VERSION_MHWILDS = 241106027
DXGI_BC1_UNORM = 71
TEX_MAGIC = 5784916  # "TEX\0" 按小端 uint32 读出的值

_DLL_NAME = "GDeflateWrapper.dll"
_dll = None


class WildsTexError(Exception):
    pass


class GDeflateError(WildsTexError):
    pass


# ===================== GDeflate（vendor 自 RE-Mesh-Editor 的 GDeflateWrapper.dll） =====================

def _load_gdeflate_dll():
    global _dll
    if _dll is not None:
        return _dll
    dll_path = Path(__file__).parent / "vendor" / _DLL_NAME
    try:
        dll = ctypes.CDLL(str(dll_path))
    except OSError as e:
        raise GDeflateError(f"无法加载 {dll_path}: {e}")

    dll.gdeflate_get_uncompressed_size.argtypes = [POINTER(c_uint8), c_uint64, POINTER(c_uint64)]
    dll.gdeflate_get_uncompressed_size.restype = c_bool

    dll.gdeflate_decompress.argtypes = [POINTER(c_uint8), c_uint64, POINTER(c_uint8), c_uint64, c_uint32]
    dll.gdeflate_decompress.restype = c_bool

    dll.gdeflate_get_compress_bound.argtypes = [c_uint64]
    dll.gdeflate_get_compress_bound.restype = c_uint64

    dll.gdeflate_compress.argtypes = [POINTER(c_uint8), POINTER(c_uint64), POINTER(c_uint8), c_uint64, c_uint32, c_uint32]
    dll.gdeflate_compress.restype = c_bool

    _dll = dll
    return dll


def gdeflate_decompress(data: bytes, num_workers: int = 4) -> bytes:
    dll = _load_gdeflate_dll()
    in_arr = (c_uint8 * len(data)).from_buffer_copy(data)
    out_size = c_uint64(0)
    if not dll.gdeflate_get_uncompressed_size(in_arr, c_uint64(len(data)), byref(out_size)):
        raise GDeflateError("gdeflate_get_uncompressed_size 失败")
    out_arr = (c_uint8 * out_size.value)()
    if not dll.gdeflate_decompress(out_arr, c_uint64(out_size.value), in_arr, c_uint64(len(data)), c_uint32(num_workers)):
        raise GDeflateError("gdeflate_decompress 失败")
    return ctypes.string_at(out_arr, out_size.value)


def gdeflate_compress(data: bytes, level: int = 12) -> bytes:
    """level 用 DirectStorage 的档位：1=FASTEST, 9=DEFAULT, 12=BEST_RATIO。"""
    dll = _load_gdeflate_dll()
    bound = dll.gdeflate_get_compress_bound(c_uint64(len(data)))
    out_size = c_uint64(bound)
    out_arr = (c_uint8 * bound)()
    in_arr = (c_uint8 * len(data)).from_buffer_copy(data)
    if not dll.gdeflate_compress(out_arr, byref(out_size), in_arr, c_uint64(len(data)), c_uint32(level), c_uint32(0)):
        raise GDeflateError("gdeflate_compress 失败")
    return ctypes.string_at(out_arr, out_size.value)


# ===================== BC1 (DXT1) 块编解码 =====================

def _ru_div(x, y):
    return (x + y - 1) // y


def _rgb565_to_888(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)
    return r.astype(np.int32), g.astype(np.int32), b.astype(np.int32)


def _rgb888_to_565(r, g, b):
    r5 = (r.astype(np.uint32) * 31 + 127) // 255
    g6 = (g.astype(np.uint32) * 63 + 127) // 255
    b5 = (b.astype(np.uint32) * 31 + 127) // 255
    return (r5 << 11 | g6 << 5 | b5).astype(np.uint16)


def decode_bc1_volume(payload: bytes, width: int, height: int, depth: int) -> np.ndarray:
    """把紧凑排列（无 scanline padding）的 BC1 块解成 (depth,height,width,3) 的 uint8 RGB。"""
    bw, bh = width // 4, height // 4
    n_blocks = bw * bh * depth
    raw = np.frombuffer(payload, dtype=np.uint8, count=n_blocks * 8).reshape(n_blocks, 8)

    c0 = raw[:, 0].astype(np.uint16) | (raw[:, 1].astype(np.uint16) << 8)
    c1 = raw[:, 2].astype(np.uint16) | (raw[:, 3].astype(np.uint16) << 8)
    bits = (raw[:, 4].astype(np.uint32) | (raw[:, 5].astype(np.uint32) << 8) |
            (raw[:, 6].astype(np.uint32) << 16) | (raw[:, 7].astype(np.uint32) << 24))

    r0, g0, b0 = _rgb565_to_888(c0)
    r1, g1, b1 = _rgb565_to_888(c1)

    opaque = c0 > c1
    r2 = np.where(opaque, (2 * r0 + r1) // 3, (r0 + r1) // 2)
    g2 = np.where(opaque, (2 * g0 + g1) // 3, (g0 + g1) // 2)
    b2 = np.where(opaque, (2 * b0 + b1) // 3, (b0 + b1) // 2)
    r3 = np.where(opaque, (r0 + 2 * r1) // 3, 0)
    g3 = np.where(opaque, (g0 + 2 * g1) // 3, 0)
    b3 = np.where(opaque, (b0 + 2 * b1) // 3, 0)

    colorsR = np.stack([r0, r1, r2, r3], axis=1)
    colorsG = np.stack([g0, g1, g2, g3], axis=1)
    colorsB = np.stack([b0, b1, b2, b3], axis=1)

    idx = (bits[:, None] >> (2 * np.arange(16))[None, :]) & 0x3

    texR = np.take_along_axis(colorsR, idx, axis=1)
    texG = np.take_along_axis(colorsG, idx, axis=1)
    texB = np.take_along_axis(colorsB, idx, axis=1)

    tex = np.stack([texR, texG, texB], axis=-1).astype(np.uint8)  # (n_blocks, 16, 3)
    tex = tex.reshape(n_blocks, 4, 4, 3)
    tex = tex.reshape(depth, bh, bw, 4, 4, 3)
    tex = tex.transpose(0, 1, 3, 2, 4, 5).reshape(depth, bh * 4, bw * 4, 3)
    return tex


def encode_bc1_volume(rgb_volume: np.ndarray) -> bytes:
    """(depth,height,width,3) uint8 RGB -> 紧凑排列的 BC1 字节串（无 padding）。

    用的是最简单的 "block 内 RGB 包围盒两角当端点" 编码（range fit），不是
    cluster-fit 那种更精细的方案——精度上够用（往返均方误差在 BC1 量化本身
    的量级），换来的是整卷能一次性用 numpy 向量化算完，不用逐 block python 循环。

    有一个必须处理的边界情况：如果一个 block 里 16 个体素颜色完全一样
    （零向量区域在向量场里非常常见，(128,128,128) 附近一大片），min==max，
    量化后 color0==color1，BC1 会被解码器判定成"3 色 + 强制透明黑"模式，
    index=3 的体素会被解码成纯黑 (0,0,0) —— 对应向量 (-1,-1,-1)，
    而不是本来的零向量。这里强制 color0 != color1（相等时把 color0 加 1）
    来保证走 4 色模式，避免这种静默把零向量场写成"全黑"的错误。
    """
    depth, height, width, _ = rgb_volume.shape
    bh, bw = height // 4, width // 4
    v = rgb_volume.reshape(depth, bh, 4, bw, 4, 3)
    v = v.transpose(0, 1, 3, 2, 4, 5)  # (depth, bh, bw, 4, 4, 3)
    n_blocks = depth * bh * bw
    blocks = v.reshape(n_blocks, 16, 3).astype(np.int32)

    mins = blocks.min(axis=1)
    maxs = blocks.max(axis=1)

    c_max565 = _rgb888_to_565(maxs[:, 0], maxs[:, 1], maxs[:, 2])
    c_min565 = _rgb888_to_565(mins[:, 0], mins[:, 1], mins[:, 2])

    c0 = np.maximum(c_max565, c_min565).copy()
    c1 = np.minimum(c_max565, c_min565).copy()
    tie = c0 == c1
    c0[tie] = np.clip(c0[tie].astype(np.int32) + 1, 0, 0xFFFF).astype(np.uint16)

    r0, g0, b0 = _rgb565_to_888(c0.astype(np.int32))
    r1, g1, b1 = _rgb565_to_888(c1.astype(np.int32))
    r2, g2, b2 = (2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3
    r3, g3, b3 = (r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3

    cand = np.stack([
        np.stack([r0, g0, b0], axis=1),
        np.stack([r1, g1, b1], axis=1),
        np.stack([r2, g2, b2], axis=1),
        np.stack([r3, g3, b3], axis=1),
    ], axis=1).astype(np.int32)  # (n_blocks, 4, 3)

    diff = blocks[:, :, None, :] - cand[:, None, :, :]
    dist2 = (diff * diff).sum(axis=-1)
    idx = dist2.argmin(axis=-1).astype(np.uint32)

    bits = np.zeros(n_blocks, dtype=np.uint32)
    for t in range(16):
        bits |= (idx[:, t] << (2 * t))

    out = np.empty((n_blocks, 8), dtype=np.uint8)
    out[:, 0] = (c0 & 0xFF).astype(np.uint8)
    out[:, 1] = (c0 >> 8).astype(np.uint8)
    out[:, 2] = (c1 & 0xFF).astype(np.uint8)
    out[:, 3] = (c1 >> 8).astype(np.uint8)
    out[:, 4] = (bits & 0xFF).astype(np.uint8)
    out[:, 5] = ((bits >> 8) & 0xFF).astype(np.uint8)
    out[:, 6] = ((bits >> 16) & 0xFF).astype(np.uint8)
    out[:, 7] = ((bits >> 24) & 0xFF).astype(np.uint8)
    return out.tobytes()


# ===================== TEX 容器读取 =====================

def _read_tex_header(data: bytes) -> dict:
    off = 0
    magic, = struct.unpack_from('<I', data, off); off += 4
    if magic != TEX_MAGIC:
        raise WildsTexError("不是 .tex 文件（magic 不对）")
    version, = struct.unpack_from('<I', data, off); off += 4
    width, height, depth = struct.unpack_from('<HHH', data, off); off += 6
    if version > 11 and version != 190820018:
        image_count = data[off]; off += 1
        image_mip_header_size = data[off]; off += 1
        mip_count = image_mip_header_size // 16
    else:
        mip_count = data[off]; off += 1
        image_count = data[off]; off += 1
    fmt, = struct.unpack_from('<I', data, off); off += 4
    off += 4  # swizzleControl
    off += 4  # cubemapMarker
    off += 1 + 1 + 2  # unkn04, unkn05, null0
    if version > 27 and version != 190820018:
        off += 1 + 1 + 2 + 2 + 2  # swizzleHeightDepth, swizzleWidth, null1, seven, one
    return {
        'version': version, 'width': width, 'height': height, 'depth': depth,
        'image_count': image_count, 'mip_count': mip_count, 'format': fmt,
        'header_end': off,
    }


def _read_mip0_bc1_bytes(data: bytes, header: dict) -> bytes:
    """读出 image0/mip0 的 GDeflate 压缩块，解压、去掉 capcom scanline 补齐，
    返回和标准 DDS 里紧凑排列的 BC1 数据完全一致的字节串。

    已经用真实语料（tex_capcom_vectorfield_0006/0007_MSK4）逐字节验证过：
    对照官方工具导出的 .dds，这里解出来的字节和 DDS payload 完全相同。
    """
    width, height = header['width'], header['height']
    mip_count, image_count = header['mip_count'], header['image_count']

    mip_table_start = header['header_end']
    image_header_table_start = mip_table_start + mip_count * image_count * 16
    image_data_start = image_header_table_start + mip_count * image_count * 8

    scanline_length, _uncompressed_size_hint = struct.unpack_from(
        '<II', data, mip_table_start + 8)  # 跳过 8 字节 mipOffset（GDeflate 路径下没用上）

    img_size, img_offset = struct.unpack_from('<II', data, image_header_table_start)
    raw = data[image_data_start + img_offset: image_data_start + img_offset + img_size]

    if len(raw) >= 2 and raw[0] == 0x04 and raw[1] == 0xFB:
        decompressed = gdeflate_decompress(raw)
    else:
        decompressed = raw

    bc1_bytes_per_block = 8
    line_bytelength = _ru_div(width, 4) * bc1_bytes_per_block
    end_size = len(decompressed)

    if end_size == line_bytelength * _ru_div(height, 4) * header['depth']:
        return decompressed

    trimmed = bytearray()
    src_off = 0
    current = 0
    while current != end_size:
        trimmed.extend(decompressed[src_off:src_off + line_bytelength])
        src_off += scanline_length
        current += scanline_length
        if current > end_size:
            raise WildsTexError(
                f"scanline 裁剪越界（current={current} end={end_size}），"
                "这个文件的 header 字段和已验证的样本对不上，拒绝继续导入")
    return bytes(trimmed)


def parse_wilds_tex_file(filepath: str) -> dict:
    """读取 MHWs 原生 .tex.<version> 向量场文件。

    返回 dict: vectors(float32, (d,d,d,3)), rgba_data(uint8,(d,d,d,4)),
    dimensions, version, detected_size。

    只接受已验证过的组合（version=241106027, format=BC1_UNORM, 单张体积贴图，
    单 mip），其它一律抛 WildsTexError——没验证过的分支不猜测着往下走。
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    header = _read_tex_header(data)

    if header['version'] != VERSION_MHWILDS:
        raise WildsTexError(f"未验证过的 tex 版本号 {header['version']}（只验证过 {VERSION_MHWILDS}），拒绝导入")
    if header['format'] != DXGI_BC1_UNORM:
        raise WildsTexError(f"未验证过的像素格式 {header['format']}（只验证过 BC1_UNORM=71），拒绝导入")
    if header['image_count'] != 1:
        raise WildsTexError(f"未验证过的 imageCount={header['image_count']}（只验证过单张体积贴图 imageCount=1），拒绝导入")
    width, height, depth = header['width'], header['height'], header['depth']
    if not (width == height == depth):
        raise WildsTexError(f"非立方体维度 {width}x{height}x{depth}，向量场编辑器只支持立方体场")

    bc1_bytes = _read_mip0_bc1_bytes(data, header)
    rgb_volume = decode_bc1_volume(bc1_bytes, width, height, depth)

    vectors = (rgb_volume.astype(np.float32) - 128.0) / 127.0

    dim = width
    rgba = np.zeros((dim, dim, dim, 4), dtype=np.uint8)
    rgba[..., :3] = rgb_volume
    rgba[..., 3] = 1  # BC1 没有可用的权重通道，固定给 1

    return {
        'vectors': vectors,
        'rgba_data': rgba,
        'dimensions': (dim, dim, dim),
        'num_slices': dim,
        'version': header['version'],
        'bounds': [[-dim / 2] * 3, [dim / 2] * 3],
        'detected_size': f"{dim}x{dim}x{dim}",
    }


# ===================== TEX 容器写出 =====================

def _pad_to_256(pitch: int) -> int:
    return _ru_div(pitch, 256) * 256


def build_wilds_vecfield_tex(vectors: np.ndarray, version: int = VERSION_MHWILDS) -> bytes:
    """把 (dim,dim,dim,3) 的向量场编码回 MHWs 原生 .tex 字节串。

    编码方式和 parse_wilds_tex_file 互逆：vector*127+128 -> RGB -> BC1 -> 按
    capcom scanline（256 字节对齐）补齐 -> GDeflate 压缩 -> 40 字节 header +
    16 字节 mip 表项 + 8 字节压缩块表项 + 压缩数据。

    验证边界：只验证到"自己写出的文件能被 parse_wilds_tex_file 读回、和
    编码前的体数据一致（在 BC1 量化误差范围内）"。没有实机验证过写出的
    体积贴图能被游戏正确加载，调用方需要清楚这一点。
    """
    if version != VERSION_MHWILDS:
        raise WildsTexError(f"只验证过写出 version={VERSION_MHWILDS}，拒绝写 version={version}")

    dim = vectors.shape[0]
    if vectors.shape != (dim, dim, dim, 3):
        raise WildsTexError(f"vectors 形状必须是立方体 (d,d,d,3)，实际是 {vectors.shape}")

    rgb_volume = np.clip(np.round(vectors * 127.0 + 128.0), 0, 255).astype(np.uint8)
    bc1_raw = encode_bc1_volume(rgb_volume)

    real_pitch = _ru_div(dim, 4) * 8
    padded_pitch = _pad_to_256(real_pitch)
    pad = padded_pitch - real_pitch
    blocks_y = _ru_div(dim, 4)

    if pad == 0:
        padded_body = bc1_raw
    else:
        chunks = []
        for row_start in range(0, len(bc1_raw), real_pitch):
            chunks.append(bc1_raw[row_start:row_start + real_pitch])
            chunks.append(b'\x00' * pad)
        padded_body = b''.join(chunks)

    compressed = gdeflate_compress(padded_body, level=12)

    header = struct.pack('<IIHHHBBIiIBBHBBHHH',
        TEX_MAGIC, version, dim, dim, dim,
        1, 16,          # imageCount=1, imageMipHeaderSize=16 (mipCount=1)
        DXGI_BC1_UNORM,
        -1, 0,          # swizzleControl=-1, cubemapMarker=0
        0, 0, 0,        # unkn04, unkn05, null0
        0, 0, 0, 0, 0,  # swizzleHeightDepth, swizzleWidth, null1, seven, one
    )
    mip_offset = len(header) + 16  # 指向压缩块表，和真实游戏文件里观察到的值一致
    uncompressed_size = padded_pitch * blocks_y  # 和真实文件里的字段值对得上的经验公式
    mip_entry = struct.pack('<QII', mip_offset, padded_pitch, uncompressed_size)
    comp_header = struct.pack('<II', len(compressed), 0)

    return header + mip_entry + comp_header + compressed


def build_wilds_vecfield_tex_file(vectors: np.ndarray, version: int, filepath: str) -> None:
    data = build_wilds_vecfield_tex(vectors, version)
    with open(filepath, 'wb') as f:
        f.write(data)
