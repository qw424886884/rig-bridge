"""Action, animation data, and persistent identity helpers."""

import math
import uuid

import bpy

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

def action_fcurve_count(action):
    return len(action_fcurves(action))

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
