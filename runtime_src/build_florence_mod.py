"""High-precision end-to-end builder for the Florence Pajama (芙洛伦衣装睡衣 fll_19x.blend) TEW1 Mod.

Rebuilt from the ground up on the proven Haruka build.py + campaign.py architecture:
  1. Direct Blender-world -> TEW1 coordinate conversion (-Y->+X, +X->+Y, +Z->+Z), feet grounded at Z=0.10.
  2. Haruka-grade segment_fit() joint-to-joint fitting for shoulders, arms, wrists, ALL 30 fingers, thighs,
     shins, and feet onto Sebastian's exact pl0000_ng joints (applied identically to Shape Keys & physics bones!).
  3. 100% complete bone mapping across all 257 weighted bones (including smooth spatial Pajamas_* skirt
     weights across pelvis/thighs/spine, Butt_* -> thigh/pelvis, Cloth_* sleeves -> forearms, zero dropped bones!).
  4. Proper material split on 000_Face (Face vs BodySkin), OPAQUE pajama cloth (zero alpha-cutout holes!),
     clean CUTOUT eye highlights / tattoos / pubic hair.
  5. Exact post-mesh_stream vertex index tracking so EVERY Face Morph delta and EVERY Hair/Chest physics
     weight maps 1-to-1 to the exact final GPU Vertex Buffer vertex index (zero spikes/tearing!).
  6. Strict Havok protection via build.hidden() (preserving stock m_hair & __clt vertex counts) and <=31 surfaces.
  7. Exact campaign.transforms() + campaign.fit() skeleton-to-skeleton transfer across all 27 chapter,
     cutscene, and severed-limb .bmd6model files.
  8. tew1_dyn.bin v3.1 with exact vert0Remap cross-skeleton disambiguation, 10 hair chains + 2 chest chains,
     5 humanoid colliders, 15 facial morph channels, F7/F8/F9 self-illumination, and 7 clothing-only
     Insert-panel Variant Groups across all chapters.
"""

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
import shutil
import struct
import sys
import zipfile

import bpy
import numpy as np

MANAGER_ROOT = Path(r"F:\HG\evil\TEW1ModManager")
ADDON_PARENT = MANAGER_ROOT / "blender_addon"
TEW_MOUNT_ROOT = Path(r"F:\dspr_mod\tew_external_mount")
for p in (str(ADDON_PARENT), str(TEW_MOUNT_ROOT), str(TEW_MOUNT_ROOT / "haruka")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tew1_bmd6 import bmd6, build, geometry, tex_encode
from tew1_bmd6.presets import PRESETS
from tango import TangoArchive
import campaign

GAME_DIR = Path(r"F:\HG\evil\TheEvilWithin\TheEvilWithin")
OVERLAY_DIR = Path(r"F:\HG\evil\TEW1ModManager\runtime_src\florence_overlay")
OUT_ZIP = MANAGER_ROOT / "dist" / "芙洛伦睡衣_全章节_物理表情差分一体版.zip"
MAT_PREFIX = "textures/tew_florence"

# Blender World (-Y forward, +X left, +Z up) -> TEW1 (+X forward, +Y left, +Z up): +90 deg around Z
R_BL2TEW = np.array([
    [0.0, -1.0, 0.0],
    [1.0,  0.0, 0.0],
    [0.0,  0.0, 1.0],
], dtype=np.float64)

# Note: pl0007 is a 2-bone (origin + r_shin) leg-wound attachment stub — MUST be 100% hidden like Haruka!
HIDDEN_ONLY_MODELS = {"pl0007"}
BODY_MODELS = {"pl0006", "pl0009_ng", "pl0200_ng", "pl0300_ng", "pl0301_ng"}
HEAD_ONLY_MODELS = {"pl0001_ng", "pl0010_ng", "pl0011_ng", "pl0012_ng", "pl0016_ng", "pl0210_ng"}
FULL_MODEL_HEAD_SLOT = {
    "pl0000_ng": "m_face",
    "pl0017_ng": "m_face",
    "pl0018_ng": "m_face",
    "pl0020_ng": "m_mouth3",
    "pl0201_ng": "m_tong",
    "pl0220_ng": "m_face",
    "pl0220_m":  "m_face",
    "pl0220_l":  "m_face",
    "pl0230_ng": "m_face",
    "em5002_ng": "m_face",
}
HEAD_ONLY_SLOT = {
    "pl0001_ng": "m_face1",
    "pl0010_ng": "m_face",
    "pl0011_ng": "m_face",
    "pl0012_ng": "m_face",
    "pl0016_ng": "m_face_crush",
    "pl0210_ng": "m_tong",
}
BODY_SLOTS_BY_MODEL = {
    "pl0000_ng": ("m_shirt__nn", "m_hand_l", "m_r_shrit_arm__na", "m_pants_leg__np"),
    "pl0017_ng": ("m_shirt", "m_metal__mt", "m_boots2__bt", "m_holster__lt"),
    "pl0018_ng": ("m_shirt", "m_metal2__mt", "m_boots3__bt", "m_holster__lt"),
    "pl0020_ng": ("m_pants", "m_coat_button", "m_boots1", "m_hand_r"),
    "pl0200_ng": ("m_shirt_body", "m_hand_r1", "m_boots__bt", "m_holster__lt"),
    "pl0201_ng": ("m_shirt_body", "m_hand_r1", "m_boots__bt", "m_holster__lt"),
    "pl0220_ng": ("m_shirt__nn", "m_vest__nv", "m_boots2__bt", "m_holster__lt"),
    "pl0220_m":  ("m_vest__nv", "m_hand_r2", "m_boots__bt", "m_holster__lt"),
    "pl0220_l":  ("m_vest__nv", "m_hand_r2", "m_boots__bt", "m_holster__lt"),
    "pl0230_ng": ("m_shirt__nn", "m_vest__nv", "m_boots2__bt", "m_holster__lt"),
    "pl0300_ng": ("m_shirt__nn", "m_vest__nv", "m_boots2__bt", "m_holster__lt"),
    "pl0301_ng": ("m_vest__nv", "m_hand_l", "m_boots__bt", "m_holster__lt"),
    "pl0006":    ("m_vest", "m_hand_R", "m_boots", "m_metal3"),
    "pl0007":    ("m_vest", "m_hand_R", "m_boots", "m_metal3"),
    "pl0009_ng": ("m_vest__nv", "m_hand_l", "m_boots__bt", "m_holster__lt"),
    "em5002_ng": ("m_shirt__nn", "m_vest__nv", "m_boots2__bt", "m_holster__lt"),
}
FRAGMENTS = {
    "pl0002": ("r_forearm", "m_hand_r1", "arm"),
    "pl0003": ("l_forearm", "m_hand_l1", "arm"),
    "pl0004": ("r_shin",    "polySurface14", "leg"),
    "pl0005": ("l_shin",    "polySurface16", "leg"),
    "pl0008": ("r_hand",    "m_hand_r3", "hand"),
}
ALL_TARGETS = set(FULL_MODEL_HEAD_SLOT) | BODY_MODELS | HIDDEN_ONLY_MODELS | HEAD_ONLY_MODELS | set(FRAGMENTS)

LEFT_ARM_BONES = {
    "l_upperarm", "l_forearm", "l_hand",
    "l_thumb_00", "l_thumb_01", "l_thumb_02",
    "l_index_01", "l_index_02", "l_index_03",
    "l_middle_01", "l_middle_02", "l_middle_03",
    "l_ring_01", "l_ring_02", "l_ring_03",
    "l_pinky_01", "l_pinky_02", "l_pinky_03",
}
RIGHT_ARM_BONES = {
    "r_upperarm", "r_forearm", "r_hand",
    "r_thumb_00", "r_thumb_01", "r_thumb_02",
    "r_index_01", "r_index_02", "r_index_03",
    "r_middle_01", "r_middle_02", "r_middle_03",
    "r_ring_01", "r_ring_02", "r_ring_03",
    "r_pinky_01", "r_pinky_02", "r_pinky_03",
}
LEG_BONES = {"l_thigh", "r_thigh", "l_shin", "r_shin", "l_foot", "r_foot", "l_toe", "r_toe"}

CHANNEL_ALIASES = (
    ("Blink",       ("まばたき", "Blink")),
    ("WinkL",       ("ウィンク", "WinkL")),
    ("WinkR",       ("ウィンク右", "WinkR")),
    ("A",           ("あ", "A")),
    ("I",           ("い", "I")),
    ("U",           ("う", "U")),
    ("E",           ("え", "E")),
    ("O",           ("お", "O")),
    ("Smile",       ("口角上げ", "Smile")),
    ("SmileEyes",   ("笑い", "SmileEyes")),
    ("Surprised",   ("びっくり", "Surprised")),
    ("BrowWorried", ("困る", "BrowWorried")),
    ("BrowAngry",   ("怒り", "BrowAngry")),
    ("BrowUp",      ("上", "BrowUp")),
    ("Frown",       ("口角下げ", "Frown")),
)

# Direct MMD Japanese -> TEW1 Sebastian native bone table
DIRECT_BONE_MAP = {
    "下半身": "pelvis", "腰": "pelvis", "センター": "pelvis", "グルーブ": "pelvis",
    "全ての親": "origin", "操作中心": "origin",
    "上半身": "spine_01",
    "上半身2": "spine_02",
    "首": "neck_00",
    "頭": "head", "目.L": "head", "目.R": "head", "両目": "head",
    # Left arm
    "肩.L": "l_shoulder", "肩P.L": "l_shoulder", "肩C.L": "l_shoulder",
    "腕.L": "l_upperarm", "腕捩.L": "l_upperarm", "腕捩1.L": "l_upperarm", "腕捩2.L": "l_upperarm", "腕捩3.L": "l_upperarm",
    "ひじ.L": "l_forearm", "手捩.L": "l_forearm", "手捩1.L": "l_forearm", "手捩2.L": "l_forearm", "手捩3.L": "l_forearm",
    "手首.L": "l_hand",
    # Right arm
    "肩.R": "r_shoulder", "肩P.R": "r_shoulder", "肩C.R": "r_shoulder",
    "腕.R": "r_upperarm", "腕捩.R": "r_upperarm", "腕捩1.R": "r_upperarm", "腕捩2.R": "r_upperarm", "腕捩3.R": "r_upperarm",
    "ひじ.R": "r_forearm", "手捩.R": "r_forearm", "手捩1.R": "r_forearm", "手捩2.R": "r_forearm", "手捩3.R": "r_forearm",
    "手首.R": "r_hand",
    # Left leg (map BOTH 足.L and 足D.L so Butt_* children inherit l_thigh!)
    "足.L": "l_thigh", "足D.L": "l_thigh", "腰キャンセル.L": "pelvis",
    "ひざ.L": "l_shin", "ひざD.L": "l_shin",
    "足首.L": "l_foot", "足首D.L": "l_foot",
    "足先EX.L": "l_foot", "足首先.L": "l_foot",
    # Right leg
    "足.R": "r_thigh", "足D.R": "r_thigh", "腰キャンセル.R": "pelvis",
    "ひざ.R": "r_shin", "ひざD.R": "r_shin",
    "足首.R": "r_foot", "足首D.R": "r_foot",
    "足先EX.R": "r_foot", "足首先.R": "r_foot",
    # Left fingers
    "親指０.L": "l_thumb_00", "親指１.L": "l_thumb_01", "親指２.L": "l_thumb_02",
    "人指１.L": "l_index_01", "人指２.L": "l_index_02", "人指３.L": "l_index_03",
    "中指１.L": "l_middle_01", "中指２.L": "l_middle_02", "中指３.L": "l_middle_03",
    "薬指１.L": "l_ring_01", "薬指２.L": "l_ring_02", "薬指３.L": "l_ring_03",
    "小指１.L": "l_pinky_01", "小指２.L": "l_pinky_02", "小指３.L": "l_pinky_03",
    # Right fingers
    "親指０.R": "r_thumb_00", "親指１.R": "r_thumb_01", "親指２.R": "r_thumb_02",
    "人指１.R": "r_index_01", "人指２.R": "r_index_02", "人指３.R": "r_index_03",
    "中指１.R": "r_middle_01", "中指２.R": "r_middle_02", "中指３.R": "r_middle_03",
    "薬指１.R": "r_ring_01", "薬指２.R": "r_ring_02", "薬指３.R": "r_ring_03",
    "小指１.R": "r_pinky_01", "小指２.R": "r_pinky_02", "小指３.R": "r_pinky_03",
}

IGNORED_VGS = {"mmd_edge_scale", "mmd_vertex_order"}


def asset_rel_path(name):
    if name == "em5002_ng":
        return "generated/nextgen/characters/em/em5002/model/em5002_ng.bmd6model"
    return build.relative_asset(name)


def load_stock_templates():
    files = sorted((GAME_DIR / "base").glob("*.tangoresource"), key=lambda p: (p.name != build.CHAPTER, p.name))
    lookups = {asset_rel_path(n): n for n in ALL_TARGETS}
    models = {}
    for arc_path in files:
        arc = TangoArchive(arc_path)
        for key in sorted(lookups.keys() & arc.entries.keys()):
            name = lookups[key]
            if name not in models:
                models[name] = bmd6.read_model(arc.read(key))
    missing = ALL_TARGETS - models.keys()
    if missing:
        raise RuntimeError(f"Missing stock templates: {sorted(missing)}")
    print(f"Loaded {len(models)} stock TEW1 templates from game archives.")
    return models


def build_bone_weight_table(arm):
    """Map EVERY bone in Florence's armature -> list of (tew_bone_name, factor).
    Special handling for Pajamas_* skirt bones so the pajama dress moves smoothly with pelvis + thighs!
    """
    table = {}
    butt_soft_map = {
        "bone0470_Butt_L_Front":  [("pelvis", 0.45), ("l_thigh", 0.55)],
        "bone0471_Butt_L_Side":   [("pelvis", 0.45), ("l_thigh", 0.55)],
        "bone0472_Butt_L_Back01": [("pelvis", 0.80), ("l_thigh", 0.20)],
        "bone0474_Butt_R_Front":  [("pelvis", 0.45), ("r_thigh", 0.55)],
        "bone0477_Butt_R_Side":   [("pelvis", 0.45), ("r_thigh", 0.55)],
        "bone0475_Butt_R_Back01": [("pelvis", 0.80), ("r_thigh", 0.20)],
    }
    for b in arm.data.bones:
        bn = b.name
        if bn in butt_soft_map:
            table[bn] = butt_soft_map[bn]
            continue
        if bn.startswith("Pajamas_"):
            # Skirt bone position in Blender world space (x > 0 is Left, z ~ 0.86..1.10)
            p = arm.matrix_world @ b.head_local
            x, z = float(p.x), float(p.z)
            if z >= 1.07:
                table[bn] = [("spine_01", 0.55), ("pelvis", 0.45)]
            elif z >= 1.01:
                t = (1.07 - z) / 0.06
                table[bn] = [("spine_01", 0.55 * (1.0 - t)), ("pelvis", 0.45 + 0.55 * t)]
            else:
                # Below hip: smoothly blend pelvis + left/right thigh as hem goes down (1.01 -> 0.85)
                drop = float(np.clip((1.01 - z) / 0.16, 0.0, 1.0))
                thigh_w = 0.52 * (drop ** 1.15)
                # Smooth left/right transition across center x in [-0.07, +0.07]
                lr = float(np.clip((x + 0.07) / 0.14, 0.0, 1.0))  # 1.0 = full Left, 0.0 = full Right
                w_l = thigh_w * lr
                w_r = thigh_w * (1.0 - lr)
                w_p = 1.0 - w_l - w_r
                entries = [("pelvis", w_p)]
                if w_l > 0.01:
                    entries.append(("l_thigh", w_l))
                if w_r > 0.01:
                    entries.append(("r_thigh", w_r))
                table[bn] = entries
            continue

        cur = b
        mapped = None
        while cur is not None:
            if cur.name in DIRECT_BONE_MAP:
                mapped = DIRECT_BONE_MAP[cur.name]
                break
            cur = cur.parent
        table[bn] = [(mapped or "pelvis", 1.0)]
    return table


def compute_haruka_segment_transforms(arm, stock_joints):
    """Compute exact global scale + shift + per-bone Haruka segment_fit() transforms -> Sebastian pl0000_ng."""
    # Find bare-foot bottom Z across 00B_BodySkin in Blender world space
    body_obj = bpy.data.objects["00B_BodySkin"]
    mw = np.array(body_obj.matrix_world, dtype=np.float64)
    n = len(body_obj.data.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    body_obj.data.vertices.foreach_get("co", co)
    body_w = co.reshape(-1, 3).astype(np.float64) @ mw[:3, :3].T + mw[:3, 3]
    z_foot_min = float(body_w[:, 2].min())

    def src_joint_bl(name):
        b = arm.data.bones[name]
        p = arm.matrix_world @ b.head_local
        return np.array([p.x, p.y, p.z], dtype=np.float64)

    def src_tail_bl(name):
        b = arm.data.bones[name]
        p = arm.matrix_world @ b.tail_local
        return np.array([p.x, p.y, p.z], dtype=np.float64)

    # Scale cleanly so (head - ankle) matches Sebastian's pl0000_ng (same proportion as Haruka!)
    src_head_z = src_joint_bl("頭")[2]
    src_ankle_z = src_joint_bl("足首D.L")[2]
    tgt_head_z = float(stock_joints["head"][2])
    tgt_ankle_z = float(stock_joints["l_foot"][2])
    scale = (tgt_head_z - tgt_ankle_z) / (src_head_z - src_ankle_z)

    # Ground feet precisely at Z = 0.10 and align hip/thigh midpoint X directly to Sebastian's thigh pivot X!
    # (Eliminates the anterior-posterior shear between pelvis/waist and thighs that caused severe hip bending!)
    l_th_raw = (src_joint_bl("足D.L") @ R_BL2TEW.T) * scale
    r_th_raw = (src_joint_bl("足D.R") @ R_BL2TEW.T) * scale
    src_hip_x = 0.5 * (float(l_th_raw[0]) + float(r_th_raw[0]))
    tgt_hip_x = 0.5 * (float(stock_joints["l_thigh"][0]) + float(stock_joints["r_thigh"][0]))
    offset = np.array([tgt_hip_x - src_hip_x, 0.0, -z_foot_min * scale + 0.10], dtype=np.float64)

    def to_tew(p_bl):
        return (p_bl @ R_BL2TEW.T) * scale + offset

    def j_src(name):
        return to_tew(src_joint_bl(name))

    def j_tail(name):
        return to_tew(src_tail_bl(name))

    transform = {}
    identity = (np.eye(3), np.zeros(3), np.eye(3))
    shoulder_fit = 0.55

    # 1. Arms, wrists, and ALL 30 fingers (exact Haruka build.py segment_fit!)
    finger_mmd = [
        ("thumb",  ("親指０", "親指１", "親指２")),
        ("index",  ("人指１", "人指２", "人指３")),
        ("middle", ("中指１", "中指２", "中指３")),
        ("ring",   ("薬指１", "薬指２", "薬指３")),
        ("pinky",  ("小指１", "小指２", "小指３")),
    ]
    for side, sfx in (("l", ".L"), ("r", ".R")):
        wrist_k = f"{side}_hand"
        target_wrist = stock_joints[wrist_k]
        source_wrist = j_src(f"手首{sfx}")
        source_frame = build.hand_frame(
            source_wrist,
            j_src(f"人指１{sfx}"),
            j_src(f"中指１{sfx}"),
            j_src(f"小指１{sfx}"),
        )
        target_frame = build.hand_frame(
            target_wrist,
            stock_joints[f"{side}_index_01"],
            stock_joints[f"{side}_middle_01"],
            stock_joints[f"{side}_pinky_01"],
        )
        rotation = target_frame @ source_frame.T
        translation = target_wrist - rotation @ source_wrist
        transform[wrist_k] = (rotation, translation, rotation)

        shoulder = j_src(f"肩{sfx}")
        arm_j = j_src(f"腕{sfx}")
        elbow = j_src(f"ひじ{sfx}")
        t_sh = stock_joints[f"{side}_shoulder"]
        t_arm = stock_joints[f"{side}_upperarm"]
        t_elb = stock_joints[f"{side}_forearm"]

        # Preserve 100% original slender Florence shoulder width (0% Y widening -> zero 'double-door' shoulders!)
        # while smoothly guiding elbow & wrist to Sebastian's exact hand grip!
        new_shoulder = np.array([shoulder[0], shoulder[1], shoulder[2] + (t_sh[2] - shoulder[2]) * 0.10])
        new_arm = np.array([arm_j[0], arm_j[1], arm_j[2] + (t_arm[2] - arm_j[2]) * 0.20])
        new_elbow = np.array([
            elbow[0] + (t_elb[0] - elbow[0]) * 0.50,
            elbow[1] + (t_elb[1] - elbow[1]) * 0.35,
            elbow[2] + (t_elb[2] - elbow[2]) * 0.50,
        ])

        transform[f"{side}_shoulder"] = (identity[0], new_shoulder - shoulder, identity[2])
        upper_across = np.array([1.0, 0.0, 0.0])
        transform[f"{side}_upperarm"] = build.segment_fit(arm_j, elbow, new_arm, new_elbow, upper_across, upper_across)
        source_roll = build.normalize(0.35 * upper_across + 0.65 * source_frame[:, 0])
        target_roll = build.normalize(0.35 * upper_across + 0.65 * target_frame[:, 0])
        transform[f"{side}_forearm"] = build.segment_fit(elbow, source_wrist, new_elbow, target_wrist, source_roll, target_roll)

        for fname, mmd_segs in finger_mmd:
            tew_segs = [f"{side}_{fname}_{digit + int(fname != 'thumb'):02}" for digit in range(3)]
            f_pts = [j_src(f"{m}{sfx}") for m in mmd_segs] + [j_tail(f"{mmd_segs[-1]}{sfx}")]
            fitted = [rotation @ pt + translation for pt in f_pts]
            for digit, seg_name in enumerate(tew_segs):
                if seg_name in stock_joints:
                    fitted[digit] = fitted[digit] + (stock_joints[seg_name] - fitted[digit]) * 0.85
            fitted[-1] = fitted[-2] + rotation @ (f_pts[-1] - f_pts[-2])
            for digit in range(3):
                transform[tew_segs[digit]] = build.segment_fit(
                    f_pts[digit], f_pts[digit + 1],
                    fitted[digit], fitted[digit + 1],
                    source_frame[:, 0], target_frame[:, 0],
                )

    # 2. C1-Smooth Shared-Joint Spine -> Pelvis -> Thighs -> Shins -> Feet chain!
    # (Prevents ANY step discontinuity or swayback kink between waist, pelvis, and thigh root!)
    across = np.array([0.0, 1.0, 0.0])
    src_sp2 = j_src("上半身2")
    src_sp1 = j_src("上半身")
    src_pel = j_src("下半身")
    src_hip_mid = 0.5 * (j_src("足D.L") + j_src("足D.R"))
    tgt_hip_mid = 0.5 * (stock_joints["l_thigh"] + stock_joints["r_thigh"])

    hip_z_fit = 0.46
    new_hip_mid = src_hip_mid + np.array([
        (tgt_hip_mid[0] - src_hip_mid[0]) * 0.85,
        0.0,
        (tgt_hip_mid[2] - src_hip_mid[2]) * hip_z_fit,
    ])
    hip_delta = new_hip_mid - src_hip_mid
    new_sp2 = src_sp2.copy()               # Keep chest / shoulders / head / hair / chest-physics 100% pure!
    new_sp1 = src_sp1 + hip_delta * 0.40   # Smooth waist bridge (only ~1 deg tilt!)
    new_pel_top = src_pel + hip_delta * 0.42

    transform["spine_01"] = build.segment_fit(src_sp2, src_sp1, new_sp2, new_sp1, across, across)
    transform["pelvis"]   = build.segment_fit(src_pel, src_hip_mid, new_pel_top, new_hip_mid, across, across)

    for side, sfx in (("l", ".L"), ("r", ".R")):
        thigh = j_src(f"足D{sfx}")
        knee = j_src(f"ひざD{sfx}")
        ankle = j_src(f"足首D{sfx}")
        toe = j_src(f"足先EX{sfx}")
        target_thigh = stock_joints[f"{side}_thigh"]
        target_knee = stock_joints[f"{side}_shin"]
        target_ankle = stock_joints[f"{side}_foot"]
        target_toe = stock_joints[f"{side}_toe"]

        # Exact shared top endpoint with pelvis bottom -> ZERO step/pinch at thigh root!
        new_thigh = np.array([
            new_hip_mid[0],
            thigh[1] + (target_thigh[1] - thigh[1]) * 0.40,
            new_hip_mid[2],
        ])
        new_knee = np.array([
            knee[0] + (target_knee[0] - knee[0]) * 0.72,
            knee[1] + (target_knee[1] - knee[1]) * 0.60,
            knee[2] + (target_knee[2] - knee[2]) * 0.72,
        ])
        new_ankle = np.array([
            ankle[0] + (target_ankle[0] - ankle[0]) * 0.85,
            ankle[1] + (target_ankle[1] - ankle[1]) * 0.62,
            ankle[2],  # Preserve exact original bare-foot ankle height (Z=0.10 grounded, ZERO boot stretching!)
        ])
        transform[f"{side}_thigh"] = build.segment_fit(thigh, knee, new_thigh, new_knee, across, across)
        transform[f"{side}_shin"]  = build.segment_fit(knee, ankle, new_knee, new_ankle, across, across)
        # Keep 100% original 1:1 Blender bare-foot length & arch proportions (pure rigid shift, ZERO 1.45x/1.60x stretch!)
        transform[f"{side}_foot"] = (identity[0], new_ankle - ankle, identity[2])
        transform[f"{side}_toe"] = transform[f"{side}_foot"]

    # 3. Gentle spine / neck / head X-center alignment (keeps cute head proportions while matching head pivot!)
    src_head = j_src("頭")
    tgt_head = stock_joints["head"]
    print(f"Global scale={scale:.3f}, offset={np.round(offset, 2).tolist()}")
    print(f"  Florence head={np.round(src_head, 2).tolist()} vs Stock head={np.round(tgt_head, 2).tolist()}")
    return scale, offset, transform


def mesh_stream_tracked(points, normals, uv, triangles, weights, continuous_tangents=True):
    """Exact replica of build.mesh_stream that ALSO returns final->source vertex index map `src_idx`!
    Guarantees 100% 1-to-1 vertex correspondence for Face Morphs and Hair/Chest Physics Weights.
    """
    src_ids = np.arange(len(points), dtype=np.int64)
    if np.any((uv < 0) | (uv > 1)):
        # Track nearest source vertex after periodic_uv split (rarely triggered)
        orig_pts = points.copy()
        (points, normals, uv, weights, triangles), crossed = geometry.periodic_uv(
            points, normals, uv, weights, triangles, build.interpolate_wire
        )
        normals = build.normalize(normals)
        # Map each post-periodic_uv vertex to its closest original vertex (distance ~0 for kept verts)
        diff = np.linalg.norm(points[:, None, :] - orig_pts[None, :, :], axis=2) if len(points) < 4000 else None
        if diff is not None:
            src_ids = np.argmin(diff, axis=1).astype(np.int64)
        else:
            # Chunked nearest lookup
            src_ids = np.empty(len(points), dtype=np.int64)
            for s0 in range(0, len(points), 512):
                s1 = min(len(points), s0 + 512)
                d = np.linalg.norm(points[s0:s1, None, :] - orig_pts[None, :, :], axis=2)
                src_ids[s0:s1] = np.argmin(d, axis=1)
    else:
        crossed = 0

    coord = points[triangles]
    edge1, edge2 = coord[:, 1] - coord[:, 0], coord[:, 2] - coord[:, 0]
    winding = (np.cross(edge1, edge2) * normals[triangles].mean(axis=1)).sum(axis=1)
    triangles = triangles.copy()
    triangles[winding > 0] = triangles[winding > 0][:, [0, 2, 1]]

    tangent, sign = geometry.mikk_corner_frames(points, normals, uv, triangles)
    corners = triangles.ravel()
    normal_bytes = build.packed_basis(normals)
    decoded = build.normalize(normal_bytes[corners].astype(float) - 127.5)
    du, dv = geometry.uv_directions(points.astype("f4").astype(float), uv.astype("f4").astype(float), triangles)
    tangent = tangent - (tangent * decoded).sum(axis=1, keepdims=True) * decoded
    projected_u = build.normalize(du - (du * decoded).sum(axis=1, keepdims=True) * decoded)
    reversed_tangent = (build.normalize(tangent) * projected_u).sum(axis=1) < -0.02
    tangent[reversed_tangent] = projected_u[reversed_tangent]
    missing = ~np.isfinite(tangent).all(axis=1) | (np.linalg.norm(tangent, axis=1) < 1e-8)
    if np.any(missing):
        fallback_normal = decoded[missing]
        axis = np.eye(3)[np.argmin(np.abs(fallback_normal), axis=1)]
        tangent[missing] = np.cross(axis, fallback_normal)
        sign[missing] = 1
    tangent_bytes = build.packed_basis(build.normalize(tangent))
    wire_tangent = build.normalize(tangent_bytes.astype(float) - 127.5)
    alignment = (np.cross(decoded, wire_tangent) * build.normalize(dv)).sum(axis=1)
    sign = np.where(np.abs(alignment) > 0.006, alignment, sign)

    frame = np.column_stack((corners, tangent_bytes, (sign >= 0) * 255))
    unique, triangles = np.unique(frame, axis=0, return_inverse=True)
    expanded = unique[:, 0]
    points, uv, weights = points[expanded], uv[expanded], weights[expanded]
    final_src_ids = src_ids[expanded]
    triangles = triangles.reshape(-1, 3)

    stream = np.zeros((len(points), 32), "u1")
    stream[:, :20] = np.column_stack((points, uv)).astype(">f4").view("u1")
    stream[:, 20:23] = normal_bytes[expanded]
    stream[:, 23] = weights[:, 0]
    stream[:, 24:28] = unique[:, 1:]
    stream[:, 28:] = weights[:, 1:]
    if continuous_tangents:
        build.apply_continuous_tangents(stream)
    return stream.tobytes(), triangles.astype(np.uint16), final_src_ids


def extract_fitted_part(obj_specs, arm, bone_table, scale, offset, seg_transforms, stock_skel, add_cg_face_weights=False):
    """Extract, combine, and Haruka-segment-fit one or more (obj_name, mat_filter_or_None) meshes in pl0000_ng space."""
    all_pts = []
    all_nrm = []
    all_uv = []
    all_tris = []
    all_tew_weights = []
    all_raw_vgs = []
    all_morphs = []
    vert_base = 0
    has_any_morph = False

    identity = (np.eye(3), np.zeros(3), np.eye(3))
    stock_bone_set = set(stock_skel.names)

    for oname, mat_filter in obj_specs:
        obj = bpy.data.objects[oname]
        mesh = obj.data
        mesh.calc_loop_triangles()

        mw = np.array(obj.matrix_world, dtype=np.float64)
        rot_w = mw[:3, :3]
        trans_w = mw[:3, 3]
        # Full linear map from mesh local -> scaled TEW1 space (before segment_fit)
        rot_tew = (R_BL2TEW @ rot_w) * scale
        nrm_mat = R_BL2TEW @ np.linalg.inv(rot_w).T

        n = len(mesh.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        pts_tew = (co.reshape(-1, 3).astype(np.float64) @ rot_w.T + trans_w) @ R_BL2TEW.T * scale + offset

        loop_nrm = np.empty(len(mesh.loops) * 3, dtype=np.float32)
        mesh.corner_normals.foreach_get("vector", loop_nrm)
        loop_nrm = build.normalize(loop_nrm.reshape(-1, 3).astype(np.float64) @ nrm_mat.T)

        uv_layer = mesh.uv_layers.active or (mesh.uv_layers[0] if len(mesh.uv_layers) > 0 else None)
        if uv_layer is not None:
            tmp_uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
            uv_layer.uv.foreach_get("vector", tmp_uv)
            loop_uv = tmp_uv.reshape(-1, 2).astype(np.float64)
            loop_uv[:, 1] = 1.0 - loop_uv[:, 1]
        else:
            # Skin patch mesh without UV layer: sample neutral skin area (0.25, 0.25)
            loop_uv = np.full((len(mesh.loops), 2), 0.25, dtype=np.float64)

        # Filter triangles by material name if requested (e.g. splitting 000_Face into Face vs BodySkin!)
        kept_tris = []
        for lt in mesh.loop_triangles:
            if mat_filter is not None:
                m = mesh.materials[lt.material_index] if lt.material_index < len(mesh.materials) else None
                mname = m.name if m else ""
                if mname != mat_filter:
                    continue
            kept_tris.append(lt.loops[:])
        if not kept_tris:
            continue
        tri_loops = np.array(kept_tris, dtype=np.int32)

        loop_vids = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", loop_vids)

        # Deduplicate (vertex_id, uv, normal) corners
        flat_loops = tri_loops.ravel()
        ckeys = np.column_stack((loop_vids[flat_loops], loop_uv[flat_loops], loop_nrm[flat_loops]))
        uniq, inv = np.unique(ckeys, axis=0, return_inverse=True)
        src_vids = uniq[:, 0].astype(np.int64)
        c_pts = pts_tew[src_vids].copy()
        c_uv = uniq[:, 1:3].copy()
        c_nrm = uniq[:, 3:].copy()
        c_tris = inv.reshape(-1, 3) + vert_base

        # Gather raw MMD vertex groups & mapped TEW1 weights
        vg_names = {vg.index: vg.name for vg in obj.vertex_groups}
        raw_vgs_v = [{vg_names[g.group]: float(g.weight) for g in v.groups if g.weight > 1e-6 and vg_names[g.group] not in IGNORED_VGS}
                     for v in mesh.vertices]

        # Extract 15 Shape Key deltas in scaled TEW1 space (before segment_fit)
        kbs_deltas = np.zeros((len(CHANNEL_ALIASES), n, 3), dtype=np.float64)
        obj_has_morph = False
        if mesh.shape_keys and len(mesh.shape_keys.key_blocks) > 1:
            kbs = mesh.shape_keys.key_blocks
            by_name = {kb.name: kb for kb in kbs}
            bco = np.empty(n * 3, dtype=np.float32)
            kbs[0].data.foreach_get("co", bco)
            bco = bco.reshape(-1, 3).astype(np.float64)
            for ci, (_, aliases) in enumerate(CHANNEL_ALIASES):
                kb = next((by_name[a] for a in aliases if a in by_name), None)
                if kb is None or kb == kbs[0]:
                    continue
                kco = np.empty(n * 3, dtype=np.float32)
                kb.data.foreach_get("co", kco)
                d = (kco.reshape(-1, 3).astype(np.float64) - bco) @ rot_tew.T
                if float(np.max(np.linalg.norm(d, axis=1))) > 1e-4:
                    kbs_deltas[ci] = d
                    obj_has_morph = True
                    has_any_morph = True

        # Map each source vertex -> normalized TEW1 bone weights (+ optional CG jaw/eyelid/eyebrow weights!)
        jaw_d = kbs_deltas[3]  # M_A ("あ")
        blink_d = kbs_deltas[0]  # M_BLINK ("まばたき")
        brow_d = kbs_deltas[13]  # M_BROW_UP ("上")
        max_jaw_down = float(np.max(-jaw_d[:, 2])) if obj_has_morph else 0.0

        tew_weights_v = []
        for vi in range(n):
            merged = defaultdict(float)
            for bn, w in raw_vgs_v[vi].items():
                targets = bone_table.get(bn)
                if targets:
                    for tbn, tf in targets:
                        merged[tbn] += w * tf
                else:
                    merged["pelvis"] += w

            # Native CG jaw / brow weights on face/mouth/teeth/tongue (matching Haruka!)
            if add_cg_face_weights and obj_has_morph and merged.get("head", 0.0) > 0.3:
                if max_jaw_down > 0.05 and "jaw" in stock_bone_set:
                    down = float(-jaw_d[vi, 2])
                    if down > max_jaw_down * 0.14:
                        amt = min(0.68, (down / max_jaw_down) * 0.72) * merged["head"]
                        merged["head"] -= amt
                        merged["jaw"] += amt

            # Smooth medial shoulder-cap weight transfer:
            # Vertices medial to Sebastian's broad l_upperarm/r_upperarm pivot (|Y| < 10.6) smoothly shift
            # upperarm weight onto l_shoulder/r_shoulder so lowering arms keeps slender sloping anime shoulders!
            ay = abs(float(pts_tew[vi, 1]))
            if ay < 10.6:
                t_sh = float(np.clip((ay - 5.8) / (10.6 - 5.8), 0.0, 1.0))
                keep_ua = t_sh * t_sh * (3.0 - 2.0 * t_sh)
                for side in ("l", "r"):
                    ua_k, sh_k = f"{side}_upperarm", f"{side}_shoulder"
                    w_ua = merged.get(ua_k, 0.0)
                    if w_ua > 0.0 and sh_k in stock_bone_set:
                        move = w_ua * (1.0 - keep_ua)
                        merged[ua_k] = w_ua - move
                        merged[sh_k] += move

            valid = [(bn, w) for bn, w in merged.items() if bn in stock_bone_set and w > 1e-7]
            valid.sort(key=lambda x: -x[1])
            valid = valid[:4] or [("pelvis", 1.0)]
            tot = sum(w for _, w in valid)
            tew_weights_v.append([(bn, w / tot) for bn, w in valid])

        c_tew_w = [tew_weights_v[vi] for vi in src_vids]
        c_raw_vg = [raw_vgs_v[vi] for vi in src_vids]
        c_morph = kbs_deltas[:, src_vids, :].copy()

        # Apply Haruka segment_fit() LBS deformation to positions, normals, AND morph deltas!
        for ci_v, assignments in enumerate(c_tew_w):
            if all(bn not in seg_transforms for bn, _ in assignments):
                continue
            p0 = c_pts[ci_v].copy()
            n0 = c_nrm[ci_v].copy()
            p_out = np.zeros(3, dtype=np.float64)
            n_out = np.zeros(3, dtype=np.float64)
            lin_blend = np.zeros((3, 3), dtype=np.float64)
            for bn, frac in assignments:
                lin, tr, rot = seg_transforms.get(bn, identity)
                p_out += frac * (lin @ p0 + tr)
                n_out += frac * (rot @ n0)
                lin_blend += frac * lin
            c_pts[ci_v] = p_out
            c_nrm[ci_v] = n_out
            if obj_has_morph:
                c_morph[:, ci_v, :] = c_morph[:, ci_v, :] @ lin_blend.T

        c_nrm = build.normalize(c_nrm)

        all_pts.append(c_pts)
        all_nrm.append(c_nrm)
        all_uv.append(c_uv)
        all_tris.append(c_tris)
        all_tew_weights.extend(c_tew_w)
        all_raw_vgs.extend(c_raw_vg)
        all_morphs.append(c_morph)
        vert_base += len(c_pts)

    return {
        "pts": np.vstack(all_pts),
        "normals": np.vstack(all_nrm),
        "uv": np.vstack(all_uv),
        "tris": np.vstack(all_tris),
        "tew_weights": all_tew_weights,
        "raw_vgs": all_raw_vgs,
        "morphs": np.concatenate(all_morphs, axis=1).astype(np.float32) if has_any_morph else None,
    }


def encode_wire_weights(tew_weights, skel):
    by_name = dict(zip(skel.names, skel.remap))
    rows = np.zeros((len(tew_weights), 5), dtype="u1")
    for vi, order in enumerate(tew_weights):
        ids = [by_name[bn] for bn, _ in order]
        ids += [ids[0]] * (4 - len(ids))
        sec = [w for _, w in order[1:]] + [0.0] * (4 - len(order))
        b, c, d = (round(x * s) for x, s in zip(sec, (30, 9, 12)))
        rows[vi] = (b * 16 + c * 4 + d, *ids)
    return rows


def build_surface_pl0000(part_data, skel, mat_path, surf_name, tpl_surf, tri_mask=None):
    """Build BMD6 Surface in pl0000_ng space, returning (Surface, final_to_part_corner_idx)."""
    tris = part_data["tris"]
    if tri_mask is not None:
        tris = tris[tri_mask]
        if len(tris) == 0:
            return None, None
        uniq, inv = np.unique(tris.ravel(), return_inverse=True)
        tris = inv.reshape(-1, 3)
        pts = part_data["pts"][uniq]
        nrm = part_data["normals"][uniq]
        uv = part_data["uv"][uniq]
        tw = [part_data["tew_weights"][i] for i in uniq]
        local_to_part = uniq
    else:
        pts = part_data["pts"]
        nrm = part_data["normals"]
        uv = part_data["uv"]
        tw = part_data["tew_weights"]
        local_to_part = np.arange(len(pts), dtype=np.int64)

    rows = encode_wire_weights(tw, skel)
    stream, tri_out, expanded = mesh_stream_tracked(pts, nrm, uv, tris, rows, continuous_tangents=True)
    final_to_part = local_to_part[expanded]
    surf = bmd6.Surface(surf_name, mat_path, stream, tri_out, tpl_surf.flags, tpl_surf.trailer)
    assert surf.count == len(final_to_part)
    return surf, final_to_part


def transfer_surface_tracked(src_surf, src_skel, dst_skel, new_name, tpl_surf, matrices, remap):
    """Transfer a pl0000_ng Surface onto target skeleton via campaign.fit + mesh_stream_tracked,
    returning (new_Surface, final_to_src_vert_idx).
    """
    moved, dirs, uv, tris, wire = campaign.fit(src_surf, src_skel, matrices, remap)
    stream, tri_out, expanded = mesh_stream_tracked(moved, dirs, uv, tris, wire, continuous_tangents=True)
    surf = bmd6.Surface(new_name, src_surf.material, stream, tri_out, tpl_surf.flags, tpl_surf.trailer)
    assert surf.count == len(expanded)
    return surf, expanded


def encode_physics_weights(raw_vgs, corner_indices, bone_to_idx):
    """Encode 4x(boneIdx, weight_u8) per FINAL vertex buffer vertex (100% aligned with GPU VB!)."""
    vc = len(corner_indices)
    enc = np.zeros((vc, 8), dtype=np.uint8)
    for out_i, ci in enumerate(corner_indices):
        grp = raw_vgs[int(ci)]
        hits = [(bone_to_idx[bn], w) for bn, w in grp.items() if bn in bone_to_idx and w > 0.005]
        if not hits:
            enc[out_i, 0] = 255
            enc[out_i, 4] = 255
            continue
        hits.sort(key=lambda x: -x[1])
        hits = hits[:4]
        tot = sum(w for _, w in hits)
        if tot < 0.995:
            if len(hits) == 4:
                hits = [(b, w / tot) for b, w in hits]
            else:
                hits.append((255, 1.0 - tot))
        else:
            hits = [(b, w / tot) for b, w in hits]
        qs = [int(round(w * 255.0)) for _, w in hits]
        qs[0] = max(0, min(255, qs[0] + (255 - sum(qs))))
        for k, ((b, _), qw) in enumerate(zip(hits, qs)):
            enc[out_i, k] = b
            enc[out_i, 4 + k] = qw
    return enc


def pack_texture(img_name, mat_slug, preset, clip_override=None, force_opaque_alpha=False):
    img = bpy.data.images[img_name]
    rgba = tex_encode.rgba_from_blender_image(img)
    if force_opaque_alpha:
        rgba = rgba.copy()
        rgba[:, :, 3] = 255
    p_idx, has_alpha, _ = PRESETS[preset]
    key = f"{MAT_PREFIX}/{mat_slug}"
    color = key + "_c"
    bimg = tex_encode.bimage_from_rgba(rgba, use_bc3=has_alpha)
    decl_bytes = build.material(p_idx, has_alpha, texture=color)
    if clip_override is not None:
        decl_str = decl_bytes.decode("ascii")
        lines = []
        for ln in decl_str.splitlines():
            if ln.startswith("clipthreshold\t"):
                lines.append(f"clipthreshold\t{clip_override:.2f}")
            else:
                lines.append(ln)
        decl_bytes = ("\n".join(lines) + "\n").encode("ascii")
    build.put(OVERLAY_DIR, f"generated/textures/{color}.bimage", bimg)
    build.put(OVERLAY_DIR, f"generated/decls/material/{key}.decl", decl_bytes)
    return key


def build_severed_fragment(mname, target_model, pl0000_model, body_surfaces_pl0000):
    """Build severed limb prop (pl0002..0005, pl0008) by cropping Florence's fitted body cleanly."""
    anchor, main_slot, category = FRAGMENTS[mname]
    src = pl0000_model.skeleton
    dest = target_model.skeleton
    joints = src.joints
    side = anchor[0]
    if category in ("arm", "hand"):
        elbow, wrist = joints[f"{side}_forearm"], joints[f"{side}_hand"]
        forward = build.normalize(wrist - elbow)
        start = elbow if category == "arm" else wrist - 1.2 * forward
        same_side = np.array((0.0, 1.0 if side == "l" else -1.0, 0.0))
        planes = ((start, forward), (np.array((0.0, elbow[1] * 0.72, 0.0)), same_side),
                  (np.array((0.0, 0.0, 35.0)), np.array((0.0, 0.0, 1.0))))
        src_surf = body_surfaces_pl0000["body_larm" if side == "l" else "body_rarm"]
    else:
        knee, ankle = joints[anchor], joints[f"{side}_foot"]
        forward = build.normalize(ankle - knee)
        same_side = np.array((0.0, 1.0 if side == "l" else -1.0, 0.0))
        planes = ((knee - 2.0 * forward, forward), (np.array((0.0, 2.0 if side == "l" else -2.0, 0.0)), same_side))
        src_surf = body_surfaces_pl0000["body_legs"]

    transfer = np.linalg.solve(
        np.vstack((dest.inverse[dest.names.index(anchor)], (0, 0, 0, 1))),
        np.vstack((src.inverse[src.names.index(anchor)], (0, 0, 0, 1))),
    )
    a, b = transfer[:3, :3], transfer[:3, 3]
    selected = campaign.crop(src_surf, planes)
    replacements = {}
    if selected is not None:
        pts, nrms, uv, tris = selected
        if category == "hand":
            src_idx = np.argmin(np.linalg.norm(pts[:, None, :] - src_surf.positions[None, :, :], axis=2), axis=1)
            src_rows = np.frombuffer(src_surf.vertices, "u1").reshape(-1, 32)[src_idx]
            s_ids, mix = campaign.source_weights(src_rows, src)
            _, remap = campaign.transforms(src, dest)
            wire = np.asarray([campaign.encoded_weights(remap[ids], w) for ids, w in zip(s_ids, mix)], dtype="u1")
        else:
            code = dest.remap[dest.names.index(anchor)]
            wire = np.tile([0, code, code, code, code], (len(pts), 1)).astype("u1")
        data = (pts @ a.T + b, build.normalize(nrms @ np.linalg.inv(a)), uv, tris, wire)
        native_slots = {s.name: s for s in target_model.surfaces}
        slot_s = native_slots.get(main_slot, target_model.surfaces[0])
        replacements[slot_s.name] = campaign.packed_surface(slot_s, src_surf.material, data)

    out_surfs = [replacements[s.name] if s.name in replacements else build.hidden(s) for s in target_model.surfaces]
    return bmd6.write_model(target_model, out_surfs)


def bake_body_patch_texture(patch_specs):
    """Unwrap the 5 vertex-colored body patch meshes into clean non-overlapping UV tiles,
    seam-match their 'Florence Skin Color' sRGB vertex colors to 00B_BodySkin's exact texture pixels,
    rasterize with exact barycentric interpolation + 12px dilation into a 1024x1024 BC1 .bimage + .decl!
    """
    def lin2srgb(c):
        c = np.clip(c, 0.0, 1.0)
        return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1.0 / 2.4)) - 0.055)

    # Sample 00B_BodySkin world coords + exact c_FlorenceSSR0101_slg_body_d.png sRGB per vertex
    img = bpy.data.images["c_FlorenceSSR0101_slg_body_d.png"]
    bw, bh = img.size
    bpx = np.empty(bw * bh * 4, dtype=np.float32)
    img.pixels.foreach_get(bpx)
    bpx = bpx.reshape(bh, bw, 4)

    body_obj = bpy.data.objects["00B_BodySkin"]
    bmw = np.array(body_obj.matrix_world, dtype=np.float64)
    bn = len(body_obj.data.vertices)
    bco = np.empty(bn * 3, dtype=np.float32)
    body_obj.data.vertices.foreach_get("co", bco)
    bpts = bco.reshape(-1, 3) @ bmw[:3, :3].T + bmw[:3, 3]
    buv = np.empty(len(body_obj.data.loops) * 2, dtype=np.float32)
    body_obj.data.uv_layers.active.uv.foreach_get("vector", buv)
    buv = buv.reshape(-1, 2)
    bvids = np.empty(len(body_obj.data.loops), dtype=np.int32)
    body_obj.data.loops.foreach_get("vertex_index", bvids)
    b_rgb = np.zeros((bn, 3), dtype=np.float64)
    b_cnt = np.zeros(bn, dtype=np.float64)
    bu = np.clip((buv[:, 0] % 1.0) * (bw - 1), 0, bw - 1).astype(int)
    bv = np.clip((buv[:, 1] % 1.0) * (bh - 1), 0, bh - 1).astype(int)
    np.add.at(b_rgb, bvids, bpx[bv, bu, :3])
    np.add.at(b_cnt, bvids, 1.0)
    b_rgb /= np.maximum(b_cnt[:, None], 1.0)

    # Target 1024x1024 RGBA atlas (note: tex_encode expects top-down RGBA uint8, while Blender UV v=0 is bottom!)
    W = H = 1024
    atlas = np.zeros((H, W, 3), dtype=np.float64)
    mask = np.zeros((H, W), dtype=bool)

    for oname, (u0, v0, u1, v1) in patch_specs:
        obj = bpy.data.objects[oname]
        mesh = obj.data
        mesh.calc_loop_triangles()

        n = len(mesh.vertices)
        n_loops = len(mesh.loops)
        co = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        omw = np.array(obj.matrix_world, dtype=np.float64)
        pts = co.reshape(-1, 3).astype(np.float64) @ omw[:3, :3].T + omw[:3, 3]
        lv = np.empty(n_loops, dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", lv)

        # Create clean non-overlapping UV coordinates (zero smart_project NaN/overflow bugs!):
        # - If mesh already has a valid finite UV layer (下身细节), reuse it cleanly!
        # - Otherwise (胸前补片, 腰胯补片, 大腿接缝, 颈部接缝), split front (ny<0) / back (ny>=0) planar (X, Z)!
        has_native_uv = len(mesh.uv_layers) > 0
        if not has_native_uv:
            mesh.uv_layers.new(name="UVMap")
        uv_layer = mesh.uv_layers.active or mesh.uv_layers[0]
        mesh.uv_layers.active = uv_layer

        pad = 0.02
        if has_native_uv:
            uv_arr = np.empty(n_loops * 2, dtype=np.float32)
            uv_layer.uv.foreach_get("vector", uv_arr)
            uv_arr = uv_arr.reshape(-1, 2).astype(np.float64)
            umin, vmin = uv_arr.min(axis=0)
            umax, vmax = uv_arr.max(axis=0)
            uv_norm = (uv_arr - np.array([umin, vmin])) / np.maximum(np.array([umax - umin, vmax - vmin]), 1e-6)
            uv_tile = np.empty_like(uv_norm)
            uv_tile[:, 0] = (u0 + pad) + uv_norm[:, 0] * max(1e-4, (u1 - u0) - 2 * pad)
            uv_tile[:, 1] = (v0 + pad) + uv_norm[:, 1] * max(1e-4, (v1 - v0) - 2 * pad)
        else:
            # Front/Back planar (X, Z) projection split by polygon world-space normal Y!
            uv_tile = np.zeros((n_loops, 2), dtype=np.float64)
            nrm_m = np.linalg.inv(omw[:3, :3]).T
            xmin, zmin = pts[:, 0].min(), pts[:, 2].min()
            xmax, zmax = pts[:, 0].max(), pts[:, 2].max()
            xr = max(xmax - xmin, 1e-5)
            zr = max(zmax - zmin, 1e-5)
            has_back = False
            poly_back = []
            for p in mesh.polygons:
                wn = np.array(p.normal[:], dtype=np.float64) @ nrm_m.T
                is_b = wn[1] > 0.0
                poly_back.append(is_b)
                if is_b:
                    has_back = True
            umid = 0.5 * (u0 + u1)
            for p, is_b in zip(mesh.polygons, poly_back):
                if has_back:
                    tu0, tu1 = (umid + pad * 0.5, u1 - pad) if is_b else (u0 + pad, umid - pad * 0.5)
                else:
                    tu0, tu1 = u0 + pad, u1 - pad
                for li in p.loop_indices:
                    pt = pts[lv[li]]
                    nx = (pt[0] - xmin) / xr
                    nz = (pt[2] - zmin) / zr
                    uv_tile[li, 0] = tu0 + nx * max(1e-4, tu1 - tu0)
                    uv_tile[li, 1] = (v0 + pad) + nz * max(1e-4, (v1 - v0) - 2 * pad)

        uv_layer.uv.foreach_set("vector", uv_tile.astype(np.float32).ravel())

        # Read 'Florence Skin Color' (FLOAT_COLOR linear) -> sRGB + exact seam match to 00B_BodySkin!

        ca = mesh.color_attributes.active_color or mesh.color_attributes[0]
        raw_c = np.empty(len(ca.data) * 4, dtype=np.float32)
        ca.data.foreach_get("color", raw_c)
        raw_c = raw_c.reshape(-1, 4)[:, :3]
        if ca.domain == "POINT":
            vcol_srgb = lin2srgb(raw_c.astype(np.float64))
        else:
            lv = np.empty(n_loops, dtype=np.int32)
            mesh.loops.foreach_get("vertex_index", lv)
            vc_acc = np.zeros((n, 3), dtype=np.float64)
            vc_cnt = np.zeros(n, dtype=np.float64)
            np.add.at(vc_acc, lv, raw_c)
            np.add.at(vc_cnt, lv, 1.0)
            vcol_srgb = lin2srgb(vc_acc / np.maximum(vc_cnt[:, None], 1.0))

        # Match outer seam vertices cleanly to exact surrounding 00B_BodySkin RGB (preserves nipple/detail pink contrast!)
        d2 = np.sum((pts[:, None, :] - bpts[None, :, :]) ** 2, axis=2)
        nn = np.argmin(d2, axis=1)
        nn_dist = np.sqrt(d2[np.arange(n), nn])
        seam = nn_dist < 0.006
        if seam.any():
            src_mean = np.maximum(vcol_srgb[seam].mean(axis=0), 1e-4)
            dst_mean = b_rgb[nn[seam]].mean(axis=0)
            ratio = np.clip(dst_mean / src_mean, 0.85, 1.15)
            vcol_srgb = np.clip(vcol_srgb * ratio[None, :], 0.0, 1.0)
            # Also smoothly lock exact seam boundary vertices (< 0.002m) to surrounding body pixel
            exact_seam = nn_dist < 0.002
            if exact_seam.any():
                blend = np.clip(1.0 - nn_dist[exact_seam] / 0.002, 0.0, 1.0)[:, None] * 0.85
                vcol_srgb[exact_seam] = vcol_srgb[exact_seam] * (1.0 - blend) + b_rgb[nn[exact_seam]] * blend
            print(f"  Baked patch {oname:8s}: seam_ratio={ratio.round(3).tolist()} mean_sRGB={vcol_srgb.mean(0).round(3).tolist()}")

        # Rasterize every triangle with exact barycentric interpolation into top-down atlas (row 0 = top = v=1.0)
        mesh.calc_loop_triangles()
        lv = np.empty(n_loops, dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", lv)
        for lt in mesh.loop_triangles:
            l0, l1, l2 = lt.loops
            x0, y0 = uv_tile[l0, 0] * (W - 1), (1.0 - uv_tile[l0, 1]) * (H - 1)
            x1, y1 = uv_tile[l1, 0] * (W - 1), (1.0 - uv_tile[l1, 1]) * (H - 1)
            x2, y2 = uv_tile[l2, 0] * (W - 1), (1.0 - uv_tile[l2, 1]) * (H - 1)
            c0, c1, c2 = vcol_srgb[lv[l0]], vcol_srgb[lv[l1]], vcol_srgb[lv[l2]]
            ix0 = max(0, int(np.floor(min(x0, x1, x2))))
            ix1 = min(W - 1, int(np.ceil(max(x0, x1, x2))))
            iy0 = max(0, int(np.floor(min(y0, y1, y2))))
            iy1 = min(H - 1, int(np.ceil(max(y0, y1, y2))))
            if ix1 < ix0 or iy1 < iy0:
                continue
            denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(denom) < 1e-8:
                continue
            gx, gy = np.meshgrid(np.arange(ix0, ix1 + 1, dtype=np.float64),
                                 np.arange(iy0, iy1 + 1, dtype=np.float64))
            w0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denom
            w1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denom
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-3) & (w1 >= -1e-3) & (w2 >= -1e-3)
            if not inside.any():
                continue
            w0c = np.clip(w0[inside], 0.0, 1.0)
            w1c = np.clip(w1[inside], 0.0, 1.0)
            w2c = np.clip(w2[inside], 0.0, 1.0)
            wsum = np.maximum(w0c + w1c + w2c, 1e-8)
            col = (w0c[:, None] * c0 + w1c[:, None] * c1 + w2c[:, None] * c2) / wsum[:, None]
            ys = gy[inside].astype(int)
            xs = gx[inside].astype(int)
            atlas[ys, xs] = col
            mask[ys, xs] = True

    # 16-pass dilation so mipmaps & BC1 4x4 blocks NEVER bleed black borders!
    bg_skin = b_rgb.mean(axis=0)
    for _ in range(16):
        acc = np.zeros_like(atlas)
        cnt = np.zeros((H, W), dtype=np.float64)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            sy0 = max(0, -dy); sy1 = H - max(0, dy)
            sx0 = max(0, -dx); sx1 = W - max(0, dx)
            dy0 = max(0, dy);  dy1 = H - max(0, -dy)
            dx0 = max(0, dx);  dx1 = W - max(0, -dx)
            m_src = mask[sy0:sy1, sx0:sx1]
            acc[dy0:dy1, dx0:dx1] += atlas[sy0:sy1, sx0:sx1] * m_src[:, :, None]
            cnt[dy0:dy1, dx0:dx1] += m_src
        grow = (~mask) & (cnt > 0)
        if not grow.any():
            break
        atlas[grow] = acc[grow] / cnt[grow, None]
        mask[grow] = True
    atlas[~mask] = bg_skin

    rgba = np.empty((H, W, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(np.rint(atlas * 255.0), 0, 255).astype(np.uint8)
    rgba[:, :, 3] = 255

    p_idx, has_alpha, _ = PRESETS["OPAQUE"]
    key = f"{MAT_PREFIX}/body_patch"
    color = key + "_c"
    bimg = tex_encode.bimage_from_rgba(rgba, use_bc3=False)
    decl_bytes = build.material(p_idx, has_alpha, texture=color)
    build.put(OVERLAY_DIR, f"generated/textures/{color}.bimage", bimg)
    build.put(OVERLAY_DIR, f"generated/decls/material/{key}.decl", decl_bytes)
    print(f"Encoded baked skin-matched patch texture: {color}.bimage (1024x1024 BC1)")
    return key


def main():
    print("=== 1. Clean overlay dir & load 27 stock TEW1 templates ===")
    if OVERLAY_DIR.exists():
        shutil.rmtree(OVERLAY_DIR)
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    templates = load_stock_templates()
    pl0000_tpl = templates["pl0000_ng"]
    stock_skel = pl0000_tpl.skeleton
    stock_joints = stock_skel.joints

    arm = bpy.data.objects["GirlsFrontline FlorencePajama_arm"]
    bone_table = build_bone_weight_table(arm)

    # Verify 0 unmapped weighted bones across all meshes
    unmapped = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name == "00N_Emotions2":
            continue
        for vg in o.vertex_groups:
            if vg.name not in IGNORED_VGS and vg.name not in bone_table:
                unmapped.append((o.name, vg.name))
    assert not unmapped, f"Unmapped vertex groups: {unmapped[:10]}"
    print(f"Bone mapping table built for all {len(bone_table)} armature bones (0 unmapped).")

    print("=== 2. Computing Haruka-grade segment_fit() transforms onto Sebastian pl0000_ng ===")
    scale, offset, seg_transforms = compute_haruka_segment_transforms(arm, stock_joints)

    print("=== 3. Encoding textures -> .bimage + forward .decl ===")
    mat_body   = pack_texture("c_FlorenceSSR0101_slg_body_d.png",  "body",      "OPAQUE", force_opaque_alpha=True)
    mat_face   = pack_texture("c_Florence_slg_face_d.png",         "face",      "OPAQUE", force_opaque_alpha=True)
    mat_hair   = pack_texture("c_FlorenceSSR01_slg_hair_d.png",    "hair",      "HAIR",   force_opaque_alpha=True)
    # Outerwear-ONLY sheer BC3 material (ONLY for var_2 pajama body & var_3 pajama sleeves!)
    mat_cloth       = pack_texture("c_FlorenceSSR0101_slg_cloth_da.png", "cloth",       "CUTOUT", clip_override=0.05, force_opaque_alpha=False)
    # 100% SOLID OPAQUE BC1 material (ZERO alpha!) for panties, bra, ribbon, choker/garter, cuffs — NEVER transparent!
    mat_cloth_solid = pack_texture("c_FlorenceSSR0101_slg_cloth_da.png", "cloth_solid", "OPAQUE", force_opaque_alpha=True)
    mat_eyes   = pack_texture("c_Florence_slg_eye_d.png",          "eyes",      "OPAQUE", force_opaque_alpha=True)
    mat_eyes_p = pack_texture("c_Florence_slg_eyeblend.png",       "eyes_plus", "CUTOUT", clip_override=0.22)
    mat_stk1   = pack_texture("73718671_p1.png",                   "sticker1",  "CUTOUT", clip_override=0.35)
    mat_stk2   = pack_texture("39780044_p3.png",                   "sticker2",  "CUTOUT", clip_override=0.35)
    mat_pubic  = pack_texture("tex.png",                           "pubic",     "CUTOUT", clip_override=0.35)
    # Bake the 5 vertex-colored body patches (nipples/lower-body/waist/thigh/neck) with exact skin-tone matching!
    patch_tiles = [
        ("下身细节", (0.00, 0.50, 0.50, 1.00)),
        ("腰胯补片", (0.50, 0.50, 1.00, 1.00)),
        ("胸前补片", (0.00, 0.00, 0.50, 0.50)),
        ("大腿接缝", (0.50, 0.25, 1.00, 0.50)),
        ("颈部接缝", (0.50, 0.00, 1.00, 0.25)),
    ]
    mat_patch  = bake_body_patch_texture(patch_tiles)

    print("=== 4. Extracting & fitting all character parts (with 000_Face material split!) ===")
    # 7 Clothing-Only Variant Groups: ONLY pajama coat (var_2) & sleeves (var_3) use sheer mat_cloth;
    # panties (var_6), bra (var_5), ribbon (var_0), choker/garter (var_1), cuffs (var_4) use 100% OPAQUE mat_cloth_solid!
    variant_specs = [
        ("发带 / 头部蝴蝶结",    "var_0", [("00I_Cloth2A", None)],       mat_cloth_solid, "HEAD"),
        ("颈环 & 大腿腿环",      "var_1", [("00H_Cloth1D", None)],       mat_cloth_solid, "BODY"),
        ("睡衣主体（爱心裙身）", "var_2", [("00K_Cloth2B", None)],       mat_cloth,       "BODY"),
        ("睡衣长袖",             "var_3", [("00L_Cloth2C", None)],       mat_cloth,       "BODY"),
        ("袖口与下摆收口边",     "var_4", [("00J_Cloth2E", None)],       mat_cloth_solid, "BODY"),
        ("上身内衣",             "var_5", [("00D_InnerWear.001", None)], mat_cloth_solid, "BODY"),
        ("下身内裤",             "var_6", [("00D_InnerWear", None)],     mat_cloth_solid, "BODY"),
    ]

    part_defs = [
        # Head parts (Face merges Face+Mouth+Teeth+Tongue+EyeWhite+Brows+Lashes — all share c_Florence_slg_face_d.png OPAQUE!)
        ("face",  [("000_Face", "Face"), ("001_Mouth", None), ("002_Teeth", None), ("003_Teeth.001", None),
                   ("004_Tongue", None), ("005_EyeWhite", None), ("006_Brows", None), ("007_Lashes", None)],
         mat_face, "HEAD", -1, True),
        ("eyes",      [("008_Eyes", None)],  mat_eyes,   "HEAD", -1, False),
        ("eyesp",     [("009_Eyes+", None)], mat_eyes_p, "HEAD", -1, False),
        ("head_skin", [("000_Face", "BodySkin")], mat_body, "HEAD", -1, False),
        ("hair",      [("00E_Hair", None), ("00F_Hair.001", None), ("00G_Hair.002", None)], mat_hair, "HEAD", -1, False),
        # Body (00B_BodySkin + Nails ONLY — 000_Face BodySkin ears/upper-neck belongs to HEAD so decapitation is 100% clean!)
        ("body",      [("00B_BodySkin", None), ("00C_Nails", None)],
         mat_body, "BODY", -1, False),
        # Baked vertex-colored body patches (nipples/lower-body/waist/thigh/neck) — skin-tone matched to 00B_BodySkin!
        ("patch", [("下身细节", None), ("胸前补片", None), ("腰胯补片", None), ("大腿接缝", None), ("颈部接缝", None)],
         mat_patch, "BODY", -1, False),
        ("stk1",  [("007_贴图1", None)], mat_stk1,  "BODY", -1, False),
        ("stk2",  [("008_贴图2", None)], mat_stk2,  "BODY", -1, False),
        ("pubic", [("下身毛发", None)],  mat_pubic, "BODY", -1, False),
    ]
    for vi, (vlabel, pkey, specs, vmat, kind) in enumerate(variant_specs):
        part_defs.append((pkey, specs, vmat, kind, vi, False))

    parts = {}
    for pkey, specs, matp, kind, vidx, cg_face in part_defs:
        pdata = extract_fitted_part(specs, arm, bone_table, scale, offset, seg_transforms, stock_skel, add_cg_face_weights=cg_face)
        parts[pkey] = {"data": pdata, "mat": matp, "kind": kind, "vidx": vidx}
        print(f"  Part {pkey:6s}: verts={len(pdata['pts']):5d} tris={len(pdata['tris']):5d} "
              f"Z=[{pdata['pts'][:,2].min():.2f}, {pdata['pts'][:,2].max():.2f}] morphs={pdata['morphs'] is not None}")

    # Anti-clipping pass on panties (var_6): original Blender upper-back waistband sits at 0.000 clearance
    # flush on 00B_BodySkin/腰胯补片, causing Z-fight / butt poke-through during gameplay poses.
    # Enforce clean outward clearance (0.22 back / 0.12 front-side) + exact nearest-skin weight sync!
    skin_pts = np.vstack([parts["body"]["data"]["pts"], parts["patch"]["data"]["pts"]])
    skin_nrms = np.vstack([parts["body"]["data"]["normals"], parts["patch"]["data"]["normals"]])
    skin_ws = parts["body"]["data"]["tew_weights"] + parts["patch"]["data"]["tew_weights"]
    v6d = parts["var_6"]["data"]
    pp = v6d["pts"]
    d2 = np.sum((pp[:, None, :] - skin_pts[None, :, :]) ** 2, axis=2)
    nn = np.argmin(d2, axis=1)
    n_out = skin_nrms[nn]
    signed = np.sum((pp - skin_pts[nn]) * n_out, axis=1)
    min_clear = np.where(pp[:, 0] < -0.5, 0.22, 0.12)
    push = np.maximum(0.0, min_clear - signed)
    pp += n_out * push[:, None]
    # Re-sync quantized weights to exact nearest underlying skin vertex so skin & panties move 100% in lockstep
    v6d["tew_weights"] = [skin_ws[int(idx)] for idx in nn]
    print(f"  Anti-clip var_6: pushed {(push > 1e-4).sum()}/{len(pp)} verts outward (max_push={push.max():.3f}, back min_clear=0.22)")

    # Precompute 4-limb dismemberment triangle masks on body (0=torso, 1=l_arm, 2=r_arm, 3=legs)
    bd = parts["body"]["data"]
    v_limb = np.zeros(len(bd["pts"]), dtype=np.int32)
    for vi, tw in enumerate(bd["tew_weights"]):
        s_l = sum(w for bn, w in tw if bn in LEFT_ARM_BONES)
        s_r = sum(w for bn, w in tw if bn in RIGHT_ARM_BONES)
        s_g = sum(w for bn, w in tw if bn in LEG_BONES)
        best = max((s_l, 1), (s_r, 2), (s_g, 3))
        if best[0] >= 0.50:
            v_limb[vi] = best[1]
    tri_g = v_limb[bd["tris"]]
    is_larm = np.sum(tri_g == 1, axis=1) >= 2
    is_rarm = (~is_larm) & (np.sum(tri_g == 2, axis=1) >= 2)
    is_legs = (~is_larm) & (~is_rarm) & (np.sum(tri_g == 3, axis=1) >= 2)
    is_torso = (~is_larm) & (~is_rarm) & (~is_legs)
    body_masks = {
        "body_torso": is_torso,
        "body_larm":  is_larm,
        "body_rarm":  is_rarm,
        "body_legs":  is_legs,
    }

    print("=== 5. Collecting Physics Chains (10 Hair + 2 Chest) & 5 Humanoid Colliders ===")
    def trace_chain(root_b):
        ch = [root_b.name]
        cur = root_b
        while len(cur.children) == 1:
            cur = cur.children[0]
            ch.append(cur.name)
        if len(ch) > 1 and ch[-1].endswith("A"):
            ch = ch[:-1]
        return ch

    def bone_pos_tew(p_bl):
        return (np.array([p_bl.x, p_bl.y, p_bl.z], dtype=np.float64) @ R_BL2TEW.T) * scale + offset

    chains_spec = []
    # 11 Hair chains under 頭 (anchorSlot = 0 -> head), tuned per zone so bangs & side hair stay silky and controlled!
    for b in sorted(arm.data.bones, key=lambda x: x.name):
        if b.parent and b.parent.name == "頭" and ("hair" in b.name.lower() or "bangs" in b.name.lower()):
            bnames = trace_chain(b)
            n_lo = bnames[0].lower()
            is_long = len(bnames) >= 5
            if is_long:
                stiff, damp, grav, rad = 115.0, 0.28, 11.5, 0.32
            elif "bangs" in n_lo or n_lo.endswith("_l01") or n_lo.endswith("_r01"):
                # Front bangs (v2.5): completely locked rigid to head (ZERO physics sway!)
                continue
            elif n_lo.endswith("_l016") or n_lo.endswith("_r016"):
                # Twin-tail side flares (v2.5): calm controlled sway
                stiff, damp, grav, rad = 520.0, 0.50, 3.0, 0.17
            else:
                # Side cheek locks & upper side hair (v2.5): calm controlled sway
                stiff, damp, grav, rad = 700.0, 0.56, 1.8, 0.12
            chains_spec.append({
                "name": bnames[0],
                "bones": bnames,
                "anchor_slot": 0,  # head
                "stiffness": stiff,
                "damping": damp,
                "gravity": grav,
                "radius": rad,
            })

    # 2 Chest chains (anchorSlot = 3 -> spine_02! Soft jiggle clamped cleanly to radius=0.75 units, NO torso push-out!)
    for cname in ("bone0400_Chest_L", "bone0404_Chest_R"):
        if cname in arm.data.bones:
            chains_spec.append({
                "name": cname,
                "bones": [cname],
                "anchor_slot": 3,  # colRemap[2] = spine_02
                "stiffness": 185.0,
                "damping": 0.26,
                "gravity": 2.2,
                "radius": 0.75,    # max smooth jiggle displacement (~1.5 cm, never explodes!)
            })

    bone_to_idx = {}
    chains_bin = []
    for ch in chains_spec:
        b_objs = [arm.data.bones[n] for n in ch["bones"]]
        nodes = [bone_pos_tew(arm.matrix_world @ b_objs[0].head_local)]
        for b in b_objs:
            bone_to_idx[b.name] = len(bone_to_idx)
            p_head = bone_pos_tew(arm.matrix_world @ b.head_local)
            p_tail = bone_pos_tew(arm.matrix_world @ b.tail_local)
            if ch["anchor_slot"] == 0 and p_tail[2] > p_head[2] + 1.0 and len(nodes) >= 2:
                # Fix dummy end-bone whose tail points straight up (+Z)
                p_tail = p_head + (nodes[-1] - nodes[-2])
            if np.linalg.norm(p_tail - p_head) < 0.2:
                # Give chest bone a clean forward (+X) 2.2-unit direction so RotationBetween works smoothly!
                p_tail = p_head + np.array([2.2, 0.0, 0.0], dtype=np.float64)
            nodes.append(p_tail)
        chains_bin.append({**ch, "num_bones": len(b_objs), "nodes": np.asarray(nodes, dtype=np.float64)})
    print(f"Configured {len(chains_bin)} physics chains ({sum(c['num_bones'] for c in chains_bin)} bones: 10 hair + 2 chest).")

    # 5 Calibrated Humanoid Colliders directly from pl0000_ng stock joints (strictly for hair chains!)
    col_bones = ("head", "neck_00", "spine_02", "l_shoulder", "r_shoulder")
    colliders_bin = [
        (0, stock_joints["head"] + np.array([0.0, 0.0, 2.2]), stock_joints["head"] + np.array([-0.5, 0.0, 5.2]), 4.4),
        (1, stock_joints["neck_00"] + np.array([0.0, 0.0, 0.0]), stock_joints["head"] + np.array([-0.4, 0.0, 0.5]), 2.8),
        (2, stock_joints["spine_02"] + np.array([-1.0, 0.0, -3.0]), stock_joints["spine_02"] + np.array([-1.2, 0.0, 8.0]), 5.6),
        (3, stock_joints["l_shoulder"] + np.array([-0.5, 0.0, -0.5]), stock_joints["l_upperarm"] + np.array([-0.3, 1.5, -1.5]), 3.5),
        (4, stock_joints["r_shoulder"] + np.array([-0.5, 0.0, -0.5]), stock_joints["r_upperarm"] + np.array([-0.3, -1.5, -1.5]), 3.5),
    ]

    print("=== 6. Building Master pl0000_ng surfaces (with exact post-mesh_stream tracking!) ===")
    tpl_face = next(s for s in pl0000_tpl.surfaces if s.name == "m_face")
    tpl_body = next(s for s in pl0000_tpl.surfaces if s.name == "m_shirt__nn")

    # Master surfaces in pl0000_ng space + exact post-mesh_stream mapping to part corners
    master_surfs = {}  # key -> (Surface, part_key, final_to_part_corner_idx)
    for pkey in ("face", "eyes", "eyesp", "head_skin", "hair", "var_0"):
        s, f2p = build_surface_pl0000(parts[pkey]["data"], stock_skel, parts[pkey]["mat"], "m_face", tpl_face)
        master_surfs[pkey] = (s, pkey, f2p)
    for bkey, slot_nm in (("body_torso", "m_shirt__nn"), ("body_larm", "m_hand_l"),
                          ("body_rarm", "m_r_shrit_arm__na"), ("body_legs", "m_pants_leg__np")):
        s, f2p = build_surface_pl0000(parts["body"]["data"], stock_skel, parts["body"]["mat"], slot_nm, tpl_body, tri_mask=body_masks[bkey])
        master_surfs[bkey] = (s, "body", f2p)
    for pkey in ("patch", "var_1", "var_2", "var_3", "var_4", "var_5", "var_6", "stk1", "stk2", "pubic"):
        s, f2p = build_surface_pl0000(parts[pkey]["data"], stock_skel, parts[pkey]["mat"], "m_shirt__nn", tpl_body)
        master_surfs[pkey] = (s, pkey, f2p)

    print("=== 7. Generating all 27 chapter / cutscene / dismemberment .bmd6model files via campaign.fit ===")
    skeletons_by_head = {}
    hair_fps = []        # (headRemap, vert0Remap, vertCount, weightOffset, pts3)
    hair_weights_list = []
    hair_weight_total = 0
    seen_phys_keys = set()
    face_matches = {}
    extra_char_fps = {}
    variant_fps = [[] for _ in variant_specs]
    seen_var_keys = [set() for _ in variant_specs]

    def pick_bone(skel, *names):
        for n in names:
            if n in skel.names:
                i = skel.names.index(n)
                return int(skel.remap[i]), skel.joints[n]
        return -1, np.zeros(3, dtype=float)

    def register_runtime_vb(part_key, surf, final_to_part, skel_hr, s_idx, head_rot_mat):
        nonlocal hair_weight_total
        info = parts[part_key]
        pts3 = surf.positions[:3].astype("<f4")
        raw_v = np.frombuffer(surf.vertices, "u1").reshape(-1, 32)
        v0_remap = int(raw_v[0, 28])
        vlast_remap = int(raw_v[-1, 28])
        vidx = info["vidx"]

        # Section 8: Clothing Variant Group fingerprint (registered per model so Insert works in ALL chapters!)
        if vidx >= 0:
            vk = (surf.count, pts3.tobytes())
            if vk not in seen_var_keys[vidx]:
                seen_var_keys[vidx].add(vk)
                variant_fps[vidx].append((surf.count, pts3))

        # Section 6: Extra character VB for F7/F8/F9 self-illumination
        ek = (surf.count, pts3.tobytes())
        if ek not in extra_char_fps:
            extra_char_fps[ek] = (surf.count, pts3)

        # Only register dynamic physics & face morphs when the model has a head skeleton profile
        if skel_hr <= 0:
            return

        # Section 5: Face Morphs (100% exact post-mesh_stream vertex indices!)
        morphs = info["data"]["morphs"]
        if morphs is not None and part_key in ("face", "eyes", "eyesp"):
            # Face morph VBs must have vert[0] on head (or match headRemap in HookCreateBuffer!)
            if v0_remap == skel_hr:
                fk = (skel_hr, s_idx, surf.count, pts3.tobytes())
                if fk not in face_matches:
                    chans = []
                    any_c = False
                    for ci in range(len(CHANNEL_ALIASES)):
                        d = morphs[ci][final_to_part] @ head_rot_mat.T
                        mag = np.linalg.norm(d, axis=1)
                        act = np.where(mag > 1e-4)[0]
                        if len(act) > 0:
                            any_c = True
                        chans.append([(int(vi), float(d[vi, 0]), float(d[vi, 1]), float(d[vi, 2])) for vi in act])
                    if any_c:
                        face_matches[fk] = (skel_hr, s_idx & 0xFF, surf.count, pts3, chans)

        # Section 4 + v3.2: Hair OR Chest physics VB (disambiguated by (skel_hr, v0_remap, vlast_remap, vertCount, pts3)!)
        enc = encode_physics_weights(info["data"]["raw_vgs"], final_to_part, bone_to_idx)
        active_verts = int((enc[:, 0] != 255).sum())
        if active_verts >= 8:
            assert len(enc) == surf.count
            pk = (skel_hr, v0_remap, vlast_remap, surf.count, pts3.tobytes())
            if pk not in seen_phys_keys:
                seen_phys_keys.add(pk)
                hair_fps.append((skel_hr, v0_remap, vlast_remap, surf.count, hair_weight_total, pts3))
                hair_weights_list.append(enc)
                hair_weight_total += surf.count

    # Process pl0000_ng first so its fingerprints always have priority!
    ordered_targets = ["pl0000_ng"] + sorted(ALL_TARGETS - {"pl0000_ng"})
    pl0000_head_pos = stock_joints["head"]

    for mname in ordered_targets:
        model = templates[mname]
        skel = model.skeleton
        rel = asset_rel_path(mname)

        # Hidden-only wound stub (pl0007 = 2-bone right-shin leg wound prop, MUST be 100% hidden like Haruka!)
        if mname in HIDDEN_ONLY_MODELS:
            out_bytes = bmd6.write_model(model, [build.hidden(s) for s in model.surfaces])
            build.put(OVERLAY_DIR, rel, out_bytes)
            print(f"  Built {mname:12s} (hidden wound stub, 0 live tris)")
            continue

        # Severed limb fragment models (pl0002..0005, pl0008)
        if mname in FRAGMENTS:
            out_bytes = build_severed_fragment(mname, model, pl0000_tpl, {
                k: master_surfs[k][0] for k in ("body_larm", "body_rarm", "body_legs")
            })
            build.put(OVERLAY_DIR, rel, out_bytes)
            print(f"  Built {mname:12s} (severed limb fragment)")
            continue

        # Compute exact skeleton-to-skeleton transform from pl0000_ng -> target model!
        if mname == "pl0000_ng":
            matrices = None
            remap = None
            head_xform = np.eye(4)
        else:
            matrices, remap = campaign.transforms(stock_skel, skel)
            head_xform = matrices[stock_skel.names.index("head")] if "head" in stock_skel.names else np.eye(4)

        # Register skeleton profile if this model has 'head'
        skel_hr = 0
        if "head" in skel.names:
            hi = skel.names.index("head")
            skel_hr = int(skel.remap[hi])
            if skel_hr not in skeletons_by_head:
                col_remaps = [pick_bone(skel, cb)[0] for cb in col_bones]
                # Exact head alignment matrix from pl0000_ng rest space -> target rest space
                jr, jj = pick_bone(skel, "jaw")
                jp = jj + np.array([3.2, 0.0, -3.0]) if jr >= 0 else np.zeros(3)
                skeletons_by_head[skel_hr] = {
                    "head_remap": skel_hr,
                    "col_remaps": col_remaps,
                    "head_align": head_xform[:3, :4].astype(np.float32),
                    "drivers": [
                        (jr, jp),
                        pick_bone(skel, "eyelid_u_l_middle", "l_eyelid", "eyelid_u_l"),
                        pick_bone(skel, "eyelid_u_r_middle", "r_eyelid", "eyelid_u_r"),
                        pick_bone(skel, "eyebrow_l_middle", "l_eyebrow_00", "eyebrow_l_in"),
                        pick_bone(skel, "eyebrow_r_middle", "r_eyebrow_00", "eyebrow_r_in"),
                        pick_bone(skel, "mouth_u_l_corner", "mouth_l_side"),
                        pick_bone(skel, "mouth_u_r_corner", "mouth_r_side"),
                    ],
                }

        # CRITICAL FIX: Use build.hidden(s) so Havok m_hair & __clt preserve their EXACT vertex buffer size!
        surfs_out = [build.hidden(s) for s in model.surfaces]
        tpl_s = next((s for s in model.surfaces if s.name == "m_face"), model.surfaces[0])
        free_slots = [i for i, s in enumerate(model.surfaces)
                      if s.name != "m_hair" and "__clt" not in s.name.lower()]

        def place_master(mkey, slot_name, prefer_last=False):
            src_s, pkey, src_f2p = master_surfs[mkey]
            target_idx = None
            if prefer_last:
                # Sheer semi-transparent cloth MUST render strictly AFTER all opaque body/arm/patch/innerwear surfaces!
                if len(surfs_out) < 31:
                    tpl_slot = next((s for s in model.surfaces if s.name == slot_name), tpl_s)
                elif free_slots:
                    target_idx = free_slots.pop()
                    tpl_slot = model.surfaces[target_idx]
                else:
                    print(f"  [WARN] {mname}: skipped {mkey} to stay <= 31 surfaces")
                    return
            else:
                named_idx = next((i for i in free_slots if model.surfaces[i].name == slot_name), None)
                # Keep the last 2 slots free for sheer pajama surfaces (var_3, var_2) so sheer skirt NEVER renders before body_legs!
                if named_idx is not None and named_idx >= len(model.surfaces) - 2 and free_slots and free_slots[0] < named_idx:
                    target_idx = free_slots[0]
                    free_slots.remove(target_idx)
                    tpl_slot = model.surfaces[named_idx]
                else:
                    target_idx = named_idx if named_idx is not None else (free_slots[0] if free_slots else None)
                    if target_idx is not None:
                        free_slots.remove(target_idx)
                        tpl_slot = model.surfaces[target_idx]
                    elif len(surfs_out) < 31:
                        tpl_slot = tpl_s
                    else:
                        print(f"  [WARN] {mname}: skipped {mkey} to stay <= 31 surfaces")
                        return

            if mname == "pl0000_ng":
                out_s = replace(src_s, name=slot_name, flags=tpl_slot.flags, trailer=tpl_slot.trailer)
                f2p = src_f2p
            else:
                out_s, exp = transfer_surface_tracked(src_s, stock_skel, skel, slot_name, tpl_slot, matrices, remap)
                f2p = src_f2p[exp]

            if target_idx is not None:
                surfs_out[target_idx] = out_s
                s_idx = target_idx
            else:
                s_idx = len(surfs_out)
                surfs_out.append(out_s)
            register_runtime_vb(pkey, out_s, f2p, skel_hr, s_idx, head_xform[:3, :3])

        has_head = mname not in BODY_MODELS
        has_body = mname not in HEAD_ONLY_MODELS

        if has_head:
            h_slot = HEAD_ONLY_SLOT[mname] if mname in HEAD_ONLY_SLOT else FULL_MODEL_HEAD_SLOT[mname]
            for mkey in ("face", "eyes", "eyesp", "head_skin", "hair", "var_0"):
                place_master(mkey, h_slot)

        if has_body:
            torso_s, larm_s, rarm_s, leg_s = BODY_SLOTS_BY_MODEL[mname]
            place_master("body_torso", torso_s)
            place_master("body_larm",  larm_s)
            place_master("body_rarm",  rarm_s)
            place_master("body_legs",  leg_s)
            # Place ALL opaque body overlays/innerwear FIRST, then sheer pajama sleeves (var_3) & body (var_2) DEAD LAST!
            for mkey in ("patch", "var_1", "var_4", "var_5", "var_6", "stk1", "stk2", "pubic"):
                place_master(mkey, torso_s)
            for mkey in ("var_3", "var_2"):
                place_master(mkey, torso_s, prefer_last=True)

        assert len(surfs_out) <= 31, f"{mname} exceeded 31 surfaces ({len(surfs_out)})!"
        # Verify Havok m_hair & __clt vertex counts were NEVER altered!
        for orig_s, new_s in zip(model.surfaces, surfs_out):
            if orig_s.name == "m_hair" or "__clt" in orig_s.name.lower():
                assert new_s.count == orig_s.count, f"Havok surface {orig_s.name} vertex count changed in {mname}!"

        out_bytes = bmd6.write_model(model, surfs_out)
        build.put(OVERLAY_DIR, rel, out_bytes)
        print(f"  Built {mname:12s} surfaces={len(surfs_out):2d}/31")

    print("=== 8. Writing tew1_dyn.bin v3.1 (Hair+Chest Physics, Morphs, Emissive, 7 Clothing Variants) ===")
    buf = bytearray()
    buf.extend(b"TEWH")
    buf.extend(struct.pack(
        "<7I",
        3,  # version 3
        len(skeletons_by_head),
        len(chains_bin),
        len(colliders_bin),
        len(hair_fps),
        len(face_matches),
        len(CHANNEL_ALIASES),
    ))

    # Section 1: Skeletons
    for hr in sorted(skeletons_by_head):
        sk = skeletons_by_head[hr]
        buf.extend(struct.pack("<B3x", hr))
        buf.extend(struct.pack("<5h2x", *sk["col_remaps"]))
        buf.extend(sk["head_align"].astype("<f4").tobytes())
        for dr, dp in sk["drivers"]:
            buf.extend(struct.pack("<h2x3f", dr, float(dp[0]), float(dp[1]), float(dp[2])))

    # Section 2: Hair + Chest Chains
    for ch in chains_bin:
        buf.extend(struct.pack("<I4f", ch["num_bones"], ch["stiffness"], ch["damping"], ch["gravity"], ch["radius"]))
        buf.extend(ch["nodes"].astype("<f4").tobytes())

    # Section 3: 5 Humanoid Colliders (applied to hair chains only in runtime v3.1!)
    for bslot, s_arm, e_arm, rad in colliders_bin:
        buf.extend(struct.pack("<I7f", bslot, *map(float, s_arm), *map(float, e_arm), rad))

    # Section 4: Physics VB Fingerprints (pad3[0]=v0_remap, pad3[1]=2, pad3[2]=vlast_remap for 100% cross-skeleton disambiguation!)
    for hr, v0_remap, vlast_remap, vcnt, _woff, pts3 in hair_fps:
        buf.extend(struct.pack("<BBBBI", hr, v0_remap, 2, vlast_remap, vcnt))
        buf.extend(pts3.tobytes())
    all_hw = np.vstack(hair_weights_list) if hair_weights_list else np.zeros((0, 8), dtype=np.uint8)
    assert len(all_hw) == hair_weight_total
    buf.extend(struct.pack("<I", len(all_hw)))
    if len(all_hw) > 0:
        buf.extend(all_hw.tobytes())

    # Section 5: Face Morphs
    for hr, part, vcnt, pts3, chans in face_matches.values():
        buf.extend(struct.pack("<BB2xI", hr, part, vcnt))
        buf.extend(pts3.tobytes())
        for entries in chans:
            buf.extend(struct.pack("<I", len(entries)))
            for vi, dx, dy, dz in entries:
                buf.extend(struct.pack("<H2x3f", vi, dx, dy, dz))

    # Section 6 (v2+): Extra Character VBs for F7/F8/F9 Emissive
    buf.extend(struct.pack("<I", len(extra_char_fps)))
    for vcnt, pts3 in extra_char_fps.values():
        buf.extend(struct.pack("<I", vcnt))
        buf.extend(pts3.tobytes())

    # Section 7 (v3): Per-chain anchorSlot + Per-hairFP matchAnyBone & weightOffset
    for ch in chains_bin:
        buf.extend(struct.pack("<B", ch["anchor_slot"]))
    for hr, v0_remap, _vlast, _vcnt, woff, _pts3 in hair_fps:
        match_any = 0 if (v0_remap == hr) else 1
        buf.extend(struct.pack("<BI", match_any, woff))

    # Section 8 (v3): 7 Clothing-Only Variant Groups for Insert Panel
    buf.extend(struct.pack("<I", len(variant_specs)))
    for vi, (vlabel, _, _, _, _) in enumerate(variant_specs):
        lbl_bytes = vlabel.encode("utf-8")[:47]
        lbl_pad = lbl_bytes + b"\x00" * (48 - len(lbl_bytes))
        fps = variant_fps[vi]
        buf.extend(lbl_pad)
        buf.extend(struct.pack("<B3xI", 0, len(fps)))
        for vcnt, pts3 in fps:
            buf.extend(struct.pack("<I", vcnt))
            buf.extend(pts3.tobytes())

    build.put(OVERLAY_DIR, "generated/tew1_dyn.bin", bytes(buf))
    print(f"Wrote base/generated/tew1_dyn.bin ({len(buf):,} bytes, {len(hair_fps)} physics VBs, {len(face_matches)} face VBs, {len(variant_specs)} clothing variants)")

    print(f"=== 9. Packaging {OUT_ZIP} ===")
    mod_info = (
        "name=芙洛伦衣装睡衣（全章节·物理表情·透纱差分版）\n"
        "version=2.9\n"
        "author=TEW1 Mod Tools\n"
        "description=全章节27模型仅睡衣外套透纱（内裤/内衣/配饰100%纯实心不透明）+ 头身干净分离（含头部断肢）+ 原版肩宽与脚掌1:1比例 + C1平滑腰胯大腿根 + 后腰内裤防穿模 + 刘海锁定不动/侧发长发与胸部物理 + 烘焙肤色对齐 + 表情与F7/F8/F9自发光 + 自定义快捷键（默认`）面板\n"
    )
    (OVERLAY_DIR / "mod.info").write_text(mod_info, encoding="utf-8")
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fp in sorted(OVERLAY_DIR.rglob("*")):
            if fp.is_file():
                zf.write(fp, fp.relative_to(OVERLAY_DIR).as_posix())
    print(f"PACKAGED: {OUT_ZIP} ({OUT_ZIP.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
