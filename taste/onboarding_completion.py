"""
온보딩(기본질문 + A/B + 무드보드) 완료 시점에 실제 TasteProfileAxis 값을 계산하고
TasteProfile.taste 텍스트를 생성하는 로직. API 명세서 2.3(PUT /users/me/taste-profile)에
해당하는 내부 트리거 — 클라이언트가 직접 호출하는 공개 엔드포인트는 아니다.
"""

from collections import Counter

from .axis_mapping import BASIC_QUESTION_AXIS_MAPPING
from .models import AxisCode, AxisStatus, BasicQuestionResponse, SelectionPhoto, TasteProfile, TasteProfileAxis
from .photo_catalog_manifest import PHOTO_CATALOG_MANIFEST
from .photo_measurements import PHOTO_MEASUREMENTS

# axis_code별 (기본질문 가중치, A/B 가중치, 무드보드1 가중치, 무드보드2 가중치)
AXIS_WEIGHTS = {
    AxisCode.BRIGHTNESS: (0.4, 0.4, 0.0, 0.2),
    AxisCode.VIVIDNESS: (0.4, 0.4, 0.0, 0.2),
    AxisCode.TONE: (0.4, 0.4, 0.0, 0.2),
    AxisCode.DENSITY: (0.3, 0.3, 0.2, 0.2),
    AxisCode.PHOTO_TYPE: (0.4, 0.4, 0.0, 0.2),
}

_AB_PHOTO_VALUE = {}
_MOODBOARD1_LABELS = {}
for round_no, entry in PHOTO_CATALOG_MANIFEST.items():
    for photo_set in entry["sets"]:
        for photo in photo_set["photos"]:
            if round_no <= 5:
                _AB_PHOTO_VALUE[photo["photo_id"]] = photo["value"]
            elif round_no == 6:
                _MOODBOARD1_LABELS[photo["photo_id"]] = (photo["distance"], photo["direction"])


def _basic_question_value(user, axis_code):
    for round_no, entry in BASIC_QUESTION_AXIS_MAPPING.items():
        if entry["axis_code"] == axis_code:
            response = BasicQuestionResponse.objects.filter(user=user, round_no=round_no).first()
            if response is None:
                return None
            return entry["choices"].get(response.answer)
    return None


def _ab_value(user, axis_code):
    for round_no, entry in PHOTO_CATALOG_MANIFEST.items():
        if round_no <= 5 and entry["axis_code"] == axis_code:
            selected = SelectionPhoto.objects.filter(user=user, round_no=round_no, status=True).first()
            if selected is None:
                return None
            return _AB_PHOTO_VALUE.get(selected.photo_id)
    return None


def _moodboard_avg(user, round_no, axis_code):
    photo_ids = SelectionPhoto.objects.filter(
        user=user, round_no=round_no, status=True
    ).values_list("photo_id", flat=True)
    values = [
        PHOTO_MEASUREMENTS[photo_id][axis_code]
        for photo_id in photo_ids
        if photo_id in PHOTO_MEASUREMENTS
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _compute_axis_value(user, axis_code):
    basic_w, ab_w, mb1_w, mb2_w = AXIS_WEIGHTS[axis_code]

    signals = [
        (_basic_question_value(user, axis_code), basic_w),
        (_ab_value(user, axis_code), ab_w),
    ]
    if mb1_w:
        signals.append((_moodboard_avg(user, 6, axis_code), mb1_w))
    if mb2_w:
        signals.append((_moodboard_avg(user, 7, axis_code), mb2_w))

    available = [(value, weight) for value, weight in signals if value is not None]
    if not available:
        return None

    total_weight = sum(weight for _, weight in available)
    weighted_sum = sum(value * weight for value, weight in available)
    return round(weighted_sum / total_weight)


BRIGHT_ADJECTIVES = {"high": "밝은", "low": "어두운"}
VIVID_ADJECTIVES = {"high": "선명한", "low": "차분한"}
TONE_ADJECTIVES = {"high": "따뜻한", "low": "차가운"}
DENSITY_ADJECTIVES = {"high": "꽉 찬 구도의", "low": "여백 있는 구도의"}
PHOTO_TYPE_ADJECTIVES = {"high": "인물", "low": "풍경"}

_AXIS_ADJECTIVES = {
    AxisCode.BRIGHTNESS: BRIGHT_ADJECTIVES,
    AxisCode.VIVIDNESS: VIVID_ADJECTIVES,
    AxisCode.TONE: TONE_ADJECTIVES,
    AxisCode.DENSITY: DENSITY_ADJECTIVES,
    AxisCode.PHOTO_TYPE: PHOTO_TYPE_ADJECTIVES,
}


def _adjective(axis_code, value):
    if value is None:
        return None
    if value >= 60:
        return _AXIS_ADJECTIVES[axis_code]["high"]
    if value <= 40:
        return _AXIS_ADJECTIVES[axis_code]["low"]
    return None


def _composition_phrase(user):
    photo_ids = SelectionPhoto.objects.filter(user=user, round_no=6, status=True).values_list(
        "photo_id", flat=True
    )
    labels = [_MOODBOARD1_LABELS[pid] for pid in photo_ids if pid in _MOODBOARD1_LABELS]
    if not labels:
        return None

    distances = Counter(distance for distance, _ in labels)
    directions = Counter(direction for _, direction in labels)
    top_distance = distances.most_common(1)[0][0]
    top_direction = directions.most_common(1)[0][0]
    return f"{top_distance}·{top_direction} 구도를 선호합니다"


def _build_taste_text(axis_values, composition_phrase):
    adjectives = [
        _adjective(axis_code, axis_values.get(axis_code)) for axis_code in AxisCode.values
    ]
    adjectives = [a for a in adjectives if a]

    parts = []
    if adjectives:
        parts.append(f"{' '.join(adjectives)} 사진을 선호합니다")
    if composition_phrase:
        parts.append(composition_phrase)

    return " ".join(parts)


def regenerate_taste_text(user):
    """현재 저장된 TasteProfileAxis 값 + 무드보드1라운드 구도 선호를 기준으로
    TasteProfile.taste 텍스트를 다시 생성해 저장한다 (API 명세서 2.3 트리거).
    온보딩 완료 직후(축 재계산 후)와 2.5(축 값 수동 수정) 양쪽에서 재사용한다."""
    axis_values = {
        axis.axis_code: axis.value for axis in TasteProfileAxis.objects.filter(user=user)
    }
    composition_phrase = _composition_phrase(user)
    taste_text = _build_taste_text(axis_values, composition_phrase)
    TasteProfile.objects.update_or_create(user=user, defaults={"taste": taste_text})


def compute_and_save_taste_profile(user):
    axis_values = {axis_code: _compute_axis_value(user, axis_code) for axis_code in AxisCode.values}

    for axis_code, value in axis_values.items():
        if value is None:
            continue
        TasteProfileAxis.objects.update_or_create(
            user=user, axis_code=axis_code, defaults={"value": value, "status": AxisStatus.REFLECTED}
        )

    regenerate_taste_text(user)
