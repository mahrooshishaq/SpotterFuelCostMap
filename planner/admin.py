from django.contrib import admin

from .models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = (
        "opis_id",
        "name",
        "city",
        "state",
        "retail_price",
        "geocode_status",
        "location_quality",
    )
    list_filter = ("state", "geocode_status", "location_quality")
    search_fields = ("opis_id", "name", "address", "city")
    ordering = ("state", "city", "name")