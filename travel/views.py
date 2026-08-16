import logging
from math import atan2, cos, radians, sin, sqrt


from django.core import signing
from django.db import transaction
from django.db.models import Count, F, Min
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication
from photobooks.models import Photobook
from photobooks.services import (
    build_photobook_pins,
    recompute_photo_layout_for_pin,
    recompute_photobook_city,
)
from products.models import NfcTag
from recommendations.travel_adapter import rank_pin_photos, refresh_pin_photos
from uploads.tokens import FileAlreadyConsumedError, FileNotUploadedError, resolve_and_consume

from .country_codes import resolve_country_code
from .models import CountryStamp, Photo, Pin, TravelSegment, VoiceMemo
from .serializers import (
    PhotoRegisterRequestSerializer,
    PinCreateRequestSerializer,
    PinUpdateRequestSerializer,
    TripCreateRequestSerializer,
    TripCurrentPatchRequestSerializer,
    TripPatchRequestSerializer,
)

request_logger = logging.getLogger("request_logger")

FILE_RESOLVE_EXCEPTIONS = (
    signing.BadSignature,
    FileNotUploadedError,
    FileAlreadyConsumedError,
    ValueError,
    PermissionError,
)
PHOTO_RADIUS_LIMIT_KM = 1.0
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
REPRESENTATIVE_PHOTO_MIN_COUNT = 4


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


def _voice_error_response(exc):
    if isinstance(exc, PermissionError):
        return Response(
            {"message": "본인이 업로드한 파일이 아닙니다.", "code": "PERMISSION_DENIED"},
            status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, signing.BadSignature):
        message = "유효하지 않거나 만료된 audio_file입니다."
    else:
        message = str(exc) or "음성 파일을 확인할 수 없습니다."
    return Response({"message": message, "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

def _distance_km(lat1, lng1, lat2, lng2):
    """두 좌표 사이 거리(km) — Haversine 공식"""
    lat1, lng1, lat2, lng2 = (radians(float(v)) for v in (lat1, lng1, lat2, lng2))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 6371.0 * 2 * atan2(sqrt(a), sqrt(1 - a))

@api_view(["GET", "POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_create(request):
    """
    GET /pins — 국가별 핀 목록 조회 (3.2, 국가 도장 탭 진입)
    POST /pins — 촬영 결과로 핀 생성 (8.2)
    """
    if request.method == "GET":
        return _pin_list_by_country(request)
    return _pin_create(request)


def _pin_list_by_country(request):
    """
    GET /pins?country_code={code} — 국가 도장을 탭했을 때 그 나라에 저장된 핀만 반환한다.
    여행 구간 배정 여부와 무관하게 전체를 대상으로 하고, 동선은 다루지 않는다(지도 렌더링은
    프론트 담당). country_code는 필수 — 값이 없으면 400.
    """
    country_code = request.query_params.get("country_code")
    if not country_code:
        return Response(
            {"message": "country_code는 필수입니다.", "code": "VALIDATION_ERROR"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cursor_id, limit = _parse_pagination(request)

    qs = (
        Pin.objects.filter(user=request.user, country_code=country_code)
        .annotate(photo_count=Count("photos"))
        .order_by("pin_id")
    )
    if cursor_id is not None:
        qs = qs.filter(pin_id__gt=cursor_id)

    pins = list(qs[: limit + 1])
    next_cursor = None
    if len(pins) > limit:
        next_cursor = str(pins[limit - 1].pin_id)
        pins = pins[:limit]

    return Response(
        {
            "pins": [
                {
                    "pin_id": p.pin_id,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "place_name": p.place_name,
                    "photo_count": p.photo_count,
                    "tagged_at": p.tagged_at,
                }
                for p in pins
            ],
            "next_cursor": next_cursor,
        }
    )


def _pin_create(request):
    """
    POST /pins — 촬영 결과로 핀 생성 (8.2)
    """
    serializer = PinCreateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    nfc_tag_id = data.get("nfc_tag_id")
    tag = None
    if nfc_tag_id:
        tag = NfcTag.objects.filter(pk=nfc_tag_id, user=request.user, unlinked_at__isnull=True).first()
        if tag is None:
            return Response(
                {"message": "등록되지 않은 태그입니다. 먼저 태그를 연결해주세요.", "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    country_name = data.get("country_name")
    # 프론트가 country_code(ISO 3166-1 alpha-2, 예: "KR")를 직접 보내면 그대로 신뢰해서
    # 쓰고, 안 보내면(구버전 클라이언트 등) 기존처럼 country_name 매핑 테이블로 폴백한다.
    # 2026-08-16 결정, docs/IMPLEMENTATION.md 참고.
    country_code = data.get("country_code") or resolve_country_code(country_name)

    try:
        with transaction.atomic():
            pin = Pin.objects.create(
                user=request.user,
                segment=None,
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                address=data.get("address"),
                city=data.get("city"),
                country_name=country_name,
                country_code=country_code,
                place_name=data.get("place_name", ""),
                tagged_at=timezone.now(),
                text_note=data.get("text_note"),
            )

            if tag is not None:
                tag.tag_count = F("tag_count") + 1
                tag.save(update_fields=["tag_count"])

            if country_code:
                CountryStamp.objects.get_or_create(
                    user=request.user, country_code=country_code, defaults={"country_name": country_name}
                )

            voice_memo = None
            audio_file = data.get("audio_file")
            if audio_file:
                relative_url = resolve_and_consume(audio_file, user=request.user, expected_file_type="voice")
                voice_memo = VoiceMemo.objects.create(
                    pin=pin, audio_url=request.build_absolute_uri(relative_url)
                )
    except FILE_RESOLVE_EXCEPTIONS as exc:

        return _voice_error_response(exc)

    request_logger.info("POST /pins pin_id=%s user_id=%s", pin.pin_id, request.user.user_id)

    return Response(
        {
            "pin_id": pin.pin_id,
            "segment_id": None,
            "latitude": pin.latitude,
            "longitude": pin.longitude,
            "address": pin.address,
            "place_name": pin.place_name,
            "tagged_at": pin.tagged_at,
            "text_note": pin.text_note,
            "voice_memo": {"voice_memo_id": voice_memo.voice_memo_id} if voice_memo else None,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def trip_current(request):
    """
    GET /trips/current — 진행 중인 여행 요약 조회 (3.1).
    PATCH /trips/current — 진행 중인 여행 이름 직접 수정 (신규).
    """
    if request.method == "PATCH":
        return _trip_current_patch(request)
    return Response(_trip_current_summary(request.user))


def _trip_current_summary(user):
    """3.1 GET과 PATCH 응답에서 공통으로 쓰는 집계 로직."""
    pins = Pin.objects.filter(user=user, segment__isnull=True)
    pin_count = pins.count()

    if pin_count == 0:
        return {
            "has_pins": False,
            "pin_count": 0,
            "photo_count": 0,
            "voice_memo_count": 0,
            "name": None,
            "started_at": None,
            "cities": [],
        }

    ordered_pins = list(pins.order_by("tagged_at"))
    photo_count = Photo.objects.filter(pin__in=pins).count()
    voice_memo_count = VoiceMemo.objects.filter(pin__in=pins).count()
    started_at = pins.aggregate(Min("tagged_at"))["tagged_at__min"]
    cities = sorted({c for c in pins.exclude(city__isnull=True).exclude(city="").values_list("city", flat=True)})
    # 진행 중인 여행이라 TravelSegment(및 저장된 name)가 아직 없음. 사용자가 PATCH로 직접 이름을
    # 지정한 적 있으면(current_trip_name_override) 그 값을 우선 쓰고, 없으면 3.2(POST /trips)와
    # 동일한 자동 이름 생성 로직으로 "지금 종료하면 이렇게 될 것"이라는 실시간 미리보기를 계산한다.
    # override가 없을 때의 자동 계산 값은 저장되지 않고 매 요청마다 다시 계산된다.
    name = user.current_trip_name_override or _default_trip_name(ordered_pins, started_at, timezone.now())

    return {
        "has_pins": True,
        "pin_count": pin_count,
        "photo_count": photo_count,
        "voice_memo_count": voice_memo_count,
        "name": name,
        "started_at": started_at,
        "cities": cities,
    }


def _trip_current_patch(request):
    """
    PATCH /trips/current (신규) — 진행 중인 여행 이름 직접 수정.
    빈 문자열("")은 자동 생성 이름으로 되돌리는 요청으로 취급한다.
    """
    serializer = TripCurrentPatchRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    name = serializer.validated_data["name"]

    has_pins = Pin.objects.filter(user=request.user, segment__isnull=True).exists()
    if not has_pins:
        return Response(
            {"message": "수정할 여행이 없습니다.", "code": "CONFLICT"},
            status=status.HTTP_409_CONFLICT,
        )

    request.user.current_trip_name_override = name or None
    request.user.save(update_fields=["current_trip_name_override"])

    return Response(_trip_current_summary(request.user))


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


@api_view(["GET", "POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def trip_list_or_create(request):
    """
    GET /trips — 여행 구간 목록 (4.1)
    POST /trips — 여행 종료(여정 생성) (3.2)
    """
    if request.method == "GET":
        return _trip_list(request)
    return _trip_create(request)


def _countries_with_cities(segment):
    """
    여행 구간에 포함된(included_in_segment=True) 핀 기준으로 국가별 도시 목록을 tagged_at
    순으로 집계한다. 국가 안에 도시가 중첩된 구조 — 어느 도시가 어느 국가 소속인지 프론트가
    바로 알 수 있게 하기 위함(2026-08-15 사용자 확인, 평평한 배열 2개 대신 이 구조로 결정).

    country_name이 없는 핀(이 필드 추가 전에 만들어진 핀 등)은 국가를 알 수 없어 집계에서
    완전히 빠진다 — city만 있고 country_name이 없으면 그 city도 어디에도 안 나타난다.
    docs/IMPLEMENTATION.md 참고.
    """
    included_pins = Pin.objects.filter(segment=segment, included_in_segment=True).order_by("tagged_at")

    countries = []
    by_country = {}
    for country_name, city in (
        included_pins.exclude(country_name__isnull=True).exclude(country_name="")
        .values_list("country_name", "city")
    ):
        entry = by_country.get(country_name)
        if entry is None:
            entry = {"country_name": country_name, "cities": [], "_seen": set()}
            by_country[country_name] = entry
            countries.append(entry)
        if city and city not in entry["_seen"]:
            entry["_seen"].add(city)
            entry["cities"].append(city)

    for entry in countries:
        del entry["_seen"]
    return countries


def _trip_list(request):
    """GET /trips (4.1). segment_id 내림차순 커서 페이지네이션"""
    cursor_id, limit = _parse_pagination(request)

    qs = TravelSegment.objects.filter(user=request.user).order_by("-segment_id")
    if cursor_id is not None:
        qs = qs.filter(segment_id__lt=cursor_id)

    segments = list(qs[: limit + 1])
    next_cursor = None
    if len(segments) > limit:
        next_cursor = str(segments[limit - 1].segment_id)
        segments = segments[:limit]

    trips = []
    for s in segments:
        trips.append(
            {
                "segment_id": s.segment_id,
                "name": s.name,
                "start_at": s.start_at,
                "end_at": s.end_at,
                "countries": _countries_with_cities(s),
            }
        )

    return Response({"trips": trips, "next_cursor": next_cursor})


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

    # 이름 우선순위: 종료 시점에 직접 입력 > 진행 중에 PATCH /trips/current로 지정한 이름 >
    # 자동 생성. (2026-08-16 결정, docs/IMPLEMENTATION.md 참고)
    name = data.get("name") or request.user.current_trip_name_override or _default_trip_name(
        pins, start_at, end_at
    )

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

        if request.user.current_trip_name_override:
            # 이번 여행에서 소비했으니 다음 진행 중 여행을 위해 리셋한다.
            request.user.current_trip_name_override = None
            request.user.save(update_fields=["current_trip_name_override"])

        # 2026-08-15: 포토북은 여행 종료 시점에 자동 생성(6번). cover_photo_url은 취향
        # 프로파일 스코어링(5.6/6.4와 동일 로직)이 붙기 전까지 null로 둔다.
        photobook = Photobook.objects.create(segment=segment, name=segment.name)
        # 도시별 핀 선정(PhotobookPin) + 핀별 사진 선정(PhotobookPhotoLayout) 확정.
        # 이후엔 여기서 만든 선정 결과가 고정되고, 5.5에서 사진이 추가될 때만 해당 핀의
        # 사진 선정을 재계산한다(recompute_photo_layout_for_pin). docs/IMPLEMENTATION.md 참고.
        build_photobook_pins(photobook)

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
            "photobook_id": photobook.photobook_id,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def trip_detail(request, segment_id):
    """
    GET/PATCH/DELETE /trips/{segmentId} — 여행 구간 상세/수정/삭제 (4.2~4.4)
    """
    try:
        segment = TravelSegment.objects.get(pk=segment_id, user=request.user)
    except TravelSegment.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return _trip_detail_get(segment)
    if request.method == "PATCH":
        return _trip_detail_patch(request, segment)
    return _trip_detail_delete(segment)


def _trip_detail_get(segment):
    """
    GET /trips/{segmentId} (4.2)
    """
    included = Pin.objects.filter(segment=segment, included_in_segment=True)
    pin_count = included.count()
    photo_count = Photo.objects.filter(pin__in=included).count()
    voice_memo_count = VoiceMemo.objects.filter(pin__in=included).count()

    return Response(
        {
            "segment_id": segment.segment_id,
            "user_id": segment.user_id,
            "name": segment.name,
            "start_at": segment.start_at,
            "end_at": segment.end_at,
            "status": segment.status,
            "pin_count": pin_count,
            "photo_count": photo_count,
            "voice_memo_count": voice_memo_count,
        }
    )


def _trip_detail_patch(request, segment):
    """
    PATCH /trips/{segmentId} (4.3)
    이름 수정, 시작/종료일 직접 수정, 및/또는 핀 제외·재포함
    """
    serializer = TripPatchRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    exclusions = data.get("pin_exclusions") or []
    pin_ids = [item["pin_id"] for item in exclusions]

    pins_by_id = {}
    if pin_ids:
        pins_qs = Pin.objects.filter(pin_id__in=pin_ids, segment=segment, user=request.user)
        pins_by_id = {p.pin_id: p for p in pins_qs}
        missing = [pid for pid in pin_ids if pid not in pins_by_id]
        if missing:
            return Response(
                {
                    "message": f"이 여행에 속하지 않은 핀입니다: {missing}",
                    "code": "VALIDATION_ERROR",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    dates_given = "start_at" in data or "end_at" in data
    if dates_given:
        new_start = data.get("start_at") or segment.start_at
        new_end = data.get("end_at") or segment.end_at
        if new_start and new_end and new_start > new_end:
            return Response(
                {"message": "start_at은 end_at보다 늦을 수 없습니다.", "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    with transaction.atomic():
        if data.get("name"):
            segment.name = data["name"]

        if dates_given:
            segment_pins = list(Pin.objects.filter(segment=segment))
            for pin in segment_pins:
                pin.included_in_segment = new_start <= pin.tagged_at <= new_end
            Pin.objects.bulk_update(segment_pins, ["included_in_segment"])

            segment.start_at = new_start
            segment.end_at = new_end
            segment.dates_manually_set = True

        if exclusions:
            pins_to_update = []
            for item in exclusions:
                pin = pins_by_id[item["pin_id"]]
                pin.included_in_segment = item["included_in_segment"]
                pins_to_update.append(pin)
            Pin.objects.bulk_update(pins_to_update, ["included_in_segment"])

        included = list(Pin.objects.filter(segment=segment, included_in_segment=True).order_by("tagged_at"))
        if not included:
            transaction.set_rollback(True)
            return Response(
                {"message": "포함된 핀이 없어 저장할 수 없습니다.", "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not dates_given and not segment.dates_manually_set and exclusions:
            segment.start_at = included[0].tagged_at
            segment.end_at = included[-1].tagged_at

        segment.save(update_fields=["name", "start_at", "end_at", "dates_manually_set"])

    photo_count = Photo.objects.filter(pin__in=included).count()

    if exclusions:
        affected_cities = {pin.city for pin in pins_to_update if pin.city}
        try:
            photobook = segment.photobook
        except Photobook.DoesNotExist:
            photobook = None
        if photobook is not None:
            for city in affected_cities:
                recompute_photobook_city(photobook, city)
        request_logger.info(
            "PATCH /trips/%s pin_exclusions 반영 — 영향받은 도시 %s 포토북 재계산",
            segment.segment_id, sorted(affected_cities),
        )

    return Response(
        {
            "segment_id": segment.segment_id,
            "name": segment.name,
            "start_at": segment.start_at,
            "end_at": segment.end_at,
            "pin_count": len(included),
            "photo_count": photo_count,
        }
    )


def _trip_detail_delete(segment):
    """DELETE /trips/{segmentId} (4.4)
    cascade로 핀/사진/음성메모까지 삭제
    """
    segment_id = segment.segment_id
    user = segment.user
    country_codes = list(
        Pin.objects.filter(segment=segment)
        .exclude(country_code__isnull=True)
        .values_list("country_code", flat=True)
        .distinct()
    )
    segment.delete()
    _cleanup_orphaned_country_stamps(user, country_codes)
    request_logger.info(
        "DELETE /trips/%s — cascade 삭제(핀/사진/음성메모)", segment_id
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def trip_pins(request, segment_id):
    """
    GET /trips/{segmentId}/pins — 구간 내 핀 목록 (4.5)
    """
    try:
        TravelSegment.objects.get(pk=segment_id, user=request.user)
    except TravelSegment.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    cursor_id, limit = _parse_pagination(request)

    qs = (
        Pin.objects.filter(segment_id=segment_id, user=request.user)
        .annotate(photo_count=Count("photos"))
        .order_by("pin_id")
    )
    if cursor_id is not None:
        qs = qs.filter(pin_id__gt=cursor_id)

    pins = list(qs[: limit + 1])
    next_cursor = None
    if len(pins) > limit:
        next_cursor = str(pins[limit - 1].pin_id)
        pins = pins[:limit]

    return Response(
        {
            "pins": [
                {
                    "pin_id": p.pin_id,
                    "place_name": p.place_name,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "photo_count": p.photo_count,
                    "tagged_at": p.tagged_at,
                    "included_in_segment": p.included_in_segment,
                }
                for p in pins
            ],
            "next_cursor": next_cursor,
        }
    )

@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_detail(request, pin_id):
    """
    GET/PATCH/DELETE /pins/{pinId} — 핀 상세/수정/삭제 (5.1~5.3)
    """
    try:
        pin = Pin.objects.get(pk=pin_id, user=request.user)
    except Pin.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return _pin_detail_get(pin)
    if request.method == "PATCH":
        return _pin_detail_patch(request, pin)
    return _pin_detail_delete(pin)


def _pin_detail_get(pin):
    """
    GET /pins/{pinId} (5.1)
    """
    voice_memo = getattr(pin, "voicememo", None)
    representative_photos = Photo.objects.filter(
        pin=pin, taste_rank__isnull=False, taste_rank__lte=3
    ).order_by("taste_rank")

    return Response(
        {
            "pin_id": pin.pin_id,
            "segment_id": pin.segment_id,
            "latitude": pin.latitude,
            "longitude": pin.longitude,
            "address": pin.address,
            "place_name": pin.place_name,
            "tagged_at": pin.tagged_at,
            "text_note": pin.text_note,
            "voice_memo": (
                {"voice_memo_id": voice_memo.voice_memo_id, "duration_sec": voice_memo.duration_sec}
                if voice_memo
                else None
            ),
            "representative_photos": [
                {"photo_id": p.photo_id, "url": p.photo_url} for p in representative_photos
            ],
        }
    )


def _pin_detail_patch(request, pin):
    """
    PATCH /pins/{pinId} (5.2). place_name/text_note만 수정 가능
    """
    serializer = PinUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    update_fields = []
    if "place_name" in data:
        pin.place_name = data["place_name"]
        update_fields.append("place_name")
    if "text_note" in data:
        pin.text_note = data["text_note"]
        update_fields.append("text_note")

    if update_fields:
        pin.save(update_fields=update_fields)

    return Response({"pin_id": pin.pin_id, "place_name": pin.place_name, "text_note": pin.text_note})


def _cleanup_orphaned_country_stamps(user, country_codes):
    """핀 삭제(개별 삭제 또는 여행 구간 삭제) 이후, 그 국가에 남은 핀이 하나도 없으면
    도장도 함께 제거한다 (스펙 3.2: "국가의 마지막 핀이 삭제되면 해당 국가의 도장도 함께
    제거한다"). country_codes는 삭제 *이전*에 미리 뽑아둔 값을 받는다 — cascade 삭제 후에는
    그 핀들을 더 이상 조회할 수 없기 때문이다."""
    for country_code in set(country_codes):
        if not country_code:
            continue
        still_has_pins = Pin.objects.filter(user=user, country_code=country_code).exists()
        if not still_has_pins:
            CountryStamp.objects.filter(user=user, country_code=country_code).delete()


def _pin_detail_delete(pin):
    """DELETE /pins/{pinId} (5.3). 진행 중(segment_id NULL)인 핀만 삭제 가능."""
    if pin.segment_id is not None:
        return Response(
            {"message": "이미 여행에 배정된 핀입니다. 여행 구간 편집에서 제외해주세요.", "code": "CONFLICT"},
            status=status.HTTP_409_CONFLICT,
        )

    pin_id = pin.pin_id
    user = pin.user
    country_code = pin.country_code
    pin.delete()
    _cleanup_orphaned_country_stamps(user, [country_code])
    request_logger.info("DELETE /pins/%s", pin_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_photos(request, pin_id):
    """GET /pins/{pinId}/photos(5.4, 목록) · POST /pins/{pinId}/photos(5.5, 등록).

    같은 경로에 메서드만 다른 두 엔드포인트라 하나의 dispatcher로 묶는다.
    """
    try:
        pin = Pin.objects.get(pk=pin_id, user=request.user)
    except Pin.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        return _pin_photos_list(request, pin)
    return _pin_photos_register(request, pin)


def _pin_photos_list(request, pin):
    """
    GET /pins/{pinId}/photos — 핀 사진 목록 조회 (5.4). 촬영 시각(captured_at) 순 정렬.
    """
    cursor_id, limit = _parse_pagination(request)

    qs = Photo.objects.filter(pin=pin).order_by("captured_at", "photo_id")
    if cursor_id is not None:
        qs = qs.filter(photo_id__gt=cursor_id)

    photos = list(qs[: limit + 1])
    next_cursor = None
    if len(photos) > limit:
        next_cursor = str(photos[limit - 1].photo_id)
        photos = photos[:limit]

    return Response(
        {
            "photos": [
                {
                    "photo_id": p.photo_id,
                    "captured_at": p.captured_at,
                    # 명세서(5.4) 응답 필드명 그대로 file_path 사용 — 내부 모델 필드명은 photo_url.
                    "file_path": p.photo_url,
                    "is_pin_cover": p.taste_rank is not None and p.taste_rank <= 3,
                }
                for p in photos
            ],
            "next_cursor": next_cursor,
        }
    )


def _pin_photos_register(request, pin):
    """
    POST /pins/{pinId}/photos — 사진 등록 (5.5)
    """
    pin_id = pin.pin_id
    is_finished_trip_pin = pin.segment_id is not None and pin.included_in_segment
    # 5.2.1 최초 추천은 이 핀에 한 번도 스코어링된 적 없을 때만 실행한다(taste_rank가 채워진
    # 사진이 하나도 없으면 "아직 최초 스코어링 전"으로 간주). 이미 스코어링된 핀에 사진이
    # 나중에 더 등록되는 경우엔 자동 재계산하지 않는다 — 5.6(새로고침)에서만 갱신.
    already_scored = Photo.objects.filter(pin=pin, taste_rank__isnull=False).exists()

    serializer = PhotoRegisterRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    photos_data = serializer.validated_data["photos"]

    added = []
    rejected = []
    for item in photos_data:
        file_id = item["file_id"]
        latitude = item.get("latitude")
        longitude = item.get("longitude")

        if latitude is None or longitude is None:
            rejected.append({"file_id": file_id, "reason": "MISSING_COORDINATES"})
            continue

        if pin.latitude is not None and pin.longitude is not None:
            distance = _distance_km(pin.latitude, pin.longitude, latitude, longitude)
            if distance > PHOTO_RADIUS_LIMIT_KM:
                rejected.append({"file_id": file_id, "reason": "OUT_OF_RADIUS"})
                continue

        try:
            relative_url = resolve_and_consume(file_id, user=request.user, expected_file_type="photo")
        except FILE_RESOLVE_EXCEPTIONS:
            rejected.append({"file_id": file_id, "reason": "INVALID_FILE"})
            continue

        photo = Photo.objects.create(
            pin=pin,
            captured_at=item["captured_at"],
            latitude=latitude,
            longitude=longitude,
            source_type="uploaded",
            photo_url=request.build_absolute_uri(relative_url),
        )
        added.append({"photo_id": photo.photo_id, "file_id": file_id})

    if added and not already_scored:
        # 5.2.1 최초 추천 — 이 핀이 처음 스코어링되는 시점. 온보딩 미완료(취향 축 없음)
        # 유저는 rank_pin_photos 내부에서 이미 no-op 처리된다.
        rank_pin_photos(pin)

    if added and is_finished_trip_pin:
        # 종료된 여정(포토북 이미 생성됨)의 핀에 사진이 새로 추가된 경우 — 그 핀의 포토북
        # 사진 선정(PhotobookPhotoLayout)만 재계산한다. 핀 자체 대표사진(taste_rank)이나
        # 포토북의 핀 선정(PhotobookPin) 자체는 건드리지 않는다.
        recompute_photo_layout_for_pin(pin)

    request_logger.info(
        "POST /pins/%s/photos added=%s rejected=%s", pin_id, len(added), len(rejected)
    )

    return Response({"added": added, "rejected": rejected})


@api_view(["POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_photos_refresh(request, pin_id):
    """
    POST /pins/{pinId}/representative-photos/refresh — 대표사진 새로고침 (5.6)
    """
    try:
        pin = Pin.objects.get(pk=pin_id, user=request.user)
    except Pin.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    photo_count = Photo.objects.filter(pin=pin).count()
    if photo_count < REPRESENTATIVE_PHOTO_MIN_COUNT:
        return Response(
            {
                "message": f"대표사진 새로고침은 사진이 {REPRESENTATIVE_PHOTO_MIN_COUNT}장 이상일 때만 가능합니다.",
                "code": "CONFLICT",
            },
            status=status.HTTP_409_CONFLICT,
        )

    refresh_pin_photos(pin)

    representative_photos = Photo.objects.filter(
        pin=pin, taste_rank__isnull=False, taste_rank__lte=3
    ).order_by("taste_rank")

    request_logger.info("POST /pins/%s/representative-photos/refresh", pin_id)

    return Response(
        {
            "representative_photos": [
                {"photo_id": p.photo_id, "url": p.photo_url} for p in representative_photos
            ]
        }
    )


@api_view(["DELETE"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def photo_delete(request, photo_id):
    """
    DELETE /photos/{photoId} — 사진 삭제 (5.7)
    """
    try:
        photo = Photo.objects.select_related("pin").get(pk=photo_id, pin__user=request.user)
    except Photo.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    pin = photo.pin
    photo.delete()
    # taste_rank<=3인 대표사진이 삭제돼도 별도 "대체" 처리가 필요 없다 — 대표사진 목록은
    # 매번 taste_rank 순으로 다시 계산되는 값이라, 순위에 빈 자리가 생겨도 자동으로
    # 다음 순위 사진이 상위 3장 안에 들어온다.

    request_logger.info("DELETE /photos/%s pin_id=%s", photo_id, pin.pin_id)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_voice_memos(request, pin_id):
    """
    GET /pins/{pinId}/voice-memos — 음성 메모 조회 (5.8)
    """
    try:
        pin = Pin.objects.get(pk=pin_id, user=request.user)
    except Pin.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    voice_memo = getattr(pin, "voicememo", None)
    return Response(
        {
            "voice_memo": (
                {
                    "voice_memo_id": voice_memo.voice_memo_id,
                    "audio_file": voice_memo.audio_url,
                    "saved_at": voice_memo.saved_at,
                }
                if voice_memo
                else None
            )
        }
    )

@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def country_stamps(request):
    """
    GET /users/me/country-stamps — 국가별 방문 도장 목록 (3.3)

    도장마다 핀 수와 방문 도시(핀 수 많은 순 최대 3개, 나머지는 extra_city_count로 뭉침)를
    함께 내려준다 — 2026-08-16 추가, docs/IMPLEMENTATION.md 참고.
    """
    stamps = CountryStamp.objects.filter(user=request.user).order_by("id")

    result = []
    for stamp in stamps:
        pins = Pin.objects.filter(user=request.user, country_code=stamp.country_code)

        city_counts = {}
        for city in pins.exclude(city__isnull=True).exclude(city="").values_list("city", flat=True):
            city_counts[city] = city_counts.get(city, 0) + 1
        ranked_cities = sorted(city_counts.items(), key=lambda item: item[1], reverse=True)

        result.append(
            {
                "country_code": stamp.country_code,
                "country_name": stamp.country_name,
                "pin_count": pins.count(),
                "cities": [city for city, _ in ranked_cities[:3]],
                "extra_city_count": max(0, len(ranked_cities) - 3),
            }
        )

    return Response({"stamps": result})