# 《恶灵附身 1》（The Evil Within 1）一体化 Mod 管理器 & Blender 插件套件

一套专为 PC 版《恶灵附身 1》（`EvilWithin.exe` x64）打造的**零侵入外挂 Mod 工具链**，涵盖：
- **便携单文件 Mod 管理器 & 原生内存加载器**（`TEW1ModManager.exe`）
- **通用 D3D11 动态物理 / 表情 / 自发光运行时**（`tew1_dyn_runtime.dll`）
- **Blender 4.0 — 5.2+ LTS 创作插件**（`TEW Mesh` + `TEW Physical` + `TEW Facial`）
- **傻瓜化中文图文全流程教程**（[TEW1_Mod制作与物理全流程教程.md](TEW1_Mod制作与物理全流程教程.md)）
- **AI Agent Skill 工作流沉淀**（[skills/tew1-mod-production/SKILL.md](skills/tew1-mod-production/SKILL.md)）

> ⚠️ **全程零侵入游戏本体目录**：所有模型、贴图、物理与语音均通过外部挂载目录与内存钩子加载，不改动游戏原版任何文件。

---

## 核心功能一览

### 1. 便携 Mod 管理器 (`TEW1ModManager.exe`)
- **绿色便携单文件**：无外部运行库依赖，Mod 与配置保存在同级 `Data/` 目录。
- **模型单选 + 功能性 Mod 独立叠加**：左侧单选角色模型，同时独立勾选/关闭语音包、补丁等功能性 Mod，启动游戏自动叠加合并。
- **动态物理与表情开关**：内置 `tew1_dyn_runtime.dll`，支持 `tew1_dyn.bin (v1/v2)` 实时头发物理、5 槽位胶囊碰撞体、自然眨眼与受击/死亡表情。
- **游戏内实用热键**：
  - `F7` / `F8` / `F9`：切换三档角色自发光（柔和 / 明亮二次元 / 全亮无阴影，再按关闭；严格隔离深度通道不发黑）。
  - `F10`：游戏内即时调试受击表情（`Shift+F10` 定格受击，`Ctrl+F10` 定格死亡）。

### 2. Blender 4.0–5.2+ 插件 (`blender_addon/tew1_bmd6`)
- **`TEW Mesh` 面板**：
  - **导入导出 `.bmd6model`**：保留原生骨架模板与断肢信息。
  - **内置 MMD / VRChat 一键对骨重命名**：自动对齐朝向、身高缩放与脚底贴地，无损 LBS 烘焙保留全部面部形态键，自动合并扭转/辅助骨权重并迁移物理发骨到 TEW1 模板骨架下。
  - **一键免转 DDS 材质生成**：内置 NumPy BC1/BC3 编码器，直接读取 PNG/TGA/JPG/材质节点贴图生成 `.bimage` 与前向着色 `.decl`（绕过原版 Megatexture）。
  - **断肢安全工具**：一键按骨骼权重拆分身体 4 部位（躯干/左臂/右臂/双腿），原版 `m_hair` 安全清零隐藏防 Havok 崩溃，导出前自动体检（`<= 31` 表面、安全头部槽位检查）。
  - **一键打包 Mod ZIP**：自动生成 `mod.info` 与完整资源树。
- **`TEW Physical` & `TEW Facial` 面板**：
  - **6 步实时物理工作流**：一键自动识别发骨/飘带/裙摆链（上限 32 条）、5 套手感预设、一键生成 5 槽位可视化球体碰撞体并在 3D 视口拖拽同步、时间轴预览烘焙。
  - **物理表情与 CG 嘴骨**：5 槽位形态键映射（支持自动匹配与无形态键一键建模板）、待机/眨眼/受击/死亡 4 态防穿模预览、**一键从张嘴形态键生成原生 CG `jaw` 嘴骨权重**。
  - **全界面悬停提示**：所有按钮与滑块鼠标悬停 1 秒即显示详细中文操作说明。

---

## 仓库目录结构

```text
TEW1ModManager/
├── src/                               # Mod 管理器 & 原生加载器 C# 源码 (WPF / Win32)
├── runtime_src/                       # D3D11 动态物理/表情/自发光运行时 C++ 源码及配套脚本
├── blender_addon/tew1_bmd6/           # Blender 4.0-5.2+ 插件源码 (TEW Mesh / TEW Physical)
├── skills/tew1-mod-production/        # Antigravity AI Skill (完整逆向规范与自动化工作流)
├── TEW1_Mod制作与物理全流程教程.md     # 面向手动作者的完整图文教程
├── build.ps1                          # 管理器一键构建脚本 (.NET Framework 4)
├── LICENSE                            # 开源与商业限制声明
└── README.md
```

---

## 快速使用

### 玩家 / 使用现成 Mod
1. 从 GitHub **Releases** 下载 `TEW1ModManager.exe`（可单独放到任意非游戏目录）。
2. 双击运行，自动识别 `EvilWithin.exe` 路径，拖入 Mod `.zip` 后勾选启动即可。

### Mod 作者（Blender 4.0–5.2+）
1. 从 **Releases** 下载 `恶灵附身1_BMD6_Blender插件_v2.5_TEW_Physical_Blender4-5.zip`。
2. 在 Blender 4.2+ 直接将 ZIP 拖入窗口安装（或 `编辑 > 偏好设置 > 插件 > 从磁盘安装`）。
3. 按 **`N`** 键展开 **`TEW Mesh`** 与 **`TEW Physical`** 面板，详细步骤请阅读：[TEW1_Mod制作与物理全流程教程.md](TEW1_Mod制作与物理全流程教程.md)。

### AI 辅助开发（Antigravity Skill）
将本仓库 `skills/tew1-mod-production/` 复制到工作区 `.agents/skills/tew1-mod-production/`，AI 助手即可自动掌握 TEW1 二进制格式、引擎 RVA、断肢规则、D3D11 运行时与语音替换全套规范。

---

## 致谢

- 骨骼预设与换骨工作流设计参考了开源项目 **Modding-Toolkit**：https://github.com/Dimcirui/Modding-Toolkit

---

## 开源声明与联系方式

- **禁止大规模商业行为**：本仓库全部代码、工具与教程严禁用于大规模商业行为，包括但不限于**收费数额超过 300 RMB（人民币叁佰元）的定制项目**、商业倒卖或盈利性分发。
- **责任保留**：一旦发现违反上述条款，作者保留全部制作者法定权利，依法追究个人责任。
- **问题反馈 / 联系作者**：如有任何使用问题或反馈，请联系作者 QQ：**`2534594973`**
