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
    category    分类 id，由 tools/gen_attribute_catalogue.py 按 **vendor 自己的源文件分组**
                （EfxTypeBillboard.cs / EfxTransform.cs / EfxPtBehavior.cs …）打上。
                不用命名空间：`Main` 一个就占 77 个、`Misc` 占 45 个，对着面板选类型的人
                毫无意义。分类文案在 i18n.py 里按 `category.<id>` 取。
    fields      dump/load 走的 JSON 键名
    fieldEnums  {字段名: 枚举类型名}。成员表在清单顶层的 `enums` 里按类型名去重存一份——
                897 个枚举字段只涉及 27 个枚举类型，逐字段展开会把清单撑大一个数量级。
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
    enums: dict[str, list] = {}
    field_enums: dict[tuple, str] = {}
    try:
        with open(_CATALOGUE_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        enums = data.get("enums") or {}
        for item in data.get("types") or []:
            for field_name, enum_name in (item.get("fieldEnums") or {}).items():
                if item.get("type"):
                    field_enums[(item["type"], field_name)] = enum_name
            by_name[item["name"]] = item
            if item.get("type"):
                by_type[item["type"]] = item
            if item.get("readable"):
                readable.append(item)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as ex:
        print(f"[MHWs EFX Editor] attribute 类型清单加载失败，新增功能不可用：{ex}")

    readable.sort(key=lambda i: i["name"])
    categories = sorted({i.get("category") or "misc" for i in readable})
    _cache = {"by_name": by_name, "by_type": by_type, "readable": readable,
              "categories": categories, "enums": enums, "field_enums": field_enums}
    return _cache


def reload_catalogue() -> None:
    global _cache, _enum_items_cache, _category_items_cache
    _cache = None
    _enum_items_cache = {}
    _category_items_cache = None


def readable_types(category: str = "ALL") -> list[dict]:
    """能新建的类型（vendor 有读写实现类的那些），按名字排序。

    按名字排就够了，不需要再把 Clip/Expression 变体单独分一类——`TypeBillboard3D` /
    `TypeBillboard3DClip` / `TypeBillboard3DExpression` 名字共享前缀，字母序下天然聚在一起。
    """
    items = _catalogue()["readable"]
    if category and category != "ALL":
        items = [i for i in items if (i.get("category") or "misc") == category]
    return items


def categories() -> list[str]:
    """清单里实际出现过的分类 id，按字母排序。"""
    return _catalogue()["categories"]


#: 不该出现在界面上的枚举成员名——**C# 侧用来强制枚举底层宽度的占位，不是游戏语义**。
#: vendor 的 `ExpressionAssignType` 有 `ForceWord = -1`（`EfxCommon.cs`），全语料
#: 9175 个文件 / 42 个类型 / 609 个字段 / 199613 个实例里**出现 0 次**；而把它放进下拉
#: 还曾经直接崩掉 Blender（有符号/无符号表示不一致，见 `model.as_int32()`）。
#: 按名字过滤而不是按值（`-1` 本身是合法取值，别的枚举可能真的用得上）。
_PLACEHOLDER_MEMBER_NAMES = frozenset({"ForceWord"})


def enum_members(attr_type_fullname: str, field_key: str) -> Optional[list]:
    """一个字段如果在 C# 侧声明成枚举，返回它的成员表 `[[值, 显示名], ...]`；否则 None。

    成员名去掉 `枚举名_` 前缀（vendor 里叫 `RotationOrder_XYZ`，面板上显示 `XYZ` 就够了，
    前缀是字段自己的标签在说的事）。

    `ForceWord` 这类**枚举宽度占位**会被剔掉（见 `_PLACEHOLDER_MEMBER_NAMES`）——
    它不是游戏语义、全语料零出现。⚠ 剔掉的只是**下拉里的选项**：如果某个文件里真的
    存着这个值，`_enum_proxy_items()` 仍然会补一条"原值"项原样保留它（铁律 #1，
    宁可拒绝也不静默改数据）。
    """
    cat = _catalogue()
    enum_name = cat["field_enums"].get((attr_type_fullname, field_key))
    if enum_name is None:
        return None
    members = cat["enums"].get(enum_name)
    if not members:
        return None
    prefix = enum_name + "_"
    out = []
    for m in members:
        name = m.get("name") or str(m.get("value"))
        short = name[len(prefix):] if name.startswith(prefix) else name
        if short in _PLACEHOLDER_MEMBER_NAMES:
            continue
        out.append([m["value"], short])
    return out


# PtBehaviorVariable.dataType（C# 侧 `PtBehaviorPropType`，见
# vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxPtBehavior.cs）——只有 11 个成员、字段已经
# 定型，反射目录（上面的 `_catalogue()`）目前只覆盖顶层 `EFXAttribute` 子类，不下探
# `PtBehaviorVariable` 这种嵌套 struct，扩展反射链路的成本明显大于硬编码这一张小表
# （2026-09-19 已和用户确认）。值不连续，跳过的数字是全语料里出现过但 vendor 没登记的
# "未知类型"（`PtBehaviorVariableDataPrefabUnknown` 兜底，见 ptbehavior_catalog.py）。
_PT_BEHAVIOR_PROP_TYPE_NAMES = {
    4: "Uint", 9: "Float", 10: "Range", 11: "Float3", 14: "Int",
    15: "Color", 16: "WstringName", 17: "Prefabpath", 18: "Enum",
    19: "Float2", 21: "Wstring2",
}


def pt_behavior_prop_type_name(value: int) -> Optional[str]:
    """`PtBehaviorVariable.dataType` 的枚举名；不在表里（vendor 未知的类型）返回 `None`，
    调用方按"未知类型"处理，不编名字。"""
    return _PT_BEHAVIOR_PROP_TYPE_NAMES.get(value)


def expression_assign_type_members() -> list:
    """`ExpressionAssignType` 的成员表（`[[值, 显示名], ...]`），供不是走通用树、而是自己
    定义 PropertyGroup 字段的场景复用（`model.EFXMaterialExpressionItem.assign_type`）——
    那边的字段在 vendor 里声明成裸 `uint`（`EFXMaterialExpression.unkn1`），不会被反射进
    `field_enums` 表，所以不能直接用 `enum_members()` 按字段查，改成随便找一个真正声明成
    `ExpressionAssignType` 的字段（`EFXAttributeTransform3DExpression.translationX`）借用
    同一张成员表——两边取值范围/含义是同一个 C# 枚举，见 docs/EXPRESSION_SEMANTICS.md 里
    `unkn1` 分布调查（全语料只出现过 0/2/3/4，没有超出这五个成员的值）。"""
    return enum_members(
        "ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DExpression", "translationX"
    ) or []


def by_name(name: str) -> Optional[dict]:
    return _catalogue()["by_name"].get(name)


def item_type_id(attr_type_fullname: str) -> Optional[int]:
    """完整 C# 类名（`Object.efx_attr_type` 存的那个）-> 文件里的 itemTypeId。查不到返回 None。"""
    item = _catalogue()["by_type"].get(attr_type_fullname)
    return item.get("itemTypeId") if item else None


def expression_assign_field_order(attr_type_fullname: str) -> list[str]:
    """一个 `IExpressionAttribute` 类型里全部 `ExpressionAssignType` 字段，按声明顺序排列——
    这个顺序就是 bit 下标（`EfxBridge bitnames` 反射时用的是同一个顺序：
    `type.GetFields(...).Where(f => f.FieldType == typeof(ExpressionAssignType))
    .OrderBy(f => f.MetadataToken)`，见 `tools/EfxBridge/Program.cs::ResolveExpressionBitNames()`）。

    只用 `fields`/`fieldEnums`（都是机械反射出来的事实：字段声明顺序、字段的 C# 类型），
    不掺 `BitNameDict` 那张人工写的"友好名字"表——`model.expression_bit_index_for_field()`
    原来是拿字段名去 `mhws_bit_names.json` 的显示名数组里找，`BitNameDict` 给某个 bit 起了
    跟字段名不一样的字符串（`particleColor` 被起名 `"GreenChColor"` 这种）时，那张数组里
    根本没有 `particleColor` 这个字符串，找不到，字段那一行就不出现 [+]（已用真实样本
    `EFXAttributeRgbCommonExpression` 复现：7 个字段因为这个原因拿不到按钮，bit 其实都在）。
    这里换成完全按声明顺序做位置匹配，不比较任何名字，绕开这整类问题。
    """
    item = _catalogue()["by_type"].get(attr_type_fullname)
    if not item:
        return []
    field_enums = item.get("fieldEnums") or {}
    return [name for name in (item.get("fields") or []) if field_enums.get(name) == "ExpressionAssignType"]


# EnumProperty 的 items 回调必须自己持有返回的元组，不能每次现造：Blender 只保存指向字符串
# 的指针、不复制内容，回调返回的临时字符串被 Python 回收后界面上就是乱码（官方文档明写的坑）。
# 按分类缓存。
_enum_items_cache: dict = {}
_category_items_cache = None


def category_items(self, context):
    """分类下拉的条目。第一项固定是"全部"。"""
    global _category_items_cache
    if _category_items_cache is None:
        from .i18n import T
        # 文案要跟着语言切换走，所以这里不能一次性缓存死；但元组本身必须被持有（见上面的坑），
        # 折中办法是缓存"这一次生成的列表"，语言切换时由 i18n 那边 tag_redraw 触发重新生成。
        _category_items_cache = [("ALL", T("category.all"), "")] + [
            (cat, T("category." + cat), "") for cat in categories()
        ]
    return _category_items_cache


def invalidate_labels() -> None:
    """语言切换后调用：分类下拉的显示文案要重算。"""
    global _category_items_cache
    _category_items_cache = None


def _cached_enum_items(category: str) -> list:
    cached = _enum_items_cache.get(category)
    if cached is None:
        # 这里不查 semantics 的中文名：items 回调在 draw 期间跑，而语言可以随时切换，
        # 缓存住就跟不上切换了。显示名统一用英文类型名（本来就是权威检索词），
        # 中文名放在选中之后的面板正文里显示。
        cached = [
            (item["name"], item["name"], f"itemTypeId {item['itemTypeId']}")
            for item in readable_types(category)
        ]
        if not cached:
            cached = [("", "（该分类下没有可新建的类型）", "")]
        _enum_items_cache[category] = cached
    return cached


def enum_items(self, context):
    """类型下拉的条目，按当前选中的分类过滤。条目形如 (name, "显示名", "tooltip")。"""
    category = getattr(context.window_manager, "efx_re_attr_category", "ALL") if context else "ALL"
    return _cached_enum_items(category)


def all_enum_items(self, context):
    """全部可新建类型的下拉条目，不看当前选中的分类——搜索弹窗
    （`efx_re.attribute_add_search`，见 structure_ops.py）要覆盖全部 ~150+ 种类型，不能被
    "浏览场景当前选中哪个分类"这个过滤状态限制住，不然用户得先猜对分类才能搜到，等于没解决
    "类型太多找不到"这个问题。"""
    return _cached_enum_items("ALL")
