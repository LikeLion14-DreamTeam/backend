import datetime
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.utils.timezone import now as timezone_now
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from photobooks.models import Photobook
from taste.models import TasteProfileAxis
from taste.photo_measurement import load_image

from .models import CountryStamp, Photo, Pin, TravelSegment, VoiceMemo
from .views import pin_photos, pin_photos_refresh

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


class PinPhotosRegisterRejectionTests(TestCase):
    """5.5 사진 등록의 반려 사유(MISSING_COORDINATES/OUT_OF_RADIUS/INVALID_FILE) 검증."""

    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            latitude="37.5000",
            longitude="127.0000",
        )
        self.factory = APIRequestFactory()

    def _post(self, photo_overrides):
        photo = {"file_id": "file_1", "captured_at": "2026-08-01T09:00:00Z"}
        photo.update(photo_overrides)
        request = self.factory.post(
            f"/pins/{self.pin.pin_id}/photos",
            {"photos": [photo]},
            format="json",
            **_auth_headers(self.user),
        )
        return pin_photos(request, self.pin.pin_id)

    def test_missing_coordinates_is_rejected(self):
        response = self._post({})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["added"], [])
        self.assertEqual(response.data["rejected"], [{"file_id": "file_1", "reason": "MISSING_COORDINATES"}])

    def test_out_of_radius_photo_is_rejected(self):
        response = self._post({"latitude": "38.5000", "longitude": "128.0000"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["added"], [])
        self.assertEqual(response.data["rejected"], [{"file_id": "file_1", "reason": "OUT_OF_RADIUS"}])

    @patch("travel.views.resolve_and_consume")
    def test_invalid_file_is_rejected(self, mock_resolve):
        from uploads.tokens import FileNotUploadedError

        mock_resolve.side_effect = FileNotUploadedError("업로드 안 됨")

        response = self._post({"latitude": "37.5001", "longitude": "127.0001"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["added"], [])
        self.assertEqual(response.data["rejected"], [{"file_id": "file_1", "reason": "INVALID_FILE"}])
        self.assertEqual(Photo.objects.filter(pin=self.pin).count(), 0)


class PinPhotosRefreshTests(TestCase):
    """5.6(대표사진 새로고침) 엔드포인트 검증 (#81)."""

    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )
        self.factory = APIRequestFactory()

    def _create_photos(self, catalog_ids):
        """catalog_ids: taste/photo_catalog의 파일명(확장자 제외), 예: '1001'."""
        base_time = datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        return [
            Photo.objects.create(
                pin=self.pin,
                captured_at=base_time + datetime.timedelta(hours=i),
                photo_url=f"https://example.com/{catalog_id}.jpg",
                source_type="uploaded",
            )
            for i, catalog_id in enumerate(catalog_ids)
        ]

    def _refresh(self, user=None):
        request = self.factory.post(
            f"/pins/{self.pin.pin_id}/representative-photos/refresh",
            **_auth_headers(user or self.user),
        )
        return pin_photos_refresh(request, self.pin.pin_id)

    @patch("recommendations.travel_adapter._download_image")
    def test_refresh_with_enough_photos_sets_top_three_ranks(self, mock_download):
        mock_download.side_effect = lambda url: load_image(CATALOG_DIR / url.rsplit("/", 1)[-1])
        _set_taste_axes(self.user)
        self._create_photos(["1001", "1002", "2001", "2002", "3001"])

        response = self._refresh()

        self.assertEqual(response.status_code, 200)
        representative_photos = response.data["representative_photos"]
        self.assertEqual(len(representative_photos), 3)
        returned_ids = {p["photo_id"] for p in representative_photos}
        ranked_ids = set(
            Photo.objects.filter(pin=self.pin, taste_rank__lte=3).values_list("photo_id", flat=True)
        )
        self.assertEqual(returned_ids, ranked_ids)
        for p in representative_photos:
            self.assertIn("url", p)

    def test_fewer_than_four_photos_returns_conflict(self):
        _set_taste_axes(self.user)
        self._create_photos(["1001", "1002", "2001"])

        response = self._refresh()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "CONFLICT")

    def test_other_users_pin_returns_404(self):
        other_user = _make_user()
        self._create_photos(["1001", "1002", "2001", "2002"])

        response = self._refresh(user=other_user)

        self.assertEqual(response.status_code, 404)


class PinCreateViewTests(TestCase):
    url = "/pins"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_minimal_pin_is_created(self):
        response = self.client.post(
            self.url, data={}, content_type="application/json", **_auth_headers(self.user)
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Pin.objects.filter(user=self.user).count(), 1)
        self.assertIsNone(response.json()["segment_id"])

    def test_country_name_creates_country_stamp(self):
        response = self.client.post(
            self.url,
            data={"country_name": "대한민국"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 201)
        stamp = CountryStamp.objects.get(user=self.user)
        self.assertEqual(stamp.country_code, "KR")
        self.assertEqual(stamp.country_name, "대한민국")

    def test_unknown_country_name_does_not_create_stamp(self):
        self.client.post(
            self.url,
            data={"country_name": "존재하지않는나라"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertFalse(CountryStamp.objects.filter(user=self.user).exists())

    def test_registered_nfc_tag_increments_tag_count(self):
        from products.models import NfcTag

        tag = NfcTag.objects.create(tag_id="tag-1", user=self.user, product_type="bag", tag_count=2)

        response = self.client.post(
            self.url,
            data={"nfc_tag_id": "tag-1"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 201)
        tag.refresh_from_db()
        self.assertEqual(tag.tag_count, 3)

    def test_unregistered_nfc_tag_returns_400(self):
        response = self.client.post(
            self.url,
            data={"nfc_tag_id": "does-not-exist"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Pin.objects.filter(user=self.user).count(), 0)

    def test_explicit_country_code_bypasses_name_mapping(self):
        response = self.client.post(
            self.url,
            data={"country_name": "매핑에없는나라", "country_code": "ZZ"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 201)
        stamp = CountryStamp.objects.get(user=self.user)
        self.assertEqual(stamp.country_code, "ZZ")

    @patch("travel.views.resolve_and_consume")
    def test_audio_file_creates_voice_memo(self, mock_resolve):
        mock_resolve.return_value = "/media/voice1.mp3"

        response = self.client.post(
            self.url,
            data={"audio_file": "token-1"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 201)
        pin = Pin.objects.get(user=self.user)
        self.assertIsNotNone(response.json()["voice_memo"])
        self.assertTrue(VoiceMemo.objects.filter(pin=pin).exists())

    @patch("travel.views.resolve_and_consume")
    def test_invalid_audio_file_returns_400_and_no_pin_created(self, mock_resolve):
        from uploads.tokens import FileNotUploadedError

        mock_resolve.side_effect = FileNotUploadedError("업로드 안 됨")

        response = self.client.post(
            self.url,
            data={"audio_file": "token-1"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Pin.objects.filter(user=self.user).count(), 0)


class PinDetailViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )

    def _url(self, pin_id=None):
        return f"/pins/{pin_id if pin_id is not None else self.pin.pin_id}"

    def test_missing_token_returns_401(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_get_returns_representative_photos(self):
        Photo.objects.create(pin=self.pin, captured_at=timezone_now(), photo_url="https://x/1.jpg", taste_rank=1)
        Photo.objects.create(pin=self.pin, captured_at=timezone_now(), photo_url="https://x/2.jpg", taste_rank=5)

        response = self.client.get(self._url(), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        photos = response.json()["representative_photos"]
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["url"], "https://x/1.jpg")

    def test_get_other_users_pin_returns_404(self):
        other_user = _make_user()
        response = self.client.get(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)

    def test_patch_updates_place_name_and_text_note(self):
        response = self.client.patch(
            self._url(),
            data={"place_name": "카페", "text_note": "좋았음"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        self.pin.refresh_from_db()
        self.assertEqual(self.pin.place_name, "카페")
        self.assertEqual(self.pin.text_note, "좋았음")

    def test_delete_pin_without_segment_succeeds(self):
        response = self.client.delete(self._url(), **_auth_headers(self.user))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Pin.objects.filter(pk=self.pin.pin_id).exists())

    def test_delete_pin_with_segment_returns_409(self):
        segment = TravelSegment.objects.create(user=self.user, name="여행")
        self.pin.segment = segment
        self.pin.save(update_fields=["segment"])

        response = self.client.delete(self._url(), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Pin.objects.filter(pk=self.pin.pin_id).exists())


class TripCurrentViewTests(TestCase):
    url = "/trips/current"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_no_pins_returns_has_pins_false(self):
        response = self.client.get(self.url, **_auth_headers(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_pins"])

    def test_pins_are_aggregated(self):
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            city="서울",
        )
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 10, 0, 0, tzinfo=datetime.timezone.utc),
            city="부산",
        )

        response = self.client.get(self.url, **_auth_headers(self.user))

        body = response.json()
        self.assertTrue(body["has_pins"])
        self.assertEqual(body["pin_count"], 2)
        self.assertEqual(body["cities"], ["부산", "서울"])

    def test_patch_with_no_pins_returns_409(self):
        response = self.client.patch(
            self.url, data={"name": "내 여행"}, content_type="application/json", **_auth_headers(self.user)
        )
        self.assertEqual(response.status_code, 409)

    def test_patch_sets_name_override(self):
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )

        response = self.client.patch(
            self.url, data={"name": "내 여행"}, content_type="application/json", **_auth_headers(self.user)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "내 여행")
        self.user.refresh_from_db()
        self.assertEqual(self.user.current_trip_name_override, "내 여행")

    def test_patch_empty_name_resets_override(self):
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )
        self.user.current_trip_name_override = "이전 이름"
        self.user.save(update_fields=["current_trip_name_override"])

        self.client.patch(
            self.url, data={"name": ""}, content_type="application/json", **_auth_headers(self.user)
        )

        self.user.refresh_from_db()
        self.assertIsNone(self.user.current_trip_name_override)


class TripListOrCreateViewTests(TestCase):
    url = "/trips"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_get_empty_list(self):
        response = self.client.get(self.url, **_auth_headers(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["trips"], [])

    def test_post_with_no_pins_returns_409(self):
        response = self.client.post(
            self.url, data={}, content_type="application/json", **_auth_headers(self.user)
        )
        self.assertEqual(response.status_code, 409)

    def test_post_creates_segment_and_photobook(self):
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
        )

        response = self.client.post(
            self.url,
            data={"name": "여름 여행"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["pin_count"], 2)
        self.assertEqual(body["name"], "여름 여행")
        self.assertTrue(Photobook.objects.filter(pk=body["photobook_id"]).exists())
        self.assertEqual(Pin.objects.filter(user=self.user, segment__isnull=True).count(), 0)

    def test_get_lists_created_segments(self):
        TravelSegment.objects.create(user=self.user, name="여행 A")
        TravelSegment.objects.create(user=self.user, name="여행 B")

        response = self.client.get(self.url, **_auth_headers(self.user))

        self.assertEqual(len(response.json()["trips"]), 2)


class TripDetailViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.segment = TravelSegment.objects.create(user=self.user, name="여행")

    def _url(self, segment_id=None):
        return f"/trips/{segment_id if segment_id is not None else self.segment.segment_id}"

    def test_missing_token_returns_401(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_get_other_users_segment_returns_404(self):
        other_user = _make_user()
        response = self.client.get(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)

    def test_get_returns_counts(self):
        Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            segment=self.segment,
            included_in_segment=True,
        )

        response = self.client.get(self._url(), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pin_count"], 1)

    def test_patch_renames_segment(self):
        Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            segment=self.segment,
            included_in_segment=True,
        )

        response = self.client.patch(
            self._url(),
            data={"name": "새 이름"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        self.segment.refresh_from_db()
        self.assertEqual(self.segment.name, "새 이름")

    def test_patch_start_after_end_returns_400(self):
        response = self.client.patch(
            self._url(),
            data={
                "start_at": "2026-08-10T00:00:00Z",
                "end_at": "2026-08-01T00:00:00Z",
            },
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_pin_exclusion_marks_pin_excluded(self):
        pin = Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            segment=self.segment,
            included_in_segment=True,
        )
        other_pin = Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 10, 0, 0, tzinfo=datetime.timezone.utc),
            segment=self.segment,
            included_in_segment=True,
        )

        response = self.client.patch(
            self._url(),
            data={"pin_exclusions": [{"pin_id": pin.pin_id, "included_in_segment": False}]},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        pin.refresh_from_db()
        self.assertFalse(pin.included_in_segment)

    def test_patch_excluding_pin_not_in_segment_returns_400(self):
        response = self.client.patch(
            self._url(),
            data={"pin_exclusions": [{"pin_id": 999999, "included_in_segment": False}]},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)

    def test_delete_cascades_pins(self):
        Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            segment=self.segment,
        )

        response = self.client.delete(self._url(), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(TravelSegment.objects.filter(pk=self.segment.segment_id).exists())
        self.assertEqual(Pin.objects.count(), 0)


class TripPinsViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.segment = TravelSegment.objects.create(user=self.user, name="여행")

    def _url(self, segment_id=None):
        return f"/trips/{segment_id if segment_id is not None else self.segment.segment_id}/pins"

    def test_missing_token_returns_401(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_other_users_segment_returns_404(self):
        other_user = _make_user()
        response = self.client.get(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)

    def test_lists_pins_in_segment(self):
        Pin.objects.create(
            user=self.user,
            tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            segment=self.segment,
        )

        response = self.client.get(self._url(), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["pins"]), 1)


class PinPhotosListViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )

    def _url(self):
        return f"/pins/{self.pin.pin_id}/photos"

    def test_missing_token_returns_401(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_lists_photos_ordered_by_captured_at(self):
        base = timezone_now()
        Photo.objects.create(
            pin=self.pin, captured_at=base + datetime.timedelta(hours=1), photo_url="https://x/2.jpg"
        )
        Photo.objects.create(
            pin=self.pin, captured_at=base, photo_url="https://x/1.jpg", taste_rank=1
        )

        response = self.client.get(self._url(), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        photos = response.json()["photos"]
        self.assertEqual([p["file_path"] for p in photos], ["https://x/1.jpg", "https://x/2.jpg"])
        self.assertTrue(photos[0]["is_pin_cover"])
        self.assertFalse(photos[1]["is_pin_cover"])

    def test_pagination_cursor_returns_remaining_items_on_next_page(self):
        base = timezone_now()
        for i in range(3):
            Photo.objects.create(
                pin=self.pin,
                captured_at=base + datetime.timedelta(hours=i),
                photo_url=f"https://x/{i}.jpg",
            )

        first_page = self.client.get(self._url() + "?limit=2", **_auth_headers(self.user))
        self.assertEqual(first_page.status_code, 200)
        first_body = first_page.json()
        self.assertEqual(len(first_body["photos"]), 2)
        self.assertIsNotNone(first_body["next_cursor"])

        second_page = self.client.get(
            self._url() + f"?limit=2&cursor={first_body['next_cursor']}", **_auth_headers(self.user)
        )
        second_body = second_page.json()
        self.assertEqual(len(second_body["photos"]), 1)
        self.assertIsNone(second_body["next_cursor"])
        self.assertEqual(
            {p["file_path"] for p in first_body["photos"] + second_body["photos"]},
            {"https://x/0.jpg", "https://x/1.jpg", "https://x/2.jpg"},
        )

    def test_other_users_pin_returns_404(self):
        other_user = _make_user()
        response = self.client.get(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)


class PhotoDeleteViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )
        self.photo = Photo.objects.create(pin=self.pin, captured_at=timezone_now(), photo_url="https://x/1.jpg")

    def _url(self, photo_id=None):
        return f"/photos/{photo_id if photo_id is not None else self.photo.photo_id}"

    def test_missing_token_returns_401(self):
        response = self.client.delete(self._url())
        self.assertEqual(response.status_code, 401)

    def test_owner_can_delete(self):
        response = self.client.delete(self._url(), **_auth_headers(self.user))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Photo.objects.filter(pk=self.photo.photo_id).exists())

    def test_other_users_photo_returns_404(self):
        other_user = _make_user()
        response = self.client.delete(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Photo.objects.filter(pk=self.photo.photo_id).exists())


class PinVoiceMemosViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.pin = Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
        )

    def _url(self):
        return f"/pins/{self.pin.pin_id}/voice-memos"

    def test_missing_token_returns_401(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_no_memo_returns_null(self):
        response = self.client.get(self._url(), **_auth_headers(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["voice_memo"])

    def test_existing_memo_is_returned(self):
        VoiceMemo.objects.create(pin=self.pin, audio_url="https://x/a.mp3", duration_sec=12)

        response = self.client.get(self._url(), **_auth_headers(self.user))

        body = response.json()["voice_memo"]
        self.assertEqual(body["audio_file"], "https://x/a.mp3")

    def test_other_users_pin_returns_404(self):
        other_user = _make_user()
        response = self.client.get(self._url(), **_auth_headers(other_user))
        self.assertEqual(response.status_code, 404)


class CountryStampsViewTests(TestCase):
    url = "/users/me/country-stamps"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_empty_when_no_stamps(self):
        response = self.client.get(self.url, **_auth_headers(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stamps"], [])

    def test_returns_only_requesting_users_stamps(self):
        CountryStamp.objects.create(user=self.user, country_code="KR", country_name="대한민국")
        other_user = _make_user()
        CountryStamp.objects.create(user=other_user, country_code="JP", country_name="일본")

        response = self.client.get(self.url, **_auth_headers(self.user))

        stamps = response.json()["stamps"]
        self.assertEqual(len(stamps), 1)
        self.assertEqual(stamps[0]["country_code"], "KR")
