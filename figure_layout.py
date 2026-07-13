import math


SIZE = 512.0
MAX_NECK_COUNT = 3
MAX_SPINE_COUNT = 6
FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")
FINGER_ROLE_IDS = {f"{side}_{name}" for side in ("left", "right") for name in FINGER_NAMES}


def _add(shapes, role_id, kind="poly", points=None, center=None, radius=0.0, label=True):
    shapes.append(
        {
            "role_id": role_id,
            "kind": kind,
            "points": points or [],
            "center": center,
            "radius": radius,
            "label": label,
        }
    )


def _px(point):
    x, y = point
    return (x / SIZE, y / SIZE)


def _px_poly(points):
    return [_px(point) for point in points]


def _px_rect(x0, y0, x1, y1):
    return _px_poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _mirror_points(points):
    return [(SIZE - x, y) for x, y in points]


def _mirror_rect(rect):
    x0, y0, x1, y1 = rect
    return (SIZE - x1, y0, SIZE - x0, y1)


def _add_rect(shapes, role_id, x0, y0, x1, y1, label=True):
    _add(shapes, role_id, points=_px_rect(x0, y0, x1, y1), label=label)


def _add_poly(shapes, role_id, points, label=True):
    _add(shapes, role_id, points=_px_poly(points), label=label)


def _interp(a, b, t):
    return a + (b - a) * t


def _add_oriented_rect(shapes, role_id, start, end, width, label=True):
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0.0001:
        return
    nx = -dy / length * width * 0.5
    ny = dx / length * width * 0.5
    _add_poly(
        shapes,
        role_id,
        [
            (x0 + nx, y0 + ny),
            (x1 + nx, y1 + ny),
            (x1 - nx, y1 - ny),
            (x0 - nx, y0 - ny),
        ],
        label=label,
    )


def _neck_roles(count):
    count = max(1, min(MAX_NECK_COUNT, int(count)))
    return [f"neck_{index:02d}" for index in range(count, 0, -1)]


def _spine_roles(count):
    count = max(1, min(MAX_SPINE_COUNT, int(count)))
    return [f"spine_{index:02d}" for index in range(count, 0, -1)]


def _adaptive_gap(y0, y1, count, preferred_gap):
    count = max(1, int(count))
    if count <= 1:
        return 0.0
    height = max(1.0, y1 - y0)
    # Keep the original silhouette readable when the same base block is split
    # into many small semantic bones.
    max_gap = height / (count * 3.0)
    return min(float(preferred_gap), max_gap)


def _split_rect_vertical(x0, y0, x1, y1, count, preferred_gap=3.0):
    count = max(1, int(count))
    gap = _adaptive_gap(y0, y1, count, preferred_gap)
    total_gap = gap * (count - 1)
    height = (y1 - y0 - total_gap) / count
    rects = []
    for index in range(count):
        by0 = y0 + index * (height + gap)
        by1 = by0 + height
        rects.append((x0, by0, x1, by1))
    return rects


def _add_counted_neck(shapes, count):
    roles = _neck_roles(count)
    # One square neck block split by count, so 1/2/3 neck rigs use the same
    # silhouette and only change semantic subdivisions.
    for role_id, rect in zip(roles, _split_rect_vertical(248, 105, 264, 121, len(roles), 2)):
        _add_rect(shapes, role_id, *rect)


def _add_spine(shapes, count):
    roles = _spine_roles(count)
    chest_role = roles[0]
    _add_poly(shapes, chest_role, [(226, 125), (286, 125), (280, 168), (233, 169)])

    if len(roles) == 1:
        return

    lower_roles = roles[1:]
    # The space between chest and hips is one base spine block. Split it
    # vertically by the requested count instead of maintaining per-count art.
    for role_id, rect in zip(lower_roles, _split_rect_vertical(243, 173, 269, 220, len(lower_roles), 4)):
        _add_rect(shapes, role_id, *rect)


def _finger_chain(shapes, role_id, start, end, width, label=True):
    gap = 2.0
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length <= gap * 2.0:
        return
    ux = dx / length
    uy = dy / length
    segment_length = (length - gap * 2.0) / 3.0
    for index in range(3):
        start_offset = index * (segment_length + gap)
        end_offset = start_offset + segment_length
        p0 = (x0 + ux * start_offset, y0 + uy * start_offset)
        p1 = (x0 + ux * end_offset, y0 + uy * end_offset)
        _add_oriented_rect(shapes, role_id, p0, p1, width, label=label and index == 1)


def _finger_segments(shapes, role_id, x0, y0, x1, y1, label=True):
    center_x = (x0 + x1) * 0.5
    _finger_chain(shapes, role_id, (center_x, y0), (center_x, y1), x1 - x0, label=label)


def _add_fingers(shapes):
    left_rects = {
        "left_thumb": [
            (168.86, 280.0, 176.17, 290.0),
            (168.86, 292.0, 176.17, 302.0),
            (168.86, 304.0, 176.17, 314.0),
        ],
        "left_pinky": [
            (118.28, 306.0, 124.89, 317.18),
            (118.28, 319.41, 124.89, 330.59),
            (118.28, 332.82, 124.89, 344.0),
        ],
        "left_ring": [
            (129.3, 306.0, 135.91, 317.18),
            (129.3, 319.41, 135.91, 330.59),
            (129.3, 332.82, 135.91, 344.0),
        ],
        "left_middle": [
            (140.31, 306.0, 146.93, 317.18),
            (140.31, 319.41, 146.93, 330.59),
            (140.31, 332.82, 146.93, 344.0),
        ],
        "left_index": [
            (151.89, 306.0, 158.5, 317.18),
            (151.89, 319.41, 158.5, 330.59),
            (151.89, 332.82, 158.5, 344.0),
        ],
    }
    for left_role, rects in left_rects.items():
        for index, rect in enumerate(rects):
            _add_rect(shapes, left_role, *rect, label=index == 1)
        right_role = "right_" + left_role[len("left_") :]
        for index, rect in enumerate(rects):
            _add_rect(shapes, right_role, *_mirror_rect(rect), label=index == 1)


def figure_layout_shapes(neck_count=1, spine_count=2, show_fingers=True):
    shapes = []

    _add_rect(shapes, "head", 237, 63, 276, 101)
    _add_counted_neck(shapes, neck_count)
    _add_spine(shapes, spine_count)
    _add_poly(shapes, "hips", [(226, 242), (239, 224), (272, 224), (285, 244), (263, 251), (248, 251)])

    left_upper_arm = [(160, 189), (175, 129), (199, 132), (199, 142), (179, 199), (160, 195)]
    left_shoulder = [(205, 132), (224, 134), (223, 143), (204, 141)]
    left_lower_arm = [(142, 253), (157, 204), (159, 198), (174, 202), (175, 208), (161, 256), (146, 256)]
    left_hand = [(131, 287.5), (138, 263.5), (155, 264.5), (152, 296.5), (134, 296.5)]
    _add_poly(shapes, "left_upper_arm", left_upper_arm)
    _add_poly(shapes, "right_upper_arm", _mirror_points(left_upper_arm))
    _add_poly(shapes, "left_shoulder", left_shoulder)
    _add_poly(shapes, "right_shoulder", _mirror_points(left_shoulder))
    _add_poly(shapes, "left_lower_arm", left_lower_arm)
    _add_poly(shapes, "right_lower_arm", _mirror_points(left_lower_arm))
    _add_poly(shapes, "left_hand", left_hand)
    _add_poly(shapes, "right_hand", _mirror_points(left_hand))

    if show_fingers:
        _add_fingers(shapes)

    left_upper_leg = [(215, 326), (221, 249), (226, 248), (246, 254), (247, 258), (236, 329), (219, 329)]
    left_lower_leg = [(214, 359), (215, 335), (227, 334), (236, 337), (224, 423), (214, 421)]
    left_foot = [(204, 428.5), (232, 428.5), (233, 429.5), (233, 436.5), (232, 437.5), (205, 437.5), (204, 436.5)]
    _add_poly(shapes, "left_upper_leg", left_upper_leg)
    _add_poly(shapes, "right_upper_leg", _mirror_points(left_upper_leg))
    _add_poly(shapes, "left_lower_leg", left_lower_leg)
    _add_poly(shapes, "right_lower_leg", _mirror_points(left_lower_leg))
    _add_poly(shapes, "left_foot", left_foot)
    _add_poly(shapes, "right_foot", _mirror_points(left_foot))
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


def _distance_to_segment(point, start, end):
    px, py = point
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0000001:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
    closest = (x0 + dx * t, y0 + dy * t)
    return math.dist(point, closest)


def polygon_distance(point, polygon):
    if point_in_polygon(point, polygon):
        return 0.0
    if not polygon:
        return 999.0
    return min(
        _distance_to_segment(point, polygon[index], polygon[(index + 1) % len(polygon)])
        for index in range(len(polygon))
    )


def point_in_layout_shape(point, shape):
    if shape["kind"] == "circle":
        return math.dist(point, shape["center"]) <= shape["radius"]
    return point_in_polygon(point, shape["points"])


def figure_role_at(neck_count, spine_count, show_fingers, point):
    shapes = figure_layout_shapes(neck_count, spine_count, show_fingers)
    for shape in reversed(shapes):
        if point_in_layout_shape(point, shape):
            return shape["role_id"]
    if show_fingers:
        best_role = None
        best_distance = 0.018
        for shape in reversed(shapes):
            if shape["role_id"] not in FINGER_ROLE_IDS or shape["kind"] == "circle":
                continue
            distance = polygon_distance(point, shape["points"])
            if distance < best_distance:
                best_distance = distance
                best_role = shape["role_id"]
        if best_role:
            return best_role
    return None
