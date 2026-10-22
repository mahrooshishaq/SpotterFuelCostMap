from decimal import Decimal

from django.test import SimpleTestCase

from planner.models import FuelStation
from planner.services.fuel_planning import (
    InfeasibleFuelPlanError,
    fuel_consumed,
    plan_fuel_stops,
    refill_cost,
)
from planner.services.station_matching import MatchedStation


class FuelPlanningTests(SimpleTestCase):
    def station(self, pk, position, price):
        station = FuelStation(
            id=pk,
            name=f"Station {pk}",
            address="Test",
            city="Test",
            state="AL",
            retail_price=Decimal(str(price)),
        )
        return MatchedStation(station, 1.0, position)

    def test_central_calculations(self):
        self.assertEqual(fuel_consumed(100), 10)
        self.assertEqual(fuel_consumed(500), 50)
        self.assertAlmostEqual(refill_cost(200, 3), 60)

    def test_direct_destination_needs_no_stop(self):
        plan = plan_fuel_stops(400, [])
        self.assertEqual(plan.stops, ())
        self.assertEqual(plan.total_route_fuel_gallons, 40)
        self.assertEqual(plan.total_purchased_gallons, 0)
        self.assertEqual(plan.total_purchase_cost, 0)

    def test_dynamic_programming_prefers_lower_total_purchase_cost(self):
        stations = [self.station(1, 200, 5), self.station(2, 400, 2)]
        plan = plan_fuel_stops(600, stations)
        self.assertEqual([stop.station.pk for stop in plan.stops], [2])
        self.assertAlmostEqual(plan.total_purchase_cost, 80)
        self.assertAlmostEqual(plan.total_purchased_gallons, 40)

    def test_cheap_but_unreachable_station_is_not_selected(self):
        stations = [self.station(1, 501, 1), self.station(2, 300, 4)]
        plan = plan_fuel_stops(800, stations)
        self.assertEqual([stop.station.pk for stop in plan.stops], [2])

    def test_multi_stop_plan_and_cost_reconcile(self):
        stations = [self.station(1, 450, 2), self.station(2, 900, 4)]
        plan = plan_fuel_stops(1000, stations)
        self.assertEqual([stop.station.pk for stop in plan.stops], [1, 2])
        self.assertAlmostEqual(plan.total_route_fuel_gallons, 100)
        self.assertAlmostEqual(plan.total_purchased_gallons, 90)
        self.assertAlmostEqual(plan.total_purchase_cost, 270)

    def test_infeasible_route_is_explicit(self):
        with self.assertRaises(InfeasibleFuelPlanError):
            plan_fuel_stops(501, [])

    def test_exactly_500_miles_is_reachable(self):
        plan = plan_fuel_stops(500, [])
        self.assertEqual(plan.total_route_fuel_gallons, 50)

    def test_overlapping_station_position_keeps_cheapest_candidate(self):
        stations = [self.station(1, 0.1, 3.50), self.station(2, 0.1, 3.00)]
        plan = plan_fuel_stops(500.1, stations)
        self.assertEqual([stop.station.pk for stop in plan.stops], [2])
        self.assertAlmostEqual(plan.total_purchased_gallons, 0.01)
        self.assertAlmostEqual(plan.total_purchase_cost, 0.03, places=2)
