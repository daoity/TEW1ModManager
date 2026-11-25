---
name: tew1-mod-production
description: End-to-end production workflow, reverse-engineered binary specs, Blender plugin authoring (TEW Mesh / TEW Physical), dismemberment rules, D3D11 dynamic physics/self-illumination runtime, and voice replacement pipeline for The Evil Within 1 (PC, EvilWithin.exe). Use whenever creating, debugging, patching, or packaging TEW1 character models (.bmd6model), materials (.decl/.bimage), real-time hair/cloth physics (tew1_dyn.bin), facial morphs, dismemberment, voice packs (.wav), or the TEW1ModManager loader/runtime DLL.
---

# The Evil Within 1 (《恶灵附身 1》) Mod 生产全流程 Skill

本 Skill 沉淀了《恶灵附身 1》（PC Steam/零售 x64 `EvilWithin.exe`）从 **零侵入外部挂载 → BMD6 骨骼建模 → 断肢兼容 → TEW Physical 实时物理/碰撞体 → 面部表情与原生 CG 嘴型 → D3D11 角色自发光 → 语音替换与静默静音 → Mod 管理器打包** 的完整工具链与避坑经验。

## 绝对铁律（修改前必读）

1. **零侵入游戏目录**：严禁修改游戏本体目录（如 `F:\HG\evil\TheEvilWithin\TheEvilWithin\`）内任何文件。所有 Mod 资产必须输出到外部 overlay 目录并通过 `+set fs_basepath <game> +set fs_installpath <overlay> +set resource_loadLooseFiles 1` + 内存补丁挂载。
2. **表面数严格 `<= 31`**：`.bmd6model` 导出总表面数绝不能超过 **31**（引擎使用 32-bit 可见性位掩码，`>= 32` 会导致部位闪烁/隐藏失效/崩溃）。
3. **Havok 布料/头发保护与 `pl0007` 必须隐藏**：原版 `m_hair` 及所有含 `__clt` 的表面**绝不可删除或改变顶点数**（保留原顶点数并将索引清零）；特殊占位模型 `pl0007` 必须 100% 隐藏（`0` 活面），否则角色脚底会出现折叠废网格。
4. **断头处决不残留头发 + 头/身皮肤彻底分离**：严禁把自定义头发、头饰、面部放在 `m_beard`、`m_beard1`、`m_Cornea`、`m_vest__nv`、`m_holster__lt`、`m_coat_button`、`m_hand_r`、`m_necktie` 上；同时务必检查身体网格最上端（耳朵/后脑/上颈延伸面片如 `000_Face(BodySkin)`），将其划归 `HEAD` 槽（`m_face`）并同步写入断头道具 `pl0001_ng` / `pl0016_ng`，保证身体止步于脖颈。
5. **原版肩宽（防“双开门”）与脚掌 1:1 比例铁律**：
   - **严禁拉伸肩宽**：塞巴斯蒂安上臂骨轴心在 `|Y| ≈ 10.25`（比女性/二次元模型 `|Y| ≈ 5.8~6.8` 宽 72%）。对骨时 `l_shoulder`/`l_upperarm` **Y 轴拉伸必须为 `0%`**（仅做轻度 Z 过渡与肘/腕衔接）；更重要的是，必须对内侧肩头区域（`|Y| < 10.6`，`smoothstep(src_upper_y, 10.6, |Y|)`）执行 **肩头内侧权重转移**（将 `l_upperarm`/`r_upperarm` 权重平滑转移给 `l_shoulder`/`r_shoulder`），否则角色在待机垂臂 ~42° 时内侧肩头会向上顶起成方形“双开门”！
   - **严禁拉伸脚掌**：绝不可把裸足/平底鞋按塞巴斯蒂安高帮战靴做 `foot_length / shoe_height` 缩放（会导致大脚怪 1.45× 长 × 1.60× 高）。`foot` / `toe` 必须用纯刚体平移（`I` 单位矩阵、`new_ankle.z = ankle.z`），按**真实脚底最低点贴地 `Z = 0.10`** 对齐。
   - **防腰胯折痕**：全局前后 X 用**双大腿根中点 X** 对齐（而非 `pelvis.x`），并对 `spine_02 -> spine_01 -> pelvis -> thigh` 做共享关节 C1 连续过渡（`hip_z_fit ≈ 0.46`）与平滑臀部权重。
6. **贴身内衣防穿模 + 仅外套半透明透纱（内裤绝不可用 BC3！）**：
   - 贴身内裤/内衣网格与皮肤共面时必穿模，必须沿皮肤法线微幅外推（后腰/臀部 `0.22`，前/侧 `0.12`）并精确同步最近皮肤顶点权重。
   - **仅透纱外套**使用 BC3/DXT5（`SHEER_OUTER`，`clipthreshold 0.05`，`twosided 1.0`），并排在 `.bmd6model` **最后槽位**（身体/腿部/皮肤补丁/内衣之后）；内裤/内衣/配饰必须使用 **100% 不透明 BC1**（`OPAQUE`），绝不可与透纱外套共用 BC3 材质！
7. **D3D11 运行时铁律（防发黑 + 防切章闪退 + 防热键冲突）**：
   - 替换 Pixel Shader **只能**匹配同时包含 `samp_tex_transmap` + `samp_tex_lightprepasslightbuffer` + `samp_tex_hairlut` 的 4 个前向彩色着色器；绝不可劫持 Depth / Shadow / Velocity Pass。
   - 运行时 DLL（v3.10+）必须通过 `g_pinnedVBs`（`AddRef` + 120 帧 `rc<=1` 自动 GC）、`GetSheerDrawPlan` 持有 `AddRef`/`Release`、DSS/RS 按描述体值哈希缓存、`kMaxCtxSlots = 512` 根治章节切换（如 Ch1→Ch2）的 `nvwgf2umx.dll 0xc0000005` 悬空指针闪退！
   - 局内悬浮面板热键**默认使用 `` ` ``（波浪/反引号键 `VK_OEM_3`）**，避免与原版管理器 `Insert` 冲突，并支持面板 `[9]` 实时改键写入 `tew1_dyn_hotkey.ini`。
8. **Python 与 Blender 环境**：本机 Python 直接用 `F:\blender-4.4.3-windows-x64\4.4\python\bin\python.exe`；Blender 命令行验证一律加 `--factory-startup -b`（`F:\blender-4.4.3-windows-x64\blender.exe --factory-startup -b`）。

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

### 流程 A：制作自定义角色模型 + 换骨对骨 + 断肢（Blender 插件 v2.8 `TEW Mesh`，兼容 Blender 4.0–5.2+）
1. 在 Blender 4.0–5.2+ 安装 `dist/恶灵附身1_BMD6_Blender插件_v2.8_TEW_Physical_Blender4-5.zip`。
2. 在 **`TEW Mesh` → `1. 导入导出 & 挂载区`** 选好外部挂载目录；可直接点 **`一键从游戏提取并导入主模板 (pl0000_ng)`**（或 **`批量提取原版 .bmd6model 模型库...`** / `TEW1ModManager.exe` 顶部「提取原版模型」 / `tools/TEW1_TangoResource_Extractor.py` 从游戏 `.tangoresource` 解包提取），然后导入源 MMD/VRChat 角色。
3. **内置 MMD/VRChat 一键对骨（自带防双开门 + 脚掌 1:1 贴地）**：在 **`2. 一键对骨、重命名与换骨`** 勾选 **`保持原版肩宽与脚掌 1:1 比例`** 与 **`自动修复「双开门」肩头内侧权重`**，点 **`一键对骨、重命名并绑定到 TEW1 骨架`**（真实脚底贴地 `Z=0.10`、双大腿中点 X 对齐防腰胯折痕、无损 LBS 保留形态键、自动合并日文旋转/扭转辅助骨、自动转移内侧肩头权重给 `l/r_shoulder`、迁移物理发骨）。
   - 手动对骨或微调后，可随时使用下方独立按钮 **`一键修复「双开门」肩宽权重`** 与 **`贴身内衣/内裤防穿模（先选内衣再选皮肤）`**。
4. **免转 DDS 按贴图去重一键材质**：在 **`3. 材质制作`** 填前缀名，点 **`一键转换角色全部材质 (免转DDS)`**。自动按 `(贴图名, 预设)` 去重复用减少包体，避免 32-bit `.tga` 留白误把 `face`/`body`/`hair`/`wear` 判为 `CUTOUT`，内裤/内衣强制锁为 100% 不透明 BC1 (`OPAQUE`)，薄纱外套归为 `SHEER_OUTER` (`BC3`, `clipthreshold 0.05`)。
5. **断肢配置与自动回收隐藏废槽**：在 **`4. 网格与断肢工具`** 将原版 31 槽（含 `m_hair`）执行 **`安全清零隐藏`**——导出器会自动回收复用已隐藏的 30 个非 Havok 原版废槽（保留 `m_hair` 原槽位不动），彻底解决 `pl0000_ng` 追加网格必超 31 的问题！支持一次多选批量指派到头/躯干/左臂/右臂/双腿槽，也可点 **`合并同材质/同贴图零碎网格`** 精简表面；打包 ZIP 前会自动校验必须存在 `.bmd6model`。

### 流程 B：制作实时物理、物理表情与 CG 嘴骨（Blender 插件 v2.6 `TEW Physical`）
1. 切到 N 面板 **`TEW Physical`**，步骤 1 点 **`一键自动识别物理骨骼链`**（上限 32 条），步骤 2 套用预设调参（前刘海推荐锁死或用 `近刚性贴额刘海 700/0.56/1.8`，侧发推荐 `稳重低幅侧发 520/0.50/3.0`）。
2. 步骤 3 点 **`一键生成默认人形 5 碰撞体`**（`head`, `neck_00`, `spine_02`, `l_shoulder`, `r_shoulder`，上限 16 个），在 3D 视口直接 `G/S` 拖拽球体后点 **`从视口同步回数据`**。
3. 步骤 4 点 **`烘焙物理预览`** 验证晃动与穿模（完后点 **`恢复原动作`**），勾选 **`自动纳入角色全部网格（支持自发光与局内 ` 键菜单）`**。
4. 步骤 5（**`TEW Facial` 物理表情与 CG 嘴骨**）：选中面部网格点 **`一键自动匹配 MMD/VRChat 形态键`**（无形态键可一键新建空白核心 5 形态键），用 4 个预览按钮检查眨眼/受击/死亡是否穿模，再点 **`一键从张嘴形态键生成 CG 嘴骨权重`**（写入原生 `jaw` 及嘴角骨权重）。
5. 步骤 6 点 **`一键同步导出 BMD6 + tew1_dyn.bin`**（保证 VB 指纹 100% 同步），再点 **`一键打包为 Mod ZIP`** 直接导入 `TEW1ModManager.exe` 测试！

### 流程 C：编译运行时 DLL 与便携管理器
- 编译 `tew1_dyn_runtime.dll`（v3.10+）：`powershell -ExecutionPolicy Bypass -File F:\HG\evil\TEW1ModManager\runtime_src\build_dyn_runtime.ps1`（产物拷贝到 `dist\tew1_dyn_runtime.dll` 与 `runtime_src\tew1_dyn_runtime.dll`）。
- 编译便携管理器 `TEW1ModManager.exe`：`powershell -ExecutionPolicy Bypass -File F:\HG\evil\TEW1ModManager\build.ps1`（自动将最新 `tew1_dyn_runtime.dll` 嵌入主程序并同时产出纯净版）。

### 流程 D：制作独立语音替换包
1. 查阅 [audio_and_voice_pipeline.md](references/audio_and_voice_pipeline.md)。
2. 动作/受击/QTE 语音放入 `base/sound/voice_talk/english/ingame_voice/sebastian/<原名>.wav`（受击类按 `-5.5..-6.0 dB` RMS 软限幅补偿 `-7/-9 dB` 衰减，保留完整尾音）。
3. 屏蔽剩余原生对话时，读取原 `.bsnd` 真实时长生成等长 8000 Hz 8-bit `0x80` 静音 WAV。
4. 在根目录写入 `mod.info`（`type=voice`），打包为独立 ZIP，在管理器中可单独勾选启用/关闭。

---

## 故障速查（实机验证 Checklist）

- **角色待机垂臂变成“双开门”宽肩**：原版 `l/r_upperarm` 轴心在 `|Y| ≈ 10.25`，必须保证对骨时 `shoulder_fit = 0` 且对 `|Y| < 10.6` 内侧肩头做 `upperarm -> shoulder` 平滑权重转移（Blender 插件 `TEW Mesh > 2` 已内置一键修复按钮）。
- **角色裸足被拉成大长脚/高跟脚**：绝不可把裸足脚踝强行对齐/缩放到塞巴斯蒂安战靴脚踝，必须保持 `foot` 刚体 1:1 比例并用真实脚底最低点贴地 `Z = 0.10`。
- **背后内裤/内衣穿出屁股**：对贴身内衣沿皮肤法线外推（后臀 `0.22` / 前侧 `0.12`）并精确复制最近皮肤顶点的骨骼权重（插件 `TEW Mesh > 2` 内置一键内衣防穿模）。
- **内裤跟着外套一起变半透明**：检查内裤是否误用了 BC3 材质或与透纱外套共用材质；内裤必须独立使用 **BC1 `OPAQUE`**，仅透纱外套使用 **BC3 `SHEER_OUTER` (`clipthreshold 0.05`)** 且排在模型最后槽位。
- **切到第二章/读档闪退 (`nvwgf2umx.dll 0xc0000005`)**：升级至 `tew1_dyn_runtime.dll` v3.10+（具备 COM `AddRef` 钉住 VB + 120 帧自动 GC + 描述体值缓存 DSS/RS + 512 槽上下文隔离）。
- **顶点色身体补丁烘焙糊掉/边缘黑线**：严禁用 Blender `smart_project`（会让几百三角面挤在 1px 缝里），必须用纯前后平面投影 UV + 邻接皮肤接缝色标定 + 16px 边缘扩张。
- **角色整张脸/模型变黑**：检查材质是否用了 `lppalbedoalphaforwardanisotropic`；检查 `tew1_dyn_runtime.log` 中 `EmissiveSwap` 计数与着色器过滤是否误中 Depth/Shadow Pass。
- **物理或自发光完全无效果**：查看 `tew1_dyn_runtime.log`：确认 `Loaded tew1_dyn pack v2`、`hairVBs > 0`、`extraCharVBs > 0`、`matched` 与 `missed=0`。若 `missed > 0`，说明 `.bmd6model` 重导后未重新同步导出 `tew1_dyn.bin`。
- **断头后头发悬在空中 / 身体最上面多出头皮耳朵**：确保头发、脸、耳部/上颈皮肤统一归入 `m_face`（以及 `pl0001_ng` 等断头模型），严禁放在 `m_beard` 或身体槽。
- **局内菜单热键与原版管理器冲突**：v3.10 起面板默认热键已改为 `` ` ``（Tab 上方反引号键），在菜单 `[9]` 可实时改键并自动保存到 `tew1_dyn_hotkey.ini`。
