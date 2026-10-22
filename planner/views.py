from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import render
from drf_spectacular.utils import OpenApiResponse, extend_schema

from .models import FuelStation
from .serializers import PlaceLookupSerializer, RoutePlanRequestSerializer
from .services.geocoding import GeocodingError, geocode_place
from .services.fuel_planning import InfeasibleFuelPlanError, plan_fuel_stops
from .services.fuel_planning import TANK_CAPACITY_GALLONS
from .services.routing import (
    InvalidRouteResponseError,
    RoutingError,
    RoutingUnavailableError,
    get_route,
)
from .services.station_matching import match_stations_to_route


def station_payload(match, leg):
    station = match.station
    return {
        "id": station.id,
        "opis_id": station.opis_id,
        "name": station.name,
        "address": station.address,
        "city": station.city,
        "state": station.state,
        "latitude": float(station.latitude),
        "longitude": float(station.longitude),
        "provided_price": float(station.retail_price),
        "stop_order": None,
        "distance_from_route_miles": round(match.distance_from_route_miles, 4),
        "route_position_miles": round(match.route_position_miles, 4),
        "leg_distance_miles": round(leg.distance_miles, 4),
        "gallons_purchased": round(leg.gallons_purchased, 4),
        "estimated_purchase_cost": round(leg.purchase_cost, 4),
    }


class RoutePlanView(APIView):
    @extend_schema(
        request=RoutePlanRequestSerializer,
        responses={
            200: OpenApiResponse(description="Route and optimized fuel-stop plan."),
            400: OpenApiResponse(description="Invalid coordinates or request."),
            422: OpenApiResponse(description="No feasible fuel-stop sequence."),
            502: OpenApiResponse(description="Routing provider failure."),
        },
        description=(
            "Returns an OSRM driving route and the least-cost feasible sequence "
            "of mapped fuel stations. Prices are provided dataset values; "
            "station detour miles are excluded from fuel calculations."
        ),
    )
    def post(self, request):
        serializer = RoutePlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        start = (data["start"]["longitude"], data["start"]["latitude"])
        destination = (
            data["destination"]["longitude"],
            data["destination"]["latitude"],
        )
        try:
            route = get_route(start, destination)
            matches = match_stations_to_route(
                route.geometry,
                FuelStation.objects.filter(
                    geocode_status=FuelStation.GeocodeStatus.MATCHED,
                    location_quality=FuelStation.LocationQuality.STATION_LEVEL,
                    latitude__isnull=False,
                    longitude__isnull=False,
                    retail_price__gt=0,
                ),
            )
            plan = plan_fuel_stops(route.distance_miles, matches)
        except InfeasibleFuelPlanError as exc:
            return Response(
                {"code": "NO_FEASIBLE_FUEL_PLAN", "detail": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except (RoutingUnavailableError, InvalidRouteResponseError) as exc:
            return Response(
                {"code": "ROUTING_ERROR", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except RoutingError as exc:
            return Response(
                {"code": "INVALID_ROUTE_REQUEST", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as exc:
            return Response(
                {"code": "INVALID_PLANNING_DATA", "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        legs_by_station_id = {
            leg.station.id: leg for leg in plan.legs if leg.station is not None
        }
        stops = []
        for order, match in enumerate(plan.stops, start=1):
            leg = legs_by_station_id[match.station.id]
            stop = station_payload(match, leg)
            stop["stop_order"] = order
            stops.append(stop)
        return Response(
            {
                "route": {
                    "geometry": route.geometry,
                    "distance_miles": round(route.distance_miles, 4),
                    "duration_minutes": round(route.duration_minutes, 4),
                },
                "stops": stops,
                "summary": {
                    "matched_station_count": len(matches),
                    "selected_stop_count": len(stops),
                    "starting_tank_gallons": TANK_CAPACITY_GALLONS,
                    "total_route_fuel_gallons": round(
                        plan.total_route_fuel_gallons, 4
                    ),
                    "total_purchased_gallons": round(
                        plan.total_purchased_gallons, 4
                    ),
                    "total_purchase_cost": round(plan.total_purchase_cost, 4),
                    "price_description": "provided price from company dataset",
                    "detour_miles_included": False,
                },
            },
            status=status.HTTP_200_OK,
        )


def map_view(request):
    return render(request, "planner/map.html")


class PlaceLookupView(APIView):
    @extend_schema(
        request=PlaceLookupSerializer,
        responses={200: OpenApiResponse(description="Resolved US place coordinates.")},
    )
    def post(self, request):
        serializer = PlaceLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            longitude, latitude = geocode_place(serializer.validated_data["place"])
        except GeocodingError as exc:
            return Response(
                {"code": "PLACE_LOOKUP_ERROR", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "place": serializer.validated_data["place"],
                "longitude": longitude,
                "latitude": latitude,
            }
        )