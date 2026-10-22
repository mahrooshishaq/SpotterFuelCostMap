"""Import the reproducibly cleaned station CSV into Django's database."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from planner.models import FuelStation


REQUIRED_COLUMNS = {
    "opis_id",
    "name",
    "address",
    "city",
    "state",
    "rack_id",
    "retail_price",
    "source_row_numbers",
    "source_row_count",
    "source_prices",
    "price_aggregation",
}
DEFAULT_INPUT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "processed"
    / "fuel_stations_cleaned.csv"
)


def normalized(value: str) -> str:
    return " ".join((value or "").strip().casefold().split())


def identity_for(row: dict[str, str]) -> tuple[str, ...]:
    """Return the stable identity used to make repeated imports idempotent."""
    opis_id = (row.get("opis_id") or "").strip()
    location = (
        normalized(row.get("address", "")),
        normalized(row.get("city", "")),
        (row.get("state") or "").strip().upper(),
    )
    if opis_id:
        return ("opis_id_location", opis_id, *location)
    return ("missing_id_location_name", *location, normalized(row.get("name", "")))


class Command(BaseCommand):
    help = "Import the cleaned fuel station CSV into the configured Django database."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--input",
            type=Path,
            default=DEFAULT_INPUT,
            help=f"Cleaned CSV path (default: {DEFAULT_INPUT})",
        )

    def handle(self, *args, **options) -> None:
        input_path = options["input"].resolve()
        if not input_path.is_file():
            raise CommandError(f"Cleaned station CSV was not found: {input_path}")

        try:
            with input_path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                actual_columns = set(reader.fieldnames or [])
                missing_columns = sorted(REQUIRED_COLUMNS - actual_columns)
                if missing_columns:
                    raise CommandError(
                        "Cleaned CSV is missing required columns: "
                        + ", ".join(missing_columns)
                    )
                rows = list(reader)
        except (OSError, UnicodeError, csv.Error) as exc:
            raise CommandError(f"Could not read cleaned station CSV: {exc}") from exc

        try:
            with transaction.atomic():
                counts = self.import_rows(rows, input_path)
        except CommandError:
            raise
        except DatabaseError as exc:
            raise CommandError(f"Station import failed; transaction rolled back: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Imported stations from {input_path}"))
        for label, value in counts.items():
            self.stdout.write(f"{label}: {value}")

    def import_rows(
        self,
        rows: list[dict[str, str]],
        input_path: Path,
    ) -> dict[str, int]:
        seen: set[tuple[str, ...]] = set()
        imported = 0
        updated = 0
        skipped = 0

        for line_number, row in enumerate(rows, start=2):
            identity = identity_for(row)
            if identity in seen:
                raise CommandError(
                    f"Duplicate station identity in {input_path} at CSV row {line_number}: "
                    f"{identity}"
                )
            seen.add(identity)

            try:
                station_data = self.parse_station(row, line_number)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

            identity_filter = {
                "opis_id": station_data["opis_id"],
                "address": station_data["address"],
                "city": station_data["city"],
                "state": station_data["state"],
            }
            if station_data["opis_id"] is None:
                identity_filter["name"] = station_data["name"]

            station = FuelStation.objects.filter(**identity_filter).first()
            if station is None:
                FuelStation.objects.create(**station_data)
                imported += 1
            else:
                changed = any(
                    getattr(station, field) != value
                    for field, value in station_data.items()
                    if field not in {"geocode_status", "geocode_source", "location_quality"}
                )
                if changed:
                    for field, value in station_data.items():
                        if field not in {
                            "geocode_status",
                            "geocode_source",
                            "location_quality",
                        }:
                            setattr(station, field, value)
                    station.save()
                    updated += 1
                else:
                    skipped += 1

        return {
            "rows_read": len(rows),
            "imported": imported,
            "updated": updated,
            "skipped_unchanged": skipped,
            "database_total": FuelStation.objects.count(),
        }

    @staticmethod
    def parse_station(row: dict[str, str], line_number: int) -> dict[str, object]:
        required_text = ("name", "address", "city", "state")
        for field in required_text:
            if not (row.get(field) or "").strip():
                raise ValueError(f"CSV row {line_number}: {field} must not be empty")

        try:
            price = Decimal((row.get("retail_price") or "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f"CSV row {line_number}: retail_price must be a valid decimal"
            ) from exc
        if not price.is_finite() or price <= 0:
            raise ValueError(
                f"CSV row {line_number}: retail_price must be finite and greater than zero"
            )

        try:
            source_row_count = int((row.get("source_row_count") or "").strip())
        except ValueError as exc:
            raise ValueError(
                f"CSV row {line_number}: source_row_count must be an integer"
            ) from exc
        if source_row_count < 1:
            raise ValueError(
                f"CSV row {line_number}: source_row_count must be at least one"
            )

        return {
            "opis_id": (row.get("opis_id") or "").strip() or None,
            "name": row["name"].strip(),
            "address": row["address"].strip(),
            "city": row["city"].strip(),
            "state": row["state"].strip().upper(),
            "rack_id": (row.get("rack_id") or "").strip() or None,
            "retail_price": price,
            "geocode_status": FuelStation.GeocodeStatus.UNMATCHED,
            "geocode_source": "",
            "location_quality": "",
            "source_row_count": source_row_count,
            "source_row_numbers": (row.get("source_row_numbers") or "").strip(),
            "source_prices": (row.get("source_prices") or "").strip(),
            "price_aggregation": (row.get("price_aggregation") or "").strip(),
        }
