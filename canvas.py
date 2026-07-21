"""Interactive humanoid figure drawing and manual correction controls."""

import math
from pathlib import Path

import blf
import bpy
import bpy.utils.previews
import gpu
from bpy.types import Operator
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .figure_layout import figure_layout_shapes, figure_role_at
from .human_schema import (
    FINGER_ROLE_IDS,
    HUMAN_ROLE_BY_ID,
    HUMAN_ROLES,
    neck_roles,
    spine_roles,
)

from .core import (
    assign_selected_bone_to_role,
    ensure_slots,
    existing_slot_for_role,
    role_ids,
    role_label,
    selected_pose_bone,
    slot_badge,
    visible_role_set,
)

HRS_CANVAS_HANDLERS = []

HRS_CANVAS_SHADER = None

HRS_PREVIEW_COLLECTION = None

HRS_FLOAT_CANVAS_STATE = {"action": None, "start_mouse": (0, 0), "start_rect": (0, 0, 0, 0)}

HRS_FLOAT_CANVAS_MIN_WIDTH = 280

HRS_FLOAT_CANVAS_MIN_HEIGHT = 420

HRS_FLOAT_CANVAS_MAX_WIDTH = 760

HRS_FLOAT_CANVAS_MAX_HEIGHT = 920

HRS_PANEL_CANVAS_PAD_X = 28

HRS_PANEL_CANVAS_PAD_TOP = 34

HRS_PANEL_CANVAS_PAD_BOTTOM = 58

HRS_CANVAS_FIT_BOUNDS = (0.20, 0.08, 0.80, 0.88)

HRS_NATIVE_FIGURE_MIN_SCALE = 4.8

HRS_NATIVE_FIGURE_MAX_SCALE = 8.6

HRS_CANVAS_CENTER_COLOR = (0.18, 0.66, 0.74, 0.94)

HRS_CANVAS_LEFT_COLOR = (0.82, 0.23, 0.17, 0.94)

HRS_CANVAS_RIGHT_COLOR = (0.22, 0.42, 0.92, 0.94)

HRS_CANVAS_SELECTED_COLOR = (0.98, 0.74, 0.22, 0.98)

HRS_CANVAS_MUTED_COLOR = (0.62, 0.62, 0.60, 0.90)

def compact_bone_name(name, limit=18):
    if not name:
        return "-"
    return name if len(name) <= limit else "..." + name[-limit + 3 :]

def compact_ui_status(text, limit=38):
    message = str(text or "").split("; ", 1)[0].strip().rstrip(".")
    if len(message) <= limit:
        return message
    return message[: limit - 3] + "..."

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
    side_text = "Left Hand" if side == "left" else "Right Hand"
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
        row.label(text="Failed to load the humanoid figure")

def draw_panel_humanoid_button_grid(layout, scene):
    figure = layout.column(align=True)
    figure.scale_y = 1.0
    figure.prop(scene, "hrs_show_fingers", text="Show Finger Slots")

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
    open_row = layout.row(align=True)
    open_row.scale_y = 1.25
    open_row.operator("hrs.open_humanoid_canvas", text="Open Humanoid Correction Panel", icon="OUTLINER_OB_ARMATURE")
    if scene.hrs_canvas_active_role:
        layout.label(text=f"Last Region: {canvas_short_label(scene, scene.hrs_canvas_active_role)}")

    toggle = layout.row(align=True)
    show_buttons = getattr(scene, "hrs_show_native_role_buttons", False)
    icon = "TRIA_DOWN" if show_buttons else "TRIA_RIGHT"
    toggle.prop(scene, "hrs_show_native_role_buttons", text="Detailed Correction Buttons", icon=icon, emboss=False)
    if show_buttons:
        draw_panel_humanoid_button_grid(layout, scene)

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

def canvas_shader():
    global HRS_CANVAS_SHADER
    if HRS_CANVAS_SHADER is None:
        HRS_CANVAS_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return HRS_CANVAS_SHADER

def canvas_short_label(scene, role_id):
    labels = {
        "head": "Head",
        "hips": "Hips",
        "left_shoulder": "Left Shoulder",
        "right_shoulder": "Right Shoulder",
        "left_upper_arm": "Left Upper Arm",
        "right_upper_arm": "Right Upper Arm",
        "left_lower_arm": "Left Forearm",
        "right_lower_arm": "Right Forearm",
        "left_hand": "Left Hand",
        "right_hand": "Right Hand",
        "left_upper_leg": "Left Thigh",
        "right_upper_leg": "Right Thigh",
        "left_lower_leg": "Left Shin",
        "right_lower_leg": "Right Shin",
        "left_foot": "Left Foot",
        "right_foot": "Right Foot",
        "left_toe": "Left Toes",
        "right_toe": "Right Toes",
        "left_thumb": "L Thumb",
        "left_index": "L Index",
        "left_middle": "L Middle",
        "left_ring": "L Ring",
        "left_pinky": "L Pinky",
        "right_thumb": "R Thumb",
        "right_index": "R Index",
        "right_middle": "R Middle",
        "right_ring": "R Ring",
        "right_pinky": "R Pinky",
    }
    if role_id.startswith("neck_"):
        return "Neck" if scene.hrs_neck_count == 1 else f"Neck{int(role_id[-2:])}"
    if role_id.startswith("spine_"):
        index = int(role_id[-2:])
        spine_count = max(1, min(MAX_SPINE_COUNT, int(scene.hrs_spine_count)))
        if scene.hrs_spine_count == 1:
            return "Chest/Spine"
        if index == spine_count:
            return "Chest"
        return f"Spine {index}"
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
    text = bpy.app.translations.pgettext_iface(text)
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

    mode_label = bpy.app.translations.pgettext_iface(
        "Source Bones" if scene.hrs_assign_mode == "SOURCE" else "Target Bones"
    )
    selected = selected_pose_bone(bpy.context)
    selected_name = selected.name if selected else bpy.app.translations.pgettext_iface("Nothing Selected")
    draw_canvas_text("Humanoid Bone Correction", x + 14, y + height - 22, size=13, center=False)
    assign_label = bpy.app.translations.pgettext_iface("Assign: ")
    current_label = bpy.app.translations.pgettext_iface("  Current: ")
    draw_canvas_text(f"{assign_label}{mode_label}{current_label}{selected_name}", x + 14, y + height - 39, size=10, color=(0.82, 0.82, 0.82, 0.92), center=False)

    bottom_y = y + 18
    draw_canvas_text("Drag title bar / Resize lower-right / Click body region / X or Esc to close", x + width * 0.5, bottom_y, size=10, color=(0.82, 0.82, 0.82, 0.92))
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

class HRS_OT_open_humanoid_canvas(Operator):
    bl_idname = "hrs.open_humanoid_canvas"
    bl_label = "Open Humanoid Mapping Figure"
    bl_options = {"REGISTER"}

    _handler = None

    def _start(self, context):
        if not context.area or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "Open the humanoid mapping figure from the 3D View sidebar")
            return {"CANCELLED"}
        region = view3d_window_region(context)
        if region is None:
            self.report({"ERROR"}, "No 3D View window region was found")
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
        self.report({"INFO"}, "Humanoid mapping panel opened. Drag the title bar to move, resize from the lower-right corner, and click a body region to assign a bone.")
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
