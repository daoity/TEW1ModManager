"""Blender 4.0 - 5.2+ compatibility helpers for TEW1 BMD6 & TEW Physical addon."""

import bpy

BLENDER_VERSION = bpy.app.version
IS_BLENDER_5 = BLENDER_VERSION >= (5, 0, 0)


def set_pose_bone_select(pose_bone, selected=True):
    """Select/deselect a PoseBone safely on both Blender 4.x and Blender 5.x."""
    if hasattr(pose_bone, "select"):
        pose_bone.select = selected
    if hasattr(pose_bone, "bone") and hasattr(pose_bone.bone, "select"):
        try:
            pose_bone.bone.select = selected
        except Exception:
            pass


def insert_pose_keyframe(pose_bone, data_path, frame):
    """Insert pose bone keyframe safely on Blender 4.x and Blender 5.x slotted actions."""
    if IS_BLENDER_5:
        pose_bone.keyframe_insert(data_path, frame=frame)
    else:
        pose_bone.keyframe_insert(data_path, frame=frame, group=pose_bone.name)


def ensure_material_nodes(mat):
    """Ensure a material has an active node tree without triggering Blender 5 deprecation warnings."""
    if not IS_BLENDER_5:
        mat.use_nodes = True
    elif getattr(mat, "node_tree", None) is None:
        try:
            mat.use_nodes = True
        except Exception:
            pass
    return mat.node_tree


def copy_action_slot(animation, baked, active_slot):
    """Assign matching action slot if supported by this Blender version."""
    if not active_slot or not hasattr(baked, "slots") or not hasattr(animation, "action_slot"):
        return
    slot = next((item for item in baked.slots if item.identifier == active_slot), None)
    if slot is not None:
        try:
            animation.action_slot = slot
        except Exception:
            pass


def active_slot_id(animation):
    slot = getattr(animation, "action_slot", None)
    return slot.identifier if slot is not None else None
