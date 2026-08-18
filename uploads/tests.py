import io
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from django.test import TestCase
from PIL import Image
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User

from .tokens import issue_file_token, resolve_and_consume, verify_file_token


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


def _not_found_error(operation):
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, operation)


def _fake_image_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(200, 50, 50)).save(buf, format="PNG")
    return buf.getvalue()


class ResolveAndConsumeHeicConversionTests(TestCase):
    """#102 — HEIC/HEIF 업로드는 resolve_and_consume에서 JPEG로 변환돼야 한다.

    실제 HEIC 인코딩 여부는 테스트 환경(코덱 설치)에 따라 달라질 수 있어, 여기서는
    PNG 바이트를 대신 써서 "content_type이 HEIC면 변환 경로를 탄다"는 분기 자체만
    검증한다 — 실제 HEIC 디코딩 자체는 로컬에서 진짜 아이폰 HEIC 파일로 별도 확인함."""

    def setUp(self):
        self.user = User.objects.create(account_identifier="heic-test", email="heic@example.com")

    @patch("uploads.tokens._s3_client")
    def test_heic_content_type_is_converted_to_jpeg(self, mock_client_factory):
        mock_s3 = MagicMock()
        mock_client_factory.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": "uploads/pending/abc123.heic"}]}
        mock_s3.head_object.side_effect = _not_found_error("HeadObject")
        mock_s3.get_object.return_value = {"Body": io.BytesIO(_fake_image_bytes())}

        token, _uid = issue_file_token(self.user, "photo", "image/heic")
        url = resolve_and_consume(token, user=self.user, expected_file_type="photo")

        self.assertTrue(url.endswith(".jpg"))
        mock_s3.copy_object.assert_not_called()
        mock_s3.put_object.assert_called_once()
        put_kwargs = mock_s3.put_object.call_args.kwargs
        self.assertEqual(put_kwargs["Key"], "uploads/consumed/abc123.jpg")
        self.assertEqual(put_kwargs["ContentType"], "image/jpeg")
        mock_s3.delete_object.assert_called_once_with(
            Bucket=mock_s3.put_object.call_args.kwargs["Bucket"], Key="uploads/pending/abc123.heic"
        )

    @patch("uploads.tokens._s3_client")
    def test_non_heic_content_type_still_uses_fast_copy_path(self, mock_client_factory):
        mock_s3 = MagicMock()
        mock_client_factory.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": "uploads/pending/xyz789.jpg"}]}
        mock_s3.head_object.side_effect = _not_found_error("HeadObject")

        token, _uid = issue_file_token(self.user, "photo", "image/jpeg")
        url = resolve_and_consume(token, user=self.user, expected_file_type="photo")

        self.assertTrue(url.endswith("xyz789.jpg"))
        mock_s3.put_object.assert_not_called()
        mock_s3.get_object.assert_not_called()
        mock_s3.copy_object.assert_called_once()
