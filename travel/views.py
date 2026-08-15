import logging

from django.db.models import Min
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication

from .models import Photo, Pin

request_logger = logging.getLogger("request_logger")


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def trip_current(request):
    """
    GET /trips/current — 진행 중인 여행 요약 조회 (3.1).
    """
    pins = Pin.objects.filter(user=request.user, segment__isnull=True)
    pin_count = pins.count()

    if pin_count == 0:
        return Response(
            {"has_pins": False, "pin_count": 0, "photo_count": 0, "started_at": None, "cities": []}
        )

    photo_count = Photo.objects.filter(pin__in=pins).count()
    started_at = pins.aggregate(Min("tagged_at"))["tagged_at__min"]
    cities = sorted({c for c in pins.exclude(city__isnull=True).exclude(city="").values_list("city", flat=True)})

    return Response(
        {
            "has_pins": True,
            "pin_count": pin_count,
            "photo_count": photo_count,
            "started_at": started_at,
            "cities": cities,
        }
    )