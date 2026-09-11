# vendor-patches

`vendor/RE-Engine-Lib` 默认铁律是不改源码（CLAUDE.md #5）——发现的缺陷记 `KNOWN_UPSTREAM_ISSUES.md`，
能绕就在 `tools/EfxBridge/Program.cs` 里绕。这个目录放的是**例外**：绕不开、又足够小、足够有
把握的补丁，才收在这里。别把这当成绕开铁律 #5 的旁路——新增前先确认真的够小、够有把握。

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

## 怎么用

**vendor 是 submodule，工作区改动不会随 `git submodule update` 保留**——每次重新 checkout /
升级 vendor 之后都要重新打一遍：

```bash
git apply tools/vendor-patches/0001-efx-expression-func18-19-20-args2-dispatch.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0002-efx-rszfixedsizearray-implicit-length-write.patch --directory=vendor/RE-Engine-Lib
git apply tools/vendor-patches/0003-efx-opaque-unknown-attribute-types.patch --directory=vendor/RE-Engine-Lib
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
