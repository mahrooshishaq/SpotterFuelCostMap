from rest_framework import serializers


class CoordinateSerializer(serializers.Serializer):
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    latitude = serializers.FloatField(min_value=-90, max_value=90)


class RoutePlanRequestSerializer(serializers.Serializer):
    start = CoordinateSerializer()
    destination = CoordinateSerializer()


class PlaceLookupSerializer(serializers.Serializer):
    place = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)


class RouteStopResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    opis_id = serializers.CharField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    provided_price = serializers.FloatField()
    stop_order = serializers.IntegerField()
    distance_from_route_miles = serializers.FloatField()
    route_position_miles = serializers.FloatField()
    leg_distance_miles = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    estimated_purchase_cost = serializers.FloatField()


class RouteSummaryResponseSerializer(serializers.Serializer):
    matched_station_count = serializers.IntegerField()
    selected_stop_count = serializers.IntegerField()
    starting_tank_gallons = serializers.FloatField()
    total_route_fuel_gallons = serializers.FloatField()
    total_purchased_gallons = serializers.FloatField()
    total_purchase_cost = serializers.FloatField()
    price_description = serializers.CharField()
    detour_miles_included = serializers.BooleanField()


class RoutePlanResponseSerializer(serializers.Serializer):
    route = serializers.DictField()
    stops = RouteStopResponseSerializer(many=True)
    summary = RouteSummaryResponseSerializer()
