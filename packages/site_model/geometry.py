"""Plain 2.5D geometry for zone resolution.

Deliberately simple: named 2D polygons per floor with an elevation, not a
survey-grade mesh (spec section 3, scope cut). No LLM is involved in deciding
whether a worker is inside a zone.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
Polygon = list[list[float]]


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """Ray-casting test. Points exactly on an edge count as inside."""
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index][0], polygon[index][1]
        x2, y2 = polygon[(index + 1) % count][0], polygon[(index + 1) % count][1]
        if _on_segment(point, (x1, y1), (x2, y2)):
            return True
        if (y1 > y) != (y2 > y):
            x_intersect = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_intersect:
                inside = not inside
    return inside


def _on_segment(point: Point, a: Point, b: Point, tolerance: float = 1e-9) -> bool:
    cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    if abs(cross) > tolerance:
        return False
    return (
        min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance
        and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance
    )


def distance_to_segment(point: Point, a: Point, b: Point) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_polygon(point: Point, polygon: Polygon) -> float:
    """Metres from the point to the polygon boundary; 0.0 when inside."""
    if point_in_polygon(point, polygon):
        return 0.0
    count = len(polygon)
    return min(
        distance_to_segment(
            point,
            (polygon[i][0], polygon[i][1]),
            (polygon[(i + 1) % count][0], polygon[(i + 1) % count][1]),
        )
        for i in range(count)
    )


def polygon_centroid(polygon: Polygon) -> Point:
    if not polygon:
        return (0.0, 0.0)
    xs = [vertex[0] for vertex in polygon]
    ys = [vertex[1] for vertex in polygon]
    return (sum(xs) / len(xs), sum(ys) / len(ys))
