from django.urls import path

from . import views

urlpatterns = [
    path("trips/current", views.trip_current, name="trip-current"),
    path("trips", views.trip_list_or_create, name="trip-list-or-create"),
    path("trips/<int:segment_id>", views.trip_detail, name="trip-detail"),
    path("trips/<int:segment_id>/pins", views.trip_pins, name="trip-pins"),
]