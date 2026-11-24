# TEW1 全章节模型、断肢 `meshKits` 与原生 CG 嘴型规范

## 1. 全章节主角模型清单与断肢道具

- **主游玩/过场全套模型**：
  - `pl0000_ng`（常规全章节核心模型，共 31 表面上限最紧张！）
  - `pl0010_ng`, `pl0011_ng`, `pl0012_ng`, `pl0210_ng`（CG/特写多嘴骨头模）
  - `pl0017_ng`, `pl0018_ng`, `pl0020_ng`（特殊章节服装/病院/终章变体）
  - `pl0201_ng`, `pl0220_*`, `pl0230_ng`, `em5002_ng`（变体/特殊剧情模型）
- **断肢独立掉落道具模型**：
  - `pl0001_ng`：被斩下的独立头颅（必须包含自定义头发与头饰，槽位放 `m_face1`）
  - `pl0002`：断右臂 | `pl0003`：断左臂 | `pl0004`：断右腿 | `pl0005`：断左腿 | `pl0008`：断右手

---

## 2. 断肢 `meshKits` 核心机制（`pl0000.md6.decl`）

1. **引擎表面匹配逻辑（RVA `0x17A260`）**：
   - 引擎按 `meshKit` 名称表遍历全部表面，**所有名称匹配的表面都会被同时隐藏或显示**（因此允许存在多个同名 `m_face` 表面，非常适合放自定义脸、头发、发饰！）。
2. **严禁踩雷的“断头残留”陷阱槽**：
   - `m_beard`, `m_beard1`, `m_Cornea`：在 `headdamage`（爆头/部分断头）状态仍保持可见！
   - `m_vest__nv`, `m_holster__lt`, `m_coat_button`, `m_hand_r`, `m_necktie`：属于身体槽，在 `headless` / `headdamage` 处决时完全不隐藏！
   - **正确做法**：自定义头发、眉毛、睫毛、面部、发饰**一律**放到真头部槽：
     - `pl0000_ng` / `pl0017_ng` / `pl0018_ng` / `pl0220_*` / `pl0230_ng` / `em5002_ng` → `m_face`
     - `pl0020_ng` → `m_mouth3`
     - `pl0201_ng` → `m_tong`
3. **四肢断肢拆分规则（以 `pl0000_ng` 为例）**：
   - 若将整件衣服/身体全塞在 `m_shirt__nn`，断臂/断腿处决时肢体不会消失。
   - 正确拆分（Blender 插件 `TEW Mesh` 提供一键自动按骨骼权重拆分按钮）：
     - 躯干 → `m_shirt__nn`
     - 左臂（`l_shoulder/l_upperarm/l_forearm/l_hand/l_手指*`） → `m_hand_l`
     - 右臂（`r_shoulder/r_upperarm/r_forearm/r_hand/r_手指*`） → `m_r_shrit_arm__na`
     - 双腿/靴子（`l/r_thigh`, `l/r_shin`, `l/r_foot`, `l/r_toe`） → `m_pants_leg__np`
4. **总表面数 `<= 31` 与 Havok `m_hair` 规则**：
   - 原版 `m_hair` 保留原始顶点数，仅将三角面索引设为零面积退化三角形 `(0, 0, 0)`，防止 Havok `.clh` 布料初始化崩溃。
   - 若新增了自定义表面导致总数 `> 31`，必须合并同材质/同断肢槽部件或复用安全空槽，确保总表面 `<= 31`。

---

## 3. 原生 9 骨 CG 嘴型与受击/死亡表情协调

- **为什么嘴部必须走原生骨骼？**
  - 游戏 CG 过场和对话由原生骨架驱动 `jaw` 与嘴周骨骼；如果运行时 DLL 长期覆写嘴部顶点或未给嘴唇/下牙刷 `jaw` 权重，CG 里主角说话嘴巴不会动。
- **原生 9 根嘴骨映射（`patch_haruka_mouth_jaw.py`）**：
  - 高精度头模（`pl0010_ng`, `pl0011_ng`, `pl0012_ng`, `pl0210_ng`）：`jaw`, `mouth_u_middle`, `mouth_u_l`, `mouth_u_r`, `mouth_d_middle`, `mouth_d_l`, `mouth_d_r`, `mouth_u_l_corner`, `mouth_u_r_corner`, `mouth_d_l_corner`, `mouth_d_r_corner`。
  - 全部 16 个头模：下唇、下牙齿、舌头顶点（`LOWER_MOUTH`）赋予平滑 `jaw` 权重，确保张嘴时不穿模。
- **运行时形态键幅度纪律**：
  - 待机与 CG 过场：`M_A` 等嘴型形态键保持 `0.0`，完全交由原生骨架驱动。
  - 眨眼：仅驱动 `M_BLINK`。
  - 受击：驱动皱眉/愁眉/眯眼，并叠加轻度 `M_A = 0.28`（严禁开到 `0.6+`，否则下牙齿容易穿出下巴）。
  - 死亡：闭眼 + 愁眉 + 极微张嘴 `M_A = 0.12`。

## 4. 读取 `.tangoresource` 重复记录避坑
- 在 `claws_of_the_horde.tangoresource` 等档案中，`pl0000.md6.decl` 存在多条同名条目；读取时若 `len(entries) > 1`，应取体积最大的记录并用 `zlib.decompressobj(-15)` 原始 deflate 解压。
