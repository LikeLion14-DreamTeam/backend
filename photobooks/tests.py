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
    """6.4(포토북 커버 사진 새로고침) 엔드포인트 검증 (#85)."""

    def setUp(self):
        self.user = _make_user()
        self.segment = TravelSegment.objects.create(user=self.user, name="테스트 여행", status=True)
        self.photobook = Photobook.objects.create(segment=self.segment, name="테스트 여행")
        self.factory = APIRequestFactory()

    def _add_photo_to_layout(self, photo_url, order=1):
        pin = Pin.objects.create(
            user=self.user,
            segment=self.segment,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
        )
        photo = Photo.objects.create(
            pin=pin,
            captured_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            photo_url=photo_url,
        )
        photobook_pin = PhotobookPin.objects.create(photobook=self.photobook, pin=pin, order=order)
        PhotobookPhotoLayout.objects.create(photobook_pin=photobook_pin, photo=photo, order=1)
        return photo

    def _refresh(self, user=None):
        request = self.factory.post(
            f"/photobooks/{self.photobook.photobook_id}/cover/refresh",
            **_auth_headers(user or self.user),
        )
        return photobook_cover_refresh(request, self.photobook.photobook_id)

    def test_refresh_picks_a_photo_already_in_the_photobook(self):
        photo_urls = {
            self._add_photo_to_layout(f"https://example.com/{i}.jpg", order=i).photo_url
            for i in range(1, 6)
        }

        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.data["cover_photo_url"], photo_urls)
        self.photobook.refresh_from_db()
        self.assertEqual(self.photobook.cover_photo_url, response.data["cover_photo_url"])

    def test_no_photos_in_photobook_leaves_cover_null(self):
        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["cover_photo_url"])

    def test_other_users_photobook_returns_404(self):
        other_user = _make_user()
        self._add_photo_to_layout("https://example.com/1.jpg")

        response = self._refresh(user=other_user)

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
