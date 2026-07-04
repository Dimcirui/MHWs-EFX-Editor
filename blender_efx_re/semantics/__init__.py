"""
blender_efx_re/semantics/__init__.py —— 字段语义知识表加载器

设计背景见 PLAN.md 里"字段语义知识表"相关的前瞻性备注，参照姊妹项目 EFX-Editor 的"语义知识
解耦"设计（该仓库 PROGRESS.md），但只搬运其中的 A 层（纯展示：label/tooltip/confidence，
改错零风险）——本项目目前没有 EFX-Editor 那种按类型拍平的 `structs.py` schema，字段树是通用
递归的 `EFXValueNode`（见 model.py），知识表只在"attribute `$type` + 顶层内容字段 key"这一级
生效，不索引更深的子字段（Vector 类型的 x/y/z 这类子字段名字本身已经够自解释）。

按 PLAN.md 的约定，顶层带 `"game": "MHWS"` 命名空间，为将来这套设计如果被姊妹项目复用、需要
按游戏区分表内容时留口子。

两层存储（不可省，EFX-Editor 那边的教训：标注文件如果和插件代码放一起，插件升级时会被整体
覆盖，测试者填的东西就没了）：
1. 出厂默认表：随本仓库分发，只读，`semantics/mhws_field_labels.json`。
2. 用户个人标注表：Blender 用户配置目录下的独立文件，不随插件更新变化（面板内"填写此字段
   含义"弹窗尚未实现，这里先留加载器和合并逻辑，弹窗/导出按钮是后续工作）。

两表按 (attr_type, field_key) 合并，用户表优先；查不到时退到 global_fields（跨类型通用词，
键仅为 field_key，当前出厂表里是空的，留着给以后 accel 这类通用字段用）。

加载防御式：坏文件/坏格式只跳过、绝不向上抛异常——这张表只影响面板展示文字，不该拖垮
导入/导出这些真正的 IO 路径。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import bpy

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

    factory = _load_table(_FACTORY_JSON)
    user = _load_table(_user_json_path())

    merged_fields: dict = {}
    for source in (factory, user):
        for type_name, field_map in (source.get("fields") or {}).items():
            merged_fields.setdefault(type_name, {}).update(field_map)

    merged_global: dict = {}
    for source in (factory, user):
        merged_global.update(source.get("global_fields") or {})

    _cache = {"fields": merged_fields, "global_fields": merged_global}
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
