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
4. 재추천(`select_refreshed_recommendations`, 5.2.3) — **5.2.1과 동일하게 유사 사진 축소를
   먼저 적용**(2026-08-15 결정: 스펙 원문엔 명시가 없지만, 축소 없이 무작위 3장을 뽑으면 비슷한
   사진끼리 나란히 뽑힐 수 있어 추천 품질이 떨어짐). 대표 사진들만 점수순으로 상위 10장 후보
   (10장 미만이면 전체, 정확히 3장이면 무작위 없이 그대로) → 그중 3장 무작위 선정.
5. 전체 순위(`rank_all_photos`/`rank_all_photos_for_refresh`, `travel.Photo.taste_rank`용) —
   핀의 사진 전체에 순위(1부터)를 매긴다. 유사 사진 그룹에서는 **대표 1장만 상위 순위 경쟁에
   참여**시키고(대표들끼리 점수 비교/무작위 선정으로 순위 결정 — 유사 사진 여러 장이 나란히
   최상위를 차지해 대표사진들이 사실상 같은 사진이 되는 문제를 막기 위함, 2026-08-15 확인),
   그룹에서 제외된 "중복" 사진들은 각자 개별 점수로 다시 정렬해 대표 사진들 뒤에 순위를
   이어붙인다. 그래서 상위 순위는 항상 서로 다른 사진이고, 그래도 핀의 모든 사진이 순위를 받는다.

## 언제 호출하는지 (travel과 확인된 사항, 2026-08-15)
- **핀 생성 시점**: 그때 있는 사진 전체를 스코어링(최초 추천).
- **5.5(사진 등록)로 나중에 수동 추가된 사진**: 자동으로 재스코어링하지 않는다 — 5.6(새로고침)을
  사용자가 직접 눌러야 새로 추가된 사진까지 포함해서 재계산된다. `travel/models.py`의
  `Photo.taste_rank` 주석("수동 새로고침에서만 갱신")과 일치.

## 출력 형식 (확정)
`select_initial_recommendations`/`select_refreshed_recommendations`는 점수 높은 순으로 정렬된
`photo_id` 리스트를, `rank_all_photos`/`rank_all_photos_for_refresh`는 `[(photo_id, rank), ...]`를
반환한다(순위는 `Photo.taste_rank`에 그대로 저장하면 됨).

## 아직 미정 (travel 연동 시 확정 필요)
- `TIME_PROXIMITY_SECONDS`/`SIMILARITY_THRESHOLD` 구체적인 수치 — 지금은 임의로 잡은 초기값,
  실제 여행 사진으로 재검증 필요.

## 빈 입력 처리
사진이 0장이면 두 함수 모두 빈 리스트를 반환한다(에러 아님) — 핀에 사진이 아직 하나도 없는
상태를 별도 분기 없이 자연스럽게 처리하도록 설계됨.
"""

import random

import numpy as np

from recommendations.clip_backend import get_image_embedding, measure_all_axes

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


def rank_all_photos(photos, taste_axes):
    """핀의 사진 전체에 순위(1부터)를 매겨 [(photo_id, rank), ...]를 반환한다
    (`travel.Photo.taste_rank`용). 유사 사진 그룹은 대표 1장만 상위 순위 경쟁에 참여시키고,
    나머지 "중복" 사진은 개별 점수로 재정렬해 뒤에 이어붙인다 — 그래야 유사 사진 여러 장이
    나란히 최상위를 차지해 대표사진 3장이 사실상 같은 사진이 되는 문제가 생기지 않는다."""
    if not photos:
        return []

    primary = reduce_similar_photos(photos)
    primary_ids = {photo_id for photo_id, _image, _captured_at in primary}
    duplicates = [p for p in photos if p[0] not in primary_ids]

    ranked_primary = sorted(primary, key=lambda p: score_photo(p[1], taste_axes), reverse=True)
    ranked_duplicates = sorted(duplicates, key=lambda p: score_photo(p[1], taste_axes), reverse=True)

    ordered = ranked_primary + ranked_duplicates
    return [(photo_id, rank) for rank, (photo_id, _image, _captured_at) in enumerate(ordered, start=1)]


def _rank_for_refresh(photos, taste_axes, rng=None):
    """5.2.3 재추천의 공통 순서 계산. 유사 사진 그룹은 대표 1장만 상위 10장 후보 풀에
    넣어(무작위 3장이 비슷한 사진끼리 몰리지 않도록) 그중 3장을 무작위 선정해 맨 앞에 두고,
    선정 안 된 대표 사진 → 중복 사진 순으로 이어붙인 전체 (photo_id, image, captured_at)
    리스트를 반환한다."""
    rng = rng or random

    primary = reduce_similar_photos(photos)
    primary_ids = {photo_id for photo_id, _image, _captured_at in primary}
    duplicates = [p for p in photos if p[0] not in primary_ids]

    scored_primary = sorted(primary, key=lambda p: score_photo(p[1], taste_axes), reverse=True)
    candidate_pool = scored_primary[:REFRESH_CANDIDATE_POOL_SIZE]

    if len(candidate_pool) <= REFRESH_RECOMMENDATION_COUNT:
        selected = candidate_pool
    else:
        selected = rng.sample(candidate_pool, REFRESH_RECOMMENDATION_COUNT)

    selected_ids = {photo_id for photo_id, _image, _captured_at in selected}
    selected_sorted = sorted(selected, key=lambda p: score_photo(p[1], taste_axes), reverse=True)
    remaining_primary = [p for p in scored_primary if p[0] not in selected_ids]
    scored_duplicates = sorted(duplicates, key=lambda p: score_photo(p[1], taste_axes), reverse=True)

    return selected_sorted + remaining_primary + scored_duplicates


def select_refreshed_recommendations(photos, taste_axes, rng=None):
    """5.2.3 재추천. 유사 사진 축소 후 상위 10장 후보 중 3장을 무작위 선정해 photo_id로 반환한다
    (후보가 정확히 3장이면 무작위 없이 그대로)."""
    ordered = _rank_for_refresh(photos, taste_axes, rng)
    return [photo_id for photo_id, _image, _captured_at in ordered[:REFRESH_RECOMMENDATION_COUNT]]


def rank_all_photos_for_refresh(photos, taste_axes, rng=None):
    """5.2.3 재추천 + 핀 전체 순위. 무작위 선정된 3장이 1~3등, 나머지 대표 사진과 중복 사진이
    그 뒤로 점수순 이어붙어 [(photo_id, rank), ...]를 반환한다(`travel.Photo.taste_rank`용)."""
    if not photos:
        return []
    ordered = _rank_for_refresh(photos, taste_axes, rng)
    return [(photo_id, rank) for rank, (photo_id, _image, _captured_at) in enumerate(ordered, start=1)]
