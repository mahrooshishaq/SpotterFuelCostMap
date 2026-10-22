from django.urls import path

from .views import PlaceLookupView, RoutePlanView


app_name = "planner"

urlpatterns = [
    path("v1/route-plan/", RoutePlanView.as_view(), name="route-plan"),
    path("v1/place-lookup/", PlaceLookupView.as_view(), name="place-lookup"),
]
