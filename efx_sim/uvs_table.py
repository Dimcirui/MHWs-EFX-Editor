# -*- coding: utf-8 -*-
"""
efx_sim/uvs_table.py —— 序列帧表（`.uvs` 的内容，由宿主喂进来）

`UVSequence` 属性里只有**游戏内部路径**（`UVSPath`），真正的帧矩形在那个 `.uvs` 文件里。
核心层不读盘、不调 EfxBridge，所以帧表由胶水层解析好之后通过 `SimResources` 注入——
这条和"核心零 bpy、能脱离 Blender 单测"是同一个约束。

`.uvs` 的结构（`uvsdump` 的 JSON，和 `blender_efx_re/uvs_model.py` 一一对应）
---------------------------------------------------------------------------
    textures[]              贴图的游戏内部路径
    sequences[].patterns[]  每帧一个 UV 矩形 (left, top, right, bottom) + textureIndex

实测样本 `11_cm_fire_000.uvs`：9 张贴图 / 9 条序列 × 64 帧，16×4 的规整网格
（0.0625 = 1/16，0.25 = 1/4）。

⚠ **v 轴方向**：`.uvs` 里的矩形是 **v 向下**（top < bottom，图像坐标系），Blender/OpenGL
的 UV 是 v 向上。翻转是**胶水层**的事（`uvs_image_editor.py` 画叠加框时同样翻），核心层
原样保留文件里的值，不替下游做决定。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""


class Frame(object):
    """一帧：UV 矩形 + 用哪张贴图。`left/top/right/bottom` 原样来自文件（v 向下）。"""

    __slots__ = ("left", "top", "right", "bottom", "texture_index")

    def __init__(self, left, top, right, bottom, texture_index=0):
        self.left = float(left)
        self.top = float(top)
        self.right = float(right)
        self.bottom = float(bottom)
        self.texture_index = int(texture_index)

    def as_rect(self):
        return (self.left, self.top, self.right, self.bottom)

    def __repr__(self):
        return ("<Frame (%.4f,%.4f)-(%.4f,%.4f) tex=%d>"
                % (self.left, self.top, self.right, self.bottom, self.texture_index))


class SimResources(object):
    """一个 entry 用到的外部资源。**恒非 None**——behavior 不必到处判空。

    `sequences`：序列下标 -> `[Frame, ...]`
    `texture_keys`：贴图下标 -> 一个**字符串标识**，核心层不解释它，原样写进
    `RenderItem.tex_key` 交给胶水层（那边拿它去查已经加载好的 `bpy.types.Image`）。
    """

    __slots__ = ("sequences", "texture_keys", "source")

    def __init__(self, sequences=None, texture_keys=None, source=""):
        self.sequences = dict(sequences or {})
        self.texture_keys = list(texture_keys or ())
        #: 这份帧表是从哪来的（`.uvs` 的路径），给 note 用
        self.source = source

    @property
    def empty(self):
        return not self.sequences

    def frames(self, sequence_index):
        """某条序列的帧列表；没有这条序列就返回 `None`（**不静默退回第 0 条**）。"""
        return self.sequences.get(int(sequence_index))

    def texture_key(self, texture_index):
        idx = int(texture_index)
        if 0 <= idx < len(self.texture_keys):
            return self.texture_keys[idx]
        return None

    def __repr__(self):
        return ("<SimResources %d 条序列 %d 张贴图 %s>"
                % (len(self.sequences), len(self.texture_keys), self.source))


def from_uvs_dict(data, texture_keys=None, source=""):
    """`uvsdump` 的 JSON dict -> `SimResources`。

    `texture_keys` 不给就用文件里的贴图路径当标识——胶水层那边正好也按路径缓存已加载的图。
    """
    sequences = {}
    for i, seq in enumerate(data.get("sequences") or ()):
        frames = []
        for pat in seq.get("patterns") or ():
            frames.append(Frame(pat.get("left", 0.0), pat.get("top", 0.0),
                                pat.get("right", 1.0), pat.get("bottom", 1.0),
                                pat.get("textureIndex", 0)))
        sequences[i] = frames
    if texture_keys is None:
        texture_keys = [t.get("path") or "" for t in (data.get("textures") or ())]
    return SimResources(sequences, texture_keys, source)
