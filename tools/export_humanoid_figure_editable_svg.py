from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1]
FIGURE_LAYOUT = PACKAGE_DIR / "figure_layout.py"
SIZE = 512


def load_layout_module():
    spec = importlib.util.spec_from_file_location("hrs_figure_layout_edit_source", FIGURE_LAYOUT)
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


def px(point):
    x, y = point
    return (x * SIZE, y * SIZE)


def point_string(point):
    x, y = px(point)
    return f"{x:.3f},{y:.3f}"


def svg_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def polygon_xml(shape, index):
    role_id = shape["role_id"]
    points = " ".join(point_string(point) for point in shape["points"])
    group_id = f"{role_id}__{index:02d}"
    return (
        f'  <g id="{svg_escape(group_id)}" data-role="{svg_escape(role_id)}" '
        f'data-shape-index="{index}">\n'
        f"    <title>{svg_escape(group_id)}</title>\n"
        f'    <polygon points="{points}" fill="#f2f2ee" stroke="#161717" '
        'stroke-width="1.15" stroke-linejoin="round"/>\n'
        "  </g>\n"
    )


def export_svg(output_path: Path, neck_count: int, spine_count: int):
    layout = load_layout_module()
    shapes = sorted(
        layout.figure_layout_shapes(neck_count, spine_count, True),
        key=shape_area,
        reverse=True,
    )
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n',
        f"  <title>Humanoid Remap Studio manual edit n{neck_count} s{spine_count}</title>\n",
        "  <desc>Clean editable SVG. Keep data-role/data-shape-index when saving back.</desc>\n",
        '  <rect id="background" width="512" height="512" rx="8" fill="#2a2b2b"/>\n',
    ]
    for index, shape in enumerate(shapes):
        parts.append(polygon_xml(shape, index))
    parts.append("</svg>\n")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(parts), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Export a clean editable humanoid figure SVG.")
    parser.add_argument("--output", required=True, help="Output SVG path.")
    parser.add_argument("--neck-count", type=int, default=1)
    parser.add_argument("--spine-count", type=int, default=2)
    args = parser.parse_args()
    output_path = Path(args.output)
    export_svg(output_path, args.neck_count, args.spine_count)
    print(output_path)


if __name__ == "__main__":
    main()
