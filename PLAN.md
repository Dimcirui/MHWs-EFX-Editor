# MHWs-EFX-Editor — 计划

MHWs（Monster Hunter Wilds，RE Engine）`.efx` 特效文件的 Blender 编辑插件。
姊妹项目：[EFX-Editor](../EFX-Editor)（MHWI/MT Framework，独立仓库，互不依赖）。

## 定位

- **不追求做成 REE（RE Engine）通用工具**，只做 MHWs。这是权宜之计：有人比这个项目更懂 REE
  格式整体，但对方暂时没精力做，以后可能会做通用版；这个项目先满足"现在就想在 Blender 里编
  MHWs 特效"的需求，不与未来的通用版竞争定位。
- 后端（RE-Engine-Lib）本身是多游戏参数化的，这一点顺手保留、不刻意阉割，但 UI、测试语料、
  功能范围只对 MHWs 负责——不为假设中的 RE4/DMC5/MHRise 场景多花一分工。

## 架构决策（已锁定，讨论过程见项目发起会话）

1. **后端**：直接调用 [kagenocookie/RE-Engine-Lib](https://github.com/kagenocookie/RE-Engine-Lib)
   （C#/.NET 8，MIT），不重写 Python codec。理由：它的 EFX 解析是 RSZ 反射式序列化 + 逐字段
   `[RszVersion(...)]` 版本门控，MHWs 的字段 schema 93%+ 已具体类型化，且是活跃维护的真实读写
   对象模型（非字节补丁式）。
2. **Vendor 策略**：整个仓库以 git submodule 引入（`vendor/RE-Engine-Lib`），**不手工摘取
   `OtherFiles/EFX/` 子集**——EFX 的读写代码依赖编译期源代码生成器
   （`REE-Lib.Generators`，通过 `ProjectReference OutputItemType="Analyzer"` 引用）和核心
   `FileHandler`/`BaseModel` 基础设施，手工抽取源码风险远大于收益。最终产物体积由
   `dotnet publish` 的裁剪（trimming）在发布时自动收窄，不需要在源码层面预先瘦身。
   当前锁定 commit：`52248353b07b97d8e67493f5ac3ce67ebc01e390`（2026-06-30）。升级时手动
   bump + 跑一遍 Phase 0 回归，不追"永远最新"。
3. **数据交换**：Python（Blender 胶水层）↔ C# 桥接 CLI，走"文件 → 结构化中间表示 → 文件"的
   批处理调用模式（类比现有 import/export operator 的调用方式），不做常驻服务、不用 pythonnet
   内嵌 CLR（避免和 Blender 自带 Python 跨版本 3.6→5.x 的兼容负担叠加）。
4. **引用建模**：所有跨 entry/attribute 的引用字段，Blender 侧一律用 `PointerProperty` 指向
   对象（对象身份而非裸下标），从第一天就这样做。这与 C# 后端自身的模型一致
   （`List<EFXEntry>`/`IBoneRelationAttribute` 靠对象身份而非裸下标解析）。
5. **增删交互**：Body/Attribute 用独立 Blender Object（沿用 EFX-Editor 的 `~TYPE` 自定义属性
   标记范式）。整层删除引导用户使用 Blender 原生 Outliner "Delete Hierarchy"（天然递归，不需要
   自己写级联删除代码）。仅删父级导致的孤儿对象不做保护，靠导出时按 parent 链过滤 + 弹窗警告
   兜底（场景变脏是用户不当操作的责任，不是这个项目要堵的漏洞）。
6. **复制/预设**：不追求与 Blender 原生 duplicate 语义对齐，走面板内复制/粘贴/预设（复用
   EFX-Editor 已验证过的产品形态）。
7. **不做"脏/未编辑 verbatim 透传"二分**（EFX-Editor 因自研解析器不完备而必须做的代偿）
   ——前提是 Phase 0 验证 C# 后端读写本身就是 byte-perfect 的。
8. **Clip（对应 EFX-Editor 的 TIML）与 Expression（公式引擎）是两个独立子系统**，UI 分开设计：
   - Clip（`EfxClipData`：frame/value/插值类型/贝塞尔切线）—— 概念上与 TIML 同构，可复用
     TIML 编辑器的关键帧/F-curve 范式。
   - Expression（`EFXExpressionList`/`EFXExpressionData`：运算符树，按哈希引用具名参数）——
     全新子系统，MHWI 没有对应物，需要节点图/公式编辑器 UI。**这是 UI 功能完整度问题，不是
     字节安全问题**：C# schema 已把它建成结构化字段，即使 Blender UI 还没做编辑器，未触碰的
     Expression 数据也能被 C# 后端正确透传，不会因为 UI 不支持而损坏。可以放到后面阶段做，
     不卡其他功能上线。
9. **解析失败处理原则：拒绝导入，不做 best-effort 半解析**。C# 后端对某个文件/某个
   attribute 类型解析抛异常时（见 [KNOWN_UPSTREAM_ISSUES.md](KNOWN_UPSTREAM_ISSUES.md)），
   Blender 导入端必须整文件拒绝并明确报错告知用户"此文件暂不支持编辑"，**不允许**把异常
   吞掉后塞一个错误/半成品结构进 Blender 场景——错误结构一旦被用户在 Blender 里改动+导出，
   就是错上加错，且比"根本没导入"更难排查、更容易骗过用户以为是好的。这与 EFX-Editor（MHWI）
   "byte-perfect 是底线，拿不准就 opaque 兜底"的谨慎精神一致，但实现方式不同：MHWI 有能力做
   opaque 兜底（自己的解析器，能精确知道"这一块我不懂，原样存/原样吐出去"）；这个项目的解析
   完全外包给 C# 后端，后端解析失败时我们没有"退回 opaque"的手段（后端不是我们写的，插不了手
   到那个粒度），所以只能整文件拒绝，粒度更粗，但安全性质是一样的。
   随 vendor commit 升级、上游修复问题后，之前被拒绝的文件会自动变得可导入，不需要额外代码
   改动。

## 阶段路线

### Phase 0 — C# 后端往返稳定性验证（已完成第一轮，结论：架构可行）

**目标**：验证第 7 点的前提——RE-Engine-Lib 对真实 MHWs `.efx` 文件的读写是否可信到可以
"不做脏标志、每次导出全量重算"。不碰 Blender、不碰 Python。

工具：[`tools/EfxBridge`](tools/EfxBridge)（.NET 8 控制台程序，引用 vendor 的 `REE-Lib.csproj`）。

```
dotnet build tools/EfxBridge -p:LangVersion=preview   # vendor 用了 C# 13 field 关键字，需要 preview
dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll roundtrip <MHWs .efx 样本目录> [--verbose] [--dump <目录>]
```

**验证标准的一次修正**：最初按"与原文件逐字节相同"判定，语料库（9241 个官方文件，
`MHWILDS_EXTRACT/EFX`）实测通过率仅 57%。抽样发现失败并非丢数据，而是 RE-Engine-Lib
的设计哲学是"解码成对象模型后总重新生成"而非"保留原字节"——例如 `CollisionEffect.efxEntryIndex[]`
原文件是任意顺序，重建后按 entry 下标重新排序，语义等价但字节不同。因为有 REFramework/TDB
反射作支撑，这套解码是成体系的、值得信任的，不是瞎猜字节布局，所以改用更贴合编辑器场景的
判据：**二次往返稳定性**——`原文件→读→写bytes1→读→写bytes2`，判据是 `bytes1==bytes2`
（读它刚写出来的东西再写一遍，必须完全一样，保证"没有编辑也不会一存再存越漂越远"）。

**实测结果（9241 个官方样本，2026-07-02）**：

| 判据 | 数量 | 占比 |
|---|---|---|
| 稳定（bytes1==bytes2） | 7950 | 86.0% |
| 异常（解析/回写抛错） | 1291 | 14.0% |
| 不稳定（bytes1≠bytes2） | 0 | 0% |

**不稳定为 0 是最重要的信号**：目前没能过关的文件全部是"解析失败"（异常），
一旦能解析成功，重建结果就是确定性的——第 7 点"不做脏标志"的前提站得住。

异常按类型归类（首行信息，数字归一化）：

| 数量 | 异常 |
|---|---|
| 1232 | `EFX attribute (Layout) was not properly read` —— 单一 schema 尺寸 bug，占异常总数 95.4% |
| 41 | `charCount ... too large` —— 字符串长度字段解析错位 |
| 6 | `OverflowException` |
| 5 | `Unsupported EFX attribute type PtColorMixerClip` —— itemType→枚举映射缺失 |
| 3 | `TypeLightningExpensive` 尺寸不匹配 |
| 4 | 其余零散 singleton（`TypeGpuMeshTrail` 尺寸差 4 字节 / `Unhandled switch case` /
    两个类型映射缺失） |

**结论**：`Layout` 这一个 bug 修好，预期通过率能从 86.0% 冲到约 99.4%
（(7950+1232)/9241）。这是目前性价比最高的单点——值得考虑直接修复并回馈上游
（MIT 协议，PR 对未来可能出现的"通用版 REE 工具"也有好处，不冲突）。

**决策（已定）**：不本地修 vendor 代码（fork 会在升级时持续增加维护负担），已排查的问题
记录在 [KNOWN_UPSTREAM_ISSUES.md](KNOWN_UPSTREAM_ISSUES.md)，升级 vendor commit 时对照复核。
异常样本的处理方式见架构决策第 9 点（拒绝导入，不做半成品解析）。当前可以进入 Phase 1。

### Phase 1+ — 待 Phase 0 通过后再定

暂不展开，避免在验证核心前提之前过度设计。大致方向：
- 若 Phase 0 通过：设计 Python↔C# 的 JSON 交换协议（复用 `efx_structs.json` 的 schema 描述做
  Blender 侧的通用属性面板），搭 Blender addon 骨架，实现最小可用的「导入→查看单个 attribute
  字段→导出」闭环。
- 若 Phase 0 发现系统性失败：按失败模式决定是"绕过该字段类型"还是"重新评估整个架构"。

**前瞻性备注（不影响当前阶段，仅为将来铺路）**：姊妹项目 EFX-Editor（MHWI）正在设计一套
"字段语义知识表"（把 label/tooltip/官方名等展示层语义从 `.py` 表搬到外部 JSON，让非程序员
测试者也能填写、不用碰代码），详见该仓库 `PROGRESS.md` "语义知识解耦" 一节。到 Phase 1 做
Blender 通用属性面板时，本项目会遇到同样的问题（RE-Engine-Lib schema 里大量字段语义未知，
需要实测标注）。届时若复用同一套设计，**在字段知识表格式里从第一天就带上游戏命名空间**
（如顶层 `"game": "MHWS"` 或按游戏分文件），使两个项目的测试者工作流、校验器、"填写含义"
弹窗代码可以直接共享，不需要各自另起一套。现在不需要做任何事，只是设计到时候留这个口子。

## 目录结构

```
MHWs-EFX-Editor/
  vendor/RE-Engine-Lib/       — git submodule，锁定 commit，见上文
  tools/EfxBridge/            — Phase 0 验证工具（.NET 控制台程序）
  PLAN.md                     — 本文件
  KNOWN_UPSTREAM_ISSUES.md    — 已知上游解析缺口跟踪，升级 vendor 时对照复核
```

Blender 插件本体（`blender_efx_re/` 或类似）尚未创建，留到 Phase 1。
