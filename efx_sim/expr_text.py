"""
efx_sim/expr_text.py —— Expression 公式的**规范记法**（给人读写的那一栏）⇄ 行视图

零 bpy，纯文本↔行视图转换，不参与求值。

## 为什么还需要它

vendor `1c2f92d` 起，引擎记法的名字、操作数顺序、参数顺序已经全部按真实语义写
（见 `expr.py` 模块 docstring），**符号和函数这一层不再需要任何转换**——以前那四个
操作数交换、`Pow`/`Clamp` 的参数重排、16 号改名全部删掉了。

剩下的差别只在**怎么读结构**，而这两条都会静默改语义，所以给人打的那一栏不能直接交给
vendor 解析器：

| | 引擎记法（`expr.parse`，镜像 vendor） | 规范记法（本模块） |
|---|---|---|
| `10 - 3 - 2` | `10 - (3 - 2)` = 9（右结合） | `(10 - 3) - 2` = 5 |
| `-2 ^ 2`     | `(-2) ^ 2` = 4               | `-(2 ^ 2)` = -4 |
| 括号         | 二元运算一律全括号              | 按优先级省括号，好读 |

规范记法就是数学惯例：`^` > 一元负 > `* / %` > `+ -`，`^` 右结合、其余左结合——正好是
Python 自己的那套，所以读的时候把 `^` 换成 `**` 交给 `ast`。写回引擎时走
`expr.from_rows()`（全括号），不依赖 vendor 的结合性。

⚠ `%` 是 **C 的 `fmod`**（符号跟被除数），不是 Python 的 `%`。这里只负责记法、不求值，
**别拿规范文本喂 Python `eval()`**，负数取模会得到不同答案。
"""
from __future__ import annotations

import ast

from . import expr


#: `ast` 节点类型 -> 中缀符号（和引擎记法同一套符号）
_CANONICAL_AST_OPS = {
    ast.Mult: "*", ast.Div: "/", ast.Mod: "%",
    ast.Add: "+", ast.Sub: "-", ast.Pow: "^",
}

#: 优先级（大的先算）。`^` 右结合，其余左结合。999 = 原子，永不需要括号。
_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 2, "^": 4}
_NEG_PRECEDENCE = 3
_ATOM_PRECEDENCE = 999

#: 规范记法的**函数写法别名** -> 中缀符号。只在**读**的时候认，写出去仍是中缀。
#: 只收 `Mod` 一个：`%` 这个符号不是人人第一反应会打的，实测有人直接打
#: `Mod(3*TIMER, TIMER)` 然后撞上"不支持的函数"。`Mod(a, b)` == `a % b`。
_CANONICAL_FUNCTION_ALIASES = {"Mod": "%"}


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
    # 优先级相同：左结合的**右**操作数要括号，右结合（`^`）的**左**操作数要括号。
    # 漏了括号就静默改语义：`2 - (TIMER - 1)` 少括号会拼成 `2 - TIMER - 1`。
    right_assoc = parent_prec == _PRECEDENCE["^"]
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
        # 负字面量本身算"一元负"级别，否则 `-1 ^ 2` 会被读成 `-(1 ^ 2)`
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

    if name in _PRECEDENCE:
        if arity != 2:
            raise expr.ExprError("二元运算符 %s 需要 2 个子节点，实际 %d 个" % (name, arity))
        prec = _PRECEDENCE[name]
        text = "%s %s %s" % (_wrap(parts[0][0], parts[0][1], prec, False),
                             name,
                             _wrap(parts[1][0], parts[1][1], prec, True))
        return text, prec, index

    if not name:
        raise expr.ExprError("函数节点的名字是空的")
    return ("%s(%s)" % (name, ", ".join(p for p, _ in parts)), _ATOM_PRECEDENCE, index)


# ---------------------------------------------------------------- 规范文本 -> 行

def canonical_to_rows(text):
    """规范记法文本 -> `expr.to_rows()` 那种行，返回 (rows, 第二根值)。

    第二根值（`a | b`）原样带回去，不做任何解释——语义没证实不等于可以丢（铁律 #1）。
    """
    raw = (text or "").strip() or "0"
    primary, secondary = expr._split_root_value(raw)
    # `^` 在 Python 里是异或；引擎记法里它只可能是幂，标识符里也不会出现
    source = expr._sanitize_identifiers(primary).replace("^", "**")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise expr.ExprError("公式语法错误：%s（原文：%r）" % (exc, primary)) from exc
    rows = []
    _collect_rows(tree.body, 0, rows)
    return rows, secondary


def _call_row(name, arity, depth):
    return {"kind": expr.KIND_CALL, "depth": depth, "arity": arity, "name": name, "value": 0.0}


def _collect_rows(node, depth, rows):
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
            _collect_rows(node.operand, depth, rows)
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
        _collect_rows(node.operand, depth + 1, rows)
        return
    if isinstance(node, ast.BinOp):
        symbol = _CANONICAL_AST_OPS.get(type(node.op))
        if symbol is None:
            raise expr.ExprError("规范记法里没有这个二元运算符：%r" % (node.op,))
        rows.append(_call_row(symbol, 2, depth))
        _collect_rows(node.left, depth + 1, rows)
        _collect_rows(node.right, depth + 1, rows)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise expr.ExprError("不支持的函数调用形式：%s" % (ast.dump(node),))
        name = _CANONICAL_FUNCTION_ALIASES.get(node.func.id, node.func.id)
        if name in _PRECEDENCE and len(node.args) != 2:
            raise expr.ExprError("%s 需要 2 个参数，实际 %d 个" % (node.func.id, len(node.args)))
        rows.append(_call_row(name, len(node.args), depth))
        for arg in node.args:
            _collect_rows(arg, depth + 1, rows)
        return
    raise expr.ExprError("不支持的语法节点：%r" % (type(node).__name__,))


# ---------------------------------------------------------------- 文本 <-> 文本

def vendor_to_canonical(formula_text):
    """引擎记法文本 -> 规范记法文本。"""
    parsed = expr.parse(formula_text)
    return rows_to_canonical(expr.to_rows(parsed), parsed.second_branch)


def canonical_to_vendor(canonical_text):
    """规范记法文本 -> 引擎记法文本（全括号，可以直接写回 JSON / 参与往返）。"""
    rows, secondary = canonical_to_rows(canonical_text)
    return expr.from_rows(rows, secondary)
