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

import json
from pathlib import Path
from typing import Optional

import bpy

_MINED_JSON = Path(__file__).resolve().parent / "mhws_field_labels_mined.json"
_FACTORY_JSON = Path(__file__).resolve().parent / "mhws_field_labels.json"


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


def reload_tables() -> None:
    """清空缓存，下次查询时重新读盘。插件 register() 时调用一次，供未来"Reload semantics"
    operator 复用。"""
    global _cache
    _cache = None


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
