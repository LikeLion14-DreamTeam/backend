import datetime
import random
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from accounts.models import User
from taste.models import TasteProfileAxis
from taste.photo_measurement import load_image, measure_all_axes
from travel.models import Photo, Pin

from .scoring import (
    rank_all_photos,
    rank_all_photos_for_refresh,
    reduce_similar_photos,
    score_photo,
    select_initial_recommendations,
    select_refreshed_recommendations,
)
from .travel_adapter import rank_pin_photos, refresh_pin_photos

# travel의 Photo 모델이 아직 없어서, taste 카탈로그 사진을 스코어링 로직 검증용으로만 재사용한다
# (사진 내용 자체는 의미 없음 — 알고리즘 동작만 확인).
CATALOG_DIR = Path(__file__).resolve().parent.parent / "taste" / "photo_catalog"


def _load(photo_id):
    return load_image(CATALOG_DIR / f"{photo_id}.jpg")


class ReduceSimilarPhotosTests(SimpleTestCase):
    def test_single_photo_returned_as_is(self):
        photo = (1001, _load(1001), datetime.datetime(2026, 8, 1, 9, 0), None)
        self.assertEqual(reduce_similar_photos([photo]), [photo])

    def test_same_image_close_in_time_is_deduplicated(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        photos = [
            (1, image, base_time, None),
            (2, image, base_time + datetime.timedelta(seconds=10), None),
        ]
        reduced = reduce_similar_photos(photos)
        self.assertEqual(len(reduced), 1)

    def test_same_image_far_apart_in_time_is_not_deduplicated(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        photos = [
            (1, image, base_time, None),
            (2, image, base_time + datetime.timedelta(hours=3), None),
        ]
        reduced = reduce_similar_photos(photos)
        self.assertEqual(len(reduced), 2)

    def test_visually_different_photos_close_in_time_are_not_deduplicated(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [
            (1001, _load(1001), base_time, None),
            (2001, _load(2001), base_time + datetime.timedelta(seconds=5), None),
        ]
        reduced = reduce_similar_photos(photos)
        self.assertEqual(len(reduced), 2)


class ScorePhotoTests(SimpleTestCase):
    def test_returns_float_within_reasonable_range(self):
        taste_axes = {
            "brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50,
        }
        score = score_photo(measure_all_axes(_load(1001)), taste_axes)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_closer_match_scores_higher(self):
        # score_photo는 이제 이미 계산된 measured_axes를 받기만 하므로(#104), 측정값을
        # 직접 만들어서 "brightness만 다르면 더 가까운 쪽이 더 높은 점수를 받는다"는
        # 스코어링 공식 자체만 격리해서 검증한다.
        taste_axes = {
            "brightness": 90, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50,
        }

        bright_score = score_photo({**taste_axes, "brightness": 85}, taste_axes)  # 90에 더 가까움
        dark_score = score_photo({**taste_axes, "brightness": 20}, taste_axes)  # 90에서 더 멂
        self.assertGreater(bright_score, dark_score)


class SelectInitialRecommendationsTests(SimpleTestCase):
    def test_returns_at_most_three(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i), None)
            for i, photo_id in enumerate([1001, 2001, 3001, 4001, 5001])
        ]
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_initial_recommendations(photos, taste_axes)
        self.assertEqual(len(result), 3)

    def test_fewer_than_three_returns_all(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [(1001, _load(1001), base_time, None)]
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_initial_recommendations(photos, taste_axes)
        self.assertEqual(len(result), 1)

    def test_empty_photos_returns_empty_list(self):
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_initial_recommendations([], taste_axes)
        self.assertEqual(result, [])

    def test_result_is_ordered_by_score_descending(self):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        photos = [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i), None)
            for i, photo_id in enumerate([1001, 1002, 2001, 2002])
        ]
        taste_axes = {"brightness": 90, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_initial_recommendations(photos, taste_axes)
        photo_by_id = {p[0]: p[1] for p in photos}
        scores = [score_photo(measure_all_axes(photo_by_id[photo_id]), taste_axes) for photo_id in result]
        self.assertEqual(scores, sorted(scores, reverse=True))


class SelectRefreshedRecommendationsTests(SimpleTestCase):
    def _photos(self, photo_ids):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        return [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i), None)
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

    def test_empty_photos_returns_empty_list(self):
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_refreshed_recommendations([], taste_axes)
        self.assertEqual(result, [])

    def test_similar_photos_do_not_all_appear_together(self):
        """유사 사진(같은 이미지, 촬영 시각 근접) 3장이 있어도 후보 풀에는 대표 1장만 남아,
        무작위 3장 추천에 유사 사진끼리 몰리지 않는다(2026-08-15, 5.2.1과 로직 통합)."""
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        duplicates = [
            (1, image, base_time, None),
            (2, image, base_time + datetime.timedelta(seconds=5), None),
            (3, image, base_time + datetime.timedelta(seconds=10), None),
        ]
        distinct_photos = [
            (2001, _load(2001), base_time + datetime.timedelta(hours=1), None),
            (3001, _load(1002), base_time + datetime.timedelta(hours=2), None),
        ]
        photos = duplicates + distinct_photos
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = select_refreshed_recommendations(photos, taste_axes, rng=random.Random(0))
        duplicate_ids = {1, 2, 3}
        self.assertLessEqual(len(set(result) & duplicate_ids), 1)


class RankAllPhotosForRefreshTests(SimpleTestCase):
    def _photos(self, photo_ids):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        return [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i), None)
            for i, photo_id in enumerate(photo_ids)
        ]

    def test_empty_photos_returns_empty_list(self):
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        self.assertEqual(rank_all_photos_for_refresh([], taste_axes), [])

    def test_every_photo_gets_a_distinct_rank(self):
        photos = self._photos([1001, 1002, 2001, 2002, 3001])
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = rank_all_photos_for_refresh(photos, taste_axes, rng=random.Random(0))

        self.assertEqual({photo_id for photo_id, _rank in result}, {p[0] for p in photos})
        ranks = sorted(rank for _photo_id, rank in result)
        self.assertEqual(ranks, list(range(1, len(photos) + 1)))

    def test_duplicate_photos_do_not_occupy_top_ranks_together(self):
        """유사 사진 3장이 있어도, 무작위 선정되는 상위 3등 안에는 대표 1장만 들어갈 수 있다.

        distinct 클러스터를 2개 준비해 대표 후보가 3개(대표1 + distinct 2장)가 되도록 한다 —
        후보 클러스터 수가 top-N(3)보다 적으면 자리를 채우기 위해 어쩔 수 없이 같은 클러스터의
        중복 사진이 상위권에 끼어들 수밖에 없으므로(핀 전체 사진에 순위를 다 매겨야 하는 요건과
        상충), 이 테스트는 클러스터가 충분할 때의 보장만 검증한다."""
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        duplicates = [
            (1, image, base_time, None),
            (2, image, base_time + datetime.timedelta(seconds=5), None),
            (3, image, base_time + datetime.timedelta(seconds=10), None),
        ]
        distinct_photos = [
            (2001, _load(2001), base_time + datetime.timedelta(hours=1), None),
            (3001, _load(3001), base_time + datetime.timedelta(hours=2), None),
        ]
        photos = duplicates + distinct_photos

        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = dict(rank_all_photos_for_refresh(photos, taste_axes, rng=random.Random(0)))

        duplicate_ids = {1, 2, 3}
        top_three_ids = {photo_id for photo_id, rank in result.items() if rank <= 3}
        self.assertLessEqual(len(top_three_ids & duplicate_ids), 1)


class RankAllPhotosTests(SimpleTestCase):
    def _photos(self, photo_ids):
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        return [
            (photo_id, _load(photo_id), base_time + datetime.timedelta(hours=i), None)
            for i, photo_id in enumerate(photo_ids)
        ]

    def test_empty_photos_returns_empty_list(self):
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        self.assertEqual(rank_all_photos([], taste_axes), [])

    def test_every_photo_gets_a_distinct_rank(self):
        photos = self._photos([1001, 1002, 2001, 2002, 3001])
        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = rank_all_photos(photos, taste_axes)

        self.assertEqual({photo_id for photo_id, _rank in result}, {p[0] for p in photos})
        ranks = sorted(rank for _photo_id, rank in result)
        self.assertEqual(ranks, list(range(1, len(photos) + 1)))

    def test_duplicate_photos_do_not_occupy_top_ranks_together(self):
        """유사 사진(같은 이미지, 촬영 시각 근접) 3장이 있어도, 상위 순위는 서로 다른
        대표 사진들이 차지하고 중복 사진들은 뒤로 밀려야 한다."""
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        image = _load(1001)
        duplicates = [
            (1, image, base_time, None),
            (2, image, base_time + datetime.timedelta(seconds=5), None),
            (3, image, base_time + datetime.timedelta(seconds=10), None),
        ]
        distinct_photo = (2001, _load(2001), base_time + datetime.timedelta(hours=1), None)
        photos = duplicates + [distinct_photo]

        taste_axes = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
        result = dict(rank_all_photos(photos, taste_axes))

        duplicate_ids = {1, 2, 3}
        # 중복 그룹에서 대표로 뽑힌 딱 1장만 1~2등 안에 들 수 있고, 나머지 둘은 반드시 뒤로 밀린다.
        top_two_ids = {photo_id for photo_id, rank in result.items() if rank <= 2}
        self.assertLessEqual(len(top_two_ids & duplicate_ids), 1)


def _make_travel_user(**kwargs):
    kwargs.setdefault("account_identifier", f"travel-test-{User.objects.count() + 1}")
    kwargs.setdefault("email", f"travel-test{User.objects.count() + 1}@example.com")
    return User.objects.create(**kwargs)


def _set_taste_axes(user, **overrides):
    values = {"brightness": 50, "vividness": 50, "tone": 50, "density": 50, "photo_type": 50}
    values.update(overrides)
    for axis_code, value in values.items():
        TasteProfileAxis.objects.create(user=user, axis_code=axis_code, value=value)


class TravelAdapterTests(TestCase):
    """travel_adapter.py — Photo.taste_rank 저장까지 실제 DB로 검증. S3 다운로드는
    _download_image를 모킹해 taste 카탈로그 이미지로 대체한다(네트워크 호출 없음)."""

    def setUp(self):
        self.user = _make_travel_user()
        self.pin = Pin.objects.create(user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0))

    def _create_photo(self, catalog_id, captured_at):
        return Photo.objects.create(pin=self.pin, captured_at=captured_at, photo_url=str(catalog_id))

    @patch("recommendations.travel_adapter._download_image")
    def test_rank_pin_photos_saves_taste_rank(self, mock_download):
        mock_download.side_effect = lambda url: _load(int(url))
        _set_taste_axes(self.user)
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        self._create_photo(1001, base_time)
        self._create_photo(2001, base_time + datetime.timedelta(hours=1))

        rank_pin_photos(self.pin)

        ranks = list(Photo.objects.filter(pin=self.pin).values_list("taste_rank", flat=True))
        self.assertEqual(sorted(ranks), [1, 2])

    @patch("recommendations.travel_adapter._download_image")
    def test_rank_pin_photos_without_taste_axes_does_nothing(self, mock_download):
        mock_download.side_effect = lambda url: _load(int(url))
        photo = self._create_photo(1001, datetime.datetime(2026, 8, 1, 9, 0, 0))

        rank_pin_photos(self.pin)

        photo.refresh_from_db()
        self.assertIsNone(photo.taste_rank)

    @patch("recommendations.travel_adapter._download_image")
    def test_rank_pin_photos_with_no_photos_does_nothing(self, mock_download):
        _set_taste_axes(self.user)
        rank_pin_photos(self.pin)
        mock_download.assert_not_called()

    @patch("recommendations.travel_adapter._download_image")
    def test_refresh_pin_photos_saves_taste_rank_for_all_photos(self, mock_download):
        mock_download.side_effect = lambda url: _load(int(url))
        _set_taste_axes(self.user)
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        for i, catalog_id in enumerate([1001, 1002, 2001, 2002, 3001]):
            self._create_photo(catalog_id, base_time + datetime.timedelta(hours=i))

        refresh_pin_photos(self.pin)

        ranks = list(Photo.objects.filter(pin=self.pin).values_list("taste_rank", flat=True))
        self.assertEqual(sorted(ranks), [1, 2, 3, 4, 5])

    @patch("recommendations.travel_adapter._download_image")
    def test_undecodable_photo_is_skipped_instead_of_crashing(self, mock_download):
        """#102 후속 — HEIC 말고도 다운로드/디코딩 실패하는 사진(손상된 파일, 미지원
        포맷 등)이 하나 있어도 핀 전체 스코어링이 죽지 않고, 그 사진만 제외한 채
        나머지 사진들은 정상적으로 순위가 매겨져야 한다."""

        def fake_download(url):
            if url == "bad":
                raise ValueError("이미지를 디코딩할 수 없습니다: bad")
            return _load(int(url))

        mock_download.side_effect = fake_download
        _set_taste_axes(self.user)
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        good_photo_1 = self._create_photo(1001, base_time)
        bad_photo = Photo.objects.create(pin=self.pin, captured_at=base_time + datetime.timedelta(hours=1), photo_url="bad")
        good_photo_2 = self._create_photo(2001, base_time + datetime.timedelta(hours=2))

        rank_pin_photos(self.pin)

        good_photo_1.refresh_from_db()
        bad_photo.refresh_from_db()
        good_photo_2.refresh_from_db()
        self.assertIsNone(bad_photo.taste_rank)
        self.assertIsNotNone(good_photo_1.taste_rank)
        self.assertIsNotNone(good_photo_2.taste_rank)
        self.assertEqual({good_photo_1.taste_rank, good_photo_2.taste_rank}, {1, 2})

    @patch("recommendations.travel_adapter._download_image")
    def test_rank_pin_photos_caches_measured_axes(self, mock_download):
        """#104 — 최초 스코어링 시점에 실측값이 Photo에 저장돼야 재추천 때 재사용할 수 있다."""
        mock_download.side_effect = lambda url: _load(int(url))
        _set_taste_axes(self.user)
        photo = self._create_photo(1001, datetime.datetime(2026, 8, 1, 9, 0, 0))

        rank_pin_photos(self.pin)

        photo.refresh_from_db()
        expected = measure_all_axes(_load(1001))
        self.assertAlmostEqual(photo.measured_brightness, expected["brightness"])
        self.assertAlmostEqual(photo.measured_vividness, expected["vividness"])
        self.assertAlmostEqual(photo.measured_tone, expected["tone"])
        self.assertAlmostEqual(photo.measured_density, expected["density"])
        self.assertAlmostEqual(photo.measured_photo_type, expected["photo_type"])

    @patch("recommendations.travel_adapter.measure_all_axes")
    @patch("recommendations.travel_adapter._download_image")
    def test_refresh_reuses_cached_measured_axes_without_remeasuring(self, mock_download, mock_measure):
        """#104 핵심 — 이미 measured_*가 채워진 사진은 재추천할 때 measure_all_axes를
        다시 호출하지 않아야 한다(캐시 재사용). 사진 다운로드(_download_image) 자체는
        유사사진 판별(pHash)에 여전히 필요해서 계속 호출된다."""
        mock_download.side_effect = lambda url: _load(int(url))
        mock_measure.return_value = {
            "brightness": 60, "vividness": 60, "tone": 60, "density": 60, "photo_type": 60,
        }
        _set_taste_axes(self.user)
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0)
        for i, catalog_id in enumerate([1001, 1002, 2001, 2002, 3001]):
            self._create_photo(catalog_id, base_time + datetime.timedelta(hours=i))

        rank_pin_photos(self.pin)
        self.assertEqual(mock_measure.call_count, 5)

        mock_measure.reset_mock()
        refresh_pin_photos(self.pin)

        mock_measure.assert_not_called()
        self.assertEqual(mock_download.call_count, 10)  # 최초 5회 + 재추천 5회, 다운로드는 매번 필요
