"""
tools/scan_flag_bits.py —— 普查"开头是 uint Flags 的 Type 属性"，把 Flags 逐位拆开找规律

    dotnet build tools/EfxBridge -p:LangVersion=preview
    dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll flagsurvey <语料目录> flagsurvey.json 200
    python tools/scan_flag_bits.py flagsurvey.json [报告输出路径，默认同目录 flag_bits_report.txt]

动机（用户提出的假说，参照姊妹项目 EFX-Editor/MHWI 的既有结论）：这类开头 `uint Flags` 字段
不是一整块不可拆的位掩码，很可能是"一个无规律/均匀分布的类型选择子字段（姊妹项目管这个叫
typeFlag，不拆）" + "若干各自独立的布尔开关位，每一位控制同一属性里某个具体字段是否生效"
叠在一起的。TypeBillboard3D 手测已经验证过这个结构：bit2 开着时 Intensity 才非零，bit4 开着
时 ColorRange 才不是默认白色——这两位跟"类型选择"无关，是纯粹的字段开关。

方法：`flagsurvey` 命令已经把全语料按 (attribute 类型, Flags 取值) 分桶、桶内其它字段的取值
分布都统计好了。这里只做纯统计意义上的"逐位分解"：
  1. 把每个类型下所有出现过的 Flags 取值按 bit0..bit31 拆开，分成"这一位为 1"/"这一位为 0"
     两组（组内按各取值桶的实例数加权合并）。
  2. 对同一属性里的每个其它字段，看它在"该位为 0"那组里最常见的取值（记 mode_off，占比 p_off），
     再看这个 mode_off 在"该位为 1"那组里的占比 p_on；signal = p_off - p_on（越接近 1 说明这一位
     一开，这个字段就整体脱离默认值 —— 越像是这个字段的启用开关）。反向（以 mode_on 为基准）
     同样算一遍，取绝对值更大的一个。
  3. 只在两组样本量都 >= MIN_GROUP_N 时才采信，避免小样本噪声（这份语料里很多 Flags 组合
     只出现几次到十几次）。
  4. 每一位报告"信号最强的字段"；如果没有任何字段过 SIGNAL_THRESHOLD，这一位就标"无信号"——
     大概率是姊妹项目所说的类型选择子字段的一部分，不是独立布尔开关；具体几位合起来构成那个
     子字段，得看这些"无信号位"是否总是成组同时出现同一批固定组合（本脚本只给出无信号位列表，
     不代替实机确认）。

**这终究是语料统计得出的相关性，不是实机确认**（CLAUDE.md 铁律 #6）。报告只用来筛出"值得优先
实机验证"的候选位 + 候选字段，不能直接当结论写进面板文案。
"""
import json
import sys
import os

MIN_GROUP_N = 30       # 每组（该位=0 / =1）样本量门槛，低于此不采信
SIGNAL_THRESHOLD = 0.3  # 判定为"这一位是该字段开关"的最小 signal


def merge_field_hist(buckets, keys):
    """把给定 Flags 取值(keys)对应的多个桶，按字段名合并成一份 {字段: {取值: 次数}} 直方图。"""
    merged: dict[str, dict[str, int]] = {}
    total = 0
    for k in keys:
        b = buckets[k]
        total += b["count"]
        for fname, hist in b["fields"].items():
            dst = merged.setdefault(fname, {})
            for val, cnt in hist["top"].items():
                dst[val] = dst.get(val, 0) + cnt
    return merged, total


def field_signal(hist_off, total_off, hist_on, total_on, fname):
    off = hist_off.get(fname, {})
    on = hist_on.get(fname, {})
    if not off or not on or total_off < MIN_GROUP_N or total_on < MIN_GROUP_N:
        return None
    best = 0.0
    best_detail = None
    for mode_val, mode_cnt in off.items():
        p_off = mode_cnt / total_off
        p_on = on.get(mode_val, 0) / total_on
        sig = p_off - p_on
        if abs(sig) > abs(best):
            best = sig
            best_detail = (mode_val, p_off, p_on, "off_default_suppressed_on")
    for mode_val, mode_cnt in on.items():
        p_on = mode_cnt / total_on
        p_off = off.get(mode_val, 0) / total_off
        sig = p_on - p_off
        if abs(sig) > abs(best):
            best = sig
            best_detail = (mode_val, p_off, p_on, "on_default_suppressed_off")
    return (best, best_detail)


def analyze_type(type_name, type_data):
    buckets = type_data["buckets"]
    flag_values = [int(k) for k in buckets]
    max_bit = max((v.bit_length() for v in flag_values), default=0)
    total_instances = type_data["instances"]

    lines = [f"=== {type_name}  (实例数 {total_instances}, 不同 Flags 取值 {len(flag_values)}) ==="]
    all_field_names = set()
    for b in buckets.values():
        all_field_names.update(b["fields"].keys())

    any_signal = False
    unsignaled_bits = []
    for bit in range(max(max_bit, 1)):
        mask = 1 << bit
        on_keys = [str(v) for v in flag_values if v & mask]
        off_keys = [str(v) for v in flag_values if not (v & mask)]
        if not on_keys or not off_keys:
            continue  # 这一位在语料里恒为常数，测不出任何信号
        hist_on, total_on = merge_field_hist(buckets, on_keys)
        hist_off, total_off = merge_field_hist(buckets, off_keys)
        if total_on < MIN_GROUP_N or total_off < MIN_GROUP_N:
            continue

        scored = []
        for fname in all_field_names:
            r = field_signal(hist_off, total_off, hist_on, total_on, fname)
            if r is not None:
                scored.append((fname, r[0], r[1]))
        scored.sort(key=lambda x: -abs(x[1]))

        top = [s for s in scored if abs(s[1]) >= SIGNAL_THRESHOLD]
        if top:
            any_signal = True
            f, sig, (val, p_off, p_on, direction) = top[0]
            lines.append(
                f"  bit{bit} (0x{mask:02x}): on n={total_on} off n={total_off}  "
                f"-> 候选开关字段 {f}  signal={sig:+.2f}  "
                f"(取值 {val}: off占比{p_off:.2f} / on占比{p_on:.2f}, {direction})"
            )
            for f2, sig2, (val2, p_off2, p_on2, dir2) in top[1:3]:
                lines.append(f"           次强: {f2}  signal={sig2:+.2f}  (取值 {val2})")
        else:
            unsignaled_bits.append(bit)

    if unsignaled_bits:
        lines.append(f"  无信号位（候选类型选择子字段的组成部分，需实机确认）: {unsignaled_bits}")
    if not any_signal:
        lines.append("  （全部位都测不出任何字段级信号——这个 Flags 可能整体就是姊妹项目那种 typeFlag）")
    return "\n".join(lines), any_signal


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    survey_path = sys.argv[1]
    report_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(survey_path)), "flag_bits_report.txt")

    data = json.load(open(survey_path, encoding="utf-8"))
    types = data["types"]

    report_sections = []
    types_with_signal = []
    types_without_signal = []
    for type_name in sorted(types):
        section, any_signal = analyze_type(type_name, types[type_name])
        report_sections.append(section)
        (types_with_signal if any_signal else types_without_signal).append(type_name)

    header = (
        f"共 {len(types)} 个带顶层数字字段 Flags 的 attribute 类型，"
        f"{len(types_with_signal)} 个测出至少一位有字段级信号，"
        f"{len(types_without_signal)} 个完全测不出信号。\n"
        f"测不出信号的类型（可能是 typeFlag 式无关字段，或该类型语料量太小/字段本来就没有\"默认值\"落差）：\n"
        f"  {', '.join(types_without_signal)}\n"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(header + "\n" + "\n\n".join(report_sections))

    print(header)
    print(f"完整报告已写到: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
