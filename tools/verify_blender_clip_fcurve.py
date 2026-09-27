# -*- coding: utf-8 -*-
"""
tools/verify_blender_clip_fcurve.py —— Clip 关键帧原生 fcurve 编辑的回归防护

必须在 Blender 里跑（要真 bpy：Action/fcurve、PropertyGroup 注册、算子），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_clip_fcurve.py

可选参数放在 `--` 之后：`--diag <样本目录>`（默认 `<仓库根>/diag`，收 `*.orig`）、
`--out <输出目录>`、`--dll <EfxBridge.dll>`，含义同 `verify_blender_roundtrip.py`。

为什么单独一条门禁
------------------
`blender_efx_re/clip_fcurve.py` 把 Clip 关键帧从自定义 `PropertyGroup` 列表搬到了这个
attribute 对象自己的原生 Action/fcurve 上（`_populate_clip_attribute()`/
`_export_clip_attribute()` 分别调 `clip_fcurve.import_curve()`/`export_curve()`）。
`verify_blender_roundtrip.py` 测不到这条路——它走的是"导入 -> 直接导出"，中间没人碰过
fcurve，测不出"读 fcurve 读错了"这类 bug（比如按 co[0] 排序漏排、Bezier 切线换算反了、
Int/Float 位转换在新代码路径里被漏掉）。这里做的是它做不了的：**在导入和导出之间，真的
读写一次 fcurve**，然后同时查两件事：

1. **不编辑，直接导出，字节 == 纯 CLI 往返基线（或数值容差内）**——抓"fcurve 中转本身
   引入的偏差"（核心断言，判据同验证纪律：和纯 CLI 产物比，不是和原文件比）。⚠ 这里不是
   严格逐字节：Blender 的 `BezTriple`（fcurve 关键帧的切线句柄）内部按 **float32 绝对坐标**
   （`frame_time + delta`）存储，Bezier 切线要通过它编辑就得先转换成绝对坐标再转换回来，
   这一去一回必然有一次 float32 舍入——不是实现 bug，是 Blender 这个数据结构本身的存储
   精度（2026-09-19 实测确认：`98.152` 存一圈变成 `98.15199...`，相对误差 ~1e-5，无法通过
   改换算公式消除）。比照姊妹项目 EFX-Editor 对 loc/rot fcurve 同类 ULP 级精度损失"用户已
   接受"的先例（见 `timl_edit.py` 模块文档 "byte-perfect" 一节），这里字节不同时退化成
   `_json_close()` 数值容差比对（`rel_tol=1e-4`），容差内算过；容差外（真正的逻辑 bug，
   比如切线符号搞反、关键帧顺序错、Int/Float 位转换漏做）仍然会被抓出来——第一次跑这条
   门禁时它真的抓到过切线符号错误（`in_x` 被写反导致 handle 越过关键帧、被 Blender 静默
   钳位成垃圾值，误差是几十个单位，远超容差），说明这个容差没有宽到会把真 bug 也放过去。
2. **真的挪一个关键帧后，`export_curve()` 读到的是新值**——抓"写不回去"类 bug（no-op 测试
   测不出来：如果 export 恒定返回导入时缓存的旧数据而不是真的读 fcurve，no-op 测试照样绿）。

另外单独测插值映射表的覆盖率 + 非标准类型拒绝闸门 + 标准导出闸门（见
`verify_interpolation_gate()`）：`_INTERP_MHWS_TO_BLENDER` 只保留语料统计+实机测试共同
确认的 4 个真实值 `{1,2,3,5}`，其余（`0/4/6/7/8/9/10/11/12/13`）真遇到时 `import_curve()`
必须拒绝导入，不能悄悄退化成某个凑合的值（铁律 #1）。2026-09-19 用户又加了一道更严的
导出闸门：即使 `3`(Event) 能正常导入（借用 Blender 的 SINE 插值名字），导出前也必须先
转成 Constant/Linear/Bezier 三种真实类型之一——`curve_interpolation_issues()` 现在只放行
这三个，SINE 也在拦截范围内。以及单独测 Hermite 切线 ÷3/×3 换算系数真的生效了（见
`verify_hermite_tangent_scale()`）——这个系数只有导入+导出各自内部自洽（互为反函数）才会
被 no-op 字节比对间接测到，具体数值对不对需要单独断言。

⚠ `--background --python` 在脚本抛未捕获异常时退出码仍是 0（实测），入口自己加一层捕获。
⚠ 样本里一条 Clip attribute 都没有 -> 退出码 1（防"没测到东西也全绿"）。
"""

from __future__ import annotations

import math
import pathlib
import shutil
import sys
import tempfile
import traceback

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402  （必须在 sys.path 铺好之后再 import 本项目的包）

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, clip_fcurve, io_tree, model, operators  # noqa: E402


def _script_args() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _parse_args(argv: list) -> dict:
    opts = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1]
    return opts


class Report:
    def __init__(self) -> None:
        self.failures = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
            if detail:
                print("        -> " + detail)


def _root_of(obj):
    for col in obj.users_collection:
        cursor = col
        while cursor is not None:
            if cursor.get("~TYPE") == model.TYPE_ROOT:
                return cursor
            cursor = next((c for c in bpy.data.collections
                           if cursor.name in c.children), None)
    return None


def _json_close(a, b, path: str = "$", diffs: list | None = None) -> list:
    """深比较两个 EfxBridge dump 出来的 JSON 结构，float 叶子按 `math.isclose()` 容差判等
    （吸收 Bezier 切线句柄的 float32 ULP 级精度损失，见本文件模块文档），其余类型必须
    完全相等。返回不相等的路径列表（空 = 相等）。"""
    if diffs is None:
        diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a.keys() | b.keys():
            if key not in a or key not in b:
                diffs.append(f"{path}.{key}: 只有一边有这个键")
                continue
            _json_close(a[key], b[key], f"{path}.{key}", diffs)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: 长度 {len(a)} != {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                _json_close(x, y, f"{path}[{i}]", diffs)
    elif isinstance(a, float) or isinstance(b, float):
        if not math.isclose(float(a), float(b), rel_tol=1e-4, abs_tol=1e-6):
            diffs.append(f"{path}: {a!r} != {b!r}")
    else:
        if a != b:
            diffs.append(f"{path}: {a!r} != {b!r}")
    return diffs


def _tuple_close(a: tuple, b: tuple, rel_tol: float = 1e-4, abs_tol: float = 1e-6) -> bool:
    """逐分量 `math.isclose()`，给 `handle_left`/`handle_right` 这类 (x, y) 元组用。"""
    return len(a) == len(b) and all(
        math.isclose(x, y, rel_tol=rel_tol, abs_tol=abs_tol) for x, y in zip(a, b)
    )


def _clip_curve_pairs(root_obj):
    """这棵对象树里所有 (attribute 对象, EFXClipCurveItem) 组合（含嵌套 efxrData 子树里的）。"""
    out = []
    for obj in bpy.data.objects:
        if obj.get("~TYPE") != model.TYPE_ATTRIBUTE:
            continue
        if not getattr(obj, "efx_is_clip_attribute", False):
            continue
        if _root_of(obj) is not root_obj:
            continue
        for curve in obj.efx_clip_curves:
            out.append((obj, curve))
    return out


def verify_sample(orig: pathlib.Path, workdir: pathlib.Path, report: Report,
                  seen_value_types: set, seen_interp_types: set) -> int:
    """返回这个样本里过了多少条 Clip 曲线（给"一条都没有就报错"用）。"""
    stem = orig.name.split(".efx.")[0]
    print(f"\n=== {stem}")

    src = workdir / orig.name.replace(".orig", "")
    shutil.copy(orig, src)

    # 纯 CLI 往返基线：完全不经过 Blender 对象树（验证纪律）
    cli_json = bridge.dump_efx(src)
    cli_out = workdir / f"{stem}_cli.efx.5571972"
    bridge.load_efx(cli_json, cli_out)

    data = bridge.dump_efx(src)
    root_obj = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, src.name)
    root_obj.efx_source_filename = src.name

    pairs = _clip_curve_pairs(root_obj)
    print(f"  Clip 曲线 {len(pairs)} 条（{len({o for o, _c in pairs})} 个 Clip attribute）")
    for _obj, curve in pairs:
        seen_value_types.add(int(curve.value_type))

    # 1. 不编辑，直接导出，字节必须和基线一致（核心断言）
    out_data = io_tree.export_root_to_efxfile(root_obj)
    out_path, notice, fatal = operators._ensure_version_suffix(
        str(workdir / f"{stem}_noop.efx.5571972"), out_data)
    if fatal:
        report.check("导出路径能补出合法版本号后缀", False, notice or "")
        return len(pairs)
    bridge.load_efx(out_data, out_path)
    blender_out = pathlib.Path(out_path)

    if blender_out.read_bytes() == cli_out.read_bytes():
        ok, detail = True, ""
    else:
        # 字节不同不直接判失败——先看是不是只有 Bezier 切线句柄的 float32 ULP 级精度损失
        # （见模块文档），是的话数值容差内也算过；容差外说明是真的逻辑 bug。
        diffs = _json_close(bridge.dump_efx(blender_out), bridge.dump_efx(cli_out))
        ok = not diffs
        detail = (f"字节不同（{blender_out.stat().st_size} 字节），数值容差比对仍不通过："
                  + "; ".join(diffs[:5]))
        if ok:
            print("  [NOTE] 字节和基线不同，但数值容差内——大概率是已知的 Bezier 切线 "
                  "float32 精度损失（见模块文档），不算失败")
    report.check("不编辑，fcurve 中转一圈后导出，字节 == 纯 CLI 往返基线（或数值容差内）",
                 ok, detail)

    # 记录样本覆盖到的插值类型（信息性，不是失败条件）
    for _obj, curve in pairs:
        fc = clip_fcurve._find_fcurve(_obj, curve)
        if fc is not None:
            for kp in fc.keyframe_points:
                seen_interp_types.add(kp.interpolation)

    # 2. 真的挪一个关键帧的值，export_curve() 必须读到新值（no-op 测试测不出"写不回去"）
    float_pair = next(((o, c) for o, c in pairs
                       if int(c.value_type) == 5 and clip_fcurve.keyframe_count(o, c) > 0), None)
    if float_pair is None:
        print("  [NOTE] 这个样本没有带关键帧的 Float 型 Clip 曲线，跳过编辑回读检查")
    else:
        obj, curve = float_pair
        fc = clip_fcurve._find_fcurve(obj, curve)
        kp = fc.keyframe_points[0]
        old_value = kp.co[1]
        kp.co[1] = old_value + 37.0
        fc.update()
        header, frames, _tangents = clip_fcurve.export_curve(obj, curve)
        report.check(
            "挪动一个关键帧的值之后，export_curve() 读回的是新值",
            frames and abs(frames[0]["FloatValue"] - (old_value + 37.0)) < 1e-3,
            f"frames[0]={frames[0] if frames else None}",
        )
        kp.co[1] = old_value  # 还原，避免污染后面的样本或复用同一 root_obj 的后续检查
        fc.update()

    return len(pairs)


def verify_interpolation_gate(report: Report) -> None:
    """插值映射表覆盖率 + 标准/非标准分类闸门 + 标准导出闸门。

    2026-09-19 用户纠正过一次架构：非标准原始类型（`0/4/6/8/9/10/11/12/13`，语料从没
    出现过、实机测出会崩/飞天/恒零）**不能**像 Event 那样借用 Blender 插值名字接进
    fcurve——那等于把它们也接进了"value 修改渠道"，跟"不提供任何关键帧编辑入口"的要求
    正好相反。改成完全独立于 Blender Animation 系统的存储
    （`EFXClipCurveItem.nonstandard_frames`），"标准"/"非标准"是两个地位平等、能互相
    切换的顶层分类（见 model._CLIP_CURVE_CATEGORY_ITEMS），不是"非标准低一级"。测四件事：
    ① `{1,2,3,5}` 全部能正确导入/识别到 fcurve 上；
    ② 只有 `{1,2,5}`（Constant/Linear/Bezier）不会被 `curve_interpolation_issues()` 判成
    问题，`3`（Event 借的 SINE）应该被判成问题——导入成功不代表能直接导出；
    ③ `classify_raw_types()` 对标准/非标准/歧义（混标准+非标准，或混多个不同非标准值）
    三种情况的分类都对，非标准值经 `import_nonstandard_curve()` 导入后**完全不touch
    fcurve**（没有 channel_key，也没有任何 fcurve 被创建）；
    ④ `set_curve_category()` 双向切换：标准↔非标准的数据搬运不丢东西，且切换方向对称
    （两个方向都能切，不是单向"降级"）。

    用内存里造的探针对象，不依赖具体样本。"""
    print("\n=== 插值映射表覆盖率 + 标准/非标准分类闸门 + 标准导出闸门")
    scene_col = bpy.context.scene.collection
    holder = bpy.data.objects.new("clip_interp_probe", None)
    scene_col.objects.link(holder)
    holder["~TYPE"] = model.TYPE_ATTRIBUTE
    holder.efx_is_clip_attribute = True
    holder.efx_clip_bit_count = 1
    curve = holder.efx_clip_curves.add()
    curve.bit_index = 0
    curve.value_type = "5"
    clip_fcurve.add_channel(holder, curve)

    # 1. {1,2,3,5} 全部能正常导入识别——映射表本身（导入侧）没有漏掉这 4 个确认值。
    all_ok = True
    for raw in (1, 2, 3, 5):
        clip_fcurve.import_curve(holder, curve, [
            {"frame_time": 0.0, "interp_type": raw, "value": 0.0, "tangent": None},
            {"frame_time": 10.0, "interp_type": raw, "value": 1.0, "tangent": None},
        ])
        fc = clip_fcurve._find_fcurve(holder, curve)
        got = fc.keyframe_points[0].interpolation
        want = clip_fcurve._INTERP_MHWS_TO_BLENDER[raw]
        if got != want:
            all_ok = False
            print(f"  [FAIL] raw={raw} 导入后 kp.interpolation={got!r}，期望 {want!r}")
    report.check("{1,2,3,5} 全部能正确导入识别", all_ok)

    # 2. 导出闸门：只有 Constant/Linear/Bezier（对应 raw 1/2/5）算"标准"，Event 借用的
    #    SINE（raw=3）现在应该被 curve_interpolation_issues() 判成问题——导入成功不代表
    #    能直接导出，这是刻意的收紧。
    export_ok = True
    for raw, should_export in ((1, True), (2, True), (3, False), (5, True)):
        clip_fcurve.import_curve(holder, curve, [
            {"frame_time": 0.0, "interp_type": raw, "value": 0.0, "tangent": None},
            {"frame_time": 10.0, "interp_type": raw, "value": 1.0, "tangent": None},
        ])
        issues = clip_fcurve.curve_interpolation_issues(holder, curve)
        got_export_ok = not issues
        if got_export_ok != should_export:
            export_ok = False
            want = clip_fcurve._INTERP_MHWS_TO_BLENDER[raw]
            print(f"  [FAIL] raw={raw}（{want}）导出闸门判定={got_export_ok}，"
                  f"期望={should_export}（issues={issues}）")
    report.check("导出闸门只放行 Constant/Linear/Bezier（raw 1/2/5），拦住 Event 的 SINE 占位（raw=3）",
                 export_ok)

    # 3a. classify_raw_types() 的三种分类都对。
    classify_ok = True
    cases = [
        ({1, 2}, "STANDARD"), ({5}, "STANDARD"), ({3}, "STANDARD"),
        ({0}, "NONSTANDARD"), ({9}, "NONSTANDARD"), ({13}, "NONSTANDARD"),
        ({1, 9}, None),   # 标准+非标准混在一起
        ({4, 9}, None),   # 两个不同的非标准值混在一起
        ({7}, None),      # 真 Bezier：既不是标准也不是这批非标准
    ]
    for raw_types, want in cases:
        got = clip_fcurve.classify_raw_types(raw_types)
        if got != want:
            classify_ok = False
            print(f"  [FAIL] classify_raw_types({raw_types}) = {got!r}，期望 {want!r}")
    report.check("classify_raw_types() 正确分类标准/非标准/歧义三种情况", classify_ok)

    # 3b. 非标准值经 import_nonstandard_curve() 导入后完全不碰 fcurve——这是这次架构调整
    #    的核心要求，"非标准曲线不接入任何 value 修改渠道"。
    nonstandard = 9  # OffsetFrame，任选一个非标准值
    curve.channel_key = ""
    curve.curve_category = "STANDARD"
    clip_fcurve.import_nonstandard_curve(
        curve,
        [{"frame_time": 0.0, "value": 1.0}, {"frame_time": 10.0, "value": 2.0}],
        nonstandard,
    )
    no_fcurve_touch = (
        curve.curve_category == "NONSTANDARD"
        and curve.nonstandard_raw_type == nonstandard
        and len(curve.nonstandard_frames) == 2
        and not curve.channel_key  # 没有分配自定义 ID 属性 key
        and clip_fcurve._find_fcurve(holder, curve) is None  # 也没有对应的 fcurve
    )
    report.check("非标准曲线导入后不分配 channel_key、不建 fcurve（不接入 Animation 系统）",
                 no_fcurve_touch)

    # 4. set_curve_category() 双向切换：非标准 -> 标准 -> 非标准，数据不丢、方向对称。
    header, frames, tangents = clip_fcurve.export_nonstandard_curve(curve)
    export_matches = (
        header == {"frameCount": 2, "valueType": 5}
        and [f["frameTime"] for f in frames] == [0.0, 10.0]
        and [f["type"] for f in frames] == [nonstandard, nonstandard]
        and tangents == []
    )
    report.check("非标准曲线导出的 frames/type 跟导入时一致，且没有切线数据", export_matches)

    clip_fcurve.set_curve_category(holder, curve, "STANDARD")
    to_standard_ok = (
        curve.curve_category == "STANDARD"
        and len(curve.nonstandard_frames) == 0
        and clip_fcurve.keyframe_count(holder, curve) == 2
    )
    clip_fcurve.set_curve_category(holder, curve, "NONSTANDARD")
    back_ok = (
        curve.curve_category == "NONSTANDARD"
        and len(curve.nonstandard_frames) == 2
        and clip_fcurve._find_fcurve(holder, curve) is None
    )
    report.check("set_curve_category() 非标准->标准->非标准双向切换都成功、不丢帧数",
                 to_standard_ok and back_ok)

    # 5. `7`（真 Bezier）既不在标准表里也不在非标准表里——两条路径都拒绝，不会被误判成
    #    "非标准"而放行导入。涉及切线数据消费顺序的未决问题，见 clip_fcurve.py 模块文档
    #    "raw=7 的导出限制"一节。
    raised7 = False
    try:
        clip_fcurve.import_curve(holder, curve, [
            {"frame_time": 0.0, "interp_type": 7, "value": 0.0, "tangent": None},
        ])
    except clip_fcurve.ClipFcurveError:
        raised7 = True
    report.check("raw=7（真 Bezier）仍被 import_curve() 拒绝，且不会被 classify_raw_types() "
                 "误判成非标准", raised7 and clip_fcurve.classify_raw_types({7}) is None)


def verify_hermite_tangent_scale(report: Report) -> None:
    """Hermite→Bezier 的 ÷3/×3 换算系数真的生效了，不是"改了注释但忘了改代码"。

    2026-09-19 用户实机拿不对称的过冲/下冲曲线定量测出：Blender 图形编辑器里直接显示的
    handle 长度，是真实 Hermite 切线的 3 倍——这条门禁不测"系数的方向对不对"（那要进游戏
    才能测），只测"代码里真的把这个系数乘上去了"：随便选一个不是 1/3/-3 之类特殊值的切线，
    往返一次，确认 `handle_right`/`handle_left` 的绝对坐标是切线的 1/3，且导出读回的切线
    在浮点容差内等于原始值。这个系数如果被后人不小心改回 1.0（等价于"当字面 Bezier 用"），
    这条门禁应该立刻炸。"""
    print("\n=== Hermite 切线 ÷3/×3 换算系数回归防护")
    scene_col = bpy.context.scene.collection
    holder = bpy.data.objects.new("clip_hermite_scale_probe", None)
    scene_col.objects.link(holder)
    holder["~TYPE"] = model.TYPE_ATTRIBUTE
    holder.efx_is_clip_attribute = True
    holder.efx_clip_bit_count = 1
    curve = holder.efx_clip_curves.add()
    curve.bit_index = 0
    curve.value_type = "5"
    clip_fcurve.add_channel(holder, curve)

    tangent0 = {"out_x": 30.0, "out_y": 9.0, "in_x": -6.0, "in_y": 0.0}
    tangent1 = {"out_x": 6.0, "out_y": 0.0, "in_x": -30.0, "in_y": -9.0}
    clip_fcurve.import_curve(holder, curve, [
        {"frame_time": 0.0, "interp_type": 5, "value": 0.0, "tangent": tangent0},
        {"frame_time": 60.0, "interp_type": 5, "value": 2.0, "tangent": tangent1},
    ])
    fc = clip_fcurve._find_fcurve(holder, curve)
    kp0, kp1 = fc.keyframe_points[0], fc.keyframe_points[1]

    ok = True
    expect_hr0 = (0.0 + tangent0["out_x"] / 3.0, 0.0 + tangent0["out_y"] / 3.0)
    if not _tuple_close(tuple(kp0.handle_right), expect_hr0):
        ok = False
        print(f"  [FAIL] kf0.handle_right={tuple(kp0.handle_right)}，期望 {expect_hr0}"
              f"（切线/3，不是切线原样当偏移量）")
    expect_hl1 = (60.0 + tangent1["in_x"] / 3.0, 2.0 + tangent1["in_y"] / 3.0)
    if not _tuple_close(tuple(kp1.handle_left), expect_hl1):
        ok = False
        print(f"  [FAIL] kf1.handle_left={tuple(kp1.handle_left)}，期望 {expect_hl1}")
    report.check("导入时切线按 ÷3 换算成 Blender 控制点偏移（不是原样当偏移量用）", ok)

    _header, _frames, tangents = clip_fcurve.export_curve(holder, curve)
    diffs: list = []
    if len(tangents) != 2:
        diffs.append(f"tangents 长度 {len(tangents)} != 2")
    else:
        _json_close(tangents[0], tangent0, "tangent0", diffs)
        _json_close(tangents[1], tangent1, "tangent1", diffs)
    if diffs:
        print(f"  [FAIL] 导出切线 {tangents!r}，期望（容差内）{[tangent0, tangent1]!r}：{diffs}")
    report.check("导出时按 ×3 换回原始切线（容差内还原，不是漂移到别的值）", not diffs)


def main() -> int:
    opts = _parse_args(_script_args())

    if "dll" in opts:
        bridge._DEFAULT_DLL = pathlib.Path(opts["dll"])
    try:
        print(f"EfxBridge: {bridge.get_bridge_dll()}")
    except bridge.BridgeError as ex:
        print(f"[ERROR] {ex}")
        return 1

    diag = pathlib.Path(opts.get("diag", _REPO_ROOT / "diag"))
    samples = sorted(diag.glob("*.orig"))
    if not samples:
        print(f"[ERROR] {diag} 下没有 *.orig 样本。diag/ 是 untracked 的游戏资产（见 .gitignore），"
              "需要自己放一份原始 .efx 并以 .orig 结尾，或用 --diag 指到别处。")
        return 1

    workdir = pathlib.Path(opts["out"]) if "out" in opts else pathlib.Path(
        tempfile.mkdtemp(prefix="efx_clip_fcurve_"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"样本目录: {diag}\n输出目录: {workdir}（跑完不删，失败时拿去 hexdump 对比）")

    blender_efx_re.register()

    report = Report()
    total_curves = 0
    seen_value_types = set()
    seen_interp_types = set()
    for orig in samples:
        total_curves += verify_sample(orig, workdir, report, seen_value_types, seen_interp_types)
    verify_interpolation_gate(report)
    verify_hermite_tangent_scale(report)

    print("\n=== 样本覆盖到的 valueType: "
          + ", ".join(str(v) for v in sorted(seen_value_types)) or "（无）")
    print("=== 样本覆盖到的 Blender 插值: " + ", ".join(sorted(seen_interp_types) or ["（无）"]))
    if "BEZIER" not in seen_interp_types:
        print("  [NOTE] 样本里没有 Bezier 关键帧——切线换算（_tangent_to_handles/"
              "_handles_to_tangent）这条路径只由上面 no-op 字节比对间接覆盖，想单独测到它，"
              "往 diag/ 放一个带 Bezier Clip 曲线的 .orig。")

    if total_curves == 0:
        # 找不到可测的东西要报错，不静默全绿（同"找不到样本退 1"的理由）
        print(f"\n[ERROR] {len(samples)} 个样本里一条 Clip 曲线都没有，这条门禁等于没跑。"
              "换一个带 IClipAttribute 的样本。")
        return 1
    print(f"\n过了 {total_curves} 条 Clip 曲线")

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # `blender --background --python x.py` 在脚本抛未捕获异常时退出码仍然是 0（实测），
    # "崩在第一行"和"全过"对调用方长得一模一样，所以自己加一层捕获（验证纪律）。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:                            # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
