# MHWs-EFX-Editor

Monster Hunter Wilds（RE Engine）`.efx` 特效文件的 Blender 编辑插件。目前处于 Phase 0（验证阶段），
还没有 Blender 插件代码。

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
