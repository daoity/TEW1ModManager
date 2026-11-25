"""TEW1 Rigging & Retargeting Tools:
Built-in ModToolkit MMD & VRChat presets, 1-click bone renaming with aux weight merging,
MMD A-Pose to T-Pose (Shape-Key-safe LBS bake), and 1-click Align & Bind to TEW1 template rig."""

import fnmatch
import math
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty
from mathutils import Matrix, Vector
import numpy as np

# ============================================================================
# Target TEW1 Sebastian Native Bone Table (Standard Key -> TEW1 Bone Name)
# ============================================================================

TEW1_TARGET_BONES = {
    "pelvis": "pelvis",
    "spine_01": "spine_01",
    "spine_02": "spine_02",
    "spine_03": "spine_02",
    "neck": "neck_00",
    "head": "head",
    "clavicle_L": "l_shoulder",
    "upperarm_L": "l_upperarm",
    "forearm_L": "l_forearm",
    "hand_L": "l_hand",
    "clavicle_R": "r_shoulder",
    "upperarm_R": "r_upperarm",
    "forearm_R": "r_forearm",
    "hand_R": "r_hand",
    "thigh_L": "l_thigh",
    "shin_L": "l_shin",
    "foot_L": "l_foot",
    "toe_L": "l_toe",
    "thigh_R": "r_thigh",
    "shin_R": "r_shin",
    "foot_R": "r_foot",
    "toe_R": "r_toe",
    "thumb_01_L": "l_thumb_00",
    "thumb_02_L": "l_thumb_01",
    "thumb_03_L": "l_thumb_02",
    "index_01_L": "l_index_01",
    "index_02_L": "l_index_02",
    "index_03_L": "l_index_03",
    "middle_01_L": "l_middle_01",
    "middle_02_L": "l_middle_02",
    "middle_03_L": "l_middle_03",
    "ring_01_L": "l_ring_01",
    "ring_02_L": "l_ring_02",
    "ring_03_L": "l_ring_03",
    "pinky_01_L": "l_pinky_01",
    "pinky_02_L": "l_pinky_02",
    "pinky_03_L": "l_pinky_03",
    "thumb_01_R": "r_thumb_00",
    "thumb_02_R": "r_thumb_01",
    "thumb_03_R": "r_thumb_02",
    "index_01_R": "r_index_01",
    "index_02_R": "r_index_02",
    "index_03_R": "r_index_03",
    "middle_01_R": "r_middle_01",
    "middle_02_R": "r_middle_02",
    "middle_03_R": "r_middle_03",
    "ring_01_R": "r_ring_01",
    "ring_02_R": "r_ring_02",
    "ring_03_R": "r_ring_03",
    "pinky_01_R": "r_pinky_01",
    "pinky_02_R": "r_pinky_02",
    "pinky_03_R": "r_pinky_03",
    "upperarm_twist_01_L": "l_upperarm",
    "upperarm_twist_02_L": "l_upperarm",
    "upperarm_twist_03_L": "l_upperarm",
    "forearm_twist_01_L": "l_forearm",
    "forearm_twist_02_L": "l_forearm",
    "forearm_twist_03_L": "l_forearm",
    "upperarm_twist_01_R": "r_upperarm",
    "upperarm_twist_02_R": "r_upperarm",
    "upperarm_twist_03_R": "r_upperarm",
    "forearm_twist_01_R": "r_forearm",
    "forearm_twist_02_R": "r_forearm",
    "forearm_twist_03_R": "r_forearm",
}

CORE_DETECT_KEYS = (
    "pelvis", "spine_01", "spine_02", "neck", "head",
    "upperarm_L", "forearm_L", "hand_L", "upperarm_R", "forearm_R", "hand_R",
    "thigh_L", "shin_L", "foot_L", "thigh_R", "shin_R", "foot_R",
)

# ============================================================================
# Built-in ModToolkit MMD & VRChat Presets
# ============================================================================

MMD_EXCLUDE = (
    "センター", "センター2", "グルーブ", "グルーブ2", "全ての親", "操作中心", "センター先",
    "足IK親.L", "足ＩＫ.L", "つま先ＩＫ先.L", "つま先ＩＫ.L",
    "足IK親.R", "足ＩＫ.R", "つま先ＩＫ先.R", "つま先ＩＫ.R",
    "*操作", "*操作.L", "*操作.R", "*調整", "*調整.L", "*調整.R",
    "*親", "*親.L", "*親.R", "*IK", "*IK.L", "*IK.R", "*ＩＫ", "*ＩＫ.L", "*ＩＫ.R",
    "*IK先", "*IK先.L", "*IK先.R", "*ＩＫ先", "*ＩＫ先.L", "*ＩＫ先.R",
)

MMD_PRESET = {
    "pelvis": (["Hips", "下半身", "骨盆"], ["下半身先", "スカート元"]),
    "spine_01": (["Spine", "上半身"], ["腰", "上半身1"]),
    "spine_02": (["Chest", "上半身2"], ["おっぱい調整", "胸上.L", "胸下.L", "胸下先.L", "胸上.R", "胸下.R", "胸下先.R"]),
    "spine_03": (["上半身3"], []),
    "neck": (["Neck", "首", "脖子"], []),
    "head": (["Head", "頭", "头"], ["頭先", "目.L", "_dummy_目.L", "_shadow_目.L", "目先.L", "目.R", "_dummy_目.R", "_shadow_目.R", "目先.R", "両目", "両目先", "齿上", "齿下"]),
    "clavicle_L": (["Left shoulder", "肩.L", "左肩"], ["肩P.L", "_dummy_肩C.L", "_shadow_肩C.L", "肩C.L"]),
    "upperarm_L": (["Left arm", "腕.L", "左腕"], ["腕回転.L"]),
    "forearm_L": (["Left elbow", "ひじ.L", "左ひじ"], ["zHandTwist_L", "ひじ回転.L", "手捩回転１.L", "手捩回転２.L", "手捩回転1.L", "手捩回転2.L"]),
    "hand_L": (["Left wrist", "手首.L", "左手首"], ["手先.L", "ダミー.L", "手首回転.L"]),
    "clavicle_R": (["Right shoulder", "肩.R", "右肩"], ["肩P.R", "_dummy_肩C.R", "_shadow_肩C.R", "肩C.R"]),
    "upperarm_R": (["Right arm", "腕.R", "右腕"], ["腕回転.R"]),
    "forearm_R": (["Right elbow", "ひじ.R", "右ひじ"], ["zHandTwist_R", "ひじ回転.R", "手捩回転１.R", "手捩回転２.R", "手捩回転1.R", "手捩回転2.R"]),
    "hand_R": (["Right wrist", "手首.R", "右手首"], ["手先.R", "ダミー.R", "手首回転.R"]),
    "thigh_L": (["Left leg", "足D.L", "足.L", "左足"], ["腰キャンセル.L", "_shadow_腰キャンセル.L", "_dummy_腰キャンセル.L", "腰キャンセル.001.L", "_dummy_腰キャンセル.001.L", "_shadow_腰キャンセル.001.L", "_dummy_足D.L", "_shadow_足D.L"]),
    "shin_L": (["Left knee", "ひざD.L", "ひざ.L", "左ひざ"], ["_dummy_ひざD.L", "_shadow_ひざD.L", "ひざ回転.L"]),
    "foot_L": (["Left ankle", "足首D.L", "足首.L", "左足首"], ["_dummy_足首D.L", "_shadow_足首D.L", "足回転.L"]),
    "toe_L": (["Left toe", "足先EX.L", "つま先.L", "左足先EX"], []),
    "thigh_R": (["Right leg", "足D.R", "足.R", "右足"], ["腰キャンセル.R", "_shadow_腰キャンセル.R", "_dummy_腰キャンセル.R", "腰キャンセル.001.R", "_dummy_腰キャンセル.001.R", "_shadow_腰キャンセル.001.R", "_dummy_足D.R", "_shadow_足D.R"]),
    "shin_R": (["Right knee", "ひざD.R", "ひざ.R", "右ひざ"], ["_dummy_ひざD.R", "_shadow_ひざD.R", "ひざ回転.R"]),
    "foot_R": (["Right ankle", "足首D.R", "足首.R", "右足首"], ["_dummy_足首D.R", "_shadow_足首D.R", "足回転.R"]),
    "toe_R": (["Right toe", "足先EX.R", "つま先.R", "右足先EX"], []),
    "thumb_01_L": (["Thumb0_L", "親指０.L", "左親指０"], []),
    "thumb_02_L": (["Thumb1_L", "親指１.L", "左親指１"], []),
    "thumb_03_L": (["Thumb2_L", "親指２.L", "左親指２"], ["親指先.L"]),
    "index_01_L": (["IndexFinger1_L", "人指１.L", "左人指１"], []),
    "index_02_L": (["IndexFinger2_L", "人指２.L", "左人指２"], []),
    "index_03_L": (["IndexFinger3_L", "人指３.L", "左人指３"], ["人指先.L", "人差指先.L"]),
    "middle_01_L": (["MiddleFinger1_L", "中指１.L", "左中指１"], []),
    "middle_02_L": (["MiddleFinger2_L", "中指２.L", "左中指２"], []),
    "middle_03_L": (["MiddleFinger3_L", "中指３.L", "左中指３"], ["中指先.L"]),
    "ring_01_L": (["RingFinger1_L", "薬指１.L", "左薬指１"], []),
    "ring_02_L": (["RingFinger2_L", "薬指２.L", "左薬指２"], []),
    "ring_03_L": (["RingFinger3_L", "薬指３.L", "左薬指３"], ["薬指先.L"]),
    "pinky_01_L": (["LittleFinger1_L", "小指１.L", "左小指１"], []),
    "pinky_02_L": (["LittleFinger2_L", "小指２.L", "左小指２"], []),
    "pinky_03_L": (["LittleFinger3_L", "小指３.L", "左小指３"], ["小指先.L", "子指先.L"]),
    "thumb_01_R": (["Thumb0_R", "親指０.R", "右親指０"], []),
    "thumb_02_R": (["Thumb1_R", "親指１.R", "右親指１"], []),
    "thumb_03_R": (["Thumb2_R", "親指２.R", "右親指２"], ["親指先.R"]),
    "index_01_R": (["IndexFinger1_R", "人指１.R", "右人指１"], []),
    "index_02_R": (["IndexFinger2_R", "人指２.R", "右人指２"], []),
    "index_03_R": (["IndexFinger3_R", "人指３.R", "右人指３"], ["人指先.R", "人差指先.R"]),
    "middle_01_R": (["MiddleFinger1_R", "中指１.R", "右中指１"], []),
    "middle_02_R": (["MiddleFinger2_R", "中指２.R", "右中指２"], []),
    "middle_03_R": (["MiddleFinger3_R", "中指３.R", "右中指３"], ["中指先.R"]),
    "ring_01_R": (["RingFinger1_R", "薬指１.R", "右薬指１"], []),
    "ring_02_R": (["RingFinger2_R", "薬指２.R", "右薬指２"], []),
    "ring_03_R": (["RingFinger3_R", "薬指３.R", "右薬指３"], ["薬指先.R"]),
    "pinky_01_R": (["LittleFinger1_R", "小指１.R", "右小指１"], []),
    "pinky_02_R": (["LittleFinger2_R", "小指２.R", "右小指２"], []),
    "pinky_03_R": (["LittleFinger3_R", "小指３.R", "右小指３"], ["小指先.R", "子指先.R"]),
    "upperarm_twist_01_L": (["腕捩1.L", "左腕捩"], ["腕捩.L", "_dummy_腕捩1.L", "_shadow_腕捩1.L"]),
    "upperarm_twist_02_L": (["腕捩2.L"], ["_dummy_腕捩2.L", "_shadow_腕捩2.L"]),
    "upperarm_twist_03_L": (["腕捩3.L"], ["_dummy_腕捩3.L", "_shadow_腕捩3.L"]),
    "forearm_twist_01_L": (["手捩1.L", "左手捩"], ["手捩.L", "_dummy_手捩1.L", "_shadow_手捩1.L"]),
    "forearm_twist_02_L": (["手捩2.L"], ["_dummy_手捩2.L", "_shadow_手捩2.L"]),
    "forearm_twist_03_L": (["手捩3.L"], ["_dummy_手捩3.L", "_shadow_手捩3.L"]),
    "upperarm_twist_01_R": (["腕捩1.R", "右腕捩"], ["腕捩.R", "_dummy_腕捩1.R", "_shadow_腕捩1.R"]),
    "upperarm_twist_02_R": (["腕捩2.R"], ["_dummy_腕捩2.R", "_shadow_腕捩2.R"]),
    "upperarm_twist_03_R": (["腕捩3.R"], ["_dummy_腕捩3.R", "_shadow_腕捩3.R"]),
    "forearm_twist_01_R": (["手捩1.R", "右手捩"], ["手捩.R", "_dummy_手捩1.R", "_shadow_手捩1.R"]),
    "forearm_twist_02_R": (["手捩2.R"], ["_dummy_手捩2.R", "_shadow_手捩2.R"]),
    "forearm_twist_03_R": (["手捩3.R"], ["_dummy_手捩3.R", "_shadow_手捩3.R"]),
}

VRCHAT_PRESET = {
    "pelvis": (["Hips", "Pelvis"], ["Skirt_root"]),
    "spine_01": (["Spine"], []),
    "spine_02": (["Chest", "Spine1"], []),
    "spine_03": (["UpperChest", "Spine2"], []),
    "neck": (["Neck"], []),
    "head": (["Head"], ["Head_Adj", "Jaw", "Hair_root", "LeftEye", "RightEye", "LeftEye_end", "RightEye_end", "Eye_L", "Eye_R", "Eye_L_end", "Eye_R_end", "L_Eye", "R_Eye"]),
    "clavicle_L": (["Shoulder_L", "Left shoulder", "LeftShoulder"], []),
    "upperarm_L": (["UpperArm_L", "Left arm", "LeftUpperArm", "LeftArm"], ["Upper_arm_support_L", "XC_ArmTwist_L", "Elbow_support.L"]),
    "forearm_L": (["LowerArm_L", "Left elbow", "LeftLowerArm", "LeftForeArm"], ["Lower_arm_support.L", "Lower_arm_support.L_end", "Lower_arm_support.L.001", "Lower_arm_support.L.002", "XC_WristTwist_L", "LowerArmAssist_L", "Wrist_support.L"]),
    "hand_L": (["Hand_L", "Left wrist", "Left Hand", "LeftHand"], ["Hand_twist_L"]),
    "clavicle_R": (["Shoulder_R", "Right shoulder", "RightShoulder"], []),
    "upperarm_R": (["UpperArm_R", "Right arm", "RightUpperArm", "RightArm"], ["Upper_arm_support_R", "XC_ArmTwist_R", "Elbow_support.R"]),
    "forearm_R": (["LowerArm_R", "Right elbow", "RightLowerArm", "RightForeArm"], ["Lower_arm_support.R", "Lower_arm_support.R_end", "Lower_arm_support.R.001", "Lower_arm_support.R.002", "XC_WristTwist_R", "LowerArmAssist_R", "Wrist_support.R"]),
    "hand_R": (["Hand_R", "Right wrist", "Right Hand", "RightHand"], ["Hand_twist_R"]),
    "thigh_L": (["UpperLeg_L", "Left leg", "LeftUpperLeg", "LeftUpLeg"], ["KneeSupport_L", "KneeSupport_L_end"]),
    "shin_L": (["LowerLeg_L", "Left knee", "LeftLowerLeg", "LeftLeg"], ["LowerLeg_L_knee", "LowerLegAssist_L"]),
    "foot_L": (["Foot_L", "Left ankle", "LeftFoot"], []),
    "toe_L": (["Toe_L", "Left toe", "Toe_Base_L", "LeftToes", "Toes.L", "LeftToeBase"], ["Toe.L_end", "PinkyToe_L", "RingToe_L", "MiddleToe_L", "IndexToe_L", "Hallux_L"]),
    "thigh_R": (["UpperLeg_R", "Right leg", "RightUpperLeg", "RightUpLeg"], ["KneeSupport_R", "KneeSupport_R_end"]),
    "shin_R": (["LowerLeg_R", "Right knee", "RightLowerLeg", "RightLeg"], ["LowerLeg_R_knee", "LowerLegAssist_R"]),
    "foot_R": (["Foot_R", "Right ankle", "RightFoot"], []),
    "toe_R": (["Toe_R", "Right toe", "Toe_Base_R", "RightToes", "Toes.R", "RightToeBase"], ["Toe.R_end", "PinkyToe_R", "RingToe_R", "MiddleToe_R", "IndexToe_R", "Hallux_R"]),
    "thumb_01_L": (["ThumbProximal_L", "Thumb0_L", "LeftThumbProximal", "LeftHandThumb1"], []),
    "thumb_02_L": (["ThumbIntermediate_L", "Thumb1_L", "LeftThumbIntermediate", "LeftHandThumb2"], []),
    "thumb_03_L": (["ThumbDistal_L", "Thumb2_L", "LeftThumbDistal", "LeftHandThumb3"], ["Thumb Distal.L_end"]),
    "index_01_L": (["IndexProximal_L", "Index1_L", "LeftIndexProximal", "LeftHandIndex1"], []),
    "index_02_L": (["IndexIntermediate_L", "Index2_L", "LeftIndexIntermediate", "LeftHandIndex2"], []),
    "index_03_L": (["IndexDistal_L", "Index3_L", "LeftIndexDistal", "LeftHandIndex3"], ["Index Distal.L_end"]),
    "middle_01_L": (["MiddleProximal_L", "Middle1_L", "LeftMiddleProximal", "LeftHandMiddle1"], []),
    "middle_02_L": (["MiddleIntermediate_L", "Middle2_L", "LeftMiddleIntermediate", "LeftHandMiddle2"], []),
    "middle_03_L": (["MiddleDistal_L", "Middle3_L", "LeftMiddleDistal", "LeftHandMiddle3"], ["Middle Distal.L_end"]),
    "ring_01_L": (["RingProximal_L", "Ring1_L", "LeftRingProximal", "LeftHandRing1"], []),
    "ring_02_L": (["RingIntermediate_L", "Ring2_L", "LeftRingIntermediate", "LeftHandRing2"], []),
    "ring_03_L": (["RingDistal_L", "Ring3_L", "LeftRingDistal", "LeftHandRing3"], ["Ring Distal.L_end"]),
    "pinky_01_L": (["LittleProximal_L", "Little1_L", "LeftLittleProximal", "LeftHandPinky1"], []),
    "pinky_02_L": (["LittleIntermediate_L", "Little2_L", "LeftLittleIntermediate", "LeftHandPinky2"], []),
    "pinky_03_L": (["LittleDistal_L", "Little3_L", "LeftLittleDistal", "LeftHandPinky3"], ["Little Distal.L_end"]),
    "thumb_01_R": (["ThumbProximal_R", "Thumb0_R", "RightThumbProximal", "RightHandThumb1"], []),
    "thumb_02_R": (["ThumbIntermediate_R", "Thumb1_R", "RightThumbIntermediate", "RightHandThumb2"], []),
    "thumb_03_R": (["ThumbDistal_R", "Thumb2_R", "RightThumbDistal", "RightHandThumb3"], ["Thumb Distal.R_end"]),
    "index_01_R": (["IndexProximal_R", "Index1_R", "RightIndexProximal", "RightHandIndex1"], []),
    "index_02_R": (["IndexIntermediate_R", "Index2_R", "RightIndexIntermediate", "RightHandIndex2"], []),
    "index_03_R": (["IndexDistal_R", "Index3_R", "RightIndexDistal", "RightHandIndex3"], ["Index Distal.R_end"]),
    "middle_01_R": (["MiddleProximal_R", "Middle1_R", "RightMiddleProximal", "RightHandMiddle1"], []),
    "middle_02_R": (["MiddleIntermediate_R", "Middle2_R", "RightMiddleIntermediate", "RightHandMiddle2"], []),
    "middle_03_R": (["MiddleDistal_R", "Middle3_R", "RightMiddleDistal", "RightHandMiddle3"], ["Middle Distal.R_end"]),
    "ring_01_R": (["RingProximal_R", "Ring1_R", "RightRingProximal", "RightHandRing1"], []),
    "ring_02_R": (["RingIntermediate_R", "Ring2_R", "RightRingIntermediate", "RightHandRing2"], []),
    "ring_03_R": (["RingDistal_R", "Ring3_R", "RightRingDistal", "RightHandRing3"], ["Ring Distal.R_end"]),
    "pinky_01_R": (["LittleProximal_R", "Little1_R", "RightLittleProximal", "RightHandPinky1"], []),
    "pinky_02_R": (["LittleIntermediate_R", "Little2_R", "RightLittleIntermediate", "RightHandPinky2"], []),
    "pinky_03_R": (["LittleDistal_R", "Little3_R", "RightLittleDistal", "RightHandPinky3"], ["Little Distal.R_end"]),
    "upperarm_twist_01_L": (["UpperArm_twist_L", "UpperArm_L_twist"], []),
    "forearm_twist_01_L": (["LowerArm_twist_L", "LowerArm_L_twist"], []),
    "upperarm_twist_01_R": (["UpperArm_twist_R", "UpperArm_R_twist"], []),
    "forearm_twist_01_R": (["LowerArm_twist_R", "LowerArm_R_twist"], []),
}

PRESET_TABLES = {
    "MMD": (MMD_PRESET, MMD_EXCLUDE),
    "VRCHAT": (VRCHAT_PRESET, ()),
}


def _norm_key(name):
    return re.sub(r"[\s._-]+", "", name).lower()


def _is_excluded(name, patterns):
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def match_preset_bones(arm_obj, preset_id):
    """Return (std_to_main, aux_to_target_std) matched against arm_obj's bones."""
    table, excludes = PRESET_TABLES[preset_id]
    bone_names = [b.name for b in arm_obj.data.bones if not _is_excluded(b.name, excludes)]
    exact = {n: n for n in bone_names}
    by_norm = {}
    for n in bone_names:
        by_norm.setdefault(_norm_key(n), n)

    def find_one(candidates):
        for cand in candidates:
            if cand in exact:
                return exact[cand]
        for cand in candidates:
            nk = _norm_key(cand)
            if nk in by_norm:
                return by_norm[nk]
        return None

    std_to_main = {}
    aux_to_std = {}
    used = set()
    for std_key, (mains, auxs) in table.items():
        m = find_one(mains)
        if m and m not in used:
            std_to_main[std_key] = m
            used.add(m)
        for cand in list(mains) + list(auxs):
            found = exact.get(cand) or by_norm.get(_norm_key(cand))
            if found and found != m and found not in used:
                aux_to_std[found] = std_key
                used.add(found)
    return std_to_main, aux_to_std


def detect_source_preset(arm_obj):
    """Auto-detect MMD or VRChat preset with higher core bone coverage."""
    best_id, best_score = "MMD", -1
    for pid in ("MMD", "VRCHAT"):
        std_to_main, _ = match_preset_bones(arm_obj, pid)
        score = sum(1 for k in CORE_DETECT_KEYS if k in std_to_main)
        if score > best_score:
            best_id, best_score = pid, score
    return best_id, best_score


def attached_meshes(arm_obj):
    out = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        found = obj.find_armature()
        if found is arm_obj or (found is None and obj.parent is arm_obj):
            out.append(obj)
    return out


def bake_pose_preserving_shapekeys(arm_obj):
    """Bake arm_obj's current Pose into mesh vertices AND all Shape Keys via NumPy LBS, then apply Pose as Rest Pose."""
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.find_armature() is arm_obj]
    pbones = arm_obj.pose.bones
    for obj in meshes:
        mesh = obj.data
        by_group = {}
        for vg in obj.vertex_groups:
            pb = pbones.get(vg.name)
            if pb is None or not pb.bone.use_deform:
                continue
            by_group[vg.index] = np.array(pb.matrix @ pb.bone.matrix_local.inverted_safe(), dtype=np.float64)
        if not by_group:
            continue
        n = len(mesh.vertices)
        acc = np.zeros((n, 4, 4), dtype=np.float64)
        total = np.zeros(n, dtype=np.float64)
        slot_of = {gi: k for k, gi in enumerate(by_group)}
        mats = np.array([by_group[gi] for gi in by_group], dtype=np.float64)
        vi, si, wt = [], [], []
        for i, v in enumerate(mesh.vertices):
            for g in v.groups:
                k = slot_of.get(g.group)
                if k is None or g.weight <= 0.0:
                    continue
                vi.append(i)
                si.append(k)
                wt.append(g.weight)
        if vi:
            vi_arr = np.array(vi, dtype=np.int64)
            wt_arr = np.array(wt, dtype=np.float64)
            np.add.at(acc, vi_arr, mats[np.array(si, dtype=np.int64)] * wt_arr[:, None, None])
            np.add.at(total, vi_arr, wt_arr)
        weighted = total > 1e-12
        if not weighted.any():
            continue
        acc[weighted] /= total[weighted, None, None]
        acc[~weighted] = np.eye(4)

        to_arm = np.array(arm_obj.matrix_world.inverted_safe() @ obj.matrix_world, dtype=np.float64)
        from_arm = np.linalg.inv(to_arm)
        skin = from_arm @ acc @ to_arm

        def apply_to_coords(co_flat):
            pts = co_flat.reshape(-1, 3).astype(np.float64)
            ones = np.ones((len(pts), 1), dtype=np.float64)
            hom = np.hstack((pts, ones))
            out = np.einsum("nij,nj->ni", skin, hom)[:, :3]
            return out.astype(np.float32).ravel()

        co = np.empty(n * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        mesh.vertices.foreach_set("co", apply_to_coords(co))

        if mesh.shape_keys and mesh.shape_keys.key_blocks:
            for kb in mesh.shape_keys.key_blocks:
                kco = np.empty(n * 3, dtype=np.float32)
                kb.data.foreach_get("co", kco)
                kb.data.foreach_set("co", apply_to_coords(kco))
        mesh.update()

    # Apply current pose as Rest Pose on the armature
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = bpy.context.mode
    if prev_mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = prev_active
    return len(meshes)


def _merge_vertex_group(obj, src_name, dst_name):
    src_vg = obj.vertex_groups.get(src_name)
    if src_vg is None or src_name == dst_name:
        return False
    dst_vg = obj.vertex_groups.get(dst_name) or obj.vertex_groups.new(name=dst_name)
    src_idx = src_vg.index
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == src_idx and g.weight > 1e-6:
                dst_vg.add([v.index], g.weight, "ADD")
                break
    obj.vertex_groups.remove(src_vg)
    return True


def rename_and_merge_to_tew1(arm_obj, preset_id, merge_aux=True):
    """Rename source rig bones & attached mesh vertex groups from MMD/VRChat to TEW1 Sebastian names."""
    std_to_main, aux_to_std = match_preset_bones(arm_obj, preset_id)
    meshes = attached_meshes(arm_obj)

    # Build safe 2-pass rename plan for primary bones first (avoids vertex group collision warnings!)
    rename_map = {}
    secondary_merges = []
    for std_key, src_name in std_to_main.items():
        tew_name = TEW1_TARGET_BONES.get(std_key)
        if not tew_name or src_name == tew_name:
            continue
        if tew_name in rename_map.values() or (tew_name in arm_obj.data.bones and tew_name not in std_to_main.values()):
            secondary_merges.append((src_name, tew_name))
            continue
        rename_map[src_name] = tew_name

    # Pass 1: temporary unique names
    tmp_map = {}
    for idx, (src_name, dst_name) in enumerate(rename_map.items()):
        tmp = f"__tew1_tmp_{idx}__"
        if src_name in arm_obj.data.bones:
            arm_obj.data.bones[src_name].name = tmp
        for obj in meshes:
            vg = obj.vertex_groups.get(src_name)
            if vg:
                vg.name = tmp
        tmp_map[tmp] = dst_name

    # Pass 2: final TEW1 native names
    for tmp, dst_name in tmp_map.items():
        if tmp in arm_obj.data.bones:
            arm_obj.data.bones[tmp].name = dst_name
        for obj in meshes:
            vg = obj.vertex_groups.get(tmp)
            if vg:
                vg.name = dst_name

    # Now merge secondary / auxiliary / twist bone weights cleanly into their final TEW1 main bone
    merged_aux = 0
    for src_name, tew_name in secondary_merges:
        for obj in meshes:
            if _merge_vertex_group(obj, src_name, tew_name):
                merged_aux += 1

    if merge_aux:
        for aux_bone, std_key in aux_to_std.items():
            tew_name = TEW1_TARGET_BONES.get(std_key)
            if not tew_name:
                continue
            for obj in meshes:
                if _merge_vertex_group(obj, aux_bone, tew_name):
                    merged_aux += 1

    return len(rename_map), merged_aux, len(meshes)


def _world_bone_head(arm_obj, bname):
    b = arm_obj.data.bones.get(bname)
    return (arm_obj.matrix_world @ b.head_local) if b else None


def _mesh_lowest_z_world(arm_obj, meshes=None):
    """Find the lowest world-space vertex Z across visible non-hidden meshes bound to arm_obj."""
    if meshes is None:
        meshes = attached_meshes(arm_obj)
    min_z = None
    for obj in meshes:
        if obj.get("tew1_zero_hide") or obj.hide_viewport or not obj.data or len(obj.data.vertices) == 0:
            continue
        n = len(obj.data.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        obj.data.vertices.foreach_get("co", co)
        pts = co.reshape(-1, 3).astype(np.float64)
        m = np.array(obj.matrix_world, dtype=np.float64)
        z_vals = pts @ m[2, :3] + m[2, 3]
        z_min = float(z_vals.min())
        if min_z is None or z_min < min_z:
            min_z = z_min
    return min_z


def _align_armature_transform(src_arm, tgt_arm, std_to_main, preserve_proportions=True):
    """Rotate (Z yaw), scale, and translate src_arm to match tgt_arm's facing, height and foot ground.
    When preserve_proportions=True:
    - Uses true sole-bottom Z (instead of Sebastian's tall combat-boot ankle Z) so bare feet keep 1:1 proportions and sit cleanly at Z=0.10.
    - Aligns global X to thigh-midpoint X (prevents anterior-posterior hip/waist kink).
    - Never widens shoulders or stretches feet.
    """
    def get_lr(arm, l_name, r_name):
        hl = _world_bone_head(arm, l_name)
        hr = _world_bone_head(arm, r_name)
        if hl is None or hr is None:
            return None
        v = Vector((hl.x - hr.x, hl.y - hr.y, 0.0))
        return v.normalized() if v.length > 1e-6 else None

    src_l = std_to_main.get("upperarm_L")
    src_r = std_to_main.get("upperarm_R")
    v_src = get_lr(src_arm, src_l, src_r)
    v_tgt = get_lr(tgt_arm, "l_upperarm", "r_upperarm")

    if v_src is not None and v_tgt is not None:
        ang = v_src.angle(v_tgt)
        cross_z = v_src.x * v_tgt.y - v_src.y * v_tgt.x
        if cross_z < 0:
            ang = -ang
        rot_z = Matrix.Rotation(ang, 4, "Z")
        src_arm.matrix_world = rot_z @ src_arm.matrix_world
        bpy.context.view_layer.update()

    src_meshes = attached_meshes(src_arm)
    src_head = _world_bone_head(src_arm, std_to_main.get("head", ""))
    tgt_head = _world_bone_head(tgt_arm, "head")
    src_foot = _world_bone_head(src_arm, std_to_main.get("foot_L", "")) or _world_bone_head(src_arm, std_to_main.get("foot_R", ""))
    tgt_foot = _world_bone_head(tgt_arm, "l_foot") or _world_bone_head(tgt_arm, "r_foot")

    # Determine target ground Z in world space (TEW1 Sebastian soles sit at local Z = 0.10)
    tgt_ground_z = (tgt_arm.matrix_world @ Vector((0.0, 0.0, 0.10))).z
    src_sole_z = _mesh_lowest_z_world(src_arm, src_meshes) if preserve_proportions else None

    scale = 1.0
    if preserve_proportions and src_head and tgt_head and src_sole_z is not None:
        dh_s = abs(src_head.z - src_sole_z)
        dh_t = abs(tgt_head.z - tgt_ground_z)
        if dh_s > 1e-4 and dh_t > 1e-4:
            scale = dh_t / dh_s
    elif src_head and tgt_head and src_foot and tgt_foot:
        dh_s = abs(src_head.z - src_foot.z)
        dh_t = abs(tgt_head.z - tgt_foot.z)
        if dh_s > 1e-4 and dh_t > 1e-4:
            scale = dh_t / dh_s
    elif src_head and tgt_head:
        src_pel = _world_bone_head(src_arm, std_to_main.get("pelvis", ""))
        tgt_pel = _world_bone_head(tgt_arm, "pelvis")
        if src_pel and tgt_pel and abs(src_head.z - src_pel.z) > 1e-4:
            scale = abs(tgt_head.z - tgt_pel.z) / abs(src_head.z - src_pel.z)

    if 0.001 < scale < 1000.0 and abs(scale - 1.0) > 1e-4:
        src_arm.scale = (src_arm.scale.x * scale, src_arm.scale.y * scale, src_arm.scale.z * scale)
        bpy.context.view_layer.update()

    # Align X/Y using thigh-midpoint (eliminates pelvis/thigh anterior-posterior kink), fallback to pelvis
    src_tl = _world_bone_head(src_arm, std_to_main.get("thigh_L", ""))
    src_tr = _world_bone_head(src_arm, std_to_main.get("thigh_R", ""))
    tgt_tl = _world_bone_head(tgt_arm, "l_thigh")
    tgt_tr = _world_bone_head(tgt_arm, "r_thigh")
    src_pel = _world_bone_head(src_arm, std_to_main.get("pelvis", ""))
    tgt_pel = _world_bone_head(tgt_arm, "pelvis")

    if preserve_proportions and src_tl and src_tr and tgt_tl and tgt_tr:
        src_hip = 0.5 * (src_tl + src_tr)
        tgt_hip = 0.5 * (tgt_tl + tgt_tr)
        dx = tgt_hip.x - src_hip.x
        dy = tgt_hip.y - src_hip.y
    else:
        dx = (tgt_pel.x - src_pel.x) if (src_pel and tgt_pel) else 0.0
        dy = (tgt_pel.y - src_pel.y) if (src_pel and tgt_pel) else 0.0

    # Align Z from true bare-foot sole to TEW1 ground Z=0.10 (1:1 bare-foot height, zero boot stretch)
    src_sole_z = _mesh_lowest_z_world(src_arm, src_meshes) if preserve_proportions else None
    if preserve_proportions and src_sole_z is not None:
        dz = tgt_ground_z - src_sole_z
    else:
        src_foot = _world_bone_head(src_arm, std_to_main.get("foot_L", "")) or _world_bone_head(src_arm, std_to_main.get("foot_R", ""))
        tgt_foot = _world_bone_head(tgt_arm, "l_foot") or _world_bone_head(tgt_arm, "r_foot")
        dz = (tgt_foot.z - src_foot.z) if (src_foot and tgt_foot) else ((tgt_pel.z - src_pel.z) if (src_pel and tgt_pel) else 0.0)

    src_arm.location = Vector((src_arm.location.x + dx, src_arm.location.y + dy, src_arm.location.z + dz))
    bpy.context.view_layer.update()
    return scale


def apply_medial_shoulder_weight_fix(tgt_arm, meshes, src_upper_y_override=None):
    """Prevent 'double-door fridge' (双开门) raised shoulder caps in arms-down idle pose.
    Sebastian's l_upperarm/r_upperarm pivots sit at |Y| ~= 10.25 (wide male shoulders), while female/anime
    characters have shoulders around |Y| ~= 5.8..6.8. Any inner shoulder-cap vertex medial to Sebastian's
    pivot that is weighted to upperarm swings UPWARD (+Z) when arms lower ~42 deg in idle pose.
    Smoothly transferring medial upperarm weights (|Y| < tgt_upper_y + margin) to l_shoulder/r_shoulder
    preserves 100% original narrow shoulder proportions in-game!
    """
    if tgt_arm is None or tgt_arm.type != "ARMATURE":
        return 0, 0
    b_lu = tgt_arm.data.bones.get("l_upperarm")
    b_ru = tgt_arm.data.bones.get("r_upperarm")
    if b_lu is None and b_ru is None:
        return 0, 0

    tgt_upper_y = abs(b_lu.head_local.y) if b_lu else abs(b_ru.head_local.y)
    if tgt_upper_y < 1e-3:
        return 0, 0

    margin = 0.35 * (tgt_upper_y / 10.25)
    cutoff = tgt_upper_y + margin
    if src_upper_y_override is not None and 0.25 * tgt_upper_y <= src_upper_y_override <= 0.90 * tgt_upper_y:
        inner_y = float(src_upper_y_override)
    else:
        inner_y = tgt_upper_y * 0.58

    span = max(0.5, cutoff - inner_y)
    arm_inv = tgt_arm.matrix_world.inverted_safe()
    fixed_verts = 0
    fixed_meshes = 0

    for obj in meshes:
        if obj.type != "MESH" or obj.get("tew1_zero_hide") or len(obj.data.vertices) == 0:
            continue
        vg_lu = obj.vertex_groups.get("l_upperarm")
        vg_ru = obj.vertex_groups.get("r_upperarm")
        if vg_lu is None and vg_ru is None:
            continue

        to_arm = np.array(arm_inv @ obj.matrix_world, dtype=np.float64)
        n = len(obj.data.vertices)
        co = np.empty(n * 3, dtype=np.float32)
        obj.data.vertices.foreach_get("co", co)
        pts = co.reshape(-1, 3).astype(np.float64)
        arm_y = pts @ to_arm[1, :3] + to_arm[1, 3]

        mesh_touched = False
        for side, vg_u in (("l", vg_lu), ("r", vg_ru)):
            if vg_u is None:
                continue
            u_idx = vg_u.index
            sh_name = f"{side}_shoulder"
            vg_sh = obj.vertex_groups.get(sh_name)
            updates = []
            for v in obj.data.vertices:
                abs_y = abs(float(arm_y[v.index]))
                if abs_y >= cutoff:
                    continue
                # Verify vertex is on the matching side (avoid touching center-line noise beyond 0.5)
                if side == "l" and arm_y[v.index] < -0.5:
                    continue
                if side == "r" and arm_y[v.index] > 0.5:
                    continue
                w_u = 0.0
                for g in v.groups:
                    if g.group == u_idx:
                        w_u = float(g.weight)
                        break
                if w_u <= 1e-4:
                    continue
                t = max(0.0, min(1.0, (abs_y - inner_y) / span))
                keep_arm = t * t * (3.0 - 2.0 * t)
                transfer = w_u * (1.0 - keep_arm)
                if transfer <= 1e-4:
                    continue
                updates.append((v.index, w_u - transfer, transfer))

            if updates:
                if vg_sh is None:
                    vg_sh = obj.vertex_groups.new(name=sh_name)
                for vi, new_u, add_sh in updates:
                    if new_u <= 1e-4:
                        vg_u.remove([vi])
                    else:
                        vg_u.add([vi], new_u, "REPLACE")
                    vg_sh.add([vi], add_sh, "ADD")
                fixed_verts += len(updates)
                mesh_touched = True

        if mesh_touched:
            fixed_meshes += 1

    return fixed_verts, fixed_meshes


def fix_innerwear_clipping(skin_obj, inner_objs, tgt_arm=None, back_offset=0.22, front_offset=0.12, detect_dist=0.35):
    """Push coplanar/clipping tight innerwear (panties/bra) slightly outward from skin_obj along skin normals
    and sync exact nearest-skin vertex weights so innerwear moves 100% in lockstep with pelvis/butt/thighs."""
    from mathutils.kdtree import KDTree

    if skin_obj is None or skin_obj.type != "MESH" or len(skin_obj.data.vertices) == 0:
        return 0, 0

    ref_inv = tgt_arm.matrix_world.inverted_safe() if (tgt_arm and tgt_arm.type == "ARMATURE") else Matrix.Identity(4)
    skin_to_ref = np.array(ref_inv @ skin_obj.matrix_world, dtype=np.float64)
    skin_rot = skin_to_ref[:3, :3]
    skin_n_mat = np.linalg.inv(skin_rot).T

    sn = len(skin_obj.data.vertices)
    sco = np.empty(sn * 3, dtype=np.float32)
    skin_obj.data.vertices.foreach_get("co", sco)
    s_pts = sco.reshape(-1, 3).astype(np.float64) @ skin_rot.T + skin_to_ref[:3, 3]

    snorm = np.empty(sn * 3, dtype=np.float32)
    skin_obj.data.vertices.foreach_get("normal", snorm)
    s_nrm = snorm.reshape(-1, 3).astype(np.float64) @ skin_n_mat.T
    s_nlen = np.linalg.norm(s_nrm, axis=1, keepdims=True)
    s_nrm = s_nrm / np.maximum(s_nlen, 1e-8)

    kd = KDTree(sn)
    for i in range(sn):
        kd.insert((float(s_pts[i, 0]), float(s_pts[i, 1]), float(s_pts[i, 2])), i)
    kd.balance()

    skin_vg_names = {vg.index: vg.name for vg in skin_obj.vertex_groups}
    skin_weights = [
        [(skin_vg_names[g.group], float(g.weight)) for g in v.groups if g.group in skin_vg_names and g.weight > 1e-5]
        for v in skin_obj.data.vertices
    ]

    total_pushed = 0
    total_synced = 0

    for obj in inner_objs:
        if obj == skin_obj or obj.type != "MESH" or len(obj.data.vertices) == 0:
            continue
        in_to_ref = np.array(ref_inv @ obj.matrix_world, dtype=np.float64)
        ref_to_in = np.linalg.inv(in_to_ref)
        in_n = len(obj.data.vertices)
        ico = np.empty(in_n * 3, dtype=np.float32)
        obj.data.vertices.foreach_get("co", ico)
        i_pts = ico.reshape(-1, 3).astype(np.float64) @ in_to_ref[:3, :3].T + in_to_ref[:3, 3]

        # Ensure matching vertex groups exist on innerwear mesh
        dst_vgs = {vg.name: vg for vg in obj.vertex_groups}
        modified_pos = False
        new_ref_pts = i_pts.copy()

        for vi in range(in_n):
            p = i_pts[vi]
            _co, si, dist = kd.find((float(p[0]), float(p[1]), float(p[2])))
            if dist > detect_dist:
                continue
            sp = s_pts[si]
            sn_vec = s_nrm[si]
            signed = float(np.dot(p - sp, sn_vec))
            # TEW1 coordinate: +X is forward, -X is back/buttocks (give slightly larger clearance at back)
            need_clear = back_offset if sn_vec[0] < -0.15 else front_offset
            if signed < need_clear:
                new_ref_pts[vi] = p + sn_vec * (need_clear - signed)
                total_pushed += 1
                modified_pos = True

            # Sync exact nearest-skin vertex weights so innerwear never clips during pelvic/thigh bend
            sw = skin_weights[si]
            if sw:
                for vg in obj.vertex_groups:
                    vg.remove([vi])
                for bname, w in sw:
                    vg = dst_vgs.get(bname)
                    if vg is None:
                        vg = obj.vertex_groups.new(name=bname)
                        dst_vgs[bname] = vg
                    vg.add([vi], w, "REPLACE")
                total_synced += 1

        if modified_pos:
            out_local = new_ref_pts @ ref_to_in[:3, :3].T + ref_to_in[:3, 3]
            obj.data.vertices.foreach_set("co", out_local.astype(np.float32).ravel())
            obj.data.update()

    return total_pushed, total_synced


def _align_limb_poses(src_arm, tgt_arm, std_to_main):
    """Rotate source limbs (upperarm/forearm/thigh/shin) in Pose Mode to match TEW1 template limb directions."""
    pairs = (
        ("upperarm_L", "forearm_L", "l_upperarm", "l_forearm"),
        ("forearm_L",  "hand_L",    "l_forearm",  "l_hand"),
        ("upperarm_R", "forearm_R", "r_upperarm", "r_forearm"),
        ("forearm_R",  "hand_R",    "r_forearm",  "r_hand"),
        ("thigh_L",    "shin_L",    "l_thigh",    "l_shin"),
        ("shin_L",     "foot_L",    "l_shin",     "l_foot"),
        ("thigh_R",    "shin_R",    "r_thigh",    "r_shin"),
        ("shin_R",     "foot_R",    "r_shin",     "r_foot"),
    )
    bpy.context.view_layer.objects.active = src_arm
    bpy.ops.object.mode_set(mode="POSE")
    aligned = 0
    for s_a, s_b, t_a, t_b in pairs:
        na, nb = std_to_main.get(s_a), std_to_main.get(s_b)
        if not (na and nb and na in src_arm.pose.bones and nb in src_arm.pose.bones):
            continue
        ta_pos = _world_bone_head(tgt_arm, t_a)
        tb_pos = _world_bone_head(tgt_arm, t_b)
        if ta_pos is None or tb_pos is None:
            continue
        tgt_dir = (tb_pos - ta_pos).normalized()
        pa, pb = src_arm.pose.bones[na], src_arm.pose.bones[nb]
        sa_pos = src_arm.matrix_world @ pa.head
        sb_pos = src_arm.matrix_world @ pb.head
        if (sb_pos - sa_pos).length < 1e-6 or tgt_dir.length < 1e-6:
            continue
        src_dir = (sb_pos - sa_pos).normalized()
        rot_world = src_dir.rotation_difference(tgt_dir).to_matrix()
        # Convert world rotation into armature local rotation around pa.head
        arm_rot = src_arm.matrix_world.to_3x3()
        rot_arm = (arm_rot.inverted_safe() @ rot_world @ arm_rot).to_4x4()
        cur = pa.matrix.copy()
        new_m = rot_arm @ cur
        new_m.translation = cur.translation
        pa.matrix = new_m
        bpy.context.view_layer.update()
        aligned += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    return aligned


def _copy_physics_bones_to_target(src_arm, tgt_arm, meshes):
    """Copy non-native weighted bones (e.g. hair/ribbon/skirt chains) from src_arm onto tgt_arm."""
    tgt_existing = set(tgt_arm.data.bones.keys())
    weighted_names = set()
    for obj in meshes:
        vgs = {vg.index: vg.name for vg in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 1e-4:
                    weighted_names.add(vgs[g.group])

    # Collect non-native weighted bones plus their non-native ancestors up to a native TEW1 bone
    to_copy = []
    seen = set()

    def collect(b):
        if b is None or b.name in tgt_existing or b.name in seen:
            return
        if b.parent is not None and b.parent.name not in tgt_existing:
            collect(b.parent)
        seen.add(b.name)
        to_copy.append(b.name)

    for b in src_arm.data.bones:
        if b.name not in tgt_existing and b.name in weighted_names:
            collect(b)

    if not to_copy:
        return 0

    src_to_tgt = tgt_arm.matrix_world.inverted_safe() @ src_arm.matrix_world
    src_data = []
    for bname in to_copy:
        sb = src_arm.data.bones[bname]
        head_t = src_to_tgt @ sb.head_local
        tail_t = src_to_tgt @ sb.tail_local
        if (tail_t - head_t).length < 1e-4:
            tail_t = head_t + Vector((0.0, 0.0, -1.0))
        parent_name = sb.parent.name if sb.parent else "head"
        if parent_name not in tgt_existing and parent_name not in seen:
            parent_name = "head" if "head" in tgt_existing else "pelvis"
        src_data.append((bname, head_t, tail_t, parent_name))

    bpy.context.view_layer.objects.active = tgt_arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = tgt_arm.data.edit_bones
    for bname, head_t, tail_t, _ in src_data:
        if bname in eb:
            continue
        nb = eb.new(bname)
        nb.head = head_t
        nb.tail = tail_t
        nb.use_deform = True
    for bname, _, _, parent_name in src_data:
        if bname in eb and parent_name in eb:
            eb[bname].parent = eb[parent_name]
    bpy.ops.object.mode_set(mode="OBJECT")

    # Ensure vertices weighted ONLY to copied physics bones also get a fallback native parent weight
    # (so TEW1 BMD6 export never rejects hair vertices as "unweighted to native skeleton")
    phys_set = set(to_copy)
    native_parent = {}
    for bname in to_copy:
        cur = tgt_arm.data.bones.get(bname)
        while cur and cur.name not in tgt_existing:
            cur = cur.parent
        native_parent[bname] = cur.name if cur else "head"

    for obj in meshes:
        vgs = {vg.index: vg.name for vg in obj.vertex_groups}
        for v in obj.data.vertices:
            has_native = any(vgs.get(g.group) in tgt_existing and g.weight > 1e-5 for g in v.groups)
            if has_native:
                continue
            phys_hits = [(vgs[g.group], g.weight) for g in v.groups if vgs.get(g.group) in phys_set and g.weight > 1e-5]
            if phys_hits:
                best_phys = max(phys_hits, key=lambda x: x[1])[0]
                fb = native_parent.get(best_phys, "head")
                vg = obj.vertex_groups.get(fb) or obj.vertex_groups.new(name=fb)
                vg.add([v.index], 1.0, "ADD")

    return len(to_copy)


def _poll_armature_ptr(self, obj):
    return obj.type == "ARMATURE"


def _poll_tew_rig_ptr(self, obj):
    return obj.type == "ARMATURE" and "tew1_bmd6_template" in obj


class TEW1RigToolsSettings(bpy.types.PropertyGroup):
    source_rig: PointerProperty(
        name="源角色骨架",
        type=bpy.types.Object,
        poll=_poll_armature_ptr,
        description="待导入转换的 MMD / VRChat / VRM 角色骨架（不需要提前手改骨名）",
    )
    target_rig: PointerProperty(
        name="TEW1 模板骨架",
        type=bpy.types.Object,
        poll=_poll_tew_rig_ptr,
        description="从原版 .bmd6model（如 pl0000_ng）导入的塞巴斯蒂安原生模板骨架",
    )
    source_preset: EnumProperty(
        name="源骨骼预设",
        items=[
            ("AUTO", "自动识别 (MMD / VRChat)", "自动检测源骨架的骨名覆盖率，智能选择 MMD 或 VRChat 预设"),
            ("MMD", "MMD 预设 (日/英/中 PMX)", "适配常见 MMD 模型（下半身/上半身/腕.L/ひじ.L/足D.L/腕捩等，参考 ModToolkit）"),
            ("VRCHAT", "VRChat / Unity Humanoid", "适配 VRChat、Unity Humanoid 与 VRM 0.x（Hips/Spine/Chest/UpperArm_L 等）"),
        ],
        default="AUTO",
        description="选择源模型的骨骼命名规范；不确定时保持「自动识别」即可",
    )
    merge_aux_weights: BoolProperty(
        name="合并辅助/扭转骨权重到主骨",
        default=True,
        description="自动将腕捩/手捩/胸/肩C/膝盖辅助等非 TEW1 原生辅助骨权重无损合并到主骨（完整保留头发/裙摆物理骨）",
    )
    align_limb_pose: BoolProperty(
        name="自动姿态对骨（保留形态键）",
        default=True,
        description="自动把源角色手臂与双腿旋转对齐到 TEW1 模板姿势，并通过 LBS 烘焙完整保留所有面部形态键",
    )
    preserve_original_proportions: BoolProperty(
        name="保持原版肩宽与脚掌 1:1 比例（防双开门/防大脚）",
        default=True,
        description="按真实脚底贴地 Z=0.10 对齐（不拉伸裸足去套塞巴斯蒂安高帮战靴）、用双腿中点对齐前后 X（防腰胯折痕），并保留原版窄肩比例",
    )
    fix_medial_shoulder_weights: BoolProperty(
        name="自动修复「双开门」肩头内侧权重",
        default=True,
        description="塞巴斯蒂安上臂旋转轴极宽(|Y|≈10.25)，放臂时内侧肩头会向上顶起成方形「双开门」；开启后自动将内侧上臂权重平滑转移给 l/r_shoulder",
    )
    migrate_to_tew_rig: BoolProperty(
        name="自动迁移物理发骨并绑定到 TEW1 骨架",
        default=True,
        description="一键把头发/飘带物理骨骼复制到 TEW1 模板骨架下，并将所有角色网格直接绑定到 TEW1 模板骨架",
    )


class TEW1RenameBonesPreset(bpy.types.Operator):
    bl_idname = "object.tew1_rename_bones_preset"
    bl_label = "一键骨骼重命名 (MMD/VRChat → TEW1)"
    bl_description = "将源角色骨架和所有绑定网格的顶点组一键重命名为恶灵附身 1 原生骨名，自动合并扭转/辅助骨权重，同时完整保留头发/衣摆物理骨"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.tew1_rig_tools
        src = st.source_rig or (context.object if context.object and context.object.type == "ARMATURE" else None)
        if src is None:
            self.report({"ERROR"}, "请先在面板指定「源角色骨架」或在视口选中源骨架。")
            return {"CANCELLED"}
        pid = st.source_preset
        if pid == "AUTO":
            pid, score = detect_source_preset(src)
            if score < 4:
                self.report({"WARNING"}, f"仅识别到 {score} 根核心骨骼，已按 {pid} 预设尽力匹配。")
        renamed, merged, n_mesh = rename_and_merge_to_tew1(src, pid, merge_aux=st.merge_aux_weights)
        self.report({"INFO"}, f"[{pid}] 已重命名 {renamed} 根骨骼，合并 {merged} 处辅助权重（同步 {n_mesh} 个网格）。")
        return {"FINISHED"}


class TEW1MmdAToTPose(bpy.types.Operator):
    bl_idname = "object.tew1_mmd_a_to_tpose"
    bl_label = "MMD A-Pose 一键转 T-Pose"
    bl_description = "将 MMD 角色斜下垂的左右上臂自动抬平为标准 T-Pose，并使用安全 LBS 烘焙保留全部面部形态键（Shape Keys）"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.tew1_rig_tools
        src = st.source_rig or (context.object if context.object and context.object.type == "ARMATURE" else None)
        if src is None:
            self.report({"ERROR"}, "请先选中或指定 MMD 源骨架。")
            return {"CANCELLED"}
        std_to_main, _ = match_preset_bones(src, "MMD")
        if "upperarm_L" not in std_to_main and "upperarm_R" not in std_to_main:
            std_to_main, _ = match_preset_bones(src, "VRCHAT")
        # Also support already-renamed TEW1 bones
        if "upperarm_L" not in std_to_main and "l_upperarm" in src.data.bones:
            std_to_main["upperarm_L"] = "l_upperarm"
        if "upperarm_R" not in std_to_main and "r_upperarm" in src.data.bones:
            std_to_main["upperarm_R"] = "r_upperarm"

        # Determine left axis from shoulder vector
        hl = _world_bone_head(src, std_to_main.get("upperarm_L", ""))
        hr = _world_bone_head(src, std_to_main.get("upperarm_R", ""))
        left_axis = Vector((hl.x - hr.x, hl.y - hr.y, 0.0)).normalized() if (hl and hr and (hl - hr).length > 1e-5) else Vector((1.0, 0.0, 0.0))

        bpy.context.view_layer.objects.active = src
        bpy.ops.object.mode_set(mode="POSE")
        count = 0
        arm_rot = src.matrix_world.to_3x3()
        for key, sign in (("upperarm_L", 1.0), ("upperarm_R", -1.0)):
            bname = std_to_main.get(key)
            if not bname or bname not in src.pose.bones:
                continue
            pb = src.pose.bones[bname]
            bone_vec = (arm_rot @ (pb.bone.tail_local - pb.bone.head_local)).normalized()
            if bone_vec.length < 1e-6:
                continue
            target_dir = left_axis * sign
            rot_world = bone_vec.rotation_difference(target_dir).to_matrix()
            rot_arm = (arm_rot.inverted_safe() @ rot_world @ arm_rot).to_4x4()
            cur = pb.matrix.copy()
            new_m = rot_arm @ cur
            new_m.translation = cur.translation
            pb.matrix = new_m
            bpy.context.view_layer.update()
            count += 1
        bpy.ops.object.mode_set(mode="OBJECT")
        if count == 0:
            self.report({"WARNING"}, "未在源骨架中找到左右上臂骨骼。")
            return {"CANCELLED"}
        n_mesh = bake_pose_preserving_shapekeys(src)
        self.report({"INFO"}, f"已完成 A→T 姿势转换（处理 {count} 根上臂，无损烘焙 {n_mesh} 个含形态键网格）。")
        return {"FINISHED"}


class TEW1AlignRigTransform(bpy.types.Operator):
    bl_idname = "object.tew1_align_rig_transform"
    bl_label = "仅自动对齐体型缩放与朝向"
    bl_description = "只对齐源角色骨架与 TEW1 模板骨架的正面朝向、身高比例和真实脚底贴地高度（保持原版肩宽与 1:1 脚掌比例），不修改骨骼姿势和骨名"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.tew1_rig_tools
        src, tgt = st.source_rig, st.target_rig
        if not src or not tgt or src == tgt:
            self.report({"ERROR"}, "请在上方分别选好「源角色骨架」和「TEW1 模板骨架」。")
            return {"CANCELLED"}
        pid = detect_source_preset(src)[0] if st.source_preset == "AUTO" else st.source_preset
        std_to_main, _ = match_preset_bones(src, pid)
        scale = _align_armature_transform(src, tgt, std_to_main, preserve_proportions=st.preserve_original_proportions)
        self.report({"INFO"}, f"已自动对齐朝向、脚底贴地与体型缩放（缩放倍率 {scale:.3f}，保持原版肩宽/脚掌比例）。")
        return {"FINISHED"}


class TEW1FixShoulderWeights(bpy.types.Operator):
    bl_idname = "object.tew1_fix_shoulder_weights"
    bl_label = "一键修复「双开门」肩宽权重（保持原版窄肩）"
    bl_description = "将位于塞巴斯蒂安宽肩旋转轴内侧(|Y|<10.6)的 l/r_upperarm 权重平滑转移给 l/r_shoulder，彻底消除放臂待机时的方形宽肩凸起（双开门）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from . import active_rig
        st = getattr(context.scene, "tew1_rig_tools", None)
        return bool(active_rig(context) or (st and st.target_rig))

    def execute(self, context):
        from . import active_rig
        st = context.scene.tew1_rig_tools
        tgt = active_rig(context) or st.target_rig
        if tgt is None:
            self.report({"ERROR"}, "请先选中 TEW1 模板骨架或在面板指定目标骨架。")
            return {"CANCELLED"}
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if not meshes:
            meshes = attached_meshes(tgt)
        if not meshes:
            self.report({"ERROR"}, "未找到绑定到 TEW1 骨架的网格。")
            return {"CANCELLED"}
        fixed_v, fixed_m = apply_medial_shoulder_weight_fix(tgt, meshes)
        self.report({"INFO"}, f"防双开门肩宽权重修正完成：平滑转移 {fixed_v} 个肩头内侧顶点（涉及 {fixed_m} 个网格）。")
        return {"FINISHED"}


class TEW1FixInnerwearClipping(bpy.types.Operator):
    bl_idname = "object.tew1_fix_innerwear_clipping"
    bl_label = "贴身内衣/内裤防穿模（自动外推 + 同步皮肤权重）"
    bl_description = "先选中贴身内衣/内裤网格，最后加选身体皮肤网格作为活动对象，一键将贴合/穿模顶点沿皮肤法线微幅外推（后臀 0.22 / 前侧 0.12）并精确同步最近皮肤顶点权重"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        return context.mode == "OBJECT" and len(meshes) >= 2 and context.object in meshes

    def execute(self, context):
        from . import active_rig
        skin_obj = context.object
        inner_objs = [o for o in context.selected_objects if o.type == "MESH" and o != skin_obj]
        tgt = active_rig(context) or skin_obj.find_armature()
        pushed, synced = fix_innerwear_clipping(skin_obj, inner_objs, tgt_arm=tgt)
        self.report(
            {"INFO"},
            f"内衣防穿模完成（皮肤基准: {skin_obj.name}）：外推 {pushed} 个穿模/共面顶点，同步 {synced} 个顶点皮肤权重。",
        )
        return {"FINISHED"}


class TEW1OneClickAlignAndBind(bpy.types.Operator):
    bl_idname = "object.tew1_oneclick_align_and_bind"
    bl_label = "一键对骨、重命名并绑定到 TEW1 骨架"
    bl_description = "全自动换骨一条龙：①识别 MMD/VRChat 预设 ②对齐朝向/身高/真实脚底贴地（1:1原比例） ③肢体姿态对骨并无损保留形态键 ④重命名骨骼并合并辅助权重 ⑤防双开门肩头内侧权重修正 ⑥迁移物理发骨并绑定到 TEW1 模板骨架"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.tew1_rig_tools
        src, tgt = st.source_rig, st.target_rig
        if not src or not tgt or src == tgt:
            self.report({"ERROR"}, "请先在上方选好「源角色骨架」与「TEW1 模板骨架」（导入的 pl0000_ng 等）。")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        pid = detect_source_preset(src)[0] if st.source_preset == "AUTO" else st.source_preset
        std_to_main, _ = match_preset_bones(src, pid)
        if len(std_to_main) < 4:
            self.report({"ERROR"}, f"按 {pid} 预设仅匹配到 {len(std_to_main)} 根骨骼，请确认源骨架类型。")
            return {"CANCELLED"}

        # Step 1: Align facing, scale, thigh-midpoint X, and true sole-bottom ground Z
        scale = _align_armature_transform(src, tgt, std_to_main, preserve_proportions=st.preserve_original_proportions)

        # Capture source slender shoulder |Y| in target rig space BEFORE renaming/hiding
        src_upper_y = None
        src_lu_w = _world_bone_head(src, std_to_main.get("upperarm_L", ""))
        src_ru_w = _world_bone_head(src, std_to_main.get("upperarm_R", ""))
        if src_lu_w and src_ru_w:
            tgt_inv = tgt.matrix_world.inverted_safe()
            src_upper_y = 0.5 * (abs((tgt_inv @ src_lu_w).y) + abs((tgt_inv @ src_ru_w).y))

        # Step 2: Pose-align limbs & bake into vertices + Shape Keys
        aligned_limbs = 0
        if st.align_limb_pose:
            aligned_limbs = _align_limb_poses(src, tgt, std_to_main)
            if aligned_limbs > 0:
                bake_pose_preserving_shapekeys(src)

        # Step 3: Rename bones & merge aux weights to TEW1 Sebastian names
        renamed, merged, n_mesh = rename_and_merge_to_tew1(src, pid, merge_aux=st.merge_aux_weights)

        # Step 4: Copy physics bones & bind all custom meshes to TEW1 template rig
        copied_phys = 0
        meshes = attached_meshes(src)
        if st.migrate_to_tew_rig:
            copied_phys = _copy_physics_bones_to_target(src, tgt, meshes)
            for obj in meshes:
                wm = obj.matrix_world.copy()
                obj.parent = tgt
                obj.matrix_world = wm
                has_arm = False
                for mod in obj.modifiers:
                    if mod.type == "ARMATURE":
                        mod.object = tgt
                        has_arm = True
                if not has_arm:
                    mod = obj.modifiers.new("TEW1 Armature", "ARMATURE")
                    mod.object = tgt
            src.hide_set(True)
            context.view_layer.objects.active = tgt

        # Step 5: Medial shoulder-cap weight transfer (eliminates 'double-door' raised shoulders in arms-down idle!)
        fixed_sh_verts = 0
        if st.fix_medial_shoulder_weights and meshes:
            fixed_sh_verts, _ = apply_medial_shoulder_weight_fix(tgt, meshes, src_upper_y_override=src_upper_y)

        self.report(
            {"INFO"},
            f"[{pid}] 一键对骨绑定完成！缩放 {scale:.2f}× | 对齐 {aligned_limbs} 节肢体 | 重命名 {renamed} 骨 | "
            f"合并 {merged} 辅助权重 | 防双开门修正 {fixed_sh_verts} 顶点 | 迁移 {copied_phys} 物理骨 | 绑定 {n_mesh} 个网格",
        )
        return {"FINISHED"}


CLASSES = (
    TEW1RigToolsSettings,
    TEW1RenameBonesPreset,
    TEW1MmdAToTPose,
    TEW1AlignRigTransform,
    TEW1FixShoulderWeights,
    TEW1FixInnerwearClipping,
    TEW1OneClickAlignAndBind,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tew1_rig_tools = PointerProperty(type=TEW1RigToolsSettings)


def unregister():
    del bpy.types.Scene.tew1_rig_tools
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
