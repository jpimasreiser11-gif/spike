"""Distances and areas on a sphere.

The Earth is a sphere of radius EARTH_RADIUS_M = 6,371,008.8 m (the IUGG mean radius R1, one third of 2a + b of the
WGS 84 ellipsoid). Distances are great-circle distances by the haversine formula. An area is the spherical excess of
the polygon, summed over a fan of triangles (Van Oosterom and Strackee's formula), with great-circle edges, a hole
subtracted, and the smaller of the two sides of a ring when it would enclose more than a hemisphere.

Accuracy: against an ellipsoidal calculation (WGS 84) expect distances off by up to about 0.5 % and areas by up to
about 1 % (the sphere's radius is not the ellipsoid's radius of curvature at every latitude). The two edges of a
GeoJSON polygon are straight lines on the lon/lat plane by the RFC; here they are great circles, which only differs
for edges many degrees long. Rings that cross themselves have no meaningful area."""

from __future__ import annotations

import math

from spike.geo.data import check

EARTH_RADIUS_M = 6_371_008.8
LatLon = tuple[float, float]
Vec = tuple[float, float, float]


def haversine(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres between two (lat, lon) points in degrees."""
    a = check(a[0], a[1], "point a")
    b = check(b[0], b[1], "point b")
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def path_length(points: list[LatLon]) -> float:
    """Length in metres of the path through the points."""
    checked = [check(p[0], p[1], "path") for p in points]
    return sum(haversine(p, q) for p, q in zip(checked, checked[1:], strict=False))


def unclosed(ring: list[LatLon]) -> list[LatLon]:
    checked = [check(p[0], p[1], "ring") for p in ring]
    return checked[:-1] if len(checked) > 1 and checked[0] == checked[-1] else checked


def perimeter(ring: list[LatLon]) -> float:
    """Length in metres of a ring, closed back to its first corner."""
    pts = unclosed(ring)
    return path_length(pts + pts[:1]) if len(pts) > 1 else 0.0


def unit(p: LatLon) -> Vec:
    lat, lon = math.radians(p[0]), math.radians(p[1])
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def ring_area(ring: list[LatLon]) -> float:
    """Area in square metres inside a ring (corners in either order, closed or not)."""
    pts = unclosed(ring)
    if len(pts) < 3:
        return 0.0
    vecs = [unit(p) for p in pts]
    a, excess = vecs[0], 0.0
    for b, c in zip(vecs[1:], vecs[2:], strict=False):  # signed excess of the triangle (a, b, c)
        excess += 2 * math.atan2(dot(a, cross(b, c)), 1 + dot(a, b) + dot(b, c) + dot(c, a))
    excess = abs(excess)
    if excess > 2 * math.pi:
        excess = 4 * math.pi - excess  # the ring was wound round the other side: take the smaller region
    return excess * EARTH_RADIUS_M**2


def polygon_area(rings: list[list[LatLon]]) -> float:
    """Area in square metres of a polygon: its outer ring minus its holes."""
    if not rings:
        return 0.0
    return max(0.0, ring_area(rings[0]) - sum(ring_area(hole) for hole in rings[1:]))
