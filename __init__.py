bl_info = {
    "name": "Humanoid Remap Studio",
    "author": "帧给你你来K",
    "version": (0, 1, 60),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > 重映射 > 人形重映射",
    "description": "Automatic humanoid action retargeting with topology fallback.",
    "category": "Animation",
}

import importlib
import json
import math
import sys
import time
import uuid
from pathlib import Path

import blf
import bpy
import bpy.utils.previews
import gpu
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .armature_scan import analyze_humanoid_roles
from .figure_layout import figure_layout_shapes, figure_role_at
from .human_schema import (
    HUMAN_ROLE_BY_ID,
    HUMAN_ROLES,
    FINGER_ROLE_IDS,
    MAX_NECK_COUNT,
    MAX_SPINE_COUNT,
    neck_roles,
    spine_roles,
    visible_role_ids,
)
from .matcher import (
    best_role_for_bone,
    normalize_name,
    normalized_aliases_for_role,
    score_name_for_role,
)
from .preset_catalog import (
    audit_preset_sample_sets,
    best_matching_preset,
    classify_bone_names,
    preset_role_matches,
    public_preset_profiles,
)


HRS_CANVAS_HANDLERS = []
HRS_PANEL_DRAW_HANDLERS = []
HRS_CANVAS_SHADER = None
HRS_PREVIEW_COLLECTION = None
HRS_FLOAT_CANVAS_STATE = {"action": None, "start_mouse": (0, 0), "start_rect": (0, 0, 0, 0)}
HRS_PANEL_CLICK_MODAL_RUNNING = False
HRS_PANEL_EMBEDDED_CLICK_ENABLED = False
HRS_PANEL_WIDGET_STATE = {"region": None, "seen_at": 0.0}
HRS_PANEL_WIDGET_TTL = 0.08
HRS_FLOAT_CANVAS_MIN_WIDTH = 280
HRS_FLOAT_CANVAS_MIN_HEIGHT = 420
HRS_FLOAT_CANVAS_MAX_WIDTH = 760
HRS_FLOAT_CANVAS_MAX_HEIGHT = 920
HRS_PANEL_MIN_HEIGHT = 320
HRS_PANEL_DEFAULT_HEIGHT = 560
HRS_PANEL_MAX_HEIGHT = 820
HRS_PANEL_TOP_OFFSET = 300
HRS_PANEL_CANVAS_PAD_X = 28
HRS_PANEL_CANVAS_PAD_TOP = 34
HRS_PANEL_CANVAS_PAD_BOTTOM = 58
HRS_PANEL_RESIZE_STATE = {
    "active": False,
    "region": None,
    "start_mouse_y": 0,
    "start_height": HRS_PANEL_DEFAULT_HEIGHT,
}
HRS_CANVAS_FIT_BOUNDS = (0.20, 0.08, 0.80, 0.88)
HRS_NATIVE_FIGURE_MIN_SCALE = 4.8
HRS_NATIVE_FIGURE_MAX_SCALE = 8.6
HRS_UI_VERSION = "v080"
HRS_GENERIC_TOPOLOGY_LABEL = "通用人形（拓扑）"
HRS_SEMANTIC_NAME_MIN_SCORE = 0.68
HRS_RETARGET_HISTORY_KEY = "hrs_retarget_history"
HRS_RETARGET_HISTORY_LIMIT = 80
HRS_ROOT_MOTION_THRESHOLD = 0.03
HRS_REST_BODY_VERTICAL_MIN = 0.58
HRS_REST_LEG_VERTICAL_MIN = 0.50
HRS_FORWARD_ALIGNMENT_MIN_DEGREES = 5.0
HRS_BATCH_RESULT_LIMIT = 100
HRS_KEEP_IN_PLACE_SYNCING = False
HRS_SOURCE_ROOT_BONE_CANDIDATES = (
    "mixamorig:Hips",
    "Hips",
    "hips",
    "mixamorig:Root",
    "Root",
    "root",
    "Pelvis",
    "pelvis",
)
HRS_CANVAS_CENTER_COLOR = (0.18, 0.66, 0.74, 0.94)
HRS_CANVAS_LEFT_COLOR = (0.82, 0.23, 0.17, 0.94)
HRS_CANVAS_RIGHT_COLOR = (0.22, 0.42, 0.92, 0.94)
HRS_CANVAS_SELECTED_COLOR = (0.98, 0.74, 0.22, 0.98)
HRS_CANVAS_MUTED_COLOR = (0.62, 0.62, 0.60, 0.90)
HRS_ARMATURE_NAME_SYNCING = False
CORE_REMAP_ROLE_IDS = (
    "hips",
    "spine_01",
    "head",
    "left_upper_arm",
    "left_lower_arm",
    "left_hand",
    "right_upper_arm",
    "right_lower_arm",
    "right_hand",
    "left_upper_leg",
    "left_lower_leg",
    "left_foot",
    "right_upper_leg",
    "right_lower_leg",
    "right_foot",
)
HRS_STRUCTURAL_CORE_MIN_SCORE = 0.56
HRS_STRUCTURAL_OPTIONAL_MIN_SCORE = 0.42
AUTO_RIG_DRIVER_ROLE_BONES = {
    "hips": ("c_root.x", "c_root_master.x", "root.x"),
    "spine_01": ("c_spine_01.x", "spine_01.x"),
    "spine_02": ("c_spine_02.x", "spine_02.x"),
    "spine_03": ("c_spine_03.x", "spine_03.x"),
    "spine_04": ("c_spine_04.x", "spine_04.x"),
    "spine_05": ("c_spine_05.x", "spine_05.x"),
    "spine_06": ("c_spine_06.x", "spine_06.x"),
    "neck_01": ("c_neck.x", "neck.x"),
    "head": ("c_head.x", "head.x"),
    "left_shoulder": ("c_shoulder.l", "shoulder.l"),
    "right_shoulder": ("c_shoulder.r", "shoulder.r"),
    "left_upper_arm": ("c_arm_fk.l", "arm.l", "arm_stretch.l"),
    "right_upper_arm": ("c_arm_fk.r", "arm.r", "arm_stretch.r"),
    "left_lower_arm": ("c_forearm_fk.l", "forearm.l", "forearm_stretch.l"),
    "right_lower_arm": ("c_forearm_fk.r", "forearm.r", "forearm_stretch.r"),
    "left_hand": ("c_hand_fk.l", "hand.l"),
    "right_hand": ("c_hand_fk.r", "hand.r"),
    "left_upper_leg": ("c_thigh_fk.l", "thigh.l", "thigh_stretch.l"),
    "right_upper_leg": ("c_thigh_fk.r", "thigh.r", "thigh_stretch.r"),
    "left_lower_leg": ("c_leg_fk.l", "leg.l", "leg_stretch.l"),
    "right_lower_leg": ("c_leg_fk.r", "leg.r", "leg_stretch.r"),
    "left_foot": ("c_foot_fk.l", "foot.l"),
    "right_foot": ("c_foot_fk.r", "foot.r"),
    "left_toe": ("c_toes_fk.l", "toes_01.l", "toes.l"),
    "right_toe": ("c_toes_fk.r", "toes_01.r", "toes.r"),
    "left_thumb": ("c_thumb1.l", "thumb1.l"),
    "right_thumb": ("c_thumb1.r", "thumb1.r"),
    "left_index": ("c_index1.l", "index1.l"),
    "right_index": ("c_index1.r", "index1.r"),
    "left_middle": ("c_middle1.l", "middle1.l"),
    "right_middle": ("c_middle1.r", "middle1.r"),
    "left_ring": ("c_ring1.l", "ring1.l"),
    "right_ring": ("c_ring1.r", "ring1.r"),
    "left_pinky": ("c_pinky1.l", "pinky1.l"),
    "right_pinky": ("c_pinky1.r", "pinky1.r"),
}

AUTO_RIG_SOURCE_ROLE_BONES = {
    "hips": ("root.x", "c_root.x", "c_root_master.x"),
    "spine_01": ("spine_01_ref.x", "c_spine_01.x", "spine_01.x"),
    "spine_02": ("spine_02_ref.x", "c_spine_02.x", "spine_02.x"),
    "spine_03": ("spine_03_ref.x", "c_spine_03.x", "spine_03.x"),
    "spine_04": ("spine_04_ref.x", "c_spine_04.x", "spine_04.x"),
    "spine_05": ("spine_05_ref.x", "c_spine_05.x", "spine_05.x"),
    "spine_06": ("spine_06_ref.x", "c_spine_06.x", "spine_06.x"),
    "neck_01": ("neck_ref.x", "c_neck.x", "neck.x"),
    "head": ("head_ref.x", "c_head.x", "head.x"),
    "left_shoulder": ("shoulder_ref.l", "c_shoulder.l", "shoulder.l"),
    "right_shoulder": ("shoulder_ref.r", "c_shoulder.r", "shoulder.r"),
    "left_upper_arm": ("arm_ref.l", "c_arm_fk.l", "arm.l", "arm_stretch.l"),
    "right_upper_arm": ("arm_ref.r", "c_arm_fk.r", "arm.r", "arm_stretch.r"),
    "left_lower_arm": ("forearm_ref.l", "c_forearm_fk.l", "forearm.l", "forearm_stretch.l"),
    "right_lower_arm": ("forearm_ref.r", "c_forearm_fk.r", "forearm.r", "forearm_stretch.r"),
    "left_hand": ("hand_ref.l", "c_hand_fk.l", "hand.l"),
    "right_hand": ("hand_ref.r", "c_hand_fk.r", "hand.r"),
    "left_upper_leg": ("thigh_ref.l", "c_thigh_fk.l", "thigh.l", "thigh_stretch.l"),
    "right_upper_leg": ("thigh_ref.r", "c_thigh_fk.r", "thigh.r", "thigh_stretch.r"),
    "left_lower_leg": ("leg_ref.l", "c_leg_fk.l", "leg.l", "leg_stretch.l"),
    "right_lower_leg": ("leg_ref.r", "c_leg_fk.r", "leg.r", "leg_stretch.r"),
    "left_foot": ("foot_ref.l", "c_foot_fk.l", "foot.l"),
    "right_foot": ("foot_ref.r", "c_foot_fk.r", "foot.r"),
    "left_toe": ("toes_01_ref.l", "c_toes_fk.l", "toes_01.l", "toes.l"),
    "right_toe": ("toes_01_ref.r", "c_toes_fk.r", "toes_01.r", "toes.r"),
    "left_thumb": ("thumb1_ref.l", "c_thumb1.l", "thumb1.l"),
    "right_thumb": ("thumb1_ref.r", "c_thumb1.r", "thumb1.r"),
    "left_index": ("index1_ref.l", "c_index1.l", "index1.l"),
    "right_index": ("index1_ref.r", "c_index1.r", "index1.r"),
    "left_middle": ("middle1_ref.l", "c_middle1.l", "middle1.l"),
    "right_middle": ("middle1_ref.r", "c_middle1.r", "middle1.r"),
    "left_ring": ("ring1_ref.l", "c_ring1.l", "ring1.l"),
    "right_ring": ("ring1_ref.r", "c_ring1.r", "ring1.r"),
    "left_pinky": ("pinky1_ref.l", "c_pinky1.l", "pinky1.l"),
    "right_pinky": ("pinky1_ref.r", "c_pinky1.r", "pinky1.r"),
}


def armature_poll(_self, obj):
    return obj is not None and obj.type == "ARMATURE"


def role_ids():
    return [role["id"] for role in HUMAN_ROLES]


def selected_pose_bone(context):
    bone = getattr(context, "active_pose_bone", None)
    if bone:
        return bone
    obj = context.object
    if obj and obj.type == "ARMATURE":
        return getattr(obj.data.bones, "active", None)
    return None


def selected_armature_object(context):
    obj = getattr(context, "object", None)
    if obj and obj.type == "ARMATURE":
        return obj
    active = getattr(getattr(context, "view_layer", None), "objects", None)
    active_obj = getattr(active, "active", None) if active else None
    if active_obj and active_obj.type == "ARMATURE":
        return active_obj
    for obj in getattr(context, "selected_objects", []) or []:
        if obj.type == "ARMATURE":
            return obj
    return None


def set_scene_armature(scene, target, armature):
    global HRS_ARMATURE_NAME_SYNCING
    HRS_ARMATURE_NAME_SYNCING = True
    try:
        if target == "SOURCE":
            scene.hrs_source_armature = armature
            if hasattr(scene, "hrs_source_armature_name"):
                scene.hrs_source_armature_name = armature.name if armature else ""
            clear_invalid_mapping_side(scene, "SOURCE")
        else:
            scene.hrs_target_armature = armature
            if hasattr(scene, "hrs_target_armature_name"):
                scene.hrs_target_armature_name = armature.name if armature else ""
            clear_invalid_mapping_side(scene, "TARGET")
    finally:
        HRS_ARMATURE_NAME_SYNCING = False


def armature_object_from_name(scene, name):
    if not name:
        return None
    obj = scene.objects.get(name) if scene else None
    if obj is None:
        obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == "ARMATURE":
        return obj
    return None


def sync_armature_name_from_pointer(scene, target):
    armature = scene.hrs_source_armature if target == "SOURCE" else scene.hrs_target_armature
    set_scene_armature(scene, target, armature if armature and armature.type == "ARMATURE" else None)


def update_armature_name(scene, target):
    if HRS_ARMATURE_NAME_SYNCING:
        return
    name = scene.hrs_source_armature_name if target == "SOURCE" else scene.hrs_target_armature_name
    if not name:
        set_scene_armature(scene, target, None)
        return
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    if obj.type != "ARMATURE":
        set_scene_armature(scene, target, None)
        scene.hrs_retarget_status = f"{name} 不是骨架对象。"
        return
    set_scene_armature(scene, target, obj)


def update_source_armature_name(self, context):
    update_armature_name(self, "SOURCE")


def update_target_armature_name(self, context):
    update_armature_name(self, "TARGET")


def update_source_armature_pointer(self, context):
    if not HRS_ARMATURE_NAME_SYNCING:
        sync_armature_name_from_pointer(self, "SOURCE")


def update_target_armature_pointer(self, context):
    if not HRS_ARMATURE_NAME_SYNCING:
        sync_armature_name_from_pointer(self, "TARGET")


def reset_batch_recognition_state(scene):
    if hasattr(scene, "hrs_batch_ready"):
        scene.hrs_batch_ready = False
    if hasattr(scene, "hrs_can_execute_retarget"):
        scene.hrs_can_execute_retarget = False
    if hasattr(scene, "hrs_auto_summary"):
        scene.hrs_auto_summary = "请选择输入并点击自动识别。"
    if hasattr(scene, "hrs_auto_detail"):
        scene.hrs_auto_detail = "批量集合只允许包含带有效 Action 的人形骨架。"


def update_source_mode(self, _context):
    reset_batch_recognition_state(self)


def update_source_collection(self, _context):
    reset_batch_recognition_state(self)


def sync_scene_armature_names_timer():
    for scene in bpy.data.scenes:
        sync_armature_name_from_pointer(scene, "SOURCE")
        sync_armature_name_from_pointer(scene, "TARGET")
    return None


def armature_bone_names(armature):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return []
    return [bone.name for bone in armature.data.bones]


def armature_has_bone(armature, bone_name):
    return bool(
        armature is not None
        and getattr(armature, "type", None) == "ARMATURE"
        and bone_name
        and armature.data.bones.get(bone_name)
    )


def armature_preset_profile(armature):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return None
    return best_matching_preset(armature_bone_names(armature), object_name=armature.name)


def armature_action_name_hint(armature):
    action = animation_action_for_armature(armature) if "animation_action_for_armature" in globals() else None
    return action.name.lower() if action else ""


def core_topology_coverage(armature, min_score=HRS_STRUCTURAL_CORE_MIN_SCORE):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return {
            "ready": False,
            "found": 0,
            "total": len(CORE_REMAP_ROLE_IDS),
            "missing": list(CORE_REMAP_ROLE_IDS),
            "minScore": 0.0,
            "matches": {},
            "chainErrors": [],
            "duplicateBones": {},
        }
    topology_matches = analyze_humanoid_roles(armature)
    usable = {}
    missing = []
    scores = []
    for role_id in CORE_REMAP_ROLE_IDS:
        match = topology_matches.get(role_id)
        if not match or match.get("score", 0.0) < min_score or not armature_has_bone(armature, match.get("bone_name", "")):
            missing.append(role_id)
            continue
        usable[role_id] = match
        scores.append(float(match.get("score", 0.0)))

    by_bone = {}
    for role_id, match in usable.items():
        by_bone.setdefault(match["bone_name"], []).append(role_id)
    duplicate_bones = {
        bone_name: role_ids
        for bone_name, role_ids in by_bone.items()
        if len(role_ids) > 1
    }

    def descends_from(child_role, parent_role):
        child_match = usable.get(child_role)
        parent_match = usable.get(parent_role)
        if not child_match or not parent_match:
            return True
        child = armature.data.bones.get(child_match["bone_name"])
        parent_name = parent_match["bone_name"]
        current = child.parent if child else None
        while current:
            if current.name == parent_name:
                return True
            current = current.parent
        return False

    expected_chains = (
        ("spine_01", "hips"),
        ("head", "spine_01"),
        ("left_lower_arm", "left_upper_arm"),
        ("left_hand", "left_lower_arm"),
        ("right_lower_arm", "right_upper_arm"),
        ("right_hand", "right_lower_arm"),
        ("left_upper_leg", "hips"),
        ("left_lower_leg", "left_upper_leg"),
        ("left_foot", "left_lower_leg"),
        ("right_upper_leg", "hips"),
        ("right_lower_leg", "right_upper_leg"),
        ("right_foot", "right_lower_leg"),
    )
    chain_errors = [
        f"{child_role}!<{parent_role}"
        for child_role, parent_role in expected_chains
        if not descends_from(child_role, parent_role)
    ]
    return {
        "ready": len(missing) == 0 and not chain_errors and not duplicate_bones,
        "found": len(usable),
        "total": len(CORE_REMAP_ROLE_IDS),
        "missing": missing,
        "minScore": min(scores) if scores else 0.0,
        "matches": usable,
        "chainErrors": chain_errors,
        "duplicateBones": duplicate_bones,
    }


def semantic_name_role_matches(armature, roles, min_score=HRS_SEMANTIC_NAME_MIN_SCORE):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return {}
    requested_roles = set(roles)
    role_ids = tuple(role["id"] for role in HUMAN_ROLES if role["id"] in requested_roles)
    candidates = {}
    for bone in armature.data.bones:
        leaf_name = bone.name.rsplit(":", 1)[-1]
        normalized_leaf = normalize_name(leaf_name)
        compact_leaf = normalized_leaf.replace("_", "")
        terminal_tokens = set(normalized_leaf.split("_"))
        terminal_penalty = int(
            bool(terminal_tokens.intersection({"end", "tip", "eye", "eyes", "eyeball"}))
        )
        auxiliary_penalty = int(
            bool(terminal_tokens.intersection({"twist", "roll", "helper", "mch", "org"}))
        )
        anatomy_bonus = 0
        if compact_leaf in {"hips", "hip", "pelvis"}:
            anatomy_bonus = 3
        elif compact_leaf in {"rootx", "crootx", "crootmasterx"}:
            anatomy_bonus = 2
        elif compact_leaf == "root":
            anatomy_bonus = 0
        finger_segment_bonus = 0
        if "proximal" in terminal_tokens or compact_leaf.endswith("1"):
            finger_segment_bonus = 2
        elif "intermediate" in terminal_tokens or "distal" in terminal_tokens:
            finger_segment_bonus = -1

        chain_name = ""
        chain_index = None
        for candidate_chain in ("spine", "neck"):
            tokens = normalized_leaf.split("_")
            if candidate_chain in tokens:
                chain_name = candidate_chain
                token_index = tokens.index(candidate_chain)
                if token_index + 1 < len(tokens) and tokens[token_index + 1].isdigit():
                    chain_index = int(tokens[token_index + 1])
                else:
                    chain_index = 1
                break
            compact_index = compact_leaf.find(candidate_chain)
            if compact_index >= 0:
                suffix = compact_leaf[compact_index + len(candidate_chain):]
                digits = "".join(character for character in suffix if character.isdigit())
                chain_name = candidate_chain
                chain_index = int(digits) + 1 if digits else 1
                break
        if normalized_leaf in {"chest", "upper_chest", "upperchest"}:
            chain_name = "spine"
            chain_index = 3 if "upper" in normalized_leaf else 2

        bone_candidates = []
        for role_order, role_id in enumerate(role_ids):
            score, reasons = score_name_for_role(bone.name, role_id)
            if score < min_score:
                continue
            aliases = normalized_aliases_for_role(role_id)
            exact_alias = bool(
                normalized_leaf in aliases
                or compact_leaf in {alias.replace("_", "") for alias in aliases}
            )
            chain_alignment = 0
            if chain_name and role_id.startswith(f"{chain_name}_"):
                role_chain_index = int(role_id.rsplit("_", 1)[-1])
                chain_alignment = 3 if role_chain_index == chain_index else -3
            rank = (
                int(exact_alias),
                chain_alignment,
                anatomy_bonus if role_id == "hips" else 0,
                finger_segment_bonus if role_id in FINGER_ROLE_IDS else 0,
                -auxiliary_penalty,
                float(score),
                -terminal_penalty,
                -role_order,
            )
            bone_candidates.append((rank, role_id, score, reasons, exact_alias))
        if not bone_candidates:
            continue
        bone_candidates.sort(reverse=True)
        rank, role_id, score, reasons, exact_alias = bone_candidates[0]
        candidate_rank = (*rank[:-1], -len(normalized_leaf), rank[-1])
        current = candidates.get(role_id)
        if current and current[0] >= candidate_rank:
            continue
        candidates[role_id] = (
            candidate_rank,
            {
                "role_id": role_id,
                "bone_name": bone.name,
                "score": max(float(score), 0.99 if exact_alias else 0.0),
                "reasons": [
                    *reasons,
                    "semantic-name",
                    *(["exact-alias"] if exact_alias else []),
                ],
            },
        )
    return {role_id: payload for role_id, (_rank, payload) in candidates.items()}


def merged_role_matches_for_armature(armature, roles, prefer_preset=True):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return {}
    roles = tuple(roles)
    preset_matches = preset_role_matches(armature, roles)
    name_matches = semantic_name_role_matches(armature, roles)
    topology_matches = analyze_humanoid_roles(armature)
    merged = {}
    topology_ready = core_topology_coverage(armature)["ready"]
    for role_id in roles:
        if prefer_preset:
            candidates = (
                (preset_matches.get(role_id), "preset"),
                (name_matches.get(role_id), "name"),
                (topology_matches.get(role_id), "topology"),
            )
        elif topology_ready:
            candidates = (
                (topology_matches.get(role_id), "topology"),
                (name_matches.get(role_id), "name"),
                (preset_matches.get(role_id), "preset"),
            )
        else:
            candidates = (
                (name_matches.get(role_id), "name"),
                (topology_matches.get(role_id), "topology"),
                (preset_matches.get(role_id), "preset"),
            )
        selected = None
        selected_route = ""
        for match, route in candidates:
            if not match:
                continue
            if not armature_has_bone(armature, match.get("bone_name", "")):
                continue
            selected = dict(match)
            selected_route = route
            break
        if selected:
            selected["route"] = selected_route
            merged[role_id] = selected
    return merged


def retarget_role_ids(scene):
    visible = set(visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers))
    visible.update(CORE_REMAP_ROLE_IDS)
    return [role["id"] for role in HUMAN_ROLES if role["id"] in visible]


def role_map_for_armature(scene, armature, roles=None, prefer_preset=None):
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return {}
    if roles is None:
        roles = retarget_role_ids(scene)
    if prefer_preset is None:
        prefer_preset = bool(armature_preset_profile(armature))
    matches = merged_role_matches_for_armature(armature, roles, prefer_preset=prefer_preset)
    role_map = {}
    for role_id, match in matches.items():
        min_score = (
            HRS_STRUCTURAL_CORE_MIN_SCORE
            if role_id in CORE_REMAP_ROLE_IDS and match.get("route") != "preset"
            else HRS_STRUCTURAL_OPTIONAL_MIN_SCORE
        )
        if match.get("score", 0.0) < min_score:
            continue
        if armature_has_bone(armature, match.get("bone_name", "")):
            role_map[role_id] = match["bone_name"]
    return role_map


def rest_bone_world_midpoint(armature, bone_name):
    if not armature or not bone_name:
        return None
    bone = armature.data.bones.get(bone_name)
    if not bone:
        return None
    return armature.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)


def world_z_alignment(vector):
    length = vector.length
    return abs(float(vector.z)) / length if length > 1.0e-8 else 0.0


def quality_role_map(scene, armature, roles):
    role_map = role_map_for_armature(scene, armature, roles=roles)
    used_bones = set(role_map.values())
    missing_roles = set(roles) - set(role_map)
    if not missing_roles:
        return role_map
    candidates = []
    for bone in armature.data.bones:
        match = best_role_for_bone(bone.name, roles)
        if not match or match["role_id"] not in missing_roles or match["score"] < 0.55:
            continue
        candidates.append((float(match["score"]), match["role_id"], bone.name))
    candidates.sort(reverse=True)
    for _score, role_id, bone_name in candidates:
        if role_id in role_map or bone_name in used_bones:
            continue
        role_map[role_id] = bone_name
        used_bones.add(bone_name)
    return role_map


def armature_rest_posture_quality(scene, armature):
    roles = (
        "hips",
        "head",
        "left_foot",
        "right_foot",
    )
    role_map = quality_role_map(scene, armature, roles)
    points = {
        role_id: rest_bone_world_midpoint(armature, role_map.get(role_id, ""))
        for role_id in roles
    }
    missing = [role_id for role_id in roles if points.get(role_id) is None]
    if missing:
        return {
            "ready": False,
            "passed": False,
            "score": 0.0,
            "missing": missing,
            "headAboveHips": False,
            "feetBelowHips": False,
            "bodyVerticalRatio": 0.0,
            "legVerticalRatio": 0.0,
            "issue": "未识别出完整的头、髋和双脚结构",
        }

    hips = points["hips"]
    head = points["head"]
    feet = (points["left_foot"], points["right_foot"])
    body_vertical = world_z_alignment(head - hips)
    leg_vertical = min(world_z_alignment(hips - foot) for foot in feet)
    head_above = bool(head.z > hips.z)
    feet_below = bool(all(foot.z < hips.z for foot in feet))
    passed = bool(
        head_above
        and feet_below
        and body_vertical >= HRS_REST_BODY_VERTICAL_MIN
        and leg_vertical >= HRS_REST_LEG_VERTICAL_MIN
    )
    score = (
        (0.25 if head_above else 0.0)
        + (0.25 if feet_below else 0.0)
        + min(1.0, body_vertical / HRS_REST_BODY_VERTICAL_MIN) * 0.25
        + min(1.0, leg_vertical / HRS_REST_LEG_VERTICAL_MIN) * 0.25
    )
    if not head_above or not feet_below:
        issue = "整体上下方向异常"
    elif body_vertical < HRS_REST_BODY_VERTICAL_MIN:
        issue = "躯干接近横向"
    elif leg_vertical < HRS_REST_LEG_VERTICAL_MIN:
        issue = "腿部方向与世界 Z 轴偏差过大"
    else:
        issue = ""
    return {
        "ready": True,
        "passed": passed,
        "score": round(score, 4),
        "missing": [],
        "headAboveHips": head_above,
        "feetBelowHips": feet_below,
        "bodyVerticalRatio": round(body_vertical, 4),
        "legVerticalRatio": round(leg_vertical, 4),
        "issue": issue,
    }


def retarget_posture_gate(scene):
    selected_source = scene.hrs_source_armature
    source = selected_source
    if selected_source and "resolved_retarget_source" in globals():
        source = resolved_retarget_source(scene).get("source") or selected_source
    target = scene.hrs_target_armature
    source_quality = armature_rest_posture_quality(scene, source) if source else None
    target_quality = armature_rest_posture_quality(scene, target) if target else None
    passed = bool(
        source_quality
        and target_quality
        and source_quality["passed"]
        and target_quality["passed"]
    )
    if source_quality and not source_quality["passed"]:
        detail = (
            f"动作骨架静止姿态异常：{source_quality['issue']}。"
            "FBX 请启用自动骨骼方向；BVH 请检查前向/上向轴。"
        )
    elif target_quality and not target_quality["passed"]:
        detail = f"目标骨架静止姿态异常：{target_quality['issue']}。请检查导入轴向或对象旋转。"
    else:
        detail = ""
    return {
        "passed": passed,
        "source": source_quality,
        "target": target_quality,
        "detail": detail,
    }


def armature_anatomical_axes(scene, armature):
    roles = (
        "hips",
        "head",
        "left_shoulder",
        "right_shoulder",
        "left_upper_leg",
        "right_upper_leg",
    )
    role_map = role_map_for_armature(scene, armature, roles=roles)
    points = {
        role_id: rest_bone_world_midpoint(armature, role_map.get(role_id, ""))
        for role_id in roles
    }
    up = None
    lateral = None
    if points["hips"] is not None and points["head"] is not None:
        up = points["head"] - points["hips"]
    if points["left_shoulder"] is not None and points["right_shoulder"] is not None:
        lateral = points["left_shoulder"] - points["right_shoulder"]
    elif points["left_upper_leg"] is not None and points["right_upper_leg"] is not None:
        lateral = points["left_upper_leg"] - points["right_upper_leg"]
    if up is None or lateral is None or up.length <= 1.0e-8 or lateral.length <= 1.0e-8:
        return {"ready": False, "roleMap": role_map}
    up.normalize()
    lateral = lateral - up * lateral.dot(up)
    if lateral.length <= 1.0e-8:
        return {"ready": False, "roleMap": role_map}
    lateral.normalize()
    forward = lateral.cross(up)
    if forward.length <= 1.0e-8:
        return {"ready": False, "roleMap": role_map}
    forward.normalize()
    return {
        "ready": True,
        "roleMap": role_map,
        "up": up,
        "lateral": lateral,
        "forward": forward,
    }


def project_direction_to_plane(direction, normal):
    projected = direction - normal * direction.dot(normal)
    if projected.length <= 1.0e-8:
        return None
    projected.normalize()
    return projected


def source_target_forward_alignment(scene, source, target):
    source_axes = armature_anatomical_axes(scene, source)
    target_axes = armature_anatomical_axes(scene, target)
    if not source_axes.get("ready") or not target_axes.get("ready"):
        return {
            "ready": False,
            "applied": False,
            "degrees": 0.0,
            "reason": "missing-anatomical-axis",
        }
    axis = target_axes["up"].copy()
    source_forward = project_direction_to_plane(source_axes["forward"], axis)
    target_forward = project_direction_to_plane(target_axes["forward"], axis)
    if source_forward is None or target_forward is None:
        return {
            "ready": False,
            "applied": False,
            "degrees": 0.0,
            "reason": "forward-parallel-to-up",
        }
    dot = max(-1.0, min(1.0, float(source_forward.dot(target_forward))))
    cross = source_forward.cross(target_forward)
    angle = math.atan2(float(axis.dot(cross)), dot)
    degrees = math.degrees(angle)
    return {
        "ready": True,
        "applied": abs(degrees) >= HRS_FORWARD_ALIGNMENT_MIN_DEGREES,
        "angle": angle,
        "degrees": degrees,
        "forwardDot": dot,
        "upDot": float(source_axes["up"].dot(target_axes["up"])),
        "lateralDot": float(source_axes["lateral"].dot(target_axes["lateral"])),
        "axis": axis,
        "sourceForward": source_forward,
        "targetForward": target_forward,
        "reason": "yaw-alignment" if abs(degrees) >= HRS_FORWARD_ALIGNMENT_MIN_DEGREES else "already-aligned",
    }


def apply_source_forward_alignment(source, alignment):
    if not alignment.get("applied"):
        return
    pivot = source.matrix_world.translation.copy()
    rotation = Matrix.Rotation(alignment["angle"], 4, alignment["axis"])
    source.matrix_world = (
        Matrix.Translation(pivot)
        @ rotation
        @ Matrix.Translation(-pivot)
        @ source.matrix_world
    )
    bpy.context.view_layer.update()


def source_role_map_for_auto_rig(scene):
    source = scene.hrs_source_armature
    roles = set(AUTO_RIG_DRIVER_ROLE_BONES.keys())
    roles.update(visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers))
    structural_map = role_map_for_armature(
        scene,
        source,
        roles=roles,
        prefer_preset=bool(armature_preset_profile(source)),
    )
    role_map = dict(structural_map)
    valid_slots = [
        slot
        for slot in scene.hrs_mapping_slots
        if slot.role_id in roles and armature_has_bone(source, slot.source_bone)
    ]
    slot_bone_counts = {}
    for slot in valid_slots:
        slot_bone_counts[slot.source_bone] = slot_bone_counts.get(slot.source_bone, 0) + 1

    for slot in valid_slots:
        current_name = role_map.get(slot.role_id, "")
        current_score = score_name_for_role(current_name, slot.role_id)[0] if current_name else 0.0
        slot_score = score_name_for_role(slot.source_bone, slot.role_id)[0]
        unique_slot_bone = slot_bone_counts.get(slot.source_bone, 0) == 1
        if unique_slot_bone and slot_score >= 0.68 and slot_score >= current_score:
            role_map[slot.role_id] = slot.source_bone
        elif not current_name and unique_slot_bone:
            role_map[slot.role_id] = slot.source_bone

    finger_tokens = {
        "thumb": ("thumb",),
        "index": ("index",),
        "middle": ("middle",),
        "ring": ("ring",),
        "pinky": ("pinky", "little"),
    }

    def explicit_finger_family(bone_name):
        compact = "".join(character for character in bone_name.lower() if character.isalnum())
        for family, tokens in finger_tokens.items():
            if any(token in compact for token in tokens):
                return family
        return ""

    def descendant_distance(bone, ancestor):
        distance = 0
        current = bone
        while current is not None and current != ancestor:
            current = current.parent
            distance += 1
        return distance if current == ancestor else 10_000

    source_bones = source.data.bones if source else ()
    for role_id in FINGER_ROLE_IDS.intersection(roles):
        side, family = role_id.split("_", 1)
        hand = source.data.bones.get(role_map.get(f"{side}_hand", "")) if source else None
        candidates = []
        for bone in source_bones:
            if explicit_finger_family(bone.name) != family:
                continue
            role_score = score_name_for_role(bone.name, role_id)[0]
            if role_score < 0.45:
                continue
            distance = descendant_distance(bone, hand) if hand else 10_000
            candidates.append((distance < 10_000, -distance, role_score, bone.name))
        if candidates:
            candidates.sort(reverse=True)
            role_map[role_id] = candidates[0][3]

    for role_id in FINGER_ROLE_IDS.intersection(roles):
        bone_name = role_map.get(role_id, "")
        explicit_family = explicit_finger_family(bone_name)
        expected_family = role_id.split("_", 1)[1]
        if explicit_family and explicit_family != expected_family:
            role_map.pop(role_id, None)

    by_bone = {}
    for role_id, bone_name in role_map.items():
        by_bone.setdefault(bone_name, []).append(role_id)
    for bone_name, role_ids_for_bone in by_bone.items():
        if len(role_ids_for_bone) <= 1:
            continue
        ranked = []
        for role_id in role_ids_for_bone:
            name_score = score_name_for_role(bone_name, role_id)[0]
            structural_bonus = 0.18 if structural_map.get(role_id) == bone_name else 0.0
            core_bonus = 0.04 if role_id in CORE_REMAP_ROLE_IDS else 0.0
            ranked.append((name_score + structural_bonus + core_bonus, role_id))
        ranked.sort(reverse=True)
        keep_role = ranked[0][1]
        for role_id in role_ids_for_bone:
            if role_id != keep_role:
                role_map.pop(role_id, None)

    source_action = animation_action_for_armature(source) if source else None
    for role_id in ("left_toe", "right_toe"):
        bone_name = role_map.get(role_id, "")
        if bone_name and not action_bone_has_rotation_delta(source_action, bone_name):
            role_map.pop(role_id, None)
    return role_map


def action_bone_has_rotation_delta(action, bone_name, tolerance=1.0e-4):
    if not action or not bone_name:
        return False
    path_prefix = escaped_pose_bone_data_path(bone_name, "")
    for curve in action_fcurves(action):
        if not curve.data_path.startswith(path_prefix):
            continue
        suffix = curve.data_path[len(path_prefix):]
        if suffix not in {"rotation_quaternion", "rotation_euler", "rotation_axis_angle"}:
            continue
        neutral = 1.0 if suffix == "rotation_quaternion" and curve.array_index == 0 else 0.0
        for point in curve.keyframe_points:
            if abs(float(point.co[1]) - neutral) > tolerance:
                return True
    return False


def target_role_map_for_auto_rig(scene):
    target = scene.hrs_target_armature
    roles = set(AUTO_RIG_DRIVER_ROLE_BONES.keys())
    roles.update(visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers))
    preset_matches = preset_role_matches(target, roles) if target else {}
    role_map = {}
    pose_bones = target.pose.bones if target and target.pose else {}
    for role_id in roles:
        match = preset_matches.get(role_id)
        if match and armature_has_bone(target, match.get("bone_name", "")):
            role_map[role_id] = match["bone_name"]
            continue
        for candidate in AUTO_RIG_DRIVER_ROLE_BONES.get(role_id, ()):
            if candidate in pose_bones:
                role_map[role_id] = candidate
                break
    return role_map


def nearest_common_bone_ancestor(first_bone, second_bone):
    if not first_bone or not second_bone:
        return None
    first_ancestors = set()
    current = first_bone
    while current:
        first_ancestors.add(current.name)
        current = current.parent
    current = second_bone
    while current:
        if current.name in first_ancestors:
            return current
        current = current.parent
    return None


def source_pelvis_bone_name(scene, role_map):
    source = scene.hrs_source_armature
    if not source or not source.pose:
        return ""

    preset_match = preset_role_matches(source, {"pelvis"}).get("pelvis")
    if preset_match and armature_has_bone(source, preset_match.get("bone_name", "")):
        return preset_match["bone_name"]

    left_leg = source.pose.bones.get(role_map.get("left_upper_leg", ""))
    right_leg = source.pose.bones.get(role_map.get("right_upper_leg", ""))
    common = nearest_common_bone_ancestor(left_leg, right_leg)
    motion_root = source.pose.bones.get(role_map.get("hips", ""))
    if not common or not motion_root or common == motion_root:
        return ""
    current = common.parent
    while current:
        if current == motion_root:
            return common.name
        current = current.parent
    return ""


def mapping_armature_for_attr(scene, attr_name):
    return scene.hrs_source_armature if attr_name == "source_bone" else scene.hrs_target_armature


def slot_side_valid(scene, slot, attr_name):
    return armature_has_bone(mapping_armature_for_attr(scene, attr_name), getattr(slot, attr_name, ""))


def slot_pair_valid(scene, slot):
    return slot_side_valid(scene, slot, "source_bone") and slot_side_valid(scene, slot, "target_bone")


def clear_invalid_mapping_side(scene, target):
    if not hasattr(scene, "hrs_mapping_slots"):
        return
    attr_name = "source_bone" if target == "SOURCE" else "target_bone"
    armature = mapping_armature_for_attr(scene, attr_name)
    for slot in scene.hrs_mapping_slots:
        bone_name = getattr(slot, attr_name)
        if bone_name and not armature_has_bone(armature, bone_name):
            setattr(slot, attr_name, "")
            if not slot.source_bone and not slot.target_bone:
                slot.status = "empty"
                slot.confidence = 0.0
                slot.note = ""


def detect_armature_profile(armature):
    names = armature_bone_names(armature)
    if not names:
        return "未选择"
    preset = armature_preset_profile(armature)
    if preset:
        return preset["label"]
    lowered = [name.lower() for name in names]
    compact_names = {name.replace("_", "").replace(".", "").replace(":", "") for name in lowered}
    object_name = armature.name.lower()
    if any(name.startswith("mixamorig:") for name in lowered) or "mixamo" in object_name:
        return "Mixamo"
    mixamo_core = {
        "hips",
        "spine",
        "spine1",
        "spine2",
        "neck",
        "head",
        "leftarm",
        "leftforearm",
        "lefthand",
        "leftupleg",
        "leftleg",
        "leftfoot",
        "rightarm",
        "rightforearm",
        "righthand",
        "rightupleg",
        "rightleg",
        "rightfoot",
    }
    if len(compact_names & mixamo_core) >= 10:
        return HRS_GENERIC_TOPOLOGY_LABEL
    if any(name.startswith("c_") for name in lowered) or any("_ref." in name or "_fk." in name or "_ik." in name for name in lowered):
        return "Auto-Rig Pro"
    if any(name.startswith(("def-", "org-", "mch-")) for name in lowered):
        return "Rigify"
    if any(name.startswith("j_bip_") or name.startswith("j_sec_") for name in lowered):
        return "VRM/VRoid"
    unreal_center = {
        "root",
        "pelvis",
        "spine_01",
        "spine_02",
        "neck_01",
        "head",
    }
    unreal_limbs = {
        "clavicle_l",
        "upperarm_l",
        "lowerarm_l",
        "hand_l",
        "thigh_l",
        "calf_l",
        "foot_l",
    }
    normalized_names = {normalize_name(name) for name in names}
    explicit_unreal = "metahuman" in object_name or any("metahuman" in name for name in lowered)
    unreal_signature = bool(
        len(normalized_names.intersection(unreal_center)) >= 4
        and len(normalized_names.intersection(unreal_limbs)) >= 4
    )
    if explicit_unreal or unreal_signature:
        return "Unreal/MetaHuman"
    topology = core_topology_coverage(armature)
    if topology["ready"]:
        return HRS_GENERIC_TOPOLOGY_LABEL
    return "通用人形"


def is_auto_rig_pro_mixamo_pair(scene):
    source_profile = detect_armature_profile(scene.hrs_source_armature)
    target_profile = detect_armature_profile(scene.hrs_target_armature)
    target_preset = armature_preset_profile(scene.hrs_target_armature)
    target_is_auto_rig = target_profile == "Auto-Rig Pro" or bool(
        target_preset and target_preset["id"] == "auto_rig_pro"
    )
    slot_coverage = mapping_coverage(scene, ensure=False) if hasattr(scene, "hrs_mapping_slots") else {"ready": False}
    source_ready = bool(
        source_profile == "Mixamo"
        or core_topology_coverage(scene.hrs_source_armature)["ready"]
        or slot_coverage["ready"]
    )
    return target_is_auto_rig and source_ready


def auto_rig_pro_runtime_available(scene):
    required_scene_properties = (
        "source_rig",
        "target_rig",
        "arp_retarget_in_place",
    )
    required_operators = (
        "build_bones_list",
        "retarget",
    )
    return bool(
        all(hasattr(scene, name) for name in required_scene_properties)
        and hasattr(bpy.ops, "arp")
        and all(hasattr(bpy.ops.arp, name) for name in required_operators)
    )


def should_use_auto_rig_pro_native(scene):
    return is_auto_rig_pro_mixamo_pair(scene) and auto_rig_pro_runtime_available(scene)


def mapping_coverage(scene, ensure=True):
    if ensure:
        ensure_slots(scene)
    visible = set(visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers))
    core = [role_id for role_id in CORE_REMAP_ROLE_IDS if role_id in visible or role_id in HUMAN_ROLE_BY_ID]
    slots = {slot.role_id: slot for slot in scene.hrs_mapping_slots}
    paired_core = []
    missing_core = []
    for role_id in core:
        slot = slots.get(role_id)
        if slot and slot_pair_valid(scene, slot):
            paired_core.append(role_id)
        else:
            missing_core.append(role_id)
    paired_visible = [
        role_id
        for role_id in visible
        if (slot := slots.get(role_id)) and slot_pair_valid(scene, slot)
    ]
    return {
        "core_total": len(core),
        "core_paired": len(paired_core),
        "core_missing": missing_core,
        "visible_total": len(visible),
        "visible_paired": len(paired_visible),
        "ready": len(missing_core) == 0 and bool(core),
    }


def source_motion_root_bone(armature):
    if not armature or not armature.pose:
        return None
    pose_bones = armature.pose.bones
    for name in HRS_SOURCE_ROOT_BONE_CANDIDATES:
        bone = pose_bones.get(name)
        if bone is not None:
            return bone
    for bone in pose_bones:
        lowered = bone.name.lower()
        if lowered.endswith(":hips") or lowered in {"hips", "root", "pelvis"}:
            return bone
    topology_hips = analyze_humanoid_roles(armature).get("hips")
    if topology_hips and topology_hips.get("score", 0.0) >= HRS_STRUCTURAL_OPTIONAL_MIN_SCORE:
        return pose_bones.get(topology_hips.get("bone_name", ""))
    return None


def pose_bone_world_location(armature, pose_bone):
    return (armature.matrix_world @ pose_bone.matrix).to_translation()


def action_root_motion_summary(scene, armature, action=None):
    summary = {
        "known": False,
        "hasRootMotion": False,
        "delta": 0.0,
        "rootBone": "",
        "threshold": HRS_ROOT_MOTION_THRESHOLD,
        "frames": [],
    }
    if not scene or not armature:
        return summary
    action = action or animation_action_for_armature(armature)
    if not action:
        return summary
    root_bone = source_motion_root_bone(armature)
    if root_bone is None:
        return summary

    start_frame, end_frame = action_frame_range(action, scene)
    frames = sorted({start_frame, (start_frame + end_frame) // 2, end_frame})
    original_frame = scene.frame_current
    original_action = animation_action_for_armature(armature)
    vertical_axis = armature_vertical_axis(armature)
    origin = None
    max_delta = 0.0
    samples = []

    try:
        armature.animation_data_create()
        armature.animation_data.action = action
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            current_root = source_motion_root_bone(armature)
            if current_root is None:
                continue
            location = pose_bone_world_location(armature, current_root)
            if origin is None:
                origin = location.copy()
            delta_sq = 0.0
            for axis in range(3):
                if axis == vertical_axis:
                    continue
                delta_sq += (location[axis] - origin[axis]) ** 2
            delta = math.sqrt(delta_sq)
            max_delta = max(max_delta, delta)
            samples.append({"frame": frame, "delta": delta})
    finally:
        if armature:
            armature.animation_data_create()
            armature.animation_data.action = original_action
        scene.frame_set(original_frame)
        bpy.context.view_layer.update()

    summary["known"] = bool(samples)
    summary["hasRootMotion"] = max_delta >= HRS_ROOT_MOTION_THRESHOLD
    summary["delta"] = max_delta
    summary["rootBone"] = root_bone.name
    summary["frames"] = samples
    return summary


def update_source_motion_state(scene, action=None):
    if action is None and "source_base_action_for_retarget" in globals():
        action = source_base_action_for_retarget(scene.hrs_source_armature)
    summary = action_root_motion_summary(scene, scene.hrs_source_armature, action)
    if hasattr(scene, "hrs_source_root_motion_known"):
        scene.hrs_source_root_motion_known = bool(summary["known"])
    if hasattr(scene, "hrs_source_has_root_motion"):
        scene.hrs_source_has_root_motion = bool(summary["hasRootMotion"])
    if hasattr(scene, "hrs_source_root_motion_delta"):
        scene.hrs_source_root_motion_delta = float(summary["delta"])
    if hasattr(scene, "hrs_source_motion_root_bone"):
        scene.hrs_source_motion_root_bone = summary["rootBone"]
    if (
        summary["known"]
        and not summary["hasRootMotion"]
        and hasattr(scene, "hrs_retarget_keep_in_place")
        and scene.hrs_retarget_keep_in_place
    ):
        scene.hrs_retarget_keep_in_place = False
    return summary


def root_motion_detail_text(summary):
    if not summary["known"]:
        return "原地状态会在执行前自动判断"
    if summary["hasRootMotion"]:
        return "源动作带位移，可切换原地动作"
    return "源动作基本原地，无需额外原地版"


def update_auto_summary(scene, assigned=0):
    source_profile = detect_armature_profile(scene.hrs_source_armature)
    target_profile = detect_armature_profile(scene.hrs_target_armature)
    source_preset = armature_preset_profile(scene.hrs_source_armature)
    target_preset = armature_preset_profile(scene.hrs_target_armature)
    coverage = mapping_coverage(scene)
    motion_summary = update_source_motion_state(scene)
    arp_native_ready = should_use_auto_rig_pro_native(scene)
    preset_route_ready = bool(source_preset and target_preset)
    posture_gate = retarget_posture_gate(scene)
    scene.hrs_source_profile = source_profile
    scene.hrs_target_profile = target_profile
    scene.hrs_can_execute_retarget = bool(
        scene.hrs_source_armature
        and scene.hrs_target_armature
        and (coverage["ready"] or arp_native_ready)
        and posture_gate["passed"]
    )
    if not scene.hrs_source_armature or not scene.hrs_target_armature:
        scene.hrs_auto_summary = "请选择两套人形骨架。"
        scene.hrs_auto_detail = "选择后点击自动识别。"
        return coverage
    resolution = resolved_retarget_source(scene)
    scene.hrs_auto_summary = f"{source_profile} -> {target_profile}"
    if not posture_gate["passed"]:
        scene.hrs_auto_detail = posture_gate["detail"]
        return coverage
    if resolution["chain"]:
        resolved_profile = detect_armature_profile(resolution["source"])
        scene.hrs_auto_detail = (
            f"检测到中间重映射动作，已追溯原始来源：{resolved_profile} -> {target_profile}；"
            "将执行通用自动重映射流程。"
        )
        return coverage
    if arp_native_ready:
        source_route = "预设库" if source_preset else "层级拓扑"
        scene.hrs_auto_detail = (
            f"目标为 Auto-Rig Pro；来源通过{source_route}识别。"
            f"将执行 FK 自动重映射流程；{root_motion_detail_text(motion_summary)}。"
        )
    elif preset_route_ready and coverage["ready"]:
        scene.hrs_auto_detail = (
            f"命中预设库：{source_profile} -> {target_profile}；"
            "将执行通用自动重映射流程。"
        )
    elif coverage["ready"]:
        scene.hrs_auto_detail = (
            f"通过层级特征识别为两套人形骨架；将执行通用自动重映射流程。"
        )
    else:
        scene.hrs_auto_detail = (
            "暂未命中稳定自动流程；请确认两套都是人形骨架。"
        )
    return coverage


def rest_bone_world_direction(armature, bone_name):
    if not armature or not bone_name:
        return None
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        return None
    direction = armature.matrix_world.to_3x3() @ (bone.tail_local - bone.head_local)
    if direction.length <= 1.0e-8:
        return None
    direction.normalize()
    return direction


def semantic_rest_angle_summary(scene, source, target, alignment=None):
    roles = tuple(dict.fromkeys((*CORE_REMAP_ROLE_IDS, "left_shoulder", "right_shoulder")))
    source_map = role_map_for_armature(scene, source, roles=roles)
    target_map = role_map_for_armature(scene, target, roles=roles)
    alignment = alignment or source_target_forward_alignment(scene, source, target)
    rotation = (
        Matrix.Rotation(alignment["angle"], 3, alignment["axis"])
        if alignment.get("applied")
        else Matrix.Identity(3)
    )
    rows = []
    for role_id in roles:
        source_direction = rest_bone_world_direction(source, source_map.get(role_id, ""))
        target_direction = rest_bone_world_direction(target, target_map.get(role_id, ""))
        if source_direction is None or target_direction is None:
            continue
        aligned_source = rotation @ source_direction
        dot = max(-1.0, min(1.0, float(aligned_source.dot(target_direction))))
        rows.append(
            {
                "roleId": role_id,
                "degrees": math.degrees(math.acos(dot)),
                "dot": dot,
            }
        )
    angles = [row["degrees"] for row in rows]
    return {
        "ready": bool(rows),
        "count": len(rows),
        "meanDegrees": sum(angles) / len(angles) if angles else 0.0,
        "maxDegrees": max(angles) if angles else 0.0,
        "roles": rows,
    }


def retarget_pair_analysis(scene, source, target):
    alignment = source_target_forward_alignment(scene, source, target)
    source_height = armature_height(source)
    target_height = armature_height(target)
    scale = target_height / max(source_height, 1.0e-8)
    return {
        "sourceProfile": detect_armature_profile(source),
        "targetProfile": detect_armature_profile(target),
        "sourcePreset": bool(armature_preset_profile(source)),
        "targetPreset": bool(armature_preset_profile(target)),
        "sourcePosture": armature_rest_posture_quality(scene, source),
        "targetPosture": armature_rest_posture_quality(scene, target),
        "forwardAlignment": alignment,
        "restAngles": semantic_rest_angle_summary(scene, source, target, alignment=alignment),
        "sourceHeight": source_height,
        "targetHeight": target_height,
        "heightScale": scale,
    }


def batch_collection_objects(collection):
    if collection is None:
        return []
    return sorted(set(collection.all_objects), key=lambda obj: obj.name.lower())


def batch_collection_audit(scene, collection=None):
    collection = collection or getattr(scene, "hrs_source_collection", None)
    target = scene.hrs_target_armature
    errors = []
    entries = []
    objects = batch_collection_objects(collection)
    if collection is None:
        errors.append("未选择动作集合")
    if target is None:
        errors.append("未选择目标骨架")
    if collection is not None and not objects:
        errors.append("动作集合为空")
    non_armatures = [obj.name for obj in objects if obj.type != "ARMATURE"]
    if non_armatures:
        errors.append("集合包含非骨架对象：" + "、".join(non_armatures[:4]))

    target_core = (
        role_map_for_armature(scene, target, roles=CORE_REMAP_ROLE_IDS)
        if target and target.type == "ARMATURE"
        else {}
    )
    target_quality = armature_rest_posture_quality(scene, target) if target else None
    if target and len(target_core) < len(CORE_REMAP_ROLE_IDS):
        errors.append("目标骨架未通过人形核心结构检查")
    if target_quality and not target_quality["passed"]:
        errors.append("目标骨架静止姿态异常：" + target_quality["issue"])

    for obj in objects:
        if obj.type != "ARMATURE":
            continue
        row_errors = []
        if obj == target:
            row_errors.append("不能把目标骨架放入动作集合")
        action = animation_action_for_armature(obj)
        if action is None or action_fcurve_count(action) == 0:
            row_errors.append("没有有效 Action")
        source_core = role_map_for_armature(scene, obj, roles=CORE_REMAP_ROLE_IDS)
        if len(source_core) < len(CORE_REMAP_ROLE_IDS):
            row_errors.append(
                f"人形核心结构不足：{len(source_core)}/{len(CORE_REMAP_ROLE_IDS)}"
            )
        quality = armature_rest_posture_quality(scene, obj)
        if not quality["passed"]:
            row_errors.append("静止姿态异常：" + quality["issue"])
        analysis = retarget_pair_analysis(scene, obj, target) if target else None
        if analysis and not analysis["forwardAlignment"].get("ready"):
            row_errors.append("无法建立可靠前向")
        entry = {
            "source": obj,
            "action": action,
            "profile": detect_armature_profile(obj),
            "analysis": analysis,
            "errors": row_errors,
        }
        entries.append(entry)
        for error in row_errors:
            errors.append(f"{obj.name}：{error}")

    ready = bool(collection and target and entries and not errors)
    return {
        "ready": ready,
        "collection": collection,
        "target": target,
        "objects": objects,
        "entries": entries,
        "errors": errors,
        "count": len(entries),
        "profiles": [entry["profile"] for entry in entries],
    }


def update_batch_summary(scene):
    audit = batch_collection_audit(scene)
    scene.hrs_batch_ready = bool(audit["ready"])
    scene.hrs_can_execute_retarget = bool(audit["ready"])
    target_profile = detect_armature_profile(scene.hrs_target_armature)
    if audit["ready"]:
        profile_text = "、".join(dict.fromkeys(audit["profiles"]))
        scene.hrs_auto_summary = f"{audit['count']} 个动作 -> {target_profile}"
        scene.hrs_auto_detail = (
            f"{audit['count']}/{audit['count']} 通过集合门禁：{profile_text}；"
            "将逐项执行预设优先、拓扑回退和坐标系自动对齐。"
        )
    else:
        scene.hrs_auto_summary = "批量集合未通过检查"
        scene.hrs_auto_detail = audit["errors"][0] if audit["errors"] else "请选择动作集合和目标骨架。"
    return audit


def ray_aabb_distance(origin, direction, min_corner, max_corner):
    t_min = -1.0e18
    t_max = 1.0e18
    for index in range(3):
        axis_origin = origin[index]
        axis_direction = direction[index]
        if abs(axis_direction) < 1.0e-8:
            if axis_origin < min_corner[index] or axis_origin > max_corner[index]:
                return None
            continue
        inv = 1.0 / axis_direction
        t1 = (min_corner[index] - axis_origin) * inv
        t2 = (max_corner[index] - axis_origin) * inv
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
        if t_min > t_max:
            return None
    if t_max < 0:
        return None
    return max(0.0, t_min)


def armature_world_bounds(armature):
    points = []
    if armature and armature.type == "ARMATURE":
        matrix = armature.matrix_world
        for bone in armature.data.bones:
            points.append(matrix @ bone.head_local)
            points.append(matrix @ bone.tail_local)
    if not points and armature:
        points = [armature.matrix_world @ Vector(corner) for corner in armature.bound_box]
    if not points:
        return None
    min_corner = Vector((min(point[index] for point in points) for index in range(3)))
    max_corner = Vector((max(point[index] for point in points) for index in range(3)))
    span = max((max_corner - min_corner).length, 0.2)
    pad = min(max(span * 0.035, 0.05), 0.35)
    return min_corner - Vector((pad, pad, pad)), max_corner + Vector((pad, pad, pad))


def view3d_pick_context_from_event(context, event):
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        if region is None:
            continue
        if not (region.x <= event.mouse_x <= region.x + region.width):
            continue
        if not (region.y <= event.mouse_y <= region.y + region.height):
            continue
        space = next((item for item in area.spaces if item.type == "VIEW_3D"), None)
        rv3d = getattr(space, "region_3d", None) if space else None
        if rv3d is None:
            continue
        return area, region, space, rv3d, event.mouse_x - region.x, event.mouse_y - region.y
    return None


def armature_from_event(context, event):
    hit = view3d_pick_context_from_event(context, event)
    if hit is None:
        return None
    _area, region, _space, rv3d, mouse_x, mouse_y = hit
    coord = (mouse_x, mouse_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord).normalized()
    best = None
    best_distance = None
    for obj in context.scene.objects:
        if obj.type != "ARMATURE" or obj.hide_get():
            continue
        bounds = armature_world_bounds(obj)
        if bounds is None:
            continue
        distance = ray_aabb_distance(origin, direction, bounds[0], bounds[1])
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best = obj
            best_distance = distance
    return best


def ensure_slots(scene):
    slots = scene.hrs_mapping_slots
    by_id = {slot.role_id: slot for slot in slots}
    for role in HUMAN_ROLES:
        if role["id"] in by_id:
            by_id[role["id"]].label = role["label"]
            continue
        slot = slots.add()
        slot.role_id = role["id"]
        slot.label = role["label"]
        slot.status = "empty"


def slot_for_role(scene, role_id):
    ensure_slots(scene)
    for slot in scene.hrs_mapping_slots:
        if slot.role_id == role_id:
            return slot
    return None


def existing_slot_for_role(scene, role_id):
    for slot in scene.hrs_mapping_slots:
        if slot.role_id == role_id:
            return slot
    return None


def visible_role_set(scene):
    return set(visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers))


def role_label(scene, role_id):
    role = HUMAN_ROLE_BY_ID[role_id]
    if role_id == "neck_01" and scene.hrs_neck_count == 1:
        return "颈"
    if role_id == "spine_01" and scene.hrs_spine_count == 1:
        return "胸/脊柱"
    if role_id.startswith("spine_"):
        index = int(role_id[-2:])
        spine_count = max(1, min(MAX_SPINE_COUNT, int(scene.hrs_spine_count)))
        if index == spine_count:
            return "胸"
        return f"脊{index}"
    return role["label"]


def slot_badge(slot):
    if slot is None or not slot.source_bone and not slot.target_bone:
        return "--"
    if slot.status == "manual":
        return "手"
    if slot.source_bone and slot.target_bone:
        return "OK"
    if slot.status == "candidate":
        return "候"
    return "半"


def assign_selected_bone_to_role(context, role_id):
    ensure_slots(context.scene)
    slot = slot_for_role(context.scene, role_id)
    bone = selected_pose_bone(context)
    if slot is None:
        raise ValueError("找不到人形槽位")
    if bone is None:
        raise ValueError("请先选中一根 Pose/Edit 骨骼")

    selected_armature = selected_armature_object(context)
    if context.scene.hrs_assign_mode == "SOURCE":
        expected_armature = context.scene.hrs_source_armature
        target_label = "动作骨架"
        if expected_armature is None:
            raise ValueError("请先选择动作骨架")
        if selected_armature != expected_armature or not armature_has_bone(expected_armature, bone.name):
            source_name = selected_armature.name if selected_armature else "未知骨架"
            raise ValueError(f"当前写入{target_label}，但选中骨骼来自 {source_name}；请选中 {expected_armature.name} 的骨骼")
        slot.source_bone = bone.name
    else:
        expected_armature = context.scene.hrs_target_armature
        target_label = "目标骨架"
        if expected_armature is None:
            raise ValueError("请先选择目标骨架")
        if selected_armature != expected_armature or not armature_has_bone(expected_armature, bone.name):
            source_name = selected_armature.name if selected_armature else "未知骨架"
            raise ValueError(f"当前写入{target_label}，但选中骨骼来自 {source_name}；请选中 {expected_armature.name} 的骨骼")
        slot.target_bone = bone.name
    slot.status = "manual"
    slot.confidence = 1.0
    slot.note = "manual assignment"
    context.scene.hrs_canvas_active_role = role_id
    return slot


def compact_bone_name(name, limit=18):
    if not name:
        return "-"
    return name if len(name) <= limit else "..." + name[-limit + 3 :]


def compact_ui_status(text, limit=38):
    message = str(text or "").split("；", 1)[0].strip().rstrip("。")
    if len(message) <= limit:
        return message
    return message[: limit - 3] + "..."


def hot_reload_package():
    package_name = __name__
    package = sys.modules.get(package_name)
    if package and hasattr(package, "unregister"):
        package.unregister()

    for module_name in (
        f"{package_name}.preset_catalog",
        f"{package_name}.human_schema",
        f"{package_name}.figure_layout",
        f"{package_name}.matcher",
        f"{package_name}.armature_scan",
    ):
        module = sys.modules.get(module_name)
        if module:
            importlib.reload(module)

    package = importlib.reload(sys.modules[package_name])
    package.register()
    for scene in bpy.data.scenes:
        package.ensure_slots(scene)
    screen = getattr(bpy.context, "screen", None)
    if screen:
        for area in screen.areas:
            area.tag_redraw()
    print("Humanoid Remap Studio hot reloaded")
    return None


def draw_role_button(layout, scene, role_id):
    if role_id is None:
        layout.label(text="")
        return
    slot = existing_slot_for_role(scene, role_id)
    text = f"{slot_badge(slot)} {role_label(scene, role_id)}"
    op = layout.operator("hrs.assign_selected_bone", text=text)
    op.role_id = role_id


def draw_center_role(layout, scene, role_id):
    row = layout.row(align=True)
    row.separator()
    draw_role_button(row, scene, role_id)
    row.separator()


def draw_three_roles(layout, scene, left_role, center_role, right_role):
    row = layout.row(align=True)
    draw_role_button(row, scene, left_role)
    draw_role_button(row, scene, center_role)
    draw_role_button(row, scene, right_role)


def humanoid_icon_dir():
    return Path(__file__).resolve().parent / "icons" / "humanoid"


def humanoid_preview_collection():
    global HRS_PREVIEW_COLLECTION
    if HRS_PREVIEW_COLLECTION is not None:
        return HRS_PREVIEW_COLLECTION

    pcoll = bpy.utils.previews.new()
    icon_dir = humanoid_icon_dir()
    for icon_path in icon_dir.glob("*.png"):
        pcoll.load(icon_path.stem, str(icon_path), "IMAGE")
    HRS_PREVIEW_COLLECTION = pcoll
    return HRS_PREVIEW_COLLECTION


def clear_humanoid_previews():
    global HRS_PREVIEW_COLLECTION
    if HRS_PREVIEW_COLLECTION is not None:
        bpy.utils.previews.remove(HRS_PREVIEW_COLLECTION)
        HRS_PREVIEW_COLLECTION = None


def humanoid_icon_value(icon_name):
    pcoll = humanoid_preview_collection()
    if icon_name in pcoll:
        return pcoll[icon_name].icon_id
    return 0


def humanoid_figure_icon_name(scene):
    neck_count = max(1, min(MAX_NECK_COUNT, int(getattr(scene, "hrs_neck_count", 1))))
    spine_count = max(1, min(MAX_SPINE_COUNT, int(getattr(scene, "hrs_spine_count", 3))))
    return f"figure_clean_n{neck_count}_s{spine_count}"


def humanoid_icon_name(role_id):
    if role_id == "head":
        return "head"
    if role_id.startswith("neck_"):
        return "neck"
    if role_id.startswith("spine_"):
        return "spine"
    if role_id == "hips":
        return "hips"
    if role_id == "left_shoulder":
        return "shoulder_left"
    if role_id == "right_shoulder":
        return "shoulder_right"
    if role_id == "left_upper_arm":
        return "upper_arm_left"
    if role_id == "right_upper_arm":
        return "upper_arm_right"
    if role_id == "left_lower_arm":
        return "lower_arm_left"
    if role_id == "right_lower_arm":
        return "lower_arm_right"
    if role_id == "left_hand":
        return "hand_left"
    if role_id == "right_hand":
        return "hand_right"
    if role_id == "left_upper_leg":
        return "upper_leg_left"
    if role_id == "right_upper_leg":
        return "upper_leg_right"
    if role_id == "left_lower_leg":
        return "lower_leg_left"
    if role_id == "right_lower_leg":
        return "lower_leg_right"
    if role_id == "left_foot":
        return "foot_left"
    if role_id == "right_foot":
        return "foot_right"
    if role_id == "left_toe":
        return "toe_left"
    if role_id == "right_toe":
        return "toe_right"
    for finger_id in ("thumb", "index", "middle", "ring", "pinky"):
        if role_id.endswith(f"_{finger_id}"):
            return finger_id
    return "spine"


def panel_button_status_text(scene, role_id):
    badge = slot_badge(existing_slot_for_role(scene, role_id))
    return "" if badge == "--" else badge


def draw_humanoid_icon_button(layout, scene, role_id, scale_y=2.0):
    row = layout.row(align=True)
    row.scale_y = scale_y
    active = role_id == getattr(scene, "hrs_canvas_active_role", "")
    op = row.operator(
        "hrs.assign_selected_bone",
        text=panel_button_status_text(scene, role_id),
        icon_value=humanoid_icon_value(humanoid_icon_name(role_id)),
        emboss=True,
        depress=active,
    )
    op.role_id = role_id


def draw_humanoid_icon_stack(layout, scene, role_ids, scale_y=1.65):
    column = layout.column(align=True)
    for role_id in role_ids:
        draw_humanoid_icon_button(column, scene, role_id, scale_y)


def draw_panel_finger_row(layout, scene, side):
    prefix = "left" if side == "left" else "right"
    side_text = "左手" if side == "left" else "右手"
    layout.label(text=side_text)
    row = layout.row(align=True)
    row.scale_y = 1.2
    for finger_id in ("thumb", "index", "middle", "ring", "pinky"):
        role_id = f"{prefix}_{finger_id}"
        active = role_id == getattr(scene, "hrs_canvas_active_role", "")
        op = row.operator(
            "hrs.assign_selected_bone",
            text="",
            icon_value=humanoid_icon_value(finger_id),
            emboss=True,
            depress=active,
        )
        op.role_id = role_id


def draw_humanoid_empty_cell(layout, scale_y=1.0):
    row = layout.row(align=True)
    row.scale_y = scale_y
    row.label(text="")


def draw_humanoid_role_cell(layout, scene, role_id, scale_y=1.6):
    if role_id:
        draw_humanoid_icon_button(layout, scene, role_id, scale_y=scale_y)
    else:
        draw_humanoid_empty_cell(layout, scale_y=scale_y)


def draw_panel_centered_role(layout, scene, role_id, scale_y=1.8):
    row = layout.row(align=True)
    draw_humanoid_role_cell(row.column(align=True), scene, None, scale_y=scale_y)
    draw_humanoid_role_cell(row.column(align=True), scene, role_id, scale_y=scale_y)
    draw_humanoid_role_cell(row.column(align=True), scene, None, scale_y=scale_y)


def draw_panel_role_stack(layout, scene, role_ids, scale_y=1.35):
    column = layout.column(align=True)
    for role_id in role_ids:
        draw_humanoid_role_cell(column, scene, role_id, scale_y=scale_y)


def native_figure_icon_scale():
    region = getattr(bpy.context, "region", None)
    width = getattr(region, "width", 300) if region else 300
    return max(HRS_NATIVE_FIGURE_MIN_SCALE, min(HRS_NATIVE_FIGURE_MAX_SCALE, (width - 82) / 32.0))


def draw_panel_native_figure(layout, scene):
    row = layout.row(align=True)
    row.alignment = "CENTER"
    icon_value = humanoid_icon_value(humanoid_figure_icon_name(scene))
    if icon_value:
        row.template_icon(icon_value=icon_value, scale=native_figure_icon_scale())
    else:
        row.label(text="人形图加载失败")


def draw_panel_humanoid_button_grid(layout, scene):
    figure = layout.column(align=True)
    figure.scale_y = 1.0
    figure.prop(scene, "hrs_show_fingers", text="显示手指槽位")

    draw_panel_centered_role(figure, scene, "head", scale_y=2.15)
    for role_id in neck_roles(scene.hrs_neck_count):
        draw_panel_centered_role(figure, scene, role_id, scale_y=0.9)

    body = figure.row(align=True)
    left_arm = body.column(align=True)
    center = body.column(align=True)
    right_arm = body.column(align=True)

    draw_panel_role_stack(
        left_arm,
        scene,
        ["left_shoulder", "left_upper_arm", "left_lower_arm", "left_hand"],
        scale_y=1.35,
    )
    draw_panel_role_stack(center, scene, spine_roles(scene.hrs_spine_count), scale_y=1.35)
    draw_humanoid_role_cell(center, scene, "hips", scale_y=1.15)
    draw_panel_role_stack(
        right_arm,
        scene,
        ["right_shoulder", "right_upper_arm", "right_lower_arm", "right_hand"],
        scale_y=1.35,
    )

    legs = figure.row(align=True)
    draw_panel_role_stack(
        legs.column(align=True),
        scene,
        ["left_upper_leg", "left_lower_leg", "left_foot", "left_toe"],
        scale_y=1.35,
    )
    draw_humanoid_empty_cell(legs.column(align=True), scale_y=1.35)
    draw_panel_role_stack(
        legs.column(align=True),
        scene,
        ["right_upper_leg", "right_lower_leg", "right_foot", "right_toe"],
        scale_y=1.35,
    )

    if scene.hrs_show_fingers:
        fingers = figure.row(align=True)
        draw_panel_finger_row(fingers.column(align=True), scene, "left")
        draw_humanoid_empty_cell(fingers.column(align=True), scale_y=1.2)
        draw_panel_finger_row(fingers.column(align=True), scene, "right")


def draw_panel_humanoid(layout, scene):
    if HRS_PANEL_EMBEDDED_CLICK_ENABLED:
        mark_panel_figure_widget_visible()
        canvas_box = layout.box()
        canvas_box.scale_y = 0.95
        for _index in range(panel_canvas_placeholder_rows(scene)):
            canvas_box.label(text="")
        return

    open_row = layout.row(align=True)
    open_row.scale_y = 1.25
    open_row.operator("hrs.open_humanoid_canvas", text="打开人形校正面板", icon="OUTLINER_OB_ARMATURE")
    if scene.hrs_canvas_active_role:
        layout.label(text=f"最近部位: {canvas_short_label(scene, scene.hrs_canvas_active_role)}")

    toggle = layout.row(align=True)
    show_buttons = getattr(scene, "hrs_show_native_role_buttons", False)
    icon = "TRIA_DOWN" if show_buttons else "TRIA_RIGHT"
    toggle.prop(scene, "hrs_show_native_role_buttons", text="详细校正按钮", icon=icon, emboss=False)
    if show_buttons:
        draw_panel_humanoid_button_grid(layout, scene)


def mark_panel_figure_widget_visible():
    region = getattr(bpy.context, "region", None)
    if region is None or getattr(region, "type", "") != "UI":
        return
    HRS_PANEL_WIDGET_STATE["region"] = region.as_pointer()
    HRS_PANEL_WIDGET_STATE["seen_at"] = time.monotonic()


def panel_figure_widget_is_live(region):
    if not HRS_PANEL_EMBEDDED_CLICK_ENABLED:
        return False
    if region is None or getattr(region, "type", "") != "UI":
        return False
    if HRS_PANEL_WIDGET_STATE.get("region") != region.as_pointer():
        return False
    return time.monotonic() - HRS_PANEL_WIDGET_STATE.get("seen_at", 0.0) <= HRS_PANEL_WIDGET_TTL


def clamp_panel_canvas_height(value):
    return max(HRS_PANEL_MIN_HEIGHT, min(HRS_PANEL_MAX_HEIGHT, int(value)))


def panel_canvas_height(scene):
    return clamp_panel_canvas_height(getattr(scene, "hrs_panel_canvas_height", HRS_PANEL_DEFAULT_HEIGHT))


def panel_canvas_placeholder_rows(scene):
    return max(9, min(30, round(panel_canvas_height(scene) / 30)))


def panel_figure_bounds(region, scene=None):
    height = panel_canvas_height(scene) if scene is not None else HRS_PANEL_DEFAULT_HEIGHT
    width = min(max(260, region.width - 30), 640)
    x0 = (region.width - width) * 0.5
    y1 = region.height - HRS_PANEL_TOP_OFFSET
    y0 = y1 - height
    return x0, y0, width, height


def canvas_point_from_fitted_uv(u, v):
    left, top, right, bottom = HRS_CANVAS_FIT_BOUNDS
    return (left + u * (right - left), top + v * (bottom - top))


def canvas_fit_aspect():
    left, top, right, bottom = HRS_CANVAS_FIT_BOUNDS
    return (right - left) / max(0.001, bottom - top)


def canvas_view_rect(rect):
    x, y, width, height = rect
    content_x = x + HRS_PANEL_CANVAS_PAD_X
    content_y = y + HRS_PANEL_CANVAS_PAD_BOTTOM
    content_width = max(1, width - HRS_PANEL_CANVAS_PAD_X * 2)
    content_height = max(1, height - HRS_PANEL_CANVAS_PAD_TOP - HRS_PANEL_CANVAS_PAD_BOTTOM)
    aspect = canvas_fit_aspect()
    view_width = content_width
    view_height = view_width / aspect
    if view_height > content_height:
        view_height = content_height
        view_width = view_height * aspect
    view_x = content_x + (content_width - view_width) * 0.5
    view_y = content_y + (content_height - view_height) * 0.5
    return view_x, view_y, view_width, view_height


def point_in_canvas_fit_bounds(point):
    left, top, right, bottom = HRS_CANVAS_FIT_BOUNDS
    return left <= point[0] <= right and top <= point[1] <= bottom


def role_from_panel_figure_uv(scene, u, v):
    # u/v are normalized image coordinates, with v=0 at the top of the figure.
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None
    point = canvas_point_from_fitted_uv(u, v)
    if not point_in_canvas_fit_bounds(point):
        return None
    return figure_role_at(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers, point)


def panel_ui_event_position(context, event):
    for area in context.screen.areas:
        if area.type != "VIEW_3D":
            continue
        ui_region = next((region for region in area.regions if region.type == "UI"), None)
        if not ui_region:
            continue
        if not (ui_region.x <= event.mouse_x <= ui_region.x + ui_region.width):
            continue
        if not (ui_region.y <= event.mouse_y <= ui_region.y + ui_region.height):
            continue
        if not panel_figure_widget_is_live(ui_region):
            return None
        return ui_region, event.mouse_x - ui_region.x, event.mouse_y - ui_region.y
    return None


def panel_resize_handle_rects(region, scene):
    x0, y0, width, _height = panel_figure_bounds(region, scene)
    center_x = x0 + width * 0.5
    grip_width = min(92, max(56, width * 0.18))
    return (
        (center_x - grip_width * 0.5, y0 + 5, center_x + grip_width * 0.5, y0 + 18),
        (center_x - grip_width * 0.68, y0 - 42, center_x + grip_width * 0.68, y0 - 20),
    )


def panel_resize_handle_from_event(context, event):
    hit = panel_ui_event_position(context, event)
    if hit is None:
        return None
    ui_region, rx, ry = hit
    for rect in panel_resize_handle_rects(ui_region, context.scene):
        x0, y0, x1, y1 = rect
        if x0 <= rx <= x1 and y0 <= ry <= y1:
            return ui_region
    return None


def panel_figure_role_from_event(context, event):
    hit = panel_ui_event_position(context, event)
    if hit is None:
        return None
    ui_region, rx, ry = hit
    rect = panel_figure_bounds(ui_region, context.scene)
    x0, y0, width, height = rect
    if not (x0 <= rx <= x0 + width and y0 <= ry <= y0 + height):
        return None
    point = canvas_from_screen(rect, rx, ry)
    if not point_in_canvas_fit_bounds(point):
        return None
    return figure_role_at(context.scene.hrs_neck_count, context.scene.hrs_spine_count, context.scene.hrs_show_fingers, point)


def canvas_shader():
    global HRS_CANVAS_SHADER
    if HRS_CANVAS_SHADER is None:
        HRS_CANVAS_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return HRS_CANVAS_SHADER


def canvas_short_label(scene, role_id):
    labels = {
        "head": "头",
        "hips": "髋",
        "left_shoulder": "左肩",
        "right_shoulder": "右肩",
        "left_upper_arm": "左大臂",
        "right_upper_arm": "右大臂",
        "left_lower_arm": "左小臂",
        "right_lower_arm": "右小臂",
        "left_hand": "左手",
        "right_hand": "右手",
        "left_upper_leg": "左大腿",
        "right_upper_leg": "右大腿",
        "left_lower_leg": "左小腿",
        "right_lower_leg": "右小腿",
        "left_foot": "左脚",
        "right_foot": "右脚",
        "left_toe": "左脚趾",
        "right_toe": "右脚趾",
        "left_thumb": "左拇",
        "left_index": "左食",
        "left_middle": "左中",
        "left_ring": "左无",
        "left_pinky": "左小",
        "right_thumb": "右拇",
        "right_index": "右食",
        "right_middle": "右中",
        "right_ring": "右无",
        "right_pinky": "右小",
    }
    if role_id.startswith("neck_"):
        return "颈" if scene.hrs_neck_count == 1 else f"颈{int(role_id[-2:])}"
    if role_id.startswith("spine_"):
        index = int(role_id[-2:])
        spine_count = max(1, min(MAX_SPINE_COUNT, int(scene.hrs_spine_count)))
        if scene.hrs_spine_count == 1:
            return "胸/脊"
        if index == spine_count:
            return "胸"
        return f"脊{index}"
    return labels.get(role_id, role_label(scene, role_id))


def canvas_rect(region):
    region_width = max(1, region.width)
    region_height = max(1, region.height)
    height = min(560, max(380, int(region_height * 0.86)))
    height = min(height, region_height - 36) if region_height > 420 else int(region_height * 0.92)
    width = int(height * 0.62)
    width = min(width, max(240, region_width - 32))
    height = int(width / 0.62)
    x = int(region_width * 0.45 - width * 0.5)
    x = max(16, min(x, region_width - width - 24))
    y = max(18, int((region_height - height) * 0.5))
    return x, y, width, height


def clamp_float_canvas_rect(region, x, y, width, height):
    region_width = max(1, region.width)
    region_height = max(1, region.height)
    max_width = min(HRS_FLOAT_CANVAS_MAX_WIDTH, max(HRS_FLOAT_CANVAS_MIN_WIDTH, region_width - 24))
    max_height = min(HRS_FLOAT_CANVAS_MAX_HEIGHT, max(HRS_FLOAT_CANVAS_MIN_HEIGHT, region_height - 24))
    width = max(HRS_FLOAT_CANVAS_MIN_WIDTH, min(max_width, int(width)))
    height = max(HRS_FLOAT_CANVAS_MIN_HEIGHT, min(max_height, int(height)))
    x = max(12, min(int(x), region_width - width - 12))
    y = max(12, min(int(y), region_height - height - 12))
    return x, y, width, height


def default_float_canvas_rect(region):
    region_width = max(1, region.width)
    region_height = max(1, region.height)
    height = min(680, max(500, int(region_height * 0.76)))
    width = min(380, max(320, int(height * 0.58)))
    x = 36
    y = max(24, int((region_height - height) * 0.5))
    return clamp_float_canvas_rect(region, x, y, width, height)


def scene_float_canvas_rect(scene):
    return (
        int(getattr(scene, "hrs_canvas_x", -1)),
        int(getattr(scene, "hrs_canvas_y", -1)),
        int(getattr(scene, "hrs_canvas_width", 360)),
        int(getattr(scene, "hrs_canvas_height", 600)),
    )


def set_float_canvas_rect(scene, rect):
    scene.hrs_canvas_x, scene.hrs_canvas_y, scene.hrs_canvas_width, scene.hrs_canvas_height = [int(value) for value in rect]


def float_canvas_rect(region, scene):
    x, y, width, height = scene_float_canvas_rect(scene)
    if x < 0 or y < 0:
        rect = default_float_canvas_rect(region)
        set_float_canvas_rect(scene, rect)
        return rect
    rect = clamp_float_canvas_rect(region, x, y, width, height)
    if rect != (x, y, width, height):
        set_float_canvas_rect(scene, rect)
    return rect


def float_canvas_title_rect(rect):
    x, y, width, height = rect
    return x, y + height - 42, x + width, y + height


def float_canvas_close_rect(rect):
    x, y, width, height = rect
    size = 24
    pad = 9
    return x + width - pad - size, y + height - pad - size, x + width - pad, y + height - pad


def float_canvas_resize_rect(rect):
    x, y, width, _height = rect
    return x + width - 34, y, x + width, y + 34


def point_in_pixel_rect(rect, px, py):
    x0, y0, x1, y1 = rect
    return x0 <= px <= x1 and y0 <= py <= y1


def float_canvas_hit_part(rect, mouse_x, mouse_y):
    x, y, width, height = rect
    if not (x <= mouse_x <= x + width and y <= mouse_y <= y + height):
        return None
    if point_in_pixel_rect(float_canvas_close_rect(rect), mouse_x, mouse_y):
        return "close"
    if point_in_pixel_rect(float_canvas_resize_rect(rect), mouse_x, mouse_y):
        return "resize"
    if point_in_pixel_rect(float_canvas_title_rect(rect), mouse_x, mouse_y):
        return "drag"
    return "body"


def fitted_uv_from_canvas_point(point):
    left, top, right, bottom = HRS_CANVAS_FIT_BOUNDS
    return ((point[0] - left) / (right - left), (point[1] - top) / (bottom - top))


def screen_from_canvas(rect, point):
    x, y, width, height = canvas_view_rect(rect)
    u, v = fitted_uv_from_canvas_point(point)
    return (x + u * width, y + (1.0 - v) * height, 0.0)


def canvas_from_screen(rect, mouse_x, mouse_y):
    x, y, width, height = canvas_view_rect(rect)
    u = (mouse_x - x) / width
    v = 1.0 - ((mouse_y - y) / height)
    return canvas_point_from_fitted_uv(u, v)


def interp(a, b, t):
    return a + (b - a) * t


def torso_width_at(y_norm):
    points = [
        (0.25, 0.35, 0.65),
        (0.42, 0.40, 0.60),
        (0.58, 0.37, 0.63),
    ]
    for index in range(len(points) - 1):
        y0, left0, right0 = points[index]
        y1, left1, right1 = points[index + 1]
        if y0 <= y_norm <= y1:
            t = (y_norm - y0) / max(0.001, y1 - y0)
            return interp(left0, left1, t), interp(right0, right1, t)
    return points[-1][1], points[-1][2]


def add_canvas_shape(shapes, scene, role_id, kind, points=None, center=None, radius=0.0, label=None):
    if role_id not in visible_role_set(scene):
        return
    shapes.append(
        {
            "role_id": role_id,
            "kind": kind,
            "points": points or [],
            "center": center,
            "radius": radius,
            "label": canvas_short_label(scene, role_id) if label is None else label,
        }
    )


def add_canvas_finger_segments(shapes, scene, role_id, x, y, width, height, lean=0.0):
    gap = height * 0.075
    segment_height = (height - gap * 2.0) / 3.0
    for segment_index in range(3):
        y0 = y + segment_index * (segment_height + gap)
        y1 = y0 + segment_height
        dx0 = lean * segment_index
        dx1 = lean * (segment_index + 1)
        add_canvas_shape(
            shapes,
            scene,
            role_id,
            "poly",
            points=[
                (x + dx0, y0),
                (x + width + dx0, y0),
                (x + width + dx1, y1),
                (x + dx1, y1),
            ],
            label=canvas_short_label(scene, role_id) if segment_index == 1 else "",
        )


def build_humanoid_canvas_shapes(scene):
    shapes = []
    for shape in figure_layout_shapes(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers):
        label = canvas_short_label(scene, shape["role_id"]) if shape.get("label", True) else ""
        add_canvas_shape(
            shapes,
            scene,
            shape["role_id"],
            shape["kind"],
            points=shape.get("points"),
            center=shape.get("center"),
            radius=shape.get("radius", 0.0),
            label=label,
        )
    return shapes


def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x0, y0 = polygon[index]
        x1, y1 = polygon[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            denom = y1 - y0
            if abs(denom) < 0.00001:
                continue
            if x < (x1 - x0) * (y - y0) / denom + x0:
                inside = not inside
    return inside


def view3d_window_region(context):
    area = getattr(context, "area", None)
    if area is None or area.type != "VIEW_3D":
        return None
    return next((region for region in area.regions if region.type == "WINDOW"), None)


def event_window_region_xy(context, event):
    region = view3d_window_region(context)
    if region is None:
        return None
    return region, event.mouse_x - region.x, event.mouse_y - region.y


def point_in_shape(point, shape):
    if shape["kind"] == "circle":
        center = shape["center"]
        return math.dist(point, center) <= shape["radius"]
    return point_in_polygon(point, shape["points"])


def polygon_center(shape):
    if shape["kind"] == "circle":
        return shape["center"]
    points = shape["points"]
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def humanoid_role_at_region(scene, region, mouse_x, mouse_y):
    if region is None:
        return None
    rect = float_canvas_rect(region, scene)
    x, y, width, height = rect
    if not (x <= mouse_x <= x + width and y <= mouse_y <= y + height):
        return None
    point = canvas_from_screen(rect, mouse_x, mouse_y)
    if not point_in_canvas_fit_bounds(point):
        return None
    for shape in reversed(build_humanoid_canvas_shapes(scene)):
        if point_in_shape(point, shape):
            return shape["role_id"]
    return None


def humanoid_role_at(context, mouse_x, mouse_y):
    region = getattr(context, "region", None)
    if region is None or getattr(region, "type", "") != "WINDOW":
        region = view3d_window_region(context)
    return humanoid_role_at_region(context.scene, region, mouse_x, mouse_y)


def role_color_family(role_id):
    if role_id.startswith("left_"):
        return "left"
    if role_id.startswith("right_"):
        return "right"
    return "center"


def role_base_canvas_color(role_id):
    family = role_color_family(role_id)
    if family == "left":
        return HRS_CANVAS_LEFT_COLOR
    if family == "right":
        return HRS_CANVAS_RIGHT_COLOR
    return HRS_CANVAS_CENTER_COLOR


def mix_canvas_color(color, tint, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(color[index] * (1.0 - amount) + tint[index] * amount for index in range(4))


def role_canvas_color(scene, role_id):
    slot = existing_slot_for_role(scene, role_id)
    active = role_id == getattr(scene, "hrs_canvas_active_role", "")
    if active:
        return HRS_CANVAS_SELECTED_COLOR
    base_color = role_base_canvas_color(role_id)
    if slot is None:
        return mix_canvas_color(base_color, HRS_CANVAS_MUTED_COLOR, 0.48)
    source = bool(slot.source_bone)
    target = bool(slot.target_bone)
    current = source if scene.hrs_assign_mode == "SOURCE" else target
    if source and target:
        return mix_canvas_color(base_color, (0.94, 0.94, 0.88, 0.98), 0.10)
    if slot.status == "manual" and current:
        return base_color
    if current:
        return mix_canvas_color(base_color, (0.94, 0.94, 0.88, 0.98), 0.24)
    if slot.status == "candidate":
        return mix_canvas_color(base_color, HRS_CANVAS_MUTED_COLOR, 0.18)
    return mix_canvas_color(base_color, HRS_CANVAS_MUTED_COLOR, 0.52)


def draw_canvas_batch(vertices, mode, color):
    shader = canvas_shader()
    batch = batch_for_shader(shader, mode, {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_canvas_polygon(rect, points, fill_color, line_color=(0.86, 0.86, 0.82, 0.38)):
    screen_points = [screen_from_canvas(rect, point) for point in points]
    draw_canvas_batch(screen_points, "TRI_FAN", fill_color)
    draw_canvas_batch([*screen_points, screen_points[0]], "LINE_STRIP", line_color)


def draw_canvas_circle(rect, center, radius, fill_color, line_color=(0.86, 0.86, 0.82, 0.38)):
    fan = [screen_from_canvas(rect, center)]
    outline = []
    for index in range(40):
        angle = math.tau * index / 40
        point = (center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius)
        fan.append(screen_from_canvas(rect, point))
        outline.append(screen_from_canvas(rect, point))
    draw_canvas_batch(fan, "TRI_FAN", fill_color)
    draw_canvas_batch([*outline, outline[0]], "LINE_STRIP", line_color)


def shifted_shape_points(shape, dx=0.004, dy=0.006):
    if shape["kind"] == "circle":
        center = shape["center"]
        return {**shape, "center": (center[0] + dx, center[1] + dy)}
    return {**shape, "points": [(point[0] + dx, point[1] + dy) for point in shape["points"]]}


def draw_canvas_shape(rect, shape, fill_color, line_color=(0.86, 0.86, 0.82, 0.38)):
    if shape["kind"] == "circle":
        draw_canvas_circle(rect, shape["center"], shape["radius"], fill_color, line_color)
    else:
        draw_canvas_polygon(rect, shape["points"], fill_color, line_color)


def draw_canvas_text(text, x, y, size=11, color=(1.0, 1.0, 1.0, 0.96), center=True):
    font_id = 0
    blf.size(font_id, size)
    blf.color(font_id, *color)
    width, height = blf.dimensions(font_id, text)
    draw_x = x - width * 0.5 if center else x
    draw_y = y - height * 0.5 if center else y
    blf.position(font_id, draw_x, draw_y, 0)
    blf.draw(font_id, text)


def draw_pixel_rect(rect, fill_color, line_color=None):
    x0, y0, x1, y1 = rect
    vertices = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
    draw_canvas_batch(vertices, "TRI_FAN", fill_color)
    if line_color is not None:
        draw_canvas_batch([*vertices, vertices[0]], "LINE_STRIP", line_color)


def draw_panel_resize_handles(region, scene):
    active = HRS_PANEL_RESIZE_STATE.get("active")
    inner, _outer = panel_resize_handle_rects(region, scene)
    color = (0.95, 0.54, 0.18, 0.95) if active else (0.72, 0.72, 0.68, 0.62)
    outline = (0.08, 0.08, 0.08, 0.70) if active else (0.02, 0.02, 0.02, 0.55)
    x0, y0, x1, y1 = inner
    grip = (x0 + 8, y0 + 5, x1 - 8, y1 - 5)
    draw_pixel_rect(grip, color, outline)


def draw_float_canvas_frame(rect, scene):
    x, y, width, height = rect
    draw_canvas_batch(
        [(x, y, 0), (x + width, y, 0), (x + width, y + height, 0), (x, y + height, 0)],
        "TRI_FAN",
        (0.045, 0.045, 0.045, 0.91),
    )
    title_rect = float_canvas_title_rect(rect)
    draw_pixel_rect(title_rect, (0.14, 0.14, 0.14, 0.96), (0.02, 0.02, 0.02, 0.70))
    close_rect = float_canvas_close_rect(rect)
    draw_pixel_rect(close_rect, (0.27, 0.09, 0.08, 0.96), (0.03, 0.03, 0.03, 0.72))
    cx0, cy0, cx1, cy1 = close_rect
    close_pad = 6
    draw_canvas_batch(
        [(cx0 + close_pad, cy0 + close_pad, 0), (cx1 - close_pad, cy1 - close_pad, 0)],
        "LINE_STRIP",
        (0.96, 0.96, 0.92, 0.98),
    )
    draw_canvas_batch(
        [(cx0 + close_pad, cy1 - close_pad, 0), (cx1 - close_pad, cy0 + close_pad, 0)],
        "LINE_STRIP",
        (0.96, 0.96, 0.92, 0.98),
    )
    draw_canvas_batch(
        [(x, y, 0), (x + width, y, 0), (x + width, y + height, 0), (x, y + height, 0), (x, y, 0)],
        "LINE_STRIP",
        (0.85, 0.85, 0.85, 0.72),
    )

    mode_label = "动作骨骼" if scene.hrs_assign_mode == "SOURCE" else "目标骨骼"
    selected = selected_pose_bone(bpy.context)
    selected_name = selected.name if selected else "未选中"
    draw_canvas_text("人形骨骼校正", x + 14, y + height - 22, size=13, center=False)
    draw_canvas_text(f"校正: {mode_label}  当前: {selected_name}", x + 14, y + height - 39, size=10, color=(0.82, 0.82, 0.82, 0.92), center=False)

    bottom_y = y + 18
    draw_canvas_text("拖动标题栏移动 / 右下角缩放 / 点击身体块写入 / X 或 ESC 关闭", x + width * 0.5, bottom_y, size=10, color=(0.82, 0.82, 0.82, 0.92))
    handle = float_canvas_resize_rect(rect)
    active_resize = HRS_FLOAT_CANVAS_STATE.get("action") == "resize"
    handle_color = (0.95, 0.54, 0.18, 0.96) if active_resize else (0.72, 0.72, 0.68, 0.68)
    hx0, hy0, hx1, hy1 = handle
    draw_canvas_batch(
        [(hx1 - 7, hy0 + 7, 0), (hx1 - 7, hy1 - 8, 0), (hx0 + 8, hy0 + 7, 0)],
        "TRI_FAN",
        handle_color,
    )


def draw_humanoid_shapes(rect, scene, label_size_body=10, label_size_finger=8, show_labels=True):
    shapes = build_humanoid_canvas_shapes(scene)
    for shape in shapes:
        draw_canvas_shape(rect, shifted_shape_points(shape), (0.02, 0.02, 0.02, 0.32), (0.02, 0.02, 0.02, 0.0))

    for shape in shapes:
        color = role_canvas_color(scene, shape["role_id"])
        outline = (0.86, 0.86, 0.82, 0.38)
        if shape["role_id"] == getattr(scene, "hrs_canvas_active_role", ""):
            outline = (1.0, 0.78, 0.30, 0.98)
        draw_canvas_shape(rect, shape, color, outline)

        if show_labels and shape["label"]:
            center = screen_from_canvas(rect, polygon_center(shape))
            label_size = label_size_finger if shape["role_id"] in FINGER_ROLE_IDS else label_size_body
            draw_canvas_text(shape["label"], center[0], center[1], size=label_size)


def draw_panel_humanoid_widget():
    context = bpy.context
    region = getattr(context, "region", None)
    scene = getattr(context, "scene", None)
    if region is None or scene is None or getattr(region, "type", "") != "UI":
        return
    if not hasattr(scene, "hrs_mapping_slots"):
        return
    if not panel_figure_widget_is_live(region):
        return

    rect = panel_figure_bounds(region, scene)
    gpu.state.blend_set("ALPHA")
    try:
        # The real Blender panel already draws the box behind this placeholder;
        # keep the GPU layer transparent so the figure reads as part of the panel.
        draw_humanoid_shapes(rect, scene, label_size_body=9, label_size_finger=6, show_labels=False)
        draw_panel_resize_handles(region, scene)
    finally:
        gpu.state.blend_set("NONE")


def draw_humanoid_canvas():
    context = bpy.context
    region = getattr(context, "region", None)
    scene = getattr(context, "scene", None)
    if region is None or scene is None:
        return
    rect = float_canvas_rect(region, scene)
    gpu.state.blend_set("ALPHA")
    try:
        draw_float_canvas_frame(rect, scene)
        draw_humanoid_shapes(rect, scene, show_labels=False)
    finally:
        gpu.state.blend_set("NONE")


def clear_humanoid_canvas_handlers():
    HRS_FLOAT_CANVAS_STATE.update({"action": None, "start_mouse": (0, 0), "start_rect": (0, 0, 0, 0)})
    while HRS_CANVAS_HANDLERS:
        handler = HRS_CANVAS_HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
        except ValueError:
            pass


def clear_humanoid_panel_draw_handlers():
    while HRS_PANEL_DRAW_HANDLERS:
        handler = HRS_PANEL_DRAW_HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "UI")
        except ValueError:
            pass


def ensure_humanoid_panel_draw_handler():
    if HRS_PANEL_DRAW_HANDLERS:
        return
    handler = bpy.types.SpaceView3D.draw_handler_add(
        draw_panel_humanoid_widget,
        (),
        "UI",
        "POST_PIXEL",
    )
    HRS_PANEL_DRAW_HANDLERS.append(handler)


class HRSMappingSlot(PropertyGroup):
    role_id: StringProperty(name="Role Id")
    label: StringProperty(name="Label")
    source_bone: StringProperty(name="Source Bone")
    target_bone: StringProperty(name="Target Bone")
    status: StringProperty(name="Status", default="empty")
    confidence: FloatProperty(name="Confidence", default=0.0, min=0.0, max=1.0)
    note: StringProperty(name="Note")


class HRS_OT_init_slots(Operator):
    bl_idname = "hrs.init_slots"
    bl_label = "初始化人形槽位"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_slots(context.scene)
        return {"FINISHED"}


class HRS_OT_assign_selected_bone(Operator):
    bl_idname = "hrs.assign_selected_bone"
    bl_label = "指认到该部位"
    bl_options = {"REGISTER", "UNDO"}

    role_id: StringProperty()

    def execute(self, context):
        try:
            assign_selected_bone_to_role(context, self.role_id)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class HRS_OT_pick_armature(Operator):
    bl_idname = "hrs.pick_armature"
    bl_label = "吸取骨架"
    bl_description = "优先使用当前选中的骨架/骨骼；没有合法选择时，进入吸管模式在 3D 视图中点选骨架"
    bl_options = {"REGISTER", "UNDO"}

    target: EnumProperty(
        name="目标",
        items=[
            ("SOURCE", "动作骨架", "写入动作骨架"),
            ("TARGET", "目标骨架", "写入目标骨架"),
        ],
        default="SOURCE",
    )

    def _assign(self, context, armature):
        set_scene_armature(context.scene, self.target, armature)
        update_auto_summary(context.scene)
        label = "动作骨架" if self.target == "SOURCE" else "目标骨架"
        self.report({"INFO"}, f"{label}: {armature.name}")
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        return {"FINISHED"}

    def execute(self, context):
        armature = selected_armature_object(context)
        if not armature:
            self.report({"WARNING"}, "当前没有选中骨架或骨骼")
            return {"CANCELLED"}
        return self._assign(context, armature)

    def invoke(self, context, _event):
        armature = selected_armature_object(context)
        if armature:
            return self._assign(context, armature)
        try:
            context.window.cursor_set("EYEDROPPER")
        except Exception:
            pass
        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "请在 3D 视图中点击要使用的骨架，ESC 或右键取消")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            try:
                context.window.cursor_set("DEFAULT")
            except Exception:
                pass
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            armature = armature_from_event(context, event)
            if armature:
                try:
                    context.window.cursor_set("DEFAULT")
                except Exception:
                    pass
                return self._assign(context, armature)
            self.report({"WARNING"}, "这里没有吸取到骨架，请点骨架区域或按 ESC 取消")
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}


def animation_action_for_armature(armature):
    animation_data = armature.animation_data if armature else None
    return animation_data.action if animation_data else None


def action_fcurves(action):
    if not action:
        return []
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    curves = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                curves.extend(list(getattr(channelbag, "fcurves", [])))
    return curves


def action_frame_range(action, scene):
    if action:
        range_value = getattr(action, "frame_range", None)
        if range_value is None:
            range_value = getattr(action, "curve_frame_range", None)
        if range_value:
            start, end = range_value
            start = int(math.floor(start))
            end = int(math.ceil(end))
            if end >= start:
                return start, end
    return int(scene.frame_start), int(scene.frame_end)


def safe_action_name(text):
    cleaned = "".join(char if char.isalnum() or char in "._- " else "_" for char in text)
    cleaned = "_".join(cleaned.split())
    return cleaned[:96] or "Retarget_Action"


def escaped_pose_bone_data_path(bone_name, suffix):
    escaped = bone_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'pose.bones["{escaped}"].{suffix}'


def armature_height(armature):
    if not armature or not armature.data.bones:
        return 1.0
    points = []
    for bone in armature.data.bones:
        points.append(bone.head_local)
        points.append(bone.tail_local)
    spans = []
    for axis in range(3):
        values = [point[axis] for point in points]
        spans.append(max(values) - min(values))
    height = max(spans)
    return height if height > 1.0e-6 else 1.0


def armature_vertical_axis(armature):
    if not armature or not armature.data.bones:
        return 2
    points = []
    for bone in armature.data.bones:
        points.append(bone.head_local)
        points.append(bone.tail_local)
    spans = []
    for axis in range(3):
        values = [point[axis] for point in points]
        spans.append(max(values) - min(values))
    return max(range(3), key=lambda axis: spans[axis])


def pose_bone_depth(pose_bone):
    depth = 0
    parent = pose_bone.parent
    while parent:
        depth += 1
        parent = parent.parent
    return depth


def pose_local_matrix(pose_bone):
    if pose_bone.parent:
        return pose_bone.parent.matrix.inverted_safe() @ pose_bone.matrix
    return pose_bone.matrix.copy()


def rest_local_matrix(pose_bone):
    bone = pose_bone.bone
    if bone.parent:
        return bone.parent.matrix_local.inverted_safe() @ bone.matrix_local
    return bone.matrix_local.copy()


def set_pose_local_matrix(pose_bone, local_matrix):
    if pose_bone.parent:
        pose_bone.matrix = pose_bone.parent.matrix @ local_matrix
    else:
        pose_bone.matrix = local_matrix


def rotation_only_delta(source_delta, include_location, location_scale):
    location, rotation, _scale = source_delta.decompose()
    delta = rotation.to_matrix().to_4x4()
    if include_location:
        delta.translation = location * location_scale
    return delta


def anatomical_primary_role_pairs(role_bones):
    pairs = {
        "left_upper_arm": ("left_upper_arm", "left_lower_arm"),
        "left_lower_arm": ("left_lower_arm", "left_hand"),
        "left_hand": ("left_lower_arm", "left_hand"),
        "right_upper_arm": ("right_upper_arm", "right_lower_arm"),
        "right_lower_arm": ("right_lower_arm", "right_hand"),
        "right_hand": ("right_lower_arm", "right_hand"),
        "left_upper_leg": ("left_upper_leg", "left_lower_leg"),
        "left_lower_leg": ("left_lower_leg", "left_foot"),
        "left_foot": (
            ("left_foot", "left_toe")
            if "left_toe" in role_bones
            else ("left_lower_leg", "left_foot")
        ),
        "right_upper_leg": ("right_upper_leg", "right_lower_leg"),
        "right_lower_leg": ("right_lower_leg", "right_foot"),
        "right_foot": (
            ("right_foot", "right_toe")
            if "right_toe" in role_bones
            else ("right_lower_leg", "right_foot")
        ),
    }
    if "left_toe" in role_bones:
        pairs["left_toe"] = ("left_foot", "left_toe")
    if "right_toe" in role_bones:
        pairs["right_toe"] = ("right_foot", "right_toe")
    if "left_shoulder" in role_bones:
        pairs["left_shoulder"] = ("left_shoulder", "left_upper_arm")
    if "right_shoulder" in role_bones:
        pairs["right_shoulder"] = ("right_shoulder", "right_upper_arm")

    spines = sorted(
        (role_id for role_id in role_bones if role_id.startswith("spine_")),
        key=lambda role_id: int(role_id.rsplit("_", 1)[-1]),
    )
    necks = sorted(
        (role_id for role_id in role_bones if role_id.startswith("neck_")),
        key=lambda role_id: int(role_id.rsplit("_", 1)[-1]),
    )
    torso_chain = [*spines, *necks, "head"]
    if torso_chain and "hips" in role_bones and torso_chain[0] in role_bones:
        pairs["hips"] = ("hips", torso_chain[0])
    for index, role_id in enumerate(torso_chain[:-1]):
        next_role = torso_chain[index + 1]
        if role_id in role_bones and next_role in role_bones:
            pairs[role_id] = (role_id, next_role)
    if "head" in role_bones:
        previous = next(
            (role_id for role_id in reversed(torso_chain[:-1]) if role_id in role_bones),
            None,
        )
        if previous:
            pairs["head"] = (previous, "head")
    return pairs


def anatomical_frame_data_for_pairs(armature, pairs, pair_side):
    role_bones = {}
    for pair in pairs:
        bone = pair.get(pair_side)
        role_id = pair.get("role_id", "")
        if role_id and bone and role_id not in role_bones:
            role_bones[role_id] = bone
    required = {
        "hips",
        "spine_01",
        "head",
        "left_upper_leg",
        "right_upper_leg",
    }
    if not required.issubset(role_bones):
        return {"ready": False, "frames": {}, "global": None}

    points = {
        role_id: bone.bone.head_local.copy()
        for role_id, bone in role_bones.items()
    }
    up = points["head"] - points["hips"]
    lateral = points["left_upper_leg"] - points["right_upper_leg"]
    if up.length <= 1.0e-8 or lateral.length <= 1.0e-8:
        return {"ready": False, "frames": {}, "global": None}
    up.normalize()
    lateral = lateral - up * lateral.dot(up)
    if lateral.length <= 1.0e-8:
        return {"ready": False, "frames": {}, "global": None}
    lateral.normalize()
    forward = lateral.cross(up)
    if forward.length <= 1.0e-8:
        return {"ready": False, "frames": {}, "global": None}
    forward.normalize()

    frames = {}
    for role_id, (start_role, end_role) in anatomical_primary_role_pairs(role_bones).items():
        if start_role not in points or end_role not in points:
            continue
        y_axis = points[end_role] - points[start_role]
        if y_axis.length <= 1.0e-8:
            continue
        y_axis.normalize()
        z_axis = forward - y_axis * forward.dot(y_axis)
        if z_axis.length <= 1.0e-8:
            z_axis = lateral - y_axis * lateral.dot(y_axis)
        if z_axis.length <= 1.0e-8:
            continue
        z_axis.normalize()
        x_axis = y_axis.cross(z_axis)
        if x_axis.length <= 1.0e-8:
            continue
        x_axis.normalize()
        z_axis = x_axis.cross(y_axis)
        z_axis.normalize()
        frames[role_id] = Matrix((x_axis, y_axis, z_axis)).transposed()

    missing_core = [role_id for role_id in CORE_REMAP_ROLE_IDS if role_id not in frames]
    return {
        "ready": not missing_core,
        "frames": frames,
        "global": Matrix((lateral, up, forward)).transposed(),
        "missingCore": missing_core,
    }


def anatomical_transfer_context(source, target, pairs):
    source_data = anatomical_frame_data_for_pairs(source, pairs, "source")
    target_data = anatomical_frame_data_for_pairs(target, pairs, "target")
    if not source_data.get("ready") or not target_data.get("ready"):
        return {"ready": False, "source": source_data, "target": target_data}
    return {
        "ready": True,
        "source": source_data,
        "target": target_data,
        "globalAlignment": target_data["global"] @ source_data["global"].inverted_safe(),
    }


def anatomical_target_rotation(pair, context):
    source_frame = context["source"]["frames"].get(pair["role_id"])
    target_frame = context["target"]["frames"].get(pair["role_id"])
    if source_frame is None or target_frame is None:
        return None
    source_rest_rotation = pair["source"].bone.matrix_local.to_3x3().normalized()
    target_rest_rotation = pair["target"].bone.matrix_local.to_3x3().normalized()
    source_calibration = source_rest_rotation.inverted_safe() @ source_frame
    target_calibration = target_rest_rotation.inverted_safe() @ target_frame
    source_pose_rotation = pair["source"].matrix.to_3x3().normalized()
    source_pose_frame = source_pose_rotation @ source_calibration
    return (
        context["globalAlignment"]
        @ source_pose_frame
        @ target_calibration.inverted_safe()
    )


def keyframe_pose_bone(pose_bone, frame, include_location):
    keyed = 0
    if include_location:
        for index, locked in enumerate(pose_bone.lock_location):
            if not locked:
                pose_bone.keyframe_insert(data_path="location", frame=frame, index=index)
                keyed += 1

    if pose_bone.rotation_mode == "QUATERNION":
        pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        keyed += 4
    elif pose_bone.rotation_mode == "AXIS_ANGLE":
        pose_bone.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        keyed += 4
    else:
        for index, locked in enumerate(pose_bone.lock_rotation):
            if not locked:
                pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, index=index)
                keyed += 1
    return keyed


def target_driver_bone_name(armature, role_id, mapped_name):
    if not armature:
        return mapped_name
    pose_bones = armature.pose.bones
    if mapped_name in pose_bones and not ("_ref." in mapped_name or mapped_name.endswith("_ref.x")):
        return mapped_name
    for candidate in AUTO_RIG_DRIVER_ROLE_BONES.get(role_id, ()):
        if candidate in pose_bones:
            return candidate
    return mapped_name


def is_auto_rig_pro_armature(armature):
    preset = armature_preset_profile(armature)
    return bool(preset and preset["id"] == "auto_rig_pro") or detect_armature_profile(armature) == "Auto-Rig Pro"


def source_driver_bone_name(source, target, role_id, mapped_name):
    if not source:
        return mapped_name
    pose_bones = source.pose.bones
    if not is_auto_rig_pro_armature(source) or is_auto_rig_pro_armature(target):
        return mapped_name
    for candidate in AUTO_RIG_SOURCE_ROLE_BONES.get(role_id, ()):
        if candidate in pose_bones:
            return candidate
    return mapped_name


def armature_by_hrs_identity(name="", uid=""):
    uid = str(uid or "")
    if uid:
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE" and hrs_object_uid(obj) == uid:
                return obj
    if name:
        obj = bpy.data.objects.get(str(name))
        if obj and obj.type == "ARMATURE":
            return obj
    return None


def action_targets_armature(action, armature):
    if not action or not armature:
        return False
    tagged_target = str(action.get("hrs_target_armature", ""))
    tagged_target_uid = str(action.get("hrs_target_uid", ""))
    armature_uid = hrs_object_uid(armature)
    if tagged_target and tagged_target == armature.name:
        return True
    if tagged_target_uid and armature_uid and tagged_target_uid == armature_uid:
        return True
    return action_assigned_to_armature(armature, action)


def resolved_retarget_source(scene):
    selected_source = scene.hrs_source_armature
    selected_action = animation_action_for_armature(selected_source)
    resolved_source = selected_source
    resolved_action = selected_action
    chain = []
    visited = set()
    for _depth in range(4):
        if not resolved_source or not resolved_action:
            break
        marker = (resolved_source.name, resolved_action.name)
        if marker in visited:
            break
        visited.add(marker)
        if not bool(resolved_action.get("hrs_retarget_result", False)):
            break
        if not action_targets_armature(resolved_action, resolved_source):
            break
        previous_source = armature_by_hrs_identity(
            resolved_action.get("hrs_source_armature", ""),
            resolved_action.get("hrs_source_uid", ""),
        )
        previous_action = action_by_name(
            str(resolved_action.get("hrs_source_action", "")),
            allow_numeric_suffix_fallback=True,
        )
        if not previous_source or not previous_action or previous_source == scene.hrs_target_armature:
            break
        chain.append(
            {
                "fromSource": resolved_source.name,
                "fromAction": resolved_action.name,
                "toSource": previous_source.name,
                "toAction": previous_action.name,
            }
        )
        resolved_source = previous_source
        resolved_action = previous_action
    return {
        "selectedSource": selected_source,
        "selectedAction": selected_action,
        "source": resolved_source,
        "action": resolved_action,
        "chain": chain,
    }


FINGER_CHAIN_MAX_BONES = 4


def finger_chain_child_score(parent_bone, child_bone):
    name = child_bone.name.lower()
    score = 0.0
    if child_bone.children:
        score += 0.24
    if len(child_bone.children) == 1:
        score += 0.12
    if any(token in name for token in ("thumb", "index", "middle", "ring", "pinky", "finger")):
        score += 0.2
    if any(token in name for token in ("ik", "pole", "target", "widget")):
        score -= 0.3
    if any(token in name for token in ("mch", "helper", "offset")):
        score -= 0.18
    parent_length = max(float(parent_bone.bone.length), 1.0e-6)
    length_ratio = float(child_bone.bone.length) / parent_length
    if 0.12 <= length_ratio <= 1.65:
        score += 0.18
    else:
        score -= 0.12
    score += min(float(child_bone.bone.length), parent_length) * 0.01
    return score


def finger_pose_chain(root_bone, max_bones=FINGER_CHAIN_MAX_BONES):
    if not root_bone:
        return []
    chain = [root_bone]
    used = {root_bone.name}
    current = root_bone
    while len(chain) < max_bones:
        candidates = [child for child in current.children if child.name not in used]
        if not candidates:
            break
        candidates.sort(key=lambda child: finger_chain_child_score(current, child), reverse=True)
        child = candidates[0]
        if finger_chain_child_score(current, child) < -0.2:
            break
        chain.append(child)
        used.add(child.name)
        current = child
    return chain


def expand_finger_chain_pairs(pairs):
    expanded = list(pairs)
    used_targets = {pair["target"].name for pair in expanded}
    for pair in list(pairs):
        if pair.get("role_id") not in FINGER_ROLE_IDS:
            continue
        source_chain = finger_pose_chain(pair.get("source"))
        target_chain = finger_pose_chain(pair.get("target"))
        for index, (source_bone, target_bone) in enumerate(zip(source_chain[1:], target_chain[1:]), start=2):
            if target_bone.name in used_targets:
                continue
            expanded.append(
                {
                    "role_id": pair["role_id"],
                    "finger_chain_index": index,
                    "source": source_bone,
                    "target": target_bone,
                    "mapped_source_name": pair.get("mapped_source_name", ""),
                    "driver_source_name": source_bone.name,
                    "mapped_target_name": pair.get("mapped_target_name", ""),
                    "driver_target_name": target_bone.name,
                    "source_rest": rest_local_matrix(source_bone),
                    "target_rest": rest_local_matrix(target_bone),
                    "target_depth": pose_bone_depth(target_bone),
                }
            )
            used_targets.add(target_bone.name)
    expanded.sort(key=lambda row: row["target_depth"])
    return expanded


def mapped_retarget_pairs_for_armatures(scene, source, target):
    roles = retarget_role_ids(scene)
    source_map = role_map_for_armature(scene, source, roles=roles)
    target_map = role_map_for_armature(scene, target, roles=roles)
    pairs = []
    for role_id in roles:
        source_name = source_map.get(role_id, "")
        target_name = target_map.get(role_id, "")
        source_name = source_driver_bone_name(source, target, role_id, source_name)
        target_name = target_driver_bone_name(target, role_id, target_name)
        source_bone = source.pose.bones.get(source_name) if source and source.pose else None
        target_bone = target.pose.bones.get(target_name) if target and target.pose else None
        if not source_bone or not target_bone:
            continue
        pairs.append(
            {
                "role_id": role_id,
                "source": source_bone,
                "target": target_bone,
                "mapped_source_name": source_map.get(role_id, ""),
                "driver_source_name": source_name,
                "mapped_target_name": target_map.get(role_id, ""),
                "driver_target_name": target_name,
                "source_rest": rest_local_matrix(source_bone),
                "target_rest": rest_local_matrix(target_bone),
                "target_depth": pose_bone_depth(target_bone),
            }
        )
    pairs.sort(key=lambda row: row["target_depth"])
    return expand_finger_chain_pairs(pairs)


def mapped_retarget_pairs(scene):
    ensure_slots(scene)
    visible = set(visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers))
    pairs = []
    for slot in scene.hrs_mapping_slots:
        if slot.role_id not in visible and slot.role_id not in CORE_REMAP_ROLE_IDS:
            continue
        if not slot_pair_valid(scene, slot):
            continue
        source_name = source_driver_bone_name(
            scene.hrs_source_armature,
            scene.hrs_target_armature,
            slot.role_id,
            slot.source_bone,
        )
        source_bone = scene.hrs_source_armature.pose.bones.get(source_name)
        target_name = target_driver_bone_name(scene.hrs_target_armature, slot.role_id, slot.target_bone)
        target_bone = scene.hrs_target_armature.pose.bones.get(target_name)
        if not source_bone or not target_bone:
            continue
        pairs.append(
            {
                "role_id": slot.role_id,
                "source": source_bone,
                "target": target_bone,
                "mapped_source_name": slot.source_bone,
                "driver_source_name": source_name,
                "mapped_target_name": slot.target_bone,
                "driver_target_name": target_name,
                "source_rest": rest_local_matrix(source_bone),
                "target_rest": rest_local_matrix(target_bone),
                "target_depth": pose_bone_depth(target_bone),
            }
        )
    pairs.sort(key=lambda row: row["target_depth"])
    return expand_finger_chain_pairs(pairs)


def bake_retarget_action(scene):
    resolution = resolved_retarget_source(scene)
    selected_source = resolution["selectedSource"]
    selected_action = resolution["selectedAction"]
    source = resolution["source"]
    target = scene.hrs_target_armature
    if selected_source is target:
        raise RuntimeError("动作骨架和目标骨架不能是同一个对象。")
    if source is target:
        raise RuntimeError("Resolved source armature is the same as the target armature.")
    source_action = resolution["action"]
    if source_action is None:
        raise RuntimeError("动作骨架没有当前 Action，不能烘焙。")
    base_source_action = source_base_action_for_retarget(source)
    if base_source_action is None:
        base_source_action = source_action

    pairs = mapped_retarget_pairs_for_armatures(scene, source, target) if resolution["chain"] else mapped_retarget_pairs(scene)
    core_role_ids = set(CORE_REMAP_ROLE_IDS)
    core_count = sum(1 for pair in pairs if pair["role_id"] in core_role_ids)
    if core_count < len(CORE_REMAP_ROLE_IDS):
        raise RuntimeError(f"核心映射不足：{core_count}/{len(CORE_REMAP_ROLE_IDS)}")

    start_frame, end_frame = action_frame_range(source_action, scene)
    frames = list(range(start_frame, end_frame + 1))
    if not frames:
        raise RuntimeError("源 Action 没有可烘焙帧。")

    target.animation_data_create()
    action_label = safe_action_name(f"Retarget_{source_action.name}_to_{target.name}")
    target_action = bpy.data.actions.new(action_label)
    target_action["hrs_retarget_result"] = True
    target_action["hrs_source_armature"] = source.name
    target_action["hrs_target_armature"] = target.name
    target_action["hrs_source_action"] = base_source_action.name
    target_action["hrs_runtime_source_action"] = source_action.name
    if resolution["chain"]:
        target_action["hrs_requested_source_armature"] = selected_source.name if selected_source else ""
        target_action["hrs_requested_source_action"] = selected_action.name if selected_action else ""
        target_action["hrs_source_resolution"] = json.dumps(resolution["chain"], ensure_ascii=False)
    target_action["hrs_created_by"] = f"Humanoid Remap Studio {HRS_UI_VERSION}"
    target.animation_data.action = target_action

    original_frame = scene.frame_current
    original_source_action = animation_action_for_armature(source)
    location_scale = armature_height(target) / armature_height(source)
    target_vertical_axis = armature_vertical_axis(target)
    root_role_ids = {"hips"}
    rest_delta_enabled = bool(scene.hrs_retarget_auto_rest_delta)
    keep_in_place = bool(scene.hrs_retarget_keep_in_place)
    first_root_translations = {}
    keyed_channels = 0
    topology_fallback = not armature_preset_profile(source) or not armature_preset_profile(target)
    anatomy_context = (
        anatomical_transfer_context(source, target, pairs)
        if rest_delta_enabled and topology_fallback
        else {"ready": False}
    )
    use_anatomical_transfer = bool(anatomy_context.get("ready"))
    target_pairs = {pair["target"].name: pair for pair in pairs}
    target_bones = sorted(target.pose.bones, key=pose_bone_depth)
    target_action["hrs_retarget_variant"] = retarget_variant_key(keep_in_place)
    target_action["hrs_source_uid"] = ensure_hrs_object_uid(source)
    target_action["hrs_target_uid"] = ensure_hrs_object_uid(target)
    target_action["hrs_anatomical_transfer"] = use_anatomical_transfer

    try:
        source.animation_data_create()
        source.animation_data.action = source_action
        for frame_index, frame in enumerate(frames):
            scene.frame_set(frame)
            bpy.context.view_layer.update()

            reset_bones = target_bones if use_anatomical_transfer else [pair["target"] for pair in pairs]
            for pose_bone in reset_bones:
                pose_bone.matrix_basis = Matrix.Identity(4)
            bpy.context.view_layer.update()

            if use_anatomical_transfer:
                desired_matrices = {}
                for target_bone in target_bones:
                    parent_matrix = (
                        desired_matrices[target_bone.parent.name]
                        if target_bone.parent
                        else None
                    )
                    rest_local = rest_local_matrix(target_bone)
                    desired_matrix = (
                        parent_matrix @ rest_local
                        if parent_matrix is not None
                        else rest_local.copy()
                    )
                    pair = target_pairs.get(target_bone.name)
                    if pair:
                        source_local = pose_local_matrix(pair["source"])
                        source_delta = pair["source_rest"].inverted_safe() @ source_local
                        include_location = pair["role_id"] in root_role_ids
                        target_delta = rotation_only_delta(
                            source_delta,
                            include_location,
                            location_scale,
                        )
                        target_local = pair["target_rest"] @ target_delta

                        target_rotation = anatomical_target_rotation(pair, anatomy_context)
                        if target_rotation is not None:
                            translation = desired_matrix.to_translation()
                            if include_location:
                                source_motion = (
                                    pair["source"].head
                                    - pair["source"].bone.head_local
                                )
                                translation = (
                                    pair["target"].bone.head_local
                                    + anatomy_context["globalAlignment"]
                                    @ source_motion
                                    * location_scale
                                )
                                if keep_in_place:
                                    if frame_index == 0:
                                        first_root_translations[pair["role_id"]] = translation.copy()
                                    origin = first_root_translations[pair["role_id"]]
                                    for axis in range(3):
                                        if axis != target_vertical_axis:
                                            translation[axis] = origin[axis]
                            desired_matrix = target_rotation.to_4x4()
                            desired_matrix.translation = translation
                        else:
                            if include_location and keep_in_place:
                                translation = target_local.to_translation()
                                if frame_index == 0:
                                    first_root_translations[pair["role_id"]] = translation.copy()
                                origin = first_root_translations[pair["role_id"]]
                                for axis in range(3):
                                    if axis != target_vertical_axis:
                                        translation[axis] = origin[axis]
                                target_local.translation = translation
                            desired_matrix = (
                                parent_matrix @ target_local
                                if parent_matrix is not None
                                else target_local
                            )
                    desired_matrices[target_bone.name] = desired_matrix
                    if not pair:
                        continue
                    local_pose = (
                        parent_matrix.inverted_safe() @ desired_matrix
                        if parent_matrix is not None
                        else desired_matrix
                    )
                    target_bone.matrix_basis = rest_local.inverted_safe() @ local_pose
            else:
                for pair in pairs:
                    source_local = pose_local_matrix(pair["source"])
                    if rest_delta_enabled:
                        source_delta = pair["source_rest"].inverted_safe() @ source_local
                    else:
                        source_delta = source_local
                    include_location = pair["role_id"] in root_role_ids
                    target_delta = rotation_only_delta(source_delta, include_location, location_scale)
                    target_local = pair["target_rest"] @ target_delta

                    if include_location and keep_in_place:
                        translation = target_local.to_translation()
                        if frame_index == 0:
                            first_root_translations[pair["role_id"]] = translation.copy()
                        origin = first_root_translations[pair["role_id"]]
                        for axis in range(3):
                            if axis != target_vertical_axis:
                                translation[axis] = origin[axis]
                        target_local.translation = translation

                    set_pose_local_matrix(pair["target"], target_local)

            bpy.context.view_layer.update()

            for pair in pairs:
                keyed_channels += keyframe_pose_bone(
                    pair["target"],
                    frame,
                    include_location=pair["role_id"] in root_role_ids,
                )
    finally:
        if source:
            source.animation_data_create()
            source.animation_data.action = original_source_action
        if selected_source and selected_source is not source:
            selected_source.animation_data_create()
            selected_source.animation_data.action = selected_action
        scene.frame_set(start_frame)
        bpy.context.view_layer.update()

    record_retarget_history(scene, target_action, source, target, base_source_action, target_action["hrs_retarget_variant"])
    return {
        "action": target_action,
        "sourceAction": source_action,
        "resolvedSource": source,
        "requestedSource": selected_source,
        "sourceResolutionChain": resolution["chain"],
        "startFrame": start_frame,
        "endFrame": end_frame,
        "frames": len(frames),
        "pairs": len(pairs),
        "corePairs": core_count,
        "fcurves": action_fcurve_count(target_action),
        "keyedChannels": keyed_channels,
        "anatomicalTransfer": use_anatomical_transfer,
        "originalFrame": original_frame,
    }


def operator_result(callable_op):
    try:
        return sorted(callable_op())
    except RuntimeError as error:
        return [f"EXCEPTION:{error}"]


def action_fcurve_count(action):
    return len(action_fcurves(action))


def pose_bone_world_direction(armature, bone_name):
    if not armature or not armature.pose:
        return None
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        return None
    vector = (armature.matrix_world @ pose_bone.tail) - (armature.matrix_world @ pose_bone.head)
    if vector.length <= 1.0e-6:
        return None
    return vector.normalized()


def mapped_bone_direction_angles(source, target, mapped_items):
    angles = []
    for item in mapped_items:
        source_vector = pose_bone_world_direction(source, item.source_bone)
        target_vector = pose_bone_world_direction(target, item.name)
        if source_vector is None or target_vector is None:
            continue
        try:
            angles.append(math.degrees(source_vector.angle(target_vector, 0.0)))
        except ValueError:
            continue
    return angles


def clear_auto_rig_redefine_state(scene, source):
    for key in ("remap_redefine_rest_pose", "remap_redefine_preserve"):
        if source and key in source.keys():
            del source[key]
    if "rest_transf_offset" in scene.keys():
        del scene["rest_transf_offset"]
    for obj in list(bpy.data.objects):
        if source and obj.name == source.name + "_copy":
            bpy.data.objects.remove(obj, do_unlink=True)
        elif "arp_remap_emp_track" in obj.keys():
            bpy.data.objects.remove(obj, do_unlink=True)


def auto_rig_role_for_target_name(target_name):
    if not target_name or target_name == "None":
        return None
    for role_id, candidates in AUTO_RIG_DRIVER_ROLE_BONES.items():
        if target_name in candidates:
            return role_id
    return None


def apply_source_role_map_to_auto_rig(scene):
    if not hasattr(scene, "bones_map_v2"):
        return {"assigned": 0, "missingCore": list(CORE_REMAP_ROLE_IDS), "roleMap": {}}
    source = scene.hrs_source_armature
    role_map = source_role_map_for_auto_rig(scene)
    assigned = 0
    touched_roles = set()
    for item in scene.bones_map_v2:
        role_id = auto_rig_role_for_target_name(getattr(item, "name", ""))
        if not role_id:
            continue
        source_bone = role_map.get(role_id)
        if source_bone and armature_has_bone(source, source_bone):
            item.source_bone = source_bone
            assigned += 1
            touched_roles.add(role_id)
    missing_core = [role_id for role_id in CORE_REMAP_ROLE_IDS if role_id not in touched_roles]
    return {
        "assigned": assigned,
        "missingCore": missing_core,
        "roleMap": role_map,
    }


def clear_auto_rig_bones_map(scene):
    if not hasattr(scene, "bones_map_v2"):
        return
    collection = scene.bones_map_v2
    if hasattr(collection, "clear"):
        collection.clear()
        return
    while len(collection):
        collection.remove(len(collection) - 1)


def rebuild_auto_rig_map_from_roles(scene):
    if not hasattr(scene, "bones_map_v2"):
        return {
            "assigned": 0,
            "missingCore": list(CORE_REMAP_ROLE_IDS),
            "missingTargetCore": list(CORE_REMAP_ROLE_IDS),
            "sourceRoleMap": {},
            "targetRoleMap": {},
        }
    source_map = source_role_map_for_auto_rig(scene)
    target_map = target_role_map_for_auto_rig(scene)
    clear_auto_rig_bones_map(scene)
    assigned = 0
    ordered_roles = [role["id"] for role in HUMAN_ROLES if role["id"] in set(source_map) | set(target_map)]
    for role_id in ordered_roles:
        source_bone = source_map.get(role_id)
        target_bone = target_map.get(role_id)
        if not source_bone or not target_bone:
            continue
        item = scene.bones_map_v2.add()
        item.name = target_bone
        item.source_bone = source_bone
        if hasattr(item, "ik"):
            item.ik = False
        if hasattr(item, "ik_world"):
            item.ik_world = False
        if hasattr(item, "ik_create_constraints"):
            item.ik_create_constraints = False
        if hasattr(item, "location"):
            item.location = False
        if hasattr(item, "set_as_root"):
            item.set_as_root = role_id == "hips"
        assigned += 1
    source_pelvis = source_pelvis_bone_name(scene, source_map)
    target_pelvis = "c_root.x" if armature_has_bone(scene.hrs_target_armature, "c_root.x") else ""
    if source_pelvis and target_pelvis and source_pelvis != source_map.get("hips"):
        item = scene.bones_map_v2.add()
        item.name = target_pelvis
        item.source_bone = source_pelvis
        if hasattr(item, "ik"):
            item.ik = False
        if hasattr(item, "ik_world"):
            item.ik_world = False
        if hasattr(item, "ik_create_constraints"):
            item.ik_create_constraints = False
        if hasattr(item, "location"):
            item.location = False
        if hasattr(item, "set_as_root"):
            item.set_as_root = False
        assigned += 1
    missing_core = [role_id for role_id in CORE_REMAP_ROLE_IDS if role_id not in source_map]
    missing_target_core = [role_id for role_id in CORE_REMAP_ROLE_IDS if role_id not in target_map]
    return {
        "assigned": assigned,
        "missingCore": missing_core,
        "missingTargetCore": missing_target_core,
        "sourceRoleMap": source_map,
        "targetRoleMap": target_map,
    }


def force_auto_rig_fk_mapping(scene):
    mapped_items = []
    if not hasattr(scene, "bones_map_v2"):
        return mapped_items
    if hasattr(scene, "arp_remap_allow_root_update"):
        scene.arp_remap_allow_root_update = False
    root_item = next(
        (item for item in scene.bones_map_v2 if item.name == "c_root_master.x"),
        None,
    )
    if root_item is None:
        root_item = next(
            (
                item
                for item in scene.bones_map_v2
                if item.source_bone == "Hips" or item.source_bone.endswith(":Hips")
            ),
            None,
        )
    if root_item is None:
        root_item = next(
            (item for item in scene.bones_map_v2 if auto_rig_role_for_target_name(item.name) == "hips"),
            None,
        )
    for item in scene.bones_map_v2:
        item.set_as_root = False
        item.ik = False
        item.ik_world = False
        item.ik_create_constraints = False
        if item == root_item:
            item.set_as_root = True
            item.location = False
    if hasattr(scene, "arp_remap_allow_root_update"):
        scene.arp_remap_allow_root_update = True
    for index, item in enumerate(scene.bones_map_v2):
        if item.set_as_root:
            scene.bones_map_index = index
            break
    source = scene.hrs_source_armature
    for item in scene.bones_map_v2:
        if item.name and item.name != "None" and armature_has_bone(source, item.source_bone):
            mapped_items.append(item)
    return mapped_items


def select_auto_rig_redefine_source_bones(source, mapped_items):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="DESELECT")
    selected = []
    for item in mapped_items:
        if not item.name or item.name == "None":
            continue
        pose_bone = source.pose.bones.get(item.source_bone)
        if pose_bone is None:
            continue
        if hasattr(pose_bone, "select"):
            pose_bone.select = True
        else:
            pose_bone.bone.select = True
        source.data.bones.active = pose_bone.bone
        selected.append(item.source_bone)
    return selected


def scale_action_bone_location(action, bone_name, scale):
    if not action or not bone_name or not math.isfinite(scale) or scale <= 0.0:
        return 0
    if abs(scale - 1.0) <= 1.0e-6:
        return 0
    data_path = escaped_pose_bone_data_path(bone_name, "location")
    scaled_channels = 0
    for fcurve in action_fcurves(action):
        if fcurve.data_path != data_path:
            continue
        for point in fcurve.keyframe_points:
            point.co[1] *= scale
            point.handle_left[1] *= scale
            point.handle_right[1] *= scale
        fcurve.update()
        scaled_channels += 1
    return scaled_channels


def shift_action_bone_location_channel(action, bone_name, array_index, offset):
    if not action or not bone_name or not math.isfinite(offset) or abs(offset) <= 1.0e-8:
        return False
    data_path = escaped_pose_bone_data_path(bone_name, "location")
    for fcurve in action_fcurves(action):
        if fcurve.data_path != data_path or fcurve.array_index != array_index:
            continue
        for point in fcurve.keyframe_points:
            point.co[1] += offset
            point.handle_left[1] += offset
            point.handle_right[1] += offset
        fcurve.update()
        return True
    return False


def align_action_root_height(scene, source, target, action, root_bone_name, source_map, target_map, scale, frame):
    source_feet = [
        source.pose.bones.get(source_map.get(role_id, ""))
        for role_id in ("left_foot", "right_foot")
    ]
    target_feet = [
        target.pose.bones.get(target_map.get(role_id, ""))
        for role_id in ("left_foot", "right_foot")
    ]
    source_feet = [bone for bone in source_feet if bone]
    target_feet = [bone for bone in target_feet if bone]
    root_bone = target.pose.bones.get(root_bone_name) if target and target.pose else None
    if not source_feet or not target_feet or not root_bone:
        return {"applied": False, "reason": "missing-foot-or-root"}

    original_frame = scene.frame_current
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    source_floor = min(pose_bone_world_location(source, bone).z for bone in source_feet)
    target_floor = min(pose_bone_world_location(target, bone).z for bone in target_feet)
    source_origin_z = float(source.matrix_world.translation.z)
    target_origin_z = float(target.matrix_world.translation.z)
    desired_floor = target_origin_z + (source_floor - source_origin_z) * scale
    world_offset = desired_floor - target_floor

    original_location = root_bone.location.copy()
    base_world_z = pose_bone_world_location(target, root_bone).z
    influences = []
    epsilon = 0.01
    for axis in range(3):
        root_bone.location = original_location.copy()
        root_bone.location[axis] += epsilon
        bpy.context.view_layer.update()
        shifted_world_z = pose_bone_world_location(target, root_bone).z
        influences.append((shifted_world_z - base_world_z) / epsilon)
    root_bone.location = original_location
    bpy.context.view_layer.update()
    vertical_axis = max(range(3), key=lambda axis: abs(influences[axis]))
    influence = influences[vertical_axis]
    if abs(influence) <= 1.0e-5:
        scene.frame_set(original_frame)
        bpy.context.view_layer.update()
        return {"applied": False, "reason": "no-vertical-root-channel"}
    local_offset = world_offset / influence
    applied = shift_action_bone_location_channel(action, root_bone_name, vertical_axis, local_offset)
    scene.frame_set(original_frame)
    bpy.context.view_layer.update()
    return {
        "applied": bool(applied),
        "frame": int(frame),
        "sourceFloor": float(source_floor),
        "targetFloorBefore": float(target_floor),
        "desiredFloor": float(desired_floor),
        "worldOffset": float(world_offset),
        "rootLocationAxis": int(vertical_axis),
        "axisInfluence": float(influence),
        "localOffset": float(local_offset),
    }


def _execute_auto_rig_pro_mixamo_retarget_aligned(scene, keep_in_place=None, source_action_override=None):
    source = scene.hrs_source_armature
    target = scene.hrs_target_armature
    if not hasattr(scene, "source_rig") or not hasattr(bpy.ops, "arp"):
        raise RuntimeError("未检测到 Auto-Rig Pro Remap 运行属性，请先启用 Auto-Rig Pro。")
    source_action = source_action_override or animation_action_for_armature(source)
    if source_action is None:
        raise RuntimeError("动作骨架没有当前 Action，不能执行 ARP 重映射。")
    source.animation_data_create()
    source.animation_data.action = source_action
    use_keep_in_place = bool(scene.hrs_retarget_keep_in_place if keep_in_place is None else keep_in_place)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    clear_auto_rig_redefine_state(scene, source)
    scene.source_rig = source.name
    scene.target_rig = target.name
    scene.arp_retarget_in_place = use_keep_in_place
    scene.batch_retarget = False
    scene.arp_show_freeze_warn = False

    build_result = operator_result(lambda: bpy.ops.arp.build_bones_list())
    import_result = ["HRS_STRUCTURAL_MAP"]
    source_map_result = rebuild_auto_rig_map_from_roles(scene)
    mapped_items = force_auto_rig_fk_mapping(scene)
    root_items = [item for item in mapped_items if item.set_as_root]
    if source_map_result["missingCore"]:
        missing = ", ".join(source_map_result["missingCore"])
        raise RuntimeError(f"ARP source structural mapping is incomplete: {missing}")
    if source_map_result.get("missingTargetCore"):
        missing = ", ".join(source_map_result["missingTargetCore"])
        raise RuntimeError(f"ARP target structural mapping is incomplete: {missing}")
    if "FINISHED" not in build_result:
        raise RuntimeError(f"ARP Build Bones List 失败：{build_result}")
    if not mapped_items:
        raise RuntimeError(f"ARP Mixamo FK 预设未生成有效映射：{import_result}")
    if len(root_items) != 1:
        raise RuntimeError("ARP Mixamo FK 映射没有唯一 root，请检查 Hips -> c_root_master.x。")

    angles = mapped_bone_direction_angles(source, target, mapped_items)
    max_angle = max(angles) if angles else 0.0
    rest_delta_needed = bool(scene.hrs_retarget_auto_rest_delta and (not angles or max_angle >= 5.0))
    redefine_result = []
    copy_rest_result = []
    save_rest_result = []
    selected_sources = []
    if rest_delta_needed:
        redefine_result = operator_result(lambda: bpy.ops.arp.redefine_rest_pose(preserve=True, rest_pose="REST"))
        selected_sources = select_auto_rig_redefine_source_bones(source, mapped_items)
        copy_rest_result = operator_result(lambda: bpy.ops.arp.copy_bone_rest())
        save_rest_result = operator_result(lambda: bpy.ops.arp.save_pose_rest())
        if "FINISHED" not in redefine_result or "FINISHED" not in copy_rest_result or "FINISHED" not in save_rest_result:
            raise RuntimeError(
                "ARP 重新定义静止姿态失败："
                f"redefine={redefine_result} copy={copy_rest_result} save={save_rest_result}"
            )

    current_action = animation_action_for_armature(source)
    if current_action is None:
        raise RuntimeError("ARP 重映射前源 Action 丢失。")
    start_frame, end_frame = action_frame_range(current_action, scene)
    before_action = target.animation_data.action if target.animation_data else None
    retarget_result = operator_result(
        lambda: bpy.ops.arp.retarget(
            frame_start=start_frame,
            frame_end=end_frame,
            # Auto-Rig Pro's FK rotation cleanup can over-roll FK hands/arms
            # after the Mixamo rest-pose alignment step. Keep ARP's baked FK
            # result intact for this preset route.
            clean_fk_rot=False,
            clean_ik_pole=False,
            only_existing_keyframes=False,
            extract_root_motion=False,
            fake_user_action=False,
            interpolation_type="LINEAR",
            handle_type="DEFAULT",
        )
    )
    after_action = target.animation_data.action if target.animation_data else None
    if "FINISHED" not in retarget_result or after_action is None or after_action == before_action:
        raise RuntimeError(f"ARP Retarget 未生成目标 Action：{retarget_result}")
    root_motion_scale = armature_height(target) / max(armature_height(source), 1.0e-8)
    root_location_channels = scale_action_bone_location(after_action, root_items[0].name, root_motion_scale)
    root_height_alignment = align_action_root_height(
        scene,
        source,
        target,
        after_action,
        root_items[0].name,
        source_map_result["sourceRoleMap"],
        source_map_result["targetRoleMap"],
        root_motion_scale,
        start_frame,
    )
    if current_action != source_action:
        current_action["hrs_runtime_in_place_action"] = True
        current_action["hrs_source_armature"] = source.name
        current_action["hrs_source_action"] = source_action.name
        current_action["hrs_created_by"] = f"Humanoid Remap Studio {HRS_UI_VERSION}"
    after_action.name = retarget_variant_action_name(source_action.name, target, use_keep_in_place)
    after_action["hrs_retarget_result"] = True
    after_action["hrs_source_armature"] = source.name
    after_action["hrs_target_armature"] = target.name
    after_action["hrs_source_action"] = source_action.name
    after_action["hrs_runtime_source_action"] = current_action.name
    after_action["hrs_retarget_variant"] = retarget_variant_key(use_keep_in_place)
    after_action["hrs_source_map_assigned"] = source_map_result["assigned"]
    after_action["hrs_root_motion_scale"] = float(root_motion_scale)
    after_action["hrs_root_location_channels_scaled"] = int(root_location_channels)
    after_action["hrs_root_height_offset"] = float(root_height_alignment.get("worldOffset", 0.0))
    after_action["hrs_created_by"] = f"Humanoid Remap Studio {HRS_UI_VERSION}"
    after_action["hrs_source_uid"] = ensure_hrs_object_uid(source)
    after_action["hrs_target_uid"] = ensure_hrs_object_uid(target)
    record_retarget_history(scene, after_action, source, target, source_action, after_action["hrs_retarget_variant"])

    return {
        "action": after_action,
        "sourceAction": current_action,
        "baseSourceAction": source_action,
        "variant": retarget_variant_key(use_keep_in_place),
        "keepInPlace": use_keep_in_place,
        "startFrame": start_frame,
        "endFrame": end_frame,
        "frames": end_frame - start_frame + 1,
        "pairs": len(mapped_items),
        "fcurves": action_fcurve_count(after_action),
        "root": root_items[0].name,
        "rootMotionScale": root_motion_scale,
        "rootLocationChannelsScaled": root_location_channels,
        "rootHeightAlignment": root_height_alignment,
        "restDeltaNeeded": rest_delta_needed,
        "maxRestAngle": max_angle,
        "selectedRestSources": len(selected_sources),
        "sourceMapAssigned": source_map_result["assigned"],
        "importResult": import_result,
        "retargetResult": retarget_result,
    }


def execute_auto_rig_pro_mixamo_retarget(scene, keep_in_place=None, source_action_override=None):
    source = scene.hrs_source_armature
    target = scene.hrs_target_armature
    if source is None or target is None:
        raise RuntimeError("请先指定动作骨架和目标骨架。")
    alignment = source_target_forward_alignment(scene, source, target)
    original_source_matrix = source.matrix_world.copy()
    try:
        apply_source_forward_alignment(source, alignment)
        result = _execute_auto_rig_pro_mixamo_retarget_aligned(
            scene,
            keep_in_place=keep_in_place,
            source_action_override=source_action_override,
        )
        action = result.get("action")
        if action is not None:
            action["hrs_forward_alignment_applied"] = bool(alignment.get("applied"))
            action["hrs_forward_alignment_degrees"] = float(alignment.get("degrees", 0.0))
            action["hrs_forward_alignment_dot"] = float(alignment.get("forwardDot", 1.0))
        result["forwardAlignmentApplied"] = bool(alignment.get("applied"))
        result["forwardAlignmentDegrees"] = float(alignment.get("degrees", 0.0))
        result["forwardAlignmentDot"] = float(alignment.get("forwardDot", 1.0))
        return result
    finally:
        source.matrix_world = original_source_matrix
        bpy.context.view_layer.update()


def retarget_variant_key(keep_in_place):
    return "IN_PLACE" if keep_in_place else "ROOT_MOTION"


def retarget_variant_label(keep_in_place):
    return "原地动作" if keep_in_place else "保留根位移"


def retarget_variant_action_name(source_action_name, target, keep_in_place):
    base = base_action_name_from_runtime(source_action_name)
    variant = retarget_variant_key(keep_in_place)
    return safe_action_name(f"{target.name}_{base}_{variant}")


def strip_blender_numeric_suffix(name):
    if name and len(name) > 4 and name[-4] == "." and name[-3:].isdigit():
        return name[:-4]
    return name or ""


def base_action_name_from_runtime(name):
    raw = name or ""
    if raw.endswith("_IN_PLACE"):
        return raw[: -len("_IN_PLACE")]
    base = strip_blender_numeric_suffix(raw)
    if base.endswith("_IN_PLACE"):
        return base[: -len("_IN_PLACE")]
    return raw


def action_name_without_suffixes(name):
    base = strip_blender_numeric_suffix(name)
    if base.endswith("_remap"):
        base = base[: -len("_remap")]
    if base.endswith("_IN_PLACE"):
        base = base[: -len("_IN_PLACE")]
    return base


def generated_retarget_action_names(source, target, action):
    names = set()
    source_action = animation_action_for_armature(source)
    for candidate in (
        source_action.name if source_action else "",
        action.get("hrs_source_action", "") if action else "",
        action.get("hrs_runtime_source_action", "") if action else "",
        action_name_without_suffixes(action.name) if action else "",
    ):
        if not candidate:
            continue
        runtime = strip_blender_numeric_suffix(str(candidate))
        base = base_action_name_from_runtime(runtime)
        for stem in {runtime, base, f"{base}_IN_PLACE"}:
            if not stem:
                continue
            names.add(safe_action_name(f"{target.name}_{stem}_{retarget_variant_key(True)}"))
            names.add(safe_action_name(f"{target.name}_{stem}_{retarget_variant_key(False)}"))
            names.add(safe_action_name(f"{target.name}_{base}_{retarget_variant_key(True)}"))
            names.add(safe_action_name(f"{target.name}_{base}_{retarget_variant_key(False)}"))
            names.add(safe_action_name(f"Retarget_{stem}_to_{target.name}"))
            names.add(safe_action_name(f"Retarget_{base}_to_{target.name}_IN_PLACE"))
            names.add(safe_action_name(f"Retarget_{base}_to_{target.name}_ROOT_MOTION"))
            names.add(f"{stem}_remap")
    expanded = set()
    for name in names:
        expanded.add(name)
        expanded.add(strip_blender_numeric_suffix(name))
    return expanded


def is_generated_retarget_action(scene, action):
    source = scene.hrs_source_armature
    target = scene.hrs_target_armature
    if not source or not target or not action:
        return False
    assigned_to_target = action_assigned_to_armature(target, action)
    tagged = bool(action.get("hrs_retarget_result", False))
    if tagged:
        tagged_source = str(action.get("hrs_source_armature", ""))
        tagged_target = str(action.get("hrs_target_armature", ""))
        tagged_source_uid = str(action.get("hrs_source_uid", ""))
        tagged_target_uid = str(action.get("hrs_target_uid", ""))
        requested_source = str(action.get("hrs_requested_source_armature", ""))
        requested_action = str(action.get("hrs_requested_source_action", ""))
        source_uid = hrs_object_uid(source)
        target_uid = hrs_object_uid(target)
        base_action = source_base_action_for_retarget(source, action)
        source_action_ok = bool(base_action and str(action.get("hrs_source_action", "")) == base_action.name)
        requested_source_ok = bool(
            assigned_to_target
            and requested_source
            and requested_source == source.name
            and base_action
            and requested_action == base_action.name
        )
        source_ok = (
            not tagged_source
            or tagged_source == source.name
            or (source_uid and tagged_source_uid == source_uid)
            or (assigned_to_target and source_action_ok)
            or requested_source_ok
        )
        target_ok = (
            assigned_to_target
            or not tagged_target
            or tagged_target == target.name
            or (target_uid and tagged_target_uid == target_uid)
        )
        return source_ok and target_ok
    generated_names = generated_retarget_action_names(source, target, action)
    return action.name in generated_names or strip_blender_numeric_suffix(action.name) in generated_names


def reset_pose_bone_to_rest(pose_bone):
    pose_bone.location = (0.0, 0.0, 0.0)
    pose_bone.scale = (1.0, 1.0, 1.0)
    if pose_bone.rotation_mode == "QUATERNION":
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    elif pose_bone.rotation_mode == "AXIS_ANGLE":
        pose_bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    else:
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)


def reset_armature_pose_to_rest(armature):
    if not armature or not armature.pose:
        return 0
    count = 0
    for pose_bone in armature.pose.bones:
        reset_pose_bone_to_rest(pose_bone)
        count += 1
    return count


def action_by_name(name, allow_numeric_suffix_fallback=False):
    if not name:
        return None
    exact = bpy.data.actions.get(str(name))
    if exact or not allow_numeric_suffix_fallback:
        return exact
    return bpy.data.actions.get(strip_blender_numeric_suffix(str(name)))


def source_base_action_for_retarget(source, target_action=None):
    if not source:
        return None
    current = animation_action_for_armature(source)
    if target_action:
        requested_source = str(target_action.get("hrs_requested_source_armature", ""))
        requested_action = str(target_action.get("hrs_requested_source_action", ""))
        if requested_action and (not requested_source or requested_source == source.name):
            action = action_by_name(requested_action, allow_numeric_suffix_fallback=True)
            if action:
                return action
        for name in (
            str(target_action.get("hrs_source_action", "")),
            base_action_name_from_runtime(str(target_action.get("hrs_runtime_source_action", ""))),
        ):
            action = action_by_name(name)
            if action:
                return action
    if current:
        if bool(current.get("hrs_runtime_in_place_action", False)):
            for name in (
                str(current.get("hrs_source_action", "")),
                base_action_name_from_runtime(current.name),
            ):
                action = action_by_name(name)
                if action:
                    return action
        current_base_name = base_action_name_from_runtime(current.name)
        if current_base_name != current.name:
            action = action_by_name(current_base_name)
            if action:
                return action
        return current
    return current


def hrs_object_uid(obj):
    if not obj:
        return ""
    return str(obj.get("hrs_uid", ""))


def ensure_hrs_object_uid(obj):
    if not obj:
        return ""
    existing = hrs_object_uid(obj)
    if existing:
        return existing
    value = uuid.uuid4().hex
    obj["hrs_uid"] = value
    return value


def action_assigned_to_armature(armature, action):
    return bool(armature and action and armature.animation_data and armature.animation_data.action == action)


def read_retarget_history(scene):
    raw = str(scene.get(HRS_RETARGET_HISTORY_KEY, "[]")) if scene else "[]"
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def write_retarget_history(scene, rows):
    if scene is None:
        return
    scene[HRS_RETARGET_HISTORY_KEY] = json.dumps(rows[-HRS_RETARGET_HISTORY_LIMIT:], ensure_ascii=False)


def record_retarget_history(scene, action, source, target, source_action, variant=""):
    if not scene or not action or not source or not target:
        return
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version": HRS_UI_VERSION,
        "action": action.name,
        "source": source.name,
        "target": target.name,
        "sourceUid": ensure_hrs_object_uid(source),
        "targetUid": ensure_hrs_object_uid(target),
        "sourceAction": source_action.name if source_action else "",
        "variant": str(variant or action.get("hrs_retarget_variant", "")),
    }
    rows = read_retarget_history(scene)
    rows = [item for item in rows if item.get("action") != action.name]
    rows.append(row)
    write_retarget_history(scene, rows)


def history_actions_for_scene(scene):
    source = scene.hrs_source_armature if scene else None
    target = scene.hrs_target_armature if scene else None
    source_uid = hrs_object_uid(source)
    target_uid = hrs_object_uid(target)
    actions = []
    for item in read_retarget_history(scene):
        action = bpy.data.actions.get(str(item.get("action", "")))
        if not action:
            continue
        source_ok = item.get("source") == getattr(source, "name", "") or (source_uid and item.get("sourceUid") == source_uid)
        target_ok = item.get("target") == getattr(target, "name", "") or (target_uid and item.get("targetUid") == target_uid)
        if source_ok and target_ok:
            actions.append(action)
    return actions


def candidate_generated_retarget_actions(scene):
    actions = [action for action in list(bpy.data.actions) if is_generated_retarget_action(scene, action)]
    for action in history_actions_for_scene(scene):
        if action not in actions:
            actions.append(action)
    return actions


def is_auto_rig_temp_target_action(scene, action):
    target = scene.hrs_target_armature
    if not target or not action:
        return False
    if bool(action.get("hrs_retarget_result", False)):
        return False
    temp_base = f"{target.name}Action"
    return strip_blender_numeric_suffix(action.name) == temp_base or action.name.startswith(f"{temp_base}.")


def candidate_auto_rig_temp_actions(scene):
    return [action for action in list(bpy.data.actions) if is_auto_rig_temp_target_action(scene, action)]


def candidate_runtime_source_actions(scene, base_action=None):
    source = scene.hrs_source_armature
    if not source:
        return []
    base = base_action or source_base_action_for_retarget(source)
    base_name = base.name if base else ""
    runtime_names = {f"{base_name}_IN_PLACE"} if base_name else set()
    actions = []
    current = animation_action_for_armature(source)
    for action in list(bpy.data.actions):
        tagged = bool(action.get("hrs_runtime_in_place_action", False))
        tagged_source = str(action.get("hrs_source_armature", ""))
        tag_matches = tagged and (not tagged_source or tagged_source == source.name)
        name_matches = action.name in runtime_names or strip_blender_numeric_suffix(action.name) in runtime_names
        current_matches = current == action and base_action_name_from_runtime(action.name) != action.name
        if (tag_matches or name_matches or current_matches) and action != base:
            actions.append(action)
    return actions


def source_in_place_preview_action_name(base_action):
    return safe_action_name(f"{base_action.name}_IN_PLACE") if base_action else ""


def constant_fcurve_values(fcurve, value):
    for key in fcurve.keyframe_points:
        key.co[1] = value
        key.handle_left[1] = value
        key.handle_right[1] = value
    fcurve.update()


def make_root_motion_fcurves_in_place(action, root_bone_name, vertical_axis):
    changed = 0
    root_location_path = escaped_pose_bone_data_path(root_bone_name, "location") if root_bone_name else ""
    for fcurve in action_fcurves(action):
        if fcurve.array_index == vertical_axis:
            continue
        if fcurve.data_path not in {root_location_path, "location"}:
            continue
        if not fcurve.keyframe_points:
            continue
        first_value = fcurve.keyframe_points[0].co[1]
        constant_fcurve_values(fcurve, first_value)
        changed += 1
    return changed


def ensure_source_in_place_preview_action(scene, source, base_action):
    if not source or not base_action:
        return None
    root_bone = source_motion_root_bone(source)
    if root_bone is None:
        return None
    action_name = source_in_place_preview_action_name(base_action)
    existing = bpy.data.actions.get(action_name)
    if existing and bool(existing.get("hrs_runtime_in_place_action", False)):
        if (
            str(existing.get("hrs_source_armature", "")) == source.name
            and str(existing.get("hrs_source_action", "")) == base_action.name
            and str(existing.get("hrs_created_by", "")) == f"Humanoid Remap Studio {HRS_UI_VERSION}"
        ):
            return existing
        remove_actions_from_blender([existing], source=source, target=scene.hrs_target_armature)

    preview_action = base_action.copy()
    preview_action.name = action_name
    preview_action["hrs_runtime_in_place_action"] = True
    preview_action["hrs_source_armature"] = source.name
    preview_action["hrs_source_action"] = base_action.name
    preview_action["hrs_source_root_bone"] = root_bone.name
    preview_action["hrs_created_by"] = f"Humanoid Remap Studio {HRS_UI_VERSION}"
    changed = make_root_motion_fcurves_in_place(preview_action, root_bone.name, armature_vertical_axis(source))
    preview_action["hrs_in_place_changed_fcurves"] = changed
    return preview_action


def switch_source_motion_variant(scene, update_status=True):
    source = scene.hrs_source_armature if scene else None
    if not source:
        return None
    base_action = source_base_action_for_retarget(source)
    if not base_action:
        return None

    source.animation_data_create()
    motion_summary = update_source_motion_state(scene, base_action)
    if (
        scene.hrs_retarget_keep_in_place
        and motion_summary["known"]
        and not motion_summary["hasRootMotion"]
    ):
        scene.hrs_retarget_keep_in_place = False

    if scene.hrs_retarget_keep_in_place:
        action = ensure_source_in_place_preview_action(scene, source, base_action)
        if action is None:
            action = base_action
            source.animation_data.action = action
            if update_status:
                scene.hrs_retarget_status = "源动作暂时无法生成原地预览，已保持原始动作。"
        else:
            source.animation_data.action = action
            if update_status:
                scene.hrs_retarget_status = f"已切换动作骨架为原地预览：{action.name}"
    else:
        source.animation_data.action = base_action
        removed = remove_runtime_source_actions_after_retarget(scene, base_action)
        action = base_action
        if update_status:
            suffix = f"；已清理原地预览 {len(removed)} 个" if removed else ""
            scene.hrs_retarget_status = f"已切回动作骨架原始位移动作：{base_action.name}{suffix}"

    bpy.context.view_layer.update()
    return action


def restore_clean_retarget_context(scene, active=None):
    target = scene.hrs_target_armature if scene else None
    source = scene.hrs_source_armature if scene else None
    active_obj = active or target or source
    try:
        if bpy.context.mode != "OBJECT" and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    if active_obj:
        try:
            active_obj.select_set(True)
            bpy.context.view_layer.objects.active = active_obj
        except Exception:
            pass
    bpy.context.view_layer.update()


def remove_nla_strips_using_actions(obj, actions):
    if not obj or not obj.animation_data or not obj.animation_data.nla_tracks:
        return 0
    action_set = set(actions)
    removed = 0
    for track in list(obj.animation_data.nla_tracks):
        for strip in list(track.strips):
            if strip.action in action_set:
                track.strips.remove(strip)
                removed += 1
        if not track.strips:
            obj.animation_data.nla_tracks.remove(track)
    return removed


def remove_actions_from_blender(actions, source=None, target=None):
    removed = []
    seen = set()
    unique_actions = []
    for action in actions:
        if action.name in seen:
            continue
        seen.add(action.name)
        unique_actions.append(action)
    for action in unique_actions:
        action_name = action.name
        if source and source.animation_data and source.animation_data.action == action:
            source.animation_data.action = None
        if target and target.animation_data and target.animation_data.action == action:
            target.animation_data.action = None
        existing = bpy.data.actions.get(action_name)
        if existing:
            bpy.data.actions.remove(existing, do_unlink=True)
        removed.append(action_name)
    return removed


def cleanup_retarget_artifacts(scene, allow_empty=False, reset_pose=True):
    source = scene.hrs_source_armature
    target = scene.hrs_target_armature
    if not source or not target:
        raise RuntimeError("请先选择动作骨架和目标骨架。")
    target_action = animation_action_for_armature(target)
    target_action_generated = bool(target_action and is_generated_retarget_action(scene, target_action))
    target_action_temp = bool(target_action and is_auto_rig_temp_target_action(scene, target_action))
    if target_action and not target_action_generated and not target_action_temp and not allow_empty:
        raise RuntimeError(f"当前目标 Action 不是插件生成的重映射结果：{target_action.name}")
    base_action = source_base_action_for_retarget(source, target_action)
    generated_actions = candidate_generated_retarget_actions(scene)
    if target_action_generated and target_action not in generated_actions:
        generated_actions.append(target_action)
    runtime_actions = candidate_runtime_source_actions(scene, base_action)
    temp_actions = candidate_auto_rig_temp_actions(scene)
    if target_action_temp and target_action not in temp_actions:
        temp_actions.append(target_action)
    if not generated_actions and not runtime_actions and not temp_actions and not allow_empty:
        raise RuntimeError("没有找到插件生成的重映射结果。")
    source.animation_data_create()
    if base_action:
        source.animation_data.action = base_action
    if target.animation_data and (not target_action or target_action_generated or target_action_temp or generated_actions or temp_actions):
        target.animation_data.action = None
    nla_strips_removed = remove_nla_strips_using_actions(target, generated_actions)
    nla_strips_removed += remove_nla_strips_using_actions(target, temp_actions)
    nla_strips_removed += remove_nla_strips_using_actions(source, runtime_actions)
    removed_actions = remove_actions_from_blender(generated_actions, source=source, target=target)
    removed_temp_actions = remove_actions_from_blender(temp_actions, source=source, target=target)
    removed_runtime_actions = remove_actions_from_blender(runtime_actions, source=source, target=target)
    reset_count = reset_armature_pose_to_rest(target) if reset_pose else 0
    clear_auto_rig_redefine_state(scene, source)
    restore_clean_retarget_context(scene, active=target)
    bpy.context.view_layer.update()
    return {
        "removedActions": removed_actions,
        "removedTemporaryActions": removed_temp_actions,
        "restoredSourceAction": base_action.name if base_action else None,
        "removedRuntimeSourceActions": removed_runtime_actions,
        "resetBones": reset_count,
        "nlaStripsRemoved": nla_strips_removed,
    }


def clear_retarget_result(scene):
    return cleanup_retarget_artifacts(scene, allow_empty=False, reset_pose=True)


def variant_action_for_scene(scene, keep_in_place):
    source = scene.hrs_source_armature
    target = scene.hrs_target_armature
    if not source or not target:
        return None
    wanted = retarget_variant_key(keep_in_place)
    for action in candidate_generated_retarget_actions(scene):
        if str(action.get("hrs_retarget_variant", "")) == wanted:
            return action
    base_action = source_base_action_for_retarget(source)
    if not base_action:
        return None
    wanted_name = retarget_variant_action_name(base_action.name, target, keep_in_place)
    return bpy.data.actions.get(wanted_name)


def switch_retarget_variant(scene, update_status=True):
    target = scene.hrs_target_armature
    if not target:
        return None
    if (
        scene.hrs_retarget_keep_in_place
        and getattr(scene, "hrs_source_root_motion_known", False)
        and not getattr(scene, "hrs_source_has_root_motion", False)
    ):
        scene.hrs_retarget_keep_in_place = False
    action = variant_action_for_scene(scene, scene.hrs_retarget_keep_in_place)
    if not action:
        if update_status:
            scene.hrs_retarget_status = f"已切换为{retarget_variant_label(scene.hrs_retarget_keep_in_place)}；执行重映射后会生成可播放结果。"
        return None
    target.animation_data_create()
    target.animation_data.action = action
    bpy.context.view_layer.update()
    if update_status:
        scene.hrs_retarget_status = f"已切换为{retarget_variant_label(scene.hrs_retarget_keep_in_place)}：{action.name}"
    return action


def update_retarget_keep_in_place(self, context):
    global HRS_KEEP_IN_PLACE_SYNCING
    if HRS_KEEP_IN_PLACE_SYNCING:
        return
    HRS_KEEP_IN_PLACE_SYNCING = True
    try:
        source_action = switch_source_motion_variant(context.scene, update_status=True)
        target_action = switch_retarget_variant(context.scene, update_status=False)
        if target_action:
            context.scene.hrs_retarget_status = (
                f"已切换为{retarget_variant_label(context.scene.hrs_retarget_keep_in_place)}：{target_action.name}"
            )
        elif source_action and context.scene.hrs_retarget_keep_in_place:
            context.scene.hrs_retarget_status = f"已切换动作骨架为原地预览：{source_action.name}"
    except Exception:
        pass
    finally:
        HRS_KEEP_IN_PLACE_SYNCING = False


def remove_runtime_source_actions_after_retarget(scene, base_action):
    source = scene.hrs_source_armature
    if not source:
        return []
    if base_action:
        source.animation_data_create()
        source.animation_data.action = base_action
    runtime_actions = candidate_runtime_source_actions(scene, base_action)
    remove_nla_strips_using_actions(source, runtime_actions)
    return remove_actions_from_blender(runtime_actions, source=source, target=scene.hrs_target_armature)


def remove_auto_rig_temp_actions_after_retarget(scene, protected_actions=None):
    protected = set(action for action in (protected_actions or []) if action)
    actions = [action for action in candidate_auto_rig_temp_actions(scene) if action not in protected]
    remove_nla_strips_using_actions(scene.hrs_target_armature, actions)
    return remove_actions_from_blender(actions, source=scene.hrs_source_armature, target=scene.hrs_target_armature)


def execute_auto_rig_pro_mixamo_retarget_pair(scene):
    source = scene.hrs_source_armature
    if not source:
        raise RuntimeError("请先选择动作骨架。")
    base_action = source_base_action_for_retarget(source)
    if base_action is None:
        raise RuntimeError("动作骨架没有当前 Action，不能执行 ARP 重映射。")
    motion_summary = update_source_motion_state(scene, base_action)
    generate_in_place = not motion_summary["known"] or motion_summary["hasRootMotion"]
    if not generate_in_place and scene.hrs_retarget_keep_in_place:
        scene.hrs_retarget_keep_in_place = False
    use_keep_in_place = bool(scene.hrs_retarget_keep_in_place)
    cleanup = cleanup_retarget_artifacts(scene, allow_empty=True, reset_pose=True)
    source.animation_data_create()
    source.animation_data.action = base_action
    protected_actions = []
    try:
        active_result = execute_auto_rig_pro_mixamo_retarget(
            scene,
            keep_in_place=use_keep_in_place,
            source_action_override=base_action,
        )
        protected_actions.append(active_result["action"])
        removed_runtime = remove_runtime_source_actions_after_retarget(scene, base_action)
        removed_temp = remove_auto_rig_temp_actions_after_retarget(scene, protected_actions)
        switch_source_motion_variant(scene, update_status=False)
        selected_action = switch_retarget_variant(scene, update_status=False)
    finally:
        restore_clean_retarget_context(scene, active=scene.hrs_target_armature)
    variants = {
        active_result["variant"]: active_result["action"].name,
    }
    return {
        "action": selected_action or active_result["action"],
        "sourceAction": base_action,
        "startFrame": active_result["startFrame"],
        "endFrame": active_result["endFrame"],
        "frames": active_result["frames"],
        "pairs": active_result["pairs"],
        "fcurves": action_fcurve_count(selected_action or active_result["action"]),
        "root": active_result["root"],
        "restDeltaNeeded": active_result["restDeltaNeeded"],
        "maxRestAngle": active_result["maxRestAngle"],
        "selectedRestSources": active_result["selectedRestSources"],
        "sourceMapAssigned": active_result.get("sourceMapAssigned", 0),
        "variants": variants,
        "cleanup": cleanup,
        "removedRuntimeSourceActions": removed_runtime,
        "removedTemporaryActions": removed_temp,
        "sourceRootMotionKnown": motion_summary["known"],
        "sourceHasRootMotion": motion_summary["hasRootMotion"],
        "sourceRootMotionDelta": motion_summary["delta"],
    }


def ensure_hrs_collection_uid(collection):
    if collection is None:
        return ""
    uid = str(collection.get("hrs_collection_uid", ""))
    if not uid:
        uid = str(uuid.uuid4())
        collection["hrs_collection_uid"] = uid
    return uid


def candidate_batch_retarget_actions(scene, collection=None):
    collection = collection or getattr(scene, "hrs_source_collection", None)
    target = scene.hrs_target_armature
    if collection is None or target is None:
        return []
    collection_uid = str(collection.get("hrs_collection_uid", ""))
    target_uid = str(target.get("hrs_object_uid", ""))
    actions = []
    for action in bpy.data.actions:
        if not action.get("hrs_batch_result"):
            continue
        collection_matches = bool(
            (collection_uid and str(action.get("hrs_batch_collection_uid", "")) == collection_uid)
            or str(action.get("hrs_batch_collection", "")) == collection.name
        )
        target_matches = bool(
            (target_uid and str(action.get("hrs_target_uid", "")) == target_uid)
            or str(action.get("hrs_target_armature", "")) == target.name
        )
        if not collection_matches or not target_matches:
            continue
        actions.append(action)
    return actions[:HRS_BATCH_RESULT_LIMIT]


def clear_batch_retarget_results(scene, allow_empty=False):
    target = scene.hrs_target_armature
    collection = getattr(scene, "hrs_source_collection", None)
    if target is None or collection is None:
        if allow_empty:
            return {"removedActions": [], "nlaStripsRemoved": 0, "resetBones": 0}
        raise RuntimeError("请先选择动作集合和目标骨架。")
    actions = candidate_batch_retarget_actions(scene, collection=collection)
    if not actions and not allow_empty:
        raise RuntimeError("当前集合没有插件生成的批量结果。")
    nla_removed = remove_nla_strips_using_actions(target, actions)
    if target.animation_data and target.animation_data.action in actions:
        target.animation_data.action = None
    removed = remove_actions_from_blender(actions, target=target)
    reset_count = reset_armature_pose_to_rest(target)
    restore_clean_retarget_context(scene, active=target)
    scene.hrs_batch_results_json = "[]"
    scene.hrs_last_batch_id = ""
    bpy.context.view_layer.update()
    return {
        "removedActions": removed,
        "nlaStripsRemoved": nla_removed,
        "resetBones": reset_count,
    }


def batch_retarget_action_name(source, target, source_action, keep_in_place):
    base = base_action_name_from_runtime(source_action.name)
    variant = retarget_variant_key(keep_in_place)
    return safe_action_name(f"{target.name}_{source.name}_{base}_{variant}")


def execute_batch_retarget(scene):
    audit = batch_collection_audit(scene)
    if not audit["ready"]:
        raise RuntimeError(audit["errors"][0] if audit["errors"] else "批量集合未通过检查。")
    collection = audit["collection"]
    target = audit["target"]
    batch_id = str(uuid.uuid4())
    collection_uid = ensure_hrs_collection_uid(collection)
    original_source = scene.hrs_source_armature
    original_source_name = scene.hrs_source_armature_name
    original_frame = scene.frame_current
    created_actions = []
    rows = []
    clear_batch_retarget_results(scene, allow_empty=True)
    try:
        for entry in audit["entries"]:
            source = entry["source"]
            source_action = entry["action"]
            set_scene_armature(scene, "SOURCE", source)
            source.animation_data_create()
            source.animation_data.action = source_action
            auto_guess_pair(scene, overwrite_manual=True)
            coverage = mapping_coverage(scene)
            posture_gate = retarget_posture_gate(scene)
            use_arp_native = should_use_auto_rig_pro_native(scene)
            if not posture_gate["passed"]:
                raise RuntimeError(f"{source.name}：{posture_gate['detail']}")
            if not coverage["ready"] and not use_arp_native:
                raise RuntimeError(f"{source.name}：未命中稳定自动流程")
            result = (
                execute_auto_rig_pro_mixamo_retarget_pair(scene)
                if use_arp_native
                else bake_retarget_action(scene)
            )
            action = result["action"]
            action.name = batch_retarget_action_name(
                source,
                target,
                source_action,
                bool(scene.hrs_retarget_keep_in_place),
            )
            action["hrs_batch_result"] = True
            action["hrs_batch_id"] = batch_id
            action["hrs_batch_collection"] = collection.name
            action["hrs_batch_collection_uid"] = collection_uid
            action["hrs_batch_source"] = source.name
            action["hrs_batch_source_action"] = source_action.name
            # Only the last batch result stays assigned to the target. Keep the
            # earlier results alive across save/reload until Clear Result removes them.
            action.use_fake_user = True
            created_actions.append(action)
            analysis = entry["analysis"] or {}
            alignment = analysis.get("forwardAlignment", {})
            rows.append(
                {
                    "source": source.name,
                    "sourceAction": source_action.name,
                    "sourceProfile": entry["profile"],
                    "targetAction": action.name,
                    "frames": int(result.get("frames", 0)),
                    "pairs": int(result.get("pairs", 0)),
                    "fcurves": int(action_fcurve_count(action)),
                    "heightScale": float(analysis.get("heightScale", 1.0)),
                    "forwardDegrees": float(alignment.get("degrees", 0.0)),
                    "forwardApplied": bool(alignment.get("applied", False)),
                    "route": "ARP_FK" if use_arp_native else "GENERIC",
                }
            )
            target.animation_data_create()
            target.animation_data.action = None
    except Exception:
        remove_nla_strips_using_actions(target, created_actions)
        remove_actions_from_blender(created_actions, target=target)
        reset_armature_pose_to_rest(target)
        raise
    finally:
        if original_source and original_source.name in bpy.data.objects:
            set_scene_armature(scene, "SOURCE", original_source)
            scene.hrs_source_armature_name = original_source_name
        else:
            set_scene_armature(scene, "SOURCE", None)
        scene.frame_set(original_frame)
        restore_clean_retarget_context(scene, active=target)
        bpy.context.view_layer.update()

    if created_actions:
        target.animation_data_create()
        target.animation_data.action = created_actions[-1]
    scene.hrs_last_batch_id = batch_id
    scene.hrs_batch_results_json = json.dumps(rows, ensure_ascii=False)
    update_batch_summary(scene)
    return {
        "batchId": batch_id,
        "collection": collection.name,
        "target": target.name,
        "count": len(rows),
        "rows": rows,
        "actions": created_actions,
    }


class HRS_OT_execute_retarget(Operator):
    bl_idname = "hrs.execute_retarget"
    bl_label = "执行重映射"
    bl_description = "按当前人形映射把动作骨架的当前 Action 烘焙到目标骨架"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if scene.hrs_source_mode == "COLLECTION":
            audit = update_batch_summary(scene)
            if not audit["ready"]:
                scene.hrs_retarget_status = audit["errors"][0] if audit["errors"] else "批量集合未通过检查。"
                self.report({"ERROR"}, scene.hrs_retarget_status)
                return {"CANCELLED"}
            try:
                result = execute_batch_retarget(scene)
            except Exception as error:
                scene.hrs_retarget_status = f"批量重映射失败：{error}"
                self.report({"ERROR"}, scene.hrs_retarget_status)
                return {"CANCELLED"}
            scene.hrs_retarget_status = f"已完成批量重映射：{result['count']}/{audit['count']} 个动作。"
            self.report({"INFO"}, scene.hrs_retarget_status)
            return {"FINISHED"}
        coverage = update_auto_summary(scene)
        if not scene.hrs_source_armature or not scene.hrs_target_armature:
            scene.hrs_retarget_status = "请先选择动作骨架和目标骨架。"
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        posture_gate = retarget_posture_gate(scene)
        if not posture_gate["passed"]:
            scene.hrs_retarget_status = posture_gate["detail"]
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        use_arp_native = should_use_auto_rig_pro_native(scene)
        if not coverage["ready"] and not use_arp_native:
            scene.hrs_retarget_status = "暂未命中稳定自动流程，请确认两套都是人形骨架。"
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        try:
            if use_arp_native:
                result = execute_auto_rig_pro_mixamo_retarget_pair(scene)
            else:
                result = bake_retarget_action(scene)
        except Exception as error:
            scene.hrs_retarget_status = f"重映射失败：{error}"
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        if use_arp_native:
            place_text = retarget_variant_label(scene.hrs_retarget_keep_in_place)
            if result["sourceRootMotionKnown"] and not result["sourceHasRootMotion"]:
                place_text = "无需原地版"
            source_profile = detect_armature_profile(scene.hrs_source_armature)
            target_profile = detect_armature_profile(scene.hrs_target_armature)
            scene.hrs_retarget_status = (
                f"已完成自动重映射：{source_profile} -> {target_profile}；当前：{place_text}。"
            )
        else:
            source_profile = detect_armature_profile(scene.hrs_source_armature)
            target_profile = detect_armature_profile(scene.hrs_target_armature)
            scene.hrs_retarget_status = (
                f"已完成自动重映射：{source_profile} -> {target_profile}。"
            )
        if (not use_arp_native) and result.get("sourceResolutionChain"):
            source_profile = detect_armature_profile(scene.hrs_source_armature)
            target_profile = detect_armature_profile(scene.hrs_target_armature)
            resolved_profile = detect_armature_profile(result.get("resolvedSource"))
            scene.hrs_retarget_status = (
                f"已完成自动重映射：{source_profile}（已追溯：{resolved_profile}） -> {target_profile}。"
            )
        self.report({"INFO"}, scene.hrs_retarget_status)
        return {"FINISHED"}


class HRS_OT_clear_retarget_result(Operator):
    bl_idname = "hrs.clear_retarget_result"
    bl_label = "清除结果"
    bl_description = "清除当前目标骨架上的插件重映射结果，并恢复源骨架原始动作"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if scene.hrs_source_mode == "COLLECTION":
            try:
                result = clear_batch_retarget_results(scene)
            except Exception as error:
                scene.hrs_retarget_status = f"清除失败：{error}"
                self.report({"ERROR"}, scene.hrs_retarget_status)
                return {"CANCELLED"}
            scene.hrs_retarget_status = f"已清除 {len(result['removedActions'])} 个批量结果。"
            self.report({"INFO"}, scene.hrs_retarget_status)
            return {"FINISHED"}
        try:
            result = clear_retarget_result(scene)
        except Exception as error:
            scene.hrs_retarget_status = f"清除失败：{error}"
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        restored = result["restoredSourceAction"] or "未变更"
        scene.hrs_retarget_status = (
            f"已清除重映射结果；已恢复源动作：{restored}。"
        )
        self.report({"INFO"}, scene.hrs_retarget_status)
        return {"FINISHED"}


class HRS_OT_open_humanoid_canvas(Operator):
    bl_idname = "hrs.open_humanoid_canvas"
    bl_label = "打开人形指认图"
    bl_options = {"REGISTER"}

    _handler = None

    def _start(self, context):
        if not context.area or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "请在 3D 视图侧边栏中打开人形指认图")
            return {"CANCELLED"}
        region = view3d_window_region(context)
        if region is None:
            self.report({"ERROR"}, "未找到 3D 视图窗口区域")
            return {"CANCELLED"}
        ensure_slots(context.scene)
        clear_humanoid_canvas_handlers()
        float_canvas_rect(region, context.scene)
        self._handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_humanoid_canvas,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        HRS_CANVAS_HANDLERS.append(self._handler)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        self.report({"INFO"}, "可控人形映射面板已打开：拖动标题栏移动，右下角缩放，左键点部位写入骨骼")
        return {"RUNNING_MODAL"}

    def invoke(self, context, _event):
        return self._start(context)

    def execute(self, context):
        return self._start(context)

    def _finish(self, context):
        if self._handler in HRS_CANVAS_HANDLERS:
            HRS_CANVAS_HANDLERS.remove(self._handler)
        if self._handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._handler, "WINDOW")
            except ValueError:
                pass
            self._handler = None
        if context.area:
            context.area.tag_redraw()
        return {"CANCELLED"}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.type in {"ESC", "RIGHTMOUSE"}:
            return self._finish(context)

        hit = event_window_region_xy(context, event)
        if hit is None:
            return {"PASS_THROUGH"}
        region, mouse_x, mouse_y = hit
        rect = float_canvas_rect(region, context.scene)

        action = HRS_FLOAT_CANVAS_STATE.get("action")
        if action in {"drag", "resize"}:
            if event.type == "MOUSEMOVE":
                start_mouse_x, start_mouse_y = HRS_FLOAT_CANVAS_STATE["start_mouse"]
                start_x, start_y, start_width, start_height = HRS_FLOAT_CANVAS_STATE["start_rect"]
                delta_x = event.mouse_x - start_mouse_x
                delta_y = event.mouse_y - start_mouse_y
                if action == "drag":
                    new_rect = clamp_float_canvas_rect(region, start_x + delta_x, start_y + delta_y, start_width, start_height)
                else:
                    new_width = start_width + delta_x
                    new_height = start_height - delta_y
                    new_y = start_y + delta_y
                    new_rect = clamp_float_canvas_rect(region, start_x, new_y, new_width, new_height)
                set_float_canvas_rect(context.scene, new_rect)
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                HRS_FLOAT_CANVAS_STATE.update({"action": None})
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            hit_part = float_canvas_hit_part(rect, mouse_x, mouse_y)
            if hit_part == "close":
                return self._finish(context)
            if hit_part in {"drag", "resize"}:
                HRS_FLOAT_CANVAS_STATE.update(
                    {
                        "action": hit_part,
                        "start_mouse": (event.mouse_x, event.mouse_y),
                        "start_rect": rect,
                    }
                )
                return {"RUNNING_MODAL"}
            if hit_part is None:
                return {"PASS_THROUGH"}

            role_id = humanoid_role_at_region(context.scene, region, mouse_x, mouse_y)
            if not role_id:
                return {"RUNNING_MODAL"}
            try:
                slot = assign_selected_bone_to_role(context, role_id)
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"RUNNING_MODAL"}
            self.report({"INFO"}, f"{canvas_short_label(context.scene, role_id)} -> {slot.source_bone if context.scene.hrs_assign_mode == 'SOURCE' else slot.target_bone}")
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


class HRS_OT_panel_figure_modal(Operator):
    bl_idname = "hrs.panel_figure_modal"
    bl_label = "人形面板点击监听"
    bl_options = {"INTERNAL"}

    def invoke(self, context, _event):
        global HRS_PANEL_CLICK_MODAL_RUNNING
        if HRS_PANEL_CLICK_MODAL_RUNNING:
            return {"CANCELLED"}
        HRS_PANEL_CLICK_MODAL_RUNNING = True
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global HRS_PANEL_CLICK_MODAL_RUNNING
        if not context.scene or "humanoid_remap_studio" not in context.preferences.addons:
            HRS_PANEL_CLICK_MODAL_RUNNING = False
            return {"CANCELLED"}

        if HRS_PANEL_RESIZE_STATE.get("active"):
            if event.type == "MOUSEMOVE":
                delta = event.mouse_y - HRS_PANEL_RESIZE_STATE["start_mouse_y"]
                context.scene.hrs_panel_canvas_height = clamp_panel_canvas_height(
                    HRS_PANEL_RESIZE_STATE["start_height"] - delta
                )
                for area in context.screen.areas:
                    if area.type == "VIEW_3D":
                        area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                HRS_PANEL_RESIZE_STATE["active"] = False
                for area in context.screen.areas:
                    if area.type == "VIEW_3D":
                        area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type in {"ESC", "RIGHTMOUSE"}:
                HRS_PANEL_RESIZE_STATE["active"] = False
                return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            resize_region = panel_resize_handle_from_event(context, event)
            if resize_region is not None:
                HRS_PANEL_RESIZE_STATE.update(
                    {
                        "active": True,
                        "region": resize_region.as_pointer(),
                        "start_mouse_y": event.mouse_y,
                        "start_height": panel_canvas_height(context.scene),
                    }
                )
                return {"RUNNING_MODAL"}

            role_id = panel_figure_role_from_event(context, event)
            if not role_id:
                return {"PASS_THROUGH"}
            try:
                slot = assign_selected_bone_to_role(context, role_id)
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"RUNNING_MODAL"}
            target = slot.source_bone if context.scene.hrs_assign_mode == "SOURCE" else slot.target_bone
            self.report({"INFO"}, f"{canvas_short_label(context.scene, role_id)} -> {target}")
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


def start_panel_figure_modal():
    if HRS_PANEL_CLICK_MODAL_RUNNING:
        return None
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is None:
                continue
            override = {
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
                "scene": bpy.context.scene,
            }
            try:
                with bpy.context.temp_override(**override):
                    bpy.ops.hrs.panel_figure_modal("INVOKE_DEFAULT")
                return None
            except Exception:
                continue
    return 1.0


def should_apply_auto_match(scene, slot, attr_name, score, overwrite_manual):
    current_value = getattr(slot, attr_name)
    if not current_value:
        return True
    if not slot_side_valid(scene, slot, attr_name):
        return True
    if slot.status == "manual" and not overwrite_manual:
        return False
    return slot.confidence <= score


def apply_auto_match(scene, slot, attr_name, match, overwrite_manual):
    if not should_apply_auto_match(scene, slot, attr_name, match["score"], overwrite_manual):
        return False

    current_value = getattr(slot, attr_name)
    current_valid = slot_side_valid(scene, slot, attr_name)
    preserve_manual = bool(slot.status == "manual" and not overwrite_manual and not current_value)
    setattr(slot, attr_name, match["bone_name"])

    reason_text = ",".join(match["reasons"])
    if preserve_manual:
        side_label = "动作" if attr_name == "source_bone" else "目标"
        suffix = f"auto-filled {side_label}:{reason_text}"
        slot.note = f"{slot.note}; {suffix}" if slot.note else suffix
        return True

    slot.status = "candidate"
    slot.confidence = match["score"]
    if current_value and not current_valid:
        slot.note = "auto-repaired-invalid;" + reason_text
    else:
        slot.note = reason_text
    return True


def reset_auto_matches(scene, overwrite_manual=False):
    for slot in scene.hrs_mapping_slots:
        if slot.status == "manual" and not overwrite_manual:
            continue
        slot.source_bone = ""
        slot.target_bone = ""
        slot.status = "empty"
        slot.confidence = 0.0
        slot.note = ""


def auto_guess_pair(scene, overwrite_manual=False):
    ensure_slots(scene)
    reset_auto_matches(scene, overwrite_manual=overwrite_manual)
    assigned = 0
    recognition_batches = []
    detected_neck_count = int(scene.hrs_neck_count)
    detected_spine_count = int(scene.hrs_spine_count)
    all_roles = role_ids()
    for armature, attr_name in (
        (scene.hrs_source_armature, "source_bone"),
        (scene.hrs_target_armature, "target_bone"),
    ):
        if armature is None:
            continue
        preset_matches = preset_role_matches(armature, all_roles)
        name_matches = semantic_name_role_matches(armature, all_roles)
        topology_matches = analyze_humanoid_roles(armature)
        merged_matches = merged_role_matches_for_armature(
            armature,
            all_roles,
            prefer_preset=bool(armature_preset_profile(armature)),
        )
        recognition_batches.append((armature, attr_name, preset_matches, name_matches, topology_matches, merged_matches))
        for role_id, match in {**topology_matches, **name_matches, **preset_matches}.items():
            if match["score"] < 0.42:
                continue
            if role_id.startswith("neck_"):
                detected_neck_count = max(detected_neck_count, int(role_id[-2:]))
            if role_id.startswith("spine_"):
                detected_spine_count = max(detected_spine_count, int(role_id[-2:]))
    scene.hrs_neck_count = max(1, min(MAX_NECK_COUNT, detected_neck_count))
    scene.hrs_spine_count = max(1, min(MAX_SPINE_COUNT, detected_spine_count))
    visible_roles = set(
        visible_role_ids(scene.hrs_neck_count, scene.hrs_spine_count, scene.hrs_show_fingers)
    )
    for _armature, attr_name, _preset_matches, _name_matches, _topology_matches, merged_matches in recognition_batches:
        for role_id, match in merged_matches.items():
            if role_id not in visible_roles or match["score"] < 0.42:
                continue
            slot = slot_for_role(scene, role_id)
            if slot is None:
                continue
            if apply_auto_match(scene, slot, attr_name, match, overwrite_manual):
                assigned += 1
    update_auto_summary(scene, assigned=assigned)
    return assigned


class HRS_OT_auto_guess(Operator):
    bl_idname = "hrs.auto_guess"
    bl_label = "自动识别人形骨架"
    bl_options = {"REGISTER", "UNDO"}

    overwrite_manual: bpy.props.BoolProperty(name="覆盖手动指认", default=False)

    def execute(self, context):
        scene = context.scene
        scene.hrs_retarget_status = ""
        if scene.hrs_source_mode == "COLLECTION":
            audit = update_batch_summary(scene)
            level = {"INFO"} if audit["ready"] else {"ERROR"}
            self.report(level, scene.hrs_auto_summary if audit["ready"] else scene.hrs_auto_detail)
            return {"FINISHED"}
        auto_guess_pair(scene, overwrite_manual=self.overwrite_manual)
        self.report({"INFO"}, scene.hrs_auto_summary)
        return {"FINISHED"}


class HRS_UL_mapping_slots(UIList):
    bl_idname = "HRS_UL_mapping_slots"

    def filter_items(self, context, data, propname):
        slots = getattr(data, propname)
        visible = visible_role_set(context.scene)
        flags = [
            self.bitflag_filter_item if slot.role_id in visible else 0
            for slot in slots
        ]
        return flags, []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text=role_label(context.scene, item.role_id))
            row.label(text=compact_bone_name(item.source_bone, 20))
            row.label(text=compact_bone_name(item.target_bone, 20))
        elif self.layout_type == "GRID":
            layout.label(text=role_label(context.scene, item.role_id))


class HRS_PT_main(Panel):
    bl_label = "人形重映射"
    bl_idname = "HRS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "重映射"

    def draw(self, context):
        scene = context.scene
        layout = self.layout

        def draw_armature_picker(label, name_prop, target):
            row = layout.row(align=True)
            row.prop_search(scene, name_prop, scene, "objects", text=label)
            op = row.operator("hrs.pick_armature", text="", icon="EYEDROPPER")
            op.target = target

        mode_row = layout.row(align=True)
        mode_row.prop(scene, "hrs_source_mode", expand=True)
        batch_mode = scene.hrs_source_mode == "COLLECTION"
        if batch_mode:
            layout.prop(scene, "hrs_source_collection", text="动作集合")
        else:
            draw_armature_picker("动作骨架", "hrs_source_armature_name", "SOURCE")
        draw_armature_picker("目标骨架", "hrs_target_armature_name", "TARGET")

        source_input_ready = bool(
            scene.hrs_source_collection if batch_mode else scene.hrs_source_armature
        )
        input_ready = bool(source_input_ready and scene.hrs_target_armature)

        auto_row = layout.row(align=True)
        auto_row.scale_y = 1.35
        auto_row.enabled = input_ready
        auto_row.operator("hrs.auto_guess", text="自动识别", icon="VIEWZOOM")

        result_row = layout.row(align=True)
        if not input_ready:
            result_row.label(
                text="选择动作集合和目标骨架" if batch_mode else "选择动作骨架和目标骨架",
                icon="INFO",
            )
        else:
            result_row.label(
                text=compact_ui_status(scene.hrs_auto_summary),
                icon="CHECKMARK" if scene.hrs_can_execute_retarget else "INFO",
            )

        source_action = animation_action_for_armature(scene.hrs_source_armature)
        source_ready = bool(scene.hrs_batch_ready if batch_mode else (scene.hrs_source_armature and source_action))
        motion_known = bool(getattr(scene, "hrs_source_root_motion_known", False))
        has_root_motion = bool(getattr(scene, "hrs_source_has_root_motion", False))
        layout.separator(factor=0.45)
        in_place_row = layout.row(align=True)
        in_place_row.enabled = bool(
            source_ready and (batch_mode or not motion_known or has_root_motion)
        )
        in_place_row.prop(scene, "hrs_retarget_keep_in_place", text="原地动作")

        action = layout.row(align=True)
        action.scale_y = 1.35
        run_col = action.column(align=True)
        run_col.enabled = bool(input_ready and scene.hrs_can_execute_retarget)
        run_col.operator(
            "hrs.execute_retarget",
            text="执行批量" if batch_mode else "执行重映射",
            icon="PLAY",
        )
        clear_col = action.column(align=True)
        if batch_mode:
            clear_col.enabled = bool(candidate_batch_retarget_actions(scene))
        else:
            clear_col.enabled = bool(
                scene.hrs_source_armature
                and scene.hrs_target_armature
                and (
                    candidate_generated_retarget_actions(scene)
                    or candidate_runtime_source_actions(scene)
                    or candidate_auto_rig_temp_actions(scene)
                )
            )
        clear_col.operator("hrs.clear_retarget_result", text="清除结果", icon="TRASH")
        if scene.hrs_retarget_status:
            status_row = layout.row(align=True)
            status_row.label(text=compact_ui_status(scene.hrs_retarget_status), icon="INFO")


classes = (
    HRSMappingSlot,
    HRS_OT_init_slots,
    HRS_OT_assign_selected_bone,
    HRS_OT_pick_armature,
    HRS_OT_execute_retarget,
    HRS_OT_clear_retarget_result,
    HRS_OT_open_humanoid_canvas,
    HRS_OT_panel_figure_modal,
    HRS_OT_auto_guess,
    HRS_UL_mapping_slots,
    HRS_PT_main,
)


def unregister_legacy_canvas_operator():
    try:
        bpy.utils.unregister_class(HRS_OT_open_humanoid_canvas)
    except RuntimeError:
        pass


def register():
    global HRS_PANEL_CLICK_MODAL_RUNNING
    HRS_PANEL_CLICK_MODAL_RUNNING = False
    clear_humanoid_canvas_handlers()
    clear_humanoid_panel_draw_handlers()
    clear_humanoid_previews()
    unregister_legacy_canvas_operator()
    for cls in classes:
        bpy.utils.register_class(cls)
    if HRS_PANEL_EMBEDDED_CLICK_ENABLED:
        ensure_humanoid_panel_draw_handler()
        bpy.app.timers.register(start_panel_figure_modal, first_interval=0.2)
    bpy.types.Scene.hrs_source_mode = EnumProperty(
        name="输入模式",
        items=[
            ("SINGLE", "单个", "重映射一个动作骨架"),
            ("COLLECTION", "批量集合", "重映射集合内全部动作骨架"),
        ],
        default="SINGLE",
        update=update_source_mode,
    )
    bpy.types.Scene.hrs_source_collection = PointerProperty(
        name="动作集合",
        type=bpy.types.Collection,
        update=update_source_collection,
    )
    bpy.types.Scene.hrs_batch_ready = BoolProperty(
        name="批量集合可执行",
        default=False,
    )
    bpy.types.Scene.hrs_batch_results_json = StringProperty(
        name="批量结果",
        default="[]",
    )
    bpy.types.Scene.hrs_last_batch_id = StringProperty(
        name="最近批量编号",
        default="",
    )
    bpy.types.Scene.hrs_source_armature = PointerProperty(
        name="动作骨架",
        type=bpy.types.Object,
        poll=armature_poll,
        update=update_source_armature_pointer,
    )
    bpy.types.Scene.hrs_target_armature = PointerProperty(
        name="目标骨架",
        type=bpy.types.Object,
        poll=armature_poll,
        update=update_target_armature_pointer,
    )
    bpy.types.Scene.hrs_source_armature_name = StringProperty(
        name="动作骨架",
        update=update_source_armature_name,
    )
    bpy.types.Scene.hrs_target_armature_name = StringProperty(
        name="目标骨架",
        update=update_target_armature_name,
    )
    bpy.types.Scene.hrs_assign_mode = EnumProperty(
        name="当前写入",
        items=[
            ("SOURCE", "源骨骼", "点击人形部位时写入源骨骼"),
            ("TARGET", "目标骨骼", "点击人形部位时写入目标骨骼"),
        ],
        default="SOURCE",
    )
    bpy.types.Scene.hrs_neck_count = IntProperty(
        name="颈段数",
        default=1,
        min=1,
        max=MAX_NECK_COUNT,
    )
    bpy.types.Scene.hrs_spine_count = IntProperty(
        name="脊柱段数",
        default=3,
        min=1,
        max=MAX_SPINE_COUNT,
    )
    bpy.types.Scene.hrs_show_fingers = BoolProperty(
        name="显示手指槽位",
        default=True,
    )
    bpy.types.Scene.hrs_show_native_role_buttons = BoolProperty(
        name="显示手动槽位按钮",
        default=False,
    )
    bpy.types.Scene.hrs_show_manual_correction = BoolProperty(
        name="显示人工校正",
        default=False,
    )
    bpy.types.Scene.hrs_panel_canvas_height = IntProperty(
        name="人形图高度",
        default=HRS_PANEL_DEFAULT_HEIGHT,
        min=HRS_PANEL_MIN_HEIGHT,
        max=HRS_PANEL_MAX_HEIGHT,
    )
    bpy.types.Scene.hrs_show_mapping_status = BoolProperty(
        name="显示映射状态",
        default=False,
    )
    bpy.types.Scene.hrs_auto_summary = StringProperty(
        name="识别摘要",
        default="尚未自动识别。",
    )
    bpy.types.Scene.hrs_auto_detail = StringProperty(
        name="识别详情",
        default="选择两套人形骨架后，点击自动识别。",
    )
    bpy.types.Scene.hrs_source_profile = StringProperty(
        name="动作骨架画像",
        default="未选择",
    )
    bpy.types.Scene.hrs_target_profile = StringProperty(
        name="目标骨架画像",
        default="未选择",
    )
    bpy.types.Scene.hrs_can_execute_retarget = BoolProperty(
        name="可执行重映射",
        default=False,
    )
    bpy.types.Scene.hrs_show_retarget_settings = BoolProperty(
        name="显示重映射设置",
        default=False,
    )
    bpy.types.Scene.hrs_source_root_motion_known = BoolProperty(
        name="源动作根位移已判断",
        default=False,
    )
    bpy.types.Scene.hrs_source_has_root_motion = BoolProperty(
        name="源动作有根位移",
        default=False,
    )
    bpy.types.Scene.hrs_source_root_motion_delta = FloatProperty(
        name="源动作根位移",
        default=0.0,
        min=0.0,
        precision=4,
    )
    bpy.types.Scene.hrs_source_motion_root_bone = StringProperty(
        name="源动作根骨骼",
        default="",
    )
    bpy.types.Scene.hrs_retarget_keep_in_place = BoolProperty(
        name="原地动作",
        default=False,
        update=update_retarget_keep_in_place,
    )
    bpy.types.Scene.hrs_retarget_auto_rest_delta = BoolProperty(
        name="自动判断静止姿态差异",
        default=True,
    )
    bpy.types.Scene.hrs_retarget_status = StringProperty(
        name="重映射状态",
        default="",
    )
    bpy.types.Scene.hrs_canvas_active_role = StringProperty(
        name="最近点击部位",
        default="",
    )
    bpy.types.Scene.hrs_canvas_x = IntProperty(default=-1, min=-4096, max=4096)
    bpy.types.Scene.hrs_canvas_y = IntProperty(default=-1, min=-4096, max=4096)
    bpy.types.Scene.hrs_canvas_width = IntProperty(
        name="人形面板宽度",
        default=360,
        min=HRS_FLOAT_CANVAS_MIN_WIDTH,
        max=HRS_FLOAT_CANVAS_MAX_WIDTH,
    )
    bpy.types.Scene.hrs_canvas_height = IntProperty(
        name="人形面板高度",
        default=600,
        min=HRS_FLOAT_CANVAS_MIN_HEIGHT,
        max=HRS_FLOAT_CANVAS_MAX_HEIGHT,
    )
    bpy.types.Scene.hrs_mapping_slot_index = IntProperty(default=0)
    bpy.types.Scene.hrs_mapping_slots = CollectionProperty(type=HRSMappingSlot)
    bpy.app.timers.register(sync_scene_armature_names_timer, first_interval=0.1)


def unregister():
    global HRS_PANEL_CLICK_MODAL_RUNNING
    HRS_PANEL_CLICK_MODAL_RUNNING = False
    clear_humanoid_canvas_handlers()
    clear_humanoid_panel_draw_handlers()
    clear_humanoid_previews()
    for prop_name in (
        "hrs_last_batch_id",
        "hrs_batch_results_json",
        "hrs_batch_ready",
        "hrs_source_collection",
        "hrs_source_mode",
        "hrs_mapping_slots",
        "hrs_mapping_slot_index",
        "hrs_canvas_height",
        "hrs_canvas_width",
        "hrs_canvas_y",
        "hrs_canvas_x",
        "hrs_canvas_active_role",
        "hrs_retarget_status",
        "hrs_retarget_auto_rest_delta",
        "hrs_retarget_keep_in_place",
        "hrs_source_motion_root_bone",
        "hrs_source_root_motion_delta",
        "hrs_source_has_root_motion",
        "hrs_source_root_motion_known",
        "hrs_show_retarget_settings",
        "hrs_can_execute_retarget",
        "hrs_target_profile",
        "hrs_source_profile",
        "hrs_auto_detail",
        "hrs_auto_summary",
        "hrs_show_mapping_status",
        "hrs_panel_canvas_height",
        "hrs_show_manual_correction",
        "hrs_show_native_role_buttons",
        "hrs_show_fingers",
        "hrs_spine_count",
        "hrs_neck_count",
        "hrs_assign_mode",
        "hrs_target_armature_name",
        "hrs_source_armature_name",
        "hrs_target_armature",
        "hrs_source_armature",
    ):
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    unregister_legacy_canvas_operator()
