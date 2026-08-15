from django.urls import path

from . import views

urlpatterns = [
    path(
        "users/me/basic-question-responses",
        views.submit_basic_question_response,
        name="basic-question-responses",
    ),
    path(
        "users/me/selection-photos",
        views.submit_selection_photo,
        name="selection-photos",
    ),
]
