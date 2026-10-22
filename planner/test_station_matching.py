from decimal import Decimal

from django.test import SimpleTestCase

from planner.models import FuelStation
from planner.services.station_matching import match_stations_to_route


class StationMatchingTests(SimpleTestCase):
    def station(self, pk, longitude, latitude, quality="station_level"):
        return FuelStation(
            id=pk,
            name=f"Station {pk}",
            address="Test address",
            city="Test city",
            state="AL",
            retail_price=Decimal("3.00"),
            longitude=Decimal(str(longitude)),
            latitude=Decimal(str(latitude)),
            location_quality=quality,
        )

    def test_includes_corridor_stations_and_orders_by_route_position(self):
        route = {
            "type": "LineString",
            "coordinates": [[-86.0, 33.0], [-85.0, 33.0]],
        }
        stations = [
            self.station(2, -85.5, 33.01),
            self.station(1, -85.9, 33.01),
            self.station(3, -84.5, 33.0),
        ]
        matches = match_stations_to_route(route, stations)
        self.assertEqual([match.station.pk for match in matches], [1, 2])
        self.assertLess(matches[0].route_position_miles, matches[1].route_position_miles)

    def test_excludes_missing_coordinates_and_centroid_fallbacks(self):
        route = {"type": "LineString", "coordinates": [[-86, 33], [-85, 33]]}
        stations = [
            self.station(1, -85.5, 33),
            self.station(2, -85.5, 33, "city_centroid"),
            self.station(3, -85.5, 33, ""),
        ]
        stations[0].latitude = None
        matches = match_stations_to_route(route, stations)
        self.assertEqual(matches, [])

    def test_accepts_exact_corridor_threshold(self):
        route = {"type": "LineString", "coordinates": [[-86, 33], [-85, 33]]}
        station = self.station(1, -85.5, 33.0 + 5 / 69)
        matches = match_stations_to_route(route, [station])
        self.assertEqual(len(matches), 1)
