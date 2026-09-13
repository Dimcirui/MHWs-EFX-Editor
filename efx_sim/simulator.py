# -*- coding: utf-8 -*-
"""
efx_sim/simulator.py —— 顶层驱动（EmitterState + Simulator）

移植自姊妹项目 EFX-Editor 的 `efx_format/sim/simulator.py`（见 docs/SIM_PORT_PLAN.md §4.2）。

逐帧流程
--------
    frame += 1
    1. on_emitter_step   —— Spawn 在这里决定这一帧生几个
    2. 合成发射器位置     —— 必须在生成之前，本帧出生的粒子要用它
    3. 消化生成队列       —— 新粒子逐个跑 on_particle_spawn（**唯一能抽 rng 的地方**）
    4. on_particle_step   —— 按 stage 顺序，逐个活着的粒子
    5. 收割死亡           —— on_particle_death 收集 SpawnRequest（P0 不消化）

**step() 与 build_render(view) 是两个独立调用。** 逐帧模拟与视角无关，所以暂停时转视角
只要重跑 build_render，不用步进；核心也因此能没有相机就单测。

已定的取舍（会影响观感，标定时优先复核）
----------------------------------------
- **出生当帧就参与 step**：frame N 生成的粒子在 frame N 以 age=0 跑一次 step，
  所以寿命 1 帧的粒子正好活 1 帧。另一种可能是"出生帧不动、下一帧才开始"，未验证。
- **先生成、后收割**：本帧要死的粒子在本帧做生成决策时仍占着 `MaxParticles` 的名额。
  两种都说得通，未验证；换顺序只需调整 step() 里这两段的位置。
- **不做子步**：EFX 全程整数帧，逐帧乘法递推没有 dt 的位置，不要引入。

与上游的差异
------------
- 输入是 `[(短类型名, fields_dict)]`，不是 `(type_hash, ...)`；`em.f(name)` 直接返回
  `shapes.FieldView`，**没有 TIML/Clip 曲线那一层**（P0 不做 Clip，见 §4.2）。
- `_has_renderer_body()` 不查分类表（本仓没有），改用 vendor 自己的 `IsTypeAttribute` 规则。
- 没有 `SimResources`（P0 不做 UVSequence 帧表）。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from . import registry as _reg
from . import rng as _rng
from . import stages as _stages
from .config import SimConfig
from .shapes import FieldView
from .state import Particle, RenderItem, Vec3, ViewContext
from .uvs_table import SimResources

#: 没有可用渲染体时，退化点的显示尺寸（米）。**纯显示默认值，不来自文件**——真实尺寸只有
#: 渲染体属性（`TypeBillboard3D` 等）知道，这里没有，所以不假装知道。
FALLBACK_SIZE = 0.1

#: `IsTypeAttribute` 的 Clip/Expression 变体后缀（vendor `EfxFile.cs:181` 的排除规则）
_TYPE_ATTR_EXCLUDED_SUFFIXES = ("Clip", "Expression")


def is_render_body_name(type_name):
    """这个短类型名是不是"渲染主体"。

    照抄 vendor 自己的判据（`EFXAttribute.IsTypeAttribute => type.ToString()
    .StartsWith("Type") && 不是 Clip/Expression 变体`，`EfxFile.cs:181`，一个 Entry 至多
    一个）。上游 EFX-Editor 是手工维护一张渲染体类型白名单，本仓不需要——vendor 已经算好了，
    而且 `Object.efx_is_type_attribute` 就存着这个结果（见 model.py 的 Entry 显示名后缀）。
    """
    name = str(type_name)
    if not name.startswith("Type"):
        return False
    return not name.endswith(_TYPE_ATTR_EXCLUDED_SUFFIXES)


def _has_renderer_body(blocks):
    """这个 entry 有没有渲染主体——决定"退化成点" vs "干脆不画"（见 build_render）。

    没有主体的 entry（纯当 Action 召唤枢纽、或者只有 `Spawn`/`Life` 这类骨架属性）本来就
    不该有画面，画一个退化点是凭空捏造。
    """
    return any(is_render_body_name(name) for name, _fields in blocks)


# ---------------------------------------------------------------------------
# EmitterState
# ---------------------------------------------------------------------------

class EmitterState(object):
    """一个发射器实例的运行期状态。behavior 通过它拿字段、拿噪声、排队生成。"""

    __slots__ = (
        "frame", "config", "seed",
        "origin", "host_origin", "drift", "velocity", "prev_origin",
        "particles", "spawned_total", "spawn_requests",
        "unsupported", "user", "finished", "trail", "resources",
        "_views", "_pending_spawn", "_notes",
    )

    def __init__(self, config, seed, resources=None):
        self.frame = -1
        self.config = config
        self.seed = seed
        #: 宿主注入的外部资源（`.uvs` 帧表等）。**恒非 None**——behavior 不必到处判空。
        self.resources = resources if resources is not None else SimResources()

        # 发射器位置拆成两份，每帧合成 `origin = host_origin + drift`：
        #   host_origin —— **宿主**报进来的位置（Blender 里就是 entry empty 的世界位置）。
        #   drift       —— 模拟层自己算出来的漂移（P0 没有属性会写它，恒为 0）。
        # 分开存是因为两者都会动：合并成一个的话，宿主每帧写一次就把累积的漂移冲掉了。
        self.host_origin = Vec3()
        self.drift = Vec3()
        self.origin = Vec3()
        self.velocity = Vec3()        # 每帧位移
        self.prev_origin = Vec3()

        self.particles = []
        self.spawned_total = 0        # 累计生成数（逐粒子播种的序号）
        self.spawn_requests = []      # 子发射请求（PtLife，P0 不消化）

        self.unsupported = []         # [短类型名]，未模拟的属性
        self.user = {}                # 发射器级的 behavior 私有状态
        self.trail = []
        self.finished = False         # 发射器不再生成且粒子清空

        self._views = {}
        self._pending_spawn = 0
        self._notes = []

    # -- 字段访问（唯一入口）------------------------------------------------
    def f(self, type_name, p=None):
        """取某个属性块的字段视图；该 entry 没有这个属性则 `None`。

        `p` 目前没用上（P0 没有 Clip 曲线，字段值与粒子年龄无关），留着是为了 P2 接
        `EfxClipData` 时 behavior 的调用点不用改——上游那边同一个签名承担的正是这件事。
        """
        return self._views.get(str(type_name))

    def has(self, type_name):
        return str(type_name) in self._views

    # -- 生成队列 ------------------------------------------------------------
    def request_spawn(self, n):
        """排队生成 n 个粒子（本帧结算）。软上限由调用方（Spawn 的 `MaxParticles`）把关，
        这里只挡硬上限。"""
        if n > 0:
            self._pending_spawn += int(n)

    @property
    def alive_count(self):
        return len(self.particles)

    # -- 噪声（step 里唯一的"随机"来源）--------------------------------------
    def noise1(self, seed, channel=0):
        return _rng.noise1(seed, self.frame, channel)

    def noise3(self, seed, channel=0):
        return _rng.noise3(seed, self.frame, channel)

    def noise_smooth3(self, seed, channel=0, period=8.0):
        return _rng.noise_smooth3(seed, self.frame, channel, period)

    # -- 记事（给 UI：本次模拟里跳过 / 猜了什么）------------------------------
    def note(self, msg):
        """**预览不静默撒谎**：凡是没模拟、按假设处理、被上限截断的，都要在这里留一条，
        面板逐条列出来。这是铁律 #2"宁可拒绝，不要悄悄丢"在只读侧的对应物。"""
        if msg not in self._notes:
            self._notes.append(msg)

    @property
    def notes(self):
        return list(self._notes)

    def __repr__(self):
        return ("<EmitterState frame=%d particles=%d spawned=%d>"
                % (self.frame, len(self.particles), self.spawned_total))


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator(object):
    """一个 EFX Entry 的粒子模拟。

    输入是 `[(短类型名, fields_dict), ...]`——**不是**解析好的文件对象，也不是 Blender
    属性树。胶水层从当前正在编辑的属性树构造它，这样预览反映的是未保存的改动。
    """

    def __init__(self, blocks, config=None, resources=None):
        self.blocks = list(blocks or [])
        self._has_body = _has_renderer_body(self.blocks)
        self.config = config or SimConfig()
        #: 属性块里没有、必须由宿主给的外部数据（`UVSequence` 的 `.uvs` 帧表）。
        #: 换资源要 reset —— 帧表在 on_emitter_init 里只看一次。
        self.resources = resources if resources is not None else SimResources()

        self.bound = []
        self.em = None
        self._h_emitter_step = []
        self._h_spawn = []
        self._h_step = []
        self._h_death = []
        self._h_render = []
        self._record_trail = False
        self.reset()

    # -- 生命周期 ------------------------------------------------------------
    def reset(self):
        """回到未开始状态（frame = -1），重新跑 on_emitter_init。"""
        cfg = self.config
        self.bound, unsupported = _reg.build_behaviors(self.blocks, cfg)

        em = EmitterState(cfg, _rng.emitter_seed(cfg.seed), self.resources)
        em.unsupported = list(unsupported)
        for b in self.bound:
            em._views[b.type_name] = b.fields

        self._h_emitter_step = [b for b in self.bound
                                if _reg.implements(b, "on_emitter_step")]
        self._h_spawn = [b for b in self.bound if _reg.implements(b, "on_particle_spawn")]
        self._h_step = [b for b in self.bound if _reg.implements(b, "on_particle_step")]
        self._h_death = [b for b in self.bound if _reg.implements(b, "on_particle_death")]
        self._h_render = [b for b in self.bound
                          if _reg.implements(b, "build_render")
                          and b.stage in cfg.render_stage_order]
        self._h_render.sort(key=lambda b: (cfg.render_stage_order.index(b.stage),
                                           b.order, b.attr_index))

        # 任一 behavior 声明 NEEDS_TRAIL -> 全局开启逐帧位置历史。开销是每粒子每帧一次
        # Vec3 拷贝，只在真需要时付。
        self._record_trail = any(type(b.behavior).NEEDS_TRAIL for b in self.bound)

        init_rng = _rng.particle_rng(em.seed, 0)
        for b in self.bound:
            b.behavior.on_emitter_init(em, init_rng)

        for name in unsupported:
            em.note("未模拟属性：%s" % name)

        self.em = em
        return em

    # -- 推进 ----------------------------------------------------------------
    def step(self):
        """推进一帧。返回本帧结束后的 EmitterState。"""
        em = self.em
        cfg = self.config
        em.frame += 1
        if em.frame > cfg.max_frames:
            if not em.finished:
                em.note("到达 max_frames=%d，预览停在这里（不代表特效本身结束）"
                        % cfg.max_frames)
            em.finished = True
            return em

        em.prev_origin = em.origin.copy()

        # 1. 发射器时间轴
        for b in self._h_emitter_step:
            b.behavior.on_emitter_step(em)

        # 2. 合成发射器位置。**必须在生成之前**——本帧出生的粒子要用它，放到生成之后
        #    就变成读上一帧的值。
        em.origin = em.host_origin + em.drift
        em.velocity = em.origin - em.prev_origin
        if self._record_trail:
            em.trail.append(em.origin.copy())

        # 3. 消化生成队列
        self._consume_spawn(em)

        # 4. 逐粒子 step
        strict = cfg.strict
        record_trail = self._record_trail
        for p in em.particles:
            if not p.alive:
                continue
            if p.delay_left > 0:
                p.delay_left -= 1
                continue
            # **年龄在跑 behavior 之前推进**（出生当帧不推，所以新粒子的第一帧 age=0）。
            # 放在末尾的话 `build_render()` 看到的 age 会比 SHADE 阶段刚算过的那一帧大 1
            # ——`Life` 按 age=N 写的 alpha，和 `UVSequence` 按 age=N+1 取的序列帧，
            # 画在同一个 RenderItem 上却不是同一帧。放在开头两边就一致了。
            if p.birth_frame != em.frame:
                p.age += 1
            for b in self._h_step:
                if strict:
                    self._strict_call(b, p, em)
                else:
                    b.behavior.on_particle_step(p, em)
            if record_trail:
                p.trail.append(p.pos.copy())

        # 5. 收割
        dead = [p for p in em.particles if not p.alive]
        if dead:
            for p in dead:
                for b in self._h_death:
                    req = b.behavior.on_particle_death(p, em)
                    if req:
                        em.spawn_requests.extend(req)
            em.particles = [p for p in em.particles if p.alive]

        return em

    def run_to(self, frame):
        """推进到指定帧（frame 从 0 起）。已经越过则先 reset。"""
        if frame < self.em.frame:
            self.reset()
        while self.em.frame < frame:
            self.step()
        return self.em

    def run(self, frames):
        """从当前状态再推进 `frames` 帧。"""
        for _ in range(int(frames)):
            self.step()
        return self.em

    # -- 渲染 pass（与 step 解耦；可重复调用，不改状态）-----------------------
    def build_render(self, view=None):
        em = self.em
        view = view or ViewContext()
        out = []
        for p in em.particles:
            if not p.active:
                continue
            item = None
            for b in self._h_render:
                item = b.behavior.build_render(p, em, view, item)
            if item is not None and item.kind == "NONE":
                continue      # 渲染体明说"我不该有视觉输出"（TypeNoDraw），不走退化点
            if item is None:
                if not self._has_body:
                    # 这个 entry 压根没有渲染主体类属性——不是"有主体但没实现"，是本来就
                    # 不该有画面，同 TypeNoDraw 一样明确不画（见 _has_renderer_body）。
                    continue
                # 有渲染主体、只是没实现（比如主体是 TypeRibbonLength）-> 退化成一个点，
                # 至少能看见"有多少、在哪、多亮"。
                item = RenderItem(kind="POINT", pos=p.pos.copy(),
                                  size=p.scale * FALLBACK_SIZE)
                item.color = [p.color[0], p.color[1], p.color[2], p.alpha]
                item.extra["vel"] = p.vel.copy()
                item.extra["age"] = p.age
            out.append(item)
        return out

    def emitter_outline(self, segments=28):
        """生成区域的线框（成对的点，与粒子同一坐标空间）。没有形状属性就返回 `[]`。

        按"behavior 有没有 `outline()`"找，**不写死 `EmitterShape3D`**——以后别的形状类
        属性加上同名方法就自动被画出来。
        """
        out = []
        for b in self.bound:
            fn = getattr(b.behavior, "outline", None)
            if fn is None:
                continue
            out.extend(fn(self.em, segments) or ())
        return out

    def suggested_duration(self, default=180):
        """"播放一次"该放多长（帧）。按各 behavior 的 `duration_hint()` 取最大值。"""
        best = 0
        for b in self.bound:
            fn = getattr(b.behavior, "duration_hint", None)
            if fn is None:
                continue
            got = fn(self.em)
            if got:
                best = max(best, int(got))
        return best or default

    # -- 内部 ----------------------------------------------------------------
    def _consume_spawn(self, em):
        n = em._pending_spawn
        em._pending_spawn = 0
        if n <= 0:
            return
        room = self.config.max_particles - len(em.particles)
        if room <= 0:
            em.note("触发硬上限 max_particles=%d，本帧不再生成"
                    % self.config.max_particles)
            return
        if n > room:
            em.note("触发硬上限 max_particles=%d，本帧生成被截断"
                    % self.config.max_particles)
            n = room
        for _ in range(n):
            idx = em.spawned_total
            em.spawned_total += 1
            p = Particle(idx, _rng.particle_seed(em.seed, idx), em.frame)
            # 默认出生在发射器原点。`EmitterShape3D` 会覆写成"原点 + 形状内采样点"，
            # 但没有生成方式属性的 entry 也得站在发射器上，不能留在世界原点。
            p.pos = em.origin.copy()
            prng = _rng.particle_rng(em.seed, idx)
            for b in self._h_spawn:
                b.behavior.on_particle_spawn(p, em, prng)
            em.particles.append(p)

    def _strict_call(self, b, p, em):
        """strict 模式：逐调用校验 behavior 没有越出它声明的阶段去写字段。

        这是"阶段按写什么命名"换来的唯一能自动检查的契约——behavior 多起来之后，没有它
        谁也说不清是谁把 pos 改坏的。
        """
        allowed = _stages.STAGE_WRITES.get(b.stage, frozenset())
        before = self._snapshot(p)
        b.behavior.on_particle_step(p, em)
        after = self._snapshot(p)
        for slot in _stages.CHECKED_SLOTS:
            if before[slot] != after[slot] and slot not in allowed:
                raise AssertionError(
                    "%s 在 %s 阶段写了 p.%s（该阶段只允许写 %s）"
                    % (b.type_name, _stages.stage_name(b.stage), slot,
                       ", ".join(sorted(allowed)) or "（无）"))

    @staticmethod
    def _snapshot(p):
        return {
            "pos": p.pos.as_tuple(),
            "vel": p.vel.as_tuple(),
            "scale": p.scale.as_tuple(),
            "rot": p.rot.as_tuple(),
            "color": tuple(p.color),
            "alpha": p.alpha,
            "age": p.age,
        }
