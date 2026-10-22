"""Local station-to-route matching for the route planner."""

from __future__ import annotations

import math
from dataclasses import dataclass

from planner.models import FuelStation


MILES_PER_DEGREE_LATITUDE = 69.0
DEFAULT_CORRIDOR_MILES = 5.0


@dataclass(frozen=True)
class MatchedStation:
    station: FuelStation
    distance_from_route_miles: float
    route_position_miles: float


def _projected_xy(longitude: float, latitude: float, reference_latitude: float) -> tuple[float, float]:
    return (
        longitude * MILES_PER_DEGREE_LATITUDE * math.cos(math.radians(reference_latitude)),
        latitude * MILES_PER_DEGREE_LATITUDE,
    )


def _distance_and_fraction(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    reference_latitude = (point[1] + start[1] + end[1]) / 3
    px, py = _projected_xy(*point, reference_latitude)
    sx, sy = _projected_xy(*start, reference_latitude)
    ex, ey = _projected_xy(*end, reference_latitude)
    dx, dy = ex - sx, ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - sx, py - sy), 0.0
    fraction = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_squared))
    nearest_x, nearest_y = sx + fraction * dx, sy + fraction * dy
    return math.hypot(px - nearest_x, py - nearest_y), fraction


def _segment_length_miles(start: tuple[float, float], end: tuple[float, float]) -> float:
    reference_latitude = (start[1] + end[1]) / 2
    sx, sy = _projected_xy(*start, reference_latitude)
    ex, ey = _projected_xy(*end, reference_latitude)
    return math.hypot(ex - sx, ey - sy)


def match_stations_to_route(
    route_geometry: dict[str, object],
    stations,
    *,
    corridor_miles: float = DEFAULT_CORRIDOR_MILES,
) -> list[MatchedStation]:
    coordinates = route_geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError("Route geometry must contain at least two coordinates")
    if corridor_miles <= 0:
        raise ValueError("corridor_miles must be positive")

    route_points: list[tuple[float, float]] = []
    for coordinate in coordinates:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            raise ValueError("Route geometry contains an invalid coordinate")
        route_points.append((float(coordinate[0]), float(coordinate[1])))

    cumulative = [0.0]
    for start, end in zip(route_points, route_points[1:]):
        cumulative.append(cumulative[-1] + _segment_length_miles(start, end))

    matches: list[MatchedStation] = []
    seen_ids: set[int] = set()
    for station in stations:
        if station.pk in seen_ids:
            continue
        if station.latitude is None or station.longitude is None:
            continue
        if station.location_quality != FuelStation.LocationQuality.STATION_LEVEL:
            continue
        point = (float(station.longitude), float(station.latitude))
        best_distance = math.inf
        best_position = 0.0
        for index, (start, end) in enumerate(zip(route_points, route_points[1:])):
            distance, fraction = _distance_and_fraction(point, start, end)
            if distance < best_distance:
                best_distance = distance
                best_position = cumulative[index] + fraction * (cumulative[index + 1] - cumulative[index])
        if best_distance <= corridor_miles:
            matches.append(MatchedStation(station, best_distance, best_position))
            seen_ids.add(station.pk)
    return sorted(matches, key=lambda match: (match.route_position_miles, match.station.pk))
