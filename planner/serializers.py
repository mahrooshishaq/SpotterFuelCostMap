from rest_framework import serializers


class CoordinateSerializer(serializers.Serializer):
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    latitude = serializers.FloatField(min_value=-90, max_value=90)


class RoutePlanRequestSerializer(serializers.Serializer):
    start = CoordinateSerializer()
    destination = CoordinateSerializer()


class PlaceLookupSerializer(serializers.Serializer):
    place = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)


class RoutePlanResponseSerializer(serializers.Serializer):
    route = serializers.DictField()
    stops = serializers.ListField()
    summary = serializers.DictField()
