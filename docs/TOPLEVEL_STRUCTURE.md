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

**决策（已定）**：`FieldParameterValues` 与 `ExpressionParameters` 均视为 MHWs 新增的、
暂不深挖语义的子系统——**只做透传，不做字段级解析/编辑 UI**，与架构决策第 8 点对 Expression
的处理原则一致（结构化透传，UI 后置，不卡其他功能）。不再尝试把 `FieldParameterValues` 往
MHWI Extern"替换参数"机制上套（调研阶段的一个假设，已放弃——两边都没有确凿的消费端代码
佐证这个映射，与其猜一个不确定的语义，不如先诚实地标记为"不透明"）。MHWI Extern 的第二种
子类型（"external EFX references"）在 Wilds 侧目前没有找到任何结构对应物，视为可能已被
移除/合并，等有真实样本再复核。

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
- **FieldParameterValues / ExpressionParameters / UvarGroups**——暂列为不透明数据块随
  文件透传，不建 PropertyGroup 编辑面板（`UvarGroups` 为 2026-07-03 复核时新发现，
  归入同一处理原则，见下方验证记录）。

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
