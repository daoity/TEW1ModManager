"""Build Haruka's BMD6 meshes, material declarations and mipmapped textures."""

import argparse
from collections import defaultdict
from dataclasses import replace
import importlib.util
from io import BytesIO
import json
from pathlib import Path
from shutil import which
from struct import pack, pack_into
import subprocess
import sys

import numpy as np

PROJECT = Path(__file__).resolve().parent
if __package__:
    from . import bmd6, geometry
    from .make_demo import CHAPTER, MODELS, hide_model, stock_resource
else:
    sys.path[:0] = [str(PROJECT), str(PROJECT.parent)]
    import bmd6
    import geometry
    from make_demo import CHAPTER, MODELS, hide_model, stock_resource


GAME = Path(r'F:\HG\evil\TheEvilWithin\TheEvilWithin')
SOURCE = Path(r'F:\blender-4.4.3-windows-x64\blender_mod_model\haruka02_MMD\haruka02_MMD(角色）.pmx')
PMX_READER = PROJECT.parents[1] / 'addon-sources/blender_mmd_tools-4.5.14/mmd_tools/core/pmx/__init__.py'
ASSET_ROOT = 'generated/nextgen/characters/pl'
MATERIAL_ROOT = 'textures/tew_haruka'
BODY_SLOTS = {
    'pl0000_ng': ('m_shirt__nn', 'm_vest__nv', 'm_boots2__bt', 'm_holster__lt'),
    'pl0020_ng': ('m_pants', 'm_coat_button', 'm_boots1', 'm_hand_r'),
    'pl0006': ('m_vest', 'm_boots', 'm_hand_R', 'm_metal3'),
}
HEAD_SLOTS = {
    'pl0000_ng': ('m_beard', 'm_mouth3__mo', 'm_eye', 'm_face', 'm_eyelash_u_r', 'm_eye_occ'),
    'pl0020_ng': ('m_beard', 'm_mouth1', 'm_eye', 'm_mouth3', 'm_eyelash_u_l', 'm_eyeoc'),
    'pl0010_ng': ('m_beard1', 'm_mouth1', 'm_eye', 'm_face', 'm_eyelash_u_r', 'm_eyeoc'),
    'pl0011_ng': ('m_beard1', 'm_mouth1', 'm_eye', 'm_face', 'm_eyelash_u_r', 'm_eyeoc'),
}
AXES = np.array(((0, 1, 0), (0, 0, 1), (-1, 0, 0)))
BODY_BONES = {1: 'origin', 4: 'pelvis', 11: 'spine_00', 12: 'spine_01', 13: 'spine_02', 14: 'pelvis', 40: 'neck_00', 41: 'head'}


def load_pmx(source, reader=PMX_READER):
    spec = importlib.util.spec_from_file_location('tew_pmx_reader', reader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load(str(source))


def bone_mapping(pmx, names, custom_bone=False):
    mapping = BODY_BONES.copy()
    for side, arm, leg in (('l', 15, 259), ('r', 44, 265)):
        for delta, joint in ((0, 'shoulder'), (1, 'upperarm'), (2, 'upperarm'), (3, 'forearm'), (4, 'hand')):
            mapping[arm + delta] = f'{side}_{joint}'
        first = 20 if side == 'l' else 50
        for finger_index, finger in enumerate(('thumb', 'index', 'middle', 'ring', 'pinky')):
            for joint in range(4):
                segment = min(joint + int(finger != 'thumb'), 2 if finger == 'thumb' else 3)
                mapping[first + 4 * finger_index + joint] = f'{side}_{finger}_{segment:02}'
        for delta, joint in ((0, 'thigh'), (1, 'shin'), (2, 'shin'), (3, 'foot'), (4, 'toe')):
            mapping[leg + delta] = f'{side}_{joint}'
        mapping[256 if side == 'l' else 257] = f'{side}_toe'
    if custom_bone:
        mapping[193] = mapping[206] = 'haruka_hair_anchor'
    available = set(names)
    result = []
    for i in range(len(pmx.bones)):
        ancestor = i
        visited = set()
        while ancestor >= 0 and ancestor not in visited and mapping.get(ancestor) not in available:
            visited.add(ancestor)
            ancestor = pmx.bones[ancestor].parent
        result.append(mapping.get(ancestor, 'origin') if ancestor >= 0 else 'origin')
    return result


def influences(weight):
    if weight.type == 0:
        return [(weight.bones[0], 1.0)]
    if weight.type in (1, 3):
        first = weight.weights[0] if weight.type == 1 else weight.weights.weight
        return list(zip(weight.bones, (first, 1.0 - first)))
    return list(zip(weight.bones, weight.weights))


def skin_weights(pmx, model, normed, custom_bone, expressions=True):
    mapping = bone_mapping(pmx, model.skeleton.names, custom_bone)
    indices = {name: i for i, name in enumerate(model.skeleton.names)}
    codes = np.zeros((len(pmx.vertices), 5), 'u1')
    expression_names = {'まばたき', '嘴巴-下', 'あ', '上'} if expressions else set()
    expression = {morph.name: {entry.index: entry.offset for entry in morph.offsets}
                  for morph in pmx.morphs if morph.name in expression_names}
    blink = expression.get('まばたき', {})
    jaw_open = expression.get('あ', {})
    lower_lip = expression.get('嘴巴-下', {})
    brow_up = expression.get('上', {})
    for i, vertex in enumerate(pmx.vertices):
        merged = defaultdict(float)
        for joint, weight in influences(vertex.weight):
            if joint >= 0 and weight > 0.0:
                merged[mapping[joint]] += weight
        for side in ('l', 'r'):
            shin, foot = f'{side}_shin', f'{side}_foot'
            if foot in indices and merged.get(shin, 0) > 0 and vertex.co[1] < 2.2:
                # The source boot mesh is driven entirely by the calf. Add
                # ankle influences so it can follow the game's foot pivot.
                amount = np.clip((2.2 - vertex.co[1]) / 1.0, 0.0, 1.0)
                value = merged[shin] * amount ** 2 * (3.0 - 2.0 * amount)
                if value > 1e-8:
                    merged[shin] -= value
                    merged[foot] += value
        # The PMX blink displacement marks the vertices that can follow native eyelid bones.
        movement = blink.get(i)
        if movement is not None and merged.get('head', 0) > 0.3 and abs(movement[1]) > 0.02:
            side = 'l' if vertex.co[0] > 0.001 else 'r'
            lid = f'{side}_eyelid' + ('_down' if movement[1] > 0 else '')
            if lid in indices:
                contribution = min(0.48, 1.4 * abs(movement[1])) * merged['head']
                merged['head'] -= contribution
                merged[lid] += contribution
        if merged.get('head', 0) > 0.30:
            jaw = max(0.0, -lower_lip.get(i, (0, 0, 0))[1], -jaw_open.get(i, (0, 0, 0))[1])
            if 'jaw' in indices and jaw > 0.024 and vertex.co[1] < 15.2:
                amount = min(0.64, jaw * 2.5) * merged['head']
                merged['head'] -= amount
                merged['jaw'] += amount
            brow = abs(brow_up.get(i, (0, 0, 0))[1])
            if brow > 0.016:
                side = 'l' if vertex.co[0] > 0.0 else 'r'
                name = f'{side}_eyebrow_{int(abs(vertex.co[0]) > 0.42):02}'
                if name in indices:
                    amount = min(0.55, brow * 2.4) * merged['head']
                    merged['head'] -= amount
                    merged[name] += amount
        valid = ((name, value) for name, value in merged.items() if value > 1e-8)
        order = sorted(valid, key=lambda item: -item[1])[:4] or [('origin', 1.0)]
        total = sum(value for _, value in order)
        normalized = [(name, value / total) for name, value in order]
        normed.append(normalized)
        lead = indices[order[0][0]]
        pad = [model.skeleton.remap[indices[name]] for name, _ in normalized] + [model.skeleton.remap[lead]] * (4 - len(order))
        secondary = [value for _, value in normalized[1:]] + [0.0] * (4 - len(order))
        quantized = [round(value * factor) for value, factor in zip(secondary, (30, 9, 12))]
        codes[i] = (quantized[0] * 16 + quantized[1] * 4 + quantized[2], *pad)
    return codes, mapping


def normalize(values):
    lengths = np.linalg.norm(values, axis=-1, keepdims=True)
    return values / np.maximum(lengths, 1e-10)


def hand_frame(wrist, index, middle, pinky):
    direction = normalize(middle - wrist)
    across = index - pinky
    across = normalize(across - np.dot(across, direction) * direction)
    return np.column_stack((across, direction, np.cross(across, direction)))


def segment_fit(a, b, target_a, target_b, across_a, across_b):
    direction = normalize(b - a)
    target_direction = normalize(target_b - target_a)
    source_frame = hand_frame(a, a + across_a, b, a)
    target_frame = hand_frame(target_a, target_a + across_b, target_b, target_a)
    rotation = target_frame @ source_frame.T
    along = np.linalg.norm(target_b - target_a) / np.linalg.norm(b - a)
    transform = rotation + (along - 1.0) * np.outer(target_direction, direction)
    return transform, target_a - transform @ a, rotation


def coordinates(pmx, joints, scale, shoulder_fit, weights, preserve_foot_1to1=True):
    source = np.array([vertex.co for vertex in pmx.vertices])
    bone_points = np.array([bone.location for bone in pmx.bones]) @ AXES * scale
    z_shift = -float(source[:, 1].min()) * scale + 0.10
    # Align global X to thigh-midpoint X (prevents anterior-posterior hip/waist kink)
    src_hip_x = 0.5 * (bone_points[259][0] + bone_points[265][0])
    tgt_hip_x = 0.5 * (joints['l_thigh'][0] + joints['r_thigh'][0])
    offset = np.array([tgt_hip_x - src_hip_x, 0.0, z_shift])
    points = source @ AXES * scale + offset
    bone_points += offset
    transform = {}
    identity = (np.eye(3), np.zeros(3), np.eye(3))

    # C1-smooth shared-joint spine_02 -> spine_01 -> pelvis -> thigh chain
    hip_z_fit = 0.46
    src_sp2, src_sp1, src_pel = bone_points[13], bone_points[12], bone_points[4]
    src_hip_mid = 0.5 * (bone_points[259] + bone_points[265])
    tgt_hip_mid = 0.5 * (joints['l_thigh'] + joints['r_thigh'])
    new_hip_mid_z = src_hip_mid[2] + (tgt_hip_mid[2] - src_hip_mid[2]) * hip_z_fit
    new_pel = np.array([src_pel[0], src_pel[1], src_pel[2] + (new_hip_mid_z - src_hip_mid[2]) * 0.55])
    new_sp1 = np.array([src_sp1[0], src_sp1[1], src_sp1[2] + (new_hip_mid_z - src_hip_mid[2]) * 0.25])
    spine_across = np.array([0.0, 1.0, 0.0])
    if np.linalg.norm(src_sp1 - src_sp2) > 1e-4:
        transform['spine_01'] = segment_fit(src_sp2, src_sp1, src_sp2, new_sp1, spine_across, spine_across)
    if np.linalg.norm(src_hip_mid - src_sp1) > 1e-4:
        new_hip_mid = np.array([tgt_hip_mid[0], src_hip_mid[1], new_hip_mid_z])
        transform['pelvis'] = segment_fit(src_sp1, src_hip_mid, new_sp1, new_hip_mid, spine_across, spine_across)

    for side, slots, first_finger in (('l', (15, 16, 18, 19), 20), ('r', (44, 45, 47, 48), 50)):
        wrist = f'{side}_hand'
        target_wrist = joints[wrist]
        source_wrist = bone_points[slots[3]]
        palm = ('index_01', 'middle_01', 'pinky_01')
        source_frame = hand_frame(source_wrist, *bone_points[[first_finger + i for i in (4, 8, 16)]])
        target_frame = hand_frame(target_wrist, *(joints[f'{side}_{joint}'] for joint in palm))
        rotation = target_frame @ source_frame.T
        translation = target_wrist - rotation @ source_wrist
        transform[wrist] = (rotation, translation, rotation)
        shoulder, arm, elbow = bone_points[list(slots[:3])]
        # Preserve original slender shoulder width when shoulder_fit == 0.0 (anti-"double-door")
        t_sh = joints[f'{side}_shoulder']
        t_arm = joints[f'{side}_upperarm']
        t_elb = joints[f'{side}_forearm']
        new_shoulder = np.array([
            shoulder[0] + (t_sh[0] - shoulder[0]) * shoulder_fit * 0.5,
            shoulder[1] + (t_sh[1] - shoulder[1]) * shoulder_fit * 0.5,
            shoulder[2] + (t_sh[2] - shoulder[2]) * max(0.10, shoulder_fit * 0.5),
        ])
        new_arm = np.array([
            arm[0] + (t_arm[0] - arm[0]) * shoulder_fit,
            arm[1] + (t_arm[1] - arm[1]) * shoulder_fit,
            arm[2] + (t_arm[2] - arm[2]) * max(0.20, shoulder_fit),
        ])
        new_elbow = np.array([
            elbow[0] + (t_elb[0] - elbow[0]) * (0.50 if shoulder_fit <= 0.01 else 0.74),
            elbow[1] + (t_elb[1] - elbow[1]) * (0.35 if shoulder_fit <= 0.01 else 0.74),
            elbow[2] + (t_elb[2] - elbow[2]) * (0.50 if shoulder_fit <= 0.01 else 0.74),
        ])
        # All adjacent sections share the same fitted joint center. The forearm
        # turns toward the wrist frame so the hand can rotate without a seam.
        transform[f'{side}_shoulder'] = (identity[0], new_shoulder - shoulder, identity[2])
        upper_across = np.array([1.0, 0.0, 0.0])
        transform[f'{side}_upperarm'] = segment_fit(arm, elbow, new_arm, new_elbow, upper_across, upper_across)
        source_roll = normalize(0.35 * upper_across + 0.65 * source_frame[:, 0])
        target_roll = normalize(0.35 * upper_across + 0.65 * target_frame[:, 0])
        transform[f'{side}_forearm'] = segment_fit(elbow, source_wrist, new_elbow, target_wrist, source_roll, target_roll)
        for finger_index, finger in enumerate(('thumb', 'index', 'middle', 'ring', 'pinky')):
            source_offset = first_finger + 4 * finger_index
            segments = [f'{side}_{finger}_{digit + int(finger != "thumb"):02}' for digit in range(3)]
            finger_points = bone_points[source_offset:source_offset + 4]
            fitted = [rotation @ point + translation for point in finger_points]
            for digit, name in enumerate(segments):
                if name in joints:
                    fitted[digit] += (joints[name] - fitted[digit]) * 0.85
            fitted[-1] = fitted[-2] + rotation @ (finger_points[-1] - finger_points[-2])
            for digit in range(3):
                transform[segments[digit]] = segment_fit(
                    *finger_points[digit:digit + 2], *fitted[digit:digit + 2], source_frame[:, 0], target_frame[:, 0]
                )
    for side, first in (('l', 259), ('r', 265)):
        thigh, knee, ankle = bone_points[[first, first + 1, first + 3]]
        toe = bone_points[256 if side == 'l' else 257]
        target_thigh = joints[f'{side}_thigh']
        target_knee = joints[f'{side}_shin']
        target_ankle = joints[f'{side}_foot']
        target_toe = joints[f'{side}_toe']
        across = np.array([0.0, 1.0, 0.0])
        # Share pelvis bottom Z smoothly with thigh top
        new_thigh = np.array([target_thigh[0], thigh[1] + (target_thigh[1] - thigh[1]) * 0.45, new_hip_mid_z])
        new_knee = np.array([target_knee[0], knee[1] + (target_knee[1] - knee[1]) * 0.50, target_knee[2]])
        if preserve_foot_1to1:
            # 100% original 1:1 bare-foot proportions (no 1.45x length / 1.60x boot-height stretch!)
            new_ankle = np.array([target_ankle[0], ankle[1] + (target_ankle[1] - ankle[1]) * 0.50, ankle[2]])
            transform[f'{side}_thigh'] = segment_fit(thigh, knee, new_thigh, new_knee, across, across)
            transform[f'{side}_shin'] = segment_fit(knee, ankle, new_knee, new_ankle, across, across)
            transform[f'{side}_foot'] = (np.eye(3), new_ankle - ankle, np.eye(3))
            transform[f'{side}_toe'] = (np.eye(3), new_ankle - ankle, np.eye(3))
        else:
            transform[f'{side}_thigh'] = segment_fit(thigh, knee, target_thigh, target_knee, across, across)
            transform[f'{side}_shin'] = segment_fit(knee, ankle, target_knee, target_ankle, across, across)
            foot_length = (target_toe[0] - target_ankle[0]) / (toe[0] - ankle[0])
            shoe_height = (target_ankle[2] - 0.10) / (ankle[2] - 0.10)
            foot = np.diag((foot_length, 1.0, shoe_height))
            transform[f'{side}_foot'] = (foot, target_ankle - foot @ ankle, np.linalg.inv(foot).T)
    normals = np.array([vertex.normal for vertex in pmx.vertices]) @ AXES
    for index, assignments in enumerate(weights):
        if all(name not in transform for name, _ in assignments):
            continue
        point, normal = points[index].copy(), normals[index].copy()
        points[index] = 0
        normals[index] = 0
        for name, fraction in assignments:
            linear, translation, rotation = transform.get(name, identity)
            points[index] += fraction * (linear @ point + translation)
            normals[index] += fraction * (rotation @ normal)
    uv = np.array([vertex.uv for vertex in pmx.vertices])
    return points, normalize(normals), uv


def packed_basis(unit):
    return np.rint(np.clip(unit, -1.0, 1.0) * 127.5 + 127.5).astype('u1')


def apply_continuous_tangents(stream):
    """Use the projection tested on the skirt, independent of mirrored UV U."""
    normals = normalize(stream[:, 20:23].astype(float) - 127.5)
    previous = normalize(stream[:, 24:27].astype(float) - 127.5)
    old_sign = np.where(stream[:, 27] == 255, 1.0, -1.0)
    old_bitangent = np.cross(normals, previous) * old_sign[:, None]

    tangent = np.cross((0.0, 0.0, 1.0), normals)
    pole = np.linalg.norm(tangent, axis=1) <= 0.2
    tangent[pole] = np.cross((1.0, 0.0, 0.0), normals[pole])
    tangent = normalize(tangent)
    sign = (np.cross(normals, tangent) * old_bitangent).sum(axis=1) >= 0

    # Coincident vertices with the same encoded normal use the same frame
    # even when the UV islands selected opposite directions for the old B.
    _, groups = np.unique(stream[:, [*range(12), 20, 21, 22]], axis=0, return_inverse=True)
    positive = np.bincount(groups, weights=sign)
    count = np.bincount(groups)
    sign = positive[groups] * 2 >= count[groups]
    stream[:, 24:27] = packed_basis(tangent)
    stream[:, 27] = sign * 255


def interpolate_wire(rows, coefficient):
    combined = defaultdict(float)
    for row, mixture in zip(rows, coefficient):
        code = int(row[0])
        b = (code >> 4) / 30.0
        c = ((code >> 2) & 3) / 9.0
        d = (code & 3) / 12.0
        for joint, weight in zip(row[1:], (1.0 - b - c - d, b, c, d)):
            if weight > 0:
                combined[int(joint)] += mixture * weight
    weights = sorted(combined.items(), key=lambda value: -value[1])[:4]
    total = sum(weight for _, weight in weights)
    lead = weights[0][0]
    digits = [round(weight / total * factor) for (_, weight), factor in zip(weights[1:], (30.0, 9.0, 12.0))]
    digits += [0] * (3 - len(digits))
    return (digits[0] * 16 + digits[1] * 4 + digits[2], *(joint for joint, _ in weights), *[lead] * (4 - len(weights)))


def mesh_stream(points, normals, uv, triangles, weights, rebuild_normals=False, continuous_tangents=False):
    if np.any((uv < 0) | (uv > 1)):
        (points, normals, uv, weights, triangles), crossed = geometry.periodic_uv(
            points, normals, uv, weights, triangles, interpolate_wire
        )
        normals = normalize(normals)
    else:
        crossed = 0
    coord = points[triangles]
    edge1, edge2 = coord[:, 1] - coord[:, 0], coord[:, 2] - coord[:, 0]
    winding = (np.cross(edge1, edge2) * normals[triangles].mean(axis=1)).sum(axis=1)
    triangles = triangles.copy()
    triangles[winding > 0] = triangles[winding > 0][:, [0, 2, 1]]
    if rebuild_normals:
        corner_normals = geometry.rebuild_corner_normals(points, normals, triangles, weights)
        corner_keys = np.column_stack((triangles.ravel(), corner_normals))
        vertices, triangles = np.unique(corner_keys, axis=0, return_inverse=True)
        source = vertices[:, 0].astype(np.intp)
        points, uv, weights = points[source], uv[source], weights[source]
        normals = vertices[:, 1:]
        triangles = triangles.reshape(-1, 3)
    tangent, sign = geometry.mikk_corner_frames(points, normals, uv, triangles)
    corners = triangles.ravel()
    normal_bytes = packed_basis(normals)
    # Reproject against the normals the game will actually decode.
    decoded = normalize(normal_bytes[corners].astype(float) - 127.5)
    du, dv = geometry.uv_directions(points.astype('f4').astype(float), uv.astype('f4').astype(float), triangles)
    tangent = tangent - (tangent * decoded).sum(axis=1, keepdims=True) * decoded
    projected_u = normalize(du - (du * decoded).sum(axis=1, keepdims=True) * decoded)
    reversed_tangent = (normalize(tangent) * projected_u).sum(axis=1) < -0.02
    tangent[reversed_tangent] = projected_u[reversed_tangent]
    missing = ~np.isfinite(tangent).all(axis=1) | (np.linalg.norm(tangent, axis=1) < 1e-8)
    if np.any(missing):
        fallback_normal = decoded[missing]
        axis = np.eye(3)[np.argmin(np.abs(fallback_normal), axis=1)]
        tangent[missing] = np.cross(axis, fallback_normal)
        sign[missing] = 1
    tangent_bytes = packed_basis(normalize(tangent))
    wire_tangent = normalize(tangent_bytes.astype(float) - 127.5)
    alignment = (np.cross(decoded, wire_tangent) * normalize(dv)).sum(axis=1)
    # Recheck the direction after rounding; keep Mikk's sign when a UV
    # derivative is degenerate or too close to perpendicular to call.
    sign = np.where(np.abs(alignment) > 0.006, alignment, sign)
    # Only share a wire vertex if its original vertex and entire packed frame
    # match. Mirrored seams retain separate vertices, including their weights.
    frame = np.column_stack((corners, tangent_bytes, (sign >= 0) * 255))
    unique, triangles = np.unique(frame, axis=0, return_inverse=True)
    expanded = unique[:, 0]
    points, uv, weights = points[expanded], uv[expanded], weights[expanded]
    triangles = triangles.reshape(-1, 3)
    stream = np.zeros((len(points), 32), 'u1')
    stream[:, :20] = np.column_stack((points, uv)).astype('>f4').view('u1')
    stream[:, 20:23] = normal_bytes[expanded]
    stream[:, 23] = weights[:, 0]
    # Retail TEW uses 255 for a positive bitangent and 0 for a negative one.
    stream[:, 24:28] = unique[:, 1:]
    stream[:, 28:] = weights[:, 1:]
    if continuous_tangents:
        apply_continuous_tangents(stream)
    return stream.tobytes(), triangles, crossed


def hidden(surface):
    if surface.name == 'm_hair' or '__clt' in surface.name:
        # Retain the vertex array size needed by existing attachment data.
        return replace(surface, indices=np.zeros_like(surface.indices))
    return replace(surface, vertices=surface.vertices[:32] * 3, indices=np.zeros((1, 3), 'u2'))


def relative_asset(name):
    stem = name.split("_", 1)[0]
    kind = "em" if stem.startswith("em") else "pl"
    return f'generated/nextgen/characters/{kind}/{stem}/model/{name}.bmd6model'


def put(root, relative, data):
    path = root / 'base' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def bimage(image, template, alpha=False):
    from PIL import Image

    fmt = 'DXT5' if alpha else 'DXT1'
    header = bytearray(template[:46])
    header[:4] = b'\x54\x5c\x0f\x36'
    pack_into('>II', header, 16, *image.size)
    header[36] = 11 if alpha else 10
    parts = []
    for level in range(16):
        with BytesIO() as out:
            image.save(out, format='DDS', pixel_format=fmt)
            dds = out.getvalue()
        block = dds[128:]
        expected = ((image.width + 3) // 4) * ((image.height + 3) // 4) * (16 if alpha else 8)
        if dds[84:88] != fmt.encode('ascii') or len(block) != expected:
            raise ValueError('DDS encoder output does not match the selected BC format.')
        parts.append(pack('>5I', level, 0, *image.size, len(block)) + block)
        if min(image.size) <= 4:
            break
        image = image.resize(tuple(max(4, axis // 2) for axis in image.size), Image.Resampling.LANCZOS)
    pack_into('>I', header, 28, len(parts))
    return bytes(header) + b''.join(parts)


def material(index, has_alpha, texture=None, clip_threshold=None):
    if texture is None:
        texture = f'{MATERIAL_ROOT}/base_{index:02}'
    flat = 'textures/character_global_ng/n_flat'
    if clip_threshold is None:
        # index 9 (SHEER_OUTER) uses low clipthreshold 0.05 so semi-transparent fabrics survive alpha-test
        clip_threshold = '0.05' if (not has_alpha or index == 9) else '0.33'
    # TEW's deferred character program pulls from virtual texture pages. This
    # native forward program requests ordinary BImages and supports skinned meshes.
    values = {
        'depthfillprogram': 'occluderhairtrans', 'shadowprogram': 'occludershadowblendhair',
        'stageprogram': 'lppalbedoalphaforwardanisotropic',
        'velocityprogram': 'velocityhair', 'depthfillonlyprogram': 'occluderhairdepthonlyblend',
        'transmap': texture, 'sparebumpmap': flat, 'sparespecularmap': 'textures/character_global_ng/white',
        'clipthreshold': str(clip_threshold), 'newspecularscale': '0.065' if index == 1 else '0.05',
        'powergloss': '22.0', 'specularfresnel': '0.09', 'fresnel_reflection': '0.065',
        'fresnel_reflection_curve': '0.4', 'envmapstrength': '1.16',
        'envmapambientstrength': '1.06',
        'envmapcharacterambientstrength': '0.68', 'envmapspecularstrength': '0.025',
        'diffuserimlighting': '1.0', 'rimlightingmidpoint': '0.015',
        'usepowerfrommaterialmap': '0.0', 'overrideenvscale': '0.0',
    }
    values.update(flowmap='_green', flowmapaniso='0.0', haircolor='0.50',
                  anisocolor0='{ 0.08, 0.08, 0.08, 0.0 }', anisocolor1='{ 0.05, 0.05, 0.05, 0.0 }',
                  hairparms='{ 0.0, 0.2, 3.0, 5.0 }', twosided='1.0', lodbiasscale='1.0',
                  materialtype='1.0', materialid='491.0')
    # Keep the native forward stage's reflection inputs stable; tune its
    # ambient/diffuse gain and sharpness per source material.
    gain = {0: '1.32', 1: '1.5', 2: '1.42', 5: '1.48', 8: '1.32', 9: '1.5'}.get(index, '1.55')
    values.update(envmapdiffusestrength=gain)
    return ('{\n' + ''.join(f'{key}\t{value}\n' for key, value in values.items()) + '}\n').encode('ascii')


def build(args):
    from PIL import Image

    pmx = load_pmx(args.source, args.reader)
    archive = args.game / 'base' / CHAPTER
    output = args.overlay.resolve()
    if output.is_relative_to(args.game.resolve()) or args.game.resolve().is_relative_to(output):
        raise ValueError('The output must be outside the game installation.')
    template = stock_resource(archive, relative_asset('pl0020_ng'))
    reference = bmd6.read_model(template)
    joints = reference.skeleton.joints
    packed_indices = np.array(pmx.faces, dtype='i4')
    report = {'source': str(args.source), 'base_scale': args.scale, 'shoulder_fit': args.shoulder_fit, 'runtime_models': {}, 'materials': []}

    use_alpha = []
    image_template = read_texture_template(archive)
    for index, m in enumerate(pmx.materials):
        source = Path(pmx.textures[m.texture].path)
        with Image.open(source) as source_image:
            image = source_image.convert('RGBA')
        # Base-body alpha also contains empty atlas padding. Leave that surface opaque.
        alpha = index in (6, 7, 9) and image.getchannel('A').getextrema()[0] < 255
        if not alpha:
            image.putalpha(255)
        image.thumbnail((args.texture_size, args.texture_size), Image.Resampling.LANCZOS)
        if index in (0, 1, 5, 8):
            pixels = np.array(image)
            rgb = pixels[:, :, :3].astype('f4')
            gain = 0.96 - 0.15 * np.square(np.max(rgb, axis=-1, keepdims=True) / 255.0)
            pixels[:, :, :3] = np.rint(rgb * gain).astype('u1')
            image = Image.fromarray(pixels)
        use_alpha.append(alpha)
        put(output, f'generated/textures/{MATERIAL_ROOT}/base_{index:02}.bimage', bimage(image, image_template, alpha))
        put(output, f'generated/decls/material/{MATERIAL_ROOT}/mat_{index:02}.decl', material(index, alpha))
        report['materials'].append({'name': m.name, 'source': source.name, 'dimensions': image.size, 'alpha': alpha})
    for name, (section_count, _) in MODELS.items():
        path = relative_asset(name)
        stock = stock_resource(archive, path)
        if name not in BODY_SLOTS and name not in HEAD_SLOTS:
            data, _ = hide_model(stock, section_count)
            put(output, path, data)
            continue
        model = bmd6.read_model(stock)
        enable_bone = args.custom_bone and name == 'pl0020_ng'
        if enable_bone:
            hair_anchor = (np.array(pmx.bones[193].location) @ AXES + np.array(pmx.bones[206].location) @ AXES) * args.scale / 2
            hair_anchor[2] += -min(v.co[1] for v in pmx.vertices) * args.scale + 0.10
            model = bmd6.append_test_bone(model, 'haruka_hair_anchor', 'head', hair_anchor)
        weights = []
        wire, mapping = skin_weights(pmx, model, weights, enable_bone, args.expressions)
        pos, normals, uv = coordinates(pmx, joints, args.scale, args.shoulder_fit, weights)
        selected = dict(zip((0, 1, 8, 9), BODY_SLOTS.get(name, ())))
        selected.update(zip((2, 3, 4, 5, 6, 7), HEAD_SLOTS.get(name, ())))
        native = {surface.name: surface for surface in model.surfaces}
        replacements = {}
        wrapped = {}
        cursor = 0
        for index, m in enumerate(pmx.materials):
            count = m.vertex_count // 3
            faces = packed_indices[cursor:cursor + count]
            cursor += count
            slot = selected.get(index)
            if slot is None:
                continue
            vertices, remapped = np.unique(faces.reshape(-1), return_inverse=True)
            remapped = remapped.reshape(-1, 3)
            stream, remapped, wrapped[slot] = mesh_stream(
                pos[vertices], normals[vertices], uv[vertices], remapped, wire[vertices],
                rebuild_normals=args.rebuild_hair_normals and index == 2,
                continuous_tangents=args.continuous_tangents,
            )
            original = native[slot]
            trailer = bytearray(original.trailer)
            pack_into('>H', trailer, 4, len(model.skeleton.names))
            replacements[slot] = bmd6.Surface(slot, f'{MATERIAL_ROOT}/mat_{index:02}', stream, remapped, original.flags, bytes(trailer))
        if cursor != len(packed_indices):
            raise ValueError('The PMX material table does not cover the complete mesh.')
        surfaces = [replacements[surface.name] if surface.name in replacements else
                    surface if surface.name == 'm_leg_rope_rp' else hidden(surface) for surface in model.surfaces]
        data = bmd6.write_model(model, surfaces)
        check = bmd6.read_model(data)
        assert len(check.surfaces) == len(surfaces) and len(check.skeleton.names) == len(model.skeleton.names)
        for expected, actual in zip(surfaces, check.surfaces):
            assert expected.name == actual.name and expected.vertices == actual.vertices and np.array_equal(expected.indices, actual.indices)
        put(output, path, data)
        report['runtime_models'][name] = {'bytes': len(data), 'sections': len(surfaces), 'bones': len(check.skeleton.names),
                                          'vertices': sum(surface.count for surface in replacements.values()),
                                          'triangles': sum(len(surface.indices) for surface in replacements.values()),
                                          'bounds': [pos.min(axis=0).tolist(), pos.max(axis=0).tolist()],
                                          'native_mesh_slots': list(replacements), 'uv_seam_triangles': wrapped}
        if name == 'pl0020_ng':
            report['bone_map'] = {f'{i}:{bone.name}': native for i, (bone, native) in enumerate(zip(pmx.bones, mapping))}

    report['source_morphs'] = len(pmx.morphs)
    report['native_expression_weight_bridge'] = ['blink', 'jaw', 'brow'] if args.expressions else []
    if args.rebuild_hair_normals:
        report['hair_normals'] = 'connected_surface'
    if args.continuous_tangents:
        report['tangents'] = 'continuous_surface_projection'
    output.joinpath('build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report['runtime_models'], indent=2))


def read_texture_template(archive):
    import struct
    import zlib
    target = b'generated/textures/lights/squarelight1.bimage'
    with archive.open('rb') as f:
        if f.read(4) != bytes.fromhex('23 94 AB CD'):
            raise ValueError('Invalid Tango archive signature.')
        for _ in range(struct.unpack('>I', f.read(4))[0]):
            for _ in range(2):
                f.seek(struct.unpack('<I', f.read(4))[0], 1)
            f.seek(4, 1)
        f.seek(struct.unpack('>I', f.read(4))[0])
        count, _, _, a, b = struct.unpack('>5I', f.read(20))
        f.seek(2 * (a + b), 1)
        length, _ = struct.unpack('>2I', f.read(8))
        name = f.read(length).split(b'\0').index(target)
        for key, offset, packed, raw in struct.iter_unpack('>4I', f.read(16 * count)):
            if key == name:
                f.seek(offset)
                data = f.read(packed)
                if packed != raw:
                    decode = zlib.decompressobj(-15)
                    data = decode.decompress(data) + decode.flush()
                if len(data) != raw or data[4:8] != b'\x09MIB':
                    raise ValueError('Could not decode the stock BImage header.')
                return data
    raise ValueError('Missing BImage template.')


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, default=GAME)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--reader', type=Path, default=PMX_READER)
    parser.add_argument('--overlay', type=Path, default=PROJECT / 'Haruka-overlay')
    parser.add_argument('--scale', type=float, default=5.15)
    parser.add_argument('--shoulder-fit', type=float, default=0.0,
                        help='0.0 preserves original slender shoulder width (anti-"double-door")')
    parser.add_argument('--texture-size', type=int, choices=(512, 1024, 2048), default=1024)
    parser.add_argument('--custom-bone', action='store_true')
    parser.add_argument('--expressions', action='store_true')
    parser.add_argument('--rebuild-hair-normals', action='store_true',
                        help='rebuild the hair normals on connected smooth surfaces before exporting tangents')
    parser.add_argument('--continuous-tangents', action='store_true',
                        help='use the continuous tangent projection for every Haruka surface')
    build(parser.parse_args(argv))


if __name__ == '__main__':
    if importlib.util.find_spec('bpy') is None:
        bundled = PROJECT.parents[1] / 'tools' / 'blender-5.2.2-windows-x64' / 'blender.exe'
        blender = str(bundled) if bundled.is_file() else which('blender')
        if blender is None:
            raise SystemExit('Blender 5.2 is needed for BMD6 tangent calculation.')
        args = [blender, '-b', '--factory-startup', '--python-exit-code', '1', '--python', str(Path(__file__).resolve())]
        raise SystemExit(subprocess.call(args + ['--', *sys.argv[1:]]))
    main(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:])
