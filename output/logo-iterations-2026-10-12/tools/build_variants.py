"""Build Roommate icon variants as SVG from one parametric geometry.

Run: python3 build_variants.py OUT_DIR

Every variant is a 512 unit square badge. Coordinates are screen space,
polygons are listed clockwise. The lamp pieces (shade, bulb, stem, leg)
keep one gap value between them, measured as a Minkowski clearance
around the bulb, so the orange separation looks even at every size.
"""

import math
import sys
from pathlib import Path

IVORY = "#FFF9ED"
BULB = "#FFDD68"
GRADIENT = ("#FF9B32", "#FB7C20", "#F26B18")
BADGE = 512


def fmt(value):
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def unit(vec):
    length = math.hypot(*vec)
    return (vec[0] / length, vec[1] / length)


def add(point, vec, scale=1.0):
    return (point[0] + vec[0] * scale, point[1] + vec[1] * scale)


def sub(point_a, point_b):
    return (point_a[0] - point_b[0], point_a[1] - point_b[1])


def inward(direction):
    """Inward normal for a clockwise polygon in screen space."""
    return (-direction[1], direction[0])


def angle_of(centre, point):
    return math.atan2(point[1] - centre[1], point[0] - centre[0])


class PathBuilder:
    def __init__(self):
        self.parts = []
        self.current = None

    def move_to(self, point):
        self.parts.append(f"M{fmt(point[0])} {fmt(point[1])}")
        self.current = point

    def line_to(self, point):
        if self.current is not None and math.dist(self.current, point) < 1e-6:
            return
        self.parts.append(f"L{fmt(point[0])} {fmt(point[1])}")
        self.current = point

    def arc_to(self, centre, radius, point, clockwise):
        start = angle_of(centre, self.current)
        end = angle_of(centre, point)
        delta = (end - start) % (2 * math.pi)
        if not clockwise:
            delta = (start - end) % (2 * math.pi)
        large = 1 if delta > math.pi else 0
        sweep = 1 if clockwise else 0
        self.parts.append(
            f"A{fmt(radius)} {fmt(radius)} 0 {large} {sweep} {fmt(point[0])} {fmt(point[1])}"
        )
        self.current = point

    def close(self):
        self.parts.append("Z")

    def data(self):
        return " ".join(self.parts)


def rounded_corners(vertices, radii):
    """Return primitives for a clockwise convex polygon with rounded corners."""
    count = len(vertices)
    corners = []
    for index in range(count):
        previous = vertices[index - 1]
        vertex = vertices[index]
        following = vertices[(index + 1) % count]
        into = unit(sub(vertex, previous))
        out = unit(sub(following, vertex))
        radius = radii[index]
        if radius <= 0:
            corners.append((vertex, vertex, None))
            continue
        cos_turn = max(-1.0, min(1.0, into[0] * out[0] + into[1] * out[1]))
        turn = math.acos(cos_turn)
        interior = math.pi - turn
        tangent = radius / math.tan(interior / 2)
        start = add(vertex, into, -tangent)
        end = add(vertex, out, tangent)
        centre = add(start, inward(into), radius)
        corners.append((start, end, centre))
    primitives = []
    for index in range(count):
        start, end, centre = corners[index]
        if centre is not None:
            primitives.append(("arc", centre, radii[index], start, end))
        next_start = corners[(index + 1) % count][0]
        primitives.append(("line", end, next_start))
    return primitives


def line_circle_crossings(start, end, centre, radius):
    """Parameters in [0, 1] where the segment crosses the circle."""
    direction = sub(end, start)
    offset = sub(start, centre)
    quad_a = direction[0] ** 2 + direction[1] ** 2
    quad_b = 2 * (offset[0] * direction[0] + offset[1] * direction[1])
    quad_c = offset[0] ** 2 + offset[1] ** 2 - radius**2
    discriminant = quad_b**2 - 4 * quad_a * quad_c
    if discriminant <= 0:
        return []
    root = math.sqrt(discriminant)
    candidates = [(-quad_b - root) / (2 * quad_a), (-quad_b + root) / (2 * quad_a)]
    return [value for value in candidates if 0 <= value <= 1]


def fillet_between(line_point, direction, centre, radius, fillet, after):
    """Fillet tangent to a line and externally tangent to a circle.

    direction is the unit travel direction along the line, the polygon
    interior lies to its right. after=True picks the solution past the
    crossing in the travel direction, False the one before it.
    Returns (line_tangent, circle_tangent, fillet_centre).
    """
    normal = inward(direction)
    offset_point = add(line_point, normal, fillet)
    rel = sub(offset_point, centre)
    quad_b = 2 * (rel[0] * direction[0] + rel[1] * direction[1])
    quad_c = rel[0] ** 2 + rel[1] ** 2 - (radius + fillet) ** 2
    root = math.sqrt(quad_b**2 - 4 * quad_c)
    roots = sorted([(-quad_b - root) / 2, (-quad_b + root) / 2])
    along = roots[1] if after else roots[0]
    fillet_centre = add(offset_point, direction, along)
    line_tangent = add(fillet_centre, normal, -fillet)
    circle_tangent = add(centre, unit(sub(fillet_centre, centre)), radius)
    return line_tangent, circle_tangent, fillet_centre


def emit_primitive(path, primitive):
    kind = primitive[0]
    if kind == "line":
        path.line_to(primitive[2])
    else:
        _, centre, radius, _, end = primitive
        path.arc_to(centre, radius, end, clockwise=True)


def polygon_path(vertices, radii, cut=None, fillets=(10, 10)):
    """Path data for a rounded clockwise polygon, optionally minus a circle.

    fillets gives the radius where the outline enters the cut circle and
    where it leaves it again, in traversal order.
    """
    primitives = rounded_corners(vertices, radii)
    path = PathBuilder()
    if cut is None:
        path.move_to(primitives[0][3] if primitives[0][0] == "arc" else primitives[0][1])
        for primitive in primitives:
            emit_primitive(path, primitive)
        path.close()
        return path.data()

    centre, radius = cut
    entry = exit_ = None
    for index, primitive in enumerate(primitives):
        if primitive[0] != "line":
            start_inside = math.dist(primitive[3], centre) < radius
            end_inside = math.dist(primitive[4], centre) < radius
            assert start_inside == end_inside, "cut circle crosses a rounded corner"
            continue
        start, end = primitive[1], primitive[2]
        for value in line_circle_crossings(start, end, centre, radius):
            point = add(start, sub(end, start), value)
            direction = unit(sub(end, start))
            radial = sub(point, centre)
            entering = direction[0] * radial[0] + direction[1] * radial[1] < 0
            if entering:
                entry = (index, value, point, direction)
            else:
                exit_ = (index, value, point, direction)
    assert entry and exit_, "cut circle must cross the outline twice"

    exit_index, exit_value, exit_point, exit_direction = exit_
    entry_index, entry_value, entry_point, entry_direction = entry
    entry_fillet, exit_fillet = fillets
    exit_line, exit_circle, _ = fillet_between(exit_point, exit_direction, centre, radius, exit_fillet, True)
    entry_line, entry_circle, _ = fillet_between(entry_point, entry_direction, centre, radius, entry_fillet, False)

    count = len(primitives)
    steps = (entry_index - exit_index) % count
    if steps == 0:
        steps = count
    path.move_to(exit_line)
    for step in range(steps + 1):
        primitive = primitives[(exit_index + step) % count]
        if step == steps:
            path.line_to(entry_line)
        else:
            emit_primitive(path, primitive)
    path.arc_to(_fillet_centre(entry_circle, entry_fillet, centre), entry_fillet, entry_circle, clockwise=True)
    path.arc_to(centre, radius, exit_circle, clockwise=False)
    path.arc_to(_fillet_centre(exit_circle, exit_fillet, centre), exit_fillet, exit_line, clockwise=True)
    path.close()
    return path.data()


def _fillet_centre(circle_tangent, fillet, cut_centre):
    """The fillet centre sits on the ray from the cut centre through the tangent point."""
    return add(circle_tangent, unit(sub(circle_tangent, cut_centre)), fillet)


def shade_vertices(bottom_left, bottom_right, top_left, top_right, bottom_y, top_y):
    return [(top_left, top_y), (top_right, top_y), (bottom_right, bottom_y), (bottom_left, bottom_y)]


def leg_vertices(centre, angle_deg, width, baseline, offset=0.0, reach=0.0):
    """Diagonal leg as a clockwise quadrilateral with a flat foot on the baseline.

    The centreline passes through `centre` shifted by `offset` along the
    leg's perpendicular. `reach` moves the top end past the centre.
    """
    angle = math.radians(angle_deg)
    down = (math.cos(angle), math.sin(angle))
    up = (-down[0], -down[1])
    perpendicular = (math.sin(angle), -math.cos(angle))
    axis_point = add(centre, perpendicular, offset)
    length_to_base = (baseline - axis_point[1]) / math.sin(angle)
    base = add(axis_point, down, length_to_base)
    half = width / 2
    top = add(axis_point, up, reach)
    top_inner = add(top, perpendicular, -half)
    top_outer = add(top, perpendicular, half)
    foot = half / math.sin(angle)
    bottom_outer = (base[0] + foot, baseline)
    bottom_inner = (base[0] - foot, baseline)
    return [top_inner, top_outer, bottom_outer, bottom_inner]


def badge(rx=108, gradient_id="orange"):
    stops = "".join(
        f'<stop offset="{offset}" stop-color="{colour}"/>'
        for offset, colour in zip(("0", ".52", "1"), GRADIENT)
    )
    return (
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="{BADGE}" y2="{BADGE}" '
        f'gradientUnits="userSpaceOnUse">{stops}</linearGradient></defs>'
        f'<rect width="{BADGE}" height="{BADGE}" rx="{rx}" fill="url(#{gradient_id})"/>'
    )


def circle_badge(gradient_id="orange"):
    stops = "".join(
        f'<stop offset="{offset}" stop-color="{colour}"/>'
        for offset, colour in zip(("0", ".52", "1"), GRADIENT)
    )
    return (
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="{BADGE}" y2="{BADGE}" '
        f'gradientUnits="userSpaceOnUse">{stops}</linearGradient></defs>'
        f'<circle cx="{BADGE / 2}" cy="{BADGE / 2}" r="{BADGE / 2}" fill="url(#{gradient_id})"/>'
    )


def svg_document(title, description, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BADGE} {BADGE}" role="img" '
        f'aria-labelledby="title description">\n'
        f"  <title id=\"title\">{title}</title>\n"
        f"  <desc id=\"description\">{description}</desc>\n"
        + "".join(f"  {line}\n" for line in body)
        + "</svg>\n"
    )


def half_bulb_path(centre, radius):
    left = (centre[0] - radius, centre[1])
    right = (centre[0] + radius, centre[1])
    return (
        f"M{fmt(left[0])} {fmt(left[1])} H{fmt(right[0])} "
        f"A{fmt(radius)} {fmt(radius)} 0 0 1 {fmt(left[0])} {fmt(left[1])} Z"
    )


def lamp_mark(
    *,
    gap=18,
    bulb_radius=56,
    bulb_centre_x=248,
    shade_top=72,
    shade_bottom=238,
    shade_left=92,
    shade_right=404,
    shade_top_left=152,
    shade_top_right=300,
    shade_radius_top=20,
    shade_radius_bottom=12,
    stem_left=92,
    stem_width=100,
    stem_radius=14,
    baseline=440,
    leg_width=64,
    leg_angle=60,
    leg_offset=0.0,
    leg_radius=14,
    stem_fillets=(12, 20),
    leg_fillets=(18, 18),
    joined_fillet=20,
    leg_anchor_y=None,
    joined=False,
    bulb_style="half",
    ivory=IVORY,
    bulb_colour=BULB,
):
    """Return SVG elements for shade, supports and bulb."""
    elements = []
    bulb_top = shade_bottom + gap
    if bulb_style == "full":
        bulb_centre = (bulb_centre_x, bulb_top + bulb_radius)
    else:
        bulb_centre = (bulb_centre_x, bulb_top)
    clearance = bulb_radius + gap
    cut = (bulb_centre, clearance)

    shade = shade_vertices(
        shade_left, shade_right, shade_top_left, shade_top_right, shade_bottom, shade_top
    )
    shade_radii = [shade_radius_top, shade_radius_top, shade_radius_bottom, shade_radius_bottom]

    support_top = bulb_top
    stem_right = stem_left + stem_width
    stem = [(stem_left, support_top), (stem_right, support_top), (stem_right, baseline), (stem_left, baseline)]
    stem_radii = [stem_radius] * 4

    if joined:
        elements.append(joined_shade_stem(
            shade, shade_radii, stem_left, stem_right, shade_bottom, baseline,
            stem_radius, bulb_centre, bulb_radius, gap, joined_fillet, ivory,
        ))
    else:
        elements.append(f'<path d="{polygon_path(shade, shade_radii)}" fill="{ivory}"/>')
        elements.append(f'<path d="{polygon_path(stem, stem_radii, cut, stem_fillets)}" fill="{ivory}"/>')

    anchor = bulb_centre if leg_anchor_y is None else (bulb_centre[0], leg_anchor_y)
    leg = leg_vertices(anchor, leg_angle, leg_width, baseline, leg_offset, reach=0)
    leg_radii = [0, 0, leg_radius, leg_radius]
    elements.append(f'<path d="{polygon_path(leg, leg_radii, cut, leg_fillets)}" fill="{ivory}"/>')

    if bulb_style == "full":
        elements.append(
            f'<circle cx="{fmt(bulb_centre[0])}" cy="{fmt(bulb_centre[1])}" r="{bulb_radius}" fill="{bulb_colour}"/>'
        )
    else:
        elements.append(f'<path d="{half_bulb_path(bulb_centre, bulb_radius)}" fill="{bulb_colour}"/>')
    return elements


def joined_shade_stem(shade, shade_radii, stem_left, stem_right, shade_bottom, baseline,
                      stem_radius, bulb_centre, bulb_radius, gap, fillet, ivory, bend_radius=24):
    """Shade and stem as one piece, with the gap flowing around the bulb's flat end."""
    clearance = bulb_radius + gap
    bulb_left_end = (bulb_centre[0] - bulb_radius, bulb_centre[1])
    assert bulb_left_end[0] <= stem_right, "joined stem needs the bulb to reach the stem's inner edge"
    top_left, top_right, bottom_right, _ = shade
    inner_corner = (stem_right, shade_bottom)
    outline = [
        (stem_left, shade_bottom), top_left, top_right, bottom_right,
        inner_corner, (stem_right, baseline), (stem_left, baseline),
    ]
    radii = [bend_radius, shade_radii[0], shade_radii[1], shade_radii[2], 0, stem_radius, stem_radius]
    primitives = rounded_corners(outline, radii)
    # Primitive order: bend arc, line, TL arc, line, TR arc, line, BR arc,
    # line to inner corner, line down inner edge, foot arc, line, foot arc, line up.
    path = PathBuilder()
    path.move_to(primitives[0][3])
    for primitive in primitives[:7]:
        emit_primitive(path, primitive)
    path.line_to((bulb_left_end[0], shade_bottom))
    path.arc_to(bulb_left_end, gap, (bulb_left_end[0] - gap, bulb_left_end[1]), clockwise=False)
    crossing_y = bulb_centre[1] + math.sqrt(clearance**2 - (stem_right - bulb_centre[0]) ** 2)
    exit_line, exit_circle, _ = fillet_between(
        (stem_right, crossing_y), (0.0, 1.0), bulb_centre, clearance, fillet, True
    )
    path.arc_to(bulb_centre, clearance, exit_circle, clockwise=False)
    path.arc_to(_fillet_centre(exit_circle, fillet, bulb_centre), fillet, exit_line, clockwise=True)
    path.line_to(primitives[9][3])
    for primitive in primitives[9:]:
        emit_primitive(path, primitive)
    path.close()
    return f'<path d="{path.data()}" fill="{ivory}"/>'



def flat_top_leg(top_left_x, top_y, baseline, width, angle_deg):
    """Parallelogram leg with horizontal top and foot, listed clockwise."""
    horizontal = width / math.sin(math.radians(angle_deg))
    shift = (baseline - top_y) / math.tan(math.radians(angle_deg))
    return [
        (top_left_x, top_y), (top_left_x + horizontal, top_y),
        (top_left_x + shift + horizontal, baseline), (top_left_x + shift, baseline),
    ]


def counter_mark(*, gap=18, bulb_radius=30, hole_centre=(248, 168), shade_top=72, shade_bottom=238,
                 stem_left=92, stem_width=100, stem_radius=14, baseline=440, leg_width=68,
                 leg_angle=60, leg_gap=26, ivory=IVORY, bulb_colour=BULB):
    """Shade with the bulb set inside it as the R's counter, plain supports below."""
    shade = shade_vertices(92, 404, 152, 300, shade_bottom, shade_top)
    hole_radius = bulb_radius + gap
    hole = (
        f"M{fmt(hole_centre[0] - hole_radius)} {fmt(hole_centre[1])} "
        f"a{hole_radius} {hole_radius} 0 1 0 {2 * hole_radius} 0 "
        f"a{hole_radius} {hole_radius} 0 1 0 {-2 * hole_radius} 0 Z"
    )
    support_top = shade_bottom + gap
    stem_right = stem_left + stem_width
    stem = [(stem_left, support_top), (stem_right, support_top), (stem_right, baseline), (stem_left, baseline)]
    leg = flat_top_leg(stem_right + leg_gap, support_top, baseline, leg_width, leg_angle)
    acute = 14
    return [
        f'<path d="{polygon_path(shade, [20, 20, 12, 12])} {hole}" fill="{ivory}" fill-rule="evenodd"/>',
        f'<path d="{polygon_path(stem, [stem_radius] * 4)}" fill="{ivory}"/>',
        f'<path d="{polygon_path(leg, [stem_radius, acute, stem_radius, acute])}" fill="{ivory}"/>',
        f'<circle cx="{fmt(hole_centre[0])}" cy="{fmt(hole_centre[1])}" r="{bulb_radius}" fill="{bulb_colour}"/>',
    ]


def shifted(elements, dx=8, dy=0):
    """Centre the mark on the badge, the shade is drawn around x=248."""
    return [f'<g transform="translate({fmt(dx)} {fmt(dy)})">'] + elements + ["</g>"]


def scaled(elements, factor, about=(256, 256)):
    offset_x = about[0] * (1 - factor)
    offset_y = about[1] * (1 - factor)
    return [f'<g transform="translate({fmt(offset_x)} {fmt(offset_y)}) scale({fmt(factor)})">'] + elements + ["</g>"]


def write(out_dir, name, title, description, body):
    target = out_dir / f"{name}.svg"
    target.write_text(svg_document(title, description, body))
    print(target)


CANDIDATE = dict(bulb_radius=60, leg_width=68, leg_radius=16, leg_fillets=(20, 20), stem_fillets=(12, 24))


def build(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    description = "A cream lampshade above a golden bulb and two supports forming an abstract R on an orange badge."
    variants = {
        "55-even-gaps": dict(),
        "56-large-bulb": dict(bulb_radius=64, leg_width=68),
        "57-joined-stem": dict(joined=True, bulb_radius=60, leg_width=68),
        "58-round-bulb": dict(bulb_style="full", bulb_radius=44, leg_width=68, leg_anchor_y=238 + 18 + 20),
        "59-wide-stance": dict(leg_offset=12, leg_width=68, bulb_radius=60),
        "60-soft-tips": CANDIDATE,
        "63-mono-ivory": dict(CANDIDATE, bulb_colour=IVORY),
    }
    for name, options in variants.items():
        write(out_dir, name, "Roommate", description, [badge()] + shifted(lamp_mark(**options)))
    write(out_dir, "61-counter-bulb", "Roommate",
          "A cream lampshade with a golden bulb set inside it, above two supports forming an abstract R.",
          [badge()] + shifted(counter_mark()))
    write(out_dir, "62-circle-badge", "Roommate", description,
          [circle_badge()] + scaled(shifted(lamp_mark(**CANDIDATE)), 0.88))
    write(out_dir, "64-glyph", "Roommate",
          "The Roommate lamp mark alone in charcoal with an orange bulb, for single colour or transparent use.",
          shifted(lamp_mark(**CANDIDATE, ivory="#2B2520", bulb_colour="#FB7C20")))


if __name__ == "__main__":
    build(Path(sys.argv[1]))
