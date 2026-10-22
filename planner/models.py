from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class FuelStation(models.Model):
    class GeocodeStatus(models.TextChoices):
        MATCHED = "matched", "Matched"
        CITY_CENTROID_FALLBACK = (
            "city_centroid_fallback",
            "City centroid fallback",
        )
        AMBIGUOUS = "ambiguous", "Ambiguous"
        UNMATCHED = "unmatched", "Unmatched"
        FAILED = "failed", "Failed"

    class LocationQuality(models.TextChoices):
        STATION_LEVEL = "station_level", "Station level"
        CITY_CENTROID = "city_centroid", "City centroid"

    opis_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    rack_id = models.CharField(max_length=64, blank=True, null=True)
    retail_price = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        validators=[MinValueValidator(Decimal("0.00000001"))],
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    geocode_status = models.CharField(
        max_length=32,
        choices=GeocodeStatus.choices,
        default=GeocodeStatus.UNMATCHED,
    )
    geocode_source = models.CharField(max_length=100, blank=True, default="")
    location_quality = models.CharField(
        max_length=32,
        choices=LocationQuality.choices,
        blank=True,
        default="",
    )
    source_row_count = models.PositiveIntegerField(default=1)
    source_row_numbers = models.TextField(blank=True, default="")
    source_prices = models.TextField(blank=True, default="")
    price_aggregation = models.CharField(
        max_length=32,
        blank=True,
        default="source_price",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["state", "city", "address", "name", "id"]
        indexes = [
            models.Index(fields=["state", "city"], name="station_state_city_idx"),
            models.Index(
                fields=["geocode_status", "location_quality"],
                name="station_geocode_quality_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.city}, {self.state}"