"""TEW Physical authoring engine: bone chains, presets, auto-detection, interactive 5-slot colliders & viewport bake."""

import json
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix, Vector

from .compat import active_slot_id, copy_action_slot, insert_pose_keyframe, set_pose_bone_select
from .hair_solver import HairChain, collider_point


PROFILE = "tew1_hair_profile"
FORMAT = "tew1-hair-authoring-v1"
HELPER = "tew1_hair_collider_display"
HELPER_NAME = "tew1_collider_name"
HELPER_ROLE = "tew1_collider_role"   # "start", "mid", "end"
PREVIEW = "tew1_hair_baked"
SOURCE_ACTION = "tew1_hair_source_action"
SOURCE_POSE = "tew1_hair_source_pose"

MAX_RUNTIME_CHAINS = 32
MAX_RUNTIME_COLLIDERS = 16

COLLIDER_BONE_SLOTS = (
    ("head", "头部"),
    ("neck_00", "颈部"),
    ("spine_02", "胸背"),
    ("l_shoulder", "左肩"),
    ("r_shoulder", "右肩"),
)

# Curated physics presets (stiffness, damping, gravity, strand_radius, label, desc)
PHYSICS_PRESETS = {
    "SOFT_LONG_HAIR": (95.0,  0.22, 14.0, 0.35, "柔软长发",       "自然飘动长发/双马尾，兼顾回弹与防穿模"),
    "CALM_SIDE_LOCKS": (520.0, 0.50,  3.0, 0.30, "稳重低幅侧发",   "实机推荐侧发/鬓角（高阻尼低重力，不炸毛不遮眼）"),
    "LIGHT_BANGS":    (180.0, 0.28,  9.0, 0.25, "轻飘刘海",       "前额刘海，较小摆动幅度，避免遮挡眼睛"),
    "RIGID_BANGS":    (700.0, 0.56,  1.8, 0.25, "近刚性贴额刘海", "实机推荐前刘海微动参数（或直接不加链锁死防穿额）"),
    "SIDE_LOCKS":     (140.0, 0.25, 11.0, 0.30, "灵动侧发",       "较灵动的鬓角/侧刘海，贴合脸颊"),
    "RIBBON_ACC":     (75.0,  0.18, 16.0, 0.28, "丝带 / 发带",    "轻盈飘带、发饰挂件，摆动更明显"),
    "STIFF_SKIRT":    (220.0, 0.32, 15.0, 0.45, "硬挺衣摆/裙摆",  "裙摆、大衣下摆，高回弹防穿透腿部"),
}

DEFAULT_CHAIN_KEYWORDS = "hair,bang,lock,ponytail,twin,ribbon,braid,skirt,cape,tail,cloth,髪,发,刘海,马尾,飘带,裙,衣摆"


def rig_object(context):
    obj = context.object
    if obj and obj.type == "ARMATURE":
        return obj
    if obj and obj.parent and obj.parent.type == "ARMATURE":
        return obj.parent
    return obj.find_armature() if obj and obj.type == "MESH" else None


def profile(rig):
    raw = rig.get(PROFILE, '{"chains":[],"colliders":[]}')
    try:
        data = json.loads(raw)
    except Exception:
        data = {"chains": [], "colliders": []}
    data.setdefault("chains", [])
    data.setdefault("colliders", [])
    return data


def set_profile(rig, data):
    rig[PROFILE] = json.dumps(data, ensure_ascii=False, allow_nan=False)


def upsert(items, key, item):
    for i, old in enumerate(items):
        if old[key] == item[key]:
            items[i] = item
            return
    items.append(item)


def write_profile(path, rig):
    data = profile(rig)
    chains = validated_chains(rig, data)
    payload = {
        "format": FORMAT,
        "units": "armature-space",
        "model": rig.get("tew1_overlay_asset", ""),
        "chains": [{
            **settings,
            "rest": [{
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else "",
                "head": list(bone.bone.head_local),
                "tail": list(bone.bone.tail_local),
            } for bone in bones],
        } for settings, bones in chains],
        "colliders": data["colliders"],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf8")


def validated_chains(rig, data):
    chains = []
    seen = set()
    for chain in data["chains"]:
        names = chain["bones"]
        bones = [rig.pose.bones.get(name) for name in names]
        if not bones or any(bone is None for bone in bones):
            raise ValueError(f"发束 {chain.get('name', '?')} 引用了不存在的骨骼。")
        if any(b.parent != a for a, b in zip(bones, bones[1:])) or seen.intersection(names):
            raise ValueError(f"发束 {chain.get('name', '?')} 骨骼必须连续，且同一骨骼只能属于一条链。")
        if any(not (0 <= chain[key] <= limit) for key, limit in
               [("stiffness", 1200.0), ("damping", 0.99), ("gravity", 1000.0), ("radius", 15.0)]):
            raise ValueError(f"请检查发束 {chain.get('name', '?')} 的刚度、阻尼、重力和半径范围。")
        seen.update(names)
        chains.append((chain, bones))
    if not chains:
        raise ValueError("请先添加至少一条物理骨骼链。")
    if len(chains) > MAX_RUNTIME_CHAINS:
        raise ValueError(f"物理骨骼链数量 ({len(chains)}) 超过运行时上限 {MAX_RUNTIME_CHAINS}。")
    if len(data["colliders"]) > MAX_RUNTIME_COLLIDERS:
        raise ValueError(f"碰撞体数量 ({len(data['colliders'])}) 超过运行时上限 {MAX_RUNTIME_COLLIDERS}。")
    if any(rig.pose.bones.get(item["bone"]) is None or not 0 < item["radius"] <= 100 for item in data["colliders"]):
        raise ValueError("碰撞体引用了无效骨骼或半径。")
    return chains


def visualize_colliders(context, rig, selectable=None):
    """Display interactive Start/End/Mid proxy spheres parented to each collider bone."""
    state = getattr(context.scene, "tew1_hair", None)
    if selectable is None:
        selectable = bool(state.gizmos_selectable) if state else True
    for obj in list(rig.children):
        if obj.get(HELPER):
            bpy.data.objects.remove(obj, do_unlink=True)
    collection = rig.users_collection[0] if rig.users_collection else context.collection
    for collider in profile(rig)["colliders"]:
        bone = rig.pose.bones.get(collider["bone"])
        if bone is None:
            continue
        start, end = (Vector(collider[k]) for k in ("start", "end"))
        is_seg = (end - start).length > 0.001
        entries = (("start", start), ("mid", start.lerp(end, 0.5)), ("end", end)) if is_seg else (("start", start),)
        for role, center in entries:
            suffix = {"start": "A", "mid": "M", "end": "B"}[role]
            obj = bpy.data.objects.new(f"TEWCol_{collider['name']}_{suffix}", None)
            collection.objects.link(obj)
            obj[HELPER] = True
            obj[HELPER_NAME] = collider["name"]
            obj[HELPER_ROLE] = role
            obj.empty_display_type = "SPHERE"
            obj.empty_display_size = collider["radius"]
            obj.show_in_front = True
            obj.hide_render = True
            obj.hide_select = (not selectable) or (role == "mid")
            obj.parent = rig
            obj.parent_type = "BONE"
            obj.parent_bone = bone.name
            context.view_layer.update()
            desired = rig.matrix_world @ bone.matrix
            obj.matrix_parent_inverse = obj.matrix_world.inverted_safe() @ desired
            obj.location = center
    context.view_layer.update()


def sync_colliders_from_gizmos(context, rig):
    """Read moved/scaled visual collider gizmos back into rig['tew1_hair_profile']."""
    data = profile(rig)
    by_name = {c["name"]: c for c in data["colliders"]}
    updated = set()
    for obj in rig.children:
        if not obj.get(HELPER):
            continue
        cname = obj.get(HELPER_NAME)
        role = obj.get(HELPER_ROLE)
        if cname not in by_name or role not in ("start", "end"):
            continue
        col = by_name[cname]
        col[role] = [round(float(v), 4) for v in obj.location]
        # Allow user to scale either empty_display_size or object scale uniformly
        avg_scale = (abs(obj.scale.x) + abs(obj.scale.y) + abs(obj.scale.z)) / 3.0
        new_rad = max(0.05, min(100.0, float(obj.empty_display_size) * avg_scale))
        if role == "start" or cname not in updated:
            col["radius"] = round(new_rad, 4)
        obj.scale = (1.0, 1.0, 1.0)
        obj.empty_display_size = col["radius"]
        updated.add(cname)
    if updated:
        set_profile(rig, data)
        visualize_colliders(context, rig)
    return len(updated)


def create_default_humanoid_colliders(context, rig):
    """Generate calibrated 5-slot humanoid colliders on head/neck_00/spine_02/l_shoulder/r_shoulder."""
    data = profile(rig)
    bones = rig.data.bones
    # Estimate rig scale from head-to-spine_02 distance (TEW1 Sebastian ~ 18-24 units in cm-ish space)
    if "head" in bones and "spine_02" in bones:
        span = (bones["head"].head_local - bones["spine_02"].head_local).length
        scale = max(0.05, span / 20.0)
    else:
        scale = 1.0

    presets = [
        ("头部", "head",       (0.0,  2.2 * scale, 0.0), (0.0, 9.2 * scale, 0.0), 8.2 * scale),
        ("颈部", "neck_00",    (0.0,  0.0, 0.0),         (0.0, 6.0 * scale, 0.0), 5.0 * scale),
        ("胸背", "spine_02",   (0.0, -3.0 * scale, 0.0), (0.0, 9.5 * scale, 0.0), 11.5 * scale),
        ("左肩", "l_shoulder", (0.0,  2.0 * scale, 0.0), (0.0, 11.0 * scale, 0.0), 6.2 * scale),
        ("右肩", "r_shoulder", (0.0,  2.0 * scale, 0.0), (0.0, 11.0 * scale, 0.0), 6.2 * scale),
    ]
    created = 0
    for label, bname, s, e, rad in presets:
        if bname not in bones:
            continue
        item = {
            "name": label,
            "bone": bname,
            "start": [round(float(x), 3) for x in s],
            "end": [round(float(x), 3) for x in e],
            "radius": round(float(rad), 3),
        }
        upsert(data["colliders"], "name", item)
        created += 1
    set_profile(rig, data)
    visualize_colliders(context, rig)
    return created


def current_capsules(rig, data):
    capsules = []
    for item in data["colliders"]:
        bone = rig.pose.bones.get(item["bone"])
        if bone is None:
            continue
        frame = bone.matrix
        capsules.append((frame @ Vector(item["start"]), frame @ Vector(item["end"]), item["radius"]))
    return capsules


def chain_points(matrices, bones):
    points = [matrix.translation.copy() for matrix in matrices]
    points.append(matrices[-1] @ Vector((0.0, bones[-1].bone.length, 0.0)))
    return points


def bake_hair(context, rig):
    """Sample the original action before creating a separate baked preview action."""
    scene = context.scene
    data = profile(rig)
    chains = validated_chains(rig, data)
    fps = scene.render.fps / scene.render.fps_base
    if not 20 <= fps <= 240:
        raise ValueError("请将预览帧率设为 20–240 FPS。")
    saved_frame, saved_subframe = scene.frame_current, scene.frame_subframe
    animation = rig.animation_data_create()
    active = animation.action
    original = active.get(SOURCE_ACTION) if active and active.get(PREVIEW) else active
    active_slot = active_slot_id(animation)
    prior_pose = {bone.name: (bone.rotation_mode, [list(row) for row in bone.matrix_basis])
                  for _, bones in chains for bone in bones}
    rest_pose = json.loads(active.get(SOURCE_POSE, "{}")) if active and active.get(PREVIEW) else {}
    rest_pose = {name: rest_pose.get(name, pose) for name, pose in prior_pose.items()}
    samples = []
    report = {"frames": 0, "maximum_tip_motion": 0.0, "minimum_sample_clearance": None}
    try:
        if active != original:
            animation.action = original
            for name, (rotation_mode, basis) in rest_pose.items():
                bone = rig.pose.bones[name]
                bone.rotation_mode = rotation_mode
                bone.matrix_basis = Matrix(basis)
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            matrices = [[bone.matrix.copy() for bone in bones] for _, bones in chains]
            samples.append((frame, matrices, current_capsules(rig, data)))
        if not samples:
            raise ValueError("场景没有可烘焙的帧。")

        solvers = [HairChain(chain_points(matrices, bones), settings)
                   for matrices, (settings, bones) in zip(samples[0][1], chains)]
        baked = original.copy() if original else bpy.data.actions.new("TEW1 物理预览")
        baked.name = "TEW1 物理预览"
        baked[PREVIEW] = True
        baked[SOURCE_POSE] = json.dumps(rest_pose)
        if original:
            original.use_fake_user = True
            baked[SOURCE_ACTION] = original
        animation.action = baked
        copy_action_slot(animation, baked, active_slot)
        for frame, matrices, capsules in samples:
            scene.frame_set(frame)
            for chain_matrices, (_, bones), solver in zip(matrices, chains, solvers):
                targets = chain_points(chain_matrices, bones)
                solved = solver.advance(targets, capsules, 1.0 / fps)
                report["maximum_tip_motion"] = max(report["maximum_tip_motion"], (solved[-1] - targets[-1]).length)
                if capsules:
                    diagnostics = [a.lerp(b, f) for a, b in zip(solved, solved[1:]) for f in (0.33, 0.67, 1.0)]
                    gap = min((point - collider_point(point, start, end)).length - radius - solver.radius
                              for start, end, radius in capsules for point in diagnostics)
                    previous = report["minimum_sample_clearance"]
                    report["minimum_sample_clearance"] = gap if previous is None else min(gap, previous)
                for i, (bone, source) in enumerate(zip(bones, chain_matrices)):
                    axis = targets[i + 1] - targets[i]
                    swung = solved[i + 1] - solved[i]
                    if axis.length_squared < 1e-10 or swung.length_squared < 1e-10:
                        continue
                    rotation = axis.rotation_difference(swung)
                    posed = rotation.to_matrix().to_4x4() @ source
                    posed.translation = solved[i]
                    parent = bone.parent
                    if parent:
                        basis = bone.bone.convert_local_to_pose(posed, bone.bone.matrix_local,
                                                                parent_matrix=parent.matrix,
                                                                parent_matrix_local=parent.bone.matrix_local,
                                                                invert=True)
                    else:
                        basis = bone.bone.convert_local_to_pose(posed, bone.bone.matrix_local, invert=True)
                    location, rotation, _ = basis.decompose()
                    if rotation.dot(bone.rotation_quaternion) < 0:
                        rotation.negate()
                    bone.rotation_mode = "QUATERNION"
                    bone.location = location
                    bone.rotation_quaternion = rotation
                    insert_pose_keyframe(bone, "location", frame)
                    insert_pose_keyframe(bone, "rotation_quaternion", frame)
                    context.view_layer.update()
            report["frames"] += 1
    except Exception:
        animation.action = active
        for name, (rotation_mode, basis) in prior_pose.items():
            bone = rig.pose.bones[name]
            bone.rotation_mode = rotation_mode
            bone.matrix_basis = Matrix(basis)
        raise
    finally:
        scene.frame_set(saved_frame, subframe=saved_subframe)
    return report


def _on_preset_changed(self, _context):
    vals = PHYSICS_PRESETS.get(self.physics_preset)
    if vals:
        self.stiffness, self.damping, self.gravity, self.strand_radius = vals[:4]


def _on_chain_index_changed(self, context):
    rig = rig_object(context)
    if not rig:
        return
    chains = profile(rig)["chains"]
    if 0 <= self.active_chain_index < len(chains):
        ch = chains[self.active_chain_index]
        self.stiffness = float(ch.get("stiffness", 105.0))
        self.damping = float(ch.get("damping", 0.20))
        self.gravity = float(ch.get("gravity", 12.0))
        self.strand_radius = float(ch.get("radius", 0.35))


def _on_collider_index_changed(self, context):
    rig = rig_object(context)
    if not rig:
        return
    cols = profile(rig)["colliders"]
    if 0 <= self.active_collider_index < len(cols):
        c = cols[self.active_collider_index]
        self.label = str(c.get("name", "头部"))
        self.bone = str(c.get("bone", "head"))
        self.start = tuple(c.get("start", (0.0, 0.0, 0.0)))
        self.end = tuple(c.get("end", (0.0, 3.0, 0.0)))
        self.capsule_radius = float(c.get("radius", 3.0))


class TEW1HairSettings(bpy.types.PropertyGroup):
    physics_preset: EnumProperty(
        name="物理风格预设",
        items=[(k, v[4], v[5]) for k, v in PHYSICS_PRESETS.items()],
        default="SOFT_LONG_HAIR",
        update=_on_preset_changed,
    )
    stiffness: FloatProperty(name="回弹刚度", default=95.0, min=0.0, max=1200.0,
                             description="越大越紧贴原位，推荐 70~240")
    damping: FloatProperty(name="空气阻尼", default=0.22, min=0.0, max=0.99,
                           description="越大晃动衰减越快，推荐 0.16~0.35")
    gravity: FloatProperty(name="重力系数", default=14.0, min=0.0, max=1000.0,
                           description="向下垂坠力度，推荐 8~20")
    strand_radius: FloatProperty(name="发束碰撞半径", default=0.35, min=0.0, max=15.0,
                                 description="发束与角色胶囊碰撞体的最小间距")

    autodetect_keywords: StringProperty(
        name="识别关键词",
        default=DEFAULT_CHAIN_KEYWORDS,
        description="逗号分隔，用于一键识别头发/飘带/裙摆骨骼链",
    )
    active_chain_index: IntProperty(name="当前链序号", default=0, min=0, update=_on_chain_index_changed)

    label: StringProperty(name="碰撞体名称", default="头部", description="碰撞体的自定义显示名称（如 头部 / 胸背 / 左肩）")
    bone: StringProperty(name="绑定骨骼", default="head", description="碰撞体跟随的 TEW1 原生骨骼，仅支持 head / neck_00 / spine_02 / l_shoulder / r_shoulder 五大槽位")
    start: FloatVectorProperty(name="端点 A", size=3, default=(0.0, 0.0, 0.0), description="胶囊碰撞体起点在绑定骨骼局部空间中的坐标（也可直接在视口拖球体后同步）")
    end: FloatVectorProperty(name="端点 B", size=3, default=(0.0, 3.0, 0.0), description="胶囊碰撞体终点在绑定骨骼局部空间中的坐标（也可直接在视口拖球体后同步）")
    capsule_radius: FloatProperty(name="胶囊半径", default=3.0, min=0.01, max=100.0, description="胶囊碰撞体的阻挡半径；长发穿模时可适当调大 0.5~1.0")
    active_collider_index: IntProperty(name="当前碰撞体序号", default=0, min=0, update=_on_collider_index_changed)
    gizmos_selectable: BoolProperty(
        name="允许在 3D 视口直接拖拽碰撞体",
        default=True,
        description="开启后可在视口用 G/S 调整碰撞体球体，再点击「从视口同步回数据」",
    )
    auto_include_emissive: BoolProperty(
        name="自动纳入角色全部网格（支持 F7/F8/F9 自发光）",
        default=True,
        description="导出 tew1_dyn.bin v2 时自动写入角色身体/服饰/眼部 VB 指纹，使游戏内三档自发光覆盖全身",
    )


class TEW1MarkHair(bpy.types.Operator):
    bl_idname = "pose.tew1_mark_hair"
    bl_label = "从选中骨骼添加/更新物理链"
    bl_description = "在姿态模式选中一条连续无分叉的发束/飘带骨骼，按当前参数保存"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.mode == "POSE" and context.selected_pose_bones)

    def execute(self, context):
        rig = rig_object(context)
        selected = {bone.name: bone for bone in context.selected_pose_bones}
        roots = [bone for bone in selected.values() if bone.parent is None or bone.parent.name not in selected]
        if len(roots) != 1:
            self.report({"ERROR"}, "请选择同一发束的连续骨骼。")
            return {"CANCELLED"}
        ordered = [roots[0].name]
        while True:
            children = [child.name for child in selected[ordered[-1]].children if child.name in selected]
            if len(children) != 1:
                break
            ordered.append(children[0])
        if len(ordered) != len(selected):
            self.report({"ERROR"}, "物理链只支持没有分叉的连续骨骼链。")
            return {"CANCELLED"}
        settings = context.scene.tew1_hair
        item = {
            "name": ordered[0],
            "bones": ordered,
            "stiffness": float(settings.stiffness),
            "damping": float(settings.damping),
            "gravity": float(settings.gravity),
            "radius": float(settings.strand_radius),
        }
        data = profile(rig)
        upsert(data["chains"], "name", item)
        try:
            validated_chains(rig, data)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        set_profile(rig, data)
        settings.active_chain_index = next(
            (i for i, c in enumerate(data["chains"]) if c["name"] == item["name"]), 0
        )
        self.report({"INFO"}, f"已保存物理链 {item['name']}（{len(ordered)} 节骨骼）")
        return {"FINISHED"}


class TEW1AutoDetectChains(bpy.types.Operator):
    bl_idname = "pose.tew1_autodetect_chains"
    bl_label = "一键自动识别物理骨骼链"
    bl_description = "按关键词自动扫描非 TEW1 原生骨骼的连续骨骼链（最多 32 条），并应用当前物理预设"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return rig_object(context) is not None

    def execute(self, context):
        from . import TEMPLATE, bmd6, template_bytes
        rig = rig_object(context)
        state = context.scene.tew1_hair
        native_names = set()
        if TEMPLATE in rig:
            try:
                native_names = set(bmd6.read_model(template_bytes(rig)).skeleton.names)
            except Exception:
                pass
        keywords = [k.strip().lower() for k in state.autodetect_keywords.split(",") if k.strip()]

        def matches(bname):
            if bname in native_names:
                return False
            low = bname.lower()
            return any(k in low for k in keywords) if keywords else True

        # Find roots of matching chains
        data = profile(rig)
        used = {b for ch in data["chains"] for b in ch["bones"]}
        added = 0
        for bone in rig.data.bones:
            if len(data["chains"]) >= MAX_RUNTIME_CHAINS:
                break
            if bone.name in used or not matches(bone.name):
                continue
            if bone.parent is not None and matches(bone.parent.name) and bone.parent.name not in used:
                continue
            # Trace unbranched chain forward
            chain = [bone.name]
            cur = bone
            while True:
                kids = [c for c in cur.children if matches(c.name) and c.name not in used]
                if len(kids) != 1:
                    break
                cur = kids[0]
                chain.append(cur.name)
            if len(chain) >= 2:
                item = {
                    "name": chain[0],
                    "bones": chain,
                    "stiffness": float(state.stiffness),
                    "damping": float(state.damping),
                    "gravity": float(state.gravity),
                    "radius": float(state.strand_radius),
                }
                data["chains"].append(item)
                used.update(chain)
                added += 1

        if added == 0:
            self.report({"WARNING"}, "未自动识别到新的多节物理骨骼链，请检查关键词或在姿态模式手动选中骨骼添加。")
            return {"CANCELLED"}
        set_profile(rig, data)
        self.report({"INFO"}, f"已自动添加 {added} 条物理骨骼链（当前共 {len(data['chains'])}/{MAX_RUNTIME_CHAINS} 条）。")
        return {"FINISHED"}


class TEW1SelectChainBones(bpy.types.Operator):
    bl_idname = "pose.tew1_select_chain_bones"
    bl_label = "在视口选中该链骨骼"
    bl_description = "自动切换到姿态模式并在 3D 视口高亮选中该物理链的全部骨骼，方便检查发束位置或刷权重"
    bl_options = {"REGISTER", "UNDO"}

    chain_index: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return rig_object(context) is not None

    def execute(self, context):
        rig = rig_object(context)
        chains = profile(rig)["chains"]
        idx = self.chain_index if self.chain_index >= 0 else context.scene.tew1_hair.active_chain_index
        if not (0 <= idx < len(chains)):
            return {"CANCELLED"}
        context.view_layer.objects.active = rig
        if context.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        bpy.ops.pose.select_all(action="DESELECT")
        target = set(chains[idx]["bones"])
        for pb in rig.pose.bones:
            if pb.name in target:
                set_pose_bone_select(pb, True)
                rig.data.bones.active = pb.bone
        return {"FINISHED"}


class TEW1ApplyChainParams(bpy.types.Operator):
    bl_idname = "object.tew1_apply_chain_params"
    bl_label = "应用物理参数到链"
    bl_description = "将上方刚度、阻尼、重力、半径滑块的当前数值写入当前选中物理链（或全部物理链）"
    bl_options = {"REGISTER", "UNDO"}

    apply_all: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        rig = rig_object(context)
        return bool(rig and profile(rig)["chains"])

    def execute(self, context):
        rig = rig_object(context)
        state = context.scene.tew1_hair
        data = profile(rig)
        targets = data["chains"] if self.apply_all else (
            [data["chains"][state.active_chain_index]]
            if 0 <= state.active_chain_index < len(data["chains"]) else []
        )
        if not targets:
            return {"CANCELLED"}
        for ch in targets:
            ch["stiffness"] = float(state.stiffness)
            ch["damping"] = float(state.damping)
            ch["gravity"] = float(state.gravity)
            ch["radius"] = float(state.strand_radius)
        set_profile(rig, data)
        self.report({"INFO"}, f"已更新 {len(targets)} 条物理链的参数。")
        return {"FINISHED"}


class TEW1MarkCollider(bpy.types.Operator):
    bl_idname = "object.tew1_mark_collider"
    bl_label = "保存/更新当前碰撞体"
    bl_description = "按上方填写的名称、绑定骨骼、端点坐标与半径保存碰撞体，并刷新 3D 视口球体显示"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig = rig_object(context)
        state = context.scene.tew1_hair
        if not rig or not state.label.strip() or state.bone not in rig.pose.bones:
            self.report({"ERROR"}, "请设置碰撞体名称和有效的骨骼（推荐 head/neck_00/spine_02/l_shoulder/r_shoulder）。")
            return {"CANCELLED"}
        data = profile(rig)
        item = {
            "name": state.label.strip(),
            "bone": state.bone,
            "start": [float(v) for v in state.start],
            "end": [float(v) for v in state.end],
            "radius": float(state.capsule_radius),
        }
        upsert(data["colliders"], "name", item)
        set_profile(rig, data)
        visualize_colliders(context, rig)
        self.report({"INFO"}, f"已保存碰撞体 {item['name']} ({item['bone']})")
        return {"FINISHED"}


class TEW1CreateDefaultColliders(bpy.types.Operator):
    bl_idname = "object.tew1_create_default_colliders"
    bl_label = "一键生成默认人形 5 碰撞体"
    bl_description = "按当前骨架比例自动创建头/颈/胸背/左肩/右肩 5 个胶囊碰撞体，并在 3D 视口生成可拖拽球体"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return rig_object(context) is not None

    def execute(self, context):
        rig = rig_object(context)
        count = create_default_humanoid_colliders(context, rig)
        if count == 0:
            self.report({"ERROR"}, "当前骨架缺少标准 TEW1 骨骼 (head/neck_00/spine_02/l_shoulder/r_shoulder)。")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已生成 {count} 个可视化碰撞体，可在 3D 视口选中球体用 G/S 调整后点「从视口同步回数据」。")
        return {"FINISHED"}


class TEW1SyncCollidersFromScene(bpy.types.Operator):
    bl_idname = "object.tew1_sync_colliders_from_scene"
    bl_label = "从 3D 视口同步碰撞体位置与半径"
    bl_description = "将你在 3D 视口拖拽/缩放后的 TEWCol_* 球体写回物理配置"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rig = rig_object(context)
        return bool(rig and any(c.get(HELPER) for c in rig.children))

    def execute(self, context):
        rig = rig_object(context)
        n = sync_colliders_from_gizmos(context, rig)
        self.report({"INFO"}, f"已从视口同步 {n} 个碰撞体的位置与半径。")
        return {"FINISHED"}


class TEW1ToggleColliderGizmos(bpy.types.Operator):
    bl_idname = "object.tew1_toggle_collider_gizmos"
    bl_label = "显示/隐藏碰撞体预览"
    bl_description = "在 3D 视口切换显示或隐藏所有 TEWCol_* 碰撞体球体（仅用于预览调位置，不影响导出数据）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return rig_object(context) is not None

    def execute(self, context):
        rig = rig_object(context)
        helpers = [c for c in rig.children if c.get(HELPER)]
        if helpers:
            for obj in helpers:
                bpy.data.objects.remove(obj, do_unlink=True)
            self.report({"INFO"}, "已隐藏碰撞体视口预览。")
        else:
            visualize_colliders(context, rig)
            self.report({"INFO"}, "已显示碰撞体视口预览。")
        return {"FINISHED"}


class TEW1RemoveHairItem(bpy.types.Operator):
    bl_idname = "object.tew1_remove_hair_item"
    bl_label = "移除物理条目"
    bl_description = "从当前骨架的物理配置中移除选中的物理链或碰撞体（支持撤销）"
    bl_options = {"REGISTER", "UNDO"}

    kind: StringProperty()
    clear_all: BoolProperty(default=False)

    def execute(self, context):
        rig = rig_object(context)
        if not rig:
            return {"CANCELLED"}
        data = profile(rig)
        state = context.scene.tew1_hair
        if self.clear_all:
            data[self.kind] = []
            set_profile(rig, data)
            if self.kind == "colliders":
                visualize_colliders(context, rig)
            self.report({"INFO"}, f"已清空全部 {self.kind}。")
            return {"FINISHED"}

        if self.kind == "colliders":
            idx = state.active_collider_index
            if 0 <= idx < len(data["colliders"]):
                removed = data["colliders"].pop(idx)["name"]
            else:
                name = state.label
                before = len(data["colliders"])
                data["colliders"] = [c for c in data["colliders"] if c["name"] != name]
                if len(data["colliders"]) == before:
                    self.report({"WARNING"}, "没有找到对应的碰撞体。")
                    return {"CANCELLED"}
                removed = name
            state.active_collider_index = max(0, min(state.active_collider_index, len(data["colliders"]) - 1))
            set_profile(rig, data)
            visualize_colliders(context, rig)
            self.report({"INFO"}, f"已移除碰撞体 {removed}")
            return {"FINISHED"}

        idx = state.active_chain_index
        if 0 <= idx < len(data["chains"]):
            removed = data["chains"].pop(idx)["name"]
        else:
            bone = context.active_pose_bone
            chain = next((item for item in data["chains"] if bone and bone.name in item["bones"]), None)
            if not chain:
                self.report({"WARNING"}, "没有找到对应的物理链。")
                return {"CANCELLED"}
            data["chains"] = [c for c in data["chains"] if c["name"] != chain["name"]]
            removed = chain["name"]
        state.active_chain_index = max(0, min(state.active_chain_index, len(data["chains"]) - 1))
        set_profile(rig, data)
        self.report({"INFO"}, f"已移除物理链 {removed}")
        return {"FINISHED"}


class TEW1BakeHair(bpy.types.Operator):
    bl_idname = "object.tew1_bake_hair"
    bl_label = "烘焙物理视口预览"
    bl_description = "按当前时间轴范围烘焙头发/飘带物理动画，在 Blender 中直接检查飘动和碰撞效果"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            rig = rig_object(context)
            if not rig:
                raise ValueError("请先选择骨架。")
            result = bake_hair(context, rig)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        clearance = result["minimum_sample_clearance"]
        extra = f"，最小碰撞间隙 {clearance:.3f}" if clearance is not None else ""
        self.report({"INFO"}, f"已烘焙 {result['frames']} 帧，最大发梢位移 {result['maximum_tip_motion']:.2f}{extra}")
        return {"FINISHED"}


class TEW1RestoreHairAction(bpy.types.Operator):
    bl_idname = "object.tew1_restore_hair_action"
    bl_label = "恢复烘焙前原始动作"
    bl_description = "撤销物理预览烘焙动画，将发骨恢复到原始静止姿态（导出模型前建议点击一次）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rig = rig_object(context)
        return bool(rig and rig.animation_data and rig.animation_data.action and rig.animation_data.action.get(PREVIEW))

    def execute(self, context):
        rig = rig_object(context)
        act = rig.animation_data.action
        orig = act.get(SOURCE_ACTION)
        rest_pose = json.loads(act.get(SOURCE_POSE, "{}"))
        rig.animation_data.action = orig
        for name, (rotation_mode, basis) in rest_pose.items():
            pb = rig.pose.bones.get(name)
            if pb:
                pb.rotation_mode = rotation_mode
                pb.matrix_basis = Matrix(basis)
        self.report({"INFO"}, "已恢复原始动作并重置发骨姿态。")
        return {"FINISHED"}


class TEW1ExportHair(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.tew1_hair_profile"
    bl_label = "导出物理配置 JSON"
    bl_description = "将当前骨架的物理链和碰撞体参数保存为 .tew1-hair.json 文件，方便备份或复用到同角色其他章节模型"
    filename_ext = ".tew1-hair.json"
    filter_glob: StringProperty(default="*.tew1-hair.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            rig = rig_object(context)
            if not rig:
                raise ValueError("请先选择骨架。")
            write_profile(Path(self.filepath), rig)
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "已导出物理配置 JSON。")
        return {"FINISHED"}


class TEW1ImportHair(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.tew1_hair_profile"
    bl_label = "导入物理配置 JSON"
    bl_description = "从 .tew1-hair.json 载入已保存的物理链和碰撞体参数，快速套用到当前角色骨架"
    filename_ext = ".tew1-hair.json"
    filter_glob: StringProperty(default="*.tew1-hair.json;*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            rig = rig_object(context)
            if not rig:
                raise ValueError("请先选择骨架。")
            payload = json.loads(Path(self.filepath).read_text(encoding="utf8"))
            chains = []
            for ch in payload.get("chains", []):
                chains.append({
                    "name": ch["name"],
                    "bones": list(ch["bones"]),
                    "stiffness": float(ch["stiffness"]),
                    "damping": float(ch["damping"]),
                    "gravity": float(ch["gravity"]),
                    "radius": float(ch["radius"]),
                })
            colliders = list(payload.get("colliders", []))
            set_profile(rig, {"chains": chains, "colliders": colliders})
            visualize_colliders(context, rig)
        except Exception as error:
            self.report({"ERROR"}, f"导入失败: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已导入 {len(chains)} 条物理链、{len(colliders)} 个碰撞体。")
        return {"FINISHED"}


CLASSES = (
    TEW1HairSettings,
    TEW1MarkHair,
    TEW1AutoDetectChains,
    TEW1SelectChainBones,
    TEW1ApplyChainParams,
    TEW1MarkCollider,
    TEW1CreateDefaultColliders,
    TEW1SyncCollidersFromScene,
    TEW1ToggleColliderGizmos,
    TEW1RemoveHairItem,
    TEW1BakeHair,
    TEW1RestoreHairAction,
    TEW1ExportHair,
    TEW1ImportHair,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tew1_hair = PointerProperty(type=TEW1HairSettings)


def unregister():
    del bpy.types.Scene.tew1_hair
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
