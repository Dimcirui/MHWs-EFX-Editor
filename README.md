# MHWs-EFX-Editor

Monster Hunter Wilds（RE Engine）`.efx` 特效文件的 Blender 编辑插件。Phase 0（C# 后端往返稳定性
验证）已完成，目前处于 Phase 1（JSON 交换协议 + Blender addon 骨架搭建中）。当前只有一个最小
"导入→查看 JSON→导出"闭环，还没有字段级 PropertyGroup 面板。

详见 [PLAN.md](PLAN.md)。

姊妹项目（MHWI/MT Framework，独立不依赖）：[EFX-Editor](../EFX-Editor)

## 克隆

本仓库用 git submodule 引入 [RE-Engine-Lib](https://github.com/kagenocookie/RE-Engine-Lib)：

```
git clone --recurse-submodules <this-repo-url>
```

已经克隆过忘了带 `--recurse-submodules`：

```
git submodule update --init --recursive
```
