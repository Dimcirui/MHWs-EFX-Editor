"""
efx_sim/expr_text.py —— Expression 公式的**记法中转层**（vendor 记法 ⇄ 规范记法）

零 bpy，纯文本↔行视图转换，不参与求值。

## 为什么需要它

`.efx` 文件里存的是**操作码对**（`type, value`），公式文本压根不进文件——它只是 vendor
的 `ExpressionAtom.ToString()` / `EfxExpressionParser` 在 JSON 那一段的记法。而 vendor
给六个二元操作码起的名字**曾经一个都不对**；上游 `a96e1d9` 已经按真实语义重命名了
（`Pow`/`Mul`/`Div`/`Mod`/`Add`/`Sub`），但**操作数顺序没跟着翻**——`ToString()` 仍然打印
`(left OP right)`，而引擎的顺序是 `right OP left`。所以六个里还有四个反着：`/`、`-`、
`Mod(`、`PowOp(`。照字面写仍然会错：想要 `1 - TIMER/60`，原样打进去会被读成
`(60/TIMER) - 1`。

这一层把两套记法隔开：

- **vendor 记法**：`EfxExpressionParser` 认的唯一写法。行数据里存的、写回 JSON 的、
  参与逐字节往返的，永远是这一侧。**一个字符都不许改**。
- **规范记法**：给人看/给人打的写法，运算符按真实语义写，优先级正好就是 Python 自己的
  那套（`**` > 一元负 > `* / %` > `+ -`），函数名用 `CALL_DISPLAY_NAMES` 的规范名。

## 对照表

| 操作码 | vendor 文本 | 规范文本 | 真实语义 | 还需要转换吗 |
|---|---|---|---|---|
| 1 | `(a * b)`      | `a * b`  | `a * b` | 不用（可交换）|
| 4 | `(a + b)`      | `a + b`  | `a + b` | 不用（可交换）|
| 2 | `(a / b)`      | `b / a`  | `b / a` | **换操作数** |
| 5 | `(a - b)`      | `b - a`  | `b - a` | **换操作数** |
| 3 | `Mod(a, b)`    | `b % a`  | `fmod(b, a)` | **换操作数 + 变中缀** |
| 0 | `PowOp(a, b)`  | `b ** a` | `pow(b, a)` | **换操作数 + 变中缀** |

**操作数顺序要翻**（除了可交换的乘/加）——引擎的操作数顺序和 vendor 的 left/right 相反
（`UnflattenExpression()` 倒着走组件流，`left` 是先消费的那个），这是四个 `swap=True`
的来源，不是笔误。

⚠ `PowOp` 这个字面量是**我们的 vendor 补丁 0007** 起的名：上游把操作码 0 也叫 `Pow`，
和函数表里的 `Pow`（操作码 20）在文本上撞名，而解析器的 `args == 2` 分支先试
`BinaryExpressionOperator`——于是**每次 dump/load 都把操作码 20 静默改写成 0**（实测字节
级确认）。补丁把操作码 0 改名成 `PowOp`，用户永远看不到它（界面显示中缀 `**`）。

⚠ 规范记法里的 `%` 是 **C 的 `fmod`**（符号跟被除数），不是 Python 的 `%`（符号跟除数）。
求值走 `expr._eval_binary_operator()`，那边用的是 `math.fmod`；这里只负责记法、不求值，
所以两者不冲突——但**别拿规范文本喂 Python `eval()`**，负数取模会得到不同答案。

## 一个红利

旧 vendor 里 `Min`/`Max` 是操作码 5 / 0（减和幂），和函数表里的真 min/max 撞名。
a96e1d9 之后 18 / 19 号自己就叫 `Min`/`Max`，这个歧义没了——但"规范名不许抢 vendor
字面量"那条判据要留着，下次再加显示名还得过这一关。

## vendor 改对之后怎么退役

上游把**操作数顺序**也翻过来（`a96e1d9` 只改了名字）、并且把 16 号 `InvLerp` 改成
`Clamp` 之后，两套记法就完全合流，本模块可以整个删掉。剩下的差异就只有这两项：

- `CANONICAL_OPERATORS` 里那四个 `swap=True`
- `CALL_DISPLAY_NAMES` 里唯一的非恒等项 `InvLerp -> Clamp`

**映射表集中在 `efx_sim/expr.py` 顶部**（本模块只引用），就是为了那一天只改那两处。
"""
from __future__ import annotations

import ast

from . import expr


#: vendor 中缀符号 / 函数写法 -> (规范中缀符号, 是否交换操作数)
#: 键里的 `Min` / `Max` 是**函数写法的操作码 5 / 0**，不是函数表里的 18 / 19。
#: **不在这里另写一张表**——两处各一份迟早会漂，而漂了之后文本往返照样全绿
#: （双向一致的错误对往返完全免疫，见模块 docstring）。
_VENDOR_TO_CANONICAL = dict(expr.CANONICAL_OPERATORS)

#: 上一张表的逆。规范符号 -> (vendor 名字, 是否交换操作数)
_CANONICAL_TO_VENDOR = {
    canon: (vendor, swap) for vendor, (canon, swap) in _VENDOR_TO_CANONICAL.items()
}

#: `ast` 节点类型 -> 规范记法的中缀符号（解析规范文本时用）
_CANONICAL_AST_OPS = {
    ast.Mult: "*", ast.Div: "/", ast.Mod: "%",
    ast.Add: "+", ast.Sub: "-", ast.Pow: "**",
}

#: 优先级（大的先算）。`**` 右结合，其余左结合。999 = 原子，永不需要括号。
_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 2, "**": 4}
_NEG_PRECEDENCE = 3
_ATOM_PRECEDENCE = 999

#: vendor 函数字面量 -> 规范函数名。**排掉 `Min`/`Max`**——它们在规范记法里是中缀。
_FUNC_TO_CANONICAL = {
    vendor: display for vendor, display in expr.CALL_DISPLAY_NAMES.items()
    if vendor not in _VENDOR_TO_CANONICAL
}
_FUNC_TO_VENDOR = {display: vendor for vendor, display in _FUNC_TO_CANONICAL.items()}

#: vendor 函数 -> 规范记法下的**参数重排**（值是"规范侧第 i 个参数取 vendor 侧第几个"）。
#:
#: 只收两个。`Pow`（操作码 20）的理由是**记法内部必须自洽**：操作码 0 在规范记法里变成了
#: 中缀 `b ** a`（底在左、指数在右），而 `Pow` 是同一个 pow、vendor 侧参数顺序却是
#: `(指数, 底)`。不重排的话规范记法里会同时存在 `a ** b` 和 `Pow(b, a)` 两种相反的读法，
#: 正是这层要消灭的东西。
#:
#: ⚠ **别顺手把 `Lerp`/`Func21` 也收进来**：那两个的参数顺序反直觉归反直觉，界面上由
#: `expr.CALL_ARG_ROLES` 逐槽位标出来（见 docs/EXPRESSION_RULES.md），行视图和参数角色名都是 vendor 一侧的；
#: 在这里再重排一次，文本和行视图就会对不上。`Func20` 能收是因为它有中缀孪生兄弟、
#: 不重排就自相矛盾，其余的没有这个问题。
#: `InvLerp` 收进来的理由同上：它的规范名是 `Clamp`，而 vendor 侧参数序是
#: `(hi, lo, value)`——**一个叫 `Clamp` 的函数把 value 放在最后**，照字面读必错，
#: 正是这层要消灭的东西。重排成 `Clamp(value, lo, hi)`（= 人人预期的那个顺序）。
#: 节点视口的插槽顺序走 `display_arg_order()`，所以文本和节点视图自动一致。
_FUNC_ARG_ORDER = {"Pow": (1, 0), "InvLerp": (2, 1, 0)}


#: 规范记法的**函数写法别名** -> (vendor 二元操作码名, 是否交换操作数)。只在**读**规范
#: 文本时认，发射时仍然发中缀符号。
#:
#: 只收 `Mod` 一个：`%` 这个符号不是人人第一反应会打的，实测有人直接打
#: `Mod(3*TIMER, TIMER)` 然后撞上"不支持的函数"。
#:
#: 规范侧 `Mod(a, b)` = `fmod(a, b)`（模数在**右**，和 C 一致）；vendor 侧的
#: `Mod(a, b)` 是 `fmod(b, a)`（模数在左），所以要交换。**两边同名、顺序相反**，
#: 这正是不能靠"名字一样就直接透传"的例子。
_CANONICAL_FUNCTION_ALIASES = {"Mod": ("Mod", True)}


def _reorder(vendor_name, args, invert=False):
    """按 `_FUNC_ARG_ORDER` 重排参数（`invert=True` 走反方向）。"""
    order = _FUNC_ARG_ORDER.get(vendor_name)
    if order is None or len(args) != len(order):
        return list(args)
    if invert:
        out = [None] * len(args)
        for canon_pos, vendor_pos in enumerate(order):
            out[vendor_pos] = args[canon_pos]
        return out
    return [args[i] for i in order]


def display_arg_order(vendor_name, arity):
    """规范记法下，这个调用的参数该按什么顺序摆给人看。

    返回长度 `arity` 的列表，第 i 项是「显示位置 i」对应的 **vendor 参数下标**——
    也就是 `_reorder()` 用的那种 order 元组，只是把两种来源（二元操作码的 `swap`、
    函数的 `_FUNC_ARG_ORDER`）合成一份，并且对不认识的名字退化成恒等序。

    节点视口的输入插槽顺序走这个函数。**不要在节点层另写一张表**：vendor 的六个二元
    操作码里有四个操作数顺序是反的，两处各维护一份的话，漂了之后文本往返照样全绿
    （双向一致的错误对往返免疫，见模块 docstring）。
    """
    arity = int(arity)
    entry = _VENDOR_TO_CANONICAL.get(vendor_name)
    if entry is not None and arity == 2:
        return [1, 0] if entry[1] else [0, 1]
    order = _FUNC_ARG_ORDER.get(vendor_name)
    if order is not None and len(order) == arity:
        return list(order)
    return list(range(arity))


def canonical_function_name(vendor_name):
    """vendor 函数字面量 -> 规范函数名（认不出来的原样返回，不装作知道）。"""
    return _FUNC_TO_CANONICAL.get(vendor_name, vendor_name)


def vendor_function_name(canonical_name):
    """规范函数名 -> vendor 函数字面量（认不出来的原样返回）。"""
    return _FUNC_TO_VENDOR.get(canonical_name, canonical_name)


def _reject_vendor_literal(name):
    """规范文本里出现 vendor 字面量时**直接拒绝**，并告诉用户规范名叫什么。

    ⚠ 这条是被真事故催出来的：把 vendor 写法 `(0.01 + InvLerp(60, 0, TIMER))` 粘进
    只认规范记法的公式栏，`+` 被当成加法、`InvLerp` 被当成"不认识的名字"原样透传，
    **而它在 `_FUNC_ARG_ORDER` 里有重排条目，于是参数被悄悄倒过来**
    （`InvLerp(60,0,TIMER)` -> `InvLerp(TIMER,0,60)`）。结果是个语法合法、能求值、
    但含义完全不同的公式（0.01 + clamp(...) 而不是 0.01 * clamp(...)，量级差 100 倍）。

    "认不出来的名字原样透传"这条只该覆盖**我们真的不知道语义**的名字
    （`Unary3`、将来的新操作码）。**已知语义、只是用了 vendor 那一侧名字**的一律拒绝
    ——静默改含义比报错糟得多（铁律 #1 的文本版）。
    """
    canonical = expr.CALL_DISPLAY_NAMES.get(name)
    if canonical is None or canonical == name or name in _FUNC_TO_VENDOR:
        return
    roles = expr.CALL_ARG_ROLES.get(name)
    hint = ""
    if roles:
        order = display_arg_order(name, len(roles))
        hint = "（参数序 %s）" % ", ".join(roles[i] for i in order)
    raise expr.ExprError(
        "`%s` 是引擎那一侧的写法，规范记法里叫 `%s`%s。"
        "整条公式别混两种写法——引擎写法里 `/` `-` `Mod(` `PowOp(` 的操作数顺序是反的。"
        % (name, canonical, hint))


# ---------------------------------------------------------------- 行 -> 规范文本

def rows_to_canonical(rows, second_branch=None):
    """`expr.to_rows()` 的行 -> 规范记法文本。

    括号按**真实优先级**省（`expr._emit_rows()` 那边是无条件加括号，因为它要逐字复刻
    vendor 的 `ToString()`；这边没有那个约束，目标是好读）。
    """
    text, _prec, used = _emit_canonical(list(rows), 0)
    if used != len(rows):
        raise expr.ExprError("行列表尾部多出 %d 行没被消费（arity 和实际子节点数对不上）"
                             % (len(rows) - used))
    if second_branch:
        text += expr._ROOT_VALUE_SEPARATOR + second_branch
    return text


def _wrap(text, child_prec, parent_prec, is_right):
    """按优先级/结合性决定要不要给子表达式加括号。"""
    if child_prec > parent_prec:
        return text
    if child_prec < parent_prec:
        return "(" + text + ")"
    # 优先级相同：左结合的**右**操作数要括号，右结合（`**`）的**左**操作数要括号。
    # ⚠ 这条对 `swap=True` 的四个操作码尤其要紧——操作数换过位置之后，vendor 侧的
    # "左子树"会落到规范侧的右操作数上，结合性跟着翻。漏了括号就静默改语义：
    # `Min(Min(1, TIMER), 2)` 是 `2 - (TIMER - 1)`，少括号会拼成 `2 - TIMER - 1`。
    right_assoc = parent_prec == _PRECEDENCE["**"]
    return "(" + text + ")" if is_right != right_assoc else text


def _emit_canonical(rows, index):
    """从 `rows[index]` 起消费一棵子树，返回 (文本, 本节点优先级, 下一个下标)。"""
    if index >= len(rows):
        raise expr.ExprError("行列表提前结束（缺子节点）")
    row = rows[index]
    kind = row["kind"]
    index += 1

    if kind == expr.KIND_CONST:
        text = expr.format_float(float(row.get("value", 0.0)))
        # 负字面量本身算"一元负"级别，否则 `-1 ** 2` 会被读成 `-(1 ** 2)`
        return text, (_NEG_PRECEDENCE if text.startswith("-") else _ATOM_PRECEDENCE), index
    if kind == expr.KIND_VAR:
        name = (row.get("name") or "").strip()
        if not name:
            raise expr.ExprError("变量节点的名字是空的")
        return expr.display_var_name(name), _ATOM_PRECEDENCE, index
    if kind == expr.KIND_NEG:
        inner, inner_prec, index = _emit_canonical(rows, index)
        # `--1` 语法非法，判据用"子文本是不是以减号开头"而不是"值是不是负的"
        if inner_prec < _NEG_PRECEDENCE or inner.startswith("-"):
            inner = "(" + inner + ")"
        return "-" + inner, _NEG_PRECEDENCE, index
    if kind != expr.KIND_CALL:
        raise expr.ExprError("未知的行 kind：%r" % (kind,))

    name = (row.get("name") or "").strip()
    arity = int(row.get("arity", 0))
    parts = []
    for _ in range(arity):
        part, part_prec, index = _emit_canonical(rows, index)
        parts.append((part, part_prec))

    mapped = _VENDOR_TO_CANONICAL.get(name)
    if mapped is not None:
        symbol, swap = mapped
        if arity != 2:
            raise expr.ExprError("二元操作码 %s 需要 2 个子节点，实际 %d 个" % (name, arity))
        left, right = (parts[1], parts[0]) if swap else (parts[0], parts[1])
        prec = _PRECEDENCE[symbol]
        text = "%s %s %s" % (_wrap(left[0], left[1], prec, False),
                             symbol,
                             _wrap(right[0], right[1], prec, True))
        return text, prec, index

    if not name:
        raise expr.ExprError("函数节点的名字是空的")
    texts = _reorder(name, [p for p, _ in parts])
    return ("%s(%s)" % (canonical_function_name(name), ", ".join(texts)),
            _ATOM_PRECEDENCE, index)


# ---------------------------------------------------------------- 规范文本 -> 行

def canonical_to_rows(text):
    """规范记法文本 -> `expr.to_rows()` 那种行（**vendor 一侧**），返回 (rows, 第二根值)。

    第二根值（`a | b`）原样带回去，不做任何解释——语义没证实不等于可以丢（铁律 #1）。
    """
    raw = (text or "").strip() or "0"
    primary, secondary = expr._split_root_value(raw)
    try:
        tree = ast.parse(expr._sanitize_identifiers(primary), mode="eval")
    except SyntaxError as exc:
        raise expr.ExprError("公式语法错误：%s（原文：%r）" % (exc, primary)) from exc
    rows = []
    _collect_vendor_rows(tree.body, 0, rows)
    return rows, secondary


def _collect_vendor_rows(node, depth, rows):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise expr.ExprError("不支持的字面量：%r" % (node.value,))
        rows.append({"kind": expr.KIND_CONST, "depth": depth, "arity": 0,
                     "name": "", "value": float(node.value)})
        return
    if isinstance(node, ast.Name):
        name = expr.vendor_var_name(expr._desanitize_identifier(node.id))
        rows.append({"kind": expr.KIND_VAR, "depth": depth, "arity": 0,
                     "name": name, "value": 0.0})
        return
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.UAdd):
            _collect_vendor_rows(node.operand, depth, rows)
            return
        if not isinstance(node.op, ast.USub):
            raise expr.ExprError("不支持的一元运算符：%r" % (node.op,))
        # 和 `expr._collect_rows()` 一样把 `-字面量` 折叠成一行带符号常量
        if (isinstance(node.operand, ast.Constant)
                and not isinstance(node.operand.value, bool)
                and isinstance(node.operand.value, (int, float))):
            rows.append({"kind": expr.KIND_CONST, "depth": depth, "arity": 0,
                         "name": "", "value": -float(node.operand.value)})
            return
        rows.append({"kind": expr.KIND_NEG, "depth": depth, "arity": 1,
                     "name": "", "value": 0.0})
        _collect_vendor_rows(node.operand, depth + 1, rows)
        return
    if isinstance(node, ast.BinOp):
        symbol = _CANONICAL_AST_OPS.get(type(node.op))
        if symbol is None:
            raise expr.ExprError("规范记法里没有这个二元运算符：%r" % (node.op,))
        vendor_name, swap = _CANONICAL_TO_VENDOR[symbol]
        rows.append({"kind": expr.KIND_CALL, "depth": depth, "arity": 2,
                     "name": vendor_name, "value": 0.0})
        left, right = (node.right, node.left) if swap else (node.left, node.right)
        _collect_vendor_rows(left, depth + 1, rows)
        _collect_vendor_rows(right, depth + 1, rows)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise expr.ExprError("不支持的函数调用形式：%s" % (ast.dump(node),))
        alias = _CANONICAL_FUNCTION_ALIASES.get(node.func.id)
        if alias is not None:
            vendor_name, swap = alias
            if len(node.args) != 2:
                raise expr.ExprError("%s 需要 2 个参数，实际 %d 个"
                                     % (node.func.id, len(node.args)))
            rows.append({"kind": expr.KIND_CALL, "depth": depth, "arity": 2,
                         "name": vendor_name, "value": 0.0})
            left, right = ((node.args[1], node.args[0]) if swap
                           else (node.args[0], node.args[1]))
            _collect_vendor_rows(left, depth + 1, rows)
            _collect_vendor_rows(right, depth + 1, rows)
            return
        _reject_vendor_literal(node.func.id)
        name = vendor_function_name(node.func.id)
        rows.append({"kind": expr.KIND_CALL, "depth": depth,
                     "arity": len(node.args), "name": name, "value": 0.0})
        for arg in _reorder(name, node.args, invert=True):
            _collect_vendor_rows(arg, depth + 1, rows)
        return
    raise expr.ExprError("不支持的语法节点：%r" % (type(node).__name__,))


# ---------------------------------------------------------------- 文本 <-> 文本

def vendor_to_canonical(formula_text):
    """vendor 公式文本 -> 规范记法文本。"""
    parsed = expr.parse(formula_text)
    return rows_to_canonical(expr.to_rows(parsed), parsed.second_branch)


def canonical_to_vendor(canonical_text):
    """规范记法文本 -> vendor 公式文本（可以直接写回 JSON / 参与往返）。"""
    rows, secondary = canonical_to_rows(canonical_text)
    return expr.from_rows(rows, secondary)
