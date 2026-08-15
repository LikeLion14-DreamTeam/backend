from django.urls import path

from . import views

urlpatterns = [
    path("pins", views.pin_create, name="pin-create"),
    path("pins/<int:pin_id>", views.pin_detail, name="pin-detail"),
    path("pins/<int:pin_id>/photos", views.pin_photos, name="pin-photos"),
    path("pins/<int:pin_id>/voice-memos", views.pin_voice_memos, name="pin-voice-memos"),
    path("photos/<int:photo_id>", views.photo_delete, name="photo-delete"),
    path("trips/current", views.trip_current, name="trip-current"),
    path("trips", views.trip_list_or_create, name="trip-list-or-create"),
    path("trips/<int:segment_id>", views.trip_detail, name="trip-detail"),
    path("trips/<int:segment_id>/pins", views.trip_pins, name="trip-pins"),
]