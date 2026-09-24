# CLAUDE.md

MHWs（Monster Hunter Wilds，RE Engine）的 `.efx` / `.uvs` 文件 Blender 编辑插件。三层结构：
Python 胶水层（`blender_efx_re/`）↔ C# 桥接 CLI（`tools/EfxBridge`）↔ vendor RE-Engine-Lib
（submodule，默认只读，什么情况下可以改见铁律 #2）。

这份文件放的是需要长期常驻上下文的东西：会损坏文件或者误导用户的硬约束、改完代码该跑哪些
验证、任务什么时候才算做完、已经拍板过不该自行改动的项目边界，以及少量高频命令。

调研过程、证据、历史结论、语料统计、本机环境这些都在 `docs/` 里，用到再去读。想往这里加一段
之前先想一下：这条如果不写在这儿，会不会直接导致坏文件或者误导用户？如果不会，它就属于
`docs/`，在下面的索引里留一行链接就够了。

## 动手前按你要碰的东西查

| 要碰什么 | 先读 |
|---|---|
| Expression 公式（运算符/函数语义、两套记法、参数顺序） | [docs/EXPRESSION_RULES.md](docs/EXPRESSION_RULES.md) |
| 上面那些结论怎么测出来的、被推翻过什么 | [docs/EXPRESSION_SEMANTICS.md](docs/EXPRESSION_SEMANTICS.md) |
| 任何"这字段/这行为看着奇怪"的现象 | [docs/PITFALLS.md](docs/PITFALLS.md) |
| 顶层结构、字段语义、`{s,r}` 之类的读法 | [docs/TOPLEVEL_STRUCTURE.md](docs/TOPLEVEL_STRUCTURE.md)、[docs/BLENDER_MODEL.md](docs/BLENDER_MODEL.md) |
| 门禁具体怎么跑、写新门禁要注意什么 | [docs/VALIDATION.md](docs/VALIDATION.md) |
| 语料在哪、有多少、怎么从 pak 里捞参考文件 | [docs/CORPUS.md](docs/CORPUS.md) |
| Blender 装在哪、本机各种绝对路径 | [docs/LOCAL_ENV.md](docs/LOCAL_ENV.md) |
| vendor 的解析缺口 / 我们打的补丁 | [KNOWN_UPSTREAM_ISSUES.md](KNOWN_UPSTREAM_ISSUES.md)、[tools/vendor-patches/README.md](tools/vendor-patches/README.md) |
| 为什么当初这么设计 | [PLAN.md](PLAN.md) |

**只读跟当前任务相关的那几篇。** 不要为了"先了解一下项目"把 `docs/` 整个加载进上下文——这些
文件加起来五千多行，全读一遍既挤掉了真正要用的上下文，也容易读到后面章节已经推翻的旧结论。

⚠ `docs/PITFALLS.md` 不是背景阅读，里面每一条都真踩过。动不熟的模块之前扫一眼小标题。

## 铁律

只剩这两条。共同点是**机器查不出来**：新写的代码随时可以重犯，但没法预先写一条断言把它钉死，
所以只能靠人记着。能写成检查的规则都已经搬进代码了，清单在本节末尾。

代码注释里到处在引用编号（`铁律 #1` 之类），增删规则的时候记得一起改。

**1. 宁可拒绝，也不要悄悄丢数据。**

任何可能静默丢弃或者截断数据的路径，都要在 Blender 侧加导出前校验，或者在 UI 上直接拦掉。
`io_tree.py` 里那几个 `check_*` 函数是这个模式的先例，UvarGroups 的 2 项上限也是。

语义没证实**不是**丢数据的理由。不确定该怎么处理的时候如实报出来，不要默默跳过。

**2. 尽可能不改 `vendor/RE-Engine-Lib` 源码**，绕过去的代码写在桥接层
（`tools/EfxBridge/Program.cs`）。

解析层依赖一个仍在活跃更新的外部库，动它的源码等于给每次升级埋一次冲突。怀疑 vendor 有
bug 的时候，**默认先假设是我们理解错了**——绝大多数"往返对不上"的根因都在我们这一层。

a. **先排除误诊**：拿一条完全不经过我们代码的路径复现。`roundtrip` 走二进制 → 对象图 →
   二进制，不过 JSON；如果只有过 JSON 的 `dump`/`load` 能复现，问题就在我们这层。
b. 无论复现成功与否都记进 `KNOWN_UPSTREAM_ISSUES.md`。**复现不出来的只能记成 upstream
   suspicion，不能写成"已确认的 vendor 缺陷"**，也不打补丁。
c. 复现出来了先评估代价，能用桥接层绕开就用桥接层。
d. 判断绕开的代价大于直接改 vendor 时，**提出来，得到同意之后再改**，改动要小到能一眼
   看出对错。
e. 最终改动必须落成 `tools/vendor-patches/NNNN-*.patch`。调试时临时改 vendor working
   tree 没问题，确认后要还原——**working tree 里的直接修改不算数**，submodule 一更新就没了。

**vendor 升级后补丁不会自动保留，要重新 `git apply`**，命令见
[tools/vendor-patches/README.md](tools/vendor-patches/README.md)。

### 以前还有五条，现在由代码看着

它们没有被废除，只是不再需要常驻上下文——每条都有了比"记着"更可靠的守卫。别再把它们加回来。

| 原来的规则 | 现在谁看着 |
|---|---|
| 解析失败就整文件拒绝导入 | 导入路径上没有宽异常捕获，`tools/check_import_no_swallow.py` 守着。唯一的例外是首选项里那个显式开关，见 `preferences.py` |
| 补不出合法版本号后缀就拒绝导出 | `operators._parsed_file_version()` 的实现和 docstring；`verify_blender_roundtrip.py` 里有用畸形路径做的对抗断言 |
| 不做脏标志，每次导出全量重算 | [PLAN.md](PLAN.md) 架构决策第 7 条 |
| 用户可见文案只写结论，不写出处 | [docs/PITFALLS.md](docs/PITFALLS.md) #25（带 ❌/✅ 清单和批量自查命令） |
| 不要把猜测包装成事实 | 置信度四档如实显示由 `verify_blender_expression_preview.py` 断言（含偏序和"取最差那一档"）；"认不出就报错/留空、不填占位"写死在 `clip_fcurve.py`、`simulator.py`、`efx_sim/expr.py` 里，各有单测 |

## 已确定的项目范围

这些都是拍过板的，不要自行重新设计或者顺手扩大：

- 这个插件只面向 MHWs，不打算做成通用的 RE Engine EFX 工具。后端已有的多游戏参数化可以
  保留，但不要为了假设中的其他 RE 游戏额外扩展 UI、语料或功能。
- 跨 entry / attribute 的引用一律用 `PointerProperty` 指对象，不用裸下标。
- 字段语义标注是两层存储：出厂表在 `semantics/`，用户自己的标注放 Blender 用户配置目录，
  从第一天就分开。语义标注系统目前不是优先级。
- `IMaterialClipAttribute` / `IMaterialExpressionAttribute` 没实现是结构性排除，不是遗漏。
- Entry 预设的范围限定在"另存为预设"和"从预设新建 Entry"，不做"套到已存在的 Entry 上"，
  也不做 Attribute 级别的预设。
- `ATTRIBUTE_TYPES.md` 是机械生成的，**只有名字和类型**。没有解释的名字一律当"未知"，
  不要当成"显然是 X"。

## 验证

判据是**和纯 CLI 往返产物逐字节相同**，不是和原文件相同。vendor 总是重新生成字节，拿原文件
当基线只会得到一个永远红的测试。

验证还必须打到 Blender 那条真实用户路径上。CLI 层绿不代表 Blender 层绿；`EfxBridge roundtrip`
（纯内存对象图）绿也不代表 `dump` / `load`（Blender 实际走的那条）绿——已经有三个 bug 是
`roundtrip` 全绿、`dump` → `load` 直接炸。

| 改了什么 | 跑什么 |
|---|---|
| `efx_sim/`（零 bpy 的那层） | `python -m unittest discover -s tests` |
| `bridge.py`/`io_tree.py`/`operators.py`/`uvs_io.py` 里加了 `except` | `python tools/check_import_no_swallow.py`（不用开 Blender） |
| IO 路径 | `verify_blender_roundtrip.py` |
| 公式记法版本拦截（`io_tree` 的 `EXPR_NOTATION_*` / `copy_paste.py` / `entry_presets.py` 里同一判据） | `verify_blender_roundtrip.py` |
| `.uvs` IO | `verify_blender_uvs_roundtrip.py` |
| `mdf` 属性 | `verify_blender_mdf_property.py` |
| `coords.py`/`transform3d_view.py`/`bone_binding.py`/`io_tree.apply_attribute_content()` | `verify_blender_bone_binding.py` |
| `model.sr_children_ordered()` / 四张 `{s,r}` 名单 / `panels.py` 并排画法 | `verify_blender_sr_pair.py` |
| `sim_preview.py` / `efx_sim/` / `es3d_overlay.py` | `verify_blender_sim_preview.py` |
| `tex_image.py` | `verify_blender_tex_image.py` |
| `asset_link.py` / `asset_paths.py` | `verify_blender_asset_link.py` |
| `expr_edit.py` / `expr_text.py` / `expr.py` 文本↔行 / `model.formula_canonical` | `verify_blender_expression_edit.py` |
| `expr_nodes.py` | `verify_blender_expr_nodes.py` |
| `expr_preview.py` / `efx_sim/plot.py` / `expr.py` 求值 | `verify_blender_expression_preview.py` |
| `model.as_int32()`/`enum_proxy`/`_read_packed_int()` / `attribute_types.enum_members()` | `verify_blender_enum_proxy.py` |
| `structure_ops.py` 的算子枚举参数 / `attribute_types.enum_items`/`all_enum_items` | `verify_blender_attribute_picker.py` |
| `model.is_material_expression_attribute_dict()`/`EFXMaterialExpressionItem` / `io_tree` 的 MaterialExpressions populate/export | `verify_blender_material_expression.py` |
| `clip_fcurve.py` / `io_tree.py`/`model.py`/`panels.py` 里 Clip 曲线相关改动 | `verify_blender_clip_fcurve.py` |
| `fixrandom_ops.py` | `verify_blender_fixrandom_ops.py` |
| `ptbehavior_catalog.py` / PtBehavior 候选目录的增删 | `verify_blender_ptbehavior_property.py` |
| `field_visibility.py` 的 `VERSION_EXCLUDED_FIELDS` | `verify_blender_version_excluded_fields.py` |
| `panels.py` 的 UIList `draw_item` / 各个 `*_add` 算子 | `verify_ui.py` |

具体跑法、参数和环境限制见 [docs/VALIDATION.md](docs/VALIDATION.md)。

### 门禁什么时候会静默全绿

下面几种情况都出现过，共同点是门禁看起来通过了：

- **`blender --background --python x.py` 抛未捕获异常的时候退出码仍然是 0**，`sys.exit(main())`
  根本轮不到执行。门禁入口要自己捕获异常再 `sys.exit(1)`。而且只看退出码不够，要确认输出里
  真的出现了 PASS 行。
- **门禁"什么都没测到"也会全绿。** 样本里一条目标结构都没有的时候要退 1，并且打印出样本
  实际覆盖到了哪些种类。
- **新加的回归防护要先看着它红。** 把原 bug 注回去、确认它真的 FAIL，再确认修复后 PASS。
  只看它绿不算数。

还有一类更隐蔽的：**往返自洽性抓不到读写两边同时采用了同一个错误约定的情况。** 出现这种
问题的时候，逐字节往返门禁、文本重拼门禁和几百个单测会一起绿，但语义其实是错的。
`BoneRelations` 的消费者集合和 Expression 的运算符语义都栽在这上面，所以这类语义只能靠实机
结果，或者另写一条不共享实现的路径来对拍。

## 完成定义

代码写完不等于任务完成。改完之后：

1. 按改动范围对照上面的表，确定要跑哪些验证。
2. 真的把它们跑一遍。
3. 检查退出码，**同时确认输出里真的出现了预期的 PASS 行**——退出码 0 在这个项目里不可靠，
   原因见上一节。
4. 没有实际跑过的验证，**禁止**描述成 "tests pass"、"verified"、"confirmed"、"已验证"、
   "已确认可用"。
5. 当前环境跑不了某一项的时候，明确说清楚是哪一项、为什么跑不了。不要把"理论上应该没问题"
   写成验证结果。
6. 新增 regression test 的时候，先把原 bug 注回去确认它确实 FAIL，再确认修复后 PASS。

## 常用命令

### 构建 C# 桥接

vendor 用了 C# 13 的 `field` 关键字，必须 `LangVersion=preview`：

```bash
dotnet build tools/EfxBridge -p:LangVersion=preview
```

⚠ 刚 `git submodule update` 过 vendor 的话，要先重新打一遍 `tools/vendor-patches/` 下的补丁
再构建，否则编译出来的是没修过 Func18/19/20、`Layout`、`PtColorMixerClip` 等类型的旧行为。
补丁清单和 apply 命令见 [tools/vendor-patches/README.md](tools/vendor-patches/README.md)。

### Blender 门禁

```bash
"E:\Program\Steam\steamapps\common\Blender\blender.exe" --background --factory-startup --python tools/verify_blender_roundtrip.py
```

`--factory-startup` 顺带隔离掉同机安装的姊妹插件 `efx_editor`，避免 `bl_idname` 撞车。
换别的门禁就换脚本名，完整清单见上面的表。

### 全语料往返复核

```bash
dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll roundtrip "E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\Art\VFX"
```

语料分布、`.uvs` 散落的三个位置、从 pak 里捞 `.mdf2` 参考文件的路径规则，见
[docs/CORPUS.md](docs/CORPUS.md)。

⚠ 手工跑 `EfxBridge load` 的时候，输出路径必须带 `.efx.<version>` 后缀。用裸 `.efx` 会炸出
`Header.Version = -1` 和一堆垃圾 typeId——那是个假故障，已经为它白排查过一整轮。

### 当前开发机路径

上面命令里的绝对路径（`E:\Program\Steam\...`、`E:\Data\...`、`MHWILDS_EXTRACT\...`）只是
当前这台开发机上东西放的位置，不是项目结构的一部分，换台机器就要改。**不要把这些路径硬编码
进插件本体。** 完整清单见 [docs/LOCAL_ENV.md](docs/LOCAL_ENV.md)。

## 第三方插件补丁

给别人的插件（非 vendor）打的补丁，用法和原理见
[tools/third-party-patches/README.md](tools/third-party-patches/README.md)。
