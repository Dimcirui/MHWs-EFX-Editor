#!/usr/bin/env python3
"""
tools/build_instance_defaults.py —— 把 `EfxBridge instancedefaults` 的输出转成
`semantics/mhws_attribute_instance_defaults.json`。

跟 `tools/build_attr_defaults.py`（逐字段独立取众数）不是同一套策略：那边容易把互相耦合的
字段拆散拼出语料里从没出现过的假组合（比如某个开关字段本身该是 0 时，另一组字段本不该是
众数值）。这里改成拿"跟逐字段众数向量最贴近的一份真实实例"整份抄下来当默认值——保证落地的
默认值是游戏文件里真实存在过的字段组合，不是统计拼出来的。是否知道字段含义不影响这条流程，
所以覆盖全部请求过的类型，不只是语义已标注的那一小撮。

用法：
    python tools/build_instance_defaults.py tools/instancedefaults_all.json blender_efx_re/semantics/mhws_attribute_instance_defaults.json
"""
from __future__ import annotations

import json
import pathlib
import sys

# 跟 build_attr_defaults.py 保持一致：这几个是每个 attribute 通用的记账字段，创建逻辑自己填，
# 不该抄某一份实例当时的值——instancedefaults 子命令在 C# 侧已经把它们从 instance 里剔掉了，
# 这里不需要重复过滤，只是留个注释说明为什么 instance 里不会出现它们。

# PtBehavior 不适用"抄一份真实实例"这条策略：它是个容器类型，具体字段布局由
# `behaviorString`（游戏内部类名）决定，默认值早就有专门的一套系统
# （`ptbehavior_catalog.py` + `semantics/mhws_ptbehavior_catalog.json`，按 behaviorString
# 分别维护候选属性目录，用户已经做完这部分）。如果这里也塞一份"某个具体 behaviorString 的
# 真实实例"当通用默认值，会把新建的 PtBehavior 提前钉死成某个具体游戏类，跟专用系统打架。
#
# 下面这 9 个是接入这套"整份实例"策略后，用
# `<blender> --background --factory-startup --python <逐类型隔离验证脚本>`（给 180 个候选
# 类型逐一单独建 attribute、导出、读回）实测出来的：套上非空的真实实例内容会触发
# KNOWN_UPSTREAM_ISSUES.md #8 那个 vendor bug（`IClipAttribute`/`IExpressionAttribute`/
# `IMaterialExpressionAttribute` 实现类里"只读属性指向同一个字段"的写法，配合
# `JsonObjectCreationHandling.Populate` 会把同一份列表数据在 JSON 层重复填充两次，写出来的
# attribute 体积翻倍，下次读回直接读到垃圾）。之前只confirm 过 `TypeMeshClip`/
# `TypeBillboard3DMaterialClip`/`TypeBillboard3DMaterialExpression` 三个，这次多验证出另外
# 6 个新命中——全零默认值（旧行为）不会触发（对应的 list 字段本来就是空的，重复填充空列表
# 还是空列表），所以这几个类型退回旧的逐字段众数表/纯零值，不套整份实例。
_SKIP_TYPES = {
    "PtBehavior",
    "TypeBillboard3DMaterialClip",
    "TypeBillboard3DMaterialExpression",
    "TypeGpuMeshClip",
    "TypeGpuMeshExpression",
    "TypeGpuMeshTrailClip",
    "TypeMeshClip",
    "TypeMeshExpression",
    "TypeRibbonLengthMaterialClip",
    "TypeRibbonLengthMaterialExpression",
    "TypeRibbonParticleMaterialExpression",
}


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    in_path = pathlib.Path(argv[1])
    out_path = pathlib.Path(argv[2])

    data = json.loads(in_path.read_text(encoding="utf-8"))

    defaults: dict = {}
    evidence: dict = {}
    skipped_no_instance = []
    for type_name, info in data["types"].items():
        if type_name in _SKIP_TYPES:
            continue
        if info is None:
            skipped_no_instance.append(type_name)
            continue
        defaults[type_name] = info["instance"]
        # evidence 只记调研方法/出处，不进 tooltip，也不参与 get_attribute_instance_default()
        # 的查表逻辑——纯粹是"这份默认值是从哪份真实文件、匹配了多少个字段选出来的"存档。
        evidence[type_name] = {
            "instances": info["instances"],
            "matchScore": info["matchScore"],
            "totalFields": info["totalFields"],
            "sourceFile": info["sourceFile"],
        }

    out = {
        "game": "MHWS",
        "defaults": defaults,
        "evidence": evidence,
    }
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK: {len(defaults)} 种类型有真实实例可用 -> {out_path}")
    print(f"  语料里一次都没出现过、没有默认值的类型数: {len(skipped_no_instance)}")
    if skipped_no_instance:
        print(f"  例如: {', '.join(skipped_no_instance[:10])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
