import logging

from django.db.models import Count
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication
from travel.models import Photo, Pin

from .models import Photobook
from .serializers import PhotobookUpdateRequestSerializer

request_logger = logging.getLogger("request_logger")

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


def _parse_pagination(request):
    """
    cursor/limit 쿼리 파라미터 파싱
    """
    limit_raw = request.query_params.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else DEFAULT_PAGE_LIMIT
    except ValueError:
        limit = DEFAULT_PAGE_LIMIT
    limit = max(1, min(limit, MAX_PAGE_LIMIT))

    cursor_raw = request.query_params.get("cursor")
    cursor_id = None
    if cursor_raw:
        try:
            cursor_id = int(cursor_raw)
        except ValueError:
            cursor_id = None
    return cursor_id, limit


def _cities_and_photo_count(segment):
    """세그먼트에 포함된(included_in_segment=True) 핀 기준으로 cities/photo_count 집계."""
    included_pins = Pin.objects.filter(segment=segment, included_in_segment=True)
    cities = []
    seen = set()
    for city in (
        included_pins.exclude(city__isnull=True).exclude(city="").order_by("tagged_at").values_list("city", flat=True)
    ):
        if city not in seen:
            seen.add(city)
            cities.append(city)
    photo_count = Photo.objects.filter(pin__in=included_pins).count()
    return cities, photo_count


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def photobook_list(request):
    """
    GET /photobooks — 포토북 목록 조회 (6.1).
    """
    cursor_id, limit = _parse_pagination(request)

    qs = Photobook.objects.filter(segment__user=request.user).select_related("segment").order_by("-photobook_id")
    if cursor_id is not None:
        qs = qs.filter(photobook_id__lt=cursor_id)

    photobooks = list(qs[: limit + 1])
    next_cursor = None
    if len(photobooks) > limit:
        next_cursor = str(photobooks[limit - 1].photobook_id)
        photobooks = photobooks[:limit]

    result = []
    for pb in photobooks:
        cities, photo_count = _cities_and_photo_count(pb.segment)
        result.append(
            {
                "photobook_id": pb.photobook_id,
                "segment_id": pb.segment_id,
                "name": pb.name,
                "start_at": pb.segment.start_at,
                "end_at": pb.segment.end_at,
                "cities": cities,
                "photo_count": photo_count,
                "cover_photo_url": pb.cover_photo_url,
            }
        )

    return Response({"photobooks": result, "next_cursor": next_cursor})


@api_view(["GET", "PATCH"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def photobook_detail(request, photobook_id):
    """
    GET /photobooks/{photobookId} — 포토북 상세 조회 (6.2)
    PATCH /photobooks/{photobookId} — 포토북 이름 수정 (6.3)
    """
    try:
        photobook = Photobook.objects.select_related("segment").get(pk=photobook_id, segment__user=request.user)
    except Photobook.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return _photobook_detail_get(photobook)
    return _photobook_detail_patch(request, photobook)


def _photobook_detail_get(photobook):
    """
    GET /photobooks/{photobookId} (6.2)
    """
    segment = photobook.segment
    cities, _ = _cities_and_photo_count(segment)

    total_days = None
    if segment.start_at and segment.end_at:
        total_days = (segment.end_at.date() - segment.start_at.date()).days + 1

    pins = (
        Pin.objects.filter(segment=segment, included_in_segment=True)
        .annotate(photo_count=Count("photos"))
        .order_by("tagged_at")
    )

    return Response(
        {
            "photobook_id": photobook.photobook_id,
            "segment_id": photobook.segment_id,
            "name": photobook.name,
            "start_at": segment.start_at,
            "end_at": segment.end_at,
            "total_days": total_days,
            "cities": cities,
            "cover_photo_url": photobook.cover_photo_url,
            "pins": [
                {
                    "pin_id": p.pin_id,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "place_name": p.place_name,
                    "photo_count": p.photo_count,
                }
                for p in pins
            ],
        }
    )


def _photobook_detail_patch(request, photobook):
    """
    PATCH /photobooks/{photobookId} (6.3). name만 수정 가능(여행 구간 이름과 독립).
    """
    serializer = PhotobookUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    photobook.name = serializer.validated_data["name"]
    photobook.save(update_fields=["name"])

    request_logger.info("PATCH /photobooks/%s name 변경", photobook.photobook_id)

    return Response({"photobook_id": photobook.photobook_id, "name": photobook.name})
