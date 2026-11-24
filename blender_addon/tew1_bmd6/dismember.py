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


def slot_role_tag(name):
    low = name.lower()
    if any(k in low for k in HAVOK_CLOTH_KEYWORDS):
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


def count_exported_surfaces(rig, model):
    base_count = len(model.surfaces)
    appended = sum(
        1 for obj in rig.children
        if obj.type == "MESH" and obj.get(SLOT, -2) == -1 and obj.get(APPEND_NAME, "").strip()
    )
    return base_count + appended


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

    used_slots = {}
    bound_meshes = []
    for obj in rig.children:
        if obj.type != "MESH":
            continue
        if SLOT not in obj:
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

        # Check vertex weights coverage on native skeleton
        vg_names = {vg.index: vg.name for vg in obj.vertex_groups}
        unweighted = 0
        for v in mesh.vertices:
            if not any(vg_names.get(g.group) in skel_names and g.weight > 1e-6 for g in v.groups):
                unweighted += 1
        if unweighted > 0:
            errors.append(f"网格 {obj.name} 有 {unweighted} 个顶点未绑定到 TEW1 原生骨骼。")

    summary = f"总表面 {total_surfs}/{MAX_SAFE_SURFACES} · 已绑定网格 {len(bound_meshes)} · 错误 {len(errors)} · 警告 {len(warnings)}"
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
        ("APPEND_FACE", "+ 追加安全头部槽 (m_face)", "追加新表面用于头发/头饰（总表面须 <= 31）"),
        ("APPEND_BODY", "+ 追加躯干槽 (m_shirt__nn)", "追加新表面用于衣服/配饰（总表面须 <= 31）"),
    ]
    for idx, surf in enumerate(model.surfaces):
        tag = slot_role_tag(surf.name)
        items.append((str(idx), f"[{idx:02d}] {surf.name} · {tag}", f"顶点数 {surf.count} | 原材质 {surf.material}"))
    return items


class TEW1AssignSlot(bpy.types.Operator):
    bl_idname = "object.tew1_assign_slot"
    bl_label = "指派 BMD6 网格/断肢槽位"
    bl_description = "将当前选中的自定义网格绑定到指定 BMD6 模板槽位，或追加安全头部/躯干槽"
    bl_options = {"REGISTER", "UNDO"}

    target_slot: EnumProperty(name="目标槽位", items=_slot_enum_items)

    @classmethod
    def poll(cls, context):
        from . import active_rig
        return active_rig(context) is not None and any(
            o.type == "MESH" for o in context.selected_objects
        )

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def execute(self, context):
        from . import active_rig, template_bytes
        rig = active_rig(context)
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if not meshes:
            self.report({"ERROR"}, "请选中至少一个网格对象。")
            return {"CANCELLED"}
        model = bmd6.read_model(template_bytes(rig))

        if self.target_slot in ("APPEND_FACE", "APPEND_BODY"):
            surf_name = "m_face" if self.target_slot == "APPEND_FACE" else "m_shirt__nn"
            if surf_name not in [s.name for s in model.surfaces]:
                if self.target_slot == "APPEND_FACE":
                    for cand in ("m_face", "m_mouth3", "m_tong", "m_face1"):
                        if cand in [s.name for s in model.surfaces]:
                            surf_name = cand
                            break
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
            if total > MAX_SAFE_SURFACES:
                self.report({"WARNING"}, f"已追加到 {surf_name}，但当前总表面 {total} > {MAX_SAFE_SURFACES}，请减少追加槽位！")
            else:
                self.report({"INFO"}, f"已将 {len(meshes)} 个网格追加到安全槽 {surf_name}（总表面 {total}/{MAX_SAFE_SURFACES}）。")
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

            mod_info = (
                f"name={ws.mod_name.strip() or 'Custom TEW1 Character Mod'}\n"
                f"author={ws.mod_author.strip() or 'TEW1 Modder'}\n"
                f"version={ws.mod_version.strip() or '1.0'}\n"
                f"type=model\n"
                f"description={ws.mod_desc.strip() or 'Authored with TEW1 BMD6 Blender Plugin v2.0 (TEW Physical)'}\n"
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
