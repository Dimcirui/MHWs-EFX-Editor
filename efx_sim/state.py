# -*- coding: utf-8 -*-
"""
efx_sim/state.py —— 模拟器的数据结构（Vec3 / Particle / RenderItem / ViewContext）

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/state.py`（见 docs/SIM_PORT_PLAN.md §4.1）。
与上游的差异：

- **坐标系换成 RE Engine 的**（见下）。
- **删掉 `BASE_AXES`**：那是 MHWI `VELOCITY3D.baseAxis`（六个基准轴之一）用的；MHWs 的
  `Velocity3D` 没有这个字段，改用 `DirectionVectorX/Y/Z` 直接给方向向量。
- **删掉 `RibbonStrip`**：P0 不做条带渲染体，而且那个类的快路依赖 numpy 数组接口。
- **`Particle.rot` 是弧度**，不是上游的度（见 docs/SIM_PORT_PLAN.md §8.1）。

坐标系
------
本层**全程使用游戏坐标系**（RE Engine，Y-up）。到 Blender 坐标（Z-up）的换算是胶水层的事，
核心层不碰——这样核心能脱离 Blender 单测，也能被别的前端原样复用。换算规则见
`blender_efx_re/coords.py`：**位置 1:1，不除 100**（RE Engine 场景单位本身就是米），轴变换是
`Rx(+90°)` 基变换。⚠ 姊妹项目是 MT Framework、单位厘米、要 /100，那套系数**不能照抄**。

时间单位
--------
全程用**整数帧**。一帧 = 1/`SimConfig.fps` 秒（默认 60）。MHWs 的字段名自带时间基：带
`Frame` 后缀的一律是帧（`AppearFrame`/`SpeedDelayFrame`/…）。`Velocity3D.SpeedCoef` 是
**每帧乘一次**的系数、`GravityRate` 是每帧叠加量——这是**逐帧乘法递推，不是 dt 积分**，
别引入 dt。

⚠ 帧率本身是**预览的假设**，不是文件里的事实：MHWs 不锁帧，引擎内部大概率按 60fps 等效
tick 归一，但这个从语料里查不出来。所以 fps 是 `SimConfig` 的旋钮，不是常量。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

import math


# ---------------------------------------------------------------------------
# Vec3 —— 极简三维向量（零依赖；几百粒子规模下比 tuple + 函数更可读，且够快）
# ---------------------------------------------------------------------------

class Vec3(object):
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    # -- 构造 / 转换 --------------------------------------------------------
    @classmethod
    def from_seq(cls, seq):
        return cls(seq[0], seq[1], seq[2])

    def copy(self):
        return Vec3(self.x, self.y, self.z)

    def as_tuple(self):
        return (self.x, self.y, self.z)

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def __len__(self):
        return 3

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]

    def __repr__(self):
        return "Vec3(%.4f, %.4f, %.4f)" % (self.x, self.y, self.z)

    def __eq__(self, other):
        if not isinstance(other, Vec3):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __hash__(self):
        return hash((self.x, self.y, self.z))

    # -- 运算 --------------------------------------------------------------
    def __add__(self, o):
        return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o):
        return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)

    def __neg__(self):
        return Vec3(-self.x, -self.y, -self.z)

    def __mul__(self, s):
        if isinstance(s, Vec3):   # 逐分量乘（缩放向量用）
            return Vec3(self.x * s.x, self.y * s.y, self.z * s.z)
        return Vec3(self.x * s, self.y * s, self.z * s)

    __rmul__ = __mul__

    def __iadd__(self, o):
        self.x += o.x
        self.y += o.y
        self.z += o.z
        return self

    def __isub__(self, o):
        self.x -= o.x
        self.y -= o.y
        self.z -= o.z
        return self

    def __imul__(self, s):
        if isinstance(s, Vec3):
            self.x *= s.x
            self.y *= s.y
            self.z *= s.z
        else:
            self.x *= s
            self.y *= s
            self.z *= s
        return self

    # -- 度量 --------------------------------------------------------------
    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def length_sq(self):
        return self.x * self.x + self.y * self.y + self.z * self.z

    def normalized(self, fallback=None):
        """长度为 0 时返回 `fallback`（默认零向量），不抛。"""
        n = self.length()
        if n <= 1e-12:
            return fallback.copy() if fallback is not None else Vec3()
        return Vec3(self.x / n, self.y / n, self.z / n)

    def dot(self, o):
        return self.x * o.x + self.y * o.y + self.z * o.z

    def cross(self, o):
        return Vec3(self.y * o.z - self.z * o.y,
                    self.z * o.x - self.x * o.z,
                    self.x * o.y - self.y * o.x)


ZERO = Vec3()
ONE = Vec3(1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# Particle
# ---------------------------------------------------------------------------

class Particle(object):
    """一个粒子的全部状态。

    `rolled`：出生时抽定的随机值（`Range.r` 那一半每粒子定死一次，不逐帧重抽）。
    `user`  ：behavior 私有的逐粒子状态，按 behavior 类做 key——新属性存自己的东西不必改
              这里的 `__slots__`，这是"可扩展"的落点之一。
    """

    __slots__ = (
        # 身份
        "index", "seed", "birth_frame",
        # 时间
        "age", "life", "delay_left", "alive",
        # 运动
        "pos", "vel", "spawn_pos",
        # 外观
        "scale", "rot", "color", "alpha",
        # 轨迹历史（只有需要的 behavior 声明 NEEDS_TRAIL 时才记录）
        "trail",
        # 扩展
        "rolled", "user",
    )

    def __init__(self, index, seed, birth_frame):
        self.index = index
        self.seed = seed
        self.birth_frame = birth_frame

        self.age = 0
        self.life = 0           # 由 Life behavior 在 spawn 时写；0 = 尚未设定
        self.delay_left = 0
        self.alive = True

        self.pos = Vec3()
        self.vel = Vec3()
        self.spawn_pos = Vec3()   # 出生位置（相对发射器原点）

        self.scale = Vec3(1.0, 1.0, 1.0)
        self.rot = Vec3()         # **弧度**，游戏坐标系
        self.color = [1.0, 1.0, 1.0]
        self.alpha = 1.0

        #: 最近若干帧的位置（旧→新，末尾是当前帧）。条带类渲染体要用；
        #: 不需要的时候恒为空列表，不占成本。
        self.trail = []

        self.rolled = {}
        self.user = {}

    @property
    def active(self):
        """已出生且过了出生延迟——只有 active 的粒子参与 step / 渲染。"""
        return self.alive and self.delay_left <= 0

    def __repr__(self):
        return ("<Particle #%d age=%d/%d pos=%s alive=%s>"
                % (self.index, self.age, self.life, self.pos, self.alive))


# ---------------------------------------------------------------------------
# SpawnRequest —— 粒子死亡触发的子发射（PtLife，P2 用）
# ---------------------------------------------------------------------------

class SpawnRequest(object):
    """一次子发射请求。behavior 产出、实例树消化。

    P0 不消化它（没有实例树），但 `Behavior.on_particle_death()` 的签名要它，先放着。

    ⚠ 将来消化它必须设递归深度 + 实例数上限：MHWs 的 `PtLife.ActionIndex` 指向 Action，
    Action 里的 `PlayEmitter` 又内嵌完整 EfxFile，循环/深嵌套在真实文件里存在，撞上会挂死。
    """

    __slots__ = ("kind", "target", "pos", "scale", "delay", "source_type", "particle")

    def __init__(self, kind, target, pos=None, scale=None, delay=0, source_type="",
                 particle=None):
        self.kind = kind            # 'action'（PtLife）| 'entry' | 'efx'（PlayEfx，未做）
        self.target = target
        self.pos = pos or Vec3()
        self.scale = scale or Vec3(1.0, 1.0, 1.0)
        self.delay = int(delay)
        self.source_type = source_type
        self.particle = particle

    def __repr__(self):
        return "<SpawnRequest %s %r @%s>" % (self.kind, self.target, self.pos)


# ---------------------------------------------------------------------------
# RenderItem —— 渲染 pass 的产物（纯数据，胶水层翻译成 GPU batch）
# ---------------------------------------------------------------------------

class RenderItem(object):
    """一个待绘制单元。RENDER_BODY 阶段产出，RENDER_MOD 阶段就地修改。"""

    __slots__ = ("kind", "pos", "size", "rot", "color", "uv_rect", "uv_corners",
                 "blend", "tex_key", "extra", "axis_u", "axis_v")

    def __init__(self, kind="BILLBOARD", pos=None, size=None, rot=0.0):
        #: 'BILLBOARD'（面朝相机的片）| 'PLANE'（固定朝向的片）| 'MESH'
        #: | 'POINT'（无渲染体时的退化显示）
        #: | 'NONE'（**显式**不渲染，例如 TypeNoDraw——与"没有渲染体"不是一回事）
        self.kind = kind
        self.pos = pos or Vec3()
        self.size = size or Vec3(1.0, 1.0, 1.0)
        self.rot = rot                       # 屏幕空间自转，**弧度**
        self.color = [1.0, 1.0, 1.0, 1.0]    # RGBA
        self.uv_rect = (0.0, 0.0, 1.0, 1.0)  # (u0, v0, u1, v1)，v 向下（同 .uvs）

        #: 四个角的 UV，序为 BL, BR, TR, TL。UVSequence 写它——序列帧的翻转/90° 旋转塞不进
        #: 一个矩形，只有四个角能表达。None = 没有序列帧信息，照 uv_rect 整张图用。
        self.uv_corners = None
        self.blend = "ALPHA"                 # 'ALPHA' | 'ADDITIVE' | 'MULTIPLY'
        self.tex_key = None                  # 贴图标识，由胶水层解释

        #: 面片的朝向。为 None 时胶水层按**面朝相机**画（TypeBillboard3D）；给了就用这一对
        #: 作为面片的横/纵轴（TypePolygon 这类固定朝向的渲染体）。
        self.axis_u = None
        self.axis_v = None

        self.extra = {}

    def __repr__(self):
        return "<RenderItem %s @%s %s>" % (self.kind, self.pos, self.blend)


# ---------------------------------------------------------------------------
# ViewContext —— 渲染 pass 的视角输入
# ---------------------------------------------------------------------------

class ViewContext(object):
    """相机信息，由胶水层填。**step() 拿不到它**——逐帧模拟必须与视角无关，这样暂停时
    转视角只需重跑 build_render，核心也能没有相机就单测。"""

    __slots__ = ("cam_pos", "cam_forward", "cam_up", "cam_right", "viewport")

    def __init__(self, cam_pos=None, cam_forward=None, cam_up=None,
                 cam_right=None, viewport=(1920, 1080)):
        self.cam_pos = cam_pos or Vec3(0.0, 0.0, -10.0)
        self.cam_forward = cam_forward or Vec3(0.0, 0.0, 1.0)
        self.cam_up = cam_up or Vec3(0.0, 1.0, 0.0)
        self.cam_right = cam_right or Vec3(1.0, 0.0, 0.0)
        self.viewport = viewport
