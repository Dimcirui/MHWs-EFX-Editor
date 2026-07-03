# 已知上游（RE-Engine-Lib）问题跟踪

记录 `vendor/RE-Engine-Lib` 里发现的、不打算本地修的解析缺口。目的：升级 vendor commit 时，
对照这份清单重跑 `tools/EfxBridge`，看哪些已经被上游解决了，不用每次重新排查一遍。

当前锁定 commit：`52248353b07b97d8e67493f5ac3ce67ebc01e390`（2026-06-30）。
基准语料：`MHWILDS_EXTRACT/EFX` 官方文件，9241 个。

---

## #1 `Layout` attribute 解析失败（影响面最大，1232/9241 = 13.3%）

**症状**：
```
System.Exception: EFX attribute (Layout) was not properly read. Expected: 988 Actual: 4197 Start:4121 End:8314
```
`Expected` 与 `Actual` 差距巨大且始终是 `Actual > Expected`（读多了，不是读少）。

**受影响代码**：
- `REE-Lib/OtherFiles/EFX/EfxMiscStructs.cs` — `EFXAttributeLayout` 类，字段
  `layoutName`（`[RszInlineWString]`，条件 `(flags1 & (8|4|16)) != 0`）+
  `layoutDataFloats`（`[RszFixedSizeArray]`，**未传 size 参数**）。类上原有注释坦承：
  `// note: not 100% on the flag bits but most Wilds files seem to work with this`。
- `REE-Lib/FileHandler.cs` — `ReadWString(pos, charCount, jumpBack)` 方法。

**诊断过程**（详见项目发起会话）：
1. 抽样核对 `flags1`/`flags2`/字符串内容——两个失败样本 `flags1=31`，条件判断触发读取
   `layoutName`，解码出的字符串内容合法可读（如 "Layout38..."），**排除 flags1 位判断本身
   有问题**。
2. 定位到 `layoutDataFloats` 的 `[RszFixedSizeArray]` 没有传 size 表达式，生成器
   （`REE-Lib.Generators/ReeLibGenerator.cs`）在这种情况下的 fallback 是
   `size = "handler.Read<int>()"`——即"没告诉我多长，那我就读下一个 int 当元素个数"。
3. 进一步定位到 `FileHandler.ReadWString` 里，`jumpBack=false` 时游标最终定位公式是
   `originPos + result.Length * 2 + 2`——**按实际字符串内容长度（遇 `\0` 截断后）算，
   不是按调用方传入的 `charCount`（声明的缓冲区大小）算**。`layoutName` 声明 `charCount=32`
   （64 字节缓冲区），但字符串内容常远短于此，游标因此停在缓冲区中间，而不是声明的末尾。
   这会导致后续 `layoutDataFloats` 的 fallback "读下一个 int 当长度" 在错误的偏移上读到
   缓冲区内部的填充/垃圾字节，当成数组长度用，从而读多。

**把握程度**：`ReadWString` 的游标计算公式**静态读代码即可确认是错的**（定长缓冲区读取
理应按声明长度前进，不该按内容长度）——这一点置信度高。但**没有单步调试完整闭环验证**
"最终为什么正好是 4197 而不是别的数字"——手工十六进制反推中间一步没有对齐，可能是这条
fallback 路径实际触发的字节位置和推算的不完全一致。**结论：高度怀疑 `ReadWString` 是根因
之一，但未 100% 确认是唯一根因。**

**当前处置**：不在本地 fork 修（vendor 是 git submodule，本地改动会在后续升级时持续增加
维护负担，且这段代码本身作者已标注"not 100%"，大概率会被上游继续打磨）。改用运行时防御：
解析失败 = Blender 导入端直接拒绝该文件，见 [PLAN.md](PLAN.md) "解析失败处理原则"。

**复现样本**（`MHWILDS_EXTRACT/EFX` 相对路径）：
- `natives/STM/Art/VFX/EffectEditor/Stage/St405/11_st405_a00_002.efx.5571972`
  （Expected:990 Actual:10965 Start:1902 End:12863）
- `natives/STM/Art/VFX/EffectEditor/Stage/St405/11_st405_smoke_000.efx.5571972`
  （Expected:988 Actual:4197 Start:4121 End:8314）

**升级 vendor 后如何复核**：跑 `tools/EfxBridge roundtrip <语料目录>`，看异常分组里
`Layout` 那一行的数量是否降为 0（或大幅下降）。

---

## #2 `charCount ... too large`（41/9241）

字符串长度字段解析到不合理的巨大值（`FileHandler.ReadWString` 里 `charCount > 1024` 直接
抛异常的那个保护性检查命中）。未深入定位具体是哪个字段/attribute 类型触发，也可能和 #1
是同一类"游标算错位置"问题的另一种表现（跑偏到别的字段上，凑巧撞上了这个长度上限检查）。

**当前处置**：未调查，先记录。

---

## #3 `System.OverflowException: Arithmetic operation resulted in an overflow.`（6/9241）

未调查。

---

## #4 `Unsupported EFX attribute type PtColorMixerClip`（5/9241）+ 另外两个零散的类型映射缺失

`EfxAttributeType` 枚举里已经有 `PtColorMixerClip`，但 MHWs 的 itemType（整数）→枚举成员
映射表里没接上，属于纯粹的映射表遗漏，不是解析逻辑 bug。理论上是几个小样本里最容易修的一类
（对照 MHWs 其他已知 itemType 数值规律补一行映射即可），但目前也还没有去动。

**当前处置**：未调查，先记录。

---

## #5 其余零散 singleton（各 1 个样本）

- `EFX attribute (TypeGpuMeshTrail) was not properly read. Expected: 568 Actual: 572`
  ——差 4 字节，疑似漏了/多算了一个字段，和 #1 是不同的 bug（数值差距小、固定尺寸不匹配，
  不是"读到垃圾长度"的模式）。
- `System.NotImplementedException: Unhandled switch case` ——具体哪个 switch 未记录。
- `Unsupported EFX attribute type FixRandomGeneratorExpression` / `FluidParticle3DSimulatorExpression`
  ——同 #4，映射表遗漏。

**当前处置**：未调查，先记录。
