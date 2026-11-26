# 《恶灵附身 1》（The Evil Within 1）一体化 Mod 管理器 & Blender 插件套件

一套专为 PC 版《恶灵附身 1》（`EvilWithin.exe` x64）打造的**零侵入外挂 Mod 工具链**，涵盖：
- **便携单文件 Mod 管理器 & 原生内存加载器 + 内置 `.tangoresource` 原版模型提取器**（`TEW1ModManager.exe`）
- **通用 D3D11 动态物理 / 表情 / 透纱 / 自发光运行时**（`tew1_dyn_runtime.dll` v3.11，完整适配 **Steam 正版** 与经典 PC 构建）
- **Blender 4.0 — 5.2+ LTS 创作插件**（`TEW Mesh` + `TEW Physical` + `TEW Facial` v2.9，支持 Steam 正版库自动识别、游戏模型一键提取、自动回收隐藏废槽防超 31 表面、按贴图去重材质）
- **独立零依赖游戏资源提取工具**（`tools/TEW1_TangoResource_Extractor.py`，双击 GUI / 命令行提取 `.bmd6model`/`.bimage`/`.decl`/`.wav`）
- **傻瓜化中文图文全流程教程**（[TEW1_Mod制作与物理全流程教程.md](TEW1_Mod制作与物理全流程教程.md)）
- **AI Agent Skill 工作流沉淀**（[skills/tew1-mod-production/SKILL.md](skills/tew1-mod-production/SKILL.md)）

> ⚠️ **全程零侵入游戏本体目录**：所有模型、贴图、物理与语音均通过外部挂载目录与内存钩子加载，不改动游戏原版任何文件。

---

## 核心功能一览

### 1. 便携 Mod 管理器 (`TEW1ModManager.exe`)
- **绿色便携单文件**：无外部运行库依赖，Mod 与配置保存在同级 `Data/` 目录。
- **模型单选 + 功能性 Mod 独立叠加**：左侧单选角色模型，同时独立勾选/关闭语音包、补丁等功能性 Mod，启动游戏自动叠加合并。
- **Steam 正版 & 经典构建双版本原生适配**：自动读取 Steam 注册表与 `libraryfolders.vdf` 定位游戏目录，原生支持 **Steam 正版（Build 2708258）** 与经典 PC 构建，自动传递 `SteamAppId=268050` 保活挂载参数，且兼容 Steam 游戏内覆盖层。
- **动态物理、表情与透纱运行时（v3.11）**：内置 `tew1_dyn_runtime.dll` v3.11，支持 `tew1_dyn.bin (v1/v2/v3)` 实时头发/胸/衣摆物理、5 槽位胶囊碰撞体、自然眨眼与受击/死亡表情、4 档双面透纱外套切换，并通过 COM 生命周期钉住 + 120 帧自动 GC 彻底根治跨章节（如 Ch1→Ch2）闪退。
- **一键提取游戏原版 `.bmd6model` 模型**：顶部栏点击 **`提取原版模型`**，可直接从游戏 `base/*.tangoresource` 解包主角全章节 27 模、全部人物(`pl*`)、全部怪物(`em*`)或全游戏 `.bmd6model` 供 Blender 导入，不再发愁找不到可导入的模型文件。
- **游戏内实用热键**：
  - **`` ` ``（Tab 上方反引号/波浪键，默认）**：开关局内服装差分 / 4 档透纱外套 / 自发光悬浮面板（不与原版管理器 `Insert` 冲突；面板按 `[9]` 可实时改键并自动保存到 `tew1_dyn_hotkey.ini`）。
  - `F7` / `F8` / `F9`：切换三档角色自发光（柔和 / 明亮二次元 / 全亮无阴影，再按关闭；严格隔离深度通道不发黑）。
  - `F10`：游戏内即时调试受击表情（`Shift+F10` 定格受击，`Ctrl+F10` 定格死亡）。

### 2. Blender 4.0–5.2+ 插件 (`blender_addon/tew1_bmd6` v2.9)
- **`TEW Mesh` 面板**：
  - **内置原版 `.tangoresource` 提取 + BMD6 导入导出**：自带 **`一键从游戏提取并导入主模板 (pl0000_ng)`** 与 **`批量提取原版 .bmd6model 模型库...`**；导出时**自动回收复用已安全隐藏的非 Havok 原版废槽**（彻底解决 `pl0000_ng` 原版已占满 31 槽导致追加报错的问题，同时严格保留 `m_hair` 原槽位），并自动将透纱外套排到最末绘制。
  - **内置 MMD / VRChat 一键对骨重命名（防双开门 + 脚掌 1:1 + 防内衣穿模）**：自动对齐朝向、身高缩放与**真实脚底贴地 `Z=0.10`（1:1 裸足不拉长）**、双大腿中点 X 对齐防腰胯折痕、无损 LBS 烘焙保留全部面部形态键、**自动修复“双开门”肩头内侧权重**、**贴身内衣/内裤一键外推防穿模并同步皮肤权重**，并迁移物理发骨到 TEW1 模板骨架下。
  - **一键免转 DDS 材质生成**：内置 NumPy BC1/DXT1 & BC3/DXT5 编码器，自动区分不透明内裤/皮肤（`OPAQUE` BC1）、实体头发（`HAIR`）、镂空（`CUTOUT`）与**透纱外套（`SHEER_OUTER` BC3 `clipthreshold 0.05`）**，绕过原版 Megatexture。
  - **断肢安全工具**：一键按骨骼权重拆分身体 4 部位（躯干/左臂/右臂/双腿），原版 `m_hair` 与 `pl0007` 安全清零隐藏防崩溃，导出前自动体检（`<= 31` 表面、安全头部槽位、头身分离与双开门预警）。
  - **一键打包 Mod ZIP**：自动生成 `mod.info` 与完整资源树。
- **`TEW Physical` & `TEW Facial` 面板**：
  - **6 步实时物理工作流**：一键自动识别发骨/飘带/裙摆链（上限 32 条）、7 套手感预设（含实机验证的稳重侧发与近刚性贴额刘海）、一键生成 5 槽位可视化球体碰撞体并在 3D 视口拖拽同步、时间轴预览烘焙。
  - **物理表情与 CG 嘴骨**：5 槽位形态键映射（支持自动匹配与无形态键一键建模板）、待机/眨眼/受击/死亡 4 态防穿模预览、**一键从张嘴形态键生成原生 CG `jaw` 嘴骨权重**。
  - **全界面悬停提示**：所有按钮与滑块鼠标悬停 1 秒即显示详细中文操作说明。

---

## 仓库目录结构

```text
TEW1ModManager/
├── src/                               # Mod 管理器 & 原生加载器 C# 源码 (WPF / Win32)
├── runtime_src/                       # D3D11 动态物理/表情/透纱/自发光运行时 C++ 源码及配套脚本
├── blender_addon/tew1_bmd6/           # Blender 4.0-5.2+ 插件源码 (TEW Mesh / TEW Physical + 内置模型提取)
├── tools/                             # 独立零依赖 .tangoresource 原版模型与资源提取工具
├── skills/tew1-mod-production/        # Antigravity AI Skill (完整逆向规范与自动化工作流)
├── TEW1_Mod制作与物理全流程教程.md     # 面向手动作者的完整图文教程
├── build.ps1                          # 管理器一键构建脚本 (.NET Framework 4)
├── LICENSE                            # 开源与商业限制声明
└── README.md
```

---

## 快速使用

### 玩家 / 使用现成 Mod
1. 从 GitHub **Releases** 下载 **`正版管理器`** 分发包（`TEW1_SteamOfficial_ModManager_v2.9.zip` 或单文件 `TEW1ModManager.exe`），解压/放置到任意非游戏目录。
2. Steam 正版玩家请先登录并运行 Steam 客户端；双击 `TEW1ModManager.exe` 自动识别游戏目录（显示 **`已就绪 · Steam 正版`** 或经典构建），拖入任意现有 Mod `.zip` 即可一键启动。

### Mod 作者（Blender 4.0–5.2+）
1. 从 **Releases** 下载 `TEW1_BMD6_Blender_Plugin_v2.9_TEW_Physical_Blender4-5.zip`（如需要也可下载独立提取器 `TEW1_TangoResource_Extractor.py`）。
2. 在 Blender 4.2+ 直接将 ZIP 拖入窗口安装（或 `编辑 > 偏好设置 > 插件 > 从磁盘安装`）。
3. 按 **`N`** 键展开 **`TEW Mesh`** 与 **`TEW Physical`** 面板，详细步骤请阅读：[TEW1_Mod制作与物理全流程教程.md](TEW1_Mod制作与物理全流程教程.md)。

### AI 辅助开发（Antigravity Skill）
将本仓库 `skills/tew1-mod-production/` 复制到工作区 `.agents/skills/tew1-mod-production/`，AI 助手即可自动掌握 TEW1 二进制格式、引擎 RVA、断肢规则、防双开门/1:1脚掌对骨、仅外套透纱、D3D11 运行时与语音替换全套规范。

---

## 致谢

- 骨骼预设与换骨工作流设计参考了开源项目 **Modding-Toolkit**：https://github.com/Dimcirui/Modding-Toolkit

---

## 开源声明与联系方式

- **禁止大规模商业行为**：本仓库全部代码、工具与教程严禁用于大规模商业行为，包括但不限于**收费数额超过 300 RMB（人民币叁佰元）的定制项目**、商业倒卖或盈利性分发。
- **责任保留**：一旦发现违反上述条款，作者保留全部制作者法定权利，依法追究个人责任。
- **问题反馈 / 联系作者**：如有任何使用问题或反馈，请联系作者 QQ：**`2534594973`**
