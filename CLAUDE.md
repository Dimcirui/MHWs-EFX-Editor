# CLAUDE.md

MHWs（Monster Hunter Wilds，RE Engine）`.efx` / `.uvs` 文件的 Blender 编辑插件。
Python 胶水层（`blender_efx_re/`）↔ C# 桥接 CLI（`tools/EfxBridge`）↔ vendor RE-Engine-Lib
（submodule，默认只读，例外见铁律 #5 和 `tools/vendor-patches/`）。

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
   KNOWN_UPSTREAM_ISSUES.md；必须绕过时优先在我们自己的 `tools/EfxBridge/Program.cs` 里绕
   （先例：`PatchEffectGroupMemberOrder()`、`PatchZeroCutoutCounts()`、`MaterialPolymorphismResolver`）。
   （[PLAN.md:114](PLAN.md:114)）**例外**：`tools/vendor-patches/` 下有编号的补丁文件——只有
   "改动小到能一眼看出对不对、且在 Program.cs 层面确实找不到干净挂钩点"才进这个目录，新增前先
   把这两条判据过一遍，不要把它当成绕开这条铁律的旁路。目前有四个：#6（`EfxExpressionParser.cs`
   的 `args==2` 分派缺 `Func18/19/20`）、#1（`ReeLibGenerator.cs` 里 `RszFixedSizeArray` 隐式长度
   前缀的 Read/Write 不对称——这是 `Layout` 13.3% 失败的真根因，全语料 roundtrip 修完后从 86.0%
   涨到 99.4%）、#4/#5（`PtColorMixerClip` 等 3 个类型缺读写实现类，补了 opaque 透传兜底 +
   `EFXAttribute.ExpectedByteSize`）、#9（`TypeStrainRibbonV3` / `FluidParticle2DSimulator`
   没声明 `IBoneRelationAttribute`，而 `BoneRelations` 是位置制索引流，漏一个消费者就整条错位——
   全语料 2.4% 的文件受影响，导出时静默丢绑定）。vendor 是 submodule，补丁不会随 `git submodule update`
   自动保留，升级 vendor 后必须重新 `git apply`（见该目录 README）。
6. **不做脏标志 / verbatim 透传二分**，每次导出全量重算（架构决策 7）。这条的前提是全语料
   "二次往返不稳定 = 0"——**每次 bump vendor commit 都要重跑整批复核确认它还成立**。（[PLAN.md:43](PLAN.md:43)）
7. **没拿到真实样本就不实现、不断言**，只把猜测记进档案等以后验证。（[TOPLEVEL:328](docs/TOPLEVEL_STRUCTURE.md:328)）

## 验证纪律 —— "怎么才算验证过"

8. **往返验证必须打到 Blender 那条真实用户路径上。CLI 层绿不代表 Blender 层绿。**
   E1 那三个缺陷藏了两个月，就是因为基线文件是 CLI 直接往返产出的，Blender 这条路的字节从没对照过。
   （[PLAN.md:650](PLAN.md:650)）**`EfxBridge roundtrip` 命令绿也不代表 `dump`/`load`（Blender
   实际走的路）绿**——`roundtrip` 是纯内存对象图二进制往返，完全不过 JSON，Func18-20（#6）、
   `material`（#7）、`TypeMeshClip` 的只读属性重复填充（#8）三个 bug 全都是"`roundtrip` 全绿、
   `dump`→`load` 直接炸"，语料覆盖率数字必须知道自己测的是哪一层，见
   [KNOWN_UPSTREAM_ISSUES.md#8](KNOWN_UPSTREAM_ISSUES.md)。
9. 判据是"**和纯 CLI 往返产物逐字节相同**"，**不是**"和原文件相同"。vendor 的哲学是总是重新生成
   字节，对原文件本来就有既有差异——拿原文件当基线只会得到一个永远红的测试。（[PLAN.md:679](PLAN.md:679)）
10. 门禁脚本：`tools/verify_blender_roundtrip.py`、`tools/verify_blender_uvs_roundtrip.py`、
    `tools/verify_blender_mdf_property.py`，退出码 0/1，找不到样本会报错退 1 而不是静默全绿。
    改了 IO 路径就跑一遍。另有 `tools/verify_blender_bone_binding.py`（骨骼绑定的落点数学
    **+ Transform3D 编辑的实时生效**——改字段要立刻烘进 Entry 的 `matrix_basis`，粒子预览的
    宿主矩阵读的就是它；改 `coords.py` / `transform3d_view.py` / `bone_binding.py` /
    `model.py` 的字段 update 回调 / `io_tree.apply_attribute_content()` 时跑）、
    `tools/verify_blender_sr_pair.py`（`{s,r}` 字段主值定位，改 `model.py` 的
    `sr_children_ordered()` / 四张 `{s,r}` 语义名单 / `panels.py` 的并排画法时跑）、
    `tools/verify_blender_sim_preview.py`（粒子预览，**含"预览跑完再导出、字节必须与跑之前
    逐字节相同"** —— 预览误写 `efx_fields` 这种错对 roundtrip 门禁完全免疫；改
    `sim_preview.py` / `efx_sim/` / `es3d_overlay.py` 时跑；ES3D 线框叠加层的检查也在这里，
    含"粒子出生位置必须落在线框包围盒内"）、`tools/verify_blender_tex_image.py`（`.tex` 解码，
    **自带"旧的坏路径"反例对照组**，改 `tex_image.py` 时跑）、
    `tools/verify_blender_asset_link.py`（导入时的资源联动，**含"联动跑完再导出、字节必须
    与跑之前逐字节相同"+ 反例对照组**；改 `asset_link.py` / `asset_paths.py` 时跑）、
    `tools/verify_blender_expression_edit.py`（Expression 公式的结构化编辑，改
    `expr_edit.py` / `efx_sim/expr.py` 的文本↔行那半边时跑。**两层判据不能互相顶替**：
    "行重拼的文本 == 导入时的文本"抓排版级改动，"全量拆开再拼回后导出的字节 == 纯 CLI
    往返基线"抓树形级改动——纯排版差异经桥接重新解析后产物字节完全相同，字节比对对它
    免疫，实测见该脚本 docstring 的注入对照表）、
    `tools/verify_blender_enum_proxy.py`（内联枚举下拉 `EFXValueNode.enum_proxy`，
    **防的是"给枚举字段选一个负数取值直接崩掉 Blender"**——`ExpressionAssignType` 有
    `ForceWord = -1`，而 `_read_packed_int()` 为位域显示把负数读成无符号
    （`-1 -> 4294967295`），两边表示不一致导致 items 里被插进一条越界的枚举数值，
    而 `EnumProperty` 的 items 第 4 位是 **C `int`**。改 `model.py` 的
    `as_int32()`/`enum_proxy`/`_read_packed_int()` 或 `attribute_types.enum_members()`
    时跑。⚠ 这类 bug **纯 Python 单测碰不到**（`model.py` import bpy）、**逐字节门禁也
    免疫**（崩在 UI 交互，文件内容没变），只能在真 Blender 里把那条 RNA 赋值做一遍；
    注回 bug 实测是 `EXCEPTION_ACCESS_VIOLATION`、退出码 11）、
    `tools/verify_blender_expression_preview.py`（Expression 公式的数值可视化 / 视口 HUD
    曲线图，改 `expr_preview.py` / `efx_sim/plot.py` / `efx_sim/expr.py` 的求值那半边时跑。
    **HUD 的 `gpu`/`blf` 绘制本身跑不到**，所以几何全挤进零 bpy 的 `efx_sim/plot.py`
    （由 `tests/test_sim_plot.py` 覆盖：自动缩放、刻度取整、`None` 断开、退化区间），
    这条门禁测数据层：真实样本上的采样值、归一化坐标、置信度取最差档、note 透传、
    "跑完预览路径后导出字节不变"、以及"`sim_preview` 建 track 时真的把具名参数传进了
    `Simulator`"。⚠ 两个别指望它的地方写在该脚本 docstring 里：「面板读数 == `efx_sim`
    求值」抓不到变量表漂移（两边喂同一个 dict），几何形状质量归单测（这里只到"不崩"级别）。
    **改了 HUD 布局要去有界面的 Blender 实测**）。
    纯 Python 那层（`efx_sim/`，零 bpy）走 `python -m unittest discover -s tests`。
    ⚠ **`--background` 下没有 GPU 上下文，`gpu` 绘制那条路门禁跑不到**，只能在有界面的
    Blender 里实测。同理 `--factory-startup` 下**第三方插件全部不加载**，`asset_link` 调
    RE Mesh Editor 那一半门禁也跑不到（要实测得 `addon_utils.enable()` 单独开它，并且先把
    它的 `showConsole` 偏好关掉——`--background` 下 `wm.console_toggle` 会直接把 Blender 崩掉）。
11. **新的回归防护必须把 bug 注回去、确认它真的 FAIL**，只看它绿不算数。（[PLAN.md:676](PLAN.md:676)）
    ⚠ **`blender --background --python x.py` 在脚本抛出未捕获异常时退出码仍然是 0**（实测），
    `sys.exit(main())` 那行根本轮不到执行——"门禁崩在第一行"和"门禁全过"对调用方长得一模一样。
    所以每个门禁的入口都要自己兜：`try: sys.exit(main()) / except SystemExit: raise /
    except BaseException: traceback.print_exc(); sys.exit(1)`。**只看 `echo $?` 不够，
    要确认输出里真的有 PASS 行。**（`asset_link` / `tex_image` / `mdf_property` / `sr_pair` /
    `expression_edit` / `expression_preview` 六个已经兜上了，其余的还没。）
    ⚠ 另一半同样容易骗人：**门禁"没测到东西"也会全绿**。`expression_edit` 为此做了两件事，
    新门禁照抄：样本里一条 Expression 公式都没有时**退 1**，以及打印"样本实际覆盖到哪些
    节点种类"（现有 `diag/` 的 13 条公式里一个一元负号都没有，负号那条规则只由内存里造的
    公式覆盖——不打印出来没人会知道）。
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
17. **`Bones` / `BoneRelations` 是位置制索引流，不认字段名**。`SetupBoneReferences()` 跨全部
    `Entries`/`Attributes` 维护一个计数器，每遇到一个 `IBoneRelationAttribute` 就消费下一个下标。
    **"谁是消费者"这个集合差一个，整条流就从那里起全体错位**，而且导出时 `BoneRelations`
    按错误的（更少的）消费者数量整体重建，静默丢槽位。已经真的漏过两个类型（#9）。
    判据靠 `Header.boneAttributeEntryCount`（游戏自己写的槽位数）对消费者个数，导入时由
    `io_tree.check_bone_relation_alignment()` 硬拦；批量核查用 `EfxBridge bonealign`。
    **唯一的例外**：插件首选项里有个默认关的「绕过骨骼绑定索引对齐校验」开关
    （`preferences.py`）。勾上之后导入放行并逐文件 WARNING，被放行的根在导出时再 WARNING
    一次（`Collection.efx_bone_alignment_bypassed` 标记）。默认行为、以及拿不到首选项的
    环境（测试）一律保持硬拦——这是受控逃生口，不是把默认改松。
    顺带：`ParentOptions.BoneName` 和 `ParentBone` 是**同一个值的两种编码**（一个内联在 attribute
    字节里、一个走文件级索引表），对齐正确时永远一致——看到两者不一致，先怀疑索引流错位，
    别当成"其中一个是死字段"。
18. `MdfProperty` 的 JSON **键序有意义**：vendor 的转换器是流式读的，读到 `value` 时按*当时
    已经读到的* `parameterType` 决定解析成贴图还是 float4（`EfxFile.cs:541`）。造新条目时
    `parameterType` 必须排在 `value` 前面，否则贴图属性会被当成 float4 读进来。
19. 判断 JSON 字段时**必须连值一起判断，只看 key 存不存在会踩坑**——`PatchZeroCutoutCounts()`
    第一版就是这么被 `verify_blender_uvs_roundtrip.py` 测出回归的。（[PLAN.md:359](PLAN.md:359)）

## 已定范围 —— 别重开拍过板的讨论

20. **只做 MHWs，不做 REE 通用工具。** 后端的多游戏参数化顺手保留，但 UI / 测试语料 / 功能范围
    不为假设中的 RE4/DMC5/MHRise 多花一分工。（[PLAN.md:6](PLAN.md:6)）
21. 跨 entry/attribute 的引用**一律 `PointerProperty` 指对象，不用裸下标**（架构决策 4，
    与 C# 后端靠对象身份解析的模型一致）。（[PLAN.md:33](PLAN.md:33)）
22. 字段语义标注**两层存储**（出厂表 `semantics/` + 用户个人标注表放 Blender 用户配置目录），
    从第一天就分开——EFX-Editor 的教训是标注和插件代码放一起，升级时会被整体覆盖。（[BLENDER_MODEL:83](docs/BLENDER_MODEL.md:83)）
23. `IMaterialClipAttribute` / `IMaterialExpressionAttribute` 未实现是**结构性排除**（继续走通用树
    透传），不是遗漏。（[TOPLEVEL:614](docs/TOPLEVEL_STRUCTURE.md:614)）
24. 语义标注系统**不是当前优先级**。（[PLAN.md:203](PLAN.md:203)）Entry 预设系统已实现
    （`entry_presets.py`，2026-09-10），但**范围明确收窄在"另存为预设 / 从预设新建 Entry"**——
    不做"把预设套到一个已存在的 Entry 上"（合并语义，没人问过怎么处理重复 attribute，
    YAGNI），也不做 Attribute 级别的预设。别看见"预设"两个字就以为是遗留的旧判断，先看
    entry_presets.py 实际做没做到你要的那个粒度。

## 用户可见文案 —— 只写结论，不写出处（**这条在两个项目里都反复失守**）

25. **tooltip / label / `description=` / i18n 文案只写"这个字段干什么、怎么用"，一句话说完。**
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

26. 顶层 `ExpressionParameters`（文件级具名参数表，已实现）**≠** attribute 内容级
    `MaterialExpressions`（未实现）。完全两套结构。
27. `Clip`（与 MHWI 的 TIML 同构，关键帧曲线）和 `Expression`（公式引擎，运算符树）是**两个独立
    子系统**，UI 分开设计。（架构决策 8）
28. [ATTRIBUTE_TYPES.md](ATTRIBUTE_TYPES.md) 是机械生成的，**只有名字 + 类型，不解释字段做什么**。
    没解释的名字当"未知"，不要当"显然是 X"。
29. **Expression 里的 `Clamp` 不是"夹住"，是重映射、两端饱和、而且中段带 smoothstep
    缓动**：`Clamp(value, hi, lo)` = `u = saturate((value - lo) / (hi - lo))`，返回
    **`u²(3 - 2u)`**（2026-09-16 实机确认缓动那一层：拿**不经过任何待测函数**的线性基准
    `TIMER/100`（= `100 - TIMER`，除法已确认）对拍，`Clamp` 的残差是 S 形摆动；再和
    `smoothstep` 参考曲线对拍则死平，和正弦缓动对拍则 ±1 摆动。**端点和饱和不受影响**，
    所以下面那条"`hi` 翻倍只改到达时间"的旧结论仍然成立——它只约束饱和、对中段不敏感，
    这也是缓动能藏这么久的原因）。⚠ **这个缓动不属于 `Func21`**：`Func21` 的重映射是
    线性的，两者之差就是这层缓动（铁律 #33），`_eval_func21()` 故意**不复用**
    `_eval_clamp()`。⚠ **测这类"中段形状"必须换一个不经过待测函数的基准**：此前所有测试
    里 `Lerp(Clamp(…))` 要么当时间轴（Z 轴用的就是它，横纵同样扭曲、图形不变）、要么和
    自己比（零差网的扫描量两边同一个表达式，缓动整项抵消），所以一直测不出来。
    读法开关 `SimConfig.expr_clamp_mode` 默认 `remap_smoothstep`，线性那档降级为对拍。
    下面这段是**饱和**那一层的依据：把 value 从 `[lo, hi]` 映到 `[0, 1]`，**上界钳**
    （2026-09-16 实机确认：同一个 `Lerp(Clamp(TIMER,hi,0),-1,0.5)`，`hi` 翻倍只让到达终点
    的时间翻倍、终点位置不变，直接排除了"上界不钳"；语料里 95 处 `Min(Clamp(...), 1)`
    以前当过"上界不钳"的证据，**铁律 #32 之后彻底解释清楚了**：`Min(a,b)` 其实是 `b - a`，
    那 95 处就是最常见的淡出写法 `1 - Clamp(...)`，和上界钳不钳毫无关系——
    "作者手写的防御性冗余封顶"这个中间解释也一起作废）。**下界钳 0 没被
    这次实机测试覆盖**（测试恒用 `lo=0`、`TIMER≥0`，`value` 从没低于 `lo` 过），仍是语料
    间接证据（默认档 `remap_saturate_both` 照对称假设钳了下界，没独立验证过）。`Lerp`/`InvLerp`/`Clamp`
    这三个名字和 `Unary0`~`Unary12` 一样**都只是 vendor 在枚举里起的名，不是确认过的
    语义**——别因为它叫 Clamp 就当 clamp 用，这个坑已经踩过一次（旧读法让全语料 31.5%
    的公式算出的量级差几个数量级）。读法开关 `SimConfig.expr_clamp_mode`，逐条语料证据见
    [EXPRESSION_SEMANTICS.md](docs/EXPRESSION_SEMANTICS.md)。`InvLerp` 也已实机确认：`InvLerp(a, b, t)` == `b + (a-b)*saturate(t)`，**就是 `Lerp`、系数挪到最后一个参数**，不做任何反向的事。
    界面上的参数角色名（`efx_sim/expr.py` 的 `CALL_ARG_ROLES`）**只准收语义已定、
    而且参数顺序反直觉的调用**——现在是 `Clamp`/`Lerp`/`InvLerp`/`Min`/`Max`/`Func20`/
    `Func21` 七条。对称运算（`Func18`/`Func19` = min/max）和一元函数**故意不收**：
    标了没有信息量。判据是"不标会不会写错"，不是"反正已经确认了就都标上"——
    和 #25 是同一条纪律的字段级版本。
    另一条和界面直接相关的语料事实：**没有"一定是常量"的参数槽位**——每个槽位都出现过
    字面量/变量/子表达式三种（`Lerp.to` 1729/483/24、`Clamp.hi` 1503/4/20，槽位 1 现在
    叫 `to` 见铁律 #31），而且
    "输入在第几个参数"是**逐函数固定**的（`Func21` 在最后、`Max`/`InvLerp` 不在第 0 位）。
    所以别写"第一个参数是输入"这种硬编码，也别按内容类型给槽位分三种画法——
    公式编辑器为此重做过一次，依据见 [EXPRESSION_SEMANTICS.md 第 8 节](docs/EXPRESSION_SEMANTICS.md)。
30. **`ExpressionAssignType` 的五个取值语义已实机确认**（2026-09-16）：`Assign` 直接
    替换目标字段，`Add`/`Subtract`/`Multiply`/`Divide` 是**在导入时的原始值基础上**做
    对应运算（`efx_sim/simulator.py` 的 `_EXPR_ASSIGN_OPS` + `base_value` 快照就是这个
    模型，实现无需改动）。这条之前一直是"vendor 起的名、没实机验过"，而同一文件家族的
    `BinaryExpressionOperator` 战绩是 0/6 全错，所以它是当时最大的未验证风险，现在关了。
    ⚠ **界面上不要提供 `ForceWord = -1`**——它是 C# 侧用来强制枚举宽度的占位，不是游戏
    语义；选它曾经直接崩 Blender（见铁律 #10 门禁清单里 `verify_blender_enum_proxy.py`
    那条）。
31. **`Lerp(t, a, b)` 的方向和直觉反着来：`t=0` 取第 3 参 `b`、`t=1` 取第 2 参 `a`**
    （2026-09-16 实机确认，此前实现是反的：`a+(b-a)*t`，已改成 `b+(a-b)*t`）。依据：两条
    对照粒子轨迹只交换 `Lerp` 的第 2/3 参（`Lerp(Clamp(TIMER,15,0),-1,0.5)` 和
    `Lerp(Clamp(TIMER,15,0),0.5,-1)`），`ExpressionAssignType` 确认是 `Assign`（排除基准值
    叠加的混淆），实机观察到的运动方向两次都只和"新读法"对得上、和"旧读法"对不上。
    **语料本身测不出这个方向**——`Lerp(Clamp(EM_SPEED,6,3),0,8)` 落在 `[0,8]` 这条旧证据
    只能确认"哪个参数是 t"，两种方向下输出都同样落在 `[0,8]` 集合里，从没独立测过方向。
    `CALL_ARG_ROLES["Lerp"]` 已从 `("t","from","to")` 改成 `("t","to","from")`，UI 上
    第 2 参的标签变成"to"、第 3 参变成"from"。改了这两个函数相关的代码/文档，记得连带查一遍
    是不是依赖了旧方向：`efx_sim/expr.py::_eval_ternary_known()`、
    `tests/test_sim_expr.py`/`test_sim_expr_edit.py`、
    `tools/verify_blender_expression_edit.py`/`verify_blender_expression_preview.py`，
    逐条证据见 [EXPRESSION_SEMANTICS.md 第 1.1 节](docs/EXPRESSION_SEMANTICS.md)。

32. **Expression 文本里的六个二元运算符，vendor 标的名字一个都不对**（2026-09-16 实机
    逐个测出来）。文本符号 → 真实语义：

    | 操作码 | 文本写法 | vendor 叫它 | **真实语义** |
    |---|---|---|---|
    | 0 | `Max(a, b)` | Max | `pow(b, a)`（指数在左，语料推断）|
    | 1 | `a + b` | Add | **`a * b`** |
    | 2 | `a - b` | Sub | **`b / a`**（被除数在右；除零按 0，引擎实测行为）|
    | 3 | `a * b` | Mul | **`fmod(b, a)`**（模数在左；C 语义，符号跟被除数）|
    | 4 | `a / b` | Div | **`a + b`** |
    | 5 | `Min(a, b)` | Min | **`b - a`**（被减数在右）|

    **真正的 min/max 在这套表达式里不存在。** 一元负号是唯一没标错的。把操作数顺序
    翻过来看（引擎的操作数顺序和 vendor 的 left/right 相反），六个操作码依次是
    **幂/乘/除/模/加/减**——严格的优先级降序，像引擎按优先级排的枚举。
    **写公式时要乘就打 `+`、要加就打 `/`**，别按符号字面意思写。实现在
    `efx_sim/expr.py::_eval_binary_operator()`（逐点实机读数都在那条 docstring 里），
    回归在 `tests/test_sim_expr.py::TestBinaryOperatorsAreAllMislabeled`。
    ⚠ **文本符号本身必须原样保留**——那是 vendor 解析器认的字面量，换符号就往返不回来。
    只有"符号算什么"是我们这层的事。
    ⚠ **这个坑躲得过所有往返验证**：文本↔操作码两边用同一套错误约定，所以逐字节门禁、
    文本重拼门禁、`exprcheck`、300 个单测全部绿灯——**往返自洽性对"双向一致的错误"
    完全免疫**（和铁律 #17"两个字段不一致只是对称证据"同一类教训）。唯一能测出来的是
    实机：`Lerp(Clamp(TIMER,15,0),0.5,-1)` 驱动 Y 当时间轴、Z 填被测公式、单粒子
    `TypeRibbonFollow` 的轨迹当示波器，读数靠"直接填常量"校准，交换操作数顺序对拍。
    `efx_sim/expr.py` 模块 docstring 里原来有一段把 `+ - * /` 划进"完全确认"档的作用域
    论证（"操作码↔符号的对应是文件→文本这一步的问题，不在本模块范围"），**那段论证连同
    它为什么错已经留在原处当教训**，别再照它推理。
    逐条语料翻译对照见 [EXPRESSION_SEMANTICS.md 第 9 节](docs/EXPRESSION_SEMANTICS.md)。

33. **`Unary<N>` 12 个全部已实机测出语义，`Func21` 也定了**（2026-09-16）：
    `Unary0`=`sin`、`Unary1`=`cos`（**弧度**）、`Unary4`=`floor`、`Unary5`=`ceil`、
    `Unary6`=`ln`、`Unary7`=`log10`、`Unary8`=`exp`、`Unary9`=`abs`、
    **`Unary10`=`saturate`（clamp01，全语料最高频 2063 次）**、
    `Unary11`=`sin`、`Unary12`=`cos`（**这两个是角度制**）、`Unary2`=`asin`。
    **`Func21(a, b, hi, lo, t)` == `Lerp(Clamp(t, hi, lo), a, b)`**（线性，`t` 在 `lo`
    端取第 2 参）。于是语料高频写法 `Unary11(Func21(90, 0, hi, 0, TIMER))` 完全读通了：
    角度在 hi 帧内从 0° 线性升到 90°、再取正弦 = 0→1 的缓出——那个 `90` 是**度数**。
    **`Func18` = `min`、`Func19` = `max`、`Func20` = `pow(b, a)`** —— 二元操作码 0~5 里
    没有 min/max，那个空缺就是 `Func18`/`Func19` 填的（**别和文本里的 `Min(`/`Max(`
    搞混**，那两个是操作码 5/0，实际是减法和幂）。**函数全部测完，`_UNKNOWN_FUNC_ARGC`
    已经空了。**
    `Func20` 和 `Max(`（操作码 0）**都是幂，这不是异常**：二元操作码表是**中缀运算符
    表**（按优先级降序：幂/乘/除/模/加/减，所以幂在 0 号），函数表是**内建函数表**，
    同时有中缀 `^` 和函数 `pow()` 是绝大多数语言的常态。
    整张表定完之后做了一张**零差自检网**（9 条恒等式，`docs/EXPRESSION_SEMANTICS.md`
    第 12 节、`tests/test_sim_expr.py::TestSelfConsistencyIdentities`）：用已确认语义
    搭恒等式，正确时恒为 0、乘 20 放大后实机应画出死平在 0 的线。逐个投毒验证过它真的
    会破（`Unary0`→cos 破 3 条、`/`→除法破 2 条等）。**这九条可以直接拿进游戏跑，
    实机全平才算端到端确认**——单测绿只证明"文本和我们的表自洽"。**枚举里没有的 3/13/14 也测过了**（改字节绕开解析器，
    工具 `tools/patch_expression_opcode.py`）：**3 = `acos`**（0/1/2/3 = sin/cos/asin/acos
    齐了，但插件里仍然写不出来——解析器不认这个名字，要等上游补枚举）；
    **13/14 引擎没实现**（输出既不依赖操作数个数、也解释不成输入的任何函数，是未实现
    操作码的退化路径），vendor 跳过它们是对的。
    实现在 `efx_sim/expr.py::_eval_known_unary()`，回归在
    `tests/test_sim_expr.py::TestKnownUnaryFunctions`。
    ⚠ **测这类函数时输入必须扫 `[-2, 2]`，不能只喂 `[0, 1]`**——在 `[0,1]` 上
    `identity`/`abs`/`saturate` 三者全等、`floor`/`trunc` 全等、`ceil`/`sign` 全等，
    第一轮就是这么卡住的。宽扫之后每个候选画出的形状都不一样（直线 / V 字 / `_/‾` /
    阶梯 / 两级台阶），一次运行一眼判读。
    ⚠ **拿"未知函数"当测试样本前先查一遍这条**：`tools/verify_blender_expression_preview.py`
    和 `tests/test_sim_expr.py` 里原来都用 `Unary10` 当"语义未知"的样本，它一确认这些
    检查就静默失效了（已改成用 `Unary2`，并补了一条反向检查"已确认的不能再算未知档"）。
    ⚠ **探针必须自带限幅**：信号一跑出画面幅度就读不出来（`±2` 和 `±21` 在屏幕上长得
    一样，`Func21` 的插值方式为此来回翻了三次）。用 `Func18(0.4, Func19(-0.4, X))`
    （= `min(0.4, max(-0.4, X))`）夹住，让"超出量程"表现为**可读的削平**。
    ⚠ **零差检验必须配正对照**："完全平在 0"和"公式根本没生效"在画面上一模一样——
    把参考曲线的端点故意改错、确认它真的画出已知偏差，再换回原式。
    ⚠ **形状判读顶不住定量结论**：`Func21` 的插值方式被"直接画出来看形状"读错过一次
    （1 米高配 4 米宽的浅斜线看着像缓 S）。可靠办法是**放大残差的零差检验**——拿已确认
    语义搭一条参考曲线、和被测量相减、再乘个大系数（`20 + <差>` 就是 ×20），"完全平在
    0"比"看着像"可靠得多；配一个正对照排掉"两项都恒 0"的假阳性。判读形状前还要先算
    两个轴各占多少米，以及确认可视范围的上界在哪（`Unary2` 的"消失点"差点被当成画面边界）。
    **语义定下来之后要连带过一遍这三处界面/推导层**（2026-09-16 已做）：
    ① `CALL_SEMANTICS`（`efx_sim/expr.py`）—— 编辑器菜单里每个调用后面显示真实语义，
    **必须显示**：名字全是错的，只给名字等于让用户照字面写错公式；
    ② `CALL_ARG_ROLES` —— 只给"参数顺序反直觉、不标会写错"的加角色名
    （`Min`/`Max`/`Func20`/`Func21`），对称运算（`Func18`/`Func19`）和一元函数**故意不标**；
    ③ **`_UNIT_PRESERVING_ARG_POSITIONS` 必须重算** —— 旧表按 vendor 的名字收了
    `+`/`-`/`Max`，而它们实际是乘/除/幂，**都不保持单位**，会让"角度显示"开关去换算
    一个其实是无量纲系数的常量、静默改坏不相关的数值。现在收的是 `/`（加）、`Min`（减）、
    `*`（取模）、`Func18`/`Func19`（真 min/max）、`Lerp`、`Func21`、`abs`/`floor`/`ceil`。
    逐条判据和语料回读见
    [EXPRESSION_SEMANTICS.md 第 10、11 节](docs/EXPRESSION_SEMANTICS.md)。

## 遇到怪现象先查这里，别从头排查

- **公式面板卡顿：别逐行"重建子树文本 -> 重新解析 -> 求值"，那是 O(N²)。**
  `expr_preview.subtree_values()`（结构树变调试器的数据源）每次面板重绘都跑一遍，
  原来的逐行做法实测 225 行 8.8 ms / 449 行 16 ms / 897 行 36 ms / 1793 行 88 ms，
  而**完整求值一次只要 0.45 ms**。已改成 `efx_sim/expr.py::evaluate_rows()` 一次自底向上
  遍历算完（提速 47~64 倍，复杂度回到线性）。⚠ **`_eval_collect()` 必须和 `_collect_rows()`
  逐字同序**（前序 + `-字面量` 折叠成一行），差一个节点面板上每行的值就静默错位到隔壁
  子树——由 `tests/test_sim_expr_edit.py::TestEvaluateRows` 钉住（两种顺序漂移都注入验证过
  会 FAIL）。顺带：真实语料的表达式中位数才 4 个组件、最大 12，这条只在人为构造的复杂
  公式上才显形（实机用傅里叶级数压到 64 阶时发现的）。

- **`.tex` 别走 `bridge.convert_tex_to_dds()`**，走 `tex_image.load_image()`。MHWs 的 tex
  载荷是 **GDeflate 压缩**的，vendor 的 `ConvertToDDS()` 把压缩字节直接套个 DDS 头，产物是
  **纯噪声**（不是 vendor 缺陷：`TexFile` 有 `DecompressGDeflate(callback)`，是我们的
  `Program.cs` 没传过回调）。⚠ **噪声和正确图像在统计上分不开**（非零占比/均值/最大值几乎
  一样），判断解码对不对**只能看图**或靠"解压后字节数 == 理论紧凑大小"这种结构性等式。
- **引用资源（`.mesh`/`.mdf2`/`.uvs`/`.tex`）的搜索根，首选是"被导入的那个 efx 自己的位置
  向上回溯到含 `natives/` 的那一层"**，资产库（Asset Browser）的语料目录只是**兜底**。
  语料目录是"随便一堆官方 efx 放哪儿"的设置，和当前文件没有必然关系——拿它当首选会在
  mod 工程场景下静默加载到官方原版的同名文件，界面上完全看不出来。来源目录由导入算子记在
  `Collection.efx_source_dir` 上，优先级全在 `asset_paths.search_roots()`。
- **导进来的 VFX 网格是纯白/纯黑，八成不是路径问题**，是这两件事：
  ① **`.mdf2` 常常只是个占位材质**（贴图槽全填 `NullWhite.tex` / `NullBlack.tex`），
  真正的贴图在 **EFX attribute 的 `properties` 覆盖表**里运行时顶上去——那张表存在的意义
  就是这个。只导 mdf2 不管覆盖表 = 纯白。走
  `asset_link._apply_property_overrides()`：靠 `PropertyNameUTF8Hash` 查
  `mdf_catalog.candidates()` 得到槽名（`BaseMap`/`EmissiveMap`/…），再换掉材质里 `label`
  等于该槽名的贴图节点（RE Mesh Editor 建节点时就拿槽名当 label，实测 7/7 命中）。
  ② **`MeshPath` 和 `MaterialPath` 不是配套的一对**，两边材质名可以完全不一样（实测 52 对
  真实引用里 11 对对不上，极端例子是网格 6 个材质槽 `Base3~Base8` 配 mdf2 一个 `lambert1`）。
  RE Mesh Editor 按材质名绑，对不上时把节点树清空就走 = 纯黑。走
  `asset_link._ensure_material_applied()`：**mdf2 只有一个材质**时就往全部材质槽上套
  （EFX 的 attribute 只有一个 `MaterialPath`、一张覆盖表，没有"第几个 submesh 用哪个"这一维）；
  mdf2 本身多材质才是真歧义，不猜、如实记 problem。
- **粒子预览里网格的颜色必须从材质上取，不能只信模拟层的 `Color`/`EmissiveColor`**：
  实测一个真实 mod 的全部 24 个 `TypeMeshV2`，这两个字段都是纯白 `(1,1,1)`——EFX 侧压根
  没有颜色信息，颜色在材质的 `EmissiveParam` 里。而且 `_resolve_mesh_tris()` 原来只收顶点
  位置、不收 UV 也不收贴图，`_collect_mesh()` 于是恒定落进 FLAT_COLOR 分支 = 一块纯白。
  现在逐三角形带上 UV + 材质贴图名 + 材质染色（`_material_preview_look()`），
  `_gpu_texture()` 同时认"游戏内部路径"和"`bpy.data.images` 的名字"两种 key。
- **一个 `.mesh` 里装着好几段，`PartsStartNo` 决定用哪几段**（`asset_link._keep_parts()`）。
  不筛的话每个 attribute 都把整份网格导一遍全堆在一起（实测一个 mod：18 段 × 24 个
  attribute），视口里就是一坨互相盖住的白块。⚠ **下标是"这份 mesh 里第几段"（把出现过的
  `Group_<N>` 去重排序后的序号），不是 `Group_` 后面那个数字**——拆过的 mesh 里那个数字
  保留着原模型编号（`POD042_001.mesh` 只有 `Group_15/16/17`，它的三个 attribute 写的是
  0/1/2）。拿段号直接对下标会看起来像左开右闭，实际是**左闭右开**：`POD042_000.mesh` 段号
  0~17 连续，attribute `[base5]` 的 `(6,7)` 正好命中材质为 `Base5` 的 `Group_6`，
  `base9_7` ↔ `(7,8)` ↔ `Group_7`——attribute 名字自己就把下标写在里面。
- **RE Mesh Editor 的 alpha 硬裁剪链对 VFX 遮罩会整条退化成 0**：它按 mdf 的 alpha-test
  标志接 `RGBtoBW(遮罩) -> GREATER_THAN(0.5) -> BSDF.Alpha`，而 VFX 遮罩常常很淡（实测
  `01_ring_alpha000` 最大亮度 0.216、`04_ring_alpha000` 只有 0.085），**整张图没有一个像素
  过得了 0.5**，那个 attribute 一点都画不出来。`asset_link._soften_degenerate_alpha_test()`
  只在这种**可证明退化**（贴图最大亮度 < 阈值）时拆阈值 + 转 `BLEND`；过得了阈值的不动。
  另外 VFX 遮罩**在哪个通道不固定**（`base9.tex` 是 RGB 纯白、形状全在 alpha 里），
  `_retarget_mask_channel()` 按"哪个通道真的有变化"改接。
- **VFX 材质的自发光要我们自己接**：RE Mesh Editor 的 `newEMINode()` 只认
  `Emissive_Color`/`EmissiveIntensity` 那几个拼法，VFX 材质用的是
  `EmissiveParam`/`EmissiveIntensityParam`，它那条通路整条静默不触发，
  `Emission Strength` 留在 0 —— 模型在视口里就是一块白。
  `asset_link._wire_emission()` 补上，**接法逐节点照抄 `newEMINode()`**
  （`EmissiveMap × 颜色参数 -> Emission Color`；`RGBtoBW(EmissiveMap) × 强度 ×
  EMISSION_MULTIPLIER -> Clamp -> Emission Strength`），连那个 0.1 的
  `EMISSION_MULTIPLIER` 都是从它模块里读的，不抄成字面量。**它自己接过的不抢**
  （`Emission Strength` 已有连线就跳过）。补的参数名只有 `EmissiveParam` /
  `EmissiveColorParam` / `EmissiveIntensityParam` 三个（扫 40 个真实 VFX mdf2 定的），
  `RimEmissive*` / `EmissiveMask*` / `Allover_Emissive_Intensity` 是别的特性，**不要收进来**。
- **覆盖表里同名条目可能不止一条**：覆盖表按 `PropertyNameUTF8Hash` 认参数，
  `mdfPropertyIndex` 只是快路径，mod 作者改过 mdf2 之后下标会漂（实测 POD042 有两条都
  哈希成 `EmissiveParam`，下标一条 3 一条 4，而 mdf2 里 4 号其实叫 `RimEmissive_Color`）。
  取值时挑"和材质默认值不一样"的那条（作者真正改过的那条），别无脑取最后一条。
- **`tex_image.load_image(reuse=True)` 判"这张图已经载过"不能只看 `has_data`**：它是
  "像素缓冲此刻在内存里"，刚 pack 进 .blend 还没人取过像素时是 False，复用永远不命中，
  同一张贴图会堆出一串 `.001/.002/…`（实测把 7 张贴图复制成 64 份）。要连 `packed_file`
  一起判。这条错不报任何错，只是 .blend 悄悄胖几十倍。
- **`.tex` / `.mesh` 在游戏里各存两份，`natives/STM/streaming/<路径>` 那份才是完整的。**
  `.tex` 非 streaming 那份是降采样小图（实测 `11_glow_000_ALPG`：128×128/1 mip vs
  512×512/3 mip，**两份都能解码成功，拿错了只是糊**）；`.mesh` 非 streaming 那份**没有顶点
  缓冲**，RE Mesh Editor 按 `<natives 根>/streaming/<相对路径>` 自己去拼那份，拼不到直接抛
  "Streaming mesh file is missing"。`asset_paths.resolve()` 对 `.tex` 已经 streaming 优先，
  `.mesh` 走 `asset_paths.ensure_streaming_companion()` 把伴生份落到**同一个** natives 根下。
  这也是 pak 缓存必须按 `natives/STM/` 原样镜像、不能拍平文件名的原因。
- **生成区域线框必须来自 `EmitterShape3D.outline()`，不许另算一套形状。** 它和 `on_particle_spawn()`
  共用同一份区间读法（含 `es3d_range_mode` 标定开关）和同一条 `_apply_local_rotation()`，改一边
  必须改另一边。姊妹项目为此删掉过一整个 Geometry Nodes 版本——那版对 range 字段的读法和模拟层
  不一致，画出来的框和粒子实际落点互相矛盾。`tools/verify_blender_sim_preview.py` 用"粒子必须
  落在线框包围盒内"钉住这条。顺带：**Box 是实心的**（逐轴 `U(lo,hi)` 独立取），只有球/圆柱的径向
  幅度才是 `[lo,hi]` 壳层——照搬姊妹项目给 Box 画内层会画出一个"这里不会有粒子"的假空腔。
  **`EmitterShape3D.RangeX/Y/Z` 是 `(min, max)`**，外边界就是第二个数——**不是** MHWI 那种
  `min + offset`（外边界 = `min+offset`），更不是 (静态值, 随机量)。判据是"`max < min` 出现过
  没有"：**0/62492**，而主值非零的有 36590/20748/36840 例；offset 读法下第二个数是**厚度**，
  半径 1.0 厚 0.1 的薄壳就该写成 `(1.0, 0.1)` 即 `max < min`，一次都没有。原来那个
  `SimConfig.es3d_range_mode` 标定开关**已删**（它的默认档把 `(-0.5, 0.5)` 这种对称圆柱读成
  `[-0.5, 0]`，高度少一半）。
- **`{s,r}` 字段的"主值"不是固定的 `s`**：`via.Range`(float) 声明成 `{s,r}`、`via.RangeI`(int)
  声明成 `{r,s}`（`RszValueType.cs:226`/`:264`），**二进制首字段恒为主值**（静态值 / min）。
  两者 **key 集合完全相同**，只能看子节点 `data_type` 区分——写死 `s` 会把全部 46 个 `RangeI`
  字段读反（`Spawn.LoopNum` 的 `(r=1,s=0)` 是"循环 1 次"，不是"静态 0/随机 1"）。一律走
  `model.sr_children_ordered()`。副值是"随机量"还是"max"**逐字段**定，四张名单都在 `model.py`
  （`_SR_INDEX_FIELD_NAMES` / `_SR_MIN_MAX_FIELD_NAMES` / `_PAIR_MIN_MAX_FIELDS` /
  `_MIN_MAX_FIELD_NAMES`），`efx_sim/shapes.py` 存镜像、由单测钉住一致。
  语料证据：[SIM_PORT_PLAN:8.6](docs/SIM_PORT_PLAN.md)
- **要判"这个二元字段到底是 min/max 还是 静态值/随机量"，别靠字段名猜，跑审计**：
  `EfxBridge pairstats <语料目录> out.json`（全语料一遍扫完，~50 秒，出**联合分布**原始计数）
  + `python3 tools/audit_range_fields.py out.json`（判据在这儿，改判据不用重编 C#）。
  判据两条：① **`副值 < 主值` 出现过（任意量）-> 默认回退 static/random**。这不只是
  "max<min 讲不通"，更是**界面诚实性**：标成 Min/Max 会让用户默认 `Min <= Max` 恒成立，
  语料里有反例时那个标签本身就在骗人；回退的代价只是少解释一层语义，标错的代价是用户照着
  错的心智模型填数。② `副值<主值` **一次都没有**时看 **MM 招牌**（"区间退化成一个点"）：
  闭区间是 `q == p 且 p != 0`，**半开区间是 `q == p+1`**（半开下 `q==p` 是空区间、结构上恒 0，
  不分开算会把 `PatternNo`/`PartsStartNo` 误判成"没证据"）。占比成规模就判 min/max。
  ⚠ **必须排掉 `p == 0`**：`(0,0)` 两种读法都满足，那是"没填"的默认值，零信息量。
  ⚠ 别再单独统计 `q == 0` 当"不随机"的证据——`q<p` 已经把它包含了，而且 `p<0` 时
  `(-0.25, 0)` 是个正常区间 `[-0.25, 0]`，单独统计会误伤。
  ①回退掉、但 MM 招牌同时也成规模的额外标成**有争议**（17 个，如两个 `BasingPoint`）。
  开闭同理靠语料：**`Max == Min` 出现过 = 闭区间**（"固定一个值"的常规写法），
  **一次都没有 = 左闭右开**（半开下它恰好是空区间，作者永远不会写）。半开名单
  `_HALF_OPEN_MAX_FIELD_NAMES` 同时供面板提示和 `shapes.roll_sr_min_max_int()` 取样，
  **别在 behavior 里自己写 `hi - 1`**（`PatternNo` 原本就是这么埋着的）。
- `ExportHelper` 吃掉版本号后缀 → `check_extension = None`：[PLAN.md:592](PLAN.md:592)
- `EfxClipData.*DataSize` 写出时不自愈，必须自己按 8/12/16 字节算：[TOPLEVEL:626](docs/TOPLEVEL_STRUCTURE.md:626)
- **`RszByteSizeField` 标的字段一律不自愈**（代码生成器只处理 `RszArraySizeField`，
  `ReeLibGenerator.cs:412` 那个 `if` 里没有它）。`EFXAttributeTypeMeshV2.propertiesDataSize`
  就是这么栽的：增删 `properties` 不重算它，写出的文件整个读不回来。增删这个数组走
  `io_tree._refresh_derived_sizes()`（`len(properties) × (32 或 28，按版本号 ≥2228526 二选一)`）。反过来 `texCount` /
  `texPathBlockLength` / `textureIndex` / `pathLength` 都会被 `DoWrite()` 自动重建，别重复算。
- **别照 `[Rsz*Field]` 标注判断"这个字段是不是记账量"**——标注和"写出时会不会重算"没有稳定
  对应关系（见上一条）。要判断就跑 `tools/scan_derived_fields.py` 投毒实测，它按"往 JSON 塞
  错值、写出再读回来看谁赢"给结论。已知反例：`unknDataSize` 标了 `RszByteSizeField` 但没人
  重算（是真实数据）、`mdfPropertyIndex` 只有贴图那条被强制。面板不画的记账字段名单在
  `panels._DERIVED_FIELD_KEYS`，**vendor 升级后要重跑这个脚本确认名单还成立**。
- `EfxClipFrame.IntValue` 的 setter 是坏的（vendor bug），Int 关键帧走 `FloatValue` +
  `int_bits_to_float()`：[TOPLEVEL:645](docs/TOPLEVEL_STRUCTURE.md:645)
- 内嵌 `efxrData.parentFile` 是 `[JsonIgnore]`，JSON 路径进来是 null，递归处理前要补：[PLAN.md:640](PLAN.md:640)
- Blender 5.1.2：`cls.bl_rna.properties` 看不到自定义属性（要用 `bpy.ops.x.get_rna_type().properties`）；
  `ImportHelper` 不提供 `filepath`，必须自己声明：[PLAN.md:485](PLAN.md:485)
- 骨骼引用在嵌套 `PlayEmitter.efxrData` 子树里读写不对称，是 vendor 行为，堵不上：[BLENDER_MODEL:285](docs/BLENDER_MODEL.md:285)
- 语义表加载器是防御式的：坏文件只警告跳过，不向上抛，不拖垮 IO 路径：[BLENDER_MODEL:80](docs/BLENDER_MODEL.md:80)
- vendor 各版本的解析缺口占比：[KNOWN_UPSTREAM_ISSUES.md](KNOWN_UPSTREAM_ISSUES.md)（`Layout`
  那 13.3% 已经在 `tools/vendor-patches/0002-*` 修掉，全语料 roundtrip 现在是 99.4%）

## 第三方插件补丁

`tools/third-party-patches/` 放给**别人的插件**打的补丁（区别于 `vendor-patches/` 改我们自己
submodule 进来的 vendor）。目前一个：给 RE-Asset-Library 的 pak 解包加"用已解出文件里的资源
路径引用反解 `UNKNOWN/` 文件名"。⚠ 第三方插件不在版本控制下，**它每次更新都会覆盖补丁**，
要重新打——用法和依据见该目录 README。

## 常用命令

构建 C# 桥接（vendor 用了 C# 13 `field` 关键字，必须 `LangVersion=preview`）。**先重新
`git submodule update` 过 vendor 的话，要先重新打一遍 `tools/vendor-patches/` 下的补丁**
（例外，见铁律 #5），否则编译出来的是没修过 Func18/19/20、`Layout`、`PtColorMixerClip` 等
类型的旧行为：

```bash
git apply tools/vendor-patches/0001-efx-expression-func18-19-20-args2-dispatch.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0002-efx-rszfixedsizearray-implicit-length-write.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0003-efx-opaque-unknown-attribute-types.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0004-efx-bonerelation-strainribbon-fluidsim.patch --directory=vendor/RE-Engine-Lib
dotnet build tools/EfxBridge -p:LangVersion=preview
```

无头 Blender 跑门禁（`--factory-startup` 顺带隔离掉同机安装的姊妹插件 `efx_editor`，避免
`bl_idname` 撞车；本机只有 Steam 目录下那个是 5.1.2，其余几个 `blender.exe` 是 3.0/2.79 跑不了）：

```bash
"E:\Program\Steam\steamapps\common\Blender\blender.exe" --background --factory-startup --python tools/verify_blender_roundtrip.py
```

全语料整批往返复核。⚠ **`MHWILDS_EXTRACT\EFX\` 这一层已经不存在了**，档案（PLAN.md /
docs/ / KNOWN_UPSTREAM_ISSUES.md）里照抄的旧路径全部找不到目录。现在 `MHWILDS_EXTRACT`
下有两份官方 `.efx`：`Art\VFX`（9221 个）和 `natives\STM\Art\VFX`（9241 个，旧路径去掉
`EFX\` 之后的同一棵树）：

```bash
dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll roundtrip "E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\Art\VFX"
```

`.uvs` 语料共 80 个（去重文件名 74 个，全是 v8），**没有统一目录**，散在
`MHWILDS_EXTRACT/**/*.uvs.8`（50 个）、游戏目录 `natives/**/*.uvs.8`（2 个）和
`E:\Data\MOD工具\MHWS MOD\**\UNKNOWN\`（28 个）三处。

材质参数覆盖表（TypeMesh 的 `properties`）要用户手上有一个真的 `.mdf2` 当参考。VFX 材质一般
没人专门解包，从 pak 里按内部路径现捞一个（`natives/STM/` 前缀 + `.45` 后缀，少一段就查不到，
单次 <1 秒）：

```bash
dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll pakextract "E:\Program\Steam\steamapps\common\MonsterHunterWilds" "natives/STM/Art/VFX/Mesh/PL/Equip/11_ch00_069_0006.mdf2.45" ref.mdf2.45
```

只想看看它声明了哪些参数（不落地文件）用 `mdfdump`，它同样支持 `--pak <游戏目录> <内部路径>`。
