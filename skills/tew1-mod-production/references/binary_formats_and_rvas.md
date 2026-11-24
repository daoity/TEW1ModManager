# TEW1 二进制格式、引擎 RVA 与 D3D11 运行时技术规范

## 1. 目标游戏二进制与内存挂载补丁

- **目标进程**：`EvilWithin.exe` (x64, SHA-256 `8737abc65d2b575cb6acb8c435dd7e2ce1053411a084b87f24e493b68df2c0ab`)
- **外部挂载启动参数**：
  `+set fs_basepath "<游戏目录>" +set fs_installpath "<外部overlay目录>" +set resource_loadLooseFiles 1`
- **关键 RVA 表（`src/NativeLoader.cs` & `src/mount.py`）**：
  - `0x787EF` (`LooseResourceCheckOffset`)：偏移 `+18` 字节由 `0x03` 改为 `0x05`（放行贴图与音频散文件，仅模型时为 `0x04`）。
  - `0x18F67E` (`ModelOpenCallOffset`)：`.bmd6model` 散文件打开入口。
  - `0x1BA9DB` (`ImageOpenCallOffset`)：`.bimage` 散文件打开入口。
  - `0x3141A1` (`WaveOpenCallOffset`)：`.wav` 散文件打开入口。
  - `0x313F52` (`WaveLangSubCallOffset`)：补丁为 `mov rax, r8; nop; nop`，使 `english/` 下的散装 `.wav` 在中文/日文/英文等任意音频语言设置下都能命中。
  - `0x305DB2` (`SoundLoadCallOffset`)：跳板优先调用 `idSoundSample::LoadWav` (`0x306040`)；若命中散装 `.wav`，清零 `streamFile` (`[rcx+0x68]=0`) 并置 `loadState=1` (`[rcx+0xC4]=1`)；未命中则回落原 `LoadGeneratedSound` (`0x306D00`)。
  - `0x318AC0` (`XA2_SoundVoice::Start`)：运行时 DLL 内联跳板 Hook，监听受击/死亡语音播放以自动触发受击与死亡表情。
  - `0x88C38A0`：`IDXGISwapChain*` 全局指针。
  - `0x88C38C0`：`ID3D11Device*` 全局指针。
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
  - 透明裁切（睫毛/蕾丝/透明发梢）使用 BC3/DXT5 并配置 `clipthreshold` 与 `twosided`。

---

## 4. `tew1_dyn.bin` v2 (`TEWH`) 动态物理/表情/自发光数据包

全部小端序（Little-Endian），由 `tew1_dyn_runtime.dll` 在加载游戏时读取：

- **Header (32 B)**：`magic="TEWH"` + `<7I`: `version (=2)`, `nSkel`, `nChains (<=32)`, `nCols (<=16)`, `nHairFps`, `nFaces`, `nMorphs (=15)`
- **Section 1 — Skeleton Profiles (`nSkel`)**：
  - `headRemap (u8 + 3 pad)`
  - `colRemap[5] (5×i16 + 2 pad)` — 严格对应 `("head", "neck_00", "spine_02", "l_shoulder", "r_shoulder")`
  - `headAlign (12×f32)` — 3×4 刚体对齐矩阵（从作者绑定骨架到各章节模型骨架）
  - `drivers[7]` — 每项 `remap (i16 + 2 pad) + probe (3×f32)`（jaw, lidL, lidR, browL, browR, mcL, mcR）
- **Section 2 — Hair/Cloth Chains (`nChains`)**：
  - `numBones (u32), stiffness (f32), damping (f32), gravity (f32), radius (f32)`
  - `restNodes[(numBones+1) * 3×f32]`（作者骨架绑定空间）
- **Section 3 — Capsule Colliders (`nCols`)**：
  - `boneSlot (u32, 0..4), startArm (3×f32), endArm (3×f32), radius (f32)`
- **Section 4 — Hair VB Fingerprints & Shared Weights**：
  - `nHairFps` 项：`headRemap (u8 + 3 pad), vertCount (u32), first3Pos (9×f32)`
  - `nHairVerts (u32, <=65536)` + `nHairVerts × 8B`（`boneIdx[4], weight_u8[4]`，`255` 表示刚性绑定 `head`）
- **Section 5 — Face Morph Surfaces (`nFaces`)**：
  - 每项：`headRemap (u8), part (u8), pad (2B), vertCount (u32), first3Pos (9×f32)`
  - 紧跟 15 个稀疏通道，每通道 `cnt (u32)` + `cnt × (vertIdx:u16, pad:u16, dx/dy/dz:3×f32)`
  - 15 通道顺序：`0:Blink, 1:WinkL, 2:WinkR, 3:A, 4:I, 5:U, 6:E, 7:O, 8:Smile, 9:SmileEyes, 10:Surprised, 11:BrowWorried, 12:BrowAngry, 13:BrowUp, 14:Frown`
- **Section 6 (v2) — Extra Character VBs (全身自发光)**：
  - `nExtra (u32, <=4096)` + `nExtra × (vertCount:u32, first3Pos:9×f32)`

---

## 5. D3D11 运行时 DLL (`tew1_dyn_runtime.cpp`) 关键架构

1. **Present 锁帧形变**：物理 XPBD/Verlet 积分与面部顶点形变统一在 `IDXGISwapChain::Present` 阶段提交 `UpdateSubresource`，确保 Depth Pre-Pass、Shadow Pass、Forward Color Pass、Velocity Pass 读到完全一致的顶点缓冲（彻底消除 Z-mismatch 变黑/重影）。
2. **多 Deferred Context 与 Win10/11 动态 vtable 重写防护**：
   - TEW1 渲染管线会创建 30+ 个 Deferred Context；Win10/11 `d3d11.dll` 会在 `PSSetShader` / `IASetVertexBuffers` 等状态调用后动态改写 vtable 槽 `[12]` (`DrawIndexed`)。
   - 必须 Hook `ID3D11Device::CreateDeferredContext`（槽 27），使用无锁每上下文表 `CtxBoundState g_ctxSlots[128]` 隔离绑定状态，并在状态钩子返回后调用 `ReassertDrawHooks()` 重新钉住 `vt[12]` / `vt[20]`。
3. **严格 4 着色器自发光过滤**：
   - 在 `CreatePixelShader` 扫描字节码，**仅**标记同时存在 `samp_tex_transmap` + `samp_tex_lightprepasslightbuffer` + `samp_tex_hairlut` 的 4 个前向彩色着色器（`lppalbedoalphaforwardanisotropic*`、`lppalbedoalphahair`）。
   - 严禁兜底放宽到无标签 PS，否则深度/阴影通道会被替换成彩色输出导致面部大片发黑。
4. **游戏内热键**：
   - `F7`：柔和自发光（Soft，再按关闭）
   - `F8`：明亮二次元自发光（Bright，再按关闭）
   - `F9`：全亮无阴影自发光（Full Unlit，再按关闭）
   - `F10`：调试受击表情（`Shift+F10` 锁定受击，`Ctrl+F10` 锁定死亡；正常表情开关仅由 Mod 管理器勾选控制）
