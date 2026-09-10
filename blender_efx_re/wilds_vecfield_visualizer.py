import bpy
import bmesh
import numpy as np
from mathutils import Vector, Color
import colorsys


def _set_bsdf_transmission(bsdf, value):
    """Blender 4.0 把 Principled BSDF 的 'Transmission' 输入改名成了
    'Transmission Weight'；直接按旧名字取会在新版本 KeyError。探测两个名字都试一下。"""
    if bsdf is None:
        return
    for key in ('Transmission Weight', 'Transmission'):
        if key in bsdf.inputs:
            try:
                bsdf.inputs[key].default_value = value
            except Exception:
                pass
            return


def create_visualization(vectors, dimensions, scale_factor=1.0,
                        vector_scale=0.1, resolution=8,
                        show_vectors=True, color_by_magnitude=True,
                        create_vertex_color_mesh=False,
                        show_streamlines=False,
                        show_slices=False,
                        slice_axis='Z',
                        slice_position=0.5,
                        visualization_mode='full',
                        show_bounds=False,
                        arrow_color_mode='DIRECTION'):
    """
    创建3D向量场可视化
    
    参数:
    - visualization_mode: str - 可视化模式
        'full' - 完整可视化（默认）
        'lightweight' - 轻量级可视化（适合高性能需求）
        'slices_only' - 仅显示切片
        'vectors_only' - 仅显示向量箭头
        'bounding_box_only' - 仅显示边界框
    """
    width, height, depth = dimensions
    
    print(f"创建可视化: {width}×{height}×{depth}, 分辨率: {resolution}, 模式: {visualization_mode}")
    
    # 根据可视化模式调整设置
    if visualization_mode == 'lightweight':
        # 轻量级模式：减少分辨率，只显示必要的可视化元素
        resolution = max(4, resolution // 2)  # 降低分辨率
        create_vertex_color_mesh = False  # 关闭顶点颜色网格
        show_streamlines = False  # 关闭流线
        show_slices = False  # 关闭切片
    elif visualization_mode == 'slices_only':
        # 仅显示切片
        create_vertex_color_mesh = False
        show_vectors = False
        show_streamlines = False
        show_slices = True
    elif visualization_mode == 'vectors_only':
        # 仅显示向量箭头
        create_vertex_color_mesh = False
        show_streamlines = False
        show_slices = False
    elif visualization_mode == 'bounding_box_only':
        # 仅显示边界框
        create_vertex_color_mesh = False
        show_vectors = False
        show_streamlines = False
        show_slices = False
    
    # 创建新的集合
    collection_name = "MHWilds_VecField"
    
    # 清理旧的集合
    if collection_name in bpy.data.collections:
        collection = bpy.data.collections[collection_name]
        for obj in list(collection.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    else:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
    
    # 创建边界框
    if show_bounds:
        create_simple_bounding_box(width, height, depth, scale_factor, collection)
    
    # 创建顶点颜色网格
    if create_vertex_color_mesh:
        create_vertex_color_grid(vectors, dimensions, scale_factor, collection)
    
    # 创建向量箭头
    if show_vectors and resolution > 0:
        create_enhanced_vector_arrows(vectors, dimensions, scale_factor,
                                     vector_scale, resolution, color_by_magnitude, collection,
                                     arrow_color_mode=arrow_color_mode)
    
    # 创建流线可视化
    if show_streamlines:
        create_streamlines(vectors, dimensions, scale_factor, collection)
    
    # 创建切片可视化
    if show_slices:
        create_field_slice(vectors, dimensions, scale_factor, slice_axis, slice_position, collection)
    
    print(f"✅ 可视化创建完成")
    return collection

def create_vertex_color_grid(vectors, dimensions, scale_factor, collection):
    """
    创建基于顶点颜色的网格可视化
    每个像素对应一个立方体，顶点颜色表示向量方向
    """
    width, height, depth = dimensions
    
    print(f"📦 创建顶点颜色网格: {width}×{height}×{depth}")
    
    # 为了性能，可以降低分辨率（可选）
    # 例如，对于30×30×30的场，可以采样为10×10×10
    sample_step = max(1, min(width, height, depth) // 10)
    if sample_step > 1:
        print(f"  使用采样步长: {sample_step}")
    
    # 创建主网格
    mesh = bpy.data.meshes.new("Turbulence_Vertex_Color_Grid")
    obj = bpy.data.objects.new("Turbulence_Grid", mesh)
    
    # 创建BMesh
    bm = bmesh.new()
    
    # 计算每个立方体的大小
    cube_size = scale_factor * 0.8  # 稍微小于网格间距
    
    # 统计创建的立方体数量
    cube_count = 0
    
    for z in range(0, depth, sample_step):
        for y in range(0, height, sample_step):
            for x in range(0, width, sample_step):
                # 获取向量
                vector = vectors[z, y, x]
                magnitude = np.linalg.norm(vector)
                
                # 跳过太小或无意义的向量
                if magnitude < 0.01:
                    continue
                
                # 计算位置 - 修正Y轴和Z轴的方向，确保向量场居中
                # 在Blender中，Y轴是向前的，Z轴是向上的
                world_x = (x - (width-1)/2) * scale_factor
                world_y = (y - (height-1)/2) * scale_factor
                world_z = (z - (depth-1)/2) * scale_factor
                
                # 创建立方体
                create_colored_cube(bm, (world_x, world_y, world_z), 
                                  cube_size, vector, magnitude)
                cube_count += 1
    
    # 更新网格
    bm.to_mesh(mesh)
    bm.free()
    
    # 创建顶点颜色数据
    create_vertex_color_data(obj, mesh, vectors, dimensions, scale_factor, sample_step)
    
    # 设置材质
    setup_vertex_color_material(obj)
    
    # 添加到集合
    collection.objects.link(obj)
    
    print(f"  创建了 {cube_count} 个彩色立方体")

def create_colored_cube(bm, location, size, vector, magnitude):
    """
    创建立方体并将其移动到指定位置
    """
    # 创建立方体
    bmesh.ops.create_cube(bm, size=size)
    
    # 获取最新创建的顶点
    cube_verts = [v for v in bm.verts][-8:]  # 立方体有8个顶点
    
    # 移动立方体到指定位置
    for vert in cube_verts:
        vert.co.x += location[0]
        vert.co.y += location[1]
        vert.co.z += location[2]

def create_vertex_color_data(obj, mesh, vectors, dimensions, scale_factor, sample_step):
    """
    为网格创建顶点颜色数据
    """
    width, height, depth = dimensions
    
    # 创建顶点颜色层
    color_layer = mesh.vertex_colors.new()
    
    # 获取顶点颜色数据
    color_data = color_layer.data
    
    # 为每个面设置颜色
    color_idx = 0
    cube_count = 0
    for z in range(0, depth, sample_step):
        for y in range(0, height, sample_step):
            for x in range(0, width, sample_step):
                vector = vectors[z, y, x]
                magnitude = np.linalg.norm(vector)
                
                if magnitude < 0.01:
                    color = (0.5, 0.5, 0.5, 1.0)  # 灰色表示无扰动
                else:
                    # 根据向量方向和幅度设置颜色
                    color = vector_to_color(vector, magnitude)
                
                # 计算该位置是否有立方体（与create_vertex_color_grid函数的跳过逻辑保持一致）
                if magnitude >= 0.01:
                    # 立方体有6个面，每个面2个三角形，每个三角形3个顶点
                    # 所以每个立方体有 6 * 2 * 3 = 36 个顶点颜色数据
                    for i in range(36):
                        if color_idx < len(color_data):
                            color_data[color_idx].color = color
                            color_idx += 1
                    cube_count += 1
    
    print(f"  已设置 {color_idx} 个顶点颜色")
    print(f"  处理了 {cube_count} 个立方体")
    
    # 更新网格显示
    mesh.update()

def vector_to_color(vector, magnitude):
    """
    将向量转换为颜色
    X: 红/青 (右/左)
    Y: 绿/品红 (前/后)  
    Z: 蓝/黄 (上/下)
    """
    # 归一化向量
    if magnitude > 0:
        norm_vec = vector / magnitude
    else:
        norm_vec = np.zeros(3)
    
    # 计算各分量
    r = 0.5 + norm_vec[0] * 0.5  # X分量 -> 红色
    g = 0.5 + norm_vec[1] * 0.5  # Y分量 -> 绿色
    b = 0.5 + norm_vec[2] * 0.5  # Z分量 -> 蓝色
    
    # 根据幅度调整亮度
    brightness = 0.3 + magnitude * 0.7
    r = r * brightness
    g = g * brightness
    b = b * brightness
    
    # 限制颜色范围
    r = max(0.0, min(1.0, r))
    g = max(0.0, min(1.0, g))
    b = max(0.0, min(1.0, b))
    
    return (r, g, b, 1.0)

def setup_vertex_color_material(obj):
    """
    设置顶点颜色材质
    """
    mat = bpy.data.materials.new("Vertex_Color_Material")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    
    # 清除默认节点
    nodes.clear()
    
    # 创建顶点颜色节点
    vertex_color = nodes.new(type='ShaderNodeVertexColor')
    vertex_color.layer_name = "Col"  # 默认顶点颜色层名称
    
    # 创建BSDF节点
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (200, 0)
    
    # 创建输出节点
    output = nodes.new(type='ShaderNodeOutputMaterial')
    output.location = (400, 0)
    
    # 连接节点
    links.new(vertex_color.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    
    # 应用到对象
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

def create_simple_bounding_box(width, height, depth, scale_factor, collection):
    """创建简化的边界框"""
    # 使用Blender的内置功能创建立方体
    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=(0, 0, 0)
    )
    cube = bpy.context.active_object
    cube.name = "Field_Bounds"
    
    # 设置缩放
    cube.scale = (
        width * scale_factor / 2,
        height * scale_factor / 2,
        depth * scale_factor / 2
    )
    
    # 设置材质
    mat = bpy.data.materials.new("Bounds_Material")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.3, 0.3, 0.3, 0.2)
        _set_bsdf_transmission(bsdf, 0.5)
        bsdf.inputs['Roughness'].default_value = 0.8
    
    cube.data.materials.append(mat)
    
    # 移动到集合
    if cube.name in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.unlink(cube)
    collection.objects.link(cube)

def create_enhanced_vector_arrows(vectors, dimensions, scale_factor,
                               vector_scale, resolution, color_by_magnitude, collection,
                               arrow_color_mode='DIRECTION'):
    """创建增强的向量箭头 - 动态长度、按方向/幅度着色

    arrow_color_mode:
        'DIRECTION' - 按向量方向着色（RGB=方向），幅度均匀的场也能看清流向结构
        'MAGNITUDE' - 按幅度着色（蓝→红）
    """
    width, height, depth = dimensions

    # 计算采样步长，增加步长减少箭头数量
    step_x = max(2, width // resolution)
    step_y = max(2, height // resolution)
    step_z = max(2, depth // resolution)

    # 计算向量幅度范围用于颜色映射
    all_magnitudes = np.linalg.norm(vectors, axis=3)
    min_mag = all_magnitudes.min()
    max_mag = all_magnitudes.max()
    mag_range = max_mag - min_mag if max_mag != min_mag else 1.0

    # 减少箭头数量：只显示较大的向量
    min_magnitude_threshold = max(0.1, mag_range * 0.3)  # 提高阈值，只显示较强的向量

    # 优化：材质按"量化键"缓存复用，避免逐箭头建材质
    vector_materials = {}
    def get_vector_material(vector, magnitude):
        """根据着色模式获取/创建材质，返回 (material, rgb)。"""
        if arrow_color_mode == 'MAGNITUDE':
            normalized_mag = (magnitude - min_mag) / mag_range
            hue = 0.6 - normalized_mag * 0.6  # 0.6=blue, 0.0=red
            rgb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            strength = 1.0 + normalized_mag * 3.0
            key = ('M', round(magnitude * 10) / 10)
        else:  # DIRECTION
            rgb = vector_to_color(vector, magnitude)[:3]
            normalized_mag = (magnitude - min_mag) / mag_range
            strength = 1.5 + normalized_mag * 2.0
            # 量化方向颜色为材质键，限制材质数量
            key = ('D', round(rgb[0] * 12), round(rgb[1] * 12), round(rgb[2] * 12))

        if key not in vector_materials:
            mat = bpy.data.materials.new(f"Vector_Mat_{key[0]}_{abs(hash(key)) % 100000}")
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            nodes.clear()
            emission = nodes.new(type='ShaderNodeEmission')
            emission.inputs['Color'].default_value = (*rgb, 1.0)
            emission.inputs['Strength'].default_value = strength
            output = nodes.new(type='ShaderNodeOutputMaterial')
            mat.node_tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])
            vector_materials[key] = (mat, rgb)
        return vector_materials[key]
    
    # 优化：使用更简单的箭头形状，减少计算量
    bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=0.05, radius2=0, depth=0.5, location=(0, 0, 0.25))
    
    arrow_template = bpy.context.active_object
    arrow_template.name = "Arrow_Template"
    
    # 旋转模板使其指向正Z方向
    arrow_template.rotation_euler[0] = -np.pi / 2
    
    # 隐藏模板
    arrow_template.hide_set(True)
    arrow_template.hide_render = True
    
    # 创建箭头
    arrow_count = 0
    for z in range(0, depth, step_z):
        for y in range(0, height, step_y):
            for x in range(0, width, step_x):
                vector = vectors[z, y, x]
                magnitude = np.linalg.norm(vector)
                
                if magnitude < min_magnitude_threshold:  # 只显示较强的向量
                    continue
                
                # 计算世界位置
                world_x = (x - (width-1)/2) * scale_factor
                world_y = (y - (height-1)/2) * scale_factor
                world_z = (z - (depth-1)/2) * scale_factor
                
                # 复制箭头
                arrow_obj = arrow_template.copy()
                arrow_obj.data = arrow_template.data.copy()
                arrow_obj.name = f"Arrow_{x}_{y}_{z}"
                
                # 设置位置
                arrow_obj.location = (world_x, world_y, world_z)
                
                # 动态缩放 - 基于向量幅度
                arrow_length = vector_scale * (0.5 + magnitude * 1.5)  # 动态长度
                arrow_obj.scale = (vector_scale * 0.5, vector_scale * 0.5, arrow_length)
                
                # 设置旋转
                direction = Vector(vector).normalized()
                if direction.length > 0:
                    rotation = direction.to_track_quat('-Z', 'Y')
                    arrow_obj.rotation_mode = 'QUATERNION'
                    arrow_obj.rotation_quaternion = rotation
                
                # 创建并应用颜色材质（按方向或幅度）
                if color_by_magnitude:
                    mat, rgb = get_vector_material(vector, magnitude)
                    if arrow_obj.data.materials:
                        arrow_obj.data.materials[0] = mat
                    else:
                        arrow_obj.data.materials.append(mat)
                    # 同时设 object color，使 Solid 视口（着色>颜色>对象）也能显色
                    arrow_obj.color = (*rgb, 1.0)
                
                # 添加到集合
                collection.objects.link(arrow_obj)
                
                arrow_count += 1
    
    # 删除模板
    bpy.data.objects.remove(arrow_template, do_unlink=True)
    
    print(f"  ✅ 创建了 {arrow_count} 个增强向量箭头")


def _sample_trilinear(vectors, px, py, pz, dimensions):
    """在连续体素坐标 (px,py,pz) 处三线性插值向量场。vectors 索引为 [z,y,x]。"""
    width, height, depth = dimensions
    # 夹取到合法范围
    px = min(max(px, 0.0), width - 1.0)
    py = min(max(py, 0.0), height - 1.0)
    pz = min(max(pz, 0.0), depth - 1.0)
    x0 = int(np.floor(px)); y0 = int(np.floor(py)); z0 = int(np.floor(pz))
    x1 = min(x0 + 1, width - 1); y1 = min(y0 + 1, height - 1); z1 = min(z0 + 1, depth - 1)
    fx = px - x0; fy = py - y0; fz = pz - z0
    # 8 邻角加权（注意索引顺序 [z,y,x]）
    c000 = vectors[z0, y0, x0]; c100 = vectors[z0, y0, x1]
    c010 = vectors[z0, y1, x0]; c110 = vectors[z0, y1, x1]
    c001 = vectors[z1, y0, x0]; c101 = vectors[z1, y0, x1]
    c011 = vectors[z1, y1, x0]; c111 = vectors[z1, y1, x1]
    c00 = c000 * (1 - fx) + c100 * fx
    c01 = c001 * (1 - fx) + c101 * fx
    c10 = c010 * (1 - fx) + c110 * fx
    c11 = c011 * (1 - fx) + c111 * fx
    c0 = c00 * (1 - fy) + c10 * fy
    c1 = c01 * (1 - fy) + c11 * fy
    return c0 * (1 - fz) + c1 * fz


def _integrate_streamline(vectors, seed, dimensions, h=0.6, max_steps=60, direction=1, min_mag=0.04):
    """从 seed 沿场积分一条流线（归一化 RK2/中点法，步长恒定）。
    direction=+1 顺流，-1 逆流。返回体素坐标点列表。"""
    width, height, depth = dimensions
    pts = []
    px, py, pz = seed
    for _ in range(max_steps):
        if not (0 <= px <= width - 1 and 0 <= py <= height - 1 and 0 <= pz <= depth - 1):
            break
        v = _sample_trilinear(vectors, px, py, pz, dimensions)
        n = float(np.linalg.norm(v))
        if n < min_mag:
            break
        d = (v / n) * direction
        pts.append((px, py, pz))
        # RK2 中点
        mx, my, mz = px + d[0] * h * 0.5, py + d[1] * h * 0.5, pz + d[2] * h * 0.5
        if not (0 <= mx <= width - 1 and 0 <= my <= height - 1 and 0 <= mz <= depth - 1):
            break
        vm = _sample_trilinear(vectors, mx, my, mz, dimensions)
        nm = float(np.linalg.norm(vm))
        if nm < min_mag:
            break
        dm = (vm / nm) * direction
        px += dm[0] * h; py += dm[1] * h; pz += dm[2] * h
    return pts


def create_streamlines(vectors, dimensions, scale_factor, collection, max_lines=160):
    """创建流线可视化 - 网格播种 + 三线性采样 + 归一化 RK2 积分 + 末端箭头 + 方向着色。"""
    print("  🌀 创建流线可视化（升级版）...")
    width, height, depth = dimensions

    def to_world(p):
        return ((p[0] - (width - 1) / 2) * scale_factor,
                (p[1] - (height - 1) / 2) * scale_factor,
                (p[2] - (depth - 1) / 2) * scale_factor)

    # 材质按量化方向颜色缓存复用
    line_materials = {}
    def get_dir_material(rgb, strength=2.5):
        key = (round(rgb[0] * 12), round(rgb[1] * 12), round(rgb[2] * 12))
        if key not in line_materials:
            m = bpy.data.materials.new(f"Streamline_Mat_{key}")
            m.use_nodes = True
            nd = m.node_tree.nodes; nd.clear()
            em = nd.new(type='ShaderNodeEmission')
            em.inputs['Color'].default_value = (*rgb, 1.0)
            em.inputs['Strength'].default_value = strength
            out = nd.new(type='ShaderNodeOutputMaterial')
            m.node_tree.links.new(em.outputs['Emission'], out.inputs['Surface'])
            line_materials[key] = m
        return line_materials[key]

    # 网格播种：在体素网格上等距取种子（控制数量）
    seed_step = max(2, min(width, height, depth) // 5)
    seeds = []
    for z in range(seed_step // 2, depth, seed_step):
        for y in range(seed_step // 2, height, seed_step):
            for x in range(seed_step // 2, width, seed_step):
                seeds.append((float(x), float(y), float(z)))
    # 数量上限保护（大场如 75³）
    if len(seeds) > max_lines:
        idx = np.linspace(0, len(seeds) - 1, max_lines).astype(int)
        seeds = [seeds[i] for i in idx]

    line_count = 0
    for i, seed in enumerate(seeds):
        # 双向积分，拼成一条过种子的完整流线
        back = _integrate_streamline(vectors, seed, dimensions, direction=-1)
        fwd = _integrate_streamline(vectors, seed, dimensions, direction=1)
        pts_vox = list(reversed(back)) + fwd[1:] if back else fwd
        if len(pts_vox) < 3:
            continue

        pts_world = [to_world(p) for p in pts_vox]

        # 沿程平均方向 → 颜色
        seg = np.array(pts_vox[-1]) - np.array(pts_vox[0])
        seg_n = np.linalg.norm(seg)
        mean_dir = seg / seg_n if seg_n > 1e-6 else np.array([0.0, 0.0, 1.0])
        rgb = vector_to_color(mean_dir, 1.0)[:3]
        mat = get_dir_material(rgb)

        # 曲线
        curve_data = bpy.data.curves.new(f"Streamline_{i}", type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 2
        spline = curve_data.splines.new(type='POLY')
        spline.points.add(len(pts_world) - 1)
        for j, (x, y, z) in enumerate(pts_world):
            spline.points[j].co = (x, y, z, 1.0)
        curve_data.bevel_depth = 0.015 * max(scale_factor, 1.0)
        curve_data.bevel_resolution = 2
        curve_obj = bpy.data.objects.new(f"Streamline_{i}", curve_data)
        curve_obj.data.materials.append(mat)
        curve_obj.color = (*rgb, 1.0)
        collection.objects.link(curve_obj)

        # 末端箭头：标示流向
        tip = pts_world[-1]
        prev = pts_world[-2]
        tip_dir = Vector((tip[0] - prev[0], tip[1] - prev[1], tip[2] - prev[2]))
        if tip_dir.length > 1e-6:
            bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=0.06 * max(scale_factor, 1.0),
                                            radius2=0, depth=0.18 * max(scale_factor, 1.0),
                                            location=tip)
            head = bpy.context.active_object
            head.name = f"Streamline_Head_{i}"
            head.rotation_mode = 'QUATERNION'
            head.rotation_quaternion = tip_dir.normalized().to_track_quat('Z', 'Y')
            head.data.materials.append(mat)
            head.color = (*rgb, 1.0)
            if head.name in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.unlink(head)
            collection.objects.link(head)

        line_count += 1

    print(f"  ✅ 创建了 {line_count} 条流线（种子 {len(seeds)}，材质 {len(line_materials)}）")


def create_field_slice(vectors, dimensions, scale_factor, slice_axis, slice_position, collection):
    """创建向量场的2D切片可视化"""
    print(f"  📊 创建 {slice_axis} 轴切片，位置: {slice_position}")
    width, height, depth = dimensions
    
    # 计算切片位置
    if slice_axis == 'X':
        slice_idx = int(slice_position * (width - 1))
        slice_data = vectors[:, :, slice_idx]
        slice_dim1, slice_dim2 = height, depth
        slice_name = f"Slice_X_{slice_idx}"
    elif slice_axis == 'Y':
        slice_idx = int(slice_position * (height - 1))
        slice_data = vectors[:, slice_idx, :]
        slice_dim1, slice_dim2 = depth, width
        slice_name = f"Slice_Y_{slice_idx}"
    else:  # Z轴
        slice_idx = int(slice_position * (depth - 1))
        slice_data = vectors[slice_idx, :, :]
        slice_dim1, slice_dim2 = height, width
        slice_name = f"Slice_Z_{slice_idx}"
    
    # 创建切片平面
    bpy.ops.mesh.primitive_plane_add(size=max(slice_dim1, slice_dim2) * scale_factor, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = slice_name
    
    # 设置平面位置和旋转
    if slice_axis == 'X':
        plane.location = ((slice_idx - (width-1)/2) * scale_factor, 0, 0)
        plane.rotation_euler[1] = np.pi / 2
    elif slice_axis == 'Y':
        plane.location = (0, (slice_idx - (height-1)/2) * scale_factor, 0)
        plane.rotation_euler[0] = np.pi / 2
    else:  # Z轴
        plane.location = (0, 0, (slice_idx - (depth-1)/2) * scale_factor)
    
    # 创建切片材质 - 半透明平面
    mat = bpy.data.materials.new(f"Slice_Material_{slice_name}")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.3, 0.6, 0.9, 0.3)
    _set_bsdf_transmission(bsdf, 0.8)
    bsdf.inputs['Roughness'].default_value = 0.2
    
    output = nodes.new(type='ShaderNodeOutputMaterial')
    
    mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    
    if plane.data.materials:
        plane.data.materials[0] = mat
    else:
        plane.data.materials.append(mat)
    
    # 为切片添加向量箭头
    resolution = 5
    step1 = max(1, slice_dim1 // resolution)
    step2 = max(1, slice_dim2 // resolution)
    
    for i in range(0, slice_dim1, step1):
        for j in range(0, slice_dim2, step2):
            if slice_axis == 'X':
                vector = slice_data[i, j]
                world_x = (slice_idx - (width-1)/2) * scale_factor
                world_y = (i - (height-1)/2) * scale_factor
                world_z = (j - (depth-1)/2) * scale_factor
            elif slice_axis == 'Y':
                vector = slice_data[i, j]
                world_x = (j - (width-1)/2) * scale_factor
                world_y = (slice_idx - (height-1)/2) * scale_factor
                world_z = (i - (depth-1)/2) * scale_factor
            else:  # Z轴
                vector = slice_data[i, j]
                world_x = (j - (width-1)/2) * scale_factor
                world_y = (i - (height-1)/2) * scale_factor
                world_z = (slice_idx - (depth-1)/2) * scale_factor
            
            magnitude = np.linalg.norm(vector)
            
            if magnitude > 0.05:
                # 创建箭头
                bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=0.05, radius2=0, depth=0.3, location=(world_x, world_y, world_z))
                arrow = bpy.context.active_object
                arrow.name = f"Slice_Arrow_{slice_name}_{i}_{j}"
                
                # 设置箭头方向
                direction = Vector(vector).normalized()
                if direction.length > 0:
                    rotation = direction.to_track_quat('-Z', 'Y')
                    arrow.rotation_mode = 'QUATERNION'
                    arrow.rotation_quaternion = rotation
                
                # 设置箭头大小
                arrow.scale = (0.5, 0.5, magnitude * 0.5)
                
                # 箭头颜色 - 基于向量方向
                hue = (np.arctan2(vector[1], vector[0]) + np.pi) / (2 * np.pi)
                rgb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                
                arrow_mat = bpy.data.materials.new(f"Slice_Arrow_Mat_{i}_{j}")
                arrow_mat.use_nodes = True
                arrow_nodes = arrow_mat.node_tree.nodes
                arrow_nodes.clear()
                
                arrow_emission = arrow_nodes.new(type='ShaderNodeEmission')
                arrow_emission.inputs['Color'].default_value = (*rgb, 1.0)
                arrow_emission.inputs['Strength'].default_value = 2.0
                
                arrow_output = arrow_nodes.new(type='ShaderNodeOutputMaterial')
                arrow_mat.node_tree.links.new(arrow_emission.outputs['Emission'], arrow_output.inputs['Surface'])
                
                if arrow.data.materials:
                    arrow.data.materials[0] = arrow_mat
                else:
                    arrow.data.materials.append(arrow_mat)
                
                # 添加到集合
                collection.objects.link(arrow)
    
    # 添加平面到集合
    collection.objects.link(plane)
    
    print(f"  ✅ 创建了 {slice_name} 切片")

def create_dense_vertex_color_mesh(vectors, dimensions, scale_factor, collection):
    """
    创建密集的顶点颜色网格（替代方案）
    创建一个大的网格，每个像素对应一个顶点
    """
    width, height, depth = dimensions
    
    print(f"🟦 创建密集顶点颜色网格: {width}×{height}×{depth}")
    
    # 创建网格
    mesh = bpy.data.meshes.new("Dense_Turbulence_Mesh")
    obj = bpy.data.objects.new("Dense_Turbulence", mesh)
    
    # 创建顶点
    vertices = []
    vertex_colors = []
    
    for z in range(depth):
        for y in range(height):
            for x in range(width):
                # 计算位置
                world_x = (x - (width-1)/2) * scale_factor
                world_y = (y - (height-1)/2) * scale_factor
                world_z = (z - (depth-1)/2) * scale_factor
                
                vertices.append((world_x, world_y, world_z))
                
                # 计算顶点颜色
                vector = vectors[z, y, x]
                magnitude = np.linalg.norm(vector)
                color = vector_to_color(vector, magnitude)
                vertex_colors.append(color[:3])  # 只取RGB
    
    # 创建面（简单立方体网格）
    faces = []
    
    # 这里可以创建更复杂的网格连接，或者保持为点云
    # 简单起见，我们只创建顶点，不创建面（点云模式）
    
    # 创建网格
    mesh.from_pydata(vertices, [], [])
    
    # 创建顶点颜色
    color_layer = mesh.vertex_colors.new()
    for i, color in enumerate(vertex_colors):
        if i < len(color_layer.data):
            color_layer.data[i].color = (color[0], color[1], color[2], 1.0)
    
    # 设置材质
    setup_vertex_color_material(obj)
    
    # 设置显示为顶点（点云）
    mesh.update()
    
    # 添加到集合
    collection.objects.link(obj)
    
    print(f"  创建了 {len(vertices)} 个彩色顶点")

# ===== 在__init__.py中需要更新的可视化调用 =====
# 修改 TFA_OT_visualize_field 中的调用
"""
# 在可视化操作符中调用：
vector_field_visualizer.create_visualization(
    vectors,
    dimensions,
    scale_factor=props.scale_factor,
    vector_scale=props.vector_scale,
    resolution=props.resolution,
    show_vectors=props.show_vectors,
    color_by_magnitude=props.color_by_magnitude,
    create_vertex_color_mesh=True  # 新增参数
)
"""

# ===== 在UI面板中添加选项 =====
"""
# 在TFAProperties中添加：
show_vertex_colors: BoolProperty(
    name="Show Vertex Colors",
    description="Display turbulence field as vertex colors",
    default=True
)

# 在UI面板中添加：
box.prop(props, "show_vertex_colors")
"""
