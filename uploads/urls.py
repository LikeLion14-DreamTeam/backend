from django.urls import path

from . import views

urlpatterns = [
    path("uploads", views.request_upload, name="request-upload"),
]
