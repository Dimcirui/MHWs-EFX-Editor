# -*- coding: utf-8 -*-
"""
blender_efx_re/clip_fcurve.py —— Clip 关键帧的原生 Blender fcurve 编辑

以前 `EFXClipCurveItem` 自己带一份 `EFXClipKeyframeItem` 列表 + 手搓 `UIList`
（`model.py`/`panels.py` 旧版），用户没法用 Dope Sheet / Graph Editor 拖关键帧。这一层把
关键帧数据搬进这个 Clip attribute 对象自己的 Action：**fcurve 是关键帧的唯一权威**，
`EFXClipCurveItem` 只留"这条曲线是什么"（驱动哪个 bit、Int/Float、fcurve 定位 key）。
`io_tree.py` 导入时调 `import_curve()` 从解析出的 JSON 建 fcurve，导出时调 `export_curve()`
从 fcurve 读回同样形状的 JSON 字典。

架构取舍：不用集合下标寻址（对比姊妹项目 EFX-Editor 的 `timl_edit.py`）
--------------------------------------------------------------------
TIML 的 synthetic 通道每次都是"全量清空重建"（`build_persistent_fcurves` 先清后建），所以用
`efx_timl_channels[i].value` 这种集合下标当 fcurve 的 `data_path` 没有稳定性问题——反正每次都
从头按同一个顺序重新分配下标。但 MHWs 的 Clip 曲线是**增量编辑**的：用户随时加一条、删一条，
其它曲线不该受影响。如果也用集合下标寻址，删除中间一条会导致后面所有曲线的下标集体前移，
沿用旧下标的 fcurve 会悄悄开始对应到别的曲线——这正是铁律 #1 明令禁止的"看起来正常但静默错位/
丢数据"。

因此每条曲线的 fcurve 挂在这个 attribute 对象自己的一个**专属自定义 ID 属性**上
（`obj["efx_clip_ch_<id>"]`，`id` 来自只增不减的计数器 `Object.efx_clip_next_channel_id`），
`EFXClipCurveItem.channel_key` 记住这个 key。这个 key 一旦分配，终身不变，曲线被删除也不回收
编号——彻底避免下标位移问题，也不需要 TIML 那种"结构变更先 commit 再整体重建"的额外协议。

插值类型语义（2026-09-19 陆续实机/语料确认，取代了早先"13 个全占位"的过渡方案）
------------------------------------------------------------------------
`FrameInterpolationType` 极大概率和 kagenocookie/RE-Engine-Lib 里独立 `.clip`/`.tml` 格式共用
同一套命名枚举（`Unknown=0, Discrete=1, Linear=2, Event=3, Slerp=4, Hermite=5, AutoHermite=6,
Bezier=7, AutoBezier=8, OffsetFrame=9, OffsetSec=0xA, PassEvent=0xB, Bezier3D=0xC, Range=0xD,
DiscreteToEnd=0xE, RangeV2=0xF, None=0x10`）——本仓自己 vendor 的注释原文就是"Maybe the same
enum as .clip files?"。证据链（详见 `docs/PITFALLS.md` 和记忆库）：

- **语料统计（`tools/EfxBridge` 的 `clipinterpstats`/`clipeventstats` 子命令）**：扫了全部 12+
  个 `IClipAttribute` 类型、1767 个真实实例，**从头到尾只出现过 `raw ∈ {1,2,3,5}`**，`0/4/6/7/
  8/9/10/11/12/13` 一次都没有——不是 Transform3D 专属现象，是全部 Clip 类型的共性。
- **实机崩溃/飞天/恒零测试**（用户拿同一个已知形状的曲线,只改起点关键帧的插值类型逐个试
  `0~12`）：`7`（结构上对应"真 Bezier"，需要 `Bezier3DKeys` 那种 8 个 float 的完整四控制点，
  EFX 的 `EfxClipInterpolationTangents` 只有 4 个 float）**直接崩游戏**；`4`（Slerp，四元数
  专属的球面插值，喂给标量位置分量）、`6/8/10/11/12`（AutoHermite/AutoBezier/OffsetSec/
  PassEvent/Bezier3D，都需要 EFX 没分配空间存的额外数据）恒为 0；`9`（OffsetFrame，把帧号当
  数值加上去）直接"飞到天上"；`0`（Unknown，未实现的默认值）恒为 0；`1`/`3` 表现成"保持起始
  值不动、最后一帧才跳变"，肉眼分不出区别。这些失败模式跟共享枚举里对应名字的字面意思逐条
  精确对应，随便编一个不相关的枚举编不出这么精确的失败模式匹配。
- **Hermite 切线幅度定量测试**（用户拿一条明显不对称的过冲/下冲曲线，Z/Y Location 各设了
  handle 长度约等于净位移 2.5 倍的夸张手柄，实机读出的过冲幅度只有 Blender 图形编辑器里
  直接显示值的 1/3 左右，跟"标准 Hermite→Bezier 换算是控制点偏移=切线/3"这个预测吻合，而
  且方向和大致量级都对——`raw=5` **不是字面 Bezier，是 Hermite**，`_tangent_to_handles()`/
  `_handles_to_tangent()` 必须做这个 ÷3/×3 换算，不能把切线原样当控制点偏移用。
- **`raw=3`（Event）取值分布**（`clipeventstats`，94 帧/59 条曲线）：只出现在 `PtColorClip`
  和 `Transform3DClip` 两种类型；位置不集中在某一处（首/中/尾都有）；有后继帧时 76% 的概率
  跟后继帧同值，有前驱帧时 71% 的概率跟前驱帧不同值；取值本身就是普通的颜色字节/位置浮点数，
  不像携带额外编码。跟曲线形状角度看和 Discrete 分不出区别，但语料里用得不算罕见，不能悄悄
  塌缩成 Discrete（会丢导出时该写回哪个原始类型的信息）。

**"能导入"和"能直接导出"从 2026-09-19 起是两个故意不同的集合**（用户拍板，不是疏漏）：

- **能直接导出的只有 3 个 Blender 原生真实类型**：`CONSTANT`/`LINEAR`/`BEZIER`
  （`_STANDARD_EXPORT_INTERP`，见下面"插值类型映射"一节），对应真实原始值 `1`/`2`/`5`。
  `curve_interpolation_issues()` 只放行这三个，其余全部拦——`3`(Event) 借的 `SINE` 也在
  拦截范围内，导出前必须先转成这三种之一。
- **能导入的是 `{0,1,2,3,4,5,6,8,9,10,11,12,13}`**（`7` 除外，见下面单独一节）：`0/4/6/8/
  9/10/11/12/13` 这 9 个"非标准"值（语料从没用过，实机测出大多恒为 0/9 飞天）跟 Event 的
  `3` 完全同构——各自借一个从没用过的 Blender 插值名字当纯占位（不代表任何形状），
  `import_curve()` 不再拒绝它们，用户可以在 Blender 原生下拉框里把它们改成任何其它类型
  （包括标准的三个）——这就是"允许导入后改类型"，不需要专门的算子，Blender 自己的插值
  下拉框已经足够。之所以敢放行：这 9 个值**都不需要额外的切线数据**
  （`interp_type == _CLIP_HERMITE_TYPE` 才会消费 `interpolationData[]`，这 9 个都不是），
  纯值+位置+占位插值名字，不存在任何数据结构层面的风险——不像 `7`。

  Blender 一共 13 个内置插值标识符，标准 3 个（`CONSTANT`/`LINEAR`/`BEZIER`）+ Event 借的
  `SINE` 用掉 4 个，正好剩 9 个（`QUAD`/`CUBIC`/`QUART`/`QUINT`/`EXPO`/`CIRC`/`BACK`/
  `BOUNCE`/`ELASTIC`）给这 9 个非标准值一一对应，不多不少——这不是巧合设计出来的，是
  `raw=7` 被排除在外之后刚好腾出的名额（如果 `7` 也要占一个名字，就会变成 10 个值抢 9 个
  槽位，不够分）。

**`raw=7`（真 Bezier）是唯一仍然在 `import_curve()` 硬拒绝的值，不是因为它比其它 9 个更
"没证据"，是因为它涉及一类完全不同的风险**：`EfxClipData` 的 `interpolationData[]` 是不看
`type` 字段、按数组顺序原样写出的纯字节数组（`WriteData()`），"哪个 frame 消费第几个
tangent"这件事全靠**我们自己**在 `io_tree._populate_clip_attribute()`/`_export_clip_attribute()`
里按 `interp_type == _CLIP_HERMITE_TYPE`（严格等于 `5`）来切片——这条切片规则抄的是我们
自己 vendor 库的 `EfxClipData.ParseClip()`/`SetFromClipList()`，那两个方法**同样只认字面
`Bezier`(枚举值 5)，不认 `7`**。如果游戏引擎自己的消费逻辑也是"只认 5"（vendor 库大概率是
从游戏逆向出来的，这不是无凭无据的猜测），那么给一个 `type=7` 的帧塞一个 tangent 条目，
游戏侧根本不会把这个条目分配给这一帧——它会被后面**下一个**真正的 `type=5` 帧错误消费，
导致那一帧的切线读错，而这个错位还会像 `BoneRelations` 那样**向后传染**，错的不是这一帧，
是从这里开始往后所有还会消费 tangent 的帧。这跟前面 9 个"纯值+位置，不摸 tangent 数组"的
情况完全不是一回事——`7` 一旦引入哪怕一条 tangent 数据，就有连锁腐蚀同一条曲线里其它
Hermite 帧的风险，属于铁律 #1 要拒绝的那一类，不能因为"用户明确要求接入"就绕过。要放行
`7`，必须先有真实证据回答"这个引擎版本上，`type=7` 到底消费几个 tangent 数组槽位"——
最直接的办法是手工构造一个 `interpolationData` 恰好塞了 8 个 float（2 个
`EfxClipInterpolationTangents` 大小）、专门给这一帧用的文件，进游戏看后续帧有没有错位，
`tools/raw_json_patch.py` 现在做不到这个（只能改单个字段，改不了数组结构），需要专门写一个
脚本或者手动改 JSON 才能测。**这不是"延后处理"，是"这条路径本身有连锁腐蚀其它帧的风险，
必须先有实机证据才能碰"。**

`Event`（`raw=3`）分到自己独立的 Blender 名字，**不能塌缩进 `CONSTANT`**：曲线形状上和
`Discrete`(`raw=1`) 分不出区别，但导出时必须知道这一帧原来写的是 1 还是 3——如果两者共用同一个
Blender 插值名字，导出代码就再也无法反推出该写哪个原始值，等于主动丢弃数据（铁律 #1）。
`_INTERP_MHWS_TO_BLENDER` 里 `3` 对应的 Blender 名字本身不代表任何真实曲线形状（游戏side
是不是真的有除了"保持数值"之外的额外触发效果依然未知），纯粹是为了保住这个 bit 的可分辨性。

切线坐标语义
------------
`EfxClipInterpolationTangents`（`out_x/out_y/in_x/in_y`）现在当"这个关键帧的 Hermite 切线"
处理（上面那条证据链的结论），换算成 Blender 原生的 `handle_left`/`handle_right`（绝对坐标）
时要过 `_HERMITE_TO_BEZIER_HANDLE_SCALE`（标准 Hermite→Bezier 换算的 1/3 系数），写在
`_tangent_to_handles()`/`_handles_to_tangent()` 里，出错时改这两个函数就是唯一的修复点。
Blender 自己没有"Hermite"这个插值标识符——它的三次贝塞尔关键帧（`interpolation="BEZIER"` +
`handle_left_type`/`handle_right_type="FREE"`）数学上和 Hermite 曲线是同一条曲线的两种参数化
（换算关系正是这个 ÷3/×3），所以借用 `BEZIER` 这个名字是唯一可行的原生落地方式——**但这
只是 Blender 侧显示用的名字，不代表 `raw=5` 是字面意义的 Bezier**，本模块和面板文案里任何
提到"这条曲线是 Bezier"的地方都是指"借用 Blender 的 Bezier 机制表示 Hermite"，不是在下
"这是字面贝塞尔"的结论。

一处仍未证实假设：`Transform3DClip`/`PtTransform3DClip` 的 bit 顺序
------------------------------------------------------------------------
2026-09-19 用户实机测过"bit 0/1/2 是位移"这个假设（拿一条已知形状的位移曲线测出符合预期的
位置变化），据此推断 9 个 bit 是"3 位移 + 3 旋转 + 3 缩放"按 Transform3D 字段顺序排列——
`_TRANSFORM3D_CLIP_XFORM` 只接了位移（0/1/2）和缩放（6/7/8）到宿主对象自己的原生
`location`/`scale`，**旋转（3/4/5）故意没接**：位移和缩放在 `coords.py` 里都是纯分量置换
（+符号），共轭变换不会把不同分量混在一起，能安全地独立按轴接原生 fcurve；旋转不是——
`coords.game_rot_matrix_to_blender()` 要三个角度先合成一个矩阵、做一次 `M @ R @ M⁻¹` 共轭，
再分解回 Euler，是三个分量耦合在一起的非线性变换，没法拆成三条独立的 1D 曲线各自接
`rotation_euler.x/y/z`——接错了会产出"看起来能用、实际角度不对"的结果，比留着不接更危险。
旋转三个 bit 暂时还留在 `efx_clip_ch_N` 自定义属性通道上（能在 Dope Sheet 编辑，只是不会
驱动视口里的旋转 gizmo）；缩放三个 bit（6/7/8）的具体顺序也没有被独立测过，纯粹是跟着位移的
推断顺延。这条假设实机验证后要回来更新这个文档和 `docs/PITFALLS.md` 对应条目，不能让"能
编辑"变成"游戏内效果被默认为正确"。

已知、已接受的限制（不是假设，是实测确认过的存储精度问题，2026-09-19）
------------------------------------------------------------------
Bezier 切线句柄存进 Blender 原生 fcurve 后会有 **float32 ULP 级精度损失**：`_tangent_to_handles()`
把 `(out_x, out_y, in_x, in_y)` 转成绝对坐标 `(frame_time + delta, value + delta)`，Blender 的
`BezTriple`（fcurve 关键帧的内部结构）按 32 位浮点存这个绝对坐标，`_handles_to_tangent()` 再用
减法把 delta 减出来——只要 `frame_time`/`value` 相对 delta 不是特别小，这一存一取必然经过一次
float32 舍入，无法通过改换算公式消除（实测：`98.152` 存一圈变成 `98.15199...`，相对误差 ~1e-5）。
这不是"语义假设错了"那一类问题，是 Blender 这个数据结构本身的存储精度，任何用绝对坐标句柄表示
一个相对小量的方案都会撞上同一堵墙。

比照姊妹项目 EFX-Editor 对 loc/rot fcurve 同类 ULP 级精度损失"用户已接受"的先例
（`timl_edit.py` 模块文档 "byte-perfect" 一节），这里同样选择接受：`tools/
verify_blender_clip_fcurve.py` 的字节比对在字节不同时退化成数值容差比对（`math.isclose`，
`rel_tol=1e-4`），容差内不算失败。**这不代表"随便什么精度损失都能用容差糊过去"**——容差外
（切线符号搞反、关键帧顺序错这类真正的逻辑 bug）仍然会被那条门禁抓出来，第一次跑就真的抓到过
一次符号错误（误差几十个单位，远超容差）。

约束（CLAUDE.md）：bpy 稳定子集；纯胶水层，不在这里做字节级 I/O（那是 `io_tree.py` 的事）。
"""

from __future__ import annotations

import bpy

from . import model

# ─────────────────────────────────────────────────────────────────────────────
# Action fcurves 兼容层（Blender 4.4+ 把 Action 改成 layers/strips/slots/channelbag）
# ─────────────────────────────────────────────────────────────────────────────
# 4.4+ Action.fcurves 被移除（AttributeError，非 deprecated）；旧版仍是直接 F 曲线集合。这层
# 薄代理把两套 API 收敛成旧版接口，业务代码统一走 `_act_fcurves()`。移植自姊妹项目 EFX-Editor
# 的 `blender_efx/timl_edit.py`（已在那边调通），按本模块"fcurve 直接挂在 attribute 对象自己
# 身上"简化——不需要 TIML 那种额外的"句柄对象"概念。
# ⚠ 判据必须用 bpy.app.version（类级 RNA 数据属性 hasattr 不可靠，实测在部分版本上误判）。
_LEGACY_ACTION_FCURVES = bpy.app.version < (4, 4, 0)

_ACTION_MARKER = "~EFX_CLIP_FC"


class _ChannelbagFCurvesProxy:
    """代理新版 ActionChannelbag.fcurves，接口对齐旧版 act.fcurves。"""
    __slots__ = ("_fcs",)

    def __init__(self, channelbag):
        self._fcs = channelbag.fcurves

    def new(self, data_path, index=0, action_group=""):
        return self._fcs.new(data_path, index=index, group_name=action_group)

    def find(self, data_path, index=0):
        return self._fcs.find(data_path, index=index)

    def remove(self, fc):
        self._fcs.remove(fc)

    def __iter__(self):
        return iter(self._fcs)

    def __len__(self):
        return len(self._fcs)

    def __bool__(self):
        return len(self._fcs) > 0


class _EmptyFCurves:
    """4.4+ 只读取用时，channelbag 还不存在的空集合替身。"""

    def find(self, data_path, index=0):
        return None

    def new(self, *a, **kw):
        raise RuntimeError("_act_fcurves(create=False) 下不能新建 fcurve")

    def remove(self, fc):
        raise RuntimeError("_act_fcurves(create=False) 下不能删除 fcurve")

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return False


def _ensure_channelbag(act, obj, create=True):
    """新版(4.4+) API 专用：返回 obj 对应的 ActionChannelbag。

    ⚠ create=True 会写 ID 数据（新建 slot/layer/strip）。Blender 禁止在 poll()/draw() 里写
    ID，任何从 poll/draw 可达的路径必须传 create=False——此时只查不建，缺任何一层就返回 None。
    """
    ad = obj.animation_data
    slot = ad.action_slot if (ad is not None and ad.action_slot is not None) else None
    if slot is None:
        for s in act.slots:
            if s.target_id_type in ("OBJECT", "UNSPECIFIED"):
                slot = s
                break
    if slot is None:
        if not create:
            return None
        slot = act.slots.new(id_type="OBJECT", name=obj.name)
    if create and ad is not None and ad.action_slot is not slot:
        ad.action_slot = slot
    if act.layers:
        layer = act.layers[0]
    elif create:
        layer = act.layers.new(name="Layer")
    else:
        return None
    if layer.strips:
        strip = layer.strips[0]
    elif create:
        strip = layer.strips.new(type="KEYFRAME")
    else:
        return None
    return strip.channelbag(slot, ensure=create)


def _act_fcurves(act, obj, create=False):
    """统一入口：旧版直接 act.fcurves；新版(4.4+)走 layers/strips/channelbag 代理。

    ⚠ 默认 create=False（只读）。只有确实要写 fcurve 的地方才传 create=True，且那个调用点
    必须在算子 execute()/导入流程里，不能在 poll()/draw() 里。
    """
    if _LEGACY_ACTION_FCURVES:
        return act.fcurves
    bag = _ensure_channelbag(act, obj, create=create)
    if bag is None:
        return _EmptyFCurves()
    return _ChannelbagFCurvesProxy(bag)


# ─────────────────────────────────────────────────────────────────────────────
# 插值类型映射（见模块文档"插值类型语义"一节的证据链）
# ─────────────────────────────────────────────────────────────────────────────

_CLIP_HERMITE_TYPE = 5  # FrameInterpolationType.Hermite——不是字面 Bezier，见模块文档

#: **标准**（`_STANDARD_EXPORT_INTERP` 允许导出的那 3 个 Blender 原生名字，见下方）：
#: `1->CONSTANT`/`2->LINEAR` 是实机确认过的真映射；`5->BEZIER` 是 Hermite 借用 Blender 唯一
#: 支持自由切线的插值标识符（不是字面 Bezier，切线换算见 `_tangent_to_handles()`）；`3` 的
#: Blender 名字纯粹是占位——曲线形状和 `1` 分不出区别，只是需要一个独立名字才能在导出时分清
#: 原始类型是 1 还是 3，不能反推出任何真实形状结论；`3` 能导入但不在允许导出的三个真实类型
#: 里（见 `_STANDARD_EXPORT_INTERP`），导出前必须先转成 Constant/Linear/Bezier 之一。
#:
#: **非标准**（`0/4/6/8/9/10/11/12/13`，2026-09-19 用户拍板改成"允许导入+允许改类型，
#: 但不提供关键帧编辑入口"）：这 9 个原始值各自借用一个 Blender 内置插值名字（纯粹占位，
#: 不代表任何真实曲线形状），跟 Event 借 SINE 是完全一样的手法——区别只是这些值从不出现
#: 在真实语料里,而且用户实机测过大多数会产出退化结果（`0`/`4`/`6`/`8`/`10`/`11`/`12` 恒为
#: 0，`9` 飞到天上，`13` 只在 DMC5 样本见过、MHWs 上未测）。之所以现在敢放行导入，是因为
#: 这些值**都不需要额外的切线数据**（`interp_type == _CLIP_HERMITE_TYPE` 才会消费
#: `interpolationData[]`，这 9 个都不是），纯值+位置+占位插值名字，跟 Event 完全同构，没有
#: 任何数据结构层面的风险。用户可以在 Blender 原生插值下拉框里把它们改成任何其它类型
#: （包括标准的三个）——这就是"允许改类型"，不需要额外的算子，Blender 自己的下拉框已经够用。
#: 唯一**不放行**的是 `7`（真 Bezier）——见下面的说明，它涉及切线数据消费顺序，跟这 9 个
#: 不是同一类风险，需要先解决那个问题才能加进来。
_INTERP_MHWS_TO_BLENDER = {
    0: "QUAD",        # Unknown，实机恒为 0，占位
    1: "CONSTANT",    # Discrete，实机确认：保持左值直到本段最后一帧才跳变
    2: "LINEAR",       # Linear，实机确认：匀速直线运动
    3: "SINE",         # Event，占位名字，导入允许、导出前必须先转成标准三种之一
    4: "CUBIC",        # Slerp，四元数专属插值喂给标量分量，实机恒为 0，占位
    5: "BEZIER",       # Hermite（不是字面 Bezier），切线换算见 `_tangent_to_handles()`
    6: "QUART",        # AutoHermite，需要额外数据 EFX 没存，实机恒为 0，占位
    8: "QUINT",        # AutoBezier，同上，实机恒为 0，占位
    9: "EXPO",         # OffsetFrame，实机"飞到天上"，占位
    10: "CIRC",        # OffsetSec，需要额外数据，实机恒为 0，占位
    11: "BACK",        # PassEvent，需要额外数据，实机恒为 0，占位
    12: "BOUNCE",      # Bezier3D，需要额外数据，实机恒为 0，占位
    13: "ELASTIC",     # 结构上确认存在但 MHWS 语料至今没见过（只见于 DMC5 样本），未实机测过，占位
}
_INTERP_BLENDER_TO_MHWS = {v: k for k, v in _INTERP_MHWS_TO_BLENDER.items()}

#: 面板/校验信息统一引用这句话，避免各处措辞漂移。
UNVERIFIED_INTERP_NOTE = (
    "仅支持 Discrete/Linear/Event/Hermite 这 4 种（真实文件从没用过别的）；"
    "Blender 这里显示的\"Bezier\"其实是 Hermite（切线已按 ÷3 换算），不是字面贝塞尔——"
    "Blender 没有单独的 Hermite 标识符，借用这个名字是最接近的原生选项；"
    "Event 和 Discrete 曲线形状分不出区别，独立占一个名字只是为了导出时能分清原始类型"
)


class ClipFcurveError(RuntimeError):
    """内部一致性检查失败时抛出（曲线缺 fcurve、fcurve 用了不在映射表里的插值）。
    正常路径不应该走到这里——`io_tree.check_clip_interpolations()` 应该已经在导出前把后一种
    情况拦成用户可读的错误；这里是防止校验被绕过时静默产出错误字节的最后一道防线。"""


# ─────────────────────────────────────────────────────────────────────────────
# Transform3DClip 的 Position/Scale bit -> 宿主 Entry/Action 对象自己的原生 Location/Scale
# fcurve（未证实假设 3，见模块文档）
# ─────────────────────────────────────────────────────────────────────────────

#: `$type` 精确匹配——bit 的含义是按 attribute 类型各自定义的 BitSet，同一个 bit_index 在别的
#: Clip 类型上完全是另一件事，不能按"看起来像 Transform3D"猜。
_TRANSFORM3D_CLIP_TYPES = frozenset({
    "ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DClip",
    "ReeLib.Efx.Structs.Transforms.EFXAttributePtTransform3DClip",
})

# bit_index -> (data_path, array_index, sign)。只覆盖 Position(0/1/2)、Scale(6/7/8)——两组都是
# `coords.py` 已确认的纯分量置换(+符号)，共轭变换不会把不同分量混在一起，能安全地独立按轴接
# 原生 fcurve（对照 `coords.game_pos_to_blender()`/`game_scale_to_blender()`）。Rotation(3/4/5)
# 故意不在这张表里——`coords.game_rot_matrix_to_blender()` 要三个角度一起过一次矩阵共轭才能换成
# Blender 的 Euler，不是能各轴独立接的映射，接错了会产出看起来能用但实际数值不对的旋转，
# 详见模块文档。bit 顺序（Position 在前、Scale 在后）本身也是未证实假设，只有 Position 三个
# bit 被 2026-09-19 那轮实机测试间接验证过（用户确认"0/1/2 是位移"下测出的结果符合预期），
# Scale 三个 bit 的顺序纯粹是按"Transform3D 字段顺序"的自然推断，没有独立验证。
_TRANSFORM3D_CLIP_XFORM = {
    0: ("location", 0, 1.0),
    1: ("location", 2, 1.0),
    2: ("location", 1, -1.0),
    6: ("scale", 0, 1.0),
    7: ("scale", 2, 1.0),
    8: ("scale", 1, 1.0),
}


def _xform_target(obj, bit_index):
    """若这条 Clip 曲线的 bit 能安全映射到宿主 Entry/Action 对象（`obj.parent`，同
    `transform3d_view.py` 里静态 Transform3D 写 `matrix_basis` 的目标一致）自己的原生
    Location/Scale fcurve，返回 `(目标对象, data_path, array_index, 符号)`；否则返回 `None`
    （退回自定义 ID 属性通道）。"""
    if obj.efx_attr_type not in _TRANSFORM3D_CLIP_TYPES or obj.parent is None:
        return None
    entry = _TRANSFORM3D_CLIP_XFORM.get(bit_index)
    if entry is None:
        return None
    data_path, index, sign = entry
    return obj.parent, data_path, index, sign


# ─────────────────────────────────────────────────────────────────────────────
# Action / fcurve 定位
# ─────────────────────────────────────────────────────────────────────────────

def _get_action(obj):
    ad = obj.animation_data
    return ad.action if ad is not None else None


def ensure_action(obj):
    """取或建 obj 自己的 Action（不是共享的——xform 通道挂在 `obj.parent` 上时，这个 `obj`
    就是那个 parent；synthetic 通道则是 Clip attribute 对象自己）。"""
    if obj.animation_data is None:
        obj.animation_data_create()
    act = obj.animation_data.action
    if act is None:
        act = bpy.data.actions.new("EFX_CLIP::%s" % obj.name)
        act.use_fake_user = True
        act[_ACTION_MARKER] = 1
        obj.animation_data.action = act
    return act


def _channel_data_path(key: str) -> str:
    return '["%s"]' % key


def _find_fcurve(obj, curve_item):
    xform = _xform_target(obj, curve_item.bit_index)
    if xform is not None:
        target, data_path, index, _sign = xform
        act = _get_action(target)
        if act is None:
            return None
        return _act_fcurves(act, target).find(data_path, index=index)
    if not curve_item.channel_key:
        return None
    act = _get_action(obj)
    if act is None:
        return None
    return _act_fcurves(act, obj).find(_channel_data_path(curve_item.channel_key), index=0)


def add_channel(obj, curve_item) -> None:
    """给一条新曲线分配 fcurve（不插关键帧，用户自己在 Dope Sheet 里插）。Position/Scale
    bit（见 `_xform_target()`）挂在宿主对象的原生 Location/Scale 上；其余 bit 走自定义 ID
    属性通道（`channel_key`），已经有 key 时是空操作（防止重复调用把 key 弄丢）。"""
    xform = _xform_target(obj, curve_item.bit_index)
    if xform is not None:
        target, data_path, index, _sign = xform
        act = ensure_action(target)
        fcs = _act_fcurves(act, target, create=True)
        if fcs.find(data_path, index=index) is None:
            fcs.new(data_path, index=index)
        return
    if curve_item.channel_key:
        return
    channel_id = obj.efx_clip_next_channel_id
    obj.efx_clip_next_channel_id = channel_id + 1
    key = "efx_clip_ch_%d" % channel_id
    obj[key] = 0.0
    curve_item.channel_key = key
    act = ensure_action(obj)
    fcs = _act_fcurves(act, obj, create=True)
    data_path = _channel_data_path(key)
    if fcs.find(data_path, index=0) is None:
        fcs.new(data_path, index=0)


def remove_channel(obj, curve_item) -> None:
    """回收一条曲线的 fcurve（+ synthetic 通道的自定义 ID 属性；xform 通道本来就没有）。
    key 本身（编号）不回收。"""
    xform = _xform_target(obj, curve_item.bit_index)
    if xform is not None:
        target, data_path, index, _sign = xform
        act = _get_action(target)
        if act is not None:
            fc = _act_fcurves(act, target).find(data_path, index=index)
            if fc is not None:
                _act_fcurves(act, target, create=True).remove(fc)
        return
    key = curve_item.channel_key
    if not key:
        return
    act = _get_action(obj)
    if act is not None:
        fc = _act_fcurves(act, obj).find(_channel_data_path(key), index=0)
        if fc is not None:
            _act_fcurves(act, obj, create=True).remove(fc)
    if key in obj.keys():
        del obj[key]
    curve_item.channel_key = ""


def remove_all_channels(obj) -> None:
    """回收 `obj.efx_clip_curves` 里*当前所有*曲线的 fcurve + 自定义 ID 属性。

    在整体替换内容前调用（比如 `copy_paste.py` 的 Paste Properties——先 `efx_clip_curves.
    clear()` 扔掉旧的 `EFXClipCurveItem`，再 `apply_attribute_content()` 重新 populate）。
    不这么做的话，旧 fcurve/自定义 ID 属性会变成没有任何 `EFXClipCurveItem` 指着的孤儿，
    永久留在这个对象的 Action 里——不影响导出字节（导出只看 `efx_clip_curves` 现存的曲线），
    但会在 Dope Sheet 里堆出一堆认不出是哪条曲线的孤立 fcurve，而且每贴一次都会再攒一份，
    不清理就是无限泄漏。"""
    for curve in obj.efx_clip_curves:
        remove_channel(obj, curve)


# ─────────────────────────────────────────────────────────────────────────────
# 切线换算（Hermite 切线 ⇄ Blender 贝塞尔控制点偏移，见模块文档"切线坐标语义"一节）
# ─────────────────────────────────────────────────────────────────────────────

#: 标准 Hermite→Bezier 换算：贝塞尔控制点偏移 = Hermite 切线 / 3（反过来，导出时要 ×3 换回
#: 切线）。2026-09-19 实机定量测试确认了这个系数的方向和大致量级——见模块文档"插值类型语义"
#: 一节的"Hermite 切线幅度定量测试"。
_HERMITE_TO_BEZIER_HANDLE_SCALE = 1.0 / 3.0


def _tangent_to_handles(frame_time, value, tangent):
    """(out_x,out_y,in_x,in_y) 是 Hermite 切线 -> (handle_left, handle_right) 是 Blender
    贝塞尔控制点的绝对坐标，两者不是同一个量纲，必须先乘 `_HERMITE_TO_BEZIER_HANDLE_SCALE`
    再当偏移量加上去。

    两边都是**直接相加**的偏移量，不是"取反再减"——实机样本证实 `in_x` 本身已经带负号
    存（如 `-98.152`），`frame_time + in_x*scale` 才会落在关键帧左边。最初写成
    `frame_time - in_x` 在真实数据上会把 `handle_left.x` 算到关键帧右边，
    Blender 的 fcurve 强制"左手柄不能越过自己所在关键帧"这条约束会把这种越界值悄悄
    钳回一个很小的正偏移——这不是"语义假设还没验证"那类不确定性，是可以现在就实测
    抓出来的机械 bug：`tools/verify_blender_clip_fcurve.py` 的"不编辑直接导出"字节比对
    第一次跑就抓到了它（诊断过程见该脚本的 git 历史/PR 说明）。"""
    scale = _HERMITE_TO_BEZIER_HANDLE_SCALE
    handle_right = (frame_time + tangent["out_x"] * scale, value + tangent["out_y"] * scale)
    handle_left = (frame_time + tangent["in_x"] * scale, value + tangent["in_y"] * scale)
    return handle_left, handle_right


def _handles_to_tangent(frame_time, value, handle_left, handle_right):
    """`_tangent_to_handles()` 的反函数——贝塞尔控制点偏移 ×3 换回 Hermite 切线。"""
    scale = 1.0 / _HERMITE_TO_BEZIER_HANDLE_SCALE  # == 3.0
    return {
        "out_x": (handle_right[0] - frame_time) * scale,
        "out_y": (handle_right[1] - value) * scale,
        "in_x": (handle_left[0] - frame_time) * scale,
        "in_y": (handle_left[1] - value) * scale,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 导入 / 导出
# ─────────────────────────────────────────────────────────────────────────────

def import_curve(obj, curve_item, frame_entries: list) -> None:
    """从解析出的一条曲线的关键帧数据建 fcurve。`frame_entries` 每项是
    `{"frame_time": float, "interp_type": int, "value": float, "tangent": dict|None}`
    （`tangent` 只在 `interp_type == 5` 时有值），已经按帧号升序排好。

    调用前必须先 `add_channel()` 分配好这条曲线的 fcurve（synthetic 通道还要先分配好
    `curve_item.channel_key`）。Position/Scale bit 写进宿主对象自己的原生 Location/Scale
    时要乘 `_xform_target()` 给的符号（`coords.py` 的分量置换里，Position.Z 那一路带负号，
    见 `_TRANSFORM3D_CLIP_XFORM` 的说明）——贝塞尔切线的 `out_y`/`in_y` 是"值方向"的增量，
    要跟着值一起乘同一个符号才能让换算后的手柄位置还对得上。"""
    xform = _xform_target(obj, curve_item.bit_index)
    if xform is not None:
        target, data_path, index, sign = xform
        act = ensure_action(target)
        fcs = _act_fcurves(act, target, create=True)
        fc = fcs.find(data_path, index=index)
        if fc is None:
            fc = fcs.new(data_path, index=index)
    else:
        sign = 1.0
        act = ensure_action(obj)
        fcs = _act_fcurves(act, obj, create=True)
        data_path = _channel_data_path(curve_item.channel_key)
        fc = fcs.find(data_path, index=0)
        if fc is None:
            fc = fcs.new(data_path, index=0)

    while len(fc.keyframe_points):
        fc.keyframe_points.remove(fc.keyframe_points[-1], fast=True)

    for entry in frame_entries:
        frame_time = entry["frame_time"]
        value = entry["value"] * sign
        raw_type = entry["interp_type"]
        blender_interp = _INTERP_MHWS_TO_BLENDER.get(raw_type)
        if blender_interp is None:
            # 不悄悄退成 CONSTANT——那样会在用户毫无察觉的情况下把这一帧的真实插值类型
            # 换成一个我们瞎编的形状，再原样导出回去就是静默数据损坏（铁律 #1/#2）。2026-09-19
            # 收窄之后，会走到这里的只剩 `7`（真 Bezier，涉及切线数据消费顺序的未决问题，见
            # 模块文档"raw=7 的导出限制"一节）和真正没见过的未来值——`0/1/2/3/4/5/6/8/9/
            # 10/11/12/13` 现在全部有映射（标准 4 个 + 非标准 9 个借用的占位名字），`7` 是
            # 唯一还需要先解决切线消费顺序才能放行的。真遇到了就是拿到一个我们完全没有把握
            # 的原始类型，该整文件拒绝导入，不该带着编造的形状继续。
            raise ClipFcurveError(
                f"Clip 关键帧用了当前映射表里没有的插值类型 {raw_type!r}"
                f"（bit{curve_item.bit_index}，frame {frame_time}）——拒绝导入，不猜一个"
                f"形状顶上去。见 clip_fcurve._INTERP_MHWS_TO_BLENDER 的说明。"
            )
        kp = fc.keyframe_points.insert(frame_time, value, options={"FAST"})
        kp.interpolation = blender_interp
        tangent = entry.get("tangent")
        if tangent is not None:
            kp.handle_left_type = "FREE"
            kp.handle_right_type = "FREE"
            signed_tangent = dict(tangent, out_y=tangent["out_y"] * sign, in_y=tangent["in_y"] * sign)
            kp.handle_left, kp.handle_right = _tangent_to_handles(frame_time, value, signed_tangent)
    fc.update()


def export_curve(obj, curve_item) -> tuple:
    """`import_curve()` 的反函数。返回 `(header_dict, frame_dicts, tangent_dicts)`，
    形状与 `io_tree._export_clip_attribute()` 现有的 `clips`/`frames`/`interpolationData`
    元素完全一致，调用方直接 `extend()`。Position/Scale bit 要把 `_xform_target()` 的符号
    除回去（符号只有 ±1，除等于再乘一次）才能还原成游戏侧的原始分量，见 `import_curve()`
    的说明。"""
    value_type = int(curve_item.value_type)
    fc = _find_fcurve(obj, curve_item)
    if fc is None:
        raise ClipFcurveError(
            f"Clip 曲线 bit{curve_item.bit_index} 没有对应的 fcurve，导出会丢失关键帧数据——"
            f"这不应该发生，请删除这条曲线后重新添加"
        )
    xform = _xform_target(obj, curve_item.bit_index)
    sign = xform[3] if xform is not None else 1.0

    frames = []
    tangents = []
    keyframe_points = sorted(fc.keyframe_points, key=lambda kp: kp.co[0])
    for kp in keyframe_points:
        frame_time = model.json_float_out(kp.co[0])
        value = kp.co[1] * sign
        interp_type = _INTERP_BLENDER_TO_MHWS.get(kp.interpolation)
        if interp_type is None:
            raise ClipFcurveError(
                f"Clip 曲线 bit{curve_item.bit_index} 用了不支持的插值类型 "
                f"'{kp.interpolation}'（导出前的校验本该拦住这个，见 "
                f"io_tree.check_clip_interpolations()）"
            )
        if value_type == 3:  # Int：IntValue 的 setter 是死代码，只能靠 FloatValue 位转换
            float_value = model.int_bits_to_float(int(round(value)))
        else:
            float_value = model.json_float_out(value)
        frames.append({
            "IntValue": 0,
            "FloatValue": float_value,
            "frameTime": frame_time,
            "type": interp_type,
        })
        if interp_type == _CLIP_HERMITE_TYPE:
            tangent = _handles_to_tangent(kp.co[0], kp.co[1], kp.handle_left, kp.handle_right)
            tangent["out_y"] *= sign
            tangent["in_y"] *= sign
            tangents.append(tangent)

    header = {"frameCount": len(frames), "valueType": value_type}
    return header, frames, tangents


def keyframe_count(obj, curve_item) -> int:
    fc = _find_fcurve(obj, curve_item)
    return len(fc.keyframe_points) if fc is not None else 0


def describe_channel(obj, curve_item) -> str:
    """给面板显示"这条曲线的关键帧实际挂在哪"——xform 通道挂在 `obj.parent` 的原生
    Location/Scale 上，容易和"应该选中这个 attribute 对象本身"的默认认知反着来，必须在
    面板上点破，不然用户在 Dope Sheet 里选错对象、看不到关键帧，会以为是插件的 bug。
    非 xform 通道返回空串（走默认提示即可）。"""
    xform = _xform_target(obj, curve_item.bit_index)
    if xform is None:
        return ""
    target, data_path, index, sign = xform
    axis = "XYZ"[index]
    prop = "Location" if data_path == "location" else "Scale"
    note = "（取反）" if sign < 0 else ""
    return f"{target.name} · {prop} {axis}{note}"


#: 2026-09-19 用户拍板：导出闸门只认 Blender 原生这三个真实语义的插值——不管
#: `_INTERP_MHWS_TO_BLENDER` 映射表里还挂着什么占位名字。`3`(Event) 借用的 `SINE` 占位
#: **故意不在这个允许列表里**——它不是真的正弦缓动，只是为了导出时能分清 1/3 才借的名字，
#: 不能被这条闸门放过；导出前必须先把它改成这三种真实类型里的一种。这比
#: `_INTERP_BLENDER_TO_MHWS`（只挡真正没见过的名字）更严。
_STANDARD_EXPORT_INTERP = frozenset({"CONSTANT", "LINEAR", "BEZIER"})


def curve_interpolation_issues(obj, curve_item) -> list:
    """扫这条曲线的 fcurve，返回用了 `_STANDARD_EXPORT_INTERP`（Constant/Linear/Bezier）以外
    插值类型的关键帧对应的 Blender 名字列表（去重，含 Event 借用的 SINE）。供
    `io_tree.check_clip_interpolations()` 在导出前拦截用。"""
    fc = _find_fcurve(obj, curve_item)
    if fc is None:
        return []
    bad = {kp.interpolation for kp in fc.keyframe_points
           if kp.interpolation not in _STANDARD_EXPORT_INTERP}
    return sorted(bad)


#: Event(3)/Hermite(5) 借用的 Blender 名字本身不代表任何形状——Event 和 Discrete 曲线外观
#: 分不出区别，Hermite 就是原生 Bezier 关键帧本身，肉眼在 Dope Sheet/Graph Editor 里都
#: 找不出"这个关键帧是哪个原始类型"，只能靠 `kp.interpolation` 反查。
_SPECIAL_INTERP_NAMES = frozenset({_INTERP_MHWS_TO_BLENDER[3], _INTERP_MHWS_TO_BLENDER[5]})


def select_special_keyframes(obj) -> int:
    """选中 `obj` 全部 Clip 曲线里插值类型是 Event(3)/Hermite(5) 的关键帧，先清空同一批
    fcurve 上其它关键帧的选择——方便直接在 Dope Sheet/Graph Editor 里定位它们，不用肉眼
    一个个对照插值下拉框。`Keyframe` 本身不支持自定义属性（`kp["x"]=1` 会直接
    `TypeError: id properties not supported for this type`，实测确认），但这里根本不需要：
    `kp.interpolation` 已经是完整、现成的信号，见 `_SPECIAL_INTERP_NAMES`。纯选择状态操作，
    不碰 `co`/`handle_left`/`handle_right`/`interpolation` 本身，对动画数据零风险。返回
    选中的关键帧总数（0 表示这个 attribute 目前没有 Event/Hermite 关键帧）。"""
    found = 0
    for curve in obj.efx_clip_curves:
        fc = _find_fcurve(obj, curve)
        if fc is None:
            continue
        for kp in fc.keyframe_points:
            hit = kp.interpolation in _SPECIAL_INTERP_NAMES
            kp.select_control_point = hit
            kp.select_left_handle = hit
            kp.select_right_handle = hit
            found += hit
        fc.update()
    return found
