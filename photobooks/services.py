"""
photobooks/services.py — 포토북 생성/갱신 시 도시별 핀 선정, 핀별 사진 선정 로직.
"""
import random

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

    TODO(recommendations 연동 전 임시): 실제로는 취향 프로파일 기준 스코어링 결과를 써야
    하지만, 그 스코어링 함수가 아직 없어 임시로 captured_at 순으로 상위 N장을 사용함.
    """
    return list(Photo.objects.filter(pin=pin).order_by("captured_at", "photo_id")[:PHOTOS_PER_PIN])


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
        for pin in _select_pins_for_city(city_pins):
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
    포토북 커버 사진 새로고침 (6.4). 포토북에 이미 포함된 사진(PhotobookPhotoLayout) 중
    순수 무작위로 1장을 뽑아 Photobook.cover_photo_url에 저장한다.

    명세서 원문은 "취향 프로파일 기준 재정렬 → 상위 10개 → 무작위 1개"였지만, 새로고침마다
    여정 전체 사진을 다시 스코어링하는 비용이 커서 취향 스코어링 없이 무작위로 단순화하기로
    결정했다 — docs/spec.md 정정 기록 참고. 포토북에 사진이 하나도 없으면 아무 것도 하지 않는다.
    """
    layouts = list(PhotobookPhotoLayout.objects.filter(photobook_pin__photobook=photobook))
    if not layouts:
        return
    chosen = random.choice(layouts)
    photobook.cover_photo_url = chosen.photo.photo_url
    photobook.save(update_fields=["cover_photo_url"])
