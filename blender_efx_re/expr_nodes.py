# -*- coding: utf-8 -*-
"""
blender_efx_re/expr_nodes.py —— Expression 公式的**节点视口**编辑

属性面板里那套缩进行视图（`expr_edit.draw_nodes()`）保留着，但它有两个改不掉的毛病：
面板宽度不够时每个参数槽位要单独占一行再缩进一级，一条 4 层的公式摊成一道往右下滑的
楼梯；而且纵向只展开"根 → 选中槽位"这一条链，兄弟分支全折叠着，屏幕上永远看不到整棵树。
节点图没有宽度天花板、可缩放平移，整棵树一眼看完——这是换过来的唯一理由。

## 三条硬约束（和 `expr_edit.py` 顶部那四条同源，别在这一层破例）

1. **公式文本仍然是唯一权威。** 节点图是 `EFXExpressionCurveItem.formula` 的视图，
   导出只读 `formula`（`io_tree._export_expression_attribute()`）。这一层最坏的结果
   被限制成"吐出一段不同的文本"——桥接解析器会拒绝非法文本，字节门禁会抓住合法但不同的
   文本。没有任何路径能绕过文本去改二进制。
2. **树的变换逻辑不往这儿挪。** 行 ↔ 文本仍然全在 `efx_sim/expr.py`（零 bpy、单测覆盖），
   插槽的显示顺序走 `efx_sim/expr_text.display_arg_order()`。这一层只做四件事：
   行 → 节点图、节点图 → 行、自动布局、画。
3. **插槽顺序按规范记法摆。** vendor 给六个二元操作码起的名字一个都不对，而且其中四个
   操作数顺序还是反的（`Min(a, b)` 实为 `b - a`）。节点上照 vendor 顺序摆插槽 = 把错的
   读法画成图，比文本误导更甚。顺序和名字都取规范侧，**表只有一张**，在 `expr_text` 里。

## 为什么叶子不是节点，是插槽上的内嵌控件

常量和变量做成独立节点的话，`Lerp(Clamp(TIMER, 120, 0), 190, -30)` 要画 9 个节点、
8 根连线，屏幕上全是"数字方块"。做成未连线插槽上的内嵌控件（同 Blender 自己的 Math
节点）之后同一条公式只剩 2 个节点。

这个收益不依赖语料统计，是树的性质：内嵌之后画出来的节点数 = **arity>0 的节点数**，
而任何每个内部节点至少 2 个子节点的树里叶子都比内部节点多——所以内嵌叶子至少砍掉一半
节点。配合语料实测的总节点数（抽样 1044 个官方文件 898 条不同公式，节点数中位 7、
最大 25，见 `expr_edit.py` 顶部），画出来的规模落在个位数。⚠ **"调用节点数中位 3"
这类更细的数字本仓没有实测过**，别引用，要用先跑一遍全语料统计。

插槽没连线时它自己就是一个叶子（常量或变量），连上线就被子树顶替，
断开又退回原来的叶子值——这也正好对上 `expr.convert_node()` 的"换成常量/变量就丢掉整棵
子树"语义。

## 一棵树，不是每条公式一个数据块

`bpy.types.NodeTree` 是 ID 数据块。每条公式建一个的话，一个中等大小的 .efx 能造出上百个
数据块，跟着 .blend 存盘、还要处理孤立数据清理和重名。这里只注册**一个**共享数据块
（`_TREE_NAME`），它镜像"当前活动的那条公式"，换曲线就整个重建。节点位置因此不持久——
但位置本来也留不住：公式文本一改就要重新布局（文本是权威，图是派生量）。

## 多连和成环

vendor 的表达式是**树**，不是 DAG：`from_rows()` 要求每个参数槽位恰好一棵子树。所以
一个节点的输出接到两个地方是**无法表达**的形状。这里的做法是**拒绝并说明**，不是悄悄
复制一份子树——复制会让图上画的和存下去的不是一回事，正是铁律 #1 要防的那类"看起来
没问题"。成环同理。两种情况都由 `read_graph()` 抛 `ExprError`，同步层报给用户并把图按
`formula` 重建一遍（那根连线随之消失），公式本身一个字符都不动。
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty,
    StringProperty,
)
from bpy.types import Menu, Node, NodeSocket, NodeTree, Operator, Panel, PropertyGroup

from . import expr_edit, model
from .i18n import T

try:
    from ..efx_sim import expr as _expr, expr_text as _expr_text, plot as _plot
except ImportError:  # pragma: no cover - 只在门禁/单测的顶层包布局下走到
    from efx_sim import expr as _expr, expr_text as _expr_text, plot as _plot


#: 共享节点树数据块的名字。**固定一个**，理由见模块 docstring。
_TREE_NAME = "EFX Expression"

#: 一元负号在 `call_name` 里的占位。`efx_sim` 那边它是独立的 `KIND_NEG`，不是调用；
#: 节点这一层不值得为一个 1 参节点再开一个类，用一个不可能和 vendor 字面量撞车的
#: 哨兵值（vendor 的名字全是标识符，不含空格）区分。
_NEG_CALL = "- neg -"

_TREE_ID = "EFX_RE_ExprNodeTree"
_SOCKET_ID = "EFX_RE_ExprSocket"
_CALL_NODE_ID = "EFX_RE_ExprCallNode"
_OUTPUT_NODE_ID = "EFX_RE_ExprOutputNode"


# ---------------------------------------------------------------------------
# 同步闸门
#
# 三个方向互相是对方的触发源（改公式 -> 重建图；改图 -> 重拼公式 -> 又触发重建图），
# 不挡一下会自己打自己。和 `expr_edit._SUSPEND` 同一套写法：用计数器不用布尔，嵌套调用
# 也要能正确恢复。
# ---------------------------------------------------------------------------
_SUSPEND = 0

#: `NodeTree.update()` 里**不能**直接改 ID 数据（Blender 在这个回调里的数据状态是半更新的，
#: 实测写 `formula` 会把整个节点编辑器的重绘打乱）。所以那里只置一个标记，真正的
#: 行 -> 文本同步延后一帧由 timer 跑。
_PENDING_SYNC = False

#: 最近一次同步失败的原因（多连/成环/行结构坏了）。画在节点编辑器侧栏上——
#: 算子报的 `self.report()` 在节点编辑器里一闪而过，用户经常没看见就以为改生效了。
_LAST_ERROR = ""


class _Suspended(object):
    def __enter__(self):
        global _SUSPEND
        _SUSPEND += 1
        return self

    def __exit__(self, *exc):
        global _SUSPEND
        _SUSPEND -= 1
        return False


# ---------------------------------------------------------------------------
# 绑定：这棵图当前镜像哪条公式
# ---------------------------------------------------------------------------

def _bound_curve(tree):
    """节点树 -> 它镜像的那条 `EFXExpressionCurveItem`（绑丢了返回 None）。

    存对象名 + 曲线下标而不是 `PointerProperty`：`EFXExpressionCurveItem` 是
    `CollectionProperty` 的元素，Blender 不允许指向它。名字失效（对象被删/改名）时
    这里返回 None，侧栏会退回"没有绑定公式"的提示，不会画一棵指向空气的图。
    """
    if tree is None or not tree.efx_owner_object:
        return None
    obj = bpy.data.objects.get(tree.efx_owner_object)
    if obj is None:
        return None
    curves = getattr(obj, "efx_expression_curves", None)
    if not curves or not (0 <= tree.efx_curve_index < len(curves)):
        return None
    return curves[tree.efx_curve_index]


def get_tree(create=False):
    """共享的节点树数据块。`create=False` 时不存在就返回 None——绝大多数调用点
    （面板重绘、曲线切换回调）不该因为看一眼就凭空造一个数据块出来。"""
    tree = bpy.data.node_groups.get(_TREE_NAME)
    if tree is not None and tree.bl_idname != _TREE_ID:
        # 同名的别的类型的节点组（用户自己建的）——不抢这个名字
        return None
    if tree is None and create:
        tree = bpy.data.node_groups.new(_TREE_NAME, _TREE_ID)
        # 不给 fake user：这是派生量，不该把一棵会被随时重建的图钉在 .blend 里
        tree.use_fake_user = False
    return tree


def bind(tree, obj, curve_index):
    tree.efx_owner_object = obj.name if obj is not None else ""
    tree.efx_curve_index = int(curve_index)


# ---------------------------------------------------------------------------
# 插槽
# ---------------------------------------------------------------------------

def _socket_leaf_changed(self, context):
    """插槽上的叶子值改了 -> 重拼公式。未连线时这个插槽**就是**一个常量/变量叶子。"""
    if _SUSPEND:
        return
    _request_sync()


class EFX_RE_ExprSocket(NodeSocket):
    """一个参数插槽。**没连线时它自己就是叶子**（常量或变量），连上线就被子树顶替。

    输出插槽复用同一个类（只画名字），省一个类；`is_output` 已经足够区分画法。
    """

    bl_idname = _SOCKET_ID
    bl_label = "Value"

    leaf_kind: EnumProperty(
        name="Kind",
        items=[
            ("CONST", "Constant", "浮点字面量"),
            ("VAR", "Variable", "具名参数或内置外部变量"),
        ],
        default="CONST",
        update=_socket_leaf_changed,
    )
    #: 同 `EFXExpressionNodeItem.value`：precision=4，理由（全语料 9066 个常量最多用到
    #: 4 位小数）在那边的注释里，不重复。
    value: FloatProperty(name="Value", precision=4, update=_socket_leaf_changed)
    var_name: StringProperty(name="Variable", default=_expr.DEFAULT_VARIABLE,
                             update=_socket_leaf_changed)
    #: 这个插槽和曲线目标字段同单位（角度）——由 `_same_unit_mask()` 在建图时算好写进来，
    #: 画的时候据此换一个 `subtype="ANGLE"` 的控件。**不是**"角度曲线里每个常量都换算"，
    #: 理由见 `efx_sim/expr.py::propagate_same_unit_as_root()`。
    show_degrees: BoolProperty(default=False)
    degrees_value: FloatProperty(
        name="Value", subtype="ANGLE",
        get=lambda self: self.value,
        set=lambda self, v: setattr(self, "value", v),
    )

    def draw(self, context, layout, node, text):
        if self.is_output:
            layout.label(text=text, translate=False)
            return
        if self.is_linked:
            layout.label(text=text, translate=False)
            return
        row = layout.row(align=True)
        if text:
            sub = row.row()
            sub.ui_units_x = 2.4
            sub.label(text=text, translate=False)
        if self.leaf_kind == "CONST":
            row.prop(self, "degrees_value" if self.show_degrees else "value", text="")
        else:
            # prop_search 而不是带 items 回调的动态 EnumProperty：后者的取值没法从 Python
            # 传给算子（`enum "Min" not found in ()`，见 `expr_edit.py` 约束 #4），
            # 门禁就测不到用户真正点的那条路径。prop_search 既能搜又能直接打，
            # 而且打一个表里没有的名字是**允许**的——`ext:<hash>` 这类占位本来就不在表里。
            row.prop_search(self, "var_name", context.scene, "efx_expr_var_names",
                            text="", icon="NONE")
        row.prop(self, "leaf_kind", text="", icon_only=True,
                 emboss=False, expand=False)

    def draw_color(self, context, node):
        # 连了线的插槽走深灰（结构），未连线的叶子走浅色（可直接改的值）——
        # 颜色只区分"这里是子树还是一个值"，不编码语义。
        if self.is_output or self.is_linked:
            return (0.40, 0.55, 0.75, 1.0)
        return (0.55, 0.55, 0.55, 1.0)


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

def _call_changed(self, context):
    if _SUSPEND:
        return
    self.rebuild_sockets()
    _request_sync()


def _socket_labels(call_name, arity):
    """按**显示顺序**给出 arity 个插槽的标签。

    中缀运算符一律 `A` / `B`：规范记法下 `A ÷ B` 已经把顺序说清楚了，再挂
    `subtract`/`from` 这种 vendor 侧的角色名反而制造第二套读法。函数走
    `expr.CALL_ARG_ROLES`（那张表只收语义已定的，见它自己的注释），按显示顺序重排。
    """
    if call_name == _NEG_CALL:
        return ["x"]
    if call_name in _expr.BINARY_OPERATORS:
        return ["A", "B"]
    roles = _expr.CALL_ARG_ROLES.get(call_name)
    order = _expr_text.display_arg_order(call_name, arity)
    if not roles or len(roles) != arity:
        return [str(i + 1) for i in range(arity)]
    return [roles[order[i]] for i in range(arity)]


def node_header(call_name):
    """节点标题栏的文字：**规范记法**的名字 + vendor 字面量。

    vendor 字面量要一起显示，否则用户对不上"图里这个 `Sin` 就是公式文本里的 `Unary0`"
    ——文本框和节点图是同一条公式的两个视图，两边的名字必须能互相认出来。
    """
    if call_name == _NEG_CALL:
        return "Negate  ( -x )"
    if call_name in _expr.BINARY_OPERATORS:
        canon = _expr.CANONICAL_OPERATORS.get(call_name)
        symbol = canon[0] if canon else call_name
        return "%s        [%s]" % (symbol, call_name)
    display = _expr.call_display_name(call_name)
    if display != call_name:
        return "%s  [%s]" % (display, call_name)
    return call_name


class EFX_RE_ExprCallNode(Node):
    """一个运算符 / 函数 / 一元负号。**一个类打通所有调用**，不是每个函数一个类。

    参数个数、置信度、规范名全部现查 `efx_sim/expr.py`（`call_arity()` /
    `call_confidence()` / `call_display_name()`），所以 vendor 升级加了新操作码时
    这一层不用动——一个类一份枚举的话，那张枚举就是第二份真相，迟早和 `CALL_SIGNATURES`
    漂开。
    """

    bl_idname = _CALL_NODE_ID
    bl_label = "Expression"
    bl_icon = "DRIVER"

    call_name: StringProperty(name="Call", default="+", update=_call_changed)
    #: 建图时写进来的行下标，用来取"这个节点在当前帧的值"。**只在两次重建之间有效**，
    #: 不是持久标识——任何结构变化都会让它失效，所以读之前必须确认图是刚建好的。
    row_index: IntProperty(default=-1)

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == _TREE_ID

    def init(self, context):
        self.outputs.new(_SOCKET_ID, "")
        self.rebuild_sockets()

    def rebuild_sockets(self):
        """按当前 `call_name` 的参数个数重建输入插槽。

        **按位置保留已有内容**：换成参数更多的函数时原来的连线/叶子值留在原位，
        多出来的补常量 0；参数变少时多的丢掉。这和 `expr.convert_node()` 的子节点
        去留规则是同一条（"多的丢、少的补常量 0"），两边必须一致，否则同一个操作
        在面板里和在节点图里结果不同。
        """
        if self.call_name == _NEG_CALL:
            arity = 1
        else:
            arity = _expr.call_arity(self.call_name)
            if arity is None:
                # 不认识的名字：保持现有插槽数，不装作知道它要几个参数
                arity = len(self.inputs)
        labels = _socket_labels(self.call_name, arity)
        with _Suspended():
            while len(self.inputs) > arity:
                self.inputs.remove(self.inputs[-1])
            while len(self.inputs) < arity:
                self.inputs.new(_SOCKET_ID, "")
            for socket, label in zip(self.inputs, labels):
                socket.name = label

    def draw_label(self):
        return node_header(self.call_name)

    def draw_buttons(self, context, layout):
        confidence = _expr.call_confidence(self.call_name)
        # 换函数的菜单。`context_pointer_set` 把"点的是哪个节点"带进菜单的 draw，
        # 不依赖"点一下控件会不会顺带把节点设成活动的"这个没保证的行为。
        layout.context_pointer_set("efx_expr_node", self)
        layout.menu(EFX_RE_MT_expr_node_call.bl_idname, text=node_header(self.call_name))

        semantics = _expr.call_semantics(self.call_name)
        if semantics:
            # 真实语义。**必须显示**：这些名字全是错的，用户看到 `Min` 不会知道它算 `b - a`。
            sub = layout.row()
            sub.active = False
            sub.label(text=semantics, translate=False)
        if confidence != _expr.CONFIDENCE_CONFIRMED:
            # 置信度如实显示，不把猜测画成确定
            layout.label(text=T(_CONFIDENCE_LABEL[confidence]),
                         icon=_CONFIDENCE_ICON[confidence], translate=False)

        value = _node_value(context, self)
        if value is not None:
            row = layout.row()
            row.active = False
            row.label(text="= %s" % _plot.format_tick(value), translate=False)


class EFX_RE_ExprOutputNode(Node):
    """公式的根。它的输入接的那棵子树就是整条公式——**图上别的游离节点不参与**
    （和 Blender 自己的材质节点一致：没接到输出的节点只是放在画布上，不影响结果）。"""

    bl_idname = _OUTPUT_NODE_ID
    bl_label = "Field"
    bl_icon = "EXPORT"

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == _TREE_ID

    def init(self, context):
        self.inputs.new(_SOCKET_ID, "")

    def draw_buttons(self, context, layout):
        curve = _bound_curve(self.id_data)
        if curve is None:
            layout.label(text=T("exprnode.unbound"), icon="ERROR", translate=False)
            return
        layout.label(text=curve.bit_name or ("bit %d" % curve.bit_index), translate=False)
        if curve.second_branch:
            # `a | b` 的第二支：语义没证实，不给结构化编辑，但要让用户知道它在、没被丢掉
            box = layout.box()
            box.label(text=T("expr.second_branch"), icon="INFO", translate=False)
            box.label(text=curve.second_branch, translate=False)


_CONFIDENCE_LABEL = {
    _expr.CONFIDENCE_CONFIRMED: "expr.conf.confirmed",
    _expr.CONFIDENCE_CORPUS: "expr.conf.corpus",
    _expr.CONFIDENCE_UNDECIDED: "expr.conf.undecided",
    _expr.CONFIDENCE_UNKNOWN: "expr.conf.unknown",
}

_CONFIDENCE_ICON = {
    _expr.CONFIDENCE_CONFIRMED: "NONE",
    _expr.CONFIDENCE_CORPUS: "INFO",
    _expr.CONFIDENCE_UNDECIDED: "QUESTION",
    _expr.CONFIDENCE_UNKNOWN: "ERROR",
}


class EFX_RE_ExprNodeTree(NodeTree):
    """共享的公式画布。一个数据块镜像"当前活动的那条公式"，理由见模块 docstring。"""

    bl_idname = _TREE_ID
    bl_label = "EFX Expression"
    bl_icon = "DRIVER"

    efx_owner_object: StringProperty(name="Owner")
    efx_curve_index: IntProperty(name="Curve", default=-1)

    def update(self):
        """Blender 在连线拓扑变化时调用。**这里只置标记**——这个回调里的数据状态是
        半更新的，直接写 `formula`（一个 ID 上的字符串属性）实测会把节点编辑器的重绘
        打乱。真正的同步延后一帧由 timer 跑。"""
        if _SUSPEND:
            return
        _request_sync()


# ---------------------------------------------------------------------------
# 图 -> 行（读回）
# ---------------------------------------------------------------------------

def _leaf_row(socket):
    if socket.leaf_kind == "VAR":
        name = (socket.var_name or "").strip()
        if not name:
            raise _expr.ExprError("有一个变量插槽的名字是空的")
        # 插槽上打的是名字（可能是 `EM_SPEED` 这种我们自己解出、vendor 表里没有的名字），
        # 存回行数据前换成 vendor 自己的 `ToString()` 会用的占位字面量（`ext:302732036`，
        # vendor 不认识这个哈希，读文件时给的就是这个占位符）——两个编辑器（这里和
        # `expr_edit.py` 的文本框）必须对同一份底层数据用同一套转换，见
        # `efx_sim/expr.py::vendor_var_name()` 的注释。
        name = _expr.vendor_var_name(name)
        return {"kind": _expr.KIND_VAR, "depth": 0, "arity": 0,
                "name": name, "value": 0.0}
    return {"kind": _expr.KIND_CONST, "depth": 0, "arity": 0,
            "name": "", "value": float(socket.value)}


def _source_node(socket):
    """插槽连到的上游节点（没连线返回 None）。`is_linked` 为真但连线无效
    （Blender 允许短暂存在的 muted/invalid 链接）时也当没连。"""
    for link in socket.links:
        if link.is_valid and not link.is_muted:
            return link.from_node
    return None


def _emit_socket(socket, rows, path, seen):
    node = _source_node(socket)
    if node is None:
        rows.append(_leaf_row(socket))
        return
    _emit_node(node, rows, path, seen)


def _emit_node(node, rows, path, seen):
    if node.bl_idname != _CALL_NODE_ID:
        raise _expr.ExprError("插槽接到了一个不能当值用的节点：%s" % node.name)
    if node.name in path:
        # 兜底。正常情况下走不到：Blender 自己会把制造环的那根连线标成
        # `is_valid == False`（实测），`_source_node()` 已经把它滤掉了。留着是因为
        # "上游哪天不再帮我们挡"和"这里静默产出一棵有环的行列表"代价差太远。
        raise _expr.ExprError("连线成环了（%s），表达式必须是一棵树" % node.name)
    if node.name in seen:
        # DAG 不是 vendor 能表达的形状。**不悄悄复制子树**——图上画的和存下去的
        # 会变成两回事，见模块 docstring。
        raise _expr.ExprError(
            "「%s」的输出接到了两个地方。表达式是一棵树，一个结果只能用在一处；"
            "要用两次就再放一个同样的节点。" % node_header(node.call_name))
    seen.add(node.name)
    path = path | {node.name}

    if node.call_name == _NEG_CALL:
        rows.append({"kind": _expr.KIND_NEG, "depth": 0, "arity": 1,
                     "name": "", "value": 0.0})
        _emit_socket(node.inputs[0], rows, path, seen)
        return

    arity = len(node.inputs)
    name = (node.call_name or "").strip()
    if not name:
        raise _expr.ExprError("有一个节点没有函数名")
    rows.append({"kind": _expr.KIND_CALL, "depth": 0, "arity": arity,
                 "name": name, "value": 0.0})
    # 插槽是按**显示顺序**摆的，行必须按 vendor 顺序发
    order = _expr_text.display_arg_order(name, arity)
    slots = [None] * arity
    for display_pos, vendor_pos in enumerate(order):
        slots[vendor_pos] = node.inputs[display_pos]
    for socket in slots:
        _emit_socket(socket, rows, path, seen)


def read_graph(tree):
    """节点图 -> `efx_sim.expr` 认的 dict 行。形状表达不了就抛 `ExprError`，
    **绝不返回一个凑出来的结构**（铁律 #1）。"""
    output = next((n for n in tree.nodes if n.bl_idname == _OUTPUT_NODE_ID), None)
    if output is None:
        raise _expr.ExprError("图里没有输出节点")
    rows = []
    _emit_socket(output.inputs[0], rows, frozenset(), set())
    return _expr.recompute_depths(rows)


# ---------------------------------------------------------------------------
# 行 -> 图（建图 + 自动布局）
# ---------------------------------------------------------------------------

_COL_WIDTH = 250.0
_SOCKET_HEIGHT = 30.0
_NODE_GAP = 40.0


def _apply_leaf(socket, row, degrees):
    with _Suspended():
        socket.show_degrees = bool(degrees)
        if row["kind"] == _expr.KIND_VAR:
            socket.leaf_kind = "VAR"
            # 反方向：行数据里的 vendor 字面量换成人看的名字再摆到插槽上,
            # 和 `_leaf_row()` 的转换互为逆操作。
            socket.var_name = _expr.display_var_name(row.get("name", "") or "")
        else:
            socket.leaf_kind = "CONST"
            socket.value = float(row.get("value", 0.0) or 0.0)


def _build_into(tree, rows, index, socket, same_unit):
    """把 `rows[index]` 这棵子树建进 `socket`，返回消费到的下一个行下标。"""
    row = rows[index]
    if int(row.get("arity", 0)) == 0:
        _apply_leaf(socket, row, same_unit[index] if index < len(same_unit) else False)
        return index + 1

    node = tree.nodes.new(_CALL_NODE_ID)
    with _Suspended():
        node.call_name = _NEG_CALL if row["kind"] == _expr.KIND_NEG else row["name"]
        node.row_index = index
        node.rebuild_sockets()
    tree.links.new(node.outputs[0], socket)

    arity = len(node.inputs)
    order = _expr_text.display_arg_order(node.call_name, arity)
    vendor_to_display = {v: d for d, v in enumerate(order)}
    cursor = index + 1
    for vendor_pos in range(arity):
        target = node.inputs[vendor_to_display.get(vendor_pos, vendor_pos)]
        cursor = _build_into(tree, rows, cursor, target, same_unit)
    return cursor


def _layout(node, depth, cursor):
    """自动布局：列按深度排（输出在最右），行按"子树的中心"对齐。

    位置不持久，每次重建都重算——公式文本一改整棵图就得重来，留住位置没有意义
    （而且会让"节点在哪"看起来像用户的数据，其实不是）。
    """
    child_centers = []
    for socket in node.inputs:
        source = _source_node(socket)
        if source is not None:
            child_centers.append(_layout(source, depth + 1, cursor))
        else:
            child_centers.append(cursor[0])
            cursor[0] -= _SOCKET_HEIGHT
    if child_centers:
        y = sum(child_centers) / len(child_centers)
    else:
        y = cursor[0]
        cursor[0] -= _SOCKET_HEIGHT
    cursor[0] -= _NODE_GAP
    node.location = (-depth * _COL_WIDTH, y)
    return y


def build_graph(tree, context=None):
    """`formula` -> 整张图。**全量重建，不做增量 diff**（同全量重算原则的路子）。"""
    global _LAST_ERROR
    curve = _bound_curve(tree)
    with _Suspended():
        tree.nodes.clear()
        output = tree.nodes.new(_OUTPUT_NODE_ID)
        output.location = (220.0, 0.0)
        if curve is None:
            return
        rows = expr_edit.read_rows(curve)
        if not rows:
            # 公式解析不了（`curve.formula_error` 非空）或者行还没建起来。
            # 只画一个空的输出节点——不画半棵树（整文件拒绝导入原则的同一条道理）。
            return
        same_unit = _same_unit_mask(context, curve, rows)
        _build_into(tree, rows, 0, output.inputs[0], same_unit)
        source = _source_node(output.inputs[0])
        if source is not None:
            _layout(source, 1, [0.0])
    _refresh_variable_names(context)
    _LAST_ERROR = ""


def _same_unit_mask(context, curve, rows):
    """哪些叶子槽位和曲线目标字段同单位（角度）。判据完全复用 `expr_edit`——
    同一个字段不该因为换了一个视图就换一套单位读法。拿不到 context 时全 False。"""
    if context is None:
        return [False] * len(rows)
    try:
        return expr_edit._same_unit_mask(context, curve, rows)
    except Exception:                                   # noqa: BLE001
        return [False] * len(rows)


# ---------------------------------------------------------------------------
# 当前帧读数
# ---------------------------------------------------------------------------

#: `(公式, 帧号) -> {行下标: 值}`。每个节点各算一遍的话一张 12 节点的图每次重绘要跑
#: 12 次完整求值，这里整张图共用一次。
_VALUE_CACHE = {}


def _node_value(context, node):
    tree = node.id_data
    curve = _bound_curve(tree)
    if curve is None or node.row_index < 0:
        return None
    frame = getattr(getattr(context, "scene", None), "frame_current", 0)
    key = (tree.name, curve.formula, frame)
    values = _VALUE_CACHE.get(key)
    if values is None:
        if len(_VALUE_CACHE) > 8:
            _VALUE_CACHE.clear()
        try:
            from . import expr_preview
            values = expr_preview.subtree_values(context, curve, expr_edit.read_rows(curve))
        except Exception:                               # noqa: BLE001
            values = {}
        _VALUE_CACHE[key] = values
    return values.get(node.row_index)


# ---------------------------------------------------------------------------
# 变量名补全表（给插槽的 prop_search 用）
# ---------------------------------------------------------------------------

class EFXExprVarName(PropertyGroup):
    """`Scene.efx_expr_var_names` 的元素。插槽的变量名走 `prop_search` 补全，
    需要一个真实存在的 CollectionProperty 当候选源。纯 UI 态，不参与导出。"""
    name: StringProperty()


def _refresh_variable_names(context):
    """内置外部变量（含猜测名、连名字都没有的占位哈希，`variable_picker_choices()`）
    + 当前文件的具名参数 -> 补全表。建图时刷一次就够：两份来源都只在导入/用户改参数表时变，
    而那两件事都会重建图。"""
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        scene = bpy.data.scenes[0] if bpy.data.scenes else None
    if scene is None:
        return
    names = _expr.variable_picker_choices()
    try:
        for name in expr_edit.file_parameter_names(context):
            if name not in names:
                names.append(name)
    except Exception:                                   # noqa: BLE001
        pass
    scene.efx_expr_var_names.clear()
    for name in names:
        scene.efx_expr_var_names.add().name = name


# ---------------------------------------------------------------------------
# 同步：图 -> 公式
# ---------------------------------------------------------------------------

def _request_sync():
    global _PENDING_SYNC
    if _PENDING_SYNC:
        return
    _PENDING_SYNC = True
    bpy.app.timers.register(_deferred_sync, first_interval=0)


def _deferred_sync():
    global _PENDING_SYNC
    _PENDING_SYNC = False
    try:
        sync_to_formula(bpy.context)
    except Exception as exc:                            # noqa: BLE001
        print(f"[MHWs EFX Editor] 节点图同步失败：{exc}")
    return None


def sync_to_formula(context, rebuild=True):
    """图 -> 行 -> `formula`。读不出合法的树就**只记错误、不动 `formula`**，
    并把图按现有 `formula` 重建一遍——那根非法连线随之消失，公式一个字符都没被碰过。"""
    global _LAST_ERROR
    tree = get_tree()
    curve = _bound_curve(tree)
    if tree is None or curve is None:
        return False
    try:
        rows = read_graph(tree)
    except _expr.ExprError as exc:
        _LAST_ERROR = str(exc)
        if rebuild:
            build_graph(tree, context)
            _LAST_ERROR = str(exc)      # build_graph 会清掉，这里再写回去
        return False
    _LAST_ERROR = ""
    with _Suspended():
        expr_edit.apply_rows(curve, rows)
    if rebuild:
        # 重建一遍：补齐（换函数补出来的常量 0）、重新布局、刷新 row_index。
        # `apply_rows` 已经把文本写定，这一步只动派生量。
        build_graph(tree, context)
    return True


def on_curve_rows_changed(curve):
    """属性面板那一侧改了公式/结构 -> 如果图正绑着这条曲线，跟着重建。
    由 `expr_edit` 在 `write_rows()` 末尾回调（两个视图共用一个 `formula`，
    改哪边另一边都要立刻跟上）。"""
    if _SUSPEND:
        return
    tree = get_tree()
    # ⚠ **`==` 不是 `is`**：`curves[i]` 每次访问都返回一个新的 Python 包装对象，
    # `is` 永远为假，图就永远跟不上面板的改动（实测踩过，门禁的"面板改了公式 ->
    # 节点图跟着重建"那条就是钉这个的）。`bpy_struct.__eq__` 比的是底层数据指针。
    if tree is None or _bound_curve(tree) != curve:
        return
    build_graph(tree, bpy.context)


# ---------------------------------------------------------------------------
# 菜单 / 算子
# ---------------------------------------------------------------------------

def _grouped_call_names():
    """运算符 + 函数，按置信度分组。复用 `expr_edit` 那一份，不另列一张表。"""
    return expr_edit._grouped_call_names()


class EFX_RE_MT_expr_node_call(Menu):
    """换掉一个节点的函数。列表和面板里那个函数菜单同源（同一份分组、同一套标签）。"""

    bl_idname = "EFX_RE_MT_expr_node_call"
    bl_label = "Function"

    def draw(self, context):
        layout = self.layout
        node = getattr(context, "efx_expr_node", None) or getattr(context, "active_node", None)
        node_name = node.name if node is not None else ""
        col = layout.column()
        op = col.operator(EFX_RE_OT_expr_node_set_call.bl_idname,
                          text=T("expr.wrap.negate"), translate=False)
        op.node_name = node_name
        op.call_name = _NEG_CALL
        for label_key, names in _grouped_call_names():
            col.separator()
            if label_key:
                col.label(text=T(label_key), translate=False)
            for name in names:
                op = col.operator(EFX_RE_OT_expr_node_set_call.bl_idname,
                                  text=expr_edit._call_label(name), translate=False,
                                  icon=_CONFIDENCE_ICON[_expr.call_confidence(name)])
                op.node_name = node_name
                op.call_name = name


class EFX_RE_OT_expr_node_set_call(Operator):
    bl_idname = "efx_re.expr_node_set_call"
    bl_label = "Set Function"
    bl_description = "把这个节点换成另一个运算符或函数，参数多的丢、少的补常量 0"
    bl_options = {"REGISTER", "UNDO"}

    node_name: StringProperty()
    call_name: StringProperty()

    def execute(self, context):
        tree = get_tree()
        node = tree.nodes.get(self.node_name) if tree is not None else None
        if node is None or node.bl_idname != _CALL_NODE_ID:
            self.report({"WARNING"}, "找不到这个节点")
            return {"CANCELLED"}
        node.call_name = self.call_name      # update 回调里重建插槽 + 排同步
        return {"FINISHED"}


class EFX_RE_MT_expr_node_add(Menu):
    """Shift+A 里挂的「EFX Expression」子菜单。按置信度分组，和函数菜单同源。"""

    bl_idname = "EFX_RE_MT_expr_node_add"
    bl_label = "EFX Expression"

    def draw(self, context):
        col = self.layout.column()
        op = col.operator(EFX_RE_OT_expr_node_add.bl_idname,
                          text=T("expr.wrap.negate"), translate=False)
        op.call_name = _NEG_CALL
        for label_key, names in _grouped_call_names():
            col.separator()
            if label_key:
                col.label(text=T(label_key), translate=False)
            for name in names:
                op = col.operator(EFX_RE_OT_expr_node_add.bl_idname,
                                  text=expr_edit._call_label(name), translate=False,
                                  icon=_CONFIDENCE_ICON[_expr.call_confidence(name)])
                op.call_name = name


class EFX_RE_OT_expr_node_add(Operator):
    """加一个游离节点。**不自己写自己的 `bl_description`** 会被 docstring 顶替，
    所以显式写一条（docs/PITFALLS.md #25）。"""

    bl_idname = "efx_re.expr_node_add"
    bl_label = "Add Expression Node"
    bl_description = "在光标处放一个新节点，接到别的插槽上才会进入公式"
    bl_options = {"REGISTER", "UNDO"}

    call_name: StringProperty()

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and getattr(space, "tree_type", "") == _TREE_ID

    def execute(self, context):
        tree = get_tree()
        if tree is None:
            return {"CANCELLED"}
        with _Suspended():
            for node in tree.nodes:
                node.select = False
            node = tree.nodes.new(_CALL_NODE_ID)
            node.call_name = self.call_name
            node.rebuild_sockets()
            node.select = True
            tree.nodes.active = node
            cursor = getattr(context.space_data, "cursor_location", None)
            if cursor is not None:
                node.location = cursor
        # 新节点还没接线，公式没变——不排同步，等用户连上线时 `update()` 自己会来
        bpy.ops.transform.translate("INVOKE_DEFAULT")
        return {"FINISHED"}


class EFX_RE_OT_expr_node_open(Operator):
    bl_idname = "efx_re.expr_node_open"
    bl_label = "Edit in Node Editor"
    bl_description = "把当前公式放进节点编辑器，整棵树一眼看完"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return (obj is not None and obj.get("~TYPE") == model.TYPE_ATTRIBUTE
                and len(getattr(obj, "efx_expression_curves", ())) > 0)

    def execute(self, context):
        obj = context.object
        tree = get_tree(create=True)
        bind(tree, obj, obj.efx_expression_curves_active_index)
        build_graph(tree, context)
        if not _show_in_editor(context, tree):
            # 没找到节点编辑器。**不替用户重排界面**——图已经建好了，说清楚怎么看到它
            # 比擅自劈掉半个视口讨人嫌得少。
            self.report({"INFO"},
                        "公式已放进节点编辑器。把某个区域切成 Node Editor，"
                        "顶部编辑器类型选「EFX Expression」就能看到。")
        return {"FINISHED"}


def _show_in_editor(context, tree):
    """把当前窗口里的某个节点编辑器切到这棵树；一个都没有就不强改用户的布局，
    只报一句——替用户重排界面比少一个便利更讨人嫌。"""
    for area in context.window.screen.areas:
        if area.type != "NODE_EDITOR":
            continue
        space = area.spaces.active
        space.tree_type = _TREE_ID
        space.node_tree = tree
        return True
    return False


def on_active_curve_changed(obj):
    """曲线列表切了一条 -> 图跟着切。由 `model` 那边
    `efx_expression_curves_active_index` 的 update 回调触发。"""
    tree = get_tree()
    if tree is None or not tree.efx_owner_object:
        return
    if tree.efx_owner_object != obj.name:
        return
    tree.efx_curve_index = obj.efx_expression_curves_active_index
    build_graph(tree, bpy.context)


# ---------------------------------------------------------------------------
# 节点编辑器侧栏
# ---------------------------------------------------------------------------

class EFX_RE_PT_expr_node_sidebar(Panel):
    bl_idname = "EFX_RE_PT_expr_node_sidebar"
    bl_label = "EFX Expression"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "EFX"

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and getattr(space, "tree_type", "") == _TREE_ID

    def draw(self, context):
        layout = self.layout
        tree = get_tree()
        curve = _bound_curve(tree)
        if curve is None:
            layout.label(text=T("exprnode.unbound"), icon="INFO", translate=False)
            return

        layout.label(text=curve.bit_name or ("bit %d" % curve.bit_index), translate=False)
        # 规范记法的公式文本。和属性面板那一栏是同一个 `formula_canonical`，
        # 改哪边另一边立刻跟着变——手打仍然是逃生口，也是唯一能写 `ext:<hash>` 的途径。
        layout.prop(curve, "formula_canonical", text="")
        if curve.formula_error:
            box = layout.box()
            box.label(text=curve.formula_error, icon="ERROR", translate=False)
        if _LAST_ERROR:
            box = layout.box()
            box.alert = True
            box.label(text=T("exprnode.rejected"), icon="ERROR", translate=False)
            for line in _wrap_text(_LAST_ERROR, 34):
                box.label(text=line, translate=False)
        layout.operator(EFX_RE_OT_expr_node_refresh.bl_idname, icon="FILE_REFRESH")


def _wrap_text(text, width):
    """侧栏宽度有限，Blender 的 label 不会自动换行——超长的错误消息不折的话
    只能看见开头几个字。"""
    lines, current = [], ""
    for char in text:
        current += char
        if len(current) >= width:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines


class EFX_RE_OT_expr_node_refresh(Operator):
    bl_idname = "efx_re.expr_node_refresh"
    bl_label = "Rebuild From Formula"
    bl_description = "按公式文本重新建图并重新布局，丢掉画布上没接线的游离节点"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tree = get_tree()
        if tree is None:
            return {"CANCELLED"}
        build_graph(tree, context)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def _draw_add_menu(self, context):
    space = getattr(context, "space_data", None)
    if space is None or getattr(space, "tree_type", "") != _TREE_ID:
        return
    self.layout.menu(EFX_RE_MT_expr_node_add.bl_idname)


_CLASSES = (
    EFXExprVarName,
    EFX_RE_ExprNodeTree,
    EFX_RE_ExprSocket,
    EFX_RE_ExprCallNode,
    EFX_RE_ExprOutputNode,
    EFX_RE_MT_expr_node_call,
    EFX_RE_MT_expr_node_add,
    EFX_RE_OT_expr_node_set_call,
    EFX_RE_OT_expr_node_add,
    EFX_RE_OT_expr_node_open,
    EFX_RE_OT_expr_node_refresh,
    EFX_RE_PT_expr_node_sidebar,
)


@persistent
def _on_load_post(_dummy):
    """打开 .blend 之后：节点图是派生量，`formula` 才是权威。这里**不**自动重建
    （用户可能根本没打开节点编辑器），只把绑定清掉——留着一个指向旧文件对象的绑定，
    下次点开会画出一棵属于上一个文件的图。"""
    tree = get_tree()
    if tree is not None:
        tree.efx_owner_object = ""
        tree.efx_curve_index = -1


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.efx_expr_var_names = CollectionProperty(type=EFXExprVarName)
    bpy.types.NODE_MT_add.append(_draw_add_menu)
    expr_edit.ON_ROWS_CHANGED.append(on_curve_rows_changed)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if on_curve_rows_changed in expr_edit.ON_ROWS_CHANGED:
        expr_edit.ON_ROWS_CHANGED.remove(on_curve_rows_changed)
    bpy.types.NODE_MT_add.remove(_draw_add_menu)
    del bpy.types.Scene.efx_expr_var_names
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
