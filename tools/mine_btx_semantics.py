#!/usr/bin/env python3
"""
tools/mine_btx_semantics.py —— 从 010 Editor 模板挖字段标注，生成
`blender_efx_re/semantics/mhws_field_labels_mined.json`。

来源：MHWs-EFX-Template（社区维护的 010 Editor 模板，https://github.com/…/MHWs-EFX-Template）
里的 `RE_EFX_STRUCTS.btx`。那份模板对 MHWs 语料的解析覆盖率是 8700/8704，字段命名和分组是
另一条独立的逆向路线，里面攒了两类我们没有的东西：

1. `<comment="中文说明">` —— 人写的字段语义（331 处）和结构体级中文名（53 处）。
2. `//Values:[...]`      —— 扫全语料统计出来的实测取值集合（1126 处）。

**只按名字匹配，不按顺序匹配。** 实测过：模板和 RE-Engine-Lib 是两条独立的逆向路线，对同一段
字节的切分方式不一样（C# 侧会把 Vector3 打包成子对象、有版本门控成员、拆合字段），231 个可读写
结构体里只有 35 个字段数一致，其中还有一半具名字段错位。按顺序对齐会大面积张冠李戴，比没有标注
更糟——所以宁可只收名字对得上的那部分。

结构体名倒是对得很好（256/281），因为两边都源自同一套 `ItemType` 枚举名。

产出分层（见 semantics/__init__.py）：
    mhws_field_labels_mined.json   本工具生成，最低优先级，可以随时整份重跑覆盖
    mhws_field_labels.json         手写，出厂默认，覆盖上面那份
    <用户配置目录>/…                用户个人标注，覆盖前两份
分成两个文件就是为了让"重跑挖掘"这个动作永远不会碰到手写的内容。

用法：
    # 1. 先让 EfxBridge 吐出权威的类型/JSON 键名清单
    dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll types /tmp/types.json
    # 2. 再挖
    python tools/mine_btx_semantics.py <RE_EFX_STRUCTS.btx 路径> /tmp/types.json
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

OUT_PATH = (pathlib.Path(__file__).resolve().parent.parent
            / "blender_efx_re" / "semantics" / "mhws_field_labels_mined.json")

# attribute 的记账字段，不是内容语义字段（见 model.ATTRIBUTE_BOOKKEEPING_KEYS）
BOOKKEEPING = {"IsTypeAttribute", "type", "UniqueID", "Version"}

EVIDENCE = ("010 Editor 模板 MHWs-EFX-Template / RE_EFX_STRUCTS.btx；"
            "由 tools/mine_btx_semantics.py 按字段名自动匹配导入")

COMMENT_RE = re.compile(r'comment\s*=\s*"([^"]*)"')
VALUES_RE = re.compile(r'//\s*Values:\s*(\[.*\])\s*$')
FIELD_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(<[^>]*>)?\s*;')

# 模板里属于 attribute 头部/占位的名字，永远不是内容字段
SKIP_FIELDS = {"itemType", "currentAttributeIndex"}

MAX_VALUES = 8  # 取值集合太长就截断，tooltip 里塞不下也没人看

# 模板把一个 via.Range 拆成两个标量字段（`AppearFrameMin` / `AppearFrameMax`），C# 侧是**一个**
# Range 对象（`AppearFrame`，面板上画成 Static/Random 两列）。剥掉这些后缀就能对上。
# 只在"剥完的名字确实是 C# 键名、且原名不是"时才生效，所以不会把本来就叫 XxxMax 的字段搞错。
RANGE_SUFFIXES = ("Min", "Max", "Variation")

# 两边对同一个概念起了完全不同的名字，机械规则救不了，只能逐条手查手写。
# 键是 (模板结构体名, 模板字段名)，值是 C# JSON 键名——加了结构体名限定，不会误伤别处的同名字段。
MANUAL_ALIASES = {
    ("Transform3D", "Translation"): "LocalPosition",
    ("Transform3D", "Rotation"): "LocalRotation",
    ("Transform3D", "Scale"): "LocalScale",
}


def parse_btx(path: pathlib.Path) -> dict:
    """把 RE_EFX_STRUCTS.btx 解析成 {结构体名: {"comment": str, "fields": {名: {...}}}}。"""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: dict = {}
    i = 0
    while i < len(lines):
        if not re.match(r'^\s*typedef\s+struct\b', lines[i]):
            i += 1
            continue
        # 按大括号配平找到块尾的 "}StructName<...>;"
        depth = 0
        started = False
        j = i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if "{" in lines[j]:
                started = True
            if started and depth == 0:
                break
            j += 1
        end = lines[j] if j < len(lines) else ""
        m = re.match(r'^\s*\}\s*(\w+)', end)
        if not m:
            i = j + 1
            continue

        struct_comment = COMMENT_RE.search(end)
        entry = {"comment": struct_comment.group(1) if struct_comment else "", "fields": {}}
        for ln in lines[i:j]:
            stripped = ln.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("local "):
                continue
            fm = FIELD_RE.match(ln)
            if not fm:
                continue
            fname = fm.group(2)
            if fname in SKIP_FIELDS:
                continue
            rec = {}
            fc = COMMENT_RE.search(fm.group(4) or "")
            if fc:
                rec["comment"] = fc.group(1).strip()
            vm = VALUES_RE.search(ln)
            if vm:
                rec["values"] = vm.group(1)
            if rec:
                entry["fields"][fname] = rec
        out[m.group(1)] = entry
        i = j + 1
    return out


def format_values(raw: str) -> str:
    """`[0.25, 1.0]` -> `实测取值：0.25 / 1.0`。解析不了就原样退回。

    这是**给使用者的事实**，不是出处，可以写进 tooltip（对齐姊妹项目 CLAUDE.md §4.1：
    具体统计数字应该写，验证状态不该写）。
    """
    try:
        vals = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    if not isinstance(vals, list) or not vals:
        return ""
    shown = vals[:MAX_VALUES]
    text = " / ".join(repr(v) if not isinstance(v, str) else v for v in shown)
    if len(vals) > MAX_VALUES:
        text += f" …（共 {len(vals)} 种）"
    return "实测取值：" + text


def resolve_key(struct_name: str, field_name: str, json_keys: set[str]) -> str | None:
    """模板字段名 -> C# JSON 键名；对不上返回 None。

    四步，越往后越宽松，但每一步都要求"落点确实是一个真实存在的 C# 键"，所以不会凭空造出
    对不上的条目：
      1. 完全同名
      2. 手写别名表（逐条查过的，见 MANUAL_ALIASES）
      3. 忽略大小写（`boneName` -> `BoneName`）
      4. 剥掉 Min/Max/Variation 后缀（模板把 via.Range 拆成了两三个标量字段）
    """
    if field_name in json_keys:
        return field_name

    alias = MANUAL_ALIASES.get((struct_name, field_name))
    if alias in json_keys:
        return alias

    lowered = {k.lower(): k for k in json_keys}
    if field_name.lower() in lowered:
        return lowered[field_name.lower()]

    for suffix in RANGE_SUFFIXES:
        if not field_name.endswith(suffix) or len(field_name) == len(suffix):
            continue
        base = field_name[: -len(suffix)]
        if base in json_keys:
            return base
        if base.lower() in lowered:
            return lowered[base.lower()]
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    btx_path = pathlib.Path(argv[1])
    types_path = pathlib.Path(argv[2])
    if not btx_path.exists():
        print(f"找不到模板：{btx_path}")
        return 1
    if not types_path.exists():
        print(f"找不到类型清单：{types_path}（先跑 EfxBridge types）")
        return 1

    btx = parse_btx(btx_path)
    catalogue = json.loads(types_path.read_text(encoding="utf-8"))["types"]

    types_out: dict = {}
    fields_out: dict = {}
    stat = {"type_labels": 0, "field_tooltip": 0, "field_values_only": 0,
            "struct_unmatched": 0, "field_unmatched": 0}

    for item in catalogue:
        full_type = item.get("type")
        struct = btx.get(item["name"])
        if struct is None:
            stat["struct_unmatched"] += 1
            continue
        if not full_type:
            # vendor 只登记了 id→枚举名、没有读写实现类，dump 里永远不会出现这个 $type
            continue

        if struct["comment"]:
            types_out[full_type] = {"label_zh": struct["comment"], "evidence": EVIDENCE}
            stat["type_labels"] += 1

        json_keys = {k for k in item["fields"] if k not in BOOKKEEPING}
        # 同一个 C# 键可能被模板的多个字段命中（Range 被拆成 Min/Max/Variation），按命中顺序累积
        collected: dict[str, list[str]] = {}
        has_comment: set[str] = set()
        for fname, rec in struct["fields"].items():
            key = resolve_key(item["name"], fname, json_keys)
            if key is None:
                stat["field_unmatched"] += 1
                continue
            parts = []
            if rec.get("comment"):
                parts.append(rec["comment"])
                has_comment.add(key)
            if rec.get("values"):
                v = format_values(rec["values"])
                if v:
                    parts.append(v)
            if not parts:
                continue
            collected.setdefault(key, []).extend(parts)

        per_field = {}
        for key, parts in collected.items():
            # 去重：Min/Max 两侧常常写着一模一样的注释
            seen, uniq = set(), []
            for p in parts:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            per_field[key] = {
                "tooltip_zh": "\n".join(uniq),
                # 不写 label_zh：模板注释是**说明**不是**标签**，硬拿来当标签会把面板挤爆；
                # 留空则面板回退到原始 JSON 键名（本来就是英文的权威字段名）。
                "confidence": "guess",
                "evidence": EVIDENCE,
            }
            if key in has_comment:
                stat["field_tooltip"] += 1
            else:
                stat["field_values_only"] += 1
        if per_field:
            fields_out[full_type] = dict(sorted(per_field.items()))

    payload = {
        "game": "MHWS",
        "_generated_by": "tools/mine_btx_semantics.py",
        "_source": "MHWs-EFX-Template / RE_EFX_STRUCTS.btx",
        "_note": "机器生成，整份可重跑覆盖。手写标注请写进 mhws_field_labels.json（优先级更高）。",
        "types": dict(sorted(types_out.items())),
        "global_fields": {},
        "fields": dict(sorted(fields_out.items())),
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"写出 {OUT_PATH}")
    print(f"  attribute 类型中文名 : {stat['type_labels']}")
    print(f"  字段（带中文说明）   : {stat['field_tooltip']}")
    print(f"  字段（只有实测取值） : {stat['field_values_only']}")
    print(f"  覆盖 attribute 类型  : {len(fields_out)}")
    print(f"  模板结构体没对上类型 : {stat['struct_unmatched']}")
    print(f"  字段名对不上（丢弃） : {stat['field_unmatched']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
