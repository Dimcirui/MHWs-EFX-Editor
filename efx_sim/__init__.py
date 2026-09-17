# -*- coding: utf-8 -*-
"""
efx_sim/ —— EFX 粒子系统模拟核心（零 bpy）

把一个 EFX Entry 的属性块喂进来，逐帧算出粒子状态。**不碰 Blender，不碰渲染**——
`blender_efx_re/sim_preview.py` 那层负责时钟（modal + timer）、绘制（gpu draw handler）
和坐标换算。这样核心能脱离 Blender 单测，将来换前端也只要移植这一层。

为什么是仓库根的平级包，不是 `blender_efx_re/sim/`
--------------------------------------------------
`blender_efx_re/__init__.py` 会 import bpy，任何放在它下面的模块都要先执行那个
`__init__.py`，脱离 Blender 就 import 不动，单测无从谈起。放在仓库根：

- 在 Blender 里是 `bl_ext.user_default.mhws_efx_editor.efx_sim`，胶水层写 `from .. import efx_sim`；
- 脱离 Blender 跑测试时仓库根在 `sys.path` 上，`import efx_sim` 直接成立（不经过根 `__init__.py`）。

`blender_manifest.toml` 用的是黑名单，这个包会自动进发行包，不用改 manifest。

用法
----
    from efx_sim import Simulator, SimConfig

    blocks = [(short_type_name, fields_dict), ...]   # entry 里属性的原始顺序
    sim = Simulator(blocks, SimConfig(seed=1))
    for _ in range(120):
        sim.step()
        items = sim.build_render(view)               # 与 step 解耦，可单独重跑

`blocks` 刻意不是解析好的文件对象：胶水层从**当前正在编辑的**属性树构造它
（`[(model.short_attr_name(o.efx_attr_type), model.children_to_dict(o.efx_fields))
for o in attrs]`），预览才能反映未保存的改动。而 `children_to_dict()` 本来就是
`io_tree.export_attribute_object()` 用的那个函数——预览和导出读同一份数据、走同一个函数，
验证纪律 #8 要的"打到真实用户路径上"不用额外争取。

设计要点（详见各模块 docstring）
--------------------------------
- stages.py   阶段按"写什么"命名（FORCE/INTEGRATE/CONSTRAIN/XFORM/SHADE），不按"什么时候跑"；
              顺序是数据不是代码。**本仓要求每个 behavior 显式声明 STAGE**。
- rng.py      随机量只在 spawn 抽（step 钩子签名里没有 rng）；逐帧随机用确定性噪声。
- shapes.py   字段只能通过 `FieldView` 读；`Range`/`RangeI`/`Int2` 的语义名单在这里，
              由单测和 `blender_efx_re/model.py` 钉住一致。
- config.py   所有未确认的语义收成开关（UNKNOWNS），标定 = 拖滑块而不是改代码。
- vecmath.py  **角度是弧度**；旋转顺序用 vendor 枚举，不继承上游的索引表。

移植自姊妹项目 EFX-Editor（MHWI）的 `efx_format/sim/`，逐文件的搬运清单、差异和依据见
docs/SIM_PORT_PLAN.md。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from .config import UNKNOWNS, SimConfig
from .expr import EvalContext, ExprError, ParsedExpr, evaluate as expr_evaluate, parse as expr_parse
from .registry import (Behavior, BoundBehavior, build_behaviors, implements,
                       register, registered_names)
from .rng import (DIST_GAUSSIAN, DIST_ONESIDED, DIST_SYMMETRIC, emitter_seed,
                  emitter_stream_rng, noise1, noise3, noise_smooth1, noise_smooth3,
                  particle_rng, roll_static_random, roll_static_random_int,
                  roll_uniform, roll_uniform_int)
from .simulator import EmitterState, Simulator, is_render_body_name, resolve_expr_field_name
from .shapes import (MIN_MAX_INT2_FIELDS, PAIR_MIN_MAX_FIELDS, SR_INDEX_FIELDS,
                     SR_MIN_MAX_FIELDS, HALF_OPEN_MAX_FIELDS,
                     FieldShapeError, FieldView)
from .stages import (CONSTRAIN, FORCE, INTEGRATE, RENDER_BODY, RENDER_MOD, SHADE,
                     STAGE_LABELS, STAGE_NAMES, XFORM, stage_name)
from .state import (ONE, ZERO, Particle, RenderItem, SpawnRequest, Vec3,
                    ViewContext)
from .uvs_table import Frame, SimResources, from_uvs_dict
from . import behaviors  # noqa: F401  —— import 即注册，必须排在 registry 之后
from .vecmath import (DEFAULT_ROTATION_ORDER, ROTATION_ORDER, quantize_angle,
                      rotate_euler, rotation_order_name, sweep_fraction,
                      unit_from_spherical)

__all__ = [
    # 顶层
    "Simulator", "EmitterState", "SimConfig", "UNKNOWNS", "is_render_body_name",
    "resolve_expr_field_name",
    # 扩展点
    "Behavior", "register", "registered_names", "BoundBehavior", "build_behaviors",
    "implements",
    # Expression 公式求值
    "expr_parse", "expr_evaluate", "EvalContext", "ParsedExpr", "ExprError",
    # 阶段
    "FORCE", "INTEGRATE", "CONSTRAIN", "XFORM", "SHADE",
    "RENDER_BODY", "RENDER_MOD", "STAGE_NAMES", "STAGE_LABELS", "stage_name",
    # 数据
    "Particle", "RenderItem", "SpawnRequest", "Vec3", "ViewContext", "ZERO", "ONE",
    # 外部资源（序列帧表）
    "SimResources", "Frame", "from_uvs_dict",
    # 字段读取
    "FieldView", "FieldShapeError",
    "SR_INDEX_FIELDS", "SR_MIN_MAX_FIELDS", "HALF_OPEN_MAX_FIELDS",
    "MIN_MAX_INT2_FIELDS",
    "PAIR_MIN_MAX_FIELDS",
    # 随机
    "roll_static_random", "roll_static_random_int", "roll_uniform", "roll_uniform_int",
    "particle_rng", "emitter_seed", "emitter_stream_rng",
    "noise1", "noise3", "noise_smooth1", "noise_smooth3",
    "DIST_ONESIDED", "DIST_SYMMETRIC", "DIST_GAUSSIAN",
    # 数学
    "rotate_euler", "rotation_order_name", "ROTATION_ORDER", "DEFAULT_ROTATION_ORDER",
    "quantize_angle", "sweep_fraction", "unit_from_spherical",
]
