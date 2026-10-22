"""Fuel calculations and route-ordered cheapest-stop planning."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from planner.services.station_matching import MatchedStation


MAX_RANGE_MILES = 500.0
FUEL_ECONOMY_MPG = 10.0
TANK_CAPACITY_GALLONS = MAX_RANGE_MILES / FUEL_ECONOMY_MPG


class FuelPlanError(Exception):
    """Base class for fuel-planning failures."""


class InfeasibleFuelPlanError(FuelPlanError):
    """No sequence of available stops can reach the destination."""


@dataclass(frozen=True)
class FuelLeg:
    from_position_miles: float
    to_position_miles: float
    distance_miles: float
    gallons_purchased: float
    price_per_gallon: float
    purchase_cost: float
    station: object | None


@dataclass(frozen=True)
class FuelPlan:
    stops: tuple[MatchedStation, ...]
    legs: tuple[FuelLeg, ...]
    total_route_fuel_gallons: float
    total_purchased_gallons: float
    total_purchase_cost: float


def fuel_consumed(distance_miles: float) -> float:
    distance = float(distance_miles)
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("distance_miles must be finite and non-negative")
    return distance / FUEL_ECONOMY_MPG


def refill_cost(distance_miles: float, price_per_gallon: float) -> float:
    price = float(price_per_gallon)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("price_per_gallon must be finite and positive")
    return fuel_consumed(distance_miles) * price


def _as_price(value: Decimal | float | int) -> float:
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("station price must be finite and positive")
    return price


def plan_fuel_stops(
    route_distance_miles: float,
    matched_stations: list[MatchedStation],
    *,
    max_range_miles: float = MAX_RANGE_MILES,
    mpg: float = FUEL_ECONOMY_MPG,
) -> FuelPlan:
    """Find the least-cost full-refill stop sequence in route order."""
    total_distance = float(route_distance_miles)
    if not math.isfinite(total_distance) or total_distance < 0:
        raise ValueError("route_distance_miles must be finite and non-negative")
    if not math.isfinite(max_range_miles) or max_range_miles <= 0:
        raise ValueError("max_range_miles must be finite and positive")
    if not math.isfinite(mpg) or mpg <= 0:
        raise ValueError("mpg must be finite and positive")

    stations = sorted(
        {
            match.station.pk: match
            for match in matched_stations
            if 0 < match.route_position_miles < total_distance
        }.values(),
        key=lambda match: (match.route_position_miles, match.station.pk),
    )
    # Multiple source records can represent stations at the same mapped
    # location. Keep the cheapest one so the planner does not create a
    # zero-distance refueling leg between duplicates.
    unique_positions: list[MatchedStation] = []
    for match in stations:
        if (
            unique_positions
            and math.isclose(
                match.route_position_miles,
                unique_positions[-1].route_position_miles,
                abs_tol=0.01,
            )
        ):
            previous = unique_positions[-1]
            if _as_price(match.station.retail_price) < _as_price(
                previous.station.retail_price
            ):
                unique_positions[-1] = match
            continue
        unique_positions.append(match)
    stations = unique_positions
    positions = [0.0, *[match.route_position_miles for match in stations], total_distance]
    node_stations: list[MatchedStation | None] = [None, *stations, None]
    costs = [math.inf] * len(positions)
    previous: list[int | None] = [None] * len(positions)
    costs[0] = 0.0

    for current in range(len(positions)):
        if not math.isfinite(costs[current]):
            continue
        for following in range(current + 1, len(positions)):
            distance = positions[following] - positions[current]
            if distance > max_range_miles + 1e-9:
                break
            destination = node_stations[following]
            edge_cost = 0.0
            if destination is not None:
                edge_cost = refill_cost(distance, _as_price(destination.station.retail_price))
            candidate_cost = costs[current] + edge_cost
            if candidate_cost < costs[following] - 1e-9:
                costs[following] = candidate_cost
                previous[following] = current

    destination_index = len(positions) - 1
    if previous[destination_index] is None and total_distance > 0:
        raise InfeasibleFuelPlanError(
            "NO_FEASIBLE_FUEL_PLAN: destination cannot be reached within the available range"
        )

    path: list[int] = []
    index: int | None = destination_index
    while index is not None:
        path.append(index)
        index = previous[index]
    path.reverse()
    stop_indices = [index for index in path if node_stations[index] is not None]
    stops = tuple(node_stations[index] for index in stop_indices)

    legs: list[FuelLeg] = []
    total_purchased = 0.0
    for start_index, end_index in zip(path, path[1:]):
        distance = positions[end_index] - positions[start_index]
        station = node_stations[end_index]
        gallons = fuel_consumed(distance)
        price = _as_price(station.station.retail_price) if station else 0.0
        purchase = gallons if station else 0.0
        cost = purchase * price
        total_purchased += purchase
        legs.append(
            FuelLeg(
                from_position_miles=positions[start_index],
                to_position_miles=positions[end_index],
                distance_miles=distance,
                gallons_purchased=purchase,
                price_per_gallon=price,
                purchase_cost=cost,
                station=station.station if station else None,
            )
        )
    total_route_fuel = fuel_consumed(total_distance)
    if not math.isclose(sum(leg.purchase_cost for leg in legs), costs[destination_index], rel_tol=1e-9, abs_tol=1e-9):
        raise FuelPlanError("Fuel plan cost reconciliation failed")
    return FuelPlan(
        stops=tuple(stop for stop in stops if stop is not None),
        legs=tuple(legs),
        total_route_fuel_gallons=total_route_fuel,
        total_purchased_gallons=total_purchased,
        total_purchase_cost=costs[destination_index],
    )
