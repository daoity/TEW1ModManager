"""Restore full native mouth skeleton skinning on Haruka BMD6 models while keeping eyes/brows on head.
- Gameplay models (pl0000_ng, pl0020_ng, ...): lower lip, chin, and lower teeth/tongue -> jaw bone.
- CG cutscene models (pl0010_ng, pl0011_ng, pl0012_ng, pl0210_ng): full multi-bone native mouth rig
  (jaw + mouth_u_* + mouth_d_* + mouth_u_l/r_corner + lower teeth/tongue) so CG & dialogue lip-sync moves cleanly!
"""

from pathlib import Path
import sys
import numpy as np

TEW_ROOT = Path(r'F:\dspr_mod\tew_external_mount')
sys.path.insert(0, str(TEW_ROOT / 'haruka'))
sys.path.insert(0, str(TEW_ROOT))

import bmd6
import build
import campaign
import independent_face


class HarukaJawPatcher:
    def __init__(self, pmx_path=build.SOURCE, donor_bmd_bytes=None):
        self.pmx = build.load_pmx(pmx_path)
        if donor_bmd_bytes is None:
            donor_path = TEW_ROOT / 'haruka' / '_probe' / 'campaign-overlay-v5' / 'base' / campaign.asset_path('pl0020_ng')
            donor_bmd_bytes = donor_path.read_bytes()
        self.donor = bmd6.read_model(donor_bmd_bytes)

        assignments = []
        build.skin_weights(self.pmx, self.donor, assignments, False, False)
        neutral = build.coordinates(self.pmx, self.donor.skeleton.joints, 5.15, 0.24, assignments)

        by_name = {m.name: {e.index: e.offset for e in m.offsets} for m in self.pmx.morphs}
        jaw_open = by_name.get('あ', {})
        lower_lip = by_name.get('嘴巴-下', {})
        upper_lip = by_name.get('嘴巴-上', {})
        corner_w = by_name.get('嘴型-嘴角拉长', {})
        corner_u = by_name.get('嘴型-嘴角上移', {})
        corner_d = by_name.get('嘴型-嘴角下移', {})

        lower_teeth_set = set(range(independent_face.LOWER_MOUTH.start, independent_face.LOWER_MOUTH.stop))
        upper_teeth_set = set(range(independent_face.UPPER_MOUTH.start, independent_face.UPPER_MOUTH.stop))

        # Per-PMX-vertex semantic mouth channels (6 floats):
        # [0] jaw_w       : lower lip / chin / lower teeth & tongue
        # [1] upper_lip_w : upper lip lift
        # [2] corner_l_w  : left mouth corner (PMX x > 0 -> TEW +Y left)
        # [3] corner_r_w  : right mouth corner (PMX x < 0 -> TEW -Y right)
        # [4] pmx_x       : signed horizontal coordinate for left/mid/right lip distribution
        # [5] is_lower_teeth : 1.0 for lower teeth/tongue (strictly jaw, no lip-bone distortion)
        n_v = len(self.pmx.vertices)
        mouth_ch = np.zeros((n_v, 6), dtype=float)
        for i, v in enumerate(self.pmx.vertices):
            x, y, z = float(v.co[0]), float(v.co[1]), float(v.co[2])
            mouth_ch[i, 4] = x

            if i in upper_teeth_set:
                continue  # upper teeth stay 100% rigid on head
            if i in lower_teeth_set:
                mouth_ch[i, 0] = 0.85
                mouth_ch[i, 5] = 1.0
                continue

            if y >= 15.05:
                continue  # never touch nose / eyes / eyelids / eyebrows

            # Lower lip & chin
            dn = max(0.0, -lower_lip.get(i, (0, 0, 0))[1], -jaw_open.get(i, (0, 0, 0))[1])
            if dn > 0.018:
                mouth_ch[i, 0] = min(0.85, dn * 3.1)

            # Upper lip (only vertices moved cleanly upward by 嘴巴-上 and not predominantly lower lip)
            up = max(0.0, upper_lip.get(i, (0, 0, 0))[1])
            if up > 0.015 and y >= 14.66 and mouth_ch[i, 0] < 0.25:
                mouth_ch[i, 1] = min(0.65, up * 3.0)

            # Mouth corners (strong lateral or vertical corner motion at |x| > 0.13)
            c_mag = max(
                abs(corner_w.get(i, (0, 0, 0))[0]),
                abs(corner_u.get(i, (0, 0, 0))[1]),
                abs(corner_d.get(i, (0, 0, 0))[1]),
            )
            if c_mag > 0.016 and abs(x) > 0.13 and 14.55 <= y <= 14.96:
                cw = min(0.68, c_mag * 2.8)
                if x > 0.0:
                    mouth_ch[i, 2] = cw
                else:
                    mouth_ch[i, 3] = cw

        all_pts, all_norms, all_uv = neutral
        tris = np.asarray(self.pmx.faces)
        cursor = 0
        self.part_ref = {}
        for part, mat in enumerate(self.pmx.materials):
            cnt = mat.vertex_count // 3
            picked = tris[cursor:cursor + cnt]
            cursor += cnt
            if part not in (3, 5):
                continue
            verts, faces = np.unique(picked, return_inverse=True)
            faces = faces.reshape(-1, 3)
            pts, norms, uv, mch = all_pts[verts], all_norms[verts], all_uv[verts], mouth_ch[verts]
            if np.any((uv < 0.0) | (uv > 1.0)):
                (pts, norms, uv, mch, faces), _ = campaign.geometry.periodic_uv(
                    pts, norms, uv, mch, faces, lambda data, coeff: coeff @ data
                )
            self.part_ref[part] = (pts, uv, mch, faces)

    @staticmethod
    def _encode_weights(pairs, head_remap, force_head_primary=False):
        # Merge duplicate bone remaps
        merged = {}
        for r, w in pairs:
            if w > 0.002:
                merged[int(r)] = merged.get(int(r), 0.0) + float(w)
        if not merged:
            merged[head_remap] = 1.0
        # Ensure sum == 1.0 (remainder goes to head)
        non_head_sum = sum(v for k, v in merged.items() if k != head_remap)
        if non_head_sum > 0.92:
            scale = 0.92 / non_head_sum
            for k in list(merged.keys()):
                if k != head_remap:
                    merged[k] *= scale
            non_head_sum = 0.92
        merged[head_remap] = max(0.0, 1.0 - non_head_sum)

        order = sorted(merged.items(), key=lambda kv: -kv[1])[:4]
        if force_head_primary and order[0][0] != head_remap:
            # Keep head primary (for vertex[0] headRemap fingerprint stability)
            order = [(head_remap, 0.55)] + [(k, v) for k, v in order if k != head_remap][:3]
        tot = sum(v for _, v in order)
        norm = [(k, v / tot) for k, v in order]
        lead = norm[0][0]
        pads = [k for k, _ in norm] + [lead] * (4 - len(norm))
        sec = [v for _, v in norm[1:]] + [0.0] * (4 - len(norm))
        q1 = max(0, min(15, int(round(sec[0] * 30.0))))
        q2 = max(0, min(3, int(round(sec[1] * 9.0))))
        q3 = max(0, min(3, int(round(sec[2] * 12.0))))
        wcode = q1 * 16 + q2 * 4 + q3
        return wcode, pads[0], pads[1], pads[2], pads[3]

    def patch_bmd6_bytes(self, data: bytes, stem: str):
        model = bmd6.read_model(data)
        skel = model.skeleton
        if 'jaw' not in skel.names or 'head' not in skel.names:
            return data, 0

        bone_remap = {nm: int(r) for nm, r in zip(skel.names, skel.remap)}
        head_remap = bone_remap['head']
        jaw_remap = bone_remap['jaw']
        has_cg_mouth = all(
            b in bone_remap for b in ('mouth_u_center', 'mouth_d_center', 'mouth_u_l_corner', 'mouth_u_r_corner')
        )

        haruka_face_surfs = [
            s for s in model.surfaces
            if s.material in ('textures/tew_haruka/mat_03', 'textures/tew_haruka/mat_05')
        ]
        if not haruka_face_surfs:
            return data, 0

        transform = np.eye(4)
        if stem not in campaign.CORE:
            matrices, _ = campaign.transforms(self.donor.skeleton, skel)
            transform = matrices[self.donor.skeleton.names.index('head')]
        R = transform[:3, :3]
        T = transform[:3, 3]

        patched_verts_total = 0
        new_surfaces = []
        for surf in model.surfaces:
            if surf.material not in ('textures/tew_haruka/mat_03', 'textures/tew_haruka/mat_05'):
                new_surfaces.append(surf)
                continue

            part = int(surf.material[-2:])
            pts_src, uv_src, mch_src, faces_src = self.part_ref[part]
            if len(surf.indices) != len(faces_src):
                new_surfaces.append(surf)
                continue

            pts_xform = pts_src @ R.T + T
            src_ref = np.column_stack((pts_xform, uv_src))
            existing = np.ndarray((surf.count, 5), '>f4', buffer=surf.vertices, strides=(32, 4)).astype(float)
            gap = np.linalg.norm(
                existing[surf.indices][:, :, None, :] - src_ref[faces_src][:, None, :, :],
                axis=-1,
            )
            max_gap = float(np.max(np.min(gap, axis=-1)))
            if max_gap > 0.05:
                raise ValueError(f'{stem} mat_0{part} mouth match failed: max_gap={max_gap:.4f}')

            match = np.take_along_axis(faces_src, np.argmin(gap, axis=-1), axis=1)
            corner_mch = mch_src[match.reshape(-1)]

            v_sum = np.zeros((surf.count, 6), dtype=float)
            v_cnt = np.zeros(surf.count, dtype=float)
            np.add.at(v_sum, surf.indices.reshape(-1), corner_mch)
            np.add.at(v_cnt, surf.indices.reshape(-1), 1.0)
            v_mch = v_sum / np.maximum(v_cnt[:, None], 1.0)

            raw = np.frombuffer(surf.vertices, dtype='u1').reshape(-1, 32).copy()
            for vi in range(surf.count):
                jw, upw, clw, crw, px, is_lt = [float(x) for x in v_mch[vi]]
                if jw <= 0.005 and upw <= 0.005 and clw <= 0.005 and crw <= 0.005:
                    continue

                pairs = []
                if is_lt > 0.5:
                    pairs.append((jaw_remap, jw))
                elif has_cg_mouth:
                    # Full native CG mouth rig!
                    if jw > 0.005:
                        # Blend 55% jaw + 45% nearest lower-lip bone for organic CG speech
                        pairs.append((jaw_remap, jw * 0.55))
                        if px > 0.14 and 'mouth_d_l_middle' in bone_remap:
                            pairs.append((bone_remap['mouth_d_l_middle'], jw * 0.45))
                        elif px < -0.14 and 'mouth_d_r_middle' in bone_remap:
                            pairs.append((bone_remap['mouth_d_r_middle'], jw * 0.45))
                        else:
                            pairs.append((bone_remap['mouth_d_center'], jw * 0.45))
                    if upw > 0.005:
                        if px > 0.14 and 'mouth_u_l_middle' in bone_remap:
                            pairs.append((bone_remap['mouth_u_l_middle'], upw))
                        elif px < -0.14 and 'mouth_u_r_middle' in bone_remap:
                            pairs.append((bone_remap['mouth_u_r_middle'], upw))
                        else:
                            pairs.append((bone_remap['mouth_u_center'], upw))
                    if clw > 0.005:
                        pairs.append((bone_remap['mouth_u_l_corner'], clw * 0.65))
                        if 'mouth_d_l_coner' in bone_remap:
                            pairs.append((bone_remap['mouth_d_l_coner'], clw * 0.35))
                    if crw > 0.005:
                        pairs.append((bone_remap['mouth_u_r_corner'], crw * 0.65))
                        if 'mouth_d_r_coner' in bone_remap:
                            pairs.append((bone_remap['mouth_d_r_coner'], crw * 0.35))
                else:
                    # Gameplay rig (only jaw bone available)
                    if jw > 0.005:
                        pairs.append((jaw_remap, jw))
                    elif clw > 0.005 or crw > 0.005:
                        pairs.append((jaw_remap, max(clw, crw) * 0.35))

                if not pairs:
                    continue

                wcode, j0, j1, j2, j3 = self._encode_weights(pairs, head_remap, force_head_primary=(vi == 0))
                raw[vi, 23] = wcode
                raw[vi, 28] = j0
                raw[vi, 29] = j1
                raw[vi, 30] = j2
                raw[vi, 31] = j3
                patched_verts_total += 1

            assert int(raw[0, 28]) == head_remap, f'{stem} mat_0{part} vertex[0] lost head_remap!'
            new_surfaces.append(bmd6.Surface(surf.name, surf.material, raw.tobytes(), surf.indices, surf.flags, surf.trailer))

        if patched_verts_total == 0:
            return data, 0
        return bmd6.write_model(model, new_surfaces), patched_verts_total


if __name__ == '__main__':
    import zipfile
    patcher = HarukaJawPatcher()
    zpath = Path(r'F:\dspr_mod\tew_external_mount\release\Haruka_全章节外部挂载.zip')
    total_models = 0
    total_verts = 0
    with zipfile.ZipFile(zpath, 'r') as zf:
        for name in sorted(zf.namelist()):
            if name.lower().endswith('.bmd6model'):
                raw = zf.read(name)
                stem = Path(name).stem
                out, n = patcher.patch_bmd6_bytes(raw, stem)
                if n > 0:
                    total_models += 1
                    total_verts += n
                    print(f'  Patched {stem:25s}: {n} mouth verts mapped to native mouth bones (size {len(raw)} -> {len(out)})')
    print(f'Total patched: {total_models} models, {total_verts} mouth vertices.')
