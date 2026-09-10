"""MHWilds VecField —— 编辑 Monster Hunter Wilds 原生向量场 (.tex) 的操作符/属性组。

从姊妹项目 blender_tfa_importer（编辑通用 .tfa 湍流场）移植过来的编辑工具链
（旋转/反转/预设/区域修改/像素修改等），格式层换成本仓的 wilds_vecfield_io.py
（原生 .tex 的 GDeflate+BC1 读写），不再支持 .tfa 本身——那是另一个完全不同的
容器格式，这份文件从名字到 bl_idname 都只认 Wilds 原生向量场。
"""

import bpy
import numpy as np
import struct
import json
from mathutils import Vector
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import (StringProperty,
                       BoolProperty,
                       FloatProperty,
                       IntProperty,
                       IntVectorProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       PointerProperty,
                       CollectionProperty)
from bpy.types import (Operator,
                       PropertyGroup,
                       AddonPreferences,
                       Panel)
from pathlib import Path
import os

from .wilds_vecfield_io import (
    parse_wilds_tex_file,
    build_wilds_vecfield_tex_file,
    WildsTexError,
    VERSION_MHWILDS,
)
from . import wilds_vecfield_field_generators as field_generators


def _set_bsdf_transmission(bsdf, value):
    """Blender 4.0 把 Principled BSDF 的 'Transmission' 输入改名成了
    'Transmission Weight'；两个名字都探测一下，避免在新版本上 KeyError。"""
    if bsdf is None:
        return
    for key in ('Transmission Weight', 'Transmission'):
        if key in bsdf.inputs:
            try:
                bsdf.inputs[key].default_value = value
            except Exception:
                pass
            return


def _safe_set_render_type(settings, preferred='HALO'):
    """粒子 render_type 在不同 Blender 版本可选值不同；探测后再设，避免报错。"""
    try:
        prop = settings.bl_rna.properties['render_type']
        allowed = [e.identifier for e in prop.enum_items]
        for cand in (preferred, 'OBJECT', 'LINE', 'PATH', 'NONE'):
            if cand in allowed:
                settings.render_type = cand
                return cand
    except Exception:
        pass
    return None

# ===== 属性组和操作符 =====
class WildsVecFieldProperties(PropertyGroup):
    filepath: StringProperty(
        name="TFA文件",
        description=".tfa文件路径",
        subtype='FILE_PATH',
        default=""
    )
    
    scale_factor: FloatProperty(
        name="缩放比例",
        description="场的缩放因子",
        default=1.0,
        min=0.1,
        max=10.0
    )
    
    vector_scale: FloatProperty(
        name="向量缩放",
        description="向量可视化的缩放因子",
        default=1.0,
        min=0.01,
        max=10.0
    )
    
    resolution: IntProperty(
        name="分辨率",
        description="可视化网格的分辨率",
        default=8,
        min=2,
        max=20
    )
    
    show_vectors: BoolProperty(
        name="显示向量",
        description="显示向量箭头",
        default=True
    )
    
    color_by_magnitude: BoolProperty(
        name="箭头着色",
        description="为向量箭头着色（关闭则不着色）",
        default=True
    )

    arrow_color_mode: EnumProperty(
        name="着色方式",
        description="箭头颜色编码：方向 或 幅度",
        items=[
            ('DIRECTION', "按方向", "RGB=向量方向；幅度均匀的场也能看清流向结构"),
            ('MAGNITUDE', "按幅度", "蓝→红表示幅度大小"),
        ],
        default='DIRECTION'
    )

    auto_visualize: BoolProperty(
        name="自动可视化",
        description="导入后自动创建可视化",
        default=True
    )
    
    # 可视化模式选项
    visualization_mode: EnumProperty(
        name="可视化模式",
        description="选择可视化性能模式",
        items=[
            ('full', "完整", "完整可视化，包含所有元素"),
            ('lightweight', "轻量", "性能优化模式"),
            ('slices_only', "仅切片", "仅显示2D切片"),
            ('vectors_only', "仅向量", "仅显示向量箭头"),
            ('bounding_box_only', "仅边界框", "仅显示边界框")
        ],
        default='full'  # 默认使用完整模式，生成完整可视化
    )
    
    # 向量修改功能属性（支持多选）
    selected_vectors: CollectionProperty(
        type=PropertyGroup,
        description="选中的向量箭头列表"
    )
    
    selected_vector_index: IntProperty(
        name="选中向量索引",
        description="列表中当前选中的向量索引",
        default=-1
    )
    
    vector_edit_mode: BoolProperty(
        name="向量编辑模式",
        description="启用向量编辑模式",
        default=False
    )
    
    # 向量旋转参数
    rotation_axis: EnumProperty(
        name="旋转轴",
        description="向量旋转的轴",
        items=[
            ('X', "X轴", "绕X轴旋转"),
            ('Y', "Y轴", "绕Y轴旋转"),
            ('Z', "Z轴", "绕Z轴旋转")
        ],
        default='Z'
    )
    
    rotation_angle: FloatProperty(
        name="旋转角度",
        description="向量旋转的角度（度）",
        default=45.0,
        min=-360.0,
        max=360.0
    )
    
    # 单个向量数值设置
    vector_x: FloatProperty(
        name="向量X",
        description="向量的X分量（左右）",
        default=0.0,
        min=-1.0,
        max=1.0
    )
    
    vector_y: FloatProperty(
        name="向量Y",
        description="向量的Y分量（上下）",
        default=0.0,
        min=-1.0,
        max=1.0
    )
    
    vector_z: FloatProperty(
        name="向量Z",
        description="向量的Z分量（前后）",
        default=1.0,
        min=-1.0,
        max=1.0
    )
    
    # 向量预设工具属性
    preset_tool_type: EnumProperty(
        name="预设工具",
        description="向量修改预设工具",
        items=[
            ('RANDOM', "随机", "设置随机向量方向"),
            ('LINEAR', "线性", "设置向量为线性方向"),
            ('POINT_TO', "指向", "向量指向特定点"),
            ('REPEL', "排斥", "向量远离特定点"),
            ('SPIRAL', "螺旋", "创建螺旋图案"),
            ('VORTEX', "涡旋", "创建可自定义轴和方向的涡旋效果"),
            ('CONSTANT', "常量", "将所有向量设置为相同值")
        ],
        default='RANDOM'
    )
    
    # 目标点位置（用于指向和排斥工具）
    target_point_x: FloatProperty(
        name="目标X",
        description="目标点的X坐标",
        default=0.0
    )
    
    target_point_y: FloatProperty(
        name="目标Y",
        description="目标点的Y坐标",
        default=0.0
    )
    
    target_point_z: FloatProperty(
        name="目标Z",
        description="目标点的Z坐标",
        default=0.0
    )
    
    # 随机向量参数
    random_min_magnitude: FloatProperty(
        name="最小幅度",
        description="随机向量的最小幅度",
        default=-1.0,
        min=-1.0,
        max=1.0
    )
    
    random_max_magnitude: FloatProperty(
        name="最大幅度",
        description="随机向量的最大幅度",
        default=1.0,
        min=-1.0,
        max=1.0
    )
    
    # 线性向量参数
    linear_direction_x: FloatProperty(
        name="线性X",
        description="线性方向的X分量",
        default=1.0,
        min=-1.0,
        max=1.0
    )
    
    linear_direction_y: FloatProperty(
        name="线性Y",
        description="线性方向的Y分量",
        default=0.0,
        min=-1.0,
        max=1.0
    )
    
    linear_direction_z: FloatProperty(
        name="线性Z",
        description="线性方向的Z分量",
        default=0.0,
        min=-1.0,
        max=1.0
    )
    
    # 涡旋效果参数
    vortex_axis: EnumProperty(
        name="涡旋轴",
        description="涡旋旋转的轴",
        items=[
            ('X', "X轴", "绕X轴旋转"),
            ('Y', "Y轴", "绕Y轴旋转"),
            ('Z', "Z轴", "绕Z轴旋转")
        ],
        default='Z'
    )
    
    vortex_direction: EnumProperty(
        name="旋转方向",
        description="涡旋旋转方向",
        items=[
            ('CLOCKWISE', "顺时针", "顺时针旋转"),
            ('COUNTERCLOCKWISE', "逆时针", "逆时针旋转")
        ],
        default='COUNTERCLOCKWISE'
    )
    
    vortex_strength: FloatProperty(
        name="涡旋强度",
        description="涡旋效果的强度 (0.0 到 1.0)",
        default=1.0,
        min=0.0,
        max=1.0
    )
    
    vortex_radius: FloatProperty(
        name="影响半径",
        description="向量受影响的半径范围 (0.0 到 1.0)",
        default=1.0,
        min=0.0,
        max=1.0
    )
    
    vortex_radius_type: EnumProperty(
        name="半径类型",
        description="影响区域的形状",
        items=[
            ('CYLINDRICAL', "圆柱状", "圆柱状影响区域"),
            ('SPHERICAL', "球状", "球状影响区域")
        ],
        default='CYLINDRICAL'
    )
    
    vortex_elasticity: FloatProperty(
        name="弹性",
        description="半径内的衰减系数 (0.0 到 1.0)。0=恒定强度, 1=线性衰减",
        default=1.0,
        min=0.0,
        max=1.0
    )
    
    vortex_zero_center: BoolProperty(
        name="中心向量归0",
        description="将中心位置的向量设置为零",
        default=False
    )
    
    # 预设叠加功能属性
    preset_overlay_mode: BoolProperty(
        name="叠加模式",
        description="叠加预设而非替换",
        default=False
    )
    
    preset_overlay_strength: FloatProperty(
        name="叠加强度",
        description="叠加强度 (0.0 到 2.0)。1.0 = 轻微影响",
        default=1.0,
        min=0.0,
        max=2.0
    )
    
    # 测试性功能属性
    pixel_modification_strength: FloatProperty(
        name="像素修改强度",
        description="像素修改强度 (0.0 到 1.0)",
        default=0.5,
        min=0.0,
        max=1.0
    )
    
    pixel_modification_type: EnumProperty(
        name="修改类型",
        description="像素修改类型",
        items=[
            ('RANDOM', "随机", "随机像素值"),
            ('SINE', "正弦波", "正弦波图案"),
            ('LINEAR', "线性", "线性渐变"),
            ('CONSTANT', "常量", "常量值"),
            ('INVERT', "反转", "反转现有值"),
            ('X_ONLY', "仅X轴", "仅修改X轴 (左右)"),
            ('Y_ONLY', "仅Y轴", "仅修改Y轴 (上下)"),
            ('Z_ONLY', "仅Z轴", "仅修改Z轴 (前后)"),
            ('ENABLED_ONLY', "启用/禁用", "启用或禁用体素"),
            ('REGION_MODIFY', "区域修改", "修改场的特定区域"),
            ('FACE_PRESET', "面预设", "修改立方体的特定面"),
            ('RADIAL_PARTICLE_OFFSET', "径向粒子偏移", "径向偏移效果: -1=全部+ → 0=正常 → 1=全部-"),
            ('REPULSION', "排斥", "排斥效果: 按强度值分割粒子: <值→-, >值→+"),
            ('CONVERGENCE', "汇聚", "汇聚效果: 向量向中心汇聚，带涡旋选项"),
        ],
        default='RANDOM'
    )
    
    pixel_modification_constant: FloatProperty(
        name="常量值",
        description="要应用的常量值 (-1.0 到 1.0)\nFF=1.0 (正方向), 80=0.0 (中间), 00=-1.0 (负方向)",
        default=0.0,
        min=-1.0,
        max=1.0
    )
    
    # 排斥效果属性
    repulsion_axis: EnumProperty(
        name="排斥轴",
        description="应用排斥效果的轴",
        items=[
            ('X', "X轴", "沿X轴应用排斥效果 (左右)"),
            ('Y', "Y轴", "沿Y轴应用排斥效果 (上下)"),
            ('Z', "Z轴", "沿Z轴应用排斥效果 (前后)"),
        ],
        default='X'
    )
    
    repulsion_strength: FloatProperty(
        name="排斥强度",
        description="排斥效果的分割点 (-1.0 到 1.0)\n归一化位置 < 值 → 负方向\n归一化位置 > 值 → 正方向",
        default=0.0,
        min=-1.0,
        max=1.0
    )
    
    # 紧缩效果属性
    convergence_radius: FloatProperty(
        name="汇聚半径",
        description="向量向中心汇聚的半径范围",
        default=1.0,
        min=0.01,
        max=2.0
    )
    
    convergence_center_x: FloatProperty(
        name="汇聚中心X",
        description="汇聚中心的X坐标",
        default=0.0,
        min=-2.0,
        max=2.0
    )
    
    convergence_center_y: FloatProperty(
        name="Convergence Center Y",
        description="Y coordinate of convergence center",
        default=0.0,
        min=-2.0,
        max=2.0
    )
    
    convergence_center_z: FloatProperty(
        name="Convergence Center Z",
        description="Z coordinate of convergence center",
        default=0.0,
        min=-2.0,
        max=2.0
    )
    
    vortex_axis: EnumProperty(
        name="Vortex Axis",
        description="Axis around which vortex rotation occurs",
        items=[
            ('X', "X Axis", "Vortex rotation around X axis"),
            ('Y', "Y Axis", "Vortex rotation around Y axis"),
            ('Z', "Z Axis", "Vortex rotation around Z axis"),
        ],
        default='Z'
    )
    
    vortex_strength: FloatProperty(
        name="Vortex Strength",
        description="Strength of vortex rotation effect",
        default=0.0,
        min=0.0,
        max=2.0
    )
    
    # 启用/禁用体素 (布尔类型，替代原来的alpha值)
    voxel_enabled: BoolProperty(
        name="Voxel Enabled",
        description="Enable or disable voxels (0=禁用, 1=启用)",
        default=True
    )
    
    # 区域修改属性
    region_min_x: IntProperty(
        name="Region Min X",
        description="Minimum X coordinate of the region to modify",
        default=0,
        min=0
    )
    
    region_max_x: IntProperty(
        name="Region Max X",
        description="Maximum X coordinate of the region to modify",
        default=10,
        min=0
    )
    
    region_min_y: IntProperty(
        name="Region Min Y",
        description="Minimum Y coordinate of the region to modify",
        default=0,
        min=0
    )
    
    region_max_y: IntProperty(
        name="Region Max Y",
        description="Maximum Y coordinate of the region to modify",
        default=10,
        min=0
    )
    
    region_min_z: IntProperty(
        name="Region Min Z",
        description="Minimum Z coordinate of the region to modify",
        default=0,
        min=0
    )
    
    region_max_z: IntProperty(
        name="Region Max Z",
        description="Maximum Z coordinate of the region to modify",
        default=10,
        min=0
    )
    
    # 面朝向预设
    face_preset: EnumProperty(
        name="Face Preset",
        description="Preset for modifying a specific face of the cube",
        items=[
            ('FRONT', "Front", "Modify front face (Z=max)"),
            ('BACK', "Back", "Modify back face (Z=min)"),
            ('LEFT', "Left", "Modify left face (X=min)"),
            ('RIGHT', "Right", "Modify right face (X=max)"),
            ('TOP', "Top", "Modify top face (Y=max)"),
            ('BOTTOM', "Bottom", "Modify bottom face (Y=min)"),
        ],
        default='FRONT'
    )
    
    # 单独分量修改属性
    modify_x: BoolProperty(
        name="Modify X",
        description="Enable modification of X component (左右)",
        default=True
    )
    
    modify_y: BoolProperty(
        name="Modify Y",
        description="Enable modification of Y component (上下)",
        default=True
    )
    
    modify_z: BoolProperty(
        name="Modify Z",
        description="Enable modification of Z component (前后)",
        default=True
    )
    
    modify_enabled: BoolProperty(
        name="Modify Enabled",
        description="Enable modification of voxel enabled state",
        default=True
    )

# 导入 Wilds 原生向量场（.tex）操作符
class WILDS_VF_OT_load_tex(Operator, ImportHelper):
    bl_idname = "wilds_vecfield.load_tex"
    bl_label = "Load Wilds Vector Field"
    bl_description = ("导入Monster Hunter Wilds原生.tex向量场贴图；"
                       "只支持已验证过的组合：BC1压缩、单张体积贴图")

    filename_ext = ""

    filter_glob: StringProperty(
        default="*.tex.*",
        options={'HIDDEN'},
    )

    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props

        try:
            field_data = parse_wilds_tex_file(self.filepath)
        except WildsTexError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"导入失败: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        scene['wilds_vecfield_data'] = {
            'vectors': field_data['vectors'].tolist(),
            'dimensions': field_data['dimensions'],
            'version': field_data['version'],
            'detected_size': field_data['detected_size'],
            'alpha': field_data['rgba_data'][..., 3].tolist(),
        }

        props.filepath = self.filepath

        if props.auto_visualize:
            bpy.ops.wilds_vecfield.visualize_field()

        self.report({'INFO'}, f"Imported Wilds vector field: {self.filepath}")
        return {'FINISHED'}

# 生成基础向量场操作符
class WILDS_VF_OT_generate_base(Operator):
    bl_idname = "wilds_vecfield.generate_base"
    bl_label = "生成基础向量场"
    bl_description = "生成全零向量的立方体向量场，供从零开始手动编辑"

    dimensions: EnumProperty(
        name="Dimensions",
        description="向量场的立方体边长（游戏内实测出现过 32/64；16 只是编辑用的轻量选项，未在语料里见过）",
        items=[
            ('16', "16×16×16", "16×16×16 field"),
            ('32', "32×32×32", "32×32×32 field（语料实测尺寸）"),
            ('64', "64×64×64", "64×64×64 field（语料实测尺寸）"),
        ],
        default='32'
    )

    version: IntProperty(
        name="Version",
        description="tex 版本号（写出 .tex 时用，MHWs 目前只验证过 241106027）",
        default=241106027,
    )

    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props

        try:
            dim = int(self.dimensions)
            vectors = np.zeros((dim, dim, dim, 3), dtype=np.float32)
            alpha = np.ones((dim, dim, dim), dtype=np.uint8)

            scene['wilds_vecfield_data'] = {
                'vectors': vectors.tolist(),
                'dimensions': (dim, dim, dim),
                'version': self.version,
                'detected_size': f"{dim}x{dim}x{dim}",
                'alpha': alpha.tolist(),
            }

            props.filepath = f"generated_{dim}x{dim}x{dim}.tex.{self.version}"

            if props.auto_visualize:
                bpy.ops.wilds_vecfield.visualize_field()

            self.report({'INFO'}, f"Generated base {dim}x{dim}x{dim} vector field")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Generation error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

# 导出为 Wilds 原生向量场（.tex）操作符
class WILDS_VF_OT_save_tex(Operator, ExportHelper):
    bl_idname = "wilds_vecfield.save_tex"
    bl_label = "Save Wilds Vector Field"
    bl_description = ("将当前向量场写成 MHWs 原生 .tex.241106027（BC1 + GDeflate）；"
                       "注意：BC1 是有损压缩，写出后再读回来数值会有轻微量化误差，"
                       "且尚未在游戏里实机验证过写出的体积贴图能被正确加载")

    filename_ext = ".tex.241106027"

    filter_glob: StringProperty(
        default="*.tex.*",
        options={'HIDDEN'},
    )

    check_extension = None  # ExportHelper 默认会吃掉版本号后缀，这里关掉自动补全/校验

    def execute(self, context):
        scene = context.scene

        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No vector field data to export")
            return {'CANCELLED'}

        try:
            field_data = scene['wilds_vecfield_data']
            vectors = np.array(field_data['vectors'], dtype=np.float32)
            version = int(field_data.get('version', VERSION_MHWILDS))

            build_wilds_vecfield_tex_file(vectors, version, self.filepath)

            self.report({'INFO'}, f"Exported Wilds vector field: {self.filepath}")
            return {'FINISHED'}

        except WildsTexError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Export error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

    def invoke(self, context, event):
        if context.scene.wilds_vecfield_props.filepath:
            original_path = Path(context.scene.wilds_vecfield_props.filepath)
            self.filepath = f"{original_path.stem}_exported.tex.241106027"
        else:
            self.filepath = "vector_field.tex.241106027"
        return super().invoke(context, event)


# 可视化操作符
class WILDS_VF_OT_visualize_field(Operator):
    bl_idname = "wilds_vecfield.visualize_field"
    bl_label = "可视化场"
    bl_description = "为导入的湍流场创建可视化"
    
    # 新增可视化选项
    show_streamlines: BoolProperty(
        name="Show Streamlines",
        description="Display particle flow streamlines",
        default=True
    )
    
    show_slices: BoolProperty(
        name="Show Field Slices",
        description="Display 2D field slices",
        default=False
    )
    
    slice_axis: EnumProperty(
        name="Slice Axis",
        description="Axis to create slice on",
        items=[
            ('X', "X Axis", "Create slice along X axis"),
            ('Y', "Y Axis", "Create slice along Y axis"),
            ('Z', "Z Axis", "Create slice along Z axis"),
        ],
        default='Z'
    )
    
    slice_position: FloatProperty(
        name="Slice Position",
        description="Position of the slice along the axis (0.0 to 1.0)",
        default=0.5,
        min=0.0,
        max=1.0
    )
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No TFA file loaded. Import a file first.")
            return {'CANCELLED'}
        
        try:
            # 尝试导入可视化模块
            import importlib
            import sys
            
            try:
                if 'blender_efx_re.wilds_vecfield_visualizer' in sys.modules:
                    importlib.reload(sys.modules['blender_efx_re.wilds_vecfield_visualizer'])
                    from . import wilds_vecfield_visualizer as vector_field_visualizer
                else:
                    from . import wilds_vecfield_visualizer as vector_field_visualizer
            except ImportError:
                # 如果模块不存在，使用简单的替代方案
                self.report({'WARNING'}, "Using simple visualization")
                create_simple_visualization(context)
                return {'FINISHED'}
            
            # 获取场数据
            field_data = scene['wilds_vecfield_data']
            vectors = np.array(field_data['vectors'])
            dimensions = field_data['dimensions']
            
            print(f"开始可视化: {dimensions}")
            
            # 创建可视化 - 使用增强版可视化
            vector_field_visualizer.create_visualization(
                vectors,
                dimensions,
                scale_factor=props.scale_factor,
                vector_scale=props.vector_scale,
                resolution=props.resolution,
                show_vectors=props.show_vectors,
                color_by_magnitude=props.color_by_magnitude,
                arrow_color_mode=props.arrow_color_mode,
                show_streamlines=self.show_streamlines,
                show_slices=self.show_slices,
                slice_axis=self.slice_axis,
                slice_position=self.slice_position,
                visualization_mode=props.visualization_mode,
                show_bounds=False
            )
            
            self.report({'INFO'}, "Field visualization created successfully")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Visualization error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=350)

def create_simple_visualization(context):
    """简单的可视化替代方案"""
    scene = context.scene
    props = scene.wilds_vecfield_props
    
    if 'wilds_vecfield_data' not in scene:
        return
    
    field_data = scene['wilds_vecfield_data']
    dimensions = field_data['dimensions']
    
    # 创建立方体边界框
    bpy.ops.mesh.primitive_cube_add(size=1)
    cube = bpy.context.active_object
    cube.name = "MHWilds_VecField_Bounds"
    cube.scale = (dimensions[0] * props.scale_factor / 2,
                  dimensions[1] * props.scale_factor / 2,
                  dimensions[2] * props.scale_factor / 2)
    
    # 设置材质
    mat = bpy.data.materials.new("Field_Bounds")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.3, 0.3, 0.3, 0.2)
        _set_bsdf_transmission(bsdf, 0.5)
    cube.data.materials.append(mat)

# 清除场数据操作符
class WILDS_VF_OT_clear_field(Operator):
    bl_idname = "wilds_vecfield.clear_field"
    bl_label = "清除场"
    bl_description = "移除所有场数据和可视化"
    
    def execute(self, context):
        scene = context.scene
        
        # 删除场数据
        if 'wilds_vecfield_data' in scene:
            del scene['wilds_vecfield_data']
        
        # 删除可视化集合
        collection_name = "MHWilds_VecField"
        if collection_name in bpy.data.collections:
            collection = bpy.data.collections[collection_name]
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(collection)
        
        # 删除粒子系统集合
        particle_collection_name = "MHWilds_VecField_Particles"
        if particle_collection_name in bpy.data.collections:
            collection = bpy.data.collections[particle_collection_name]
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(collection)
        
        # 重置文件路径
        scene.wilds_vecfield_props.filepath = ""
        
        self.report({'INFO'}, "Field data and visualizations cleared")
        return {'FINISHED'}

# 清除场景所有物体操作符
class WILDS_VF_OT_clear_all_objects(Operator):
    bl_idname = "wilds_vecfield.clear_all_objects"
    bl_label = "清除所有对象"
    bl_description = "移除场景中的所有对象"
    
    def execute(self, context):
        # 删除场景中的所有物体
        for obj in list(context.scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        
        # 重置文件路径
        context.scene.wilds_vecfield_props.filepath = ""
        
        # 清除场数据
        if 'wilds_vecfield_data' in context.scene:
            del context.scene['wilds_vecfield_data']
        
        self.report({'INFO'}, "All objects cleared from scene")
        return {'FINISHED'}

# 选择向量操作符（支持多选）
class WILDS_VF_OT_select_vector(Operator):
    bl_idname = "wilds_vecfield.select_vector"
    bl_label = "选择向量"
    bl_description = "添加/移除向量箭头到选择列表。使用框选选择多个向量，然后运行此操作符。"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        # 检查是否有选中的对象或活动对象是向量箭头
        return len(context.selected_objects) > 0 or (context.active_object is not None and context.active_object.name.startswith("Arrow_"))
    
    def execute(self, context):
        props = context.scene.wilds_vecfield_props
        selected_objects = context.selected_objects
        
        # 如果没有选中的对象，就使用活动对象
        if not selected_objects and context.active_object:
            selected_objects = [context.active_object]
        
        updated_count = 0
        
        for obj in selected_objects:
            if not obj.name.startswith("Arrow_"):
                continue
            
            # 解析向量坐标
            try:
                name_parts = obj.name.split("_")
                x = int(name_parts[1])
                y = int(name_parts[2])
                z = int(name_parts[3])
                
                # 检查该向量是否已在选中列表中
                vector_name = obj.name
                is_selected = any(v.name == vector_name for v in props.selected_vectors)
                
                if is_selected:
                    # 移除选中的向量
                    for i, v in enumerate(props.selected_vectors):
                        if v.name == vector_name:
                            props.selected_vectors.remove(i)
                            updated_count -= 1
                            break
                    self.report({'INFO'}, f"Removed vector from selection: {vector_name}")
                else:
                    # 添加到选中列表
                    vector_item = props.selected_vectors.add()
                    vector_item.name = vector_name
                    vector_item["coords"] = (x, y, z)
                    updated_count += 1
                    self.report({'INFO'}, f"Added vector to selection: {vector_name}")
            except Exception as e:
                self.report({'WARNING'}, f"Failed to process vector {obj.name}: {str(e)}")
                continue
        
        if updated_count > 0:
            props.vector_edit_mode = True
            self.report({'INFO'}, f"Added {updated_count} vectors to selection")
        elif updated_count < 0:
            if len(props.selected_vectors) == 0:
                props.vector_edit_mode = False
            self.report({'INFO'}, f"Removed {-updated_count} vectors from selection")
        else:
            self.report({'INFO'}, "No vectors were added or removed from selection")
        
        return {'FINISHED'}

# 清除选中向量列表操作符
class WILDS_VF_OT_clear_selected_vectors(Operator):
    bl_idname = "wilds_vecfield.clear_selected_vectors"
    bl_label = "清除选中向量"
    bl_description = "清除所有选中的向量"
    
    def execute(self, context):
        props = context.scene.wilds_vecfield_props
        props.selected_vectors.clear()
        props.vector_edit_mode = False
        self.report({'INFO'}, "Cleared all selected vectors")
        return {'FINISHED'}

# 更新向量方向操作符（支持多选）
class WILDS_VF_OT_update_vector(Operator):
    bl_idname = "wilds_vecfield.update_vector"
    bl_label = "更新向量"
    bl_description = "根据选中箭头的旋转更新向量场"
    
    @classmethod
    def poll(cls, context):
        props = context.scene.wilds_vecfield_props
        return len(props.selected_vectors) > 0 and 'wilds_vecfield_data' in context.scene
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No vector field data found")
            return {'CANCELLED'}
        
        field_data = scene['wilds_vecfield_data']
        vectors = np.array(field_data['vectors'])
        updated_count = 0
        
        for vector_item in props.selected_vectors:
            vector_name = vector_item.name
            if vector_name not in bpy.data.objects:
                continue
            
            arrow_obj = bpy.data.objects[vector_name]
            x, y, z = vector_item["coords"]
            
            # 获取当前箭头的旋转方向
            direction = Vector((0, 0, 1))
            if arrow_obj.rotation_mode == 'QUATERNION':
                direction.rotate(arrow_obj.rotation_quaternion)
            else:
                direction.rotate(arrow_obj.rotation_euler)
            
            direction.normalize()
            
            # 获取原始向量的幅度
            original_magnitude = np.linalg.norm(vectors[z, y, x])
            
            # 更新向量方向，保持原始幅度
            vectors[z, y, x] = direction * original_magnitude
            
            # 更新相关的力场
            self.update_related_force_fields(scene, x, y, z, direction * original_magnitude)
            updated_count += 1
        
        # 更新场景中的向量场数据
        field_data['vectors'] = vectors.tolist()
        scene['wilds_vecfield_data'] = field_data
        
        self.report({'INFO'}, f"Updated {updated_count} vectors")
        return {'FINISHED'}
    
    def update_related_force_fields(self, scene, x, y, z, new_vector):
        """更新与该向量相关的力场"""
        magnitude = np.linalg.norm(new_vector)
        
        # 查找相关的力场
        for obj in scene.objects:
            if obj.name.startswith(f"MHWildsVF_Force_{x}_") and f"_{y}_" in obj.name and f"_{z}" in obj.name:
                # 更新力场方向和强度
                obj.field.strength = magnitude * 2.0
                
                direction = Vector(new_vector).normalized()
                obj.rotation_mode = 'QUATERNION'
                obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                break

# 旋转向量操作符
class WILDS_VF_OT_rotate_vectors(Operator):
    bl_idname = "wilds_vecfield.rotate_vectors"
    bl_label = "旋转向量"
    bl_description = "绕指定轴旋转选中的向量"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        props = context.scene.wilds_vecfield_props
        return len(props.selected_vectors) > 0 and 'wilds_vecfield_data' in context.scene
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No vector field data found")
            return {'CANCELLED'}
        
        field_data = scene['wilds_vecfield_data']
        vectors = np.array(field_data['vectors'])
        updated_count = 0
        
        # 转换角度为弧度
        angle_rad = np.radians(props.rotation_angle)
        axis = props.rotation_axis
        
        # 创建旋转矩阵
        if axis == 'X':
            rotation_matrix = np.array([
                [1, 0, 0],
                [0, np.cos(angle_rad), -np.sin(angle_rad)],
                [0, np.sin(angle_rad), np.cos(angle_rad)]
            ])
        elif axis == 'Y':
            rotation_matrix = np.array([
                [np.cos(angle_rad), 0, np.sin(angle_rad)],
                [0, 1, 0],
                [-np.sin(angle_rad), 0, np.cos(angle_rad)]
            ])
        else:  # Z轴
            rotation_matrix = np.array([
                [np.cos(angle_rad), -np.sin(angle_rad), 0],
                [np.sin(angle_rad), np.cos(angle_rad), 0],
                [0, 0, 1]
            ])
        
        for vector_item in props.selected_vectors:
            x, y, z = vector_item["coords"]
            
            # 获取当前向量
            current_vector = vectors[z, y, x]
            
            # 应用旋转
            rotated_vector = np.dot(rotation_matrix, current_vector)
            
            # 更新向量场数据
            vectors[z, y, x] = rotated_vector
            
            # 更新相关的箭头和力场
            vector_name = vector_item.name
            if vector_name in bpy.data.objects:
                arrow_obj = bpy.data.objects[vector_name]
                # 更新箭头方向
                direction = Vector(rotated_vector).normalized()
                arrow_obj.rotation_mode = 'QUATERNION'
                arrow_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
            
            # 更新相关的力场
            self.update_related_force_fields(scene, x, y, z, rotated_vector)
            updated_count += 1
        
        # 更新场景中的向量场数据
        field_data['vectors'] = vectors.tolist()
        scene['wilds_vecfield_data'] = field_data
        
        self.report({'INFO'}, f"Rotated {updated_count} vectors by {props.rotation_angle} degrees around {axis} axis")
        return {'FINISHED'}
    
    def update_related_force_fields(self, scene, x, y, z, new_vector):
        """更新与该向量相关的力场"""
        magnitude = np.linalg.norm(new_vector)
        
        # 查找相关的力场
        for obj in scene.objects:
            if obj.name.startswith(f"MHWildsVF_Force_{x}_") and f"_{y}_" in obj.name and f"_{z}" in obj.name:
                # 更新力场方向和强度
                obj.field.strength = magnitude * 2.0
                
                direction = Vector(new_vector).normalized()
                obj.rotation_mode = 'QUATERNION'
                obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                break

# 反转向量操作符
class WILDS_VF_OT_invert_vectors(Operator):
    bl_idname = "wilds_vecfield.invert_vectors"
    bl_label = "反转向量"
    bl_description = "反转选中向量的方向"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        props = context.scene.wilds_vecfield_props
        return len(props.selected_vectors) > 0 and 'wilds_vecfield_data' in context.scene
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No vector field data found")
            return {'CANCELLED'}
        
        field_data = scene['wilds_vecfield_data']
        vectors = np.array(field_data['vectors'])
        updated_count = 0
        
        for vector_item in props.selected_vectors:
            x, y, z = vector_item["coords"]
            
            # 反转向量
            current_vector = vectors[z, y, x]
            inverted_vector = -current_vector
            
            # 更新向量场数据
            vectors[z, y, x] = inverted_vector
            
            # 更新相关的箭头和力场
            vector_name = vector_item.name
            if vector_name in bpy.data.objects:
                arrow_obj = bpy.data.objects[vector_name]
                # 更新箭头方向
                direction = Vector(inverted_vector).normalized()
                arrow_obj.rotation_mode = 'QUATERNION'
                arrow_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
            
            # 更新相关的力场
            self.update_related_force_fields(scene, x, y, z, inverted_vector)
            updated_count += 1
        
        # 更新场景中的向量场数据
        field_data['vectors'] = vectors.tolist()
        scene['wilds_vecfield_data'] = field_data
        
        self.report({'INFO'}, f"Inverted {updated_count} vectors")
        return {'FINISHED'}
    
    def update_related_force_fields(self, scene, x, y, z, new_vector):
        """更新与该向量相关的力场"""
        magnitude = np.linalg.norm(new_vector)
        
        # 查找相关的力场
        for obj in scene.objects:
            if obj.name.startswith(f"MHWildsVF_Force_{x}_") and f"_{y}_" in obj.name and f"_{z}" in obj.name:
                # 更新力场方向和强度
                obj.field.strength = magnitude * 2.0
                
                direction = Vector(new_vector).normalized()
                obj.rotation_mode = 'QUATERNION'
                obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                break

# 设置向量数值操作符
class WILDS_VF_OT_set_vector_values(Operator):
    bl_idname = "wilds_vecfield.set_vector_values"
    bl_label = "设置向量值"
    bl_description = "直接设置选中向量的值"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        props = context.scene.wilds_vecfield_props
        return len(props.selected_vectors) > 0 and 'wilds_vecfield_data' in context.scene
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No vector field data found")
            return {'CANCELLED'}
        
        field_data = scene['wilds_vecfield_data']
        vectors = np.array(field_data['vectors'])
        updated_count = 0
        
        # 获取用户设置的向量值
        new_vector = np.array([props.vector_x, props.vector_y, props.vector_z])
        
        for vector_item in props.selected_vectors:
            x, y, z = vector_item["coords"]
            
            # 获取原始向量的幅度（可选：保持原始幅度）
            original_magnitude = np.linalg.norm(vectors[z, y, x])
            
            # 计算新向量的幅度
            new_magnitude = np.linalg.norm(new_vector)
            
            # 如果新向量的幅度不为零，则使用用户设置的值，否则保持原始方向
            if new_magnitude > 0:
                # 可以选择保持原始幅度或使用新的幅度
                # 使用新的幅度
                final_vector = new_vector
                # 或者保持原始幅度：final_vector = new_vector / new_magnitude * original_magnitude
            else:
                # 如果新向量为零，保持原始向量
                final_vector = vectors[z, y, x]
            
            # 更新向量场数据
            vectors[z, y, x] = final_vector
            
            # 更新相关的箭头和力场
            vector_name = vector_item.name
            if vector_name in bpy.data.objects:
                arrow_obj = bpy.data.objects[vector_name]
                # 更新箭头方向
                direction = Vector(final_vector).normalized()
                arrow_obj.rotation_mode = 'QUATERNION'
                arrow_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                # 更新箭头长度
                arrow_length = np.linalg.norm(final_vector) * props.vector_scale
                arrow_obj.scale = (props.vector_scale * 0.5, props.vector_scale * 0.5, arrow_length)
            
            # 更新相关的力场
            self.update_related_force_fields(scene, x, y, z, final_vector)
            updated_count += 1
        
        # 更新场景中的向量场数据
        field_data['vectors'] = vectors.tolist()
        scene['wilds_vecfield_data'] = field_data
        
        self.report({'INFO'}, f"Set values for {updated_count} vectors")
        return {'FINISHED'}
    
    def update_related_force_fields(self, scene, x, y, z, new_vector):
        """更新与该向量相关的力场"""
        magnitude = np.linalg.norm(new_vector)
        
        # 查找相关的力场
        for obj in scene.objects:
            if obj.name.startswith(f"MHWildsVF_Force_{x}_") and f"_{y}_" in obj.name and f"_{z}" in obj.name:
                # 更新力场方向和强度
                obj.field.strength = magnitude * 2.0
                
                direction = Vector(new_vector).normalized()
                obj.rotation_mode = 'QUATERNION'
                obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                break

# 向量预设工具操作符
class WILDS_VF_OT_apply_vector_preset(Operator):
    bl_idname = "wilds_vecfield.apply_vector_preset"
    bl_label = "应用向量预设"
    bl_description = "将向量修改预设应用到选中向量"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        props = context.scene.wilds_vecfield_props
        return len(props.selected_vectors) > 0 and 'wilds_vecfield_data' in context.scene
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No vector field data found")
            return {'CANCELLED'}
        
        field_data = scene['wilds_vecfield_data']
        vectors = np.array(field_data['vectors'])
        updated_count = 0
        
        # 获取目标点
        target_point = np.array([props.target_point_x, props.target_point_y, props.target_point_z])
        
        for vector_item in props.selected_vectors:
            x, y, z = vector_item["coords"]
            
            # 当前向量位置
            vector_pos = np.array([x, y, z])
            new_vector = np.array([0.0, 0.0, 0.0])
            
            # 根据预设类型计算新向量
            preset_type = props.preset_tool_type
            
            if preset_type == 'RANDOM':
                # 随机向量
                magnitude = np.random.uniform(props.random_min_magnitude, props.random_max_magnitude)
                direction = np.random.randn(3)
                if np.linalg.norm(direction) > 0:
                    direction = direction / np.linalg.norm(direction)
                new_vector = direction * magnitude
            
            elif preset_type == 'LINEAR':
                # 线性方向
                linear_dir = np.array([props.linear_direction_x, props.linear_direction_y, props.linear_direction_z])
                if np.linalg.norm(linear_dir) > 0:
                    linear_dir = linear_dir / np.linalg.norm(linear_dir)
                new_vector = linear_dir
            
            elif preset_type == 'POINT_TO':
                # 指向Blender游标位置
                cursor_pos = np.array(bpy.context.scene.cursor.location)
                # 转换向量坐标到世界空间
                # 计算向量场的尺寸和中心
                depth, height, width, _ = vectors.shape
                center = np.array([width/2, height/2, depth/2])
                # 将向量的网格坐标转换为世界坐标
                world_vector_pos = vector_pos - center
                # 计算方向
                direction = cursor_pos - world_vector_pos
                if np.linalg.norm(direction) > 0:
                    direction = direction / np.linalg.norm(direction)
                new_vector = direction
            
            elif preset_type == 'REPEL':
                # 远离Blender游标位置
                cursor_pos = np.array(bpy.context.scene.cursor.location)
                # 转换向量坐标到世界空间
                depth, height, width, _ = vectors.shape
                center = np.array([width/2, height/2, depth/2])
                world_vector_pos = vector_pos - center
                # 计算方向
                direction = world_vector_pos - cursor_pos
                if np.linalg.norm(direction) > 0:
                    direction = direction / np.linalg.norm(direction)
                new_vector = direction
            
            elif preset_type == 'SPIRAL':
                # 螺旋模式
                radius = np.linalg.norm(vector_pos)
                if radius > 0:
                    # 径向单位向量
                    radial = vector_pos / radius
                    # 垂直于径向的单位向量（逆时针）
                    tangential = np.array([-radial[1], radial[0], 0])
                    if np.linalg.norm(tangential) == 0:
                        tangential = np.array([0, -radial[2], radial[1]])
                    if np.linalg.norm(tangential) > 0:
                        tangential = tangential / np.linalg.norm(tangential)
                    # 螺旋方向：径向向外 + 切向
                    new_vector = radial + tangential
                    new_vector = new_vector / np.linalg.norm(new_vector)
            
            elif preset_type == 'VORTEX':
                # 涡旋效果
                # 获取向量场的尺寸，用于计算相对坐标
                depth, height, width, _ = vectors.shape
                
                # 计算向量场中心
                center = np.array([width/2, height/2, depth/2])
                
                # 计算向量到中心的偏移
                offset = vector_pos - center
                
                # 根据所选轴向计算距离和切向方向
                axis = props.vortex_axis
                direction = props.vortex_direction
                strength = props.vortex_strength
                max_radius = props.vortex_radius * max(width, height, depth) / 2
                radius_type = props.vortex_radius_type
                elasticity = props.vortex_elasticity
                
                # 旋向因子
                direction_factor = -1.0 if direction == 'CLOCKWISE' else 1.0
                
                # 计算实际距离
                if radius_type == 'CYLINDRICAL':
                    # 圆柱半径：垂直于轴向的距离
                    if axis == 'X':
                        distance = np.sqrt(offset[1]**2 + offset[2]**2)
                        # 计算切向方向（垂直于轴向和径向）
                        if distance > 0:
                            tangential = np.array([0, -offset[2], offset[1]]) * direction_factor
                        else:
                            tangential = np.array([0, 1, 0]) * direction_factor
                    elif axis == 'Y':
                        distance = np.sqrt(offset[0]**2 + offset[2]**2)
                        if distance > 0:
                            tangential = np.array([offset[2], 0, -offset[0]]) * direction_factor
                        else:
                            tangential = np.array([1, 0, 0]) * direction_factor
                    else:  # Z轴
                        distance = np.sqrt(offset[0]**2 + offset[1]**2)
                        if distance > 0:
                            tangential = np.array([-offset[1], offset[0], 0]) * direction_factor
                        else:
                            tangential = np.array([0, 1, 0]) * direction_factor
                else:  # SPHERICAL
                    # 球半径：三维距离
                    distance = np.linalg.norm(offset)
                    if distance > 0:
                        # 计算径向向量
                        radial = offset / distance
                        # 计算垂直于轴向和径向的切向方向
                        if axis == 'X':
                            up = np.array([1, 0, 0])
                        elif axis == 'Y':
                            up = np.array([0, 1, 0])
                        else:  # Z轴
                            up = np.array([0, 0, 1])
                        # 叉乘计算切向方向
                        tangential = np.cross(up, radial) * direction_factor
                        if np.linalg.norm(tangential) == 0:
                            # 如果径向与轴向平行，使用默认切向
                            if axis == 'X':
                                tangential = np.array([0, 1, 0]) * direction_factor
                            elif axis == 'Y':
                                tangential = np.array([1, 0, 0]) * direction_factor
                            else:  # Z轴
                                tangential = np.array([0, 1, 0]) * direction_factor
                    else:
                        # 中心位置的默认方向
                        if axis == 'X':
                            tangential = np.array([0, 1, 0]) * direction_factor
                        elif axis == 'Y':
                            tangential = np.array([1, 0, 0]) * direction_factor
                        else:  # Z轴
                            tangential = np.array([0, 1, 0]) * direction_factor
                
                # 归一化切向方向
                if np.linalg.norm(tangential) > 0:
                    tangential = tangential / np.linalg.norm(tangential)
                
                # 计算弹性衰减因子
                if distance <= max_radius:
                    # 距离在影响范围内
                    # 检查是否需要将中心向量归零
                    if props.vortex_zero_center and distance < 0.5:
                        # 中心位置向量归0
                        new_vector = np.array([0.0, 0.0, 0.0])
                    else:
                        # 弹性衰减：距离越远，影响越小
                        # elasticity=0: 恒定强度；elasticity=1: 线性衰减
                        falloff = 1.0 - (distance / max_radius) * elasticity
                        # 应用力度和衰减因子
                        vortex_vector = tangential * strength * falloff
                        new_vector = vortex_vector
                else:
                    # 距离超出影响范围，不应用涡旋效果
                    new_vector = np.array([0.0, 0.0, 0.0])
            
            elif preset_type == 'CONSTANT':
                # 常量向量
                new_vector = np.array([props.vector_x, props.vector_y, props.vector_z])
            
            # 更新向量
            if props.preset_overlay_mode:
                # 叠加模式：主模式（原始向量）保持主导，副模式（新向量）微调
                original_vector = vectors[z, y, x]
                
                # 保持原始向量的幅度
                original_magnitude = np.linalg.norm(original_vector)
                if original_magnitude == 0:
                    # 如果原始向量为零，直接使用新向量
                    vectors[z, y, x] = new_vector
                else:
                    # 计算混合系数：强度范围0-2，1.0=轻微影响
                    # 公式：系数 = 强度 / 4，这样1.0对应25%的副模式影响
                    blend_factor = props.preset_overlay_strength / 4.0
                    
                    # 归一化原始向量和新向量
                    original_dir = original_vector / original_magnitude
                    new_dir = new_vector / np.linalg.norm(new_vector) if np.linalg.norm(new_vector) > 0 else original_dir
                    
                    # 使用球面线性插值（slerp）进行方向混合，保持平滑过渡
                    # slerp公式简化版：(1-t)*a + t*b，适合小角度调整
                    blended_dir = original_dir * (1.0 - blend_factor) + new_dir * blend_factor
                    
                    # 归一化混合后的方向
                    if np.linalg.norm(blended_dir) > 0:
                        blended_dir = blended_dir / np.linalg.norm(blended_dir)
                    
                    # 重新应用原始幅度
                    blended_vector = blended_dir * original_magnitude
                    vectors[z, y, x] = blended_vector
            else:
                # 替换模式：直接使用新向量
                vectors[z, y, x] = new_vector
            
            # 更新相关的箭头和力场
            vector_name = vector_item.name
            if vector_name in bpy.data.objects:
                arrow_obj = bpy.data.objects[vector_name]
                # 更新箭头方向
                direction = Vector(new_vector).normalized()
                arrow_obj.rotation_mode = 'QUATERNION'
                arrow_obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                # 更新箭头长度
                arrow_length = np.linalg.norm(new_vector) * props.vector_scale
                arrow_obj.scale = (props.vector_scale * 0.5, props.vector_scale * 0.5, arrow_length)
            
            # 更新相关的力场
            self.update_related_force_fields(scene, x, y, z, new_vector)
            updated_count += 1
        
        # 更新场景中的向量场数据
        field_data['vectors'] = vectors.tolist()
        scene['wilds_vecfield_data'] = field_data
        
        self.report({'INFO'}, f"Applied {preset_type} preset to {updated_count} vectors")
        return {'FINISHED'}
    
    def update_related_force_fields(self, scene, x, y, z, new_vector):
        """更新与该向量相关的力场"""
        magnitude = np.linalg.norm(new_vector)
        
        # 查找相关的力场
        for obj in scene.objects:
            if obj.name.startswith(f"MHWildsVF_Force_{x}_") and f"_{y}_" in obj.name and f"_{z}" in obj.name:
                if obj.type == 'EMPTY' and obj.field.type == 'FORCE':
                    # 更新力场强度和方向
                    direction = Vector(new_vector).normalized()
                    obj.field.strength = magnitude * 2.0  # 力场强度调整
                    obj.rotation_mode = 'QUATERNION'
                    obj.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                    break

# 退出向量编辑模式操作符
class WILDS_VF_OT_exit_vector_edit(Operator):
    bl_idname = "wilds_vecfield.exit_vector_edit"
    bl_label = "退出向量编辑模式"
    bl_description = "退出向量编辑模式"
    
    def execute(self, context):
        props = context.scene.wilds_vecfield_props
        props.vector_edit_mode = False
        props.selected_vectors.clear()
        self.report({'INFO'}, "Exited vector edit mode and cleared selected vectors")
        return {'FINISHED'}

# 粒子系统可视化操作符
class WILDS_VF_OT_particle_system(Operator):
    bl_idname = "wilds_vecfield.particle_system"
    bl_label = "粒子系统 (测试系统慎用)"
    bl_description = """使用TFA向量场作为力场创建粒子系统可视化

⚠️ 测试系统：可能导致性能问题，建议在高性能设备上使用
⚠️ 生成大量对象，可能导致Blender卡顿
⚠️ 建议先使用可视化功能预览效果"""
    
    # 粒子系统参数
    particle_count: IntProperty(
        name="粒子数量",
        description="发射的粒子数量",
        default=1000,
        min=100,
        max=10000
    )
    
    emitter_radius: FloatProperty(
        name="发射器半径",
        description="粒子发射器的半径",
        default=1.0,
        min=0.1,
        max=5.0
    )
    
    particle_lifetime: FloatProperty(
        name="粒子生命周期",
        description="每个粒子的生命周期（秒）",
        default=5.0,
        min=1.0,
        max=20.0
    )
    
    particle_size: FloatProperty(
        name="粒子大小",
        description="每个粒子的大小",
        default=0.05,
        min=0.01,
        max=0.2
    )
    
    enable_velocity: BoolProperty(
        name="启用初始速度",
        description="为粒子启用初始速度",
        default=True
    )
    
    initial_velocity: FloatProperty(
        name="初始速度",
        description="粒子的初始速度",
        default=1.0,
        min=0.0,
        max=5.0
    )
    
    # 起始帧和结束帧设置
    start_frame: IntProperty(
        name="Start Frame",
        description="Frame to start emitting particles",
        default=1,
        min=1,
        max=10000
    )
    
    end_frame: IntProperty(
        name="End Frame",
        description="Frame to stop emitting particles",
        default=100,
        min=1,
        max=10000
    )
    
    def execute(self, context):
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No TFA file loaded. Import a file first.")
            return {'CANCELLED'}
        
        try:
            # 获取场数据
            field_data = scene['wilds_vecfield_data']
            vectors = np.array(field_data['vectors'])
            dimensions = field_data['dimensions']
            width, height, depth = dimensions
            
            # 创建粒子系统集合
            collection_name = "MHWilds_VecField_Particles"
            if collection_name in bpy.data.collections:
                # 清理旧的粒子系统
                collection = bpy.data.collections[collection_name]
                for obj in list(collection.objects):
                    bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.collections.remove(collection)
            
            collection = bpy.data.collections.new(collection_name)
            scene.collection.children.link(collection)
            
            # 创建边界框用于参考
            bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
            bounds = bpy.context.active_object
            bounds.name = "Particle_Field_Bounds"
            bounds.scale = (width/2, height/2, depth/2)
            bounds.hide_render = True
            
            # 设置边界框材质
            mat = bpy.data.materials.new("Bounds_Material")
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            bsdf = nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs['Base Color'].default_value = (0.3, 0.3, 0.3, 0.1)
                _set_bsdf_transmission(bsdf, 0.8)
            bounds.data.materials.append(mat)
            
            # 移动到集合
            collection.objects.link(bounds)
            
            # 创建粒子发射器
            bpy.ops.mesh.primitive_ico_sphere_add(radius=self.emitter_radius, subdivisions=1, location=(0, 0, 0))
            emitter = bpy.context.active_object
            emitter.name = "Particle_Emitter"
            emitter.hide_render = True
            
            # 添加粒子系统
            emitter.modifiers.new(name="Particle_System", type='PARTICLE_SYSTEM')
            ps = emitter.particle_systems[0]
            settings = ps.settings
            
            # 使用Blender预设的粒子系统设置（优化版）
            settings.type = 'EMITTER'
            settings.emit_from = 'VOLUME'
            # 减少粒子数量，提高性能
            optimized_particle_count = min(self.particle_count, 5000)  # 限制最大粒子数量为5000
            settings.count = optimized_particle_count
            
            # 设置发射时间 - 使用用户指定的起始帧和结束帧
            settings.frame_start = self.start_frame
            settings.frame_end = self.end_frame
            settings.lifetime = self.particle_lifetime
            settings.lifetime_random = 0.2
            
            # 使用更简单的渲染类型，提高性能；探测式设置，避免不同 Blender 版本枚举值不一致报错
            _safe_set_render_type(settings, preferred='HALO')
            settings.particle_size = self.particle_size * 0.8  # 适当减小粒子大小，提高性能
            
            # 优化粒子物理设置，确保更好地响应湍流场力场
            
            # 使用NEWTON物理，确保粒子能够被力场正确影响
            settings.physics_type = 'NEWTON'
            
            # 调整粒子质量，使其对力场更敏感
            settings.mass = 0.05  # 更小的质量，更容易被力场影响
            
            # 设置初始阻尼为0，让粒子自由运动
            settings.damping = 0.0  # 零阻尼，粒子保持运动状态
            
            # 确保重力被禁用，让湍流场成为主要驱动力
            if hasattr(settings, 'use_gravity'):
                settings.use_gravity = False
            
            # 启用力场影响，确保粒子与湍流场向量交互
            if hasattr(settings, 'use_force_fields'):
                settings.use_force_fields = True  # 启用力场影响
            
            # 在Blender 5.0中，确保粒子系统能够正确响应力场
            # 力场权重是通过界面或上下文设置的，不能直接修改
            # 确保力场影响被启用即可，粒子会自动响应场景中的力场
            print("✅ 粒子系统力场影响已启用")
            
            # 启用初始速度，让用户自行调整强度
            if hasattr(settings, 'use_initial_velocity'):
                settings.use_initial_velocity = True
            
            # 调整初始速度，让粒子更容易进入湍流场
            if hasattr(settings, 'normal_velocity'):
                settings.normal_velocity = self.initial_velocity
            elif hasattr(settings, 'normal_factor'):
                settings.normal_factor = self.initial_velocity
            
            # 增加粒子生命周期，让粒子有足够时间响应湍流场
            settings.lifetime = self.particle_lifetime
            # 增加生命周期随机性（兼容不同Blender版本）
            if hasattr(settings, 'lifetime_random'):
                settings.lifetime_random = 0.3
            elif hasattr(settings, 'random_lifetime'):
                settings.random_lifetime = 0.3
            
            # 优化粒子大小，提高可视化效果
            settings.particle_size = self.particle_size
            # 增加大小随机性（兼容不同Blender版本）
            if hasattr(settings, 'particle_size_random'):
                settings.particle_size_random = 0.5
            elif hasattr(settings, 'size_random'):
                settings.size_random = 0.5
            
            # 启用粒子碰撞检测（如果需要）
            # 但对于湍流场效果，碰撞可能不是必需的
            # if hasattr(settings, 'use_collision'):
            #     settings.use_collision = False
                
            # 确保发射器体积足够大
            emitter.scale = (self.emitter_radius, self.emitter_radius, self.emitter_radius)
            
            # 创建TFA向量场力场网格
            print("创建TFA向量场力场网格...")
            
            # 优化力场分布和参数，确保粒子与湍流场向量更好地交互
            
            # 优化：生成更完整的力场覆盖
            # 减小采样步长，增加力场数量
            spacing_factor = 4  # 减小间距，增加力场密度
            spacing_x = width / max(1, width // spacing_factor)
            spacing_y = height / max(1, height // spacing_factor)
            spacing_z = depth / max(1, depth // spacing_factor)
            
            # 计算采样步长 - 提高采样密度
            sample_step_x = max(1, width // 20)  # 更小的步长，增加力场数量
            sample_step_y = max(1, height // 20)
            sample_step_z = max(1, depth // 20)
            
            # 降低向量幅度阈值，保留更多向量
            magnitude_threshold = 0.05  # 降低阈值，保留更多向量
            
            # 增加最大力场数量，生成更完整的力场覆盖
            max_force_fields = 200  # 增加最大力场数量
            force_fields = []
            force_field_count = 0
            
            # 计算向量幅度范围
            all_magnitudes = np.linalg.norm(vectors, axis=3)
            max_mag = all_magnitudes.max()
            
            # 为每个TFA向量创建一个力场（优化版）
            for z_idx in range(0, depth, sample_step_z):
                for y_idx in range(0, height, sample_step_y):
                    for x_idx in range(0, width, sample_step_x):
                        # 限制力场数量
                        if force_field_count >= max_force_fields:
                            break
                        
                        # 获取TFA向量
                        tfa_vector = vectors[z_idx, y_idx, x_idx]
                        magnitude = np.linalg.norm(tfa_vector)
                        
                        # 只保留较强的向量
                        if magnitude < magnitude_threshold or magnitude < max_mag * 0.2:
                            continue
                        
                        # 计算世界位置
                        world_x = (x_idx - (width-1)/2) * 1.0
                        world_y = (y_idx - (height-1)/2) * 1.0
                        world_z = (z_idx - (depth-1)/2) * 1.0
                        
                        # 简化：只使用一种力场类型，减少复杂性
                        force_type = 'FORCE'
                        
                        # 创建力场
                        try:
                            bpy.ops.object.effector_add(type=force_type, location=(world_x, world_y, world_z))
                            force_field = bpy.context.active_object
                            force_field.name = f"MHWildsVF_Force_{x_idx}_{y_idx}_{z_idx}"
                            
                            # 设置力场参数
                            base_strength = magnitude * 2.0  # 减小强度，避免力场过强
                            force_field.field.strength = base_strength
                            force_field.field.flow = 1.0  # 最大流动效果
                            force_field.field.noise = 0.0  # 关闭噪声，使用纯净的湍流场
                            
                            # 增大影响范围，确保力场覆盖相邻区域
                            force_field.field.shape = 'POINT'  # 使用点形力场
                            force_field.field.size = spacing_x * 2.0  # 增大影响范围，减少力场数量需求
                            
                            # 设置力场方向（根据TFA向量）
                            direction = Vector(tfa_vector).normalized()
                            if direction.length > 0:
                                # 计算旋转，使力场沿向量方向
                                force_field.rotation_mode = 'QUATERNION'
                                force_field.rotation_quaternion = direction.to_track_quat('-Z', 'Y')
                            
                            # 移动到集合
                            collection.objects.link(force_field)
                            force_fields.append(force_field)
                            force_field_count += 1
                        except Exception as e:
                            print(f"⚠️  创建力场失败: {e}")
                            continue
                
                if force_field_count >= max_force_fields:
                    break
            
            if force_field_count >= max_force_fields:
                print(f"⚠️  力场数量已达上限 ({max_force_fields})，已停止创建")
            
            print(f"✅ 创建了 {len(force_fields)} 个力场，优化粒子与湍流场的交互")
            
            # 移动发射器到集合
            collection.objects.link(emitter)
            
            print(f"创建了 {len(force_fields)} 个力场")
            
            # 确保发射器在正确位置
            emitter.location = (0, 0, 0)
            emitter.scale = (self.emitter_radius, self.emitter_radius, self.emitter_radius)
            
            # 设置场景动画范围为用户指定的起始帧和结束帧
            scene.frame_start = self.start_frame
            scene.frame_end = self.end_frame
            
            # 确保当前帧是动画开始帧
            scene.frame_set(self.start_frame)
            
            # 保存TFA场数据到场景，以便驱动程序访问
            scene['tfa_vectors'] = vectors.tolist()
            scene['tfa_dimensions'] = dimensions
            
            # 为用户准备好粒子系统设置
            # 选择发射器对象，方便用户立即修改
            bpy.context.view_layer.objects.active = emitter
            
            # 提供清晰的操作指引
            self.report({'INFO'}, f"✅ 粒子系统创建成功！")
            self.report({'INFO'}, f"📊 粒子数量: {self.particle_count}")
            self.report({'INFO'}, f"⏱️  生命周期: {self.particle_lifetime}秒")
            self.report({'INFO'}, f"🎬 动画范围: {scene.frame_current} 到 {scene.frame_end}帧")
            self.report({'INFO'}, f"⚙️  重力已禁用，力场权重已设置")
            self.report({'INFO'}, f"💡 提示：在属性面板中调整粒子系统设置")
            self.report({'INFO'}, f"💡 提示：按 Alt+A 播放动画查看粒子运动")
            
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Particle system error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=350)

# 像素修改测试操作符
class WILDS_VF_OT_modify_pixels(Operator):
    bl_idname = "wilds_vecfield.modify_pixels"
    bl_label = "修改像素"
    bl_description = "修改所有像素值用于测试目的"
    
    def execute(self, context):
        scene = context.scene
        
        if 'wilds_vecfield_data' not in scene:
            self.report({'ERROR'}, "No TFA data loaded. Import a file first.")
            return {'CANCELLED'}
        
        try:
            import numpy as np
            
            props = scene.wilds_vecfield_props
            field_data = scene['wilds_vecfield_data']
            
            # 获取向量数据；从瘦身存储重建工作用 RGBA（RGB 占位，下游若非 ENABLED_ONLY
            # 会由 modified_vectors 重新编码，且导出只用 vectors+alpha，故 RGB 留零无影响）
            vectors = np.array(field_data['vectors'])
            # 优先瘦身存储的 alpha；兼容旧 .blend 的 rgba_data；都无则全 1
            if field_data.get('alpha') is not None:
                alpha = np.array(field_data['alpha'], dtype=np.uint8)
            elif field_data.get('rgba_data') is not None:
                alpha = np.array(field_data['rgba_data'], dtype=np.uint8)[..., 3]
            else:
                alpha = np.ones(vectors.shape[:3], dtype=np.uint8)
            rgba_data = np.zeros((*alpha.shape, 4), dtype=np.uint8)
            rgba_data[..., 3] = alpha
            original_vectors = vectors.copy()
            original_rgba = rgba_data.copy()
            
            # 获取修改参数
            strength = props.pixel_modification_strength
            mod_type = props.pixel_modification_type
            constant_value = props.pixel_modification_constant
            voxel_enabled = props.voxel_enabled
            
            # 获取单独分量修改标志
            modify_x = props.modify_x
            modify_y = props.modify_y
            modify_z = props.modify_z
            modify_enabled = props.modify_enabled
            
            print(f"🔧 开始修改像素: 类型={mod_type}, 强度={strength}, 常量={constant_value}, 启用={voxel_enabled}")
            print(f"   原始向量形状: {vectors.shape}")
            print(f"   分量修改: X={modify_x}, Y={modify_y}, Z={modify_z}, 启用={modify_enabled}")
            print(f"   坐标系统: X=左右, Y=上下, Z=前后")
            print(f"   向量标准: FF=1.0(正方向), 80=0.0(中间), 00=-1.0(负方向)")
            
            # 创建修改后的向量和RGBA数组（初始为原始值）
            modified_vectors = vectors.copy()
            modified_rgba = rgba_data.copy()
            
            # 应用不同的修改类型
            if mod_type in ['RANDOM', 'SINE', 'LINEAR', 'CONSTANT', 'INVERT']:
                # 原始修改类型，支持分量选择
                if mod_type == 'RANDOM':
                    # 随机修改
                    random_vectors = np.random.uniform(-1.0, 1.0, vectors.shape)
                    modified_vectors = vectors * (1 - strength) + random_vectors * strength
                    print("   ✅ 应用随机修改")
                    
                elif mod_type == 'SINE':
                    # 正弦波修改
                    depth, height, width, _ = vectors.shape
                    x = np.linspace(0, 4*np.pi, width)
                    y = np.linspace(0, 4*np.pi, height)
                    z = np.linspace(0, 4*np.pi, depth)
                    Z, Y, X = np.meshgrid(z, y, x, indexing='ij')
                    sine_pattern = np.sin(X + Y + Z)
                    sine_vectors = np.stack([sine_pattern, sine_pattern, sine_pattern], axis=-1)
                    modified_vectors = vectors * (1 - strength) + sine_vectors * strength
                    print("   ✅ 应用正弦波修改")
                    
                elif mod_type == 'LINEAR':
                    # 线性渐变
                    depth, height, width, _ = vectors.shape
                    x = np.linspace(-1.0, 1.0, width)
                    y = np.linspace(-1.0, 1.0, height)
                    z = np.linspace(-1.0, 1.0, depth)
                    Z, Y, X = np.meshgrid(z, y, x, indexing='ij')
                    linear_pattern = (X + Y + Z) / 3
                    linear_vectors = np.stack([linear_pattern, linear_pattern, linear_pattern], axis=-1)
                    modified_vectors = vectors * (1 - strength) + linear_vectors * strength
                    print("   ✅ 应用线性渐变")
                    
                elif mod_type == 'CONSTANT':
                    # 常量值
                    constant_vectors = np.full(vectors.shape, constant_value)
                    modified_vectors = vectors * (1 - strength) + constant_vectors * strength
                    print(f"   ✅ 应用常量值: {constant_value}")
                    
                elif mod_type == 'INVERT':
                    # 反转现有值
                    modified_vectors = vectors * (1 - strength) + (-vectors) * strength
                    print("   ✅ 应用反转修改")
                
                # 根据分量选择应用修改
                if not modify_x:
                    modified_vectors[..., 0] = vectors[..., 0]  # 保持原始X分量
                if not modify_y:
                    modified_vectors[..., 1] = vectors[..., 1]  # 保持原始Y分量
                if not modify_z:
                    modified_vectors[..., 2] = vectors[..., 2]  # 保持原始Z分量
                    
                # 确保向量在[-1, 1]范围内
                modified_vectors = np.clip(modified_vectors, -1.0, 1.0)
                    
            elif mod_type == 'X_ONLY':
                # 仅修改X轴（左右）
                print(f"   ✅ 仅修改X轴(左右), 强度={strength}, 常量={constant_value}")
                if modify_x:
                    # 生成X轴修改
                    x_modification = np.full(vectors.shape[:3], constant_value)
                    modified_vectors[..., 0] = vectors[..., 0] * (1 - strength) + x_modification * strength
                    modified_vectors[..., 0] = np.clip(modified_vectors[..., 0], -1.0, 1.0)
            
            elif mod_type == 'Y_ONLY':
                # 仅修改Y轴（上下）
                print(f"   ✅ 仅修改Y轴(上下), 强度={strength}, 常量={constant_value}")
                if modify_y:
                    # 生成Y轴修改
                    y_modification = np.full(vectors.shape[:3], constant_value)
                    modified_vectors[..., 1] = vectors[..., 1] * (1 - strength) + y_modification * strength
                    modified_vectors[..., 1] = np.clip(modified_vectors[..., 1], -1.0, 1.0)
            
            elif mod_type == 'Z_ONLY':
                # 仅修改Z轴（前后）
                print(f"   ✅ 仅修改Z轴(前后), 强度={strength}, 常量={constant_value}")
                if modify_z:
                    # 生成Z轴修改
                    z_modification = np.full(vectors.shape[:3], constant_value)
                    modified_vectors[..., 2] = vectors[..., 2] * (1 - strength) + z_modification * strength
                    modified_vectors[..., 2] = np.clip(modified_vectors[..., 2], -1.0, 1.0)
            
            elif mod_type == 'ENABLED_ONLY':
                # 仅修改体素启用状态
                print(f"   ✅ 仅修改体素启用状态, 设置为 {'启用' if voxel_enabled else '禁用'}")
                if modify_enabled:
                    # 将启用状态设置为0或1
                    enabled_value = 1 if voxel_enabled else 0
                    modified_rgba[..., 3] = enabled_value
            
            elif mod_type == 'REGION_MODIFY':
                # 区域修改：只修改指定区域，其他区域保持不变
                print(f"   ✅ 开始区域修改")
                print(f"   区域范围: X[{props.region_min_x}, {props.region_max_x}], Y[{props.region_min_y}, {props.region_max_y}], Z[{props.region_min_z}, {props.region_max_z}]")
                
                # 获取场数据的实际尺寸
                depth, height, width, _ = vectors.shape
                
                # 计算修改区域的边界（确保在有效范围内）
                min_z = max(0, props.region_min_z)
                max_z = min(depth, props.region_max_z + 1)  # +1 因为Python切片是左闭右开
                min_y = max(0, props.region_min_y)
                max_y = min(height, props.region_max_y + 1)
                min_x = max(0, props.region_min_x)
                max_x = min(width, props.region_max_x + 1)
                
                print(f"   实际修改区域: X[{min_x}, {max_x}], Y[{min_y}, {max_y}], Z[{min_z}, {max_z}]")
                
                # 在指定区域内应用修改
                region_vectors = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x].copy()
                
                # 根据常量值设置区域向量
                constant_value = props.pixel_modification_constant
                region_modification = np.full(region_vectors.shape, constant_value)
                
                # 应用修改
                region_vectors = region_vectors * (1 - strength) + region_modification * strength
                
                # 确保向量在[-1, 1]范围内
                region_vectors = np.clip(region_vectors, -1.0, 1.0)
                
                # 根据分量选择应用修改
                if not modify_x:
                    region_vectors[..., 0] = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x, 0]  # 保持原始X分量
                if not modify_y:
                    region_vectors[..., 1] = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x, 1]  # 保持原始Y分量
                if not modify_z:
                    region_vectors[..., 2] = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x, 2]  # 保持原始Z分量
                
                # 将修改后的区域放回完整向量数组
                modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x] = region_vectors
                
                # 更新区域内的启用状态
                if modify_enabled:
                    enabled_value = 1 if voxel_enabled else 0
                    modified_rgba[min_z:max_z, min_y:max_y, min_x:max_x, 3] = enabled_value
                
                print(f"   ✅ 区域修改完成: 修改了 {region_vectors.size // 3} 个体素")
            
            elif mod_type == 'FACE_PRESET':
                # 面预设修改：修改立方体贴图的指定面
                print(f"   ✅ 开始面预设修改: {props.face_preset}")
                
                # 获取场数据的实际尺寸
                depth, height, width, _ = vectors.shape
                
                # 根据面预设计算修改区域
                min_z, max_z, min_y, max_y, min_x, max_x = 0, depth, 0, height, 0, width
                
                if props.face_preset == 'FRONT':
                    # 前面 (Z=max)
                    min_z = depth - 1
                    max_z = depth
                    face_desc = "前面 (Z=max)"
                elif props.face_preset == 'BACK':
                    # 后面 (Z=min)
                    min_z = 0
                    max_z = 1
                    face_desc = "后面 (Z=min)"
                elif props.face_preset == 'LEFT':
                    # 左面 (X=min)
                    min_x = 0
                    max_x = 1
                    face_desc = "左面 (X=min)"
                elif props.face_preset == 'RIGHT':
                    # 右面 (X=max)
                    min_x = width - 1
                    max_x = width
                    face_desc = "右面 (X=max)"
                elif props.face_preset == 'TOP':
                    # 顶面 (Y=max)
                    min_y = height - 1
                    max_y = height
                    face_desc = "顶面 (Y=max)"
                elif props.face_preset == 'BOTTOM':
                    # 底面 (Y=min)
                    min_y = 0
                    max_y = 1
                    face_desc = "底面 (Y=min)"
                
                print(f"   修改面: {face_desc}, 区域: X[{min_x}, {max_x}], Y[{min_y}, {max_y}], Z[{min_z}, {max_z}]")
                
                # 在指定面内应用修改
                face_vectors = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x].copy()
                
                # 根据常量值设置面向量
                constant_value = props.pixel_modification_constant
                face_modification = np.full(face_vectors.shape, constant_value)
                
                # 应用修改
                face_vectors = face_vectors * (1 - strength) + face_modification * strength
                
                # 确保向量在[-1, 1]范围内
                face_vectors = np.clip(face_vectors, -1.0, 1.0)
                
                # 根据分量选择应用修改
                if not modify_x:
                    face_vectors[..., 0] = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x, 0]  # 保持原始X分量
                if not modify_y:
                    face_vectors[..., 1] = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x, 1]  # 保持原始Y分量
                if not modify_z:
                    face_vectors[..., 2] = modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x, 2]  # 保持原始Z分量
                
                # 将修改后的面放回完整向量数组
                modified_vectors[min_z:max_z, min_y:max_y, min_x:max_x] = face_vectors
                
                # 更新面内的启用状态
                if modify_enabled:
                    enabled_value = 1 if voxel_enabled else 0
                    modified_rgba[min_z:max_z, min_y:max_y, min_x:max_x, 3] = enabled_value
                
                print(f"   ✅ 面修改完成: 修改了 {face_vectors.size // 3} 个体素")
            
            elif mod_type == 'RADIAL_PARTICLE_OFFSET':
                # 径向粒子偏移：根据强度值调整粒子运动方向（原排斥效果）
                print(f"   ✅ 开始径向粒子偏移修改")
                print(f"   偏移轴向: {props.repulsion_axis}")
                print(f"   偏移强度: {props.repulsion_strength}")
                
                # 获取场数据的实际尺寸
                depth, height, width, _ = vectors.shape
                
                # 确定要修改的轴向索引
                if props.repulsion_axis == 'X':
                    axis_idx = 0
                    axis_name = "X轴 (左右)"
                elif props.repulsion_axis == 'Y':
                    axis_idx = 1
                    axis_name = "Y轴 (上下)"
                elif props.repulsion_axis == 'Z':
                    axis_idx = 2
                    axis_name = "Z轴 (前后)"
                
                print(f"   实际修改轴向: {axis_name}")
                
                # 获取偏移强度
                offset_strength = props.repulsion_strength
                
                # 为每个体素应用径向偏移效果
                for z in range(depth):
                    for y in range(height):
                        for x in range(width):
                            # 获取当前向量
                            current_vector = vectors[z, y, x]
                            
                            # 根据偏移强度调整轴向分量
                            if offset_strength == 1.0:
                                # 强度=1.0: 所有粒子向负方向运动
                                modified_vectors[z, y, x, axis_idx] = -abs(current_vector[axis_idx])
                            elif offset_strength == -1.0:
                                # 强度=-1.0: 所有粒子向正方向运动
                                modified_vectors[z, y, x, axis_idx] = abs(current_vector[axis_idx])
                            else:
                                # 强度在-1.0到1.0之间: 线性混合
                                # 当strength=0: 保持原样
                                # 当strength>0: 向负方向偏移
                                # 当strength<0: 向正方向偏移
                                original_value = current_vector[axis_idx]
                                
                                if offset_strength > 0:
                                    # 向负方向偏移
                                    new_value = original_value * (1 - offset_strength) - abs(original_value) * offset_strength
                                else:
                                    # 向正方向偏移
                                    new_value = original_value * (1 + offset_strength) + abs(original_value) * (-offset_strength)
                                
                                modified_vectors[z, y, x, axis_idx] = new_value
                
                print(f"   ✅ 径向粒子偏移完成: 修改了 {width*height*depth} 个体素")
            
            elif mod_type == 'REPULSION':
                # 排斥效果：根据强度值调整粒子运动方向
                # 强度值作为分割点: 
                #  - 粒子位置 < 强度值: 向负方向运动
                #  - 粒子位置 > 强度值: 向正方向运动
                #  - 强度=1.0: 所有粒子向负方向运动
                #  - 强度=-1.0: 所有粒子向正方向运动
                print(f"   ✅ 开始排斥效果修改")
                print(f"   排斥轴向: {props.repulsion_axis}")
                print(f"   排斥强度(分割点): {props.repulsion_strength}")
                
                # 获取场数据的实际尺寸
                depth, height, width, _ = vectors.shape
                
                # 确定要修改的轴向索引
                if props.repulsion_axis == 'X':
                    axis_idx = 0
                    axis_name = "X轴 (左右)"
                elif props.repulsion_axis == 'Y':
                    axis_idx = 1
                    axis_name = "Y轴 (上下)"
                elif props.repulsion_axis == 'Z':
                    axis_idx = 2
                    axis_name = "Z轴 (前后)"
                
                print(f"   实际修改轴向: {axis_name}")
                
                # 获取排斥强度（分割点值）
                split_value = props.repulsion_strength
                
                # 为每个体素应用排斥效果
                for z in range(depth):
                    for y in range(height):
                        for x in range(width):
                            # 计算相对于中心点的归一化位置 (-1.0 到 1.0)
                            if props.repulsion_axis == 'X':
                                # X轴（左右）
                                normalized_pos = (x / (width - 1)) * 2.0 - 1.0
                            elif props.repulsion_axis == 'Y':
                                # Y轴（上下）
                                normalized_pos = (y / (height - 1)) * 2.0 - 1.0
                            else:  # Z轴（前后）
                                normalized_pos = (z / (depth - 1)) * 2.0 - 1.0
                            
                            # 根据归一化位置与分割点的关系确定运动方向
                            if normalized_pos < split_value:
                                # 位置小于分割点: 向负方向运动
                                modified_vectors[z, y, x, axis_idx] = -1.0
                            elif normalized_pos > split_value:
                                # 位置大于分割点: 向正方向运动
                                modified_vectors[z, y, x, axis_idx] = 1.0
                            else:
                                # 正好在分割点: 保持原位
                                modified_vectors[z, y, x, axis_idx] = 0.0
                
                print(f"   ✅ 排斥效果完成: 修改了 {width*height*depth} 个体素")
            
            elif mod_type == 'CONVERGENCE':
                # 紧缩效果：向量向中心聚集，可选择涡旋效果
                print(f"   ✅ 开始紧缩效果修改")
                
                # 获取场数据的实际尺寸
                depth, height, width, _ = vectors.shape
                
                # 获取紧缩参数
                convergence_radius = props.convergence_radius
                center_x = props.convergence_center_x
                center_y = props.convergence_center_y
                center_z = props.convergence_center_z
                vortex_axis = props.vortex_axis
                vortex_strength = props.vortex_strength
                
                print(f"   紧缩半径: {convergence_radius}")
                print(f"   紧缩中心: ({center_x}, {center_y}, {center_z})")
                print(f"   涡旋轴向: {vortex_axis}")
                print(f"   涡旋强度: {vortex_strength}")
                
                # 为每个体素应用紧缩效果
                for z in range(depth):
                    for y in range(height):
                        for x in range(width):
                            # 计算体素在归一化空间中的位置 (-1.0 到 1.0)
                            norm_x = (x / (width - 1)) * 2.0 - 1.0
                            norm_y = (y / (height - 1)) * 2.0 - 1.0
                            norm_z = (z / (depth - 1)) * 2.0 - 1.0
                            
                            # 计算到紧缩中心的向量
                            center_vec = np.array([center_x, center_y, center_z])
                            voxel_vec = np.array([norm_x, norm_y, norm_z])
                            to_center = center_vec - voxel_vec
                            
                            # 计算距离
                            distance = np.linalg.norm(to_center)
                            
                            # 只有在半径内的向量才会被修改
                            if distance <= convergence_radius:
                                if distance > 0:
                                    # 归一化指向中心的向量
                                    to_center_norm = to_center / distance
                                    
                                    # 计算聚集强度（距离中心越远，强度越大）
                                    # 使用径向衰减函数
                                    convergence_strength = (1.0 - (distance / convergence_radius))
                                    
                                    # 基础向量指向中心
                                    center_vector = to_center_norm * convergence_strength
                                    
                                    # 应用涡旋效果
                                    if vortex_strength > 0:
                                        # 根据涡旋轴向计算旋转
                                        if vortex_axis == 'X':
                                            # 绕X轴旋转：在YZ平面上涡旋
                                            theta = vortex_strength * convergence_strength
                                            vortex_x = 0
                                            vortex_y = -center_vector[2] * np.sin(theta) + center_vector[1] * np.cos(theta)
                                            vortex_z = center_vector[2] * np.cos(theta) + center_vector[1] * np.sin(theta)
                                        elif vortex_axis == 'Y':
                                            # 绕Y轴旋转：在XZ平面上涡旋
                                            theta = vortex_strength * convergence_strength
                                            vortex_x = center_vector[2] * np.sin(theta) + center_vector[0] * np.cos(theta)
                                            vortex_y = 0
                                            vortex_z = center_vector[2] * np.cos(theta) - center_vector[0] * np.sin(theta)
                                        else:  # Z轴
                                            # 绕Z轴旋转：在XY平面上涡旋
                                            theta = vortex_strength * convergence_strength
                                            vortex_x = -center_vector[1] * np.sin(theta) + center_vector[0] * np.cos(theta)
                                            vortex_y = center_vector[1] * np.cos(theta) + center_vector[0] * np.sin(theta)
                                            vortex_z = 0
                                        
                                        # 合并中心聚集和涡旋效果
                                        vortex_vector = np.array([vortex_x, vortex_y, vortex_z])
                                        final_vector = center_vector + vortex_vector
                                    else:
                                        # 仅中心聚集效果
                                        final_vector = center_vector
                                    
                                    # 应用修改
                                    modified_vectors[z, y, x] = final_vector
                                else:
                                    # 在中心位置，向量为零
                                    modified_vectors[z, y, x] = [0.0, 0.0, 0.0]
                
                print(f"   ✅ 紧缩效果完成: 修改了 {width*height*depth} 个体素")
            
            # 确保向量在[-1, 1]范围内
            modified_vectors = np.clip(modified_vectors, -1.0, 1.0)
            
            # 重新计算RGBA数据（如果修改了向量）
            if mod_type != 'ENABLED_ONLY':
                # 根据测试结果调整向量到RGBA的转换
                # 向量范围 [-1.0, 1.0] → RGBA范围 [00, 80, FF]
                # FF=1.0(正方向), 80=0.0(中间), 00=-1.0(负方向)
                vectors_uint8 = np.clip(np.round(((modified_vectors + 1.0) * 127.5)), 0, 255).astype(np.uint8)
                modified_rgba[..., 0:3] = vectors_uint8
                
            # 更新启用状态（仅当非区域/面修改且需要修改启用状态时）
            if modify_enabled and mod_type not in ['REGION_MODIFY', 'FACE_PRESET']:
                enabled_value = 1 if voxel_enabled else 0
                modified_rgba[..., 3] = enabled_value
            
            # 更新场数据（只回写 vectors + 独立 alpha 通道）
            field_data['vectors'] = modified_vectors.tolist()
            field_data['alpha'] = modified_rgba[..., 3].tolist()
            
            # 统计修改结果
            min_val = modified_vectors.min()
            max_val = modified_vectors.max()
            avg_val = modified_vectors.mean()
            enabled_count = np.sum(modified_rgba[..., 3] > 0)
            total_count = modified_rgba[..., 3].size
            
            print(f"   ✅ 向量修改完成: 最小值={min_val:.4f}, 最大值={max_val:.4f}, 平均值={avg_val:.4f}")
            print(f"   ✅ 启用状态: {enabled_count}/{total_count} 体素已启用")
            print(f"   ✅ 向量方向: X=左右, Y=上下, Z=前后")
            print(f"   ✅ 向量标准: FF=1.0(正), 80=0.0(中), 00=-1.0(负)")
            
            # 更新场景数据
            scene['wilds_vecfield_data'] = field_data
            
            # 重新生成可视化
            if props.auto_visualize:
                bpy.ops.wilds_vecfield.visualize_field()
            
            self.report({'INFO'}, f"Successfully modified pixels: {mod_type}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to modify pixels: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

# 用户界面面板
class VIEW3D_PT_wilds_vecfield_tools(Panel):
    bl_label = "MHWilds 向量场工具"
    bl_idname = "VIEW3D_PT_wilds_vecfield_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MHWilds VecField"
    bl_context = "objectmode"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.wilds_vecfield_props
        
        # 文件导入和生成部分
        box = layout.box()
        box.label(text="File Operations", icon='FILE')
        
        row = box.row()
        row.operator("wilds_vecfield.load_tex", text="Load .tex", icon='IMPORT')
        row.operator("wilds_vecfield.generate_base", text="Generate Base", icon='ADD')
        
        if props.filepath:
            box.label(text=f"File: {props.filepath.split('/')[-1]}")
        
        if 'wilds_vecfield_data' in scene:
            field_data = scene['wilds_vecfield_data']
            dims = field_data['dimensions']
            
            # 显示检测到的尺寸
            if 'detected_size' in field_data:
                box.label(text=f"Detected: {field_data['detected_size']}", icon='FILE_TICK')
            
            box.label(text=f"Loaded: {dims[0]}×{dims[1]}×{dims[2]}", icon='CHECKMARK')
            
            # 显示版本信息
            if 'version' in field_data:
                box.label(text=f"Version: {field_data['version']}")
            
            # 显示基准色信息
            box.label(text=f"Base Color: 80 80 80 01", icon='COLOR')
        
        # 可视化设置
        box = layout.box()
        box.label(text="Visualization Settings", icon='SHADING_RENDERED')
        box.prop(props, "auto_visualize")
        box.prop(props, "visualization_mode")
        box.prop(props, "scale_factor")
        box.prop(props, "vector_scale")
        box.prop(props, "resolution")
        box.prop(props, "show_vectors")
        box.prop(props, "color_by_magnitude")
        if props.color_by_magnitude:
            box.prop(props, "arrow_color_mode")
        
        row = box.row()
        row.operator("wilds_vecfield.visualize_field", text="Create Visualization", icon='MOD_PARTICLES')
        row.operator("wilds_vecfield.particle_system", text="Particle System (测试系统慎用)", icon='PARTICLES')
        
        # 向量编辑功能UI
        box = layout.box()
        box.label(text="Vector Editing", icon='ARROW_LEFTRIGHT')
        
        # 显示选中向量数量
        selected_count = len(props.selected_vectors)
        box.label(text=f"Selected Vectors: {selected_count}", icon='SELECT_SET')
        
        if props.vector_edit_mode or selected_count > 0:
            # 编辑模式下显示的UI
            
            # 显示选中的向量数量
            if selected_count > 0:
                box.label(text=f"Selected Vectors: {selected_count}", icon='SELECT_SET')
            
            # 向量数值设置功能
            value_box = box.box()
            value_box.label(text="Vector Values", icon='DOT')
            
            value_box.prop(props, "vector_x", text="X (左右)")
            value_box.prop(props, "vector_y", text="Y (上下)")
            value_box.prop(props, "vector_z", text="Z (前后)")
            value_box.operator("wilds_vecfield.set_vector_values", text="Set Vector Values", icon='FILE_REFRESH')
            
            # 向量旋转功能
            rotation_box = box.box()
            rotation_box.label(text="Vector Rotation", icon='TRIA_RIGHT')
            
            rotation_box.prop(props, "rotation_axis", text="Axis")
            rotation_box.prop(props, "rotation_angle", text="Angle")
            rotation_box.operator("wilds_vecfield.rotate_vectors", text="Rotate Selected Vectors", icon='FILE_REFRESH')
            
            # 反转向量功能
            box.operator("wilds_vecfield.invert_vectors", text="Invert Selected Vectors", icon='ARROW_LEFTRIGHT')
            
            # 向量预设工具
            preset_box = box.box()
            preset_box.label(text="Vector Presets", icon='PRESET')
            
            preset_box.prop(props, "preset_tool_type", text="Preset Type")
            
            # 根据选中的预设类型显示相应的参数
            if props.preset_tool_type == 'RANDOM':
                preset_box.label(text="Random Parameters:")
                preset_box.prop(props, "random_min_magnitude", text="Min Magnitude")
                preset_box.prop(props, "random_max_magnitude", text="Max Magnitude")
            
            elif props.preset_tool_type == 'LINEAR':
                preset_box.label(text="Linear Direction:")
                preset_box.prop(props, "linear_direction_x", text="X")
                preset_box.prop(props, "linear_direction_y", text="Y")
                preset_box.prop(props, "linear_direction_z", text="Z")
            
            elif props.preset_tool_type in ['POINT_TO', 'REPEL']:
                preset_box.label(text="Using Blender Cursor Position")
                preset_box.label(text="Note: Adjust cursor position in object mode")
            
            elif props.preset_tool_type == 'CONSTANT':
                preset_box.label(text="Constant Vector:")
                preset_box.prop(props, "vector_x", text="X")
                preset_box.prop(props, "vector_y", text="Y")
                preset_box.prop(props, "vector_z", text="Z")
            
            elif props.preset_tool_type == 'VORTEX':
                preset_box.label(text="Vortex Parameters:")
                preset_box.prop(props, "vortex_axis", text="Axis")
                preset_box.prop(props, "vortex_direction", text="Direction")
                preset_box.prop(props, "vortex_strength", text="Strength")
                preset_box.prop(props, "vortex_radius", text="Affected Radius")
                preset_box.prop(props, "vortex_radius_type", text="Radius Type")
                preset_box.prop(props, "vortex_elasticity", text="Elasticity")
                preset_box.prop(props, "vortex_zero_center", text="Zero Center Vectors")
            
            # 预设叠加选项
            preset_box.label(text="Overlay Options:")
            preset_box.prop(props, "preset_overlay_mode", text="Overlay Mode")
            preset_box.prop(props, "preset_overlay_strength", text="Overlay Strength")
            
            # 应用预设按钮
            preset_box.operator("wilds_vecfield.apply_vector_preset", text="Apply Preset", icon='PLAY')
            
            # 更新和退出按钮
            row = box.row()
            row.operator("wilds_vecfield.update_vector", text="Update Vector Field", icon='FILE_REFRESH')
            row.operator("wilds_vecfield.clear_selected_vectors", text="Clear Selection", icon='TRASH')
            row.operator("wilds_vecfield.exit_vector_edit", text="Exit Edit Mode", icon='X')
            
            box.label(text="提示: 在3D视图中选择向量箭头，然后使用旋转工具或按钮修改方向", icon='INFO')
        else:
            # 非编辑模式下显示的UI
            box.operator("wilds_vecfield.select_vector", text="Select Vector Arrow", icon='EYEDROPPER')
            box.label(text="提示: 先创建可视化，然后选择向量箭头", icon='INFO')
            box.label(text="提示: 多次点击可添加/移除多个向量", icon='INFO')
        
        # 测试性功能：像素修改
        if 'wilds_vecfield_data' in scene:
            box = layout.box()
            box.label(text="Test: Pixel Modification", icon='EXPERIMENTAL')
            
            # 修改类型选择
            box.prop(props, "pixel_modification_type")
            
            # 强度控制
            box.prop(props, "pixel_modification_strength")
            
            # 常量值（用于常量、单轴、区域和面部修改）
            if props.pixel_modification_type in ['CONSTANT', 'X_ONLY', 'Y_ONLY', 'Z_ONLY', 'REGION_MODIFY', 'FACE_PRESET']:
                box.prop(props, "pixel_modification_constant")
                box.label(text="向量标准: FF=1.0(正), 80=0.0(中), 00=-1.0(负)", icon='INFO')
            
            # 启用/禁用设置
            if props.pixel_modification_type == 'ENABLED_ONLY':
                box.prop(props, "voxel_enabled")
                box.label(text="启用状态: 0=禁用, 1=启用", icon='INFO')
            
            # 区域修改设置
            if props.pixel_modification_type == 'REGION_MODIFY':
                box.label(text="区域修改设置", icon='GROUP')
                
                # 获取场数据的实际尺寸
                field_data = scene['wilds_vecfield_data']
                vectors = np.array(field_data['vectors'])
                depth, height, width, _ = vectors.shape
                
                box.label(text=f"场尺寸: X={width}, Y={height}, Z={depth}", icon='INFO')
                
                # X轴范围
                row = box.row(heading="X范围")
                row.prop(props, "region_min_x", text="最小")
                row.prop(props, "region_max_x", text="最大")
                
                # Y轴范围
                row = box.row(heading="Y范围")
                row.prop(props, "region_min_y", text="最小")
                row.prop(props, "region_max_y", text="最大")
                
                # Z轴范围
                row = box.row(heading="Z范围")
                row.prop(props, "region_min_z", text="最小")
                row.prop(props, "region_max_z", text="最大")
            
            # 面部预设设置
            if props.pixel_modification_type == 'FACE_PRESET':
                box.label(text="立方体贴图面修改", icon='CUBE')
                box.prop(props, "face_preset")
                
                # 获取场数据的实际尺寸
                field_data = scene['wilds_vecfield_data']
                vectors = np.array(field_data['vectors'])
                depth, height, width, _ = vectors.shape
                
                box.label(text=f"场尺寸: X={width}, Y={height}, Z={depth}", icon='INFO')
                
                # 显示所选面的描述
                face_desc = {
                    'FRONT': f"前面 (Z={depth-1})",
                    'BACK': "后面 (Z=0)",
                    'LEFT': "左面 (X=0)",
                    'RIGHT': f"右面 (X={width-1})",
                    'TOP': f"顶面 (Y={height-1})",
                    'BOTTOM': "底面 (Y=0)"
                }
                box.label(text=face_desc.get(props.face_preset, ""), icon='INFO')
            
            # 排斥效果设置
            if props.pixel_modification_type == 'REPULSION':
                box.label(text="排斥效果设置", icon='FORCE_FORCE')
                
                # 排斥轴向选择
                box.prop(props, "repulsion_axis")
                
                # 排斥强度调整
                box.prop(props, "repulsion_strength")
                
                # 显示排斥强度的效果说明
                strength = props.repulsion_strength
                if strength == 1.0:
                    box.label(text="效果: 所有粒子向负方向运动", icon='TRIA_RIGHT')
                elif strength == -1.0:
                    box.label(text="效果: 所有粒子向正方向运动", icon='TRIA_RIGHT')
                elif strength > 0:
                    box.label(text=f"效果: 粒子向负方向偏移 {strength*100:.0f}%", icon='TRIA_RIGHT')
                elif strength < 0:
                    box.label(text=f"效果: 粒子向正方向偏移 {abs(strength)*100:.0f}%", icon='TRIA_RIGHT')
                else:
                    box.label(text="效果: 正常行为，无偏移", icon='TRIA_RIGHT')
            
            # 紧缩效果设置
            if props.pixel_modification_type == 'CONVERGENCE':
                box.label(text="紧缩效果设置", icon='FORCE_MAGNETIC')
                
                # 紧缩半径设置
                box.prop(props, "convergence_radius", text="Convergence Radius")
                
                # 中心位置设置
                box.label(text="Center Position:")
                col = box.column(align=True)
                col.prop(props, "convergence_center_x", text="X")
                col.prop(props, "convergence_center_y", text="Y")
                col.prop(props, "convergence_center_z", text="Z")
                
                # 涡旋效果设置
                box.label(text="Vortex Effect:")
                col = box.column(align=True)
                col.prop(props, "vortex_axis", text="Axis")
                col.prop(props, "vortex_strength", text="Strength")
            
            # 坐标系统说明
            box.label(text="坐标系统: X=左右, Y=上下, Z=前后", icon='ARROW_LEFTRIGHT')
            
            # 单独分量修改选项
            col = box.column(heading="Component Selection", align=True)
            col.prop(props, "modify_x", text="X (左右)")
            col.prop(props, "modify_y", text="Y (上下)")
            col.prop(props, "modify_z", text="Z (前后)")
            col.prop(props, "modify_enabled", text="启用状态")
            
            # 修改按钮
            row = box.row()
            row.operator("wilds_vecfield.modify_pixels", text="Modify Pixels", icon='GREASEPENCIL')
            
            # 信息显示（防御：优先 alpha，兼容旧 .blend 的 rgba_data，缺失则跳过，避免 draw 崩溃）
            field_data = scene['wilds_vecfield_data']
            alpha_src = field_data.get('alpha')
            if alpha_src is None and field_data.get('rgba_data') is not None:
                alpha_src = np.array(field_data['rgba_data'])[..., 3]
            if alpha_src is not None:
                alpha = np.array(alpha_src)
                enabled_voxels = int(np.sum(alpha > 0))
                total_voxels = alpha.size
                box.label(text=f"Enabled Voxels: {enabled_voxels}/{total_voxels}", icon='INFO')
            
            # 向量统计信息
            vectors = np.array(field_data['vectors'])
            min_val = vectors.min()
            max_val = vectors.max()
            avg_val = vectors.mean()
            box.label(text=f"向量范围: {min_val:.3f} 到 {max_val:.3f}, 平均: {avg_val:.3f}", icon='STATUSBAR')
        
        if 'wilds_vecfield_data' in scene:
            # 导出部分
            box = layout.box()
            box.label(text="Export", icon='EXPORT')
            
            row = box.row()
            row.operator("wilds_vecfield.save_tex", text="Save .tex", icon='FILE_BACKUP')
            
            # 清除按钮
            box = layout.box()
            box.label(text="Management", icon='SETTINGS')
            row = box.row()
            row.operator("wilds_vecfield.clear_field", text="Clear Field", icon='TRASH')
            row.operator("wilds_vecfield.clear_all_objects", text="Clear All Objects", icon='X')

# 公式生成向量场（移植自 blender_tfa_importer 优化版原型的 field_generators 一套）
class WildsVecFieldGenProps(PropertyGroup):
    """公式生成的参数，独立挂在 scene.wilds_vecfield_gen，不干扰 wilds_vecfield_props。"""
    dim: IntProperty(name="维度 N", default=16, min=4, max=256,
                     description="立方体边长。必须是 4 的倍数（BC1 按 4x4 像素分块）；语料实测出现过 32/64")
    field_type: EnumProperty(
        name="场类型",
        items=[
            ('UNIFORM',    "均匀风",      "整个空间朝同一方向吹"),
            ('VORTEX',     "漩涡/龙卷",   "绕某个轴旋转"),
            ('RADIAL',     "径向爆发",    "从中心向外(或向内)"),
            ('CURLNOISE',  "旋度噪声",    "无散度湍流，最像烟雾，粒子不堆积"),
            ('TURBULENCE', "通用湍流",    "多层噪声，较乱，像官方 turbulance"),
            ('CURVE',      "沿预设轨迹",  "沿内置轨迹(直线/圆环/螺旋/8字...)流动"),
            ('SEL_CURVE',  "沿选中曲线",  "沿你在场景里选中的 Blender 曲线流动"),
            ('BREATHING',  "呼吸径向",    "径向球壳场;配合往复驱动做推出去/吸回来"),
            ('SWIRL_CONFINED', "波浪紊流", "旋度噪声+回拉;粒子乱飘又被拉回(刀鞘效果)"),
        ],
        default='VORTEX')
    pull: FloatProperty(name="回拉强度", default=0.4, min=0.0, max=1.5,
                        description="波浪紊流里把飘远粒子拉回来的力;越大越聚拢")
    shell: FloatProperty(name="球壳半径", default=0.45, min=0.05, max=1.0,
                         description="呼吸径向场里力最强的半径位置")

    # 这三个后处理开关搬自 .tfa 管线的游戏实机校准；数学上对任何容器格式都适用，
    # 但 "game_correct_x" 具体这个坐标修正只在 .tfa 消费路径上验证过，本仓写的是原生
    # .tex（大概率是不同的消费路径），默认关闭，需要用户自己判断要不要开。
    game_correct_x: BoolProperty(name="校正X轴(仅 .tfa 验证过)", default=False,
                                 description="镜像位置X轴。这是针对 .tfa 格式在游戏里验证过的坐标修正，"
                                             "对本仓读写的原生 .tex 向量场未验证，默认关闭")
    flat_emitter: BoolProperty(name="扁发射器模式(分层复制)", default=False,
                               description="扁圆盘发射器只采样中间层;开启后把中间层图案复制到所有层,保证完整呈现")
    make_seamless: BoolProperty(name="二方连续(边界无缝)", default=True,
                                description="让场在立方体边界循环连续,避免接缝")
    preset_path: EnumProperty(
        name="轨迹形状",
        items=[
            ('LINE',       "直线",      ""),
            ('CIRCLE',     "圆环",      ""),
            ('SPIRAL',     "螺旋",      ""),
            ('HELIX_TALL', "高螺旋",    ""),
            ('S_CURVE',    "S 形",      ""),
            ('FIGURE8',    "8 字",      ""),
            ('WAVE',       "波浪",      ""),
            ('TORUS_KNOT', "环面结",    ""),
        ],
        default='SPIRAL')
    curve_radius: FloatProperty(name="影响半径", default=0.35, min=0.05, max=1.5,
                                description="曲线周围多大范围内有力；越大力覆盖越广")
    strength: FloatProperty(name="强度", default=1.0, min=-2.0, max=2.0,
                            description="整体力度；漩涡里是沿轴气流，径向里负值=吸入")
    direction: FloatVectorProperty(name="方向", default=(0.0, 1.0, 0.0), size=3,
                                   subtype='DIRECTION')
    axis: EnumProperty(name="旋转轴",
                       items=[('X', "X (左右)", ""), ('Y', "Y (上下)", ""), ('Z', "Z (前后)", "")],
                       default='Y')
    swirl: FloatProperty(name="切向旋转", default=1.0, min=0.0, max=2.0,
                         description="绕轴转多快")
    inward: FloatProperty(name="向心/离心", default=-0.2, min=-1.0, max=1.0,
                          description="负=向内收束, 正=向外扩散")
    scale: FloatProperty(name="湍流密度", default=2.5, min=0.5, max=8.0,
                         description="越大湍流越细碎")
    seed: IntProperty(name="随机种子", default=7, min=0, max=9999)

    auto_visualize: BoolProperty(name="生成后自动可视化", default=True)


def _get_selected_curve_points(context, dim, samples=100):
    """从选中的 Blender 曲线物体取一串点，归一化到 [-0.85,0.85]（供 make_from_curve）。
    支持 Curve 物体；也支持用网格物体的顶点顺序当路径。返回 (M,3) 或 None。"""
    obj = context.active_object
    if obj is None or obj not in context.selected_objects:
        obj = next((o for o in context.selected_objects if o.type in ('CURVE', 'MESH')), None)
    if obj is None:
        return None

    pts = []
    if obj.type == 'CURVE':
        depsgraph = context.evaluated_depsgraph_get()
        ob_eval = obj.evaluated_get(depsgraph)
        me = ob_eval.to_mesh()
        try:
            if len(me.vertices) >= 2:
                for v in me.vertices:
                    pts.append(obj.matrix_world @ v.co)
        finally:
            ob_eval.to_mesh_clear()
        if not pts:
            for sp in obj.data.splines:
                for bp in sp.bezier_points:
                    pts.append(obj.matrix_world @ bp.co)
                for p in sp.points:
                    pts.append(obj.matrix_world @ p.co.xyz)
    else:
        for v in obj.data.vertices:
            pts.append(obj.matrix_world @ v.co)

    if len(pts) < 2:
        return None

    arr = np.array([(p.x, p.y, p.z) for p in pts], dtype=np.float32)
    center = (arr.max(0) + arr.min(0)) / 2.0
    arr = arr - center
    span = np.abs(arr).max()
    if span > 1e-6:
        arr = arr / span * 0.85
    if len(arr) > samples:
        idx = np.linspace(0, len(arr)-1, samples).astype(int)
        arr = arr[idx]
    return arr


class WILDS_VF_OT_generate_formula(Operator):
    bl_idname = "wilds_vecfield.generate_formula"
    bl_label = "按公式生成场"
    bl_description = "按当前参数用公式生成向量场，载入为当前场（可再可视化/导出）"

    def execute(self, context):
        scene = context.scene
        g = scene.wilds_vecfield_gen
        dim = g.dim
        try:
            ft = g.field_type
            if ft == 'UNIFORM':
                v = field_generators.make_uniform(dim, tuple(g.direction), g.strength)
            elif ft == 'VORTEX':
                v = field_generators.make_vortex(dim, g.axis, g.strength, g.swirl, g.inward)
            elif ft == 'RADIAL':
                v = field_generators.make_radial(dim, g.strength)
            elif ft == 'CURLNOISE':
                v = field_generators.make_curl_noise(dim, g.scale, g.strength, g.seed)
            elif ft == 'TURBULENCE':
                v = field_generators.make_turbulence(dim, g.scale, g.strength, g.seed)
            elif ft == 'BREATHING':
                v = field_generators.make_breathing_radial(dim, strength=g.strength, shell=g.shell)
            elif ft == 'SWIRL_CONFINED':
                v = field_generators.make_swirl_noise_confined(dim, scale=g.scale,
                                                               strength=g.strength, pull=g.pull, seed=g.seed)
            elif ft == 'CURVE':
                v = field_generators.make_from_preset(dim, g.preset_path,
                                                      radius=g.curve_radius, strength=g.strength)
            else:  # SEL_CURVE：从选中的 Blender 曲线取点
                pts = _get_selected_curve_points(context, dim)
                if pts is None:
                    self.report({'ERROR'}, "请先在场景里选中一条曲线(Curve)物体")
                    return {'CANCELLED'}
                v = field_generators.make_from_curve(dim, points=pts,
                                                     radius=g.curve_radius, strength=g.strength)

            if g.flat_emitter:
                v = field_generators.flatten_layers(v)
            if g.make_seamless:
                v = field_generators.make_periodic(v, blend=2)
            if g.game_correct_x:
                v = field_generators.correct_game_axes(v)

            alpha = np.ones((dim, dim, dim), dtype=np.uint8)
            scene['wilds_vecfield_data'] = {
                'vectors': v.tolist(),
                'dimensions': (dim, dim, dim),
                'version': VERSION_MHWILDS,
                'detected_size': f"{dim}x{dim}x{dim}",
                'alpha': alpha.tolist(),
            }
            mag = np.linalg.norm(v, axis=3)
            self.report({'INFO'},
                        f"已生成 {dim}³ {ft} 场（幅度均值{mag.mean():.2f} 最大{mag.max():.2f}），可直接导出/可视化")

            if g.auto_visualize:
                try:
                    bpy.ops.wilds_vecfield.visualize_field()
                except Exception as e:
                    print("自动可视化失败(不影响数据):", e)
        except Exception as e:
            self.report({'ERROR'}, f"生成失败: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}


class VIEW3D_PT_wilds_vecfield_generate(Panel):
    bl_label = "公式生成"
    bl_idname = "VIEW3D_PT_wilds_vecfield_generate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MHWilds VecField"

    def draw(self, context):
        layout = self.layout
        g = context.scene.wilds_vecfield_gen

        layout.prop(g, "dim")
        layout.prop(g, "field_type")

        if g.field_type == 'UNIFORM':
            layout.prop(g, "direction")
        elif g.field_type == 'VORTEX':
            layout.prop(g, "axis")
            layout.prop(g, "swirl")
            layout.prop(g, "inward")
        elif g.field_type in ('CURLNOISE', 'TURBULENCE', 'SWIRL_CONFINED'):
            layout.prop(g, "scale")
            layout.prop(g, "seed")
            if g.field_type == 'SWIRL_CONFINED':
                layout.prop(g, "pull")
        elif g.field_type == 'BREATHING':
            layout.prop(g, "shell")
        elif g.field_type == 'CURVE':
            layout.prop(g, "preset_path")
            layout.prop(g, "curve_radius")
        elif g.field_type == 'SEL_CURVE':
            layout.prop(g, "curve_radius")
            layout.label(text="需要先选中一条曲线物体", icon='INFO')

        layout.prop(g, "strength")

        box = layout.box()
        box.label(text="后处理", icon='MODIFIER')
        box.prop(g, "flat_emitter")
        box.prop(g, "make_seamless")
        box.prop(g, "game_correct_x")

        layout.prop(g, "auto_visualize")
        layout.operator("wilds_vecfield.generate_formula", icon='PHYSICS')


# 场信息面板已移至ui_panels.py
from . import wilds_vecfield_panels as ui_panels

# 所有类列表
classes = [
    WildsVecFieldProperties,
    WildsVecFieldGenProps,
    WILDS_VF_OT_load_tex,
    WILDS_VF_OT_generate_base,
    WILDS_VF_OT_generate_formula,
    WILDS_VF_OT_save_tex,
    WILDS_VF_OT_visualize_field,
    WILDS_VF_OT_clear_field,
    WILDS_VF_OT_clear_all_objects,
    WILDS_VF_OT_modify_pixels,  # 添加像素修改操作符
    WILDS_VF_OT_particle_system,  # 添加粒子系统操作符
    WILDS_VF_OT_select_vector,  # 添加选择向量操作符
    WILDS_VF_OT_clear_selected_vectors,  # 添加清除选中向量操作符
    WILDS_VF_OT_update_vector,  # 添加更新向量操作符
    WILDS_VF_OT_rotate_vectors,  # 添加旋转向量操作符
    WILDS_VF_OT_invert_vectors,  # 添加反转向量操作符
    WILDS_VF_OT_set_vector_values,  # 添加设置向量数值操作符
    WILDS_VF_OT_apply_vector_preset,  # 添加向量预设工具操作符
    WILDS_VF_OT_exit_vector_edit,  # 添加退出向量编辑模式操作符
    VIEW3D_PT_wilds_vecfield_tools,
    VIEW3D_PT_wilds_vecfield_generate,
]

def register():
    # 注册ui_panels.py中的类
    ui_panels.register()

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.wilds_vecfield_props = PointerProperty(type=WildsVecFieldProperties)
    bpy.types.Scene.wilds_vecfield_gen = PointerProperty(type=WildsVecFieldGenProps)

    print("✅ MHWilds VecField registered successfully")

def unregister():
    # 清理场景属性
    for scene in bpy.data.scenes:
        if 'wilds_vecfield_data' in scene:
            del scene['wilds_vecfield_data']

    # 删除属性
    if hasattr(bpy.types.Scene, 'wilds_vecfield_props'):
        del bpy.types.Scene.wilds_vecfield_props
    if hasattr(bpy.types.Scene, 'wilds_vecfield_gen'):
        del bpy.types.Scene.wilds_vecfield_gen

    # 注销所有类
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    # 注销ui_panels.py中的类
    ui_panels.unregister()
    
    print("❌ MHWilds VecField unregistered")

# 用于测试
if __name__ == "__main__":
    register()
