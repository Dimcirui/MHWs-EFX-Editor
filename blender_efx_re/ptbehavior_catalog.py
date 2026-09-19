"""
blender_efx_re/ptbehavior_catalog.py —— PtBehavior 属性候选目录加载器

`EFXAttributePtBehavior.properties` 是按 `behaviorString`（游戏原生类名）分组的稀疏覆盖表，
和 `EFXAttributeTypeMeshV2.properties`（见 mdf_catalog.py）同属"能加哪些字段只有外部权威源
知道"的情况，但权威源不同：mdf_catalog 现查一个用户指定的 `.mdf2` 文件；这里没有外部文件可查，
只能靠离线全语料扫描固化成静态目录（`tools/gen_ptbehavior_catalog.py` 生成，见该脚本文档），
运行时只读加载，不再现查。

只收录了属性顺序在全语料里全局一致的 behaviorString（`_excluded` 里记着被排除的类和原因，
不在这里暴露给调用方——调用方只需要知道"这个类能不能加"）。每条候选自带一份从语料里真实
捕获的完整 `PtBehaviorVariable` 模板：新增时整个克隆，不手工拼字段——`varSize` 等字段没有
`[RszByteSizeField]`/`[RszArraySizeField]` 标注，不会被 vendor 自愈，猜字节布局的风险比
克隆真实样本大得多。

`defaults[behaviorString]`（`default_instance()`）是另一张表：每个类在全语料里出现次数
最多的那一套字段组合，取自**同一个真实实例**——不是把 `behaviors[cls]` 里各字段各自
"第一次见到"的模板拼起来的大杂烩。新建/改写 `behaviorString` 时用它当自动填充的默认字段块
（见 `model._apply_ptbehavior_default()`），不是把候选目录全部塞进去。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_CATALOG_JSON = Path(__file__).resolve().parent / "semantics" / "mhws_ptbehavior_catalog.json"

_cache: Optional[dict] = None


def _load() -> dict:
    """返回 `{"behaviors": {...}, "_excluded": [...]}`；加载失败返回两个键都是空的字典/列表。"""
    global _cache
    if _cache is not None:
        return _cache
    empty = {"behaviors": {}, "defaults": {}, "_excluded": []}
    if not _CATALOG_JSON.exists():
        _cache = empty
        return _cache
    try:
        with open(_CATALOG_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as ex:
        # 防御式加载，对齐 semantics/__init__.py::_load_table()：坏文件只警告跳过，
        # 不向上抛——这张表只影响"能不能加候选"这个编辑期功能，不该拖垮导入导出。
        print(f"[MHWs EFX Editor] PtBehavior 候选目录加载失败，跳过：{_CATALOG_JSON} ({ex})")
        _cache = empty
        return _cache
    behaviors = data.get("behaviors")
    defaults = data.get("defaults")
    excluded = data.get("_excluded")
    _cache = {
        "behaviors": behaviors if isinstance(behaviors, dict) else {},
        "defaults": defaults if isinstance(defaults, dict) else {},
        "_excluded": excluded if isinstance(excluded, list) else [],
    }
    return _cache


def has_catalog(behavior_string: str) -> bool:
    """这个 behaviorString 有没有收录进候选目录（能不能加/删属性）。"""
    return bool(behavior_string) and behavior_string in _load()["behaviors"]


def candidates(behavior_string: str) -> list[dict]:
    """返回 `[{"name": ..., "template": {...}}, ...]`，按规范顺序排列；没收录返回空列表。"""
    return _load()["behaviors"].get(behavior_string) or []


def default_instance(behavior_string: str) -> list[dict]:
    """这个类在全语料里出现次数最多的那一套字段组合，`[{"name": ..., "template": {...}}, ...]`，
    按那个真实实例本身的字段顺序排列；没收录、或这个类的众数用法就是"什么都不覆盖"，
    返回空列表——空列表本身就是真实结论，不代表"数据缺失"。"""
    return _load()["defaults"].get(behavior_string) or []


def known_behavior_strings() -> list[tuple[str, bool]]:
    """全语料扫描见过的全部 `behaviorString`，含被排除的那几个（结构混杂、没有候选目录，
    但已经是别人真实文件里合法出现过的值，选字段时应该看得到，不能假装不存在）。

    返回 `[(behaviorString, 有没有候选目录), ...]`，按名字排序。给"从已知列表选"的搜索
    弹窗用——列出的是"语料里真实见过的类名"，不是"能加候选属性的类名"，两者不一样：
    没有候选目录的类照样能被合法引用，只是不提供增删入口（继续走通用树透传）。
    """
    data = _load()
    names = {name: True for name in data["behaviors"]}
    for item in data["_excluded"]:
        name = item.get("behaviorString") if isinstance(item, dict) else None
        if name:
            names.setdefault(name, False)
    return sorted(names.items())
