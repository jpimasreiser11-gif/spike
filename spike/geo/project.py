"""The projection of Spike Geo's maps: equirectangular with a standard parallel.

x = R (lon - lon0) cos(lat_ts), y = R lat, in metres on the sphere of `measure.EARTH_RADIUS_M`. The scale is true along
the standard parallel `lat_ts` (the middle latitude of the data) in both directions; away from it east-west distances
are stretched or squeezed by cos(lat_ts) / cos(lat), so the picture is for looking, and numbers come from `measure`.
It is chosen over Web Mercator because it needs no basemap, handles the poles and keeps areas near the middle of the
map comparable, which a choropleth needs. `lon0` is the middle of the smallest arc of longitudes that holds the data,
so a map that crosses the antimeridian is drawn in one piece."""

from __future__ import annotations

import math
from dataclasses import dataclass

from spike.geo.measure import EARTH_RADIUS_M

MIN_COS = 0.05  # near the poles cos(lat_ts) would flatten the map to a line


def center_lon(lons: list[float]) -> float:
    """The middle of the smallest arc of the circle that holds all the longitudes (degrees, -180..180)."""
    ordered = sorted(((lon + 180) % 360) - 180 for lon in lons)
    if ordered[0] == ordered[-1]:
        return ordered[0]
    gaps = [b - a for a, b in zip(ordered, ordered[1:], strict=False)] + [ordered[0] + 360 - ordered[-1]]
    widest = max(range(len(gaps)), key=lambda i: (gaps[i], -i))
    middle = ordered[(widest + 1) % len(ordered)] + (360 - gaps[widest]) / 2
    return ((middle + 180) % 360) - 180


@dataclass(frozen=True)
class Equirectangular:
    lon0: float
    lat_ts: float

    @classmethod
    def fit(cls, points: list[tuple[float, float]]) -> Equirectangular:
        """The projection centred on a set of (lat, lon) points."""
        lats = [p[0] for p in points] or [0.0]
        lons = [p[1] for p in points] or [0.0]
        return cls(lon0=round(center_lon(lons), 6), lat_ts=round((min(lats) + max(lats)) / 2, 6))

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        """(x, y) in metres; y grows northwards."""
        delta = ((lon - self.lon0 + 180) % 360) - 180
        return (EARTH_RADIUS_M * math.radians(delta) * max(MIN_COS, math.cos(math.radians(self.lat_ts))),
                EARTH_RADIUS_M * math.radians(lat))
