from django.urls import path

from . import views

urlpatterns = [
    path("trips/current", views.trip_current, name="trip-current"),
]