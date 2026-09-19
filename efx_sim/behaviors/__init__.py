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
    Velocity3D       初速度 + 逐帧积分。四档方向模型（Direction / Normal / Radial /
                     Spread）和姊妹项目 EFX-Editor 是同一个，字段对应关系经全语料
                     分桶实测（见 velocity3d.py 的对照表）；`ScreenSpace`/`Max` 零样本未做
    UVSequence       序列帧（帧表由胶水层从 `.uvs` 解析后经 SimResources 注入）

`Transform3D`（7.83%）**只贡献增量，不认识矩阵本身**：本仓的 Entry 用 Blender 原生
parent-child，`transform3d_view.py` 编辑时就把静态值烘进父对象的 `matrix_basis`，预览读
`matrix_world` 当宿主矩阵——这条路对**静态**字段完全够用，`transform3d.py` 这个 behavior
存在的唯一理由是 Expression/Clip 曲线会让字段**逐帧变化**，矩阵只烘一次跟不上，所以它把
"当前值相对烘焙基准的增量"分别写进 `em.drift`（`LocalPosition`）/`em.rotation_drift`
（`LocalRotation`）/`em.scale_drift`（`LocalScale`）（没有曲线驱动时增量恒为零，行为和
完全不模拟一致）。位置增量早就接进了 `em.origin`；旋转/缩放增量只有胶水层
（`sim_preview.py::_entry_matrix()`）消费——换算成一个纯旋转+缩放矩阵，插在
`entry_obj.matrix_world` 和 entry 下面的内容之间，**逐分量近似，不是严格矩阵合成**，
基准本身非恒等时会有偏差（见 `transform3d.py` 说明）。⚠ 它和上游 EFX-Editor 的
`TRANSFORM3D` 同名不同物——那边带三组**速度**，MHWs 把动态部分拆成了独立的
`Transform3DModifier`。见 docs/SIM_PORT_PLAN.md §5.1。

`Transform3DModifier`（Entry 持续变换，55 个字段全部匿名）**目前是全表唯一一个 confidence
只有 guess 的 behavior**（2026-09-17 新增）：字段语义纯靠语料统计推出来，没有游戏内实测，
`on_emitter_init` 里每次都会 `em.note()` 提醒这一点。往 `em.drift`/`em.rotation_drift`/
`em.scale_drift` 上叠加，ORDER 必须晚于 `transform3d.py` 的 -10，见 transform3dmodifier.py
说明。

P0 之后追加（渲染主体的另外几档）
---------------------------------
    TypePolygon           固定朝向的片（不朝相机，对照 EFX-Editor 的 PLANE）
    TypeRibbonLength      定长直条带（不跟踪轨迹，对照 EFX-Editor RIBBON 的"定长面片"档）
    TypeRibbonFollow      轨迹跟随条带（几何取自 `p.trail`，对照 EFX-Editor RIBBON 的
                          "轨迹跟随"档，见 ribbonfollow.py 说明）
    TypeGpuPolygon        同 TypePolygon，GPU 批量渲染变体（字段是子集，见各自模块说明）
    TypeGpuRibbonLength   同 TypeRibbonLength，GPU 批量渲染变体
    TypeMeshV2            宿主绑定的 .mesh（对照 EFX-Editor 的 MESH），核心只出变换/染色，
                          几何由 `asset_link.py` 绑定的对象在胶水层取
    ScaleAnim             逐帧缩放动画，写 `p.scale`（各渲染体已经把它当乘数用，见其模块说明）
    ScaleAnimDelayFrame   `ScaleAnim` 的整体启动延迟，没有自己的钩子（见 scaleanim.py 说明）
    RotateAnim            逐帧旋转动画，写 `p.rot`；只接进了 TypePolygon/TypeGpuPolygon/
                          TypeMeshV2（固定朝向、有明确合成方式的渲染体），TypeBillboard3D
                          没接（屏幕空间自转需要相机标定，没有实机数据，见其模块说明）
    RotateAnimDelayFrame  `RotateAnim` 的整体启动延迟，同上没有自己的钩子
    ParentOptions         只接 `ParticleUseLocal`+`ConstInheritRate`：已出生的粒子要不要
                          继续跟着发射器的逐帧位移走（`RelationPos`/`RelationRot`/
                          `RelationScl` 那部分——发射器自己怎么跟父级/骨骼——从来不是
                          `efx_sim` 的事，见 parentoptions.py 说明）
    TypePolygonTrail      固定轴向的直线刀光。全语料只有 35 个实例、零 010 模板注释，是
                          证据最薄的一档——目前借用 RIBBON 的朝相机 billboard 几何
                          （按命名推断本该固定朝向，还没实现），宽度是纯显示占位，
                          见 polygontrail.py 说明
    TypeNoDraw            **显式**不渲染的渲染主体——产出 `kind="NONE"`，不让兜底分支把它
                          画成一个假的退化点，见 nodraw.py 说明
    PtLife                粒子死亡时召唤一个 Action（`Actions[ActionIndex]`），只做
                          `Status==死亡时` 这一档，只产出 `SpawnRequest`、不递归模拟被
                          召唤的子树，见 ptlife.py 说明
    Attractor             弹簧力+阻尼吸引目标点，`FORCE` 阶段写 `p.vel`。只做字段语义里
                          把握够的一/二/三档（目标点两分量、距离阈值、阻尼、球形死区+速度
                          乘区）；`AttractAxisBias`/`SpawnDelay`/Shape 系统（`ShapeRangeX/Y/Z`+
                          `ShapeRotation`）故意不做，语义还是猜测或有未解决的反常现象
                          （"始终正对摄像机"），见 attractor.py 说明

`Gpu` 前缀的这两个都和 `Spawn`/`EmitterShape3D`/`Life`/`Velocity3D` 同 entry 共存
（语料文件级共现率 ≥99.6%），真正的粒子数/位置/寿命/运动仍由那几个属性决定——"Gpu" 只是
换了个渲染实现，不是另起一套独立的 GPU 粒子系统，所以能直接复用 CPU 侧同款几何/染色模型。

未实现的属性不是"不支持"：`registry.build_behaviors()` 会把它们记进 `em.unsupported`，
面板上列出"本 entry 有 N 个未模拟属性"。**预览不静默撒谎。**

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from . import attractor        # noqa: F401
from . import billboard3d      # noqa: F401
from . import emittershape3d   # noqa: F401
from . import gpupolygon       # noqa: F401
from . import gpuribbonlength  # noqa: F401
from . import life             # noqa: F401
from . import meshv2           # noqa: F401
from . import nodraw           # noqa: F401
from . import parentoptions    # noqa: F401
from . import polygon          # noqa: F401
from . import polygontrail     # noqa: F401
from . import ptlife           # noqa: F401
from . import ribbonfollow     # noqa: F401
from . import ribbonlength     # noqa: F401
from . import rotateanim       # noqa: F401
from . import scaleanim        # noqa: F401
from . import spawn                # noqa: F401
from . import transform3d          # noqa: F401
from . import transform3dmodifier  # noqa: F401
from . import uvsequence           # noqa: F401
from . import velocity3d           # noqa: F401

__all__ = ["spawn", "life", "emittershape3d", "billboard3d", "velocity3d",
           "uvsequence", "polygon", "polygontrail", "ribbonlength", "ribbonfollow",
           "gpupolygon", "gpuribbonlength", "meshv2", "scaleanim", "rotateanim",
           "transform3d", "transform3dmodifier", "parentoptions", "nodraw", "ptlife",
           "attractor"]
