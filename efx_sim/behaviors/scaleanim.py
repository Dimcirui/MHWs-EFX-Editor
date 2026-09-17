# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/scaleanim.py —— `ScaleAnim`（逐帧缩放动画，写 `p.scale`）

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/behaviors/scaleanim.py`：两组独立的
**"加法累积 + 逐帧乘法衰减"**，和 `Velocity3D` 的 `GravityRate`(加)+`SpeedCoef`(乘) 是
同一个形状——"Add" 是每帧加到 `p.scale` 上的量，"…Coef"/"…AddCoef" 是这个量**本身**每帧要
乘一次的系数（1=不变，<1 衰减，>1 越滚越大）。这套读法不是猜的：上游用户在 test.efx
上实测过（官方 TimelineParam 通道名就叫 `SizeScalarAdd`/`SizeXAdd`/`SizeYAdd`/`SizeZAdd`，
"Add" 写在名字里），MHWs 这边字段名与之逐个对应（`SizeScalarCoef`/`SizeXAddCoef` 这些）。

    整体（三轴同步）   SizeScalarAdd + SizeScalarCoef
    逐轴               SizeXAdd/SizeYAdd/SizeZAdd + 各自的 …AddCoef
    SizeDelayFrame     只挡**逐轴**那组，不影响整体那组（照抄上游 `animUpdateStart`
                       的先例——两组是否共用一个延迟没有实测，先按上游的分法来）

**加在 `p.scale` 这个从 1 起的归一化倍率上**，不是加在某个具体渲染体自己的尺寸字段上。
上游有两条路（'size' 直接加尺寸字段、只给 BILLBOARD3D 接了；'multiplier' 加归一化倍率，
其余渲染体都走这条）——MHWs 这边从第一个渲染体（`TypeBillboard3D`）开始就统一把 `p.scale`
当乘数用（`size.x * p.scale.x`），`TypePolygon`/`TypeRibbonLength`/`TypeMeshV2` 全部照此
约定，天生只有"multiplier"这一条路可选，不需要 `scaleanim_add_target` 那样的开关。

`ScaleAnimDelayFrame`（TypeID 89，独立的伴生属性，不是 `ScaleAnim` 自己的字段）
------------------------------------------------------------------------------
只有 `frameDelay`/`unkn2` 两个字段，没有实机验证，但"某某DelayFrame 是主属性的整体启动
延迟"在这个格式里是常见命名思路（`Velocity3D.SpeedDelayFrame`/`GravityDelayFrame`、
`Spawn.EmitterDelayFrame` 都是这个思路）。这里按**整体延迟**处理——两组（整体/逐轴）
一起等 `frameDelay` 帧，等完了逐轴那组再单独叠加自己的 `SizeDelayFrame`。`unkn2` 非 0 时
note，不消费。

这个属性没有自己的模拟逻辑——它的数据由 `ScaleAnim` 在 spawn 时顺手读一下
（`em.f("ScaleAnimDelayFrame")`），但仍然要注册一个空壳类占住这个类型名：不注册的话
`build_behaviors()` 会把它记进 `unsupported`，而它的数据其实被消费了（只是消费者是
`ScaleAnim`，不是它自己），那样报"未模拟"就是误报。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import XFORM

TYPE_NAME = "ScaleAnim"
DELAY_TYPE_NAME = "ScaleAnimDelayFrame"


@register(DELAY_TYPE_NAME)
class ScaleAnimDelayFrame(Behavior):
    """没有自己的钩子——`ScaleAnim` 直接读它的字段（见模块说明）。注册只是为了不被
    误报成"未模拟"：它的数据确实被消费了，只是消费者是 `ScaleAnim`。"""

    STAGE = XFORM


@register(TYPE_NAME)
class ScaleAnim(Behavior):
    """XFORM 阶段：写 p.scale。"""

    STAGE = XFORM
    ORDER = 100

    def on_emitter_init(self, em, rng):
        if em.f(TYPE_NAME) is None:
            return
        delay_f = em.f(DELAY_TYPE_NAME)
        if delay_f is not None and delay_f.i("unkn2"):
            em.note("ScaleAnimDelayFrame.unkn2=%d 未参与模拟（取值语义未确认）"
                    % delay_f.i("unkn2"))

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist

        # `frameDelay` 是 U32（**不是** Range），没有随机分量，直接读整数。
        delay_f = em.f(DELAY_TYPE_NAME)
        start_delay = max(0, delay_f.i("frameDelay")) if delay_f is not None else 0

        uv = f.roll("SizeScalarAdd", rng, mode)
        ua = f.roll("SizeScalarCoef", rng, mode, default=(1.0, 0.0))

        axis_v = [f.roll("SizeXAdd", rng, mode), f.roll("SizeYAdd", rng, mode),
                 f.roll("SizeZAdd", rng, mode)]
        axis_a = [f.roll("SizeXAddCoef", rng, mode, default=(1.0, 0.0)),
                 f.roll("SizeYAddCoef", rng, mode, default=(1.0, 0.0)),
                 f.roll("SizeZAddCoef", rng, mode, default=(1.0, 0.0))]
        axis_delay = start_delay + max(0, f.roll_int("SizeDelayFrame", rng, mode))

        p.user[ScaleAnim] = {"uv": uv, "ua": ua, "av": axis_v, "aa": axis_a,
                             "start_delay": start_delay, "axis_delay": axis_delay}

    def on_particle_step(self, p, em):
        st = p.user.get(ScaleAnim)
        if st is None or p.age < st["start_delay"]:
            return

        # ① 整体：三轴同步加同一个量
        uv = st["uv"]
        if uv:
            p.scale.x += uv
            p.scale.y += uv
            p.scale.z += uv
        st["uv"] = uv * st["ua"]

        # ② 逐轴：过了 start_delay + SizeDelayFrame 才开始
        if p.age < st["axis_delay"]:
            return
        av, aa = st["av"], st["aa"]
        if av[0]:
            p.scale.x += av[0]
        if av[1]:
            p.scale.y += av[1]
        if av[2]:
            p.scale.z += av[2]
        av[0] *= aa[0]
        av[1] *= aa[1]
        av[2] *= aa[2]
