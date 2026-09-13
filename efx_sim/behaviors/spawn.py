# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/spawn.py —— `Spawn`（发射节奏）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `Spawn`，TypeID 15）。P0 只消费其中五个：

    MaxParticles       U32     同时存活上限
    SpawnNum           Int2    **min/max**：每批生成几个
    IntervalFrame      Int2    **min/max**：两批之间隔几帧
    EmitterDelayFrame  Int2    **min/max**：开始发射前等几帧
    LoopNum            RangeI  (静态值, 随机量)：发几批；**0 = 无限**

`Int2{x,y}` 的 min/max 语义来自 `model._MIN_MAX_FIELD_NAMES`（本仓全语料定过的，
`shapes.MIN_MAX_INT2_FIELDS` 是它的镜像）。`LoopNum` 走默认的 (静态值, 随机量)——它是
`RangeI`，**主值在 `r`**（全语料 `(r=1,s=0)` 占 55%、`s != 0` 只占 1.4%），见
docs/SIM_PORT_PLAN.md §8.6。

模型（P0 的假设，写在这里是为了能被推翻）
------------------------------------------
一"批"= 一次生成 `SpawnNum` 个粒子；批与批之间隔 `IntervalFrame` 帧；一共发 `LoopNum` 批，
`LoopNum == 0` 则无限发。`MaxParticles` 是**同时存活**的软上限，满了就跳过这一批。

这是按字段名读出来的最直接一版，**没有实机确认**。`LoopNum` 到底是"批次数"还是"整轮重复
次数"（配合 `UseLoopNumRatio`）尤其没底——上游 EFX-Editor 那边 MHWI 的对应机制是三层结构
（属性 → 轮次 → 个体），MHWs 的字段集不一样，不能照搬它的分支。

**不消费**的字段（非默认值时逐个 note，不猜）
---------------------------------------------
`ParticleInterval`（语义未知）、`UseSpawnFrame`/`SpawnFrame`、`RingBufferMode`、
`UseLoopNumRatio`、`Interpolate`、`DistancePerSpawn`、`UseRevival`/`RevivalNum`/
`RevivalInterval`、`TrySpawnAllParticles`、`SpawnChanceFrame`、`InitializeFull`、
`OriginalMaxParticles`、`mhws_unkn_toggle`。

发射器级的随机（每批重抽的数量 / 间隔）走 `em` 自己的随机流，不占用逐粒子的流——改粒子数
不会扰动发射节奏，改节奏也不会扰动粒子形态，调参时观感稳定。见 `rng.emitter_stream_rng`。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..rng import emitter_stream_rng
from ..stages import FORCE

TYPE_NAME = "Spawn"

#: 不消费的字段 -> (读法, 默认值)。非默认值就 note 一条。
#: 读法 'b'=bool / 'i'=int / 'f'=float / 'sr'=Range 对 / 'xy'=Int2 对
_UNUSED_FIELDS = (
    ("ParticleInterval", "i", 0),
    ("UseSpawnFrame", "b", False),
    ("RingBufferMode", "b", False),
    ("UseLoopNumRatio", "b", False),
    ("Interpolate", "b", False),
    ("UseRevival", "b", False),
    ("TrySpawnAllParticles", "b", False),
    ("SpawnChanceFrame", "i", 0),
    ("InitializeFull", "b", False),
)


@register(TYPE_NAME)
class Spawn(Behavior):
    """只跑发射器时间轴，不参与逐粒子 step。"""

    STAGE = FORCE
    ORDER = 0

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        srng = emitter_stream_rng(em.seed)
        loops_static, loops_random = f.sr("LoopNum")
        loops = int(round(loops_static + srng.uniform(0.0, loops_random)))

        em.user[Spawn] = {
            "rng": srng,
            "wait": max(0, f.roll_min_max_int("EmitterDelayFrame", srng)),
            "bursts_left": None if loops <= 0 else loops,   # None = 无限
            "done": False,
        }
        self._note_unused(f, em)

    def on_emitter_step(self, em):
        f = em.f(TYPE_NAME)
        st = em.user.get(Spawn)
        if f is None or st is None or st["done"]:
            return

        if st["wait"] > 0:
            st["wait"] -= 1
            return

        # MaxParticles 是**同时存活**的软上限：满了就跳过这一批，但节奏照走
        # （另一种可能是"等到有空位再补"，未验证——换法只需把下面这段挪到扣批次之后）。
        cap = f.i("MaxParticles")
        n = max(0, f.roll_min_max_int("SpawnNum", st["rng"]))
        if cap > 0:
            room = cap - em.alive_count
            if room <= 0:
                n = 0
            elif n > room:
                n = room
        em.request_spawn(n)

        if st["bursts_left"] is not None:
            st["bursts_left"] -= 1
            if st["bursts_left"] <= 0:
                st["done"] = True
                return
        st["wait"] = max(0, f.roll_min_max_int("IntervalFrame", st["rng"]))

    def duration_hint(self, em):
        """有限批次时，"播放一次"至少要盖到最后一批发出来（寿命那段由 `Life` 加）。"""
        f = em.f(TYPE_NAME)
        if f is None:
            return 0
        static, random_amount = f.sr("LoopNum")
        loops = int(static + random_amount)
        if loops <= 0:
            return 0                      # 无限：长度由播放器自己定
        delay = f.min_max("EmitterDelayFrame")[1]
        interval = f.min_max("IntervalFrame")[1]
        return int(delay + max(0, loops - 1) * interval)

    # -- 内部 ----------------------------------------------------------------
    @staticmethod
    def _note_unused(f, em):
        for key, kind, default in _UNUSED_FIELDS:
            if not f.has(key):
                continue
            got = f.b(key) if kind == "b" else f.i(key)
            if got != default:
                em.note("Spawn.%s=%s 未参与模拟" % (key, got))
        if f.f("DistancePerSpawn", 1.0) not in (0.0, 1.0):
            em.note("Spawn.DistancePerSpawn=%g 未参与模拟" % f.f("DistancePerSpawn"))
        for key in ("SpawnFrame", "RevivalNum", "RevivalInterval"):
            if f.has(key) and f.sr(key) != (0.0, 0.0):
                em.note("Spawn.%s 非 0，未参与模拟" % key)
