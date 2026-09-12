"""Pure ROI geometry: rectangles, polygons and line segments (spec §5).

Every function here is a pure function of normalized coordinates: no clock, no
configuration lookup, no I/O (spec §1 C-1).  Degenerate ROIs are rejected when
the ``Roi`` is constructed instead of silently answering "does not intersect"
at evaluation time (spec §5.1) -- a rule that never fires is harder to debug
than a rule that refuses to bind.

Tolerance is fixed at ``EPS`` for every boundary question (spec §5.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

EPS = 1e-9
"""Geometry tolerance in normalized coordinates (spec §5.3).

Not to be confused with the 1e-6 float tolerance used when comparing golden
vector expectations (spec §15.1): this one decides what counts as "on the
boundary", that one decides what counts as "equal".
"""

Point = tuple[float, float]


class RoiShape(StrEnum):
    RECT = "RECT"
    POLYGON = "POLYGON"
    LINE = "LINE"


class CrossDirection(StrEnum):
    """Line crossing direction (spec §5.2).

    The names are labels for the two sign flips of ``signed_side``; for a
    vertical line whose first point is the upper one, LEFT_TO_RIGHT is also
    left-to-right on screen.
    """

    LEFT_TO_RIGHT = "LEFT_TO_RIGHT"
    RIGHT_TO_LEFT = "RIGHT_TO_LEFT"


class RoiRelation(StrEnum):
    ENTER = "ENTER"
    INSIDE = "INSIDE"
    EXIT = "EXIT"


SHAPE_CAPABILITY: dict[RoiShape, str] = {
    RoiShape.POLYGON: "POLYGON_ROI",
    RoiShape.LINE: "LINE_ROI",
}
"""Capabilities contributed by the ROI itself, never by an observation (spec §6)."""

INTERIOR_SHAPES = frozenset({RoiShape.RECT, RoiShape.POLYGON})


class RoiGeometryError(ValueError):
    """Construction-time rejection; binding reports it as ROI_GEOMETRY_INVALID."""

    code = "ROI_GEOMETRY_INVALID"

    def __init__(self, roi_id: str, reason: str) -> None:
        super().__init__(f"ROI {roi_id!r}: {reason}")
        self.roi_id = roi_id
        self.reason = reason


class RoiShapeMismatchError(RoiGeometryError):
    """An interior (or direction) question was asked of a shape that has none.

    Binding must reject these combinations before evaluation (spec §6 step 4):
    LINE_CROSS needs a LINE, everything that asks "is it inside" needs a RECT
    or a POLYGON.
    """


@dataclass(frozen=True, slots=True)
class Box:
    """Axis-aligned normalized box, the shape every detection carries.

    Boxes come from models, so this type stays tolerant: validating detection
    payloads belongs to the observation envelope (M11-T03), not to geometry.
    A zero-area box simply contributes zero area here.
    """

    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> Point:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(x0, y0, x1, y1) with x1 >= x0 and y1 >= y0."""
        return (
            min(self.x, self.x + self.w),
            min(self.y, self.y + self.h),
            max(self.x, self.x + self.w),
            max(self.y, self.y + self.h),
        )

    @property
    def outline(self) -> tuple[Point, ...]:
        x0, y0, x1, y1 = self.bounds
        return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Box":
        return cls(float(data["x"]), float(data["y"]), float(data["w"]), float(data["h"]))


@dataclass(frozen=True, slots=True)
class Roi:
    """A validated region of interest.

    Construction is the only place degenerate geometry is rejected, so build
    every ROI through this type (or :meth:`from_mapping`) rather than passing
    raw points around.
    """

    roi_id: str
    shape: RoiShape
    points: tuple[Point, ...] = ()
    rect: Box | None = None
    positive_direction: CrossDirection | None = None

    def __post_init__(self) -> None:
        # Coerce first: a raw "POLYGON" string compares equal to the enum member
        # but fails the identity checks below, which would validate the wrong
        # shape.  Frozen dataclasses need object.__setattr__ for this.
        object.__setattr__(self, "shape", RoiShape(self.shape))
        object.__setattr__(self, "points", tuple((float(p[0]), float(p[1])) for p in self.points))
        if self.positive_direction is not None:
            object.__setattr__(self, "positive_direction", CrossDirection(self.positive_direction))
        _validate(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Roi":
        """Build from the JSON shape used by the spec, the schema and the vectors."""
        try:
            shape = RoiShape(data["shape"])
        except (KeyError, ValueError) as exc:
            raise RoiGeometryError(str(data.get("roiId", "<unknown>")), f"unknown shape: {exc}") from exc
        direction = data.get("positiveDirection")
        rect = data.get("rect")
        return cls(
            roi_id=str(data.get("roiId", "")),
            shape=shape,
            points=tuple((float(p[0]), float(p[1])) for p in data.get("points", ())),
            rect=Box.from_mapping(rect) if rect is not None else None,
            positive_direction=CrossDirection(direction) if direction is not None else None,
        )

    @property
    def capabilities(self) -> frozenset[str]:
        """Capabilities this ROI contributes to the binding check (spec §6)."""
        capability = SHAPE_CAPABILITY.get(self.shape)
        return frozenset() if capability is None else frozenset({capability})

    @property
    def has_interior(self) -> bool:
        return self.shape in INTERIOR_SHAPES

    @property
    def outline(self) -> tuple[Point, ...]:
        """Closed outline used by every area computation; LINE has none."""
        if self.shape is RoiShape.RECT:
            assert self.rect is not None  # guaranteed by _validate
            return self.rect.outline
        if self.shape is RoiShape.POLYGON:
            return self.points
        raise RoiShapeMismatchError(self.roi_id, "a LINE has no interior; bind LINE_CROSS instead")


# --- construction-time validation (spec §5.1) -------------------------------


def _in_unit_range(value: float) -> bool:
    return -EPS <= value <= 1.0 + EPS


def _validate(roi: Roi) -> None:
    if not roi.roi_id:
        raise RoiGeometryError("<empty>", "roiId must not be empty")
    for point in roi.points:
        if not (_in_unit_range(point[0]) and _in_unit_range(point[1])):
            raise RoiGeometryError(roi.roi_id, f"point out of the normalized range: {point}")
    if roi.shape is RoiShape.RECT:
        _validate_rect(roi)
    elif roi.shape is RoiShape.POLYGON:
        _validate_polygon(roi)
    else:
        _validate_line(roi)


def _validate_rect(roi: Roi) -> None:
    if roi.rect is None:
        raise RoiGeometryError(roi.roi_id, "RECT requires rect")
    if roi.points:
        raise RoiGeometryError(roi.roi_id, "RECT carries rect, not points")
    rect = roi.rect
    if rect.w <= EPS or rect.h <= EPS:
        raise RoiGeometryError(roi.roi_id, f"degenerate rect: w={rect.w}, h={rect.h}")
    if not (_in_unit_range(rect.x) and _in_unit_range(rect.y)):
        raise RoiGeometryError(roi.roi_id, f"rect origin out of range: x={rect.x}, y={rect.y}")
    if rect.x + rect.w > 1.0 + EPS or rect.y + rect.h > 1.0 + EPS:
        raise RoiGeometryError(roi.roi_id, "rect crosses the frame boundary")


def _validate_polygon(roi: Roi) -> None:
    if roi.rect is not None:
        raise RoiGeometryError(roi.roi_id, "POLYGON carries points, not rect")
    points = roi.points
    if len(points) < 3:
        raise RoiGeometryError(roi.roi_id, f"POLYGON needs at least 3 points, got {len(points)}")
    count = len(points)
    for index in range(count):
        here, nxt = points[index], points[(index + 1) % count]
        if _distance(here, nxt) <= EPS:
            raise RoiGeometryError(roi.roi_id, f"duplicate adjacent points at index {index}: {here}")
    if abs(_signed_area(points)) <= EPS:
        raise RoiGeometryError(roi.roi_id, "polygon area is zero")
    conflict = _self_intersection(points)
    if conflict is not None:
        raise RoiGeometryError(roi.roi_id, f"edges {conflict[0]} and {conflict[1]} self-intersect")


def _validate_line(roi: Roi) -> None:
    if roi.rect is not None:
        raise RoiGeometryError(roi.roi_id, "LINE carries points, not rect")
    if len(roi.points) != 2:
        raise RoiGeometryError(roi.roi_id, f"LINE needs exactly 2 points, got {len(roi.points)}")
    if _distance(roi.points[0], roi.points[1]) <= EPS:
        raise RoiGeometryError(roi.roi_id, "zero-length line")
    if roi.positive_direction is None:
        raise RoiGeometryError(roi.roi_id, "LINE requires positiveDirection")


def _distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _signed_area(points: Sequence[Point]) -> float:
    """Shoelace area; the sign follows the winding order and is never used."""
    total = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _on_segment(point: Point, a: Point, b: Point) -> bool:
    """True when point lies on segment a-b, endpoints included."""
    if abs(_cross(a, b, point)) > EPS:
        return False
    return (
        min(a[0], b[0]) - EPS <= point[0] <= max(a[0], b[0]) + EPS
        and min(a[1], b[1]) - EPS <= point[1] <= max(a[1], b[1]) + EPS
    )


def _collinear_overlap(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """True when two collinear segments share more than a single point."""
    if abs(_cross(a1, a2, b1)) > EPS or abs(_cross(a1, a2, b2)) > EPS:
        return False
    dx, dy = a2[0] - a1[0], a2[1] - a1[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= EPS:
        return False
    def project(p: Point) -> float:
        return ((p[0] - a1[0]) * dx + (p[1] - a1[1]) * dy) / length
    a_lo, a_hi = 0.0, length
    b_lo, b_hi = sorted((project(b1), project(b2)))
    return min(a_hi, b_hi) - max(a_lo, b_lo) > EPS


def _segments_touch(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """Any shared point at all: proper crossing, endpoint touch or overlap."""
    d1 = _cross(b1, b2, a1)
    d2 = _cross(b1, b2, a2)
    d3 = _cross(a1, a2, b1)
    d4 = _cross(a1, a2, b2)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and (
        (d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)
    ):
        return True
    return (
        _on_segment(a1, b1, b2)
        or _on_segment(a2, b1, b2)
        or _on_segment(b1, a1, a2)
        or _on_segment(b2, a1, a2)
    )


def _self_intersection(points: Sequence[Point]) -> tuple[int, int] | None:
    """First offending edge pair, or None (spec §5.1).

    Non-adjacent edges may not share any point; adjacent edges share exactly
    one endpoint by construction, so only a collinear fold-back is rejected.
    A redundant collinear vertex on a straight edge stays legal.
    """
    count = len(points)
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            adjacent = (j == i + 1) or (i == 0 and j == count - 1)
            a1, a2 = edges[i]
            b1, b2 = edges[j]
            if adjacent:
                if _collinear_overlap(a1, a2, b1, b2):
                    return (i, j)
            elif _segments_touch(a1, a2, b1, b2):
                return (i, j)
    return None


# --- containment (spec §5.2) ------------------------------------------------


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Even-odd ray casting; a point on the boundary counts as inside (spec §5.2)."""
    count = len(polygon)
    for index in range(count):
        if _on_segment(point, polygon[index], polygon[(index + 1) % count]):
            return True
    x, y = point
    inside = False
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def point_in_roi(roi: Roi, point: Point) -> bool:
    """"Is it inside" for RECT and POLYGON; boundary counts as inside."""
    if roi.shape is RoiShape.RECT:
        assert roi.rect is not None
        x0, y0, x1, y1 = roi.rect.bounds
        return x0 - EPS <= point[0] <= x1 + EPS and y0 - EPS <= point[1] <= y1 + EPS
    return point_in_polygon(point, roi.outline)


def box_in_roi(roi: Roi, box: Box) -> bool:
    """ROI membership: the box **center** is inside (spec §5.2).

    This is the single membership rule for ENTER/INSIDE/EXIT and for the
    per-frame grouping used by COUNT, AREA_RATIO and ABSENCE.  It differs from
    M07, which required the whole box to be contained (spec §17 row 11).
    """
    return point_in_roi(roi, box.center)


def relation_holds(relation: RoiRelation, was_inside: bool | None, is_inside: bool) -> bool:
    """Timing of ENTER/INSIDE/EXIT (spec §5.2).

    ``was_inside`` is None for the first observation of a subject, where
    neither ENTER nor EXIT can hold.  INSIDE also holds on the ENTER frame.
    """
    if relation is RoiRelation.INSIDE:
        return is_inside
    if was_inside is None:
        return False
    if relation is RoiRelation.ENTER:
        return not was_inside and is_inside
    return was_inside and not is_inside


# --- areas (spec §5.2, §8.1) ------------------------------------------------


def roi_area(roi: Roi) -> float:
    """Denominator for AREA_RATIO on a roi: subject (spec §8.1)."""
    if roi.shape is RoiShape.RECT:
        assert roi.rect is not None
        return roi.rect.area
    return abs(_signed_area(roi.outline))


def _clip_half_plane(
    polygon: Sequence[Point], axis: int, value: float, keep_greater: bool
) -> list[Point]:
    """Sutherland-Hodgman against one axis-aligned half plane."""
    def inside(p: Point) -> bool:
        return p[axis] >= value if keep_greater else p[axis] <= value

    result: list[Point] = []
    count = len(polygon)
    for index in range(count):
        current = polygon[index]
        following = polygon[(index + 1) % count]
        current_in, following_in = inside(current), inside(following)
        if current_in:
            result.append(current)
        if current_in != following_in:
            span = following[axis] - current[axis]
            ratio = 0.0 if span == 0 else (value - current[axis]) / span
            other = 1 - axis
            crossing = [0.0, 0.0]
            crossing[axis] = value
            crossing[other] = current[other] + ratio * (following[other] - current[other])
            result.append((crossing[0], crossing[1]))
    return result


def _outline_rect_overlap(outline: Sequence[Point], x0: float, y0: float, x1: float, y1: float) -> float:
    """Area of an arbitrary (possibly concave) outline clipped to a rectangle.

    The clip region is convex, which is what Sutherland-Hodgman requires; a
    concave subject may come back with zero-area bridges, and the shoelace area
    of that result is still the exact intersection area.
    """
    polygon: Sequence[Point] = outline
    for axis, value, keep_greater in ((0, x0, True), (0, x1, False), (1, y0, True), (1, y1, False)):
        polygon = _clip_half_plane(polygon, axis, value, keep_greater)
        if len(polygon) < 3:
            return 0.0
    return abs(_signed_area(polygon))


def overlap_area(roi: Roi, box: Box) -> float:
    """Overlap area between a box and the ROI (spec §5.2).

    Used in exactly one place by the operators: the AREA_RATIO numerator when
    the source only provides boxes (``areaSource: "BOX_FALLBACK"``, spec §8.1).
    ROI membership never uses it.
    """
    x0, y0, x1, y1 = box.bounds
    if x1 - x0 <= EPS or y1 - y0 <= EPS:
        return 0.0
    if roi.shape is RoiShape.RECT:
        assert roi.rect is not None
        rx0, ry0, rx1, ry1 = roi.rect.bounds
        width = min(x1, rx1) - max(x0, rx0)
        height = min(y1, ry1) - max(y0, ry0)
        return width * height if width > 0.0 and height > 0.0 else 0.0
    return _outline_rect_overlap(roi.outline, x0, y0, x1, y1)


def intersects(roi: Roi, box: Box) -> bool:
    """Overlap area > EPS; touching an edge is not intersecting (spec §5.2, §5.3)."""
    return overlap_area(roi, box) > EPS


def union_overlap_area(roi: Roi, boxes: Iterable[Box]) -> float:
    """Area of ``roi ∩ (∪ boxes)`` -- overlapping boxes counted once (spec §8.1).

    The boxes are axis aligned, so compressing their edge coordinates yields a
    grid whose every cell is either fully inside or fully outside each box; the
    ROI is then clipped cell by cell.  Exact, and bounded by the box count.
    """
    kept = [box for box in boxes if box.w > EPS and box.h > EPS]
    if not kept:
        return 0.0
    xs = sorted({edge for box in kept for edge in (box.bounds[0], box.bounds[2])})
    ys = sorted({edge for box in kept for edge in (box.bounds[1], box.bounds[3])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        if right - left <= EPS:
            continue
        for bottom, top in zip(ys, ys[1:]):
            if top - bottom <= EPS:
                continue
            covered = any(
                box.bounds[0] <= left + EPS
                and box.bounds[2] >= right - EPS
                and box.bounds[1] <= bottom + EPS
                and box.bounds[3] >= top - EPS
                for box in kept
            )
            if covered:
                total += overlap_area(roi, Box(left, bottom, right - left, top - bottom))
    return total


# --- line crossing (spec §5.2) ----------------------------------------------


def signed_side(roi: Roi, point: Point) -> float:
    """Signed side of a point relative to the line (spec §5.2).

    ``side(p) = (p.x - A.x) * d.y - (p.y - A.y) * d.x`` with ``d = B - A``.
    The line is treated as infinitely long: whether the intersection falls
    between A and B is not checked, matching M07.
    """
    if roi.shape is not RoiShape.LINE:
        raise RoiShapeMismatchError(roi.roi_id, "signed_side needs a LINE; bind LINE_CROSS to a line")
    (ax, ay), (bx, by) = roi.points
    return (point[0] - ax) * (by - ay) - (point[1] - ay) * (bx - ax)


def side_sign(roi: Roi, point: Point) -> int:
    """-1, 0 or +1; 0 means "on the line" within EPS (spec §5.3)."""
    side = signed_side(roi, point)
    if side > EPS:
        return 1
    if side < -EPS:
        return -1
    return 0


def step_side(roi: Roi, previous_sign: int, point: Point) -> tuple[int, CrossDirection | None]:
    """Advance the per-subject side state by one observation (spec §5.2).

    Returns the sign to remember and the crossing this observation completed,
    if any.  Callers keep ``previous_sign`` per (rule, subject) and start at 0.

    Three rules live here: a point on the line neither crosses nor overwrites
    the last non-zero sign, the first non-zero sign only records, and a sign
    flip from negative to positive is LEFT_TO_RIGHT.
    """
    sign = side_sign(roi, point)
    if sign == 0 or previous_sign == 0 or sign == previous_sign:
        return (previous_sign if sign == 0 else sign), None
    return sign, (CrossDirection.LEFT_TO_RIGHT if sign > 0 else CrossDirection.RIGHT_TO_LEFT)


def is_positive_crossing(roi: Roi, direction: CrossDirection | None) -> bool:
    """True when a crossing goes the way the ROI declares (spec §5.2, §8.1)."""
    if roi.shape is not RoiShape.LINE:
        raise RoiShapeMismatchError(
            roi.roi_id, "is_positive_crossing needs a LINE; bind LINE_CROSS to a line"
        )
    return direction is not None and direction == roi.positive_direction
