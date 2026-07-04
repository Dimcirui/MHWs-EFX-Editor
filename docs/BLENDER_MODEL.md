# MHWs EFX — Blender 对象模型实现笔记

从 [PLAN.md](../PLAN.md) 拆出来的专题文档，记录 `~TYPE` 对象模型（`model.py`/`io_tree.py`/
`operators.py`/`panels.py`/`copy_paste.py`/`semantics/`）在真实 Blender 里的验证过程、
过程中修的 bug、面板 UX 打磨、以及字段语义知识表的实现细节。这是"这个插件目前长什么样、
为什么长这样"的施工记录，设计层面的顶层数据结构结论见 [TOPLEVEL_STRUCTURE.md](TOPLEVEL_STRUCTURE.md)。

## Phase 1 补充 —— Blender 实机验证（2026-07-03，Blender 5.1.2，via Blender MCP）

此前 `~TYPE` 对象模型的代码（`model.py`/`io_tree.py`）只做过静态审查，从未在真实 Blender 里跑过
（仓库环境本身没装 Blender）。这次用 Blender MCP 连到一个真实运行的 Blender 5.1.2 实例，跑了
plan 里排定的验证项：注册插件、import 两个 `diag/` 样本、检查对象树计数/嵌套关系、内容级
往返一致性比对、编辑字段、加 Group 标签、走真实 operator（`bpy.ops.efx_re.export`）触发拒绝
路径。过程中发现并修复了 3 个真实 bug（均已实测复核，不是猜测）：

1. **`EFXValueNode.children` 递归属性从未真正注册**（`model.py`）。原写法
   `EFXValueNode.children = CollectionProperty(type=EFXValueNode)` 是普通类属性赋值，
   `bpy.utils.register_class` 只扫描 `__annotations__` 来决定注册哪些 RNA 属性，普通赋值
   不会进 `__annotations__`，导致 `.children` 永远停留在 `_PropertyDeferred` 占位对象上——
   任何嵌套 OBJECT/ARRAY 字段（例如 `Vector3`/`via.Range` 这类真正嵌套的 JSON 值）一填就
   `AttributeError: '_PropertyDeferred' object has no attribute 'add'`。修复：改成
   `EFXValueNode.__annotations__["children"] = CollectionProperty(type=EFXValueNode)`。
2. **导出 attribute 字典时 `$type` 键顺序错误**（`io_tree.py`）。原代码先塞内容字段、
   最后才 `attr_dict["$type"] = ...`，Python dict 保序意味着 JSON 里 `$type` 排在其他字段
   后面。C# 侧 `EfxJsonTypeResolver` 是流式读取判别多态类型，不像 .NET 内置
   `[JsonPolymorphic]` 那样会缓冲整个对象重放——`$type` 不在第一位会导致直接退回抽象基类
   `EFXAttribute`（无参构造函数），抛 `NotSupportedException`。修复：`$type` 改成
   attr_dict 的第一个键。
3. **Entry 的 `index` 字段被导出时强制按数组位置重算，且这个假设是错的**（`model.py`+
   `io_tree.py`）。原注释假设"这个字段本该等于数组下标，只有删除 Entry 后才会错位，所以导出
   时按当前顺序重新赋值"——用 `11_guide_110` 实测证伪：其 11 个顶层 Entries 的原始 `index`
   值是 `{1,32,28,29,27,33,10,9,8,7,31}`，与数组位置 0-10 完全不对应；反而是
   `EffectGroups.efxEntryIndexes`（如 `[9,8,7,6,3,2,1,4,5]`）才是真正按数组位置引用。也就是
   说 `index` 是某种独立于数组位置的标识（语义未知，推测是权威制作工具的创建序号），强行按
   位置重算会在**完全没有编辑的往返**里就篡改这个字段。修复：`index` 改为和其余未知字段一样
   原样透传（从 `ENTRY_STRUCTURAL_KEYS` 移除），不在导出时重算。删除 Entry 后 `index` 要不要
   重新分配，等确认真实语义后再决定。大样本层面的进一步验证见
   [TOPLEVEL_STRUCTURE.md](TOPLEVEL_STRUCTURE.md) 的 cross-reference 一节。

修复后的验证结果：
- `guide_110`（11 Entries + 2 Actions，含 2 层嵌套 `PlayEmitter.efxrData`）与 `guide_006`
  （7 Entries，无 Action）均能正常 import，对象树计数、`~TYPE` 分布、`PlayEmitter` 的嵌套
  `EFX_ROOT` parent 关系（挂在 attribute 对象上，不是 PointerProperty）与顶层结构结论完全
  一致；Blender 对同名 Attribute 对象（如两个 Action 各自的 `PlayEmitter`）的自动去重命名
  （`PlayEmitter`/`PlayEmitter.001`）不影响 parent 链，纯展示层面。
- 内容级往返（Blender 树 -> 重新导出成 dict，不经过 C# 写入）与原始 dump 深度比较：
  `guide_006` 完全零差异；`guide_110` 唯一差异是刻意设计的 `EffectGroups: [] `（导出时清空，
  交给 C# 后端从 Groups 反推重建）。浮点数在 JSON 文本上的显示差异（如 `1.2` vs
  `1.2000000476837158`）是 Blender `FloatProperty` 单精度存储再转 Python 双精度显示的正常
  现象，不是精度丢失。
- 编辑 `efx_fields` 里的标量字段、增删 `efx_groups` 标签，改动能正确反映到重新导出的 dict。
- 两个样本每个 Entry 都带非空 Expression 数据，触发了已知遗留缺口（`EFXExpressionDataBase`
  反序列化不支持，见 `bridge.py` 顶部注释），走真实 `bpy.ops.efx_re.export` 触发时验证了
  拒绝路径按架构决策 9 正确工作：`BridgeError` 被捕获、operator 报 `{"ERROR"}` 并返回
  `{"CANCELLED"}`，磁盘上不会留下部分写入的 `.efx` 文件。**真正的字节级往返稳定性
  （write→read→write→比较字节）暂时无法用现有两个样本验证**——两个样本的每个 Entry 都带
  Expression，这个子系统的写入路径本就不支持（架构决策 8 已预期，不在这次修复范围）。
  曾尝试把 Expression 字段整体置空来绕过验证纯 Blender 管线，但这会触发 C# 写入端一个不同的
  问题（写出的字节在下一次读回时报 `Unknown EFX attribute type`）——这是给后端喂了一个它没
  设计要处理的"人为置空"输入形状，不代表真实使用场景，没有继续深挖，等有不含 Expression 的
  真实样本再补这一项验证。

## Phase 1 补充 —— 字段语义知识表（2026-07-04）

上面这一轮 cross-reference（见 [TOPLEVEL_STRUCTURE.md](TOPLEVEL_STRUCTURE.md)）暴露出一个
更根本的问题：面板目前直接把 JSON 键名（`unkn15`/`re4_unkn1` 这类）糊在 UI 上给用户看，即使
以后深挖出了真实语义也没地方放。参照姊妹项目 EFX-Editor 已经设计好、但"未排期"的"语义知识
解耦"方案（该仓库 `PROGRESS.md`），做了一个缩小版：EFX-Editor 面对的是按类型拍平的
`structs.py`（67 类型、6 处要同步改），本项目字段树是通用递归的 `EFXValueNode`（见
`model.py`），所以只搬运原设计的 A 层（纯展示：label/tooltip/confidence，改错零风险），不
牵扯 B/C 层（TIML 轨道语义、字节布局）——那两层本来就不适用于我们的字段模型。

**实现**（`blender_efx_re/semantics/`）：
- `mhws_field_labels.json`：出厂默认表，顶层 `"game": "MHWS"`（为将来这套设计如果被 EFX-Editor
  复用、需要按游戏区分表内容留的口子），记录单元是
  `fields[$type][字段 key] -> {label_zh, tooltip_zh, confidence, evidence, tester, date}`，
  另有一个当前为空的 `global_fields`（跨类型通用词回退表，键仅为字段 key，留给以后
  `accel` 这类词用）。**只在"attribute `$type` + 顶层内容字段 key"这一级生效**，不索引更深
  的子字段——Vector 类型的 `x`/`y`/`z` 这类子字段名字本身已经够自解释，不值得为它们建索引。
- `__init__.py`：加载器，出厂表 + 用户个人标注表（Blender 用户配置目录下，弹窗写入这一半还
  没做）按 `(attr_type, field_key)` 合并、用户表优先；解析防御式，坏文件/坏格式只打印警告
  跳过，不向上抛异常——这张表只影响面板展示文字，不该拖垮导入/导出这些真正的 IO 路径。两层
  存储从第一天就做（不是留到以后），因为 EFX-Editor 的教训是"标注文件和插件代码放一起，插件
  升级时会被整体覆盖"——这个坑必须在打地基阶段就避开，不能后补。
- `panels.py`：`draw_node()` 现在按 `(attr_type, key)` 查表，查到就把 `label_zh` 当显示文字、
  并且用一个占位 operator（`EFX_OT_field_info`，点击不做任何事）承载 tooltip——因为
  `UILayout.label()` 本身不支持 tooltip，Blender operator 的 `description()` classmethod
  支持根据传入属性动态生成 tooltip 文本，是常见的绕过手法。查不到表就照旧显示原始 JSON
  键名，不影响任何未标注字段的可用性。

**出厂表种子数据**：只种了 `EFXAttributeParentOptions`（`RelationPos`/`RelationRot`/
`RelationScl`/`ParticleUseLocal`/`ConstInheritRate`/`ConstFrame`）6 个字段，来源是 010 模板
`RE_EFX_STRUCTS.btx` 里的中文注释——选这个类型是因为它是这次 cross-reference 里少数有实质注释
内容的类型（该结构体本身在模板里标记为 `//unconfirmed`，所以全部标了 `confidence: "guess"`），
用真实数据而不是占位符跑通整条链路。**没有做全部 238 个 attribute 类型的扫描**（不在当次
cross-reference 范围内，且当前不是优先级），后续按需逐步补充。

**实机验证（Blender 5.1.2，via Blender MCP）**：import `diag/11_guide_006.efx.5571972.orig`，
选中其中一个 `ParentOptions` attribute 对象，面板正确显示中文标签+问号图标（有知识表条目的
字段）与原始键名（没有条目的字段，如 `ParentBone`/`ParticleUseLocal_re7`，回退逻辑按预期工作）
并存；`EFX_OT_field_info.description()` classmethod 用真实/空 `tooltip_text` 分别验证过，
返回值符合预期（有内容显示内容，空文本回退到"（此字段暂无标注）"）。

**尚未做**：面板内"填写此字段含义"弹窗（非程序员主入口，写用户个人标注文件）、"导出我的
标注"按钮（回流给维护者合并进出厂表的路径）、`Reload semantics` operator（改完 JSON 不用
重启 Blender）、`tools/check_semantics.py` 校验器（EFX-Editor 那边配套的键存在性/枚举取值
合法性检查，本项目目前表很小，先手动保证正确性）。目前优先级较低（语义标注不是当前重点，
详见 PLAN.md 当前阶段重心）。

## Phase 1 补充 —— 面板 UX 打磨（2026-07-04）

用户实测面板后提的四点反馈，逐一处理：

1. **`via.Color` 字段改画成颜色轮**。查 vendor 源码（`RszValueType.cs:316` 的
   `via.Color`）确认了一个关键细节：R/G/B/A 在 C# 端是 `[JsonIgnore]` 计算属性，**不会出现在
   JSON 里**，真正落盘/dump 出来的只有一个打包 `uint32` 字段 `rgba`（`R | G<<8 | B<<16 |
   A<<24`）——所以颜色字段在我们的字段树里长得是 `{"rgba": 4278190080}`（唯一子键），不是
   用户猜测的 `[R,G,B,A]` 四个独立字段。检测逻辑（`model.is_rgba_color_node()`）按这个真实
   形状识别：OBJECT 节点、唯一子节点、键名是 `"rgba"`。渲染用 `EFXValueNode.color_value`
   （`FloatVectorProperty(subtype="COLOR", size=4)`，get/set 直接读写那个 `rgba` 子节点的
   打包整数，不额外存副本，字段树仍是唯一数据源，导出不受影响）。实机验证：把一个真实
   `color0` 字段（`ShaderSettings` attribute）设成半透明红色，读回、导出，打包整数
   `0x800000ff`（R=255/G=0/B=0/A=128）与设置的 `(1,0,0,0.5)` 完全对应，面板上也确认渲染出了
   带透明度棋盘格的红色色块（不是一个巨大整数或四行 float）。
2. **字段分组/分类展示——只回答，不在当轮实现**（用户明确说了不用现在做）：可行，且不难。
   两条路线：（a）纯展示层方案——在字段语义知识表里加一个可选的 `group` 键（如
   `{"group": "Position/Rotation/Scale"}`），`panels.py` 按 `group` 把同一 attribute 的顶层
   字段收拢进几个可折叠 box 再画，查不到 `group` 的字段退回现在的"平铺+知识表标签"逻辑，
   完全不用碰 `model.py`/`io_tree.py`/导出逻辑（分组信息只影响展示顺序，不改变数据结构，
   风险和"字段语义知识表"这条 A 层功能一样低）；（b）更彻底的方案——像 EFX-Editor 那样为
   每个 attribute 类型定义一份"字段展示顺序 + 分组"表，但考虑到本项目字段树是通用递归的
   （不像 EFX-Editor 有拍平过的 `structs.py`），做成硬编码表的性价比不如方案（a）灵活。
   推荐方案（a）：复用已经在跑的知识表基础设施，加一个字段、改几行 `draw_node` 分组逻辑
   即可，不需要新的存储层或迁移。**方案（b）的一个具体子集（XYZ/Static-Random 这两种"字段
   自身结构"的并排列布局）已经落地**，见下一节。
3. **Entry 改名 + attribute 对象加 `[父对象名]` 前缀防止 Outliner 里一堆 `.001`**。
   命名跟随 RE-Engine-Lib 实际类名（`EFXEntry`/`Entries`）而不是 EFX-Editor（MHWI）的 Body——
   `TYPE_BODY`→`TYPE_ENTRY`、`BODY_STRUCTURAL_KEYS`→`ENTRY_STRUCTURAL_KEYS`、
   `build_body_object`→`build_entry_object`、`export_body_object`→`export_entry_object`，
   相关注释/面板文案同步。Attribute 对象名从裸类型名（`UnitCulling`）改成
   `f"[{parent_obj.name}] {short_name}"`（如 `[Root] UnitCulling`）——**这个前缀同时套用在
   Entry 和 Action 两种父对象上**，没有把范围限制在用户原话提到的"Entry 的 block"：因为
   上一轮实机验证时真实撞到的那次 `.001` 碰撞（两个不同 Action 各自的 `PlayEmitter`
   attribute）恰恰发生在 Action 层，只给 Entry 加前缀不给 Action 加的话，这个已知碰撞不会
   被修好，两边用同一个 `build_attribute_object()` 函数、行为不一致也说不过去，所以扩大到
   两种父对象统一处理。实机验证：同一个样本（`11_guide_110`）两个 Action 各自的
   `PlayEmitter` 现在分别叫 `[Action0] PlayEmitter`/`[Action] PlayEmitter`，不再触发 Blender
   的 `.001` 去重后缀；导出侧不依赖对象名（靠 parent 链 + `efx_index`），改名不影响往返。
4. **侧栏分类 `bl_category` 从 `"EFX"` 改成 `"Wilds EFX"`**，避免和姊妹项目 EFX-Editor
   （MHWI）如果将来也叫 `"EFX"` 时在 Blender 侧栏里混在一个 tab 下（两边字段/对象模型完全
   不兼容，混在一起会造成用户误操作）。`EFX_PT_main`/`EFX_PT_object` 两处都改了，面板
   `bl_label`（"MHWs EFX"/"EFX Object"）本身已经够区分，未改动。

**顺带修的一个真 bug（实机截图时意外发现，不在用户这四点反馈里）**：`Saturation`
（`ShaderSettings` attribute 的一个真实、语义明确的字段名）在 Blender 中文界面下被自动渲染成
"饱和度"——不是知识表标注的结果（知识表里根本没有这条），是 `layout.label()`/
`layout.operator()` 默认 `translate=True`，Blender 自带的界面翻译表里恰好收录了
"Saturation"这个词（颜色管理相关的常见 UI 术语），字符串完全匹配就被静默替换。这个问题不
只影响这一个字段——任何原始 JSON 键名或知识表标签只要精确撞上 Blender 内置词条就会被换成
可能不相关的翻译，看起来像是"我们标注的"但实际上是巧合、且未来可能替换成完全不对应当前
语义的词。修复：`_draw_label()`、`EFX_PT_object.draw()` 里显示 `obj.name`/`obj.efx_attr_type`
的地方都传了 `translate=False`。实机验证：同一个 `Saturation` 字段改前显示"饱和度"，改后
正确显示英文原名 `Saturation`。

## Phase 1 补充 —— XYZ / Static-Random 并排列布局（2026-07-04）

上一节末尾"回答但不实现"的字段分组问题，用户当场明确了两个具体形状，随即实现：

1. **XYZ 三分量对象画成一行三列**，不再是"3 items"折叠框。检测逻辑
   （`model.xyz_child_order()`）按真实序列化形状识别：OBJECT 节点、恰好 3 个子节点、键名
   集合是 `{x,y,z}`（vendor `PaddedVec3`/`Int3` 等）或 `{X,Y,Z}`（`Vector3`）之一——两种
   大小写都存在于真实样本里（如 `RelationPos` 用小写、`Center`/`LocalRotation` 用大写），
   按各自原始大小写画列标签，不强行统一。对齐姊妹项目 EFX-Editor 的展示习惯
   （`panels.py` 的 FLOAT3/INT3 分支：标题行 + 一行三个 `prop(..., text="X")` 内联短标签）。
2. **`via.Range{s,r}` 对象画成一行两列**，标签用 **Static/Random**（`s`/`r` 各自对应）——
   最初按用户原话记成了 Value/Jitter（姊妹项目 EFX-Editor/MHWI 社区习惯用的措辞），用户随后
   订正：应该用 REE（RE-Engine-Lib）惯例命名 Static/Random，原因是这套命名以后计划回哺到
   EFX-Editor，统一方向是"MHWI 那边改用 REE 命名"而不是反过来，所以本项目从一开始就该用
   REE 这一套。文字/函数名都已改（`Value`→`Static`、`Jitter`→`Random`，函数名
   `is_solid_random_node`→`is_static_random_node`，`s`=solid 的说法也订正成了
   `s`=static）。检测逻辑：OBJECT 节点、恰好 2 个子节点、键名集合是 `{s,r}`。

两处都不新增存储、不改变字段树结构——纯展示分支，`_draw_scalar_prop()` 复用了原本单行标量
绘制的逻辑（只是多传一个内联 `text=` 短标签），导出路径完全不受影响。

**实机验证（Blender 5.1.2，via Blender MCP）**：`11_guide_006` 的 `UnitCulling` attribute
（`Center`/`Size`/`Rotation`，均为大写 `{X,Y,Z}`）正确画成三列；`EmitterShape3D` attribute
（`RangeX/Y/Z`、`ScaleHorizontal`、`ScaleVertical`，均为 `{s,r}`）正确画成 Static/Random 两列，
`LocalRotation`（`{X,Y,Z}`）同一张截图里同时验证了三列布局（改名前截图，措辞是当时的
Value/Jitter，逻辑和布局本身不受这次改名影响）。往返正确性：通过
`export_attribute_object()` 复核过对这些字段的编辑能正确回写（调试过程中一次误操作——
测试脚本对一个恰好取值为整数 `0` 的字段直接写了 `float_value`——暴露的是
`EFXValueNode`"按 JSON 字面量形状推断 int/float"这个通用机制早就有的行为，不是本轮改动引入
的新问题：面板本身画的是 `node.data_type` 对应的正确控件，用户从面板编辑不会踩这个坑；
只有绕过面板直接写错 slot 才会复现。已知限制，记在这里备查，暂不处理——要修就要在"要不要给
特定 attribute 类型的已知浮点字段提前定型"这个更大的设计问题上做决定，这与 model.py 文档里
"不为每个类型建 schema，靠 JSON 形状推断"的既有设计取舍冲突，不在这轮顺手改。

## Phase 1 补充 —— Entry/Attribute 复制粘贴（2026-07-04）

架构决策 6 说的是"复制/预设"两件事，用户明确了预设先不做，复制/粘贴够用——这一节只做后者。
新增模块 `blender_efx_re/copy_paste.py`，四个 operator：`efx_re.entry_copy`/`entry_paste`、
`efx_re.attribute_copy`/`attribute_paste`。

**实现思路（比预想的简单，原因是复用了既有的对称性）**：`export_entry_object()`/
`export_attribute_object()` 产出的 dict 形状，本来就是 `build_entry_object()`/
`build_attribute_object()` 消费的输入形状——两者是一对反函数，import/export 路径早就验证过
（上面几节的实机验证），复制/粘贴不需要另写序列化代码，只需要解决两个新问题：

1. **剪贴板载体**：用 Blender 系统剪贴板（`window_manager.clipboard`，一个受 OS 剪贴板支持
   的字符串），存 `{"__mhws_efx_clip__": "mhws_efx_entry"/"mhws_efx_attribute", "data": {...}}`
   这样一个 JSON 信封——marker 字段用来在粘贴时校验剪贴板内容确实是这个插件、这个类型的
   数据，不是用户从别处复制的无关文本（比如不小心复制了一段普通文字后点 Paste，`poll()`
   直接不通过，不会尝试解析报错）。选系统剪贴板不选 `bpy.data.texts`（后者是这个项目里
   opaque 字段已经在用的存储方式）是因为它顺带天然支持跨 `.blend` 文件粘贴，不需要额外
   代码。
2. **粘贴目标定位**：
   - Paste Entry：从当前选中对象往 parent 链上找 `EFX_ROOT`（新增
     `io_tree.find_root()`，从 operators.py 里原来的私有 `_find_root()` 提升成公开函数，
     两处共用），再用新增的 `io_tree.root_collections()`（按 `own_collection.children[0]`/
     `[1]` 的固定链接顺序取 main/actions 两个子 collection，不靠名字匹配——Collection 和
     Object 各自的去重命名空间是独立的，两者撞名后缀不保证同步）拿到 Entry 该链接进哪个
     collection。选中 `EFX_ROOT` 本身、`EFX_ENTRY`、`EFX_ACTION`、`EFX_ATTRIBUTE`
     中的任意一个都能定位到同一个 root，所以 Paste Entry 按钮在 Root 面板和 Entry 面板上
     都会出现。
   - Paste Attribute：选中 Entry/Action 时粘贴为它的新子 attribute；选中 Attribute 时粘贴
     为它的兄弟（取它的 `parent`）——两种都支持，省得用户每次先手动点回父对象。
   - 新对象的 `efx_index`（决定导出顺序）取"当前同类型兄弟对象里最大值 + 1"，新对象排在
     最后，不影响原有顺序；这是复制/粘贴路径里唯一需要新写的排序逻辑（`_next_index()`）。
     复制一个 Entry 时它自己的 Attributes 会在粘贴时被 `build_entry_object()` 内部的
     `enumerate()` 重新分配 0..n-1 下标，不会带着原 Entry 的下标混进来。
   - 顺带把 `io_tree.py` 原来的私有 `_typed_children()` 也提升成公开的 `typed_children()`
     （复制粘贴要用它找兄弟、算新下标）。

**实机验证（Blender 5.1.2，via Blender MCP）**：`11_guide_006` 的 `Root` Entry（含 2 个
Attribute）复制后粘贴成 `Root.001`——`export_entry_object()` 对原对象和粘贴出的新对象产出的
dict **完全相等**（除了 Blender 对象名因去重多了 `.001`，这不影响导出内容），efx_index
正确排到末尾（7）。`[Root] UnitCulling` attribute 复制后：（a）粘贴到另一个 Entry
（`start_middle`）上，正确追加为它的第 18 个 attribute（原有 17 个 index 不变）；（b）再次
粘贴、这次是选中刚粘贴出的 attribute（而不是它的父 Entry）执行 Paste，正确识别出应该粘贴成
它的兄弟，变成第 19 个 attribute。全部经过之后 `export_root_to_efxfile()` 能正常产出结构
完整的字典（往返到真实 `.efx` 字节这一步仍然受这个样本本身带 Expression 数据的限制，属于
已知的、和这次改动无关的上游缺口，见上文"Blender 实机验证"一节）。也验证过失败路径：剪贴板
是无关文本、或者选中了不相关类型的对象（如 Camera）时，对应按钮的 `poll()` 正确返回 False
（按钮置灰），不会尝试解析或崩溃。

**已知限制**：复制一个 Entry/Attribute 时，游戏侧的 `name`/`nameHash` 等字段（存在 opaque
数据里）原样带过去，粘贴后的对象在 Outliner 里靠 Blender 自己的 `.001` 去重后缀区分，但
游戏侧数据本身目前没有 UI 能重新编辑成不一样的值——这是既有的"opaque 字段没有编辑 UI"设计
边界，复制/粘贴没有让它变得更好也没有变得更差，等以后要给这些字段建编辑 UI 时一起解决。

## Phase 1 补充 —— Bones / BoneRelations 编辑 UI（2026-07-04）

结构调研见 [TOPLEVEL_STRUCTURE.md](TOPLEVEL_STRUCTURE.md)"Bones / BoneRelations 结构调研"
一节；这里记录 Blender 侧怎么落地。用户明确了当前策略：骨骼在游戏里到底怎么工作还没搞清楚
（等用户或朋友继续研究），所以**只做强制手动维护，不做"自动补齐缺失骨骼"的便利按钮**——
校验失败就直接拒绝导出，把决定权留给用户。

**数据模型**（`model.py`）：
- 新增 `EFXBoneItem`（`name` + `value` 两个字段）。`value` 语义未知，按"结构性 UI 先做，
  标注后补"存成十进制字符串而不是 `IntProperty`——vendor 是 `uint32`，`IntProperty` 是有符号
  32 位，字符串存全量精度，避免真遇到高位字段被截断，思路和 `EFXValueNode` 的 BIGINT 处理
  一致。
- `ROOT_STRUCTURAL_KEYS` 加入 `Bones`/`BoneRelations`：`Bones` 建 UI（`EFX_ROOT.efx_bones`
  collection），`BoneRelations` 和 `EffectGroups` 同一个模式——导出时固定给空数组，交给 C#
  后端从各 attribute 当前的 `ParentBone` 反查重建下标（`EfxFile.cs:982-989` 已确认）。
- 新增 `is_bone_reference_field()`：纯结构判断（`node.key == "ParentBone"`），不维护一份
  硬编码的 attribute 类型清单——`ParentBone` 是 C# 接口 `IBoneRelationAttribute` 统一定义的
  属性名，任何实现了这个接口的 attribute 在 JSON 里都会出现这个键，vendor 升级新增实现类
  时这里不用跟着改代码。

**Import/Export**（`io_tree.py`）：
- `build_root_from_efxfile()` 从 `Bones` 数组填 `efx_bones`；`export_root_to_efxfile()` 从
  `efx_bones` 反填 `Bones`，`BoneRelations` 固定 `[]`。
- `build_attribute_object()` 新增一步规整：`ParentBone` 是 `null`（无绑定）时改存成空字符串
  `""`——C# 写出逻辑用 `string.IsNullOrEmpty(ParentBone)` 判断"无父骨骼"，`null`/`""`
  语义完全等价，但 `EFXValueNode` 的 `NULL` data_type 没有可编辑的 slot（画不出
  `prop_search`），所以统一转成可编辑的 `STRING` 空值，导出行为不变。
- 新增 `check_bone_references()`：导出前扫描顶层文件自己 Entries/Actions 下每个 attribute 的
  `ParentBone`，非空就必须能在 `efx_bones` 里找到同名条目，找不到直接抛
  `BoneReferenceError`（`EFX_OT_export` 捕获后 `{"ERROR"}` + `{"CANCELLED"}`，不写文件）。
  这里堵的是一个真实读出来的设计隐患：C# 后端写出时 `Bones.FindIndex(name)` 找不到会**静默**
  写成 `-1`（"无父骨骼"），不报任何异常——如果不在 Python 侧提前拦，用户改错骨骼名字会在
  完全没有报错提示的情况下丢失绑定，这正是架构决策 9 想避免的"错误结构骗过用户"，只是这次
  堵漏洞的是我们自己的胶水层，不是 C# 解析失败那种情况。
- **已知范围限制**：这次的编辑 UI 和校验只覆盖顶层文件自己的 Bones/Entries/Actions，不递归
  进嵌套 `PlayEmitter.efxrData` 子树。原因是 vendor 源码本身读写不对称——读时嵌套文件的骨骼
  引用查的是外层文件的 `Bones`（`parentFile?.Bones ?? Bones`，`EfxFile.cs:855`），写时却查
  嵌套文件自己的 `Bones`（`EfxFile.cs:984`，不查 `parentFile`）——这意味着嵌套树里如果真的
  用了骨骼绑定，重新导出后大概率会失效，但这是 vendor 自身的行为，不是这个功能能堵上的坑。
  面板上 `draw_node()` 给嵌套树里的 `ParentBone` 字段画 `prop_search` 时，`io_tree.find_root()`
  会定位到最近的外层 `EFX_ROOT`（可能是嵌套的那个，不是最外层文件），意味着嵌套树内的骨骼
  搜索框实际会对着一个大概率是空的 `efx_bones` 列表——不会报错崩溃（`prop_search` 允许自由
  输入，不强制列表内选择），只是自动补全用不上。等有真实带嵌套骨骼绑定的样本、确认 vendor
  这条路径实际行为后再决定要不要专门处理。

**UI**（`panels.py`）：`EFX_PT_object` 的 Root 面板新增一个 `EFX_UL_bones` 列表（对齐
Subselect Groups 列表的样式，一行显示 name + value，`+`/`-` 增删）；`draw_node()` 检测到
`ParentBone` 字段时画 `layout.prop_search(node, "string_value", root_obj, "efx_bones", ...)`
——和 Blender 挑选顶点组/骨骼同一个"输入名字、自动补全"控件，而不是裸文本框，降低打错字
概率（虽然 `prop_search` 本身不强制限制输入必须在列表里，真正兜底的是上面的导出前校验）。

**实机验证（2026-07-04，Blender 5.1.2，via Blender MCP）**：写完代码时这个仓库还没连上运行
中的 Blender，只做了 `py_compile` + 逐行走查；随后连上真实实例补了完整验证。第一步先发现
Blender 里已经装了同名冲突的插件（`bl_ext.user_default.efx_editor` 其实是姊妹项目
EFX-Editor/MHWI，不是本项目——本项目的 `id` 是 `mhws_efx_editor`，两者不冲突，只是这个环境
之前没装过本项目）；本项目也从未真正打包安装过（`dist/` 下有一个旧 zip，内容早于这轮改动）。
用 Python 重新打了 zip（`__init__.py` + `blender_manifest.toml` + `blender_efx_re/`，排除
`__pycache__`），但 `bpy.ops.extensions.package_install_files` 在无头脚本调用下没有实际生效
（返回 `FINISHED` 但不出现在已装插件列表里，怀疑是这个操作符设计为异步/依赖 UI 事件循环，
脚本一次性调用拿不到真正完成的状态）——改用更直接的开发期做法：把仓库根目录加进
`sys.path`，直接 `import blender_efx_re; blender_efx_re.register()`，绕开扩展安装 UI，效果
等价（`blender_efx_re` 本身是个独立包，不依赖外层扩展包装）。

验证结果：
- 注册无异常（只有一条"面板类重复注册，注销先前的"信息级提示，是前一次残留状态，非本轮改动
  引入的问题）。
- Import `diag/11_guide_006.efx.5571972.orig`（7 Entries，0 Actions，104 条 entry 级
  attribute）成功，`EFX_ROOT.efx_bones` 正确为空（对应样本 `Bones: []`）。
- Root 面板截图确认 Bones 列表正确渲染（空列表 + `+`/`-` 按钮），`efx_re.bone_add` 增加一条
  `pelvis`/`42` 后再截图确认。
- `[start_in] ParentOptions`（真实样本里的 attribute）的 `ParentBone` 字段截图确认画的是
  带搜索图标的 `prop_search` 控件，与同一 attribute 上 `BoneName`（遗留字段，未做特殊处理）
  的普通文本框视觉上明显不同；`Attractor`/`VanishArea3D` 两个 attribute 也各自命中
  `is_bone_reference_field()==True`，与 `ParentOptions` 行为一致（这三个是
  docs/TOPLEVEL_STRUCTURE.md 里真实样本 `$type` 确认适用于 MHWilds 的类型）。
- `check_bone_references()` 二态测试都通过：设成 `efx_bones` 里存在的名字（`pelvis`）不报错；
  改成不存在的名字（`nonexistent_bone`）正确抛 `BoneReferenceError`，报错文案包含具体
  attribute 对象名和骨骼名字。
- 走真实 `bpy.ops.efx_re.export` operator 端到端验证：骨骼名字不合法时，operator 在**调用
  C# 桥接之前**就报 `{"ERROR"}` 并返回 `{"CANCELLED"}`（脚本调用下 Blender 把
  `self.report({'ERROR'}, ...)` 转成 `RuntimeError` 抛出，属于脚本环境下的正常行为，不是
  bug）；改成合法名字后，operator 正确放行、继续往下走，实际卡在一个已知的、和这轮改动完全
  无关的既有缺口（`EFXExpressionDataBase` 反序列化不支持，见"Blender 实机验证"一节）——
  这恰恰证明我们的校验只在真正该拒绝时拒绝，不会误伤合法数据，且 `Bones`/`BoneRelations`
  的 JSON payload 本身没有让 C# 桥接层多报任何新错误。
- 直接检查 `io_tree.export_root_to_efxfile()` 的返回值，确认 `Bones` 正确导出成
  `[{"name": "pelvis", "value": 42}]`、`BoneRelations` 正确固定为 `[]`。

测试完成后清空了这个 Blender 实例里的场景对象/collection（避免留下测试脏数据误导下次
session），没有改动仓库里的任何样本文件。
