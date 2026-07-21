"""Run a preset-free, scrambled-name cross-rig retarget regression in Blender."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


PACKAGE_PARENT = str(Path(__file__).resolve().parents[2])
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

import humanoid_remap_studio as addon
from humanoid_remap_studio.actions import (
    action_fcurve_count,
    action_fcurves,
    animation_action_for_armature,
    escaped_pose_bone_data_path,
)
from humanoid_remap_studio.core import (
    CORE_REMAP_ROLE_IDS,
    armature_preset_profile,
    auto_guess_pair,
    mapping_coverage,
    merged_role_matches_for_armature,
    retarget_posture_gate,
    set_scene_armature,
)
from humanoid_remap_studio.human_schema import FINGER_ROLE_IDS
from humanoid_remap_studio.retarget import mapped_retarget_pairs, reset_armature_pose_to_rest


TEMP_PREFIX = "HRS_GENERALIZATION"
ASSERTED_ROLES = tuple(dict.fromkeys((
    *CORE_REMAP_ROLE_IDS,
    "left_toe",
    "right_toe",
    *sorted(FINGER_ROLE_IDS),
)))
SEGMENTS = (
    ("hips", "spine_01"),
    ("spine_01", "head"),
    ("spine_01", "left_upper_arm"),
    ("left_upper_arm", "left_lower_arm"),
    ("left_lower_arm", "left_hand"),
    ("spine_01", "right_upper_arm"),
    ("right_upper_arm", "right_lower_arm"),
    ("right_lower_arm", "right_hand"),
    ("hips", "left_upper_leg"),
    ("left_upper_leg", "left_lower_leg"),
    ("left_lower_leg", "left_foot"),
    ("left_foot", "left_toe"),
    ("hips", "right_upper_leg"),
    ("right_upper_leg", "right_lower_leg"),
    ("right_lower_leg", "right_foot"),
    ("right_foot", "right_toe"),
)
METRIC_SEGMENTS = (
    ("hips", "spine_01"),
    ("spine_01", "head"),
    ("left_upper_arm", "left_lower_arm"),
    ("left_lower_arm", "left_hand"),
    ("right_upper_arm", "right_lower_arm"),
    ("right_lower_arm", "right_hand"),
    ("left_upper_leg", "left_lower_leg"),
    ("left_lower_leg", "left_foot"),
    ("left_foot", "left_toe"),
    ("right_upper_leg", "right_lower_leg"),
    ("right_lower_leg", "right_foot"),
    ("right_foot", "right_toe"),
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--max-frame", type=int, default=0)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def role_map(matches):
    return {
        role_id: match.get("bone_name", "")
        for role_id, match in matches.items()
        if match.get("bone_name")
    }


def baseline_roles(obj):
    return role_map(merged_role_matches_for_armature(obj, ASSERTED_ROLES, prefer_preset=True))


def mapping_mismatches(actual, expected):
    raw = {
        role_id: [actual.get(role_id, ""), expected.get(role_id, "")]
        for role_id in ASSERTED_ROLES
        if actual.get(role_id) != expected.get(role_id)
    }
    coherent_side_flips = []
    for role_base in (
        "upper_arm", "lower_arm", "hand", "upper_leg", "lower_leg", "foot", "toe",
        "thumb", "index", "middle", "ring", "pinky",
    ):
        left_role = "left_" + role_base
        right_role = "right_" + role_base
        if (
            actual.get(left_role)
            and actual.get(right_role)
            and actual.get(left_role) == expected.get(right_role)
            and actual.get(right_role) == expected.get(left_role)
        ):
            coherent_side_flips.extend((left_role, right_role))
    structural = {
        role_id: values
        for role_id, values in raw.items()
        if role_id not in coherent_side_flips
    }
    return raw, structural, sorted(coherent_side_flips)


def rename_action_paths(action, mapping):
    for curve in action_fcurves(action):
        for old_name, new_name in mapping.items():
            old_prefix = escaped_pose_bone_data_path(old_name, "")
            if not curve.data_path.startswith(old_prefix):
                continue
            new_prefix = escaped_pose_bone_data_path(new_name, "")
            curve.data_path = new_prefix + curve.data_path[len(old_prefix):]
            break


def scramble_bones(obj, prefix, action=None):
    names = [bone.name for bone in obj.data.bones]
    mapping = {name: f"{prefix}_{index:03d}" for index, name in enumerate(names)}
    for name in names:
        obj.data.bones[name].name = mapping[name]
    if action:
        rename_action_paths(action, mapping)
    return mapping


def trim_action(action, maximum_frame):
    if maximum_frame <= 0:
        return
    start = float(action.frame_range[0])
    action.use_frame_range = True
    action.frame_start = start
    action.frame_end = max(start, float(maximum_frame))


def clone_armature(original, name, action=None):
    clone = original.copy()
    clone.data = original.data.copy()
    clone.name = name
    bpy.context.scene.collection.objects.link(clone)
    clone.hide_viewport = False
    clone.hide_render = False
    clone.hide_set(False)
    clone.animation_data_clear()
    if action:
        clone.animation_data_create()
        clone.animation_data.action = action
    return clone


def sample_frames(action):
    start, end = (int(round(value)) for value in action.frame_range)
    span = max(0, end - start)
    return tuple(sorted({start, start + span // 4, start + span // 2, start + span * 3 // 4, end}))


def anatomical_basis(obj, slots, slot_index):
    def point(role_id):
        bone = obj.data.bones.get(slots[role_id][slot_index])
        return bone.head_local.copy() if bone else None

    hips = point("hips")
    head = point("head")
    left_leg = point("left_upper_leg")
    right_leg = point("right_upper_leg")
    if any(value is None for value in (hips, head, left_leg, right_leg)):
        return None
    up = head - hips
    lateral = left_leg - right_leg
    if up.length <= 1.0e-8 or lateral.length <= 1.0e-8:
        return None
    height = up.length
    up.normalize()
    lateral = lateral - up * lateral.dot(up)
    if lateral.length <= 1.0e-8:
        return None
    lateral.normalize()
    forward = lateral.cross(up)
    if forward.length <= 1.0e-8:
        return None
    forward.normalize()
    return lateral, forward, up, height


def anatomical_direction(direction, basis):
    lateral, forward, up, _height = basis
    projected = Vector((direction.dot(lateral), direction.dot(forward), direction.dot(up)))
    if projected.length <= 1.0e-8:
        return None
    projected.normalize()
    return projected


def collect_direction_errors(source, target, slots, source_basis, target_basis):
    errors = []
    worst = {"degrees": 0.0}
    for start_role, end_role in METRIC_SEGMENTS:
        if start_role not in slots or end_role not in slots:
            continue
        source_start = source.pose.bones.get(slots[start_role][0])
        source_end = source.pose.bones.get(slots[end_role][0])
        target_start = target.pose.bones.get(slots[start_role][1])
        target_end = target.pose.bones.get(slots[end_role][1])
        if not all((source_start, source_end, target_start, target_end)):
            continue
        source_direction = anatomical_direction(source_end.head - source_start.head, source_basis)
        target_direction = anatomical_direction(target_end.head - target_start.head, target_basis)
        if source_direction is None or target_direction is None:
            continue
        degrees = math.degrees(source_direction.angle(target_direction))
        errors.append(degrees)
        if degrees > worst["degrees"]:
            worst = {"degrees": degrees, "segment": f"{start_role}->{end_role}"}
    return errors, worst


def plot_points(obj, slots, slot_index, basis, x_offset):
    lateral, forward, up, height = basis
    hips = obj.pose.bones[slots["hips"][slot_index]].head.copy()
    result = {}
    for role_id in ASSERTED_ROLES:
        if role_id not in slots:
            continue
        bone = obj.pose.bones.get(slots[role_id][slot_index])
        if not bone:
            continue
        delta = bone.head - hips
        result[role_id] = Vector((
            delta.dot(lateral) / height + x_offset,
            -delta.dot(forward) / height,
            delta.dot(up) / height,
        ))
    return result


def create_chain_object(scene, name, points, color, created_data, created_materials):
    curve = bpy.data.curves.new(name + "_DATA", "CURVE")
    created_data.append(curve)
    curve.dimensions = "3D"
    curve.bevel_depth = 0.012
    curve.bevel_resolution = 3
    for start_role, end_role in SEGMENTS:
        if start_role not in points or end_role not in points:
            continue
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (*points[start_role], 1.0)
        spline.points[1].co = (*points[end_role], 1.0)
    obj = bpy.data.objects.new(name, curve)
    scene.collection.objects.link(obj)
    material = bpy.data.materials.new(name + "_MATERIAL")
    material.diffuse_color = (*color, 1.0)
    curve.materials.append(material)
    created_materials.append(material)
    return obj


def render_comparison(scene, source, target, slots, source_basis, target_basis, path):
    render_scene = bpy.data.scenes.new(TEMP_PREFIX + "_RENDER_SCENE")
    created_objects = []
    created_data = []
    created_materials = []
    created_world = None
    camera = None
    try:
        source_points = plot_points(source, slots, 0, source_basis, -0.67)
        target_points = plot_points(target, slots, 1, target_basis, 0.67)
        created_objects.append(create_chain_object(
            render_scene, TEMP_PREFIX + "_SOURCE_CHAIN", source_points, (0.95, 0.18, 0.12), created_data, created_materials
        ))
        created_objects.append(create_chain_object(
            render_scene, TEMP_PREFIX + "_TARGET_CHAIN", target_points, (0.08, 0.72, 0.95), created_data, created_materials
        ))
        camera_data = bpy.data.cameras.new(TEMP_PREFIX + "_CAMERA_DATA")
        created_data.append(camera_data)
        camera = bpy.data.objects.new(TEMP_PREFIX + "_CAMERA", camera_data)
        render_scene.collection.objects.link(camera)
        created_objects.append(camera)
        visible_points = [*source_points.values(), *target_points.values()]
        min_x = min(point.x for point in visible_points)
        max_x = max(point.x for point in visible_points)
        min_z = min(point.z for point in visible_points)
        max_z = max(point.z for point in visible_points)
        center = Vector(((min_x + max_x) * 0.5, 0.0, (min_z + max_z) * 0.5))
        camera.location = Vector((center.x, -6.0, center.z))
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera_data.type = "ORTHO"
        width = max_x - min_x
        height = max_z - min_z
        aspect = 900.0 / 700.0
        camera_data.ortho_scale = max(width * 1.16, height * aspect * 1.16, 0.5)
        render_scene.camera = camera
        render_scene.render.engine = "BLENDER_WORKBENCH"
        render_scene.display.shading.light = "FLAT"
        render_scene.display.shading.color_type = "MATERIAL"
        render_scene.display.shading.background_type = "VIEWPORT"
        render_scene.display.shading.background_color = (0.025, 0.025, 0.025)
        render_scene.render.resolution_x = 900
        render_scene.render.resolution_y = 700
        render_scene.render.resolution_percentage = 100
        render_scene.render.image_settings.file_format = "PNG"
        render_scene.render.film_transparent = False
        created_world = bpy.data.worlds.new(TEMP_PREFIX + "_WORLD")
        created_world.color = (0.025, 0.025, 0.025)
        render_scene.world = created_world
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        render_scene.render.filepath = path
        bpy.ops.render.render(write_still=True, scene=render_scene.name)
        return Path(path).is_file() and Path(path).stat().st_size > 0
    finally:
        for obj in created_objects:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for data in created_data:
            collection = (
                bpy.data.curves if isinstance(data, bpy.types.Curve)
                else bpy.data.cameras if isinstance(data, bpy.types.Camera)
                else None
            )
            if collection and data.name in collection:
                collection.remove(data)
        for material in created_materials:
            if material.name in bpy.data.materials:
                bpy.data.materials.remove(material)
        if created_world and created_world.name in bpy.data.worlds:
            bpy.data.worlds.remove(created_world)
        if render_scene.name in bpy.data.scenes:
            bpy.data.scenes.remove(render_scene)


def remove_action(action):
    if not action:
        return
    try:
        existing = bpy.data.actions.get(action.name)
    except ReferenceError:
        return
    if existing is action:
        bpy.data.actions.remove(action)


def main():
    args = parse_args()
    if not hasattr(bpy.types.Scene, "hrs_source_armature"):
        addon.register()
    scene = bpy.context.scene
    original_source = scene.objects.get(args.source)
    original_target = scene.objects.get(args.target)
    if not original_source or original_source.type != "ARMATURE":
        raise RuntimeError(f"source armature not found: {args.source}")
    if not original_target or original_target.type != "ARMATURE":
        raise RuntimeError(f"target armature not found: {args.target}")
    base_action = animation_action_for_armature(original_source)
    if not base_action:
        raise RuntimeError(f"source action not found: {args.source}")

    source_baseline = baseline_roles(original_source)
    target_baseline = baseline_roles(original_target)
    source_copy = None
    target_copy = None
    source_action = None
    result_action = None
    report = {"passed": False, "label": args.label}
    try:
        source_action = base_action.copy()
        source_action.name = TEMP_PREFIX + "_SOURCE_ACTION"
        trim_action(source_action, args.max_frame)
        source_copy = clone_armature(original_source, TEMP_PREFIX + "_SOURCE", source_action)
        target_copy = clone_armature(original_target, TEMP_PREFIX + "_TARGET")
        reset_armature_pose_to_rest(target_copy)
        source_names = scramble_bones(source_copy, "GEN_SRC", source_action)
        target_names = scramble_bones(target_copy, "GEN_TGT")
        source_expected = {
            role_id: source_names[name]
            for role_id, name in source_baseline.items()
            if name in source_names
        }
        target_expected = {
            role_id: target_names[name]
            for role_id, name in target_baseline.items()
            if name in target_names
        }
        source_roles = role_map(merged_role_matches_for_armature(
            source_copy, ASSERTED_ROLES, prefer_preset=False
        ))
        target_roles = role_map(merged_role_matches_for_armature(
            target_copy, ASSERTED_ROLES, prefer_preset=False
        ))
        source_text_mismatch, source_mismatch, source_side_flips = mapping_mismatches(
            source_roles, source_expected
        )
        target_text_mismatch, target_mismatch, target_side_flips = mapping_mismatches(
            target_roles, target_expected
        )

        scene.hrs_source_mode = "SINGLE"
        scene.hrs_show_fingers = True
        set_scene_armature(scene, "SOURCE", source_copy)
        set_scene_armature(scene, "TARGET", target_copy)
        assigned = auto_guess_pair(scene, overwrite_manual=True)
        coverage = mapping_coverage(scene)
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        target_copy.select_set(True)
        bpy.context.view_layer.objects.active = target_copy
        operator_error = ""
        try:
            operator_result = sorted(bpy.ops.hrs.execute_retarget())
        except RuntimeError as error:
            operator_result = ["ERROR"]
            operator_error = str(error)
        result_action = target_copy.animation_data.action if target_copy.animation_data else None
        slots = {
            slot.role_id: (slot.source_bone, slot.target_bone)
            for slot in scene.hrs_mapping_slots
            if slot.role_id in ASSERTED_ROLES and slot.source_bone and slot.target_bone
        }
        retarget_pairs = mapped_retarget_pairs(scene)
        finger_pair_counts = {
            role_id: sum(pair.get("role_id") == role_id for pair in retarget_pairs)
            for role_id in sorted(FINGER_ROLE_IDS)
        }
        finger_chain_complete = bool(
            len(finger_pair_counts) == len(FINGER_ROLE_IDS)
            and all(count >= 3 for count in finger_pair_counts.values())
        )
        animated_finger_targets = []
        if result_action:
            curves = action_fcurves(result_action)
            for pair in retarget_pairs:
                if pair.get("role_id") not in FINGER_ROLE_IDS:
                    continue
                prefix = escaped_pose_bone_data_path(pair["target"].name, "")
                if any(curve.data_path.startswith(prefix) for curve in curves):
                    animated_finger_targets.append(pair["target"].name)
        finger_pair_total = sum(finger_pair_counts.values())
        animated_finger_pair_total = len(set(animated_finger_targets))
        source_basis = anatomical_basis(source_copy, slots, 0)
        target_basis = anatomical_basis(target_copy, slots, 1)
        frames = sample_frames(source_action)
        direction_errors = []
        worst = {"degrees": 0.0}
        max_scale_error = 0.0
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            frame_errors, frame_worst = collect_direction_errors(
                source_copy, target_copy, slots, source_basis, target_basis
            )
            direction_errors.extend(frame_errors)
            if frame_worst["degrees"] > worst["degrees"]:
                worst = {**frame_worst, "frame": frame}
            for pose_bone in target_copy.pose.bones:
                max_scale_error = max(max_scale_error, *(abs(float(value) - 1.0) for value in pose_bone.scale))
        visual_frame = int(worst.get("frame", frames[len(frames) // 2]))
        scene.frame_set(visual_frame)
        bpy.context.view_layer.update()
        screenshot_ok = render_comparison(
            scene, source_copy, target_copy, slots, source_basis, target_basis, args.screenshot
        )
        mean_error = sum(direction_errors) / len(direction_errors) if direction_errors else 999.0
        max_error = max(direction_errors, default=999.0)
        source_preset = (armature_preset_profile(source_copy) or {}).get("id", "")
        target_preset = (armature_preset_profile(target_copy) or {}).get("id", "")
        report = {
            "passed": bool(
                coverage["ready"]
                and not source_mismatch
                and not target_mismatch
                and not source_preset
                and not target_preset
                and operator_result == ["FINISHED"]
                and result_action
                and direction_errors
                and all(math.isfinite(value) for value in direction_errors)
                and mean_error <= 4.0
                and max_error <= 12.0
                and max_scale_error <= 0.01
                and finger_chain_complete
                and animated_finger_pair_total == finger_pair_total
                and screenshot_ok
            ),
            "label": args.label,
            "file": bpy.data.filepath,
            "source": args.source,
            "target": args.target,
            "source_bones": len(source_copy.data.bones),
            "target_bones": len(target_copy.data.bones),
            "source_preset_after_scramble": source_preset,
            "target_preset_after_scramble": target_preset,
            "assigned": assigned,
            "coverage_ready": coverage["ready"],
            "coverage_missing": coverage["core_missing"],
            "coverage_chain_errors": coverage.get("chain_errors", []),
            "coverage_duplicate_sources": coverage.get("duplicate_sources", []),
            "coverage_duplicate_targets": coverage.get("duplicate_targets", []),
            "source_mismatch": source_mismatch,
            "target_mismatch": target_mismatch,
            "source_text_mismatch": source_text_mismatch,
            "target_text_mismatch": target_text_mismatch,
            "source_coherent_text_side_flips": source_side_flips,
            "target_coherent_text_side_flips": target_side_flips,
            "operator_result": operator_result,
            "operator_error": operator_error,
            "posture_gate": retarget_posture_gate(scene),
            "result_action": result_action.name if result_action else "",
            "result_fcurves": action_fcurve_count(result_action) if result_action else 0,
            "sample_frames": frames,
            "direction_error_mean_degrees": mean_error,
            "direction_error_max_degrees": max_error,
            "worst_direction": worst,
            "max_target_scale_channel_error": max_scale_error,
            "finger_pair_counts": finger_pair_counts,
            "finger_chain_complete": finger_chain_complete,
            "finger_pair_total": finger_pair_total,
            "animated_finger_pair_total": animated_finger_pair_total,
            "visual_frame": visual_frame,
            "screenshot": args.screenshot,
            "screenshot_ok": screenshot_ok,
        }
    finally:
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

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HRS_GENERALIZATION=" + json.dumps(report, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
