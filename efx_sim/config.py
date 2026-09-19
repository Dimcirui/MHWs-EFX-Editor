# -*- coding: utf-8 -*-
"""
efx_sim/config.py —— 模拟参数

这个文件的作用不是"配置"，是**把所有未确认的语义收成可调开关**。

`UNKNOWNS` 里每个条目都对应一处"实测才能定"的行为。做成开关而不是写死，是因为标定它们的
方式是在 Blender 里拖一下滑块对拍，不是改代码重装插件——把未知变成参数，标定周期从"一次
编辑-重装-重试"压到"拖一下滑块"。标定完一条，就把默认值改掉、并在 `UNKNOWNS` 里降级成
注释（保留开关，但不再是待办）。

⚠ **这批未知项不是照抄上游的。** 姊妹项目 EFX-Editor 的 13 条 `UNKNOWNS` 是它自己的未知项，
其中一部分在 MHWs 这边已经由语料或 vendor 定死（旋转顺序、角度单位），另一部分则是本仓独有
（`Range.r` 的分布、`KeepHoldFrame`）。见 docs/SIM_PORT_PLAN.md §5.4 / §8。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from . import stages as _stages
from .rng import DIST_SYMMETRIC

#: 待标定项清单：key -> (中文说明, 候选值, 当前默认)
#: UI 可以直接拿它生成一排下拉框；标定完把 default 改掉即可。
UNKNOWNS = {
    "random_dist": (
        "`Range.r`（随机量）怎么参与抽取。`s` 是静态基准、`r` 是浮动量这一点已由全语料定下。"
        "2026-09-17 实机确认 `Velocity3D.Speed` 是对称双向 `[s-r, s+r]`（与 `Attractor.Force`"
        "已确认的公式一致），改按此默认；其余共用这个开关的字段未逐个验证，仍可能有例外。",
        ("onesided", "symmetric", "gaussian"), "symmetric",
    ),
    "life_model": (
        "总寿命怎么算。'sum'=AppearFrame+KeepFrame+VanishFrame；"
        "'keep'=KeepFrame 即总长、出现/消失包含在内。",
        ("sum", "keep"), "sum",
    ),
    "keep_hold_frame": (
        "`Life.KeepHoldFrame`（语义未知）参不参与寿命。",
        ("ignore", "add"), "ignore",
    ),
    "spawn_interval_source": (
        "每批之间隔几帧：读 `IntervalFrame`（Int2 min/max）还是 `ParticleInterval`"
        "（标量，语义未知）。",
        ("interval_frame", "particle_interval"), "interval_frame",
    ),
    "rot_order_applied": (
        "旋转顺序串（如 'ZXY'）里是先写的先作用于向量，还是相反。上游同样未实测。",
        ("forward", "reverse"), "forward",
    ),
    "uvs_speed_unit": (
        "`UVSequence.PlaySpeed` 是每帧推进几帧序列（per_frame，默认）还是每秒推进几帧。"
        "全语料中位 1.0 左右，64 帧的序列按帧读约 1 秒播完一轮，量级合理；按秒读要 64 秒。",
        ("per_frame", "per_second"), "per_frame",
    ),
    "uvs_playback": (
        "播放模式从哪来：'flags'=按 `UVSequence.Flags` 的 bit0-1 读"
        "（0 只显示起始帧 / 1 循环 / 2 播一次后消失 / 3 播一次后定格，默认）；"
        "'loop' / 'hold' = 不看 Flags 全体强制，标定对照用。",
        ("flags", "loop", "hold"), "flags",
    ),
    "uvs_once_span": (
        "播一次（Flags 模式 2 消亡 / 3 定格）算几格：'to_end'=从起始帧走到序列末尾；"
        "'full_cycle'=不论起点都走满整条序列。姊妹项目同样未实测，默认取一致的 to_end。",
        ("to_end", "full_cycle"), "to_end",
    ),
    "velocity_unit": (
        "`Velocity3D.Speed` / `GravityRate` 的时间基：'per_second'=米每秒 / 米每二次方秒"
        "（默认）；'per_frame'=每帧这么多。⚠ `SpeedCoef` **不受这个开关影响**，它是无量纲的"
        "逐帧乘数，恒按帧。",
        ("per_second", "per_frame"), "per_second",
    ),
    "expr_timer_unit": (
        "Expression 公式里 `TIMER` 变量的时间基：'frames'=自 emitter 开始播放以来经过的帧数"
        "（默认，已实机确认）；'seconds'=帧数/fps，对拍用。",
        ("frames", "seconds"), "frames",
    ),
    "expr_clamp_mode": (
        "Expression 公式里 `Clamp(value, hi, lo)` 怎么读："
        "'remap_smoothstep'=把 value 从 [lo, hi] 重映射到 [0, 1]、两端钳、"
        "**中段带 smoothstep 缓动**（默认，已实机确认：拿不经过任何待测函数的线性基准 "
        "`TIMER/100` 对拍，`Clamp` 的残差是 S 形摆动，再和 smoothstep 参考曲线对拍则死平）；"
        "'remap_saturate_both'=同样两端钳但中段**线性**（旧默认，已被实机推翻，留作对拍）；"
        "'remap_saturate_low'=只钳下界（更旧的默认，上界不钳也已被推翻）；"
        "'remap_unclamped'=两端都不钳；'bounds_clamp'=最早的『夹到 [lo, hi] 之间』读法。"
        "⚠ 这个开关**不影响 `Func21`**：它的重映射是线性的，两个函数的差别就是这层缓动。",
        ("remap_smoothstep", "remap_saturate_both", "remap_saturate_low",
         "remap_unclamped", "bounds_clamp"),
        "remap_smoothstep",
    ),
    "expr_unknown_func_policy": (
        "碰到语义未确认的函数怎么办。'identity'=原样透传第一个参数（默认，比返回 0 更"
        "不容易把下游的插值带偏）。⚠ **现在没有这样的函数了**——12 个 `Unary*` 和 "
        "`Func18`~`Func21` 已经全部实机测出语义，这个开关留给 vendor 升级后冒出来的新"
        "函数（或给枚举补上 3/13/14 之后）。",
        ("identity",), "identity",
    ),
}

#: 已定、不再是待办，但保留开关的项（降级区，别再当待办看）
SETTLED = {
    # 角度单位：MHWs 是弧度，已由取值峰值指纹坐实（π 的有理数倍），无开关。
    # 旋转顺序映射：用 vendor 枚举，无开关。见 vecmath.py。
}


class SimConfig(object):
    """一次模拟的全部参数。behavior 通过 `em.config` 读。"""

    __slots__ = (
        "seed", "fps",
        "random_dist", "life_model", "keep_hold_frame", "spawn_interval_source",
        "rot_order_applied", "velocity_unit",
        "uvs_speed_unit", "uvs_playback", "uvs_once_span",
        "expr_timer_unit", "expr_unknown_func_policy", "expr_clamp_mode",
        "disabled", "order_override", "strict",
        "max_particles", "max_frames",
        "stage_order", "render_stage_order",
    )

    def __init__(self, **kw):
        #: 随机种子。改它 = 换一批粒子形态，其余全部确定性复现。
        self.seed = 0

        #: 一帧 = 1/fps 秒。**这是预览的假设，不是文件里的事实**——MHWs 不锁帧，引擎内部
        #: 大概率按 60fps 等效 tick 归一，但这个从语料里查不出来。
        self.fps = 60

        # -- 待标定项（见 UNKNOWNS）-----------------------------------------
        self.random_dist = DIST_SYMMETRIC
        self.life_model = "sum"
        self.keep_hold_frame = "ignore"
        self.spawn_interval_source = "interval_frame"
        self.rot_order_applied = "forward"
        self.velocity_unit = "per_second"
        self.uvs_speed_unit = "per_frame"
        self.uvs_playback = "flags"
        self.uvs_once_span = "to_end"
        self.expr_timer_unit = "frames"
        self.expr_unknown_func_policy = "identity"
        self.expr_clamp_mode = "remap_smoothstep"

        # -- 调试 / 扩展点 ---------------------------------------------------
        #: 属性短类型名集合：强制当作"未模拟"（UI 上逐个勾掉做对照用）
        self.disabled = frozenset()
        #: type_name -> (stage, order)，覆盖 behavior 类上的声明
        self.order_override = {}
        #: 打开后逐调用比对 `stages.STAGE_WRITES`，behavior 写越界即抛
        self.strict = False

        # -- 安全阀 ---------------------------------------------------------
        #: 同时存在的粒子数上限。真实文件的 `Spawn.MaxParticles` 最大到几千，
        #: 预览不是游戏，超了就截断并 note，不跟着卡死。
        self.max_particles = 4000
        #: 单次播放的最大帧数（防 LoopNum=0 的无限循环把预览跑飞）
        self.max_frames = 3600

        self.stage_order = _stages.DEFAULT_STAGE_ORDER
        self.render_stage_order = _stages.DEFAULT_RENDER_STAGE_ORDER

        for k, v in kw.items():
            if k not in self.__slots__:
                raise TypeError("SimConfig 没有参数 %r" % k)
            setattr(self, k, v)

    def dt(self):
        """一帧对应多少"时间单位"。`velocity_unit == 'per_second'` 时是 1/fps 秒，
        否则 1（字段本身就是每帧量）。速度积分和重力叠加都乘它，一套代码覆盖两种读法。"""
        if self.velocity_unit == "per_frame":
            return 1.0
        return 1.0 / float(self.fps or 60)

    def describe_unknowns(self):
        """当前所有待标定项的取值——面板要如实显示这些，预览不装作自己知道。"""
        return {k: getattr(self, k) for k in UNKNOWNS}

    def __repr__(self):
        return "<SimConfig seed=%d fps=%d %s>" % (
            self.seed, self.fps,
            " ".join("%s=%s" % kv for kv in sorted(self.describe_unknowns().items())))
