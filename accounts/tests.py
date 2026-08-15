import datetime
from unittest.mock import patch

from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from travel.models import Pin, TravelSegment

from .models import User


def _make_user(**kwargs):
    kwargs.setdefault("account_identifier", f"test-{User.objects.count() + 1}")
    kwargs.setdefault("email", f"test{User.objects.count() + 1}@example.com")
    return User.objects.create(**kwargs)


def _auth_headers(user):
    token = AccessToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@patch("accounts.views._get_google_client_id", return_value="test-client-id")
class GoogleLoginViewTests(TestCase):
    url = "/auth/google"

    @patch("accounts.views.google_id_token.verify_oauth2_token")
    def test_new_user_is_created(self, mock_verify, mock_client_id):
        mock_verify.return_value = {"sub": "google-sub-1", "email": "new@example.com"}

        response = self.client.post(
            self.url, data={"google_id_token": "dummy"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("session_token", body)
        self.assertEqual(body["user"]["email"], "new@example.com")
        self.assertTrue(User.objects.filter(account_identifier="google-sub-1").exists())

    @patch("accounts.views.google_id_token.verify_oauth2_token")
    def test_existing_user_is_reused_not_duplicated(self, mock_verify, mock_client_id):
        existing = _make_user(account_identifier="google-sub-2", email="old@example.com")
        mock_verify.return_value = {"sub": "google-sub-2", "email": "old@example.com"}

        response = self.client.post(
            self.url, data={"google_id_token": "dummy"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["user_id"], existing.pk)
        self.assertEqual(User.objects.filter(account_identifier="google-sub-2").count(), 1)

    @patch("accounts.views.google_id_token.verify_oauth2_token")
    def test_existing_user_email_change_is_synced(self, mock_verify, mock_client_id):
        existing = _make_user(account_identifier="google-sub-3", email="old@example.com")
        mock_verify.return_value = {"sub": "google-sub-3", "email": "changed@example.com"}

        self.client.post(self.url, data={"google_id_token": "dummy"}, content_type="application/json")

        existing.refresh_from_db()
        self.assertEqual(existing.email, "changed@example.com")

    @patch("accounts.views.google_id_token.verify_oauth2_token")
    def test_invalid_google_token_returns_400(self, mock_verify, mock_client_id):
        mock_verify.side_effect = ValueError("invalid token")

        response = self.client.post(
            self.url, data={"google_id_token": "dummy"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_missing_token_field_returns_400(self, mock_client_id):
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 400)


class LogoutViewTests(TestCase):
    url = "/auth/logout"

    def test_authenticated_logout_returns_204(self):
        user = _make_user()
        response = self.client.post(self.url, **_auth_headers(user))
        self.assertEqual(response.status_code, 204)

    def test_missing_token_returns_401(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 401)


class MeGetViewTests(TestCase):
    url = "/users/me"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_returns_user_fields_and_stats(self):
        response = self.client.get(self.url, **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user_id"], self.user.pk)
        self.assertEqual(body["pin_count"], 0)
        self.assertEqual(body["completed_trip_count"], 0)
        self.assertEqual(body["visited_city_count"], 0)

    def test_stats_reflect_pins_and_segments(self):
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0), city="서울"
        )
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 10, 0, 0), city="서울"
        )
        Pin.objects.create(
            user=self.user, tagged_at=datetime.datetime(2026, 8, 1, 11, 0, 0), city="부산"
        )
        TravelSegment.objects.create(user=self.user, name="완료된 여행", status=True)
        TravelSegment.objects.create(user=self.user, name="진행 중 여행", status=False)

        response = self.client.get(self.url, **_auth_headers(self.user))

        body = response.json()
        self.assertEqual(body["pin_count"], 3)
        self.assertEqual(body["completed_trip_count"], 1)
        self.assertEqual(body["visited_city_count"], 2)

    def test_stats_are_scoped_to_requesting_user(self):
        other_user = _make_user()
        Pin.objects.create(
            user=other_user, tagged_at=datetime.datetime(2026, 8, 1, 9, 0, 0), city="도쿄"
        )

        response = self.client.get(self.url, **_auth_headers(self.user))

        self.assertEqual(response.json()["pin_count"], 0)


class MeUpdateViewTests(TestCase):
    url = "/users/me"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.patch(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_updates_onboarding_completed(self):
        response = self.client.patch(
            self.url,
            data={"onboarding_completed": True},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["onboarding_completed"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.onboarding_completed)

    def test_partial_update_leaves_other_field_untouched(self):
        self.user.permission_intro_shown = True
        self.user.save(update_fields=["permission_intro_shown"])

        self.client.patch(
            self.url,
            data={"onboarding_completed": True},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.onboarding_completed)
        self.assertTrue(self.user.permission_intro_shown)


class EventsPermissionsViewTests(TestCase):
    url = "/events/permissions"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_camera_permission_updates_user_field(self):
        response = self.client.post(
            self.url,
            data={"permission_type": "camera", "status": "granted", "os": "android"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.camera_permission, "granted")

    def test_location_permission_denied_updates_user_field(self):
        self.client.post(
            self.url,
            data={"permission_type": "location", "status": "denied", "os": "ios"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.location_permission, "denied")

    def test_nfc_permission_does_not_touch_user_fields(self):
        response = self.client.post(
            self.url,
            data={"permission_type": "nfc", "status": "unsupported", "os": "android"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.camera_permission)
        self.assertIsNone(self.user.location_permission)
        self.assertIsNone(self.user.microphone_permission)

    def test_invalid_permission_type_returns_400(self):
        response = self.client.post(
            self.url,
            data={"permission_type": "bluetooth", "status": "granted", "os": "android"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)
