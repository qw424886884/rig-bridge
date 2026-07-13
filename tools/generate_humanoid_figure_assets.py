from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw


PACKAGE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = PACKAGE_DIR / "icons" / "humanoid"
FIGURE_LAYOUT = PACKAGE_DIR / "figure_layout.py"
SIZE = 512
SCALE = 4

BACKGROUND = (33, 34, 34, 255)
PANEL = (42, 43, 43, 255)
BODY_FILL = (218, 218, 214, 255)
CORE_FILL = (232, 232, 228, 255)
FINGER_FILL = (242, 242, 238, 255)
OUTLINE = (234, 234, 226, 92)
SHADOW = (10, 11, 11, 100)
BACKGROUND_CACHE = None

CORE_ROLES = {"head", "hips", "left_shoulder", "right_shoulder"}
FINGER_ROLES = {
    "left_thumb",
    "left_index",
    "left_middle",
    "left_ring",
    "left_pinky",
    "right_thumb",
    "right_index",
    "right_middle",
    "right_ring",
    "right_pinky",
}


def load_layout_module():
    spec = importlib.util.spec_from_file_location("hrs_figure_layout_asset_source", FIGURE_LAYOUT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shape_area(shape):
    points = shape.get("points", [])
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return abs(total) * 0.5


def color_for_role(role_id):
    if role_id in FINGER_ROLES or "hand" in role_id:
        return FINGER_FILL
    if role_id in CORE_ROLES or role_id.startswith("neck_") or role_id.startswith("spine_"):
        return CORE_FILL
    return BODY_FILL


def scale_point(point):
    x, y = point
    return (int(round(x * SIZE * SCALE)), int(round(y * SIZE * SCALE)))


def background_image():
    global BACKGROUND_CACHE
    if BACKGROUND_CACHE is not None:
        return BACKGROUND_CACHE.copy()
    image = Image.new("RGBA", (SIZE, SIZE), BACKGROUND)
    pixels = image.load()
    cx = SIZE * 0.5
    cy = SIZE * 0.5
    max_radius = (cx * cx + cy * cy) ** 0.5
    for y in range(SIZE):
        for x in range(SIZE):
            radius = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / max_radius
            glow = max(0.0, 1.0 - radius) ** 1.6
            value = int(26 + 17 * glow)
            pixels[x, y] = (value, value + 1, value + 1, 255)
    BACKGROUND_CACHE = image.resize((SIZE * SCALE, SIZE * SCALE), Image.Resampling.BICUBIC)
    return BACKGROUND_CACHE.copy()


def draw_polygon(draw, points, fill, outline=OUTLINE, width=0.65):
    scaled = [scale_point(point) for point in points]
    draw.polygon(scaled, fill=fill)
    draw.line([*scaled, scaled[0]], fill=outline, width=max(1, int(round(width * SCALE))), joint="curve")


def render_png(neck_count, spine_count):
    layout = load_layout_module()
    shapes = sorted(
        layout.figure_layout_shapes(neck_count, spine_count, True),
        key=shape_area,
        reverse=True,
    )
    image = background_image()
    draw = ImageDraw.Draw(image, "RGBA")

    for shape in shapes:
        points = [(x + 0.004, y + 0.006) for x, y in shape["points"]]
        draw_polygon(draw, points, SHADOW, outline=(0, 0, 0, 0), width=0)

    for shape in shapes:
        draw_polygon(draw, shape["points"], color_for_role(shape["role_id"]))

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def point_string(point):
    return f"{point[0] * SIZE:.2f},{point[1] * SIZE:.2f}"


def svg_polygon(shape, dx=0.0, dy=0.0, fill="#dadad6", opacity="1"):
    points = " ".join(point_string((x + dx, y + dy)) for x, y in shape["points"])
    role_id = shape["role_id"]
    return (
        f'  <polygon data-role="{role_id}" points="{points}" '
        f'fill="{fill}" fill-opacity="{opacity}" stroke="#f6f6f0" stroke-width="1.15" '
        'stroke-linejoin="round"/>\n'
    )


def svg_fill_for_role(role_id):
    if role_id in FINGER_ROLES or "hand" in role_id:
        return "#f2f2ee"
    if role_id in CORE_ROLES or role_id.startswith("neck_") or role_id.startswith("spine_"):
        return "#e8e8e4"
    return "#dadad6"


def render_svg(neck_count, spine_count):
    layout = load_layout_module()
    shapes = sorted(
        layout.figure_layout_shapes(neck_count, spine_count, True),
        key=shape_area,
        reverse=True,
    )
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n',
        f"  <title>Humanoid Remap Studio vector figure n{neck_count} s{spine_count}</title>\n",
        "  <desc>Generated from figure_layout.py vector anatomy parts; no PNG base or bitmap cuts.</desc>\n",
        '  <rect width="512" height="512" rx="8" fill="#2a2b2b"/>\n',
    ]
    for shape in shapes:
        parts.append(svg_polygon(shape, dx=0.004, dy=0.006, fill="#080909", opacity="0.34"))
    for shape in shapes:
        parts.append(svg_polygon(shape, fill=svg_fill_for_role(shape["role_id"])))
    parts.append("</svg>\n")
    return "".join(parts)


def write_assets():
    layout = load_layout_module()
    max_neck_count = getattr(layout, "MAX_NECK_COUNT", 3)
    max_spine_count = getattr(layout, "MAX_SPINE_COUNT", 3)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": "figure_layout.py",
        "generated": [],
        "notes": [
            "Generated directly from vector anatomy parts.",
            "PNG files are previews/legacy assets only; the editable source is figure_layout.py.",
            "No locked base PNG or bitmap editing workflow is used.",
        ],
    }
    for neck_count in range(1, max_neck_count + 1):
        for spine_count in range(1, max_spine_count + 1):
            stem = f"figure_clean_n{neck_count}_s{spine_count}"
            png_name = f"{stem}.png"
            svg_name = f"{stem}.svg"
            render_png(neck_count, spine_count).save(OUT_DIR / png_name)
            (OUT_DIR / svg_name).write_text(render_svg(neck_count, spine_count), encoding="utf-8")
            manifest["generated"].extend([png_name, svg_name])

    default = render_png(1, 2)
    for alias in ("figure.png", "figure_block.png", "figure_rig_ref.png", "figure_vector_ref.png"):
        default.save(OUT_DIR / alias)
    (OUT_DIR / "figure_vector_ref.svg").write_text(render_svg(1, 2), encoding="utf-8")
    manifest["generated"].extend(
        ["figure.png", "figure_block.png", "figure_rig_ref.png", "figure_vector_ref.png", "figure_vector_ref.svg"]
    )

    (OUT_DIR / "figure_layout_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "out": str(OUT_DIR), "count": len(manifest["generated"])}, ensure_ascii=False))


if __name__ == "__main__":
    write_assets()
