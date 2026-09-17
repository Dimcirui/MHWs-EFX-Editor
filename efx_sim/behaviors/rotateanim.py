# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/rotateanim.py —— `RotateAnim`（逐帧旋转动画，写 `p.rot`）

同 `scaleanim.py` 一样的**"加法累积 + 逐帧乘法衰减"**形状（"Add" 每帧加到 `p.rot` 上，
"Coef" 是这个量本身每帧要乘一次的系数），但只有**逐轴一组**——MHWs 的 `RotateAnim` 没有
`ScaleAnim.SizeScalarAdd` 那种"三轴同步"的整体分量，`RotationAddX/Y/Z` 各自独立：

    RotationAddX/Y/Z    Range   每帧加到 p.rot 对应分量上的角度增量（弧度）
    RotationCoefX/Y/Z   Range   上面那个增量本身每帧的衰减/增长系数（1=不变）
    RotationDelayFrame  RangeI  延迟多少帧才开始（三轴共用一个延迟，不像 ScaleAnim 分两组）

`RotateAnimDelayFrame`（TypeID 86，独立的伴生属性，同 `ScaleAnimDelayFrame` 的地位）
--------------------------------------------------------------------------------
只有 `frameDelay`/`unkn2`，处理方式照抄 `scaleanim.py::ScaleAnimDelayFrame` 那一节：
当整体启动延迟，`unkn2` 不消费、非 0 时 note，注册一个空壳类避免被误报"未模拟"。

写进 `p.rot` 之后，谁读、怎么读是各渲染体自己的事
--------------------------------------------------
`p.rot` 是三个独立累积的标量角度，**不是**一次性定好顺序的旋转状态（不像
`TypePolygon.RotationOrder` 那种"一次性按顺序应用"的静态量）。已经在读它的渲染体：

    TypePolygon / TypeGpuPolygon / TypeMeshV2
        在各自原有的静态 RotationX/Y/Z 上**逐分量相加**后再走同一条 `rotate_euler()`/
        `local_matrix_to_blender()`——见各自文件的改动。

    TypeBillboard3D / TypeRibbonLength / TypeGpuRibbonLength / TypeGpuPolygon 的
    "面朝相机"那一档不存在（`TypeGpuPolygon` 走的是固定朝向，已覆盖）
        `TypeBillboard3D` 恒朝相机，它的"转"是屏幕空间自转——要把 `p.rot`（游戏坐标系的
        三轴角）投影到当前相机的视线轴上才有意义，这需要额外的相机-空间标定（姊妹项目
        EFX-Editor 自己也只校准过"绕 Z 自旋 + PLANE"一种组合，符号还得反着来）。MHWs
        没有任何实机对拍能定这件事，猜错了比不做更容易骗人（转速/转向都可能是错的却
        看着像"模拟对了"），所以**不接**，改为 note——"预览不静默撒谎"用在这里就是宁可
        承认"这个我不转"，也不要装作转对了。`TypeRibbonLength`/`TypeGpuRibbonLength`
        没有旋转的渲染体概念（直条带只有伸展方向），本来就无从谈起，不 note。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import XFORM

TYPE_NAME = "RotateAnim"
DELAY_TYPE_NAME = "RotateAnimDelayFrame"

#: 有旋转渲染体、但目前接不上 `p.rot`（缺相机空间标定），发现就 note
_NOT_WIRED_RENDER_BODIES = ("TypeBillboard3D",)


@register(DELAY_TYPE_NAME)
class RotateAnimDelayFrame(Behavior):
    """没有自己的钩子——`RotateAnim` 直接读它的字段（见模块说明）。注册只是为了不被
    误报成"未模拟"：它的数据确实被消费了，只是消费者是 `RotateAnim`。"""

    STAGE = XFORM


@register(TYPE_NAME)
class RotateAnim(Behavior):
    """XFORM 阶段：写 p.rot。排在 ScaleAnim 之后（两者写不同槽位，互不影响）。"""

    STAGE = XFORM
    ORDER = 110

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        if f.i("Flags"):
            em.note("RotateAnim.Flags=%d 未参与模拟（取值语义未确认）" % f.i("Flags"))
        delay_f = em.f(DELAY_TYPE_NAME)
        if delay_f is not None and delay_f.i("unkn2"):
            em.note("RotateAnimDelayFrame.unkn2=%d 未参与模拟（取值语义未确认）"
                    % delay_f.i("unkn2"))
        for name in _NOT_WIRED_RENDER_BODIES:
            if em.f(name) is not None:
                em.note("RotateAnim 未接入 %s 的渲染（屏幕空间自转需要相机朝向标定，"
                        "没有实机数据，宁可不转也不猜转速/转向）" % name)

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        mode = em.config.random_dist

        delay_f = em.f(DELAY_TYPE_NAME)
        start_delay = max(0, delay_f.i("frameDelay")) if delay_f is not None else 0
        start_delay += max(0, f.roll_int("RotationDelayFrame", rng, mode))

        vel = [f.roll("RotationAddX", rng, mode), f.roll("RotationAddY", rng, mode),
              f.roll("RotationAddZ", rng, mode)]
        # RotationCoef{X,Y,Z}=0 是"未设置"哨兵值，实机按 1（不衰减）处理，不是字面乘 0——
        # 语料里 X 轴众数是 1.0（艺术家为了匀速转必须显式填 1，说明结构体零值不是"匀速"），
        # 但真机测试把 0 和 0.1 分别丢进游戏对比过：0 恒速、0.1 几帧内迅速停转，
        # 证实引擎把 0 特判成"不衰减"而非"乘 0 瞬间归零"。
        acc = [f.roll("RotationCoefX", rng, mode, default=(1.0, 0.0)) or 1.0,
              f.roll("RotationCoefY", rng, mode, default=(1.0, 0.0)) or 1.0,
              f.roll("RotationCoefZ", rng, mode, default=(1.0, 0.0)) or 1.0]

        p.user[RotateAnim] = {"v": vel, "a": acc, "delay": start_delay}

    def on_particle_step(self, p, em):
        st = p.user.get(RotateAnim)
        if st is None or p.age < st["delay"]:
            return

        v, a = st["v"], st["a"]
        if v[0]:
            p.rot.x += v[0]
        if v[1]:
            p.rot.y += v[1]
        if v[2]:
            p.rot.z += v[2]
        v[0] *= a[0]
        v[1] *= a[1]
        v[2] *= a[2]
