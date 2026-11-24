---
name: tew1-mod-production
description: End-to-end production workflow, reverse-engineered binary specs, Blender plugin authoring (TEW Mesh / TEW Physical), dismemberment rules, D3D11 dynamic physics/self-illumination runtime, and voice replacement pipeline for The Evil Within 1 (PC, EvilWithin.exe). Use whenever creating, debugging, patching, or packaging TEW1 character models (.bmd6model), materials (.decl/.bimage), real-time hair/cloth physics (tew1_dyn.bin), facial morphs, dismemberment, voice packs (.wav), or the TEW1ModManager loader/runtime DLL.
---

# The Evil Within 1 (《恶灵附身 1》) Mod 生产全流程 Skill

本 Skill 沉淀了《恶灵附身 1》（PC Steam/零售 x64 `EvilWithin.exe`）从 **零侵入外部挂载 → BMD6 骨骼建模 → 断肢兼容 → TEW Physical 实时物理/碰撞体 → 面部表情与原生 CG 嘴型 → D3D11 角色自发光 → 语音替换与静默静音 → Mod 管理器打包** 的完整工具链与避坑经验。

## 绝对铁律（修改前必读）

1. **零侵入游戏目录**：严禁修改游戏本体目录（如 `F:\HG\evil\TheEvilWithin\TheEvilWithin\`）内任何文件。所有 Mod 资产必须输出到外部 overlay 目录并通过 `+set fs_basepath <game> +set fs_installpath <overlay> +set resource_loadLooseFiles 1` + 内存补丁挂载。
2. **表面数严格 `<= 31`**：`.bmd6model` 导出总表面数绝不能超过 **31**（引擎使用 32-bit 可见性位掩码，`>= 32` 会导致部位闪烁/隐藏失效/崩溃）。
3. **Havok 布料/头发保护**：原版 `m_hair` 及所有含 `__clt` 的表面**绝不可删除或改变顶点数**；需隐藏时保留原顶点缓冲，将三角面索引清零（或写成单个零面积退化三角形 `(0,0,0)`）。
4. **断头处决不残留头发**：严禁把自定义头发、头饰、面部放在 `m_beard`、`m_beard1`、`m_Cornea`、`m_vest__nv`、`m_holster__lt`、`m_coat_button`、`m_hand_r`、`m_necktie` 上（断头/爆头时会悬空残留！）。必须全部放到真正的纯头部槽（`m_face` / `m_mouth3` / `m_tong`，允许同名多表面）。
5. **D3D11 自发光严防“面部发黑”**：替换 Pixel Shader 时**只能**匹配同时包含 `samp_tex_transmap` + `samp_tex_lightprepasslightbuffer` + `samp_tex_hairlut` 的 4 个前向彩色着色器；绝不可劫持 Depth / Shadow / Velocity Pass，且必须在 `CreateDeferredContext` 中隔离每个上下文状态并在状态切换后 `ReassertDrawHooks`。
6. **Python 环境**：本机直接用 `F:\blender-4.4.3-windows-x64\4.4\python\bin\python.exe`（系统 `python` 是 MS Store 占位符）；Blender 验证用 `F:\blender-4.4.3-windows-x64\blender.exe -b`。

---

## 核心工作流与参考文档导航

按需按以下模块查阅深层规范（渐进式加载）：

| 任务场景 | 参考文档 | 关键产物/脚本 |
| :--- | :--- | :--- |
| 二进制结构、游戏 RVA、Shader、D3D11 运行时 DLL | [binary_formats_and_rvas.md](references/binary_formats_and_rvas.md) | `runtime_src/tew1_dyn_runtime.cpp`, `src/NativeLoader.cs` |
| 全章节模型清单、断肢 `meshKits`、原生 9 骨 CG 嘴型 | [dismemberment_and_skeletons.md](references/dismemberment_and_skeletons.md) | `runtime_src/patch_haruka_dismember.py`, `patch_haruka_mouth_jaw.py` |
| 主角语音替换、响度补偿、QTE 循环、静音原对话 | [audio_and_voice_pipeline.md](references/audio_and_voice_pipeline.md) | `runtime_src/build_haruka_voice_pack.py` |
| Blender 插件与完整工具链索引 | [toolchain_index.md](references/toolchain_index.md) | `blender_addon/tew1_bmd6/` (`TEW Mesh` + `TEW Physical`) |
| 面向人类作者的手作完整教程 | `F:\HG\evil\TEW1ModManager\TEW1_Mod制作与物理全流程教程.md` | 随插件与管理器同步分发 |

---

## 标准生产 SOP

### 流程 A：制作自定义角色模型 + 换骨对骨 + 断肢（Blender 插件 v2.5 `TEW Mesh`，兼容 Blender 4.0–5.2+）
1. 在 Blender 4.0–5.2+ 安装 `dist/恶灵附身1_BMD6_Blender插件_v2.5_TEW_Physical_Blender4-5.zip`。
2. 在 **`TEW Mesh` → `1. 导入导出 & 挂载区`** 选好外部挂载目录，点 **`导入 BMD6`** 导入原版模板（如 `pl0000_ng.bmd6model`），并导入源 MMD/VRChat 角色。
3. **内置 MMD/VRChat 一键对骨重命名（无需外部 ModToolkit）**：在 **`2. 一键对骨、重命名与换骨`** 选好源骨架与 TEW1 模板骨架，点 **`一键对骨、重命名并绑定到 TEW1 骨架`**（自动校正朝向/缩放/姿态并无损 LBS 烘焙保留形态键，自动重命名骨骼与合并扭转/辅助权重，同时迁移物理发骨到模板骨架下）。
4. **免转 DDS 一键材质**：在 **`3. 材质制作`** 填前缀名，点 **`一键转换角色全部材质 (免转DDS)`**（纯 NumPy BC1/BC3 编码器直接从 PNG/TGA/JPG/材质节点输出 `.bimage` + 前向着色 `.decl`）。
5. **断肢配置**：在 **`4. 网格与断肢工具`** 对原版 `m_hair` 及不用原版槽执行 **`安全清零隐藏`**；头发/面片/头饰放到 `m_face`；整件身体点 **`一键按权重拆分身体断肢(4部位)`**；点 **`导出前全面体检`** 确认 `总表面 <= 31`。

### 流程 B：制作实时物理、物理表情与 CG 嘴骨（Blender 插件 v2.5 `TEW Physical`）
1. 切到 N 面板 **`TEW Physical`**，步骤 1 点 **`一键自动识别物理骨骼链`**（上限 32 条），步骤 2 套用 5 套预设调参。
2. 步骤 3 点 **`一键生成默认人形 5 碰撞体`**（`head`, `neck_00`, `spine_02`, `l_shoulder`, `r_shoulder`，上限 16 个），在 3D 视口直接 `G/S` 拖拽球体后点 **`从视口同步回数据`**。
3. 步骤 4 点 **`烘焙物理预览`** 验证晃动与穿模（完后点 **`恢复原动作`**），勾选 **`自动纳入角色全部网格（支持 F7/F8/F9 自发光）`**。
4. 步骤 5（**`TEW Facial` 物理表情与 CG 嘴骨**）：选中面部网格点 **`一键自动匹配 MMD/VRChat 形态键`**（无形态键可一键新建空白核心 5 形态键），用 4 个预览按钮检查眨眼/受击/死亡是否穿模，再点 **`一键从张嘴形态键生成 CG 嘴骨权重`**（写入原生 `jaw` 及嘴角骨权重）。
5. 步骤 6 点 **`一键同步导出 BMD6 + tew1_dyn.bin`**（保证 VB 指纹 100% 同步），再点 **`一键打包为 Mod ZIP`** 直接导入 `TEW1ModManager.exe` 测试！

### 流程 C：编译运行时 DLL 与便携管理器
- 编译 `tew1_dyn_runtime.dll`：`powershell -ExecutionPolicy Bypass -File F:\HG\evil\TEW1ModManager\runtime_src\build_dyn_runtime.ps1`（产物拷贝到 `dist\tew1_dyn_runtime.dll`，打包进管理器前同步嵌入资源）。
- 编译便携管理器 `TEW1ModManager.exe`：使用 `F:\HG\evil\TEW1ModManager\build.ps1`（如存在）或 `csc.exe` 编译 `src\*.cs` 嵌入 `tew1_dyn_runtime.dll`。

### 流程 D：制作独立语音替换包
1. 查阅 [audio_and_voice_pipeline.md](references/audio_and_voice_pipeline.md)。
2. 动作/受击/QTE 语音放入 `base/sound/voice_talk/english/ingame_voice/sebastian/<原名>.wav`（受击类按 `-5.5..-6.0 dB` RMS 软限幅补偿 `-7/-9 dB` 衰减，保留完整尾音）。
3. 屏蔽剩余原生对话时，读取原 `.bsnd` 真实时长生成等长 8000 Hz 8-bit `0x80` 静音 WAV。
4. 在根目录写入 `mod.info`（`type=voice`），打包为独立 ZIP，在管理器中可单独勾选启用/关闭。

---

## 故障速查（实机验证 Checklist）

- **角色整张脸/模型变黑**：检查材质是否用了 `lppalbedoalphaforwardanisotropic`；检查 `tew1_dyn_runtime.log` 中 `EmissiveSwap` 计数与着色器过滤是否误中 Depth/Shadow Pass。
- **物理或自发光完全无效果**：查看游戏或挂载日志 `tew1_dyn_runtime.log`：确认 `Loaded tew1_dyn pack v2`、`hairVBs > 0`、`extraCharVBs > 0`、`matched` 与 `missed=0`。若 `missed > 0`，说明 `.bmd6model` 重导后未重新同步导出 `tew1_dyn.bin`（顶点前 3 点指纹失配）。
- **断头后头发悬在空中**：检查对应章节 `.bmd6model`（特别是 `pl0000_ng` / `pl0020_ng` / `pl0201_ng`）的头发是否误绑在 `m_beard` 或身体槽上。
- **挨打无语音或声音极小**：检查 `.wav` 路径是否为 `base/sound/voice_talk/english/ingame_voice/sebastian/`、`NativeLoader` 是否打了 `WaveLangSubCallOffset` (`0x313F52`) 和 `SoundLoadCallOffset` (`0x305DB2`) 补丁、受击语音响度是否补偿了 `-7/-9 dB` decl 衰减。
