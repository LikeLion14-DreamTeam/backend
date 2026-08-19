import logging

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication
from travel.models import Photo, Pin, VoiceMemo

from .models import Photobook, PhotobookPin
from .serializers import PhotobookUpdateRequestSerializer
from .services import refresh_cover_photo

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
    """세그먼트에 포함된(included_in_segment=True) 핀 기준으로 cities/photo_count 집계"""
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
    GET /photobooks — 포토북 목록 조회 (6.1)
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


def _serialize_photobook_pin(photobook_pin):
    """
    포토북 상세(6.2) 도시 카드 안의 핀 하나 — place_name/시간/기록/사진(최대 4장)/음성메모.
    사진은 PhotobookPhotoLayout 순서대로(1등 = 큰 사진).
    """
    pin = photobook_pin.pin
    voice_memo = getattr(pin, "voicememo", None)
    photo_layouts = sorted(photobook_pin.photo_layouts.all(), key=lambda layout: layout.order)

    return {
        "pin_id": pin.pin_id,
        "order": photobook_pin.order,
        "place_name": pin.place_name,
        "tagged_at": pin.tagged_at,
        "latitude": pin.latitude,
        "longitude": pin.longitude,
        "text_note": pin.text_note,
        "photos": [
            {"photo_id": layout.photo.photo_id, "photo_url": layout.photo.photo_url, "order": layout.order}
            for layout in photo_layouts
        ],
        "voice_memo": (
            {"audio_url": voice_memo.audio_url, "duration_sec": voice_memo.duration_sec}
            if voice_memo
            else None
        ),
    }


def _photobook_detail_get(photobook):
    """
    GET /photobooks/{photobookId} (6.2). 도시별 카드 구조 — 각 카드 안엔 포토북 생성 시점에
    확정된 핀 선정(PhotobookPin) + 핀별 사진 선정(PhotobookPhotoLayout) 결과를 그대로 보여줌
    + 지도/동선 렌더링에 쓰이도록 각 핀에 좌표도 포함
    + 도시 카드마다 국가명(country_name)도 함께 내려줌(2026-08-19 추가) — 같은 도시로 묶인
    핀들의 국가가 다를 수 있다는 가정은 하지 않고, 그룹의 첫 핀 값을 그대로 씀.
    """
    segment = photobook.segment

    included_pins = Pin.objects.filter(segment=segment, included_in_segment=True)
    pin_count = included_pins.count()
    photo_count = Photo.objects.filter(pin__in=included_pins).count()
    voice_memo_count = VoiceMemo.objects.filter(pin__in=included_pins).count()

    total_days = None
    if segment.start_at and segment.end_at:
        total_days = (segment.end_at.date() - segment.start_at.date()).days + 1

    photobook_pins = (
        PhotobookPin.objects.filter(photobook=photobook)
        .select_related("pin", "pin__voicememo")
        .prefetch_related("photo_layouts__photo")
        .order_by("photobook_pin_id")
    )

    # 포토북 생성 시 도시를 방문 순서대로 채운 것과 동일한 순서로 도시 카드가 나열되도록 설정
    cities = {}
    for pp in photobook_pins:
        city = pp.pin.city or ""
        cities.setdefault(city, []).append(pp)

    city_results = []
    for city, pps in cities.items():
        tagged_ats = [pp.pin.tagged_at for pp in pps]
        city_results.append(
            {
                "city": city,
                "country_name": pps[0].pin.country_name,
                "start_at": min(tagged_ats),
                "end_at": max(tagged_ats),
                "pin_count": len(pps),
                "pins": [_serialize_photobook_pin(pp) for pp in pps],
            }
        )

    return Response(
        {
            "photobook_id": photobook.photobook_id,
            "segment_id": photobook.segment_id,
            "name": photobook.name,
            "start_at": segment.start_at,
            "end_at": segment.end_at,
            "total_days": total_days,
            "pin_count": pin_count,
            "photo_count": photo_count,
            "voice_memo_count": voice_memo_count,
            "cover_photo_url": photobook.cover_photo_url,
            "cities": city_results,
        }
    )


@api_view(["POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def photobook_cover_refresh(request, photobook_id):
    """
    POST /photobooks/{photobookId}/cover/refresh — 포토북 커버 사진 새로고침 (6.4)
    """
    try:
        photobook = Photobook.objects.get(pk=photobook_id, segment__user=request.user)
    except Photobook.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    refresh_cover_photo(photobook)

    request_logger.info("POST /photobooks/%s/cover/refresh", photobook_id)

    return Response({"cover_photo_url": photobook.cover_photo_url})


def _photobook_detail_patch(request, photobook):
    """
    PATCH /photobooks/{photobookId} (6.3)
    name 수정 — 여행 구간 이름과 하나로 동기화한다. (2026-08-17 결정: 이전엔 독립
    관리였으나, 어느 쪽에서 이름을 바꾸든 나머지 한쪽도 같이 바뀌도록 통일했다.
    docs/IMPLEMENTATION.md 참고.)
    """
    serializer = PhotobookUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    name = serializer.validated_data["name"]

    photobook.name = name
    photobook.save(update_fields=["name"])

    photobook.segment.name = name
    photobook.segment.save(update_fields=["name"])

    request_logger.info("PATCH /photobooks/%s name 변경(여행 구간 이름도 동기화)", photobook.photobook_id)

    return Response({"photobook_id": photobook.photobook_id, "name": photobook.name})
