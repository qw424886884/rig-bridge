"""Animation retargeting, baking, variant switching, and cleanup."""

import json
import time
import uuid

import bpy
from mathutils import Matrix

from .human_schema import FINGER_ROLE_IDS, visible_role_ids

from .actions import (
    action_assigned_to_armature,
    action_fcurve_count,
    action_fcurves,
    action_frame_range,
    action_name_without_suffixes,
    animation_action_for_armature,
    armature_height,
    armature_vertical_axis,
    base_action_name_from_runtime,
    ensure_hrs_object_uid,
    escaped_pose_bone_data_path,
    hrs_object_uid,
    resolved_retarget_source,
    safe_action_name,
    source_base_action_for_retarget,
    strip_blender_numeric_suffix,
)
from .core import (
    AUTO_RIG_DRIVER_ROLE_BONES,
    AUTO_RIG_SOURCE_ROLE_BONES,
    CORE_REMAP_ROLE_IDS,
    HRS_BATCH_RESULT_LIMIT,
    HRS_RETARGET_HISTORY_KEY,
    HRS_RETARGET_HISTORY_LIMIT,
    HRS_UI_VERSION,
    armature_preset_profile,
    auto_guess_pair,
    batch_collection_audit,
    detect_armature_profile,
    ensure_slots,
    mapping_coverage,
    retarget_posture_gate,
    retarget_role_ids,
    role_map_for_armature,
    set_scene_armature,
    slot_pair_valid,
    source_motion_root_bone,
    update_batch_summary,
    update_source_motion_state,
)

HRS_KEEP_IN_PLACE_SYNCING = False

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
        raise RuntimeError("The source and target armatures cannot be the same object.")
    if source is target:
        raise RuntimeError("Resolved source armature is the same as the target armature.")
    source_action = resolution["action"]
    if source_action is None:
        raise RuntimeError("The source armature has no active Action to bake.")
    base_source_action = source_base_action_for_retarget(source)
    if base_source_action is None:
        base_source_action = source_action

    pairs = mapped_retarget_pairs_for_armatures(scene, source, target) if resolution["chain"] else mapped_retarget_pairs(scene)
    core_role_ids = set(CORE_REMAP_ROLE_IDS)
    core_count = sum(1 for pair in pairs if pair["role_id"] in core_role_ids)
    if core_count < len(CORE_REMAP_ROLE_IDS):
        raise RuntimeError(f"Insufficient core mapping: {core_count}/{len(CORE_REMAP_ROLE_IDS)}")

    start_frame, end_frame = action_frame_range(source_action, scene)
    frames = list(range(start_frame, end_frame + 1))
    if not frames:
        raise RuntimeError("The source Action has no frames to bake.")

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

def retarget_variant_key(keep_in_place):
    return "IN_PLACE" if keep_in_place else "ROOT_MOTION"

def retarget_variant_label(keep_in_place):
    return "In-Place" if keep_in_place else "Root Motion"

def retarget_variant_action_name(source_action_name, target, keep_in_place):
    base = base_action_name_from_runtime(source_action_name)
    variant = retarget_variant_key(keep_in_place)
    return safe_action_name(f"{target.name}_{base}_{variant}")

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
                scene.hrs_retarget_status = "An in-place preview could not be created; the original source Action remains active."
        else:
            source.animation_data.action = action
            if update_status:
                scene.hrs_retarget_status = f"Switched the source armature to the in-place preview: {action.name}"
    else:
        source.animation_data.action = base_action
        removed = remove_runtime_source_actions_after_retarget(scene, base_action)
        action = base_action
        if update_status:
            suffix = f"; removed in-place previews: {len(removed)} items" if removed else ""
            scene.hrs_retarget_status = f"Restored the original root-motion Action on the source armature: {base_action.name}{suffix}"

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
        raise RuntimeError("Select a source and target armature first.")
    target_action = animation_action_for_armature(target)
    target_action_generated = bool(target_action and is_generated_retarget_action(scene, target_action))
    if target_action and not target_action_generated and not allow_empty:
        raise RuntimeError(f"The active target Action was not generated by this extension: {target_action.name}")
    base_action = source_base_action_for_retarget(source, target_action)
    generated_actions = candidate_generated_retarget_actions(scene)
    if target_action_generated and target_action not in generated_actions:
        generated_actions.append(target_action)
    runtime_actions = candidate_runtime_source_actions(scene, base_action)
    if not generated_actions and not runtime_actions and not allow_empty:
        raise RuntimeError("No retarget result generated by this extension was found.")
    source.animation_data_create()
    if base_action:
        source.animation_data.action = base_action
    if target.animation_data and (not target_action or target_action_generated or generated_actions):
        target.animation_data.action = None
    nla_strips_removed = remove_nla_strips_using_actions(target, generated_actions)
    nla_strips_removed += remove_nla_strips_using_actions(source, runtime_actions)
    removed_actions = remove_actions_from_blender(generated_actions, source=source, target=target)
    removed_runtime_actions = remove_actions_from_blender(runtime_actions, source=source, target=target)
    reset_count = reset_armature_pose_to_rest(target) if reset_pose else 0
    restore_clean_retarget_context(scene, active=target)
    bpy.context.view_layer.update()
    return {
        "removedActions": removed_actions,
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
            scene.hrs_retarget_status = f"Switched to {retarget_variant_label(scene.hrs_retarget_keep_in_place)}; a playable result will be created after retargeting."
        return None
    target.animation_data_create()
    target.animation_data.action = action
    bpy.context.view_layer.update()
    if update_status:
        scene.hrs_retarget_status = f"Switched to {retarget_variant_label(scene.hrs_retarget_keep_in_place)}: {action.name}"
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
                f"Switched to {retarget_variant_label(context.scene.hrs_retarget_keep_in_place)}: {target_action.name}"
            )
        elif source_action and context.scene.hrs_retarget_keep_in_place:
            context.scene.hrs_retarget_status = f"Switched the source armature to the in-place preview: {source_action.name}"
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
        raise RuntimeError("Select a source collection and target armature first.")
    actions = candidate_batch_retarget_actions(scene, collection=collection)
    if not actions and not allow_empty:
        raise RuntimeError("The current collection has no batch results generated by this extension.")
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
        raise RuntimeError(audit["errors"][0] if audit["errors"] else "The batch collection failed validation.")
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
            if not posture_gate["passed"]:
                raise RuntimeError(f"{source.name}: {posture_gate['detail']}")
            if not coverage["ready"]:
                raise RuntimeError(f"{source.name}: no stable automatic workflow was found")
            result = bake_retarget_action(scene)
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
                    "route": "GENERIC",
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
