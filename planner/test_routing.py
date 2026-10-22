import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from planner.services.routing import (
    InvalidRouteResponseError,
    RoutingError,
    RoutingUnavailableError,
    get_route,
)


class RoutingServiceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @staticmethod
    def response(payload):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        return Response()

    def test_normalizes_valid_osrm_response(self):
        payload = {
            "code": "Ok",
            "routes": [{
                "distance": 16093.44,
                "duration": 3600,
                "geometry": {"type": "LineString", "coordinates": [[-73.9, 40.7], [-73.8, 40.8]]},
            }],
        }
        with patch("planner.services.routing.urlopen", return_value=self.response(payload)) as request:
            result = get_route((-73.9, 40.7), (-73.8, 40.8), use_cache=False)
        self.assertAlmostEqual(result.distance_miles, 10)
        self.assertAlmostEqual(result.duration_minutes, 60)
        self.assertEqual(result.geometry["type"], "LineString")
        request.assert_called_once()
        self.assertIn("overview=full", request.call_args.args[0].full_url)
        self.assertIn("geometries=geojson", request.call_args.args[0].full_url)

    def test_reuses_successful_cache(self):
        payload = {
            "code": "Ok",
            "routes": [{
                "distance": 1000,
                "duration": 60,
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            }],
        }
        with patch("planner.services.routing.urlopen", return_value=self.response(payload)) as request:
            get_route((0, 0), (1, 1))
            get_route((0, 0), (1, 1))
        request.assert_called_once()

    def test_rejects_non_route_geometry(self):
        payload = {"code": "Ok", "routes": [{"distance": 10, "duration": 10, "geometry": {}}]}
        with patch("planner.services.routing.urlopen", return_value=self.response(payload)):
            with self.assertRaises(InvalidRouteResponseError):
                get_route((0, 0), (1, 1), use_cache=False)

    def test_rejects_invalid_coordinates(self):
        with self.assertRaises(RoutingError):
            get_route((181, 0), (1, 1), use_cache=False)

    def test_surfaces_provider_failure(self):
        from urllib.error import URLError

        with patch("planner.services.routing.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(RoutingUnavailableError):
                get_route((0, 0), (1, 1), use_cache=False)
