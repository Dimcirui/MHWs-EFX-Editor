# -*- coding: utf-8 -*-
"""
blender_efx_re/expr_edit.py —— Expression 公式的结构化（模块化）编辑

`EFXExpressionCurveItem.formula` 存的是 vendor 的公式文本（`Lerp(Clamp(ext:302732036, 6, 3),
0, 8)` 这种）。以前面板只给一个单行文本框，`ext:302732036` 这种东西没人打得出来。这一层把
那行文本摊成**槽位**：一行 = 一个节点 + 它的全部参数槽位，每个槽位一律是同一种控件
（角色名 + 内容 + 展开标记），点开一个槽位就在下面出现它的检查器
（`[槽位类型] [该类型的具体值]`）和它内容的下一级。纵向只展开"从根到选中槽位"这一条链。

为什么是槽位而不是树：语料实测**每个参数槽位都能装下字面量/变量/子表达式三种**，没有哪个
槽位一定是常量，所以按内容类型分三种画法会让"同一个槽位换个内容就换外观换位置"，用户看到
的不是结构而是内容的偶然形状。逐条依据和取舍见 `draw_nodes()` 上面那段。

四条设计约束（都不是风格问题，改动前先想清楚）
----------------------------------------------
1. **文本仍然是唯一权威**。行视图（`EFXExpressionCurveItem.nodes`）是 `formula` 的视图，
   导出只读 `formula`（`io_tree._export_expression_attribute()`）。编辑器的最坏结果因此
   被限制成"吐出一段不同的文本"——桥接解析器会拒绝非法文本，字节门禁会抓住合法但不同的
   文本；没有任何路径能绕过文本去改二进制。
2. **这个视图不是唯一的编辑入口**：节点视口在 `expr_nodes.py`，两边共用同一个 `formula`。
   改这一层的同步逻辑时记得那边也挂在 `ON_ROWS_CHANGED` 上。

   ⚠ 这一条**原本是"不做节点编辑器"**，依据是语料实测公式极小（抽样 1044 个官方文件里
   898 条不同公式，AST 深度中位 2、最大 7，节点数中位 7、最大 25，26.9% 是单变量/单常量），
   节点图的机械成本不划算。那个判断只覆盖了"要不要那么大能力"，**没覆盖"当前这个画法读不
   读得懂"**——窄面板下每个槽位单独占一行再缩进一级，一条 4 层的公式摊成一道往右下滑的楼梯，
   而且纵向只展开"根 -> 选中槽位"这一条链，兄弟分支永远看不见。用户实际用下来卡在后者，
   所以加了节点视口。**行视图保留**，它在窄侧栏里仍然比节点图省地方。
3. **树的变换逻辑全在 `efx_sim/expr.py`**（零 bpy、`python -m unittest` 覆盖得到），
   这一层只做三件事：PropertyGroup ↔ dict 行、算子壳、画。逻辑别往这儿挪，挪过来就脱离
   单测了。
4. **下拉一律 `Menu` + `StringProperty`，不用带 items 回调的动态 `EnumProperty`**。
   动态 enum 的取值没法从 Python 传给算子（`bpy.ops...(target="Min")` 直接报
   `enum "Min" not found in ()`，实测），门禁就测不到用户真正点的那条路径。这也是本仓
   已有的写法（`EFX_RE_MT_attribute_type_picker` 就是这么干的）。

置信度必须如实显示
------------------
`Unary0~12` / `Func18~21` 语义未确认（vendor 注释原话只是"potential candidates"），
`Lerp`/`InvLerp`/`Clamp` 是名字确认、参数顺序靠猜。抽样 910 条公式里只有 36.0% 完全确认，
28.7% 只差参数顺序，35.3% 含未确认函数或未知变量。菜单里这三档分开列、选中未确认的函数时
在面板上标出来——**不把猜测画成确定**。
"""

from __future__ import annotations

import re

import bpy
from bpy.app.handlers import persistent
from bpy.props import IntProperty, StringProperty
from bpy.types import Menu, Operator

from . import io_tree, model, semantics
from .i18n import T

# 两种加载方式都要能跑，理由同 `sim_preview._sim()`：装成扩展时 `efx_sim` 是叔叔包，
# 门禁脚本把仓库根塞进 sys.path 直接 `import blender_efx_re` 时 `..` 已经越界。
try:
    from ..efx_sim import expr as _expr, plot as _plot, resolve_expr_field_name
except ImportError:  # pragma: no cover - 只在门禁/单测的顶层包布局下走到
    from efx_sim import expr as _expr, plot as _plot, resolve_expr_field_name

#: 给 panels.py 用的转发（那边只判"这条公式里有没有语义未确认的函数"，不该为这一件事
#: 再 import 一次 efx_sim）
call_confidence = _expr.call_confidence
CONFIDENCE_UNKNOWN = _expr.CONFIDENCE_UNKNOWN


# ---------------------------------------------------------------------------
# 同步：formula 文本 <-> nodes 行
# ---------------------------------------------------------------------------
# 两个方向互相是对方的 update 回调的触发源，不挡一下就会自己打自己（写 formula ->
# 触发重建行 -> 行的 update -> 再写 formula …）。用一个计数器而不是布尔：嵌套调用
# （结构算子内部先写行再写文本）也要能正确恢复。
_SUSPEND = 0


class _Suspended(object):
    def __enter__(self):
        global _SUSPEND
        _SUSPEND += 1
        return self

    def __exit__(self, *exc):
        global _SUSPEND
        _SUSPEND -= 1
        return False


#: 行视图被重写之后要通知谁。`expr_nodes` 在 register() 时把自己挂进来——
#: 属性面板和节点视口是同一个 `formula` 的两个视图，改哪边另一边都要立刻跟上。
#: 用回调表而不是直接 import `expr_nodes`：那边 import 了本模块，直连就是循环 import。
ON_ROWS_CHANGED = []


def _notify_rows_changed(curve) -> None:
    for callback in tuple(ON_ROWS_CHANGED):
        try:
            callback(curve)
        except Exception as exc:                        # noqa: BLE001
            # 派生视图的订阅者炸了不该拖垮编辑本身（公式文本已经写定了）
            print(f"[MHWs EFX Editor] 结构变更通知失败：{exc}")


def _curve_of_node(node):
    """从一个节点行反查它所属的曲线。`path_from_id()` 给的是
    `efx_expression_curves[3].nodes[7]` 这种完整 RNA 路径，从里面把曲线下标抠出来——
    比在节点上再存一份"我属于第几条曲线"可靠（结构算子会重排行，存下标就要跟着维护）。"""
    owner = node.id_data
    match = re.match(r"efx_expression_curves\[(\d+)\]", node.path_from_id())
    if owner is None or match is None:
        return None
    index = int(match.group(1))
    curves = getattr(owner, "efx_expression_curves", None)
    if curves is None or index >= len(curves):
        return None
    return curves[index]


def read_rows(curve) -> list:
    """PropertyGroup 行 -> `efx_sim.expr` 认的 dict 行。

    VAR 槽位的 `name` 在 PropertyGroup 里存的是**给人看的名字**（`EM_SPEED`），dict 行
    要还原成 `to_rows()`/`from_rows()` 认的 vendor 字面量（`ext:302732036`）——和
    `expr_nodes.py::_leaf_row()` 对同一份底层数据用同一套转换，理由见那边的注释。
    """
    return [
        {"kind": n.kind, "depth": n.depth, "arity": n.arity,
         "name": _expr.vendor_var_name(n.name) if n.kind == _expr.KIND_VAR else n.name,
         "value": n.value}
        for n in curve.nodes
    ]


def write_rows(curve, rows) -> None:
    """dict 行 -> PropertyGroup 行（整体重建，不做增量 diff）。

    没有"折叠状态"要保：槽位设计里纵向展开的就是"从根到选中槽位"那条链
    （`expr.path_to_root()`），由 `nodes_active_index` 一个整数完全决定，不需要逐行存
    展开位。上一版有个 `ui_expand` 是给树形视图用的，随视图一起删了。

    VAR 槽位反过来要把 dict 行里的 vendor 字面量换成给人看的名字再存进 PropertyGroup
    （`display_var_name()`，`read_rows()` 的逆），否则检查器里直接显示 `ext:302732036`
    ——和节点视口（`expr_nodes.py` 526 行）本该一致的两个编辑器就对不上了。
    """
    with _Suspended():
        curve.nodes.clear()
        for row in rows:
            item = curve.nodes.add()
            item.kind = row["kind"]
            item.depth = int(row.get("depth", 0))
            item.arity = int(row.get("arity", 0))
            name = row.get("name", "") or ""
            item.name = _expr.display_var_name(name) if row["kind"] == _expr.KIND_VAR else name
            item.value = float(row.get("value", 0.0) or 0.0)
        curve.nodes_active_index = min(
            max(curve.nodes_active_index, 0), max(len(curve.nodes) - 1, 0))
    _notify_rows_changed(curve)


def rebuild_rows(curve) -> None:
    """`formula` -> 行 + `second_branch`。解析失败时清空行并把原因写进 `formula_error`，
    面板据此退回"只有文本框"的形态——不给用户一棵解析了一半的树。"""
    try:
        parsed = _expr.parse(curve.formula)
        rows = _expr.to_rows(parsed)
    except _expr.ExprError as exc:
        with _Suspended():
            curve.nodes.clear()
            curve.second_branch = ""
            curve.formula_error = str(exc)
        return
    with _Suspended():
        curve.second_branch = parsed.second_branch or ""
        curve.formula_error = ""
    write_rows(curve, rows)


def write_formula(curve) -> None:
    """行 -> `formula`。拼不出来（行结构坏了）就只写错误、**不动 `formula`**：宁可让
    用户看见"结构坏了"，也不要拿一条内容不对的公式覆盖掉原来那条（铁律 #1）。"""
    try:
        text = _expr.from_rows(read_rows(curve), curve.second_branch or None)
    except _expr.ExprError as exc:
        with _Suspended():
            curve.formula_error = str(exc)
        return
    with _Suspended():
        curve.formula = text
        curve.formula_error = ""


def on_formula_edited(curve) -> None:
    """`EFXExpressionCurveItem.formula` 的 update 回调（定义在 model.py）。"""
    if _SUSPEND:
        return
    rebuild_rows(curve)


def on_node_edited(node) -> None:
    """节点行 `value`/`name` 的 update 回调（定义在 model.py）。"""
    if _SUSPEND:
        return
    curve = _curve_of_node(node)
    if curve is not None:
        write_formula(curve)


def apply_rows(curve, rows) -> None:
    """结构算子的收尾：写行 + 重拼文本。"""
    write_rows(curve, rows)
    write_formula(curve)


def rebuild_missing_rows() -> int:
    """给所有"有公式但没有结构化行"的曲线补上行，返回补了多少条。

    为什么需要这一步：行是**派生视图**，跟着 .blend 一起存盘。任何一个在这个功能存在
    之前存下来的 .blend（或者导入完之后才热加载新代码的会话）里，曲线有 `formula` 但
    `nodes` 是空的——面板就只剩一个"按文本重新解析"按钮，看起来像功能没做出来。

    只补**空的**，不碰已经有行的（那些可能正被用户编辑），也**永远不碰 `formula`**——
    这个函数只读文本、写派生量，改不动导出字节。
    """
    fixed = 0
    for obj in bpy.data.objects:
        curves = getattr(obj, "efx_expression_curves", None)
        if not curves:
            continue
        for curve in curves:
            if len(curve.nodes) == 0 and not curve.formula_error:
                rebuild_rows(curve)
                fixed += 1
    return fixed


@persistent
def _on_load_post(_dummy) -> None:
    """打开 .blend 之后补一遍。`@persistent` 是必须的——不加的话 Blender 在每次载入
    新文件时会把非 persistent 的 handler 全清掉，只有第一次生效。"""
    try:
        rebuild_missing_rows()
    except Exception as exc:                        # noqa: BLE001
        # handler 里抛异常会污染整个载入流程（而且报错位置离现场很远）。这里补的是
        # 派生视图，补不上最多是面板退回"按文本重新解析"那个形态，不值得拖垮载入。
        print(f"[MHWs EFX Editor] Expression 结构化视图重建失败，面板会退回手动重解析：{exc}")


# ---------------------------------------------------------------------------
# 候选项
# ---------------------------------------------------------------------------
#: 置信度 -> 菜单分组标题的 i18n key。**只写状态，不写出处**（docs/PITFALLS.md #25）：
#: "语义未知"是未知状态本身，不是"谁什么时候验过"。
_CONFIDENCE_ORDER = (
    (_expr.CONFIDENCE_CONFIRMED, "expr.conf.confirmed"),
    (_expr.CONFIDENCE_CORPUS, "expr.conf.corpus"),
    (_expr.CONFIDENCE_UNDECIDED, "expr.conf.undecided"),
    (_expr.CONFIDENCE_UNKNOWN, "expr.conf.unknown"),
)

#: 置信度 -> 菜单项/节点行的图标
_CONFIDENCE_ICON = {
    _expr.CONFIDENCE_CONFIRMED: "NONE",
    _expr.CONFIDENCE_CORPUS: "INFO",
    _expr.CONFIDENCE_UNDECIDED: "QUESTION",
    _expr.CONFIDENCE_UNKNOWN: "ERROR",
}


def _grouped_call_names():
    """运算符 + 函数，按置信度分组：`[(分组标题 key 或 None, [名字, ...]), ...]`。"""
    groups = [(None, list(_expr.BINARY_OPERATORS))]
    for confidence, label_key in _CONFIDENCE_ORDER:
        names = sorted(n for n, (_a, c) in _expr.CALL_SIGNATURES.items() if c == confidence)
        if names:
            groups.append((label_key, names))
    return groups


def _call_label(name) -> str:
    """菜单里一项的显示文字：**规范名** + 参数个数 + vendor 字面量 + 真实语义。

    参数个数要显示：换成参数个数不同的函数会补/丢参数，点之前就该看得见。

    vendor 字面量（`Unary0`/`Clamp`/…）在规范名之外**还要再显示一次**：公式文本里写的
    是它，不摆出来的话用户对不上"我在菜单里选的 `Sin` 就是文本里那个 `Unary0`"。

    语义在规范名说不完的时候显示（弧度还是角度、`Pow` 的指数在第几个参数……）；
    `+ - * /` 这四个符号则**只能**靠语义说话——它们的名字本身就是错的（`+` 是乘、
    `-` 是除），见 `efx_sim/expr.py::CALL_SEMANTICS`。"""
    display = _expr.call_display_name(name)
    operator = _expr.CANONICAL_OPERATORS.get(name)
    if name in _expr.BINARY_OPERATORS:
        # 规范符号在前、vendor 写法的符号跟在方括号里——和函数那一支的 `Sin  [Unary0]` 同形
        head = "%s  [%s]" % (operator[0], name) if operator else name
    else:
        head = "%s (%d)" % (display, _expr.call_arity(name))
        if display != name:
            head = "%s  [%s]" % (head, name)
    semantics = _expr.call_semantics(name)
    return "%s  =  %s" % (head, semantics) if semantics else head


def file_parameter_names(context) -> list:
    """当前文件自己的具名 Expression 参数（`EfxFile.ExpressionParameters`）。公式文本里
    `Color_A`/`BloodColor`/`Length` 这类名字就是从这张表来的——它是**逐文件**的，和内置
    外部变量不是一回事（名字像但两回事，同 docs/PITFALLS.md #26 的道理）。"""
    root = io_tree.resolve_root(context)
    if root is None:
        return []
    return [p.name for p in root.efx_expression_parameters if p.name]


#: 解不出名字的占位前缀（`ext:<hash>` / `const:` / `p:` / `ukn:`）。这些**不算拼错**
#: ——它们本来就不在任何名字表里，见 `EfxExpressionTreeUtils.KnownExternalHashes`。
_PLACEHOLDER_VAR_PREFIXES = ("ext:", "const:", "p:", "ukn:")


def unknown_variable_names(context, curve) -> list:
    """这条公式里**既不是内置外部变量、也不在本文件具名参数表里**的变量名。

    为什么要专门报出来：求值时未知变量按 `0.0` 处理（`expr._resolve_variable()` 会记一条
    note），而 `0` 往往让公式**看起来仍然合理**——实测有人把 `PI` 打成小写 `pi`，
    `Sin(TIMER/60 + pi/2) - Cos(TIMER/60)` 这条本该恒为 0 的式子退化成 `sin(t) - cos(t)`，
    在游戏里画出一条漂亮的上升斜线，一点都不像出错。note 只在下面「数值可视化」那一节
    显示，位置离公式框很远，所以这里单独给一份、画在公式框旁边。

    ⚠ 大小写敏感，**不做"你是不是想打 PI"的自动纠正**：猜一个名字等于替用户改数据。
    """
    names = (set(_expr.KNOWN_EXTERNAL_VARIABLES) | set(_expr.RESOLVED_EXTERNAL_VARIABLES)
             | set(file_parameter_names(context)))
    unknown = []
    for node in curve.nodes:
        if node.kind != "VAR":
            continue
        name = (node.name or "").strip()
        if not name or name in names or name.startswith(_PLACEHOLDER_VAR_PREFIXES):
            continue
        if name not in unknown:
            unknown.append(name)
    return unknown


# ---------------------------------------------------------------------------
# 角度显示——曲线目标字段是不是弧度制角度 + 哪些槽位和它同一个单位
# ---------------------------------------------------------------------------

def _curve_target_field(context, curve):
    """这条曲线驱动哪个 `(sibling attribute 的完整 vendor 类名, 字段名)`——语义表
    （`semantics.get_field_entry()`）按**完整类名**（如
    `ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3D`）索引，不是短名，见
    `panels.draw_node()` 传的 `attr_type=getattr(data, "efx_attr_type", "")`；不能拿
    `model.short_attr_name()` 的结果去查，那张表根本没有短名这个键，永远查不到。

    "驱动哪个字段"这份知识（bit_name -> 字段名的覆盖表 + fallback 规则）复用
    `efx_sim.resolve_expr_field_name()`，和 `sim_preview.collect_expressions()` 算
    `is_angle_degrees` 用的是同一个函数，也和定位 sibling attribute 的写法（按 entry
    子对象里 `short_attr_name() == base_name` 找）是同一条规则——不重新发明一遍，
    也不会因为两边读法不一致而对不上号。"""
    obj = getattr(context, "object", None)
    if obj is None or obj.parent is None:
        return None, None
    short_name = model.short_attr_name(obj.efx_attr_type)
    if not short_name.endswith("Expression"):
        return None, None
    base_name = short_name[: -len("Expression")]
    bit_name = curve.bit_name
    if not bit_name:
        return None, None
    field_name = resolve_expr_field_name(base_name, bit_name)

    sibling = next(
        (child for child in obj.parent.children
         if child.get("~TYPE") == model.TYPE_ATTRIBUTE
         and model.short_attr_name(child.efx_attr_type) == base_name),
        None,
    )
    if sibling is None:
        return None, None
    return sibling.efx_attr_type, field_name


def _curve_wants_degrees(context, curve) -> bool:
    """这条曲线的目标字段是不是弧度制角度字段、且「角度显示」开关开着——和 `panels.py`
    静态字段那边完全同一条判据（`semantics.wants_degrees()`），差别只是这次驱动字段的是
    一段公式而不是一个静态值：**同一个字段不该因为换了驱动方式就换一套单位读法**。"""
    attr_type, field_name = _curve_target_field(context, curve)
    if attr_type is None:
        return False
    entry = semantics.get_field_entry(attr_type, field_name)
    return semantics.wants_degrees(entry)


def _same_unit_mask(context, curve, rows) -> list:
    """和 `rows` 等长的布尔列表：这一行是不是该按「角度显示」换算的槽位——`_curve_wants_
    degrees()` 判定这条曲线整体是不是角度字段，`propagate_same_unit_as_root()` 在这个
    前提下再筛出真正和根节点同单位的那些行（`Clamp(TIMER,120,0)` 的帧数阈值绝不能被
    换算，见 `efx_sim/expr.py` 那个函数的说明）。不是角度曲线时全 False，不占额外开销。"""
    if not _curve_wants_degrees(context, curve):
        return [False] * len(rows)
    return _expr.propagate_same_unit_as_root(rows)


# ---------------------------------------------------------------------------
# 定位活动曲线 / 活动节点
# ---------------------------------------------------------------------------

def active_curve(context):
    obj = getattr(context, "object", None)
    if obj is None or not getattr(obj, "efx_is_expression_attribute", False):
        return None
    index = obj.efx_expression_curves_active_index
    if 0 <= index < len(obj.efx_expression_curves):
        return obj.efx_expression_curves[index]
    return None


def active_node(context):
    curve = active_curve(context)
    if curve is None:
        return None
    index = curve.nodes_active_index
    if 0 <= index < len(curve.nodes):
        return curve.nodes[index]
    return None


def _active_node_index(context) -> int:
    curve = active_curve(context)
    return curve.nodes_active_index if curve is not None else 0


# ---------------------------------------------------------------------------
# 算子
# ---------------------------------------------------------------------------
# 全部只用 IntProperty/StringProperty：能从 Python 直接调，门禁测的就是用户点的那条路。

class _NodeOperator(object):
    """结构算子的共同部分。刻意是**纯 mixin**（不继承 `Operator`），照
    `bpy_extras.io_utils.ExportHelper` 的写法——那是官方保证能继承注解的形态。"""

    bl_options = {"REGISTER", "UNDO"}

    node_index: IntProperty(name="Node Index", min=0)

    @classmethod
    def poll(cls, context):
        return active_curve(context) is not None

    def _rows(self, context):
        curve = active_curve(context)
        if curve is None:
            return None, None
        rows = read_rows(curve)
        if not (0 <= self.node_index < len(rows)):
            return curve, None
        return curve, rows


class EFX_RE_OT_expression_node_select(_NodeOperator, Operator):
    """把某一行设成活动节点（下面的操作按钮都作用在它身上）。"""

    bl_idname = "efx_re.expression_node_select"
    bl_label = "Select Expression Node"
    bl_description = "选中这个节点，下面的操作按钮作用在它身上"

    def execute(self, context):
        curve, rows = self._rows(context)
        if rows is None:
            return {"CANCELLED"}
        curve.nodes_active_index = self.node_index
        return {"FINISHED"}


class EFX_RE_OT_expression_node_replace(_NodeOperator, Operator):
    """把一个节点换成别的东西。子节点的去留规则见 `efx_sim.expr.convert_node()`。

    名字从"换成"改成"替换"：前者读起来像在改某个值，后者更明确是"这一项整个换掉"。
    """

    bl_idname = "efx_re.expression_node_replace"
    bl_label = "Replace Expression Node"
    bl_description = "把选中的这一项整个换成常量、变量、运算符或函数"

    target: StringProperty(name="Target")

    def execute(self, context):
        curve, rows = self._rows(context)
        if rows is None:
            return {"CANCELLED"}
        try:
            apply_rows(curve, _expr.convert_node(rows, self.node_index, self.target))
        except _expr.ExprError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class EFX_RE_OT_expression_node_delete(_NodeOperator, Operator):
    """删掉选中这一层，第一个参数顶替它（`efx_sim.expr.delete_node()`）。

    **上一版这里是"提一层"（用选中节点替换掉它的父节点）**——实际语义是"删掉我的父级
    函数"，选中 `Clamp` 点一下会把外层 `Lerp` 整个干掉，容易误操作。按用户意见改成
    "删除选中这一层"：作用点和选中项一致，而且正好是"内嵌"的逆操作。
    叶子上不可用（叶子不是"一层"，见 `can_delete_node()`）。
    """

    bl_idname = "efx_re.expression_node_delete"
    bl_label = "Delete Expression Node"
    bl_description = "删掉选中的这一层，它的第一个参数顶上来（其余参数一起删掉）"

    def execute(self, context):
        curve, rows = self._rows(context)
        if rows is None:
            return {"CANCELLED"}
        if not _expr.can_delete_node(rows, self.node_index):
            return {"CANCELLED"}
        # 删完之后选中项落在"顶上来的那个子节点"身上——它就在原来的位置，选中不跳走
        apply_rows(curve, _expr.delete_node(rows, self.node_index))
        curve.nodes_active_index = min(self.node_index, max(len(curve.nodes) - 1, 0))
        return {"FINISHED"}


class EFX_RE_OT_expression_node_set_var(_NodeOperator, Operator):
    """从候选里挑一个变量名填进节点。"""

    bl_idname = "efx_re.expression_node_set_var"
    bl_label = "Set Expression Variable"
    bl_description = "从本文件的具名参数和内置外部变量里挑一个"

    var_name: StringProperty(name="Variable")

    def execute(self, context):
        curve, rows = self._rows(context)
        if rows is None:
            return {"CANCELLED"}
        rows[self.node_index]["kind"] = _expr.KIND_VAR
        rows[self.node_index]["arity"] = 0
        rows[self.node_index]["name"] = self.var_name
        apply_rows(curve, rows)
        return {"FINISHED"}


class EFX_RE_OT_expression_rebuild_rows(Operator):
    """手打文本以后重新解析成结构。"""

    bl_idname = "efx_re.expression_rebuild_rows"
    bl_label = "Reparse Formula"
    bl_description = "按文本框里的公式重新生成下面的结构"

    @classmethod
    def poll(cls, context):
        return active_curve(context) is not None

    def execute(self, context):
        rebuild_rows(active_curve(context))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# 菜单
# ---------------------------------------------------------------------------

class EFX_RE_MT_expression_function(Menu):
    """「函数类型」菜单：运算符 + 函数 + 取负，按置信度分组。

    **不含常量/变量**——那是「槽位类型」那一层的事（见
    `EFX_RE_MT_expression_slot_kind`）。把"是哪一类东西"和"是这一类里的哪一个"拆成两步，
    是因为语料实测每个槽位都能装三种内容（`efx_sim.expr` 的槽位视角一节），既然同构，
    就该先选类型再选具体值，而不是把 30 个选项混在一个菜单里。
    """

    bl_idname = "EFX_RE_MT_expression_function"
    bl_label = "Function"

    def draw(self, context):
        layout = self.layout
        index = _active_node_index(context)
        op = layout.operator(EFX_RE_OT_expression_node_replace.bl_idname,
                             text=T("expr.wrap.negate"), translate=False)
        op.node_index = index
        op.target = _expr.KIND_NEG
        for label_key, names in _grouped_call_names():
            layout.separator()
            if label_key:
                layout.label(text=T(label_key), translate=False)
            for name in names:
                op = layout.operator(
                    EFX_RE_OT_expression_node_replace.bl_idname,
                    text=_call_label(name), translate=False,
                    icon=_CONFIDENCE_ICON.get(_expr.call_confidence(name), "NONE"),
                )
                op.node_index = index
                op.target = name


class EFX_RE_MT_expression_slot_kind(Menu):
    """「槽位类型」菜单：常量 / 变量 / 表达式（表达式是个子菜单，直接挑函数）。

    切到「表达式」时**原内容会被保留成新函数的第一个参数**
    （`efx_sim.expr.convert_node()` 对叶子的处理），所以这一步同时顶替了原来那个
    独立的「内嵌」操作：`a [VAR_C]` 选表达式 -> `Min` 就得到 `a [Min(VAR_C, 0)]`，
    改回变量类型还能把 `VAR_C` 拿回来。
    """

    bl_idname = "EFX_RE_MT_expression_slot_kind"
    bl_label = "Slot Kind"

    def draw(self, context):
        layout = self.layout
        index = _active_node_index(context)
        for target, key in ((_expr.KIND_CONST, "expr.kind.const"),
                            (_expr.KIND_VAR, "expr.kind.var")):
            op = layout.operator(EFX_RE_OT_expression_node_replace.bl_idname,
                                 text=T(key), translate=False)
            op.node_index = index
            op.target = target
        layout.menu(EFX_RE_MT_expression_function.bl_idname,
                    text=T("expr.kind.expr"))


class EFX_RE_MT_expression_variable(Menu):
    """变量候选：本文件的具名参数（在前，改这个才对当前文件有意义）+ 内置外部变量
    （vendor 已解出真名的、我们猜出名字的、连猜测都没有只能露哈希的三档全列出来，
    `_expr.variable_picker_choices()`），选哪一档用户不需要关心——菜单文字上打的就是
    选出来能看懂的样子，落进公式里再统一换回 `vendor_var_name()` 认的字面量。"""

    bl_idname = "EFX_RE_MT_expression_variable"
    bl_label = "Variable"

    def draw(self, context):
        layout = self.layout
        index = _active_node_index(context)
        names = file_parameter_names(context)
        if names:
            layout.label(text=T("expr.var.file_params"), translate=False)
            for name in names:
                op = layout.operator(EFX_RE_OT_expression_node_set_var.bl_idname,
                                     text=name, translate=False)
                op.node_index = index
                op.var_name = name
            layout.separator()
        layout.label(text=T("expr.var.builtins"), translate=False)
        for name in _expr.variable_picker_choices():
            op = layout.operator(EFX_RE_OT_expression_node_set_var.bl_idname,
                                 text=name, translate=False)
            op.node_index = index
            op.var_name = _expr.vendor_var_name(name)


# ---------------------------------------------------------------------------
# 绘制 —— 槽位设计
# ---------------------------------------------------------------------------
# 一行 = 一个节点 + 它的全部槽位；槽位一律画成同一种控件（角色名 + 内容 + 展开标记），
# 内容类型只改变控件里面显示什么，**不改变它的位置和大小**。
#
# 为什么不按内容类型分三种画法：语料实测每个参数槽位都能装下字面量/变量/子表达式三种
# （`Lerp.to` 常量 1729 / 变量 483 / 子表达式 24；`Clamp.hi` 1503/4/20），没有哪个
# 槽位"一定是常量"。按内容分画法的话，同一个槽位换个内容就换外观、换位置，用户看到的
# 就不是公式结构而是内容的偶然形状。上一版就是这么做的（常量给数值框、子表达式给一行
# 缩进），结果把函数和它自己的参数割裂到了不同的行上。
#
# 纵向只展开**从根到选中槽位的那一条链**（`expr.path_to_root()`）。一次只看一级的代价由
# 另外两处补掉：完整公式在上面的文本框里，形状在视口 HUD 上。


#: 一个槽位横排要的宽度（UI 单位）：角色名 3 + 内容 5.5 + 展开标记 1.2，外加 0.8 余量
_SLOT_UNITS = 10.5
#: 节点头 6 + 值列 5 + 余量 4
_ROW_OVERHEAD = 15.0
#
# 这两个数是**估的**（Blender 没有"这个控件要多宽"的查询接口），所以刻意往宽了留余量：
# 判错成"窄"只是多占几行，判错成"宽"会把文字和数字整个挤没——两种错的代价差很远。
# 用真实环境校准过一次（2026-09-15，ui_scale 1.5）：N 面板 690px = 23 单位、
# 属性编辑器 856px = 28.5 单位。3 个槽位横排要 46.5 单位，所以这两处都走竖排；
# 1 个槽位要 25.5，属性编辑器能横排、N 面板不能。想看横排就把面板拖宽或降低界面缩放。


def _available_units(context) -> float:
    """当前区域大约有多少个 UI 单位宽。

    Blender 的 1 个 UI 单位约 20 像素（乘界面缩放）。**必须按区域实际宽度判断**，不能
    凭默认宽度拍——同一个面板在 N 面板和属性编辑器里宽度差一倍，而 Blender 在宽度不够时
    不会换行，会**把所有控件按比例压扁**，压到一定程度按钮里的文字和数值框里的数字**整个
    消失**（用户截图里 `from`/`to` 是两个空框子就是这个）。拿不到区域就当足够宽。
    """
    region = getattr(context, "region", None)
    if region is None:
        return 1e6
    scale = getattr(context.preferences.system, "ui_scale", 1.0) or 1.0
    return float(region.width) / (20.0 * scale)


def _fits_one_line(context, slot_count) -> bool:
    return _available_units(context) >= _ROW_OVERHEAD + slot_count * _SLOT_UNITS


def _draw_structure(layout, context, curve) -> None:
    rows = read_rows(curve)
    if not rows:
        return
    roles = _expr.arg_roles(rows)
    values = _node_values(context, curve, rows)
    same_unit = _same_unit_mask(context, curve, rows)
    selected = min(max(curve.nodes_active_index, 0), len(rows) - 1)
    chain = _expr.path_to_root(rows, selected)

    col = layout.column()
    for position, node_index in enumerate(chain):
        child_on_path = chain[position + 1] if position + 1 < len(chain) else None
        if rows[node_index]["arity"]:
            _draw_slot_row(col, context, curve, rows, roles, values, same_unit,
                           node_index, child_on_path, selected, position)
        if child_on_path == selected:
            # 检查器紧跟在**包含这个槽位的那一行**后面，不是跟在选中内容后面
            _draw_inspector(col, context, curve, rows, same_unit, selected, position + 1)
    if len(chain) == 1:
        # 选中的是根：它没有"包含它的行"，所以行在前、检查器在后
        _draw_inspector(col, context, curve, rows, same_unit, selected, 1)


def _draw_slot_row(col, context, curve, rows, roles, values, same_unit, index,
                   child_on_path, selected, depth) -> None:
    """一个节点 + 它的全部槽位。

    宽度够就横排成一行（`● Lerp   t [Clamp]▸  from [190]▸  to [-30]▸   值`），
    不够就**头一行、槽位逐行缩进一级**。两种排法里槽位控件本身完全一样，所以"槽位同构"
    这条性质不受影响；变的只是把它们摆成一行还是一列。
    """
    children = _expr.child_indices(rows, index)
    wide = _fits_one_line(context, len(children))

    row = col.row()
    _draw_indent(row, depth)
    head = row.row()
    if wide:
        head.ui_units_x = 6.0
    head.operator(
        EFX_RE_OT_expression_node_select.bl_idname,
        text=_expr.node_summary(rows, index), translate=False,
        icon="LAYER_ACTIVE" if index == selected else "LAYER_USED",
        depress=index == selected,
    ).node_index = index

    if wide:
        for child in children:
            _draw_slot(row, curve, rows, roles, same_unit, child,
                       marked=(child == child_on_path or child == selected), wide=True)
        _draw_row_value(row, values.get(index))
        return

    # 窄：值跟在头后面，槽位逐行往下排（缩进一级，视觉上属于这个节点）
    _draw_row_value(row, values.get(index))
    for child in children:
        line = col.row()
        _draw_indent(line, depth + 1)
        _draw_slot(line, curve, rows, roles, same_unit, child,
                   marked=(child == child_on_path or child == selected), wide=False)


def _draw_slot(row, curve, rows, roles, same_unit, index, marked, wide) -> None:
    """一个槽位控件。三种内容**同样的结构**：角色名 + 内容控件 + 展开标记。

    常量的内容控件是可直接编辑的数值框（改常量是最高频操作，不该多一次点击，
    和检查器里的「常量值」指同一个值）；变量和表达式是按钮，点了就选中这个槽位。
    `same_unit[index]` 为真时改画 `degrees_value`（角度显示开关 + 这个槽位和曲线目标
    字段同单位，见 `_same_unit_mask()`）——和这个节点本身是不是 `CONST` 无关，只有
    `CONST` 才会用到，其余分支走的还是 `_expr.node_summary()` 那个按钮。
    """
    node = curve.nodes[index]
    if roles[index]:
        label = row.row()
        if wide:
            label.ui_units_x = 3.0
            label.alignment = "RIGHT"
        else:
            label.ui_units_x = 5.0
        label.label(text=roles[index], translate=False)

    body = row.row()
    if wide:
        body.ui_units_x = 5.5
    if node.kind == "CONST":
        body.prop(node, "degrees_value" if same_unit[index] else "value", text="")
    else:
        body.operator(
            EFX_RE_OT_expression_node_select.bl_idname,
            text=_expr.node_summary(rows, index), translate=False,
            depress=marked,
        ).node_index = index

    mark = row.row()
    mark.ui_units_x = 1.2
    mark.operator(
        EFX_RE_OT_expression_node_select.bl_idname, text="",
        icon="TRIA_DOWN" if marked else "TRIA_RIGHT", depress=marked,
    ).node_index = index


def _draw_inspector(col, context, curve, rows, same_unit, index, depth) -> None:
    """选中槽位的检查器：`[槽位类型：X] [该类型的具体值]`（+ 表达式才有的「删除这一层」）。

    窄面板下拆成两行——三个控件挤在一行里同样会被压到看不见文字。
    """
    node = curve.nodes[index]
    wide = _available_units(context) >= 34.0

    kind_key = {"CONST": "expr.kind.const", "VAR": "expr.kind.var"}.get(
        node.kind, "expr.kind.expr")

    row = col.row()
    _draw_indent(row, depth)
    left = row.row()
    if wide:
        left.ui_units_x = 9.0
    left.menu(EFX_RE_MT_expression_slot_kind.bl_idname,
              text="%s: %s" % (T("expr.slot.kind"), T(kind_key)))
    if not wide:
        row = col.row()
        _draw_indent(row, depth)

    if node.kind == "CONST":
        row.prop(node, "degrees_value" if same_unit[index] else "value",
                 text=T("expr.slot.value"))
    elif node.kind == "VAR":
        row.prop(node, "name", text="")
        pick = row.row()
        if wide:
            pick.ui_units_x = 8.0
        pick.menu(EFX_RE_MT_expression_variable.bl_idname, text=T("expr.slot.var"))
    else:
        row.menu(EFX_RE_MT_expression_function.bl_idname,
                 text="%s: %s" % (T("expr.slot.func"), _expr.node_summary(rows, index)))
        # 「删除这一层」和"把槽位类型改成变量/常量"是两个不同的意图：后者丢掉整棵子树，
        # 前者保留里面的输入、只去掉外面这层函数。所以它不能被槽位类型顶替。
        drop = row.row()
        if wide:
            drop.ui_units_x = 6.0
        drop.enabled = _expr.can_delete_node(rows, index)
        drop.operator(EFX_RE_OT_expression_node_delete.bl_idname,
                      text=T("expr.slot.delete_layer"), icon="X").node_index = index


def draw_nodes(layout, context, curve) -> None:
    """活动曲线的结构化视图。形态见本节顶部的说明。"""
    if curve.formula_error:
        # 文本解析不了：只报错，不画半棵树（上面的文本框仍然可编辑，改对了自动恢复）
        box = layout.box()
        box.label(text=curve.formula_error, icon="ERROR", translate=False)
        box.operator(EFX_RE_OT_expression_rebuild_rows.bl_idname,
                     text=T("expr.reparse"), icon="FILE_REFRESH")
        return

    if not curve.nodes:
        # 正常情况下走不到这儿：导入时建、打开 .blend 时由 load_post 补
        # （`rebuild_missing_rows()`）。剩下的只有"导入完之后才热加载了新代码"这类开发态。
        box = layout.box()
        box.label(text=T("expr.no_rows"), icon="INFO")
        box.operator(EFX_RE_OT_expression_rebuild_rows.bl_idname,
                     text=T("expr.reparse"), icon="FILE_REFRESH")
        return

    _draw_structure(layout, context, curve)

    if curve.second_branch:
        # `a  |  b` 的第二支：语义没证实，不给结构化编辑，但要让用户知道它在、没被丢掉
        box = layout.box()
        box.label(text=T("expr.second_branch"), icon="INFO")
        box.label(text=curve.second_branch, translate=False)


def _draw_indent(row, depth) -> None:
    """缩进。**用 `BLANK1` 空图标一格一格排，不用 `separator(factor=)`**——后者在
    `align=True` 的行里宽度不稳定，而且它吃掉的空间会从后面控件的分配里扣，导致每一行的
    内容起点都不一样（上一版用户截图里"字段从各种不同位置开始"就是这么来的）。
    链最深 7 级（语料实测），最多 8 格。
    """
    for _ in range(min(int(depth), 8)):
        row.label(text="", icon="BLANK1")


def _node_values(context, curve, rows) -> dict:
    """每个节点在当前帧的值：`{行下标: 值 或 None}`。

    走 `expr_preview`（变量表 + 求值都在那儿，两边共用一份，免得读数和 HUD 不一致）。
    拿不到就返回空 dict —— 值那一列是**锦上添花**，不该因为它失败就不画结构。
    """
    try:
        from . import expr_preview
        return expr_preview.subtree_values(context, curve, rows)
    except Exception:                                   # noqa: BLE001
        return {}


def _draw_row_value(row, value) -> None:
    """行尾：该节点在当前帧的值。算不出来画一个问号，**不画 0** —— 0 看起来像结果。"""
    sub = row.row()
    sub.ui_units_x = 5.0
    sub.alignment = "RIGHT"
    sub.active = False                  # 灰一点：这是只读的派生量，不是可编辑字段
    if value is None:
        sub.label(text="?", translate=False)
    else:
        sub.label(text=_plot.format_tick(value), translate=False)


_CLASSES = (
    EFX_RE_OT_expression_node_select,
    EFX_RE_OT_expression_node_replace,
    EFX_RE_OT_expression_node_delete,
    EFX_RE_OT_expression_node_set_var,
    EFX_RE_OT_expression_rebuild_rows,
    # 函数菜单要排在槽位类型菜单前面：后者把它当子菜单挂
    EFX_RE_MT_expression_function,
    EFX_RE_MT_expression_slot_kind,
    EFX_RE_MT_expression_variable,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    # 注册这一刻不能碰 bpy.data（Blender 禁止在 register() 里读写场景数据），所以启用
    # 插件时那一遍补齐延后一帧用 timer 跑——覆盖"场景已经在了、之后才启用/重载插件"这条路。
    bpy.app.timers.register(_deferred_rebuild, first_interval=0)


def _deferred_rebuild():
    try:
        rebuild_missing_rows()
    except Exception as exc:                        # noqa: BLE001
        print(f"[MHWs EFX Editor] Expression 结构化视图重建失败，面板会退回手动重解析：{exc}")
    return None                                      # 只跑一次


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
