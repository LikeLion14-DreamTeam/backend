import datetime
import random
from pathlib import Path

from django.test import SimpleTestCase

from taste.photo_measurement import load_image

from .scoring import (
    reduce_similar_photos,
    score_photo,
    select_initial_recommendations,
    select_refreshed_recommendations,
)

# travel의 Photo 모델이 아직 없어서, taste 카탈로그 사진을 스코어링 로직 검증용으로만 재사용한다
# (사진 내용 자체는 의미 없음 — 알고리즘 동작만 확인).
CATALOG_DIR = Path(__file__).resolve().parent.parent / "taste" / "photo_catalog"


def _load(photo_id):
    return load_image(CATALOG_DIR / f"{photo_id}.jpg")


class ReduceSimilarPhotosTests(SimpleTestCase):
    def test_single_photo_returned_as_is(self):
        photo = (1001, _load(1001), datetime.datetime(2026, 8, 1, 9, 0))
        self.assertEqual(reduce_similar_photos([photo]), [photo])

    def test_same_image_close_in_time_is_deduplicated(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        photos = [
            (1, image, base_time),
            (2, image, base_time + datetime.timedelta(seconds=10)),
        ]
        reduced = reduce_similar_photos(photos)
        self.assertEqual(len(reduced), 1)

    def test_same_image_far_apart_in_time_is_not_deduplicated(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        photos = [
            (1, image, base_time),
            (2, image, base_time + datetime.timedelta(hours=3)),
        ]
        reduced = reduce_similar_photos(photos)
        self.assertEqual(len(reduced), 2)

    def test_visually_different_photos_close_in_time_are_not_deduplicated(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [
            (1001, _load(1001), base_time),
            (2001, _load(2001), base_time + datetime.timedelta(seconds=5)),
        ]
        reduced = reduce_similar_photos(photos)
        self.assertEqual(len(reduced), 2)


class ScorePhotoTests(SimpleTestCase):
    def test_returns_float_within_reasonable_range(self):
        taste_axes = {
            "brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50,
        }
        score = score_photo(_load(1001), taste_axes)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_closer_match_scores_higher(self):
        bright_photo = _load(1002)  # brightness axis, "80" 큐레이션 쪽
        dark_photo = _load(1001)  # brightness axis, "20" 큐레이션 쪽
        taste_axes = {
            "brightness": 90, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50,
        }
        bright_score = score_photo(bright_photo, taste_axes)
        dark_score = score_photo(dark_photo, taste_axes)
        self.assertGreater(bright_score, dark_score)


class SelectInitialRecommendationsTests(SimpleTestCase):
    def test_returns_at_most_three(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i))
            for i, photo_id in enumerate([1001, 2001, 3001, 4001, 5001])
        ]
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_initial_recommendations(photos, taste_axes)
        self.assertEqual(len(result), 3)

    def test_fewer_than_three_returns_all(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [(1001, _load(1001), base_time)]
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_initial_recommendations(photos, taste_axes)
        self.assertEqual(len(result), 1)


class SelectRefreshedRecommendationsTests(SimpleTestCase):
    def _photos(self, photo_ids):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        return [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i))
            for i, photo_id in enumerate(photo_ids)
        ]

    def test_returns_three_when_pool_larger(self):
        photos = self._photos([1001, 1002, 2001, 2002, 3001, 3002, 4001, 4002, 5001, 5002, 6001, 6002])
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_refreshed_recommendations(photos, taste_axes, rng=random.Random(0))
        self.assertEqual(len(result), 3)

    def test_exactly_three_candidates_returned_without_randomization(self):
        photos = self._photos([1001, 1002, 1003])
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_refreshed_recommendations(photos, taste_axes)
        self.assertEqual(set(result), {1001, 1002, 1003})

    def test_fewer_than_three_returns_all(self):
        photos = self._photos([1001, 1002])
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_refreshed_recommendations(photos, taste_axes)
        self.assertEqual(set(result), {1001, 1002})
