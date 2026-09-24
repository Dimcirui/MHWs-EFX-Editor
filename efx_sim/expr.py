# -*- coding: utf-8 -*-
"""
efx_sim/expr.py —— IExpressionAttribute 公式（文本形式）的解析与求值

`EFXExpressionCurveItem.formula`（`blender_efx_re/model.py`）存的是 vendor
`ExpressionAtom.ToString()` / `EfxExpressionStringParser.Parse()` 那一套**引擎记法**的文本
（如 `"Lerp(0, 8, Clamp(ext:302732036, 3, 6))"`），不是后缀栈——双向转换全部交给 EfxBridge
（见 model.py::EFXExpressionCurveItem 的说明），这个模块只管"文本 -> 数值"和"文本 <-> 行"。

## 引擎记法（vendor `1c2f92d` 起）

上游按我们实机测出的语义把名字**和**操作数/参数顺序都改对了，文本现在按字面意思算：

- 中缀 `+ - * / % ^`：加、减、乘、除、取模（C 的 `fmod`，符号跟被除数）、幂。
  除零 / 模零实机是 0，这里记 note 后按 0 处理。
- 函数：`Sin Cos Asin Acos`（弧度）、`SinDeg CosDeg`（角度）、`Floor Ceil Log`(ln)
  `Log10 Exp Abs Saturate`；`Min Max Pow(base, exp)`；
  `Lerp(from, to, t)`、`Clamp(value, lo, hi)`、`SmoothStep(lo, hi, value)`、
  `Remap(t, lo, hi, from, to)`——都是 HLSL 的参数顺序。

逐条实机判据、被推翻过的读法见 docs/EXPRESSION_SEMANTICS.md，约束见
docs/EXPRESSION_RULES.md。⚠ **那两份文档里的读数是用当时的记法写的**（最早是
`Unary*`/`Func*`，后来是 `a96e1d9` 那套操作数反序的写法），换算表在 RULES 开头。

## 解析器为什么手写

vendor 解析器有两处和 Python 表达式语法不一样，照搬 `ast.parse` 会让预览和实际写进
文件的东西不一致：

- **`+ - * / %` 是右结合的**：`10 - 3 - 2` 被读成 `10 - (3 - 2)`（vendor 的
  `ParseBinaryOperationAddSub`/`MulDiv` 是右递归，已记 KNOWN_UPSTREAM_ISSUES）。
- **一元负号比 `^` 结合得紧**：`-2 ^ 2` 是 `(-2) ^ 2` = 4，Python 的 `-2 ** 2` 是 -4。

`parse()` 逐条镜像 vendor 的文法，产出的仍是 `ast` 节点，下游求值 / 行视图不用改。
给人读写的"规范记法"（按数学惯例左结合、少括号）在 `efx_sim/expr_text.py`，
我们自己写出去的引擎文本一律全括号（`_emit_rows()`），不依赖结合性。

约束：纯 Python，**禁 import bpy**；零第三方依赖。
"""

from __future__ import annotations

import ast
import math

#: vendor `ExpressionRootValueOption.ToString()` 用 `"  |  "` 连接两个根值，语义 vendor
#: 自己也不确定。只取第一支求值，第二支记 note，不扩语法去猜它的用法。
_ROOT_VALUE_CHAR = "|"

#: 2 参函数（区别于中缀运算符）。`Min`/`Max` 对称；`Pow(base, exp)`。
_KNOWN_BINARY_FUNCS = {
    "Min": min,
    "Max": max,
    "Pow": None,        # 走 _eval_known_binary_func 里的定义域兜底
}

#: 3 参函数
_TERNARY_KNOWN_FUNCS = frozenset({"Lerp", "Clamp", "SmoothStep"})

#: 1 参函数：名字 -> 实现（None = 在 `_eval_known_unary()` 里带定义域兜底）。
#: 实机测法的关键是输入扫 `[-2, 2]` 而不是 `[0, 1]`，否则 identity/abs/saturate 分不开。
_KNOWN_UNARY_FUNCS = {
    "Sin": math.sin,                                       # 弧度
    "Cos": math.cos,                                       # 弧度
    "Asin": None,
    "Acos": None,
    "Floor": lambda x: float(math.floor(x)),
    "Ceil": lambda x: float(math.ceil(x)),
    "Log": None,         # ln
    "Log10": None,
    "Exp": None,
    "Abs": abs,
    "Saturate": lambda x: max(0.0, min(1.0, x)),           # clamp01
    "SinDeg": lambda x: math.sin(math.radians(x)),         # **角度制**
    "CosDeg": lambda x: math.cos(math.radians(x)),         # **角度制**
}

#: 每个一元函数的实机读数（回归测试引用同一份原始观察）。读数里的函数名是当时的代号。
_KNOWN_UNARY_EVIDENCE = {
    "Sin": "圆测试从侧面起（sin(0)=0）；[-2,2] 宽扫呈 谷前(-0.909)-谷(-1@-pi/2)-峰(1@pi/2)-峰后(0.909)",
    "Cos": "圆测试配 Unary0 画出整圆；[-2,2] 宽扫呈 谷(-0.416)-峰(1@0)-谷(-0.416)",
    "Floor": "[-2,2] 阶梯，第一个完整台阶在 -2（trunc/ceil 都会从 -1 开始）",
    "Ceil": "[-2,2] 阶梯，第一个完整台阶在 -1",
    "Log": "输入 0->1 时从 -inf 爬到 0；Unary6(Unary8(t)) 复合终点恰好 1.0（同底互逆）",
    "Exp": "[-2,2] 宽扫起点 0.14 == e^-2 = 0.1353（10^-2=0.01 / 2^-2=0.25 都不对）",
    "Asin": "输入扫 0->1.4：升到 1.4416 时粒子消失（画面内，不是边界）== asin 在 x>1 无定义，"
              "消失前最后一帧 asin(1.003 之前) = 1.4416；tan/atanh 会先冲出画面、atan 根本不消失、"
              "acos 是往下走到 -0.87 才消失",
    "Log10": "Unary7(Unary8(t)) 复合终点 0.434 == log10(e)（ln 会是 1.0、log2 会是 1.443）",
    "Abs": "[-2,2] 宽扫画出直线 V 字；输入缩到 [-0.5,0.5] 后是小 V、顶点贴 0（排掉 max(|x|,1) 的平底 U）",
    "Saturate": "[-2,2] 宽扫呈 `_/‾`：0 段 -> 斜升到 1 -> 停在 1，就是 clamp01",
    "SinDeg": "[-2,2] 恒 0、[-180,180] 扫出完整三角波 -> sin 的角度制版本（sin(2°)=0.035）",
    "CosDeg": "[-2,2] 恒 1、[-180,180] 扫出三角波 -> cos 的角度制版本（cos(2°)=0.9994）",
}

#: 语义**仍然**未确认的函数名 -> 参数个数。目前是空的（函数全部实机测完了）；留着是因为
#: 以后遇到新操作码时，UI 仍要如实展示"这条曲线用到未确认语义的函数"，不装作算对了。
#: ⚠ vendor 的枚举跳过了 13 / 14（引擎没实现），文本里写不出来。
_UNKNOWN_FUNC_ARGC = {}


class ExprError(Exception):
    """公式语法本身有问题（vendor 语法之外的写法）——不是"变量/函数语义未知"，那种走 note。"""


class EvalContext(object):
    """一次求值需要的输入 + 输出."""

    __slots__ = ("variables", "unknown_func_policy", "clamp_mode", "notes",
                 "guessed_names", "_unresolved")

    def __init__(self, variables, unknown_func_policy="identity", notes=None,
                 clamp_mode="remap_smoothstep", guessed_names=None):
        #: 标识符 -> 数值。key 就是公式文本里出现的原样标识符
        #: （`TIMER`/`ext:302732036`/`p:2597296009`/已解析出名字的 `EM_SPEED` 等）。
        self.variables = variables
        self.unknown_func_policy = unknown_func_policy
        #: `Clamp` 怎么读，见 `_eval_ternary_known()` 和 `SimConfig.expr_clamp_mode`
        self.clamp_mode = clamp_mode
        #: **预览不静默撒谎**（铁律 #1 在只读侧的对应物，同 `EmitterState.note()`）：
        #: 未知变量、未确认语义的函数、被丢弃的第二根值都记在这里，去重按消息文本。
        self.notes = notes if notes is not None else []
        #: `variables` 里这些 key 即使**有值**，也不是确认过的真值，是我们自己选的代表值
        #: （`RAND`=0.5、`PLAY_SPEED`=1.0 这类，调用方——`expr_preview.build_variables()`/
        #: `Simulator._eval_expressions()`——在构造变量表时一并传进来）。跟"表里根本没有、
        #: 按 0 处理"是同一个置信度：都是"引擎才知道的量，我们替上了一个数"，`EM_SPEED`/
        #: `WIND_SPEED`（名字解出来了）和裸 `ext:<hash>`（连名字都没有）也在同一档——
        #: 名字解出来与否只影响显示成什么字符串，不影响这里的置信度判断（不把猜测当事实）。
        self.guessed_names = guessed_names or ()
        #: `[(显示名, 实际取的值), ...]`，去重按显示名。`evaluate()`/`evaluate_rows()`
        #: 收尾时统一拼成一条 note，不在 `_resolve_variable()` 里逐个各发一条——多个变量
        #: 分开报，界面上就是一串长得几乎一样的行，看不出这是同一件事。
        self._unresolved = []

    def note(self, msg):
        if msg not in self.notes:
            self.notes.append(msg)

    def _note_guessed(self, display_name, value):
        for existing_name, _ in self._unresolved:
            if existing_name == display_name:
                return
        self._unresolved.append((display_name, value))

    def flush_guessed_notes(self):
        """把 `_unresolved` 拼成**一条**note。`evaluate()`/`evaluate_rows()` 收尾时调，
        不暴露成公开 API 之外的细节。"""
        if not self._unresolved:
            return
        parts = ["%s 按取 %s 处理" % (name, format_float(value))
                 for name, value in self._unresolved]
        self.note("预览给不出真值：%s" % "、".join(parts))


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
    """引擎记法文本 -> `ParsedExpr`。空文本/`None` 当常量 0 处理（vendor 默认值就是 `"0"`，
    见 `EFXExpressionCurveItem.formula` 的 `default="0"`）。

    文法逐条镜像 vendor `EfxExpressionStringParser`（右结合、一元负号只吃一个原子），
    见模块 docstring。比 vendor 严格的一处：**尾部多出来的东西直接报错**——vendor 解析完
    一个表达式就停，`1 2` 会被静默读成 `1`（铁律 #1：宁可拒绝）。
    """
    text = (formula_text or "").strip() or "0"
    primary, secondary = _split_root_value(text)
    parser = _VendorParser(primary)
    body = parser.parse_expression()
    if parser.peek()[0] != "eof":
        raise ExprError("公式语法错误：第 %d 个字符处多出了内容（原文：%r）"
                        % (parser.peek()[2] + 1, primary))
    return ParsedExpr(ast.Expression(body=body), secondary)


#: vendor 中缀符号 -> `ast` 运算符类型
_TOKEN_TO_AST_OP = {"+": ast.Add, "-": ast.Sub, "*": ast.Mult, "/": ast.Div,
                    "%": ast.Mod, "^": ast.Pow}
_IDENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:")


def _tokenize(text):
    """-> `[(kind, value, 起始下标), ...]`，末尾一个 `("eof", None, len)`。"""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif ch in "()+-*/%^,":
            tokens.append((ch, ch, i))
            i += 1
        elif "0" <= ch <= "9":
            # 同 vendor `ReadFloat`：数字串里最多一个小数点，没有指数写法
            start, seen_dot = i, False
            while i < n and ("0" <= text[i] <= "9" or (text[i] == "." and not seen_dot)):
                seen_dot = seen_dot or text[i] == "."
                i += 1
            tokens.append(("num", float(text[start:i]), start))
        elif ch in _IDENT_CHARS:
            start = i
            while i < n and text[i] in _IDENT_CHARS:
                i += 1
            tokens.append(("name", text[start:i], start))
        else:
            raise ExprError("公式语法错误：第 %d 个字符 %r 不认识（原文：%r）" % (i + 1, ch, text))
    tokens.append(("eof", None, n))
    return tokens


class _VendorParser(object):
    """vendor 递归下降文法的镜像：

        expr   := muldiv (('+'|'-') expr)?          ← 右递归 = 右结合
        muldiv := pow (('*'|'/'|'%') muldiv)?       ← 同上
        pow    := unary ('^' pow)?
        unary  := '-' atom | atom                   ← 负号只吃一个原子，所以 -2^2 = (-2)^2
        atom   := num | name | name '(' expr (',' expr)* ')' | '(' expr ')'
    """

    def __init__(self, text):
        self.text = text
        self.tokens = _tokenize(text)
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def take(self, kind=None):
        tok = self.tokens[self.pos]
        if kind is not None and tok[0] != kind:
            found = "结尾" if tok[0] == "eof" else repr(tok[1])
            raise ExprError("公式语法错误：第 %d 个字符处应为 %r，实际是 %s（原文：%r）"
                            % (tok[2] + 1, kind, found, self.text))
        self.pos += 1
        return tok

    def _binary(self, operand, symbols, recurse):
        left = operand()
        if self.peek()[0] in symbols:
            op = self.take()[0]
            return ast.BinOp(left=left, op=_TOKEN_TO_AST_OP[op](), right=recurse())
        return left

    def parse_expression(self):
        return self._binary(self.parse_muldiv, ("+", "-"), self.parse_expression)

    def parse_muldiv(self):
        return self._binary(self.parse_pow, ("*", "/", "%"), self.parse_muldiv)

    def parse_pow(self):
        return self._binary(self.parse_unary, ("^",), self.parse_pow)

    def parse_unary(self):
        if self.peek()[0] == "-":
            self.take()
            return ast.UnaryOp(op=ast.USub(), operand=self.parse_atom())
        return self.parse_atom()

    def parse_atom(self):
        tok = self.peek()
        if tok[0] == "num":
            self.take()
            return ast.Constant(value=tok[1])
        if tok[0] == "(":
            self.take()
            inner = self.parse_expression()
            self.take(")")
            return inner
        if tok[0] == "name":
            self.take()
            if self.peek()[0] != "(":
                return ast.Name(id=_sanitize_identifiers(tok[1]), ctx=ast.Load())
            self.take("(")
            args = [self.parse_expression()]
            while self.peek()[0] == ",":
                self.take()
                args.append(self.parse_expression())
            self.take(")")
            return ast.Call(func=ast.Name(id=tok[1], ctx=ast.Load()), args=args, keywords=[])
        found = "结尾" if tok[0] == "eof" else repr(tok[1])
        raise ExprError("公式语法错误：第 %d 个字符处应为数字、变量或括号，实际是 %s（原文：%r）"
                        % (tok[2] + 1, found, self.text))


def evaluate(parsed, ctx):
    """对 `parse()` 的产物求值，返回 float。"""
    if parsed.second_branch:
        ctx.note("公式带第二根值（'a | b'），语义未证实（vendor 自己也只是猜测），只用第一支")
    result = _eval(parsed.tree.body, ctx)
    ctx.flush_guessed_notes()
    return result


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
        symbol = _OP_SYMBOLS.get(type(node.op))
        if symbol is None:
            raise ExprError("不支持的二元运算符：%r" % (node.op,))
        return _eval_binary_operator(symbol, _eval(node.left, ctx), _eval(node.right, ctx), ctx)
    if isinstance(node, ast.Name):
        return _resolve_variable(node.id, ctx)
    if isinstance(node, ast.Call):
        return _eval_call(node, ctx)
    raise ExprError("不支持的语法节点：%r" % (type(node).__name__,))


def _resolve_variable(raw_name, ctx):
    name = _desanitize_identifier(raw_name)
    # `display_var_name()` 定义在本文件后面（`RESOLVED_EXTERNAL_VARIABLES` 那一节），
    # 模块级函数调用时才查名字，不受定义顺序影响。
    #
    # 名字解出来了没有（`EM_SPEED` vs 裸 `ext:<hash>`）只影响下面报出来的字符串好不好读，
    # 不改变置信度判断——两者都是"引擎才知道的量，我们给不出真值"，同一档，不单独分文案
    # （不把猜测当事实：解出来的名字本身不构成语义证据）。`ctx.guessed_names` 里的名字
    # （`RAND`/`PLAY_SPEED` 这类）道理相同：`ctx.variables` 里有值不代表这个值被确认过，
    # 只是我们自己选的代表值——跟"表里根本没有、按 0 处理"是同一件事，一起走这条 note。
    value = ctx.variables.get(name)
    if value is None:
        ctx._note_guessed(display_var_name(name), 0.0)
        return 0.0
    if name in ctx.guessed_names:
        ctx._note_guessed(display_var_name(name), value)
    return float(value)


def _eval_call(node, ctx):
    if not isinstance(node.func, ast.Name) or node.keywords:
        raise ExprError("不支持的函数调用形式：%s" % (ast.dump(node),))
    return _apply_call(node.func.id, [_eval(a, ctx) for a in node.args], ctx)


def _apply_call(fname, args, ctx):
    """参数**已经求好值**之后的函数派发。和 `_eval_call` 拆开是为了让
    `evaluate_rows()` 能复用同一套语义——那条路是自底向上一次遍历算完所有子树的值，
    不能再让每个节点自己去递归求参数（那样就退化成 O(N²) 了）。"""
    if fname in _KNOWN_UNARY_FUNCS:
        if len(args) != 1:
            raise ExprError("%s 需要 1 个参数，实际 %d 个" % (fname, len(args)))
        return _eval_known_unary(fname, args[0], ctx)

    if fname in _KNOWN_BINARY_FUNCS:
        if len(args) != 2:
            raise ExprError("%s 需要 2 个参数，实际 %d 个" % (fname, len(args)))
        return _eval_known_binary_func(fname, args[0], args[1], ctx)

    if fname == "Remap":
        if len(args) != 5:
            raise ExprError("Remap 需要 5 个参数，实际 %d 个" % len(args))
        return _eval_remap(args, ctx)

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
    if fname == "SmoothStep":
        lo, hi, value = args
        return _eval_smoothstep(value, lo, hi, ctx)
    if fname == "Lerp":
        # `Lerp(from, to, t)` == `from + (to - from) * saturate(t)`：线性、`t` 两端饱和、
        # 方向（t=0 取 from），三件事由一条零差探针一次钉死（docs/EXPRESSION_SEMANTICS.md）。
        a, b, t = args
        return a + (b - a) * max(0.0, min(1.0, t))
    # `Clamp(value, lo, hi)` == `max(lo, min(hi, value))`。
    # ⚠ **两次钳位的先后是测出来的**：`lo > hi` 时 `lo` 赢，别"顺手规范化成 min<=max"。
    value, lo, hi = args
    return max(lo, min(hi, value))


def _eval_smoothstep(value, lo, hi, ctx):
    """`SmoothStep(lo, hi, value)`：`u = saturate((value - lo) / (hi - lo))`，返回
    `u²(3 - 2u)`——**两端饱和、中段带缓动**，全部实机确认。

    `SimConfig.expr_clamp_mode` 保留了几档被推翻的旧读法（`bounds_clamp` 字面夹紧、
    `remap_unclamped`、`remap_saturate_low`、线性 `remap_saturate_both`）用于对拍，
    判据见 docs/EXPRESSION_SEMANTICS.md。`Remap` 的重映射是**线性**的，不走这里。
    """
    if ctx.clamp_mode == "bounds_clamp":
        a, b = (lo, hi) if lo <= hi else (hi, lo)
        return min(max(value, a), b)
    if hi == lo:
        ctx.note("SmoothStep 的两个边界相等（%g），重映射除零，按 0.0 处理" % hi)
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


def _eval_binary_operator(symbol, a, b, ctx):
    """中缀运算 `a <symbol> b`，按字面意思算（六个操作码逐个实机确认过，判据见
    docs/EXPRESSION_SEMANTICS.md）。

    - 除零、模零实机是 0（不是 inf/NaN），记 note 后按 0 处理。
    - `%` 是 C 的 `fmod`（符号跟被除数），**不能用 Python 的 `%`**。
    - `^` 无定义 / 溢出按 0 处理——NaN/Inf 会顺着位置字段传进视口和导出。
    """
    if symbol == "+":
        return a + b
    if symbol == "-":
        return a - b
    if symbol == "*":
        return a * b
    if symbol == "/":
        if b == 0:
            ctx.note("公式除零，按 0.0 处理")
            return 0.0
        return a / b
    if symbol == "%":
        if b == 0:
            ctx.note("公式取模的模数为 0，按 0.0 处理")
            return 0.0
        return math.fmod(a, b)
    if symbol == "^":
        return _safe_pow(a, b, ctx)
    raise ExprError("不支持的二元运算符：%r" % (symbol,))


def _safe_pow(base, exponent, ctx):
    try:
        result = float(base) ** float(exponent)
    except (OverflowError, ValueError, ZeroDivisionError):
        ctx.note("幂运算无定义，按 0.0 处理")
        return 0.0
    if isinstance(result, complex) or result != result or result in (float("inf"), float("-inf")):
        ctx.note("幂运算算出复数/NaN/Inf，按 0.0 处理")
        return 0.0
    return result


def _eval_known_binary_func(fname, a, b, ctx):
    """`Min`/`Max`（对称）、`Pow(base, exp)`，实机确认。

    `Pow` 和中缀 `^`（操作码 0）是同一个运算，这不是异常：一个在中缀运算符表（按优先级
    排，幂在 0 号），一个在内建函数表（docs/EXPRESSION_SEMANTICS.md 11.6）。
    """
    if fname == "Pow":
        return _safe_pow(a, b, ctx)
    return float(_KNOWN_BINARY_FUNCS[fname](a, b))


def _eval_remap(args, ctx):
    """`Remap(t, lo, hi, from, to)`：把 `t` 从 `[lo, hi]` **线性**映到 `[0, 1]`（两端饱和），
    再在 `from`/`to` 之间线性插值。实机零差检验确认。

    ⚠ **故意不复用 `_eval_smoothstep()`**：`SmoothStep` 带缓动、`Remap` 不带，两者的差别
    就是这层缓动。`SimConfig.expr_clamp_mode` 的对拍档不影响这里。
    """
    t, lo, hi, a, b = args
    if hi == lo:
        ctx.note("Remap 的 lo/hi 相等（%g），重映射除零，按 0.0 处理" % hi)
        return 0.0
    u = max(0.0, min(1.0, (t - lo) / (hi - lo)))
    return a + (b - a) * u


def _eval_known_unary(fname, x, ctx):
    """已实机测出语义的 1 参函数。下面的读数是当年测的时候写的，用的是那时 vendor 的
    编号占位（`Unary<N>`），名字对照见 docs/EXPRESSION_RULES.md 开头的换算表。

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
    if fname == "Asin":
        if x < -1.0 or x > 1.0:
            ctx.note("`Asin` 的输入超出 [-1, 1]，无定义，按 0.0 处理")
            return 0.0
        return math.asin(x)
    if fname == "Acos":
        if x < -1.0 or x > 1.0:
            ctx.note("`Acos` 的输入超出 [-1, 1]，无定义，按 0.0 处理")
            return 0.0
        return math.acos(x)
    if fname in ("Log", "Log10"):
        base_name = "ln" if fname == "Log" else "log10"
        if x <= 0:
            ctx.note("`%s`（实为 %s）的输入 <= 0，无定义，按 0.0 处理" % (fname, base_name))
            return 0.0
        return math.log(x) if fname == "Log" else math.log10(x)
    if fname == "Exp":
        try:
            return math.exp(x)
        except OverflowError:
            ctx.note("`Exp` 溢出，按 0.0 处理")
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

#: `ast` 二元运算符 -> 引擎记法的中缀符号（行视图里存的就是这个符号）
_OP_SYMBOLS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
               ast.Mod: "%", ast.Pow: "^"}

#: 中缀运算符符号集合（行视图里和函数名共用 `name` 字段，靠在不在这个集合里区分写法）
BINARY_OPERATORS = ("+", "-", "*", "/", "%", "^")


#: 置信度分层，逐条依据见 docs/EXPRESSION_SEMANTICS.md。
#: **UI 要如实展示这一层，四档不能画成一个样**。
CONFIDENCE_CONFIRMED = "confirmed"      # 语义完全确认
CONFIDENCE_CORPUS = "corpus"            # 语料一致性推断：有成规模的正面证据、零反例，但没实机确认
CONFIDENCE_UNDECIDED = "undecided"      # 语料里有互相矛盾的用法，读法未定
CONFIDENCE_UNKNOWN = "unknown"          # 纯数字占位，vendor 自己也只给了候选猜测

#: 中缀运算符 -> 置信度。六个操作码逐个实机确认过（判据见 docs/EXPRESSION_SEMANTICS.md）。
BINARY_OPERATOR_CONFIDENCE = {symbol: CONFIDENCE_CONFIRMED for symbol in BINARY_OPERATORS}

#: 函数名 -> (参数个数, 置信度)。中缀运算符不在这里，走 `BINARY_OPERATORS`（恒 2 参）+
#: `BINARY_OPERATOR_CONFIDENCE`。参数个数来自 `EfxExpressionParser.cs` 的 `FunctionArgCounts`。
#: 整张表已经逐个实机确认完，未知表 `_UNKNOWN_FUNC_ARGC` 是空的。
CALL_SIGNATURES = {name: (3, CONFIDENCE_CONFIRMED) for name in _TERNARY_KNOWN_FUNCS}
CALL_SIGNATURES.update(
    (name, (argc, CONFIDENCE_UNKNOWN)) for name, argc in _UNKNOWN_FUNC_ARGC.items()
)
CALL_SIGNATURES.update((name, (1, CONFIDENCE_CONFIRMED)) for name in _KNOWN_UNARY_FUNCS)
CALL_SIGNATURES.update((name, (2, CONFIDENCE_CONFIRMED)) for name in _KNOWN_BINARY_FUNCS)
CALL_SIGNATURES["Remap"] = (5, CONFIDENCE_CONFIRMED)


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
    第二根值（`a | b`）原样带回去——语义没证实不等于可以丢（铁律 #1）。
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
    ctx.flush_guessed_notes()
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
    ——那是编辑器状态坏了，静默凑出一条合法但内容不对的公式正好是铁律 #1 要防的东西。
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

    - 二元 `+ - * / % ^` **总是带括号**（`ExpressionBinaryOperation.ToString()` 是
      `"({left} {op} {right})"`）。vendor 还有一套按优先级省括号的 `AppendString()`，
      但我们的 JSON 转换器写的是 `value.root.ToString()`（`Program.cs` 的
      `FixedExpressionTreeJsonConverter`），**走的是带括号这一套**。
      ⚠ 这也是结合性安全的保证：vendor 解析器是右结合的，而 `AppendString()` 对同级
      左子树不加括号，`(a - b) - c` 会被它写成 `a - b - c`、再读回来就成了 `a - (b - c)`。
      全括号就没有这个问题。
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

#: `KNOWN_EXTERNAL_VARIABLES` 里这几个，预览/模拟给出的值本身也是我们自己选的代表数，
#: 不是确认过的运行时真值——`RAND`/`EM_INIRAND*` 没有量级证据，`[0,1)` 只是多数引擎的
#: 约定；`PLAY_SPEED` 没有对应的预览/模拟概念，固定给 1.0（未建模，不是"确认了就是 1"，
#: 原话见 `efx_sim/simulator.py` 变量表那段注释）。`TIMER`（已实机确认为帧号）和 `PI`
#: （数学常数，不是经验声明）不在这张表里，两者不属于同一档。
#:
#: 传给 `EvalContext(guessed_names=...)`，求值时和"表里根本没有、按 0 处理"走同一条 note
#: （`_resolve_variable()`）——两者是同一件事："引擎才知道的量，我们替上了一个数"，跟
#: 这个名字是 vendor 自己命名的还是我们自己解出来的无关（不把猜测当事实）。调用方
#: （`expr_preview.build_variables()`/`Simulator._eval_expressions()`）必须传同一张表，
#: 否则面板读数和粒子预览会对"这条提示该不该出现"给出两个答案。
GUESSED_BUILTIN_VARIABLES = ("RAND", "EM_INIRAND", "EM_INIRAND_SHARED", "PLAY_SPEED")

#: vendor 表里没有、我们自己解出来的外部变量名字，和 `KNOWN_EXTERNAL_VARIABLES` 地位相同——
#: 分开放只是因为它不属于"vendor 自己那 22 个"的镜像范围，不是置信度分级。
#:
#: `EM_SPEED` 解出过程：全语料唯一未解出的高频哈希 `302732036`（26699 棵树里出现 1824 次）
#: 用暴力枚举撞出唯一命中的候选词，用法（clamp 到真实数值量级再 lerp）也吻合"发射器移动
#: 速度"。名字这一层不需要额外验证：`MurMur3HashUtils.GetAsciiHash("EM_SPEED") ==
#: 302732036`，而且读过 `EfxExpressionParser.cs:61`（`StoreNewParameters`）能确认——公式
#: 文本里裸写 `EM_SPEED`（不带 `ext:` 前缀）解析出的标识符 `source` 会被这行代码统一改写成
#: `External`，和显式写 `ext:302732036` 走到的分支**产出完全相同的 `EFXExpressionTree`**，
#: 不依赖实机、不是概率论证。（这个哈希本身连 vendor 自己都没解出来，见
#: `EfxExpressionParser.cs` 里注释掉的 `// [302732036] = "???"`。）
#:
#: `WIND_SPEED` 解出过程（2026-09-18）：`213419702`（627 次，`VortexelWindEmitterExpression`
#: 等风场相关 attrType 为主）暴力枚举撞中，同样是 `GetAsciiHash("WIND_SPEED") ==
#: 213419702` 精确命中。用法证据：`Art\VFX\EffectEditor\Stage\St101\11_st101_wind_000.efx`
#: （文件名直接叫 wind）里 11 处全是 `(0.8 + 0.2 * Sin(0.02 * TIMER)) *
#: Clamp(ext:213419702, 0, 20)`（当时的记法写作 `InvLerp(20, 0, ext:213419702)`）——16 号已实机确认是真 `clamp`（见 docs/
#: EXPRESSION_SEMANTICS.md 第 30 条），钳到 `[0, 20]` 这个量级和风速单位吻合。
#:
#: 两者名字之外，运行时具体怎么变化仍未知（Blender 预览环境造不出真实的"发射器移动速度"/
#: "风速"），这属于语义结论那一类，跟这里"叫什么名字"是两回事，继续按
#: 未知变量处理即可，见 memory `mhws-expression-external-var-hashes.md` 和
#: docs/EXPRESSION_SEMANTICS.md 第 16 节。
RESOLVED_EXTERNAL_VARIABLES = (
    "EM_SPEED",
    "WIND_SPEED",
)

#: `RESOLVED_EXTERNAL_VARIABLES` 里每个名字对应的 vendor 占位字面量。存在的唯一原因是
#: vendor 自己的 `ToString()` 不认识这些哈希（不在它的 `KnownExternalHashes` 里），从
#: 文件读出来的公式文本永远是 `ext:<hash>`——这是 vendor 侧的限制，不是我们对这些名字
#: 有所保留。`KNOWN_EXTERNAL_VARIABLES` 里的 22 个不需要这张表，因为 vendor 自己的
#: `ToString()` 已经把它们替换成真名了，文本到我们手上时就是名字，不是占位符。
_RESOLVED_EXTERNAL_VAR_LITERALS = {
    "EM_SPEED": "ext:302732036",
    "WIND_SPEED": "ext:213419702",
}
_RESOLVED_EXTERNAL_VAR_NAMES = {
    literal: name for name, literal in _RESOLVED_EXTERNAL_VAR_LITERALS.items()
}


def display_var_name(name):
    """变量名（vendor 字面量，可能是 `ext:302732036` 这种占位）-> 界面上显示的名字。"""
    return _RESOLVED_EXTERNAL_VAR_NAMES.get(name, name)


def vendor_var_name(name):
    """界面上打的变量名 -> 存盘/求值用的 vendor 字面量（`display_var_name()` 的逆）。"""
    return _RESOLVED_EXTERNAL_VAR_LITERALS.get(name, name)


#: 全语料扫描确认出现过、但连名字都没解出来的外部变量哈希（memory
#: `mhws-expression-external-var-hashes.md`）。元素本身就是 `ext:<hash>` 占位字面量，
#: 不是名字——选择器里选出来是什么样、存到公式里就是什么样。
UNRESOLVED_EXTERNAL_VAR_LITERALS = (
    "ext:1017435601",
    "ext:3433402344",
)


def variable_picker_choices():
    """变量选择器（下拉/`prop_search` 候选表）里，跟当前文件无关的那一半：vendor 自己
    解出的内置外部变量、我们自己解出的（`EM_SPEED`）、连名字都没有的占位哈希，三档全给——
    地位相同，都是"公式文本里能直接写的标识符"，用户不需要分辨来源。"""
    return (
        list(KNOWN_EXTERNAL_VARIABLES)
        + list(RESOLVED_EXTERNAL_VARIABLES)
        + list(UNRESOLVED_EXTERNAL_VAR_LITERALS)
    )


#: 新建变量节点时的默认名字。选 `TIMER` 是因为它是语料里最常见的内置变量（抽样 147 个
#: 文件出现 203 次），而且语义无歧义——不用先想"填什么"才能继续编辑。
#: 公式文本里长得像变量、其实是**值存在文件里的具名常量**的名字 ->
#: (vendor 的名字哈希, 常量值)。
#:
#: 文本形式区分不了这两种东西：`PI` 和 `TIMER` 都只是一个标识符。真相在树的参数表
#: （`EFXExpressionTree.parameters`）的 `source` 字段上——`ExpressionParameterSource`
#: 的 `Constant = 1` 表示"值在文件里"，`External = 2` 表示"引擎运行时喂"。
#:
#: 目前只有 `PI` 一条，依据是全语料实测：6 个用到它的文件、110 处出现，**无一例外**都是
#: `source=1, constantValue=3.1415927`；同一批文件里的 `TIMER` 则一律 `source=2`。
#: 哈希取自 vendor 的 `EfxExpressionParser.KnownExternalHashes`（那张表只负责把哈希译成
#: 名字，**不代表引擎会给它绑值**——`PI` 就是反例）。
#:
#: ⚠ 新打的公式里写 `PI` 时必须靠这张表补出常量条目，否则解析器只能按名字回退成
#: External，引擎没有东西绑给它，实机读成 **0**（实测：`Z = PI` 的粒子贴地）。
NAMED_CONSTANTS = {
    "PI": (4068760923, 3.1415927),
}

DEFAULT_VARIABLE = "TIMER"


def recompute_depths(rows):
    """按 `arity` 重算每行的 `depth`。所有结构变换都靠这个收尾——`depth` 只给面板算缩进，
    是派生量，任何时候都不该手动维护（照全量重算原则的路子：全量重算，不做增量）。"""
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
    - 原节点**是叶子**（常量/变量）：把它自己放进"主输入"那个槽位（`primary_arg_position()`）。
      `TIMER` -> `Min` 得到 `Min(TIMER, 0)`、-> `Lerp` 得到 `Lerp(0, 0, TIMER)`，
      不是全 0——手滑点错也不会把已经填好的值弄丢。

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
        children = _child_subtrees(rows, index)[:arity]
        while len(children) < arity:
            children.append([_const_row()])
    else:
        children = [[_const_row()] for _ in range(arity)]
        children[primary_arg_position(target, arity)] = [dict(old)]

    if target == KIND_NEG:
        node = {"kind": KIND_NEG, "depth": 0, "arity": 1, "name": "", "value": 0.0}
    else:
        node = {"kind": KIND_CALL, "depth": 0, "arity": arity,
                "name": target, "value": 0.0}
    new_rows = head + [node]
    for child in children:
        new_rows.extend(child)
    return recompute_depths(new_rows + tail)


#: 函数名 -> "主输入"在第几个参数。没列的都是第 0 个。
#:
#: 引擎记法是 HLSL 的参数顺序，`Lerp(from, to, t)` / `SmoothStep(lo, hi, value)` 的主输入在
#: **最后**。内嵌 / 删除一层 / 叶子换函数都按这个槽位走，所以给 `TIMER` 套一层 `Lerp` 得到的
#: 是 `Lerp(0, 0, TIMER)`（`TIMER` 当 t），而不是把它塞成端点。
_PRIMARY_ARG_POSITION = {"Lerp": 2, "SmoothStep": 2}


def primary_arg_position(name, arity):
    """`name` 这个调用的主输入在第几个参数（越界时退回 0）。"""
    pos = _PRIMARY_ARG_POSITION.get(name, 0)
    return pos if pos < arity else 0


def wrap_node(rows, index, target):
    """在 `rows[index]` **上面**插一层：原子树放进新节点的主输入槽位
    （`primary_arg_position()`），其余参数补常量 0。

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
        slots = [[_const_row()] for _ in range(arity)]
        slots[primary_arg_position(target, arity)] = subtree
        extra = [row for slot in slots for row in slot]
        return recompute_depths(rows[:index] + [node] + extra + rows[index + span:])

    return recompute_depths(
        rows[:index] + [node] + subtree + extra + rows[index + span:])


def can_delete_node(rows, index):
    """`rows[index]` 能不能"删掉这一层"。叶子（常量/变量）不行——它不是"一层"，里面没有
    东西可以顶上来。清空一个叶子走"替换成常量"，**不要**让删除在叶子上变成别的语义，
    一个按钮两种行为正是要避免的那种含混。"""
    return 0 <= index < len(rows) and int(rows[index].get("arity", 0)) > 0


def delete_node(rows, index):
    """**删掉 `rows[index]` 这一层**：用它的主输入子节点（`primary_arg_position()`）顶替
    它自己，其余参数一起丢掉。

    `Lerp(-1, 0.5, SmoothStep(0, 15, TIMER))` 里选中 `SmoothStep` 删除 ->
    `Lerp(-1, 0.5, TIMER)`。

    这是 `wrap_node()`（内嵌）的**精确逆操作**：内嵌插一层、把原内容放进主输入槽位；删除
    去掉一层、把主输入提回来。两个操作互为逆，用户点错了原地就能撤。

    **上一版这里是 `promote_node()`（用选中节点替换掉它的父节点）——语义是"删掉我爸"，
    容易误操作，已按用户意见改掉。** 叶子上不可用（见 `can_delete_node()`）。
    """
    if not can_delete_node(rows, index):
        return [dict(r) for r in rows]
    rows = [dict(r) for r in rows]
    span = subtree_span(rows, index)
    arity = int(rows[index]["arity"])
    keep = child_indices(rows, index)[primary_arg_position(rows[index].get("name") or "", arity)]
    keep_span = subtree_span(rows, keep)
    return recompute_depths(
        rows[:index] + rows[keep:keep + keep_span] + rows[index + span:])


#: 函数名 -> 各参数的角色名，界面逐槽位标出来。**只收语义已定的多参函数**；`Min`/`Max`
#: 对称、一元函数只有一个参数、中缀运算符按字面读，标了没有信息量。
CALL_ARG_ROLES = {
    "Lerp": ("from", "to", "t"),
    "Clamp": ("value", "lo", "hi"),
    "SmoothStep": ("lo", "hi", "value"),
    "Remap": ("t", "lo", "hi", "from", "to"),
    "Pow": ("base", "exponent"),
}

#: 调用名 -> **真实语义**的极简说明，给界面用（用户文案规则：只写"这个东西干什么"，
#: 出处/置信度/验证过程一律不进去，那些在 docs/ 和代码注释里）。
#: **只收"名字说不完"的**：弧度/角度之分、`Log` 的底、`%` 的符号规则、插值类的公式。
#: 用数学记法写，跨语言通用、不用过 i18n。
CALL_SEMANTICS = {
    "%": "fmod（符号跟被除数）",
    "Sin": "sin (rad)",
    "Cos": "cos (rad)",
    "Asin": "asin (rad)",
    "Acos": "acos (rad)",
    "SinDeg": "sin (deg)",
    "CosDeg": "cos (deg)",
    "Log": "ln",
    "Saturate": "clamp(x, 0, 1)",
    "Lerp": "from + (to - from) * saturate(t)",
    "Clamp": "max(lo, min(hi, value))",
    "SmoothStep": "u*u*(3-2*u), u = saturate((value-lo)/(hi-lo))",
    "Remap": "from + (to - from) * saturate((t-lo)/(hi-lo))",
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
#: 只收**语义已定、而且真的保持单位**的那些（给没确认的东西编一个"它和角度同单位"就是
#: 把猜测画成确定）：
#:
#:   `+` / `-` / `%` / `Min` / `Max`   两侧和结果同单位
#:   `Lerp(from, to, t)`               输出和两个端点同单位，`t` 无量纲
#:   `Clamp(value, lo, hi)`            输出和三个参数全部同单位
#:   `Remap(t, lo, hi, from, to)`      输出和两个端点同单位；`t`/`lo`/`hi` 自成一个单位组
#:   `Abs` / `Floor` / `Ceil`          逐点保持单位
#:
#: ⚠ **不收**：`*`（只有一侧带单位，从结构分不出哪侧）、`/`（结果单位是商）、`^`/`Pow`
#: （指数无量纲、底数单位不守恒）；`SmoothStep` 的输出是无量纲的 `[0,1]`，它的三个参数
#: 自成一个单位组（常见的是帧数，见 `SmoothStep(0, 120, TIMER)`）；三角/对数/指数/
#: `Saturate` 的输入输出也不是同一个物理量。
_UNIT_PRESERVING_ARG_POSITIONS = {
    "+": (0, 1),
    "-": (0, 1),
    "%": (0, 1),
    "Min": (0, 1),
    "Max": (0, 1),
    "Lerp": (0, 1),
    "Clamp": (0, 1, 2),
    "Remap": (3, 4),
    "Abs": (0,),
    "Floor": (0,),
    "Ceil": (0,),
}


def propagate_same_unit_as_root(rows):
    """从根节点（这条曲线赋值给目标字段的那个值）出发，标出哪些行和根节点是**同一个
    物理量**（比如都是弧度制角度）——给 `expr_edit.py` 的"角度显示"开关用：只有落在
    这个集合里的 `CONST` 槽位才该在开关打开时按度显示/输入，其余（比如
    `SmoothStep(0, 120, TIMER)` 里的 `0`/`120`，那是帧数阈值不是角度）必须保持原始单位，
    不然会把一个逐帧计数当角度换算，静默改坏语义完全不相关的常量。

    只在 `_UNIT_PRESERVING_ARG_POSITIONS` 覆盖的运算上继续往下传播，其余（`SmoothStep`、
    `*`/`/`、未确认函数）一律截断——不确定就不传，比传错安全。

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
        name = (row.get("name") or "").strip()
        return display_var_name(name) or "?"
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
