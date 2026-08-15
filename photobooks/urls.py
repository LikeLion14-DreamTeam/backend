from django.urls import path

from . import views

urlpatterns = [
    path("photobooks", views.photobook_list, name="photobook-list"),
    path("photobooks/<int:photobook_id>", views.photobook_detail, name="photobook-detail"),
]
