"""Generic Blender exporter for TEW1 Mod dynamic physics, facial morphs & self-illumination (tew1_dyn.bin v2).
Allows any Mod creator to author hair/cloth chains, 5-slot bone colliders, emissive surface tags,
and optional Blender Shape Keys on any character and export base/generated/tew1_dyn.bin (v2)."""

from pathlib import Path, PurePosixPath
import struct

import bpy
from bpy.props import StringProperty
import numpy as np

from . import bmd6
from .dismember import EXCLUDE_EMISSIVE, ZERO_HIDE
from .hair_author import (
    MAX_RUNTIME_CHAINS,
    MAX_RUNTIME_COLLIDERS,
    profile as hair_profile,
    rig_object,
    validated_chains,
)

MAGIC = b"TEWH"
VERSION = 2

COLLIDER_BONES = ("head", "neck_00", "spine_02", "l_shoulder", "r_shoulder")

# 15 standard expression channels with flexible English / Chinese / MMD Japanese Shape Key aliases
CHANNEL_ALIASES = (
    ("Blink",       ("Haruka_Blink", "Blink", "blink", "まばたき", "眨眼", "闭眼")),
    ("WinkL",       ("Haruka_Wink_L", "Wink_L", "WinkL", "wink_l", "ウィンク", "左眼眨眼")),
    ("WinkR",       ("Haruka_Wink_R", "Wink_R", "WinkR", "wink_r", "ウィンク右", "右眼眨眼")),
    ("A",           ("Haruka_A", "A", "vrc.v_aa", "aa", "嘴型-啊", "あ", "啊")),
    ("I",           ("Haruka_I", "I", "vrc.v_ih", "ih", "い", "一")),
    ("U",           ("Haruka_U", "U", "vrc.v_ou", "ou", "う", "乌")),
    ("E",           ("Haruka_E", "E", "vrc.v_e",  "eh", "嘴型-ei", "え", "诶")),
    ("O",           ("Haruka_O", "O", "vrc.v_oh", "oh", "嘴型-哦", "お", "哦")),
    ("Smile",       ("Haruka_Smile", "Smile", "smile", "嘴型-笑2", "嘴型-笑", "微笑")),
    ("SmileEyes",   ("Haruka_SmileEyes", "SmileEyes", "Joy", "笑い", "笑眼")),
    ("Surprised",   ("Haruka_Surprised", "Surprised", "Surprise", "びっくり", "惊讶")),
    ("BrowWorried", ("Haruka_BrowWorried", "Worried", "Sad", "困る", "担忧", "发愁")),
    ("BrowAngry",   ("Haruka_BrowAngry", "Angry", "Fierce", "怒り", "眉毛-愤怒", "生气")),
    ("BrowUp",      ("Haruka_BrowUp", "BrowUp", "上", "挑眉")),
    ("Frown",       ("Haruka_Frown", "Frown", "嘴型-嘴角下移", "撇嘴")),
)


def _pick_bone(skel, *names):
    for n in names:
        if n in skel.names:
            idx = skel.names.index(n)
            return int(skel.remap[idx]), skel.joints[n]
    return -1, np.zeros(3, dtype=float)


def _match_shape_key(key_blocks, aliases):
    by_lower = {kb.name.lower(): kb for kb in key_blocks}
    for alias in aliases:
        if alias in key_blocks:
            return key_blocks[alias]
        low = alias.lower()
        if low in by_lower:
            return by_lower[low]
    return None


def scan_rig_shape_keys(rig):
    """Return list of matched channel names across child meshes of rig (for UI diagnostics)."""
    from .facial_author import read_facial_map
    if rig is None:
        return []
    found = set()
    for obj in rig.children:
        if obj.type != "MESH" or not obj.data.shape_keys or len(obj.data.shape_keys.key_blocks) <= 1:
            continue
        kbs = obj.data.shape_keys.key_blocks
        manual = read_facial_map(obj)
        for ch_name, aliases in CHANNEL_ALIASES:
            mname = manual.get(ch_name, "")
            if (mname and mname in kbs) or _match_shape_key(kbs, aliases) is not None:
                found.add(ch_name)
    return [name for name, _ in CHANNEL_ALIASES if name in found]


def _build_mesh_rest_and_data(rig, obj, hair_bone_to_idx):
    """Extract mesh rest positions in armature space, hair vertex weights, and 15 shape-key deltas."""
    mesh = obj.data
    n = len(mesh.vertices)
    if n == 0:
        return None
    mat = np.array(rig.matrix_world.inverted_safe() @ obj.matrix_world, dtype=float)
    rot = mat[:3, :3]

    co = np.empty(n * 3, dtype=float)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    pts = co @ rot.T + mat[:3, 3]

    # Hair / cloth physics weights
    vg_to_hair = {}
    for vg in obj.vertex_groups:
        if vg.name in hair_bone_to_idx:
            vg_to_hair[vg.index] = hair_bone_to_idx[vg.name]

    hair_w = None
    if vg_to_hair:
        hw = np.zeros((n, len(hair_bone_to_idx)), dtype=float)
        any_w = False
        for v in mesh.vertices:
            for g in v.groups:
                if g.group in vg_to_hair and g.weight > 1e-4:
                    hw[v.index, vg_to_hair[g.group]] += g.weight
                    any_w = True
        if any_w:
            hair_w = hw

    # Facial shape key deltas (manual TEW Facial map takes priority over automatic aliases)
    from .facial_author import read_facial_map
    morphs = None
    if mesh.shape_keys and len(mesh.shape_keys.key_blocks) > 1:
        kbs = mesh.shape_keys.key_blocks
        basis = kbs[0]
        manual = read_facial_map(obj)
        bco = np.empty(n * 3, dtype=float)
        basis.data.foreach_get("co", bco)
        bco = bco.reshape(-1, 3)
        deltas = np.zeros((len(CHANNEL_ALIASES), n, 3), dtype=float)
        found_any = False
        for ci, (ch_name, aliases) in enumerate(CHANNEL_ALIASES):
            mname = manual.get(ch_name, "")
            kb = kbs[mname] if (mname and mname in kbs) else _match_shape_key(kbs, aliases)
            if kb is None or kb == basis:
                continue
            kco = np.empty(n * 3, dtype=float)
            kb.data.foreach_get("co", kco)
            d = (kco.reshape(-1, 3) - bco) @ rot.T
            if float(np.max(np.linalg.norm(d, axis=1))) > 1e-4:
                deltas[ci] = d
                found_any = True
        if found_any:
            morphs = deltas

    return {
        "obj": obj,
        "pts": pts,
        "hair_w": hair_w,
        "morphs": morphs,
        "exclude_emissive": bool(obj.get(EXCLUDE_EMISSIVE, False)),
    }


def _build_kdtree(ref_pts):
    """Build Blender's native C++ KDTree for fast O(N log M) surface vertex matching."""
    from mathutils.kdtree import KDTree
    kd = KDTree(len(ref_pts))
    for i, p in enumerate(ref_pts):
        kd.insert((float(p[0]), float(p[1]), float(p[2])), i)
    kd.balance()
    return kd


def _aabb_close(pts_a, pts_b, tol=1.0):
    min_a, max_a = pts_a.min(axis=0), pts_a.max(axis=0)
    min_b, max_b = pts_b.min(axis=0), pts_b.max(axis=0)
    return bool(np.all(np.abs(min_a - min_b) <= tol) and np.all(np.abs(max_a - max_b) <= tol))


def _nearest_indices(query_pts, ref_pts, kd=None):
    """Fast KDTree nearest-neighbor matching from BMD6 surface vertices to Blender mesh vertices."""
    if kd is None:
        kd = _build_kdtree(ref_pts)
    n_q = len(query_pts)
    best_idx = np.empty(n_q, dtype=np.int32)
    best_dist = np.empty(n_q, dtype=float)
    for i, p in enumerate(query_pts):
        _co, idx, dist = kd.find((float(p[0]), float(p[1]), float(p[2])))
        best_idx[i] = idx
        best_dist[i] = dist
    return best_idx, best_dist


def _is_degenerate_hidden_surface(surf):
    """Detect zero-area hidden surfaces (e.g. zeroed-index m_hair)."""
    if len(surf.indices) == 0:
        return True
    if len(surf.indices) == 1 and int(surf.indices[0, 0]) == int(surf.indices[0, 1]) == int(surf.indices[0, 2]):
        return True
    return False


def validate_physics_setup(rig, overlay_dir=""):
    """Preflight check for TEW Physical workflow. Returns (errors, warnings, summary)."""
    errors = []
    warnings = []
    if rig is None or rig.type != "ARMATURE":
        return ["未选中有效的角色骨架。"], [], "无骨架"

    data = hair_profile(rig)
    chains = data.get("chains", [])
    colliders = data.get("colliders", [])

    if "head" not in rig.data.bones:
        errors.append("骨架中缺少必需的原生骨骼 'head'。")

    missing_col_bones = [b for b in COLLIDER_BONES if b not in rig.data.bones]
    if missing_col_bones:
        warnings.append("骨架缺少部分标准碰撞槽骨骼: " + ", ".join(missing_col_bones))

    if len(chains) > MAX_RUNTIME_CHAINS:
        errors.append(f"物理链数量 {len(chains)} 超过运行时上限 {MAX_RUNTIME_CHAINS}。")
    if len(colliders) > MAX_RUNTIME_COLLIDERS:
        errors.append(f"碰撞体数量 {len(colliders)} 超过运行时上限 {MAX_RUNTIME_COLLIDERS}。")

    if chains:
        try:
            validated_chains(rig, data)
        except ValueError as exc:
            errors.append(str(exc))

        # Check if any child mesh actually carries weights for these physics bones
        chain_bones = {b for ch in chains for b in ch["bones"]}
        weighted_meshes = 0
        for obj in rig.children:
            if obj.type != "MESH" or obj.get(ZERO_HIDE):
                continue
            if any(vg.name in chain_bones for vg in obj.vertex_groups):
                weighted_meshes += 1
        if weighted_meshes == 0:
            errors.append("骨架下没有任何子网格拥有物理链骨骼的顶点组（权重）。请确认头发/布料网格已刷上对应发骨权重。")
    else:
        warnings.append("尚未添加物理骨骼链（将仅导出自发光/表情指纹）。")

    if not colliders and chains:
        warnings.append("尚未配置碰撞体，长发可能会穿透头颈或肩膀。建议点击「一键生成默认人形 5 碰撞体」。")

    for col in colliders:
        if col.get("bone") not in COLLIDER_BONES:
            warnings.append(f"碰撞体 '{col.get('name')}' 绑定在非标准槽骨骼 '{col.get('bone')}'，导出时将被跳过（仅支持 {', '.join(COLLIDER_BONES)}）。")

    if overlay_dir.strip():
        gen_dir = Path(bpy.path.abspath(overlay_dir)).resolve() / "base" / "generated"
        bmds = list(gen_dir.rglob("*.bmd6model")) if gen_dir.is_dir() else []
        if not bmds:
            warnings.append("挂载目录 base/generated 中暂无 .bmd6model，请先导出模型或使用「一键同步导出 BMD6 + 物理包」。")

    summary = f"物理链 {len(chains)}/{MAX_RUNTIME_CHAINS} · 碰撞体 {len(colliders)}/{MAX_RUNTIME_COLLIDERS} · 错误 {len(errors)} · 警告 {len(warnings)}"
    return errors, warnings, summary


def export_dyn_pack(rig, overlay_dir, include_extra_emissive=True):
    """Compile Blender rig's hair chains, colliders, shape keys & emissive VBs into base/generated/tew1_dyn.bin (v2)."""
    overlay = Path(bpy.path.abspath(str(overlay_dir))).resolve()
    gen_dir = overlay / "base" / "generated"
    if not gen_dir.is_dir():
        raise ValueError("所选挂载目录中找不到 base/generated，请先导出 BMD6 模型到挂载目录。")

    bmd_files = sorted(gen_dir.rglob("*.bmd6model"))
    if not bmd_files:
        raise ValueError("base/generated 中没有找到任何 .bmd6model 文件。")

    # 1. Read hair chains & colliders from rig profile
    data = hair_profile(rig)
    chains_out = []
    bone_name_to_idx = {}
    if data.get("chains"):
        validated = validated_chains(rig, data)
        for settings, bones in validated:
            nodes = [np.array(bones[0].bone.head_local, dtype=float)]
            for b in bones:
                bone_name_to_idx[b.name] = len(bone_name_to_idx)
                nodes.append(np.array(b.bone.tail_local, dtype=float))
            chains_out.append({
                "num_bones": len(bones),
                "stiffness": float(settings["stiffness"]),
                "damping": float(settings["damping"]),
                "gravity": float(settings["gravity"]),
                "radius": float(settings["radius"]),
                "nodes": np.asarray(nodes, dtype=float),
            })

    colliders_out = []
    for col in data.get("colliders", []):
        bname = col["bone"]
        if bname not in COLLIDER_BONES or bname not in rig.data.bones:
            continue
        m_bl = np.array(rig.data.bones[bname].matrix_local, dtype=float)
        s_arm = m_bl[:3, :3] @ np.array(col["start"], dtype=float) + m_bl[:3, 3]
        e_arm = m_bl[:3, :3] @ np.array(col["end"], dtype=float) + m_bl[:3, 3]
        colliders_out.append((COLLIDER_BONES.index(bname), s_arm, e_arm, float(col["radius"])))
    if len(colliders_out) > MAX_RUNTIME_COLLIDERS:
        raise ValueError(f"有效碰撞体数量 ({len(colliders_out)}) 超过上限 {MAX_RUNTIME_COLLIDERS}。")

    # 2. Gather child meshes (hair weighted, shape-keyed, and/or emissive candidates)
    child_meshes = [o for o in rig.children if o.type == "MESH" and not o.get(ZERO_HIDE)]
    mesh_infos = []
    for obj in child_meshes:
        info = _build_mesh_rest_and_data(rig, obj, bone_name_to_idx)
        if info:
            mesh_infos.append(info)

    hair_sources = [m for m in mesh_infos if m["hair_w"] is not None]
    face_sources = [m for m in mesh_infos if m["morphs"] is not None]
    emissive_excluded_sources = [m for m in mesh_infos if m["exclude_emissive"]]
    for m in hair_sources + face_sources + emissive_excluded_sources:
        if "kd" not in m:
            m["kd"] = _build_kdtree(m["pts"])
    rig_head_pos = np.array(rig.data.bones["head"].head_local, dtype=float) if "head" in rig.data.bones else np.zeros(3)

    if not hair_sources and not face_sources and not include_extra_emissive:
        raise ValueError("骨架下未找到物理发束权重、形态键，且未开启全身自发光标记。")

    # 3. Match against all BMD6 models in overlay
    skeletons_by_head = {}
    hair_matches = {}
    hair_weights_encoded = None
    face_matches = {}
    extra_char_fps = {}

    for path in bmd_files:
        model = bmd6.read_model(path.read_bytes())
        skel = model.skeleton
        if "head" not in skel.names:
            continue
        head_idx = skel.names.index("head")
        head_remap = int(skel.remap[head_idx])
        model_head_pos = skel.joints["head"]
        delta_head = model_head_pos - rig_head_pos
        head_align = np.eye(4)
        head_align[:3, 3] = delta_head

        if head_remap not in skeletons_by_head:
            col_remaps = [_pick_bone(skel, cb)[0] for cb in COLLIDER_BONES]
            jaw_r, jaw_j = _pick_bone(skel, "jaw")
            jaw_probe = jaw_j + np.array([3.2, 0.0, -3.0]) if jaw_r >= 0 else np.zeros(3)
            lid_l_r, lid_l_p = _pick_bone(skel, "eyelid_u_l_middle", "l_eyelid", "eyelid_u_l")
            lid_r_r, lid_r_p = _pick_bone(skel, "eyelid_u_r_middle", "r_eyelid", "eyelid_u_r")
            brow_l_r, brow_l_p = _pick_bone(skel, "eyebrow_l_middle", "l_eyebrow_00", "eyebrow_l_in")
            brow_r_r, brow_r_p = _pick_bone(skel, "eyebrow_r_middle", "r_eyebrow_00", "eyebrow_r_in")
            mc_l_r, mc_l_p = _pick_bone(skel, "mouth_u_l_corner", "mouth_l_side")
            mc_r_r, mc_r_p = _pick_bone(skel, "mouth_u_r_corner", "mouth_r_side")
            skeletons_by_head[head_remap] = {
                "head_remap": head_remap,
                "col_remaps": col_remaps,
                "head_align": head_align[:3, :4].astype(np.float32),
                "drivers": [
                    (jaw_r, jaw_probe), (lid_l_r, lid_l_p), (lid_r_r, lid_r_p),
                    (brow_l_r, brow_l_p), (brow_r_r, brow_r_p), (mc_l_r, mc_l_p), (mc_r_r, mc_r_p),
                ],
            }

        for s_idx, surf in enumerate(model.surfaces):
            if surf.count < 3 or _is_degenerate_hidden_surface(surf):
                continue
            pts_surf = surf.positions.astype(float) - delta_head
            pts3 = surf.positions[:3].astype("<f4")
            matched_as_hair_or_face = False

            # Match hair / cloth physics source
            for hs in hair_sources:
                if not _aabb_close(pts_surf, hs["pts"]):
                    continue
                nn_idx, nn_dist = _nearest_indices(pts_surf, hs["pts"], hs["kd"])
                if float(np.median(nn_dist)) < 0.05 and float(np.percentile(nn_dist, 98)) < 0.15:
                    w_mapped = hs["hair_w"][nn_idx]
                    if int((w_mapped.max(axis=1) > 0.005).sum()) < 8:
                        continue
                    # Runtime shares one hair_weights array across all matched hair VBs; ensure same vertCount
                    if hair_weights_encoded is not None and len(hair_weights_encoded) != surf.count:
                        continue
                    fp_key = (head_remap, surf.count, pts3.tobytes())
                    if fp_key not in hair_matches:
                        hair_matches[fp_key] = (head_remap, surf.count, pts3)
                    if hair_weights_encoded is None:
                        enc_i = np.full((surf.count, 4), 255, dtype=np.uint8)
                        enc_w = np.zeros((surf.count, 4), dtype=np.uint8)
                        for vi in range(surf.count):
                            row = w_mapped[vi]
                            nz = np.where(row > 0.005)[0]
                            if len(nz) == 0:
                                enc_i[vi, 0] = 255
                                enc_w[vi, 0] = 255
                                continue
                            order = nz[np.argsort(-row[nz])][:4]
                            ws = row[order].copy()
                            total = float(ws.sum())
                            items = [(int(b), float(w)) for b, w in zip(order, ws)]
                            if total < 0.995:
                                if len(items) == 4:
                                    items = [(int(b), float(w / total)) for b, w in zip(order, ws)]
                                else:
                                    items.append((255, 1.0 - total))
                            else:
                                items = [(int(b), float(w / total)) for b, w in zip(order, ws)]
                            q = [int(round(w * 255.0)) for _, w in items]
                            q[0] = max(0, min(255, q[0] + (255 - sum(q))))
                            for k, ((b, _), qw) in enumerate(zip(items, q)):
                                enc_i[vi, k] = b
                                enc_w[vi, k] = qw
                        hair_weights_encoded = np.hstack((enc_i, enc_w))
                    matched_as_hair_or_face = True
                    break

            # Match face shape-key source
            for fs in face_sources:
                if not _aabb_close(pts_surf, fs["pts"]):
                    continue
                nn_idx, nn_dist = _nearest_indices(pts_surf, fs["pts"], fs["kd"])
                if float(np.median(nn_dist)) < 0.05 and float(np.percentile(nn_dist, 98)) < 0.15:
                    fp_key = (head_remap, s_idx, surf.count, pts3.tobytes())
                    if fp_key not in face_matches:
                        channels = []
                        any_ch = False
                        for ci in range(len(CHANNEL_ALIASES)):
                            d = fs["morphs"][ci][nn_idx]
                            mag = np.linalg.norm(d, axis=1)
                            active = np.where(mag > 1e-4)[0]
                            if len(active) > 0:
                                any_ch = True
                            channels.append([(int(vi), float(d[vi, 0]), float(d[vi, 1]), float(d[vi, 2])) for vi in active])
                        if any_ch:
                            face_matches[fp_key] = (head_remap, s_idx & 0xFF, surf.count, pts3, channels)
                    matched_as_hair_or_face = True
                    break

            # Section 6 (v2): Extra Character Surface Fingerprints for F7/F8/F9 Self-Illumination
            if include_extra_emissive and not matched_as_hair_or_face and len(extra_char_fps) < 4096:
                # Only register custom forward-shader surfaces (skip unedited stock Sebastian materials)
                is_custom_mat = surf.material.startswith("textures/") and "characters/pl/" not in surf.material
                if is_custom_mat:
                    excluded = False
                    for ex in emissive_excluded_sources:
                        if not _aabb_close(pts_surf, ex["pts"]):
                            continue
                        _, ex_dist = _nearest_indices(pts_surf[:min(32, len(pts_surf))], ex["pts"], ex["kd"])
                        if float(np.median(ex_dist)) < 0.05:
                            excluded = True
                            break
                    if not excluded:
                        ekey = (surf.count, pts3.tobytes())
                        if ekey not in extra_char_fps:
                            extra_char_fps[ekey] = (surf.count, pts3)

    if not hair_matches and not face_matches and not extra_char_fps:
        raise ValueError("未在挂载目录的 BMD6 模型中匹配到当前角色的头发、面部或自定义自发光网格。")

    if hair_weights_encoded is None:
        hair_weights_encoded = np.zeros((0, 8), dtype=np.uint8)
        hair_matches = {}

    # 4. Write tew1_dyn.bin (v2)
    out_path = gen_dir / "tew1_dyn.bin"
    buf = bytearray()
    buf.extend(MAGIC)
    buf.extend(struct.pack(
        "<IIIIIII",
        VERSION,
        len(skeletons_by_head),
        len(chains_out),
        len(colliders_out),
        len(hair_matches),
        len(face_matches),
        len(CHANNEL_ALIASES),
    ))

    # Section 1: Skeleton profiles
    for hr in sorted(skeletons_by_head):
        sk = skeletons_by_head[hr]
        buf.extend(struct.pack("<B3x", hr))
        buf.extend(struct.pack("<5h2x", *sk["col_remaps"]))
        buf.extend(sk["head_align"].astype("<f4").tobytes())
        for dr, dp in sk["drivers"]:
            buf.extend(struct.pack("<h2x3f", dr, float(dp[0]), float(dp[1]), float(dp[2])))

    # Section 2: Hair / cloth chains
    for ch in chains_out:
        buf.extend(struct.pack("<I4f", ch["num_bones"], ch["stiffness"], ch["damping"], ch["gravity"], ch["radius"]))
        buf.extend(ch["nodes"].astype("<f4").tobytes())

    # Section 3: Colliders (in authoring rig bind space)
    for bslot, s_arm, e_arm, rad in colliders_out:
        buf.extend(struct.pack(
            "<I7f", bslot,
            float(s_arm[0]), float(s_arm[1]), float(s_arm[2]),
            float(e_arm[0]), float(e_arm[1]), float(e_arm[2]),
            float(rad),
        ))

    # Section 4: Hair fingerprints + shared hair weights
    for hr, vcnt, pts3 in hair_matches.values():
        buf.extend(struct.pack("<B3xI", hr, vcnt))
        buf.extend(pts3.tobytes())
    buf.extend(struct.pack("<I", len(hair_weights_encoded)))
    if len(hair_weights_encoded) > 0:
        buf.extend(hair_weights_encoded.tobytes())

    # Section 5: Face morph surfaces
    for hr, part, vcnt, pts3, channels in face_matches.values():
        buf.extend(struct.pack("<BB2xI", hr, part, vcnt))
        buf.extend(pts3.tobytes())
        for ch_entries in channels:
            buf.extend(struct.pack("<I", len(ch_entries)))
            for vi, dx, dy, dz in ch_entries:
                buf.extend(struct.pack("<H2x3f", vi, dx, dy, dz))

    # Section 6 (v2): Extra Character Surface Fingerprints (F7/F8/F9 self-illumination)
    buf.extend(struct.pack("<I", len(extra_char_fps)))
    for vcnt, pts3 in extra_char_fps.values():
        buf.extend(struct.pack("<I", vcnt))
        buf.extend(pts3.tobytes())

    out_path.write_bytes(bytes(buf))
    return {
        "path": str(out_path),
        "version": VERSION,
        "bytes": len(buf),
        "skeletons": len(skeletons_by_head),
        "chains": len(chains_out),
        "colliders": len(colliders_out),
        "hair_surfaces": len(hair_matches),
        "face_surfaces": len(face_matches),
        "extra_emissive": len(extra_char_fps),
    }


class TEW1ValidatePhysics(bpy.types.Operator):
    bl_idname = "object.tew1_validate_physics"
    bl_label = "物理配置导出前检查"
    bl_description = "检查骨骼链、碰撞体槽位、权重覆盖与挂载目录状态"

    @classmethod
    def poll(cls, context):
        return rig_object(context) is not None

    def execute(self, context):
        rig = rig_object(context)
        ws = context.scene.tew1_workspace
        errors, warnings, summary = validate_physics_setup(rig, ws.overlay)
        for w in warnings:
            self.report({"WARNING"}, w)
        for e in errors:
            self.report({"ERROR"}, e)
        if not errors and not warnings:
            self.report({"INFO"}, "物理配置检查全部通过！" + summary)
        elif not errors:
            self.report({"WARNING"}, "物理配置可用但有提示：" + summary)
        else:
            self.report({"ERROR"}, "物理配置存在错误：" + summary)
        return {"FINISHED"}


class TEW1ExportDynPack(bpy.types.Operator):
    bl_idname = "export_scene.tew1_dyn_pack"
    bl_label = "导出动态物理包 (tew1_dyn.bin v2)"
    bl_description = "将当前角色的物理链、碰撞体、形态键与全身自发光指纹打包为 base/generated/tew1_dyn.bin (v2)"
    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, _event):
        ws = getattr(context.scene, "tew1_workspace", None)
        if ws and ws.overlay.strip():
            self.directory = ws.overlay
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            rig = rig_object(context)
            if not rig:
                raise ValueError("请先选中角色骨架或其子网格。")
            state = context.scene.tew1_hair
            res = export_dyn_pack(rig, self.directory, include_extra_emissive=state.auto_include_emissive)
        except Exception as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"已导出 tew1_dyn.bin v2（{res['bytes']:,} B | {res['chains']} 链 | {res['colliders']} 碰撞体 | "
            f"{res['hair_surfaces']} 头发VB | {res['face_surfaces']} 面部VB | {res['extra_emissive']} 自发光VB）"
        )
        return {"FINISHED"}


class TEW1SyncExportAll(bpy.types.Operator):
    bl_idname = "export_scene.tew1_sync_export_all"
    bl_label = "一键同步导出 BMD6 + tew1_dyn.bin (推荐)"
    bl_description = "先导出当前骨架的 BMD6 模型到挂载目录，再立即重编译 tew1_dyn.bin v2，保证顶点指纹 100% 同步"

    @classmethod
    def poll(cls, context):
        from . import active_rig
        rig = active_rig(context)
        return bool(context.mode == "OBJECT" and rig and rig.get("tew1_overlay_asset"))

    def execute(self, context):
        from . import active_rig, export_model
        from .workflow import loose_root
        ws = context.scene.tew1_workspace
        state = context.scene.tew1_hair
        rig = active_rig(context)
        try:
            root = loose_root(ws.overlay)
            key = PurePosixPath(rig["tew1_overlay_asset"])
            if key.is_absolute() or ".." in key.parts or not key.as_posix().startswith("generated/nextgen/"):
                raise ValueError("模板没有可用的游戏内资源路径。")
            path = (root / "base" / key).resolve()
            if not path.is_relative_to(root) or path.suffix != ".bmd6model":
                raise ValueError("BMD6 输出路径无效。")
            path.parent.mkdir(parents=True, exist_ok=True)
            export_model(path, rig, True)
            res = export_dyn_pack(rig, root, include_extra_emissive=state.auto_include_emissive)
        except Exception as err:
            self.report({"ERROR"}, str(err))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"同步导出成功：{path.name} + tew1_dyn.bin v2（{res['chains']} 链 | {res['hair_surfaces']} 头发VB | {res['extra_emissive']} 自发光VB）"
        )
        return {"FINISHED"}


class TEW1ToggleMeshEmissive(bpy.types.Operator):
    bl_idname = "object.tew1_toggle_mesh_emissive"
    bl_label = "切换当前网格自发光排除"
    bl_description = "开启排除后，该网格不加入 F7/F8/F9 自发光列表"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH")

    def execute(self, context):
        obj = context.object
        obj[EXCLUDE_EMISSIVE] = not bool(obj.get(EXCLUDE_EMISSIVE, False))
        state = "已排除自发光" if obj[EXCLUDE_EMISSIVE] else "已纳入自发光"
        self.report({"INFO"}, f"{obj.name}: {state}")
        return {"FINISHED"}


CLASSES = (
    TEW1ValidatePhysics,
    TEW1ExportDynPack,
    TEW1SyncExportAll,
    TEW1ToggleMeshEmissive,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
