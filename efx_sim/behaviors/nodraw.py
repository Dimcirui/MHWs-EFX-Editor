# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/nodraw.py —— `TypeNoDraw`（**显式**不渲染的渲染主体）

字段（[ATTRIBUTE_TYPES.md](../../ATTRIBUTE_TYPES.md) `TypeNoDraw`，TypeID 78）：

    Flags / Color / ColorRange / RotationOrder / Rotation / RotationRandom /
    Size / SizeRandom / unkn14 / unkn15

它满足 vendor 自己的 `IsTypeAttribute` 判据（`is_render_body_name`），是一个正规的渲染
主体——**但它的名字本身就是"不画"**，和"没有渲染主体"（`_has_renderer_body` 为 False）、
"有渲染主体但没实现"（退化成一个点，见 `simulator.py` 的兜底分支）都不是一回事：前者本来
就不该有画面，后者是我们自己没做完。`TypeNoDraw` 是**属性自己声明**它不产出视觉输出。

没有它之前，`TypeNoDraw` entry 会落进"有渲染主体、只是没实现"的兜底分支，被画成一个假的
退化点——这正是它需要一个 behavior 的原因，即使这个 behavior 什么都不算。字段全部不消费：
不需要知道 `Size`/`Color` 等字段实际是干什么的（大概率是给挂在它身上的子系统，比如碰撞体或
`PtLife` 召唤锚点用的定位参考），也不影响"这个 entry 不画"这个结论。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from ..registry import Behavior, register
from ..stages import RENDER_BODY
from ..state import RenderItem

TYPE_NAME = "TypeNoDraw"


@register(TYPE_NAME)
class TypeNoDraw(Behavior):
    """RENDER_BODY 阶段：显式产出 `kind="NONE"`，不给兜底分支留机会画退化点。"""

    STAGE = RENDER_BODY
    ORDER = 100

    def build_render(self, p, em, view, item):
        return RenderItem(kind="NONE", pos=p.pos.copy())
