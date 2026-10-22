"""Geocode a small, deterministic station sample for manual validation.

This command deliberately does not update FuelStation records. Coordinates
are only imported after the sample has been manually reviewed.
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

from planner.models import FuelStation


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "geocoding"
    / "geocoding_sample.csv"
)
DEFAULT_REPORT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "geocoding"
    / "geocoding_report.json"
)
DEFAULT_CACHE = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "geocoding"
    / "nominatim_cache.json"
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "FuelStopPlanner/0.1 (local assessment; contact project owner)"


def has_conventional_address(station: FuelStation) -> bool:
    return bool(re.match(r"^\d+\s+[A-Za-z]", station.address.strip()))


def sample_stations(limit: int) -> list[FuelStation]:
    """Select geographically varied records without relying on insertion order."""
    stations = list(FuelStation.objects.order_by("state", "city", "id"))
    selected: list[FuelStation] = []
    selected_ids: set[int] = set()

    def add(station: FuelStation) -> None:
        if station.id not in selected_ids and len(selected) < limit:
            selected.append(station)
            selected_ids.add(station.id)

    by_state: dict[str, list[FuelStation]] = {}
    for station in stations:
        by_state.setdefault(station.state, []).append(station)

    # First select one station per state, preferring a conventional address.
    state_groups = sorted(by_state.items())
    for state, state_stations in state_groups:
        del state
        conventional = [s for s in state_stations if has_conventional_address(s)]
        add((conventional or state_stations)[0])
        if len(selected) >= limit:
            break

    # If the requested sample is larger than the number of states represented,
    # add deterministic highway/exit examples from states already represented.
    for station in stations:
        add(station)
        if len(selected) >= limit:
            break
    return selected


def query_nominatim(query: str, user_agent: str) -> list[dict[str, object]]:
    parameters = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": "3",
        "countrycodes": "us",
    }
    request = Request(
        f"{NOMINATIM_URL}?{urlencode(parameters)}",
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Nominatim returned a non-list response")
    return payload


def classify_results(station: FuelStation, results: list[dict[str, object]]) -> str:
    if not results:
        return "unmatched"
    expected_city = station.city.casefold()
    expected_state = station.state.casefold()
    plausible = []
    for result in results:
        address = result.get("address", {})
        if not isinstance(address, dict):
            continue
        city_values = {
            str(address.get(key, "")).casefold()
            for key in ("city", "town", "village", "municipality")
        }
        state_code = str(address.get("ISO3166-2-lvl4", "")).split("-")[-1].casefold()
        if expected_city in city_values and state_code == expected_state:
            plausible.append(result)
    if len(plausible) == 1:
        return "candidate_plausible"
    if len(plausible) > 1:
        return "ambiguous"
    return "candidate_mismatch"


def query_variants(station: FuelStation) -> list[str]:
    full = ", ".join(
        part
        for part in (station.name, station.address, station.city, station.state, "USA")
        if part
    )
    constrained = ", ".join(
        part for part in (station.address, station.city, station.state, "USA") if part
    )
    return [full, constrained] if constrained != full else [full]


class Command(BaseCommand):
    help = "Query Nominatim for a small station sample and create a manual-review report."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--delay", type=float, default=1.1)
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
        parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
        parser.add_argument("--user-agent", default=USER_AGENT)

    def handle(self, *args, **options) -> None:
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be at least 1")
        if options["delay"] < 1:
            raise CommandError("--delay must be at least 1 second for public Nominatim")

        stations = sample_stations(limit)
        if len(stations) < limit:
            self.stdout.write(
                self.style.WARNING(
                    f"Only {len(stations)} stations are available; requested {limit}."
                )
            )

        output_path = options["output"].resolve()
        report_path = options["report"].resolve()
        cache_path = options["cache"].resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            cache = {}
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read geocoding cache: {exc}") from exc
        if not isinstance(cache, dict):
            raise CommandError("Geocoding cache must contain a JSON object")
        rows: list[dict[str, object]] = []
        status_counts: Counter[str] = Counter()

        for index, station in enumerate(stations):
            variants = query_variants(station)
            query = variants[0]
            result_rows: list[dict[str, object]] = []
            error = ""
            status = "failed"
            query_used = ""
            for variant_index, variant in enumerate(variants):
                query_used = variant
                cache_key = variant
                if cache_key in cache:
                    cached = cache[cache_key]
                    if isinstance(cached, dict):
                        cached_results = cached.get("results", [])
                        if isinstance(cached_results, list):
                            result_rows = cached_results
                        error = str(cached.get("error", ""))
                else:
                    try:
                        result_rows = query_nominatim(variant, options["user_agent"])
                        cache[cache_key] = {"results": result_rows, "error": ""}
                    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                        error = str(exc)
                        cache[cache_key] = {"results": [], "error": error}
                    cache_path.write_text(
                        json.dumps(cache, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    if variant_index + 1 < len(variants):
                        time.sleep(options["delay"])
                if error:
                    break
                if result_rows:
                    break
            query = query_used
            if error:
                status = "failed"
            else:
                status = classify_results(station, result_rows)
            status_counts[status] += 1
            best = result_rows[0] if result_rows else {}
            rows.append(
                {
                    "sample_order": index + 1,
                    "database_id": station.id,
                    "opis_id": station.opis_id or "",
                    "name": station.name,
                    "address": station.address,
                    "city": station.city,
                    "state": station.state,
                    "query": query,
                    "query_attempts": " | ".join(variants),
                    "match_status": status,
                    "latitude": best.get("lat", "") if isinstance(best, dict) else "",
                    "longitude": best.get("lon", "") if isinstance(best, dict) else "",
                    "returned_type": best.get("type", "") if isinstance(best, dict) else "",
                    "returned_display_name": (
                        best.get("display_name", "") if isinstance(best, dict) else ""
                    ),
                    "result_count": len(result_rows),
                    "error": error,
                    "manual_review": "",
                    "manual_notes": "",
                }
            )
            if index + 1 < len(stations):
                time.sleep(options["delay"])

        fieldnames = list(rows[0].keys()) if rows else []
        with output_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        report = {
            "sample_size": len(rows),
            "status_counts_before_manual_review": dict(sorted(status_counts.items())),
            "nominatim_url": NOMINATIM_URL,
            "cache_file": str(cache_path),
            "user_agent": options["user_agent"],
            "minimum_delay_seconds": options["delay"],
            "manual_review_required": True,
            "instructions": (
                "Review each row against the station name/address. Set manual_review "
                "to station_level, ambiguous, or failed; do not treat candidate "
                "statuses as validated coordinates."
            ),
        }
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Sample CSV: {output_path}"))
        self.stdout.write(self.style.SUCCESS(f"Sample report: {report_path}"))
        self.stdout.write(json.dumps(report["status_counts_before_manual_review"], indent=2))
