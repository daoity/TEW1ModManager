"""Compile Haruka's hair physics rig and 15 independent PMX facial morphs into haruka_runtime.bin."""

import argparse
import json
from pathlib import Path
import struct
import sys

import numpy as np

TEW_ROOT = Path(r'F:\dspr_mod\tew_external_mount')
sys.path.insert(0, str(TEW_ROOT / 'haruka'))
sys.path.insert(0, str(TEW_ROOT))

import bmd6
import build
import campaign
import independent_face
import morph_targets

MAGIC = b'TEWH'
VERSION = 2

# 15 independent Haruka PMX morph channels
MORPH_SPECS = (
    ('Blink',       'まばたき',     1.00, False),
    ('WinkL',       'ウィンク',     1.00, False),
    ('WinkR',       'ウィンク右',   1.00, False),
    ('A',           '嘴型-啊',      1.13, True),
    ('I',           'い',           1.04, True),
    ('U',           'う',           1.04, True),
    ('E',           '嘴型-ei',      1.05, True),
    ('O',           '嘴型-哦',      1.10, True),
    ('Smile',       '嘴型-笑2',     1.00, False),
    ('SmileEyes',   '笑い',         1.00, False),
    ('Surprised',   'びっくり',     1.00, False),
    ('BrowWorried', '困る',         1.00, False),
    ('BrowAngry',   '怒り',         1.00, False),
    ('BrowUp',      '上',           1.00, False),
    ('Frown',       '嘴型-嘴角下移', 1.00, False),
)

FACE_PARTS = (3, 5, 6, 7)
COLLIDER_BONES = ('head', 'neck_00', 'spine_02', 'l_shoulder', 'r_shoulder')


def build_extended_face_targets(pmx):
    if pmx.materials[3].name != 'female02_face_inside01' or len(pmx.vertices) <= independent_face.UPPER_MOUTH.stop:
        raise ValueError('The authored target table requires the original Haruka PMX.')
    positions = np.asarray([v.co for v in pmx.vertices], dtype=float)
    by_name = {m.name: m for m in pmx.morphs}
    lip = independent_face.lower_lip_indices(pmx, build.influences)
    hinge = np.asarray(pmx.bones[169].location, dtype=float)
    result = {}
    for name, src_name, strength, has_teeth in MORPH_SPECS:
        if src_name not in by_name:
            raise ValueError(f'Missing PMX morph {src_name!r} for channel {name!r}.')
        delta = np.zeros_like(positions)
        for item in by_name[src_name].offsets:
            delta[item.index] = np.asarray(item.offset, dtype=float) * strength
        if has_teeth:
            delta[independent_face.LOWER_MOUTH] = independent_face.lower_dental_delta(positions, delta, lip, hinge)
            delta[independent_face.UPPER_MOUTH] = 0.0
        result[name] = delta
    return result


def build_hair_chains(hair_json_path, pmx, donor_joints):
    profile = json.loads(hair_json_path.read_text(encoding='utf8'))
    chains = []
    bone_name_to_idx = {}

    for ch in profile['chains']:
        nodes = [np.asarray(ch['rest'][0]['head'], dtype=float)]
        for r in ch['rest']:
            bone_name_to_idx[r['name']] = len(bone_name_to_idx)
            nodes.append(np.asarray(r['tail'], dtype=float))
        stiffness = float(ch['stiffness'])
        damping = float(ch['damping'])
        gravity = float(ch['gravity'])
        # Reduce side_l / side_r sway amplitude by ~60% while keeping smooth soft motion
        if ch['name'] in ('side_l', 'side_r'):
            stiffness = 480.0
            damping = 0.18
            gravity = 6.5
        chains.append({
            'name': ch['name'],
            'bones': list(ch['bones']),
            'stiffness': stiffness,
            'damping': damping,
            'gravity': gravity,
            'radius': float(ch['radius']),
            'nodes': np.asarray(nodes, dtype=float),
        })

    # Add gentle front bangs chain (haruka_hair02_bone_F00..F02) using exact PMX-to-TEW transform
    # Compute PMX->TEW scale & offset from head-aligned L00/R00 rest positions vs PMX locations
    pmx_by_name = {b.name: np.asarray(b.location, dtype=float) for b in pmx.bones}
    pmx_l00_tew = pmx_by_name['haruka_hair02_bone_L00'] @ build.AXES * 5.15
    tew_l00 = chains[0]['nodes'][0]
    pmx_to_tew_offset = tew_l00 - pmx_l00_tew

    # Verify accuracy on R00 & LB00
    for check_name, check_node in (('haruka_hair02_bone_R00', chains[1]['nodes'][0]),
                                   ('haruka_hair02_bone_LB00', chains[2]['nodes'][0])):
        pred = pmx_by_name[check_name] @ build.AXES * 5.15 + pmx_to_tew_offset
        err = float(np.linalg.norm(pred - check_node))
        if err > 0.05:
            raise ValueError(f'PMX->TEW hair bone alignment error {err:.4f} on {check_name}')

    front_names = ['haruka_hair02_bone_F00', 'haruka_hair02_bone_F01', 'haruka_hair02_bone_F02']
    if all(n in pmx_by_name for n in front_names):
        f_nodes = [pmx_by_name[n] @ build.AXES * 5.15 + pmx_to_tew_offset for n in front_names]
        # Tip of F02: extrapolate along F01->F02 or use F03 if present
        if 'haruka_hair02_bone_F03' in pmx_by_name:
            f_tip = pmx_by_name['haruka_hair02_bone_F03'] @ build.AXES * 5.15 + pmx_to_tew_offset
        else:
            f_tip = f_nodes[-1] + (f_nodes[-1] - f_nodes[-2]) * 0.85
        f_nodes.append(f_tip)
        for n in front_names:
            bone_name_to_idx[n] = len(bone_name_to_idx)
        chains.append({
            'name': 'front_bangs',
            'bones': front_names,
            'stiffness': 1400.0,
            'damping': 0.22,
            'gravity': 1.5,
            'radius': 0.25,
            'nodes': np.asarray(f_nodes, dtype=float),
        })

    # Convert colliders from BMD6 bone-local space to pl0020_ng armature/bind space
    colliders = []
    for col in profile['colliders']:
        bname = col['bone']
        bidx = COLLIDER_BONES.index(bname)
        colliders.append({
            'name': col['name'],
            'bone_slot': bidx,
            'bone_name': bname,
            'local_start': np.asarray(col['start'], dtype=float),
            'local_end': np.asarray(col['end'], dtype=float),
            'radius': float(col['radius']),
        })

    return chains, bone_name_to_idx, colliders


def build_hair_vertex_weights(pmx, donor, neutral, bone_name_to_idx):
    """Map PMX mat_02 vertex weights onto donor pl0020_ng mat_02 6349 vertices."""
    pmx_bone_to_hair = {}
    for i, b in enumerate(pmx.bones):
        if b.name in bone_name_to_idx:
            pmx_bone_to_hair[i] = bone_name_to_idx[b.name]

    # Build per-PMX-vertex dense hair weight vector (len = num_hair_bones)
    num_hair_bones = len(bone_name_to_idx)
    all_w = np.zeros((len(pmx.vertices), num_hair_bones), dtype=float)
    for vi, v in enumerate(pmx.vertices):
        for bi, w in build.influences(v.weight):
            if bi in pmx_bone_to_hair and w > 1e-5:
                all_w[vi, pmx_bone_to_hair[bi]] += w

    # Extract mat_02 surface from PMX with periodic UV handling identical to build.py
    tris = np.asarray(pmx.faces)
    cursor = 0
    all_points, all_normals, all_uv = neutral
    src_ref = None
    src_w = None
    src_faces = None
    for part, mat in enumerate(pmx.materials):
        cnt = mat.vertex_count // 3
        picked = tris[cursor:cursor + cnt]
        cursor += cnt
        if part != 2:
            continue
        verts, faces = np.unique(picked, return_inverse=True)
        faces = faces.reshape(-1, 3)
        pts, norms, uv, wmat = all_points[verts], all_normals[verts], all_uv[verts], all_w[verts]
        if np.any((uv < 0.0) | (uv > 1.0)):
            (pts, norms, uv, wmat, faces), _ = campaign.geometry.periodic_uv(
                pts, norms, uv, wmat, faces, lambda data, coeff: coeff @ data)
        src_ref = np.column_stack((pts, uv))
        src_w = wmat
        src_faces = faces
        break

    # Match donor mat_02 surface
    hair_surf = next(s for s in donor.surfaces if s.material == 'textures/tew_haruka/mat_02')
    existing = np.ndarray((hair_surf.count, 5), '>f4', buffer=hair_surf.vertices, strides=(32, 4)).astype(float)
    if len(hair_surf.indices) != len(src_faces):
        raise ValueError(f'Hair triangle count mismatch: {len(hair_surf.indices)} vs {len(src_faces)}')
    gap = np.linalg.norm(existing[hair_surf.indices][:, :, None, :] - src_ref[src_faces][:, None, :, :], axis=-1)
    max_gap = float(np.max(np.min(gap, axis=-1)))
    if max_gap > 0.025:
        raise ValueError(f'Hair corner match failed: max_gap={max_gap:.4f}')
    match = np.take_along_axis(src_faces, np.argmin(gap, axis=-1), axis=1)
    corner_w = src_w[match.reshape(-1)]

    # Average per BMD6 vertex (since hair vertices with same index share same weights)
    v_sum = np.zeros((hair_surf.count, num_hair_bones), dtype=float)
    v_cnt = np.zeros(hair_surf.count, dtype=float)
    corners = hair_surf.indices.reshape(-1)
    np.add.at(v_sum, corners, corner_w)
    np.add.at(v_cnt, corners, 1.0)
    v_w = v_sum / np.maximum(v_cnt[:, None], 1.0)

    # Encode top-4 (boneIdx, weight_u8) per vertex, where 255 = rigid head scalp
    encoded_idx = np.full((hair_surf.count, 4), 255, dtype=np.uint8)
    encoded_w = np.zeros((hair_surf.count, 4), dtype=np.uint8)
    active_verts = 0
    for vi in range(hair_surf.count):
        row = v_w[vi]
        nz = np.where(row > 0.005)[0]
        if len(nz) == 0:
            encoded_idx[vi, 0] = 255
            encoded_w[vi, 0] = 255
            continue
        active_verts += 1
        order = nz[np.argsort(-row[nz])][:4]
        ws = row[order].copy()
        total = float(ws.sum())
        # Remaining weight stays pinned to rigid head scalp (255)
        items = [(int(b), float(w)) for b, w in zip(order, ws)]
        if total < 0.995:
            if len(items) == 4:
                ws = ws / total
                items = [(int(b), float(w)) for b, w in zip(order, ws)]
            else:
                items.append((255, 1.0 - total))
        else:
            ws = ws / total
            items = [(int(b), float(w)) for b, w in zip(order, ws)]

        # Quantize to uint8 summing to 255
        q = [int(round(w * 255.0)) for _, w in items]
        diff = 255 - sum(q)
        q[0] = max(0, min(255, q[0] + diff))
        for k, ((b, _), qw) in enumerate(zip(items, q)):
            encoded_idx[vi, k] = b
            encoded_w[vi, k] = qw

    print(f'Hair weights mapped: {hair_surf.count} verts ({active_verts} dynamic hair verts, max_gap={max_gap:.5f})')
    return encoded_idx, encoded_w


def pick_bone(skel, *names):
    for n in names:
        if n in skel.names:
            idx = skel.names.index(n)
            return int(skel.remap[idx]), skel.joints[n]
    return -1, np.zeros(3, dtype=float)


def compile_pack(overlay_dir, hair_json_path, pmx_path, out_path):
    pmx = build.load_pmx(pmx_path)
    donor = bmd6.read_model((overlay_dir / 'base' / campaign.asset_path('pl0020_ng')).read_bytes())

    assignments = []
    build.skin_weights(pmx, donor, assignments, False, False)
    neutral = build.coordinates(pmx, donor.skeleton.joints, 5.15, .24, assignments)

    # 1. Hair rig + vertex weights
    chains, bone_name_to_idx, colliders_raw = build_hair_chains(hair_json_path, pmx, donor.skeleton.joints)
    hair_idx, hair_w = build_hair_vertex_weights(pmx, donor, neutral, bone_name_to_idx)

    # Transform colliders to pl0020_ng armature/bind space once (verified 0.00e+00 error!)
    colliders_arm = []
    for col in colliders_raw:
        bi = donor.skeleton.names.index(col['bone_name'])
        m_inv = donor.skeleton.inverse[bi]
        m_bind = np.linalg.inv(np.vstack((m_inv, [0.0, 0.0, 0.0, 1.0])))
        s_arm = m_bind[:3, :3] @ col['local_start'] + m_bind[:3, 3]
        e_arm = m_bind[:3, :3] @ col['local_end'] + m_bind[:3, 3]
        colliders_arm.append((col['bone_slot'], s_arm, e_arm, col['radius']))

    # 2. Extended 15 facial morphs in TEW coordinate space
    face_shapes = build_extended_face_targets(pmx)
    shape_names = [spec[0] for spec in MORPH_SPECS]
    offsets = np.stack([face_shapes[n] @ build.AXES * 5.15 for n in shape_names], axis=1)
    pieces = morph_targets.prepared_faces(pmx, offsets, neutral)

    # 3. Scan ALL Haruka models in overlay to collect unique skeletons, hair fingerprints, face morph tables, and extra body/accessory surface fingerprints
    skeletons_by_head = {}
    hair_matches = {}
    face_matches = {}
    extra_char_fps = {}

    for path in sorted((overlay_dir / 'base').rglob('*.bmd6model')):
        model = bmd6.read_model(path.read_bytes())
        skel = model.skeleton
        haruka_surfs = [s for s in model.surfaces if s.material.startswith('textures/tew_haruka/mat_0')]
        if not haruka_surfs:
            continue

        # Collect ALL non-hair, non-face character surface VBs (body, clothes, eyes, accessories)
        # so in-game Self-Illumination Mode covers 100% of the character cleanly!
        for surf in haruka_surfs:
            part = int(surf.material[-2:])
            if part != 2 and part not in FACE_PARTS:
                pts3 = surf.positions[:3].astype('<f4')
                ekey = (surf.count, pts3.tobytes())
                if ekey not in extra_char_fps:
                    extra_char_fps[ekey] = (surf.count, pts3)

        head_surf = next((s for s in haruka_surfs if int(s.material[-2:]) in (2, 3, 5, 6, 7)), None)
        if head_surf is None:
            continue

        head_remap = int(np.frombuffer(head_surf.vertices, 'u1').reshape(-1, 32)[0, 28])

        transform = np.eye(4)
        if path.stem not in campaign.CORE:
            matrices, _ = campaign.transforms(donor.skeleton, skel)
            transform = matrices[donor.skeleton.names.index('head')]

        if head_remap not in skeletons_by_head:
            col_remaps = []
            for cb in COLLIDER_BONES:
                r, _ = pick_bone(skel, cb)
                col_remaps.append(r)

            # Facial driver probes in this skeleton's bind space
            jaw_r, jaw_j = pick_bone(skel, 'jaw')
            # Chin probe offset forward (+X) and slightly down (-Z) from jaw hinge so jaw pitch rotates it visibly
            jaw_probe = jaw_j + np.array([3.2, 0.0, -3.0]) if jaw_r >= 0 else np.zeros(3)

            lid_l_r, lid_l_p = pick_bone(skel, 'eyelid_u_l_middle', 'l_eyelid', 'eyelid_u_l')
            lid_r_r, lid_r_p = pick_bone(skel, 'eyelid_u_r_middle', 'r_eyelid', 'eyelid_u_r')
            brow_l_r, brow_l_p = pick_bone(skel, 'eyebrow_l_middle', 'l_eyebrow_00', 'eyebrow_l_in')
            brow_r_r, brow_r_p = pick_bone(skel, 'eyebrow_r_middle', 'r_eyebrow_00', 'eyebrow_r_in')
            mc_l_r, mc_l_p = pick_bone(skel, 'mouth_u_l_corner', 'mouth_l_side')
            mc_r_r, mc_r_p = pick_bone(skel, 'mouth_u_r_corner', 'mouth_r_side')

            skeletons_by_head[head_remap] = {
                'head_remap': head_remap,
                'sample_model': path.stem,
                'col_remaps': col_remaps,
                'head_align': transform[:3, :4].astype(np.float32),
                'drivers': [
                    (jaw_r, jaw_probe),
                    (lid_l_r, lid_l_p),
                    (lid_r_r, lid_r_p),
                    (brow_l_r, brow_l_p),
                    (brow_r_r, brow_r_p),
                    (mc_l_r, mc_l_p),
                    (mc_r_r, mc_r_p),
                ],
            }

        for surf in haruka_surfs:
            part = int(surf.material[-2:])
            pts3 = surf.positions[:3].astype('<f4')
            fp_key = (head_remap, part, surf.count, pts3.tobytes())

            if part == 2 and fp_key not in hair_matches:
                hair_matches[fp_key] = (head_remap, surf.count, pts3)
            elif part in FACE_PARTS and fp_key not in face_matches:
                changed = morph_targets.match_corners(surf, pieces[part], transform)
                packed, pts, vals, idxs = morph_targets.preserve_trajectories(surf, changed)
                if len(packed) != surf.count:
                    raise ValueError(f'{path.stem} mat_0{part} needed vertex splits ({len(packed)} != {surf.count})')
                # Build sparse morph delta arrays for all 15 channels
                channels = []
                for ch_i in range(len(MORPH_SPECS)):
                    d = vals[:, ch_i, :]
                    mag = np.linalg.norm(d, axis=1)
                    active = np.where(mag > 1e-4)[0]
                    entries = [(int(vi), float(d[vi, 0]), float(d[vi, 1]), float(d[vi, 2])) for vi in active]
                    channels.append(entries)
                face_matches[fp_key] = (head_remap, part, surf.count, pts3, channels)

    print(f'Collected {len(skeletons_by_head)} skeletons, {len(hair_matches)} hair fingerprints, {len(face_matches)} face surface entries, {len(extra_char_fps)} extra character surface fingerprints.')

    # 4. Serialize compact binary pack
    buf = bytearray()
    buf.extend(MAGIC)
    buf.extend(struct.pack('<IIIIIII',
        VERSION,
        len(skeletons_by_head),
        len(chains),
        len(colliders_arm),
        len(hair_matches),
        len(face_matches),
        len(MORPH_SPECS),
    ))

    # Section 1: Skeletons
    for hr in sorted(skeletons_by_head):
        sk = skeletons_by_head[hr]
        buf.extend(struct.pack('<B3x', hr))
        buf.extend(struct.pack('<5h2x', *sk['col_remaps']))
        buf.extend(sk['head_align'].astype('<f4').tobytes())
        for dr, dp in sk['drivers']:
            buf.extend(struct.pack('<h2x3f', dr, float(dp[0]), float(dp[1]), float(dp[2])))

    # Section 2: Hair Chains
    for ch in chains:
        n_bones = len(ch['bones'])
        buf.extend(struct.pack('<I4f', n_bones, ch['stiffness'], ch['damping'], ch['gravity'], ch['radius']))
        buf.extend(ch['nodes'].astype('<f4').tobytes())

    # Section 3: Colliders (in pl0020_ng bind space)
    for bslot, s_arm, e_arm, rad in colliders_arm:
        buf.extend(struct.pack('<I7f', bslot,
                               float(s_arm[0]), float(s_arm[1]), float(s_arm[2]),
                               float(e_arm[0]), float(e_arm[1]), float(e_arm[2]),
                               float(rad)))

    # Section 4: Hair Fingerprints + Shared 6349 Hair Skinning Weights
    for hr, vcnt, pts3 in hair_matches.values():
        buf.extend(struct.pack('<B3xI', hr, vcnt))
        buf.extend(pts3.tobytes())
    buf.extend(struct.pack('<I', len(hair_idx)))
    # Interleave 4x boneIdx + 4x weight = 8 bytes per vertex
    interleaved = np.hstack((hair_idx, hair_w))
    buf.extend(interleaved.tobytes())

    # Section 5: Face Surfaces + 15 Sparse Morph Channels each
    total_sparse = 0
    for hr, part, vcnt, pts3, channels in face_matches.values():
        buf.extend(struct.pack('<BB2xI', hr, part, vcnt))
        buf.extend(pts3.tobytes())
        for ch_entries in channels:
            total_sparse += len(ch_entries)
            buf.extend(struct.pack('<I', len(ch_entries)))
            for vi, dx, dy, dz in ch_entries:
                buf.extend(struct.pack('<H2x3f', vi, dx, dy, dz))

    # Section 6 (v2): Extra Character Surface Fingerprints (body, clothes, eyes, accessories — for character-wide shaders/emissive)
    buf.extend(struct.pack('<I', len(extra_char_fps)))
    for vcnt, pts3 in extra_char_fps.values():
        buf.extend(struct.pack('<I', vcnt))
        buf.extend(pts3.tobytes())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(buf))
    print(f'Wrote {out_path} ({len(buf):,} bytes, {total_sparse:,} sparse morph vertex deltas, {len(extra_char_fps)} extra char VBs)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overlay', type=Path, default=TEW_ROOT / 'haruka' / '_probe' / 'campaign-overlay-v5')
    parser.add_argument('--hair-json', type=Path, default=TEW_ROOT / 'release' / 'Haruka_柔软长发.tew1-hair.json')
    parser.add_argument('--pmx', type=Path, default=build.SOURCE)
    parser.add_argument('--out', type=Path, default=Path(r'F:\HG\evil\TEW1ModManager\runtime_src\haruka_runtime.bin'))
    args = parser.parse_args()
    compile_pack(args.overlay, args.hair_json, args.pmx, args.out)
