# -*- coding: utf-8 -*-
"""把 .efx 里某个 Expression 函数组件的操作码改成另一个值，**绕开"解析器不认这个名字"
的限制**——用来实机探测 vendor 枚举里没有的操作码（`EfxExpressionFunction` 跳过了
3 / 13 / 14）。

为什么需要它：`EfxExpressionStringParser` 按枚举名认函数，枚举里没有的名字直接拒绝，
所以光靠文本形式写不出操作码 3。但组件在文件里就是 8 字节一对
`(type:int32, value:int32)`（`type=3` 是函数、`value` 是操作码），改后 4 个字节即可——
**长度不变，所有尺寸字段都不用动**。

用它测出来的结论（2026-09-16，逐条见 docs/EXPRESSION_SEMANTICS.md 第 10 节）：

- **操作码 3 = `acos`**（弧度）。0/1/2/3 = sin/cos/asin/acos 齐了。
- **操作码 13 / 14 引擎没实现**：输出既不依赖操作数个数（1/2/3 参载体表现完全相同）、
  也解释不成输入的任何函数（13 全程贴上界、14 "平直后突然阶跃到 0"），是求值器碰到
  未实现操作码之后的退化路径。加上全语料零出现，**vendor 跳过它们是对的**。

⚠ 打过补丁的文件 **vendor 自己读不回来**（`UnflattenExpression` 对未知操作码抛
`NotSupportedException`），这是预期的——它只用来喂游戏。所以每次都配一个**未打补丁的
对照文件**：这样"游戏里什么都不出现"才能区分"操作码不存在"和"文件被我改坏了"。

用法:  python tools/patch_expression_opcode.py <输入.efx.版本号> <旧操作码> <新操作码> [输出路径]
"""

import struct, sys, os, shutil

# Windows 控制台默认 GBK，docstring / 提示里有它编不出来的字符会直接抛 UnicodeEncodeError
# （门禁/脚本因为一句 print 崩掉最冤），所以统一重配一次标准输出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def find_components(buf, func_value):
    """返回所有 (偏移, type, value) 满足 type==3 且 value==func_value 的组件位置。
    只认 8 字节对齐不了的情况，所以逐 4 字节扫，靠 (type, value) 的组合过滤。"""
    hits = []
    for off in range(0, len(buf) - 8, 4):
        t, v = struct.unpack_from("<ii", buf, off)
        if t == 3 and v == func_value:
            hits.append(off)
    return hits

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    src, old, new = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    dst = sys.argv[4] if len(sys.argv) > 4 else src
    buf = bytearray(open(src, "rb").read())
    hits = find_components(buf, old)
    print("文件: %s (%d 字节)" % (src, len(buf)))
    print("找到 %d 处 (type=3, value=%d) 的函数组件: %s"
          % (len(hits), old, [hex(h) for h in hits]))
    if not hits:
        print("没找到——确认导出的公式里真的用了那个函数")
        return 1
    if len(hits) > 1:
        print("⚠ 命中多处，会全部改掉。想只改一处就换一个在公式里只出现一次的函数。")
    for off in hits:
        struct.pack_into("<i", buf, off + 4, new)
    if dst == src:
        shutil.copy2(src, src + ".bak")
        print("原文件已备份到", src + ".bak")
    open(dst, "wb").write(buf)
    print("已把这 %d 处的操作码 %d 改成 %d -> %s" % (len(hits), old, new, dst))
    # 复核
    buf2 = open(dst, "rb").read()
    print("复核: 新文件里 (3,%d) 有 %d 处、(3,%d) 还剩 %d 处"
          % (new, len(find_components(bytearray(buf2), new)),
             old, len(find_components(bytearray(buf2), old))))
    return 0

if __name__ == "__main__":
    sys.exit(main())
