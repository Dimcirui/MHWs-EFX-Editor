"""
tools/verify_blender_tex_image.py —— `.tex` 解码门禁

    <blender> --background --factory-startup --python tools/verify_blender_tex_image.py \
        [-- --sample <tex 文件> --dump <png 输出目录>]

退出码 0/1。找不到样本 -> 报错退 1，不静默全绿。

## 为什么这个门禁不看统计量

解坏的那张（vendor `ConvertToDDS()` 直接套头）和解对的那张，统计特征分不开：

    坏：非零 97.9%  均值 0.5166  最大 1.0000
    对：非零 100%   均值 0.5570  最大 0.9686

**没有任何统计量能区分噪声和正确图像**——这就是为什么 `uvs_image_editor.py` 里那句"对某些
贴图会转花"存在了这么久却没人定位到根因。所以这里查的是**结构性等式**，不是统计量：

1. GDeflate 解压后的字节数**恰好等于** `ceil(w/块宽) * ceil(h/块高) * 每块字节数`。
   压缩数据解错一位，长度就对不上——这个等式过不了假。
2. 解出来的 DDS 能被 Blender 读成正确尺寸、且 `has_data`。
3. **相邻帧相关性**：序列帧图集里同一行相邻两格的内容是连续动画，应当明显相关；
   噪声图里任意两格都不相关。这是唯一能从像素层面区分噪声的判据（见下）。
4. 不认识的格式/布局必须**抛 TexDecodeError**，不能交半成品。

`--dump <目录>` 会把解出来的图存成 PNG，**人可以直接去看**。自动化判据再全，最终确认解码
对不对还是得看一眼——这条写在这里是为了下次不要再只信统计量。
"""
from __future__ import annotations

import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402

from blender_efx_re import tex_image  # noqa: E402

_FAILED = 0


def _check(ok: bool, label: str, detail: str = "") -> None:
    global _FAILED
    if ok:
        print(f"  PASS  {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}" + (f"  —— {detail}" if detail else ""))


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            out[argv[i][2:]] = argv[i + 1]
    return out


def _samples(opts) -> list[pathlib.Path]:
    if "sample" in opts:
        return [pathlib.Path(opts["sample"])]
    roots = [
        pathlib.Path(r"E:\Program\Steam\steamapps\common\MonsterHunterWilds"
                     r"\MHWILDS_EXTRACT"),
        pathlib.Path(r"E:\Data\MOD工具\MHWS MOD"),
    ]
    found = []
    for root in roots:
        if root.is_dir():
            found.extend(sorted(root.rglob("*.tex.*"))[:8])
    return found[:12]


#: 已知的一张 16x4 序列帧图集（像素级判据要用）。解包目录里没有序列贴图，从 pak 现捞，
#: 单次 <1 秒（见 CLAUDE.md「常用命令」的 pakextract 一节）。
_ATLAS_INTERNAL = ("natives/STM/Art/VFX/Texture/Common/Sequence/"
                   "11_fire_000_ALBA.tex.241106027")
_GAME_DIR = pathlib.Path(r"E:\Program\Steam\steamapps\common\MonsterHunterWilds")


def _sequence_atlas(opts, samples):
    """拿一张序列帧图集：优先命令行给的样本，其次本地已有的 Sequence 贴图，最后从 pak 现捞。"""
    if "sample" in opts:
        return pathlib.Path(opts["sample"])
    for s in samples:
        if "Sequence" in str(s):
            return s
    if not _GAME_DIR.is_dir():
        return None
    try:
        from blender_efx_re import bridge
        import tempfile
        out = pathlib.Path(tempfile.gettempdir()) / "mhws_gate_atlas.tex.241106027"
        if not out.is_file():
            # bridge.py 没有 pakextract 的具名包装（它是开发期用的子命令，不在插件的
            # 数据路径上），门禁直接走 _run()——只有这里用，不值得为它加一个公开 API。
            bridge._run("pakextract", str(_GAME_DIR), _ATLAS_INTERNAL, str(out))
        return out if out.is_file() else None
    except Exception:
        return None


def _tile_correlation(img, cols=16, rows=4):
    """序列帧图集判据：把图切成 cols×rows 格，比较同一行相邻两格的亮度序列。

    正确解码的序列帧是连续动画，相邻格高度相关；噪声图任意两格都不相关。
    返回 (相邻格相关系数均值, 随机格对相关系数均值)。
    """
    w, h = img.size
    px = img.pixels[:]          # 一次性取（bpy_prop_array 不支持扩展切片）
    tw, th = w // cols, h // rows

    def tile_lum(cx, cy, step=4):
        vals = []
        for y in range(cy * th, (cy + 1) * th, step):
            base = y * w * 4
            for x in range(cx * tw, (cx + 1) * tw, step):
                i = base + x * 4
                vals.append((px[i] + px[i + 1] + px[i + 2]) / 3.0)
        return vals

    def corr(a, b):
        n = min(len(a), len(b))
        if n < 8:
            return 0.0
        ma, mb = sum(a[:n]) / n, sum(b[:n]) / n
        va = sum((v - ma) ** 2 for v in a[:n])
        vb = sum((v - mb) ** 2 for v in b[:n])
        if va <= 1e-12 or vb <= 1e-12:
            return 0.0
        cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        return cov / (va ** 0.5 * vb ** 0.5)

    adj, far = [], []
    for cy in range(rows):
        tiles = [tile_lum(cx, cy) for cx in range(cols)]
        for cx in range(cols - 1):
            adj.append(corr(tiles[cx], tiles[cx + 1]))
        # 远距离格对（同一行首尾）当对照组
        far.append(corr(tiles[0], tiles[cols // 2]))
    return (sum(adj) / len(adj) if adj else 0.0,
            sum(far) / len(far) if far else 0.0)


def main() -> int:
    global _FAILED
    opts = _args()
    samples = _samples(opts)
    if not samples:
        print("[ERROR] 找不到任何 .tex 样本——门禁不能因为没样本就算过")
        return 1

    dump_dir = pathlib.Path(opts["dump"]) if "dump" in opts else None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    decoded = 0
    refused = 0
    for src in samples:
        meta = tex_image.describe(src)
        if not meta:
            continue
        label = f"{src.name[:42]} {meta['width']}x{meta['height']} {meta['format_name']}"
        try:
            # 1. 结构性等式：解压后字节数必须恰好等于理论紧凑大小（extract_mip0 内部断言）
            payload, header = tex_image.extract_mip0(src.read_bytes())
            bw, bh, bpb = tex_image._FORMAT_INFO[header["format"]]
            want = (-(-header["width"] // bw)) * (-(-header["height"] // bh)) * bpb
            _check(len(payload) == want, f"{label} 紧凑字节数吻合",
                   f"{len(payload)} != {want}")

            # 2. Blender 能读成正确尺寸
            img = tex_image.load_image(src, name=f"probe_{src.name}", reuse=False)
            _check(tuple(img.size) == (header["width"], header["height"])
                   and img.has_data, f"{label} Blender 读出正确尺寸",
                   f"{tuple(img.size)} has_data={img.has_data}")
            decoded += 1

            if dump_dir:
                img.file_format = "PNG"
                img.save_render(str(dump_dir / (src.name + ".png")))
        except tex_image.TexDecodeError as ex:
            # 拒绝本身是正确行为（不认识的格式/布局），只要它是**抛**而不是交半成品
            refused += 1
            print(f"  SKIP  {label} 明确拒绝：{str(ex)[:80]}")
        except Exception as ex:   # noqa: BLE001
            _check(False, f"{label} 非预期异常", f"{type(ex).__name__}: {ex}")

    _check(decoded > 0, "至少解码成功一张", f"成功 {decoded} 张，明确拒绝 {refused} 张")

    # 3. 像素层面"不是噪声"：相邻格相关性。**这是唯一能从像素上区分噪声的判据**，
    #    统计量（非零占比/均值/最大值）在噪声和正确图像上几乎一样，见模块说明。
    #    ⚠ 这个判据**只对序列帧图集成立**，不能用在普通贴图上：角色 albedo 的相邻格本来
    #    就不相关（实测 ALBD.tex 只有 0.139），拿它当判据会误报。只在能拿到序列帧图集时跑。
    probe = _sequence_atlas(opts, samples)
    if probe is not None:
        img = tex_image.load_image(probe, name="probe_corr", reuse=False)
        adj, far = _tile_correlation(img)
        print(f"  INFO  {probe.name}: 相邻格相关 {adj:.3f}，远距格相关 {far:.3f}")
        _check(adj > 0.3, "解出来的图相邻格明显相关（不是噪声）", f"adj={adj:.3f}")

        # 反例常驻：把**旧的坏路径**（vendor ConvertToDDS，不解 GDeflate）的产物喂进同一个
        # 判据，必须被判成噪声。按 CLAUDE.md #11，回归防护要能真的抓到那个 bug——与其每次
        # 手工注入，不如把坏路径永久留成对照组。
        try:
            from blender_efx_re import bridge
            import tempfile
            with tempfile.TemporaryDirectory(prefix="mhws_tex_negctl_") as td:
                bad_dds = pathlib.Path(td) / "bad.dds"
                bridge.convert_tex_to_dds(probe, bad_dds)
                bad = bpy.data.images.load(str(bad_dds))
                bad.pack()
                b_adj, b_far = _tile_correlation(bad)
                print(f"  INFO  反例（vendor ConvertToDDS，不解压）: "
                      f"相邻格相关 {b_adj:.3f}，远距格相关 {b_far:.3f}")
                _check(b_adj < 0.3, "反例被判为噪声（判据真的能抓到这个 bug）",
                       f"b_adj={b_adj:.3f}")
                _check(adj - b_adj > 0.3, "正确产物与坏产物被明确区分",
                       f"{adj:.3f} vs {b_adj:.3f}")
        except Exception as ex:   # noqa: BLE001
            print(f"  INFO  反例对照跑不了（{type(ex).__name__}），跳过")
    else:
        print("  INFO  拿不到序列帧图集，跳过像素级判据"
              "（结构性等式仍然覆盖了全部样本）")

    # 4. 同一个文件载两次必须复用同一个数据块
    #
    #    `load_image(reuse=True)` 原来只看 `existing.has_data`，而 `has_data` 是"像素缓冲
    #    **此刻**在内存里"——刚 pack 进 .blend、还没人取过像素的图它是 False，于是复用永远
    #    不命中，同一张贴图堆出一串 `.001/.002/…`（实测一个 mod 的 24 个网格把 7 张贴图复制
    #    成了 64 份）。这条错**不会报任何错**，只是 .blend 悄悄胖几十倍，必须有门禁钉住。
    if samples:
        before_names = set(bpy.data.images.keys())
        first = tex_image.load_image(samples[0])
        after_first = set(bpy.data.images.keys())
        second = tex_image.load_image(samples[0])
        _check(second is first and set(bpy.data.images.keys()) == after_first,
               "同一个 .tex 载两次复用同一个数据块（不堆 .001）",
               f"新增 {len(set(bpy.data.images.keys()) - before_names)} 个数据块")

    # 5. 垃圾输入必须抛
    try:
        tex_image.extract_mip0(b"NOPE" + b"\0" * 64)
        _check(False, "非 TEX 输入必须抛 TexDecodeError")
    except tex_image.TexDecodeError:
        _check(True, "非 TEX 输入明确拒绝")

    if _FAILED:
        print(f"\n===== {_FAILED} FAILED")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己兜住异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # **未捕获异常**时**退出码仍然是 0**（实测），`sys.exit(main())` 那行根本轮不到执行——
    # 净效果是"门禁崩在第一行"和"门禁全过"对调用方长得一模一样，正是静默全绿。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
