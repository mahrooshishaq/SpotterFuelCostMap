"""Match company stations with OpenStreetMap fuel stations via Overpass."""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelStation


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE = ROOT / "data" / "geocoding" / "overpass_fuel_stations.json"
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
STATE_BBOXES = {
    "AK": (51.2, -170.0, 71.5, -129.9), "AL": (30.1, -88.5, 35.1, -84.8),
    "AR": (33.0, -94.7, 36.5, -89.6),
    "AZ": (31.3, -114.8, 37.1, -109.0), "CA": (32.5, -124.5, 42.1, -114.1),
    "CO": (37.0, -109.1, 41.1, -102.0), "CT": (40.9, -73.8, 42.1, -71.8),
    "DE": (38.4, -75.8, 39.9, -75.0), "FL": (24.4, -87.7, 31.1, -80.0),
    "GA": (30.3, -85.6, 35.1, -80.8), "HI": (18.8, -160.3, 22.3, -154.8),
    "IA": (40.3, -96.6, 43.6, -90.1),
    "ID": (42.0, -117.3, 49.1, -111.0), "IL": (36.9, -91.5, 42.6, -87.0),
    "IN": (37.7, -88.1, 41.8, -84.8), "KS": (37.0, -102.1, 40.1, -94.6),
    "KY": (36.5, -89.6, 39.2, -81.9), "LA": (28.8, -94.1, 33.1, -89.0),
    "MA": (41.2, -73.5, 42.9, -69.8), "MD": (37.9, -79.5, 39.8, -75.0),
    "ME": (43.0, -71.1, 47.5, -66.8), "MI": (41.7, -90.5, 48.3, -82.1),
    "MN": (43.5, -97.3, 49.4, -89.5), "MO": (35.9, -95.8, 40.7, -89.1),
    "MS": (30.1, -91.7, 35.0, -88.1), "MT": (44.4, -116.1, 49.1, -104.0),
    "NC": (33.8, -84.4, 36.6, -75.4), "ND": (45.9, -104.1, 49.1, -96.5),
    "NE": (40.0, -104.1, 43.1, -95.3), "NV": (35.0, -120.0, 42.1, -114.0),
    "NH": (42.7, -72.6, 45.4, -70.6), "NJ": (38.9, -75.6, 41.4, -73.8),
    "NM": (31.3, -109.1, 37.1, -103.0), "NY": (40.5, -79.8, 45.1, -71.8),
    "OH": (38.4, -84.9, 42.0, -80.5), "OK": (33.6, -103.0, 37.1, -94.4),
    "OR": (41.9, -124.7, 46.3, -116.5), "PA": (39.7, -80.6, 42.3, -74.7),
    "RI": (41.1, -71.9, 42.1, -71.1), "SC": (32.0, -83.4, 35.3, -78.5),
    "SD": (42.5, -104.1, 46.1, -96.4), "TN": (34.9, -90.4, 36.7, -81.6),
    "TX": (25.8, -106.7, 36.6, -93.5), "UT": (37.0, -114.1, 42.1, -109.0),
    "VA": (36.5, -83.7, 39.5, -75.2), "VT": (42.7, -73.5, 45.1, -71.5),
    "WA": (45.5, -124.8, 49.1, -116.9), "WV": (37.1, -82.7, 40.7, -77.7),
    "WI": (42.4, -92.9, 47.1, -86.7), "WY": (41.0, -111.1, 45.1, -104.0),
}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}
STOP_WORDS = {
    "THE", "OF", "AND", "AT", "TRAVEL", "CENTER", "CENTRE", "STOP",
    "STORE", "STATION", "FUEL", "GAS", "INC", "LLC", "USA",
}
BRAND_ALIASES = {
    "CASEYS": "CASEYS",
    "CASEY": "CASEYS",
    "7ELEVEN": "7ELEVEN",
    "SEVENELEVEN": "7ELEVEN",
    "PILOT": "PILOT",
    "FLYINGJ": "FLYINGJ",
    "FLYING": "FLYINGJ",
    "LOAFNJUG": "LOAFNJUG",
    "RACETRAC": "RACETRAC",
    "CIRCLEK": "CIRCLEK",
    "SPEEDWAY": "SPEEDWAY",
    "SHELL": "SHELL",
    "CHEVRON": "CHEVRON",
    "CITGO": "CITGO",
    "SUNSTOP": "SUNSTOP",
    "CEFCO": "CEFCO",
    "MARATHON": "MARATHON",
    "ALLSUPS": "ALLSUPS",
}


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Z0-9]+", (value or "").upper())
        if len(token) >= 3 and token not in STOP_WORDS
    }


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def brands(value: str) -> set[str]:
    result = set()
    for token in tokens(value):
        compacted = compact(token)
        result.add(BRAND_ALIASES.get(compacted, compacted))
    return result


def store_numbers(value: str) -> set[str]:
    return set(re.findall(r"(?:#\s*)?(\d{2,6})", (value or "").upper()))


def state_from_tags(tags: dict[str, object]) -> str:
    state = str(tags.get("addr:state", "")).upper()
    if state in US_STATES:
        return state
    return state.split("-")[-1] if state.split("-")[-1] in US_STATES else ""


def city_from_tags(tags: dict[str, object]) -> str:
    for key in ("addr:city", "addr:town", "addr:village", "addr:municipality"):
        if tags.get(key):
            return str(tags[key])
    return ""


def osm_point(element: dict[str, object]) -> tuple[float, float] | None:
    if element.get("type") == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        center = element.get("center", {})
        if not isinstance(center, dict):
            return None
        lat, lon = center.get("lat"), center.get("lon")
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def fetch_bbox(
    bbox: tuple[float, float, float, float],
    user_agent: str,
    endpoints: tuple[str, ...],
    retries: int = 2,
) -> list[dict[str, object]]:
    query = f"""
[out:json][timeout:60];
nwr["amenity"="fuel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
out center tags;
"""
    last_error: Exception | None = None
    for endpoint in endpoints:
        for attempt in range(retries + 1):
            request = Request(
                f"{endpoint}?{urlencode({'data': query})}",
                headers={"User-Agent": user_agent, "Accept": "application/json"},
            )
            try:
                with urlopen(request, timeout=150) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                elements = payload.get("elements") if isinstance(payload, dict) else None
                if not isinstance(elements, list):
                    raise ValueError("Overpass returned no elements list")
                return elements
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise
            except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(
        f"all Overpass endpoints failed after retries: {last_error}"
    ) from last_error


def normalize_osm(elements: list[dict[str, object]], state: str) -> list[dict[str, object]]:
    records = []
    for element in elements:
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            continue
        point = osm_point(element)
        if point is None:
            continue
        records.append(
            {
                "osm_id": f"{element.get('type')}:{element.get('id')}",
                "name": str(tags.get("name", "")),
                "brand": str(tags.get("brand", "")),
                "operator": str(tags.get("operator", "")),
                "city": city_from_tags(tags),
                "state": state_from_tags(tags) or state,
                "latitude": point[0],
                "longitude": point[1],
            }
        )
    return records


def match_station(station: FuelStation, candidates: list[dict[str, object]]) -> tuple[dict[str, object] | None, str, int]:
    source_tokens = tokens(f"{station.name} {station.address}")
    source_brands = brands(station.name)
    source_numbers = store_numbers(station.name)
    scored: list[tuple[int, dict[str, object]]] = []
    for candidate in candidates:
        if candidate["state"] != station.state:
            continue
        city_score = 3 if compact(str(candidate["city"])) == compact(station.city) else 0
        name_text = f"{candidate['name']} {candidate['brand']} {candidate['operator']}"
        shared = source_tokens & tokens(name_text)
        brand_score = 5 if source_brands & brands(name_text) else 0
        number_score = 3 if source_numbers & store_numbers(name_text) else 0
        score = city_score + brand_score + number_score + min(len(shared), 2)
        if score >= 6:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], str(item[1]["osm_id"])))
    if not scored:
        return None, "unmatched", 0
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, "ambiguous", scored[0][0]
    if scored[0][0] < 7:
        return None, "low_confidence", scored[0][0]
    return scored[0][1], "matched", scored[0][0]


class Command(BaseCommand):
    help = "Match FuelStation records to OpenStreetMap amenity=fuel records."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--states", help="Comma-separated states; default is all states in the database.")
        parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
        parser.add_argument("--delay", type=float, default=2.0)
        parser.add_argument("--tile-size", type=float, default=2.0)
        parser.add_argument(
            "--allow-partial",
            action="store_true",
            help="Continue and report failed tiles instead of aborting the run.",
        )
        parser.add_argument("--user-agent", default="FuelStopPlanner/0.1 (local assessment)")
        parser.add_argument(
            "--endpoint",
            action="append",
            dest="endpoints",
            help="Overpass endpoint; may be supplied more than once.",
        )
        parser.add_argument("--apply", action="store_true", help="Apply unique high-confidence matches.")

    def handle(self, *args, **options) -> None:
        if options["delay"] < 1:
            raise CommandError("--delay must be at least 1 second")
        if not 0.25 <= options["tile_size"] <= 5:
            raise CommandError("--tile-size must be between 0.25 and 5 degrees")
        states = {
            state.strip().upper()
            for state in (options["states"].split(",") if options["states"] else
                          FuelStation.objects.values_list("state", flat=True).distinct())
            if state.strip()
        }
        invalid = sorted(states - US_STATES)
        if invalid:
            raise CommandError(f"Invalid US state codes: {', '.join(invalid)}")
        cache_path = options["cache"].resolve()
        endpoints = tuple(options["endpoints"] or OVERPASS_ENDPOINTS)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            cache = {}
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read Overpass cache: {exc}") from exc

        all_osm: list[dict[str, object]] = []
        requests_made = 0
        failed_tiles: list[dict[str, object]] = []
        for state_index, state in enumerate(sorted(states)):
            south, west, north, east = STATE_BBOXES[state]
            tiles = []
            lat = south
            while lat < north:
                lon = west
                while lon < east:
                    tiles.append((
                        round(lat, 4),
                        round(lon, 4),
                        round(min(lat + options["tile_size"], north), 4),
                        round(min(lon + options["tile_size"], east), 4),
                    ))
                    lon += options["tile_size"]
                lat += options["tile_size"]
            for tile_index, bbox in enumerate(tiles):
                key = f"{state}:{','.join(str(value) for value in bbox)}"
                if key in cache:
                    records = cache[key]
                else:
                    try:
                        records = normalize_osm(
                            fetch_bbox(bbox, options["user_agent"], endpoints),
                            state,
                        )
                    except (
                        HTTPError, URLError, TimeoutError, ValueError,
                        RuntimeError, json.JSONDecodeError,
                    ) as exc:
                        if not options["allow_partial"]:
                            raise CommandError(
                                f"Overpass request failed for {state} tile {bbox}: {exc}"
                            ) from exc
                        failed_tiles.append(
                            {"state": state, "bbox": bbox, "error": str(exc)}
                        )
                        records = []
                    cache[key] = records
                    cache_path.write_text(
                        json.dumps(cache, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    requests_made += 1
                    if tile_index + 1 < len(tiles) or state_index + 1 < len(states):
                        time.sleep(options["delay"])
                all_osm.extend(record for record in records if record.get("state") in {"", state})

        by_state: dict[str, list[dict[str, object]]] = defaultdict(list)
        for record in all_osm:
            by_state[str(record["state"])].append(record)
        candidates = []
        counts = defaultdict(int)
        for station in FuelStation.objects.filter(state__in=states).order_by("id"):
            candidate, status, score = match_station(station, by_state[station.state])
            counts[status] += 1
            if candidate is not None:
                candidates.append((station, candidate, score))

        updated = 0
        if options["apply"]:
            with transaction.atomic():
                for station, candidate, score in candidates:
                    if station.location_quality == FuelStation.LocationQuality.STATION_LEVEL:
                        continue
                    station.latitude = candidate["latitude"]
                    station.longitude = candidate["longitude"]
                    station.geocode_status = FuelStation.GeocodeStatus.MATCHED
                    station.geocode_source = f"openstreetmap_overpass:{candidate['osm_id']}:score_{score}"
                    station.location_quality = FuelStation.LocationQuality.STATION_LEVEL
                    station.save(update_fields=[
                        "latitude", "longitude", "geocode_status",
                        "geocode_source", "location_quality", "updated_at",
                    ])
                    updated += 1

        self.stdout.write(json.dumps({
            "states_processed": len(states),
            "osm_station_records": len(all_osm),
            "overpass_requests_made": requests_made,
            "match_counts": dict(sorted(counts.items())),
            "high_confidence_matches": len(candidates),
            "coordinates_updated": updated,
            "dry_run": not options["apply"],
            "failed_tiles": failed_tiles,
            "partial_results": bool(failed_tiles),
            "cache": str(cache_path),
        }, indent=2, sort_keys=True))
