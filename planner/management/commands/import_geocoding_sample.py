"""Import manually approved station coordinates from the review CSV."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelStation


DEFAULT_INPUT = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "geocoding"
    / "geocoding_sample.csv"
)
REQUIRED_COLUMNS = {
    "database_id",
    "opis_id",
    "latitude",
    "longitude",
    "manual_review",
}


class Command(BaseCommand):
    help = "Import only manually approved station-level sample coordinates."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)

    def handle(self, *args, **options) -> None:
        input_path = options["input"].resolve()
        if not input_path.is_file():
            raise CommandError(f"Geocoding review CSV was not found: {input_path}")

        try:
            with input_path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
                if missing:
                    raise CommandError(
                        "Geocoding review CSV is missing required columns: "
                        + ", ".join(missing)
                    )
                rows = list(reader)
        except (OSError, UnicodeError, csv.Error) as exc:
            raise CommandError(f"Could not read geocoding review CSV: {exc}") from exc

        with transaction.atomic():
            counts = self.import_rows(rows, input_path)

        self.stdout.write(self.style.SUCCESS(f"Reviewed coordinates imported from {input_path}"))
        for label, value in counts.items():
            self.stdout.write(f"{label}: {value}")

    def import_rows(
        self,
        rows: list[dict[str, str]],
        input_path: Path,
    ) -> dict[str, int]:
        approved = 0
        updated = 0
        unchanged = 0
        excluded = 0

        for line_number, row in enumerate(rows, start=2):
            review = (row.get("manual_review") or "").strip().casefold()
            if review != "station_level":
                excluded += 1
                continue
            approved += 1

            try:
                database_id = int((row.get("database_id") or "").strip())
                latitude = Decimal((row.get("latitude") or "").strip())
                longitude = Decimal((row.get("longitude") or "").strip())
            except (InvalidOperation, ValueError) as exc:
                raise CommandError(
                    f"{input_path}, CSV row {line_number}: approved row has invalid "
                    "database_id, latitude, or longitude"
                ) from exc
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise CommandError(
                    f"{input_path}, CSV row {line_number}: approved coordinates are out of range"
                )

            try:
                station = FuelStation.objects.get(pk=database_id)
            except FuelStation.DoesNotExist as exc:
                raise CommandError(
                    f"{input_path}, CSV row {line_number}: no station with database_id "
                    f"{database_id}"
                ) from exc

            opis_id = (row.get("opis_id") or "").strip() or None
            if station.opis_id != opis_id:
                raise CommandError(
                    f"{input_path}, CSV row {line_number}: OPIS ID does not match "
                    f"database station {database_id}"
                )

            values = {
                "latitude": latitude,
                "longitude": longitude,
                "geocode_status": FuelStation.GeocodeStatus.MATCHED,
                "geocode_source": "nominatim_manual_review",
                "location_quality": FuelStation.LocationQuality.STATION_LEVEL,
            }
            if all(getattr(station, field) == value for field, value in values.items()):
                unchanged += 1
                continue
            for field, value in values.items():
                setattr(station, field, value)
            station.save(update_fields=[*values, "updated_at"])
            updated += 1

        return {
            "review_rows_read": len(rows),
            "station_level_rows_approved": approved,
            "coordinates_updated": updated,
            "coordinates_unchanged": unchanged,
            "non_station_level_rows_excluded": excluded,
            "database_station_total": FuelStation.objects.count(),
        }
