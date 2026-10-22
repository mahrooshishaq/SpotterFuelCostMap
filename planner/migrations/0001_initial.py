from decimal import Decimal

from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "opis_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=64,
                        null=True,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(max_length=120)),
                ("state", models.CharField(max_length=2)),
                (
                    "rack_id",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "retail_price",
                    models.DecimalField(
                        decimal_places=8,
                        max_digits=12,
                        validators=[MinValueValidator(Decimal("0.00000001"))],
                    ),
                ),
                (
                    "latitude",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                    ),
                ),
                (
                    "longitude",
                    models.DecimalField(
                        blank=True,
                        decimal_places=6,
                        max_digits=9,
                        null=True,
                    ),
                ),
                (
                    "geocode_status",
                    models.CharField(
                        choices=[
                            ("matched", "Matched"),
                            (
                                "city_centroid_fallback",
                                "City centroid fallback",
                            ),
                            ("ambiguous", "Ambiguous"),
                            ("unmatched", "Unmatched"),
                            ("failed", "Failed"),
                        ],
                        default="unmatched",
                        max_length=32,
                    ),
                ),
                (
                    "geocode_source",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "location_quality",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=32,
                        choices=[
                            ("station_level", "Station level"),
                            ("city_centroid", "City centroid"),
                        ],
                    ),
                ),
                ("source_row_count", models.PositiveIntegerField(default=1)),
                ("source_row_numbers", models.TextField(blank=True, default="")),
                ("source_prices", models.TextField(blank=True, default="")),
                (
                    "price_aggregation",
                    models.CharField(
                        blank=True,
                        default="source_price",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["state", "city", "address", "name", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(
                fields=["state", "city"],
                name="station_state_city_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(
                fields=["geocode_status", "location_quality"],
                name="station_geocode_quality_idx",
            ),
        ),
    ]
