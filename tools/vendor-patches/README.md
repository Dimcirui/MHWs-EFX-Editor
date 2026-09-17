# vendor-patches

`vendor/RE-Engine-Lib` 默认铁律是不改源码（CLAUDE.md #4）——发现的缺陷记 `KNOWN_UPSTREAM_ISSUES.md`，
能绕就在 `tools/EfxBridge/Program.cs` 里绕。这个目录放的是**例外**：绕不开、又足够小、足够有
把握的补丁，才收在这里。别把这当成绕开铁律 #4 的旁路——新增前先确认真的够小、够有把握。

⚠ **第一步永远是先证明这真是 vendor 的错**，不是我们喂错了。判据：跑一条完全不经我们
代码的路径复现（`roundtrip` 是二进制→对象图→二进制，不过 JSON；`dump`/`load` 过 JSON，
复现不了就说明锅在我们这层）。0005 就是这么定的：撤掉补丁后纯二进制路径 0/4 与原文件
相同，打上后 3/4——一个字节都没经过我们的代码，所以确凿是 vendor 写错。

## 0001-efx-expression-func18-19-20-args2-dispatch.patch

对应 `KNOWN_UPSTREAM_ISSUES.md` #6。`EfxExpressionParser.ParseFunction()` 的 `args==2` 分支
无条件把函数名当 `BinaryExpressionOperator` 解析，MHWilds 专属的 `Func18`/`Func19`/`Func20`
（`EfxExpressionFunction` 成员，同样是 2 参）会直接解析失败——公式能显示，改完存不回去。

评估过用 Program.cs 层面的文本替换绕过（同 `material` 那个套路），但这里没有干净的挂钩点：
`EfxExpressionStringParser` 是 vendor 内部的私有静态递归下降解析器，没有暴露任何可拦截的中间层，
外部 workaround 只能靠"替换成一个不会真正出现的占位符再解析回来"这种字符串手术，比这个补丁本身
更绕、更依赖对 vendor 内部语法的隐性假设。改动量也就一个 if/else 分支，跟它自己在同一个函数里
给 `args>=3` 用的写法（`Enum.Parse<EfxExpressionFunction>` + `ExpressionFuncOperation`）完全同构，
判断为小到可以本地垫这一块。

## 0002-efx-rszfixedsizearray-implicit-length-write.patch

对应 `KNOWN_UPSTREAM_ISSUES.md` #1（`Layout` attribute 解析失败，语料里最大的一块，13.3%）。
这个改的不是 `EfxExpressionParser.cs` 里那种具体某个类的读写方法，是 **`REE-Lib.Generators`
里的 Roslyn 源生成器本身**（`ReeLibGenerator.cs`）——`[RszFixedSizeArray]` 不带显式 size 参数、
且字段不是 `readonly` 时，生成的 Read 代码会先读一个 `int` 当元素个数再读数组，但生成的 Write
代码只写数组本体，从不写这个长度前缀。两边不对称：我们自己写出的文件，下次再读回来时，会把
紧跟在数组后面的字节当成"下一次读取的长度"，读出一个离谱的巨大值，级联炸穿后面所有字段——这正是
`Layout` 报错信息里"Actual 远大于 Expected"的成因。

全仓库只有两处用到这个不带参数的写法：`EFXAttributeLayout.layoutDataFloats`（`EfxMiscStructs.cs`）
和 `EfxPtBehavior.cs` 的 `Data` 字段，改动面很小；而且这是源生成器，补丁改的是生成器本身，一次
`dotnet build` 就会重新生成两处受影响的读写代码，不需要另外触碰任何生成产物。

**实测确认**：全语料 roundtrip 从"7930 稳定 / 1291 异常（86.0%/14.0%）"提升到
"9168 稳定 / 53 异常（99.4%）"——`Layout`（1232）和 `OverflowException`（6，同一根因的另一种
表现）两类异常全部清零，剩下 53 个是完全不相关的其他缺口（`charCount too large`/未实现类型等，
见 `KNOWN_UPSTREAM_ISSUES.md`）。回归测试：临时撤掉这个补丁重新编译，`tools/verify_blender_roundtrip.py`
在 `11_st405_smoke_000`/`11_st405_a00_002` 两个真实样本上原样复现历史记录里的
`Expected: 988 Actual: 4197` 异常（数值分毫不差），加回补丁后全绿。

## 0003-efx-opaque-unknown-attribute-types.patch

对应 `KNOWN_UPSTREAM_ISSUES.md` #4/#5。`PtColorMixerClip`/`FixRandomGeneratorExpression`/
`FluidParticle2DSimulatorExpression` 这三个类型在 MHWilds 的 itemType 映射表里有登记，但 vendor
没给它们配读写实现类——`EfxAttributeTypeRemapper.Create()` 找不到类型直接抛
`Unsupported EFX attribute type`，带这些 attribute 的文件整个读不进来。

不认识这几个类型的字段结构（vendor 自己也不认识），照抄社区 010 模板的兜底思路
（`ubyte unkn[unknSeqNum - 4]`）：新增 `EfxUnknownAttributes.cs`，给这三个类型各配一个"整个
attribute body 当不透明字节数组读写"的类，不解释字段、不暴露给用户编辑，只保证原样导入导出。

这个比 0001/0002 多碰了一处共享代码：MHWilds 起每个 attribute 前面有一个"声明长度"字段
（`EfxFile.cs` 里的 `expectedSize`），原来只在 `EFXEntry.DoRead()`/`EFXAction.DoRead()` 里读出来
做读后校验，没有传给 attribute 对象自己——不透明类要知道自己多长，必须先能读到这个数。补丁给
`EFXAttribute` 基类加了一个默认 `-1` 的新字段 `ExpectedByteSize`，在那两处 `DoRead()` 里各加一行
赋值。纯加法、不改任何现有分支的行为，理论上不影响其余 ~238 个已注册类型的读写，但改动面确实是
共享基础设施而不是隔离的新文件，评估的时候要认这一点。

**实测确认**：三个类型对应的语料样本（`PtColorMixerClip`/`FixRandomGeneratorExpression`/
`FluidParticle2DSimulatorExpression` 各一个）单独 dump 均成功；`FixRandomGeneratorExpression`/
`FluidParticle2DSimulatorExpression` 两个样本在 Blender 真实路径下 5 项检查全绿。回归测试：
临时移除这个补丁重新编译，两个样本原样复现 `Unsupported EFX attribute type` 异常，加回补丁后
恢复全绿。

**`PtColorMixerClip` 样本的已知限制**：这个具体样本文件里还带一个 `TypeMeshClip` attribute，
经排查是一个跟这次补丁完全无关的独立 bug（`EFXAttributeTypeMeshClip.MaterialClip => clipData`
这种"只读属性指向同一个字段"的写法，在 `JsonObjectCreationHandling.Populate` 模式下会把同一个
`List` 从两份 JSON 快照重复填充一次，导出体积翻倍）——这个 bug 之前一直被这份样本更早的
`PtColorMixerClip` 解析失败挡住，本次修复后才第一次暴露出来，跟 0003 patch 无关。已经记进
`KNOWN_UPSTREAM_ISSUES.md #8`，没有一并修。

## 0004-efx-bonerelation-strainribbon-fluidsim.patch

对应 `KNOWN_UPSTREAM_ISSUES.md` #9。`Bones`/`BoneRelations` 是**位置制**索引流：`SetupBoneReferences()`
按"遇到顺序"给每个 `IBoneRelationAttribute` 分配下一个下标——**"谁是消费者"这个集合差一个，整条流就
从那里起全体错位**。语料证明 MHWilds 下除了 vendor 认的 4 个类型，还有 `EFXAttributeTypeStrainRibbonV3`
和 `EFXAttributeFluidParticle2DSimulator` 也各消费一个槽位。后果不只是读错：导出时 `BoneRelations` 按（更少的）
消费者数量整体重建，**每个受影响文件都会静默少写若干个 short**，绑定关系永久丢失。

判据不靠猜：`Header.boneAttributeEntryCount` 是游戏自己写进文件的槽位数。全语料 9175 个文件、
11927 个作用域里有 220 个和 vendor 的消费者数量对不上、且永远是 vendor 少；补上这两个类型后降到 **0**，
同时"按下标查出来的骨骼名 vs attribute 自己内联存的骨骼名"不一致数从 **1158 降到 1**。
独立确证（没参与推导）：`TypeStrainRibbonV3` 自己也有一个内联 `boneName`，补丁生效后这 916 个实例
的内联名也进入比对，**916/916 全部与新对齐的下标解析结果一致**。

改动就是给两个类各加一个接口声明 + 一行 `public string? ParentBone { get; set; }`（这个自动属性
不带任何 `[Rsz*]` 标注，源生成器不会给它生成读写代码，字节布局不变），共 4 行有效改动，和
`EFXAttributeTypeStrainRibbonV2` 现成的写法逐字同构。Program.cs 层面没有挂钩点——C# 没法从外部给一个类
追加接口实现，而 `SetupBoneReferences()` 和写出侧都是靠 `is IBoneRelationAttribute` 做类型判断的。

## 0007 —— `BinaryExpressionOperator.Pow` 改名 `PowOp`，消除和函数 `Pow`（操作码 20）的文本撞名

上游 `a96e1d9` 把操作码 0 命名为 `Pow`，而 `EfxExpressionFunction.Pow` 是操作码 20，两者
`ToString()` 都写成 `Pow(a, b)`。`EfxExpressionStringParser.ParseFunction()` 的 `args == 2`
分支**先试 `BinaryExpressionOperator`**，所以文本读回来一律是操作码 0——**每次
`dump`/`load` 都把操作码 20 静默改写成 0**。

字节级实测（`11_em0159_00_308.efx.5571972`，公式 `Pow((0.01 * TIMER), 3)`）：

```
原文件    : 03 00 00 00 14 00 00 00   = (type=3, value=20) 函数 Pow
dump->load: 01 00 00 00 00 00 00 00   = (type=1, value=0)  运算符 Pow
```

补丁把**操作码 0** 改名成 `PowOp`（用户看不到这个字面量，界面显示中缀 `**`），文本因此
无歧义。修补后同一文件 `dump`->`load` **逐字节相同**。

⚠ 这条符合铁律 #4 的三条判据：① 拿完全不经我们代码的路径复现（字节对照），②
改动是一个枚举成员改名 + 三处引用，③ 文本是 vendor 解析器自己产/自己吃的，
`Program.cs` 没有干净挂钩点。

## 0006-efx-attractor-unknwild-float-fields.patch

跟前 5 个不一样，**这个不是修 bug**——`UndeterminedFieldType` 本来就是 vendor 给"类型待定"
字段留的合法占位（4 字节原样读写，`GetMostLikelyValueTypeObject()`/`GetMostLikelyValueTypeString()`
两个 helper 就是给这种字段以后确定类型用的），改之前它读写完全正确，不存在"往返对不上"这回事，
所以 README 开头那条"先证明是 vendor 的错"的判据在这里不适用——没有错可证明，纯粹是**类型精化**：
拿到了足够的证据把"待定"收窄成"确定是 float"。

对应 `EFXAttributeAttractor`（`Attractor` attribute）MHWilds 专属块里的 `unknWild1`/`unknWild10`。
全语料 1105 个实例用 `fieldstats`/`condstats` 扫出来的取值分布：两个字段的非零取值按 IEEE754
位模式解出来全部是干净的十进制数——`unknWild1` 只有 7 种非零取值 {0.1, 0.2, 0.3, 0.8, 1.0, 8.0,
10.0}；`unknWild10` 只在 `Flags==8` 时非零（102 个同 Flags 实例里 74 个），落在 -0.68~2.0 弧度。
按裸 `int` 读会是 1036831949 这种没有意义的天文数字，8 次不同实例全部"恰好"是圆整小数的概率
按纯随机 int 分布算趋近于 0，判定这两个字段是原始类型精度丢失（vendor 保守存成 undetermined），
不是我们瞎猜。语义（`unknWild1`/`unknWild10` 分别是什么物理量）仍然完全不知道，**只订正数据类型，
不改字段名、不下语义结论**——那部分留给 `mhws_field_labels.json`，等真机验证后再补。

风险评估：这个改动**无论解读对不对，都不会丢数据**——`float`/`UndeterminedFieldType` 都是 4 字节
原样读写，位模式的重新解读只影响 JSON 里怎么显示这个数（嵌套 `{"value": N}` 还是裸浮点数），不影响
二进制布局；`float` 读进来再写出去是 `BitConverter` 级别的位对位还原，NaN payload 也不例外。改动
只有 2 行有效改动（外加一段注释），Program.cs 层面没有合适的挂钩点——这两个字段的"真实类型"是
结构体自身声明决定的，桥接层没法在不碰 `EfxJsonTypeResolver`/反射的前提下让同一个 `[$type]` 判别
出来的字段按不同类型序列化。

**实测确认**：改前改后 `fieldstats` 扫到的实例数、文件数、失败数完全一致（1105 / 9175 / 46），
非零取值从 `unknWild1.value: {"1036831949": 75, ...}` 变成 `unknWild1: {"0.1": 75, ...}`，数值
逐一对应验证过是同一批位模式；全语料 `roundtrip` 稳定/异常分布（9175 稳定 / 0 不稳定 / 46 异常）
和改动前完全一致，无回归。

## 怎么用

**vendor 是 submodule，工作区改动不会随 `git submodule update` 保留**——每次重新 checkout /
升级 vendor 之后都要重新打一遍：

```bash
git apply tools/vendor-patches/0001-efx-expression-func18-19-20-args2-dispatch.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0002-efx-rszfixedsizearray-implicit-length-write.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0003-efx-opaque-unknown-attribute-types.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0004-efx-bonerelation-strainribbon-fluidsim.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0005-efx-inline-wstring-bytesize-fields.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0006-efx-attractor-unknwild-float-fields.patch --directory=vendor/RE-Engine-Lib
```

（`git apply` 认不出就说明补丁跟当前 vendor commit 对不上下文了，去对应源文件里手动照着补丁
内容改一遍，然后重新生成这个 patch 文件。）

## 什么时候可以删

**0001**：跑 `dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll exprcheck "Func18(TIMER, 2)"`，
如果不打补丁也能 `OK`（说明上游自己修好了），删掉这个文件、删掉 `EfxExpressionParser.cs` 里那几行、
`KNOWN_UPSTREAM_ISSUES.md` #6 标一下已解决即可。

**0002**：跑一遍全语料 `roundtrip`（见仓库 `CLAUDE.md`），如果不打补丁 `Layout` 类异常已经是 0，
说明上游自己修好了，删掉这个文件、删掉 `ReeLibGenerator.cs` 里那几行、`KNOWN_UPSTREAM_ISSUES.md`
#1 标一下已解决即可。

**0003**：跑一遍 `dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll types <输出.json>`，看
`PtColorMixerClip`/`FixRandomGeneratorExpression`/`FluidParticle2DSimulatorExpression` 是不是
已经有上游自己的实现类了。如果有，删掉这个文件、删掉 `EfxUnknownAttributes.cs`、删掉 `EfxFile.cs`
里 `ExpectedByteSize` 那几行、`KNOWN_UPSTREAM_ISSUES.md` #4/#5 标一下已解决即可——注意上游一旦
自己实现了，大概率跟我们这个"整块当字节数组"的粗糙版本字段完全对不上，不能指望平滑过渡，直接
换成上游的类。

**0004**：跑一遍
`dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll bonealign <语料目录> <输出.json> --extra __NONE__`，
如果不打补丁"数量对不上的作用域"已经是 0，说明上游自己修好了，删掉这个文件、撤掉那两个类上的
改动、`KNOWN_UPSTREAM_ISSUES.md` #9 标一下已解决即可。

**0005**：跑 `python tools/check_inline_wstring_size.py <语料目录> [数量]`（dump -> load -> 和原文件
逐字节比），如果不打补丁受影响文件已经是 0，说明上游自己修好了，删掉这个文件、撤掉那 18 个
字段上的 `ByteSize = true`、`KNOWN_UPSTREAM_ISSUES.md` #11 标一下已解决即可。

**0006**：这个不是"上游修不修"的问题（本来就没错），只在上游自己给 `Attractor` 的 MHWilds
专属字段配了正式类型/名字时才需要处理——那时大概率连字段名都不一样，直接对照上游的类型定义，
删掉这个文件、把 `unknWild1`/`unknWild10` 换成上游版本即可，不需要"先确认没打补丁也一样"这一步。
