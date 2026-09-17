# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/ptlife.py —— `PtLife`（粒子生命周期某阶段召唤一个 Action）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `PtLife`，TypeID 136）：

    Flags        U32   语义未知，未参与模拟
    Status       U32（枚举 PtLifeStatus）  触发时机：-1=未知/0=生成时/1=淡入时/2=持续时/
                 3=淡出时/4=死亡时。confirmed，见
                 semantics/mhws_field_labels.json 的 EFXAttributePtLife.Status
    ActionIndex  S32   指向文件顶层 `Actions[ActionIndex]`（`EFXAction`，社区叫 Play）

只做 Status==生成时 / 死亡时
----------------------------
这两档能直接挂在现有的 `on_particle_spawn`/`on_particle_death` 钩子上——`Appear`/`Keep`/
`Vanish` 分别对应淡入结束/持续期间/淡出开始这几个中间时刻，触发它们需要额外跟踪 `Life`
的阶段迁移（本仓没做），遇到时如实 note，不假装模拟了别的阶段（`registry.py`："预览不
静默撒谎"）。

实测样本（`11_it03_005.efx.5571972` 的 `0_PT` entry）走的正是"生成时"这一档：一个只有
`TypeNoDraw`（不画）+`Spawn`+`Life`+`PtLife` 的纯逻辑 entry，分批生成几个隐形粒子，每个
一出生就立刻召唤同一个 Action——"死亡时召唤"不是唯一常见形态，两档都要支持。

只产出 `SpawnRequest`，不递归模拟被召唤的 Action
-------------------------------------------------
`Actions[i]` 内嵌完整的 `PlayEmitter`/`EfxFile` 子树，真实文件里存在循环/深嵌套引用
（见 `state.SpawnRequest` 类文档），递归消化需要先定深度/实例数上限——这属于"知道召唤了
谁、在哪召唤"之后的下一步，是宿主（比如 Blender 预览的 `sim_preview.py`）的事，`efx_sim`
自己不认识 Action/Entry 对象图，只管把"该不该召唤、召唤哪个 Action、在哪召唤"这三件事
算对，攒进 `EmitterState.spawn_requests`。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import SHADE
from ..state import SpawnRequest

TYPE_NAME = "PtLife"

STATUS_INITIALIZE = 0
STATUS_TERMINATE = 4

_SUPPORTED_STATUSES = (STATUS_INITIALIZE, STATUS_TERMINATE)

_STATUS_LABELS = {
    -1: "未知",
    0: "生成时",
    1: "淡入时",
    2: "持续时",
    3: "淡出时",
    4: "死亡时",
}


def _summon_note(action_index):
    return ("PtLife 召唤 Action #%d（子效果的实际展开由宿主决定，本层只记录召唤请求）"
            % action_index)


@register(TYPE_NAME)
class PtLife(Behavior):
    """不写任何粒子状态字段，只在 Status 对应的时机把召唤请求塞进 `em.spawn_requests`。"""

    STAGE = SHADE
    ORDER = 900   # 不写 SHADE 的任何字段，排在真正写颜色/透明度的 behavior 之后纯粹为了阅读顺序

    def on_emitter_init(self, em, rng):
        f = em.f(TYPE_NAME)
        if f is None:
            return
        status = f.i("Status")
        if status not in _SUPPORTED_STATUSES:
            label = _STATUS_LABELS.get(status, "取值 %d" % status)
            em.note("PtLife.Status=%s（%s），本预览只模拟“生成时”/“死亡时”两档触发，"
                    "此 Entry 不会召唤 Action" % (status, label))

    def on_particle_spawn(self, p, em, rng):
        f = em.f(TYPE_NAME)
        if f is None or f.i("Status") != STATUS_INITIALIZE:
            return
        action_index = f.i("ActionIndex")
        em.note(_summon_note(action_index))
        em.spawn_requests.append(
            SpawnRequest(kind="action", target=action_index, pos=p.pos.copy(),
                        scale=p.scale.copy(), source_type=TYPE_NAME, particle=p))

    def on_particle_death(self, p, em):
        f = em.f(TYPE_NAME)
        if f is None or f.i("Status") != STATUS_TERMINATE:
            return None
        action_index = f.i("ActionIndex")
        em.note(_summon_note(action_index))
        return [SpawnRequest(kind="action", target=action_index, pos=p.pos.copy(),
                             scale=p.scale.copy(), source_type=TYPE_NAME, particle=p)]
