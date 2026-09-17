"""
tools/verify_blender_asset_link.py —— 导入时资源联动（asset_link.py）的 Blender 侧门禁

    <blender> --background --factory-startup --python tools/verify_blender_asset_link.py \
        [-- --sample <efx 文件>]

退出码 0/1。找不到样本 -> 报错退 1，不静默全绿。

## 它防的是什么

1. **联动不能碰导出字节。** `asset_link` 只该写 Blender 的父子关系和 attribute 上的编辑期
   状态（`efx_mdf_reference`），这两样 `io_tree.export_*` 都不看。但"挂在 Entry 下面的对象"
   这件事离 `typed_children()` 只有一个 `~TYPE` 判断的距离——判错了就是把一个网格对象当成
   attribute 导出去。现有的 `verify_blender_roundtrip.py` 是"导入->导出"、中间不经过联动，
   对这种错**完全免疫**。
   第 3 项带**反例对照组**（铁律 #11）：把同一个挂上去的对象打上 `~TYPE = EFX_ATTRIBUTE`
   标记，字节必须**变**——否则这条字节比较根本没有牙。
2. **引用发现要和文件内容对得上。** `iter_mesh_refs()` / `iter_uvs_refs()` 走的是建好的
   属性树，拿 `bridge.dump_efx()` 的原始 JSON 当独立第二意见交叉核对。
3. **`SequenceNo` 的主值取的是首字段（`r`）不是 `s`**（CLAUDE.md "`{s,r}` 字段的主值"）。
   写死 `s` 不会报错，只会静默指错序列。
4. `asset_paths` 的候选顺序：`.tex` 先找 `streaming/`（全分辨率那份），别的扩展名不找；
   pak 缓存是 `natives/STM/` 镜像（RE Mesh Editor 靠这段反推贴图根目录）。
5. **资源先在这个 efx 自己旁边找**：从被导入的 `.efx` 向上回溯到含 `natives/` 的那一层，
   排在资产库语料目录**前面**。反过来会在 mod 工程场景下静默加载官方原版的同名文件，
   界面上完全看不出来。带反例对照组：不传 `near` 时不能命中那棵临时树。
6. UVS 集合、网格集合挂进 EFX_ROOT 之后，`io_tree.root_collections()` 还能取对
   Entries/Actions（它按 `children[0]`/`children[1]` 取，多挂几个子集合不能把它挤歪）。
7. VFX 材质的自发光接线：颜色/强度进对了节点、强度乘过 `EMISSION_MULTIPLIER`、
   **RE Mesh Editor 自己接过的不抢**。

## 不覆盖的部分

**`.mesh` 那一半跑不到**：`--factory-startup` 不加载任何第三方插件，RE Mesh Editor 不在场，
`asset_link.mesh_importer_available()` 恒 False。所以第 1 项里"挂网格"是用一个 Empty 模拟的
（它测的正是"挂一个非 ~TYPE 对象上去会不会污染导出"，那才是危险的部分）。真正调
RE Mesh Editor 那一步只能在有界面的 Blender 里实测。

**拖入的确认弹窗跑不到**：`--background` 下 `invoke_props_dialog()` 弹不出窗、会当场直接执行
算子并返回 `{"FINISHED"}`，和"没弹窗直接导入"在脚本里**完全无法区分**（试过从 Python 侧
monkeypatch `bpy.types.WindowManager.invoke_props_dialog` 来拦——拦不住，`context.window_manager`
上的方法走的是 RNA，不看 Python 类属性）。与其加一条怎么都会绿的检查，不如不加：
这条只能在有界面的 Blender 里真拖一个文件进去看。
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
from blender_efx_re import (asset_link, asset_paths, bridge, io_tree,  # noqa: E402
                            mdf_catalog, model, operators, uvs_model)

_FAILED = 0


def _check(ok: bool, label: str, detail: str = "") -> None:
    global _FAILED
    if ok:
        print(f"  PASS  {label}")
    else:
        _FAILED += 1
        print(f"  FAIL  {label}" + (f"  —— {detail}" if detail else ""))


def _script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


#: 语料根的候选，按顺序试第一个存在的。列一串而不是写死一条：用户重新组织过一次解包目录
#: （`MHWILDS_EXTRACT/EFX/natives/STM/...` -> `MHWILDS_EXTRACT/natives/STM/...`），
#: 写死那条之后整条门禁直接哑掉。全落空仍然报错退 1，不静默全绿。
_CORPUS_ROOTS = (
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\natives\STM\Art\VFX",
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\EFX\natives\STM\Art\VFX",
)
_CORPUS_ROOT = next((pathlib.Path(p) for p in _CORPUS_ROOTS if pathlib.Path(p).is_dir()),
                    pathlib.Path(_CORPUS_ROOTS[0]))
#: 手头已知同时带 MeshPath 和 UVSPath 的样本（2026-09-13 实测：1 个 TypeMeshV2 + 4 个
#: UVSequence）。不在的话就现扫一个，两条都落空才报错退 1。
_PREFERRED_SAMPLE = _CORPUS_ROOT / "EffectEditor" / "Common" / "guide" / "11_guide_004.efx.5571972"


def _pick_sample() -> pathlib.Path:
    argv = _script_args()
    if "--sample" in argv:
        return pathlib.Path(argv[argv.index("--sample") + 1])
    if _PREFERRED_SAMPLE.is_file():
        return _PREFERRED_SAMPLE
    if not _CORPUS_ROOT.is_dir():
        raise SystemExit(f"[FATAL] 找不到语料目录：{_CORPUS_ROOT}（用 -- --sample <文件> 指定）")
    # 路径字段是 UTF-16 内联字符串，按字节找 `.mesh` / `.uvs` 就够筛出候选，
    # 比逐个 dump 快几个数量级。
    needles = (".mesh".encode("utf-16-le"), ".uvs".encode("utf-16-le"))
    for path in sorted(_CORPUS_ROOT.rglob("*.efx.5571972"))[:400]:
        data = path.read_bytes()
        if all(n in data for n in needles):
            return path
    raise SystemExit("[FATAL] 语料里扫不到同时引用 mesh 和 uvs 的样本")


def _export_bytes(root_col, tmpdir: pathlib.Path, tag: str) -> bytes:
    """走导出算子的数据路径写一份文件，读回字节。判据是"联动前后一致"，不是"和原文件一致"
    （铁律 #9）。"""
    data = io_tree.export_root_to_efxfile(root_col)
    out = tmpdir / f"{tag}.efx"
    path, _notice, fatal = operators._ensure_version_suffix(str(out), data)
    if fatal:
        raise RuntimeError(f"补不出版本号后缀：{fatal}")
    bridge.load_efx(data, path)
    return pathlib.Path(path).read_bytes()


def _json_refs(sample: pathlib.Path) -> tuple[set, set]:
    """独立第二意见：直接从 `dump` 的 JSON 里捞路径，不经过属性树。"""
    data = bridge.dump_efx(sample)
    meshes, uvs = set(), set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and value:
                    if key in model.MESH_PATH_KEYS:
                        meshes.add(value)
                    elif key == model.UVS_PATH_KEY:
                        uvs.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return meshes, uvs


def _json_sequence_numbers(sample: pathlib.Path) -> list[int]:
    """JSON 里每个 UVSequence 的 `SequenceNo` 首字段（= 主值，见 CLAUDE.md）。

    `via.RangeI` 声明成 `{r, s}`，JSON 对象的键序就是二进制字段序，所以"第一个键的值"
    就是主值——这里**故意不查名单**，用键序当独立判据，好和 `model.sr_children_ordered()`
    那条（查名单 + 看 data_type）互相印证。
    """
    data = bridge.dump_efx(sample)
    out: list[int] = []

    def walk(node):
        if isinstance(node, dict):
            seq = node.get("SequenceNo")
            if isinstance(seq, dict) and seq:
                out.append(int(list(seq.values())[0]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


def _import_sample(sample: pathlib.Path):
    """走**真实的导入算子**（铁律 #8），不是直接调 build_root_from_efxfile()——
    `efx_source_dir` 之类"只有算子才会填"的东西，绕过算子就测不到。
    两个联动开关留默认关，联动那一半在 check_readonly() 里单独跑。

    `bpy.ops.efx_re.import` 写不出来：`import` 是 Python 关键字，只能 getattr。
    """
    getattr(bpy.ops.efx_re, "import")(filepath=str(sample))
    return bpy.context.scene.efx_re_active_root


# ---------------------------------------------------------------------------

def check_path_helpers() -> None:
    print("[1] asset_paths 的候选顺序 / 缓存布局")

    tex_candidates = asset_paths._relative_candidates(
        "Art/VFX/Texture/a.tex.241106027", "tex")
    _check(len(tex_candidates) == 2 and tex_candidates[0].startswith("streaming/"),
           ".tex 先找 streaming/（全分辨率那份）", str(tex_candidates))

    for ext, rel in (("uvs", "Art/VFX/UVS/a.uvs.8"), ("mesh", "Art/VFX/Mesh/a.mesh.241111606")):
        cands = asset_paths._relative_candidates(rel, ext)
        _check(cands == [rel], f".{ext} 只有一份，不去 streaming/ 里瞎找", str(cands))

    _check(asset_paths.internal_with_suffix("Art/VFX/Mesh/a.mesh").endswith(".mesh.241111606"),
           ".mesh 的版本号后缀是 241111606",
           asset_paths.internal_with_suffix("Art/VFX/Mesh/a.mesh"))

    natives_root = asset_paths.cache_natives_root()
    _check(natives_root.parts[-2:] == ("natives", "STM"),
           "pak 缓存是 natives/STM 镜像（RE Mesh Editor 靠这段反推贴图根）",
           str(natives_root))


def check_root_priority(sample: pathlib.Path, tmpdir: pathlib.Path) -> None:
    """资源解析必须**先顺着这个 efx 自己的位置**往上找 natives/，而不是走资产库语料目录。"""
    print("[2] 搜索根的来源和优先级")

    # 造一棵和语料无关的 natives 树：<tmp>/mymod/natives/STM/Art/VFX/UVS/Common/<真 uvs>
    rel = "Art/VFX/UVS/Common/11_cm_glow_900.uvs"
    mod_root = tmpdir / "mymod"
    planted = mod_root.joinpath("natives", "STM", *rel.split("/"))
    planted = planted.with_name(planted.name + ".8")
    planted.parent.mkdir(parents=True, exist_ok=True)
    from_corpus = asset_paths.resolve(rel)
    if from_corpus is None:
        _check(False, "语料/pak 里能解析到基准 .uvs（不然这一项没有对照物）", rel)
        return
    planted.write_bytes(pathlib.Path(from_corpus).read_bytes())

    fake_efx = mod_root.joinpath("natives", "STM", "Art", "VFX", "x.efx.5571972")
    fake_efx.parent.mkdir(parents=True, exist_ok=True)
    fake_efx.write_bytes(b"")

    roots = asset_paths.roots_from(fake_efx)
    _check(mod_root.resolve() in [r.resolve() for r in roots],
           "从 efx 路径向上回溯能找到它自己那棵 natives 树的根", str(roots[:3]))

    _check(asset_paths.search_roots(near=fake_efx)[0].resolve() == mod_root.resolve(),
           "efx 自己那棵树排在最前（语料目录只是兜底）",
           str(asset_paths.search_roots(near=fake_efx)[:2]))

    got = asset_paths.resolve(rel, near=fake_efx)
    _check(got is not None and pathlib.Path(got).resolve() == planted.resolve(),
           "resolve(near=...) 拿到的是 efx 旁边那份，不是语料/缓存那份",
           f"{got}（期望 {planted}）")

    # 反例对照组（铁律 #11）：不给 near 就该退回原来那条路——不然上面那条等于没测
    _check(pathlib.Path(asset_paths.resolve(rel)).resolve() != planted.resolve(),
           "反例对照：不给 near 时不会命中这棵临时树（说明上面那条确实是 near 起的作用）")


def check_ref_discovery(root_col, sample: pathlib.Path) -> None:
    print("[3] 引用发现 vs dump JSON")
    _check(pathlib.Path(asset_link._source_dir(root_col)).resolve() == sample.parent.resolve(),
           "导入算子记下了源文件目录，asset_link 能读到（资源解析的首选根）",
           asset_link._source_dir(root_col))

    json_meshes, json_uvs = _json_refs(sample)

    tree_meshes = {path for _a, _o, path, _m in asset_link.iter_mesh_refs(root_col)}
    tree_uvs = {path for _a, _o, path in asset_link.iter_uvs_refs(root_col)}

    _check(bool(json_uvs), "样本里确实有 UVSPath 引用（不然这一项等于没测）", str(sample))
    _check(tree_meshes == json_meshes, "mesh 引用集合和 JSON 一致",
           f"树 {sorted(tree_meshes)} vs JSON {sorted(json_meshes)}")
    _check(tree_uvs == json_uvs, "uvs 引用集合和 JSON 一致",
           f"树 {sorted(tree_uvs)} vs JSON {sorted(json_uvs)}")

    # 每条 mesh 引用都该带上材质路径（MHWs 语料 213/213 非空，见 model.MESH_PATH_KEYS）
    missing_material = [path for _a, _o, path, mat in asset_link.iter_mesh_refs(root_col)
                        if not mat]
    _check(not missing_material or not json_meshes,
           "每条 mesh 引用都带 MaterialPath", str(missing_material))

    print("[4] SequenceNo 取的是首字段（r），不是 s")
    json_seq = sorted(_json_sequence_numbers(sample))
    tree_seq = sorted(asset_link._sequence_no(attr)
                      for attr, _o, _p in asset_link.iter_uvs_refs(root_col))
    _check(tree_seq == json_seq, "SequenceNo 主值和 JSON 的首字段一致",
           f"树 {tree_seq} vs JSON {json_seq}")


def check_readonly(root_col, tmpdir: pathlib.Path) -> None:
    print("[5] 联动不碰导出字节（含反例对照组）")
    before = _export_bytes(root_col, tmpdir, "before")

    entries = io_tree.root_entries(root_col)
    if not entries:
        _check(False, "样本里有 Entry 可挂", "root_entries() 是空的")
        return
    owner = entries[0]

    # (a) 模拟"网格挂到 Entry 下面 + 归拢进网格集合"：RE Mesh Editor 不在场时用 Empty
    #     顶替——这一项测的正是"挂一个非 ~TYPE 对象、多挂一个子集合，会不会被当成 EFX 数据
    #     导出去"，和对象是不是真网格无关。
    stand_in = bpy.data.objects.new("stand_in_mesh", None)
    bpy.context.scene.collection.objects.link(stand_in)
    stand_in_col = bpy.data.collections.new("stand_in.mesh")
    bpy.context.scene.collection.children.link(stand_in_col)
    asset_link._parent_to_owner([stand_in], owner)
    asset_link._regroup([stand_in], [stand_in_col], root_col)
    _check(stand_in.parent is owner, "顶替对象确实挂上去了")

    meshes_col = asset_link._meshes_collection(root_col)
    _check(meshes_col.get("~TYPE") == model.TYPE_MESH_GROUP,
           "网格集合建在 EFX_ROOT 下、带 ~TYPE 标记", meshes_col.name)
    _check(asset_link._meshes_collection(root_col) is meshes_col,
           "再调一次拿到的是同一个集合（按 ~TYPE 找，不按名字找）")
    _check(stand_in_col.name in meshes_col.children
           and stand_in_col.name not in bpy.context.scene.collection.children,
           "导入产出的集合从场景根挪进了网格集合",
           f"{[c.name for c in meshes_col.children]}")
    _check(stand_in.name in meshes_col.objects,
           "散在场景根上的新对象也收进了网格集合")

    # (b) .uvs 联动：真的跑一遍（路径解析不到时只会攒 problems，字节判据照样有效）
    n_uvs, n_tex, problems = asset_link.link_uvs(root_col, scene=bpy.context.scene)
    print(f"        link_uvs -> {n_uvs} 个 .uvs / {n_tex} 张贴图 / {len(problems)} 条未解决")
    if problems:
        for name, ref, reason in problems[:3]:
            print(f"        · {name} <- {ref} —— {reason}")
    _check(n_uvs > 0,
           "真的把引用的 .uvs 建成了 UVS Object",
           "路径解析不到——检查资产库面板的 EFX 根目录 / asset_paths 的游戏目录设置")

    after = _export_bytes(root_col, tmpdir, "after")
    _check(before == after, "联动跑完再导出，字节与跑之前逐字节相同",
           f"{len(before)} vs {len(after)} 字节")

    # (c) 反例对照组：把顶替对象打上 attribute 标记，导出结果必须**不一样**——不变就说明
    #     上面那条字节比较根本没有牙（铁律 #11）。
    #     "不一样"包含两种：字节不同，或者干脆导不出去（多出来的那条 attribute 没有合法
    #     内容，C# 侧反序列化就会拒绝）。两种都证明这条路真的会被污染，都算通过。
    stand_in["~TYPE"] = model.TYPE_ATTRIBUTE
    stand_in.efx_attr_type = "ReeLib.Efx.Structs.Common.EFXAttributePtLife"
    try:
        poisoned = _export_bytes(root_col, tmpdir, "poisoned")
        differs, how = poisoned != before, f"{len(poisoned)} vs {len(before)} 字节"
    except Exception as ex:   # noqa: BLE001
        differs, how = True, "导出直接失败：" + str(ex).strip().split("\n")[0]
    _check(differs, f"反例对照：标成 attribute 之后导出结果确实变了（{how}）")
    del stand_in["~TYPE"]

    print("[6] UVS 挂进 EFX_ROOT 之后 root_collections() 没被挤歪")
    entries_col, actions_col = io_tree.root_collections(root_col)
    _check(entries_col.name.endswith("_Entries") and actions_col.name.endswith("_Actions"),
           "Entries/Actions 子集合还是那两个",
           f"{entries_col.name} / {actions_col.name}")
    # UVS 根现在是 Empty Object（`~TYPE` 标在它上面），包着它们的是一个纯视觉的共享集合
    # （不带 `~TYPE`）——这个 EFX 引用的全部 .uvs 应该只多出这**一个**子集合，不是每个 .uvs
    # 各一个（uvs_io.new_uvs_collection() 的整个意义就是不让它们各建各的）。按"装了 UVS
    # Object"识别这个包裹集合，不是排除法——root_col 底下还有网格联动建的 `_Meshes` 集合
    # 这类别的子集合，排除法会把它们也误算进来。
    uvs_wrapper_children = [c for c in root_col.children
                           if any(o.get("~TYPE") == uvs_model.TYPE_UVS_ROOT for o in c.objects)]
    uvs_objs = [o for c in uvs_wrapper_children for o in c.objects
               if o.get("~TYPE") == uvs_model.TYPE_UVS_ROOT]
    _check(len(uvs_wrapper_children) == (1 if n_uvs > 0 else 0),
           "建出来的 UVS Object 共享同一个包裹集合，挂在这个 EFX_ROOT 下面",
           f"{[c.name for c in uvs_wrapper_children]}")
    _check(len(uvs_objs) == n_uvs,
           "包裹集合里的 UVS Object 个数和 link_uvs() 报的一致",
           f"{len(uvs_objs)} vs {n_uvs}")



#: 带贴图覆盖的样本：`11_it13_400.efx` 的 TypeMeshV2 覆盖表里有 1 条 Texture
#: （hash 791668758 -> mdf2 的 `EmissiveMap` 槽）。换样本时这三个值要一起换。
_OVERRIDE_SAMPLE = "EffectEditor/Weapon/it13/11_it13_400.efx.5571972"


def check_property_overrides(tmpdir: pathlib.Path) -> None:
    """attribute 的 `properties` 贴图覆盖要真的换到材质节点上。

    这是"导进来的网格纯黑纯白"的正主：VFX 的 mdf2 常常是占位材质（贴图槽全是 NullWhite /
    NullBlack），真实贴图在 EFX 的覆盖表里。只导 mdf2 不管覆盖表 = 纯白/纯黑。

    RE Mesh Editor 不在场，所以材质节点由本脚本按它的命名约定（贴图节点的 `label` 就是
    mdf2 里的槽名）**现造**——这一项测的是槽位匹配和换图本身，不是它建图的过程。
    """
    print("[7] properties 的贴图覆盖应用到材质上")
    sample = _CORPUS_ROOT / pathlib.PurePosixPath(_OVERRIDE_SAMPLE)
    if not sample.is_file():
        _check(False, "带贴图覆盖的样本在", str(sample))
        return

    root_col = _import_sample(sample)
    near = asset_link._source_dir(root_col)
    target = None
    for attr, _owner, _mesh_p, mat_p in asset_link.iter_mesh_refs(root_col):
        if mat_p:
            target = (attr, mat_p)
            break
    if target is None:
        _check(False, "样本里有带 MaterialPath 的 mesh attribute")
        return
    attr_obj, material_path = target

    mdf_local = asset_paths.resolve(material_path, near=near)
    if mdf_local is None:
        _check(False, "样本的 .mdf2 能解析到（不然这一项没法测）", material_path)
        return
    slots = [e["name"] for e in mdf_catalog.candidates(str(mdf_local)) if e["kind"] == "texture"]
    _check(bool(slots), "参考材质里读出了贴图槽名", str(slots[:4]))

    # 按 RE Mesh Editor 的约定造一个材质：贴图节点的 label = mdf2 的槽名。
    # 再加一个 label 对不上的节点当**反例对照组**——它必须原样不动。
    placeholder = bpy.data.images.new("probe_placeholder", 4, 4)
    material = bpy.data.materials.new("probe_mat")
    material.use_nodes = True
    material.node_tree.nodes.clear()
    made = {}
    for slot_name in slots + ["NotASlot"]:
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.label = slot_name
        node.image = placeholder
        made[slot_name] = node
    mesh_obj = bpy.data.objects.new("probe_mesh", bpy.data.meshes.new("probe_mesh"))
    mesh_obj.data.materials.append(material)
    bpy.context.scene.collection.objects.link(mesh_obj)

    problems = []
    applied = asset_link._apply_property_overrides(
        [mesh_obj], attr_obj, mdf_local, material_path, near, problems)
    print(f"        应用了 {applied} 张；未解决 {len(problems)} 条")
    for name, ref, reason in problems[:3]:
        print(f"        · {name} <- {ref} —— {reason}")

    _check(applied > 0, "至少有一张覆盖贴图换上去了",
           "覆盖表里没有 Texture 条目，或贴图路径解析不到")
    changed = [n for n in made.values() if n.image is not placeholder]
    _check(bool(changed), "被换的节点确实指向了新图",
           str([(n.label, n.image.name if n.image else None) for n in made.values()]))
    _check(made["NotASlot"].image is placeholder,
           "反例对照：label 对不上的贴图节点没被动过")
    _check(all(n.label in slots for n in changed),
           "换掉的节点全都是 mdf2 里真实存在的槽",
           str([n.label for n in changed]))

    # 色彩空间：按**槽名**定，不是从被替换掉的占位图上抄。抄占位图是踩过的坑——mdf2 的
    # NullWhite 之类是 Non-Color 的兜底图，抄过来会让 BaseMap 少一次 sRGB->线性 解码，
    # 中间调亮 2 倍多，表现为"贴图被洗白"。反例对照组在下面。
    probe_img = bpy.data.images.new("probe_cs", 4, 4)
    probe_img.colorspace_settings.name = "Non-Color"   # 模拟占位图的色彩空间
    asset_link._apply_colorspace(probe_img, "BaseMap", "Art/VFX/x/POD042__Base000.tex")
    _check(probe_img.colorspace_settings.name == "sRGB",
           "反例对照：BaseMap 不会继承占位图的 Non-Color（换成 sRGB）",
           probe_img.colorspace_settings.name)

    for slot, path, want in (("BaseMap", "a/b_Base000.tex", "sRGB"),
                             ("AlphaMap", "a/b_alpha000.tex", "Non-Color"),
                             ("NormalMap", "a/b_NRRO.tex", "Non-Color"),
                             ("UnknownSlot", "a/b_ALBA.tex", "sRGB")):
        img = bpy.data.images.new("probe_cs_" + slot + want, 4, 4)
        asset_link._apply_colorspace(img, slot, path)
        _check(img.colorspace_settings.name == want,
               f"{slot} + {path.rsplit('/', 1)[-1]} -> {want}",
               img.colorspace_settings.name)

    # 只读不变式同样适用：换贴图不能碰导出字节
    before = _export_bytes(root_col, tmpdir, "ovr_before")
    asset_link._apply_property_overrides(
        [mesh_obj], attr_obj, mdf_local, material_path, near, [])
    _check(before == _export_bytes(root_col, tmpdir, "ovr_after"),
           "应用贴图覆盖前后导出字节一致")



def check_emissive_wiring() -> None:
    """VFX 材质的自发光接线（`_wire_emission`）。

    RE Mesh Editor 的 `newEMINode()` 只认 `Emissive_Color`/`EmissiveIntensity` 那几个拼法，
    VFX 材质用的是 `EmissiveParam`/`EmissiveIntensityParam`，所以它那条通路整条不触发、
    `Emission Strength` 留在 0——模型在视口里就是一块白。这里验我们补的那一段接得对，
    **并且不跟它抢**（它已经接过就不动）。

    节点树是现造的：这一项测的是接线本身，不需要真的跑一遍 RE Mesh Editor。
    """
    print("[8] VFX 自发光接线")

    def make_tree(with_emissive=True):
        mat = bpy.data.materials.new("probe_emi")
        mat.use_nodes = True
        tree = mat.node_tree
        tree.nodes.clear()
        tree.nodes.new("ShaderNodeBsdfPrincipled")
        if with_emissive:
            node = tree.nodes.new("ShaderNodeTexImage")
            node.label = "EmissiveMap"
            node.image = bpy.data.images.new("probe_emi_img", 4, 4)
        return tree

    tree = make_tree()
    before = len(tree.nodes)
    ok = asset_link._wire_emission(tree, (0.7, 0.84, 0.97), 2.0, 0.1)
    bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
    _check(ok and bsdf.inputs["Emission Strength"].is_linked,
           "接上了 Emission Strength")

    tint = next((n for n in tree.nodes if n.label == "EFX Emissive Tint"), None)
    _check(tint is not None
           and [round(v, 3) for v in tint.inputs["Color2"].default_value][:3] == [0.7, 0.84, 0.97],
           "自发光颜色参数进了 Tint 节点",
           str(list(tint.inputs["Color2"].default_value)) if tint else "没有 Tint 节点")
    _check(tint is not None and tint.blend_type == "MULTIPLY"
           and abs(tint.inputs["Fac"].default_value - 1.0) < 1e-6,
           "Tint 是 MULTIPLY / fac=1（同 newEMINode）")

    scale = next((n for n in tree.nodes if n.label == "EFX Emissive Strength"), None)
    _check(scale is not None and abs(scale.inputs[1].default_value - 0.2) < 1e-6,
           "强度 = 参数 × EMISSION_MULTIPLIER（2.0 × 0.1）",
           str(scale.inputs[1].default_value) if scale else "没有强度节点")
    _check(any(n.type == "CLAMP" for n in tree.nodes), "有 Clamp 挡负强度（同 newEMINode）")

    # 反例对照 1：已经接过就不许再接（RE Mesh Editor 自己接过的材质不能被我们覆盖）
    count_after_first = len(tree.nodes)
    again = asset_link._wire_emission(tree, (1.0, 0.0, 0.0), 9.0, 0.1)
    _check(again is False and len(tree.nodes) == count_after_first,
           "反例对照：Emission Strength 已有连线时不抢、也不加节点",
           f"返回 {again}，节点 {count_after_first} -> {len(tree.nodes)}")

    # 反例对照 2：没有 EmissiveMap 就什么都不做
    bare = make_tree(with_emissive=False)
    n_bare = len(bare.nodes)
    _check(asset_link._wire_emission(bare, (1, 1, 1), 1.0, 0.1) is False
           and len(bare.nodes) == n_bare,
           "反例对照：没有 EmissiveMap 节点时不动手")
    _check(before < count_after_first, "确实往树上加了节点（不然上面几条等于没测）")



def check_mask_and_parts(sample: pathlib.Path) -> None:
    """遮罩通道改接、退化 alpha 阈值拆除、`PartsStartNo` 分段筛选。"""
    print("[9] 遮罩通道 / 退化 alpha 阈值 / PartsStartNo 分段")

    def flat_image(name, rgb, alpha):
        im = bpy.data.images.new(name, 8, 8, alpha=True)
        im.pixels = [c for _ in range(64) for c in (rgb, rgb, rgb, alpha)]
        return im

    def varying_alpha_image(name):
        im = bpy.data.images.new(name, 8, 8, alpha=True)
        im.pixels = [c for i in range(64) for c in (1.0, 1.0, 1.0, (i % 8) / 7.0)]
        return im

    # --- 遮罩通道：RGB 恒定 + alpha 有变化 -> 改接 Alpha ---
    mat = bpy.data.materials.new("probe_mask")
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.label = "AlphaMap"
    bw = tree.nodes.new("ShaderNodeRGBToBW")
    tree.links.new(tex.outputs["Color"], bw.inputs[0])
    tree.links.new(bw.outputs[0], bsdf.inputs["Alpha"])
    tex.image = varying_alpha_image("probe_mask_img")
    _check(asset_link._retarget_mask_channel(tex, tex.image)
           and bool(tex.outputs["Alpha"].links),
           "RGB 恒定、遮罩在 alpha 里时改接 Alpha 输出")

    # 反例对照：RGB 有变化就不许动
    mat2 = bpy.data.materials.new("probe_mask2")
    mat2.use_nodes = True
    t2 = mat2.node_tree
    t2.nodes.clear()
    b2 = t2.nodes.new("ShaderNodeBsdfPrincipled")
    x2 = t2.nodes.new("ShaderNodeTexImage")
    x2.label = "AlphaMap"
    t2.links.new(x2.outputs["Color"], b2.inputs["Alpha"])
    im2 = bpy.data.images.new("probe_mask_img2", 8, 8, alpha=True)
    im2.pixels = [c for i in range(64) for c in ((i % 8) / 7.0,) * 3 + (1.0,)]
    x2.image = im2
    _check(asset_link._retarget_mask_channel(x2, im2) is False
           and not x2.outputs["Alpha"].links,
           "反例对照：RGB 本身有变化时不改接")

    # --- 退化 alpha 阈值：整张图都过不了 0.5 -> 拆阈值 + 转 BLEND ---
    def make_alpha_test(name, luma):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        t = m.node_tree
        t.nodes.clear()
        b = t.nodes.new("ShaderNodeBsdfPrincipled")
        x = t.nodes.new("ShaderNodeTexImage")
        x.label = "AlphaMap"
        bwn = t.nodes.new("ShaderNodeRGBToBW")
        gt = t.nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        gt.inputs[1].default_value = 0.5
        t.links.new(x.outputs["Color"], bwn.inputs[0])
        t.links.new(bwn.outputs[0], gt.inputs[0])
        t.links.new(gt.outputs[0], b.inputs["Alpha"])
        m.blend_method = "HASHED"
        x.image = flat_image(name + "_img", luma, 1.0)
        return m, x

    dim_mat, dim_tex = make_alpha_test("probe_dim", 0.1)
    changed = asset_link._soften_degenerate_alpha_test(dim_tex, dim_tex.image)
    still_gt = any(n.type == "MATH" and n.operation == "GREATER_THAN"
                   for n in dim_mat.node_tree.nodes)
    _check(changed and not still_gt and dim_mat.blend_method == "BLEND",
           "最大亮度 0.1 < 0.5：阈值被拆掉、材质转 BLEND",
           f"changed={changed} 还有阈值={still_gt} blend={dim_mat.blend_method}")
    bsdf2 = next(n for n in dim_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    _check(bsdf2.inputs["Alpha"].is_linked, "拆完之后 Alpha 仍然接着（不是断开）")

    bright_mat, bright_tex = make_alpha_test("probe_bright", 1.0)
    _check(asset_link._soften_degenerate_alpha_test(bright_tex, bright_tex.image) is False
           and any(n.type == "MATH" and n.operation == "GREATER_THAN"
                   for n in bright_mat.node_tree.nodes)
           and bright_mat.blend_method == "HASHED",
           "反例对照：贴图过得了阈值时不动 RE Mesh Editor 的硬裁剪")

    # --- PartsStartNo 分段筛选：下标是"这份 mesh 里第几段"，左闭右开 ---
    root_col = _import_sample(sample)
    attr = next((a for a, _o, _m, _mat in asset_link.iter_mesh_refs(root_col)), None)
    if attr is None:
        _check(False, "样本里有 mesh attribute 可用来测分段筛选")
        return
    span = asset_link._parts_range(attr)
    _check(span is not None and span[1] > span[0],
           "从 attribute 上读出了 [Min, Max)", str(span))
    if span is None:
        return

    # 造一份"段号不从 0 开始"的网格（拆过的 mesh 就是这样），验下标走的是序号不是段号
    made = []
    for group in (11, 12, 13, 14):
        obj = bpy.data.objects.new(f"Group_{group}_Sub_0__Probe", None)
        bpy.context.scene.collection.objects.link(obj)
        made.append((group, obj.name))
    removed = asset_link._keep_parts([bpy.data.objects[n] for _g, n in made], attr)
    survivors = sorted(g for g, n in made if n in bpy.data.objects)
    expect = sorted([11, 12, 13, 14][i] for i in range(span[0], min(span[1], 4)))
    _check(survivors == expect,
           f"PartsStartNo{span} 在段号 11~14 的网格上留下 {expect}",
           f"实得 {survivors}（删了 {removed} 个）")


def main() -> int:
    sample = _pick_sample()
    if not sample.is_file():
        raise SystemExit(f"[FATAL] 样本不存在：{sample}")
    print(f"样本：{sample}")
    blender_efx_re.register()
    try:
        check_path_helpers()
        with tempfile.TemporaryDirectory(prefix="mhws_asset_link_") as td:
            tmpdir = pathlib.Path(td)
            check_root_priority(sample, tmpdir)
            root_col = _import_sample(sample)
            check_ref_discovery(root_col, sample)
            check_readonly(root_col, tmpdir)
            check_property_overrides(tmpdir)
            check_emissive_wiring()
            check_mask_and_parts(sample)
    finally:
        blender_efx_re.unregister()

    print(("全部通过" if _FAILED == 0 else f"{_FAILED} 项失败"))
    return 1 if _FAILED else 0


if __name__ == "__main__":
    # ⚠ 必须自己兜住异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # **未捕获异常**时**退出码仍然是 0**（实测），`sys.exit(main())` 那行根本轮不到执行——
    # 净效果是"门禁崩在第一行"和"门禁全过"对调用方长得一模一样，正是静默全绿。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
