"""Sidebar panels and lists for the public workflow."""

from bpy.types import Panel, UIList

from .actions import (
    animation_action_for_armature,
)
from .core import (
    role_label,
    visible_role_set,
)
from .canvas import (
    compact_bone_name,
    compact_ui_status,
)
from .retarget import (
    candidate_batch_retarget_actions,
    candidate_generated_retarget_actions,
    candidate_runtime_source_actions,
)

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
    bl_label = "Humanoid Retarget"
    bl_idname = "HRS_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Motion Remap"

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
            layout.prop(scene, "hrs_source_collection", text="Source Collection")
        else:
            draw_armature_picker("Source", "hrs_source_armature_name", "SOURCE")
        draw_armature_picker("Target", "hrs_target_armature_name", "TARGET")

        source_input_ready = bool(
            scene.hrs_source_collection if batch_mode else scene.hrs_source_armature
        )
        input_ready = bool(source_input_ready and scene.hrs_target_armature)

        auto_row = layout.row(align=True)
        auto_row.scale_y = 1.35
        auto_row.enabled = input_ready
        auto_row.operator("hrs.auto_guess", text="Detect Rigs", icon="VIEWZOOM")

        result_row = layout.row(align=True)
        if not input_ready:
            result_row.label(
                text="Select a Source Collection and Target Armature" if batch_mode else "Select a Source and Target Armature",
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
        in_place_row.prop(scene, "hrs_retarget_keep_in_place", text="In-Place")

        action = layout.row(align=True)
        action.scale_y = 1.35
        run_col = action.column(align=True)
        run_col.enabled = bool(input_ready and scene.hrs_can_execute_retarget)
        run_col.operator(
            "hrs.execute_retarget",
            text="Retarget Batch" if batch_mode else "Run Retarget",
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
                )
            )
        clear_col.operator("hrs.clear_retarget_result", text="Clear Result", icon="TRASH")
        if scene.hrs_retarget_status:
            status_row = layout.row(align=True)
            status_row.label(text=compact_ui_status(scene.hrs_retarget_status), icon="INFO")
