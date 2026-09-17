# -*- coding: utf-8 -*-
"""
tools/infer_expression_bit_fields.py —— 推断 Expression 的无名 bit 驱动本体的哪个字段

    dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll exprhostcorr <语料目录> hostcorr.json
    python tools/infer_expression_bit_fields.py hostcorr.json [--type Velocity3DExpression] [--all]

`exprhostcorr` 只吐原始计数，**判据全在这个文件里**——改判据不用重新编译 C#，而且"依据"和
"结论"分开看得见（同 `tools/audit_range_fields.py` 的先例）。

## 为什么需要推断

vendor 的 `BitNameDict` 只给一部分 bit 起了名（`nameof(speed)` 这种），其余是按声明顺序
补出来的占位名 `unkn<N>`。`efx_sim/simulator.py::_EXPR_FIELD_OVERRIDES` 只能收有名字的，
于是占位名那些 bit 上的公式在预览里**整条定位不到**（会 note，不会假装算对）。全语料里
这类"真被作者用过、但我们不知道它改什么"的 bit 有几百处。

## 正对照是这个脚本的核心，不是附属品

有名字的 bit 是**现成的已知答案**。任何判据先拿它们试：推不出 `speed -> Speed`、
`velocityY -> DirectionVectorY`、`appearLife -> AppearFrame` 的判据，没资格拿去推未知的。
两条一开始看着很有道理的判据就是这么被否掉的，结论记在这儿免得有人再走一遍：

- **❌ Multiply 退化性**（"`Multiply` 把结果乘在导入原值上，原值 0 就恒为 0，作者不会写
  恒为 0 的曲线，所以候选字段在 Multiply 样本里出现过 0 就能排除"）。听着很硬，**正对照
  直接否掉**：`speed` 的 567 个 Multiply 样本里，`Speed == (0,0)` 的真实存在，于是这条判据
  把正确答案 `Speed` 自己排除了。要么作者确实留了一批死曲线（真实内容里很常见），要么
  `Multiply` 不是乘在这个存储值上——无论哪种，这条判据都不能用。
- **❌ 非默认率提升（lift）**（"作者会驱动一个字段，往往也会给它设个非默认基值"）。同样被
  正对照否掉：`speed` 那 1031 个样本里所有字段的 lift 都 ≈1.0，`Speed` 连前五都进不去。
  原因是 `Assign` 会整个覆盖存储值，作者根本没有理由再去调那个基值。

## ✅ 通过正对照的判据：作者给具名参数起的名字

公式里的标识符有一部分是**文件级具名参数**（`ExpressionParameters`，作者自己起的名）。
作者给参数起名时用的是"这个值拿去干什么"，于是它反过来指出了这一位驱动什么。正对照上
这条几乎全中：

    appearLife  <- `Appear`        keepLife   <- `Keep`      vanishLife <- `Vanish`
    speed       <- `UseVelocity`   velocityX/Y/Z <- `RotateX`/`RotateY`/`Direction`
    spawnNum    <- `Spawn`         emitterDelayFrame <- `Delay`
    rangeXMin/Max <- `RangeX`/`SCALE_X`   rangeZMin/Max <- `RangeZ`/`Zrange`

⚠ **只在作者按"量"起名时有效**。按"游戏状态"起名的参数（`DANGER`/`Charge`/`LvRate`/
`Length`/`IsBlue`）对任何字段都可能出现，零鉴别力——报告里把这类列出来但不据此下判断。
所以这条判据给出的是**语义类别**（颜色 / 不透明度 / 位置 Y / 旋转 / 范围），不是具体字段名；
要落到具体字段，还得配合本体里"还没被占掉的、类别对得上的字段只剩一个"这种排除。

## ❌ 没通过正对照的判据：`Assign` 公式的输出量级

`Assign` 把字段**直接替换**成公式结果，所以公式的输出区间必须落在这个字段合理的取值范围
里。拿 bit 的 `Assign` 桶公式（`exprhostcorr` 按 assign 分了桶，正是为了这个）扫一遍
`TIMER`，取输出区间，再和本体各字段自己的**全语料取值分布**比对：

    score = 落进该字段非零取值区间的采样点比例  /  log(1 + 该字段区间宽度)

分母是"区间越宽越不说明问题"的惩罚项——`Speed` 那种 0~1500 的宽区间几乎什么都装得下，
`SpeedCoef` 那种挤在 0.9~1.0 的窄区间才有鉴别力。

判据仍然是**统计相合，不是证明**。输出分三档：

    confirmed   已在 `_EXPR_FIELD_OVERRIDES` 里（正对照用，不是本脚本的结论）
    likely      第一候选的分数 >= 次候选的 2 倍，且量级吻合度 >= 0.8
    candidate   其余（照分数排序列出前三个，等实机或更多证据）

**`likely` 也不等于可以直接写进 `_EXPR_FIELD_OVERRIDES`**（铁律 #6）：写进去就意味着预览
会拿这个字段算曲线，猜错的代价是"画出一条看着合理的假曲线"，比"这条曲线没生效"更难发现。
判据是"错了会不会骗过人"，不是"证据够不够多"。

这条判据的正对照成绩是 **14/27**——同一个本体里一堆字段的取值区间本来就重叠（帧数都在
0~240、各种 rate 都在 0~1），量级分不开它们。保留它是因为它偶尔能在"类别已定、候选还剩
两三个"时当次级判据，**但它单独给出的第一候选不可信**。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from efx_sim import expr as _expr  # noqa: E402
from efx_sim.simulator import _EXPR_FIELD_OVERRIDES  # noqa: E402

#: 占位名（vendor 没给这一位起过名字，反射表按声明顺序补的）
_PLACEHOLDER_RE = re.compile(r"^(?:unkn|ukn|re\d+_unkn|rert_unkn|sb_unkn|dd2_unkn|prag_)", re.I)

#: 值键里的数字。`(0.98,0)` / `-0.4` / `(0,0,0)` 都走这条
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

#: 公式文本里的标识符（`ext:302732036` 这种带冒号的前缀也要整个吃掉）
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?::[A-Za-z_0-9]+)?")

#: `TIMER` 的扫描点。覆盖到 240 是因为语料里 `Clamp(TIMER, 240, 120)` 这种长窗口确实有
_TIMER_SWEEP = tuple(range(0, 241, 5))

#: 已知语义的函数名/内置变量，不能当成"外部未知参数"喂值
_RESERVED = frozenset({"PI", "TIMER", "RAND", "EM_INIRAND", "EM_INIRAND_SHARED", "PLAY_SPEED"})


def is_placeholder(bit_name: str) -> bool:
    return bool(bit_name) and bool(_PLACEHOLDER_RE.match(bit_name))


def numbers_in_value_key(key: str):
    """`"(0.98,0)"` -> `[0.98, 0.0]`。枚举名/字符串/布尔返回空——它们不可能是公式目标
    （公式结果是个 float，赋给枚举或字符串没有意义），空列表在下游直接让这个字段落选。"""
    if key in ("null", "True", "False") or key.startswith('"'):
        return []
    return [float(m.group()) for m in _NUMBER_RE.finditer(key)]


def field_span(hist):
    """字段的全语料取值分布 -> `(非零最小绝对值, 最大绝对值, 有效样本数)`。

    用绝对值：符号本身不提供量级信息，而 `GravityRate` 这类字段两个符号都有真实样本。
    """
    values = []
    total = 0
    for key, count in hist.items():
        nums = numbers_in_value_key(key)
        if not nums:
            continue
        total += count
        values.extend(abs(v) for v in nums if v != 0.0)
    if not values:
        return None
    return (min(values), max(values), total)


def author_params(bit):
    """这一位的公式里出现过的**作者具名参数** -> 出现次数（高到低）。

    排掉内置变量和函数名；`ext:<hash>` 那种引擎喂的外部量也排掉（它没有作者起的名字，
    `exprvarstats` 那条线才管它）。见模块说明——这是唯一通过正对照的判据。
    """
    hist = {}
    for bucket in (bit.get("formulas") or {}).values():
        for text, count in bucket.items():
            for name in _IDENT_RE.findall(text):
                if ":" in name or name in _RESERVED or name in _expr.CALL_SIGNATURES:
                    continue
                if _expr.normalize_call_name(name) in _expr.CALL_SIGNATURES:
                    continue
                hist[name] = hist.get(name, 0) + count
    return sorted(hist.items(), key=lambda kv: -kv[1])


#: 参数名里出现这些词就只反映"游戏状态"、不反映"驱动哪个量"，列出来但不参与判断
_STATE_WORDS = re.compile(
    r"^(?:DANGER|Charge|OverCharge|IsCharge|ChargeRate|Lv\d*|LvRate|Length|GLength|"
    r"IsFirst|IsConst|IsBlue|IsMultiple|IsUnderWater|IsPreview|Frenzy|Boost|PROCESS|"
    r"ESCAPE|APPEAR|RangeTime|ShieldState|BarrierRate|Hit_Col|NoteLife)$", re.I)


def informative_params(bit):
    return [(name, n) for name, n in author_params(bit) if not _STATE_WORDS.match(name)]


def component_count(hist):
    """字段的数值分量个数（`via.Range` = 2、`Vector3` = 3、`float` = 1）。取众数：
    同一个字段的所有取值键分量数本该一致，不一致说明这个字段不是纯数值，返回 0 让它落选。"""
    counts = {}
    for key, n in hist.items():
        nums = numbers_in_value_key(key)
        if nums:
            counts[len(nums)] = counts.get(len(nums), 0) + n
    return max(counts, key=counts.get) if counts else 0


#: bit 名的"副值"后缀。有这类后缀 = 它和相邻那一位共用一个字段的主/副值
#: （`speed`/`speedRand`、`rangeXMin`/`rangeXMax`、`appearLife`/`appearLifeRand`——
#: 四个已知类型全是这个形状），于是目标字段必须是个**两分量**字段。
_SECONDARY_SUFFIX_RE = re.compile(r"(?:Rand|Random|Range|Max)$")


def paired_regime(bits, index):
    """这一位是不是"主/副值成对"那种形状 -> 目标字段必须恰好两个数值分量。

    判据只看**名字**，不看下标奇偶：`Transform3DExpression` 的 9 位是
    `translationX/Y/Z`+`rotationX/Y/Z`+`scaleX/Y/Z`（驱动 `Vector3` 的某个分量，不成对），
    光看奇偶会把它们误判成成对。名字里带副值后缀的那一位、以及它紧邻的前一位，才算成对。
    """
    name = bits.get(str(index), {}).get("bitName", "") or ""
    if _SECONDARY_SUFFIX_RE.search(name):
        return True
    nxt = bits.get(str(index + 1), {}).get("bitName", "") or ""
    if not name or not _SECONDARY_SUFFIX_RE.search(nxt):
        return False
    return nxt.startswith(name[:3])


def formula_outputs(text):
    """一条公式在 `TIMER` 扫描下的输出采样。解析失败返回空列表（调用方跳过这条）。

    未知外部参数（`Charge`/`Length`/`ext:…` 这些，语义我们不掌握）按 0 和 1 各跑一遍——
    量级判据只需要知道"输出大致落在哪个数量级"，不需要知道这些参数的真实取值。
    """
    try:
        parsed = _expr.parse(text)
    except Exception:
        return []
    unknown = {name for name in _IDENT_RE.findall(text)
               if name not in _RESERVED and name not in _expr.CALL_SIGNATURES}
    out = []
    for extra in (0.0, 1.0):
        for timer in _TIMER_SWEEP:
            variables = {"PI": math.pi, "TIMER": float(timer), "RAND": 0.5,
                         "EM_INIRAND": 0.5, "EM_INIRAND_SHARED": 0.5, "PLAY_SPEED": 1.0}
            for name in unknown:
                variables[name] = extra
            ctx = _expr.EvalContext(variables, "identity", [])
            try:
                value = _expr.evaluate(parsed, ctx)
            except Exception:
                continue
            if isinstance(value, (int, float)) and math.isfinite(value):
                out.append(float(value))
    return out


def magnitude_score(outputs, span):
    """输出采样落进字段取值区间的比例，再按区间宽度惩罚。见模块说明的公式。"""
    if not outputs or span is None:
        return 0.0, 0.0
    lo, hi, _ = span
    lo = min(lo, hi)
    # 两端各放宽一档：作者完全可以用公式开出比语料静态值更大/更小的值
    lo_ok, hi_ok = lo * 0.5, hi * 2.0
    inside = sum(1 for v in outputs if lo_ok <= abs(v) <= hi_ok or (v == 0.0 and lo_ok <= 0))
    fit = inside / len(outputs)
    width_penalty = math.log(1.0 + (hi_ok / lo_ok if lo_ok > 0 else hi_ok + 1.0))
    return fit / max(1.0, width_penalty), fit


def known_answers():
    """`(hostType, bitName) -> fieldName`，取自 `_EXPR_FIELD_OVERRIDES`。正对照用。"""
    return {key: value[0] for key, value in _EXPR_FIELD_OVERRIDES.items()}


def rank_candidates(bit, baseline, taken, want_components=None):
    """`[(score, fit, fieldName), ...]` 从高到低。`taken` 是已被有名字的 bit 占掉的字段
    （bit <-> 字段是 1:1，见 docs/EXPRESSION_SEMANTICS.md §7.1），不再参与竞争。"""
    assign_formulas = (bit.get("formulas") or {}).get("Assign") or {}
    outputs = []
    for text in assign_formulas:
        outputs.extend(formula_outputs(text))
    rows = []
    for field, hist in baseline.items():
        if field in taken:
            continue
        if want_components is not None and component_count(hist) != want_components:
            continue
        score, fit = magnitude_score(outputs, field_span(hist))
        if score > 0.0:
            rows.append((score, fit, field))
    rows.sort(reverse=True)
    return rows, len(outputs)


def verdict(rows):
    if not rows:
        return "candidate"
    top = rows[0]
    runner = rows[1][0] if len(rows) > 1 else 0.0
    if top[1] >= 0.8 and top[0] >= 2.0 * runner:
        return "likely"
    return "candidate"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("hostcorr_json")
    ap.add_argument("--type", action="append", default=None, help="只看这些 Expression 类型")
    ap.add_argument("--all", action="store_true", help="连没被用过的 bit 也列出来")
    ap.add_argument("--min-set", type=int, default=1, help="至少被用过几次才列（默认 1）")
    args = ap.parse_args(argv)

    data = json.load(open(args.hostcorr_json, encoding="utf-8"))
    known = known_answers()

    control_hits, control_total, control_misses = 0, 0, []
    reports = []

    for type_name, tinfo in sorted(data["types"].items()):
        host = tinfo["hostType"]
        baseline = tinfo["hostBaseline"]
        bits = tinfo["bits"]
        taken = {field for (h, bit_name), field in known.items() if h == host}

        lines = []
        for index in sorted(bits, key=int):
            bit = bits[index]
            name = bit["bitName"]
            if bit["setCount"] < args.min_set and not args.all:
                continue

            answer = known.get((host, name))
            want = 2 if paired_regime(bits, int(index)) else None
            rows, n_out = rank_candidates(
                bit, baseline, taken - ({answer} if answer else set()), want)

            if answer is not None and is_placeholder(name):
                # 这一条是**我们自己推断**进覆盖表的（bit 名是占位名 = vendor 没给答案），
                # 不能拿它充正对照——那等于用推断去验证推断，分数会凭空变好看
                continue
            if answer is not None:
                control_total += 1
                got = rows[0][2] if rows else None
                if got == answer:
                    control_hits += 1
                else:
                    control_misses.append("%s.bit%s %s：正确答案 %s，判据给的是 %s"
                                          % (type_name, index, name, answer, got))
                continue

            if not is_placeholder(name):
                continue   # vendor 给了真名字但我们还没收进覆盖表——那是接线问题，不是推断问题

            lines.append((index, name, bit, rows, n_out))

        if lines and (not args.type or type_name in args.type):
            reports.append((type_name, host, lines))

    print("=" * 78)
    print("正对照：%d/%d 条已知答案被判据重新推出来" % (control_hits, control_total))
    for miss in control_misses:
        print("  MISS", miss)
    print("=" * 78)
    if control_total and control_hits * 2 < control_total:
        print("⚠ 判据连一半已知答案都推不出来 —— 下面的推断不要当结论用，只当『值得查的方向』。")
    print()

    for type_name, host, lines in reports:
        print("### %s  ->  本体 %s" % (type_name, host))
        for index, name, bit, rows, n_out in lines:
            assign_hist = (bit.get("formulas") or {}).get("Assign") or {}
            print("  bit%-3s %-12s 用过 %-5d  assign=%s  (Assign 公式 %d 条 / %d 个采样点)"
                  % (index, name, bit["setCount"], bit["assign"], len(assign_hist), n_out))
            print("        判定：%s" % verdict(rows))
            for score, fit, field in rows[:3]:
                print("          %-26s score=%.3f 量级吻合=%.2f" % (field, score, fit))
            info = informative_params(bit)
            if info:
                print("          ★ 作者具名参数（有信息量）  %s"
                      % ", ".join("%s×%d" % (n, c) for n, c in info[:6]))
            state = [n for n, _ in author_params(bit) if _STATE_WORDS.match(n)]
            if state:
                print("            （只反映游戏状态、不参与判断：%s）" % ", ".join(state[:6]))
            for text in list(assign_hist)[:3]:
                print("          公式样本  %s" % text)
            names = list(bit.get("entryNames") or {})[:4]
            if names:
                print("          entry 名   %s" % ", ".join(names))
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
