"""
tools/verify_blender_version_excluded_fields.py —— 版本性排除字段隐藏门禁

背景：`blender_efx_re/field_visibility.py` 的 `VERSION_EXCLUDED_FIELDS` 收了 27 种
attribute 类型共 82 个字段——这些字段的 vendor `RszVersion`/`RszVersionExact` 版本条件
代入 `Version = EfxVersion.MHWilds` 求值恒为 False，读写代码进不去，MHWilds 文件里恒为
默认值（详见该文件顶部注释、`tools/scan_version_excluded_fields.py`）。这些字段默认在面板上
隐藏，但**必须能用"显示全部字段"开关找回来**——纯视觉排除，不是数据层面丢字段。

用法（仓库根目录下）：

    <blender> --background --factory-startup --python tools/verify_blender_version_excluded_fields.py

检查项：
1. 语料随便挑一个含 `Spawn` attribute 的文件导入，Blender 里这个 attribute 的
   `efx_fields` 确实还带着 `re4_unkn0` 这些字段（数据没丢，只是不画）。
2. 默认（`efx_re_show_all_fields=False`）画面板，`_FakeLayout` 记录的 `prop()` 调用里
   **不出现**任何 `VERSION_EXCLUDED_FIELDS["...EFXAttributeSpawn"]` 里的字段名。
3. 打开"显示全部字段"开关，同一个 attribute 再画一遍，这些字段**必须出现**——证明隐藏是
   纯视觉、开关能兜底，不是数据层面的裁剪。
4. 导出再读回，`re4_unkn0` 等字段的值和导入时一致（隐藏不影响导出字节）。

退出码：全绿 0，有失败 1。
"""

from __future__ import annotations

import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy  # noqa: E402

import blender_efx_re  # noqa: E402
from blender_efx_re import bridge, field_visibility, io_tree, operators, panels  # noqa: E402

_SPAWN_TYPE = "ReeLib.Efx.Structs.Basic.EFXAttributeSpawn"
_HIDDEN_FIELDS = field_visibility.VERSION_EXCLUDED_FIELDS[_SPAWN_TYPE]

_DEFAULT_EFX_CANDIDATES = (
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\Art\VFX\EffectEditor\Weapon\it00\11_it00_000.efx.5571972",
    r"E:\Program\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT"
    r"\natives\STM\Art\VFX\EffectEditor\Weapon\it00\11_it00_000.efx.5571972",
)
_DEFAULT_EFX = next((p for p in _DEFAULT_EFX_CANDIDATES if pathlib.Path(p).is_file()),
                    _DEFAULT_EFX_CANDIDATES[0])


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        if not ok:
            if detail:
                print("         " + detail)
            self.failures.append(label)

    def finish(self) -> None:
        if self.failures:
            print(f"\n{len(self.failures)} 项失败:")
            for f in self.failures:
                print(f"  - {f}")
            sys.exit(1)
        print("\n全部通过")
        sys.exit(0)


class _FakeLayout:
    """无头 Blender 没有区域可以真画面板，用它把 draw 跑一遍：记录每次 prop() 绑定的
    node.key，用来断言"这个字段到底有没有被画出来"。照抄 verify_blender_ptbehavior_property.py
    的写法。"""

    def __init__(self, log: list, enabled: bool = True) -> None:
        self.log = log
        self.enabled = enabled

    def _child(self, *args, **kwargs):
        return _FakeLayout(self.log, self.enabled)

    row = column = split = box = _child

    def prop(self, data, prop_name, **kwargs):
        self.log.append(("prop", getattr(data, "key", ""), prop_name))

    def label(self, **kwargs):
        self.log.append(("label", kwargs.get("text", "")))

    def operator(self, idname, **kwargs):
        self.log.append(("operator", idname))
        return type("Op", (), {})()

    def prop_search(self, data, prop_name, *a, **kwargs):
        self.log.append(("prop_search", getattr(data, "key", ""), prop_name))

    def __getattr__(self, name):
        return self._child


def _find_spawn_attribute():
    for obj in bpy.data.objects:
        if getattr(obj, "efx_attr_type", "") == _SPAWN_TYPE:
            return obj
    return None


def main() -> None:
    report = Report()

    if not pathlib.Path(_DEFAULT_EFX).is_file():
        print(f"[FATAL] 样本文件不存在: {_DEFAULT_EFX}")
        sys.exit(1)

    blender_efx_re.register()
    getattr(bpy.ops.efx_re, "import")(filepath=_DEFAULT_EFX)

    obj = _find_spawn_attribute()
    if obj is None:
        print("[FATAL] 样本里没有 Spawn attribute，样本覆盖不到测试目标")
        sys.exit(1)

    field_keys = {n.key for n in obj.efx_fields}
    missing = _HIDDEN_FIELDS - field_keys
    report.check("Spawn 的版本性排除字段仍在数据模型里（没被裁掉）",
                 not missing, f"缺失: {missing}")

    scene = bpy.context.scene
    scene.efx_re_show_all_fields = False
    log_default: list = []
    panels._draw_fields_content(_FakeLayout(log_default), bpy.context, obj)
    drawn_default = {e[1] for e in log_default if e[0] in ("prop", "prop_search", "label")}
    leaked = _HIDDEN_FIELDS & drawn_default
    report.check("默认（不显示全部字段）时，版本性排除字段一个都没画出来",
                 not leaked, f"泄露: {leaked}")
    report.check("默认状态下'显示全部字段'开关确实画出来了（has_rules 生效）",
                 any(e[0] == "prop" and e[2] == "efx_re_show_all_fields" for e in log_default))

    scene.efx_re_show_all_fields = True
    log_all: list = []
    panels._draw_fields_content(_FakeLayout(log_all), bpy.context, obj)
    drawn_all = {e[1] for e in log_all if e[0] in ("prop", "prop_search", "label")}
    recovered = _HIDDEN_FIELDS & drawn_all
    report.check("打开'显示全部字段'后，版本性排除字段能找回来（纯视觉排除，非数据裁剪）",
                 recovered == _HIDDEN_FIELDS, f"仍缺失: {_HIDDEN_FIELDS - recovered}")
    scene.efx_re_show_all_fields = False

    # ---- 导出/读回，确认隐藏不影响字节 -------------------------------------
    def _snapshot(n):
        """把 EFXValueNode 摘成可比较的原生值，OBJECT 类型递归成 {子键: 值} 的字典。"""
        if n.data_type == "OBJECT":
            return {c.key: _snapshot(c) for c in n.children}
        if n.data_type == "BOOL":
            return bool(n.bool_value)
        if n.data_type == "FLOAT":
            return float(n.float_value)
        if n.data_type == "STRING":
            return n.string_value
        if n.data_type == "NULL":
            return None
        return int(n.int_value)

    before_values = {n.key: _snapshot(n) for n in obj.efx_fields if n.key in _HIDDEN_FIELDS}

    root_col = io_tree.find_root(obj)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out_path = pathlib.Path(tmp) / "roundtrip.efx"
        data = io_tree.export_root_to_efxfile(root_col)
        resolved, notice, fatal = operators._ensure_version_suffix(str(out_path), data)
        report.check("导出拿到合法版本号后缀", not fatal, notice or "")
        if not fatal:
            bridge.load_efx(data, resolved)
            dumped = bridge.dump_efx(pathlib.Path(resolved))
            spawn_json = None
            for entry in (dumped.get("Entries") or []) + []:
                for attr in entry.get("Attributes") or []:
                    if attr.get("$type", "").split(",")[0] == _SPAWN_TYPE:
                        spawn_json = attr
                        break
                if spawn_json:
                    break
            if spawn_json is None:
                # 也可能在 Actions 里
                for act in dumped.get("Actions") or []:
                    for attr in act.get("Attributes") or []:
                        if attr.get("$type", "").split(",")[0] == _SPAWN_TYPE:
                            spawn_json = attr
                            break
                    if spawn_json:
                        break
            report.check("读回的文件里还能找到 Spawn attribute", spawn_json is not None)
            def _matches(expected, actual) -> bool:
                if isinstance(expected, dict):
                    return isinstance(actual, dict) and all(
                        _matches(v, actual.get(k)) for k, v in expected.items())
                if isinstance(expected, bool):
                    return bool(actual) == expected
                if isinstance(expected, float):
                    try:
                        return abs(float(actual) - expected) < 1e-6
                    except (TypeError, ValueError):
                        return False
                return actual == expected

            if spawn_json is not None:
                mismatches = []
                for key, expected in before_values.items():
                    if key not in spawn_json:
                        mismatches.append(f"{key}: 读回缺失该字段")
                        continue
                    if not _matches(expected, spawn_json[key]):
                        mismatches.append(f"{key}: 导入时={expected!r} 读回={spawn_json[key]!r}")
                report.check("隐藏字段导出/读回后值不变（隐藏只影响绘制，不影响导出）",
                             not mismatches, "; ".join(mismatches))

    report.finish()


if __name__ == "__main__":
    # ⚠ 必须自己捕获异常再 sys.exit(1)：`blender --background --python x.py` 在脚本抛出
    # **未捕获异常**时**退出码仍然是 0**（实测），下面那行根本轮不到执行——净效果是
    # "门禁崩在第一行"和"门禁全过"对调用方长得一模一样，正是静默全绿。
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.exit(1)
