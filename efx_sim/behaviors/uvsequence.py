# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/uvsequence.py —— `UVSequence`（序列帧）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `UVSequence`，TypeID 89）：

    SequenceNo   RangeI   用 `.uvs` 里的第几条序列
    PatternNo    RangeI   **起始帧号的范围**（不是播放区间！见下）
    PlaySpeed    Range    **(min, max)**：播放速度，逐粒子在区间里抽一次
    Flags        U32      位域：播放模式 / 翻转 / 方向 / 朝向
    UVSPath      String   `.uvs` 的**游戏内部路径**，帧表由胶水层解析好经 `SimResources` 注入

`PatternNo` 是"从第几帧起手"，不是"只在这几帧之间播"
----------------------------------------------------
每个粒子出生时在 `[Min, Max)` 里抽一个**起始帧**，然后从那里**沿整条序列**往下播。
`Min=0 / Max=1` 就是"全体从第 0 帧起手"——**不是"只显示第 0 帧"**（那是 `Flags`
的播放模式 0 管的事）。按播放区间读的话，全语料 21435 个 `Max=1` 的实例会整片卡在
开头一两格不动，这正是"UVS 不播动画"的成因。

区间是**左闭右开 `[r, s)`**（RangeI 的实测结论，PLAN.md:323）：全语料 `s` 最小取 1、
从不取 0，`s == r + 1` 即"固定起手"。

`Flags` 位域（`semantics/mhws_field_labels.json` 的 `UVSequence.Flags`，与 MHWI 的
`loopingMode` 同构）
--------------------------------------------------------------------------------
    bit0-1  播放模式   0 只显示起始帧 / 1 循环 / 2 播一次后消失 / 3 播一次后定格
    bit2-3  水平翻转   0 不翻 / 1 固定翻 / 2 随机翻      <- 未模拟
    bit4-5  垂直翻转   同上                              <- 未模拟
    bit6-7  播放方向   0 正放 / 1 倒放 / 2 随机
    bit8-9  贴图朝向   0 正常 / 1 顺时针 90° / 2 逆时针 90°  <- 未模拟

全语料 66170 个实例按播放模式分布：只显示起始帧 12241 / 循环 42330 / 播一次后消失
10544 / 播一次后定格 1055——四档都是主流量级，不读 `Flags` 就有 35% 的实例播错。

翻转和朝向要改的是 UV 的**四个角**（换角序 / 转 90°），`RenderItem` 现在只有一个
`uv_rect`，胶水层 `_quad_uvs()` 从矩形推四角。没有四角通道就实现不了，先 note 出来，
不偷偷按"不翻"糊过去。

待标定
------
- `SimConfig.uvs_speed_unit`：`PlaySpeed` 是"每帧推进几帧序列"（`per_frame`，默认）还是
  "每秒推进几帧"。默认按帧：全语料 `PlaySpeed` 中位 1.0 左右，64 帧的序列按帧读正好约
  1 秒播完一轮，量级合理；按秒读则 64 秒一轮，明显不对。
- `SimConfig.uvs_once_span`：播一次（模式 2/3）算几格——从起始帧走到序列末尾（`to_end`，
  默认，同姊妹项目）还是不论起点都走满整条序列（`full_cycle`）。
- `SimConfig.uvs_playback`：`flags`（默认，按上表读）或强制 `loop` / `hold`，标定对照用。
- 时钟用**粒子年龄**。另一种可能是发射器时间轴（全体同步），没实测。

没有帧表时不猜
--------------
胶水层拿不到 `.uvs`（路径解析不到 / 没配游戏目录）时 `SimResources` 是空的——那就**什么都
不写**，note 一条，让渲染体按整张贴图画。不编一个 0~1 的矩形冒充帧表。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import math

from ..registry import Behavior, register
from ..stages import RENDER_MOD

TYPE_NAME = "UVSequence"

# -- Flags bit0-1：播放模式 --------------------------------------------------
PB_START_ONLY = 0
PB_LOOP = 1
PB_ONCE_VANISH = 2
PB_ONCE_HOLD = 3

# -- Flags bit6-7：播放方向 --------------------------------------------------
DIR_FORWARD = 0
DIR_REVERSE = 1
DIR_RANDOM = 2

#: 未模拟的位（水平翻转 / 垂直翻转 / 贴图朝向 / 最高位未知）——非零就 note
_UNSIMULATED_BITS = 0b1111111100


def _start_frame(f, rng):
    """`PatternNo` 的 `[Min, Max)` -> 这个粒子的起始帧。

    左闭右开那一下**不在这里做**：走 `FieldView.roll_sr_min_max_int()`，上界开闭由
    `shapes.HALF_OPEN_MAX_FIELDS` 说了算。早先这里是一句光秃秃的 `hi - 1`，等于把
    "`PatternNo` 是半开的"这条知识埋在一个 behavior 的私有函数里——而 `PartsStartNo`
    是一模一样的约定，下一个实现它的人从 `sr_min_max()` 拿到的是裸 `(min, max)`，
    不会知道要减一。
    """
    return f.roll_sr_min_max_int("PatternNo", rng)


@register(TYPE_NAME)
class UVSequence(Behavior):
    """RENDER_MOD 阶段：把当前帧的 UV 矩形和贴图标识写到上游产出的 `RenderItem` 上。"""

    STAGE = RENDER_MOD
    ORDER = 10

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        if em.resources.empty:
            path = f.s("UVSPath")
            em.note("UVSequence 没有帧表可用（%s），按整张贴图绘制"
                    % (path or "UVSPath 为空"))
        unsimulated = int(f.i("Flags") or 0) & _UNSIMULATED_BITS
        if unsimulated:
            em.note("UVSequence.Flags 的翻转/朝向位（0x%X）未模拟：预览不做 UV 翻转和 90° 旋转"
                    % unsimulated)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        seq_index, _companion = f.sr_index("SequenceNo")
        speed_lo, speed_hi = f.sr_min_max("PlaySpeed")
        flags = int(f.i("Flags") or 0)

        direction = (flags >> 6) & 0x3
        if direction == DIR_RANDOM:
            sign = -1 if rng.random() < 0.5 else 1
        elif direction == DIR_REVERSE:
            sign = -1
        else:
            sign = 1

        p.rolled["uvs_seq"] = int(seq_index)
        # 起始帧在出生时抽定，播放期间不重抽
        p.rolled["uvs_start"] = _start_frame(f, rng)
        p.rolled["uvs_mode"] = flags & 0x3
        p.rolled["uvs_sign"] = sign
        p.rolled["uvs_speed"] = rng.uniform(min(speed_lo, speed_hi),
                                            max(speed_lo, speed_hi))

    def on_particle_step(self, p, em):
        """播一次后消失（模式 2）：走完一轮就把粒子杀掉。

        **这是 `UVSequence` 唯一会影响寿命的地方**，所以必须在 step 里做——`build_render()`
        会被重复调用（暂停时转视角就重跑一遍），不能在那儿改存活状态。这里只按 `p.age`
        推导，同一帧重复调用结论一致。
        """
        if self._mode(p, em) != PB_ONCE_VANISH:
            return
        n = self._frame_count(p, em)
        if n <= 0:
            return
        if self._advanced(p, em) > self._once_span(p, em, n):
            p.alive = False

    def build_render(self, p, em, view, item):
        if item is None:
            return item
        res = em.resources
        if res.empty:
            return item
        if item.kind not in ("BILLBOARD", "PLANE"):
            # `item.uv_rect`/`item.tex_key` 只有 `_collect()` 里画单张四边形贴图的那条路
            # （BILLBOARD/PLANE，走 `_quad_uvs()`）会读。`RIBBON`（`TypeRibbonLength`/
            # `TypeRibbonFollow`/`TypeGpuRibbonLength`，P0 明确"只画等宽等色的折线"，
            # `_collect_ribbon()` 恒写 `uv=(0,0)`）和 `MESH`（有自己的逐三角形 UV，见
            # `_collect_mesh()`）硬套上这里的贴图，会把整条帯/整个网格按"UV 恒为
            # (0,0)"采样成同一个像素——原来就是这么把 `TypeRibbonFollow` 悄悄画没的：
            # 采样点正好落在贴图的透明角上，几何/颜色都对，就是看不见。`POINT`（渲染体
            # 没实现时的退化点）本来就恒定按纯色画（`_collect()` 里 `key = None`），
            # 贴不贴都没区别，一并跳过。
            em.note("UVSequence 只对单张四边形贴图的渲染体生效，%s 这种渲染体不套用序列帧"
                    "贴图（避免用固定 UV (0,0) 把整个几何体采样成同一个像素）" % item.kind)
            return item

        frames = res.frames(p.rolled.get("uvs_seq", 0))
        if frames is None:
            # 序列下标越界：**不退回第 0 条**——那会画出一个看着正常、其实是别的动画的结果。
            em.note("UVSequence.SequenceNo=%s 在帧表里不存在（共 %d 条），该粒子不改 UV"
                    % (p.rolled.get("uvs_seq"), len(res.sequences)))
            return item
        n = len(frames)
        if n <= 0:
            return item

        idx = self._frame_index(p, em, n)
        frame = frames[idx]
        item.uv_rect = frame.as_rect()
        key = res.texture_key(frame.texture_index)
        if key is not None:
            item.tex_key = key
        item.extra["uvs_frame"] = idx
        item.extra["uvs_n"] = n
        return item

    # -- 帧号推导（全部只读 `p.age`，无累积状态）---------------------------
    @staticmethod
    def _mode(p, em):
        """生效的播放模式：默认按 `Flags` 读，配置里可以强制覆盖（标定对照用）。"""
        forced = getattr(em.config, "uvs_playback", "flags")
        if forced == "loop":
            return PB_LOOP
        if forced == "hold":
            return PB_ONCE_HOLD
        return p.rolled.get("uvs_mode", PB_LOOP)

    @staticmethod
    def _frame_count(p, em):
        frames = em.resources.frames(p.rolled.get("uvs_seq", 0))
        return len(frames) if frames else 0

    @staticmethod
    def _advanced(p, em):
        """到这一帧为止推进了几格（不含方向、不含回绕）。"""
        t = p.age * p.rolled.get("uvs_speed", 1.0)
        if em.config.uvs_speed_unit == "per_second":
            # 不能借 `config.dt()`：那个只在 `velocity_unit == per_second` 时才是 1/fps，
            # 跟着速度那个开关走会让这里的"每秒"随着另一个无关开关变成"每帧"。
            t /= float(em.config.fps or 60)
        return int(math.floor(abs(t)))

    @staticmethod
    def _once_span(p, em, n):
        """“播一次”走几格。"""
        if em.config.uvs_once_span == "full_cycle":
            return n - 1
        start = int(p.rolled.get("uvs_start", 0)) % n
        if p.rolled.get("uvs_sign", 1) < 0:
            return start                # 倒着走到第 0 格
        return n - 1 - start            # 正着走到末格

    def _frame_index(self, p, em, n):
        start = int(p.rolled.get("uvs_start", 0)) % n
        mode = self._mode(p, em)
        if mode == PB_START_ONLY:
            return start
        sign = 1 if p.rolled.get("uvs_sign", 1) >= 0 else -1
        adv = self._advanced(p, em)
        if mode != PB_LOOP:
            # 播一次（消亡 / 定格）：夹在这一轮的终点。`full_cycle` 下终点可能越出帧数
            # （起点非 0 时），靠下面的取模收回 [0, n)。
            adv = min(adv, self._once_span(p, em, n))
        return (start + sign * adv) % n

    def duration_hint(self, em):
        """一轮序列播完要多少帧——“播放一次”至少该让序列走完一遍。"""
        f = em.f(TYPE_NAME)
        if f is None or em.resources.empty:
            return 0
        if (int(f.i("Flags") or 0) & 0x3) == PB_START_ONLY:
            return 0                    # 只显示起始帧，没有“一轮”可言
        seq_index, _companion = f.sr_index("SequenceNo")
        frames = em.resources.frames(int(seq_index))
        if not frames:
            return 0
        speed_lo, _speed_hi = f.sr_min_max("PlaySpeed")
        speed = max(1e-6, abs(speed_lo))
        return int(len(frames) / speed)
