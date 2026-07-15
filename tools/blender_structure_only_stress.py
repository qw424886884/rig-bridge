"""Blender-side regression test for name-free humanoid structure recognition.

Run this file through Blender MCP while Humanoid Remap Studio is enabled and a
known animated humanoid source is selected. The test clones that source twice,
scrambles every bone name independently, runs the public retarget operator, and
removes every temporary data-block before returning a JSON report.
"""

import json
import math
import sys

import bpy


MODULE_NAME = "humanoid_remap_studio"
TEMP_PREFIX = "HRS_STRUCTURE_STRESS"
SAMPLE_FRAMES = (1, 45, 82, 132, 175)
MAX_ROTATION_ERROR_DEGREES = 0.1
MAX_ROOT_POSITION_RATIO = 0.005
MAX_SCALE_CHANNEL_ERROR = 0.01
RESTORED_SCENE_PROPERTIES = (
    "hrs_auto_summary",
    "hrs_auto_detail",
    "hrs_source_profile",
    "hrs_target_profile",
    "hrs_can_execute_retarget",
    "hrs_source_root_motion_known",
    "hrs_source_has_root_motion",
    "hrs_source_root_motion_delta",
    "hrs_source_motion_root_bone",
    "hrs_retarget_status",
    "hrs_spine_count",
    "hrs_neck_count",
)

module = sys.modules[MODULE_NAME]
scene = bpy.context.scene


def rename_action_paths(action, mapping):
    for curve in module.action_fcurves(action):
        for old_name, new_name in mapping.items():
            old_prefix = module.escaped_pose_bone_data_path(old_name, "")
            if not curve.data_path.startswith(old_prefix):
                continue
            new_prefix = module.escaped_pose_bone_data_path(new_name, "")
            curve.data_path = new_prefix + curve.data_path[len(old_prefix):]
            break


def scramble_bones(obj, namespace, action=None):
    original_names = [bone.name for bone in obj.data.bones]
    mapping = {
        old_name: f"{namespace}_{index:03d}"
        for index, old_name in enumerate(original_names)
    }
    for old_name in original_names:
        obj.data.bones[old_name].name = mapping[old_name]
    if action:
        rename_action_paths(action, mapping)
    return mapping


def role_map(matches):
    return {
        role_id: match.get("bone_name", "")
        for role_id, match in matches.items()
        if match.get("bone_name")
    }


def remove_action(action):
    if action is None:
        return
    try:
        existing = bpy.data.actions.get(action.name)
    except ReferenceError:
        return
    if existing is action:
        bpy.data.actions.remove(action)


original_source = scene.hrs_source_armature
original_target = scene.hrs_target_armature
original_source_mode = scene.hrs_source_mode
original_frame = scene.frame_current
original_active = bpy.context.view_layer.objects.active
original_selected = tuple(bpy.context.selected_objects)
original_scene_properties = {
    name: getattr(scene, name) for name in RESTORED_SCENE_PROPERTIES
}
original_target_action = (
    original_target.animation_data.action
    if original_target and original_target.animation_data
    else None
)
history_exists = module.HRS_RETARGET_HISTORY_KEY in scene
original_history = scene.get(module.HRS_RETARGET_HISTORY_KEY)

source_copy = None
target_copy = None
source_data = None
target_data = None
source_action = None
result_action = None
report = {"passed": False}

try:
    if original_source is None or original_target is None:
        raise RuntimeError("select a live source and target pair before testing")
    base_action = module.animation_action_for_armature(original_source)
    if base_action is None:
        raise RuntimeError("the selected source has no action")

    preset_expected = role_map(
        module.preset_role_matches(original_source, module.role_ids())
    )
    if not preset_expected:
        raise RuntimeError(
            "the source must have a known baseline preset for regression comparison"
        )

    source_copy = original_source.copy()
    source_data = original_source.data.copy()
    source_copy.data = source_data
    source_copy.name = f"{TEMP_PREFIX}_SOURCE"
    scene.collection.objects.link(source_copy)
    source_copy.hide_viewport = False
    source_copy.hide_render = False
    source_copy.hide_set(False)
    source_copy.animation_data_clear()
    source_copy.animation_data_create()
    source_action = base_action.copy()
    source_action.name = f"{TEMP_PREFIX}_ACTION"
    source_copy.animation_data.action = source_action
    source_names = scramble_bones(source_copy, "SRC", action=source_action)

    target_copy = original_source.copy()
    target_data = original_source.data.copy()
    target_copy.data = target_data
    target_copy.name = f"{TEMP_PREFIX}_TARGET"
    scene.collection.objects.link(target_copy)
    target_copy.hide_viewport = False
    target_copy.hide_render = False
    target_copy.hide_set(False)
    target_copy.animation_data_clear()
    module.reset_armature_pose_to_rest(target_copy)
    target_names = scramble_bones(target_copy, "TGT")

    scene.hrs_source_mode = "SINGLE"
    module.set_scene_armature(scene, "SOURCE", source_copy)
    module.set_scene_armature(scene, "TARGET", target_copy)
    assigned = module.auto_guess_pair(scene, overwrite_manual=True)
    coverage = module.mapping_coverage(scene)

    source_roles = role_map(
        module.merged_role_matches_for_armature(
            source_copy,
            module.role_ids(),
            prefer_preset=False,
        )
    )
    target_roles = role_map(
        module.merged_role_matches_for_armature(
            target_copy,
            module.role_ids(),
            prefer_preset=False,
        )
    )
    expected_source = {
        role_id: source_names[bone_name]
        for role_id, bone_name in preset_expected.items()
        if bone_name in source_names
    }
    expected_target = {
        role_id: target_names[bone_name]
        for role_id, bone_name in preset_expected.items()
        if bone_name in target_names
    }
    asserted_roles = tuple(
        dict.fromkeys((*module.CORE_REMAP_ROLE_IDS, "left_toe", "right_toe"))
    )
    source_mismatch = {
        role_id: {
            "actual": source_roles.get(role_id, ""),
            "expected": expected_source.get(role_id, ""),
        }
        for role_id in asserted_roles
        if source_roles.get(role_id) != expected_source.get(role_id)
    }
    target_mismatch = {
        role_id: {
            "actual": target_roles.get(role_id, ""),
            "expected": expected_target.get(role_id, ""),
        }
        for role_id in asserted_roles
        if target_roles.get(role_id) != expected_target.get(role_id)
    }

    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    target_copy.select_set(True)
    bpy.context.view_layer.objects.active = target_copy
    operator_result = sorted(bpy.ops.hrs.execute_retarget())
    result_action = (
        target_copy.animation_data.action
        if target_copy.animation_data
        else None
    )

    slot_rows = {
        slot.role_id: (slot.source_bone, slot.target_bone)
        for slot in scene.hrs_mapping_slots
        if slot.source_bone and slot.target_bone
    }
    sampled_roles = [
        role_id for role_id in module.CORE_REMAP_ROLE_IDS if role_id in slot_rows
    ]
    rotation_errors = []
    position_errors = []
    root_position_errors = []
    scale_channel_errors = []
    worst_position = {"error": 0.0}
    for frame in SAMPLE_FRAMES:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for role_id in sampled_roles:
            source_name, target_name = slot_rows[role_id]
            source_bone = source_copy.pose.bones.get(source_name)
            target_bone = target_copy.pose.bones.get(target_name)
            if not source_bone or not target_bone:
                continue
            rotation_error = math.degrees(
                source_bone.matrix.to_quaternion()
                .rotation_difference(target_bone.matrix.to_quaternion())
                .angle
            )
            position_error = (source_bone.head - target_bone.head).length
            rotation_errors.append(rotation_error)
            position_errors.append(position_error)
            scale_channel_errors.extend(
                abs(float(value) - 1.0)
                for value in target_bone.scale
            )
            if role_id == "hips":
                root_position_errors.append(position_error)
            if position_error > worst_position["error"]:
                worst_position = {
                    "error": position_error,
                    "frame": frame,
                    "role": role_id,
                }

    max_rotation_error = max(rotation_errors, default=999.0)
    max_position_error = max(position_errors, default=999.0)
    source_height = module.armature_height(source_copy)
    max_position_ratio = max_position_error / max(source_height, 1.0e-6)
    max_root_position_error = max(root_position_errors, default=999.0)
    max_root_position_ratio = max_root_position_error / max(source_height, 1.0e-6)
    max_scale_channel_error = max(scale_channel_errors, default=999.0)
    report = {
        "passed": bool(
            coverage["ready"]
            and not source_mismatch
            and not target_mismatch
            and operator_result == ["FINISHED"]
            and result_action
            and max_rotation_error <= MAX_ROTATION_ERROR_DEGREES
            and max_root_position_ratio <= MAX_ROOT_POSITION_RATIO
            and max_scale_channel_error <= MAX_SCALE_CHANNEL_ERROR
        ),
        "source_profile": module.detect_armature_profile(source_copy),
        "target_profile": module.detect_armature_profile(target_copy),
        "source_preset": (
            module.armature_preset_profile(source_copy) or {}
        ).get("id", ""),
        "target_preset": (
            module.armature_preset_profile(target_copy) or {}
        ).get("id", ""),
        "asserted_roles": asserted_roles,
        "assigned": assigned,
        "coverage_ready": coverage["ready"],
        "coverage_missing": coverage["core_missing"],
        "source_mismatch": source_mismatch,
        "target_mismatch": target_mismatch,
        "operator_result": operator_result,
        "result_action": result_action.name if result_action else "",
        "result_fcurves": (
            module.action_fcurve_count(result_action) if result_action else 0
        ),
        "sampled_frames": SAMPLE_FRAMES,
        "sampled_roles": sampled_roles,
        "max_rotation_error_degrees": max_rotation_error,
        "max_position_error": max_position_error,
        "source_height": source_height,
        "max_position_ratio": max_position_ratio,
        "worst_position": worst_position,
        "max_root_position_error": max_root_position_error,
        "max_root_position_ratio": max_root_position_ratio,
        "max_target_scale_channel_error": max_scale_channel_error,
        "position_policy": "preserve-target-proportions",
    }
finally:
    scene.frame_set(original_frame)
    if target_copy and target_copy.animation_data:
        target_copy.animation_data.action = None
    remove_action(result_action)
    if source_copy and source_copy.animation_data:
        source_copy.animation_data.action = None
    remove_action(source_action)
    if source_copy and source_copy.name in bpy.data.objects:
        bpy.data.objects.remove(source_copy, do_unlink=True)
    if target_copy and target_copy.name in bpy.data.objects:
        bpy.data.objects.remove(target_copy, do_unlink=True)
    if source_data and source_data.name in bpy.data.armatures:
        bpy.data.armatures.remove(source_data)
    if target_data and target_data.name in bpy.data.armatures:
        bpy.data.armatures.remove(target_data)

    module.set_scene_armature(scene, "SOURCE", original_source)
    module.set_scene_armature(scene, "TARGET", original_target)
    scene.hrs_source_mode = original_source_mode
    if original_target:
        original_target.animation_data_create()
        original_target.animation_data.action = original_target_action
    if history_exists:
        scene[module.HRS_RETARGET_HISTORY_KEY] = original_history
    elif module.HRS_RETARGET_HISTORY_KEY in scene:
        del scene[module.HRS_RETARGET_HISTORY_KEY]
    module.auto_guess_pair(scene, overwrite_manual=True)
    for name, value in original_scene_properties.items():
        setattr(scene, name, value)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in original_selected:
        if obj.name in bpy.data.objects:
            obj.select_set(True)
    if original_active and original_active.name in bpy.data.objects:
        original_active.select_set(True)
        bpy.context.view_layer.objects.active = original_active
    bpy.context.view_layer.update()

print(json.dumps(report, ensure_ascii=False, indent=2))
