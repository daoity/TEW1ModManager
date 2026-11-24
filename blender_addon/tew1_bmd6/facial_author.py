"""TEW Facial authoring tools:
Core 5-slot Shape Key mapper (Blink / Hurt A / BrowWorried / BrowAngry / SmileEyes),
live in-game expression preview (Idle / Blink / Hurt / Death), starter Shape Key generator,
and 1-click native CG mouth jaw weight generator from the 'A' Shape Key."""

import json

import bpy
from bpy.props import EnumProperty, FloatProperty, PointerProperty, StringProperty
import numpy as np

FACIAL_MAP_PROP = "tew1_facial_map"

CORE_FACIAL_SLOTS = (
    ("Blink",       "slot_blink",       "自然眨眼 (Blink)",      "游戏内自动眨眼与死亡闭眼所用的形态键（如 まばたき / Blink / 眨眼）"),
    ("A",           "slot_a",           "受击微张嘴 (A)",        "受击微张嘴（幅度自动限幅 0.28 防穿下牙）与一键生成 CG 嘴骨权重所用的张嘴形态键（如 あ / A / vrc.v_aa）"),
    ("BrowWorried", "slot_brow_worried","痛苦/愁眉 (Worried)",   "受击和死亡时自动触发的愁眉形态键（如 困る / Sad / Worried / 担忧）"),
    ("BrowAngry",   "slot_brow_angry",  "皱眉/咬牙 (Angry)",     "受击时自动触发的皱眉痛感形态键（如 怒り / Angry / 生气）"),
    ("SmileEyes",   "slot_smile_eyes",  "痛感眯眼 (SmileEyes)",  "受击瞬间辅助紧闭双眼的形态键（如 笑い / Joy / 笑眼，可留空）"),
)


def read_facial_map(obj):
    if obj is None or obj.type != "MESH":
        return {}
    raw = obj.get(FACIAL_MAP_PROP, "{}")
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_facial_map(obj, data):
    if obj is not None and obj.type == "MESH":
        obj[FACIAL_MAP_PROP] = json.dumps(data, ensure_ascii=False)


def _sync_slot_to_mesh(slot_key, prop_name):
    def _updater(self, context):
        obj = context.object
        if obj is None or obj.type != "MESH":
            return
        fmap = read_facial_map(obj)
        val = getattr(self, prop_name, "").strip()
        if val:
            fmap[slot_key] = val
        else:
            fmap.pop(slot_key, None)
        write_facial_map(obj, fmap)
    return _updater


def load_mesh_slots_into_scene(context, obj):
    """Sync active mesh's stored facial map (or auto-matched aliases) into UI fields."""
    from .dyn_export import CHANNEL_ALIASES, _match_shape_key
    st = context.scene.tew1_facial
    fmap = read_facial_map(obj)
    kbs = obj.data.shape_keys.key_blocks if (obj and obj.type == "MESH" and obj.data.shape_keys) else None
    alias_lookup = dict(CHANNEL_ALIASES)
    changed = False
    for ch_key, prop_name, _, _ in CORE_FACIAL_SLOTS:
        chosen = fmap.get(ch_key, "")
        if kbs and (not chosen or chosen not in kbs):
            kb = _match_shape_key(kbs, alias_lookup.get(ch_key, ()))
            chosen = kb.name if kb else ""
            if chosen:
                fmap[ch_key] = chosen
                changed = True
        if getattr(st, prop_name) != chosen:
            setattr(st, prop_name, chosen)
    if changed and obj and obj.type == "MESH":
        write_facial_map(obj, fmap)


class TEW1FacialSettings(bpy.types.PropertyGroup):
    slot_blink: StringProperty(
        name="自然眨眼",
        default="",
        description="选择用于游戏内自然眨眼和死亡闭眼的形态键（如 まばたき / Blink / 眨眼）",
        update=_sync_slot_to_mesh("Blink", "slot_blink"),
    )
    slot_a: StringProperty(
        name="受击张嘴",
        default="",
        description="选择用于受击微张嘴（游戏内自动压到 0.28 防下牙穿模）及推导 CG 嘴骨权重的张嘴形态键（如 あ / A）",
        update=_sync_slot_to_mesh("A", "slot_a"),
    )
    slot_brow_worried: StringProperty(
        name="愁眉/痛苦",
        default="",
        description="选择受击和死亡时自动触发的愁眉形态键（如 困る / Worried / Sad）",
        update=_sync_slot_to_mesh("BrowWorried", "slot_brow_worried"),
    )
    slot_brow_angry: StringProperty(
        name="皱眉/咬牙",
        default="",
        description="选择受击瞬间自动触发的皱眉形态键（如 怒り / Angry / 生气）",
        update=_sync_slot_to_mesh("BrowAngry", "slot_brow_angry"),
    )
    slot_smile_eyes: StringProperty(
        name="痛感眯眼",
        default="",
        description="选择受击瞬间辅助紧闭双眼的形态键（如 笑い / Joy / SmileEyes，可不填）",
        update=_sync_slot_to_mesh("SmileEyes", "slot_smile_eyes"),
    )
    jaw_strength: FloatProperty(
        name="CG 嘴骨权重强度",
        default=0.72,
        min=0.1,
        max=1.0,
        description="从张嘴形态键自动推导原生 jaw 骨骼权重的最大比例，推荐 0.65~0.80（避免下牙穿模）",
    )


class TEW1AutoDetectFacialKeys(bpy.types.Operator):
    bl_idname = "object.tew1_autodetect_facial_keys"
    bl_label = "一键自动匹配 MMD / VRChat 表情形态键"
    bl_description = "自动扫描当前选中面部网格的 Shape Keys，按 MMD 日文 / VRChat 英文 / 中文别名填入 5 个核心表情槽位"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH")

    def execute(self, context):
        obj = context.object
        if not obj.data.shape_keys or len(obj.data.shape_keys.key_blocks) <= 1:
            self.report({"WARNING"}, "当前网格还没有形态键；若是无形态键模型，可点击下方「一键新建空白核心表情形态键」。")
            return {"CANCELLED"}
        load_mesh_slots_into_scene(context, obj)
        fmap = read_facial_map(obj)
        self.report({"INFO"}, f"已自动匹配 {len(fmap)}/5 个核心表情槽位：" + (", ".join(f"{k}={v}" for k, v in fmap.items()) or "无"))
        return {"FINISHED"}


class TEW1CreateStarterShapeKeys(bpy.types.Operator):
    bl_idname = "object.tew1_create_starter_shapekeys"
    bl_label = "一键新建空白核心表情形态键（无形态键模型用）"
    bl_description = "为没有自带表情的模型自动创建 Basis 与 Blink / A / BrowWorried / BrowAngry / SmileEyes 空白形态键并绑定好槽位，之后直接进入雕刻模式用抓起笔刷微调即可"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH")

    def execute(self, context):
        obj = context.object
        mesh = obj.data
        if not mesh.shape_keys:
            obj.shape_key_add(name="Basis", from_mix=False)
        existing = {kb.name for kb in mesh.shape_keys.key_blocks}
        created = 0
        fmap = read_facial_map(obj)
        for ch_key, _, _, _ in CORE_FACIAL_SLOTS:
            if ch_key not in existing:
                obj.shape_key_add(name=ch_key, from_mix=False)
                created += 1
            fmap[ch_key] = ch_key
        write_facial_map(obj, fmap)
        load_mesh_slots_into_scene(context, obj)
        self.report({"INFO"}, f"已新建 {created} 个核心表情形态键并自动完成绑定，选中对应形态键即可在雕刻/编辑模式手作捏脸。")
        return {"FINISHED"}


class TEW1PreviewFacial(bpy.types.Operator):
    bl_idname = "object.tew1_preview_facial"
    bl_label = "实时预览游戏内表情状态"
    bl_description = "按游戏内 tew1_dyn_runtime.dll 的真实权重组合，在 Blender 视口预览当前网格的待机 / 眨眼 / 受击 / 死亡表情，方便直观检查是否穿模"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        name="预览状态",
        items=[
            ("IDLE",  "待机归零", "将全部表情形态键归零，恢复自然待机脸"),
            ("BLINK", "自然眨眼", "预览游戏内自动眨眼（Blink = 1.0）"),
            ("HURT",  "受击表情", "预览游戏内受击痛感（愁眉 0.85 + 皱眉 0.65 + 眯眼 0.60 + 微张嘴 0.28）"),
            ("DEATH", "死亡表情", "预览游戏内死亡表情（闭眼 1.0 + 愁眉 0.75 + 微张嘴 0.12）"),
        ],
        default="IDLE",
    )

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH" and context.object.data.shape_keys)

    def execute(self, context):
        obj = context.object
        kbs = obj.data.shape_keys.key_blocks
        fmap = read_facial_map(obj)
        if not fmap:
            load_mesh_slots_into_scene(context, obj)
            fmap = read_facial_map(obj)

        # Reset all mapped keys to 0
        for kb in kbs:
            kb.value = 0.0

        weights = {
            "IDLE":  {},
            "BLINK": {"Blink": 1.0},
            "HURT":  {"BrowWorried": 0.85, "BrowAngry": 0.65, "SmileEyes": 0.60, "A": 0.28},
            "DEATH": {"Blink": 1.0, "BrowWorried": 0.75, "A": 0.12},
        }[self.preset]

        applied = 0
        for ch_key, w in weights.items():
            kname = fmap.get(ch_key)
            if kname and kname in kbs:
                kbs[kname].value = w
                applied += 1
        obj.data.update()
        self.report({"INFO"}, f"已切换视口表情预览：{self.preset}（驱动 {applied} 个通道）")
        return {"FINISHED"}


class TEW1GenerateCGMouthWeights(bpy.types.Operator):
    bl_idname = "object.tew1_generate_cg_mouth_weights"
    bl_label = "一键从张嘴形态键生成原生 CG 嘴骨权重 (jaw)"
    bl_description = "读取当前面部网格的「受击张嘴 (A)」形态键位移，自动把下唇/下巴/下牙顶点平滑分配权重给 TEW1 原生 jaw（及 CG 过场嘴角/唇骨），让 CG 过场动画里角色嘴巴自然会动"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH")

    def execute(self, context):
        from .hair_author import rig_object
        obj = context.object
        rig = rig_object(context)
        if rig is None or "jaw" not in rig.data.bones:
            self.report({"ERROR"}, "当前面部网格所属骨架缺少 TEW1 原生 'jaw' 骨骼，请先完成换骨绑定到 TEW1 模板骨架。")
            return {"CANCELLED"}
        mesh = obj.data
        if not mesh.shape_keys or len(mesh.shape_keys.key_blocks) <= 1:
            self.report({"ERROR"}, "请先准备并绑定「受击张嘴 (A)」形态键，插件需要用它的位移来识别嘴唇和下巴顶点。")
            return {"CANCELLED"}

        fmap = read_facial_map(obj)
        if not fmap.get("A"):
            load_mesh_slots_into_scene(context, obj)
            fmap = read_facial_map(obj)
        a_name = fmap.get("A", "")
        kbs = mesh.shape_keys.key_blocks
        if not a_name or a_name not in kbs:
            self.report({"ERROR"}, "未绑定有效的张嘴形态键 (A)，请在上方「受击张嘴」下拉框中选择。")
            return {"CANCELLED"}

        n = len(mesh.vertices)
        basis = kbs[0]
        target = kbs[a_name]
        bco = np.empty(n * 3, dtype=np.float32)
        tco = np.empty(n * 3, dtype=np.float32)
        basis.data.foreach_get("co", bco)
        target.data.foreach_get("co", tco)
        bco = bco.reshape(-1, 3)
        tco = tco.reshape(-1, 3)

        # Transform displacement to armature space so Z is vertical up/down
        to_arm = np.array(rig.matrix_world.inverted_safe() @ obj.matrix_world, dtype=np.float64)
        delta_arm = (tco - bco) @ to_arm[:3, :3].T
        down = -delta_arm[:, 2]  # downward opening displacement
        mag = np.linalg.norm(delta_arm, axis=1)
        max_down = float(down.max())
        if max_down < 1e-4:
            self.report({"ERROR"}, f"形态键 '{a_name}' 未检测到向下的张嘴顶点位移。")
            return {"CANCELLED"}

        strength = float(context.scene.tew1_facial.jaw_strength)
        vg_head = obj.vertex_groups.get("head") or obj.vertex_groups.new(name="head")
        vg_jaw = obj.vertex_groups.get("jaw") or obj.vertex_groups.new(name="jaw")

        # Optional 9-bone CG mouth support (pl0010_ng / pl0011_ng / pl0012_ng / pl0210_ng)
        has_corner = ("mouth_u_l_corner" in rig.data.bones and "mouth_u_r_corner" in rig.data.bones)
        vg_cl = (obj.vertex_groups.get("mouth_u_l_corner") or obj.vertex_groups.new(name="mouth_u_l_corner")) if has_corner else None
        vg_cr = (obj.vertex_groups.get("mouth_u_r_corner") or obj.vertex_groups.new(name="mouth_u_r_corner")) if has_corner else None

        pts_arm = bco @ to_arm[:3, :3].T + to_arm[:3, 3]
        head_x = float(rig.data.bones["head"].head_local.x)

        updated = 0
        for vi in range(n):
            if mag[vi] < max_down * 0.08:
                continue
            # Lower mouth / jaw vertices move down significantly
            if down[vi] > max_down * 0.12:
                ratio = min(1.0, float(down[vi] / max_down))
                w_jaw = strength * (ratio ** 0.85)
                # Preserve existing non-head weights if any, split head weight between head & jaw
                try:
                    w_head = vg_head.weight(vi)
                except RuntimeError:
                    w_head = 1.0
                assign = w_head * w_jaw
                vg_head.add([vi], max(0.0, w_head - assign), "REPLACE")
                vg_jaw.add([vi], assign, "REPLACE")
                updated += 1
            elif has_corner and abs(delta_arm[vi, 0]) > max_down * 0.12:
                # Subtle mouth corner stretch for CG cutscenes
                vg_c = vg_cl if (pts_arm[vi, 0] >= head_x) else vg_cr
                ratio = min(0.45, float(mag[vi] / max_down) * 0.5)
                try:
                    w_head = vg_head.weight(vi)
                except RuntimeError:
                    w_head = 1.0
                assign = w_head * ratio
                vg_head.add([vi], max(0.0, w_head - assign), "REPLACE")
                vg_c.add([vi], assign, "REPLACE")
                updated += 1

        self.report({"INFO"}, f"已从形态键 '{a_name}' 自动生成原生 CG 嘴骨权重（写入 {updated} 个嘴部顶点，强度 {strength:.2f}）。")
        return {"FINISHED"}


CLASSES = (
    TEW1FacialSettings,
    TEW1AutoDetectFacialKeys,
    TEW1CreateStarterShapeKeys,
    TEW1PreviewFacial,
    TEW1GenerateCGMouthWeights,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tew1_facial = PointerProperty(type=TEW1FacialSettings)


def unregister():
    del bpy.types.Scene.tew1_facial
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
