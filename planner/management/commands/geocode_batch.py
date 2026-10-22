"""Resumable Nominatim batch for stations with conventional addresses."""

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

from planner.management.commands.geocode_sample import (
    DEFAULT_CACHE,
    USER_AGENT,
    classify_results,
    has_conventional_address,
    query_variants,
)
from planner.models import FuelStation


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "data" / "geocoding" / "geocoding_batch.csv"
DEFAULT_REPORT = ROOT / "data" / "geocoding" / "geocoding_batch_report.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


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


def name_tokens(name: str) -> set[str]:
    ignored = {"THE", "OF", "AND", "AT", "TRAVEL", "CENTER", "CENTRE", "STOP"}
    return {
        token
        for token in re.findall(r"[A-Z0-9]+", name.upper())
        if len(token) >= 3 and token not in ignored
    }


def auto_review(station: FuelStation, result: dict[str, object]) -> tuple[str, str]:
    """Approve only strong station-like results; otherwise exclude them."""
    result_type = str(result.get("type", "")).casefold()
    display_name = str(result.get("display_name", ""))
    result_name = str(result.get("name", ""))
    station_tokens = name_tokens(station.name)
    returned_tokens = name_tokens(f"{result_name} {display_name}")
    shared_tokens = station_tokens & returned_tokens
    station_feature = result_type in {"fuel", "convenience", "services", "service"}
    if station_feature and shared_tokens:
        return (
            "station_level",
            f"automatic approval: station-like result with shared tokens {sorted(shared_tokens)}",
        )
    if station_feature:
        return (
            "ambiguous",
            "automatic exclusion: station-like result did not match the source station name",
        )
    return (
        "failed",
        f"automatic exclusion: result type {result_type or 'unknown'} is not a station feature",
    )


class Command(BaseCommand):
    help = "Geocode conventional-address stations with a resumable cached batch."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--delay", type=float, default=1.1)
        parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
        parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
        parser.add_argument("--user-agent", default=USER_AGENT)

    def handle(self, *args, **options) -> None:
        if options["delay"] < 1:
            raise CommandError("--delay must be at least 1 second for public Nominatim")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1")

        stations = [
            station
            for station in FuelStation.objects.order_by("state", "city", "id")
            if has_conventional_address(station)
        ]
        if options["limit"] is not None:
            stations = stations[: options["limit"]]

        cache_path = options["cache"].resolve()
        output_path = options["output"].resolve()
        report_path = options["report"].resolve()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
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
        request_count = 0
        cache_hits = 0
        for index, station in enumerate(stations):
            variants = query_variants(station)
            results: list[dict[str, object]] = []
            error = ""
            query_used = variants[-1]
            for variant_index, variant in enumerate(variants):
                query_used = variant
                if variant in cache:
                    cache_hits += 1
                    cached = cache[variant]
                    results = cached.get("results", []) if isinstance(cached, dict) else []
                    error = str(cached.get("error", "")) if isinstance(cached, dict) else ""
                else:
                    request_count += 1
                    try:
                        results = query_nominatim(variant, options["user_agent"])
                        cache[variant] = {"results": results, "error": ""}
                    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                        error = str(exc)
                        results = []
                        cache[variant] = {"results": [], "error": error}
                    cache_path.write_text(
                        json.dumps(cache, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    if variant_index + 1 < len(variants):
                        time.sleep(options["delay"])
                if error or results:
                    break

            status = "failed" if error else classify_results(station, results)
            status_counts[status] += 1
            best = results[0] if results else {}
            if error:
                review = "failed"
                review_notes = f"automatic exclusion: request error: {error}"
            elif isinstance(best, dict) and best:
                review, review_notes = auto_review(station, best)
            else:
                review = "failed"
                review_notes = "automatic exclusion: no geocoder result"
            rows.append(
                {
                    "database_id": station.id,
                    "opis_id": station.opis_id or "",
                    "name": station.name,
                    "address": station.address,
                    "city": station.city,
                    "state": station.state,
                    "query_used": query_used,
                    "query_attempts": " | ".join(variants),
                    "match_status": status,
                    "latitude": best.get("lat", "") if isinstance(best, dict) else "",
                    "longitude": best.get("lon", "") if isinstance(best, dict) else "",
                    "returned_type": best.get("type", "") if isinstance(best, dict) else "",
                    "returned_display_name": (
                        best.get("display_name", "") if isinstance(best, dict) else ""
                    ),
                    "result_count": len(results),
                    "error": error,
                    "manual_review": review,
                    "manual_notes": review_notes,
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
            "eligible_conventional_address_stations": len(stations),
            "requests_made_this_run": request_count,
            "cache_hits_this_run": cache_hits,
            "status_counts_before_manual_review": dict(sorted(status_counts.items())),
            "manual_review_required": False,
            "manual_review_available": True,
            "review_policy": (
                "Automatic review is conservative: station_level requires a "
                "fuel/convenience/service result and a shared meaningful token "
                "between the source station name and returned result. All other "
                "results are excluded."
            ),
            "automatic_review_counts": dict(
                sorted(Counter(row["manual_review"] for row in rows).items())
            ),
            "coordinates_imported": 0,
            "policy": (
                "Only manually reviewed station_level rows may be imported. "
                "Highway/exit descriptions are excluded from this batch."
            ),
        }
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"Batch CSV: {output_path}"))
        self.stdout.write(self.style.SUCCESS(f"Batch report: {report_path}"))
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
