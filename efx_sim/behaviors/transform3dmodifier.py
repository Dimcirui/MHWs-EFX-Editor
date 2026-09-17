# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/transform3dmodifier.py —— `Transform3DModifier`（Entry 持续变换），P0.5 猜测实现

⚠⚠⚠ **这整个 behavior 都是猜测，没有游戏内实测**（2026-09-17）。55 个字段全部叫
`unkn0~unkn54`，语义来自纯语料统计（取值分布指纹 + 结构对称性推理），置信度只有
`guess`——比本仓其它 behavior 依赖的字段标注低一整档。写这个 behavior 是因为用户明确要求
"先落实、拿真实效果去对拍、错了再改"，不是因为语义已经确认。**每一帧都会 `em.note()`
提醒这一点**，预览面板上一定看得到这行字，不会让用户误以为这是确认过的行为。

字段结构（详见 `blender_efx_re/semantics/mhws_field_labels.json` 对应 evidence）：

    unkn0           位图，猜测是"启用了哪几组子功能"，具体位含义未破解，本 behavior 不读它
                    （所有组统一按"值全 0 = 无效果"处理，等价于开关常开）
    unkn1~unkn6     位移增量（静态随机，一次性）   X/随机 Y/随机 Z/随机
    unkn7~unkn12    旋转增量（静态随机，一次性，弧度）——已通过语料指纹确认到 likely
    unkn13~unkn18   缩放增量（静态随机，一次性）   **叠加在 1.0 基准上**，0=不额外缩放
    unkn19~unkn30   位移速度（持续，每帧叠加）+ 每根轴的变动系数（同 Velocity3D.SpeedCoef
                    模型：系数每帧对速度自乘一次，1=匀速）
    unkn31~unkn42   旋转角速度（持续），同上结构——已通过语料指纹确认到 likely
    unkn43~unkn54   缩放速度（持续，累加式增量，不是乘法倍率——和 unkn13~18 同一套
                    "叠加在 1.0 基准上"的读法），同上结构

时间基未定，按**逐帧**（不乘 `dt`）处理，理由：`Velocity3D.SpeedCoef` 已确认是逐帧乘一次、
不受 `velocity_unit`（per_second/per_frame）影响，这里的"变动系数"字段取值分布和它几乎
同一个模子刻出来的（0.0/~1.0 双峰），推测速度本身也是同一套逐帧模型，不是按秒积分。
**这条假设和字段语义一样未经实测**，跟着 note 一起提醒。

和 `transform3d.py` 的接口约定：两者都写 `em.drift`/`em.rotation_drift`/`em.scale_drift`，
不能互相覆盖——**ORDER 必须比 Transform3D 的 -10 大**（本类用 -5，同一帧内 Transform3D 先
跑），这里读到的是 Transform3D 已经写过的值，往上叠加/相乘，不是推倒重写。`em.drift`/
`em.rotation_drift` 是加法合成，`em.scale_drift` 是乘法合成（比例量）——这两条合成规则和
`transform3d.py` 模块说明里"origin = host_origin + drift"的既有约定一致，缩放的"1.0=不缩放"
基准也是抄它的。

⚠ **`em.has("Transform3D")` 决定当前帧要不要先"退掉"自己上一帧加过的量**：`transform3d.py`
每帧是**整体重算再赋值**（`em.drift = current_pos - base_pos`），不是累加——它在的话，
这一帧轮到我的时候 `em.drift` 已经是它重新算好的干净值，我只管把这一帧该加的量加上去，
不用管上一帧我加过什么。但**这个 entry 完全没有 `Transform3D` 属性**（`efx_sim` 里到处
可见的常态：静态位移/旋转/缩放没人写、只有这个 Modifier 一个 behavior 在动 `em.drift`）
时，压根没人在我之前重置它——`em.drift` 一直是"我上一帧算完留下的那个值"，这时候如果
还是直接 `+=`，我上一帧已经加过的静态增量（`pos_delta` 这种不随时间变化的部分）会被
每一帧重复叠加、线性发散。所以没有 `Transform3D` 时改成"先减掉我上一帧加的总量，再加
这一帧的总量"——`em.user` 记一份"我上次一共加了多少"，代数上等价于每帧都在一个干净
基准上重新算一遍，效果和 `Transform3D` 在场时完全一致，只是没有别人替我们保持这份干净
基准，只能自己维护。缩放同理，只是"减/加"换成"除/乘"。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import FORCE
from ..state import Vec3
from .. import rng as _rng

TYPE_NAME = "Transform3DModifier"

_SCALE_NEUTRAL = Vec3(1.0, 1.0, 1.0)

_STATIC_KEY = "_t3dm_static"          # (pos_delta, rot_delta, scale_delta) 一次性抽样结果
_VEL_KEY = "_t3dm_velocity"           # (pos_vel, pos_coef, rot_vel, rot_coef, scale_vel, scale_coef)
_ACCUM_KEY = "_t3dm_accum"            # (pos_accum, rot_accum, scale_accum) 逐帧累计
_LAST_APPLIED_KEY = "_t3dm_last_applied"  # 上一帧实际加/乘进 em.* 的量，没有 Transform3D 时用来退位
_SCALE_EPS = 1e-6


def _roll_pair(f, value_key, jitter_key, rng, mode):
    """`(值字段, 随机值字段)` 一次性抽样——语义上和 `via.Range` 的 `{s,r}` 是同一件事，
    只是这个结构体把两者存成了两个独立的顶层标量字段，不能走 `f.roll()`（那个函数认的是
    单个 `{s,r}` 复合字段）。"""
    static = f.f(value_key, 0.0)
    jitter = f.f(jitter_key, 0.0)
    return _rng.roll_static_random(static, jitter, rng, mode)


def _roll_axis3(f, keys, rng, mode):
    """三根轴各自 `(值,随机值)` 一对，拼成 Vec3。`keys` 是 `((vx,jx),(vy,jy),(vz,jz))`。"""
    return Vec3(*(_roll_pair(f, vk, jk, rng, mode) for vk, jk in keys))


@register(TYPE_NAME)
class Transform3DModifier(Behavior):
    """FORCE 阶段：叠加位移/旋转/缩放的静态随机增量 + 持续速度，见模块说明。
    ORDER 必须晚于 `Transform3D`（-10），才能在它写完 `em.drift` 等三个量之后再叠加。"""

    STAGE = FORCE
    ORDER = -5

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        em.note("Transform3DModifier：全部字段语义未经游戏内验证，仅按语料统计猜测模拟"
                 "（含逐帧不乘 dt 的时间基假设），预览效果可能和真实游戏不符")

        mode = em.config.random_dist
        pos_delta = _roll_axis3(f, (("unkn1", "unkn2"), ("unkn3", "unkn4"), ("unkn5", "unkn6")), rng, mode)
        rot_delta = _roll_axis3(f, (("unkn7", "unkn8"), ("unkn9", "unkn10"), ("unkn11", "unkn12")), rng, mode)
        scale_delta = _roll_axis3(f, (("unkn13", "unkn14"), ("unkn15", "unkn16"), ("unkn17", "unkn18")), rng, mode)
        em.user[_STATIC_KEY] = (pos_delta, rot_delta, scale_delta)

        pos_vel = _roll_axis3(f, (("unkn19", "unkn20"), ("unkn23", "unkn24"), ("unkn27", "unkn28")), rng, mode)
        pos_coef = _roll_axis3(f, (("unkn21", "unkn22"), ("unkn25", "unkn26"), ("unkn29", "unkn30")), rng, mode)
        rot_vel = _roll_axis3(f, (("unkn31", "unkn32"), ("unkn35", "unkn36"), ("unkn39", "unkn40")), rng, mode)
        rot_coef = _roll_axis3(f, (("unkn33", "unkn34"), ("unkn37", "unkn38"), ("unkn41", "unkn42")), rng, mode)
        scale_vel = _roll_axis3(f, (("unkn43", "unkn44"), ("unkn47", "unkn48"), ("unkn51", "unkn52")), rng, mode)
        scale_coef = _roll_axis3(f, (("unkn45", "unkn46"), ("unkn49", "unkn50"), ("unkn53", "unkn54")), rng, mode)
        # 变动系数字段全语料默认恒为 0（不是 1）——和"变动系数=1 匀速"的语义矛盾，猜测是
        # "没设置"和"设置成 1.0 匀速"在编辑器里长得一样、字段真实默认值就是 0，这里按"系数
        # 0 视为 1（不变）"处理，否则没设置过这组字段的绝大多数 entry 会在第一帧就把速度乘成 0。
        pos_coef = Vec3(*(c if c != 0.0 else 1.0 for c in pos_coef))
        rot_coef = Vec3(*(c if c != 0.0 else 1.0 for c in rot_coef))
        scale_coef = Vec3(*(c if c != 0.0 else 1.0 for c in scale_coef))
        em.user[_VEL_KEY] = [pos_vel, pos_coef, rot_vel, rot_coef, scale_vel, scale_coef]
        em.user[_ACCUM_KEY] = [Vec3(), Vec3(), Vec3()]
        em.user[_LAST_APPLIED_KEY] = [Vec3(), Vec3(), _SCALE_NEUTRAL.copy()]

    def on_emitter_step(self, em):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        pos_delta, rot_delta, scale_delta = em.user[_STATIC_KEY]
        pos_vel, pos_coef, rot_vel, rot_coef, scale_vel, scale_coef = em.user[_VEL_KEY]
        pos_accum, rot_accum, scale_accum = em.user[_ACCUM_KEY]

        # 速度每帧先自乘一次系数（同 Velocity3D.SpeedCoef 模型），再累加——顺序和
        # on_particle_step() 里 `p.vel *= coef` 在 `p.pos += p.vel * dt` 之前一致。
        pos_vel = pos_vel * pos_coef
        rot_vel = rot_vel * rot_coef
        scale_vel = scale_vel * scale_coef
        em.user[_VEL_KEY][0] = pos_vel
        em.user[_VEL_KEY][2] = rot_vel
        em.user[_VEL_KEY][4] = scale_vel

        pos_accum = pos_accum + pos_vel
        rot_accum = rot_accum + rot_vel
        scale_accum = scale_accum + scale_vel
        em.user[_ACCUM_KEY] = [pos_accum, rot_accum, scale_accum]

        pos_total = pos_delta + pos_accum
        rot_total = rot_delta + rot_accum
        # 缩放是比例量：静态/持续两部分都按"叠加在 1.0 基准上的增量"读（见模块说明），
        # 先合成成一个乘数再和 Transform3D 已经算好的比例相乘，不是相加。
        scale_total = _SCALE_NEUTRAL + scale_delta + scale_accum

        last_pos, last_rot, last_scale = em.user[_LAST_APPLIED_KEY]
        if not em.has("Transform3D"):
            # 没人在我之前把 em.drift 等三个量重置成干净基准——先退掉我自己上一帧加/乘
            # 过的量，代数上等价于每帧都在干净基准上重新算一遍（见模块说明）。
            em.drift = em.drift - last_pos
            em.rotation_drift = em.rotation_drift - last_rot
            if abs(last_scale.x) > _SCALE_EPS and abs(last_scale.y) > _SCALE_EPS and abs(last_scale.z) > _SCALE_EPS:
                em.scale_drift = Vec3(em.scale_drift.x / last_scale.x,
                                      em.scale_drift.y / last_scale.y,
                                      em.scale_drift.z / last_scale.z)
            else:
                em.note("Transform3DModifier：缩放比例分量过小无法安全退位，"
                        "本帧缩放增量可能和上一帧重复叠加")

        em.drift = em.drift + pos_total
        em.rotation_drift = em.rotation_drift + rot_total
        em.scale_drift = em.scale_drift * scale_total
        em.user[_LAST_APPLIED_KEY] = [pos_total, rot_total, scale_total]
