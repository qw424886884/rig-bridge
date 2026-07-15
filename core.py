"""Humanoid recognition, validation, mapping, and batch analysis."""

import json
import math
import time

import bpy
from mathutils import Matrix, Vector

from .armature_scan import analyze_humanoid_roles
from .human_schema import (
    FINGER_ROLE_IDS,
    HUMAN_ROLE_BY_ID,
    HUMAN_ROLES,
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

from .actions import (
    action_fcurve_count,
    action_fcurves,
    action_frame_range,
    animation_action_for_armature,
    armature_height,
    armature_vertical_axis,
    escaped_pose_bone_data_path,
    resolved_retarget_source,
    source_base_action_for_retarget,
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

HRS_UI_VERSION = "v080"

HRS_GENERIC_TOPOLOGY_LABEL = "Generic Humanoid (Topology)"

HRS_SEMANTIC_NAME_MIN_SCORE = 0.68

HRS_RETARGET_HISTORY_KEY = "hrs_retarget_history"

HRS_RETARGET_HISTORY_LIMIT = 80

HRS_ROOT_MOTION_THRESHOLD = 0.03

HRS_REST_BODY_VERTICAL_MIN = 0.58

HRS_REST_LEG_VERTICAL_MIN = 0.50

HRS_FORWARD_ALIGNMENT_MIN_DEGREES = 5.0

HRS_BATCH_RESULT_LIMIT = 100

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
        scene.hrs_retarget_status = f"{name} is not an armature object."
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
        scene.hrs_auto_summary = "Select the input and click Auto Detect."
    if hasattr(scene, "hrs_auto_detail"):
        scene.hrs_auto_detail = "The batch collection may contain only humanoid armatures with valid Actions."

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
            "issue": "Could not identify a complete head, hips, and both feet structure",
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
        issue = "The overall up direction is invalid"
    elif body_vertical < HRS_REST_BODY_VERTICAL_MIN:
        issue = "The torso is nearly horizontal"
    elif leg_vertical < HRS_REST_LEG_VERTICAL_MIN:
        issue = "The leg direction deviates too far from the world Z axis"
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
            f"Source armature rest pose is invalid: {source_quality['issue']}."
            "For FBX, enable Automatic Bone Orientation; for BVH, verify the forward and up axes."
        )
    elif target_quality and not target_quality["passed"]:
        detail = f"Target armature rest pose is invalid: {target_quality['issue']}. Check the import axes or object rotation."
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
        return "Not Selected"
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
    return "Generic Humanoid"

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
        return "In-place motion will be evaluated before retargeting"
    if summary["hasRootMotion"]:
        return "The source Action contains root motion; In-Place is available"
    return "The source Action is already in place; no extra variant is needed"

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
        scene.hrs_auto_summary = "Select two humanoid armatures."
        scene.hrs_auto_detail = "Click Auto Detect after selecting both armatures."
        return coverage
    resolution = resolved_retarget_source(scene)
    scene.hrs_auto_summary = f"{source_profile} -> {target_profile}"
    if not posture_gate["passed"]:
        scene.hrs_auto_detail = posture_gate["detail"]
        return coverage
    if resolution["chain"]:
        resolved_profile = detect_armature_profile(resolution["source"])
        scene.hrs_auto_detail = (
            f"An intermediate retarget Action was detected; resolved original source: {resolved_profile} -> {target_profile}; "
            "The generic automatic retarget workflow will run."
        )
        return coverage
    if arp_native_ready:
        source_route = "preset library" if source_preset else "hierarchy and topology"
        scene.hrs_auto_detail = (
            f"The target is Auto-Rig Pro; the source was identified through {source_route} identification."
            f"The automatic FK retarget workflow will run; {root_motion_detail_text(motion_summary)}."
        )
    elif preset_route_ready and coverage["ready"]:
        scene.hrs_auto_detail = (
            f"Preset match: {source_profile} -> {target_profile}; "
            "The generic automatic retarget workflow will run."
        )
    elif coverage["ready"]:
        scene.hrs_auto_detail = (
            f"Both rigs were identified as humanoid from hierarchy features; the generic automatic retarget workflow will run."
        )
    else:
        scene.hrs_auto_detail = (
            "No stable automatic workflow was found. Confirm that both rigs are humanoid armatures."
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
        errors.append("No source collection selected")
    if target is None:
        errors.append("No target armature selected")
    if collection is not None and not objects:
        errors.append("The source collection is empty")
    non_armatures = [obj.name for obj in objects if obj.type != "ARMATURE"]
    if non_armatures:
        errors.append("The collection contains non-armature objects: " + ", ".join(non_armatures[:4]))

    target_core = (
        role_map_for_armature(scene, target, roles=CORE_REMAP_ROLE_IDS)
        if target and target.type == "ARMATURE"
        else {}
    )
    target_quality = armature_rest_posture_quality(scene, target) if target else None
    if target and len(target_core) < len(CORE_REMAP_ROLE_IDS):
        errors.append("The target armature failed the core humanoid structure check")
    if target_quality and not target_quality["passed"]:
        errors.append("Target armature rest pose is invalid: " + target_quality["issue"])

    for obj in objects:
        if obj.type != "ARMATURE":
            continue
        row_errors = []
        if obj == target:
            row_errors.append("The target armature cannot be included in the source collection")
        action = animation_action_for_armature(obj)
        if action is None or action_fcurve_count(action) == 0:
            row_errors.append("No valid Action")
        source_core = role_map_for_armature(scene, obj, roles=CORE_REMAP_ROLE_IDS)
        if len(source_core) < len(CORE_REMAP_ROLE_IDS):
            row_errors.append(
                f"Insufficient core humanoid structure: {len(source_core)}/{len(CORE_REMAP_ROLE_IDS)}"
            )
        quality = armature_rest_posture_quality(scene, obj)
        if not quality["passed"]:
            row_errors.append("Invalid rest pose: " + quality["issue"])
        analysis = retarget_pair_analysis(scene, obj, target) if target else None
        if analysis and not analysis["forwardAlignment"].get("ready"):
            row_errors.append("Could not determine a reliable forward axis")
        entry = {
            "source": obj,
            "action": action,
            "profile": detect_armature_profile(obj),
            "analysis": analysis,
            "errors": row_errors,
        }
        entries.append(entry)
        for error in row_errors:
            errors.append(f"{obj.name}: {error}")

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
        profile_text = ", ".join(dict.fromkeys(audit["profiles"]))
        scene.hrs_auto_summary = f"{audit['count']} Actions -> {target_profile}"
        scene.hrs_auto_detail = (
            f"{audit['count']}/{audit['count']} passed batch validation: {profile_text}; "
            "Each Action will use preset-first recognition, topology fallback, and automatic axis alignment."
        )
    else:
        scene.hrs_auto_summary = "The batch collection failed validation"
        scene.hrs_auto_detail = audit["errors"][0] if audit["errors"] else "Select a source collection and target armature."
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
        return "Neck"
    if role_id == "spine_01" and scene.hrs_spine_count == 1:
        return "Chest/Spine"
    if role_id.startswith("spine_"):
        index = int(role_id[-2:])
        spine_count = max(1, min(MAX_SPINE_COUNT, int(scene.hrs_spine_count)))
        if index == spine_count:
            return "Chest"
        return f"Spine {index}"
    return role["label"]

def slot_badge(slot):
    if slot is None or not slot.source_bone and not slot.target_bone:
        return "--"
    if slot.status == "manual":
        return "Set"
    if slot.source_bone and slot.target_bone:
        return "OK"
    if slot.status == "candidate":
        return "Candidate"
    return "Partial"

def assign_selected_bone_to_role(context, role_id):
    ensure_slots(context.scene)
    slot = slot_for_role(context.scene, role_id)
    bone = selected_pose_bone(context)
    if slot is None:
        raise ValueError("Humanoid mapping slot not found")
    if bone is None:
        raise ValueError("Select a Pose or Edit bone first")

    selected_armature = selected_armature_object(context)
    if context.scene.hrs_assign_mode == "SOURCE":
        expected_armature = context.scene.hrs_source_armature
        target_label = "Source Armature"
        if expected_armature is None:
            raise ValueError("Select a source armature first")
        if selected_armature != expected_armature or not armature_has_bone(expected_armature, bone.name):
            source_name = selected_armature.name if selected_armature else "Unknown Armature"
            raise ValueError(f"Current assignment: {target_label}, but the selected bone belongs to {source_name}; select a bone from {expected_armature.name}")
        slot.source_bone = bone.name
    else:
        expected_armature = context.scene.hrs_target_armature
        target_label = "Target Armature"
        if expected_armature is None:
            raise ValueError("Select a target armature first")
        if selected_armature != expected_armature or not armature_has_bone(expected_armature, bone.name):
            source_name = selected_armature.name if selected_armature else "Unknown Armature"
            raise ValueError(f"Current assignment: {target_label}, but the selected bone belongs to {source_name}; select a bone from {expected_armature.name}")
        slot.target_bone = bone.name
    slot.status = "manual"
    slot.confidence = 1.0
    slot.note = "manual assignment"
    context.scene.hrs_canvas_active_role = role_id
    return slot

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
        side_label = "Source" if attr_name == "source_bone" else "Target"
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
