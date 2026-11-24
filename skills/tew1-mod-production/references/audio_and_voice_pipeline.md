# TEW1 主角语音替换、响度补偿与原生对话静音规范

## 1. 散装 `.wav` 目录与底层挂载机制

- **覆盖路径**：`base/sound/voice_talk/english/ingame_voice/sebastian/<原文件名>.wav`
- **跨语言生效原理**：
  - `NativeLoader.cs` 将 `WaveLangSubCallOffset (0x313F52)` 补丁为 `mov rax, r8; nop; nop`，跳过引擎把 `english/` 替换成当前系统语言目录的行为，使单份 `english/` 散装音频在所有语言下通用。
  - `SoundLoadCallOffset (0x305DB2)` 跳板优先调用 `idSoundSample::LoadWav (0x306040)`；命中散装 `.wav` 时置 `streamFile = NULL ([rcx+0x68]=0)`、`loadState = 1 ([rcx+0xC4]=1)`，否则回退 `LoadGeneratedSound (0x306D00)`。

---

## 2. 动作 / 受击 / QTE 语音处理与响度补偿

- **为什么受击语音常听不见？**
  - 原版声学声明中，`damage_shot.decl` 施加了 **`-7 dB`** 衰减，`damage_slashed.decl` 施加了 **`-9 dB`** 衰减，且受击瞬间同时叠加枪声/挥砍/血溅 SFX。
- **处理标准（参考 `runtime_src/build_haruka_voice_pack.py`）**：
  1. **保留完整尾音**：不要激进裁剪末尾静音/气声，避免听感生硬。
  2. **软削波限幅与响度抬升**：受击语音用 `tanh` 软膝限幅将目标 RMS 抬升至 **`-5.5 ~ -6.0 dB`**（普通动作/喘息约 `-9 ~ -11 dB`），单声道 16-bit PCM WAV（推荐 44100 Hz 或 22050 Hz）。
  3. **按受击类型严格分类**：轻受击、重受击（带“重”标记）、枪击、利器砍伤、灼烧、坠落、死亡分别映射到对应 `sebastian` 受击事件名。
  4. **被抓取 QTE 循环语音**：若素材缺少独立抓取挣扎语音，将两条挣扎语音首尾淡入淡出合并为无缝循环 WAV。

---

## 3. 静音剩余原版主角对话（保持字幕与过场 100% 同步）

- **千万不要用 0.05 秒短静音替代长对白！** 否则游戏内字幕会瞬间跳过、部分剧情脚本会提前触发或错位。
- **正确做法**：
  1. 扫描原版 `.tangoresource` 中剩余所有主角对话 `.bsnd`，解析其精确采样数与采样率，算出真实秒数 `duration`。
  2. 生成**等时长**的 **8000 Hz、单声道、8-bit unsigned PCM（全部填充 `0x80` 零电平）** 静音 `.wav`。
  3. 体积极小（约 8 KB/秒，300+ 条静音文件压缩后仅几百 KB），且完美保留所有字幕停留时间与过场节奏。

---

## 4. 独立功能性语音 Mod 打包格式

在独立 ZIP 根目录放入 `mod.info`：
```ini
name=Haruka 主角动作受击语音包
author=YourName
version=1.0
type=voice
description=替换主角动作/受击/QTE语音并静音剩余原版对话，支持管理器独立开关
```
`TEW1ModManager.exe` 会将 `type=voice` 识别为功能性语音 Mod，允许与任意角色模型 Mod 自由组合并单独勾选启用/关闭。
