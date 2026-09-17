# -*- coding: utf-8 -*-
"""
efx_sim/expr.py —— IExpressionAttribute 公式（文本形式）的解析与求值

`EFXExpressionCurveItem.formula`（`blender_efx_re/model.py`）存的是 vendor
`EFXExpressionTree.ToString()`/`EfxExpressionStringParser.Parse()` 的人类可读文本（如
`"Lerp(Clamp(ext:302732036, 6, 3), 0, 8)"`），不是后缀栈——双向转换全部交给 EfxBridge
（见 model.py::EFXExpressionCurveItem 的说明），这个模块只管"文本 -> 数值"这一步。

**用 Python 自带 `ast` 模块当解析器，不手写递归下降**——vendor 的公式文本语法
（标识符/浮点数/`+-*/`/一元负号/括号/`Name(arg,...)` 函数调用）是 Python 表达式语法的严格
子集，唯一冲突点是标识符允许 `:`（`ext:302732036`/`p:2597296009` 这种未解析出名字的占位
形式，见 `EfxExpressionParser.cs` 的 `ReadIdentifier()`），预处理时把 `:` 换成 `__` 再喂给
`ast.parse(..., mode="eval")`。

置信度分层（**只有这样分层，才对得起铁律 #7"没拿到真实样本就不实现、不断言"**）
--------------------------------------------------------------------------
- **实机确认：vendor 给六个二元操作码起的名字，一个都不对。** 文本里的
  `+` 是**乘**、`-` 是**除**（`b/a`）、`*` 是**取模**（`fmod(b,a)`）、`/` 是**加**，
  函数写法的 `Min(a,b)` 是**减**（`b-a`）、`Max(a,b)` 是**幂**（`pow(b,a)`，这一个是
  语料推断）。**真正的 min/max 不存在。** 逐点判据见 `_eval_binary_operator()`。
  ⚠ **这条曾经被这份 docstring 自己划出过作用域**——原文把 `+ - * /` 列在"完全确认"档，
  理由是"这几个符号是 vendor 从 `ParseBinaryOperationAddSub`/`MulDiv` 直接翻译出的字面
  符号，和'操作码 0-5 哪个是 Add'那个更上游、vendor 自己承认 not 100% sure 的不确定性
  （`ExpressionTree.cs:11`）无关，那是文件→文本这一步的问题，不在本模块范围"。
  **这个作用域划分错得很彻底**：文本↔操作码的往返是自洽的（字节门禁、文本门禁、
  `exprcheck` 全绿，一个都没报警），错误只在"符号算什么"这一步显形，而那一步恰好
  就在本模块里。**教训：往返自洽性对"两边用同一套错误约定"完全免疫**，只有实机能测。
  一元负号是唯一没翻车的：`Lerp(Clamp(TIMER, 15, 0), 0.5, -1)` 的起点实机就在 -1。
- **实机确认（只覆盖上界）**：`Clamp(value, hi, lo)` 是把 `value` 从 `[lo, hi]` 重映射到
  `[0, 1]`，**上界会饱和**——2026-09-16 搭了两条 `Lerp(Clamp(TIMER, hi, 0), -1, 0.5)` 驱动
  的粒子轨迹对拍，`hi` 从 15 翻倍到 30，终点位置完全相同、只有到达时间翻倍，直接排除了
  "上界不钳"（那样的话 `hi` 翻倍会改变终点，见 `_eval_clamp()` docstring 的详细推导）。
  这次测试 `lo` 恒为 0、`TIMER` 恒 ≥0，**下界饱和没被覆盖到**，仍是下面这条语料推断撑着。
  默认档改成 `remap_saturate_both`，`remap_saturate_low`（旧默认）降级为对拍档。
- **语料一致性推断（比"猜"强，比实机确认弱）**：`Lerp(t, a, b)` 和 `Clamp` 的参数顺序
  （`value`/`hi`/`lo` 分别对应哪个位置）。vendor 在 `EfxExpressionFunction` 枚举里给了
  字面名字，但那和 `Unary*` 一样只是 vendor 起的名，没有任何地方写明参数顺序或语义。
  依据是全语料 1044 个文件 / 3882 条公式实例：边界都是字面量的 1493 例里第 2 参 > 第 3 参
  占 1493/1493；`Lerp(Clamp(EM_SPEED, 6, 3), 0, 8)` 的输出落在它自己写的 `[0, 8]`（反过来
  印证 `Lerp` 第一个参数确实是插值系数），逐条证据见 `_eval_clamp()` 的 docstring 和
  docs/EXPRESSION_SEMANTICS.md。`bounds_clamp`/`remap_unclamped` 两档保留旧读法对拍，见
  `SimConfig.expr_clamp_mode`。
  **`InvLerp` 也定了（2026-09-16 实机）**：`InvLerp(a, b, t)` == `b + (a-b)*saturate(t)`
  ——**就是 `Lerp`，只是插值系数挪到最后一个参数**，不做任何"反向"的事。判据是两条
  探针：`InvLerp(x, 1, 0)` 恒定 1 不动（说明第 3 参是系数、第 1 参不是 value），
  `InvLerp(1, 0, x)` 是两端饱和的 0→1 斜坡（说明 `t` 钳 `[0,1]`）。语料里那两种互斥
  用法里，`InvLerp(1, 0.5, 1 - Clamp(TIMER, 120, 30))` 读通了（从 1 淡到 0.5），
  而 `InvLerp(Length, 65, 20)` 在这个读法下退化成恒等于 `Length`（`65`/`20` 是死参数）
  ——那大概是作者写错了，实机结果优先。
- **纯数字占位，语义未确认**：`Unary0`~`Unary12`、`Func18`~`Func21`——vendor 注释原话是
  "unary potential candidates: sin/cos/tan/atan2/…"，不是定论。全语料统计（`EfxBridge
  exprvarstats`）这批函数占全部函数调用的约 13%（`Unary10` 一项 2063 次）。按用户决定：
  不跳过、不返回 0，按 `SimConfig.expr_unknown_func_policy`（目前只有 `"identity"`：1 参
  原样返回、多参返回第一个参数）处理，并在 `EvalContext.notes` 记一笔，UI 如实展示"这条曲线
  用到未确认语义的函数"，不装作算对了。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from __future__ import annotations

import ast
import math

#: vendor `ExpressionRootValueOption.ToString()` 用 `"  |  "` 连接两个根值
#: （`ExpressionTree.cs:269`），语义"vendor 自己也不确定"（原话："maybe it's a feature where
#: you can specify two values, and they get used as a min-max random range?"）。只取第一支
#: 求值，第二支记 note，不扩语法去猜它的用法。
_ROOT_VALUE_CHAR = "|"

#: 2 参函数写法的两个操作码。**名字全是错的**：文本里的 `Min(a, b)` 是**减法**
#: （`b - a`，操作码 5）、`Max(a, b)` 是**幂**（`pow(b, a)`，操作码 0）。
#: 逐条依据见 `_eval_binary_operator()`。
#: **真正的 min/max 不在二元操作码里，在函数里**：`Func18` = `min`、`Func19` = `max`
#: （2026-09-16 实机确认，见 `_eval_known_binary_func()`）。
_BINARY_KNOWN_FUNCS = frozenset({"Min", "Max"})

#: 2 参、实机测出语义的**函数**（区别于上面那两个"函数写法的二元操作码"）。
#: `Func18`/`Func19` 名字纯是编号，语义是 min/max。
_KNOWN_BINARY_FUNCS = {
    "Func18": min,
    "Func19": max,
    "Func20": None,     # pow(b, a) = b^a，走 _eval_known_binary_func 里的兜底分支
}

#: 3 参、具名确认但参数顺序是猜的函数，见模块 docstring
_TERNARY_KNOWN_FUNCS = frozenset({"Lerp", "InvLerp", "Clamp"})

#: 1 参函数里**语义已经测出来的**：名字 -> (实现, 置信度说明用的 key)。
#: 2026-09-16 实机测法：Y 轴当时间基准、Z 轴填 `UnaryN(<输入>)`、单粒子
#: `TypeRibbonFollow` 的轨迹当示波器。**关键是输入要扫 `[-2, 2]`**——只喂 `[0, 1]` 的话
#: `identity`/`abs`/`saturate` 三者全等、`floor`/`trunc` 全等、`ceil`/`sign` 全等，
#: 前一轮就是因为这个卡住的。逐条判据见 `_KNOWN_UNARY_EVIDENCE`。
_KNOWN_UNARY_FUNCS = {
    "Unary0": math.sin,                                    # 弧度
    "Unary1": math.cos,                                    # 弧度
    "Unary2": None,      # asin（弧度），走 _eval_known_unary 里的定义域兜底
    "Unary4": lambda x: float(math.floor(x)),
    "Unary5": lambda x: float(math.ceil(x)),
    "Unary6": None,      # ln，走 _eval_known_unary 里的定义域兜底
    "Unary7": None,      # log10，同上
    "Unary8": None,      # e^x，走溢出兜底
    "Unary9": abs,
    "Unary10": lambda x: max(0.0, min(1.0, x)),            # saturate / clamp01
    "Unary11": lambda x: math.sin(math.radians(x)),        # **角度制**
    "Unary12": lambda x: math.cos(math.radians(x)),        # **角度制**
}

#: 每个已测函数的实机读数（写在这儿是为了让 docstring 和回归测试引用同一份原始观察）
_KNOWN_UNARY_EVIDENCE = {
    "Unary0": "圆测试从侧面起（sin(0)=0）；[-2,2] 宽扫呈 谷前(-0.909)-谷(-1@-pi/2)-峰(1@pi/2)-峰后(0.909)",
    "Unary1": "圆测试配 Unary0 画出整圆；[-2,2] 宽扫呈 谷(-0.416)-峰(1@0)-谷(-0.416)",
    "Unary4": "[-2,2] 阶梯，第一个完整台阶在 -2（trunc/ceil 都会从 -1 开始）",
    "Unary5": "[-2,2] 阶梯，第一个完整台阶在 -1",
    "Unary6": "输入 0->1 时从 -inf 爬到 0；Unary6(Unary8(t)) 复合终点恰好 1.0（同底互逆）",
    "Unary8": "[-2,2] 宽扫起点 0.14 == e^-2 = 0.1353（10^-2=0.01 / 2^-2=0.25 都不对）",
    "Unary2": "输入扫 0->1.4：升到 1.4416 时粒子消失（画面内，不是边界）== asin 在 x>1 无定义，"
              "消失前最后一帧 asin(1.003 之前) = 1.4416；tan/atanh 会先冲出画面、atan 根本不消失、"
              "acos 是往下走到 -0.87 才消失",
    "Unary7": "Unary7(Unary8(t)) 复合终点 0.434 == log10(e)（ln 会是 1.0、log2 会是 1.443）",
    "Unary9": "[-2,2] 宽扫画出直线 V 字；输入缩到 [-0.5,0.5] 后是小 V、顶点贴 0（排掉 max(|x|,1) 的平底 U）",
    "Unary10": "[-2,2] 宽扫呈 `_/‾`：0 段 -> 斜升到 1 -> 停在 1，就是 clamp01",
    "Unary11": "[-2,2] 恒 0、[-180,180] 扫出完整三角波 -> sin 的角度制版本（sin(2°)=0.035）",
    "Unary12": "[-2,2] 恒 1、[-180,180] 扫出三角波 -> cos 的角度制版本（cos(2°)=0.9994）",
}

#: 纯数字占位、语义**仍然**未确认的函数名 -> 参数个数（`EfxExpressionParser.cs` 的
#: `FunctionArgCounts`：Unary* 全部 1 参，Func18/19/20 是 2 参，Func21 是 5 参）。
#: 函数全部测完了（12 个 `Unary*` + `Func18`/`19`/`20`/`21`），这张表现在是空的。
#: **唯一还没定语义的是三参的 `InvLerp`**（语料里两种用法互斥，见模块 docstring），
#: 它走 `_TERNARY_KNOWN_FUNCS` 那条路、置信度是 `undecided`。
#:
#: ⚠ **vendor 的枚举跳过了 3 / 13 / 14**，所以文本里写 `Unary3(...)` 会被解析器当成
#: 未知函数名直接拒绝——那是**我们这侧的限制，不是引擎说 3 不存在**（vendor 的枚举
#: 大概是按语料里出现过的取值列的，没出现过就没列）。0/1/2 是 `sin`/`cos`/`asin`，
#: **3 很可能是 `acos`**，但要测得先给 `EfxExpressionFunction` 加枚举项（vendor 补丁），
#: 没有语料样本之前不值得动（铁律 #5/#7）。
_UNKNOWN_FUNC_ARGC = {}


class ExprError(Exception):
    """公式语法本身有问题（vendor 语法之外的写法）——不是"变量/函数语义未知"，那种走 note。"""


class EvalContext(object):
    """一次求值需要的输入 + 输出."""

    __slots__ = ("variables", "unknown_func_policy", "clamp_mode", "notes")

    def __init__(self, variables, unknown_func_policy="identity", notes=None,
                 clamp_mode="remap_smoothstep"):
        #: 标识符 -> 数值。key 就是公式文本里出现的原样标识符
        #: （`TIMER`/`ext:302732036`/`p:2597296009`/已解析出名字的 `EM_SPEED` 等）。
        self.variables = variables
        self.unknown_func_policy = unknown_func_policy
        #: `Clamp` 怎么读，见 `_eval_ternary_known()` 和 `SimConfig.expr_clamp_mode`
        self.clamp_mode = clamp_mode
        #: **预览不静默撒谎**（铁律 #2 在只读侧的对应物，同 `EmitterState.note()`）：
        #: 未知变量、未确认语义的函数、被丢弃的第二根值都记在这里，去重按消息文本。
        self.notes = notes if notes is not None else []

    def note(self, msg):
        if msg not in self.notes:
            self.notes.append(msg)


class ParsedExpr(object):
    """`parse()` 的产物：一棵 `ast.Expression` + 可能存在的第二根值原始文本。"""

    __slots__ = ("tree", "second_branch")

    def __init__(self, tree, second_branch):
        self.tree = tree
        self.second_branch = second_branch


def _sanitize_identifiers(text):
    """vendor 标识符允许 `:`（`ext:`/`const:`/`p:`/`ukn:` 前缀），Python 标识符不允许——
    统一换成 `__`，求值时再原样换回来对变量表做 key。"""
    return text.replace(":", "__")


def _desanitize_identifier(name):
    return name.replace("__", ":", 1) if "__" in name else name


def _split_root_value(text):
    """在**括号外**找第一个 `|`，切成 (主支, 副支或 None)。不能用字符串 split——公式内容
    本身不含 `|`，但保险起见按括号深度过滤，避免误伤将来语法扩展。"""
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == _ROOT_VALUE_CHAR and depth == 0:
            return text[:i].strip(), text[i + 1:].strip()
    return text, None


def parse(formula_text):
    """公式文本 -> `ParsedExpr`。空文本/`None` 当常量 0 处理（vendor 默认值就是 `"0"`，
    见 `EFXExpressionCurveItem.formula` 的 `default="0"`）。"""
    text = (formula_text or "").strip() or "0"
    primary, secondary = _split_root_value(text)
    try:
        tree = ast.parse(_sanitize_identifiers(primary), mode="eval")
    except SyntaxError as exc:
        raise ExprError("公式语法错误：%s（原文：%r）" % (exc, primary)) from exc
    return ParsedExpr(tree, secondary)


def evaluate(parsed, ctx):
    """对 `parse()` 的产物求值，返回 float。"""
    if parsed.second_branch:
        ctx.note("公式带第二根值（'a | b'），语义未证实（vendor 自己也只是猜测），只用第一支")
    return _eval(parsed.tree.body, ctx)


def _eval(node, ctx):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError("不支持的字面量：%r" % (node.value,))
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return -_eval(node.operand, ctx)
        if isinstance(node.op, ast.UAdd):
            return _eval(node.operand, ctx)
        raise ExprError("不支持的一元运算符：%r" % (node.op,))
    if isinstance(node, ast.BinOp):
        a = _eval(node.left, ctx)
        b = _eval(node.right, ctx)
        if isinstance(node.op, ast.Add):
            return _eval_binary_operator("+", a, b, ctx)
        if isinstance(node.op, ast.Sub):
            return _eval_binary_operator("-", a, b, ctx)
        if isinstance(node.op, ast.Mult):
            return _eval_binary_operator("*", a, b, ctx)
        if isinstance(node.op, ast.Div):
            return _eval_binary_operator("/", a, b, ctx)
        raise ExprError("不支持的二元运算符：%r" % (node.op,))
    if isinstance(node, ast.Name):
        return _resolve_variable(node.id, ctx)
    if isinstance(node, ast.Call):
        return _eval_call(node, ctx)
    raise ExprError("不支持的语法节点：%r" % (type(node).__name__,))


def _resolve_variable(raw_name, ctx):
    name = _desanitize_identifier(raw_name)
    value = ctx.variables.get(name)
    if value is None:
        ctx.note("未知变量 %s，按 0.0 处理" % name)
        return 0.0
    return float(value)


def _eval_call(node, ctx):
    if not isinstance(node.func, ast.Name) or node.keywords:
        raise ExprError("不支持的函数调用形式：%s" % (ast.dump(node),))
    return _apply_call(node.func.id, [_eval(a, ctx) for a in node.args], ctx)


def _apply_call(fname, args, ctx):
    """参数**已经求好值**之后的函数派发。和 `_eval_call` 拆开是为了让
    `evaluate_rows()` 能复用同一套语义——那条路是自底向上一次遍历算完所有子树的值，
    不能再让每个节点自己去递归求参数（那样就退化成 O(N²) 了）。"""
    if fname in _BINARY_KNOWN_FUNCS:
        if len(args) != 2:
            raise ExprError("%s 需要 2 个参数，实际 %d 个" % (fname, len(args)))
        return _eval_binary_operator(fname, args[0], args[1], ctx)

    if fname in _KNOWN_UNARY_FUNCS:
        if len(args) != 1:
            raise ExprError("%s 需要 1 个参数，实际 %d 个" % (fname, len(args)))
        return _eval_known_unary(fname, args[0], ctx)

    if fname in _KNOWN_BINARY_FUNCS:
        if len(args) != 2:
            raise ExprError("%s 需要 2 个参数，实际 %d 个" % (fname, len(args)))
        return _eval_known_binary_func(fname, args[0], args[1], ctx)

    if fname == "Func21":
        if len(args) != 5:
            raise ExprError("Func21 需要 5 个参数，实际 %d 个" % len(args))
        return _eval_func21(args, ctx)

    if fname in _TERNARY_KNOWN_FUNCS:
        if len(args) != 3:
            raise ExprError("%s 需要 3 个参数，实际 %d 个" % (fname, len(args)))
        return _eval_ternary_known(fname, args, ctx)

    argc = _UNKNOWN_FUNC_ARGC.get(fname)
    if argc is not None:
        if len(args) != argc:
            raise ExprError("%s 需要 %d 个参数，实际 %d 个" % (fname, argc, len(args)))
        ctx.note("公式用到未确认语义的函数 %s，按 %s 策略处理"
                  % (fname, ctx.unknown_func_policy))
        return _apply_unknown_func_policy(args, ctx.unknown_func_policy)

    raise ExprError("不支持的函数：%s" % fname)


def _eval_ternary_known(fname, args, ctx):
    if fname == "Clamp":
        return _eval_clamp(args, ctx)
    if fname == "Lerp":
        # `Lerp(t, a, b)` == `b + (a - b) * saturate(t)`
        # **`t` 要钳在 `[0, 1]`，不做线性外推。** 这一点是 2026-09-16 收尾时才补上的：
        # 直接证据来自 `InvLerp`（同一个函数、系数在末位）的探针——`InvLerp(1, 0, x)`
        # 的 x 扫 -1→2，实机是"前端平在 0、中段斜升、后端平在 1"，两端都饱和。
        # 旁证是测 `Lerp` 线性那条（`Lerp(100 - TIMER, 1, 0)` 对 `TIMER/100`）末尾的折点：
        # `TIMER` 超过窗口后 `t > 1`，若外推则残差恒为 0（全程平），实机却折了下去。
        # ⚠ 之前的实现漏了钳位，而 `InvLerp` 那半边钳了——**同一个函数被写成两种行为**，
        # 是在给 vendor 写 issue、逐个核对签名时才发现的。
        t, a, b = args
        return b + (a - b) * max(0.0, min(1.0, t))
    # InvLerp(a, b, t) == b + (a - b) * saturate(t)  —— 就是 `Lerp`，只是插值系数挪到
    # 了最后一个参数。**名字是错的**，它不做任何"反向"的事（2026-09-16 实机确认）。
    a, b, t = args
    return b + (a - b) * max(0.0, min(1.0, t))


def _eval_clamp(args, ctx):
    """`Clamp(value, hi, lo)` —— **不是"夹到 [lo,hi] 之间"，是把 value 从 `[lo, hi]`
    重映射到 `[0, 1]`，且两端都饱和**。

    名字是 vendor 在 `EfxExpressionFunction` 枚举里起的（值 17），和 `Unary*` 一样属于
    "vendor 给了个名字"而不是"vendor 确认了语义"，但**上界饱和这一点已经实机确认**
    （2026-09-16）：搭了两条 `Lerp(Clamp(TIMER, hi, 0), -1, 0.5)` 驱动的粒子轨迹，`hi`
    从 15 翻倍到 30，两条轨迹的**终点位置完全相同，只有到达终点所需的时间翻倍**——
    如果上界不钳，`hi` 翻倍会让同一个 `TIMER` 算出的 `t` 减半、最终稳定值也会跟着变
    （`t` 会持续超过 1 并线性上冲，不会停在同一个点），实测直接排除了这个可能。
    **下界饱和后来单独测过了**（2026-09-16 同日收尾）：`Clamp(Lerp(100 - TIMER, 1, -1), 1, 0)`
    的输入从 -1 扫到 +1、`lo = 0`，前半段整个落在下界以下——实测**贴在 0**，不是跑成
    负值。所以两端饱和现在都是实机确认的。

    全语料证据（1044 个官方 .efx、3882 条公式实例，`_eval_clamp` 引入时的原始依据）：

    - **参数顺序是语义固定的**：边界都是字面量的 1493 例里，第 2 参 > 第 3 参占 1493/1493，
      一个反例都没有。
    - `Min(Clamp(...), 1)` 这个写法出现 95 次——当时用来反推"上界不钳"的证据，现在被实机
      结果推翻，只能解释成作者手写的防御性冗余封顶（多写一层不影响正确性，只是没必要）。
    - `Lerp(Clamp(EM_SPEED, 6, 3), 0, 8)` 的输出落在它自己写的 `[0, 8]`（旧字面夹紧读法
      算出 `[24, 48]`，大 3~6 倍），这条证据不受这次修正影响，仍然支持"是重映射、不是字面
      夹紧"这个大方向，只是上界钳不钳这一细节从"不钳"改成"钳"。

    下界：语料里 `Max(Clamp(...), 0)` 一次都没有，方向和上界现在的实机结果一致，但仍是
    **间接证据**（见上面那条 ⚠），不是独立测过的。

    `bounds_clamp`/`remap_unclamped`/`remap_saturate_low`（旧默认，已被推翻）三档保留用于
    对拍，见 `SimConfig.expr_clamp_mode`。逐条证据见 docs/EXPRESSION_SEMANTICS.md。
    """
    value, hi, lo = args
    if ctx.clamp_mode == "bounds_clamp":
        a, b = (lo, hi) if lo <= hi else (hi, lo)
        return min(max(value, a), b)
    if hi == lo:
        ctx.note("Clamp 的两个边界相等（%g），重映射除零，按 0.0 处理" % hi)
        return 0.0
    t = (value - lo) / (hi - lo)
    if ctx.clamp_mode == "remap_smoothstep":
        u = max(0.0, min(1.0, t))
        return u * u * (3.0 - 2.0 * u)
    if ctx.clamp_mode == "remap_saturate_both":
        return max(0.0, min(1.0, t))
    if ctx.clamp_mode == "remap_saturate_low":
        return max(0.0, t)
    return t


#: vendor 文本符号 -> (真实语义的说明, 实现)。**六个二元操作码没有一个是 vendor 标的
#: 那个意思**，见 `_eval_binary_operator()` 的完整判据表。
_BINARY_OPERATOR_SEMANTICS = ("+", "-", "*", "/", "Min", "Max")


def _eval_binary_operator(symbol, a, b, ctx):
    """求值一个二元运算。`a` 是 vendor 文本里的**左**操作数、`b` 是**右**操作数。

    **vendor 给这六个操作码起的名字全部是错的**（2026-09-16 实机逐个测出来）：

    ==========  ==========  =================  ==============================
    操作码      文本写法    vendor 叫它        真实语义
    ==========  ==========  =================  ==============================
    0           ``Max(a,b)``  Max              ``pow(b, a)``（指数是左操作数）
    1           ``a + b``     Add              ``a * b``
    2           ``a - b``     Sub              ``b / a``（被除数是右操作数）
    3           ``a * b``     Mul              ``fmod(b, a)``（模数是左操作数）
    4           ``a / b``     Div              ``a + b``
    5           ``Min(a,b)``  Min              ``b - a``（被减数是右操作数）
    ==========  ==========  =================  ==============================

    **真正的 min/max 在这套表达式里根本不存在。**

    把操作数顺序翻过来（引擎的操作数顺序和 vendor 的 left/right 相反），六个操作码是
    **幂、乘、除、模、加、减**——严格的优先级降序，像是引擎按优先级排的枚举。vendor
    自己在 `BinaryExpressionOperator`（`ExpressionTree.cs:11`）上写着 "Am not 100% sure
    on the exact operators for 1-4 but they seem reasonable"，实际连它有把握的 0 和 5
    也错了。

    实机判据（Y 轴 `Lerp(Clamp(TIMER, 15, 0), 0.5, -1)` 当时间轴、Z 轴填被测公式、单粒子
    `TypeRibbonFollow` 的轨迹当示波器，读数靠"直接填常量"对照校准）。每个操作码都用
    交换操作数的对照点钉住，`(a, b) -> 结果`：

    - 操作码 1（`+`）：``(1,0)->0``、``(0,1)->0``、``(1,1)->1``、``(1,2)->2``、
      ``(2,1)->2``。对称，且乘法是唯一同时满足五点的读法（加法在 ``(1,0)`` 就该给 1）。
    - 操作码 2（`-`）：``(1,2)->2`` 而 ``(2,1)->0.5``，**非交换**，正好是 ``b/a``。
      ``(0,1)->0`` 说明**除零按 0**（``1/0`` 实测是 0，不是 inf/NaN）。
    - 操作码 3（`*`）：``0.4*0.5->0.1``、``0.5*0.4->0.4``，非交换；决定性的一组是
      ``X * 1`` 随 X 变化**非单调**——X=0.6/0.5/0.4/0.3 实测 0.4/0/0.2/0.1，正好是
      ``fmod(1, X)``。符号取被除数（C 语义）：``2 * sweep`` 里 sweep 从 -1 扫到 0.5
      实测原样透传，**所以必须用 `math.fmod`，不能用 Python 的 `%`**。
    - 操作码 4（`/`）：``(1,0)->1``、``(1,1)->2``、``(2,0)->2``，对称，是加法。
    - 操作码 5（`Min`）：``(1,0)->-1``、``(0,1)->1``、``(1,1)->0``、``(1,2)->1``、
      ``(2,1)->-1``，正好是 ``b-a``。
    - 操作码 0（`Max`）：``(1,0)->0``、``(0,1)->1``、``(1,1)->1``、``(1,2)->2``、
      ``(2,1)->1``。这五点 ``pow(b,a)`` 和"直接返回 b"都满足，**是语料把它定下来的**：
      全部 3 处 `Max(` 用法的第一个参数都是小整数指数——`Max(2, Unary9(Unary0(...)))`、
      `Max(2, Lerp(...))`、`Func21(..., Max(4, FinishRate))`——按 ``pow`` 读是"归一化值
      取平方/四次方"（缓动曲线的标准写法），按"返回 b"读这三个指数全是死参数
      （退化用法反推语义，同 `_eval_clamp()` 那条）。所以 0 是 `corpus` 档不是
      `confirmed`，见 `BINARY_OPERATOR_CONFIDENCE`。

    语料侧的总体佐证——按这张表把真实公式翻译成常规记法，全都变成教科书写法，
    按 vendor 的旧读法则大量退化（逐条见 docs/EXPRESSION_SEMANTICS.md 第 9 节）：

    - ``(6 - Unary0(((2 - PI) / (100 - TIMER))))`` -> ``sin(PI/2 + TIMER/100) / 6``
      （经典的 PI/2 相移把 sin 变 cos）
    - ``(1 / (0.1 + Unary0((0.01 + TIMER))))`` -> ``1 + 0.1*sin(0.01*TIMER)``
    - ``Lerp(Clamp(Unary0((0.8 + TIMER)), 1, -1), 2, 1)``：``Clamp`` 的边界正好是
      ±1 = 正弦值域，把它归一化再映到 1~2
    - ``Min(Clamp(TIMER, 100, 20), 1)`` -> ``1 - Clamp(TIMER, 100, 20)``：这个全语料
      出现 95 次的写法，真身是最常见的**淡出** ``1 - t``（以前被当成"作者手写的防御性
      封顶"，还当过"Clamp 上界不钳"的证据）
    - ``(0.5 / (0.2 + EM_INIRAND))`` -> ``0.5 + 0.2*EM_INIRAND``（基准值加随机扰动）
    - ``(3 + IsConst)`` -> ``3 * IsConst``（用 0/1 标志位门控一个值）

    ⚠ **文本里的符号必须原样保留**（`+ - * /` / `Min(` / `Max(`）——那是 vendor 解析器
    认的字面量，换符号就往返不回去。这里只改"这些符号算什么"。
    """
    if symbol == "+":                       # 操作码 1 = 乘
        return a * b
    if symbol == "-":                       # 操作码 2 = 除（被除数是右操作数）
        if a == 0:
            ctx.note("公式除零（`-` 实为 `右/左`，左操作数是除数），按 0.0 处理")
            return 0.0
        return b / a
    if symbol == "*":                       # 操作码 3 = 取模（模数是左操作数）
        if a == 0:
            ctx.note("公式取模的模数为 0（`*` 实为 `fmod(右, 左)`），按 0.0 处理")
            return 0.0
        return math.fmod(b, a)
    if symbol == "/":                       # 操作码 4 = 加
        return a + b
    if symbol == "Min":                     # 操作码 5 = 减（被减数是右操作数）
        return b - a
    if symbol == "Max":                     # 操作码 0 = 幂（指数是左操作数）
        ctx.note("公式用到 `Max(a, b)`（实为 `pow(b, a)`，语料推断、未实机独立确认）")
        try:
            result = float(b) ** float(a)
        except (OverflowError, ValueError, ZeroDivisionError):
            ctx.note("`Max(a, b)`（实为 `pow(b, a)`）的幂运算无定义，按 0.0 处理")
            return 0.0
        if result != result or result in (float("inf"), float("-inf")):
            ctx.note("`Max(a, b)`（实为 `pow(b, a)`）算出 NaN/Inf，按 0.0 处理")
            return 0.0
        return result
    raise ExprError("不支持的二元运算符：%r" % (symbol,))


def _eval_known_binary_func(fname, a, b, ctx):
    """`Func18` = `min(a, b)`、`Func19` = `max(a, b)`、`Func20` = `pow(b, a)`
    （2026-09-16 实机确认）。前两个**对称**，不存在"哪个参数在前"的问题；`Func20` 的
    **底数是右操作数、指数是左操作数**（和其他非对称运算一致：引擎的第一操作数 =
    vendor 文本的第二个参数）。

    `Func20` 的判据：`Func20(x, 0.5)` 随 `x` 增大**单调下降**，且把 `x` 扫到 -4 时起点
    跑到画面外很高处（`0.5^-4 = 16`，/8 之后是 +2.0）。**无界**排掉了 `atan2(b, a)`
    （有界 <= pi，全程留在 ±0.5 的可视带里）；起点为正、中途无极点排掉了 `b / a`
    （起点在轴下方、`x=0` 处有极点）。语料里它只和 `SpawnExpression` 搭配、第二参恒为 3：
    `Func20((0.01 + TIMER), 3)` = `3^(0.01*TIMER)`，一条平缓的指数上升。

    ⚠ **`Func20` 和 `Max(a, b)`（操作码 0）现在读法完全相同，这是个未解决的疑点。**
    操作码 0 的 5 个实机点（`(1,0)->0`、`(0,1)->1`、`(1,1)->1`、`(1,2)->2`、`(2,1)->1`）
    同时满足 `pow(b,a)` 和"直接返回 b"，当初是靠语料 idiom（3 处 `Max(` 的左参都是小整数
    指数）选了 `pow`。既然 `Func20` 已确认是 `pow(b,a)`，引擎给同一个运算开两个入口就很
    反常——**操作码 0 更可能是"直接返回 b"**，而那正是**栈失衡**的签名（同最早 `Func21`
    那次"结果恒等于末尾常量"的现象：不是 2 参运算的话，留在槽位里的就是最先入栈的那个
    操作数，也就是 vendor 文本的右操作数）。
    待测探针：`Max(2, <从 -1 扫到 +1 的量>)` —— `pow` 给 **U 形抛物线**（+1→0→+1，
    全程非负）、"返回 b" 给**直线**（-1→+1，一半在轴下方）。测完再定操作码 0 的读法。

    **这两个填上了一个显眼的空缺**：二元操作码 0~5 里根本没有 min/max
    （见 `_eval_binary_operator()` 的表），而任何 VFX 表达式语言都少不了这两个——
    它们藏在函数写法里。注意**别和文本里的 `Min(`/`Max(` 搞混**：那两个名字是
    vendor 给操作码 5/0 起的，实际是减法和幂。

    实机判据（输入换成从 -1 扫到 +1 的量、第二参固定 0.5，看**形状**而不是数值——
    这样绕开了"读不准高度"和"跑出画面"两个问题，而 min/max 的图形正好是镜像）：

    - `Func18(sweep, 0.5)`：斜线升到 +0.5 后**变平**（``/‾``）-> `min`
    - `Func19(sweep, 0.5)`：**先平**在 +0.5、后半段继续升到 +1（``_/``）-> `max`

    交换两个参数结果不变（实测），排掉全部非对称候选（`fmod`/`pow`/`atan2`/除法）；
    ``hypot`` 会是 V 字、``a+b``/``a*b``/``a/b`` 会是直线，都和实测形状不符。

    语料退化检验同样支持：

    - `Func18(Lerp(Unary10((0.05 + TIMER)), 20, 1), 20)` =
      `min(1→20 的斜坡, 20)` —— 给斜坡封顶（末端刚好触到）。按 `max` 读则恒等于 20，
      整条斜坡作废。
    - `Func19(Length, 0)` = `max(Length, 0)` —— **"钳到非负"的标准写法**。按 `min` 读
      在 `Length >= 0` 时恒为 0，纯退化。
    - `Func19((16 - Length), 0.17)` = `max(Length/16, 0.17)` —— 给下限。
    """
    if fname == "Func20":
        try:
            result = float(b) ** float(a)
        except (OverflowError, ValueError, ZeroDivisionError):
            ctx.note("`Func20`（实为 `pow(b, a)`）的幂运算无定义，按 0.0 处理")
            return 0.0
        if result != result or result in (float("inf"), float("-inf")):
            ctx.note("`Func20`（实为 `pow(b, a)`）算出 NaN/Inf，按 0.0 处理")
            return 0.0
        return result
    return float(_KNOWN_BINARY_FUNCS[fname](a, b))


def _eval_func21(args, ctx):
    """`Func21(a, b, hi, lo, t)` == `Lerp(Clamp(t, hi, lo), a, b)`：把 `t` 从 `[lo, hi]`
    重映射到 `[0, 1]`（两端饱和），再在 `b`（t 在 lo 端）和 `a`（t 在 hi 端）之间**线性**
    插值。也就是"融合了 `Clamp` 和 `Lerp` 的一个五参算子"。2026-09-16 实机确认。

    判据是一次**放大残差的零差检验**（这个手法比直接比对两条曲线灵敏得多，值得复用）：
    拿已确认语义搭一条参考曲线，和被测量相减，再乘一个大系数放到同一块屏幕上判读。

    ::

        Y = 20 + Min(90 - Func21(90, 0, 60, 0, TIMER),
                     2 - Min(Unary12(180 + Clamp(TIMER, 60, 0)), 1))

    （`+` 是乘、`-` 是除、`Min(a,b)` 是 `b-a`，见 `_eval_binary_operator()`；所以这条是
    `20 * ((1-cos(180°·t))/2 - Func21(...)/90)`，参考曲线那半边是角度制正弦缓动，
    已用本模块逐帧核对过。）三种候选给出三个完全不同的图形：

    ==========================  =========================================
    实机看到的 Y                结论
    ==========================  =========================================
    **一个周期、±2 的正弦**     `Func21` 是**线性**插值（t=0.25 谷 -2.07、
                                t=0.75 峰 +2.07、两端归 0 —— 这正是
                                "正弦缓动 - 线性" 残差本身的形状）
    ±0.2 的小起伏               smoothstep（`3t²-2t³`）
    完全平在 0                  正弦缓动
    ==========================  =========================================

    实机读到的是第一行，所以**线性**。⚠ 在这次零差检验之前，同一个量用
    `90 - Func21(90, 0, 60, 0, TIMER)` 直接画形状，被读成了"躺倒的正弦曲线"——那是
    **判读误差**（纵轴 1 米、横轴 4 米的浅斜线看着像缓 S）。教训：**形状判读顶不住
    定量结论，两条曲线相减再放大才顶得住**。

    语料回读：`Unary11(Func21(90, 0, hi, 0, TIMER))`（高频写法）= `sin(角度)`，角度在
    `hi` 帧内从 0° 线性升到 90°，取正弦得到 0→1 的缓出曲线。`Unary11` 是角度制 sin
    （见 `_eval_known_unary()`），所以那个 `90` 是**度数**——这条以前完全读不通的公式
    现在每个数字都有解释了。

    ⚠ **`Func21` 不是 `Lerp(Clamp(t, hi, lo), a, b)`**，虽然它长得像。2026-09-16 用
    `TIMER` 当独立线性基准（`100 - TIMER` == `TIMER/100`，不经过任何待测函数）分别测出：

    ====================  =========================  ================
    被测                  残差 vs 线性基准（放大 ×3） 结论
    ====================  =========================  ================
    `Lerp(TIMER/100,1,0)` 纹丝不动                   `Lerp` 线性
    `Func21(1,0,100,0,t)` 纹丝不动                   **`Func21` 线性**
    `Clamp(TIMER,100,0)`  S 形摆动 ±0.3              **`Clamp` 带缓动**
    `Lerp(Clamp(...),1,0)` S 形摆动（同上）          摆动来自里面的 `Clamp`
    ====================  =========================  ================

    所以这里**故意不复用 `_eval_clamp()`**——`Clamp` 带 smoothstep、`Func21` 不带，
    两者的差别就是这层缓动。`SimConfig.expr_clamp_mode` 的对拍档**不影响** `Func21`。
    """
    a, b, hi, lo, t = args
    if hi == lo:
        ctx.note("Func21 的 hi/lo 相等（%g），重映射除零，按 0.0 处理" % hi)
        return 0.0
    # **不能复用 `_eval_clamp()`**：`Clamp` 的重映射带 smoothstep 缓动，`Func21` 的是
    # 线性的（2026-09-16 实机分别测出来的，见下面 docstring 的判据表）。这两个函数的
    # 差别**就是**这层缓动——这也是 `Func21` 存在的理由。
    u = max(0.0, min(1.0, (t - lo) / (hi - lo)))
    return b + (a - b) * u


def _eval_known_unary(fname, x, ctx):
    """已实机测出语义的 1 参函数。**vendor 的 `Unary<N>` 只是编号，不是名字**
    （枚举注释原话："unary potential candidates: sin/cos/tan/atan2/inverse/…"）。

    ========  ==============  ================================================
    代号      真实语义        实机判据（`_KNOWN_UNARY_EVIDENCE` 里有原始读数）
    ========  ==============  ================================================
    Unary0    ``sin``（弧度）  圆测试 + [-2,2] 宽扫的谷/峰位置
    Unary1    ``cos``（弧度）  同上，配 Unary0 画出整圆
    Unary2    ``asin``（弧度）  输入扫 0->1.4 时在**画面内**消失，消失前最后值 1.4416
    Unary4    ``floor``       [-2,2] 阶梯，第一个完整台阶在 -2
    Unary5    ``ceil``        [-2,2] 阶梯，第一个完整台阶在 -1
    Unary6    ``ln``          Unary6(Unary8(t)) 复合是恒等（终点恰好 1.0）
    Unary8    ``exp``         宽扫起点 0.14 == e^-2
    Unary9    ``abs``         宽扫画出直线 V 字
    Unary10   ``saturate``    宽扫呈 ``_/‾``（clamp01）；**全语料最高频**，
                              语料里 ``saturate(0.016*TIMER)`` 就是"62 帧淡入"
    ========  ==============  ================================================

    **圆测试**（一次同时验四件事）：``Y = Unary0(6.28319 + Clamp(TIMER,120,0))``、
    ``Z = Unary1(同)``（`+` 是乘法，所以这是 ``sin/cos(2*pi*t)``）实机画出**半径 1 米的
    整圆**，且**起点在侧面**——起点在侧面就说明 `Unary0(0)=0`（sin），在顶/底则是 cos。
    圆能闭合同时证明了：这两个是一对正余弦、吃的是**弧度**（角度制下 2pi 度只有 6°，
    只会画出一个点）、`+` 真的是乘法、`Clamp` 真的是 `[lo,hi]->[0,1]` 的重映射。

    ``Unary7`` 的底数同样靠复合定：``Unary7(Unary8(t))`` 实机终点 **0.434** ==
    ``log10(e)``（`ln` 会是 1.0、`log2` 会是 1.443）。

    ``Unary11``/``Unary12`` 是**角度制**的 sin/cos：`[-2,2]` 宽扫时分别恒 0 / 恒 1
    （``sin(2°)=0.035``、``cos(2°)=0.9994``，肉眼就是 0 和 1），把扫描范围放到
    `[-180,180]` 之后实机画出完整三角波。语料侧的佐证：``Unary11`` 被喂的正是
    ``Func21(90, 0, hi, 0, TIMER)`` —— **`90` 是度数**，``sin(0°→90°)`` 就是 0→1 的缓入。

    ``Unary2`` 是靠**定量**的消失点定下来的：输入扫 `0 -> 1.4`、Y 整体下移 1 米之后，
    实机"升到 +0.4~0.5 时粒子直接消失"。`asin` 在 x>1 无定义，算下来是第 86/120 帧
    消失、消失前最后一个值 1.4416（显示 **+0.4416**），正落在读数区间里。其余候选全部
    和现象矛盾：`tan` 第 95 帧就冲出画面上边界（值 2.0）、`atanh` 第 83 帧冲出且消失前
    的值是 1.74、`atan` 根本不消失（终点 -0.05）、`acos` 是往下走到 -0.87 才消失。
    ⚠ 这条差点被判成"画面边界伪装成无定义"——**关键是消失点在画面内还是边界上**，
    判读前要先确认可视范围的上界在哪。

    `trunc` 这个同形候选两边都被排掉了：``Unary4`` 靠"宽扫第一个完整台阶在 -2"
    （``trunc(-1.9) = -1``）、``Unary5`` 靠第一轮 `[0,1]` 的"恒为 1"
    （``trunc(0.3) = 0``）。``Unary9`` 的 ``max(|x|,1)`` 候选靠"输入缩到 `[-0.5,0.5]`
    之后是顶点贴 0 的小 V"排掉（平底 U 会是一条平在 1 的线）。

    定义域兜底一律"记 note + 返回 0"，和除零/取模除零同一套：NaN/Inf 会顺着位置字段
    传进视口和导出，不能放过去。
    """
    if fname == "Unary2":
        if x < -1.0 or x > 1.0:
            ctx.note("`Unary2`（实为 asin）的输入超出 [-1, 1]，无定义，按 0.0 处理")
            return 0.0
        return math.asin(x)
    if fname in ("Unary6", "Unary7"):
        base_name = "ln" if fname == "Unary6" else "log10"
        if x <= 0:
            ctx.note("`%s`（实为 %s）的输入 <= 0，无定义，按 0.0 处理" % (fname, base_name))
            return 0.0
        return math.log(x) if fname == "Unary6" else math.log10(x)
    if fname == "Unary8":
        try:
            return math.exp(x)
        except OverflowError:
            ctx.note("`Unary8`（实为 e^x）溢出，按 0.0 处理")
            return 0.0
    return float(_KNOWN_UNARY_FUNCS[fname](x))


def _apply_unknown_func_policy(args, policy):
    if policy == "identity":
        return args[0] if args else 0.0
    raise ExprError("未知的 expr_unknown_func_policy：%r" % (policy,))


# ---------------------------------------------------------------------------
# 结构化编辑支持 —— parse() 的逆函数 + 扁平行视图
# ---------------------------------------------------------------------------
# 为什么和解析器放同一个模块（而不是 blender_efx_re/ 那层）：文本格式化要逐条复刻 vendor
# `ExpressionAtom.ToString()` 的括号/空格规则，和 `parse()` 认的语法是同一份约定。拆到两个
# 包里，改一边忘另一边的产物就是"和原文本只差一对括号"——那种 bug 不报错、只在逐字节门禁
# 里露一下头。放这儿还顺带被 `python -m unittest discover -s tests` 覆盖到
# （`blender_efx_re/__init__.py` import bpy，那层脱离 Blender 根本 import 不动）。
#
# **文本仍然是唯一的权威形式**：结构化编辑器改完行以后必须走 `from_rows()` 写回
# `EFXExpressionCurveItem.formula`，导出路径只读那个字符串（见
# `io_tree._export_expression_attribute()`）。行视图是"文本的一个视图"，不是并行的第二份
# 数据——这样编辑器出 bug 的最坏结果是吐出一段不同的**文本**，会被 `exprcheck` / 桥接
# 当场拒绝或被字节门禁抓住，而不是绕过文本偷偷改二进制。

#: vendor `ExpressionRootValueOption.ToString()` 的连接符（`ExpressionTree.cs:269`，
#: 两边各两个空格）。`_split_root_value()` 两侧都 strip 过，原样拼回去才能复原原文本。
_ROOT_VALUE_SEPARATOR = "  |  "

#: `ast` 二元运算符 -> vendor 文本符号。vendor 只有这四个中缀运算符
#: （`BinaryExpressionOperator` 的 Add/Sub/Mul/Div，Min/Max 走函数写法）。
#: ⚠ **`*` 实际是取模**（`A * B` == `fmod(B, A)`，见 `_eval_mod_operator()`），符号本身
#: 不能改——vendor 解析器只认这个字面量。
_OP_SYMBOLS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}

#: 中缀运算符符号集合（行视图里和函数名共用 `name` 字段，靠在不在这个集合里区分写法）
BINARY_OPERATORS = ("+", "-", "*", "/")


#: 置信度分层，逐条依据见模块 docstring 和 docs/EXPRESSION_SEMANTICS.md。
#: **UI 要如实展示这一层，四档不能画成一个样**（铁律 #7）。
CONFIDENCE_CONFIRMED = "confirmed"      # 语义完全确认（运算符本身 + Min/Max）
CONFIDENCE_CORPUS = "corpus"            # 语料一致性推断：有成规模的正面证据、零反例，但没实机确认
CONFIDENCE_UNDECIDED = "undecided"      # 语料里有互相矛盾的用法，读法未定
CONFIDENCE_UNKNOWN = "unknown"          # 纯数字占位，vendor 自己也只给了候选猜测

#: 中缀运算符 -> 置信度。四个符号的**真实语义**全部实机确认过一遍，而且**全都不是
#: vendor 标的那个意思**（`+`=乘、`-`=除、`*`=取模、`/`=加），逐点判据见
#: `_eval_binary_operator()`。函数写法的 `Min`（=减）同样实机确认；`Max`（=幂）是语料
#: 推断，走 `CALL_SIGNATURES`。
BINARY_OPERATOR_CONFIDENCE = {
    "+": CONFIDENCE_CONFIRMED,   # 操作码 1，实为 `a * b`
    "-": CONFIDENCE_CONFIRMED,   # 操作码 2，实为 `b / a`
    "*": CONFIDENCE_CONFIRMED,   # 操作码 3，实为 `fmod(b, a)`
    "/": CONFIDENCE_CONFIRMED,   # 操作码 4，实为 `a + b`
}

#: 调用名 -> (参数个数, 置信度)。中缀运算符不在这里，走 `BINARY_OPERATORS`（恒 2 参）+
#: `BINARY_OPERATOR_CONFIDENCE`（**逐符号一档，不是恒 confirmed**）。参数个数来自
#: `EfxExpressionParser.cs` 的 `functionArgCount`。
#:
#: `Lerp`/`Clamp` 是 `corpus` 不是 `confirmed`：名字是 vendor 在枚举里起的，语义靠全语料
#: 1044 个文件 / 3882 条公式实例反推（`Clamp` 那条的决定性判据是 95 处
#: `Min(Clamp(...), 1)` 在"夹住"读法下全是空操作）。`InvLerp` 是 `undecided`：语料里
#: `InvLerp(Length, 65, 20)` 和 `InvLerp(1, 0.5, Min(Clamp(...), 1))` 两种用法互斥，
#: 样本只有 ~91 条，**没定，别动**。
CALL_SIGNATURES = {
    # 名字全是错的：`Min(a,b)` 实为 `b - a`（操作码 5）、`Max(a,b)` 实为 `pow(b, a)`
    # （操作码 0，`Max(2, <扫描>)` 画出 U 形抛物线实机确认）。见 `_eval_binary_operator()`。
    "Min": (2, CONFIDENCE_CONFIRMED),
    "Max": (2, CONFIDENCE_CONFIRMED),
    # `Lerp`：方向、线性、`t` 在第 1 位、`t` 两端饱和，四点全部实机确认
    "Lerp": (3, CONFIDENCE_CONFIRMED),
    # `Clamp`：重映射 + **两端**饱和 + 中段 smoothstep，全部实机确认。下界那一半是最后
    # 补上的（`Clamp(Lerp(100 - TIMER, 1, -1), 1, 0)`，输入扫 -1→+1、`lo=0`，实测前半段
    # 贴在 0 而不是跑成负值）。
    "Clamp": (3, CONFIDENCE_CONFIRMED),
    # `InvLerp` 就是 `Lerp`、系数在最后一个参数（实机确认）
    "InvLerp": (3, CONFIDENCE_CONFIRMED),
}
CALL_SIGNATURES.update(
    (name, (argc, CONFIDENCE_UNKNOWN)) for name, argc in _UNKNOWN_FUNC_ARGC.items()
)
#: 实机测出语义的 1 参函数（见 `_eval_known_unary()`）。**11 个里 11 个都实机确认过**，
#: 同形候选（`trunc` / `max(|x|,1)`）都被具体读数排掉了，逐条判据见
#: `_KNOWN_UNARY_EVIDENCE`。只剩 `Unary2` 还在未知表里。
CALL_SIGNATURES.update(
    (name, (1, CONFIDENCE_CONFIRMED)) for name in _KNOWN_UNARY_FUNCS
)
#: `Func21(a, b, hi, lo, t)` == `Lerp(Clamp(t, hi, lo), a, b)`，实机零差检验确认，
#: 见 `_eval_func21()`。
CALL_SIGNATURES["Func21"] = (5, CONFIDENCE_CONFIRMED)
#: `Func18` = `min`、`Func19` = `max`，实机确认，见 `_eval_known_binary_func()`。
CALL_SIGNATURES.update((name, (2, CONFIDENCE_CONFIRMED)) for name in _KNOWN_BINARY_FUNCS)

#: 行视图的节点种类
KIND_CONST = "CONST"    # 浮点字面量
KIND_VAR = "VAR"        # 标识符（具名参数 / 内置外部变量 / `ext:<hash>` 占位）
KIND_NEG = "NEG"        # 一元负号，恒 1 个子节点
KIND_CALL = "CALL"      # 中缀运算符（`name` 在 BINARY_OPERATORS 里）或函数调用


def call_arity(name):
    """调用名 -> 参数个数。不认识的名字返回 None（调用方自己决定是拒绝还是沿用现有个数）。"""
    if name in BINARY_OPERATORS:
        return 2
    sig = CALL_SIGNATURES.get(name)
    return sig[0] if sig else None


def call_confidence(name):
    """调用名 -> 置信度档位。不认识的名字按"未确认"处理，不装作知道。"""
    if name in BINARY_OPERATORS:
        return BINARY_OPERATOR_CONFIDENCE[name]
    sig = CALL_SIGNATURES.get(name)
    return sig[1] if sig else CONFIDENCE_UNKNOWN


def format_float(value):
    """镜像 vendor `ExpressionFloat.ToString()`（`ExpressionTree.cs:112`）：`F6` 定点、
    去掉尾随 0、只剩小数点就连小数点一起去。

    **不要换成 `repr()` / `%g`**——文本是导出时唯一写进 JSON 的东西，格式一变产物字节就跟着
    变，而且 `F6` 这个 6 位小数上限是 vendor 文本形式本来就有的天花板（不是这里引入的）。
    """
    text = "%.6f" % float(value)
    text = text.rstrip("0")
    if text.endswith("."):
        text = text[:-1]
    return text or "0"


def emit_parsed(parsed):
    """`parse()` 的逆函数：`ParsedExpr` -> vendor 公式文本。

    **走行视图绕一圈**（`from_rows(to_rows(...))`）而不是另写一个 AST 遍历器。以前这里
    真有两个并行的 emitter（一个吃 AST、一个吃行），格式规则各写一遍——两边漂了只会在
    "文本变了但二进制没变"这种地方露头，而字节门禁对它免疫（`(1.5 - Length)` 少一对括号，
    桥接重新解析出来的树一模一样，产物字节完全相同）。合成一个就没有"漂"这回事。

    格式规则本身逐条复刻 vendor `ExpressionAtom.ToString()`，见 `_emit_rows()`。
    第二根值（`a | b`）原样带回去——语义没证实不等于可以丢（铁律 #2）。
    """
    return from_rows(to_rows(parsed), parsed.second_branch)


def evaluate_rows(parsed, ctx):
    """一次遍历算出**每一行子树**在当前变量下的值，返回 `[值 或 None, ...]`，
    下标和 `to_rows()` 的行下标一一对应。

    **为什么必须是一次遍历**：面板的"结构树变调试器"要显示每一行自己那支算出多少。
    原来的做法是"对每一行重建子树文本 -> 重新解析 -> 求值"，那是 **O(N²)**——实测
    225 行 8 ms、449 行 18 ms、897 行 48 ms（而完整求值一次只要 0.45 ms）。面板每次
    重绘都跑一遍，公式一复杂界面就肉眼可见地卡。这条路径改成自底向上一次算完，
    复杂度降到 O(N)。

    遍历顺序必须和 `_collect_rows()` **逐字一致**（前序，且 `-字面量` 折叠成一行），
    否则行下标会错位。两边由 `tests/test_sim_expr_edit.py` 的等价性测试钉住。

    单个节点算不出来（比如未知函数抛 `ExprError`）时该行记 `None`，**不影响其他行**——
    调试器要能显示"这一支坏了、别的支还好"。
    """
    out = []
    _eval_collect(parsed.tree.body, ctx, out)
    return out


def _eval_collect(node, ctx, out):
    """前序占位 -> 递归子节点 -> 回填自己的值。返回本节点的值（算不出来返回 None）。"""
    slot = len(out)
    out.append(None)

    if isinstance(node, ast.Constant):
        try:
            value = _eval(node, ctx)
        except ExprError:
            value = None
        out[slot] = value
        return value
    if isinstance(node, ast.Name):
        value = _resolve_variable(node.id, ctx)
        out[slot] = value
        return value
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub):
            return None
        if isinstance(node.operand, ast.Constant) and not isinstance(
                node.operand.value, bool) and isinstance(node.operand.value, (int, float)):
            # 和 `_collect_rows()` 一样把 `-字面量` 折叠成**一行**，不能多占一个槽位
            value = -float(node.operand.value)
            out[slot] = value
            return value
        inner = _eval_collect(node.operand, ctx, out)
        value = None if inner is None else -inner
        out[slot] = value
        return value
    if isinstance(node, ast.BinOp):
        a = _eval_collect(node.left, ctx, out)
        b = _eval_collect(node.right, ctx, out)
        symbol = _OP_SYMBOLS.get(type(node.op))
        if symbol is None or a is None or b is None:
            return None
        try:
            value = _eval_binary_operator(symbol, a, b, ctx)
        except ExprError:
            value = None
        out[slot] = value
        return value
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            return None
        args = [_eval_collect(a, ctx, out) for a in node.args]
        if any(a is None for a in args):
            return None
        try:
            value = _apply_call(node.func.id, args, ctx)
        except ExprError:
            value = None
        out[slot] = value
        return value
    return None


def to_rows(parsed):
    """`ParsedExpr` -> 扁平的前序行列表，每行一个 dict：

        {"kind": KIND_*, "depth": int, "arity": int, "name": str, "value": float}

    为什么是扁平前序 + `arity`（子节点个数）而不是嵌套结构：Blender 的
    `CollectionProperty` 装不了递归类型，而前序 + arity 是树的一种无歧义线性编码，
    重建只要顺序消费一遍。`depth` 纯粹给面板算缩进用，不参与重建（重建只看 arity）。

    ⚠ **行和 AST 节点不是一一对应的**：`-1`（AST 里是 USub 套 Constant）折叠成**一行**
    带符号常量，见 `_collect_rows()` 里的说明。`-TIMER`（USub 套标识符）折不了，仍是两行。
    """
    rows = []
    _collect_rows(parsed.tree.body, 0, rows)
    return rows


def _collect_rows(node, depth, rows):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError("不支持的字面量：%r" % (node.value,))
        rows.append({"kind": KIND_CONST, "depth": depth, "arity": 0,
                     "name": "", "value": float(node.value)})
        return
    if isinstance(node, ast.Name):
        rows.append({"kind": KIND_VAR, "depth": depth, "arity": 0,
                     "name": _desanitize_identifier(node.id), "value": 0.0})
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub):
            raise ExprError("vendor 公式没有这个一元运算符：%r" % (node.op,))
        if isinstance(node.operand, ast.Constant) and not isinstance(
                node.operand.value, bool) and isinstance(node.operand.value, (int, float)):
            # **负号 + 字面量折叠成一个带符号的常量**。`-1` 在 AST 里是两层
            # （USub 套 Constant(1)），摊成两行的话界面上负号会变成一个游离的符号、
            # 和数字隔开，而且用户改那个数值时没法直接改符号。
            #
            # 文本形式不受影响：`format_float(-1.0)` 就是 `-1`，和 vendor
            # `ExpressionNegation(ExpressionFloat(1)).ToString()` 的输出一模一样，
            # 所以导出字节不变（由 verify_blender_expression_edit.py 的文本/字节两层判据钉住）。
            rows.append({"kind": KIND_CONST, "depth": depth, "arity": 0,
                         "name": "", "value": -float(node.operand.value)})
            return
        rows.append({"kind": KIND_NEG, "depth": depth, "arity": 1,
                     "name": "", "value": 0.0})
        _collect_rows(node.operand, depth + 1, rows)
        return
    if isinstance(node, ast.BinOp):
        symbol = _OP_SYMBOLS.get(type(node.op))
        if symbol is None:
            raise ExprError("vendor 公式没有这个二元运算符：%r" % (node.op,))
        rows.append({"kind": KIND_CALL, "depth": depth, "arity": 2,
                     "name": symbol, "value": 0.0})
        _collect_rows(node.left, depth + 1, rows)
        _collect_rows(node.right, depth + 1, rows)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise ExprError("不支持的函数调用形式：%s" % (ast.dump(node),))
        rows.append({"kind": KIND_CALL, "depth": depth, "arity": len(node.args),
                     "name": node.func.id, "value": 0.0})
        for arg in node.args:
            _collect_rows(arg, depth + 1, rows)
        return
    raise ExprError("不支持的语法节点：%r" % (type(node).__name__,))


def from_rows(rows, second_branch=None):
    """`to_rows()` 的逆函数：扁平行 -> 公式文本。

    行数对不上（arity 声明的子节点数量和实际行数不符）直接抛 `ExprError`，**不补零、不截断**
    ——那是编辑器状态坏了，静默凑出一条合法但内容不对的公式正好是铁律 #2 要防的东西。
    """
    text, used = _emit_rows(list(rows), 0)
    if used != len(rows):
        raise ExprError("行列表尾部多出 %d 行没被消费（arity 和实际子节点数对不上）"
                        % (len(rows) - used))
    if second_branch:
        text += _ROOT_VALUE_SEPARATOR + second_branch
    return text


def _emit_rows(rows, index):
    """从 `rows[index]` 起消费一棵子树，返回 (文本, 消费到的下一个下标)。

    **本仓唯一的公式文本格式化处**，逐条复刻 vendor `ExpressionAtom.ToString()`：

    - 二元 `+ - * /` **总是带括号**（`ExpressionBinaryOperation.ToString()` 是
      `"({left} {op} {right})"`）。vendor 还有一套按优先级省括号的 `AppendString()`，
      但我们的 JSON 转换器写的是 `value.root.ToString()`（`Program.cs` 的
      `FixedExpressionTreeJsonConverter`），**走的是带括号这一套**——语料里的
      `(1.5 - Length)`、`(45 + -(Unary0((PI + Clamp(TIMER, 30, 0)))))` 就是证据。
    - `Min`/`Max` 在 vendor 那边是二元**操作符**不是函数（`BinaryExpressionOperator`），
      但文本形式同样是 `Min(a, b)`，这里统一按调用发。文本一致就够了——桥接 load 时
      重新解析文本建树，操作码由解析器还原。
    - 负号：子节点是字面量/变量时 `-x`，否则 `-(x)`（`ExpressionNegation.ToString()`）。
    """
    if index >= len(rows):
        raise ExprError("行列表提前结束（缺子节点）")
    row = rows[index]
    kind = row["kind"]
    index += 1
    if kind == KIND_CONST:
        return format_float(row.get("value", 0.0)), index
    if kind == KIND_VAR:
        name = (row.get("name") or "").strip()
        if not name:
            raise ExprError("变量节点的名字是空的")
        return name, index
    if kind == KIND_NEG:
        child_kind = rows[index]["kind"] if index < len(rows) else None
        inner, index = _emit_rows(rows, index)
        # vendor 的规则是"子节点是字面量/变量就不加括号"。但我们把"负号+字面量"折叠成了
        # 带符号常量（见 `_collect_rows()`），于是出现了 vendor 自己产不出的情形：
        # NEG 套一个**负**常量。这时不加括号会拼成 `--1`——**语法非法、读不回来**。
        # 判据用"子文本是不是以减号开头"而不是"值是不是负的"：拼出来的字符串才是真相。
        if child_kind in (KIND_CONST, KIND_VAR) and not inner.startswith("-"):
            return "-" + inner, index
        return "-(" + inner + ")", index
    if kind == KIND_CALL:
        name = (row.get("name") or "").strip()
        arity = int(row.get("arity", 0))
        args = []
        for _ in range(arity):
            arg, index = _emit_rows(rows, index)
            args.append(arg)
        if name in BINARY_OPERATORS:
            if arity != 2:
                raise ExprError("中缀运算符 %s 需要 2 个子节点，实际 %d 个" % (name, arity))
            return "(%s %s %s)" % (args[0], name, args[1]), index
        if not name:
            raise ExprError("函数节点的名字是空的")
        return "%s(%s)" % (name, ", ".join(args)), index
    raise ExprError("未知的行 kind：%r" % (kind,))


def subtree_span(rows, index):
    """`rows[index]` 这棵子树占用的行数（含自己）。结构化编辑的删除/替换全靠它定位区间。"""
    if index >= len(rows):
        raise ExprError("下标越界：%d" % index)
    end = index + 1
    for _ in range(int(rows[index].get("arity", 0))):
        end += subtree_span(rows, end)
    return end - index


#: vendor `EfxExpressionTreeUtils.KnownExternalHashes`（`EfxExpressionParser.cs:443`）里
#: 22 个已解出名字的内置外部变量。**这是一份镜像**，vendor 升级后要对一遍（由
#: `tests/test_sim_expr_edit.py` 钉住条目数，名字本身改不了——文本里出现的就是这些字面量）。
#: 变量下拉的另一半来自当前文件自己的 `ExpressionParameters` 具名参数表，那半边由
#: `blender_efx_re` 那层现取（`efx_sim` 不认识 Blender 数据）。
KNOWN_EXTERNAL_VARIABLES = (
    "PI", "TIMER", "RAND", "PLAY_SPEED", "EM_INIRAND", "EM_INIRAND_SHARED",
    "SpawnNum", "speed", "Speed", "scale", "alpha", "Color", "color",
    "pitch", "yaw", "roll", "ColorRange", "Piece_Color", "int_num", "Wide",
    "LightShadowRatio", "BackFaceLightRatio",
)

#: 新建变量节点时的默认名字。选 `TIMER` 是因为它是语料里最常见的内置变量（抽样 147 个
#: 文件出现 203 次），而且语义无歧义——不用先想"填什么"才能继续编辑。
DEFAULT_VARIABLE = "TIMER"


def recompute_depths(rows):
    """按 `arity` 重算每行的 `depth`。所有结构变换都靠这个收尾——`depth` 只给面板算缩进，
    是派生量，任何时候都不该手动维护（照铁律 #6 的路子：全量重算，不做增量）。"""
    stack = []          # [剩余待消费的子节点数, ...]
    for row in rows:
        while stack and stack[-1] == 0:
            stack.pop()
        row["depth"] = len(stack)
        if stack:
            stack[-1] -= 1
        stack.append(int(row.get("arity", 0)))
    return rows


def _const_row(value=0.0):
    return {"kind": KIND_CONST, "depth": 0, "arity": 0, "name": "", "value": float(value)}


def _var_row(name=DEFAULT_VARIABLE):
    return {"kind": KIND_VAR, "depth": 0, "arity": 0, "name": name, "value": 0.0}


def convert_node(rows, index, target):
    """把 `rows[index]` 这个节点换成另一种东西，返回**新的**行列表（不原地改）。

    `target` 取 `KIND_CONST` / `KIND_VAR` / 中缀运算符符号 / 函数名。子节点的去留规则：

    - 原节点**有子节点**（调用/负号）：子节点按顺序留用，多的丢、少的补常量 0。
      `Min(a, b)` -> `Lerp` 得到 `Lerp(a, b, 0)`，不会把 `Min(a,b)` 整个塞进第一个参数。
    - 原节点**是叶子**（常量/变量）：把它自己当第一个参数留用。`TIMER` -> `Min` 得到
      `Min(TIMER, 0)`，不是 `Min(0, 0)`——手滑点错也不会把已经填好的值弄丢。

    换成常量/变量时整棵子树都被丢掉（这就是"清空这一支"的操作），调用方负责在 UI 上让它
    看起来像一次明确的破坏性操作。
    """
    rows = [dict(r) for r in rows]
    span = subtree_span(rows, index)
    old = rows[index]
    tail = rows[index + span:]
    head = rows[:index]

    if target == KIND_CONST:
        return recompute_depths(head + [_const_row()] + tail)
    if target == KIND_VAR:
        return recompute_depths(head + [_var_row()] + tail)

    if target == KIND_NEG:
        arity = 1
    else:
        arity = call_arity(target)
    if arity is None:
        raise ExprError("不认识的目标：%r" % (target,))

    if int(old.get("arity", 0)) > 0:
        children = _child_subtrees(rows, index)
    else:
        children = [[dict(old)]]
    children = children[:arity]
    while len(children) < arity:
        children.append([_const_row()])

    if target == KIND_NEG:
        node = {"kind": KIND_NEG, "depth": 0, "arity": 1, "name": "", "value": 0.0}
    else:
        node = {"kind": KIND_CALL, "depth": 0, "arity": arity,
                "name": target, "value": 0.0}
    new_rows = head + [node]
    for child in children:
        new_rows.extend(child)
    return recompute_depths(new_rows + tail)


def wrap_node(rows, index, target):
    """在 `rows[index]` **上面**插一层：原子树变成新节点的第 0 个参数，其余参数补常量 0。

    `target` 取 `KIND_NEG`（套一个负号）/ 中缀运算符符号 / 函数名。
    """
    rows = [dict(r) for r in rows]
    span = subtree_span(rows, index)
    subtree = rows[index:index + span]

    if target == KIND_NEG:
        node = {"kind": KIND_NEG, "depth": 0, "arity": 1, "name": "", "value": 0.0}
        extra = []
    else:
        arity = call_arity(target)
        if arity is None:
            raise ExprError("不认识的目标：%r" % (target,))
        node = {"kind": KIND_CALL, "depth": 0, "arity": arity, "name": target, "value": 0.0}
        extra = [_const_row() for _ in range(arity - 1)]

    return recompute_depths(
        rows[:index] + [node] + subtree + extra + rows[index + span:])


def can_delete_node(rows, index):
    """`rows[index]` 能不能"删掉这一层"。叶子（常量/变量）不行——它不是"一层"，里面没有
    东西可以顶上来。清空一个叶子走"替换成常量"，**不要**让删除在叶子上变成别的语义，
    一个按钮两种行为正是要避免的那种含混。"""
    return 0 <= index < len(rows) and int(rows[index].get("arity", 0)) > 0


def delete_node(rows, index):
    """**删掉 `rows[index]` 这一层**：用它的第一个子节点顶替它自己，其余参数一起丢掉。

    `Lerp(Clamp(TIMER, 15, 0), -1, 0.5)` 里选中 `Clamp` 删除 -> `Lerp(TIMER, -1, 0.5)`。

    这是 `wrap_node()`（内嵌）的**精确逆操作**：内嵌插一层、把原内容放到第 0 参；删除去掉
    一层、把第 0 参提回来。两个操作互为逆，用户点错了原地就能撤。

    为什么保留第 0 个参数：语义已定的函数里第 0 参恒是"主输入"
    （`Clamp(value, hi, lo)` 的 value、`Lerp(t, from, to)` 的 t、全部 `Unary*` 的唯一参数），
    而 `wrap_node()` 也正是把原子树放在第 0 位。

    **上一版这里是 `promote_node()`（用选中节点替换掉它的父节点）——语义是"删掉我爸"，
    容易误操作，已按用户意见改掉。** 叶子上不可用（见 `can_delete_node()`）。
    """
    if not can_delete_node(rows, index):
        return [dict(r) for r in rows]
    rows = [dict(r) for r in rows]
    span = subtree_span(rows, index)
    first_child = index + 1
    child_span = subtree_span(rows, first_child)
    return recompute_depths(
        rows[:index] + rows[first_child:first_child + child_span] + rows[index + span:])


#: 函数名 -> 各参数的角色名。**只收语义已定的**：`Clamp(value, hi, lo)` 和
#: `Lerp(t, from, to)` 的读法有全语料证据（见 docs/EXPRESSION_SEMANTICS.md），
#: `Min`/`Max` 对称不需要名字，`InvLerp`（读法未定）和 `Unary*`/`Func*`（语义未知）
#: **一律不收** —— 给它们编一个参数名就是把猜测画成确定（铁律 #7）。
#:
#: 只有两个条目看着少，但实测这两个占函数调用的 763/~1700，而 `Lerp(Clamp(...))` 这个
#: 套路本身就是全语料 31.5% 的公式，正好是最需要解释的那个形状。
CALL_ARG_ROLES = {
    "Clamp": ("value", "hi", "lo"),
    "Lerp": ("t", "to", "from"),
    # `InvLerp(a, b, t)` 就是 `Lerp`、系数在最后 —— 角色名沿用同一套
    "InvLerp": ("to", "from", "t"),
    # `Func21(a, b, hi, lo, t)` == `Lerp(Clamp(t, hi, lo), a, b)`，所以前两个槽位的角色
    # 和 `Lerp` 的第 2/3 参一致（`to` 是 t 在 hi 端取的值），后三个和 `Clamp` 一致。
    "Func21": ("to", "from", "hi", "lo", "t"),
    # 这两个的**参数顺序和名字相反**，角色名是用户最需要看到的东西：
    # `Max(a, b)` == `pow(b, a)`、`Func20(a, b)` == `pow(b, a)` —— 指数在前、底数在后。
    "Max": ("exponent", "base"),
    "Func20": ("exponent", "base"),
    # `Min(a, b)` == `b - a` —— 减数在前、被减数在后。
    "Min": ("subtract", "from"),
}

#: 调用名 -> **真实语义**的极简说明，给界面用（铁律 #25：只写"这个东西干什么"，
#: 出处/置信度/验证过程一律不进去，那些在 docs/ 和代码注释里）。
#: 之所以必须显示：**这些名字全是错的**——用户打 `Min(a, b)` 完全不知道它算 `b - a`、
#: 打 `+` 不知道它是乘法。用数学记法写，跨语言通用、不用过 i18n。
CALL_SEMANTICS = {
    # 中缀运算符（`BINARY_OPERATORS`）
    "+": "a * b",
    "-": "b / a",
    "*": "fmod(b, a)",
    "/": "a + b",
    # 函数写法的两个操作码
    "Min": "b - a",
    "Max": "pow(b, a)",
    # 三角
    "Unary0": "sin (rad)",
    "Unary1": "cos (rad)",
    "Unary2": "asin (rad)",
    "Unary11": "sin (deg)",
    "Unary12": "cos (deg)",
    # 取整
    "Unary4": "floor",
    "Unary5": "ceil",
    # 对数 / 指数
    "Unary6": "ln",
    "Unary7": "log10",
    "Unary8": "exp",
    # 其他
    "Unary9": "abs",
    "Unary10": "saturate",
    # 多参
    "Func18": "min(a, b)",
    "Func19": "max(a, b)",
    "Func20": "pow(b, a)",
    "Func21": "b+(a-b)*saturate((t-lo)/(hi-lo))",
    "Lerp": "b + (a - b) * saturate(t)",
    "Clamp": "smoothstep(saturate((value-lo)/(hi-lo)))",
    "InvLerp": "b + (a - b) * saturate(t)",
}


def call_semantics(name):
    """调用名 -> 真实语义的极简说明（没有就返回空串）。"""
    return CALL_SEMANTICS.get(name, "")


def arg_roles(rows):
    """每一行的参数角色名，和 `rows` 平行的列表（没有就是空串）。

    角色取自**父节点的函数名 + 自己在兄弟里的序号**，所以这是纯结构推导，不需要界面参与。
    """
    out = [""] * len(rows)
    for index, row in enumerate(rows):
        roles = CALL_ARG_ROLES.get(row.get("name") or "")
        if not roles or int(row.get("arity", 0)) == 0:
            continue
        cursor = index + 1
        for position in range(int(row["arity"])):
            if cursor >= len(rows):
                break
            if position < len(roles):
                out[cursor] = roles[position]
            cursor += subtree_span(rows, cursor)
    return out


# ---------------------------------------------------------------------------
# 槽位视角 —— 界面按"一个节点 + 它的若干槽位"来画，不按"一棵树"来画
# ---------------------------------------------------------------------------
# 语料实测（1044 个文件 / 6621 个带参数的节点）：**每个参数槽位都能装下三种东西**
# ——字面量、变量、子表达式，没有哪个槽位是"只可能是常量"的。举证：
#   `Lerp.to`   常量 1729 / 变量 483 / 子表达式 24（第 2 参，2026-09-16 起改叫 to，见下）
#   `Lerp.from` 常量 1741 / 变量 220 / 子表达式 275（第 3 参）
#   `Clamp.hi`  常量 1503 / 变量 4   / 子表达式 20
# （只有 6 个槽位在全语料里只出现过常量，比如 `Func21` 的前四个。）
#
# 所以界面**不能按内容类型分三种画法**——同一个槽位换个内容就换外观、换位置，用户看到的
# 就不是公式结构而是内容的偶然形状。三个槽位必须长成同一种控件，内容类型只改变控件里面
# 显示什么。下面这几个函数就是给那套画法供数据的。


#: 函数/运算符名 -> 参与"和整体输出同一个物理量"传播的子节点位置下标（0-based）。
#: 只收**语义已定、而且真的保持单位**的那些（铁律 #29：给没确认的东西编一个"它和角度
#: 同单位"就是把猜测画成确定）。
#:
#: ⚠ **2026-09-16 大改过一次，因为运算符的真实语义全变了**（铁律 #32）。旧表按
#: vendor 的名字收了 `+`/`-`/`Max`，而它们实际是**乘 / 除 / 幂**——这三个都不保持单位：
#:
#: - 乘（文本 `+`）：只有一侧带单位、另一侧是无量纲系数，**没法只从结构分辨哪侧是哪侧**
#:   （`angle * 2` 和 `2 * angle` 长得一样），所以不收——这正是旧表给"`*`/`/` 不收"
#:   写的那条理由，现在适用到 `+` 身上。
#: - 除（文本 `-`）：结果单位 = 被除数单位 / 除数单位，压根不是同一个量。
#: - 幂（文本 `Max(`、函数 `Func20`）：指数是无量纲的，底数的单位也不守恒（`x²` 是单位²）。
#:
#: 现在收的是：
#:   `/`（实为**加法**）            两侧和结果同单位 -> {0, 1}
#:   `Min(a, b)`（实为 `b - a`）    减法，同上 -> {0, 1}
#:   `*`（实为 `fmod(b, a)`）       被除数 / 模数 / 结果三者同单位 -> {0, 1}
#:   `Func18`/`Func19`（真 min/max）单纯比大小 -> {0, 1}
#:   `Lerp(t, to, from)`           输出和 `to`/`from` 同单位，`t` 无量纲 -> {1, 2}
#:   `Func21(a, b, hi, lo, t)`     = `Lerp(Clamp(t,hi,lo), a, b)`，输出和 `a`/`b` 同单位；
#:                                 `hi`/`lo`/`t` 自成一个单位组（同 `Clamp`）-> {0, 1}
#:   `Unary9`/`Unary4`/`Unary5`    `abs`/`floor`/`ceil`，逐点保持单位 -> {0}
#:
#: **`Clamp` 故意不收**（`InvLerp` 2026-09-16 测出来其实是 `Lerp`，已收进来）：
#: 它的输出是重映射到 `[0,1]` 的无量纲值，和自己的 `value`/`hi`/`lo` 不是同一个单位体系——那几个输入形成一个独立的单位组（常见的是
#: "逐帧计数"，见 `Clamp(TIMER, 120, 0)`），不能从外层"这条曲线整体是角度"reverse 过去。
#: **三角 / 对数 / 指数 / `saturate` 同样不收**：`sin` 的输入是角度而输出无量纲、
#: `ln`/`exp` 的输入必须无量纲、`saturate` 拿 0/1 当边界所以输入也得是无量纲——
#: 这些都不是"和输出同一个物理量"。
_UNIT_PRESERVING_ARG_POSITIONS = {
    "/": (0, 1),
    "Min": (0, 1),
    "*": (0, 1),
    "Func18": (0, 1),
    "Func19": (0, 1),
    "Lerp": (1, 2),
    "InvLerp": (0, 1),
    "Func21": (0, 1),
    "Unary9": (0,),
    "Unary4": (0,),
    "Unary5": (0,),
}


def propagate_same_unit_as_root(rows):
    """从根节点（这条曲线赋值给目标字段的那个值）出发，标出哪些行和根节点是**同一个
    物理量**（比如都是弧度制角度）——给 `expr_edit.py` 的"角度显示"开关用：只有落在
    这个集合里的 `CONST` 槽位才该在开关打开时按度显示/输入，其余（比如
    `Clamp(TIMER, 120, 0)` 里的 `120`/`0`，那是帧数阈值不是角度）必须保持原始单位，
    不然会把一个逐帧计数当角度换算，静默改坏语义完全不相关的常量。

    只在 `_UNIT_PRESERVING_ARG_POSITIONS` 覆盖的运算上继续往下传播，其余（`Clamp`/
    `InvLerp`、`*`/`/`、未确认函数）一律截断——不确定就不传，比传错安全。

    返回和 `rows` 等长的布尔列表。"""
    n = len(rows)
    same_unit = [False] * n
    if n:
        same_unit[0] = True
    for index, row in enumerate(rows):
        if not same_unit[index]:
            continue
        kind = row.get("kind")
        if kind == KIND_NEG:
            children = child_indices(rows, index)
            if children:
                same_unit[children[0]] = True
            continue
        if kind != KIND_CALL:
            continue
        positions = _UNIT_PRESERVING_ARG_POSITIONS.get(row.get("name") or "")
        if not positions:
            continue
        children = child_indices(rows, index)
        for pos in positions:
            if pos < len(children):
                same_unit[children[pos]] = True
    return same_unit


def child_indices(rows, index):
    """`rows[index]` 各个直接子节点（= 各个槽位的内容）的行下标，按参数顺序。"""
    out = []
    cursor = index + 1
    for _ in range(int(rows[index].get("arity", 0))):
        out.append(cursor)
        cursor += subtree_span(rows, cursor)
    return out


def path_to_root(rows, index):
    """`[根, ..., index]` 这条祖先链。

    界面**只画这条链**：一次只看一级，而链本身就把"谁套在谁里面"讲清楚了
    （比缩进强，因为每一级的其余槽位也还看得见）。全公式的文本在上面的文本框里，
    形状在视口 HUD 上，三者各管一件事。
    """
    if not (0 <= index < len(rows)):
        raise ExprError("下标越界：%d" % index)
    chain = [index]
    cursor = index
    while True:
        parent = parent_index(rows, cursor)
        if parent is None:
            break
        chain.append(parent)
        cursor = parent
    chain.reverse()
    return chain


def node_summary(rows, index):
    """槽位控件上显示的文字：叶子显示它自己，表达式只显示"头"（函数名/运算符）。

    只显示头是"一次只看一级"的代价：从父行看不出子表达式里填了什么，得点进去。
    """
    row = rows[index]
    kind = row["kind"]
    if kind == KIND_CONST:
        return format_float(row.get("value", 0.0))
    if kind == KIND_VAR:
        return (row.get("name") or "").strip() or "?"
    if kind == KIND_NEG:
        return "-"
    return (row.get("name") or "").strip() or "?"


def subtree_rows(rows, index):
    """`rows[index]` 那棵子树，深度重新归零（可以当成一棵独立的树用）。"""
    if not (0 <= index < len(rows)):
        raise ExprError("下标越界：%d" % index)
    span = subtree_span(rows, index)
    return recompute_depths([dict(r) for r in rows[index:index + span]])


def subtree_text(rows, index):
    """`rows[index]` 那棵子树的公式文本。**把结构里任意一级单独拿出来求值/画曲线全靠它**
    ——没有它，界面只能整条公式一起算，看不出每一级各自算成什么。"""
    return from_rows(subtree_rows(rows, index))


def _child_subtrees(rows, index):
    """`rows[index]` 各个直接子节点的子树切片列表。"""
    out = []
    cursor = index + 1
    for _ in range(int(rows[index].get("arity", 0))):
        span = subtree_span(rows, cursor)
        out.append([dict(r) for r in rows[cursor:cursor + span]])
        cursor += span
    return out


def parent_index(rows, index):
    """`rows[index]` 的父节点下标，根节点返回 None。前序编码下"最近的、其子树覆盖到
    index 的那个更浅节点"就是父节点。"""
    if index <= 0:
        return None
    for i in range(index - 1, -1, -1):
        if i + subtree_span(rows, i) > index:
            return i
    return None
