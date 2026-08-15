import logging

from django.core import signing
from django.db import transaction
from django.db.models import Count, F, Min
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication
from products.models import NfcTag
from uploads.tokens import FileAlreadyConsumedError, FileNotUploadedError, resolve_and_consume

from .country_codes import resolve_country_code
from .models import CountryStamp, Photo, Pin, TravelSegment, VoiceMemo
from .serializers import (
    PinCreateRequestSerializer,
    PinUpdateRequestSerializer,
    TripCreateRequestSerializer,
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


@api_view(["POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_create(request):
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

    try:
        with transaction.atomic():
            pin = Pin.objects.create(
                user=request.user,
                segment=None,
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                address=data.get("address"),
                city=data.get("city"),
                place_name=data.get("place_name", ""),
                tagged_at=timezone.now(),
                text_note=data.get("text_note"),
            )

            if tag is not None:
                tag.tag_count = F("tag_count") + 1
                tag.save(update_fields=["tag_count"])

            country_name = data.get("country_name")
            country_code = resolve_country_code(country_name)
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

    return Response(
        {
            "trips": [
                {
                    "segment_id": s.segment_id,
                    "name": s.name,
                    "start_at": s.start_at,
                    "end_at": s.end_at,
                }
                for s in segments
            ],
            "next_cursor": next_cursor,
        }
    )


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
        request_logger.info(
            "PATCH /trips/%s pin_exclusions 반영 — 포토북 재생성은 스킵(photobooks 앱 없음)",
            segment.segment_id,
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
    segment.delete()
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
    representative_photos = Photo.objects.filter(pin=pin, is_main=True).order_by("photo_id")

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


def _pin_detail_delete(pin):
    """DELETE /pins/{pinId} (5.3). 진행 중(segment_id NULL)인 핀만 삭제 가능."""
    if pin.segment_id is not None:
        return Response(
            {"message": "이미 여행에 배정된 핀입니다. 여행 구간 편집에서 제외해주세요.", "code": "CONFLICT"},
            status=status.HTTP_409_CONFLICT,
        )

    pin_id = pin.pin_id
    pin.delete()
    request_logger.info("DELETE /pins/%s", pin_id)
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def pin_photos(request, pin_id):
    """GET /pins/{pinId}/photos — 핀 전체 사진 조회 (5.4)."""
    try:
        pin = Pin.objects.get(pk=pin_id, user=request.user)
    except Pin.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    return _pin_photos_list(request, pin)


def _pin_photos_list(request, pin):
    """GET /pins/{pinId}/photos (5.4). photo_id 오름차순(촬영 순서 프록시) 커서 페이지네이션."""
    cursor_id, limit = _parse_pagination(request)

    qs = Photo.objects.filter(pin=pin).order_by("photo_id")
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
                    "file_path": p.photo_url,
                    "is_pin_cover": p.is_main,
                }
                for p in photos
            ],
            "next_cursor": next_cursor,
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
    was_main = photo.is_main
    photo.delete()

    if was_main:
        replacement = Photo.objects.filter(pin=pin, is_main=False).order_by("?").first()
        if replacement is not None:
            replacement.is_main = True
            replacement.save(update_fields=["is_main"])

    request_logger.info("DELETE /photos/%s pin_id=%s was_main=%s", photo_id, pin.pin_id, was_main)
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