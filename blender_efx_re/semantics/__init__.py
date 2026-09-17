"""
blender_efx_re/semantics/__init__.py —— 字段语义知识表加载器

设计背景见 PLAN.md 里"字段语义知识表"相关的前瞻性备注，参照姊妹项目 EFX-Editor 的"语义知识
解耦"设计（该仓库 PROGRESS.md），但只搬运其中的 A 层（纯展示：label/tooltip/confidence，
改错零风险）——本项目目前没有 EFX-Editor 那种按类型拍平的 `structs.py` schema，字段树是通用
递归的 `EFXValueNode`（见 model.py），知识表只在"attribute `$type` + 顶层内容字段 key"这一级
生效，不索引更深的子字段（Vector 类型的 x/y/z 这类子字段名字本身已经够自解释）。

按 PLAN.md 的约定，顶层带 `"game": "MHWS"` 命名空间，为将来这套设计如果被姊妹项目复用、需要
按游戏区分表内容时留口子。

三层存储（层数不可省，EFX-Editor 那边的教训：标注文件如果和插件代码放一起，插件升级时会被
整体覆盖，测试者填的东西就没了）：
1. 机器挖掘表：`semantics/mhws_field_labels_mined.json`，由 `tools/mine_btx_semantics.py`
   从 010 Editor 模板（MHWs-EFX-Template）自动生成，**整份可以随时重跑覆盖**，所以优先级最低。
2. 出厂手写表：随本仓库分发，只读，`semantics/mhws_field_labels.json`。手写的东西单独放一个
   文件，就是为了让"重跑挖掘"这个动作永远碰不到它。
3. 用户个人标注表：Blender 用户配置目录下的独立文件，不随插件更新变化（面板内"填写此字段
   含义"弹窗尚未实现，这里先留加载器和合并逻辑，弹窗/导出按钮是后续工作）。

三表按 (attr_type, field_key) 逐条合并，后加载的覆盖先加载的（用户 > 手写 > 机器挖）；查不到
时退到 global_fields（跨类型通用词，键仅为 field_key，当前出厂表里是空的，留着给以后 accel
这类通用字段用）。

除了字段级标注，表里还有一层 `types`：attribute 类型自身的中文名（"透明度校正" 这种），
见 get_type_entry()。

加载防御式：坏文件/坏格式只跳过、绝不向上抛异常——这张表只影响面板展示文字，不该拖垮
导入/导出这些真正的 IO 路径。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Optional

import bpy

_MINED_JSON = Path(__file__).resolve().parent / "mhws_field_labels_mined.json"
_HASHES_JSON = Path(__file__).resolve().parent / "mhws_name_hashes.json"
_FACTORY_JSON = Path(__file__).resolve().parent / "mhws_field_labels.json"
_ATTR_DEFAULTS_JSON = Path(__file__).resolve().parent / "mhws_attribute_defaults.json"
_BIT_NAMES_JSON = Path(__file__).resolve().parent / "mhws_bit_names.json"


def _user_json_path() -> Path:
    """用户个人标注文件路径：Blender 用户配置目录下，不随插件更新覆盖。"""
    return Path(bpy.utils.user_resource("CONFIG")) / "mhws_efx_editor_field_labels.json"


def _load_table(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as ex:
        print(f"[MHWs EFX Editor] 字段知识表加载失败，跳过：{path} ({ex})")
        return {}
    if not isinstance(data, dict) or data.get("game") != "MHWS":
        print(f"[MHWs EFX Editor] 字段知识表格式不对（缺顶层 \"game\": \"MHWS\"），跳过：{path}")
        return {}
    return data


_cache: Optional[dict] = None


def _merged_table() -> dict:
    global _cache
    if _cache is not None:
        return _cache

    # 顺序即优先级：后面的覆盖前面的
    sources = (_load_table(_MINED_JSON), _load_table(_FACTORY_JSON), _load_table(_user_json_path()))

    merged_fields: dict = {}
    merged_global: dict = {}
    merged_types: dict = {}
    for source in sources:
        for type_name, field_map in (source.get("fields") or {}).items():
            merged_fields.setdefault(type_name, {}).update(field_map)
        merged_global.update(source.get("global_fields") or {})
        merged_types.update(source.get("types") or {})

    _cache = {"fields": merged_fields, "global_fields": merged_global, "types": merged_types}
    return _cache


_hash_cache: Optional[dict] = None


def _hash_table() -> dict:
    """MurMur3(UTF-8) 名字哈希 -> 原名。由 tools/mine_btx_hashes.py 生成，每条都复算验证过。"""
    global _hash_cache
    if _hash_cache is None:
        data = _load_table(_HASHES_JSON)
        _hash_cache = data.get("hashes") or {}
    return _hash_cache


def lookup_name_hash(value: int) -> Optional[str]:
    """一个 uint32 如果是某个已知名字的 MurMur3(UTF-8) 哈希，返回那个名字，否则 None。

    RE Engine 到处用这种哈希代替字符串存名字（材质属性名、贴图槽名、Expression 参数名），
    落到 JSON 里全是裸数字。表里每一条都是复算验证过的**事实**（名字算出来就等于这个数），
    不是推测，所以不需要限定"只在某某字段上查"——能命中就说明确实是那个名字，误命中要求
    32 位碰撞（约 1500/2^32）。
    """
    return _hash_table().get(str(value))


_attr_defaults_cache: Optional[dict] = None


def _attr_defaults_table() -> dict:
    global _attr_defaults_cache
    if _attr_defaults_cache is None:
        data = _load_table(_ATTR_DEFAULTS_JSON)
        _attr_defaults_cache = data.get("defaults") or {}
    return _attr_defaults_cache


def get_attribute_defaults(type_name: str) -> Optional[dict]:
    """查一个 EfxAttributeType 枚举短名（`bridge.new_attribute()` 用的那个名字）对应的
    "建议默认值"——语料众数统计出来的，只覆盖置信度够高的字段，见 tools/build_attr_defaults.py。
    查不到返回 None（这批分析目前只覆盖了语料里最常见的 40 种类型，见 tools/typefreq_report.json）。

    返回的是深拷贝：调用方（`structure_ops.add_attribute()`）要把这份默认值原地合并进
    `bridge.new_attribute()` 吐出来的结构里，不能直接改到缓存的字典上，否则下一次新建同类型
    attribute 会读到被前一次调用改坏的表。
    """
    entry = _attr_defaults_table().get(type_name)
    return copy.deepcopy(entry) if entry is not None else None


_bit_names_cache: Optional[dict] = None


def _bit_names_table() -> dict:
    global _bit_names_cache
    if _bit_names_cache is None:
        data = _load_table(_BIT_NAMES_JSON)
        _bit_names_cache = {
            "expressionAttributes": data.get("expressionAttributes") or {},
            "clipAttributes": data.get("clipAttributes") or {},
        }
    return _bit_names_cache


def get_expression_bit_names(attr_type: str) -> Optional[list]:
    """查一个 `IExpressionAttribute` 的 `$type`（完整 C# 类名）对应的 bit_index -> 字段名表
    （0-based，`None` 表示这一位 vendor 自己也没起名字）。由 `EfxBridge bitnames` 反射生成
    （见该命令说明），不是手工维护——vendor 升级后重跑该命令覆盖 `mhws_bit_names.json` 即可。
    查不到这个类型整条（没实现 `IExpressionAttribute`，或表还没重新生成过）返回 `None`。"""
    return _bit_names_table()["expressionAttributes"].get(attr_type)


def get_clip_bit_names(attr_type: str) -> Optional[list]:
    """同 `get_expression_bit_names()`，查 `IClipAttribute`。Clip 的曲线数据没有 per-bit
    具名字段，绝大多数类型这里整条全是 `None`——如实反映 vendor 源码里确实没给这些 bit
    起过名字，不是我们没查到（见 `EfxBridge bitnames` 命令说明）。"""
    return _bit_names_table()["clipAttributes"].get(attr_type)


def reload_tables() -> None:
    """清空缓存，下次查询时重新读盘。插件 register() 时调用一次，供未来"Reload semantics"
    operator 复用。"""
    global _cache, _hash_cache, _attr_defaults_cache, _bit_names_cache
    _cache = None
    _hash_cache = None
    _attr_defaults_cache = None
    _bit_names_cache = None


def get_field_entry(attr_type: str, field_key: str) -> Optional[dict]:
    """查一个 (attribute $type, 顶层内容字段 key) 对应的知识表条目；查不到返回 None。"""
    table = _merged_table()
    by_type = table["fields"].get(attr_type)
    if by_type and field_key in by_type:
        return by_type[field_key]
    return table["global_fields"].get(field_key)


def get_type_entry(attr_type: str) -> Optional[dict]:
    """查一个 attribute 类型自身的标注（目前只有 `label_zh`，如 "透明度校正"）；查不到返回 None。

    面板上用它给类型名配一个中文名，光看 `EmitterShape3D` 这种英文类型名对不熟 RE Engine 的
    使用者不够友好。英文侧没有对应字段时由调用方回退到类型短名本身（那本来就是英文）。
    """
    return _merged_table()["types"].get(attr_type)


def is_angle_radians_field(entry: Optional[dict]) -> bool:
    """知识表 `unit == "angle_radians"`——**不看**"角度显示"开关，这是文件格式/引擎行为
    本身的事实（这个字段的浮点存储是弧度），跟"编辑器要不要按度显示"是两件事。

    `sim_preview.collect_expressions()` 用这条（不是 `wants_degrees()`）来判断一条
    Expression 曲线的目标字段是不是角度、从而要不要把公式结果从度转成弧度——全语料实测
    `Transform3DExpression` 真正绑定过公式的 560 条 rotationX/Y/Z 曲线里，227 个"和公式
    根节点同单位"的字面量常量 0 个落在弧度制常见值（π 的有理数倍）附近，172/202 超过
    2π，众数是 360/10/5/30——**公式里的字面量按度写，是引擎/文件格式层面的事实，不是
    用户界面的显示偏好**，不能被 `Scene.efx_re_angle_degrees` 这个纯 UI 开关左右
    （开关关着的时候，公式结果一样要转换，只是编辑器不把常量槽位显示成度而已）。"""
    return entry is not None and entry.get("unit") == "angle_radians"


def wants_degrees(entry: Optional[dict]) -> bool:
    """`is_angle_radians_field()` + `Scene.efx_re_angle_degrees` 开关同时命中，才把这个
    弧度制角度字段改按度显示/输入（底层仍存弧度）——纯 UI 层的显示/编辑便利。

    原本只有 `panels.py` 一处用（静态字段），`expr_edit.py` 的 Expression 公式常量槽位
    要复用同一条判据（同一个字段，只是这次驱动它的是一段公式而不是一个静态值，"这个字段
    是不是角度"这件事不应该因为驱动方式变了就有两套读法）——放在这个模块避免
    `expr_edit.py` <-> `panels.py` 之间产生循环 import（`panels.py` 已经 import
    `expr_edit`）。"""
    return (
        is_angle_radians_field(entry)
        and getattr(bpy.context.scene, "efx_re_angle_degrees", False)
    )
