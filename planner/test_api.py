from decimal import Decimal
from unittest.mock import patch

from rest_framework.test import APITestCase

from planner.models import FuelStation
from planner.services.routing import RouteResult


class RoutePlanApiTests(APITestCase):
    def setUp(self):
        self.station = FuelStation.objects.create(
            opis_id="demo-1",
            name="Demo Fuel",
            address="1 Main St",
            city="Demo",
            state="AL",
            retail_price=Decimal("3.00"),
            latitude=Decimal("33.0"),
            longitude=Decimal("-85.5"),
            geocode_status="matched",
            location_quality="station_level",
        )
        self.route = RouteResult(
            geometry={
                "type": "LineString",
                "coordinates": [[-86.0, 33.0], [-85.0, 33.0]],
            },
            distance_miles=400,
            duration_minutes=400,
        )

    @patch("planner.views.get_route")
    def test_route_plan_returns_route_and_stops(self, get_route):
        get_route.return_value = self.route
        response = self.client.post(
            "/api/v1/route-plan/",
            {
                "start": {"longitude": -86.0, "latitude": 33.0},
                "destination": {"longitude": -85.0, "latitude": 33.0},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["route"]["geometry"]["type"], "LineString")
        self.assertEqual(response.data["summary"]["selected_stop_count"], 0)
        self.assertEqual(response.data["summary"]["starting_tank_gallons"], 50.0)
        self.assertEqual(response.data["summary"]["total_purchased_gallons"], 0.0)
        get_route.assert_called_once()

    def test_invalid_request_is_rejected(self):
        response = self.client.post(
            "/api/v1/route-plan/",
            {"start": {"longitude": -86.0}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
