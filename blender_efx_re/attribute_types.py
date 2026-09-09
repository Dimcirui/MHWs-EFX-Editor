"""
blender_efx_re/attribute_types.py —— MHWs 全部 attribute 类型的清单

数据来自 `dotnet tools/EfxBridge/bin/Debug/net8.0/EfxBridge.dll types
blender_efx_re/semantics/mhws_attribute_types.json`，随仓库分发。

**为什么固化成文件而不是现问 EfxBridge**：类型清单要喂给 `EnumProperty` 的 items 回调，
而 items 回调是在**面板 draw 期间**被调用的——那里绝不能起子进程（每帧一次 dotnet 启动，
界面会直接卡死）。vendor 升级后重新生成一次即可。

清单里每项：
    itemTypeId  文件里那个整数。**决定 attribute 在 entry 内的排列顺序**——
                `EFXEntry.DoRead` 有 `typeId < lastAttributeTypeId` 的断言，而
                `DoWrite` 只是按列表顺序写、不会替我们排（`ReorderEntries()` 存在但没人调），
                所以新增时得自己插到正确位置，见 structure_ops.sorted_insert_index()。
    name        EfxAttributeType 枚举名，`new attribute <name>` 用这个
    type        完整 C# 类名，等于 dump 出来的 `$type`，也是 Object.efx_attr_type 存的值
    readable    false = vendor 只登记了 id→枚举名、没有读写实现类（KNOWN_UPSTREAM_ISSUES #4），
                这类既解析不了也新建不了，选择器里直接不列出来
    fields      dump/load 走的 JSON 键名
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_CATALOGUE_JSON = Path(__file__).resolve().parent / "semantics" / "mhws_attribute_types.json"

_cache: Optional[dict] = None


def _catalogue() -> dict:
    """{"by_name": {...}, "by_type": {...}, "readable": [...]}，加载失败时是空表。

    防御式加载：清单只影响"能不能新增"，坏文件不该拖垮导入/导出这些真正的 IO 路径。
    """
    global _cache
    if _cache is not None:
        return _cache

    by_name: dict[str, dict] = {}
    by_type: dict[str, dict] = {}
    readable: list[dict] = []
    try:
        with open(_CATALOGUE_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("types") or []:
            by_name[item["name"]] = item
            if item.get("type"):
                by_type[item["type"]] = item
            if item.get("readable"):
                readable.append(item)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as ex:
        print(f"[MHWs EFX Editor] attribute 类型清单加载失败，新增功能不可用：{ex}")

    readable.sort(key=lambda i: i["name"])
    _cache = {"by_name": by_name, "by_type": by_type, "readable": readable}
    return _cache


def reload_catalogue() -> None:
    global _cache
    _cache = None


def readable_types() -> list[dict]:
    """能新建的类型（vendor 有读写实现类的那些），按名字排序。"""
    return _catalogue()["readable"]


def by_name(name: str) -> Optional[dict]:
    return _catalogue()["by_name"].get(name)


def item_type_id(attr_type_fullname: str) -> Optional[int]:
    """完整 C# 类名（`Object.efx_attr_type` 存的那个）-> 文件里的 itemTypeId。查不到返回 None。"""
    item = _catalogue()["by_type"].get(attr_type_fullname)
    return item.get("itemTypeId") if item else None


# EnumProperty 的 items 回调必须自己持有返回的元组，不能每次现造：Blender 只保存指向字符串
# 的指针、不复制内容，回调返回的临时字符串被 Python 回收后界面上就是乱码（官方文档明写的坑）。
_enum_items_cache: Optional[list] = None


def enum_items(self, context):
    """给"新增 Attribute"的类型下拉用。条目形如 (name, "显示名", "tooltip")。"""
    global _enum_items_cache
    if _enum_items_cache is None:
        # 这里不查 semantics 的中文名：items 回调在 draw 期间跑，而语言可以随时切换，
        # 缓存住就跟不上切换了。显示名统一用英文类型名（本来就是权威检索词），
        # 中文名放在选中之后的面板正文里显示。
        _enum_items_cache = [
            (item["name"], item["name"], f"itemTypeId {item['itemTypeId']}")
            for item in readable_types()
        ]
        if not _enum_items_cache:
            _enum_items_cache = [("", "（类型清单未加载）", "")]
    return _enum_items_cache
