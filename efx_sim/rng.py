# -*- coding: utf-8 -*-
"""
efx_sim/rng.py —— 随机量抽取 + 确定性噪声

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/rng.py`（见 docs/SIM_PORT_PLAN.md §4.1）。

两条规矩，都是**结构性**的（靠签名而不是靠注释保证）：

1. **随机量只在 spawn/init 抽，抽完存进 `p.rolled`。**
   `Range.r` 是每个粒子出生时定死的一次抽取，不是每帧重抽。
   `Behavior.on_particle_step(self, p, em)` 的签名里**没有 rng**，所以"每帧重抽"在这套 API
   下写不出来。

2. **逐帧随机用确定性噪声，不用随机数抽取。**
   `Noise` / `PtVortexelWind` 这类确实需要逐帧变化的，用 `noise1/noise3`——它们是
   `(seed, frame, channel)` 的纯函数。这样重启必然复现，核心也能脱离 Blender 单测。

命名：`Range{s, r}` 是 Static / Random
--------------------------------------
上游用的是 MHWI 社区习惯的 `值 + 抖动(jitter)`；本仓沿用 REE 惯例的 **Static / Random**
（见 `blender_efx_re/model.py::is_static_random_node()` 的说明，那套命名以后计划回哺到
EFX-Editor）。所以这里的函数叫 `roll_static_random()` 而不是 `jitter()`。

`r` 怎么参与抽取（`RANDOM_DIST`）是未定项
-----------------------------------------
`s` 是静态基准值、`r` 是随机浮动量，这一点本仓已经用全语料定下来了；但**"浮动"具体怎么取
值**（单边 `[s, s+r]`、对称 `[s-r, s+r]`、还是高斯）没有实机确认。默认按单边——这和上游
标定出的 MHWI 结论一致（"在 static 基础上**追加** [0, amount]"），但**那是 MHWI 的实机结论，
不是 MHWs 的**，所以它在 `SimConfig.random_dist` 里是开关，不是常量。

⚠ 语料里 `r` 会出现**负值**（如 `EmitterShape3D.RangeY = {s:-0.2, r:-0.2}`）。单边分布下
`uniform(0, -0.2)` 仍然合法（返回 `[-0.2, 0]`），所以不特判、不取绝对值——但"r 可以为负"
这件事本身是"`(s,r)` 到底是不是 static/random"的反证据之一，见 docs/SIM_PORT_PLAN.md §8.5。

⚠ `r == 0` 时**仍然抽一次**（结果当然等于 s）。故意的：这样把某个字段的 `r` 从 0 改成非 0
时，不会连带打乱其他所有字段抽到的值，编辑体验稳定。代价是随机数流跟游戏对不上——但逐帧
对齐游戏本来就不可达，不值得为它牺牲编辑期的稳定性。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import random

from .state import Vec3

# -- 随机分布 ---------------------------------------------------------------
DIST_ONESIDED  = "onesided"    # s + U[0, r]      <- 默认
DIST_SYMMETRIC = "symmetric"   # s + U[-r, r]
DIST_GAUSSIAN  = "gaussian"    # s + N(0, r / 2)

DIST_MODES = (DIST_ONESIDED, DIST_SYMMETRIC, DIST_GAUSSIAN)

DIST_LABELS = {
    DIST_ONESIDED:  {"EN": "s + U[0, r]",   "ZH": "静态值 + 均匀[0, r]"},
    DIST_SYMMETRIC: {"EN": "s + U[-r, r]",  "ZH": "静态值 + 均匀[-r, r]"},
    DIST_GAUSSIAN:  {"EN": "s + N(0, r/2)", "ZH": "静态值 + 高斯(0, r/2)"},
}


def roll_static_random(static, random_amount, rng, mode=DIST_ONESIDED):
    """`static` 上叠加 `random_amount` 规模的浮动。**所有随机抽取都必须走这里。**

    `rng` 是 `random.Random` 实例（逐粒子播种，见 `particle_rng`）。
    """
    static = float(static)
    random_amount = float(random_amount)
    if mode == DIST_SYMMETRIC:
        return static + rng.uniform(-random_amount, random_amount)
    if mode == DIST_GAUSSIAN:
        return static + rng.gauss(0.0, random_amount * 0.5)
    # DIST_ONESIDED（默认）
    return static + rng.uniform(0.0, random_amount)


def roll_static_random_int(static, random_amount, rng, mode=DIST_ONESIDED):
    """整数字段（帧数一类）：按浮点抽完取整。"""
    return int(round(roll_static_random(static, random_amount, rng, mode)))


def roll_uniform(lo, hi, rng):
    """min/max 形状的字段（`Int2{x,y}`，见 `shapes.MIN_MAX_INT2_FIELDS`）。

    不保证 `lo <= hi`——语料里 max < min 是真实存在的（面板会给崩溃风险提示），
    这里照 `random.uniform` 的行为处理（它对反序区间照样返回区间内的值），不静默交换。
    """
    return rng.uniform(float(lo), float(hi))


def roll_uniform_int(lo, hi, rng):
    lo = int(lo)
    hi = int(hi)
    if lo == hi:
        return lo
    a, b = (lo, hi) if lo <= hi else (hi, lo)
    return rng.randint(a, b)


# ---------------------------------------------------------------------------
# 播种
# ---------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


def _mix64(x):
    """splitmix64 的 finalizer：整数 -> 雪崩良好的 64 位整数。"""
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


def emitter_seed(base_seed, fixed_seeds=()):
    """发射器级种子。

    `fixed_seeds` 预留给 `FixRandomGenerator`（全语料 2.51%，MHWI `RANDOMFIX` 的对应物）。
    **P0 不消费它**——那个属性怎么被游戏取用没有实测，混进种子只能保证"改种子表 → 形态变化"
    这个可观察行为，不假装复现游戏的取用规则。
    """
    h = _mix64(int(base_seed) & _MASK64)
    for s in fixed_seeds:
        h = _mix64(h ^ (int(s) & 0xFFFFFFFF))
    return h


def particle_seed(em_seed, particle_index):
    """逐粒子种子：同一发射器内按序号派生，重启后必然复现。"""
    return _mix64((int(em_seed) ^ (int(particle_index) * 0x2545F4914F6CDD1D)) & _MASK64)


def particle_rng(em_seed, particle_index):
    """给 `on_particle_spawn` 用的 rng。"""
    return random.Random(particle_seed(em_seed, particle_index))


def emitter_stream_rng(em_seed):
    """发射器级的随机流（每批粒子数 / 间隔这类**每批**重抽的量）。

    刻意和逐粒子的流分开：改粒子数不会扰动发射节奏，改节奏也不会扰动粒子形态，调参时观感
    稳定。reset 后从同一种子重建，所以照样确定性。
    """
    return random.Random(_mix64((int(em_seed) ^ 0x5EED_E177_5EED_E177) & _MASK64))


# ---------------------------------------------------------------------------
# 确定性噪声（给 on_particle_step 用；不是随机数抽取）
# ---------------------------------------------------------------------------

def noise1(seed, frame, channel=0):
    """(seed, frame, channel) -> [-1, 1] 的白噪声。纯函数，逐帧独立。"""
    h = _mix64((int(seed) & _MASK64) ^ _mix64((int(frame) << 16) ^ int(channel)))
    # h >> 11 取高 53 位 -> [0, 2^53)，除以 2^53 得 [0, 1)，再映到 [-1, 1)
    return (h >> 11) / float(1 << 53) * 2.0 - 1.0


def noise3(seed, frame, channel=0):
    """三分量白噪声向量，各分量独立。"""
    return Vec3(noise1(seed, frame, channel * 3 + 0),
                noise1(seed, frame, channel * 3 + 1),
                noise1(seed, frame, channel * 3 + 2))


def noise_smooth1(seed, t, channel=0, period=8.0):
    """时间上连续的值噪声：整数节点间插值，`period` 帧一个节点。

    需要"飘"而不是"抖"的效果用这个；白噪声逐帧跳变会像噪点。
    """
    if period <= 0.0:
        return noise1(seed, int(t), channel)
    u = float(t) / float(period)
    i = int(u // 1.0)
    f = u - i
    a = noise1(seed, i, channel)
    b = noise1(seed, i + 1, channel)
    f = f * f * (3.0 - 2.0 * f)     # smoothstep，避免线性插值的折角
    return a + (b - a) * f


def noise_smooth3(seed, t, channel=0, period=8.0):
    return Vec3(noise_smooth1(seed, t, channel * 3 + 0, period),
                noise_smooth1(seed, t, channel * 3 + 1, period),
                noise_smooth1(seed, t, channel * 3 + 2, period))
