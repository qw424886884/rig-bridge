"""Blender operators and mapping slot data types."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from .core import (
    armature_from_event,
    assign_selected_bone_to_role,
    auto_guess_pair,
    detect_armature_profile,
    ensure_slots,
    retarget_posture_gate,
    selected_armature_object,
    set_scene_armature,
    should_use_auto_rig_pro_native,
    update_auto_summary,
    update_batch_summary,
)
from .retarget import (
    bake_retarget_action,
    clear_batch_retarget_results,
    clear_retarget_result,
    execute_auto_rig_pro_mixamo_retarget_pair,
    execute_batch_retarget,
    retarget_variant_label,
)

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
    bl_label = "Initialize Humanoid Slots"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_slots(context.scene)
        return {"FINISHED"}

class HRS_OT_assign_selected_bone(Operator):
    bl_idname = "hrs.assign_selected_bone"
    bl_label = "Assign to This Region"
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
    bl_label = "Pick Armature"
    bl_description = "Use the selected armature or bone when valid; otherwise pick an armature in the 3D View"
    bl_options = {"REGISTER", "UNDO"}

    target: EnumProperty(
        name="Target",
        items=[
            ("SOURCE", "Source Armature", "Assign the Source Armature"),
            ("TARGET", "Target Armature", "Assign the Target Armature"),
        ],
        default="SOURCE",
    )

    def _assign(self, context, armature):
        set_scene_armature(context.scene, self.target, armature)
        update_auto_summary(context.scene)
        label = "Source Armature" if self.target == "SOURCE" else "Target Armature"
        self.report({"INFO"}, f"{label}: {armature.name}")
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        return {"FINISHED"}

    def execute(self, context):
        armature = selected_armature_object(context)
        if not armature:
            self.report({"WARNING"}, "No armature or bone is selected")
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
        self.report({"INFO"}, "Click an armature in the 3D View, or press Esc or right-click to cancel")
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
            self.report({"WARNING"}, "No armature was picked here. Click an armature or press Esc to cancel.")
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

class HRS_OT_execute_retarget(Operator):
    bl_idname = "hrs.execute_retarget"
    bl_label = "Retarget Animation"
    bl_description = "Bake the active source Action to the target armature using the detected humanoid mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if scene.hrs_source_mode == "COLLECTION":
            audit = update_batch_summary(scene)
            if not audit["ready"]:
                scene.hrs_retarget_status = audit["errors"][0] if audit["errors"] else "The batch collection failed validation."
                self.report({"ERROR"}, scene.hrs_retarget_status)
                return {"CANCELLED"}
            try:
                result = execute_batch_retarget(scene)
            except Exception as error:
                scene.hrs_retarget_status = f"Batch retarget failed: {error}"
                self.report({"ERROR"}, scene.hrs_retarget_status)
                return {"CANCELLED"}
            scene.hrs_retarget_status = f"Batch retarget completed: {result['count']}/{audit['count']} Actions."
            self.report({"INFO"}, scene.hrs_retarget_status)
            return {"FINISHED"}
        coverage = update_auto_summary(scene)
        if not scene.hrs_source_armature or not scene.hrs_target_armature:
            scene.hrs_retarget_status = "Select a source and target armature first."
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        posture_gate = retarget_posture_gate(scene)
        if not posture_gate["passed"]:
            scene.hrs_retarget_status = posture_gate["detail"]
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        use_arp_native = should_use_auto_rig_pro_native(scene)
        if not coverage["ready"] and not use_arp_native:
            scene.hrs_retarget_status = "No stable automatic workflow was found. Confirm that both rigs are humanoid armatures."
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        try:
            if use_arp_native:
                result = execute_auto_rig_pro_mixamo_retarget_pair(scene)
            else:
                result = bake_retarget_action(scene)
        except Exception as error:
            scene.hrs_retarget_status = f"Retarget failed: {error}"
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        if use_arp_native:
            place_text = retarget_variant_label(scene.hrs_retarget_keep_in_place)
            if result["sourceRootMotionKnown"] and not result["sourceHasRootMotion"]:
                place_text = "No in-place variant needed"
            source_profile = detect_armature_profile(scene.hrs_source_armature)
            target_profile = detect_armature_profile(scene.hrs_target_armature)
            scene.hrs_retarget_status = (
                f"Automatic retarget completed: {source_profile} -> {target_profile}; current variant: {place_text}."
            )
        else:
            source_profile = detect_armature_profile(scene.hrs_source_armature)
            target_profile = detect_armature_profile(scene.hrs_target_armature)
            scene.hrs_retarget_status = (
                f"Automatic retarget completed: {source_profile} -> {target_profile}."
            )
        if (not use_arp_native) and result.get("sourceResolutionChain"):
            source_profile = detect_armature_profile(scene.hrs_source_armature)
            target_profile = detect_armature_profile(scene.hrs_target_armature)
            resolved_profile = detect_armature_profile(result.get("resolvedSource"))
            scene.hrs_retarget_status = (
                f"Automatic retarget completed: {source_profile} (resolved source: {resolved_profile}） -> {target_profile}."
            )
        self.report({"INFO"}, scene.hrs_retarget_status)
        return {"FINISHED"}

class HRS_OT_clear_retarget_result(Operator):
    bl_idname = "hrs.clear_retarget_result"
    bl_label = "Clear Result"
    bl_description = "Remove the generated target Action and restore the original source Action"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if scene.hrs_source_mode == "COLLECTION":
            try:
                result = clear_batch_retarget_results(scene)
            except Exception as error:
                scene.hrs_retarget_status = f"Cleanup failed: {error}"
                self.report({"ERROR"}, scene.hrs_retarget_status)
                return {"CANCELLED"}
            scene.hrs_retarget_status = f"Removed {len(result['removedActions'])} batch results."
            self.report({"INFO"}, scene.hrs_retarget_status)
            return {"FINISHED"}
        try:
            result = clear_retarget_result(scene)
        except Exception as error:
            scene.hrs_retarget_status = f"Cleanup failed: {error}"
            self.report({"ERROR"}, scene.hrs_retarget_status)
            return {"CANCELLED"}
        restored = result["restoredSourceAction"] or "No Change"
        scene.hrs_retarget_status = (
            f"Retarget result cleared; restored source Action: {restored}."
        )
        self.report({"INFO"}, scene.hrs_retarget_status)
        return {"FINISHED"}

class HRS_OT_auto_guess(Operator):
    bl_idname = "hrs.auto_guess"
    bl_label = "Auto Detect Humanoid Rigs"
    bl_options = {"REGISTER", "UNDO"}

    overwrite_manual: bpy.props.BoolProperty(name="Override Manual Assignments", default=False)

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
