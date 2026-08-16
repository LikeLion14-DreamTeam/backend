import datetime

from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from travel.models import Photo, Pin, TravelSegment

from .models import Photobook, PhotobookPhotoLayout, PhotobookPin
from .services import build_photobook_pins
from .views import photobook_cover_refresh


def _make_user(**kwargs):
    kwargs.setdefault("account_identifier", f"photobooks-test-{User.objects.count() + 1}")
    kwargs.setdefault("email", f"photobooks-test{User.objects.count() + 1}@example.com")
    return User.objects.create(**kwargs)


def _auth_headers(user):
    token = AccessToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class PhotobookCoverRefreshTests(TestCase):
    """6.4(여정 커버 새로고침) 엔드포인트 검증 (#85). 커버는 여정 전체 핀 중 무작위 1개를
    고르고, 그 핀의 대표사진(taste_rank<=3) 중 무작위 1장을 쓴다 — 도시별로 포토북에
    큐레이션된 핀(PhotobookPin)으로 후보가 제한되지 않는다."""

    def setUp(self):
        self.user = _make_user()
        self.segment = TravelSegment.objects.create(user=self.user, name="테스트 여행", status=True)
        self.photobook = Photobook.objects.create(segment=self.segment, name="테스트 여행")
        self.factory = APIRequestFactory()

    def _make_pin(self, ranks, included_in_segment=True):
        """ranks: 이 핀에 만들 사진들의 taste_rank 목록(None 포함 가능). 생성된 사진 URL 목록을 반환."""
        pin = Pin.objects.create(
            user=self.user,
            segment=self.segment,
            included_in_segment=included_in_segment,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
        )
        urls = []
        for i, rank in enumerate(ranks):
            url = f"https://example.com/{pin.pin_id}-{i}.jpg"
            Photo.objects.create(
                pin=pin,
                captured_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
                photo_url=url,
                taste_rank=rank,
            )
            urls.append(url)
        return pin, urls

    def _refresh(self, user=None):
        request = self.factory.post(
            f"/photobooks/{self.photobook.photobook_id}/cover/refresh",
            **_auth_headers(user or self.user),
        )
        return photobook_cover_refresh(request, self.photobook.photobook_id)

    def test_refresh_picks_a_representative_photo_from_some_pin(self):
        _, urls1 = self._make_pin([1, 2, 3, None])
        _, urls2 = self._make_pin([1, 2, 3])
        representative_urls = set(urls1[:3]) | set(urls2)

        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.data["cover_photo_url"], representative_urls)
        self.photobook.refresh_from_db()
        self.assertEqual(self.photobook.cover_photo_url, response.data["cover_photo_url"])

    def test_pin_without_representative_photos_is_not_a_candidate(self):
        # taste_rank가 3 초과이거나 없는 사진뿐인 핀은 후보에서 제외되고, 대표사진 있는 핀만 뽑힘
        self._make_pin([None, 4, 5])
        _, urls2 = self._make_pin([1, 2, 3])

        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.data["cover_photo_url"], urls2)

    def test_excluded_pin_is_not_a_candidate(self):
        self._make_pin([1, 2, 3], included_in_segment=False)

        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["cover_photo_url"])

    def test_no_pins_leaves_cover_null(self):
        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["cover_photo_url"])

    def test_other_users_photobook_returns_404(self):
        other_user = _make_user()
        self._make_pin([1, 2, 3])

        response = self._refresh(user=other_user)

        self.assertEqual(response.status_code, 404)


class PhotobookListViewTests(TestCase):
    url = "/photobooks"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_empty_when_no_photobooks(self):
        response = self.client.get(self.url, **_auth_headers(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["photobooks"], [])

    def test_returns_only_requesting_users_photobooks_with_aggregates(self):
        segment = TravelSegment.objects.create(user=self.user, name="여행")
        photobook = Photobook.objects.create(segment=segment, name="여행")
        pin = Pin.objects.create(
            user=self.user,
            segment=segment,
            included_in_segment=True,
            city="서울",
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
        )
        Photo.objects.create(
            pin=pin,
            captured_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            photo_url="https://x/1.jpg",
        )

        other_user = _make_user()
        other_segment = TravelSegment.objects.create(user=other_user, name="다른 여행")
        Photobook.objects.create(segment=other_segment, name="다른 여행")

        response = self.client.get(self.url, **_auth_headers(self.user))

        photobooks = response.json()["photobooks"]
        self.assertEqual(len(photobooks), 1)
        self.assertEqual(photobooks[0]["photobook_id"], photobook.photobook_id)
        self.assertEqual(photobooks[0]["cities"], ["서울"])
        self.assertEqual(photobooks[0]["photo_count"], 1)


class PhotobookDetailGetViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.segment = TravelSegment.objects.create(
            user=self.user,
            name="여행",
            start_at=datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
            end_at=datetime.datetime(2026, 8, 3, 0, 0, 0, tzinfo=datetime.timezone.utc),
        )
        self.photobook = Photobook.objects.create(segment=self.segment, name="여행")

    def _url(self, photobook_id=None):
        return f"/photobooks/{photobook_id if photobook_id is not None else self.photobook.photobook_id}"

    def test_missing_token_returns_401(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_other_users_photobook_returns_404(self):
        other_user = _make_user()
        response = self.client.get(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)

    def test_get_groups_pins_by_city_with_total_days(self):
        pin = Pin.objects.create(
            user=self.user,
            segment=self.segment,
            included_in_segment=True,
            city="도쿄",
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
        )
        photo = Photo.objects.create(
            pin=pin,
            captured_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            photo_url="https://x/1.jpg",
        )
        photobook_pin = PhotobookPin.objects.create(photobook=self.photobook, pin=pin, order=1)
        PhotobookPhotoLayout.objects.create(photobook_pin=photobook_pin, photo=photo, order=1)

        response = self.client.get(self._url(), **_auth_headers(self.user))

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["total_days"], 3)
        self.assertEqual(body["pin_count"], 1)
        self.assertEqual(len(body["cities"]), 1)
        self.assertEqual(body["cities"][0]["city"], "도쿄")
        self.assertEqual(len(body["cities"][0]["pins"][0]["photos"]), 1)


class PhotobookDetailPatchViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.segment = TravelSegment.objects.create(user=self.user, name="여행")
        self.photobook = Photobook.objects.create(segment=self.segment, name="여행")

    def _url(self, photobook_id=None):
        return f"/photobooks/{photobook_id if photobook_id is not None else self.photobook.photobook_id}"

    def test_missing_token_returns_401(self):
        response = self.client.patch(self._url(), data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_updates_name(self):
        response = self.client.patch(
            self._url(),
            data={"name": "새 이름"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        self.photobook.refresh_from_db()
        self.assertEqual(self.photobook.name, "새 이름")

    def test_other_users_photobook_returns_404(self):
        other_user = _make_user()
        response = self.client.patch(
            self._url(),
            data={"name": "새 이름"},
            content_type="application/json",
            **_auth_headers(other_user),
        )
        self.assertEqual(response.status_code, 404)


class SelectPhotosForPinTasteRankOrderingTests(TestCase):
    """포토북 핀 카드 사진 선정이 taste_rank 순으로 되는지 검증 (photobooks TODO 해결)."""

    def test_photos_ordered_by_taste_rank_with_nulls_last(self):
        user = _make_user()
        segment = TravelSegment.objects.create(user=user, name="테스트 여행", status=True)
        photobook = Photobook.objects.create(segment=segment, name="테스트 여행")
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        pin = Pin.objects.create(
            user=user, segment=segment, included_in_segment=True, city="도쿄", tagged_at=base_time
        )

        photo_rank3 = Photo.objects.create(
            pin=pin, captured_at=base_time, photo_url="rank3", taste_rank=3
        )
        photo_rank1 = Photo.objects.create(
            pin=pin, captured_at=base_time + datetime.timedelta(hours=1), photo_url="rank1", taste_rank=1
        )
        photo_no_rank = Photo.objects.create(
            pin=pin, captured_at=base_time + datetime.timedelta(hours=2), photo_url="no_rank", taste_rank=None
        )

        build_photobook_pins(photobook)

        layouts = PhotobookPhotoLayout.objects.filter(photobook_pin__photobook=photobook).order_by("order")
        ordered_urls = [layout.photo.photo_url for layout in layouts]
        self.assertEqual(ordered_urls, ["rank1", "rank3", "no_rank"])
