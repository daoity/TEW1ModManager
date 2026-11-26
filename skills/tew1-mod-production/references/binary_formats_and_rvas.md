# TEW1 二进制格式、引擎 RVA 与 D3D11 运行时技术规范

## 1. 目标游戏二进制与内存挂载补丁

- **目标进程**：`EvilWithin.exe` (x64，支持双构建自动识别)：
  - **Steam 正版（2015-05-28，Build 2708258）**：SHA-256 `743df7a126a66470dbfc27b8c30348eea7d29bf948b82705da6e7babc6e67437`（`TimeDateStamp=0x5566C3D1`，`SizeOfImage=0x9F3D000`，启动时自动注入环境变量 `SteamAppId=268050` 与 `SteamGameId=268050` 以直连 Steam 客户端并保留挂载参数）
  - **经典 PC 构建（2015-05-15）**：SHA-256 `8737abc65d2b575cb6acb8c435dd7e2ce1053411a084b87f24e493b68df2c0ab`（`TimeDateStamp=0x5555AEBA`，`SizeOfImage=0x9F44000`）
- **外部挂载启动参数**：
  `+set fs_basepath "<游戏目录>" +set fs_installpath "<外部overlay目录>" +set resource_loadLooseFiles 1`
- **关键 RVA 对照表（`src/NativeLoader.cs`、`src/mount.py` & `runtime_src/tew1_dyn_runtime.cpp` v3.11）**：
  - `LooseResourceCheckOffset`：Steam 正版 `0x78EEF` / 经典构建 `0x787EF`（偏移 `+18` 字节由 `0x03` 改为 `0x05` 放行贴图与音频散文件，仅模型时为 `0x04`）。
  - `ModelOpenCallOffset`：Steam 正版 `0x18F69E` / 经典构建 `0x18F67E`（`.bmd6model` 散文件打开入口）。
  - `ImageOpenCallOffset`：Steam 正版 `0x1BB29B` / 经典构建 `0x1BA9DB`（`.bimage` 散文件打开入口）。
  - `WaveOpenCallOffset`：Steam 正版 `0x314821` / 经典构建 `0x3141A1`（`.wav` 散文件打开入口）。
  - `WaveLangSubCallOffset`：Steam 正版 `0x3145D2` (`e8 99 4e d6 ff`) / 经典构建 `0x313F52` (`e8 29 4d d6 ff`)，补丁为 `mov rax, r8; nop; nop`，使 `english/` 下的散装 `.wav` 在任意音频语言设置下命中。
  - `SoundLoadCallOffset`：Steam 正版 `0x3064F2` (`e8 59 0f 00 00`) / 经典构建 `0x305DB2` (`e8 49 0f 00 00`)；跳板优先调用 `idSoundSample::LoadWav`（Steam `0x306780` / 经典 `0x306040`），未命中则回落 `LoadGeneratedSound`（Steam `0x307450` / 经典 `0x306D00`）。
  - `XA2_SoundVoice::Start`：Steam 正版 `0x3190F0` / 经典构建 `0x318AC0`（运行时 DLL 内联跳板 Hook，自动触发受击与死亡表情）。
  - `IDXGISwapChain*` 全局指针：Steam 正版 `0x88BC8A8` / 经典构建 `0x88C38A0`。
  - `ID3D11Device*` 全局指针：Steam 正版 `0x88BC8C8` / 经典构建 `0x88C38C0`（v3.11 放宽 vtable 所属模块校验，兼容 Steam Overlay `GameOverlayRenderer64.dll` 等代理层）。
- **散文件覆盖边界**：`.bmd6model`、`.bimage`、`.wav`、新建自定义材质 `.decl` 可直接热挂载覆盖；原版已打包在 `.tangoresource` 内的 UI/声音 `.decl` 不保证被散文件覆盖。

---

## 2. `.bmd6model` 骨骼模型格式

- **魔数**：文件首尾各 4 字节 `1A 36 4D 4D` (`\x1a6MM`)。
- **骨骼区**：以 `\x06\0\0\0origin` 起始的 ASCII 长度前缀名表；父表（`>H`，根 `0xFFFF`）；四元数表；`remap` 字节映射表（8 字节对齐 padding）；`3x4` 大端逆绑定矩阵表。
- **表面区**：每个表面包含 `name`、`material`、头部 `\x01\x00\x00` + `vertCount (>H)` + `flags (2B)` + `triCount (>H)` + AABB (`>6f`)、顶点流、索引流 (`>u2` × `3*triCount`)、`trailer (11B)`。
- **32 字节顶点布局**：
  - `[0..11]`：3 × Big-Endian float32 位置 `(x, y, z)`
  - `[12..19]`：2 × Big-Endian float32 UV `(u, 1-v)`
  - `[20..22]`：3 × uint8 打包法线 `round((n * 0.5 + 0.5) * 255)`
  - `[23]`：1 × uint8 打包权重 `q1*16 + q2*4 + q3`（`w1=q1/30`, `w2=q2/9`, `w3=q3/12`, `w0=1-w1-w2-w3`）
  - `[24..27]`：3 × uint8 打包切线 + 1 × uint8 副切线符号（`255` 或 `0`）
  - `[28..31]`：4 × uint8 `remap` 后骨骼索引
- **安全红线**：总表面数 `<= 31`；每表面顶点数 `3..65535`、三角面数 `1..65535`；带 Havok 物理的原版槽（`m_hair`, `*__clt*`）保持原顶点数。

---

## 3. `.bimage` 贴图与前向材质 `.decl`

- **`.bimage` 格式**：46 字节大端头（魔数 `[4..8] = \x09MIB`，宽高在 `[16..24]`，mip 数量在 `[28..32]`，压缩格式 `[36]`：`10 = BC1/DXT1`，`11 = BC3/DXT5`），随后紧接各 mip 级 `pack(">5I", level, 0, w, h, size) + dds_bytes`。
- **绕过 Megatexture 的自定义前向材质 `.decl` 配方**：
  ```text
  stageprogram lppalbedoalphaforwardanisotropic
  depthfillprogram occluderhairtrans
  shadowprogram occludershadowblendhair
  velocityprogram velocityhair
  depthfillonlyprogram occluderhairdepthonlyblend
  ```
  - 底色贴图通过 `transmap "textures/<作者>/<材质名>_c"` 引用 `.bimage`。
  - **常规衣服 / 皮肤 / 贴身内衣（内裤、胸罩）**：必须使用 **BC1/DXT1 (`OPAQUE`)** + `force_opaque_alpha`，绝不可因贴图图集留白带 Alpha 而误用 BC3！
  - **睫毛 / 蕾丝镂空 (`CUTOUT`)**：使用 BC3/DXT5，`clipthreshold 0.33`，`twosided 1.0`。
  - **半透明透纱外套 (`SHEER_OUTER`)**：使用 BC3/DXT5，`clipthreshold 0.05`，`twosided 1.0`，并将对应表面放在 `.bmd6model` 最后槽位（确保身体/腿部/皮肤补丁/内衣先于外套绘制）。

---

## 4. `tew1_dyn.bin` v2 (`TEWH`) 动态物理/表情/自发光/差分服装数据包

全部小端序（Little-Endian），由 `tew1_dyn_runtime.dll`（v3.10+）在加载游戏时读取：

- **Header (32 B)**：`magic="TEWH"` + `<7I`: `version (=2)`, `nSkel`, `nChains (<=32)`, `nCols (<=16)`, `nHairFps`, `nFaces`, `nMorphs (=15)`
- **Section 1 — Skeleton Profiles (`nSkel`)**：
  - `headRemap (u8 + 3 pad)`
  - `colRemap[5] (5×i16 + 2 pad)` — 严格对应 `("head", "neck_00", "spine_02", "l_shoulder", "r_shoulder")`
  - `headAlign (12×f32)` — 3×4 刚体对齐矩阵（从作者绑定骨架到各章节模型骨架）
  - `drivers[7]` — 每项 `remap (i16 + 2 pad) + probe (3×f32)`（jaw, lidL, lidR, browL, browR, mcL, mcR）
- **Section 2 — Hair/Cloth/Chest Chains (`nChains`)**：
  - `numBones (u32), stiffness (f32), damping (f32), gravity (f32), radius (f32)`
  - `restNodes[(numBones+1) * 3×f32]`（作者骨架绑定空间）
  - 扩展锚定：可通过链头标志支持胸骨/躯干物理链（`anchorSlot = 3` 锚定 `spine_02`）与多段 `weightOffset`。
- **Section 3 — Capsule Colliders (`nCols`)**：
  - `boneSlot (u32, 0..4), startArm (3×f32), endArm (3×f32), radius (f32)`
- **Section 4 — Hair/Physics VB Fingerprints & Shared Weights**：
  - `nHairFps` 项：`headRemap (u8 + 3 pad), vertCount (u32), first3Pos (9×f32)`
  - 扩展多网格消歧：`pad3[1] == 2` 时使用 `v0 + vlast` 双端点指纹精确区分同顶点数/同起点表面。
  - `nHairVerts (u32, <=65536)` + `nHairVerts × 8B`（`boneIdx[4], weight_u8[4]`，`255` 表示刚性绑定 `head`）
- **Section 5 — Face Morph Surfaces (`nFaces`)**：
  - 每项：`headRemap (u8), part (u8), pad (2B), vertCount (u32), first3Pos (9×f32)`
  - 紧跟 15 个稀疏通道，每通道 `cnt (u32)` + `cnt × (vertIdx:u16, pad:u16, dx/dy/dz:3×f32)`
  - 15 通道顺序：`0:Blink, 1:WinkL, 2:WinkR, 3:A, 4:I, 5:U, 6:E, 7:O, 8:Smile, 9:SmileEyes, 10:Surprised, 11:BrowWorried, 12:BrowAngry, 13:BrowUp, 14:Frown`
- **Section 6 (v2) — Extra Character VBs (全身自发光)**：
  - `nExtra (u32, <=4096)` + `nExtra × (vertCount:u32, first3Pos:9×f32)`
- **Section 7 (可选，扩展差分服装 & 透纱标记)**：支持换装/隐藏部位差分分组与仅针对透纱外套的实时 4 档透明度切换。

---

## 5. D3D11 运行时 DLL (`tew1_dyn_runtime.cpp` v3.10) 关键架构

1. **Present 锁帧形变**：物理 XPBD/Verlet 积分与面部顶点形变统一在 `IDXGISwapChain::Present` 阶段提交 `UpdateSubresource`，确保 Depth Pre-Pass、Shadow Pass、Forward Color Pass、Velocity Pass 读到完全一致的顶点缓冲（彻底消除 Z-mismatch 变黑/重影）。
2. **多 Deferred Context 与 Win10/11 动态 vtable 重写防护**：
   - TEW1 渲染管线在跨章节时会创建大量 Deferred Context；Win10/11 `d3d11.dll` 会在 `PSSetShader` / `IASetVertexBuffers` 等状态调用后动态改写 vtable 槽 `[12]` (`DrawIndexed`)。
   - 必须 Hook `ID3D11Device::CreateDeferredContext`（槽 27），使用无锁每上下文表 `CtxBoundState g_ctxSlots[512]`（v3.10 已由 128 扩至 512）隔离绑定状态，并在状态钩子返回后调用 `ReassertDrawHooks()` 重新钉住 `vt[12]` / `vt[20]`。
3. **跨章节防崩溃（COM 生命周期钉住 + 120 帧自动 GC）**：
   - **根因**：TEW1 切换章节（如 Ch1 → Ch2）时会释放旧章节 `ID3D11Buffer*`，若运行时表持有裸指针并在 `Present` / `DrawIndexed` 中调用 `UpdateSubresource` 或切换 VB，会触发 `nvwgf2umx.dll` `0xc0000005` UAF 闪退。
   - **v3.10 根治方案**：追踪任何 VB 时写入 `g_pinnedVBs` 并 `AddRef()`；在 `GetSheerDrawPlan` 返回 `plan.vbToDraw` 前额外 `AddRef()`、绘制后 `Release()`；每 120 帧执行 `GarbageCollectUnloadedVBs()`，一旦检测游戏侧引用归零（`refcount == 1`）即自动 `Release` 并从追踪表移除；`g_sheerDSSCache` 与 `g_sheerRSCache` 使用**描述体值哈希键**（严禁用裸指针做 Key，避免地址复用碰撞）。
4. **仅外套双面半透明透纱管线（4 档可调）**：
   - 透纱外套开启半透明时：原始 VB 写入 `NaN`（让 Depth Pre-Pass 零遮挡内部皮肤/内衣），同时维护带实时胸物理的孪生 `sheerVB`；在 Forward Color Pass 切换至 `sheerVB` + 自动识别 Z 方向的 `DepthWriteMask=ZERO` 深度模板状态 + 克隆 `D3D11_CULL_NONE` 双面光栅化状态，并在像素着色器中分离 `heartMask = smoothstep(0.90, 0.98, opacity)`（花纹保持 100% 实色，白纱按 4 档映射：`0=不透明 100%`, `1=高透纱 22-46%`, `2=中透纱 42-62% [默认]`, `3=微透纱 60-78%`）。
5. **严格 4 着色器自发光过滤**：
   - 在 `CreatePixelShader` 扫描字节码，**仅**标记同时存在 `samp_tex_transmap` + `samp_tex_lightprepasslightbuffer` + `samp_tex_hairlut` 的 4 个前向彩色着色器（`lppalbedoalphaforwardanisotropic*`、`lppalbedoalphahair`）。
   - 严禁兜底放宽到无标签 PS，否则深度/阴影通道会被替换成彩色输出导致面部大片发黑。
6. **游戏内热键（v3.10 自定义快捷键，避免冲突）**：
   - **`` ` ``（Tab 上方反引号/波浪键 `VK_OEM_3`，默认）**：开关局内服装差分 / 透纱档位 / 自发光 / 热键设置悬浮面板（不再使用会与原版管理器冲突的 `Insert`）；在面板按 `[9]` 进入「等待按键」可实时自定义为任意键（`ESC` 取消），自动持久化保存到 DLL 同级 `tew1_dyn_hotkey.ini`。
   - **`F7` / `F8` / `F9`**：三档角色自发光（柔和 / 明亮二次元 / 全亮无阴影，再按关闭）。
   - **`F10`**：调试受击表情（`Shift+F10` 锁定受击，`Ctrl+F10` 锁定死亡）。
