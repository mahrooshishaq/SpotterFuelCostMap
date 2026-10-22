"""Validated OSRM driving-route client."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.cache import cache


class RoutingError(Exception):
    """Base class for application-level route failures."""


class RoutingUnavailableError(RoutingError):
    """The routing provider could not be reached."""


class InvalidRouteResponseError(RoutingError):
    """The routing provider returned an unusable response."""


@dataclass(frozen=True)
class RouteResult:
    geometry: dict[str, object]
    distance_miles: float
    duration_minutes: float
    waypoints: tuple[dict[str, object], ...] = ()


OSRM_BASE_URL = "https://router.project-osrm.org/route/v1/driving"
ROUTE_CACHE_SECONDS = 60 * 60
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 30


def _coordinate(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RoutingError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise RoutingError(f"{label} must be finite")
    return result


def _validate_coordinates(coordinates: tuple[float, float], label: str) -> tuple[float, float]:
    longitude = _coordinate(coordinates[0], f"{label} longitude")
    latitude = _coordinate(coordinates[1], f"{label} latitude")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise RoutingError(f"{label} coordinates are out of range")
    return longitude, latitude


def _cache_key(start: tuple[float, float], destination: tuple[float, float]) -> str:
    material = json.dumps(
        {"profile": "driving", "start": start, "destination": destination},
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"fuel-stop-planner:route:{digest}"


def _validate_payload(payload: object) -> RouteResult:
    if not isinstance(payload, dict) or payload.get("code") != "Ok":
        code = payload.get("code") if isinstance(payload, dict) else "invalid_payload"
        raise InvalidRouteResponseError(f"OSRM returned no usable route: {code}")
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes:
        raise InvalidRouteResponseError("OSRM response contains no routes")
    route = routes[0]
    if not isinstance(route, dict):
        raise InvalidRouteResponseError("OSRM route is malformed")
    geometry = route.get("geometry")
    if (
        not isinstance(geometry, dict)
        or geometry.get("type") != "LineString"
        or not isinstance(geometry.get("coordinates"), list)
        or len(geometry["coordinates"]) < 2
    ):
        raise InvalidRouteResponseError("OSRM route geometry is not a non-empty LineString")
    try:
        distance_metres = float(route["distance"])
        duration_seconds = float(route["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidRouteResponseError("OSRM distance or duration is missing") from exc
    if not math.isfinite(distance_metres) or distance_metres <= 0:
        raise InvalidRouteResponseError("OSRM distance must be positive and finite")
    if not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise InvalidRouteResponseError("OSRM duration must be finite and non-negative")
    waypoints = payload.get("waypoints", [])
    if not isinstance(waypoints, list):
        waypoints = []
    return RouteResult(
        geometry=geometry,
        distance_miles=distance_metres / 1609.344,
        duration_minutes=duration_seconds / 60,
        waypoints=tuple(point for point in waypoints if isinstance(point, dict)),
    )


def get_route(
    start: tuple[float, float],
    destination: tuple[float, float],
    *,
    use_cache: bool = True,
) -> RouteResult:
    """Fetch one normalized driving route using (longitude, latitude) inputs."""
    start = _validate_coordinates(start, "start")
    destination = _validate_coordinates(destination, "destination")
    key = _cache_key(start, destination)
    if use_cache:
        cached = cache.get(key)
        if isinstance(cached, RouteResult):
            return cached
    coordinates = ";".join(
        f"{longitude:.7f},{latitude:.7f}"
        for longitude, latitude in (start, destination)
    )
    query = urlencode({"overview": "full", "geometries": "geojson"})
    request = Request(
        f"{OSRM_BASE_URL}/{coordinates}?{query}",
        headers={"Accept": "application/json", "User-Agent": "FuelStopPlanner/0.1"},
    )
    try:
        with urlopen(request, timeout=CONNECT_TIMEOUT_SECONDS + READ_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RoutingUnavailableError(f"OSRM route request failed: {exc}") from exc
    result = _validate_payload(payload)
    if use_cache:
        cache.set(key, result, ROUTE_CACHE_SECONDS)
    return result
