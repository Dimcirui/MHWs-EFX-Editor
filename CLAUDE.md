# CLAUDE.md

MHWs（Monster Hunter Wilds，RE Engine）`.efx` / `.uvs` 文件的 Blender 编辑插件。
Python 胶水层（`blender_efx_re/`）↔ C# 桥接 CLI（`tools/EfxBridge`）↔ vendor RE-Engine-Lib（submodule，只读）。

**这份文件只放"动手前必须遵守的约束"。为什么这么定、字节级证据、调研过程在
[PLAN.md](PLAN.md) / [docs/](docs/) / [KNOWN_UPSTREAM_ISSUES.md](KNOWN_UPSTREAM_ISSUES.md)——
那些是档案，不是指令。改动这份文件时保持这个分工：新增的调研写进档案，只有"下次动手前必须知道"
才升级到这里。**

## 铁律 —— 违反直接产出损坏文件 / 骗过用户

1. **解析失败就整文件拒绝导入**，绝不吞异常塞半成品结构进 Blender 场景。错误结构被用户改完再导出，
   比"根本没导入"更难排查、更容易骗过用户。（架构决策 9，[PLAN.md:53](PLAN.md:53)）
2. **宁可拒绝，不要悄悄丢数据。** 任何会静默丢/截断数据的路径，都必须在 Blender 侧加导出前校验或
   UI 硬拦截。现有先例：`io_tree.check_bone_references()`、`io_tree.check_clip_bits()`、
   UvarGroups 的 2 项上限在 Add 操作符里直接 `{"ERROR"}`。新结构一律照这个办。
   （[TOPLEVEL:396](docs/TOPLEVEL_STRUCTURE.md:396) / [:700](docs/TOPLEVEL_STRUCTURE.md:700)）
3. **补不出合法版本号后缀就拒绝导出**，不留一个注定读不回来的文件。（[PLAN.md:602](PLAN.md:602)）
4. 版本号后缀校验**照抄 `PathUtils.ParseFileFormat()`**：扩展名从 basename 的**第一个**点算起，
   版本号必须紧跟其后。不能用"文件名里出现过 `.efx.<数字>`"这种宽松判断——主干里多一个点
   （`a.b.efx.5571972`）就足够毁掉整个文件。（[PLAN.md:598](PLAN.md:598)）
5. **不改 `vendor/RE-Engine-Lib` 源码**（fork 会在每次升级时持续增加维护负担）。发现的缺陷记进
   KNOWN_UPSTREAM_ISSUES.md；必须绕过时在我们自己的 `tools/EfxBridge/Program.cs` 里绕
   （先例：`PatchEffectGroupMemberOrder()`、`PatchZeroCutoutCounts()`）。（[PLAN.md:114](PLAN.md:114)）
6. **不做脏标志 / verbatim 透传二分**，每次导出全量重算（架构决策 7）。这条的前提是全语料
   "二次往返不稳定 = 0"——**每次 bump vendor commit 都要重跑整批复核确认它还成立**。（[PLAN.md:43](PLAN.md:43)）
7. **没拿到真实样本就不实现、不断言**，只把猜测记进档案等以后验证。（[TOPLEVEL:328](docs/TOPLEVEL_STRUCTURE.md:328)）

## 验证纪律 —— "怎么才算验证过"

8. **往返验证必须打到 Blender 那条真实用户路径上。CLI 层绿不代表 Blender 层绿。**
   E1 那三个缺陷藏了两个月，就是因为基线文件是 CLI 直接往返产出的，Blender 这条路的字节从没对照过。
   （[PLAN.md:650](PLAN.md:650)）
9. 判据是"**和纯 CLI 往返产物逐字节相同**"，**不是**"和原文件相同"。vendor 的哲学是总是重新生成
   字节，对原文件本来就有既有差异——拿原文件当基线只会得到一个永远红的测试。（[PLAN.md:679](PLAN.md:679)）
10. 门禁脚本：`tools/verify_blender_roundtrip.py`、`tools/verify_blender_uvs_roundtrip.py`，
    退出码 0/1，找不到样本会报错退 1 而不是静默全绿。改了 IO 路径就跑一遍。
11. **新的回归防护必须把 bug 注回去、确认它真的 FAIL**，只看它绿不算数。（[PLAN.md:676](PLAN.md:676)）
12. 手工跑 `EfxBridge load` 时**输出路径必须带 `.efx.<version>` 后缀**，用裸 `.efx` 会炸出
    `Header.Version = -1` 和垃圾 typeId——那是假故障，已经为此白排查过一整轮。（[TOPLEVEL:594](docs/TOPLEVEL_STRUCTURE.md:594)）

## 已知机关 —— 不知道就一定重踩

13. **RE Engine 的格式版本号在文件名里，不在文件内容里**（`FileHandler.FileVersion` 从路径算）。
    反过来，**写出侧不看输出路径**，字节由 JSON 里的版本号字段决定。
14. **无 setter 的属性会被 System.Text.Json 静默跳过**——`ExpressionBits`（丢了 12 字节）、
    `UvsPattern.cutoutUVs`（产物从 56776 缩到 19912 字节）都栽过，两次都不报错。碰新字段先查有没有 setter。
15. NaN/Infinity 在 JSON 里必须是**带引号字符串**；Python `json.dump` 默认写裸 token，会被
    `System.Text.Json` 直接拒绝。走 `model.json_float_in()` / `json_float_out()`。（[TOPLEVEL:470](docs/TOPLEVEL_STRUCTURE.md:470)）
16. `UpdateEffectGroups()` 重排出来的 **EffectGroups 数组顺序对游戏有意义**（E2：游戏内报
    "Invalid"）。默认原样透传 opaque 里的原始数组，组内成员顺序靠 `PatchEffectGroupMemberOrder()`
    事后 patch。别再拿 `CollisionEffect.efxEntryIndex[]` 那个"语义等价、字节不同"的先例类比它。
17. 判断 JSON 字段时**必须连值一起判断，只看 key 存不存在会踩坑**——`PatchZeroCutoutCounts()`
    第一版就是这么被 `verify_blender_uvs_roundtrip.py` 测出回归的。（[PLAN.md:359](PLAN.md:359)）

## 已定范围 —— 别重开拍过板的讨论

18. **只做 MHWs，不做 REE 通用工具。** 后端的多游戏参数化顺手保留，但 UI / 测试语料 / 功能范围
    不为假设中的 RE4/DMC5/MHRise 多花一分工。（[PLAN.md:6](PLAN.md:6)）
19. 跨 entry/attribute 的引用**一律 `PointerProperty` 指对象，不用裸下标**（架构决策 4，
    与 C# 后端靠对象身份解析的模型一致）。（[PLAN.md:33](PLAN.md:33)）
20. 字段语义标注**两层存储**（出厂表 `semantics/` + 用户个人标注表放 Blender 用户配置目录），
    从第一天就分开——EFX-Editor 的教训是标注和插件代码放一起，升级时会被整体覆盖。（[BLENDER_MODEL:83](docs/BLENDER_MODEL.md:83)）
21. `IMaterialClipAttribute` / `IMaterialExpressionAttribute` 未实现是**结构性排除**（继续走通用树
    透传），不是遗漏。（[TOPLEVEL:614](docs/TOPLEVEL_STRUCTURE.md:614)）
22. 语义标注系统**不是当前优先级**。（[PLAN.md:203](PLAN.md:203)）Entry 预设系统已实现
    （`entry_presets.py`，2026-09-10），但**范围明确收窄在"另存为预设 / 从预设新建 Entry"**——
    不做"把预设套到一个已存在的 Entry 上"（合并语义，没人问过怎么处理重复 attribute，
    YAGNI），也不做 Attribute 级别的预设。别看见"预设"两个字就以为是遗留的旧判断，先看
    entry_presets.py 实际做没做到你要的那个粒度。

## 用户可见文案 —— 只写结论，不写出处（**这条在两个项目里都反复失守**）

23. **tooltip / label / `description=` / i18n 文案只写"这个字段干什么、怎么用"，一句话说完。**
    调研方法、语料扫描计数、日期、"谁验的、验没验过"一律不进去。
    - ❌ 不要出现：「实机确认」「已确认(2026-09-10)」「语料验证」「扫了 91105 个实例」、任何日期、
      任何"模板注释说 X 但字段名像 Y，两边对不上"这类推导过程。
    - ✅ 可以写：**统计数字本身**（「全语料只出现过 0/1/2」）——那是给使用者的事实，不是出处；
      **不确定性本身**（「作用未知」）——但写成**未知状态**，不是**验证状态**（不写「尚未实机确认」）。
    - 出处 / 置信度 / 验证时间 / 推导过程 → JSON 条目的 `evidence` 字段、代码注释、`docs/`。
      `panels.py::_field_tooltip()` 本来就把 `confidence`/`evidence`/`tester`/`date` 排除在渲染之外。
    - 010 模板里已经有现成措辞的**直接复用**，别自己重写一套。
    - **Operator 的 docstring 会原样变成按钮悬停文案**（Blender 拿 `__doc__` 当 `bl_description`）。
      所以每个 Operator 都要显式写一行 `bl_description`（紧跟 `bl_label`）承担用户侧说明，
      docstring 留给开发者写设计理由——两个读者，两个字段，别混用。
    - 自检（`tooltip_zh` 中位数 26 字，超 60 字的先自问一遍是不是把调研过程写进去了；
      逐 bit / 逐取值的枚举拆解可以长）：

      ```bash
      python3 -c "import json;d=json.load(open('blender_efx_re/semantics/mhws_field_labels.json',encoding='utf-8'));print([(t+'.'+k,len(v.get('tooltip_zh') or '')) for t,f in d['fields'].items() for k,v in f.items() if len(v.get('tooltip_zh') or '')>60])"
      ```
    - 姊妹项目 EFX-Editor 有同一条规则（其 `CLAUDE.md` §4.1，带 ❌/✅ 清单和批量自查命令），
      两边保持一致。

## 名字像但是两回事

24. 顶层 `ExpressionParameters`（文件级具名参数表，已实现）**≠** attribute 内容级
    `MaterialExpressions`（未实现）。完全两套结构。
25. `Clip`（与 MHWI 的 TIML 同构，关键帧曲线）和 `Expression`（公式引擎，运算符树）是**两个独立
    子系统**，UI 分开设计。（架构决策 8）
26. [ATTRIBUTE_TYPES.md](ATTRIBUTE_TYPES.md) 是机械生成的，**只有名字 + 类型，不解释字段做什么**。
    没解释的名字当"未知"，不要当"显然是 X"。

## 遇到怪现象先查这里，别从头排查

- `ExportHelper` 吃掉版本号后缀 → `check_extension = None`：[PLAN.md:592](PLAN.md:592)
- `EfxClipData.*DataSize` 写出时不自愈，必须自己按 8/12/16 字节算：[TOPLEVEL:626](docs/TOPLEVEL_STRUCTURE.md:626)
- `EfxClipFrame.IntValue` 的 setter 是坏的（vendor bug），Int 关键帧走 `FloatValue` +
  `int_bits_to_float()`：[TOPLEVEL:645](docs/TOPLEVEL_STRUCTURE.md:645)
- 内嵌 `efxrData.parentFile` 是 `[JsonIgnore]`，JSON 路径进来是 null，递归处理前要补：[PLAN.md:640](PLAN.md:640)
- Blender 5.1.2：`cls.bl_rna.properties` 看不到自定义属性（要用 `bpy.ops.x.get_rna_type().properties`）；
  `ImportHelper` 不提供 `filepath`，必须自己声明：[PLAN.md:485](PLAN.md:485)
- 骨骼引用在嵌套 `PlayEmitter.efxrData` 子树里读写不对称，是 vendor 行为，堵不上：[BLENDER_MODEL:285](docs/BLENDER_MODEL.md:285)
- 语义表加载器是防御式的：坏文件只警告跳过，不向上抛，不拖垮 IO 路径：[BLENDER_MODEL:80](docs/BLENDER_MODEL.md:80)
- vendor 各版本的解析缺口占比、`Layout` 那 13.3%：[KNOWN_UPSTREAM_ISSUES.md](KNOWN_UPSTREAM_ISSUES.md)

## 常用命令

构建 C# 桥接（vendor 用了 C# 13 `field` 关键字，必须 `LangVersion=preview`）：

```bash
dotnet build tools/EfxBridge -p:LangVersion=preview
```

无头 Blender 跑门禁（`--factory-startup` 顺带隔离掉同机安装的姊妹插件 `efx_editor`，避免
`bl_idname` 撞车；本机只有 Steam 目录下那个是 5.1.2，其余几个 `blender.exe` 是 3.0/2.79 跑不了）：

```bash
"E:\Program\Steam\steamapps\common\Blender\blender.exe" --background --factory-startup --python tools/verify_blender_roundtrip.py
```

全语料整批往返复核（9221 个官方 `.efx`）：

```bash
dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll roundtrip "E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\EFX\natives\STM\Art\VFX"
```

`.uvs` 语料共 72 个（全是 v8），**没有统一目录**，散在 `MHWILDS_EXTRACT/**/*.uvs.8`、
`natives/**/*.uvs.8` 和 `E:\Data\MOD工具\MHWS MOD\**\UNKNOWN\` 三处。
