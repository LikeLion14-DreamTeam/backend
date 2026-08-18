"""
recommendations 앱 — travel.Pin/Photo와 scoring.py를 연결하는 어댑터.

travel 담당자가 이 모듈의 함수를 자기 뷰(5.5/5.6)에서 호출하면 된다. 사진 다운로드(S3 공개 URL
GET), 취향 프로파일 조회(taste 앱), 스코어링(scoring.py), 결과 저장(Photo.taste_rank)까지
전부 이 안에서 처리한다.
"""

import logging

import cv2
import numpy as np
import requests

from taste.models import TasteProfileAxis
from travel.models import Photo

from .scoring import rank_all_photos, rank_all_photos_for_refresh

logger = logging.getLogger("request_logger")


def _download_image(photo_url):
    response = requests.get(photo_url, timeout=10)
    response.raise_for_status()
    image_array = np.frombuffer(response.content, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"이미지를 디코딩할 수 없습니다: {photo_url}")
    return image


def _get_taste_axes(user):
    return {axis.axis_code: axis.value for axis in TasteProfileAxis.objects.filter(user=user)}


def _to_scoring_photos(photos):
    """사진을 (photo_id, image, captured_at) 형태로 내려받는다. 한 장이라도 다운로드/디코딩에
    실패하면(지원 안 하는 포맷, 손상된 파일, 일시적 네트워크 오류 등) 그 사진만 건너뛰고
    나머지로 계속 진행한다 — 예전에는 이 실패가 그대로 전파돼 핀 전체 스코어링이 500으로
    죽었다."""
    result = []
    for photo in photos:
        try:
            image = _download_image(photo.photo_url)
        except (ValueError, requests.exceptions.RequestException) as exc:
            logger.warning(
                "사진 다운로드/디코딩 실패, 스코어링에서 제외: photo_id=%s url=%s error=%s",
                photo.photo_id, photo.photo_url, exc,
            )
            continue
        result.append((photo.photo_id, image, photo.captured_at))
    return result


def _score_and_save(pin, rank_func):
    """핀의 사진을 다운로드해 rank_func으로 순위를 매기고 Photo.taste_rank에 저장한다.

    온보딩을 완료하지 않아 취향 축이 하나도 없는 유저는 순위를 매길 기준이 없으므로 아무 것도
    하지 않는다(에러 아님).
    """
    photos = list(pin.photos.all())
    if not photos:
        return

    taste_axes = _get_taste_axes(pin.user)
    if not taste_axes:
        return

    scoring_photos = _to_scoring_photos(photos)
    ranking = dict(rank_func(scoring_photos, taste_axes))

    for photo in photos:
        photo.taste_rank = ranking.get(photo.photo_id)
    Photo.objects.bulk_update(photos, ["taste_rank"])


def rank_pin_photos(pin):
    """5.2.1 최초 추천 — 핀 생성 시점에 있는 사진 전체에 순위를 매겨 Photo.taste_rank에 저장한다.
    유사 사진은 대표 1장만 상위 순위 경쟁에 참여한다(scoring.rank_all_photos 참고)."""
    _score_and_save(pin, rank_all_photos)


def refresh_pin_photos(pin):
    """5.6 재추천/새로고침 — 5.5로 나중에 추가된 사진까지 포함해 핀의 사진 전체를 다시
    스코어링하고 Photo.taste_rank를 갱신한다. 유사 사진 축소 후 상위 10장 후보 중 3장을
    무작위 선정해 1~3등으로 두고, 나머지는 점수순으로 이어붙인다(scoring.rank_all_photos_for_refresh
    참고). 매번 호출할 때마다 무작위 선정 결과가 바뀔 수 있다 — 그게 "새로고침"의 의도다."""
    _score_and_save(pin, rank_all_photos_for_refresh)
