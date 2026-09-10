# -*- coding: utf-8 -*-
"""
wilds_vecfield_field_generators.py  —  按公式一键生成三维湍流向量场

移植自 blender_tfa_importer 的优化版原型（field_generators.py），本模块是
【纯 numpy】的，不依赖 bpy，可以单独测试。每个 make_* 函数都返回一个
(N, N, N, 3) 的 float32 数组，索引顺序是 [z, y, x]，每个分量范围约 [-1, 1]，
正好对应向量场的 RGB 编码（(byte-128)/127）。

坐标约定：每个体素中心的归一化坐标 p 落在 [-1, 1]，原点在立方体正中心。
    vectors[z, y, x] = (vx, vy, vz)

这些配方就是"想要什么流场，直接算出来"，用来替代"只能从全零场慢慢手改"的做法。

⚠ 下面 `correct_game_axes()` / `make_vortex()` 里提到的"游戏实测"，指的是原作者
在 **`.tfa`**（EFX turbulence attribute 消费的格式）这条管线上做过的游戏内验证，
**不是**针对本仓库读写的原生 `.tex` 向量场（`VFX_Library/TEX_Vectorfield` 下那批
资产，走的很可能是完全不同的消费路径）。这条坐标修正搬过来是因为数学配方本身
（漩涡/湍流/曲线流动等）与容器格式无关，但"要不要在导出前做 X 轴镜像"这一步
对 `.tex` 管线尚未验证，UI 上默认关闭，需要用户自己判断。
"""

import numpy as np


# ============================================================================
# 【游戏正确化】后处理（.tfa 管线实测校准，见上方模块说明的验证边界）
# ----------------------------------------------------------------------------
#   1. correct_game_axes: 游戏的位置X轴翻转(tfa +X位置->游戏后方)，Y/Z正常
#   2. flatten_layers:    扁发射器只采样中间层，把中间层图案复制到所有Y层
#   3. make_periodic:     让场在立方体边界无缝循环(二方连续)，避免游戏里断裂
# ============================================================================

def correct_game_axes(field):
    """位置X轴镜像。游戏里 tfa 的位置X是翻转的，导出前镜像一次让方向与Blender一致。
    field: (N,N,N,3) 索引[z,y,x]。只翻转位置(数组的x轴)，不动向量分量。"""
    return np.ascontiguousarray(np.flip(field, axis=2))


def flatten_layers(field, src_layer=None):
    """把某一层(默认中间层)的图案复制到所有 Y 层。
    用于扁发射器：它只采样中间层，这样保证扁圆盘能吃到完整水平图案。
    field: (N,N,N,3) 索引[z,y,x]，Y是数组第2维。"""
    dim = field.shape[0]
    if src_layer is None:
        src_layer = dim // 2
    out = field.copy()
    layer = field[:, src_layer, :, :]        # (z, x, 3) 取中间Y层
    for y in range(dim):
        out[:, y, :, :] = layer
    return out


def make_periodic(field, blend=2):
    """让场在三个方向的边界无缝循环(二方连续)。
    做法:把靠近边界的几层与对面边界做线性混合,消除接缝。
    blend: 参与混合的边界层数。field: (N,N,N,3)。"""
    f = field.copy()
    dim = f.shape[0]
    b = min(blend, dim // 2)
    if b < 1:
        return f
    for axis in range(3):
        for i in range(b):
            w = (i + 1) / (b + 1) * 0.5      # 边界处权重小,往里渐增
            # 取该轴两端的切片做混合
            sl_lo = [slice(None)] * 3; sl_lo[axis] = i
            sl_hi = [slice(None)] * 3; sl_hi[axis] = dim - 1 - i
            lo = f[tuple(sl_lo)].copy()
            hi = f[tuple(sl_hi)].copy()
            f[tuple(sl_lo)] = lo * (1 - w) + hi * w
            f[tuple(sl_hi)] = hi * (1 - w) + lo * w
    return f


def _grid(dim):
    """返回归一化坐标网格 X, Y, Z（形状都是 (dim,dim,dim)，范围约 [-1,1]）。
    注意 meshgrid 用 indexing='ij' 且顺序 (Z,Y,X)，以匹配 [z,y,x] 索引。"""
    lin = (np.arange(dim) + 0.5) / dim * 2.0 - 1.0     # 体素中心，避免落在边界
    Z, Y, X = np.meshgrid(lin, lin, lin, indexing='ij')
    return X, Y, Z


def _stack(vx, vy, vz):
    return np.stack([vx, vy, vz], axis=-1).astype(np.float32)


# ---------------------------------------------------------------- 各种配方

def make_zero(dim=16):
    """全零场（无风），等价于官方基准 80 80 80。"""
    z = np.zeros((dim, dim, dim), np.float32)
    return _stack(z, z, z)


def make_uniform(dim=16, direction=(0.0, 1.0, 0.0), strength=1.0):
    """均匀风：整个空间朝同一方向。direction 会被归一化。"""
    d = np.array(direction, np.float32)
    n = np.linalg.norm(d)
    d = (d / n * strength) if n > 1e-9 else d
    o = np.ones((dim, dim, dim), np.float32)
    return _stack(o * d[0], o * d[1], o * d[2])


def make_vortex(dim=16, axis='Y', strength=0.3, swirl=1.0, inward=-0.2):
    """
    绕轴漩涡 / 龙卷。
      axis    旋转轴 'X'/'Y'/'Z'
      swirl   切向旋转强度（转多快）
      inward  向心(<0 收束) / 离心(>0 扩散)
      strength 沿轴方向的分量（上升/下沉气流）

    ★重要(游戏实测确认)：MHW游戏的坐标约定与数学惯例差一个轴翻转。
    数学"标准"的切向 (-a2, a1) 在游戏里会变成双曲摊开、不转圈！
    游戏里真正转圈的是 (+a2, a1) 这种符号(实测spin_B)。
    所以这里切向用 t1=+a2/r，与游戏坐标一致，导出的漩涡进游戏直接转。
    """
    X, Y, Z = _grid(dim)
    if axis == 'Y':   a1, a2, ax = X, Z, Y
    elif axis == 'X': a1, a2, ax = Y, Z, X
    else:             a1, a2, ax = X, Y, Z
    r = np.sqrt(a1**2 + a2**2) + 1e-6
    t1, t2 = a2 / r, a1 / r           # 切向（游戏正确符号,实测转圈; swirl取负=反向）
    r1, r2 = a1 / r, a2 / r           # 径向
    c1 = t1 * swirl + r1 * inward
    c2 = t2 * swirl + r2 * inward
    axv = np.ones_like(ax) * strength
    if axis == 'Y':   return _stack(c1, axv, c2)
    elif axis == 'X': return _stack(axv, c1, c2)
    else:             return _stack(c1, c2, axv)


def make_radial(dim=16, strength=1.0):
    """径向：从中心向外爆发(strength>0)或向内吸入(strength<0)。"""
    X, Y, Z = _grid(dim)
    r = np.sqrt(X**2 + Y**2 + Z**2) + 1e-6
    return _stack(X / r * strength, Y / r * strength, Z / r * strength)


def make_curl_noise(dim=16, scale=2.5, strength=1.0, seed=7):
    """
    旋度噪声：无散度湍流，最像真实烟雾/流体，粒子不会堆积。
    做法：构造随机势场，取旋度(∇×P)。scale 越大湍流越细碎。
    """
    rng = np.random.default_rng(int(seed))
    X, Y, Z = _grid(dim)

    def potential():
        p = np.zeros((dim, dim, dim), np.float32)
        for _ in range(4):
            f = rng.uniform(0.5, scale, 3)
            ph = rng.uniform(0, 2 * np.pi, 3)
            a = rng.uniform(0.5, 1.0)
            p += a * np.sin(f[0]*np.pi*X + ph[0]) \
                   * np.cos(f[1]*np.pi*Y + ph[1]) \
                   * np.sin(f[2]*np.pi*Z + ph[2])
        return p

    Px, Py, Pz = potential(), potential(), potential()
    vx = np.gradient(Pz, axis=1) - np.gradient(Py, axis=0)
    vy = np.gradient(Px, axis=0) - np.gradient(Pz, axis=2)
    vz = np.gradient(Py, axis=2) - np.gradient(Px, axis=1)
    m = np.max(np.sqrt(vx**2 + vy**2 + vz**2)) + 1e-9
    return _stack(vx / m * strength, vy / m * strength, vz / m * strength)


def make_turbulence(dim=16, scale=3.0, strength=0.6, seed=3):
    """
    通用湍流：多层正弦噪声（fBm 风格），比 curl 更"乱"，像官方 turbulance。
    """
    rng = np.random.default_rng(int(seed))
    X, Y, Z = _grid(dim)
    vx = np.zeros((dim,)*3, np.float32); vy = vx.copy(); vz = vx.copy()
    amp = 1.0
    freq = scale
    for _ in range(4):
        for comp, arr in enumerate((vx, vy, vz)):
            f = rng.uniform(freq*0.7, freq*1.3, 3)
            ph = rng.uniform(0, 2*np.pi, 3)
            arr += amp * np.sin(f[0]*np.pi*X+ph[0]) \
                       * np.sin(f[1]*np.pi*Y+ph[1]) \
                       * np.sin(f[2]*np.pi*Z+ph[2])
        amp *= 0.5
        freq *= 2.0
    m = np.max(np.sqrt(vx**2+vy**2+vz**2)) + 1e-9
    return _stack(vx/m*strength, vy/m*strength, vz/m*strength)


def make_swirl_noise_confined(dim=16, scale=2.5, strength=1.0, pull=0.4, seed=5):
    """
    '波浪紊流'场：旋度噪声(自然乱飘) + 向心回拉(pull)。
    粒子会像水面波浪一样各自乱飘，飘远了被拉回中心，形成'飘出去又回来'的循环。
    适合刀鞘那种漂浮往复效果。pull 越大回拉越强、粒子越聚拢。
    """
    noise = make_curl_noise(dim, scale=scale, strength=1.0, seed=seed)
    X, Y, Z = _grid(dim)
    r = np.sqrt(X**2 + Y**2 + Z**2) + 1e-6
    # 向心分量（指向中心）
    inward = np.stack([-X/r, -Y/r, -Z/r], -1)
    v = noise * strength + inward * pull
    m = np.max(np.linalg.norm(v, axis=3)) + 1e-9
    return (v / m).astype(np.float32)


def make_breathing_radial(dim=16, strength=1.0, shell=0.5):
    """
    '呼吸'径向场：从一个球壳向外的径向方向场。
    配合 efx 里 forceMultiplier 随时间正负交替，即可做整体推出去/吸回来的呼吸效果。
    tfa 只存方向；'往复'由 efx 力度动画或本插件的往复驱动实现。
    shell: 球壳半径，粒子主要在这个半径附近被推动。
    """
    X, Y, Z = _grid(dim)
    r = np.sqrt(X**2 + Y**2 + Z**2) + 1e-6
    dirv = np.stack([X/r, Y/r, Z/r], -1)   # 单位径向
    # 让靠近 shell 半径的地方力最强（高斯环）
    w = np.exp(-((r - shell) ** 2) / (2 * (0.25 ** 2)))[..., None]
    v = dirv * w * strength
    m = np.max(np.linalg.norm(v, axis=3)) + 1e-9
    return (v / m).astype(np.float32)


def make_from_curve(dim=16, points=None, radius=0.35, strength=1.0, falloff=2.0):
    """
    沿样条线的流场：给一串世界坐标控制点(范围[-1,1])，让附近体素朝
    "下一段切线方向"流动，离曲线越远越弱。用来做粒子沿路径走的效果。
    """
    if points is None:
        t = np.linspace(0, 1, 40)
        points = np.stack([np.cos(t*6)*0.6, t*1.6-0.8, np.sin(t*6)*0.6], axis=1)
    pts = np.asarray(points, np.float32)
    if len(pts) < 2:
        return make_zero(dim)
    seg = pts[1:] - pts[:-1]
    tang = seg / (np.linalg.norm(seg, axis=1, keepdims=True) + 1e-9)
    mid = (pts[1:] + pts[:-1]) * 0.5

    X, Y, Z = _grid(dim)
    P = np.stack([X, Y, Z], axis=-1)
    vx = np.zeros((dim,)*3, np.float32); vy = vx.copy(); vz = vx.copy()
    wsum = np.zeros((dim,)*3, np.float32)
    for m_, tg in zip(mid, tang):
        d = np.linalg.norm(P - m_, axis=-1)
        w = np.clip(1.0 - (d / radius), 0, 1) ** falloff
        vx += w * tg[0]; vy += w * tg[1]; vz += w * tg[2]
        wsum += w
    nz = wsum > 1e-6
    for arr in (vx, vy, vz):
        arr[nz] /= wsum[nz]
    m = np.max(np.sqrt(vx**2+vy**2+vz**2)) + 1e-9
    return _stack(vx/m*strength, vy/m*strength, vz/m*strength)


def preset_path(name, samples=80):
    """返回一批世界坐标控制点(范围约[-0.85,0.85])，用于 make_from_curve。"""
    t = np.linspace(0, 1, samples)
    tau = t * 2 * np.pi
    z0 = np.zeros_like(t)
    if name == 'LINE':               # 直线（沿 Y 上升）
        return np.stack([z0, t*1.7-0.85, z0], axis=1)
    if name == 'CIRCLE':             # 水平圆环（XZ 平面）
        return np.stack([np.cos(tau)*0.75, z0, np.sin(tau)*0.75], axis=1)
    if name == 'SPIRAL':             # 上升螺旋
        return np.stack([np.cos(tau*2)*0.7, t*1.6-0.8, np.sin(tau*2)*0.7], axis=1)
    if name == 'HELIX_TALL':         # 更密的高螺旋
        return np.stack([np.cos(tau*4)*0.6, t*1.7-0.85, np.sin(tau*4)*0.6], axis=1)
    if name == 'S_CURVE':            # S 形
        return np.stack([np.sin(tau)*0.6, t*1.7-0.85, z0], axis=1)
    if name == 'FIGURE8':            # 8 字 (lemniscate, 立体)
        return np.stack([0.75*np.sin(tau), 0.25*np.sin(2*tau), 0.75*np.sin(tau)*np.cos(tau)], axis=1)
    if name == 'WAVE':               # 波浪前进
        return np.stack([t*1.7-0.85, np.sin(tau*2)*0.5, np.cos(tau*2)*0.2], axis=1)
    if name == 'TORUS_KNOT':         # 环面结（复杂缠绕）
        p, q = 2, 3
        return np.stack([np.cos(p*tau)*(0.5+0.25*np.cos(q*tau)),
                         np.sin(q*tau)*0.25,
                         np.sin(p*tau)*(0.5+0.25*np.cos(q*tau))], axis=1)
    # 默认螺旋
    return np.stack([np.cos(tau*3)*0.6, t*1.6-0.8, np.sin(tau*3)*0.6], axis=1)


def make_from_preset(dim=16, preset='SPIRAL', radius=0.35, strength=1.0):
    """按预设轨迹名生成沿曲线流动的场。"""
    return make_from_curve(dim, points=preset_path(preset), radius=radius, strength=strength)


# 供插件按类型分发
GENERATORS = {
    'ZERO':      make_zero,
    'UNIFORM':   make_uniform,
    'VORTEX':    make_vortex,
    'RADIAL':    make_radial,
    'CURLNOISE': make_curl_noise,
    'TURBULENCE':make_turbulence,
    'CURVE':     make_from_curve,
}
