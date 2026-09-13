# -*- coding: utf-8 -*-
"""
efx_sim/behaviors/ —— 逐属性的模拟行为

**加一个属性 = 新建一个文件 + `@register("类型短名")` + 在下面加一行 import。**
不需要改 registry / simulator / stages 里的任何东西。

P0 已实现（覆盖全语料 37.7% 的属性实例）
----------------------------------------
    Spawn            发射节奏（批次 / 间隔 / 上限）
    Life             寿命与淡入淡出
    EmitterShape3D   生成位置（Box / Sphere / Cylinder + 扫描角）
    TypeBillboard3D  渲染主体（P0 只画纯色片）
    Velocity3D       初速度 + 逐帧积分，**只支持 VelocityType=Direction**
    UVSequence       序列帧（帧表由胶水层从 `.uvs` 解析后经 SimResources 注入）

`Transform3D`（7.83%）**故意不在这里**：本仓的 Entry 用 Blender 原生 parent-child，
`transform3d_view.py` 已经把它烘进父对象的 `matrix_basis`，预览直接读 `matrix_world` 当
宿主矩阵就行。⚠ 它和上游 EFX-Editor 的 `TRANSFORM3D` 同名不同物——那边带三组**速度**，
MHWs 把动态部分拆成了独立的 `Transform3DModifier`，静态的只有 4 个字段。
见 docs/SIM_PORT_PLAN.md §5.1。

未实现的属性不是"不支持"：`registry.build_behaviors()` 会把它们记进 `em.unsupported`，
面板上列出"本 entry 有 N 个未模拟属性"。**预览不静默撒谎。**

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from . import billboard3d      # noqa: F401
from . import emittershape3d   # noqa: F401
from . import life             # noqa: F401
from . import spawn            # noqa: F401
from . import uvsequence       # noqa: F401
from . import velocity3d       # noqa: F401

__all__ = ["spawn", "life", "emittershape3d", "billboard3d", "velocity3d",
           "uvsequence"]
