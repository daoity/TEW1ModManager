# TEW1 Mod 工具链与代码资产全索引

根目录：`F:\HG\evil\TEW1ModManager\`

## 1. Blender 插件 v2.7（兼容 Blender 4.0–5.2+，面向手工作者的完整制作套件）
- 源码目录：`blender_addon/tew1_bmd6/`
- 发布安装包：`dist/恶灵附身1_BMD6_Blender插件_v2.7_TEW_Physical_Blender4-5.zip`
- 模块结构（参考 `NSACloud/RE-Mesh-Editor` 模块化架构 + 内置 ModToolkit MMD/VRChat 预设）：
  - `tango_extract.py`：内置 `.tangoresource` 解包提取器（自动搜索游戏目录、**一键提取并直接导入 `pl0000_ng`/`pl0020_ng`/`pl0010_ng`/`pl0001_ng`**、按主角全章节/全人物 `pl*`/全怪物 `em*`/全游戏 `.bmd6model` 批量提取），彻底解决新手“找不到 `.bmd6model`”问题。
  - `compat.py`：Blender 4.0–5.2+ 兼容封装（PoseBone 选择、Slotted Action 关键帧、材质节点）。
  - `__init__.py`：`.bmd6model` 读写桥接、`File > Import / Export` 菜单、槽位替换/追加（自动把透纱外套追加槽排到最后绘制）、安全清零隐藏。
  - `bmd6.py` / `build.py` / `geometry.py` / `presets.py`：BMD6 二进制读写、网格流编码、连续切线、默认 `shoulder_fit=0.0` + 1:1 刚体脚掌 + C1 腰胯过渡、4 套前向材质模板（含 `SHEER_OUTER` 透纱外套）。
  - `rig_tools.py`：内置 ModToolkit 的 **MMD & VRChat** 完整骨骼预设、**一键骨骼重命名 + 辅助/扭转骨权重合并**、**MMD A→T（无损保留形态键 LBS 烘焙）**、**一键对骨对齐缩放（默认保持原版肩宽 + 真实脚底贴地 Z=0.10 脚掌 1:1 + 双大腿中点 X 对齐）**、**一键修复「双开门」肩宽权重**、**贴身内衣/内裤防穿模（自动外推 + 同步皮肤权重）**。
  - `tex_encode.py`：纯 NumPy 矢量化 **BC1/DXT1 & BC3/DXT5 + Mipmap 编码器**、**一键批量转换角色全部材质**（自动将内裤/内衣强制锁为 100% 不透明 BC1 `OPAQUE`，自动识别透纱外套 `SHEER_OUTER`）。
  - `dismember.py`：断肢槽位识别与分配、**一键按骨骼权重拆分身体 4 断肢部位**、Havok 槽安全隐藏、4 骨骼权重规范化、导出前全面体检（含 `<=31` 表面、`pl0007` 隐藏、身体伸入头部检查、肩头内侧双开门预警）、`Mod ZIP` 一键打包。
  - `hair_author.py` / `hair_solver.py`：7 套物理风格预设（含实机验证的 `稳重低幅侧发 520/0.50/3.0` 与 `近刚性贴额刘海 700/0.56/1.8`）、**一键自动识别发骨链**、**一键生成人形 5 碰撞体**、3D 视口可拖拽球体与反向同步、时间轴 XPBD 物理预览烘焙、JSON 导入导出。
  - `facial_author.py`：**`TEW Facial`** 物理表情与 CG 嘴骨（核心 5 槽位下拉映射 + 自动匹配、待机/眨眼/受击/死亡 4 态视口实时预览、无形态键一键建空白模板、**一键从张嘴形态键生成原生 CG `jaw`/嘴角骨权重**）。
  - `dyn_export.py`：`tew1_dyn.bin` **v2** 通用编译器（KDTree+AABB 极速匹配、发束/布料物理链 `<=32`、5 槽碰撞体 `<=16`、优先读取 `TEW Facial` 映射的 15 通道形态键、Section 6 全身自发光 VB 指纹 `<=4096`）、**一键同步导出 BMD6 + tew1_dyn.bin**。
  - `ui_panels.py`：
    - 3D 视口 N 面板 **`TEW Mesh`**（1.导入导出与挂载区 → 2.MMD/VRChat 一键对骨 + 防双开门 + 防穿模 → 3.一键免转 DDS/透纱材质 → 4.网格与断肢工具 → 5.一键打包 Mod ZIP）
    - 3D 视口 N 面板 **`TEW Physical`**（1.总览与识链 → 2.物理骨骼链 → 3.胶囊碰撞体 5 槽位可视化 → 4.视口预览烘焙与自发光 → 5.物理表情与 CG 嘴骨 `TEW Facial` → 6.校验与同步导出 v2）
    - 材质属性面板 **`TEW1 材质属性 (TEW Mat)`**

## 2. 运行时 DLL 与构建脚本 (`runtime_src/`)
- `tew1_dyn_runtime.cpp` + `build_dyn_runtime.ps1` → `dist/tew1_dyn_runtime.dll`（**v3.10**）：通用角色物理、胸/衣摆扩展物理、表情、三档自发光 (`F7/F8/F9`)、4 档双面透纱外套切换、自定义面板热键（默认 `` ` ``，局内 `[9]` 一键改键写入 `tew1_dyn_hotkey.ini`）、COM 钉住 VB + 120 帧自动 GC 根治跨章节闪退、受击/死亡调试 (`F10`) 与音频触发运行时。
- `build_florence_mod.py`：包含原版窄肩防双开门、1:1 裸足、C1 腰胯、内衣防穿模、仅外套透纱、头身皮肤分离、顶色补丁平面 UV 烘焙等全套最佳实践的完整生产参考脚本。
- `build_haruka_runtime_pack.py`：命令行批量构建全章节 `tew1_dyn.bin` v2 的参考范例。
- `patch_haruka_mouth_jaw.py`：批量写入原生 9 骨 CG 嘴型与 `LOWER_MOUTH` 权重参考脚本。
- `patch_haruka_dismember.py`：全章节模型断肢槽位修复、头发移入安全头槽、身体 4 部位拆分参考脚本。
- `build_haruka_voice_pack.py`：主角动作/受击/QTE 语音响度补偿与 `.bsnd` 等时长静音生成器。
- `build_mod_zip.py`：批量打包可发布 Mod ZIP 脚本。

## 3. 便携 WPF Mod 管理器与独立提取器 (`src/` & `tools/` & `dist/`)
- `src/NativeLoader.cs`：挂起拉起 `EvilWithin.exe`，注入 6 处散文件内存补丁并可选注入 `tew1_dyn_runtime.dll`。
- `src/TangoExtractor.cs`：内置 C# `.tangoresource` 原版 `.bmd6model` 提取器（使用 .NET 原生 `DeflateStream` 零依赖解压，可在管理器顶部栏一键导出核心 27 模/全人物/全怪物/全游戏模型）。
- `src/MainWindow.cs` / `src/OverlayLibrary.cs`：模型单选启动 + 语音等功能性 Mod 独立启用/关闭 + 物理/表情开关 + 覆盖合并 + 顶部一键提取原版模型。
- `tools/TEW1_TangoResource_Extractor.py`：独立零依赖 Python GUI+CLI 资源提取工具（`.bmd6model` / `.bimage` / `.decl` / `.wav`）。
- `dist/TEW1ModManager.exe` / `dist/TEW1ModManager_纯净版.exe`：单文件便携管理器成品。

## 4. 完整人工教程
- `F:\HG\evil\TEW1ModManager\TEW1_Mod制作与物理全流程教程.md`
