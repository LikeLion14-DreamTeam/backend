from django.urls import path

from . import views

urlpatterns = [
    path("auth/google", views.google_login, name="google-login"),
    path("auth/logout", views.logout, name="logout"),
    path("users/me", views.me, name="me"),
    path("events/permissions", views.events_permissions, name="events-permissions"),
]
