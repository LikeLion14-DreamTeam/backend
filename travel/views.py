import logging

from django.db import transaction
from django.db.models import Min
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication

from .models import Photo, Pin, TravelSegment
from .serializers import TripCreateRequestSerializer

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


def _default_trip_name(pins, start_at, end_at):
    """
    name 미입력 시 기본 이름
    """
    cities = []
    seen = set()
    for pin in pins:
        if pin.city and pin.city not in seen:
            seen.add(pin.city)
            cities.append(pin.city)
    if cities:
        return ", ".join(cities)

    start_date = start_at.date()
    end_date = end_at.date()
    if start_date == end_date:
        return f"{start_date} 여행"
    return f"{start_date}~{end_date} 여행"


@api_view(["POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def trip_list_or_create(request):
    """
    POST /trips — 여행 종료(여정 생성) (3.2)
    """
    return _trip_create(request)


def _trip_create(request):
    """
    POST /trips — 여행 종료(여정 생성) (3.2)
    """
    serializer = TripCreateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    pins = list(Pin.objects.filter(user=request.user, segment__isnull=True).order_by("tagged_at"))
    if not pins:
        return Response(
            {"message": "종료할 여행이 없습니다.", "code": "CONFLICT"},
            status=status.HTTP_409_CONFLICT,
        )

    start_at = pins[0].tagged_at
    end_at = data.get("end_at") or pins[-1].tagged_at

    included_pins = [p for p in pins if p.tagged_at <= end_at]
    if not included_pins:
        return Response(
            {"message": "종료할 여행이 없습니다.", "code": "CONFLICT"},
            status=status.HTTP_409_CONFLICT,
        )

    name = data.get("name") or _default_trip_name(pins, start_at, end_at)

    with transaction.atomic():
        segment = TravelSegment.objects.create(
            user=request.user, name=name, start_at=start_at, end_at=end_at, status=True,
            dates_manually_set="end_at" in data and data["end_at"] is not None,
        )
        included_ids = {p.pin_id for p in included_pins}
        for pin in pins:
            pin.segment = segment
            pin.included_in_segment = pin.pin_id in included_ids
        Pin.objects.bulk_update(pins, ["segment", "included_in_segment"])

    request_logger.info(
        "POST /trips segment_id=%s user_id=%s pin_count=%s",
        segment.segment_id, request.user.user_id, len(included_pins),
    )

    return Response(
        {
            "segment_id": segment.segment_id,
            "user_id": request.user.user_id,
            "name": segment.name,
            "start_at": segment.start_at,
            "end_at": segment.end_at,
            "status": segment.status,
            "pin_count": len(included_pins),
            "photobook_id": None,
        },
        status=status.HTTP_201_CREATED,
    )