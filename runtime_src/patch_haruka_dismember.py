"""Fix all Haruka dismemberment / gore surface mappings across every player BMD6 model:
1. Head dismemberment (headdamage / headless / Crash / dismembered):
   - Move mat_02 (hair), mat_01 (head acc 1), mat_09 (head acc 2) off body/headdamage-visible slots
     (m_beard, m_vest__nv, m_holster__lt, m_coat_button, m_hand_r, m_necktie, etc.)
     onto a true head-only slot hidden in BOTH headdamage AND headless (e.g. m_face / m_mouth3),
     while keeping stock m_hair intact (zeroed indices) for Havok cloth (.clh) compatibility.
   - Add mat_01 & mat_09 onto the severed head prop (pl0001_ng) so hair accessories stay on the severed head.
2. Limb dismemberment on pl0000_ng (armless_lr / Crash / dismembered):
   - Split mat_00 (body+arms+legs) cleanly by bone weights into native pl0000.md6.decl slots:
       * m_hand_l          <- Left arm  (hidden in armless_lr, Crash, dismembered)
       * m_r_shrit_arm__na <- Right arm (hidden in armless_lr, Crash, dismembered)
       * m_pants_leg__np   <- Legs/boots (hidden in Crash, dismembered)
       * m_shirt__nn       <- Torso/upper dress
"""

from pathlib import Path
import sys
import numpy as np

TEW_ROOT = Path(r'F:\dspr_mod\tew_external_mount')
sys.path.insert(0, str(TEW_ROOT / 'haruka'))
sys.path.insert(0, str(TEW_ROOT))

import bmd6
import campaign


LEFT_ARM_BONES = {
    'l_upperarm', 'l_forearm', 'l_hand',
    'l_thumb_00', 'l_thumb_01', 'l_thumb_02',
    'l_index_01', 'l_index_02', 'l_index_03',
    'l_middle_01', 'l_middle_02', 'l_middle_03',
    'l_ring_01', 'l_ring_02', 'l_ring_03',
    'l_pinky_01', 'l_pinky_02', 'l_pinky_03',
}
RIGHT_ARM_BONES = {
    'r_upperarm', 'r_forearm', 'r_hand',
    'r_thumb_00', 'r_thumb_01', 'r_thumb_02',
    'r_index_01', 'r_index_02', 'r_index_03',
    'r_middle_01', 'r_middle_02', 'r_middle_03',
    'r_ring_01', 'r_ring_02', 'r_ring_03',
    'r_pinky_01', 'r_pinky_02', 'r_pinky_03',
}
LEG_BONES = {
    'l_thigh', 'r_thigh', 'l_shin', 'r_shin', 'l_foot', 'r_foot', 'l_toe', 'r_toe',
}

# Models that contain BOTH body & head: target head slot name hidden in headless & headdamage
FULL_MODEL_HEAD_SLOT = {
    'pl0000_ng': 'm_face',
    'pl0017_ng': 'm_face',
    'pl0018_ng': 'm_face',
    'pl0020_ng': 'm_mouth3',
    'pl0201_ng': 'm_tong',
    'pl0220_ng': 'm_face',
    'pl0220_m':  'm_face',
    'pl0220_l':  'm_face',
    'pl0230_ng': 'm_face',
    'em5002_ng': 'm_face',
}

HEAD_MATS = {
    'textures/tew_haruka/mat_01',
    'textures/tew_haruka/mat_02',
    'textures/tew_haruka/mat_09',
}


def make_collapsed_placeholder(name: str, template_surf: bmd6.Surface) -> bmd6.Surface:
    return bmd6.Surface(
        name=name,
        material=template_surf.material,
        vertices=template_surf.vertices[:32] * 3,
        indices=np.zeros((1, 3), dtype='u2'),
        flags=template_surf.flags,
        trailer=template_surf.trailer,
    )


def subset_surface(surf: bmd6.Surface, tri_mask: np.ndarray, new_name: str) -> bmd6.Surface:
    picked = surf.indices[tri_mask]
    uniq, inv = np.unique(picked.reshape(-1), return_inverse=True)
    new_indices = inv.reshape(-1, 3).astype(np.uint16)
    raw = np.frombuffer(surf.vertices, dtype='u1').reshape(-1, 32)
    new_verts = raw[uniq].tobytes()
    return bmd6.Surface(
        name=new_name,
        material=surf.material,
        vertices=new_verts,
        indices=new_indices,
        flags=surf.flags,
        trailer=surf.trailer,
    )


def split_pl0000_body_surface(model: bmd6.Model, body_surf: bmd6.Surface):
    """Split mat_00 body surface into torso, left arm, right arm, and legs by vertex skin weights."""
    remap_to_name = {int(r): nm for nm, r in zip(model.skeleton.names, model.skeleton.remap)}
    raw = np.frombuffer(body_surf.vertices, dtype='u1').reshape(-1, 32)

    # Compute per-vertex group score: 0=torso, 1=left_arm, 2=right_arm, 3=legs
    v_group = np.zeros(body_surf.count, dtype=np.int32)
    for vi in range(body_surf.count):
        wcode = int(raw[vi, 23])
        w1 = (wcode >> 4) / 30.0
        w2 = ((wcode >> 2) & 3) / 9.0
        w3 = (wcode & 3) / 12.0
        w0 = max(0.0, 1.0 - (w1 + w2 + w3))
        scores = [0.0, 0.0, 0.0, 0.0]
        for j, w in zip(raw[vi, 28:32], (w0, w1, w2, w3)):
            if w <= 0.0:
                continue
            bn = remap_to_name.get(int(j), '')
            if bn in LEFT_ARM_BONES:
                scores[1] += w
            elif bn in RIGHT_ARM_BONES:
                scores[2] += w
            elif bn in LEG_BONES:
                scores[3] += w
            else:
                scores[0] += w
        # Assign to limb only if limb weight dominates (>= 0.5) so torso seams stay clean
        best_limb = int(np.argmax(scores[1:])) + 1
        if scores[best_limb] >= 0.50:
            v_group[vi] = best_limb
        else:
            v_group[vi] = 0

    tris = body_surf.indices
    tri_g = v_group[tris]  # (T, 3)
    # A triangle belongs to a limb if at least 2 of its 3 vertices belong to that limb
    is_larm = np.sum(tri_g == 1, axis=1) >= 2
    is_rarm = (~is_larm) & (np.sum(tri_g == 2, axis=1) >= 2)
    is_legs = (~is_larm) & (~is_rarm) & (np.sum(tri_g == 3, axis=1) >= 2)
    is_torso = (~is_larm) & (~is_rarm) & (~is_legs)

    parts = {
        'm_shirt__nn':       subset_surface(body_surf, is_torso, 'm_shirt__nn'),
        'm_hand_l':          subset_surface(body_surf, is_larm,  'm_hand_l'),
        'm_r_shrit_arm__na': subset_surface(body_surf, is_rarm,  'm_r_shrit_arm__na'),
        'm_pants_leg__np':   subset_surface(body_surf, is_legs,  'm_pants_leg__np'),
    }
    return parts


def transform_head_surface_to_target(src_surf: bmd6.Surface, src_skel, dst_skel, new_name: str, template_trailer: bytes):
    """Transform a head-bound surface (mat_01 / mat_09) from pl0000_ng into pl0001_ng severed head space."""
    matrices, _ = campaign.transforms(src_skel, dst_skel)
    M = matrices[src_skel.names.index('head')]
    R = M[:3, :3]
    T = M[:3, 3]
    head_remap = int(dst_skel.remap[dst_skel.names.index('head')])

    raw = np.frombuffer(src_surf.vertices, dtype='u1').reshape(-1, 32).copy()
    pos = np.ndarray((src_surf.count, 3), dtype='>f4', buffer=raw, strides=(32, 4)).astype(float)
    new_pos = (pos @ R.T + T).astype('>f4')
    raw[:, :12] = new_pos.view('u1').reshape(-1, 12)

    # Rotate normals & tangents cleanly by R
    for offset in (20, 24):
        vec = raw[:, offset:offset + 3].astype(float) - 127.5
        nrm = np.linalg.norm(vec, axis=1, keepdims=True)
        vec = vec / np.maximum(nrm, 1e-8)
        rot = vec @ R.T
        rot = rot / np.maximum(np.linalg.norm(rot, axis=1, keepdims=True), 1e-8)
        raw[:, offset:offset + 3] = np.rint(np.clip(rot, -1.0, 1.0) * 127.5 + 127.5).astype('u1')

    # Pin 100% to target head bone
    raw[:, 23] = 0
    raw[:, 28] = head_remap
    raw[:, 29] = head_remap
    raw[:, 30] = head_remap
    raw[:, 31] = head_remap

    return bmd6.Surface(
        name=new_name,
        material=src_surf.material,
        vertices=raw.tobytes(),
        indices=src_surf.indices.copy(),
        flags=src_surf.flags,
        trailer=template_trailer,
    )


def patch_all_dismemberment(entries: list) -> list:
    """entries: list of (arcname, bytes). Returns updated list of (arcname, bytes)."""
    # First parse pl0000_ng as donor for mat_01 & mat_09 to copy onto severed head pl0001_ng
    pl0000_model = None
    for name, data in entries:
        if Path(name).stem.lower() == 'pl0000_ng' and name.lower().endswith('.bmd6model'):
            pl0000_model = bmd6.read_model(data)
            break

    out_entries = []
    for name, data in entries:
        if not name.lower().endswith('.bmd6model'):
            out_entries.append((name, data))
            continue

        stem = Path(name).stem
        stem_l = stem.lower()

        if stem_l in FULL_MODEL_HEAD_SLOT:
            model = bmd6.read_model(data)
            head_slot = FULL_MODEL_HEAD_SLOT[stem_l]
            existing_names = {s.name for s in model.surfaces}
            if head_slot not in existing_names:
                out_entries.append((name, data))
                continue

            # Find a harmless template surface for collapsed placeholders (so meshKits never warn)
            placeholder_tpl = next(
                (s for s in model.surfaces if s.count == 3 and not s.material.startswith('textures/tew_haruka/')),
                model.surfaces[0],
            )

            # On pl0000_ng, also split mat_00 body into torso / left arm / right arm / legs!
            split_body_map = {}
            if stem_l == 'pl0000_ng':
                body_surf = next((s for s in model.surfaces if s.material == 'textures/tew_haruka/mat_00'), None)
                if body_surf is not None:
                    split_body_map = split_pl0000_body_surface(model, body_surf)
                    print(
                        f"  [Dismember] pl0000_ng body split: "
                        + ", ".join(f"{k}={v.count}v/{len(v.indices)}t" for k, v in split_body_map.items())
                    )

            new_surfaces = []
            freed_slot_names = []
            for s in model.surfaces:
                if stem_l == 'pl0000_ng' and s.name in split_body_map:
                    # Replace m_shirt__nn, m_hand_l, m_r_shrit_arm__na, m_pants_leg__np with split Haruka body parts!
                    new_surfaces.append(split_body_map[s.name])
                    continue

                if s.material in HEAD_MATS and s.name != head_slot:
                    # Move hair (mat_02) and head accessories (mat_01, mat_09) onto true head slot!
                    old_name = s.name
                    freed_slot_names.append(old_name)
                    new_surfaces.append(
                        bmd6.Surface(head_slot, s.material, s.vertices, s.indices, s.flags, s.trailer)
                    )
                    continue

                new_surfaces.append(s)

            # Keep exact stock surface count (<= 31, safely inside uint32 visibility bitmasks!).
            # Retail TEW1 silently skips unused meshKit names when those invisible slots are omitted.
            patched = bmd6.write_model(model, new_surfaces)
            assert len(new_surfaces) <= 31, f"{stem} exceeded 31 surfaces ({len(new_surfaces)})!"
            print(
                f"  [Dismember] {stem:12s}: moved {len(freed_slot_names)} head surfaces ({freed_slot_names}) -> '{head_slot}' (surfs={len(new_surfaces)})"
            )
            out_entries.append((name, patched))
            continue

        if stem_l == 'pl0001_ng' and pl0000_model is not None:
            # Add mat_01 & mat_09 head accessories onto severed head prop pl0001_ng!
            model = bmd6.read_model(data)
            have_mats = {s.material for s in model.surfaces}
            face_tpl = next((s for s in model.surfaces if s.name == 'm_face1'), model.surfaces[0])
            new_surfaces = list(model.surfaces)
            added = []
            for mat_name in ('textures/tew_haruka/mat_01', 'textures/tew_haruka/mat_09'):
                if mat_name in have_mats:
                    continue
                src_s = next((s for s in pl0000_model.surfaces if s.material == mat_name), None)
                if src_s is not None:
                    new_surfaces.append(
                        transform_head_surface_to_target(src_s, pl0000_model.skeleton, model.skeleton, 'm_face1', face_tpl.trailer)
                    )
                    added.append(mat_name[-6:])
            if added:
                patched = bmd6.write_model(model, new_surfaces)
                print(f"  [Dismember] pl0001_ng (severed head): added head accessories {added} -> 'm_face1'")
                out_entries.append((name, patched))
            else:
                out_entries.append((name, data))
            continue

        out_entries.append((name, data))

    return out_entries
