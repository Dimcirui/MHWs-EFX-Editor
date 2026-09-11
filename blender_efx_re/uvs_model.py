"""
blender_efx_re/uvs_model.py —— .uvs（UV 序列图集）对象模型

对应 PLAN.md "Phase 2 — UVS 编辑" 一节。数据模型和 EFX 的 ~TYPE 对象树刻意不同（该节
"已确认的事实"第 3 点）：

- **不是"每个实体一个 Blender Object"**——UVS 是纯数据表，没有空间语义（不像 EFX 的
  Transform3D 要在视口里摆位），而且数量级差太多：实测样本 9 张贴图 × 9 序列 × 每序列 64
  pattern，每个建一个 Empty 会把 Outliner 直接撑爆。改用一个 `~TYPE = EFX_UVS` 的
  **Collection**（沿用 EFX_ROOT 的决定——同一个项目两处 `~TYPE` 根都是集合，行为一致），上面挂
  嵌套 CollectionProperty：`efx_uvs_textures[]` / `efx_uvs_sequences[] -> patterns[]`。
- **不需要 EFX 那套递归 EFXValueNode 通用树**——UVS 的字段形状完全固定且已被 vendor
  `UvsFile.cs`（183 行）逐字段注释清楚，不是 ~150 个 attribute 子类各有不同形状那种情况，
  直接手写具名 PropertyGroup 字段就够，不需要为"vendor 升级新增字段类型"预留通用性。

字段级取舍（对照 vendor `ReeLib.Uvs.*`，见 tools/EfxBridge/Program.cs "uvsdump / uvsload
子命令"一节）：

- `Header.textureCount`/`sequenceCount`/`patternCount`、各种 `*Offset`、
  `SequenceBlock.patternCount`/`patternTableOffset`、`UvsPattern.cutoutUVCount`——全部由
  `UvsFile.DoWrite()` 按当前列表内容重新计算（UvsFile.cs:145-182），**不建 UI，不参与导出
  dict**，Python 侧完全不用管这些值对不对。
- `Header.attributes`——`[RszConditional("handler.FileVersion >= 7")]` 门控字段，只在 v7+ 存在。
  2026-09-10 用全部 72 个文件交叉核对 + 一次真实语料引用范围核查（`EFXAttributeUVSequence.
  PatternNo` 命中了大量真实特效，见 PLAN.md）确认了这是**两层开关**：`attributes=0` 的
  24 个文件 100% 对应全部 pattern `cutoutUVCount=-1`；`attributes=1` 的 48 个文件里，
  `cutoutUVCount` 只会是 `0`（这一帧不裁剪）或 `8`（这一帧用八边形裁剪），**从不出现 -1**。
  `-1` 是"整个文件关闭裁剪功能"的哨兵值，只有文件级开关本身决定要不要用；一旦开着，
  每个 pattern 自己决定裁不裁。字段名 `useUVCutout` 是我们自己猜的、不确定是否准确对应它
  在引擎里的真实用途（它在 Header 里、管的可能是比"裁不裁剪"更高层的东西），改成弱化措辞
  `cutout_related`，不在名字里断言具体功能。
  据此把模型改成两级布尔：`Collection.efx_uvs_cutout_related`（文件级，对应 vendor
  `Header.attributes`）+ `EFXUvsPatternItem.use_cutout`（pattern 级，`cutout_related` 关闭时
  不生效，导出时强制按 -1 处理）。`cutout_related=False` 时不管 `use_cutout`/`cutout_points`
  编辑成什么样，导出都按空数组处理（vendor 自然写 `-1`）；`cutout_related=True` 时
  `use_cutout=True` 的 pattern 导出成 8 点（已经画好点的用 `pad_cutout_points_to_8()`
  补/截到 8 个，没画的用 `default_cutout_rect_points()` 顶上——贴着矩形四角、复制最后一角
  凑够 8 个，这是从语料里挖出来的真实惯例：官方文件里大量 8 点"裁剪多边形"其实就是矩形
  本身，没有实际裁切效果，见 `11_cm_electrical_000.uvs.8`）；`use_cutout=False` 的 pattern
  需要导出成字面 `0`——见下一条，这个值 vendor 自己的写出路径产不出来，需要
  `EfxBridge` 二次 patch。
- **`cutoutUVCount=0`（`use_cutout=False` 但 `cutout_related=True`）结构上无法通过 vendor
  的常规写出路径产出，已经用 post-write 字节 patch 解决**：字面 0 和 -1 读出来都是"0 个点"
  （`RszList(nameof(cutoutUVCount))` 对两者行为相同），但 vendor 写出逻辑
  （`UvsFile.cs:172`）是 `cutoutUVs.Count == 0 ? -1 : cutoutUVs.Count`——空列表**只会**写成
  -1，没有任何路径能重新产出字面 0（直接拿 `EfxBridge` 对 `11_cm_electrical_000.uvs.8` 做
  纯 dump→load 实测过：10 个原本 `cutoutUVCount=0` 的 pattern 全部被写成 -1，证实是 vendor
  库本身的结构性限制，不是我们代码的 bug）。而这 21 个 `cutoutUVCount=0` 的 pattern 被
  证实是真实、活跃使用的游戏特效数据（不是编辑器残留，见 PLAN.md 的语料交叉引用核查），
  必须原样保真——`uvs_io.export_uvs_root()` 在需要字面 0 的 pattern 上显式带
  `"cutoutUVCount": 0` 这个额外 JSON 字段，`tools/EfxBridge/Program.cs` 的 `uvsload` 在
  `UvsFile.WriteTo()` 写完之后，对着这些 pattern 用 `BaseModel.Start` 记录的偏移做二次字节
  patch，把 vendor 算出来的 -1 改回 0——同 `PatchEffectGroupMemberOrder()` 处理 EffectGroups
  顺序的思路，绕开 vendor 的 `DoWrite()` 计算逻辑。
- `TextureBlock.stateHolder`/`texHandle1`/`texHandle2`/`texHandle3`——运行时句柄，语义未知，
  样本里全是常量/占位值。C# 声明是 `long`（64 位），按 `EFXBoneItem.value` 的 BIGINT-safe
  惯例存成十进制字符串，不用 `IntProperty`（32 位有符号，怕真实语料里出现超范围值时静默截断）。
- `UvsPattern.flags`——同样是 `long`，同样按十进制字符串存，语义未知（PLAN.md 风险清单里
  点名"pattern 级 flags 语义都未知"，等有语料后用类似 `fieldstats` 的方法普查）。
- `UvsPattern.cutoutUVs`——原本 PLAN.md Step 3 的决定是"先只读显示点数，不编辑"，2026-09-09
  之后确认了 `Header.attributes`/`cutoutUVCount` 相关性、需要能实际编辑裁剪多边形来继续排查，
  改成结构化存储：`cutout_points`（`EFXUvsCutoutPointItem` 的 `CollectionProperty`，每个点一个
  可编辑的 x/y），不再用 JSON 文本占位透传。
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Collection, PropertyGroup

# 加 `EFX_RE_` 前缀的理由见 model.py 里 TYPE_ROOT 等常量的说明——姊妹项目 EFX-Editor
# （MHWI）的 standalone.py 用的也是裸的 "EFX_UVS"，同装两个插件时会撞。
TYPE_UVS_ROOT = "EFX_RE_UVS"

# 这个插件只支持 MHWilds，目前语料里也只见过这一个版本号——不做成可编辑字段，导入时非 8
# 直接拒绝（见 uvs_operators.EFX_UVS_OT_import），面板上就是个固定文字，不需要 Collection
# 属性存它。
MHWILDS_UVS_FILE_VERSION = 8


class EFXUvsCutoutPointItem(PropertyGroup):
    """`UvsPattern.cutoutUVs` 里的一个 `Vector2` 顶点（JSON 键是大写 `X`/`Y`，见
    tools/EfxBridge/Program.cs 的 `CreateUvsJsonOptions()`：`IncludeFields=true` 且没配
    命名策略，字段名原样当 JSON 键）。多个顶点依次连接、首尾相接构成一个闭合多边形——
    不是"一个点存一条边的起止"，是"一个点就是一个顶点"。"""

    x: FloatProperty(name="X")
    y: FloatProperty(name="Y")


class EFXUvsPatternItem(PropertyGroup):
    """对应 `ReeLib.Uvs.UvsPattern`（UvsFile.cs:46-62）：贴图上的一个 UV 矩形。"""

    left: FloatProperty(name="Left")
    top: FloatProperty(name="Top")
    right: FloatProperty(name="Right")
    bottom: FloatProperty(name="Bottom")
    texture_index: IntProperty(
        name="Texture Index", min=0,
        description="指向所属 EFX_UVS 集合 efx_uvs_textures 表里的下标",
    )
    flags: StringProperty(
        name="Flags", default="0",
        description="原始 long 值，十进制字符串存储（避免 32 位截断），语义未知",
    )
    cutout_points: CollectionProperty(
        type=EFXUvsCutoutPointItem,
        name="Cutout UVs",
        description="裁剪多边形顶点，按顺序首尾相接构成闭合多边形（0 个点＝没有裁剪多边形）",
    )
    cutout_points_active_index: IntProperty()
    # pattern 级裁剪开关——只在集合级 `efx_uvs_cutout_related` 打开时才生效（2026-09-10
    # 定案，见模块头 `Header.attributes` 一节）：关闭时导出 `cutoutUVCount=0`（字面 0，靠
    # EfxBridge 的二次字节 patch 实现，vendor 自身写不出这个值）；打开时导出 8 点裁剪多边形
    # （`cutout_points` 有数据就用它，没有就用 `default_cutout_rect_points()` 顶一个默认
    # 矩形）。取代了之前的只读 `cutout_uv_count_raw`（原始 -1/0/8 三态整数）——现在这三态
    # 完全由 `efx_uvs_cutout_related`（文件级）+ `use_cutout`（pattern 级）两个布尔组合表达，
    # 不需要再单独存一份原始整数。
    use_cutout: BoolProperty(
        name="Use Cutout",
        description="这一帧要不要裁剪（仅在集合的 efx_uvs_cutout_related 打开时生效）",
    )


def default_cutout_rect_points(left: float, top: float, right: float, bottom: float) -> list[tuple[float, float]]:
    """`use_cutout=True` 时给没画裁剪多边形的 pattern 顶上的默认值——四角顺序左上→左下→
    右下→右上，再重复右上角 4 次凑够 8 个，复刻的是官方语料里的真实惯例（见模块头
    `Header.attributes` 一节）。"""
    corners = [(left, top), (left, bottom), (right, bottom), (right, top)]
    return corners + [corners[-1]] * 4


def pad_cutout_points_to_8(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """把任意长度（>=1）的点列表规整成正好 8 个：不够就重复最后一个点补齐，超过就截断到前
    8 个——`cutoutUVCount` 打开裁剪时实测只能是 8（见模块头 `Header.attributes` 一节），编辑
    过程中点数可以是任意值，但导出前必须收敛成这个取值。"""
    if len(points) >= 8:
        return list(points[:8])
    return list(points) + [points[-1]] * (8 - len(points))


class EFXUvsSequenceItem(PropertyGroup):
    """对应 `ReeLib.Uvs.SequenceBlock`（UvsFile.cs:36-44）：一段 pattern 序列。

    `name` 纯展示用（vendor 的 SequenceBlock 本身没有名字字段，是导入时按下标生成的
    `Sequence {i}`），不参与导出——序列的身份就是它在 `efx_uvs_sequences` 里的下标本身。
    """

    name: StringProperty(name="Name")
    patterns: CollectionProperty(type=EFXUvsPatternItem)
    patterns_active_index: IntProperty()


def _normalize_texture_path(self, context) -> None:
    """贴图路径里的反斜杠就地改成正斜杠。

    和 EFX 侧 `model._normalize_path_separators()` 同一个理由：RE Engine 的资源路径哈希
    （`MurMur3HashUtils.GetPakFilepathHash`）不处理分隔符方向，`\\` 和 `/` 算出来是两个完全
    不同的哈希，游戏按哈希查资源表，方向错了引用直接失效（EFX 侧那次是 `UVSPath` 写成反斜杠、
    游戏内报 "Invalid"）。UVS 的贴图路径是同一类字段，同样的坑。

    做成 `update` 回调而不是像 EFX 侧那样只在导入时规整：这里的路径**经常是用户自己填的**
    （从资源管理器复制、或者 GIF 转序列帧那个算子直接塞进来的 Windows 路径），只管导入那一次
    盖不住。回调里改回自己会再触发一次 update，但第二次 `fixed == self.path` 不再赋值，到此为止。
    """
    fixed = self.path.replace("\\", "/")
    if fixed != self.path:
        self.path = fixed


class EFXUvsTextureItem(PropertyGroup):
    """对应 `ReeLib.Uvs.TextureBlock`（UvsFile.cs:22-34）。`path` 是游戏相对路径
    （不带扩展名版本号，如 `Art/VFX/Texture/Common/Sequence/11_fire_000_ALBA.tex`）——
    贴图预览（PLAN.md Step 4，本轮未做）会需要用户配一个解包根目录去把它解析成真实文件。
    """

    path: StringProperty(name="Path", update=_normalize_texture_path)
    # 运行时句柄，语义未知，long 类型，BIGINT-safe 字符串存储（同 flags）。2026-09-09 批量扫了
    # 72 个官方文件：`state_holder` 91% 等于自己在贴图表里的下标（有例外，更像作者编号，
    # 不是每次重算的位置，见 PLAN.md），`tex_handle1/2/3` 486 个槽位里 485 个是 -1（唯一一个
    # 例外语义不明，原样记录不深挖）——新建贴图时默认值就按这套"最常见的样子"给，不是瞎猜。
    state_holder: StringProperty(name="State Holder", default="0")
    tex_handle1: StringProperty(name="Tex Handle 1", default="-1")
    tex_handle2: StringProperty(name="Tex Handle 2", default="-1")
    tex_handle3: StringProperty(name="Tex Handle 3", default="-1")


_CLASSES = (
    EFXUvsCutoutPointItem, EFXUvsPatternItem, EFXUvsSequenceItem, EFXUvsTextureItem,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    # EFX_UVS 专属，全部挂在 Collection 上（EFX_UVS 就是那个集合本身，同 EFX_ROOT 的决定，
    # 没有根 Empty）。文件版本号不做成属性——这个插件只支持 MHWilds 的固定版本号 8
    # （`MHWILDS_UVS_FILE_VERSION`），面板上直接显示常量文字就够。
    Collection.efx_uvs_source_filename = StringProperty(
        name="Source Filename",
        description="导入时的原始文件名（含版本号后缀），导出时作为默认文件名",
    )
    # 对应 vendor 的 Header.attributes。名字刻意弱化成 "cutout related"：只确认了它是文件级
    # 总开关，没确认引擎里的真实用途是不是字面意义的"启用裁剪"。
    Collection.efx_uvs_cutout_related = BoolProperty(
        name="UV Cutout Related",
        description="文件级总开关：关闭时整个文件都不裁剪；打开时才由每个 pattern 自己的 "
                    "use_cutout 决定裁不裁",
    )
    Collection.efx_uvs_textures = CollectionProperty(type=EFXUvsTextureItem)
    Collection.efx_uvs_textures_active_index = IntProperty()
    Collection.efx_uvs_sequences = CollectionProperty(type=EFXUvsSequenceItem)
    Collection.efx_uvs_sequences_active_index = IntProperty()


def unregister():
    del Collection.efx_uvs_sequences_active_index
    del Collection.efx_uvs_sequences
    del Collection.efx_uvs_textures_active_index
    del Collection.efx_uvs_textures
    del Collection.efx_uvs_cutout_related
    del Collection.efx_uvs_source_filename

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
