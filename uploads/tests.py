from django.test import TestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User

from .tokens import verify_file_token


def _make_user(**kwargs):
    kwargs.setdefault("account_identifier", f"uploads-test-{User.objects.count() + 1}")
    kwargs.setdefault("email", f"uploads-test{User.objects.count() + 1}@example.com")
    return User.objects.create(**kwargs)


def _auth_headers(user):
    token = AccessToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class RequestUploadViewTests(TestCase):
    url = "/uploads"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.post(self.url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_photo_upload_request_returns_presigned_url_and_token(self):
        response = self.client.post(
            self.url,
            data={"file_type": "photo", "content_type": "image/jpeg"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("upload_url", body)
        self.assertIn("expires_at", body)
        payload = verify_file_token(body["file_id"])
        self.assertEqual(payload["user_id"], self.user.pk)
        self.assertEqual(payload["file_type"], "photo")
        self.assertEqual(payload["content_type"], "image/jpeg")

    def test_voice_upload_request_returns_voice_file_type(self):
        response = self.client.post(
            self.url,
            data={"file_type": "voice", "content_type": "audio/mpeg"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 200)
        payload = verify_file_token(response.json()["file_id"])
        self.assertEqual(payload["file_type"], "voice")

    def test_invalid_file_type_returns_400(self):
        response = self.client.post(
            self.url,
            data={"file_type": "video", "content_type": "video/mp4"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_content_type_returns_400(self):
        response = self.client.post(
            self.url,
            data={"file_type": "photo"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 400)

    def test_two_requests_issue_distinct_tokens(self):
        response1 = self.client.post(
            self.url,
            data={"file_type": "photo", "content_type": "image/jpeg"},
            content_type="application/json",
            **_auth_headers(self.user),
        )
        response2 = self.client.post(
            self.url,
            data={"file_type": "photo", "content_type": "image/jpeg"},
            content_type="application/json",
            **_auth_headers(self.user),
        )

        self.assertNotEqual(response1.json()["file_id"], response2.json()["file_id"])
