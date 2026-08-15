"""
recommendations 앱 — 핀별 사진 추천 스코어링.

이 앱은 모델도 URL도 없다 (2026-08-15 결정, docs/IMPLEMENTATION.md 참고). travel 앱의
Pin/Photo API(5.5 사진 등록, 5.6 대표사진 새로고침, 5.7 사진 삭제) 내부에서 이 모듈의 함수를
호출하는 구조다.

⚠️ 설계 초안: travel의 Photo 모델이 아직 develop에 머지되지 않아, 아래 함수들은 travel.models를
import하지 않고 최소한의 인풋만 받도록 설계했다 — 각 사진은 `(photo_id, image, captured_at)`
튜플로 표현한다(`image`는 taste/photo_measurement.py와 동일하게 cv2 BGR numpy 배열). 실제
travel 연동 시, 호출부(travel 뷰)에서 `Photo.photo_url`을 다운로드해 이 형태로 변환해서 넘기면
된다 — 이미지를 어떻게 읽어오는지(로컬/S3)는 이 모듈이 신경 쓰지 않는다.

## 알고리즘 (기능명세서 5.2.1 / 5.2.3 기준)

1. 유사 사진 축소(`reduce_similar_photos`, 5.2.1) — 사진이 1장이면 축소 생략. 촬영 시각이
   가깝고(`TIME_PROXIMITY_SECONDS` 이내) + CLIP 임베딩 코사인 유사도가 높은
   (`SIMILARITY_THRESHOLD` 이상) 사진들을 하나로 묶어 대표 1장만 남긴다.
2. 스코어링(`score_photo`) — `taste.photo_measurement.measure_all_axes()`로 사진의 5개 축
   실측값을 구하고, 유저의 `TasteProfileAxis` 값과 축별 절댓값 차이의 평균을 100에서 뺀 값을
   점수로 쓴다(차이가 작을수록 = 취향에 가까울수록 높은 점수).
3. 최초 추천(`select_initial_recommendations`, 5.2.1) — 유사 사진 축소 → 스코어링 → 상위
   3장(3장 미만이면 있는 대로).
4. 재추천(`select_refreshed_recommendations`, 5.2.3) — 유사 사진 축소 없이 전체 스코어링 →
   상위 10장 후보(10장 미만이면 전체, 정확히 3장이면 무작위 없이 그대로) → 그중 3장 무작위 선정.

## 출력 형식 (확정)
`select_initial_recommendations`/`select_refreshed_recommendations`는 **점수 높은 순으로 정렬된
`photo_id` 리스트**를 반환한다. 리스트의 순서 자체가 순위다 — 별도로 순위 숫자를 담은 튜플을
반환하지 않는다. `PHOTO.is_main`이 순위(INT)를 저장하는 형태라면, 호출부(travel)에서
`for rank, photo_id in enumerate(result, start=1): ...`로 순위를 매기면 된다. 이 편이 스코어링
함수를 travel의 특정 필드 타입에 묶지 않아 더 안정적이다.

## 아직 미정 (travel 연동 시 확정 필요)
- `TIME_PROXIMITY_SECONDS`/`SIMILARITY_THRESHOLD` 구체적인 수치 — 지금은 임의로 잡은 초기값,
  실제 여행 사진으로 재검증 필요.

## 빈 입력 처리
사진이 0장이면 두 함수 모두 빈 리스트를 반환한다(에러 아님) — 핀에 사진이 아직 하나도 없는
상태를 별도 분기 없이 자연스럽게 처리하도록 설계됨.
"""

import random

import numpy as np

from taste.photo_measurement import get_image_embedding, measure_all_axes

TIME_PROXIMITY_SECONDS = 120
SIMILARITY_THRESHOLD = 0.9

INITIAL_RECOMMENDATION_COUNT = 3
REFRESH_CANDIDATE_POOL_SIZE = 10
REFRESH_RECOMMENDATION_COUNT = 3


def _cosine_similarity(a, b):
    a = np.asarray(a)
    b = np.asarray(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def reduce_similar_photos(photos):
    """(photo_id, image, captured_at) 리스트를 촬영 시각 근접 + 이미지 유사도로 줄인다."""
    if len(photos) <= 1:
        return list(photos)

    sorted_photos = sorted(photos, key=lambda p: p[2])
    embeddings = {photo_id: get_image_embedding(image) for photo_id, image, _ in sorted_photos}

    kept = []
    for photo in sorted_photos:
        photo_id, _image, captured_at = photo
        is_duplicate = False
        for kept_id, _kept_image, kept_captured_at in kept:
            time_close = abs((captured_at - kept_captured_at).total_seconds()) <= TIME_PROXIMITY_SECONDS
            if time_close and _cosine_similarity(embeddings[photo_id], embeddings[kept_id]) >= SIMILARITY_THRESHOLD:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(photo)
    return kept


def score_photo(image, taste_axes):
    """taste_axes: {axis_code: value(0~100)}. 값이 클수록 취향에 가깝다."""
    measured = measure_all_axes(image)
    diffs = [abs(measured[axis] - taste_axes[axis]) for axis in taste_axes]
    return 100 - (sum(diffs) / len(diffs))


def select_initial_recommendations(photos, taste_axes):
    """5.2.1 최초 추천. 상위 3장(부족하면 있는 대로)의 photo_id를 점수 높은 순으로 반환."""
    reduced = reduce_similar_photos(photos)
    scored = sorted(reduced, key=lambda p: score_photo(p[1], taste_axes), reverse=True)
    return [photo_id for photo_id, _image, _captured_at in scored[:INITIAL_RECOMMENDATION_COUNT]]


def select_refreshed_recommendations(photos, taste_axes, rng=None):
    """5.2.3 재추천. 유사 사진 축소는 하지 않는다 — 핀의 전체 사진을 스코어링해 상위 10장을
    후보로 추리고, 그중 3장을 무작위 선정한다(후보가 정확히 3장이면 무작위 없이 그대로)."""
    rng = rng or random

    scored = sorted(photos, key=lambda p: score_photo(p[1], taste_axes), reverse=True)
    candidate_pool = scored[:REFRESH_CANDIDATE_POOL_SIZE]

    if len(candidate_pool) <= REFRESH_RECOMMENDATION_COUNT:
        selected = candidate_pool
    else:
        selected = rng.sample(candidate_pool, REFRESH_RECOMMENDATION_COUNT)

    return [photo_id for photo_id, _image, _captured_at in selected]
