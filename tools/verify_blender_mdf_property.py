"""
tools/verify_blender_mdf_property.py —— 材质参数覆盖表（TypeMesh 的 `properties`）增删门禁

必须在 Blender 里跑（要真 bpy），仓库根目录下：

    <blender> --background --factory-startup --python tools/verify_blender_mdf_property.py

可选参数放在 `--` 之后：

    ... -- --efx <样本 .efx 路径> --game <游戏安装目录> --mdf <参考 .mdf2>

`--game` 默认 `E:\\Program\\Steam\\steamapps\\common\\MonsterHunterWilds`，只用来在没给
`--mdf` 时用 `pakextract` 现捞一份样本 attribute 引用的那个材质（VFX 材质一般没人专门解包）。
找不到样本/游戏目录时报错退 1，不静默全绿（同其它两个门禁脚本的约定）。

检查项：

1. `mdf_catalog` 能解析参考 .mdf2，且候选列表**恰好**排除掉已经覆盖过的参数。
2. `efx_re.mdf_property_add` 加出来的那条，四个结构字段全部对得上 mdf2（`mdfPropertyIndex`
   = 参数在材质里的下标、`mdfParameterValueCount` = componentCount、`parameterType` 按
   componentCount 分档、`PropertyNameUTF8Hash` = 参数名的 UTF-8 哈希）。
3. 加完之后走 Export 算子写出来的文件**能被 RE-Engine-Lib 读回来**，且读回来的条数、
   `propertiesDataSize` 都对得上。
4. `efx_re.mdf_property_remove` 删掉之后同样能读回来，条数正确。
5. **把 bug 注回去要真的 FAIL**（CLAUDE.md 验证纪律 #11）：临时停掉
   `io_tree._refresh_derived_sizes()` 之后，同样的导出必须失败——这个字段 vendor 写出
   时不自愈（`RszByteSizeField` 没进代码生成器的重算分支，`EFXAttributeTypeMeshV2.DoWrite()`
   也没补），不重算就会写出一个读不回来的文件。这条是整个功能唯一的"必须我们自己算"的地方，
   所以它的回归防护必须被验证过是有效的，而不是只看它绿。

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
from blender_efx_re import bridge, io_tree, mdf_catalog, model, operators, structure_ops  # noqa: E402

_DEFAULT_GAME_DIR = r"E:\Program\Steam\steamapps\common\MonsterHunterWilds"
# MHWilds 的 .mdf2 版本号后缀。pak 里的条目按完整内部路径算哈希，少这个后缀就查不到。
_MDF2_VERSION = 45
_DEFAULT_EFX = (
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\EFX\natives\STM"
    r"\Art\VFX\EffectEditor\Weapon\it13\11_it13_400.efx.5571972"
)


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


def _find_mdf_attribute():
    """场景里第一个带材质参数覆盖表的 attribute 对象。"""
    for obj in bpy.data.objects:
        node, material_path = structure_ops.resolve_mdf_properties(obj)
        if node is not None:
            return obj, node, material_path
    return None, None, None


def _export(root_col, out_path: pathlib.Path) -> pathlib.Path:
    """走导出算子那条数据路径（不含文件浏览器 UI），返回实际写出的路径。"""
    data = io_tree.export_root_to_efxfile(root_col)
    resolved, notice, fatal = operators._ensure_version_suffix(str(out_path), data)
    if fatal:
        raise RuntimeError(notice or "导出路径拿不到合法版本号后缀")
    bridge.load_efx(data, resolved)
    return pathlib.Path(resolved)


def _read_back_properties(path: pathlib.Path):
    """读回写出的文件，返回第一个带覆盖表的 attribute 的 (properties, propertiesDataSize)。"""
    data = bridge.dump_efx(path)
    for entry in data.get("Entries") or []:
        for attr in entry.get("Attributes") or []:
            props = attr.get("properties")
            if (isinstance(props, list) and props and isinstance(props[0], dict)
                    and "PropertyNameUTF8Hash" in props[0]):
                return props, attr.get("propertiesDataSize")
    return None, None


class _FakeLayout:
    """记录调用的假 UILayout。无头 Blender 没有区域可以真画面板，但面板代码里的逻辑错误
    （拿错节点、prop 名字打错、形状判断写反）不该等到用户点开侧栏才发现——用它把 draw 跑一遍，
    既验证不抛异常，也能断言主行上画出来的确实是"该编辑的那几个"。

    `__getattr__` 兜底成"返回子布局的空调用"，这样 draw_node 里那些还没用到的布局 API
    （prop_search/template_list/separator...）不会让这个桩失效。
    """

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


def _verify_panel_draw(node, attr_owner, report) -> None:
    """把材质覆盖表那段 UI 用假布局跑一遍，断言主行只画该编辑的字段、展开后派生字段是只读的。"""
    from blender_efx_re import panels

    by_kind = {}
    for child in node.children:
        by_kind.setdefault(model.node_to_value(child).get("parameterType"), child)

    # Float 是整包 float4，Range 只画取值区间那两个（X/Y 全语料恒为 0，见 panels 里的说明）。
    # Float 要挑一个**名字不像颜色**的——像颜色的走色块那条分支，另外单独验。
    plain_float = next(
        (c for c in node.children
         if model.node_to_value(c).get("parameterType") == "Float"
         and not panels.is_color_param_name(panels._mdf_property_name(c))), None)
    for kind, child, expected in (
        ("Float", plain_float, ["X", "Y", "Z", "W"]),
        ("Range", by_kind.get("Range"), ["Z", "W"]),
    ):
        if child is None:
            continue
        child.ui_expand = False
        log: list = []
        panels._draw_mdf_property(_FakeLayout(log), child, 0, attr_owner)
        drawn = [e[1] for e in log if e[0] == "prop" and e[2] != "ui_expand"]
        report.check(f"{kind} 主行画出 {'/'.join(expected)}", drawn == expected, str(drawn))

    # 色块判据照抄 RE Mesh Editor（blender_re_mdf.py:184）：4 分量 + 名字带 color/_col_ +
    # 不带 rate。这几条是它实际表现的样子，跑偏了就说明我们和它长得不一样了。
    for name, expected in (
        ("ColorParam", True), ("ColorA", True), ("Emissive_Col_A", True),
        ("ColorBlendRate", False), ("UVTransform", False), ("Opacity", False),
    ):
        report.check(f"色块判据：{name} -> {expected}",
                     panels.is_color_param_name(name) is expected)

    # 名字命中色块判据的 Float 参数，主行画的应该是那个色块代理属性而不是四个数。
    color_child = next(
        (c for c in node.children
         if model.node_to_value(c).get("parameterType") == "Float"
         and panels.is_color_param_name(panels._mdf_property_name(c))), None)
    if color_child is not None:
        color_child.ui_expand = False
        log = []
        panels._draw_mdf_property(_FakeLayout(log), color_child, 0, attr_owner)
        drawn = [(e[1], e[2]) for e in log if e[0] == "prop" and e[2] != "ui_expand"]
        report.check(
            f"颜色参数 '{panels._mdf_property_name(color_child)}' 主行画的是色块",
            drawn == [("value", "float4_color_value")], str(drawn),
        )

    texture_child = by_kind.get("Texture")
    if texture_child is None:
        print("  （这条覆盖表里没有贴图属性，跳过贴图的面板绘制检查）")
        return

    # 折叠态：主行只有 texturePath 一个可编辑控件，四个重算字段一个都不该出现。
    texture_child.ui_expand = False
    log: list = []
    panels._draw_mdf_property(_FakeLayout(log), texture_child, 0, attr_owner)
    # `ui_expand` 是折叠箭头本身，不算字段控件（它画在 property 节点上，所以 key 是数组下标）。
    fields = [entry for entry in log if entry[0] == "prop" and entry[2] != "ui_expand"]
    report.check(
        "折叠态主行只画 texturePath（不画 pathLength/textureIndex 这些重算字段）",
        [f[1] for f in fields] == ["texturePath"],
        str(fields),
    )
    report.check("折叠态有删除按钮",
                 any(e[0] == "operator" and e[1] == "efx_re.mdf_property_remove" for e in log))

    # 展开态：派生字段必须是画在 enabled=False 的行里。
    texture_child.ui_expand = True
    log = []
    panels._draw_mdf_property(_FakeLayout(log), texture_child, 0, attr_owner)
    drawn = {entry[1]: entry[3] for entry in log if entry[0] == "prop" and entry[1]}
    derived = sorted(panels._MDF_DERIVED_KEYS | panels._MDF_DERIVED_VALUE_KEYS)
    editable_derived = [key for key in derived if drawn.get(key) is True]
    report.check("展开态派生/重算字段全部画成只读", not editable_derived, str(editable_derived))
    report.check("展开态 flags 仍可编辑（语义未知但不是派生量）", drawn.get("flags") is True,
                 str(drawn))
    texture_child.ui_expand = False


def _verify_bookkeeping_hidden(obj, report) -> None:
    """记账字段不该出现在字段列表里，但**必须照样导出**——隐藏的是界面，不是数据。"""
    from blender_efx_re import panels

    log: list = []
    panels._draw_fields_content(_FakeLayout(log), bpy.context, obj)
    drawn = {entry[1] for entry in log if entry[0] == "prop"}
    leaked = sorted(panels._DERIVED_FIELD_KEYS & drawn)
    report.check("记账字段不出现在字段列表里", not leaked, str(leaked))

    exported = io_tree.export_attribute_object(obj)
    present = [k for k in ("propertiesDataSize", "texCount", "texPathBlockLength", "texPaths")
               if k in exported]
    report.check("记账字段仍然照常导出（隐藏的是界面不是数据）", len(present) == 4, str(present))

    # `mdfPropertyIndex` 在贴图那条是派生的、其余是真实数据，一半一半，不能按名字一刀切。
    # 名单要是哪天被人顺手"补全"了，这条会先炸。
    report.check("'mdfPropertyIndex' 没有被误加进隐藏名单",
                 "mdfPropertyIndex" not in panels._DERIVED_FIELD_KEYS)


def _verify_unkn_data_size(report) -> None:
    """`TypeGpuMesh.unknDataSize` 是 `unknData` 那个字节块的长度（语料 392/392 满足），
    vendor 不重算，我们自己算——这里直接验那个重算函数：块变了长度就得跟着变，块坏了不动它。

    不走完整的导入/导出：语料里带这个字段的是 TypeGpuMesh，和本脚本用的样本不是同一个
    attribute，为它单独准备一个样本不值当；重算逻辑本身是纯函数，直接喂字典验更直接。
    """
    import base64

    blob = base64.b64encode(bytes(96)).decode("ascii")
    attr = {"unknDataSize": 7, "unknData": blob}
    io_tree._refresh_derived_sizes(attr, 5571972)
    report.check("unknDataSize 按 unknData 的真实长度重算", attr["unknDataSize"] == 96,
                 str(attr["unknDataSize"]))

    attr = {"unknDataSize": 32, "unknData": None}
    io_tree._refresh_derived_sizes(attr, 5571972)
    report.check("unknData 为空时 unknDataSize 归 0", attr["unknDataSize"] == 0,
                 str(attr["unknDataSize"]))

    # base64 坏掉时保持原值：瞎算一个 0 会把原本还能救的块长也抹掉。
    attr = {"unknDataSize": 32, "unknData": "!!! not base64 !!!"}
    io_tree._refresh_derived_sizes(attr, 5571972)
    report.check("base64 坏掉时不乱动 unknDataSize", attr["unknDataSize"] == 32,
                 str(attr["unknDataSize"]))

    # 没有这个字段的 attribute 不该被凭空塞一个。
    attr = {"$type": "whatever"}
    io_tree._refresh_derived_sizes(attr, 5571972)
    report.check("没有 unknDataSize 的 attribute 不会被凭空加字段",
                 "unknDataSize" not in attr)


def _verify_mismatch_marking(node, obj, mdf_path: str, report) -> None:
    """指一个**不相干**的材质，覆盖表里的条目应该被标出来、并且真的画成标红行。

    用参考材质自己的第一个参数造一个"只有这一个参数"的假材质来核对逻辑不够——那验不到
    "载入算子会把结果记下来"这条链路。这里直接换一个真实的、不相干的 .mdf2（把参考材质的
    参数表整体挪一位模拟不了载入流程），走完整的算子。
    """
    from blender_efx_re import panels

    # 造一个"参数下标全部挪一位"的假材质：直接改缓存里那份解析结果，等价于指了一个结构不同
    # 的材质，但不需要再去找第二个真实文件。
    payload = mdf_catalog.load(mdf_path)
    original = [dict(p) for p in payload["materials"][0]["parameters"]]
    for param in payload["materials"][0]["parameters"]:
        param["index"] += 1
    try:
        bpy.ops.efx_re.mdf_reference_load(filepath=mdf_path)
        marked = structure_ops.mismatched_hashes(obj)
        report.check("指了结构对不上的材质：标记被记下来", bool(marked), str(marked))

        first_marked = next(
            (c for c in node.children if panels._mdf_property_hash(c) in marked), None)
        report.check("对不上的条目能在覆盖表里定位到", first_marked is not None)
        if first_marked is not None:
            log: list = []
            panels._draw_mdf_property(_FakeLayout(log), first_marked, 0, obj, marked)
            report.check("对不上的那一行画了错误图标",
                         any(e[0] == "label" and e[3] == "ERROR" for e in log),
                         str(log[:4]))
    finally:
        payload["materials"][0]["parameters"] = original

    # 换回对的材质，标记必须清干净——否则红点会一直挂着，比不标还糟。
    bpy.ops.efx_re.mdf_reference_load(filepath=mdf_path)
    report.check("换回对的材质后标记清空", structure_ops.mismatched_hashes(obj) == set(),
                 repr(obj.efx_mdf_mismatched))

    bpy.ops.efx_re.mdf_reference_clear()
    report.check("清除参考材质会一并清掉标记", obj.efx_mdf_mismatched == "")
    bpy.ops.efx_re.mdf_reference_load(filepath=mdf_path)


def _verify_texture_branch(root_col, node, material_path, entries, workdir, report) -> None:
    """贴图槽那条分支单独验一遍：它和数值参数走的是 `build_property_dict()` 里完全不同的一支，
    而且是唯一一条 vendor 写出时会**解引用** `texturePath` 的路径
    （`EFXAttributeTypeMeshV2.DoWrite()` 里 `p.texturePath!.Length`）——填不上就是写出时崩，
    不是静默出错。语料里的材质通常贴图槽已经被占了，所以先删掉再重新加，模拟"换一张贴图"。
    """
    textures = [e for e in entries if e["kind"] == "texture"]
    if not textures:
        print("  （这个材质没有贴图槽，跳过贴图分支）")
        return
    pick = textures[0]

    for index, child in enumerate(node.children):
        values = model.node_to_value(child)
        if values.get("PropertyNameUTF8Hash") == pick["utf8Hash"]:
            bpy.ops.efx_re.mdf_property_remove(index=index)
            break

    before = len(node.children)
    bpy.ops.efx_re.mdf_property_add(candidate=str(pick["utf8Hash"]))
    added = model.node_to_value(node.children[-1])
    report.check(
        f"贴图槽 '{pick['name']}' 加出来的那条形状对",
        (added["parameterType"] == "Texture" and added["mdfPropertyIndex"] == -1
         and added.get("texturePath") == pick.get("path")),
        str(added),
    )

    out_path = _export(root_col, workdir / "texture.efx")
    props, _ = _read_back_properties(out_path)
    report.check("加了贴图属性之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("读回来的条数对（贴图）", len(props) == before + 1,
                     f"{len(props)} != {before + 1}")
        back = next((p for p in props if p["PropertyNameUTF8Hash"] == pick["utf8Hash"]), None)
        report.check(
            "贴图路径原样读回来了（vendor 会重建 texPaths 表并回填 textureIndex）",
            back is not None and back.get("texturePath") == pick.get("path"),
            str(back),
        )


def verify(efx_path: pathlib.Path, mdf_path: str, workdir: pathlib.Path, report: Report) -> None:
    data = bridge.dump_efx(efx_path)
    root_col = io_tree.build_root_from_efxfile(data, bpy.context.scene.collection, efx_path.name)
    root_col.efx_source_filename = efx_path.name

    obj, node, material_path = _find_mdf_attribute()
    if obj is None:
        report.check(f"{efx_path.name}: 找到带材质参数覆盖表的 attribute", False,
                     "样本里没有 TypeMesh 系列 attribute，换一个 --efx")
        return
    print(f"  样本 {efx_path.name}：{obj.efx_attr_type.split('.')[-1]} -> {material_path}")

    # 导入时每条 property 都该是收起的（`EFXValueNode.ui_expand` 全局默认展开，这一处由
    # io_tree.collapse_mdf_properties() 单独收起来）。
    report.check("导入后每条 property 默认收起",
                 not any(child.ui_expand for child in node.children),
                 str([child.key for child in node.children if child.ui_expand]))

    # 参考材质走真实算子那条路（它会自己解析一遍、失败就不记路径）。
    bpy.context.view_layer.objects.active = obj
    bpy.ops.efx_re.mdf_reference_load(filepath=mdf_path)
    report.check("载入参考 .mdf2", obj.efx_mdf_reference == mdf_path,
                 f"efx_mdf_reference = {obj.efx_mdf_reference!r}")

    before = len(node.children)
    present = structure_ops._present_hashes(node)

    try:
        entries = mdf_catalog.candidates(obj.efx_mdf_reference)
    except mdf_catalog.CatalogError as ex:
        report.check("解析参考材质的参数表", False, str(ex))
        return
    report.check("解析参考材质的参数表", bool(entries), f"候选 {len(entries)} 条")

    # 指错材质的唯一后果就是下标错，而下标错不会有任何报错——所以"能认出对不上"这条本身
    # 也要验：对的材质必须零投诉，把下标整体挪一位必须被抓出来。
    report.check("对的材质：现有条目全部核对通过",
                 not structure_ops.reference_mismatches(node, entries))
    shifted = [dict(e, index=e["index"] + 1) if e["kind"] == "param" else e for e in entries]
    report.check("把参考材质的下标挪一位，必须被认出来",
                 bool(structure_ops.reference_mismatches(node, shifted)))
    report.check("对的材质：不留下任何标红记录", obj.efx_mdf_mismatched == "",
                 repr(obj.efx_mdf_mismatched))

    free = [e for e in entries if e["utf8Hash"] not in present]
    report.check(
        "候选列表排除掉已经覆盖过的参数",
        len(free) == len(entries) - len([e for e in entries if e["utf8Hash"] in present]),
    )
    if not free:
        report.check("样本还有没被覆盖的参数可以加", False, "这个材质已经全覆盖，换一个样本")
        return

    pick = free[0]
    bpy.ops.efx_re.mdf_property_add(candidate=str(pick["utf8Hash"]))
    report.check("Add 算子加出一条", len(node.children) == before + 1,
                 f"{before} -> {len(node.children)}")

    added = model.node_to_value(node.children[-1])
    expected_type = "Float" if pick["componentCount"] == 4 else "Range"
    report.check(
        f"新增的 '{pick['name']}' 四个结构字段都对得上 mdf2",
        (added["PropertyNameUTF8Hash"] == pick["utf8Hash"]
         and added["mdfPropertyIndex"] == pick["index"]
         and added["mdfParameterValueCount"] == pick["componentCount"]
         and added["parameterType"] == expected_type),
        str(added),
    )
    # 键序不能变：vendor 的 MdfPropertyJsonConverter.Read() 读到 "value" 时按**当时已经读到的**
    # parameterType 决定解析成贴图还是 float4（EfxFile.cs:541-547），parameterType 排到后面
    # 的话贴图属性会被当成 float4 读进来。
    keys = [child.key for child in node.children[-1].children]
    report.check(
        "parameterType 排在 value 前面（vendor 流式解析依赖这个顺序）",
        "parameterType" in keys and "value" in keys
        and keys.index("parameterType") < keys.index("value"),
        str(keys),
    )

    out_path = _export(root_col, workdir / "added.efx")
    props, size = _read_back_properties(out_path)
    report.check("加完之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("读回来的条数对", len(props) == before + 1, f"{len(props)} != {before + 1}")
        report.check("读回来的 propertiesDataSize 对", size == (before + 1) * 32,
                     f"{size} != {(before + 1) * 32}")

    bpy.ops.efx_re.mdf_property_remove(index=len(node.children) - 1)
    report.check("Remove 算子删掉一条", len(node.children) == before,
                 f"{len(node.children)} != {before}")
    out_path = _export(root_col, workdir / "removed.efx")
    props, size = _read_back_properties(out_path)
    report.check("删完之后写出的文件能读回来", props is not None)
    if props is not None:
        report.check("删完读回来的条数对", len(props) == before, f"{len(props)} != {before}")

    _verify_panel_draw(node, obj, report)
    _verify_bookkeeping_hidden(obj, report)
    _verify_unkn_data_size(report)
    _verify_mismatch_marking(node, obj, mdf_path, report)
    _verify_texture_branch(root_col, node, material_path, entries, workdir, report)

    # ---- 把 bug 注回去，确认防护真的会 FAIL（验证纪律 #11）-------------------
    bpy.ops.efx_re.mdf_property_add(candidate=str(pick["utf8Hash"]))
    original = io_tree._refresh_derived_sizes
    io_tree._refresh_derived_sizes = lambda attr_dict, version: None
    try:
        broken = _export(root_col, workdir / "broken.efx")
        bridge.dump_efx(broken)
        injected_fails = False
    except Exception:
        injected_fails = True
    finally:
        io_tree._refresh_derived_sizes = original
    report.check(
        "停掉 propertiesDataSize 重算之后，同样的导出必须失败",
        injected_fails,
        "防护无效：不重算 propertiesDataSize 也能写出可读的文件，说明这条检查测不到东西",
    )


def _extract_reference(game_dir: str, material_path: str, workdir: pathlib.Path) -> str:
    """用 `pakextract` 从游戏 pak 里现捞一份参考 .mdf2 —— VFX 材质一般没人专门解包，
    门禁不该因此要求先手工准备一个文件。"""
    internal = f"natives/STM/{material_path}.{_MDF2_VERSION}"
    out_path = workdir / f"reference.mdf2.{_MDF2_VERSION}"
    bridge._run("pakextract", game_dir, internal, str(out_path))
    return str(out_path)


def _first_material_path(efx_path: pathlib.Path) -> str:
    """样本里第一个 TypeMesh 系列 attribute 引用的材质路径（不建 Blender 对象，纯读 JSON）。"""
    data = bridge.dump_efx(efx_path)
    for entry in data.get("Entries") or []:
        for attr in entry.get("Attributes") or []:
            if isinstance(attr.get("properties"), list) and "propertiesDataSize" in attr:
                for key in ("MaterialPath", "mdfPath"):
                    if attr.get(key):
                        return attr[key]
    return ""


def main() -> int:
    opts = _parse_args(_script_args())
    game_dir = opts.get("game", _DEFAULT_GAME_DIR)
    efx_path = pathlib.Path(opts.get("efx", _DEFAULT_EFX))

    if not efx_path.is_file():
        print(f"[ERROR] 样本不存在：{efx_path}（用 -- --efx <文件> 指定）")
        return 1

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="efx_mdfprop_"))

    mdf_path = opts.get("mdf", "")
    if not mdf_path:
        if not pathlib.Path(game_dir).is_dir():
            print(f"[ERROR] 游戏目录不存在：{game_dir}"
                  "（用 -- --game <目录> 指定，或用 -- --mdf <文件> 直接给一个参考材质）")
            return 1
        material_path = _first_material_path(efx_path)
        if not material_path:
            print(f"[ERROR] 样本里没有带材质参数覆盖表的 attribute：{efx_path}")
            return 1
        try:
            mdf_path = _extract_reference(game_dir, material_path, workdir)
        except Exception as ex:
            print(f"[ERROR] 从 pak 里取参考材质失败（{material_path}）：{str(ex).strip()[:200]}")
            return 1
    if not pathlib.Path(mdf_path).is_file():
        print(f"[ERROR] 参考材质不存在：{mdf_path}")
        return 1

    print(f"参考材质: {mdf_path}\n输出目录: {workdir}（跑完不删）")

    blender_efx_re.register()

    report = Report()
    verify(efx_path, mdf_path, workdir, report)

    if report.failures:
        print(f"\n===== {len(report.failures)} 项失败")
        for label in report.failures:
            print(f"  - {label}")
        return 1
    print("\n===== ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
