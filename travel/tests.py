import datetime
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from taste.models import TasteProfileAxis
from taste.photo_measurement import load_image

from .models import Photo, Pin
from .views import pin_photos

CATALOG_DIR = Path(__file__).resolve().parent.parent / "taste" / "photo_catalog"


def _make_user(**kwargs):
    kwargs.setdefault("account_identifier", f"travel-test-{User.objects.count() + 1}")
    kwargs.setdefault("email", f"travel-test{User.objects.count() + 1}@example.com")
    return User.objects.create(**kwargs)


def _set_taste_axes(user):
    for axis_code in ["brightness", "vividness", "tone", "density", "photo_type"]:
        TasteProfileAxis.objects.create(user=user, axis_code=axis_code, value=50)


def _auth_headers(user):
    token = AccessToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class PinPhotosInitialScoringTests(TestCase):
    """5.5(사진 등록)에 5.2.1 최초 추천이 연결됐는지 검증 (#75).
    S3 업로드(resolve_and_consume)와 사진 다운로드(_download_image)는 모킹해
    실제 네트워크 호출 없이 taste 카탈로그 이미지로 대체한다."""

    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )
        self.factory = APIRequestFactory()

    def _post_photos(self, file_ids):
        photos = [
            {
                "file_id": file_id,
                "captured_at": "2026-08-01T09:00:00Z",
                "latitude": "37.5",
                "longitude": "127.0",
            }
            for file_id in file_ids
        ]
        request = self.factory.post(
            f"/pins/{self.pin.pin_id}/photos",
            {"photos": photos},
            format="json",
            **_auth_headers(self.user),
        )
        return pin_photos(request, self.pin.pin_id)

    @patch("travel.views.resolve_and_consume")
    @patch("recommendations.travel_adapter._download_image")
    def test_first_registration_triggers_initial_scoring(self, mock_download, mock_resolve):
        mock_download.side_effect = lambda url: load_image(CATALOG_DIR / "1001.jpg")
        mock_resolve.side_effect = lambda file_id, **kwargs: f"/media/{file_id}.jpg"
        _set_taste_axes(self.user)

        response = self._post_photos(["file_1", "file_2"])

        self.assertEqual(response.status_code, 200)
        ranks = list(Photo.objects.filter(pin=self.pin).values_list("taste_rank", flat=True))
        self.assertEqual(sorted(ranks), [1, 2])

    @patch("travel.views.resolve_and_consume")
    @patch("recommendations.travel_adapter._download_image")
    def test_second_registration_does_not_rescore(self, mock_download, mock_resolve):
        mock_download.side_effect = lambda url: load_image(CATALOG_DIR / "1001.jpg")
        mock_resolve.side_effect = lambda file_id, **kwargs: f"/media/{file_id}.jpg"
        _set_taste_axes(self.user)

        self._post_photos(["file_1"])
        first_photo = Photo.objects.get(pin=self.pin)
        self.assertEqual(first_photo.taste_rank, 1)

        self._post_photos(["file_3"])

        first_photo.refresh_from_db()
        self.assertEqual(first_photo.taste_rank, 1)
        new_photo = Photo.objects.exclude(pk=first_photo.pk).get(pin=self.pin)
        self.assertIsNone(new_photo.taste_rank)

    @patch("travel.views.resolve_and_consume")
    @patch("recommendations.travel_adapter._download_image")
    def test_no_taste_axes_does_not_crash(self, mock_download, mock_resolve):
        mock_download.side_effect = lambda url: load_image(CATALOG_DIR / "1001.jpg")
        mock_resolve.side_effect = lambda file_id, **kwargs: f"/media/{file_id}.jpg"

        response = self._post_photos(["file_1"])

        self.assertEqual(response.status_code, 200)
        photo = Photo.objects.get(pin=self.pin)
        self.assertIsNone(photo.taste_rank)
