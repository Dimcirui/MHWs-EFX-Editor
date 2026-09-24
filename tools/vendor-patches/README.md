# vendor-patches

`vendor/RE-Engine-Lib` 默认铁律是不改源码（铁律 #2）——发现的缺陷记 `KNOWN_UPSTREAM_ISSUES.md`，
能绕就在 `tools/EfxBridge/Program.cs` 里绕。这个目录放的是**例外**：绕不开、又足够小、足够有
把握的补丁，才收在这里。别把这当成绕开铁律 #2 的旁路——新增前先确认真的够小、够有把握。

⚠ **第一步永远是先证明这真是 vendor 的错**，不是我们喂错了。判据：跑一条完全不经我们
代码的路径复现（`roundtrip` 是二进制→对象图→二进制，不过 JSON；`dump`/`load` 过 JSON，
复现不了就说明锅在我们这层）。0005 就是这么定的：撤掉补丁后纯二进制路径 0/4 与原文件
相同，打上后 3/4——一个字节都没经过我们的代码，所以确凿是 vendor 写错。

## 已退役：0001 / 0007（2026-09-24，vendor bump 到 `1c2f92d`）

- **0001**（`args == 2` 分支把 2 参函数当运算符解析）：上游 `bf0e5e5` 删掉了那个分支。
- **0007**（操作码 0 和函数 20 都叫 `Pow`，dump/load 把 20 改写成 0）：上游把操作码 0 的
  文本形式改成中缀 `^`，撞名不复存在。原样本 `11_em0159_00_308.efx.5571972` 不打补丁
  `dump`->`load` 逐字节相同。

两个补丁文件已删除，编号不复用。当时的说明见 `KNOWN_UPSTREAM_ISSUES.md` #6 和第 11 节。

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

**追记（2026-09-17，用户实机测试）**：`unknWild1` 已确认是阻尼/阻力系数——给 0.5 粒子运动明显
变慢，给 1.0 粒子看不出运动。同一轮测试里，老字段 `ForceResist` 全语料 1104/1105 恒为 0.0（唯一
例外 0.2），改任意值实机也测不出效果，判定 MHWilds 下已废弃，语义被这个字段接管，故重命名为
`ForceResistWilds`。`unknWild10` 语义仍未知，字段名不动。改名不影响二进制布局（`RszAutoReadWrite`
按声明顺序/类型生成读写代码，不看字段名字符串），已重新跑过 `roundtrip` 确认无回归。

**追记 2（2026-09-17，用户实机测试，规模远超前两次，改动性质也变了）**：这轮不再是"类型精化"，
是**字段边界重新划分**——vendor 把 `AttractPosition`/`ForceScale`/`ReversalForceScale`/
`ReversalDistance`/`ForceResist` 以及 `unknWild3`~`unknWild6` 这几个 `via.Range`/`Vector3` 的
分界线全部画错了位置，实际的 Vector3/via.Range 边界比声明的边界晚半个字段到一整个字段不等。
证据链（全部来自实机、不是语料统计）：

- vendor 的 `AttractPosition`（首个 `Vector3`）改任意值实机测不出效果；`ForceScale.s/.r` +
  `ReversalForceScale.s`（本该是两个 `via.Range` 的前 3 个 float）单独改一维，能让粒子群精确
  朝 +X/+Y/+Z 偏移吸引目标点、且和 `AttractPosition` 效果相同可叠加——说明真正的局部偏移
  Vector3 在这三个字段上，vendor 声明的 `AttractPosition` 只有配合 `Flags` bit1(数值 1) 才会
  作为**另一个**、世界/固定参考系目标点分量生效，两者分别改名 `AttractPositionLocal`（恒开）
  / `AttractPositionWorld`（bit1 门控）。
- `ReversalForceScale.r`（实机振荡周期测试确认是弹簧力常数）+ `ReversalDistance.s`（实机确认
  双向对称随机 `[Static-x, Static+x]`，取 x/-x 效果相同，见 docs/PITFALLS.md #29）是真正的一对，
  但两者版本可用性不同（前者恒可用，后者 DD2+ 专属），**不能**合并成一个 `via.Range`（会在
  RE7RT/RE4 文件上错误读写字节），改成两个独立 float `ForceStatic`/`ForceBiRand`，各自保留
  原本的版本条件。`ReversalDistance.r` 语义未知，占位 `unkn1`。
- `unknWild3.s`/`.r` 是两个互不相关的独立量（不是一对），拆成两个 float：`.r` 实机确认是
  吸引力最大作用距离阈值（`-1`=无限制哨兵值），改名 `MaxAttractDistance`；`.s` 有明确效果
  （粒子群从球壳收缩成正八面体再收缩成十字）但模型未定，先占位 `unkn2` 不强行命名。
- `unknWild4`/`unknWild5`/`unknWild6` 三个 `via.Range`（6 个 float）的真实分组同样错位了半个
  `via.Range`：`unknWild4.s` 是独立的"死区半径"，改名 `MultZoneRadius`；`unknWild4.r`+
  `unknWild5.s` 是真正一对（区域内逐帧速度乘数），新声明 `via.Range ZoneVelocityMultiplier`；
  `unknWild5.r`+`unknWild6.s` 是另一对（疑似生成延迟），新声明 `via.Range SpawnDelay`；
  `unknWild6.r` 语义未知，占位 `unkn3`。这两对是否遵守标准 Static+Random 公式（`[s,s+r]`）
  还是像 `ForceBiRand` 那样是双向对称，尚未验证，别照搬。

**声明顺序即字节顺序，拆分时踩过一次坑**：`via.Range` 自身是 `{float s; float r;}`，`s` 在前、
`r` 在后——第一版把 `unknWild3.s`（未命名）和 `unknWild3.r`（`MaxAttractDistance`）的声明顺序
写反了，导致 `MaxAttractDistance` 实际读到的是 `.s` 的字节。靠 `fieldstats` 重新跑一遍、比对
"是否还有 -1 哨兵值"这个已知指纹发现的，改完顺序后指纹对上了才确认修好。**这类拆分改动光凭
"编译通过 + roundtrip 绿"不够**，必须拿改动前的字段级取值分布当基线，逐字段核对指纹没有错位。

**实测确认**：改动前后 `fieldstats` 扫到的实例数、文件数、失败数完全一致（1105 / 9175 / 46），
拆分后每个新字段的取值分布逐一比对旧字段名下的历史指纹（含上面提到的顺序 bug 修复前后两版）；
全语料 `roundtrip` 稳定/异常分布（9175 稳定 / 0 不稳定 / 46 异常）全程保持不变，无回归。

**追记 3（2026-09-17，用户实机测试）**：`unkn3`~`unknWild9` 这段实机测试显示是 `MultZoneRadius`
定义的胶囊形区域在做三轴延伸，`unknWild9.r`/`unknWild10` 都已确认是转角（`unknWild10` 绕全局
Y），用户怀疑三转角里的第三个可能藏在 `endwilds` 里——`endwilds` 全语料 1105/1105 恒为 0，之前
当成死字段占位用 `UndeterminedFieldType`。类型订正为 `float`（跟 `unknWild1`/`unknWild10` 那次
同样的位模式论证——两者都是 4 字节原样读写，改哪个类型都不丢字节），**但这次没有非零语料样本
能验证位模式是否真是干净小数**，纯粹是"结构位置紧挨着两个已确认的转角"这个旁证撑住的，比前两次
的证据弱，语义和数据类型的置信度不能混为一谈——字段名暂不改，等实机测出它是不是真的转角再定。
`unkn3`~`unknWild9` 那几对的分组/公式仍未验证，本次不动。已重新跑 `roundtrip` 确认无回归。

**追记 4（2026-09-17，用户实机测试，`endwilds` 确认+结构定型）**：`endwilds` 实机测试确认
就是角度，`unknWild9.r`/`unknWild10`/`endwilds` 三个连续 float 是一组角度（欧拉角）。原
`unknWild6.r`~`endwilds`（1 个独立 float + 3 个 via.Range + 1 个独立 float，共 8 个 float）
整体重新分组、按 `EFXAttributeEmitterShape3D` 的 `RangeX/Y/Z` + `Vector3 LocalRotation` 惯例
命名（加 `Shape` 前缀区分，这里不是 ES3D 本身）：

```
原 unknWild6.r + unknWild7.s  -> ShapeRangeX (via.Range)
原 unknWild7.r + unknWild8.s  -> ShapeRangeY (via.Range)
原 unknWild8.r + unknWild9.s  -> ShapeRangeZ (via.Range)
原 unknWild9.r/unknWild10/endwilds -> ShapeRotation (Vector3)
```

⚠ **命名对齐的是结构，不是已确认的语义**——实机测试发现给 `ShapeRangeX/Y/Z.s` 各设 1、
`Flags=8` 时，看到的是一个**始终正对摄像机**的正方形边框，角色自转不会带着它转，这不是
典型的世界/局部空间几何体该有的行为，这组参数到底是不是"定义一个物理空间形状"还没有最终
结论。语料里 `Flags=8` 从不单独出现（只见于 8/24/26，均带数值 16 那一位），疑似 16 是这套
参数自己的形状类型开关（类似 `EmitterShape3D.ShapeType`），待验证。三对 Range 各自的公式
（Static+Random/min-max/`ForceBiRand` 那种双向对称）、`ShapeRotation` 三轴的旋转顺序都还
没验证，只是先把结构定下来，方便继续测——跟前几次一样，**声明顺序必须和原本 s 在前、r 在后
的字节序对齐**，这次改完立刻用 `fieldstats` 逐字段核对了历史指纹，全部一次对上，没有再犯
`MaxAttractDistance` 那次的顺序错误。已重新跑 `roundtrip` 确认无回归。

**追记 5（2026-09-18）**：`unknWild3.s`（球壳收缩成正八面体/十字那个形状偏置字段，之前占位
`unkn2`）改名 `AttractAxisBias`。单粒子追踪确认轨迹是直线段，排除了之前怀疑的旋转/切向力
分量；具体是不是"XYZ 分量独立收缩、负值让粒子高速沿轴飞出"这个模型是用户推导出来的，不是
逐条单独实机验证过，命名先按这个推导定，语义置信度按"guess"记。至此 `EFXAttributeAttractor`
只剩 `unkn1`（原 `ReversalDistance.r`）没有名字。已重新跑 `roundtrip` 确认无回归。

## 怎么用

**vendor 是 submodule，工作区改动不会随 `git submodule update` 保留**——每次重新 checkout /
升级 vendor 之后都要重新打一遍：

```bash
git apply tools/vendor-patches/0002-efx-rszfixedsizearray-implicit-length-write.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0003-efx-opaque-unknown-attribute-types.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0004-efx-bonerelation-strainribbon-fluidsim.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0005-efx-inline-wstring-bytesize-fields.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0006-efx-attractor-unknwild-float-fields.patch --directory=vendor/RE-Engine-Lib
```

（`git apply` 认不出就说明补丁跟当前 vendor commit 对不上下文了，去对应源文件里手动照着补丁
内容改一遍，然后重新生成这个 patch 文件。）

## 什么时候可以删

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

**0006**：这个不是"上游修不修"的问题（本来就没错），只在上游自己把 `EFXAttributeAttractor`
的字段边界重新划分对、配了正式名字时才需要处理——那时大概率连字段数量和分组都不一样（不只是
改名），直接对照上游的类型定义重写整个字段列表，删掉这个文件，不需要"先确认没打补丁也一样"
这一步。
