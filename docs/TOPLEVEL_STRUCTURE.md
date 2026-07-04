# MHWs EFX — 顶层数据结构调研

从 [PLAN.md](../PLAN.md) 拆出来的专题文档，记录 `EfxFile`（`ReeLib.EfxFile`）顶层字段
（`Entries`/`Actions`/`EffectGroups`/`FieldParameterValues`/`ExpressionParameters`/
`UvarGroups`/`Bones`/`BoneRelations`）与姊妹项目 EFX-Editor（MHWI）对应概念（Body/Play/
Extern/Subselect Table）的比对结论，以及这些字段里未知语义的 cross-reference 结果。这是
"设计尚未实现的顶层字段"这项工作的主要参考资料，后续继续调研/定案时直接在本文件追加，不
再堆回 PLAN.md。

## Phase 1 补充 — MHWs 顶层数据结构与 MHWI（EFX-Editor）对照调研（2026-07-03）

背景：开始设计 PointerProperty/对象模型前，先搞清楚 MHWs 的 EFX 顶层结构相对 MHWI（姊妹
项目 [EFX-Editor](https://github.com/Dimcirui/MHW-EFX-Editor) 的 Body/Play/Extern/
Subselect Table 概念，见其 README"Basic structure"一节）发生了什么变化。以下结论完全基于
静态阅读 `vendor/RE-Engine-Lib` 源码（`EfxFile.cs` 的 Read/Write 顺序、`AddAttribute` 的
护栏逻辑、`AttributeTypeIDs` 表）得出，**当前仓库没有任何真实 MHWs `.efx` 样本**，样本到手
后需要用实际文件复核。

**`EfxFile`（`ReeLib.EfxFile`）顶层字段清单**：

```
Entries               List<EFXEntry>                — Body（与 MHWI 概念一致）
Actions               List<EFXAction>                — 独立顶层列表，= Play（已确认）
EffectGroups          List<EffectGroup>              — 命名分组 + Entry 下标子集，= Subselect Table（已确认）
FieldParameterValues  List<EFXFieldParameterValue>   — 命名+类型化的值/路径表，Wilds 新增，暂不深挖
ExpressionParameters  List<EFXExpressionParameter>   — 公式引擎具名参数表，Wilds 新增，暂不深挖（决策8已覆盖）
UvarGroups            List<UvarGroup>                — 外部 .uvar 文件引用表，Wilds 新增，暂不深挖（2026-07-03 复核新发现）
Bones / BoneRelations                                 — 骨骼绑定表，与 MHWI PARENTOPTIONS 概念一致
```

**结论 1：`Actions` = MHWI 的 Play。** 证据是结构性的，不只是同名：`EFXEntryBase.AddAttribute`
（`EfxFile.cs:233`）显式拒绝把 `PlayEmitter`/`PlayEfx` 挂到 `EFXEntry` 上——这两个 attribute
类型只能挂在 `EFXAction` 上。"Action" 这个顶层列表存在的意义就是承载 Play 类 attribute，
且和 Body 一样有独立的具名字符串表（`Strings.ActionNames`）。工业界习惯把这类"动作触发器"
叫 Action，Play 是社区约定名，两者所指一致。

**结论 2：`EffectGroups` = MHWI 的 Subselect Table。** `EffectGroup` 就是"命名分组 + 一组
Entry 下标"（`groupName` + `efxEntryIndexes`），和 `EFXEntry.Groups`（每个 Body 反向记录
自己属于哪些组）互为镜像，导出时由 `UpdateEffectGroups()`（`EfxFile.cs:893`）从 Body 侧的
Groups 重新推导、重建下标数组。这与架构决策第 4 点"对象身份而非裸下标"的精神一致：Blender
侧不需要为 Subselect 做下标 PointerProperty 数组，只需要在每个 Body 对象上挂一个字符串/
标签列表（对应 `EFXEntry.Groups`），文件级 `EffectGroups` 列表整个当成导出时的派生产物
处理，不需要用户直接编辑下标。外部调用方式已确认：`.epv`（Effect Provider）按"带
conditional bit id 的 Subselect 表项"调用某个 EFX 文件里的 Body 子集；这个条件判断逻辑本身
不在 `.efx` 文件内、也不由 RE-Engine-Lib 解释，`.efx` 侧只需要如实存储分组数据。

**结论 3：`PlayEmitter` 是内嵌（组合），不是引用。** 这一点和直觉相反，值得记录：
`EFXAttributePlayEmitter.efxrData` 是一个完整、独立的 `EfxFile` 对象图（自己的
Header/Entries/Actions/EffectGroups 等），整个内联序列化在这个 attribute 里
（`EfxFile.cs` 约 495-515 行），不是"指向同文件内某个 Body/Action 的指针"。**这直接影响
Blender 对象模型**：Play → PlayEmitter 不应该做成"PointerProperty 指向本文件内某个 Body
对象"，而应该做成"PlayEmitter 拥有一个嵌套子集合（递归的 Body/Action/EffectGroups 结构）"
——即 Blender 场景里大概率是一层嵌套 Collection，而不是跨对象的裸指针。

**决策（已定，2026-07-03；`FieldParameterValues`/`UvarGroups`/`ExpressionParameters`（顶层
参数表）已于 2026-07-04 全部升级为有编辑 UI，见下方对应的"结构调研与实现"一节——注意这里的
"`ExpressionParameters`"专指 `EfxFile.ExpressionParameters` 这个顶层具名参数表，不是
attribute 内容字段里那个更复杂的 `Expression`/`MaterialExpressions` 公式树，那个仍然按架构
决策第 8 点结构化透传、不建字段级 UI，两者是完全不同的两套结构，容易望文生义搞混）**：
最初调研阶段曾把这三个字段都归为"MHWs 新增、暂不深挖语义的子系统"，只做透传；后续陆续确认
它们的二进制结构后逐一升级成了编辑 UI（细节见下方三个"结构调研与实现"小节）。不再尝试把
`FieldParameterValues` 往 MHWI Extern"替换参数"机制上套（调研阶段的一个假设，已放弃——两边
都没有确凿的消费端代码佐证这个映射，与其猜一个不确定的语义，不如先诚实地标记为"不透明"）。
MHWI Extern 的第二种子类型（"external EFX references"）在 Wilds 侧目前没有找到任何结构
对应物，视为可能已被移除/合并，等有真实样本再复核。

**Blender 对象模型草案（已达成一致，实现时按此展开）**：命名跟随 RE-Engine-Lib 实际类名
（`EfxFile.Entries: List<EFXEntry>`）叫 **Entry**，不叫 EFX-Editor（MHWI）习惯用的 Body——下面
以及本文件其余"调研结论"段落里出现的"Body"，指的是 MHWI/EFX-Editor 自己的既有术语，两个
项目各自命名习惯不同，不是同一个词（2026-07-04 结合实现一起定下来，之前调研阶段写的草案
原文用的还是 Body，未回改，读的时候按"同一层概念、后来改了名字"理解即可）：
- **Entry**（对应 `Entries`，MHWI 那边叫 Body）——`~TYPE` 对象 + PropertyGroup 字段面板。
- **Action**（对应 `Actions`，新顶层类型，与 Entry 同级而非 Entry 的子级）——承载
  `PlayEmitter`/`PlayEfx`；`PlayEmitter` 拥有嵌套子集合，不用 PointerProperty。
- **Subselect**——不建单独对象类型，落在 Entry 对象上的一个字符串标签列表
  （对应 `EFXEntry.Groups`），文件级 `EffectGroups` 视为导出时派生数据。
- **ExpressionParameters**——2026-07-04 升级为有编辑 UI：`EFX_ROOT.efx_expression_parameters`
  列表，见下方"`ExpressionParameters` 结构调研与实现"一节（最初以为比 `UvarGroups`/
  `FieldParameterValues` 更棘手，是因为把"C# 端三个 union 视图属性"和"Blender 侧要不要做
  UI"这两件事混在一起了——union 属性早在 Phase 1 就被 `EfxBridge/Program.cs` 的
  `StripUnsafeComputedProperties` 挡掉了，Python 侧看到的实际形状很规整）。
- **UvarGroups**——2026-07-04 升级为有编辑 UI：`EFX_ROOT.efx_uvar_groups` 列表（最多 2 项），
  见下方"`UvarGroups` 结构调研与实现"一节。
- **FieldParameterValues**——2026-07-04 升级为有编辑 UI：`EFX_ROOT.efx_field_parameters`
  列表（`EFXFieldParameterItem`），见下方"`FieldParameterValues` 结构调研与实现"一节。

**验证（2026-07-03，用 `diag/11_guide_110.efx.5571972.orig` 复核）**：仓库里唯二的样本
中，`11_guide_110` 恰好带 2 个 Action + 2 个 EffectGroup，用 `EfxBridge dump` 检查其 JSON，
结论 1/2/3 全部与真实文件一致——`Actions[i].Attributes[0].$type` 确认是
`EFXAttributePlayEmitter`；`PlayEmitter.efxrData` 确认是完整嵌套的 `EfxFile`
对象图（`Entries`/`Actions`/`EffectGroups`/... 齐全，4 个 Entries）；`EffectGroups`
确认是 `{groupName, efxEntryIndexes}` 形状。`11_guide_006` 两个 Entry 均为 0，未提供
额外信息。样本量仍然只有 1 个正样本，后续拿到更多真实样本后应继续复核，尤其是
`efxEntryIndexes` 在有 Body 增删场景下的重建行为。

**顺带发现：未在上文字段清单中记录的顶层字段 `UvarGroups`**（`List<?>`，字段形状
`{uvarType, path, group}`，样本值 `{uvarType: 2, path: "Art/VFX/VFX_group_common.uvar",
group: "VFX_group_common"}`）——指向外部 `.uvar` 文件的引用，语义和消费端未调研，
`FieldParameterValues`/`ExpressionParameters` 两个样本里均为空，无法从样本验证。暂按同一
原则处理：视为不透明数据块随文件透传，不建编辑 UI，留待后续样本/需求驱动再深挖。

**前瞻性备注（不影响当前阶段，仅为将来铺路）**：姊妹项目 EFX-Editor（MHWI）正在设计一套
"字段语义知识表"（把 label/tooltip/官方名等展示层语义从 `.py` 表搬到外部 JSON，让非程序员
测试者也能填写、不用碰代码），详见该仓库 `PROGRESS.md` "语义知识解耦" 一节。到 Phase 1 做
Blender 通用属性面板时，本项目会遇到同样的问题（RE-Engine-Lib schema 里大量字段语义未知，
需要实测标注）。届时若复用同一套设计，**在字段知识表格式里从第一天就带上游戏命名空间**
（如顶层 `"game": "MHWS"` 或按游戏分文件），使两个项目的测试者工作流、校验器、"填写含义"
弹窗代码可以直接共享，不需要各自另起一套。现在不需要做任何事，只是设计到时候留这个口子。

## Phase 1 补充 — 未知字段语义 cross-reference（2026-07-03）

用户提供了三份新资料：社区维护的 010 Editor 二进制模板（`MHWs-EFX-Template-main`，带中文
注释，fork 自 [NSACloud/RE-Engine-EFX-Template](https://github.com/NSACloud/RE-Engine-EFX-Template)）、
同一模板未加注释的参考版本（`mhws`），以及游戏本体解包出的全量官方 `.efx` 样本（约 9241 个，
`MHWILDS_EXTRACT/EFX`）。用这些资料和 vendor 源码交叉核对了此前标记"语义未知/暂不深挖"的几
个顶层字段，结论如下（全部基于随机抽样 250 个官方样本 + 010 模板代码逻辑，不是猜测）：

**`EFXEntry.index`（Body 的 `index` 字段，`docs/BLENDER_MODEL.md` 记录的实机验证 bug）——
结论被大样本进一步坐实。** 250 个随机官方样本里，**0/248**（2 个文件解析报错，见下）文件的
`index` 字段与数组位置完全一致——不是孤例，是普遍现象。010 模板里这个字段叫 `entryIndex`，
模板同时维护了一个独立的 `local uint currentEntryIndex = parentof(this).i`（数组位置）用于
查表取名字/供 `boneAttributeRelation.entryIndex` 做交叉引用——**印证 `EffectGroups`/
`BoneAttributeRelation` 两处跨 Entry 引用都用的是数组位置，不是这个 `index` 字段本身**，和
我们已修的 `EffectGroups.efxEntryIndexes` 用法结论一致。真实值形如 `[1, 9, 6, 5, 4, 3]`
（6 个 Entry，取值范围到 9）——数值范围超出当前数组长度且不连续，推测是权威制作工具里的
"创建顺序全局计数器"（可能不随删除重置，也可能跨这个文件产生过程中的其它列表共享同一计数
空间），对运行时/`.efx` 格式本身没有约束意义。这个字段目前除了"原样保留"没有更好的处理
方式，维持现状。

**`UvarGroups`（Wilds 新增顶层字段）—— 结构已完全搞清楚，语义有较强证据支持的猜测。**
vendor 源码（`EfxFile.cs:758-776`）显示这**不是变长列表，是固定两个槽位**：文件里紧跟着两个
`int`（`uvarType1`/`uvarType2`），每个非 0 时才追加一个 `EFXUvarGroup`。250 个样本抽样命中
95 个非空槽位：
- `uvarType == 1`：`path`/`group` 均为 `null`——纯标记位，不带数据（`EFXUvarGroup.path`/
  `.group` 在 vendor 里用 `[RszConditional(nameof(uvarType), "==", 2)]` 标注，`==1` 时压根不
  从文件读这两个字段）。语义仍不确定，但结构上确认了"只是个开关"。
- `uvarType == 2`：必定带 `path`+`group`，抽样只见到两个值——
  `Art/VFX/VFX_group_common.uvar`（group 同名）和 `Art/VFX/VFX_weather.uvar`（group 同名）。
  这是指向游戏内共享 `.uvar`（RE Engine 具名用户变量文件）的引用，`group` 是该 uvar 文件内的
  变量组名。命名和内容强烈暗示用途：**这个 EFX 文件的某些参数可能在运行时被这两个共享变量组
  驱动**（`VFX_weather` 很可能是天气系统实时写入的一组变量，`VFX_group_common` 是全局共享的
  通用 VFX 变量），但具体"哪个字段绑定到哪个变量"完全不在 `.efx` 文件里体现（大概率是运行时
  按变量名/哈希在别处关联，`.efx` 只声明"我依赖这个 uvar 组"）。**结论：维持不透明透传不变
  （已经是对的，`UvarGroups` 本就没在 `ROOT_STRUCTURAL_KEYS` 里）**，这次只是把"完全未知"
  升级成"结构确定、大致用途有据可猜"，不改代码。
- 250 个样本里 2 个抛异常（"Found unhandled uvar type"类，`uvarType > 2`）——与 vendor 注释
  "DD2 见过 0/1，RE4/DMC5/RERT 恒为 0"一致，是已知的 vendor 解析缺口，按架构决策 9 已经会被
  正确拒绝，不需要处理。

**`FieldParameterValues`（Wilds 新增，命名+类型化参数表）—— 部分语义可以确认。**
250 个样本里只命中 2 条（同一效果的重复引用），样本太小不足以覆盖全部 `type` 取值，但
010 模板和 vendor 源码各自独立维护了同一个"当 `type` 属于某个特定取值集合时，参数值替换成一
个外部文件路径宽字符串"的分支（模板：`type == 110||184||202||194||217`；vendor：
`type is 110 or 144 or 183 or 184 or 202 or 194 or 215 or 217`，vendor 的集合更大更新）。抽到
的样本正好命中这个分支：`type: 217` 对应
`filePath: "RE_ENGINE_LIBRARY/VFX_Library/Texture/TEX_Vectorfield/tex_capcom_vectorfield_0006_MSK4.tex"`
（`name: "Field"`）——即一个矢量场纹理引用，说明 `FieldParameterValues` 是**具名、可类型化
的"外部可调参数"表**：多数 `type` 取值下是纯数值（未继续深挖 `unkn0`/`unkn2`/`unkn4`/
`value_ukn1-6`/`wilds_unkn0` 各自含义），一部分 `type` 取值（对应贴图/资源类参数）下是文件路径。
和 `UvarGroups` 一样，这次只是升级理解、不改代码——本来就是原样透传。

**`ExpressionParameters`——无新发现，验证了已有实现的正确性。** 250 个样本命中 47 条，抽样
显示的字段（`type`/`value1`/`value2`/`value3`/具名 hash）与 vendor 里已经做了 `Float2`/
`Color`/`Range` 类型化访问器的 `EFXExpressionParameter` 完全对应（如 `name: "Length"` 两次
出现取值 `10`/`50`，符合"具名数值参数供 Expression 公式引擎按名字查找"的定位），当前代码
的处理方式（结构化透传，UI 后置，见架构决策 8）不需要调整。

**方法论备注**：010 模板由独立的社区逆向工程产出，字段名/结构与 RE-Engine-Lib（基于
REFramework/TDB 反射）几乎在所有交叉点上互相印证（`entryIndex` vs 数组位置的区分、
`FieldParameterValue.type` 触发路径分支的取值集合），这让人对两边的可信度都更有信心——不是
一边猜另一边抄，是两套独立方法收敛到同一结论。

## `Bones` / `BoneRelations` 结构调研（2026-07-04）

此前只标注"概念上与 MHWI PARENTOPTIONS 一致"，没有深挖。这次直接读 vendor 源码
（`REE-Lib/OtherFiles/EfxFile.cs`）搞清楚了完整机制，关键结论：**Blender 侧完全不需要处理
裸下标**——C# 后端自己在读时就把下标解析成骨骼名字字符串，写时再从名字反查下标，架构决策 4
"跨引用一律用对象身份而非裸下标"在这里天然成立，甚至不需要我们自己实现。

**字段清单**（`EfxFile.cs:657-671`）：
```
Bones          List<EFXBone>   — {name: string, value: uint}，文件级命名骨骼表
BoneRelations  List<short>     — 纯下标数组，按"遇到顺序"消费，不认字段名
```
`EFXBone`（`EfxFile.cs:590-596`）只有 `name` + `value` 两个字段；`value` 语义未知（**不是**
`nameHash`——`nameHash` 是写入时临时用 MurMur3 对 `name` 现算的，`value` 是独立存储的另一个
量，磁盘上两者都在但语义分开）。读写只在 `Header.Version > EfxVersion.DMC5`（MHWilds 满足）
时才生效（`EfxFile.cs:787,971`）——老版本游戏没有这套机制。

**下标→名字的解析机制**（`SetupBoneReferences()`，`EfxFile.cs:853-891`，读完整个文件后跑一遍）：
维护一个跨全部 `Entries`/`Attributes` 的顺序计数器，每遇到一个实现了 `IBoneRelationAttribute`
接口（`interface IBoneRelationAttribute { string? ParentBone { get; set; } }`，`EfxFile.cs:607`）
的 attribute，就消费 `BoneRelations` 里的下一个下标值，去 `Bones` 表里查名字，写进该 attribute
的 `.ParentBone` 属性（下标 `-1` 或越界 → `ParentBone = null`，"没有父骨骼"）。写回时
（`EfxFile.cs:982-989`）反过来：按同样的遍历顺序，对每个 `IBoneRelationAttribute`，用
`Bones.FindIndex(b => b.name == parented.ParentBone)` 查出下标重新写回 `BoneRelations`——
**`BoneRelations` 本身在导出时是完全重新生成的派生数据**，和 `EffectGroups` 的处理方式
（结论 2）是同一个模式，Blender 侧不需要透传、更不需要编辑它。

**已确认对 MHWilds 生效的 4 个 `IBoneRelationAttribute` 实现类**（各自还带一个同名概念但
*完全独立存储*的"原始字段"，见下方风险提示）：
`EFXAttributeParentOptions.BoneName`（真实样本 `$type` 命中确认）、
`EFXAttributeAttractor.boneName`（真实样本命中确认）、
`EFXAttributeVanishArea3D.JointName`（真实样本命中确认）、
`EFXAttributeTypeLightning3D.boneName`（未在样本里出现，靠版本解析算法确认，见下）。

**订正（2026-07-04，实现骨骼编辑 UI 前复核发现）：最初列了 6 个类，其中
`EFXAttributeTypeLightning3DV1` 和 `EFXAttributeTypeStrainRibbonV2` 经复核不适用于
MHWilds，已剔除。** 原因是 `EfxAttributeTypeRemapper.GenerateEfxLookup()`
（`EfxAttributeTypes.cs:408-465`）按 `EfxStructAttribute` 声明的版本列表做"精确匹配，否则退回
`GameOrder`（`EfxFile.AllVersions`，即 `EfxVersion` 枚举声明顺序，恰好是游戏发布顺序）里
最近的更早版本"这套解析规则，同一个 `EfxAttributeType` 在不同游戏版本下可能对应不同的具体类：
- `TypeLightning3D`：`EFXAttributeTypeLightning3DV1`（RE7/RE2/DMC5）实现接口，但
  `EFXAttributeTypeLightning3D`（RE8/MHRiseSB/**DD2**）也实现接口——MHWilds 没有专属覆盖，
  退回"最近的更早版本"命中 DD2（比 RE7/RE2/DMC5 更晚），所以 MHWilds 用的是后者
  （`EFXAttributeTypeLightning3D`，不是 V1）——**结论不变，只是排除了不适用的 V1**。
- `TypeStrainRibbon`：`EFXAttributeTypeStrainRibbonV2`（RE8/RERT）实现接口，但
  `EFXAttributeTypeStrainRibbonV3`（**RE4**，声明注释里直接写"past this is wild territory
  for Wilds"，内部还有 `[RszVersion(EfxVersion.MHWilds, ...)]` 门控字段，证实一直沿用到
  MHWilds）**不**实现 `IBoneRelationAttribute`——RE4 比 RE8/RERT 更接近 MHWilds，退回逻辑命中
  V3，MHWilds 的 `TypeStrainRibbon` attribute 实际上**没有**索引表骨骼绑定能力，只剩一个
  纯遗留、无下标关联的 `boneName` 字符串字段。**这个类从骨骼引用字段清单里整个删掉**（不是
  当前 4 个之一，Blender 侧不应该给它挂 `prop_search`）。
- `ParentOptions`/`Attractor`/`VanishArea3D` 三个已经是真实样本 `$type` 直接命中的，不受这套
  退回逻辑的不确定性影响，结论不需要重新核对。

**风险 1（真实数据校验，2026-07-04）：`BoneName`/`boneName`/`JointName` 与 `ParentBone` 是
两个独立存储位置，不是同一个值的两种展现方式。** 用 `EfxBridge dump` 复核了仓库里唯二的样本
（`guide_006`/`guide_110`），全部 20 处 `IBoneRelationAttribute` 实例里，`BoneName` 系字段
（`[RszInlineWString(ByteSize=True)]`，无版本门控，MHWilds 下仍然真实读写）**全部是空字符串
`""`**，`ParentBone`（纯运行时属性，不参与 RSZ 读写，只由 `SetupBoneReferences()`/写出逻辑
维护）**全部是 `null`**——两者在这两个样本里表现一致（都是"无绑定"），但样本恰好都没有真实
用到骨骼绑定，**无法确认 `BoneName` 在有真实绑定的文件里是否也保持为空**。从代码结构看，
`BoneName` 这个字段从 RE7 就存在（`EfxStruct` 版本列表包含 RE7/RE2/DMC5），推测是老版本游戏
直接内联骨骼名字的机制；RE3+ 引入 `Bones`/`BoneRelations` 下标表后，`BoneName` 字段本身
在新版本里大概率是废弃但仍被读写的遗留字段（新工具链不再往里写东西，但字节布局保留兼容）。
**这个推测目前只有 0 个正样本佐证**，等有真实带骨骼绑定的 MHWs 样本（或能重新访问
`MHWILDS_EXTRACT/EFX` 那 9241 个语料）时应该批量确认：是否存在任何非空 `BoneName` 与非
`null` 的 `ParentBone` 同时出现、且两者不一致的情况。

**风险 2（代码读出的真实设计隐患，非样本问题）：`ParentBone` 与 `Bones` 表失配时静默降级为
"无父骨骼"，不报错。** 写出逻辑 `Bones.FindIndex(b => b.name == parented.ParentBone)`——如果
`ParentBone` 是某个不在 `Bones` 表里的名字，`FindIndex` 返回 `-1`，直接当成"没有父骨骼"写进
文件，**没有任何异常或警告**。这意味着如果 Blender 侧允许用户把某个 attribute 的骨骼引用
改成一个新名字、却忘了同步维护文件级 `Bones` 表，导出会静默产生"看起来正常但绑定丢失"的
文件——这正是架构决策 9 想避免的那类"错误结构骗过用户"情况，只是这次是我们自己的 Python
胶水层要对齐这个纪律，不是 C# 后端解析失败那种情况。**设计骨骼编辑 UI 时必须堵上这个口子**
（校验/自动同步二选一，见下方 Blender 设计讨论）。

## 哈希调研补记（2026-07-04）

排查过"`unkn` 字段是否也像 TIML 那样带可还原的哈希"这个思路（动机：姊妹项目在 MHWI 侧靠
TIML attribute hash 破解了不少字段语义），结论是**否**——vendor 里唯一的哈希机制
（`EfxCommon.cs` 的 `PropertyNameUTF8Hash`、`EfxExpressionParser.cs`/`ExpressionData.cs` 的
`MurMur3HashUtils`）只对**被引用的字符串标识符**（着色器/材质参数名、Expression 具名参数名）
做哈希，不覆盖 attribute 结构体自身的 `unkn*` 字段槽位；RSZ 通用字段元数据
（`RszParser.cs` 的 `RszField`）本身也没有 crc/hash 成员，EFX attribute 类是硬编码 C# 类型，
不走这条通用注册表。也就是说 `FieldParameterValues`/`ExpressionParameters` 里的具名哈希
（`KnownExternalHashes`/`UnknownParameterHashes`）如果还有未解析条目，理论上可以用同样的手段
去撞库，但这和"给 unkn 结构字段找名字"是两件不同的事，后者目前只能靠人工逆向（对照真实特效
效果调值 + 反编译游戏代码），没有捷径。

## `FieldParameterValues` 结构调研与实现（2026-07-04）

此前（2026-07-03 的"未知字段语义 cross-reference"一节）已经确认了核心语义：这是一张
**具名、可类型化的"外部可调参数"表**，多数 `type` 取值下是纯数值，`type` 属于特定取值集合
时是外部资源路径（矢量场纹理等）。这次直接读 `EfxFile.cs:512-578` 的 `EFXFieldParameterValue`
完整类定义，把结构钉死，并实现了编辑 UI（这次改成"结构性 UI 现在做"而不是继续维持决策 8
定的"只透传不建 UI"——用户明确要求把这个字段纳入本轮设计）。

**字段清单**（`EFXFieldParameterValue`，`EfxFile.cs:512-530`）：
```
unkn0                    uint     — 语义未知
fieldParameterNameHash   uint     — 语义未知，见下方风险说明
unkn2                    uint     — 语义未知
type                     uint     — 已确认：决定 filePath 是否是真正使用的外部资源路径
unkn4                    uint     — 语义未知
value_ukn1               int      — type==196 时兼作 filePath 的字符长度前缀，其余情况语义未知
value_ukn2 ~ value_ukn3  uint     — 语义未知
value_ukn4 ~ value_ukn6  float    — 语义未知
wilds_unkn0              float    — 仅 Version >= MHWilds 存在，语义未知
name                     string?  — 具名参数名字，走 Strings.FieldParameterNames 平行表（同
                                     Bones/Actions 的具名机制）
filePath                 string?  — 仅当 type ∈ {110,144,183,184,196,202,194,215,217} 时是
                                     真正使用的外部资源路径（已用真实样本证实 type==217 对应
                                     矢量场纹理 `.tex` 路径，见上一节）
```

**关键结构性结论：JSON 形状与 `type` 无关，恒定 14 个键。** `type` 只决定二进制读写时走哪个
分支（`DoRead`/`DoWrite` 里 `type==196` 走一条完全独立的短分支，不读/不写
`value_ukn2~6`/`wilds_unkn0`；其余情况走标准分支，`filePath` 只在特定 `type` 集合下额外读写），
但 EfxBridge 的 JSON 序列化是对 C# 字段当前值的反射直译，不会因为某个二进制分支没碰到某个
字段就在 JSON 里省略它——没被这次读取触碰到的字段就是其默认值（0/0.0），照样出现在 JSON
里。这意味着 Blender 侧不需要按 `type` 做任何 UI 分支逻辑，用统一的通用字段树天然覆盖了
所有 `type` 取值。

**风险（同 `EFXBone.value` 一个类别）：`fieldParameterNameHash` 不会被 vendor 自动重算。**
通读了 `EfxFile.cs` 全部 `MurMur3HashUtils` 调用点：`ExpressionParameters`（导出时重算
`expressionParameterNameUTF16Hash`/`expressionParameterNameUTF8Hash`，`EfxFile.cs:966-967`）、
`Bones`（导出时重算 `nameHash`，`EfxFile.cs:974`）都有自动同步机制，但
`FieldParameterValues.Write(handler)`（`EfxFile.cs:994`）只是逐项调用 `DefaultWrite`，
**没有任何针对 `fieldParameterNameHash` 的重算逻辑**。也就是说如果用户在 Blender 侧改了
某个 FieldParameterValue 的 `name`，`fieldParameterNameHash` 不会跟着变，两者可能失配。
这次没有对应的"导出前校验"（不像 Bones 的 `ParentBone` 那样有一个可枚举的"合法值集合"能拿来
比对——`fieldParameterNameHash` 应该等于什么，本身就是未知的，没有基准可核对），只是如实
在字段树里把它暴露成一个可编辑的 raw 值（同 `EFXBoneItem.value` 的处理方式），把"改名字要不
要同步哈希"这个判断交给用户，不假装我们能校验一个连算法都不确定的哈希。**留给未来的线索**：
`EfxCommon.cs` 里另有一个语义相邻的 `PropertyNameUTF8Hash`（专门给"被引用的着色器/材质参数名"
做哈希，见上一节"哈希调研补记"），"FieldParameterValues"这个名字和"着色器/材质字段的具名可调
参数"的定位高度吻合，`fieldParameterNameHash` 有理由怀疑是用同一个哈希算法对 `name` 计算的
结果，但**没有拿到真实非零样本核实过**，不确认不实现，仅记录这个猜测供以后验证。

**Blender 实现**：`EFX_ROOT.efx_field_parameters`（`EFXFieldParameterItem` 列表），结构上和
`efx_bones` 平行（都是文件级具名表，UIList + Add/Remove），但内容处理不同——`EFXBoneItem`
只有 `name`+`value` 两个字段，直接摊成两个 `StringProperty`；`EFXFieldParameterItem` 除 `name`
外还有 13 个语义大半未知的字段，改为重用通用 `EFXValueNode` 树（`item.fields`，机制和
attribute 内容字段的 `efx_fields` 完全一样），不手写 13 个具名 PropertyGroup 属性——决策 9
的一贯原则：字段太多、语义大半不确定时，通用树比手写 schema 更诚实。`filePath` 为 `null`
时按 `ParentBone` 的先例规整成 `""`（C# 侧两处 `filePath ??= ...` 写出兜底证实语义等价）。
新增条目时用 `model.FIELD_PARAMETER_CONTENT_DEFAULTS` 预置全部 13 个键（否则字段树是空的，
用户看不到任何可编辑的行）。

**实机验证（2026-07-04，Blender 5.1 + `diag/11_guide_110.efx.5571972.orig`）**：
仓库里唯二的两个真实样本 `FieldParameterValues` 均为空数组（这与 2026-07-03 的 250 样本
调研一致——命中率本来就低，2/250），无法验证真实数据的读入路径，只验证了写入路径：用
Add 按钮新建一条 `type=217`+真实矢量场纹理路径的记录，`io_tree.export_root_to_efxfile()`
直接 dict 检查确认输出 14 个键、`fieldParameterNameHash` 故意设成超过 2^31-1 的大数验证
BIGINT 精度不丢；再单独构造一个不含 `Entries`/`Expression` 内容的最小 `EfxFile` JSON
（绕开与本次改动无关的既有 Expression 反序列化限制，见下方 `docs/BLENDER_MODEL.md` 的
既有记录），过 `EfxBridge load` 确认 C# 端能正常反序列化构造出的 `EFXFieldParameterValue`
JSON 形状，不抛异常。完整 Blender `bpy.ops.efx_re.export()` 走到的唯一失败点仍然是那个
已知的、与本次改动无关的 Expression 反序列化限制（`EFXExpressionDataBase` 缺少无参构造函数）
——和 Bones 那轮验证撞到的是同一个既有缺口，不是新引入的问题。

## `UvarGroups` 结构调研与实现（2026-07-04）

2026-07-03 已经把语义搞得比较清楚（见上方"未知字段语义 cross-reference"一节：`uvarType==1`
是纯标记位，`uvarType==2` 带 `path`+`group`，指向一个游戏内共享 `.uvar` 具名用户变量文件）。
这次直接读 `EfxFile.cs:758-776`（读）和 `EfxFile.cs:1001-1011`（写）把二进制层的结构钉死，
发现一个此前没写进文档、对 Blender 侧设计有直接影响的细节。

**不是自然变长列表，是两个固定二进制槽位，但对象模型层面表现为一个最多 2 项的有序列表：**
```
读（EfxFile.cs:758-776，门控 Header.Version > EfxVersion.DMC5，MHWilds 满足）：
    uvarType1 = 读一个 int
    uvarType2 = 读一个 int
    uvarType1 != 0 时：按 uvarType1 建一条 EFXUvarGroup，Add 进 UvarGroups
    uvarType2 != 0 时：按 uvarType2 建一条 EFXUvarGroup，Add 进 UvarGroups
    （uvarType1 > 2 或 uvarType2 > 2 时直接 throw——决策 9 的整文件拒绝已覆盖，
     不会有 >2 的值流进 Blender）

写（EfxFile.cs:1001-1011）：
    写 UvarGroups[0]?.uvarType ?? 0        — "槽位 1"
    写 UvarGroups[1]?.uvarType ?? 0        — "槽位 2"
    UvarGroups.Count >= 1 时写 UvarGroups[0] 的 path/group
    UvarGroups.Count >= 2 时写 UvarGroups[1] 的 path/group
```
写完全按**列表下标**分配槽位，不按 `uvarType` 取值配对、也不管原始数据来自哪个槽位。举例：
如果原文件"槽位 1 为空（0）、槽位 2 是 `uvarType==2`"，读出来的 `UvarGroups` 列表只有一条
（下标 0，因为槽位 1 是 0 从不 Add），vendor 自己重新写出时会把这条记录归到"槽位 1"——
原始槽位归属信息在 **vendor 自己的读写往返里就已经丢失**，这和 `EfxBridge/Program.cs`
头部注释里 `CollisionEffect` 下标重排是同一类"解码成干净模型、总是重新生成字节，语义等价、
字节不同"的哲学，不是 bug。**结论**：Blender 侧不需要、也不可能保留"槽位 1 vs 槽位 2"这个
身份，只需要维护一个最多 2 项的有序列表，交给 vendor 写出时按下标重新分配槽位——这也意味着
超过 2 项的列表会被**静默截断**（`UvarGroups[2]` 及之后完全不会被写逻辑碰到，既不写
`uvarType`，也不写 `path`/`group`），必须在 Blender 侧堵住这个口子（做法见下）。

**`path`/`group` 是 `RszConditional(uvarType == 2)` 门控字段**（`EfxFile.cs:603-604`）：
`uvarType == 1` 时 vendor 完全不读/不写这两个字段，值是多少不影响导出字节。

**Blender 实现**：`EFX_ROOT.efx_uvar_groups`（`EFXUvarGroupItem` 列表，最多 2 项）。和
`EFXFieldParameterItem`（13 个语义大半未知的字段，用通用树）不同，这里只有 3 个字段且形状
简单明确，改用类似 `EFXBoneItem` 的手写具名字段：`uvar_type` 是一个两选项 `EnumProperty`
（"Marker Only"/"Named Uvar Reference"，标签直接体现已确认的结构含义，而不是裸
`IntProperty`——这个区分是结构上 100% 确认的，值得暴露成有意义的下拉框，游戏侧的真正用途
才是待确认的部分）、`path`/`group` 是普通 `StringProperty`，`uvarType == 1` 时面板隐藏这两
行输入框（避免用户误以为"标记位"槽位也能填路径）。**最多 2 项的限制在 `EFX_OT_uvar_group_add`
里硬拦截**（`len(...) >= 2` 直接 `{"ERROR"}` + `{"CANCELLED"}`，不静默截断，同 Bones
`check_bone_references()` 一脉相承的"宁可拒绝，不要悄悄丢数据"纪律），导出侧
（`export_root_to_efxfile()`）不需要重复这个校验——UI 是唯一的写入入口，Add 操作符已经
保证列表不会超过 2 项。

**实机验证（2026-07-04，Blender 5.1 + `diag/11_guide_110.efx.5571972.orig`）**：这次比
`FieldParameterValues` 幸运——`11_guide_110` 真的有一条非空 `UvarGroups`（正是
2026-07-03 调研记录的那个真实样本：`{uvarType: 2, path: "Art/VFX/VFX_group_common.uvar",
group: "VFX_group_common"}`），完整覆盖了读入路径，不需要像 `FieldParameterValues` 那样
靠手工构造数据模拟。
- Import 后 `efx_uvar_groups[0]` 的 `uvar_type`/`path`/`group` 与样本原始 JSON 完全一致。
- `io_tree.export_root_to_efxfile()` 直接 dict 检查：导出的 `UvarGroups` 和原始样本
  逐字段相同（`uvarType: 2`, `path`/`group` 原样），证明无编辑往返是无损的。
- 截图确认面板正确渲染：列表显示已导入的 `VFX_group_common` 条目（类型下拉 + 文件夹图标 +
  group 名），详情框显示 Type/Path/Group 三个可编辑字段。
- 二态测试 `EFX_OT_uvar_group_add` 的数量上限：已有 1 项时 Add 成功（到 2 项）；再次 Add
  正确拒绝，报错文案提示"最多 2 项"，不静默创建第 3 项。
- Remove 测试：删除后列表正确回到 1 项。

测试完成后同样清空了 Blender 实例里的场景对象/collection 和临时 JSON 文件，没有改动仓库里
的任何样本文件。

## `ExpressionParameters`（顶层参数表）结构调研与实现（2026-07-04）

**先厘清和"棘手"这个印象的落差**：一开始把这个字段标记为"比 `FieldParameterValues`/
`UvarGroups` 更难"，理由是 `EFXExpressionParameter`（`EfxFile.cs:400-448`）有三个"标签联合
视图"计算属性——`Float2`/`Color`/`Range`，共享底层 `value1`/`value2`/`value3`，只有和当前
`type` 匹配的那个可读，其余两个 getter 直接 `throw`。但这个坑早在 Phase 1 就被
`EfxBridge/Program.cs` 的 `StripUnsafeComputedProperties`（文件头部注释里"已发现并绕过的坑"）
挡掉了——JSON 序列化时这三个属性直接从 `JsonTypeInfo` 里剔除，Python 侧压根看不到它们，也
不会因为读到不匹配的 union 分支而崩溃。真正棘手的其实是**攻击了错误的目标**：`docs/`
之前一直把这个字段和 attribute 内容字段里那个更复杂的公式树（`IExpressionAttribute.
Expression`/`IMaterialExpressionAttribute.MaterialExpressions`，`EfxFile.cs:612-621`，
`EFXExpressionDataBase` 缺无参构造函数那个已知反序列化缺口就出在这里）混在一起考虑了——
两者名字相似但完全是两套结构，后者依然按架构决策第 8 点结构化透传、不建字段级 UI，本节
只讨论前者（`EfxFile.ExpressionParameters: List<EFXExpressionParameter>`，文件级具名参数
表，和 `Bones`/`FieldParameterValues`/`UvarGroups` 同一个层级）。

**字段清单**（`EFXExpressionParameter`，`EfxFile.cs:400-409`；`type` 取值见
`EfxExpressionParameterType`，`EfxFile.cs:69-87`）：
```
expressionParameterNameUTF16Hash  uint     — 导出前被 vendor 无条件用 MurMur3 从 name 重算
expressionParameterNameUTF8Hash   uint     — 同上（UTF8 版本）
type                               enum     — 0=Float / 1=Color / 2=Range / 3=Float2
value1 / value2 / value3          float    — 具体哪几个生效由 type 决定（见下）
name                               string?  — 走 Strings.ExpressionParameterNames 平行表
                                              （同 Bones/Actions/FieldParameterValues 机制）
```
`type` 语义（vendor 注释 + 真实样本双重印证，"数据形状"层面完全确认，"游戏侧用途"部分仍是
推测——两者分开标注，不混为一谈）：
- `Float (0)`：`value1` 生效，单个浮点值。
- `Color (1)`：`value1` 的浮点数值**按位重新解释**成打包 `uint32` RGBA（`BitConverter.
  SingleToInt32Bits`/`Int32BitsToSingle`），和 `via.Color.rgba` 走位打包 uint32 的手法完全
  一样，`value2`/`value3` 未用。
- `Range (2)`：`value1`/`value2`/`value3` 都生效，vendor 注释推测是
  `{初始值, 最小值, 最大值}`（"X 总是落在 Y-Z 区间内"），**未证实**。
- `Float2 (3)`：`value1`/`value2` 生效，`value3` 未用，vendor 注释"样本里只见过 0.0/1.0"，
  疑似布尔语义，**未证实**。

**哈希字段不需要在 Blender 侧维护同步**：通读确认 `EfxFile.cs:965-969` 的写出逻辑——
```csharp
foreach (var exprParam in ExpressionParameters) {
    exprParam.expressionParameterNameUTF16Hash = MurMur3HashUtils.GetHash(exprParam.name ?? "");
    exprParam.expressionParameterNameUTF8Hash = MurMur3HashUtils.GetUTF8Hash(exprParam.name ?? "");
    exprParam.Write(handler);
}
```
两个哈希在写之前**无条件**被覆盖重算，不像 `FieldParameterValues.fieldParameterNameHash`
那样"改名字不会自动同步"——这里改名字天然保持同步，Blender 侧导出时随便填 0 占位即可，
已用真实样本验证vendor 会正确算出和原文件一致的哈希（见下方实机验证）。

**踩到一个真实的、和 NaN/Infinity 编码有关的正确性问题（不是理论风险，真实样本已经命中）**：
`Color` 类型把一个浮点数的**位模式**当 RGBA 用，任何 `alpha≈255`（最常见的不透明色）叠加
`blue>=128` 的组合，重新解释成 float 后指数位全 1，正好落进 NaN/Infinity 的位模式区间——
`11_guide_110` 的真实样本里 9 条 `ExpressionParameters` 有 4 条（`colorR_N/P/D/T`）就是这种
情况。`EfxBridge` 用 `JsonNumberHandling.AllowNamedFloatingPointLiterals`把 NaN/Infinity
序列化成**带引号的字符串**（`"NaN"`，不是裸 token）；而 Python 内置 `json.dump` 对
`float('nan')` 默认写的是**裸 token**（`NaN`，不带引号，`allow_nan=True` 的默认行为）——
两者形式不一致。实测证实：把裸 token 喂给 `EfxBridge load` 会被 `System.Text.Json` 直接拒绝
（`'N' is an invalid start of a value`），**即使开着 `AllowNamedFloatingPointLiterals` 也不
接受裸 token，只接受带引号字符串**。这个坑对现有的 `EFXValueNode` 通用树是无害的——通用树
按 `isinstance(value, float)` 判定 data_type，读到 JSON 字符串 `"NaN"` 时会分类成 `STRING`
而不是 `FLOAT`，全程当不透明字符串囫囵存取，原样往返，从不会真的产生一个 Python `float`
意义上的 NaN。但这次 `value1/2/3` 为了配合颜色轮控件需要用真正的 `FloatProperty`（数值参与
颜色换算），必须显式转换：`model.json_float_in()`（导入时把 `"NaN"`/`"Infinity"` 字符串转
成真正的 Python `float`，`float()` 内置就支持）、`model.json_float_out()`（导出时反过来，
`math.isnan`/`math.isinf` 命中时手动转回带引号字符串，不依赖 `json.dump` 的默认行为）。

**Blender 实现**：`EFX_ROOT.efx_expression_parameters`（`EFXExpressionParamItem` 列表，
无数量上限，不像 `UvarGroups` 那样有二进制层面的硬限制）。字段形状简单固定、`type` 语义
已确认到"哪几个字段生效"这一层，和 `UvarGroups` 一样选择手写具名字段而不是通用树：
`name`/`param_type`（4 选项 `EnumProperty`）/`value1`/`value2`/`value3`（真正的
`FloatProperty`）+ 一个 `color_value`（`FloatVectorProperty`，get/set 直接对 `value1` 做
和 `via.Color` 一样的按位重解释，`type==Color` 时才有意义）。面板详情框按 `param_type` 只
展示当前生效的字段（`Float` 只显示 `value1`，`Color` 显示颜色轮，`Range` 显示三个值，
`Float2` 显示两个值）——和 `UvarGroups` 隐藏无效 `path`/`group` 输入框同一个思路，不新增
判断模式。

**实机验证（2026-07-04，Blender 5.1 + `diag/11_guide_110.efx.5571972.orig`）**：这个字段
的运气和 `UvarGroups`一样好——真实样本有 9 条数据，且恰好覆盖了最需要验证的 NaN 场景。
- Import 后逐条核对：`IsBlue`（`type=Float2`，`value1/2=0`）、`color_N/P/D/T`
  （`type=Color`，`value1` 是有限但很极端的负浮点数）、`colorR_N/P/D/T`（`type=Color`，
  `value1` 真的是 `float('nan')`，用 `math.isnan()` 直接断言确认）——与样本原始 JSON 完全
  对应。
- 颜色轮 get/set 正确解码：`color_N` 解出 RGB≈(85,216,44) alpha=255（一个合理的绿色），
  `colorR_N` 的 NaN 位模式解出一个 alpha≈127 的半透明蓝色——两者都是合理的颜色值，位运算
  逻辑正确。截图确认面板选中 `colorR_N` 时正确显示一个带透明棋盘格的颜色轮控件。
- 直接检查 `io_tree.export_root_to_efxfile()` 的返回值：导出的 7 个 `ExpressionParameters`
  字典（除两个哈希占位成 0 外）与原始样本逐字段相同，NaN 条目正确导出成带引号字符串
  `"NaN"`（不是裸 token）。
- **过真实 `EfxBridge load`/`dump` 完整走了一遍**（构造一个剥离 `Entries`/`Actions`/
  `Bones`/`BoneRelations`/`FieldParameterValues`/`UvarGroups` 的最小 `EfxFile`，只保留原始
  9 条 `ExpressionParameters`）：`load` 成功接受带引号的 `"NaN"` 字符串，`dump` 回来的 9
  条记录（含 4 条 NaN）与原始样本逐字段相同，两个哈希字段也被 vendor 正确重算回和原始样本
  一致的值——证明这条"必须用带引号字符串而不是裸 token"的判断是对的，不是纸上谈兵。
- Add/Remove 操作符二态测试：Add 后数量 +1，Remove 后数量 -1，行为符合预期（这个字段没有
  `UvarGroups` 那种数量上限，不需要拦截逻辑）。
- 走真实 `bpy.ops.efx_re.export` operator 端到端验证：卡在一个已知的、和这轮改动完全无关
  的既有缺口——但这次的报错路径确认是 `Entries[1].Attributes[13].Expression.
  expressions[0].components[0].data`（attribute 内容字段里的公式树，`EFXExpressionDataBase`
  缺无参构造函数），不是本节实现的顶层 `ExpressionParameters` 列表，进一步印证了本节开头
  "两者是完全不同的两套结构"的判断。

测试完成后同样清空了 Blender 实例里的场景对象/collection 和临时 JSON/efx 测试文件，没有
改动仓库里的任何样本文件。

## vendor 升级：`5224835` → `ebb1bc7`，解决长期存在的 Expression 反序列化缺口（2026-07-04）

**背景**：用户提供线索——姊妹应用 [REE-Content-Editor](https://github.com/kagenocookie/REE-Content-Editor)
（同一作者 kagenocookie，作为独立 GUI 工具消费同一个 `RE-Engine-Lib`）几小时前把内嵌的
`RE-Engine-Lib` submodule 从 `5224835`（正好是本项目当前 vendor 版本）升到
`ebb1bc7dfd52637ad9fc7f2c5c87d34c798d4790`，提交信息是"Fix efx json serialization for
expressions, embedded efx"。用 `gh api repos/kagenocookie/RE-Engine-Lib/compare/...` 直接
拉了这两个 commit 之间的完整 diff（`8b5325b`/`ebb1bc7` 两个提交），逐个确认了对本项目的影响，
决定升级。**已完成**：`vendor/RE-Engine-Lib` submodule 指针更新到 `ebb1bc7`，`EfxBridge`
重新编译，四个已实现的顶层字段（Bones/FieldParameterValues/UvarGroups/ExpressionParameters）
全部重新走了一遍实机验证，外加第一次真正跑通了含真实 Entries/Actions 的完整
`bpy.ops.efx_re.export` 端到端流程（此前每一轮验证都卡在同一个已知缺口上，从未真正走完）。

**升级修的是什么**：`EFXExpressionDataBase`（attribute 内容字段里 `Expression`/
`MaterialExpressions` 公式树用到的多态基类）此前反序列化直接抛
`NotSupportedException`（"缺无参构造函数"）——这是本项目从 Bones 那一轮起，每一次
`bpy.ops.efx_re.export()` 端到端验证都会撞到的同一个缺口，一直被记录成"已知的、和本项目改动
无关的既有问题"。新版本给 `EFXExpressionDataBase` 补了正规的
`JsonPolymorphismOptions`（`type` 字段做判别式，显式列出 5 个派生类），问题从根上解决。
用真实样本（`11_guide_110`，含 2 个 Action + PlayEmitter + 141 个 attribute）验证：
`bpy.ops.efx_re.export()` 第一次返回 `{"FINISHED"}`，导出文件用 `EfxBridge dump` 复核可以
正常读回，`Entries`/`Actions`/`Bones`/`FieldParameterValues`/`UvarGroups`/
`ExpressionParameters` 逐字段和原始样本完全一致，`EffectGroups` 按预期重新排序（同一组下标，
顺序不同，语义等价——这个"解码成干净模型、总是重新生成字节"的差异本来就是项目公认的正常
行为，见 `EfxBridge/Program.cs` 头部注释）。

**`ExpressionParameters` 的 JSON 形状整个变了**（升级前的形状记录在上方
"`ExpressionParameters`（顶层参数表）结构调研与实现"一节，不删除，作为历史记录保留，注意
读的时候要按"旧版本"理解）：
```
旧（vendor 5224835）：{expressionParameterNameUTF16Hash, expressionParameterNameUTF8Hash,
                        type: <int 0-3>, value1, value2, value3, name}
新（vendor ebb1bc7）：{type: <string, "Float"/"Color"/"Range"/"Float2">, name, value}
                       value 形状随 type 变化：
                         Float  → 裸数字
                         Float2 → {X, Y}
                         Range  → {X, Y, Z}
                         Color  → {rgba: <uint32>}（和 via.Color 完全一样的打包整数）
```
新增了一个自定义 `EFXExpressionParameterJsonConverter`（vendor `EfxFile.cs` 里的
`EfxJsonTypeResolver` 静态构造函数注册），彻底取代了旧版本"三个标签联合视图属性靠反射直接
序列化、桥接层手工剔除"的做法。两个具名哈希字段在新版本里**完全不出现在 JSON 里**——读
`name` 时转换器就地用 MurMur3 算好塞进内存对象，写的时候压根不输出，Blender 侧不需要提供
占位值。

**最大的实际收益：`Color` 类型不再有 NaN 风险。** 旧版本把 RGBA 按位重新解释成一个浮点数
（`value1`），真实样本证实这经常落进 NaN 位模式（`alpha≈255` 叠加 `blue>=128`），逼着我们写
`model.json_float_in/out` 显式处理"EfxBridge 用带引号字符串表示 NaN、Python `json.dump`
默认写裸 token 两者不兼容"这个坑。新版本 `Color` 直接是一个干净的 `rgba: uint32`，完全不
经过浮点数，`EFXExpressionParamItem` 相应改用 `rgba_str`（十进制字符串，BIGINT-safe，同
`EFXBoneItem.value` 的惯例）存储，颜色轮 get/set 变成纯粹的整数位运算，不再需要
`struct.pack`/`unpack`。`json_float_in/out` 两个函数保留，继续给 `value1/2/3`
（`Float`/`Range`/`Float2` 类型）做防御性处理——这几个字段本质上还是普通浮点数，理论上仍
可能是 NaN/Infinity，只是目前的真实样本没有命中过，符合决策 9 的一贯态度。

**顺带清理**：`EfxBridge/Program.cs` 里为三个已知坑写的 `StripUnsafeComputedProperties`
工作区（`EFXExpressionParameter.{Float2,Color,Range}` 剔除、`EFXEntryBase.TypeAttribute`
剔除、`EfxFile.parentFile` 剔除）全部由 vendor 自己解决了（前两个分别用自定义
`JsonConverter`/`[JsonIgnore]`，`parentFile` 也直接标了 `[JsonIgnore]`），整个
`TypeInfoResolver` 包装层被删除，直接用 vendor 自带的 `EfxJsonTypeResolver.jsonOptions`。
删除后重新跑了 `EfxBridge roundtrip diag --verbose`（4 个文件全部 `STABLE`）和两个样本的
`dump`/`load` 往返，确认没有引入新问题。

**升级过程中的一次误报，记录下来避免以后重踩**：升级后第一次用命令行手工测试
`dump→load→dump`（输出文件名用的是不带版本号后缀的裸 `.efx`，比如
`g006_new.efx`），第二次 `dump` 读回时炸出 `Header.Version` 变成 `-1`、attribute typeId
读到垃圾值——一度以为是这次升级引入的新回归（做了多组对照实验，包括纯二进制 `roundtrip`
命令验证读写本身没问题，一度怀疑是 JSON 反序列化路径的新 bug）。往深挖after才发现真正原因：
`EfxHeader.DoRead()` 里 `Version = (EfxVersion)handler.FileVersion;`——`Version` 字段本来
就**不存在于二进制字节里**，而是运行时从 `FileHandler.FileVersion` 派生的，`FileVersion`
的取值逻辑（`FileHandler.cs:24-31`）在 `FilePath` 非空时会去解析文件名里的数字后缀
（`PathUtils.ParseFileFormat`）——这一段行为在旧版本（`5224835`）里就已经存在，不是这次升级
改的。给输出文件名补上正确的 `.efx.5571972` 后缀后，问题完全消失，多轮往返稳定、字节级/
内容级比对完全一致。**教训**：以后手工用 `EfxBridge load` 测试时，输出路径必须带正确的
`.efx.<version>` 后缀，不能图方便用裸 `.efx`——这不是 bug，是这套文件格式的设计（版本号本来
就该体现在文件名里，不是任何一个游戏版本都会把它编码进二进制内容本身）。

## `Clip`（attribute 内容级，不是顶层字段）结构调研与实现（2026-07-04）

**先厘清范围**：`Clip` 不是 `EfxFile` 的顶层字段——它是 attribute 内容级的结构，和本文件
其余章节记录的 `Bones`/`FieldParameterValues`/`UvarGroups`/`ExpressionParameters`（都挂在
`EfxFile` 上）不是同一个层级。放进这份文档是因为调研方法和记录习惯一致（同一批"结构确定、
语义部分确定"的字段），且和已经记录在"Bones / BoneRelations 结构调研"里的 `ParentBone`
一样，都是"接口在 attribute 具体类上暴露的字段"这种模式。

**不是一个字段，是一整族 attribute 类型**：`IClipAttribute`/`IMaterialClipAttribute`
（`EfxFile.cs:1009-1019`）两个接口，一共被 ~24 个 `*Clip`/`*MaterialClip` 后缀的独立
attribute 类实现（`Transform3DClip`/`EmitterColorClip`/`PtVelocity3DClip`/`TypeMeshClip`/
……，遍布 `EfxTransform.cs`/`EfxEmitter.cs`/`EfxTypeMesh.cs`/`EfxTypeRibbon.cs` 等十来个
文件）。这些 attribute **不是**"某个正常 attribute 多出来的几个字段"，而是**独立的、必须
和对应的"主" attribute 成对出现的兄弟 attribute**（比如 `Transform3DClip` 要求同一个
Entry 上也有 `Transform3D`）——`EFXEntryBase.AddAttribute()`（`EfxFile.cs:232`）会在挂载时
校验这个配对关系，找不到主 attribute 只会打日志警告，不会拒绝，但结构上"孤立的 Clip
attribute"是不完整的状态。**这一轮只实现纯 `IClipAttribute`（15 个类）**，
`IMaterialClipAttribute`（~9 个，额外带 `mdfProperties`/`indices` 材质属性哈希关联）留给
以后的迭代，见下方"范围边界"。

**核心数据结构**（`ClipSubstructs.cs`）：
```
EfxClipData:
    loopType: EfxClipPlaybackType     — 4 个取值（-1/0/2/4），vendor 注释坦承是猜的
    clipDuration: float               — 所有关键帧里最大的 frameTime，写出时不会自动重算
    clipCount/frameCount/interpolationDataCount: int   — 三个数组的长度，写出时会从数组
                                                          长度自愈（不需要我们手动维护）
    clipDataSize/frameDataSize/interpolationDataSize: int   — 三个数组的字节长度，
                                                              **写出时不会自愈**，必须自己
                                                              按 8/12/16 字节算对（结构体
                                                              大小，见下）
    clips: EfxClipHeader[]            — 每条子曲线的 {frameCount, valueType}
    frames: EfxClipFrame[]            — 所有子曲线的关键帧，按子曲线顺序拼接成一个平铺数组
    interpolationData: EfxClipInterpolationTangents[]   — 只有 Bezier 类型的帧才有一条，
                                                          按"遇到顺序"消费，不是按下标对齐

EfxClipHeader:      {frameCount: int, valueType: ClipValueType}          — 8 字节
EfxClipFrame:       {frameTime: float, type: FrameInterpolationType, value: float(私有)}
                    — 12 字节，IntValue/FloatValue 是对同一个私有 value 字段的两种位重解释
EfxClipInterpolationTangents:  {out_x, out_y, in_x, in_y: float}          — 16 字节
```
`ClipValueType`：`Int=3`/`Float=5`。`FrameInterpolationType`：`Unknown=0`/`Type1=1`/
`Type2=2`（结构体默认值）/`Type3=3`/`Bezier=5`（唯一有结构性证据的——带独立的切线数据段）/
`Type13=13`（仅 DMC5 样本见过）。

**一个真实的 vendor bug：`EfxClipFrame.IntValue` 的 setter 是死代码。**
```csharp
public int IntValue { get => BitConverter.SingleToInt32Bits(value); set => BitConverter.Int32BitsToSingle(value); }
```
setter 算出了转换结果，但忘了赋值回私有字段 `value`（应该是 `this.value = ...`）——C# 属性
setter 的隐式参数刚好也叫 `value`，和私有字段同名，这行代码实际是对局部参数做了一次纯计算
后直接丢弃，`this.value` 完全没被碰过。**通过 `IntValue` 赋值完全不生效**，通读全仓库确认
`FloatValue` 的 setter 是对的（显式 `this.value = value`），所以导出 `ClipValueType.Int`
类型的关键帧必须自己把整数位模式转换成浮点数，写进 `FloatValue`（`model.
int_bits_to_float()`），不能指望 `IntValue`。`IntValue` 的 getter 本身没问题，导入时直接读
没问题。

**`ClipBits`（`BitSet`）决定"这个 Clip attribute 驱动主 attribute 的哪几个字段"，子曲线
数组和置位 bit 一一对应**：`clips[]`（一条子曲线一项）的下标顺序，和 `ClipBits` 里从低到高
排序后的置位 bit 下标一一对应（vendor `BitSet.GetBitInsertIndex()` 就是算这个映射用的：
"给定一个 bit，它前面已经置位的 bit 数量，就是它在数组里应该排的位置"）。也就是说：启用
一个 bit（比如"位置 X 分量"）等于给这个 attribute 新增一条独立的关键帧曲线，关掉一个 bit
等于删掉对应曲线——Blender 侧因此不单独维护"启用哪些 bit"的勾选列表，"添加一条曲线"和
"启用一个 bit"是同一个操作，见下方 Blender 实现。`BitNames`（把 bit 下标映射成字段名）是
vendor **C# 类字段初始化时硬编码的常量**（比如 `expressionBits = new BitSet(6) {
BitNameDict = {...} }`），不是文件自己的数据——`BitSet.DoRead()`/`DoWrite()` 只处理 `Bits`
这个整数数组，`BitNames` 对导出字节没有任何影响。真实样本（`Transform3DClip`，见下）的
`clipBits = new BitSet(9)` 没有定义 `BitNameDict`，`bitNames` 全程是 `null`——只知道"bit 1
被启用"，不知道 bit 1 对应哪个字段，这是**结构确定、字段身份未知**的典型情况，按决策 9
如实标注（面板上没有名字就显示 `Bit {index}`）。

**JSON 序列化里的两组"只读视图"重复内容，导入时全部忽略**：
1. attribute 顶层的 `Clip`/`ClipBits`/`MaterialClip`——`IClipAttribute`/
   `IMaterialClipAttribute` 接口暴露的计算属性（`Clip => clipData`），纯粹是对
   `clipData`/`clipBits` 字段的只读别名，序列化会重复输出一遍完整内容，反序列化用不到（没有
   setter）。真正要读/写的是小写的 `clipData`/`clipBits` 字段本身。
2. `clipData` 内部的 `IsParsed`/`ParsedClip`——`EfxClipData.ParseClip()` 的缓存视图，把
   平铺的 `clips`/`frames`/`interpolationData` 重新分组成"每条子曲线自己的关键帧列表"，
   更适合人读，但同样是只读、没有 setter。**这次没有依赖它**：`ParsedClip` 是否存在、格式
   会不会变，都不影响我们自己的导入逻辑——Blender 侧直接照抄 `ParseClip()` 本身的分组算法
   （按 `clips[]` 每一项的 `frameCount` 依次切 `frames[]`，Bezier 帧顺带从
   `interpolationData[]` 取一个），比依赖一个我们自己也能重算的便利视图更稳健。

**范围边界（这一轮明确不做的）**：
- `IMaterialClipAttribute`（`EFXAttributeTypeMeshClip`/`TypeBillboard3DMaterialClip`/……
  9 个类）——额外的 `mdfProperties: EfxMaterialClip_Struct4[]`（材质属性哈希 +
  几个未知字段）/`indices: uint[]` 关联材质参数，本轮结构性排除
  （`model.is_clip_attribute_dict()` 检测 `clipData` 里有没有 `mdfProperties` 键），继续
  走通用树透传，不建专属 UI。
- "主/Clip 兄弟 attribute 必须成对存在"这个约束本轮不做导出前校验——只有真正拿到一个
  "有 Clip 没有主 attribute"的真实样本、确认这在游戏里到底是不是致命错误，才知道要不要拦。

**Blender 实现**：`Object.efx_is_clip_attribute`（持久标记，导出时判断走不走 Clip 专属逻辑，
不靠"曲线列表是不是空"推断——0 条曲线也是合法状态）+ `efx_clip_bit_count`（只读展示，
attribute 类型固定的常量）+ `efx_clip_loop_type`（4 选项 Enum）+ `efx_clip_curves`
（`EFXClipCurveItem` 列表，一条曲线 = 一个启用的 bit，`bit_index`/`bit_name`（纯展示）/
`value_type`（Int/Float Enum）/`keyframes`）。每条曲线的 `keyframes`
（`EFXClipKeyframeItem` 列表）：`frame_time`/`interp_type`（6 选项 Enum）/`value`（统一用
`FloatProperty`，Int 类型时存整数的浮点表示，导出时四舍五入取整再按位转换）/4 个 Bezier
切线分量（只在 `interp_type == "5"` 时面板显示）。三层级联 UIList（曲线列表 → 选中曲线的
关键帧列表 → 选中关键帧的详情），Add 曲线自动挑最低的未使用 bit（挑不到时报错，不静默失败）。

新增 `io_tree.check_clip_bits()`（导出前校验，同 `check_bone_references()` 的纪律）：
`bit_index` 越界（超出 `[0, bit_count)`）或重复（两条曲线用了同一个 bit）都直接拒绝导出——
越界会让 C# 侧 `BitSet.SetBit()` 在 `load` 阶段直接数组越界抛异常（不是理论风险，`Bits[
bitIndex >> 5]` 是裸数组访问），重复会让两条曲线的数据在写出时对同一个 bit 位互相覆盖，
两种情况都不能悄悄放行。和 `check_bone_references()` 不同的是这个校验**会递归进嵌套
PlayEmitter.efxrData 子树**——Clip 的 bit 校验是纯局部的（不依赖任何文件级共享表），没有
已知的嵌套读写不对称问题，没有理由把检查范围收窄到顶层。

**实机验证（2026-07-04，Blender 5.1 + `diag/11_guide_110.efx.5571972.orig`）**：真实样本
里的唯一一个 Clip attribute（`Entry4` 上的 `Transform3DClip`）覆盖了大部分关键路径——
`bit_index=1`（`bitNames` 确认是 `null`，面板正确显示成"Bit 1"）、`value_type=Float`、
3 个关键帧全部是 `Bezier` 插值（带真实的切线数据）。
- Import 后逐字段核对：`bit_count=9`、`loop_type="-1"`（面板正确显示"Looping"）、
  曲线的 `bit_index`/`value_type`/3 个关键帧的 `frame_time`/`value`/`interp_type`/4 个
  切线分量，与样本原始 JSON（`clipData.clips[0]`+`clipData.frames[]`+
  `clipData.interpolationData[]`+`clipBits.bits`）完全一致。
- 直接检查 `io_tree.export_attribute_object()` 的返回值：`clipData`/`clipBits` 逐字段
  完全相同，三个 `*Size` 字段（`8`/`36`/`48`）精确匹配原始样本（confirmed 1 条曲线×8 字节、
  3 帧×12 字节、3 条切线×16 字节）。
- **过真实 `bpy.ops.efx_re.export()` 走完整链路**：导出后用 `EfxBridge dump` 复核，
  `clipData`/`clipBits` 和原始样本逐字段完全相同（这次不像 `EffectGroups` 那样有"重新计算
  导致顺序不同"的情况——Clip 没有被 C# 后端二次处理，纯粹是我们自己写出去多少就是多少）。
- 手工验证 `IntValue`/`FloatValue` 位转换往返：`int_bits_to_float(42)` →
  `5.885453550164232e-44` → 反向 `struct.unpack("<i", ...)` 精确取回 `42`，确认
  `EfxClipFrame.IntValue` setter bug 的规避方案是对的（真实测过，不是纸上谈兵）。
- `check_clip_bits()` 三态测试：合法状态放行；`bit_index` 设成 99（超出 `bit_count=9`）
  正确拒绝；两条曲线设成同一个 `bit_index` 正确拒绝（报错信息标出具体是哪个 attribute、
  哪个 bit）；恢复合法状态后正确放行——四个状态全部通过。
- 走真实 `bpy.ops.efx_re.export` operator 用一个刻意构造的重复 `bit_index` 触发拒绝：
  operator 在调用 C# 桥接之前就报错、不写文件，和 `check_bone_references()` 的既有行为
  一致。
- 截图确认三层级联 UI 渲染正确：曲线列表显示"Bit 1 / 3 kf / Float"，选中后关键帧列表显示
  3 个 `t=.../v=.../Bezier` 条目，选中关键帧后详情框显示 Time/Interpolation/Value 和 4 个
  Bezier 切线分量，数值全部与原始样本吻合。

测试完成后同样清空了 Blender 实例里的场景对象/collection 和临时 JSON/efx 测试文件，没有
改动仓库里的任何样本文件。
