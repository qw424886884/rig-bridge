bl_info = {
    "name": "Rig Bridge",
    "author": "帧给你你来K",
    "version": (0, 1, 62),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Motion Remap > Humanoid Retarget",
    "description": "Move animation between humanoid rigs automatically.",
    "category": "Animation",
}

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import canvas, core, operators, retarget, translations, ui
from .human_schema import MAX_NECK_COUNT, MAX_SPINE_COUNT


CLASSES = (
    operators.HRSMappingSlot,
    operators.HRS_OT_init_slots,
    operators.HRS_OT_assign_selected_bone,
    operators.HRS_OT_pick_armature,
    operators.HRS_OT_execute_retarget,
    operators.HRS_OT_clear_retarget_result,
    canvas.HRS_OT_open_humanoid_canvas,
    canvas.HRS_OT_panel_figure_modal,
    operators.HRS_OT_auto_guess,
    ui.HRS_UL_mapping_slots,
    ui.HRS_PT_main,
)


SCENE_PROPERTIES = (
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
)

TRANSLATION_DOMAIN = __package__ or __name__
_TRANSLATIONS_REGISTERED = False


def register():
    global _TRANSLATIONS_REGISTERED
    if not _TRANSLATIONS_REGISTERED:
        bpy.app.translations.register(TRANSLATION_DOMAIN, translations.TRANSLATIONS)
        _TRANSLATIONS_REGISTERED = True

    canvas.HRS_PANEL_CLICK_MODAL_RUNNING = False
    canvas.clear_humanoid_canvas_handlers()
    canvas.clear_humanoid_panel_draw_handlers()
    canvas.clear_humanoid_previews()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if canvas.HRS_PANEL_EMBEDDED_CLICK_ENABLED:
        canvas.ensure_humanoid_panel_draw_handler()
        bpy.app.timers.register(canvas.start_panel_figure_modal, first_interval=0.2)

    bpy.types.Scene.hrs_source_mode = EnumProperty(
        name="Source Mode",
        items=[
            ("SINGLE", "Single", "Retarget one source armature"),
            ("COLLECTION", "Batch Collection", "Retarget every valid source armature in the collection"),
        ],
        default="SINGLE",
        update=core.update_source_mode,
    )
    bpy.types.Scene.hrs_source_collection = PointerProperty(
        name="Source Collection", type=bpy.types.Collection, update=core.update_source_collection
    )
    bpy.types.Scene.hrs_batch_ready = BoolProperty(name="Batch Ready", default=False)
    bpy.types.Scene.hrs_batch_results_json = StringProperty(name="Batch Results", default="[]")
    bpy.types.Scene.hrs_last_batch_id = StringProperty(name="Last Batch ID", default="")
    bpy.types.Scene.hrs_source_armature = PointerProperty(
        name="Source Armature", type=bpy.types.Object, poll=core.armature_poll,
        update=core.update_source_armature_pointer,
    )
    bpy.types.Scene.hrs_target_armature = PointerProperty(
        name="Target Armature", type=bpy.types.Object, poll=core.armature_poll,
        update=core.update_target_armature_pointer,
    )
    bpy.types.Scene.hrs_source_armature_name = StringProperty(
        name="Source Armature", update=core.update_source_armature_name
    )
    bpy.types.Scene.hrs_target_armature_name = StringProperty(
        name="Target Armature", update=core.update_target_armature_name
    )
    bpy.types.Scene.hrs_assign_mode = EnumProperty(
        name="Current Assignment",
        items=[
            ("SOURCE", "Source Bone", "Assign the selected source bone when clicking a humanoid region"),
            ("TARGET", "Target Bone", "Assign the selected target bone when clicking a humanoid region"),
        ],
        default="SOURCE",
    )
    bpy.types.Scene.hrs_neck_count = IntProperty(
        name="Neck Segments", default=1, min=1, max=MAX_NECK_COUNT
    )
    bpy.types.Scene.hrs_spine_count = IntProperty(
        name="Spine Segments", default=3, min=1, max=MAX_SPINE_COUNT
    )
    bpy.types.Scene.hrs_show_fingers = BoolProperty(name="Show Finger Slots", default=True)
    bpy.types.Scene.hrs_show_native_role_buttons = BoolProperty(
        name="Show Manual Slot Buttons", default=False
    )
    bpy.types.Scene.hrs_show_manual_correction = BoolProperty(name="Show Manual Correction", default=False)
    bpy.types.Scene.hrs_panel_canvas_height = IntProperty(
        name="Humanoid Figure Height", default=canvas.HRS_PANEL_DEFAULT_HEIGHT,
        min=canvas.HRS_PANEL_MIN_HEIGHT, max=canvas.HRS_PANEL_MAX_HEIGHT,
    )
    bpy.types.Scene.hrs_show_mapping_status = BoolProperty(name="Show Mapping Status", default=False)
    bpy.types.Scene.hrs_auto_summary = StringProperty(name="Detection Summary", default="Auto Detect has not been run.")
    bpy.types.Scene.hrs_auto_detail = StringProperty(
        name="Detection Details", default="Select two humanoid armatures, then click Auto Detect."
    )
    bpy.types.Scene.hrs_source_profile = StringProperty(name="Source Rig Profile", default="Not Selected")
    bpy.types.Scene.hrs_target_profile = StringProperty(name="Target Rig Profile", default="Not Selected")
    bpy.types.Scene.hrs_can_execute_retarget = BoolProperty(name="Ready to Retarget", default=False)
    bpy.types.Scene.hrs_show_retarget_settings = BoolProperty(name="Show Retarget Settings", default=False)
    bpy.types.Scene.hrs_source_root_motion_known = BoolProperty(
        name="Source Root Motion Evaluated", default=False
    )
    bpy.types.Scene.hrs_source_has_root_motion = BoolProperty(name="Source Has Root Motion", default=False)
    bpy.types.Scene.hrs_source_root_motion_delta = FloatProperty(
        name="Source Root Motion", default=0.0, min=0.0, precision=4
    )
    bpy.types.Scene.hrs_source_motion_root_bone = StringProperty(name="Source Motion Root Bone", default="")
    bpy.types.Scene.hrs_retarget_keep_in_place = BoolProperty(
        name="In-Place", default=False, update=retarget.update_retarget_keep_in_place
    )
    bpy.types.Scene.hrs_retarget_auto_rest_delta = BoolProperty(
        name="Evaluate Rest-Pose Difference Automatically", default=True
    )
    bpy.types.Scene.hrs_retarget_status = StringProperty(name="Retarget Status", default="")
    bpy.types.Scene.hrs_canvas_active_role = StringProperty(name="Last Selected Region", default="")
    bpy.types.Scene.hrs_canvas_x = IntProperty(default=-1, min=-4096, max=4096)
    bpy.types.Scene.hrs_canvas_y = IntProperty(default=-1, min=-4096, max=4096)
    bpy.types.Scene.hrs_canvas_width = IntProperty(
        name="Humanoid Panel Width", default=360,
        min=canvas.HRS_FLOAT_CANVAS_MIN_WIDTH, max=canvas.HRS_FLOAT_CANVAS_MAX_WIDTH,
    )
    bpy.types.Scene.hrs_canvas_height = IntProperty(
        name="Humanoid Panel Height", default=600,
        min=canvas.HRS_FLOAT_CANVAS_MIN_HEIGHT, max=canvas.HRS_FLOAT_CANVAS_MAX_HEIGHT,
    )
    bpy.types.Scene.hrs_mapping_slot_index = IntProperty(default=0)
    bpy.types.Scene.hrs_mapping_slots = CollectionProperty(type=operators.HRSMappingSlot)
    bpy.app.timers.register(core.sync_scene_armature_names_timer, first_interval=0.1)


def unregister():
    global _TRANSLATIONS_REGISTERED
    canvas.HRS_PANEL_CLICK_MODAL_RUNNING = False
    canvas.clear_humanoid_canvas_handlers()
    canvas.clear_humanoid_panel_draw_handlers()
    canvas.clear_humanoid_previews()
    for timer in (canvas.start_panel_figure_modal, core.sync_scene_armature_names_timer):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    for prop_name in SCENE_PROPERTIES:
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if _TRANSLATIONS_REGISTERED:
        bpy.app.translations.unregister(TRANSLATION_DOMAIN)
        _TRANSLATIONS_REGISTERED = False
