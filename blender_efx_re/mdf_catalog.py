"""
blender_efx_re/mdf_catalog.py —— 从一个参考 .mdf2 读出"这个 attribute 能覆盖哪些参数"

`EFXAttributeTypeMeshV2.properties`（`MdfProperty` 数组，vendor `EfxCommon.cs:27`）是一张
**稀疏覆盖表**：attribute 自己不定义参数，只记录"我把所引用材质的第几号参数改成了什么"。所以
"能加哪些 property"这个问题的唯一权威答案在 `.mdf2` 里，EFX 侧一点线索都没有——这也是为什么
这个功能整个挂在"先导入一个参考 mdf2"上，而不是一个全局设置：没有 mdf2 就没有可信答案。

四个字段和 mdf2 的对应关系（2026-09-10 用 `11_it13_400.efx.5571972` 引用的
`Art/VFX/Mesh/PL/Equip/11_ch00_069_0006.mdf2` 逐条比对，13/13 全中）：

- `mdfPropertyIndex` = 参数在 mdf2 参数表里的**下标**（贴图类型恒为 -1，vendor
  `MdfProperty.DoWrite()` 强制写死）
- `mdfParameterValueCount` = mdf2 的 `componentCount`
- `parameterType` = `componentCount == 4` 时 `Float`（整包 float4/颜色），`== 1` 时 `Range`
- `PropertyNameUTF8Hash` = 参数名的 **UTF-8** MurMur3 哈希。mdf2 自己存的是 UTF-16 和 ASCII
  两种哈希，和 EFX 用的这个对不上，所以由 `mdfdump` 子命令按参数名现算一份 UTF-8 的带出来

`value` 的初值形状（同日全语料抽样 70 个文件 / 603 个实例统计）：`Range` 是
`(0, 0, min, max)`——320/346 是 `min == max`，其余也全部满足 `X = Y = 0`；`Float` 直接就是
mdf2 里那个 float4；`Texture` 的 `uknInt` 恒为 1、`_padding` 恒为 0（96/96），`pathLength`/
`textureIndex` 由 vendor 写出时重算，不用管。

参考 mdf2 存在 attribute 对象自己身上（`Object.efx_mdf_reference`，见 model.py），不是全局
设置——不同 mesh attribute 引用的是不同材质，一个全局路径服务不了它们。这个属性不参与导出
（`io_tree.export_attribute_object()` 只读 `efx_fields` 那几样），只是编辑期状态。
"""

from __future__ import annotations

import os

from . import bridge

# 解析一次要跑一个 EfxBridge 子进程，而候选列表每打开一次下拉就要查一遍，按文件路径 +
# 修改时间缓存（改了文件重新解析，不用手动清）。
_cache: dict[tuple[str, float], dict] = {}


class CatalogError(RuntimeError):
    """材质解析失败——文件不在、读不出来、或者形状超出已验证范围。

    一律向上抛、由算子转成 `{"ERROR"}`：拿不到材质就说明填不出可靠的 `mdfPropertyIndex`，
    这种情况必须拒绝而不是猜一个下标（猜错等于静默改到另一个参数上，铁律 #2/#7）。
    """


def clear_cache() -> None:
    _cache.clear()


def load(mdf_path: str) -> dict:
    """读一个参考 .mdf2，返回 `mdfdump` 的 payload。读不了/形状不对就抛 `CatalogError`。"""
    mdf_path = (mdf_path or "").strip()
    if not mdf_path:
        raise CatalogError("还没有导入参考 .mdf2")
    if not os.path.isfile(mdf_path):
        raise CatalogError(f"参考 .mdf2 不在了：{mdf_path}")

    key = (mdf_path, os.path.getmtime(mdf_path))
    if key in _cache:
        return _cache[key]

    try:
        payload = bridge.dump_mdf(mdf_path)
    except bridge.BridgeError as ex:
        first_line = str(ex).strip().split("\n")[0]
        raise CatalogError(f"读参考 .mdf2 失败：{first_line}") from ex

    materials = payload.get("materials") or []
    if not materials:
        raise CatalogError(f"这个 .mdf2 里一个材质都没有：{os.path.basename(mdf_path)}")
    if len(materials) > 1:
        # EFX 侧只有一个 MaterialPath、一份 properties，`mdfPropertyIndex` 里也没有"用第几个
        # 材质"这一维——多材质的 mdf2 该按哪张参数表算下标是未知的，已核对过的真实引用全都是
        # 单材质。宁可拒绝也不猜（铁律 #2/#7）。
        raise CatalogError(
            f"这个 .mdf2 里有 {len(materials)} 个材质，而 attribute 只有一个 MaterialPath，"
            "下标该按哪张参数表算无法确定，拒绝猜"
        )

    _cache[key] = payload
    return payload


def candidates(mdf_path: str) -> list[dict]:
    """参考材质里全部可覆盖项，统一成一种形状：

        {"kind": "param"|"texture", "name", "utf8Hash", "index", "componentCount", "value", "path"}

    参数在前、贴图槽在后，各自保持 mdf2 里的原始顺序（`index` 就是那个顺序，不能重排后再取）。
    """
    material = load(mdf_path)["materials"][0]
    entries = []
    for param in material.get("parameters") or []:
        entries.append({
            "kind": "param",
            "name": param["name"],
            "utf8Hash": int(param["utf8Hash"]),
            "index": int(param["index"]),
            "componentCount": int(param["componentCount"]),
            "value": param.get("value") or {},
        })
    for tex in material.get("textures") or []:
        entries.append({
            "kind": "texture",
            "name": tex["name"],
            "utf8Hash": int(tex["utf8Hash"]),
            "index": -1,
            "componentCount": 1,
            "path": tex.get("path") or "",
        })
    return entries


def material_name(mdf_path: str) -> str:
    """参考材质的材质名，给面板显示用。读不出来时返回空串——面板不该因为显示不了名字就报错。"""
    try:
        return load(mdf_path)["materials"][0].get("name") or ""
    except CatalogError:
        return ""


def build_property_dict(entry: dict, version: int) -> dict:
    """按一条 `candidates()` 条目造一份新的 `MdfProperty` JSON 字典（初值取自 mdf2）。

    **键的顺序有意义，不能改**：vendor 的 `MdfPropertyJsonConverter.Read()` 是流式的，读到
    `"value"` 时按**当时已经读到的** `parameterType` 决定把它解析成 `MdfPropertyTextureValue`
    还是 `Vector4`（`EfxFile.cs:541-547`）。`parameterType` 排在 `value` 后面的话，贴图属性会
    被当成 float4 读进来。这里的顺序和 vendor 自己 `Write()` 的顺序完全一致。
    """
    if entry["kind"] == "texture":
        return {
            "Version": version,
            "parameterType": "Texture",
            "PropertyNameUTF8Hash": entry["utf8Hash"],
            # 贴图恒为 -1：vendor `MdfProperty.DoWrite()` 就是这么强制的，写别的值也会被覆盖。
            "mdfPropertyIndex": -1,
            "mdfParameterValueCount": 1,
            "flags": 0,
            # pathLength/textureIndex 由 `EFXAttributeTypeMeshV2.DoWrite()` 按 texturePath
            # 重算并重建 texPaths 表，这里给 0 就行；uknInt/_padding 用全语料里唯一见过的取值。
            "value": {"pathLength": 0, "textureIndex": 0, "uknInt": 1, "_padding": 0},
            "texturePath": entry.get("path") or "",
        }

    component_count = entry["componentCount"]
    base = entry.get("value") or {}
    if component_count == 4:
        parameter_type = "Float"
        value = {
            "X": float(base.get("X", 0.0)), "Y": float(base.get("Y", 0.0)),
            "Z": float(base.get("Z", 0.0)), "W": float(base.get("W", 0.0)),
        }
    else:
        # Range 是 `(min_a, min_b, max_a, max_b)`（vendor `MaterialParameterType` 的注释），
        # 语料里 X/Y 恒为 0、Z/W 是取值区间；材质的单个基础值 v 铺成 (0, 0, v, v) = 不随机。
        parameter_type = "Range"
        v = float(base.get("X", 0.0))
        value = {"X": 0.0, "Y": 0.0, "Z": v, "W": v}

    return {
        "Version": version,
        "parameterType": parameter_type,
        "PropertyNameUTF8Hash": entry["utf8Hash"],
        "mdfPropertyIndex": entry["index"],
        "mdfParameterValueCount": component_count,
        "flags": 0,
        "value": value,
    }
