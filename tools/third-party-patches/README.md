# third-party-patches

给**别人的插件**打的补丁。和 `tools/vendor-patches/` 的区别：那边改的是我们自己 submodule
进来的 `vendor/RE-Engine-Lib`，这边改的是装在用户 Blender 扩展目录里的第三方插件。

⚠ **第三方插件不在我们的版本控制下，每次它更新都会把补丁覆盖掉**，要重新打一遍。这跟
CLAUDE.md 铁律 #2 对 vendor 的顾虑是同一件事（fork 会持续增加维护负担），只是这次是用户
明确要求集成进解包流程，所以接受这个代价。补丁刻意做得**只有三个 hunk**，重新打很便宜。

## 0001-re-asset-library-resolve-unknown-from-references.patch

**目标**：`RE-Asset-Library`（NSA Cloud）的 `modules/pak/re_pak_utils.py`
（本机在 `…/Blender/5.1/scripts/addons/RE-Asset-Library-main/`）

**作用**：pak 解包结束后，用**已经解出来的文件**反解 `UNKNOWN/` 里那些 `#UNKN#` 文件的真名
并归位。

### 原理

RE 的资源文件里以明文存着它引用的其它资源的**内部路径**：

    .uvs   -> 贴图路径表
    .efx   -> UVSequence.UVSPath、TypeMesh 材质的贴图路径
    .mdf2  -> 贴图路径
    .mesh  -> mdf2 路径

而 `re_pak_utils.py` 自己写出的未知文件名就是两个哈希：

    #UNKN#{hashNameLower}-{hashNameUpper}{扩展名}
    hashNameLower = hashUTF16(assetPath.lower())
    hashNameUpper = hashUTF16(assetPath.upper())
    assetPath = 完整内部路径（含 natives/<平台>/ 前缀 + 版本号后缀）

所以把扫出来的路径串按同一规则算一遍，就能精确反查。**只在两个 32 位哈希都命中时才动文件**
——猜错一个名字比留在 UNKNOWN 里更糟，那会让人以为这就是正确的资源路径。

### 三个实现上的要点（都是实测踩出来的）

1. **不解析任何格式，直接扫字节里的字符串。** 这样 `.uvs`/`.efx` 这类 RE-Asset-Library 本身
   不解析的格式也覆盖得到，而且补丁零新增依赖。实测在同一批文件上，扫字节得到的路径集合与
   用正经解析器（`EfxBridge uvsdump`/`dump`/`mdfdump`）得到的**完全一致**（37 vs 37，
   零漏零误报）。
2. **UTF-16LE 要扫两个字节对齐。** 起始于奇数偏移的字符串，整体从 0 解码会被错位切碎——
   只扫一个对齐会漏掉 12/46 个路径。
3. **版本号后缀不猜。** 候选路径里没有版本号（`…/x.tex`），但 `UNKNOWN` 文件名里带着
   （`.tex.241106027`），按扩展名把见过的版本号各试一遍即可，不需要维护一张版本号表。
   `natives/<平台>` 前缀同理，从解包出来的目录结构里认，不写死 `natives/STM`。

### 实测

MHWs 的一个 EFX mod（`幻枢归奇_extract`，34 个未知文件）：**27 个归位**，包括 6 个 `.mesh`、
2 个 `.mdf2`、18 个 `.tex` 和那个 `.uvs` 自己。剩下 7 个是没有任何已解出文件引用到的
（顶层 `.efx` 本身等），要靠更上层的场景/prefab 才能反解。

### 怎么打

不是 git 仓库（zip 解出来的），用 `patch`：

```bash
cd "<Blender配置>/scripts/addons/RE-Asset-Library-main"
patch -p1 < "<本仓>/tools/third-party-patches/0001-re-asset-library-resolve-unknown-from-references.patch"
```

打完重启 Blender。撤销加 `-R`。

### 怎么验

补丁是拿**打完补丁的那份文件**验的，不是拿开发时的独立副本：从 patched 文件里把三个新增函数
抠出来、配上宿主自己的 `hashUTF16` 跑真实解包目录，得到 27/34。宿主的
`modules/hashing/mmh3/pymmh3.hashUTF16` 和验证时用的实现已逐位对拍过（含真实文件名里的
`4259247684` / `1207738330` 两个已知值）。
