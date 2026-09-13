# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/life.py —— `Life`（寿命与淡入淡出）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `Life`，TypeID 87）：

    AppearFrame / KeepFrame / VanishFrame / KeepHoldFrame   RangeI
    Flags                                                   U32

四个 `RangeI` 是 **(min, max) 区间**，不是 (静态值, 随机量)
----------------------------------------------------------
全语料 91178 个实例里 `r > s` 出现 **0 次**（同为 `RangeI` 的 `Spawn.LoopNum` 有 74.7%），
而且 `r == s`（两端填一样 = 不随机）占 71~99.8%——所以绝大多数文件的寿命是**定值**，
"寿命有随机性"这件事很少发生。证据见 docs/SIM_PORT_PLAN.md §8.6，读法走
`FieldView.min_max_pair()`（`shapes.PAIR_MIN_MAX_FIELDS` 里有这四个）。

待标定
------
- `SimConfig.life_model`：总寿命 = Appear + Keep + Vanish（`sum`，默认），还是 Keep 本身
  就是总长、出现/消失包含在内（`keep`）。
- `SimConfig.keep_hold_frame`：`KeepHoldFrame` 语义未知，默认不参与寿命（`ignore`）。

`Flags` 是"持续开关"：1 = 无限寿命
------------------------------------
知识表标的是 confirmed：「0=关闭，1=**特效变为持续性**；罕见情况取值为 2（语义未知）」，
证据是 010 模板 `RE_EFX_STRUCTS.btx` 里 `ContinuesSwitch` 的字段注释「0关闭1特效变为持续性」
（另两处同名字段注释「改1变持续」）。**关掉的是"持续性"，不是 Life 属性本身。**

姊妹项目 EFX-Editor 的 `LIFE` 有一个独立的 `Bool("indefiniteLifespan", label_zh="无限寿命")`
——同一个概念，MHWs 把它折进了 `Flags`。

语料按 `Flags` 分桶独立支持这个读法（Flags=1 桶里三个时长字段明显"无所谓"）：

                      AppearFrame=0   KeepFrame=0   VanishFrame=0   distinct(Keep)
    Flags=0 n=76188       53.6%          16.6%          8.3%             176
    Flags=1 n=14324       71.0%          32.0%         47.3%              57

`VanishFrame` 为 0 的比例差 5.7 倍、取值种类只有三分之一——寿命被忽略该有的样子。

所以：**`Flags == 1` -> 不按寿命判死**（`p.life = 0`），淡入照常、**没有淡出**（没有终点可
淡向；真实的结束是外部停止发射器，预览里模拟不了，非零 `VanishFrame` 会 note 一条）。
`Flags == 2` 只有 0.7%、语义未知 -> 按 0 处理并 note。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import SHADE

TYPE_NAME = "Life"

FLAG_NORMAL = 0        # 正常寿命
FLAG_CONTINUOUS = 1    # 持续性 = 无限寿命


@register(TYPE_NAME)
class Life(Behavior):
    """写 alpha（SHADE 阶段），并负责把粒子标成死亡。"""

    STAGE = SHADE
    ORDER = 10      # 淡入淡出是基准 alpha，别的调制（Blink 等）排在后面

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        cfg = em.config

        appear = max(0, f.roll_min_max_pair_int("AppearFrame", rng))
        keep = max(0, f.roll_min_max_pair_int("KeepFrame", rng))
        vanish = max(0, f.roll_min_max_pair_int("VanishFrame", rng))

        if cfg.life_model == "keep":
            total = keep
            vanish = min(vanish, max(0, total - appear))   # 淡出段贴着总长的尾巴
        else:                                              # 'sum'（默认）
            total = appear + keep + vanish

        if cfg.keep_hold_frame == "add":
            total += max(0, f.roll_min_max_pair_int("KeepHoldFrame", rng))
        elif f.min_max_pair("KeepHoldFrame") != (0.0, 0.0):
            em.note("Life.KeepHoldFrame 非 0，语义未知，未参与寿命计算")

        flags = f.i("Flags")
        if flags == FLAG_CONTINUOUS:
            # 持续性：不按寿命判死。淡入照常，淡出取消——没有终点可淡向。
            p.rolled["life_continuous"] = True
            p.rolled["life_vanish"] = 0
            p.life = 0
            if vanish:
                em.note("Life 是持续性（Flags=1），VanishFrame 未参与模拟"
                        "（真实的结束是外部停止发射器，预览里模拟不了）")
        elif flags not in (FLAG_NORMAL, FLAG_CONTINUOUS):
            em.note("Life.Flags=%d 语义未知（全语料 0.7%%），按 0（正常寿命）处理" % flags)

        p.rolled["life_appear"] = appear
        p.rolled["life_vanish"] = p.rolled.get("life_vanish", vanish)
        p.rolled["life_total"] = total
        if not p.rolled.get("life_continuous"):
            p.life = total

    def on_particle_step(self, p, em):
        continuous = p.rolled.get("life_continuous", False)
        total = 0 if continuous else p.rolled.get("life_total", 0)
        appear = p.rolled.get("life_appear", 0)
        vanish = p.rolled.get("life_vanish", 0)

        # total == 0 -> 不按寿命判死（该 entry 没给寿命，交给别的属性或者一直活着）
        if total > 0 and p.age >= total:
            p.alive = False
            p.alpha = 0.0
            return

        a = 1.0
        if appear > 0 and p.age < appear:
            a = float(p.age) / float(appear)
        elif total > 0 and vanish > 0:
            fade_start = total - vanish
            if p.age >= fade_start:
                a = max(0.0, float(total - p.age) / float(vanish))
        p.alpha = a

    def duration_hint(self, em):
        """"播放一次"至少要盖住最长的那条寿命（按 max 端算，不抽随机）。"""
        f = em.f(TYPE_NAME)
        if f is None:
            return 0
        if f.i("Flags") == FLAG_CONTINUOUS:
            return 0                      # 持续性：没有自然终点，长度由播放器自己定
        total = sum(f.min_max_pair(k)[1] for k in ("AppearFrame", "KeepFrame", "VanishFrame"))
        return int(total)
