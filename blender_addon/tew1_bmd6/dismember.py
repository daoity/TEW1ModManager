"""TEW1 dismemberment slot management, body weight auto-splitting, validation & Mod ZIP packaging."""

from pathlib import Path
import zipfile

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper
import numpy as np

from . import bmd6

SLOT = "tew1_surface_index"
APPEND_NAME = "tew1_append_surface_name"
ZERO_HIDE = "tew1_zero_hide"
EXCLUDE_EMISSIVE = "tew1_exclude_emissive"

MAX_SAFE_SURFACES = 31

# Verified TEW1 meshKits dismemberment slot classifications
HEAD_ONLY_SLOTS = frozenset({
    "m_face", "m_face1", "m_eye", "m_eye_occ", "m_eyeoc", "m_eye_l", "m_eye_r",
    "m_eyelash_u_l", "m_eyelash_u_r", "m_eyelash_d_l", "m_eyelash_d_r",
    "m_mouth1", "m_mouth2", "m_mouth3", "m_mouth3__mo", "m_tong", "m_tongue",
    "m_teeth_u", "m_teeth_d",
})

UNSAFE_HEAD_SLOTS = frozenset({
    "m_beard", "m_beard1", "m_Cornea", "m_cornea",
    "m_vest__nv", "m_holster__lt", "m_coat_button", "m_hand_r", "m_necktie",
    "m_shirt__nn", "m_pants", "m_pants_leg__np", "m_boots1", "m_boots2__bt",
})

HAVOK_CLOTH_KEYWORDS = ("m_hair", "__clt")

BODY_DISMEMBER_SLOTS = {
    "torso": ("m_shirt__nn", "m_shirt", "m_pants", "m_vest"),
    "l_arm": ("m_hand_l", "m_l_hand", "m_arm_l"),
    "r_arm": ("m_r_shrit_arm__na", "m_hand_r", "m_hand_R", "m_arm_r"),
    "legs":  ("m_pants_leg__np", "m_boots2__bt", "m_boots1", "m_boots"),
}

L_ARM_BONES = frozenset({
    "l_shoulder", "l_upperarm", "l_forearm", "l_hand",
    "l_forearm_twist", "l_upperarm_twist", "l_elbow", "l_sup_elbow",
    "l_thumb_00", "l_thumb_01", "l_thumb_02",
    "l_index_01", "l_index_02", "l_index_03",
    "l_middle_01", "l_middle_02", "l_middle_03",
    "l_ring_01", "l_ring_02", "l_ring_03",
    "l_pinky_01", "l_pinky_02", "l_pinky_03",
})
R_ARM_BONES = frozenset({
    "r_shoulder", "r_upperarm", "r_forearm", "r_hand",
    "r_forearm_twist", "r_upperarm_twist", "r_elbow", "r_sup_elbow",
    "r_thumb_00", "r_thumb_01", "r_thumb_02",
    "r_index_01", "r_index_02", "r_index_03",
    "r_middle_01", "r_middle_02", "r_middle_03",
    "r_ring_01", "r_ring_02", "r_ring_03",
    "r_pinky_01", "r_pinky_02", "r_pinky_03",
})
LEG_BONES = frozenset({
    "l_thigh", "r_thigh", "l_shin", "r_shin",
    "l_foot", "r_foot", "l_toe", "r_toe",
    "l_sup_knee", "r_sup_knee", "l_knee", "r_knee",
})


def is_havok_surface(name):
    low = name.lower()
    return any(k in low for k in HAVOK_CLOTH_KEYWORDS)


def slot_role_tag(name):
    if is_havok_surface(name):
        return "Havok布料/原发(勿改顶点数)"
    if name in HEAD_ONLY_SLOTS:
        return "安全头部断肢槽"
    if name in ("m_beard", "m_beard1", "m_Cornea", "m_cornea"):
        return "断头不隐藏(勿放头发!)"
    if name in ("m_shirt__nn", "m_shirt", "m_vest__nv", "m_vest"):
        return "躯干槽"
    if name in ("m_hand_l", "m_arm_l"):
        return "左臂断肢槽"
    if name in ("m_r_shrit_arm__na", "m_hand_r", "m_hand_R", "m_arm_r"):
        return "右臂断肢槽"
    if name in ("m_pants_leg__np", "m_pants", "m_boots1", "m_boots2__bt", "m_boots"):
        return "腿部/靴子断肢槽"
    return "常规槽位"


def count_recyclable_slots(rig, model):
    """Count zero-hidden non-Havok stock slots that export_model() automatically recycles for appended meshes."""
    count = 0
    for obj in rig.children:
        if obj.type != "MESH" or not obj.get(ZERO_HIDE):
            continue
        slot = int(obj.get(SLOT, -2))
        if 0 <= slot < len(model.surfaces) and not is_havok_surface(model.surfaces[slot].name):
            count += 1
    return count


def count_exported_surfaces(rig, model):
    base_count = len(model.surfaces)
    appended = sum(
        1 for obj in rig.children
        if obj.type == "MESH" and obj.get(SLOT, -2) == -1 and obj.get(APPEND_NAME, "").strip()
    )
    recyclable = count_recyclable_slots(rig, model)
    return base_count + max(0, appended - recyclable)


def validate_rig_for_export(rig):
    """Run comprehensive pre-export checks and return (errors, warnings, summary)."""
    from . import template_bytes
    errors = []
    warnings = []

    try:
        model = bmd6.read_model(template_bytes(rig))
    except Exception as exc:
        return [f"无法读取骨架内嵌 BMD6 模板: {exc}"], [], "模板无效"

    skel_names = set(model.skeleton.names)
    total_surfs = count_exported_surfaces(rig, model)
    if total_surfs > MAX_SAFE_SURFACES:
        errors.append(f"导出总表面数为 {total_surfs}，超过安全上限 {MAX_SAFE_SURFACES}（游戏可能闪烁或崩溃）。")

    asset_name = str(rig.get("tew1_overlay_asset", "")).lower()
    if "pl0007" in asset_name:
        live_pl0007 = [o for o in rig.children if o.type == "MESH" and SLOT in o and not o.get(ZERO_HIDE)]
        if live_pl0007:
            warnings.append("当前模板为 pl0007（全裸/特殊占位模型），建议将所有表面设为「安全清零隐藏」，否则脚底可能出现折叠废网格。")

    head_bone = rig.data.bones.get("head")
    neck_z = float(head_bone.head_local.z) if head_bone else None
    lu_bone = rig.data.bones.get("l_upperarm")
    tgt_upper_y = abs(float(lu_bone.head_local.y)) if lu_bone else None
    arm_inv = rig.matrix_world.inverted_safe()

    used_slots = {}
    bound_meshes = []
    unbound_custom = []
    for obj in rig.children:
        if obj.type != "MESH":
            continue
        if SLOT not in obj:
            if not obj.hide_viewport and not obj.hide_get() and not obj.get(ZERO_HIDE):
                unbound_custom.append(obj.name)
            continue
        slot = int(obj[SLOT])
        if slot == -1:
            aname = str(obj.get(APPEND_NAME, "")).strip()
            if not aname:
                errors.append(f"网格 {obj.name} 设为追加槽(-1)，但未填写追加表面名。")
                continue
            surf_name = aname
        elif 0 <= slot < len(model.surfaces):
            if slot in used_slots:
                errors.append(f"网格槽 {slot} ({model.surfaces[slot].name}) 被 {used_slots[slot]} 和 {obj.name} 重复占用。")
            used_slots[slot] = obj.name
            surf_name = model.surfaces[slot].name
        else:
            errors.append(f"网格 {obj.name} 的槽号 {slot} 超出模板范围 (0..{len(model.surfaces) - 1})。")
            continue

        bound_meshes.append((obj, slot, surf_name))

        if obj.get(ZERO_HIDE):
            continue

        mesh = obj.data
        if not mesh.uv_layers.active:
            errors.append(f"网格 {obj.name} 缺少活动 UV 层。")
        if any(m.show_viewport and m.type != "ARMATURE" for m in obj.modifiers):
            errors.append(f"网格 {obj.name} 含有未应用的非骨架修改器。")

        # Check Havok cloth surface vertex count safety
        if slot >= 0 and any(k in surf_name.lower() for k in HAVOK_CLOTH_KEYWORDS):
            orig_cnt = model.surfaces[slot].count
            if len(mesh.vertices) != orig_cnt:
                warnings.append(
                    f"槽 {slot} ({surf_name}) 是原版 Havok 物理槽，顶点数已变动({orig_cnt}->{len(mesh.vertices)})，"
                    f"建议改为「安全清零隐藏」并把自定义头发放到 m_face。"
                )

        # Check unsafe head/hair slot placement
        low_obj = obj.name.lower()
        looks_head = any(k in low_obj for k in ("hair", "face", "head", "brow", "lash", "eye", "发", "头", "脸", "眼"))
        if looks_head and surf_name in UNSAFE_HEAD_SLOTS:
            warnings.append(
                f"网格 {obj.name} 疑似头部/头发部件，但绑定在 {surf_name}，断头处决时会悬浮残留！建议改放到 m_face / m_mouth3 / m_tong。"
            )

        # Check material path
        mat_path = ""
        if mesh.materials and mesh.materials[0] is not None:
            mat_path = str(mesh.materials[0].get("tew1_material_path", ""))
        if not mat_path:
            warnings.append(f"网格 {obj.name} 第一个材质未设置 tew1_material_path（将沿用原版材质路径）。")

        # Check vertex weights coverage on native skeleton + head-skin split + medial shoulder-cap check
        vg_names = {vg.index: vg.name for vg in obj.vertex_groups}
        unweighted = 0
        medial_upperarm_verts = 0
        to_arm = np.array(arm_inv @ obj.matrix_world, dtype=np.float64)
        n_v = len(mesh.vertices)
        v_co = np.empty(n_v * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", v_co)
        v_arm = v_co.reshape(-1, 3).astype(np.float64) @ to_arm[:3, :3].T + to_arm[:3, 3]
        lu_vg = obj.vertex_groups.get("l_upperarm")
        ru_vg = obj.vertex_groups.get("r_upperarm")
        lu_i = lu_vg.index if lu_vg else -1
        ru_i = ru_vg.index if ru_vg else -1
        for v in mesh.vertices:
            has_nat = False
            for g in v.groups:
                if vg_names.get(g.group) in skel_names and g.weight > 1e-6:
                    has_nat = True
                if tgt_upper_y and tgt_upper_y > 4.0 and g.group in (lu_i, ru_i) and g.weight > 0.35:
                    if abs(float(v_arm[v.index, 1])) < tgt_upper_y * 0.82:
                        medial_upperarm_verts += 1
            if not has_nat:
                unweighted += 1
        if unweighted > 0:
            errors.append(f"网格 {obj.name} 有 {unweighted} 个顶点未绑定到 TEW1 原生骨骼。")
        if medial_upperarm_verts >= 12:
            warnings.append(
                f"网格 {obj.name} 有 {medial_upperarm_verts} 个肩头内侧顶点(|Y|<{tgt_upper_y*0.82:.1f})绑定了较重 upperarm 权重，"
                f"待机垂臂时可能呈方形「双开门」；建议在「TEW Mesh > 2」点「一键修复双开门肩宽权重」。"
            )
        # Check body slot leaking head/ear skin vertices above neck
        if neck_z is not None and surf_name not in HEAD_ONLY_SLOTS and n_v > 0:
            above_head = int((v_arm[:, 2] > neck_z + 2.5).sum())
            if above_head >= 20 and not looks_head:
                warnings.append(
                    f"身体槽网格 {obj.name} ({surf_name}) 有 {above_head} 个顶点伸入头部区域(Z>{neck_z+2.5:.1f})，"
                    f"若含耳部/上颈/后脑皮肤请分离并移入 m_face（及断头模型 pl0001_ng），否则断头时头部会残留多出网格。"
                )

    if unbound_custom:
        sample = ", ".join(unbound_custom[:5]) + ("..." if len(unbound_custom) > 5 else "")
        warnings.append(
            f"骨架下有 {len(unbound_custom)} 个可见自定义网格尚未指派 BMD6 槽位（不会被导出！）：{sample}。"
            f"请选中它们点「指派/追加 网格与断肢槽位」（会自动回收隐藏的原版废槽）。"
        )

    recyclable = count_recyclable_slots(rig, model)
    summary = f"总表面 {total_surfs}/{MAX_SAFE_SURFACES} (可回收隐藏槽 {recyclable}) · 已绑定 {len(bound_meshes)} · 错误 {len(errors)} · 警告 {len(warnings)}"
    return errors, warnings, summary


def _slot_enum_items(self, context):
    from . import active_rig, template_bytes
    rig = active_rig(context)
    if rig is None:
        return [("0", "请先选中带 BMD6 模板的骨架", "")]
    try:
        model = bmd6.read_model(template_bytes(rig))
    except Exception:
        return [("0", "模板读取失败", "")]
    items = [
        ("APPEND_FACE", "+ 头部/头发/面部槽 (m_face · 自动回收隐藏槽)", "支持多选批量指派！自动复用已隐藏的原版非 Havok 废槽，不超 31 上限"),
        ("APPEND_BODY", "+ 躯干/服装槽 (m_shirt__nn · 自动回收隐藏槽)", "支持多选批量指派！自动复用已隐藏的原版废槽，适合躯干与衣服"),
        ("APPEND_LARM", "+ 左臂断肢槽 (m_hand_l · 自动回收隐藏槽)", "支持多选批量指派！断左臂时自动隐藏"),
        ("APPEND_RARM", "+ 右臂断肢槽 (m_r_shrit_arm__na · 自动回收隐藏槽)", "支持多选批量指派！断右臂时自动隐藏"),
        ("APPEND_LEGS", "+ 双腿/鞋袜断肢槽 (m_pants_leg__np · 自动回收隐藏槽)", "支持多选批量指派！断腿/碾压时自动隐藏"),
    ]
    for idx, surf in enumerate(model.surfaces):
        tag = slot_role_tag(surf.name)
        items.append((str(idx), f"[{idx:02d}] {surf.name} · {tag}", f"顶点数 {surf.count} | 原材质 {surf.material}"))
    return items


class TEW1AssignSlot(bpy.types.Operator):
    bl_idname = "object.tew1_assign_slot"
    bl_label = "指派 BMD6 网格/断肢槽位"
    bl_description = "将选中的一个或多个自定义网格绑定到指定 BMD6 模板槽位，或批量指派到头部/躯干/四肢槽（自动回收已隐藏的非 Havok 原版槽，确保 <= 31 表面）"
    bl_options = {"REGISTER", "UNDO"}

    target_slot: EnumProperty(name="目标槽位", items=_slot_enum_items)

    @classmethod
    def poll(cls, context):
        from . import active_rig
        return active_rig(context) is not None and any(
            o.type == "MESH" for o in context.selected_objects
        )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        from . import active_rig, template_bytes
        rig = active_rig(context)
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if not meshes:
            self.report({"ERROR"}, "请选中至少一个网格对象。")
            return {"CANCELLED"}
        model = bmd6.read_model(template_bytes(rig))

        append_presets = {
            "APPEND_FACE": ("m_face", ("m_face", "m_mouth3", "m_tong", "m_face1")),
            "APPEND_BODY": ("m_shirt__nn", ("m_shirt__nn", "m_shirt", "m_pants", "m_vest")),
            "APPEND_LARM": ("m_hand_l", ("m_hand_l", "m_l_hand", "m_arm_l")),
            "APPEND_RARM": ("m_r_shrit_arm__na", ("m_r_shrit_arm__na", "m_hand_r", "m_hand_R", "m_arm_r")),
            "APPEND_LEGS": ("m_pants_leg__np", ("m_pants_leg__np", "m_boots2__bt", "m_boots1", "m_boots")),
        }
        if self.target_slot in append_presets:
            default_name, fallbacks = append_presets[self.target_slot]
            existing_names = {s.name for s in model.surfaces}
            surf_name = next((c for c in fallbacks if c in existing_names), default_name)
            for obj in meshes:
                mat = obj.matrix_world.copy()
                obj.parent = rig
                obj.matrix_world = mat
                obj[SLOT] = -1
                obj[APPEND_NAME] = surf_name
                if ZERO_HIDE in obj:
                    del obj[ZERO_HIDE]
                if not any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers):
                    mod = obj.modifiers.new("TEW1 Armature", "ARMATURE")
                    mod.object = rig
            total = count_exported_surfaces(rig, model)
            recyc = count_recyclable_slots(rig, model)
            if total > MAX_SAFE_SURFACES:
                self.report(
                    {"WARNING"},
                    f"已指派 {len(meshes)} 个网格到 {surf_name}，但当前总表面 {total} > {MAX_SAFE_SURFACES}（可回收隐藏槽 {recyc}）。"
                    f"请隐藏不用的原版槽，或用「合并同贴图/同材质零碎网格」精简数量！",
                )
            else:
                self.report(
                    {"INFO"},
                    f"已将 {len(meshes)} 个网格指派到 {surf_name}（导出表面 {total}/{MAX_SAFE_SURFACES}，可回收隐藏槽 {recyc}）。",
                )
            return {"FINISHED"}

        if len(meshes) != 1:
            self.report({"ERROR"}, "替换单个编号槽位时请只选中 1 个网格（多个网格请选「追加」模式）。")
            return {"CANCELLED"}
        slot = int(self.target_slot)
        obj = meshes[0]
        for child in list(rig.children):
            if child != obj and child.get(SLOT) == slot:
                del child[SLOT]
                child.hide_set(True)
        mat = obj.matrix_world.copy()
        obj.parent = rig
        obj.matrix_world = mat
        obj[SLOT] = slot
        if APPEND_NAME in obj:
            del obj[APPEND_NAME]
        if ZERO_HIDE in obj:
            del obj[ZERO_HIDE]
        if not any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers):
            mod = obj.modifiers.new("TEW1 Armature", "ARMATURE")
            mod.object = rig
        self.report({"INFO"}, f"已将 {obj.name} 绑定到槽 [{slot:02d}] {model.surfaces[slot].name}")
        return {"FINISHED"}


class TEW1SafeHideSlot(bpy.types.Operator):
    bl_idname = "object.tew1_safe_hide_slot"
    bl_label = "安全隐藏原版槽位（防 Havok 崩溃）"
    bl_description = "导出时保留原顶点数但清零三角面，专用于隐藏原版 m_hair / 衣服 / 配件而不触发 Havok 崩溃"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and obj.type == "MESH" and obj.get(SLOT, -2) >= 0)

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == "MESH" and obj.get(SLOT, -2) >= 0:
                obj[ZERO_HIDE] = not bool(obj.get(ZERO_HIDE, False))
                obj.hide_viewport = bool(obj[ZERO_HIDE])
                count += 1
        self.report({"INFO"}, f"已切换 {count} 个原版槽位的「安全清零隐藏」标记。")
        return {"FINISHED"}


class TEW1AutoSplitBodyDismember(bpy.types.Operator):
    bl_idname = "object.tew1_split_body_dismember"
    bl_label = "一键按骨骼权重拆分身体断肢部位"
    bl_description = "将选中的整件身体/服装网格按骨骼权重自动拆分为躯干、左臂、右臂、腿部 4 个断肢子网格"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from . import active_rig
        obj = context.object
        return bool(context.mode == "OBJECT" and active_rig(context) and obj and obj.type == "MESH")

    def execute(self, context):
        from . import active_rig, template_bytes
        rig = active_rig(context)
        src = context.object
        mesh = src.data
        if len(mesh.polygons) == 0:
            self.report({"ERROR"}, "网格没有面可拆分。")
            return {"CANCELLED"}

        model = bmd6.read_model(template_bytes(rig))
        slot_by_name = {s.name: idx for idx, s in enumerate(model.surfaces)}

        vg_names = {vg.index: vg.name for vg in src.vertex_groups}
        n_verts = len(mesh.vertices)
        w_l = np.zeros(n_verts, dtype=float)
        w_r = np.zeros(n_verts, dtype=float)
        w_leg = np.zeros(n_verts, dtype=float)
        for v in mesh.vertices:
            for g in v.groups:
                bname = vg_names.get(g.group, "")
                if bname in L_ARM_BONES:
                    w_l[v.index] += g.weight
                elif bname in R_ARM_BONES:
                    w_r[v.index] += g.weight
                elif bname in LEG_BONES:
                    w_leg[v.index] += g.weight

        part_polys = {"torso": [], "l_arm": [], "r_arm": [], "legs": []}
        for poly in mesh.polygons:
            vids = list(poly.vertices)
            sl = float(w_l[vids].mean())
            sr = float(w_r[vids].mean())
            sg = float(w_leg[vids].mean())
            best = max((sl, "l_arm"), (sr, "r_arm"), (sg, "legs"))
            part = best[1] if best[0] >= 0.45 else "torso"
            part_polys[part].append(poly.index)

        non_empty = [k for k, v in part_polys.items() if v]
        if len(non_empty) <= 1:
            self.report({"WARNING"}, "未检测到多个可区分的肢体权重区域（请先完成骨骼绑定）。")
            return {"CANCELLED"}

        col = src.users_collection[0] if src.users_collection else context.collection
        created = []
        used_slots = {int(c[SLOT]) for c in rig.children if c.type == "MESH" and c != src and c.get(SLOT, -2) >= 0}

        for part_key in ("torso", "l_arm", "r_arm", "legs"):
            poly_ids = part_polys[part_key]
            if not poly_ids:
                continue
            dup = src.copy()
            dup.data = src.data.copy()
            dup.name = f"{src.name}_{part_key}"
            col.objects.link(dup)

            # Remove polygons not belonging to this part via bmesh
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(dup.data)
            bm.faces.ensure_lookup_table()
            keep = set(poly_ids)
            to_del = [f for f in bm.faces if f.index not in keep]
            bmesh.ops.delete(bm, geom=to_del, context="FACES")
            bm.to_mesh(dup.data)
            bm.free()
            dup.data.update()

            # Auto-assign matching dismemberment slot on template
            assigned_slot = None
            for cand in BODY_DISMEMBER_SLOTS[part_key]:
                if cand in slot_by_name and slot_by_name[cand] not in used_slots:
                    assigned_slot = slot_by_name[cand]
                    used_slots.add(assigned_slot)
                    break
            if assigned_slot is not None:
                dup[SLOT] = assigned_slot
                if APPEND_NAME in dup:
                    del dup[APPEND_NAME]
            else:
                # Fallback to append with first known slot name on template
                fallback = next((c for c in BODY_DISMEMBER_SLOTS[part_key] if c in slot_by_name), BODY_DISMEMBER_SLOTS[part_key][0])
                dup[SLOT] = -1
                dup[APPEND_NAME] = fallback
            created.append(f"{part_key}({len(poly_ids)}面)")

        # Hide original unsplit mesh and clear its slot so it isn't double-exported
        if SLOT in src:
            del src[SLOT]
        src.hide_set(True)
        self.report({"INFO"}, "已拆分断肢部位: " + ", ".join(created))
        return {"FINISHED"}


class TEW1NormalizeWeights(bpy.types.Operator):
    bl_idname = "object.tew1_normalize_weights"
    bl_label = "规范化骨骼权重 (TEW1 上限4骨骼)"
    bl_description = "移除空权重组、限制每顶点最多 4 根骨骼影响并归一化权重，避免 BMD6 量化变形"
    bl_options = {"REGISTER", "UNDO"}

    remove_non_native: BoolProperty(
        name="同时清理非原生/非物理多余权重组",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return bool(context.mode == "OBJECT" and any(o.type == "MESH" for o in context.selected_objects))

    def execute(self, context):
        from . import active_rig, template_bytes
        from .hair_author import profile as hair_profile
        rig = active_rig(context)
        allowed = None
        if self.remove_non_native and rig is not None:
            try:
                model = bmd6.read_model(template_bytes(rig))
                allowed = set(model.skeleton.names)
                for ch in hair_profile(rig).get("chains", []):
                    allowed.update(ch.get("bones", []))
            except Exception:
                allowed = None

        processed = 0
        removed_groups = 0
        prev_active = context.view_layer.objects.active
        for obj in [o for o in context.selected_objects if o.type == "MESH"]:
            if not obj.vertex_groups:
                continue
            if allowed is not None:
                for vg in list(obj.vertex_groups):
                    if vg.name not in allowed:
                        obj.vertex_groups.remove(vg)
                        removed_groups += 1
            context.view_layer.objects.active = obj
            bpy.ops.object.vertex_group_clean(group_select_mode="ALL", limit=1e-4)
            bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
            bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
            processed += 1
        context.view_layer.objects.active = prev_active
        self.report({"INFO"}, f"已规范化 {processed} 个网格权重（清理多余组 {removed_groups} 个）。")
        return {"FINISHED"}


class TEW1ValidateModel(bpy.types.Operator):
    bl_idname = "object.tew1_validate_model"
    bl_label = "导出前全面体检 (表面/断肢/权重)"
    bl_description = "检查总表面数 <= 31、断头槽位安全性、Havok 槽保护、UV、修改器与顶点权重"

    @classmethod
    def poll(cls, context):
        from . import active_rig
        return active_rig(context) is not None

    def execute(self, context):
        from . import active_rig
        rig = active_rig(context)
        errors, warnings, summary = validate_rig_for_export(rig)
        for w in warnings:
            self.report({"WARNING"}, w)
        for e in errors:
            self.report({"ERROR"}, e)
        if not errors and not warnings:
            self.report({"INFO"}, "体检全部通过！" + summary)
        elif not errors:
            self.report({"WARNING"}, "体检通过但有警告：" + summary)
        else:
            self.report({"ERROR"}, "体检发现错误：" + summary)
        return {"FINISHED"}


class TEW1MergeSameMaterialMeshes(bpy.types.Operator):
    bl_idname = "object.tew1_merge_same_material_meshes"
    bl_label = "合并同材质/同贴图零碎网格"
    bl_description = "将当前选中的多个网格按「相同 TEW1 材质路径或相同底色贴图（且同断肢槽分类）」自动合并，完整保留形态键与权重，大幅精简表面数量"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        meshes = [o for o in context.selected_objects if o.type == "MESH" and not o.get(ZERO_HIDE)]
        return context.mode == "OBJECT" and len(meshes) >= 2

    def execute(self, context):
        from .tex_encode import find_material_albedo_image
        meshes = [o for o in context.selected_objects if o.type == "MESH" and not o.get(ZERO_HIDE)]
        if len(meshes) < 2:
            self.report({"WARNING"}, "请至少选中 2 个待合并的自定义网格。")
            return {"CANCELLED"}

        groups = {}
        for obj in meshes:
            mat = obj.data.materials[0] if (obj.data.materials and obj.data.materials[0]) else None
            mpath = str(mat.get("tew1_material_path", "")).strip() if mat else ""
            if not mpath and mat is not None:
                img = find_material_albedo_image(mat)
                mpath = f"img:{img.name}" if img else f"mat:{mat.name}"
            if not mpath:
                continue
            slot_key = (int(obj.get(SLOT, -2)), str(obj.get(APPEND_NAME, "")))
            groups.setdefault((mpath, slot_key), []).append(obj)

        merged_groups = 0
        removed_objs = 0
        prev_active_name = context.view_layer.objects.active.name if context.view_layer.objects.active else ""
        for (_mpath, _skey), objs in groups.items():
            if len(objs) < 2:
                continue
            bpy.ops.object.select_all(action="DESELECT")
            target = objs[0]
            for o in objs:
                o.select_set(True)
            context.view_layer.objects.active = target
            bpy.ops.object.join()
            # Keep only first material slot on merged mesh so BMD6 exports cleanly
            while len(target.data.materials) > 1:
                target.data.materials.pop()
            merged_groups += 1
            removed_objs += len(objs) - 1

        if prev_active_name and prev_active_name in bpy.data.objects:
            context.view_layer.objects.active = bpy.data.objects[prev_active_name]
        if merged_groups == 0:
            self.report({"INFO"}, "选中的网格中没有可合并的同贴图/同材质组。")
            return {"FINISHED"}
        self.report({"INFO"}, f"合并完成：将 {merged_groups} 组同材质/同贴图网格合并，精简了 {removed_objs} 个表面！")
        return {"FINISHED"}


class TEW1PackModZip(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.tew1_pack_mod_zip"
    bl_label = "一键打包为 Mod ZIP"
    bl_description = "将当前挂载目录 (base/...) 与自动生成的 mod.info 打包成可直接导入 TEW1ModManager 的 ZIP"
    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})

    def invoke(self, context, event):
        ws = context.scene.tew1_workspace
        safe = (ws.mod_name.strip() or "TEW1_Custom_Mod").replace(" ", "_")
        self.filepath = safe + ".zip"
        return super().invoke(context, event)

    def execute(self, context):
        from .workflow import loose_root
        ws = context.scene.tew1_workspace
        try:
            root = loose_root(ws.overlay)
            base_dir = root / "base"
            if not base_dir.is_dir():
                raise ValueError("挂载目录中找不到 base/ 文件夹，请先导出模型/贴图/物理包。")
            files = [p for p in base_dir.rglob("*") if p.is_file()]
            if not files:
                raise ValueError("base/ 目录为空，没有可打包的文件。")
            has_model = any(p.suffix.lower() == ".bmd6model" for p in files)
            has_audio = any(p.suffix.lower() == ".wav" for p in files)
            if not has_model and not has_audio:
                raise ValueError(
                    "挂载目录 base/ 中没有任何 .bmd6model 模型文件（当前只有贴图/材质）！"
                    "请先完成槽位指派并点击「导出 BMD6 到挂载目录」或「一键同步导出 BMD6 + tew1_dyn.bin」再打包。"
                )

            mod_info = (
                f"name={ws.mod_name.strip() or 'Custom TEW1 Character Mod'}\n"
                f"author={ws.mod_author.strip() or 'TEW1 Modder'}\n"
                f"version={ws.mod_version.strip() or '1.0'}\n"
                f"type={'model' if has_model else 'voice'}\n"
                f"description={ws.mod_desc.strip() or 'Authored with TEW1 BMD6 Blender Plugin v2.8 (TEW Physical)'}\n"
            )

            out_zip = Path(self.filepath)
            out_zip.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.writestr("mod.info", mod_info.encode("utf-8"))
                for fp in sorted(files):
                    rel = fp.relative_to(root).as_posix()
                    zf.write(fp, rel)
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已打包 Mod ZIP: {out_zip.name}（含 {len(files)} 个资源文件）")
        return {"FINISHED"}


CLASSES = (
    TEW1AssignSlot,
    TEW1SafeHideSlot,
    TEW1AutoSplitBodyDismember,
    TEW1MergeSameMaterialMeshes,
    TEW1NormalizeWeights,
    TEW1ValidateModel,
    TEW1PackModZip,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
