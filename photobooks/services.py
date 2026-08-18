"""
photobooks/services.py — 포토북 생성/갱신 시 도시별 핀 선정, 핀별 사진 선정 로직.
"""
import random

from django.db.models import F

from travel.models import Photo, Pin

from .models import PhotobookPhotoLayout, PhotobookPin

PINS_PER_CITY = 3
PHOTOS_PER_PIN = 4


def _select_pins_for_city(pins):
    """
    한 도시 안에서 포토북에 보여줄 핀을 우선순위로 선정함
    1순위: 음성메모+텍스트 둘 다 있는 핀
    2순위: 음성메모 또는 텍스트 중 하나라도 있는 핀
    3순위: 둘 다 없는 핀 — 랜덤
    핀이 PINS_PER_CITY(3)개 이하면 전부 포함(우선순위 계산 불필요)
    """
    pins = list(pins)
    if len(pins) <= PINS_PER_CITY:
        return pins

    tier1, tier2, tier3 = [], [], []
    for pin in pins:
        has_voice = getattr(pin, "voicememo", None) is not None
        has_text = bool(pin.text_note)
        if has_voice and has_text:
            tier1.append(pin)
        elif has_voice or has_text:
            tier2.append(pin)
        else:
            tier3.append(pin)

    random.shuffle(tier3)

    selected = []
    for tier in (tier1, tier2, tier3):
        for pin in tier:
            if len(selected) >= PINS_PER_CITY:
                break
            selected.append(pin)
        if len(selected) >= PINS_PER_CITY:
            break

    return selected


def _select_photos_for_pin(pin):
    """
    포토북 속 핀 카드에 보여줄 사진(최대 PHOTOS_PER_PIN장, 1등은 큰 사진)을 고름
    사진이 PHOTOS_PER_PIN장이 안 되면 있는 만큼만 반환

    Photo.taste_rank(취향 프로파일 기준 순위) 순으로 정렬한다 — 새로 스코어링하지 않고
    이미 계산돼 있는 값을 그대로 재사용(recommendations 앱 호출 없음). taste_rank가 아직
    없는 사진(온보딩 미완료 유저, 5.5 최초 스코어링 전)은 뒤로 밀리고 그 안에서
    captured_at 순으로 대체된다.
    """
    return list(
        Photo.objects.filter(pin=pin)
        .order_by(F("taste_rank").asc(nulls_last=True), "captured_at", "photo_id")[:PHOTOS_PER_PIN]
    )


def _write_photo_layout(photobook_pin, pin):
    photos = _select_photos_for_pin(pin)
    PhotobookPhotoLayout.objects.bulk_create(
        [
            PhotobookPhotoLayout(photobook_pin=photobook_pin, photo=photo, order=i + 1)
            for i, photo in enumerate(photos)
        ]
    )


def build_photobook_pins(photobook):
    """
    포토북 생성 시점에 한 번 호출 — 도시별로 핀을 선정해 PhotobookPin/PhotobookPhotoLayout을 채움
    도시 순서는 그 도시에 속한 핀 중 가장 이른 tagged_at 기준
    """
    segment = photobook.segment
    pins = (
        Pin.objects.filter(segment=segment, included_in_segment=True)
        .select_related("voicememo")
        .order_by("tagged_at")
    )

    cities = {}
    for pin in pins:
        if not pin.city:
            continue
        cities.setdefault(pin.city, []).append(pin)

    for city_pins in cities.values():
        order = 0
        selected_pins = sorted(_select_pins_for_city(city_pins), key=lambda p: p.tagged_at)
        for pin in selected_pins:
            order += 1
            photobook_pin = PhotobookPin.objects.create(photobook=photobook, pin=pin, order=order)
            _write_photo_layout(photobook_pin, pin)


def recompute_photobook_city(photobook, city):
    """
    4.3(PATCH /trips/{segmentId} pin_exclusions)으로 핀 제외/재포함이 일어나면 그 도시의
    포토북 수록 핀 구성이 바뀔 수 있다. build_photobook_pins와 같은 선정 로직
    (_select_pins_for_city)을 그 도시 범위로만 다시 돌려 PhotobookPin/PhotobookPhotoLayout을
    갱신한다. 제외된 핀이 애초에 선정되지 않았던 핀이면 결과가 그대로 유지되고, 선정돼
    있었으면 다른 후보로 자동 교체된다 — 별도 "선정 여부 확인" 분기가 필요 없다.
    """
    segment = photobook.segment
    pins = (
        Pin.objects.filter(segment=segment, included_in_segment=True, city=city)
        .select_related("voicememo")
        .order_by("tagged_at")
    )

    PhotobookPin.objects.filter(photobook=photobook, pin__city=city).delete()

    order = 0
    selected_pins = sorted(_select_pins_for_city(pins), key=lambda p: p.tagged_at)
    for pin in selected_pins:
        order += 1
        photobook_pin = PhotobookPin.objects.create(photobook=photobook, pin=pin, order=order)
        _write_photo_layout(photobook_pin, pin)


def recompute_photo_layout_for_pin(pin):
    """
    종료된 여정의 핀에 사진이 나중에 추가됐을 때 호출
    """
    photobook_pin = PhotobookPin.objects.filter(pin=pin).first()
    if photobook_pin is None:
        return
    PhotobookPhotoLayout.objects.filter(photobook_pin=photobook_pin).delete()
    _write_photo_layout(photobook_pin, pin)


def refresh_cover_photo(photobook):
    """
    여정 커버 사진 새로고침 (6.4, Photobook.cover_photo_url을 여정 커버로 사용 — "포토북
    커버"라는 별도 개념은 없다). 여정에 포함된(included_in_segment=True) 핀 전체 중에서
    대표사진(taste_rank<=3)이 있는 핀을 무작위로 하나 고르고, 그 핀의 대표사진 중에서
    다시 무작위로 1장을 뽑아 커버로 저장한다.

    도시별로 큐레이션된 포토북 수록 핀(PhotobookPin)으로 후보를 제한하지 않고 여정 전체
    핀을 후보로 삼는다 — 도시당 3핀 제한 때문에 포토북에 안 뽑힌 핀도 커버 후보가 될 수
    있어야 한다는 2026-08-16 결정. taste_rank는 5.2.1/5.6에서 이미 계산돼 있는 값을 그대로
    재사용하고 새로 스코어링하지 않는다 — 명세서 원문의 "취향 프로파일 기준 재정렬 → 상위
    10개 → 무작위 1개"는 매 새로고침마다 여정 전체를 재스코어링하는 비용이 커서 채택하지
    않았다 (docs/spec.md 정정 기록 참고). 대표사진이 있는 핀이 하나도 없으면 아무 것도
    하지 않는다.
    """
    candidate_pins = list(
        Pin.objects.filter(segment=photobook.segment, included_in_segment=True)
        .filter(photos__taste_rank__lte=3)
        .distinct()
    )
    if not candidate_pins:
        return
    chosen_pin = random.choice(candidate_pins)
    representative_photos = list(Photo.objects.filter(pin=chosen_pin, taste_rank__lte=3))
    chosen_photo = random.choice(representative_photos)
    photobook.cover_photo_url = chosen_photo.photo_url
    photobook.save(update_fields=["cover_photo_url"])
