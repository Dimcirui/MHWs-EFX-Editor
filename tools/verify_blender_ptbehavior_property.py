"""
tools/verify_blender_ptbehavior_property.py —— PtBehavior 候选目录增删门禁

必须在 Blender 里跑（要真 bpy），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_ptbehavior_property.py

可选参数放在 `--` 之后：

    ... -- --efx <样本 .efx 路径>

不给 `--efx` 时按 `_DEFAULT_EFX_CANDIDATES` 试固定样本（真实语料，含
`app.EffectPlEmissiveControl` 这个已收录进候选目录的 behaviorString）。找不到样本、或样本里
一个「收录进候选目录的 PtBehavior」都没有，**报错退 1，不静默全绿**（同其它门禁脚本的约定）。

检查项：

1. `ptbehavior_catalog.candidates()` 能读到目录，候选列表**恰好**排除掉已经覆盖过的属性名。
2. `efx_re.ptbehavior_property_add` 加出来的那条，`behaviorProperty` 就是选中的候选名，
   模板字段（`varSize`/`dataType`/`variable`/`varHash`）原样带过去（不是我们手工拼的）。
3. **新增按候选目录的规范顺序插入，不是简单追加**——加完之后 `properties` 里全部
   `behaviorProperty` 的相对顺序必须是候选目录规范顺序的一个子序列。
4. 加完之后走 Export 算子写出来的文件**能被 RE-Engine-Lib 读回来**，条数、每条的名字/顺序
   都和 Blender 里的状态一致。
5. `efx_re.ptbehavior_property_remove` 删掉之后同样能读回来，条数、内容都回到加之前的状态
   （加了又删 = 无操作，字节应该和从没加过时的导出完全一样）。
6. 面板绘制（`panels._draw_ptbehavior_property`）不崩，主行画出属性名 + 删除按钮。
7. **把"保序插入"这个改动临时注回去，确认它真的 FAIL**（CLAUDE.md 验证纪律）：
   把新增强制改成"总是追加到末尾"，再验一次"相对顺序是候选目录子序列"，必须失败——这条是
   整个功能里唯一"我们自己算的行为"（克隆真实样本本身不会错，插入位置算法才会）。
8. `efx_re.ptbehavior_property_add_all` 一次性补齐全部缺失候选，条数、保序、导出回读都和
   单条添加的判据一致；补齐之后 `poll()` 必须变 `False`（没有更多可加的了）。
9. **改写 `behaviorString`**（不管改之前 `properties` 是空的还是已经有内容），`properties`
   都会**整个替换**成 `ptbehavior_catalog.default_instance()`——这个类在全语料里出现次数
   最多的那一套字段组合，取自同一个真实实例，**不是** `candidates()` 的全量并集（不留一个
   全空的 attribute 等用户手点，但也不是把这个类见过的全部字段都塞进去）。**2026-09-19
   改**：`behaviorProperty` 在 PtBehavior 里不是全局唯一 ID，换类之后旧字段对新类要么查不到
   要么语义对不上，"保留"反而比"替换"更容易产出无效数据，所以不管改之前有没有内容都替换
   （不再是"只在为空时才填"）；新类的默认字段块本身为空（这个类的众数用法就是"什么都不
   覆盖"）时，替换的结果就是清空。批量填充期间 `model.suppress_field_updates()` 生效时
   （导入/粘贴路径）不触发这套自动替换逻辑。
10. **面板画法标准化**（对齐 `_draw_mdf_property` 的模式）：已知且已实现的 dataType
    （如 `PropFloat`）主行画出紧凑值控件；已知但没实现紧凑控件的 dataType（如 `PropUint`）
    落回"展开编辑"；vendor 完全不认识的 dataType 落回"未知数据类型"（两种兜底文案不一样）；
    展开区里 `Version`/`varSize`/`dataType`/`varHash`/`behaviorProperty` 以及 `variable`
    内部的 `unkn`/`size`/`re4_unkn0`/`re4_unkn1`/`restData` 这些派生/记账字段画出来但只读
    （`enabled=False`，不隐藏），真正的值字段（`variable.value`）保持可编辑。
11. 新增的一条（不管是 `add`/`add_all` 还是改 `behaviorString` 触发的自动默认填充）默认是
    折起来的（`ui_expand is False`）——每条都已经有紧凑主行了，跟
    `io_tree.collapse_mdf_properties()` 对导入路径的处理一致，不应该一加就摊开一整块字段。
12. **候选目录没收录的类，已经存在的属性依然要走标准化画法**——候选目录只管"能不能从目录
    新增"，不该连"已经存在的属性能不能显示成紧凑控件"都搭进去。用真实存在的排除类名
    `app.EffectRasterizeVortexelGeometry` 造一个带真实属性的探针验证：`draw_node()` 分派
    进 PtBehavior 专属画法（画出属性名 + 紧凑值控件，不是回退到通用树的裸下标），但
    `efx_re.ptbehavior_property_add`/`_remove` 的 `poll()` 依然因为没有候选目录返回
    `False`（增删范围不变，只修复"看不到内容"这一半）。
13. **vendor 不认识/名字认识但没实现的 dataType，语料能推出字节形状的那些**
    （3/6/8/12/20/22 完全不认识；4/10/21 vendor 起了名字
    （`PropUint`/`PropRange`/`PropWstring2`）但没有反序列化类，见
    `panels._PTBEHAVIOR_UNKNOWN_DATATYPE_SHAPES`）：紧凑控件读出的值和手工构造的原始字节
    一致，写回去再读一致（round-trip），写回去之后字节数不变（`PropWstring2` 例外，见下）；
    `dataType=20` 画成 S/R 两列（用户按项目既有 {s,r} 命名习惯定的，不是语义已验证）；
    `dataType=4`（`PropUint`）同一个 wire 数值被至少 3 种语义复用（int/hash/float），按
    字段名分派——默认 int32，`DestFloat4` 这类命名例外按 float32（见
    `_PTBEHAVIOR_PROP_UINT_FLOAT_FIELD_NAMES`）；`dataType=21`（`PropWstring2`）是 UTF-16
    宽字符串，编辑会连 `variable.size`/外层 `varSize` 一起按公式重算（变长/变短都要验证），
    形状不合法（没有 `\x00\x00` 结尾等）时不提供紧凑编辑；字节数和期望对不上时不画紧凑
    控件，安全回退到兜底文案，不拿越界字节瞎猜。
14. **dataType=24（`OBB`）9 个浮点单行放不下，画成 T/R/S 三行**：`unknown_float32x9_value`
    读写正确、round-trip；`_draw_ptbehavior_property()` 画出 3 个行标签（T/R/S）+ 9 个
    对应的 `prop`，且不受 `ui_expand` 折叠状态影响；字节数不对（不是 36 字节）时落回
    「未知数据类型」（`dataType=24` vendor 自己也不认识，不是"认识但没实现"那一类）。
    T/R/S 具体是不是"平移/旋转/缩放"是用户按 9 自由度的 TRS 惯例做的判断，样本只有
    4 个真实实例，不是语义已验证（铁律 #3），见 `panels._PTBEHAVIOR_OBB_DATATYPE` 处的
    取证说明。

退出码：全绿 0，有失败 1。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, io_tree, model, operators, ptbehavior_catalog, structure_ops  # noqa: E402

#: 解包根换过一次（`MHWILDS_EXTRACT/EFX/natives/STM/...` -> `MHWILDS_EXTRACT/Art/VFX/...`），
#: 都试一遍，全落空仍然报错退 1。这个样本含 `app.EffectPlEmissiveControl`（已收录进候选目录）。
_DEFAULT_EFX_CANDIDATES = (
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\Art\VFX\EffectEditor\Weapon\it00\11_it00_000.efx.5571972",
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\natives\STM\Art\VFX\EffectEditor\Weapon\it00\11_it00_000.efx.5571972",
)
_DEFAULT_EFX = next((p for p in _DEFAULT_EFX_CANDIDATES if pathlib.Path(p).is_file()),
                    _DEFAULT_EFX_CANDIDATES[0])


def _script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _parse_args(argv: list[str]) -> dict[str, str]:
    opts: dict[str, str] = {}
    for i in range(0, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            opts[argv[i][2:]] = argv[i + 1]
    return opts


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if not ok:
            self.failures.append(label)
            if detail:
                print("        -> " + detail)


class _FakeLayout:
    """无头 Blender 没有区域可以真画面板，用它把 draw 跑一遍：既验证不抛异常，也能断言
    主行上画出来的确实是"名字 + 删除按钮"。照抄 `verify_blender_mdf_property.py` 的写法。"""

    def __init__(self, log: list, enabled: bool = True) -> None:
        self.log = log
        self.enabled = enabled

    def _child(self, *args, **kwargs):
        return _FakeLayout(self.log, self.enabled)

    row = column = split = box = _child

    def prop(self, data, prop_name, **kwargs):
        self.log.append(("prop", getattr(data, "key", ""), prop_name, self.enabled))

    def label(self, **kwargs):
        self.log.append(("label", kwargs.get("text", ""), self.enabled, kwargs.get("icon", "")))

    def operator(self, idname, **kwargs):
        self.log.append(("operator", idname, self.enabled))
        return type("Op", (), {})()

    def __getattr__(self, name):
        return self._child


def _find_ptbehavior_attribute():
    """场景里第一个「命中候选目录」的 PtBehavior attribute 对象。"""
    for obj in bpy.data.objects:
        node, behavior_string = structure_ops.resolve_ptbehavior_properties(obj)
        if node is not None:
            return obj, node, behavior_string
    return None, None, None


def _export(root_col, out_path: pathlib.Path) -> pathlib.Path:
    data = io_tree.export_root_to_efxfile(root_col)
    resolved, notice, fatal = operators._ensure_version_suffix(str(out_path), data)
    if fatal:
        raise RuntimeError(notice or "导出路径拿不到合法版本号后缀")
    bridge.load_efx(data, resolved)
    return pathlib.Path(resolved)


def _read_back_ptbehavior(path: pathlib.Path):
    """读回写出的文件，返回第一个 `EFXAttributePtBehavior` 的 `properties` 列表。"""
    data = bridge.dump_efx(path)
    for entry in data.get("Entries") or []:
        for attr in entry.get("Attributes") or []:
            if str(attr.get("$type", "")).endswith("EFXAttributePtBehavior"):
                return attr.get("properties")
    return None


def _ptbehavior_child_name(child) -> str | None:
    for sub in child.children:
        if sub.key == "behaviorProperty":
            return model.node_to_value(sub)
    return None


def _names_in_order(properties_node) -> list[str]:
    return [name for child in properties_node.children
            if (name := _ptbehavior_child_name(child)) is not None]


def _is_subsequence(sub: list[str], full: list[str]) -> bool:
    it = iter(full)
    return all(x in it for x in sub)  # 依赖 iter 状态推进，逐个按顺序找


def _find_ptbehavior_child_by_name(properties_node, name: str):
    return next((c for c in properties_node.children if _ptbehavior_child_name(c) == name), None)


def verify_panel_rendering(properties_node, report: Report) -> None:
    """检查项 10：面板绘制标准化——紧凑值控件、派生字段只读、未知/未实现 dataType 的兜底文案。

    复用 `verify_auto_default()` 场景 1 已经自动填好的 `app.EffectPlEmissiveControl` 默认
    字段块，里面有 `RimWidthAnimStart`（PropFloat=9，已实现紧凑控件）。另两种用例用合成探针：
    **`attribute_types.pt_behavior_prop_type_name()` 里 11 个 vendor 有名字的数值现在全部
    实现了紧凑控件**（检查项 13/14），"已知名字但没实现"这个兜底分支已经没有真实候选了，
    改用"已知名字、但这条实例的字节数不符合形状要求"（`dataType=4` 但只给 2 字节，正常应该
    是 4 字节）来测同一条兜底路径——`type_name` 认识但 `_draw_ptbehavior_property_value()`
    因为长度不对返回 `False` 时同样会走这条"展开编辑"文案。"vendor 也没法推出形状"用
    `dataType=25`（`OtherMaterialParamList` 那种嵌套材质参数结构，形状太复杂）。
    """
    from blender_efx_re import i18n, panels

    float_child = _find_ptbehavior_child_by_name(properties_node, "RimWidthAnimStart")
    uint_child = _make_unknown_ptbehavior_probe("known_badlen", 4, b"\x00\x00")
    unknown_child = _make_unknown_ptbehavior_probe("truly_unknown", 25, b"\x00" * 12)
    report.check(
        "面板渲染测试用例齐全（RimWidthAnimStart=Float）",
        float_child is not None, str(float_child),
    )
    if float_child is None:
        return

    # ---- 已知且已实现的类型（PropFloat）：主行画出紧凑值控件 -------------------
    float_child.ui_expand = False
    log: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log), float_child, 0)
    report.check(
        "PropFloat 主行画出了紧凑值控件（float_value），不是兜底文案",
        any(e[0] == "prop" and e[2] == "float_value" for e in log),
        str(log),
    )

    # ---- 已知名字但字节数不符合形状要求（PropUint 只给 2 字节）：落回"展开编辑" -
    uint_child.ui_expand = False
    log = []
    panels._draw_ptbehavior_property(_FakeLayout(log), uint_child, 0)
    report.check(
        "PropUint 字节数不对时落回「展开编辑」兜底文案（dataType 名字认识，不是「未知数据类型」）",
        any(e[0] == "label" and e[1] == i18n.T("mdf.unknown_shape") for e in log),
        str(log),
    )

    # ---- 真正未知的 dataType（不在 PtBehaviorPropType 里）：落回"未知数据类型" -
    unknown_child.ui_expand = False
    log = []
    panels._draw_ptbehavior_property(_FakeLayout(log), unknown_child, 0)
    report.check(
        "未知 dataType 落回「未知数据类型」兜底文案，和「展开编辑」的措辞不一样",
        any(e[0] == "label" and e[1] == i18n.T("ptbehavior.unknown_shape") for e in log),
        str(log),
    )
    report.check(
        "未知 dataType 的主行没有画出任何值编辑 prop 控件（排除结构性的 ui_expand 折叠开关）",
        not any(e[0] == "prop" and e[2] != "ui_expand" for e in log),
        str(log),
    )

    # ---- 展开区：派生/记账字段只读，但仍然画出来（不隐藏） --------------------
    float_child.ui_expand = True
    log = []
    panels._draw_ptbehavior_property(_FakeLayout(log), float_child, 0)
    derived_props = [
        e for e in log if e[0] == "prop"
        and e[1] in ("Version", "varSize", "dataType", "varHash", "behaviorProperty")
    ]
    report.check(
        "展开区画出了 Version/varSize/dataType/varHash/behaviorProperty 这几个派生字段"
        "（不隐藏——隐藏会让「为什么是这个值」不可查）",
        len(derived_props) >= 4,
        str(log),
    )
    report.check(
        "这几个派生字段在展开区是只读的（enabled=False）",
        bool(derived_props) and all(e[3] is False for e in derived_props),
        str(derived_props),
    )
    accounting_props = [
        e for e in log if e[0] == "prop"
        and e[1] in ("unkn", "size", "re4_unkn0", "re4_unkn1", "restData")
    ]
    report.check(
        "variable 内部的记账/填充字段（unkn/size/re4_unkn0/re4_unkn1）也是只读的",
        bool(accounting_props) and all(e[3] is False for e in accounting_props),
        str(accounting_props),
    )
    value_props = [e for e in log if e[0] == "prop" and e[2] == "float_value"
                   and e[1] not in ("Version", "varSize", "dataType", "varHash", "behaviorProperty")]
    report.check(
        "variable.value 这个真正的值字段在展开区仍然可编辑（enabled=True）",
        any(e[3] is True for e in value_props),
        str(value_props),
    )


def verify_auto_default(behavior_string: str, report: Report) -> None:
    """检查项 9：新建空白 PtBehavior，改 `behaviorString` 应该自动补全默认字段块
    （`ptbehavior_catalog.default_instance()`，不是 `candidates()` 的全量并集）。"""

    default_entries = ptbehavior_catalog.default_instance(behavior_string)
    default_order = [e["name"] for e in default_entries]
    report.check(
        f"{behavior_string} 有非空的默认字段块可测（样本类目众数用法不是「什么都不覆盖」）",
        bool(default_entries),
        "换一个 --efx，或者这个类在语料里众数用法就是空覆盖表，测不出「自动补全」这一步",
    )
    if not default_entries:
        return

    # ---- 场景 1：全新空白 attribute，改 behaviorString 应该自动补全 -----------
    obj = bpy.data.objects.new("ptbehavior_default_probe", None)
    bpy.context.scene.collection.objects.link(obj)
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    model.populate_dict_as_children(obj.efx_fields, {"behaviorString": None, "properties": []})
    behavior_node = structure_ops.resolve_behavior_string_node(obj)
    properties_node = model.find_field(obj.efx_fields, "properties")
    report.check(
        "造出的空白 attribute 结构正确（有 behaviorString/properties，properties 是空的）",
        behavior_node is not None and properties_node is not None
        and len(properties_node.children) == 0,
    )

    behavior_node.string_value = behavior_string
    report.check(
        "改写 behaviorString 之后 properties 自动补全成默认字段块（众数实例，不是全量候选）",
        len(properties_node.children) == len(default_entries),
        f"{len(properties_node.children)} != {len(default_entries)}",
    )
    filled_names = _names_in_order(properties_node)
    report.check(
        "自动补全的顺序就是众数实例本身的字段顺序",
        filled_names == default_order,
        f"实际 {filled_names}\n期望 {default_order}",
    )
    candidate_names = {e["name"] for e in ptbehavior_catalog.candidates(behavior_string)}
    report.check(
        "默认字段块不是候选目录的全量并集（除非这个类候选本来就只有这么多）",
        len(default_entries) <= len(candidate_names),
        f"默认 {len(default_entries)} 条 > 候选目录 {len(candidate_names)} 条，不合理",
    )
    report.check(
        "自动填充出来的每一条都默认是折起来的（ui_expand is False）",
        all(c.ui_expand is False for c in properties_node.children),
        str([(name, c.ui_expand) for c, name in zip(properties_node.children, filled_names)]),
    )

    verify_panel_rendering(properties_node, report)

    # ---- 场景 2：properties 已经非空，改 behaviorString 要整个替换成新类的默认字段块 ---
    # （2026-09-19 改：behaviorProperty 在 PtBehavior 里不是全局唯一 ID，换了 behaviorString
    # 之后原来的字段名对新类要么查不到要么语义对不上，留着比清空更危险——铁律 #1 保护的是
    # "有意义的数据"，不是"字面还在但已经失效的字节"，见 model._apply_ptbehavior_default()
    # 的文档。）
    other_behavior = next(
        (name for name, has_cat in ptbehavior_catalog.known_behavior_strings()
         if has_cat and name != behavior_string and ptbehavior_catalog.default_instance(name)),
        None)
    empty_default_behavior = next(
        (name for name, has_cat in ptbehavior_catalog.known_behavior_strings()
         if has_cat and not ptbehavior_catalog.default_instance(name)), None)
    if other_behavior is None:
        print("  （语料里找不到第二个带非空默认字段块的 behaviorString，跳过"
              "「切换类会整个替换」场景）")
    else:
        obj2 = bpy.data.objects.new("ptbehavior_nonempty_probe", None)
        bpy.context.scene.collection.objects.link(obj2)
        obj2["~TYPE"] = model.TYPE_ATTRIBUTE
        model.populate_dict_as_children(obj2.efx_fields, {"behaviorString": None, "properties": []})
        behavior_node2 = structure_ops.resolve_behavior_string_node(obj2)
        properties_node2 = model.find_field(obj2.efx_fields, "properties")
        behavior_node2.string_value = behavior_string
        before_names = set(_names_in_order(properties_node2))
        report.check("场景 2 前置：先自动填过一次，properties 非空", bool(before_names),
                     str(before_names))

        behavior_node2.string_value = other_behavior
        after_names = _names_in_order(properties_node2)
        expected_names = [e["name"] for e in ptbehavior_catalog.default_instance(other_behavior)]
        report.check(
            "切到另一个类之后，properties 整个替换成新类自己的默认字段块（不是旧类字段"
            "残留、也不是两边合并）",
            after_names == expected_names,
            f"实际 {after_names}\n期望（{other_behavior} 的默认字段块） {expected_names}",
        )
        report.check(
            "新字段块里不该出现旧类（且新类没有同名字段）的残留名字",
            not (before_names - set(expected_names)) & set(after_names),
            f"旧类字段 {before_names}，新类字段 {after_names}",
        )

        # ---- 把"整个替换"这个改动临时注回原来的"只在空时才填"，确认真的会 FAIL -----
        original_apply = model._apply_ptbehavior_default

        def _broken_apply(node):
            # 模拟"改回旧版——只在 properties 为空时才填"这个回归：旧字段会原样留着。
            fields = getattr(node.id_data, "efx_fields", None)
            props_node = model.find_field(fields, "properties")
            if props_node is None or props_node.children:
                return
            entries = ptbehavior_catalog.default_instance(node.string_value)
            with model.suppress_field_updates():
                for entry in entries:
                    child = props_node.children.add()
                    model.populate_node(child, str(len(props_node.children) - 1),
                                         entry["template"])

        model._apply_ptbehavior_default = _broken_apply
        try:
            # 造一个新的非空探针，切换类名，用旧版逻辑应该会保留旧字段（不替换）。
            obj2b = bpy.data.objects.new("ptbehavior_regression_probe", None)
            bpy.context.scene.collection.objects.link(obj2b)
            obj2b["~TYPE"] = model.TYPE_ATTRIBUTE
            model.populate_dict_as_children(obj2b.efx_fields, {"behaviorString": None, "properties": []})
            behavior_node2b = structure_ops.resolve_behavior_string_node(obj2b)
            properties_node2b = model.find_field(obj2b.efx_fields, "properties")
            behavior_node2b.string_value = behavior_string
            behavior_node2b.string_value = other_behavior
            broken_names = _names_in_order(properties_node2b)
        finally:
            model._apply_ptbehavior_default = original_apply
        report.check(
            '注回旧版"只在空时才填"逻辑之后，"整个替换"检查必须 FAIL（不能一直绿）',
            broken_names != expected_names,
            f"防护无效：旧逻辑跑出来的字段仍然被判定成正确的新类默认字段块，"
            f"broken_names={broken_names}",
        )

        # ---- 切到一个"众数用法就是什么都不覆盖"的类：应该被清空，不是留着旧字段 ----
        if empty_default_behavior is None:
            print("  （语料里找不到默认字段块为空的 behaviorString，跳过「切到空默认类"
                  "会清空」场景）")
        else:
            obj2c = bpy.data.objects.new("ptbehavior_empty_default_probe", None)
            bpy.context.scene.collection.objects.link(obj2c)
            obj2c["~TYPE"] = model.TYPE_ATTRIBUTE
            model.populate_dict_as_children(obj2c.efx_fields, {"behaviorString": None, "properties": []})
            behavior_node2c = structure_ops.resolve_behavior_string_node(obj2c)
            properties_node2c = model.find_field(obj2c.efx_fields, "properties")
            behavior_node2c.string_value = behavior_string
            behavior_node2c.string_value = empty_default_behavior
            report.check(
                f"切到「众数用法是空覆盖」的类（{empty_default_behavior}）之后 properties "
                "被清空，不是留着旧类的字段",
                len(properties_node2c.children) == 0,
                f"{_names_in_order(properties_node2c)}",
            )

    # ---- 场景 3：批量填充（suppress_field_updates 生效）期间不触发 -----------
    obj3 = bpy.data.objects.new("ptbehavior_suppressed_probe", None)
    bpy.context.scene.collection.objects.link(obj3)
    obj3["~TYPE"] = model.TYPE_ATTRIBUTE
    # populate_dict_as_children 本来就在 suppress_field_updates() 里跑，这里顺带把
    # behaviorString 直接设成有候选目录的类名——模拟导入/粘贴那条路。
    model.populate_dict_as_children(
        obj3.efx_fields, {"behaviorString": behavior_string, "properties": []})
    properties_node3 = model.find_field(obj3.efx_fields, "properties")
    report.check(
        "批量填充（导入/粘贴路径）设置 behaviorString 不会触发自动补全",
        len(properties_node3.children) == 0,
        f"{len(properties_node3.children)} != 0（说明 suppress_field_updates 没生效）",
    )


def verify(efx_path: pathlib.Path, workdir: pathlib.Path, report: Report) -> None:
    data = bridge.dump_efx(efx_path)
    root_col = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, efx_path.name)
    root_col.efx_source_filename = efx_path.name

    obj, node, behavior_string = _find_ptbehavior_attribute()
    if obj is None:
        report.check(
            f"{efx_path.name}: 找到收录进候选目录的 PtBehavior attribute", False,
            "样本里没有命中 `ptbehavior_catalog` 的 behaviorString，换一个 --efx",
        )
        return
    print(f"  样本 {efx_path.name}：behaviorString = {behavior_string}，"
          f"现有 {len(node.children)} 条属性")

    bpy.context.view_layer.objects.active = obj
    before = len(node.children)
    before_names = structure_ops._present_ptbehavior_names(node)

    catalog_entries = ptbehavior_catalog.candidates(behavior_string)
    order = [e["name"] for e in catalog_entries]
    report.check("候选目录非空", bool(catalog_entries), f"behaviorString={behavior_string}")

    verify_auto_default(behavior_string, report)

    free = [e["name"] for e in catalog_entries if e["name"] not in before_names]
    report.check(
        "候选列表排除掉已经覆盖过的属性",
        len(free) == len(catalog_entries) - len(before_names & set(order)),
    )
    if not free:
        report.check("样本还有没被覆盖的候选可以加", False, "这个类的候选已经全覆盖，换一个样本")
        return

    pick = free[0]
    bpy.ops.efx_re.ptbehavior_property_add(candidate=pick)
    report.check("Add 算子加出一条", len(node.children) == before + 1,
                 f"{before} -> {len(node.children)}")

    added_names = structure_ops._present_ptbehavior_names(node) - before_names
    report.check(f"新增的是选中的候选 '{pick}'", added_names == {pick}, str(added_names))

    added_child = _find_ptbehavior_child_by_name(node, pick)
    report.check(
        "Add 算子新增的这条默认是折起来的（ui_expand is False）",
        added_child is not None and added_child.ui_expand is False,
        f"ui_expand={getattr(added_child, 'ui_expand', None)}",
    )

    names_now = _names_in_order(node)
    report.check(
        "保序插入：新增后 properties 的相对顺序是候选目录规范顺序的子序列",
        _is_subsequence(names_now, order),
        f"实际顺序 {names_now}\n规范顺序 {order}",
    )

    out_path = _export(root_col, workdir / "added.efx")
    props = _read_back_ptbehavior(out_path)
    report.check("加完之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("读回来的条数对", len(props) == before + 1, f"{len(props)} != {before + 1}")
        readback_names = [p.get("behaviorProperty") for p in props]
        report.check("读回来的顺序和 Blender 里一致", readback_names == names_now,
                     f"{readback_names} != {names_now}")

    # ---- 面板绘制：不崩，主行画出名字 + 删除按钮 -------------------------------
    from blender_efx_re import panels

    new_child = next(c for c in node.children
                      if any(sub.key == "behaviorProperty" and model.node_to_value(sub) == pick
                             for sub in c.children))
    new_child.ui_expand = False
    index = list(node.children).index(new_child)
    log: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log), new_child, index)
    report.check(f"面板主行画出属性名 '{pick}'",
                 any(e[0] == "label" and e[1] == pick for e in log), str(log))
    report.check("面板主行有删除按钮",
                 any(e[0] == "operator" and e[1] == "efx_re.ptbehavior_property_remove"
                     for e in log))

    # ---- 删除，回到加之前的状态 --------------------------------------------
    bpy.ops.efx_re.ptbehavior_property_remove(index=index)
    report.check("Remove 算子删掉一条", len(node.children) == before,
                 f"{len(node.children)} != {before}")
    out_path = _export(root_col, workdir / "removed.efx")
    props = _read_back_ptbehavior(out_path)
    report.check("删完之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("删完读回来的条数对", len(props) == before, f"{len(props)} != {before}")
        readback_names = [p.get("behaviorProperty") for p in props]
        report.check("删完读回来的名字和加之前完全一致（加了又删=无操作）",
                     set(readback_names) == before_names, str(readback_names))

    # ---- Add All：一次性补齐所有缺失候选 ------------------------------------
    bpy.ops.efx_re.ptbehavior_property_add_all()
    report.check(
        "Add All 算子补齐所有缺失候选",
        len(node.children) == before + len(free),
        f"{len(node.children)} != {before + len(free)}",
    )
    names_all = _names_in_order(node)
    report.check(
        "Add All 之后的顺序仍是候选目录规范顺序的子序列",
        _is_subsequence(names_all, order),
        f"实际顺序 {names_all}\n规范顺序 {order}",
    )
    report.check(
        "Add All 之后没有缺失候选了，poll() 应该变 False",
        not structure_ops.EFX_RE_OT_ptbehavior_property_add_all.poll(bpy.context),
    )
    newly_added = [c for c in node.children if _ptbehavior_child_name(c) in free]
    report.check(
        "Add All 新增的每一条都默认是折起来的（ui_expand is False）",
        bool(newly_added) and all(c.ui_expand is False for c in newly_added),
        str([(_ptbehavior_child_name(c), c.ui_expand) for c in newly_added]),
    )

    out_path = _export(root_col, workdir / "added_all.efx")
    props = _read_back_ptbehavior(out_path)
    report.check("Add All 之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("Add All 读回来的条数对", len(props) == before + len(free),
                     f"{len(props)} != {before + len(free)}")
        readback_names = [p.get("behaviorProperty") for p in props]
        report.check("Add All 读回来的顺序和 Blender 里一致", readback_names == names_all,
                     f"{readback_names} != {names_all}")

    # 清回加之前的状态，后面的回归防护复用同一个 `node`
    for name in list(structure_ops._present_ptbehavior_names(node) - before_names):
        idx = next(i for i, c in enumerate(node.children)
                   if any(sub.key == "behaviorProperty" and model.node_to_value(sub) == name
                          for sub in c.children))
        bpy.ops.efx_re.ptbehavior_property_remove(index=idx)
    report.check("清理 Add All 新增的属性，回到加之前的状态",
                 len(node.children) == before, f"{len(node.children)} != {before}")

    # ---- 把"保序插入"注回去，确认它真的 FAIL（验证纪律）--------------------
    pick2 = next((n for n in free if n != pick), None)
    if pick2 is None:
        print("  （这个类候选只有 1 条，跳过保序插入的回归防护验证）")
        return

    import blender_efx_re.structure_ops as so
    original_add = so.EFX_RE_OT_ptbehavior_property_add.execute

    def _broken_execute(self, context):
        # 模拟"忘了按规范顺序插入、直接追加到末尾"这个 bug：跳过 move()，只 add() + populate。
        properties_node, behavior_string = so.resolve_ptbehavior_properties(context.object)
        catalog_entries = ptbehavior_catalog.candidates(behavior_string)
        entry = next(e for e in catalog_entries if e["name"] == self.candidate)
        child = properties_node.children.add()
        model.populate_node(child, str(len(properties_node.children) - 1), entry["template"])
        so._renumber_array_keys(properties_node)
        return {"FINISHED"}

    so.EFX_RE_OT_ptbehavior_property_add.execute = _broken_execute
    try:
        bpy.ops.efx_re.ptbehavior_property_add(candidate=pick2)
        broken_names = _names_in_order(node)
        broken_ok = _is_subsequence(broken_names, order)
    finally:
        so.EFX_RE_OT_ptbehavior_property_add.execute = original_add
        bpy.ops.efx_re.ptbehavior_property_remove(index=len(node.children) - 1)

    report.check(
        "注回「总是追加到末尾」的 bug 之后，保序检查必须 FAIL（不能一直绿）",
        not broken_ok,
        f"防护无效：追加到末尾的结果仍然被判定为子序列，说明这条检查测不到顺序问题。"
        f"broken_names={broken_names}",
    )


def verify_excluded_class_still_renders(report: Report) -> None:
    """检查项 12：没收录候选目录的类，已经存在的属性依然要走标准化画法（不回退到通用树的
    裸下标显示），但增删入口继续按既有范围决定保持关闭。

    用真实存在的排除类名 `app.EffectRasterizeVortexelGeometry`（`_excluded` 里"没有任何
    属性"那条——全语料扫描没见过它被覆盖过任何字段，没法从真实样本里现找一个带属性的实例）
    手工造一个带真实属性的探针。
    """
    from blender_efx_re import panels

    behavior_string = "app.EffectRasterizeVortexelGeometry"
    report.check(
        f"'{behavior_string}' 确实是没收录候选目录的类（这个检查项的前提）",
        not ptbehavior_catalog.has_catalog(behavior_string),
        "如果这个类现在被收录了，换一个语料里真实排除的类名重写这个检查",
    )

    obj = bpy.data.objects.new("ptbehavior_excluded_probe", None)
    bpy.context.scene.collection.objects.link(obj)
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    model.populate_dict_as_children(obj.efx_fields, {
        "behaviorString": behavior_string,
        "properties": [{
            "Version": 5571972,
            "varSize": 20,
            "dataType": 9,  # PropFloat
            "variable": {
                "$type": "PropFloat",
                "Version": 5571972,
                "unkn": 1,
                "size": 4,
                "re4_unkn0": -1,
                "re4_unkn1": 0,
                "value": 1.5,
            },
            "varHash": 12345,
            "behaviorProperty": "TestField",
        }],
    })

    properties_node = model.find_field(obj.efx_fields, "properties")
    report.check(
        "造出的探针有 1 条属性",
        properties_node is not None and len(properties_node.children) == 1,
    )

    node_result, bstr_result = structure_ops.resolve_ptbehavior_properties_node(obj)
    report.check(
        "resolve_ptbehavior_properties_node() 不需要候选目录，照样解析出 properties",
        node_result is not None and bstr_result == behavior_string,
    )
    node_gated, _ = structure_ops.resolve_ptbehavior_properties(obj)
    report.check(
        "resolve_ptbehavior_properties()（增删用）依然要求候选目录，这个类没有就拒绝"
        "（增删范围不变）",
        node_gated is None,
    )

    properties_node.ui_expand = True
    log: list = []
    panels.draw_node(_FakeLayout(log), properties_node, attr_owner=obj)
    report.check(
        "没收录候选目录的类，properties 依然被 PtBehavior 专属画法接管"
        "（画出属性名 'TestField'，不是通用树的裸下标 '0'）",
        any(e[0] == "label" and e[1] == "TestField" for e in log),
        str(log),
    )
    report.check(
        "已存在的这一条属性画出了紧凑值控件（float_value），不是兜底文案",
        any(e[0] == "prop" and e[2] == "float_value" for e in log),
        str(log),
    )

    bpy.context.view_layer.objects.active = obj
    report.check(
        "efx_re.ptbehavior_property_add 对没收录候选目录的类 poll() 是 False（增删范围不变）",
        not structure_ops.EFX_RE_OT_ptbehavior_property_add.poll(bpy.context),
    )
    report.check(
        "efx_re.ptbehavior_property_remove 对没收录候选目录的类 poll() 也是 False",
        not structure_ops.EFX_RE_OT_ptbehavior_property_remove.poll(bpy.context),
    )


def _make_unknown_ptbehavior_probe(name_suffix: str, data_type: int, raw_bytes: bytes,
                                    name: str = "TestField"):
    """造一个带 `PtBehaviorVariableDataPrefabUnknown` 形状（`variable.data` 是 base64）的
    探针，`dataType`/原始字节/`behaviorProperty`（`name`）由调用方指定。给"vendor 不认识但
    语料能推出字节形状"和"vendor 也没法推出形状"两类检查共用；`name` 主要给 dataType=4
    （`PropUint`）那种"要看字段名才知道按 int 还是 float 解读"的场景用。"""
    import base64

    obj = bpy.data.objects.new(f"ptbehavior_unknown_probe_{name_suffix}", None)
    bpy.context.scene.collection.objects.link(obj)
    obj["~TYPE"] = model.TYPE_ATTRIBUTE
    model.populate_dict_as_children(obj.efx_fields, {
        "behaviorString": "app.EffectTestProbe",
        "properties": [{
            "Version": 5571972,
            "varSize": 99,
            "dataType": data_type,
            "variable": {
                "$type": "_unknown",
                "data": base64.b64encode(raw_bytes).decode("ascii"),
                "Version": 5571972,
                "unkn": 1,
                "size": len(raw_bytes),
                "re4_unkn0": -1,
                "re4_unkn1": 0,
            },
            "varHash": 1,
            "behaviorProperty": name,
        }],
    })
    properties_node = model.find_field(obj.efx_fields, "properties")
    return properties_node.children[0]


def verify_array_group_class_partially_recovered(report: Report) -> None:
    """检查项 13：`tools/gen_ptbehavior_catalog.py` 遇到 `Xxx[N]` 分组头的类不再整类排除，
    先剔掉分组头和分组内部字段，剩下的顶层字段顺序一致的话照样收录。

    用 `via.effect.script.EffectDecal2.EffectDecal_V2` 当探针（`_has_array_group_names`
    docstring 里点名的例子）：这个类以前在 `_excluded` 里，理由是"属性名里有 Xxx[N]"；
    `_recover_top_level_names()` 上线之后应该被收录，候选目录里既不能有 `Xxx[N]` 这种
    分组头名字，也不能有分组内部字段（`ValueType`/`VariableName`/`VariableNameHash`/
    `ValueF`/`ValueTexture`/`ValueVec4`——语料里验证过这几个只出现在
    `OtherMaterialParamList[N]` 分组内部，从不在分组外露面）。
    """
    behavior_string = "via.effect.script.EffectDecal2.EffectDecal_V2"
    report.check(
        f"'{behavior_string}' 现在收录了候选目录（不再整类排除）",
        ptbehavior_catalog.has_catalog(behavior_string),
        "如果这个类在语料重新生成之后又被排除了，检查 _recover_top_level_names() 是不是被改坏了",
    )

    names = [e["name"] for e in ptbehavior_catalog.candidates(behavior_string)]
    report.check(
        "候选目录里没有带下标的分组头（Xxx[N]）",
        names and not any("[" in n for n in names),
        f"names={names}",
    )

    interior_leak = {
        "ValueType", "VariableName", "VariableNameHash",
        "ValueF", "ValueTexture", "ValueVec4",
    } & set(names)
    report.check(
        "候选目录里没有泄漏 OtherMaterialParamList[N] 分组内部的嵌套字段",
        not interior_leak,
        f"interior_leak={interior_leak}",
    )


def verify_unknown_datatype_shapes(report: Report) -> None:
    """检查项 13：vendor 不认识但语料能推出字节形状的 dataType（3/6/8/12/20/22）——
    紧凑控件读写正确、字节数对不上时安全回退、S/R 标签只用在 dataType=20 上。
    """
    import struct

    from blender_efx_re import i18n, panels

    make_probe = _make_unknown_ptbehavior_probe

    # ---- dataType=3：单个 int32 ---------------------------------------------
    child = make_probe("i32", 3, struct.pack("<i", 42))
    variable = model.find_field(child.children, "variable")
    report.check("unknown_data_byte_length() 认出这条数据是 4 字节",
                 model.unknown_data_byte_length(variable) == 4)
    report.check("unknown_int32_value 读出手工写进去的 42", variable.unknown_int32_value == 42)
    variable.unknown_int32_value = -7
    report.check("unknown_int32_value 写回去再读一致（round-trip）",
                 variable.unknown_int32_value == -7)
    report.check("写回去之后字节数没变（不会撑大/压扁 data 字段）",
                 model.unknown_data_byte_length(variable) == 4)

    child.ui_expand = False
    log: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log), child, 0)
    report.check(
        "dataType=3 主行画出了紧凑控件（unknown_int32_value），不是兜底文案",
        any(e[0] == "prop" and e[2] == "unknown_int32_value" for e in log), str(log),
    )

    # ---- dataType=20：int32x2，主行画成 S/R 两列 ----------------------------
    child2 = make_probe("period", 20, struct.pack("<ii", 3, 1))
    variable2 = model.find_field(child2.children, "variable")
    report.check("unknown_int32x2_value 读出手工写进去的 (3, 1)",
                 tuple(variable2.unknown_int32x2_value) == (3, 1))
    variable2.unknown_int32x2_value = (9, 4)
    report.check("unknown_int32x2_value 写回去再读一致",
                 tuple(variable2.unknown_int32x2_value) == (9, 4))

    child2.ui_expand = False
    log2: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log2), child2, 0)
    hits = [e for e in log2 if e[0] == "prop" and e[2] == "unknown_int32x2_value"]
    report.check(
        "dataType=20 主行画出了两条 unknown_int32x2_value（S 一条、R 一条）",
        len(hits) == 2, str(log2),
    )

    # ---- dataType=4（PropUint）：默认按 int32，但特定字段名（DestFloat4）按 float32 -----
    child4a = make_probe("uint_default", 4, struct.pack("<I", 7), name="TargetParts")
    variable4a = model.find_field(child4a.children, "variable")
    report.check("dataType=4 默认按 int32 解读（TargetParts=7）",
                 variable4a.unknown_int32_value == 7)
    child4a.ui_expand = False
    log4a: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log4a), child4a, 0)
    report.check(
        "dataType=4 的 TargetParts 主行画出 unknown_int32_value（不是兜底文案）",
        any(e[0] == "prop" and e[2] == "unknown_int32_value" for e in log4a), str(log4a),
    )

    child4b = make_probe("uint_float_override", 4, struct.pack("<f", 2.5), name="DestFloat4")
    variable4b = model.find_field(child4b.children, "variable")
    report.check("dataType=4 但字段名是 DestFloat4 时按 float32 解读（不是 int32）",
                 abs(variable4b.unknown_float32_value - 2.5) < 1e-6)
    child4b.ui_expand = False
    log4b: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log4b), child4b, 0)
    report.check(
        "dataType=4 的 DestFloat4 主行画出 unknown_float32_value（按字段名覆盖，不是默认的 int32）",
        any(e[0] == "prop" and e[2] == "unknown_float32_value" for e in log4b), str(log4b),
    )

    # ---- dataType=10（PropRange）：float32x2 --------------------------------
    child10 = make_probe("range", 10, struct.pack("<ff", 0.0, 1.0), name="AlphaMaskRange")
    variable10 = model.find_field(child10.children, "variable")
    report.check("unknown_float32x2_value 读出手工写进去的 (0.0, 1.0)",
                 tuple(round(v, 4) for v in variable10.unknown_float32x2_value) == (0.0, 1.0))
    child10.ui_expand = False
    log10: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log10), child10, 0)
    report.check(
        "dataType=10 主行画出了紧凑控件（unknown_float32x2_value）",
        any(e[0] == "prop" and e[2] == "unknown_float32x2_value" for e in log10), str(log10),
    )

    # ---- dataType=21（PropWstring2）：宽字符串，编辑要连 varSize 一起重算 -----
    import base64 as _base64

    text = "Art/VFX/test.tex"
    raw = (text + "\x00").encode("utf-16-le")
    prop_name = "Texture"
    overhead = 21
    varsize = len(raw) + len(prop_name.encode("utf-8")) + overhead
    obj21 = bpy.data.objects.new("ptbehavior_wstring_probe", None)
    bpy.context.scene.collection.objects.link(obj21)
    obj21["~TYPE"] = model.TYPE_ATTRIBUTE
    model.populate_dict_as_children(obj21.efx_fields, {
        "behaviorString": "app.EffectTestProbe",
        "properties": [{
            "Version": 5571972,
            "varSize": varsize,
            "dataType": 21,
            "variable": {
                "$type": "_unknown",
                "data": _base64.b64encode(raw).decode("ascii"),
                "Version": 5571972,
                "unkn": 1,
                "size": len(raw),
                "re4_unkn0": -1,
                "re4_unkn1": 0,
            },
            "varHash": 1,
            "behaviorProperty": prop_name,
        }],
    })
    child21 = model.find_field(obj21.efx_fields, "properties").children[0]
    variable21 = model.find_field(child21.children, "variable")

    report.check("model.is_unknown_wstring_shape() 认出这是合法的宽字符串",
                 model.is_unknown_wstring_shape(variable21))
    report.check(f"unknown_wstring_value 读出手工写进去的 '{text}'",
                 child21.unknown_wstring_value == text)

    new_text = "Art/VFX/a_much_longer_replacement_path.tex"
    child21.unknown_wstring_value = new_text
    report.check("unknown_wstring_value 写回去再读一致（round-trip）",
                 child21.unknown_wstring_value == new_text)

    new_raw_len = len((new_text + "\x00").encode("utf-16-le"))
    inner_size_node = model.find_field(variable21.children, "size")
    report.check("写入更长的字符串之后 variable.size 跟着更新",
                 inner_size_node.int_value == new_raw_len,
                 f"{inner_size_node.int_value} != {new_raw_len}")

    varsize_node = model.find_field(child21.children, "varSize")
    expected_varsize = new_raw_len + len(prop_name.encode("utf-8")) + overhead
    report.check("写入更长的字符串之后外层 varSize 也按公式（size+字段名字节数+21）重算",
                 varsize_node.int_value == expected_varsize,
                 f"{varsize_node.int_value} != {expected_varsize}")

    # 缩短字符串，确认 size/varSize 会跟着缩小（不是只处理变长、没处理变短）
    shorter_text = "a.tex"
    child21.unknown_wstring_value = shorter_text
    shorter_raw_len = len((shorter_text + "\x00").encode("utf-16-le"))
    report.check("缩短字符串之后 variable.size 跟着缩小",
                 inner_size_node.int_value == shorter_raw_len,
                 f"{inner_size_node.int_value} != {shorter_raw_len}")
    report.check(
        "缩短字符串之后外层 varSize 也跟着缩小",
        varsize_node.int_value == shorter_raw_len + len(prop_name.encode("utf-8")) + overhead,
        str(varsize_node.int_value),
    )

    child21.ui_expand = False
    log21: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log21), child21, 0)
    report.check(
        "dataType=21 主行画出了紧凑控件（unknown_wstring_value）",
        any(e[0] == "prop" and e[2] == "unknown_wstring_value" for e in log21), str(log21),
    )

    # ---- 形状不合法（没有 null 结尾）时不提供紧凑编辑，安全回退 ---------------
    child21_bad = make_probe("wstring_badshape", 21, "AB".encode("utf-16-le"))
    child21_bad.ui_expand = False
    log21_bad: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log21_bad), child21_bad, 0)
    report.check(
        "没有 null 结尾的宽字符串形状不合法时不画紧凑控件，落回兜底文案",
        not any(e[0] == "prop" and e[2] == "unknown_wstring_value" for e in log21_bad),
        str(log21_bad),
    )

    # ---- dataType=24（OBB）：9 个浮点单行放不下，画成 T/R/S 三行 -----------
    obb_bytes = struct.pack("<fffffffff", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 5.0, 5.0)
    child24 = make_probe("obb", 24, obb_bytes, name="OBB")
    variable24 = model.find_field(child24.children, "variable")
    report.check(
        "unknown_float32x9_value 读出手工写进去的 9 个分量",
        tuple(round(v, 4) for v in variable24.unknown_float32x9_value)
        == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 5.0, 5.0),
    )
    variable24.unknown_float32x9_value = (1, 2, 3, 4, 5, 6, 7, 8, 9)
    report.check(
        "unknown_float32x9_value 写回去再读一致（round-trip）",
        tuple(round(v, 4) for v in variable24.unknown_float32x9_value) == (1, 2, 3, 4, 5, 6, 7, 8, 9),
    )

    child24.ui_expand = False
    log24: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log24), child24, 0)
    obb_prop_hits = [e for e in log24 if e[0] == "prop" and e[2] == "unknown_float32x9_value"]
    report.check(
        "dataType=24 画出了 9 个 unknown_float32x9_value（T/R/S 三行，每行 3 个）",
        len(obb_prop_hits) == 9, str(log24),
    )
    obb_label_hits = [e for e in log24 if e[0] == "label" and e[1] in ("T", "R", "S")]
    report.check(
        "dataType=24 画出了 T/R/S 三个行标签",
        {e[1] for e in obb_label_hits} == {"T", "R", "S"}, str(log24),
    )
    report.check(
        "dataType=24 不受 ui_expand 折叠状态影响——child.ui_expand=False 时 T/R/S 照样画出来",
        len(obb_prop_hits) == 9,  # 上面已经在 ui_expand=False 状态下验证过
    )

    # ---- 字节数和期望不对（OBB 只给 32 字节）：落回「未知数据类型」而不是硬凑 ---
    child24_bad = make_probe("obb_badlen", 24, b"\x00" * 32)
    child24_bad.ui_expand = False
    log24_bad: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log24_bad), child24_bad, 0)
    report.check(
        "OBB 字节数不对时不画 T/R/S 三行，落回「未知数据类型」（dataType=24 本身 vendor 也不认识）",
        not any(e[0] == "prop" and e[2] == "unknown_float32x9_value" for e in log24_bad)
        and any(e[0] == "label" and e[1] == i18n.T("ptbehavior.unknown_shape") for e in log24_bad),
        str(log24_bad),
    )

    # ---- 字节数和期望对不上：安全回退，不拿越界字节瞎猜 ---------------------
    child3 = make_probe("badlen", 3, struct.pack("<h", 5))  # dataType=3 期望 4 字节，只给 2
    child3.ui_expand = False
    log3: list = []
    panels._draw_ptbehavior_property(_FakeLayout(log3), child3, 0)
    report.check(
        "字节数对不上时不画紧凑控件，落回兜底文案",
        not any(e[0] == "prop" and e[2] == "unknown_int32_value" for e in log3),
        str(log3),
    )


def main() -> int:
    opts = _parse_args(_script_args())
    efx_path = pathlib.Path(opts.get("efx", _DEFAULT_EFX))

    if not efx_path.is_file():
        print(f"[ERROR] 样本不存在：{efx_path}（用 -- --efx <文件> 指定）")
        return 1

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="efx_ptbehavior_"))
    print(f"输出目录: {workdir}（跑完不删）")

    blender_efx_re.register()

    report = Report()
    verify(efx_path, workdir, report)
    verify_excluded_class_still_renders(report)
    verify_array_group_class_partially_recovered(report)
    verify_unknown_datatype_shapes(report)

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    # ⚠ 必须自己捕获异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # 未捕获异常时退出码仍然是 0（实测），`sys.exit(main())` 那行根本轮不到执行。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
