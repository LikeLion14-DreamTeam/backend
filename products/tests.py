from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User

from .models import NfcTag


def _make_user(**kwargs):
    kwargs.setdefault("account_identifier", f"test-{User.objects.count() + 1}")
    kwargs.setdefault("email", f"test{User.objects.count() + 1}@example.com")
    return User.objects.create(**kwargs)


def _auth_headers(user):
    token = AccessToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class MyProductsViewTests(TestCase):
    url = "/users/me/products"

    def setUp(self):
        self.user = _make_user()

    def test_missing_token_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_empty_when_no_tags(self):
        response = self.client.get(self.url, **_auth_headers(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["products"], [])

    def test_returns_only_linked_tags_for_requesting_user(self):
        NfcTag.objects.create(tag_id="tag-1", user=self.user, product_type="bag", product_name="가방")
        NfcTag.objects.create(
            tag_id="tag-2",
            user=self.user,
            product_type="charm",
            product_name="참",
            unlinked_at=timezone.now(),
        )
        other_user = _make_user()
        NfcTag.objects.create(tag_id="tag-3", user=other_user, product_type="keyring", product_name="키링")

        response = self.client.get(self.url, **_auth_headers(self.user))

        products = response.json()["products"]
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["tag_id"], "tag-1")
        self.assertEqual(products[0]["product_type"], "BAG")


class ProductUnlinkViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()

    def _url(self, tag_id):
        return f"/products/{tag_id}/unlink"

    def test_missing_token_returns_401(self):
        response = self.client.patch(self._url("tag-1"))
        self.assertEqual(response.status_code, 401)

    def test_unlink_clears_user_and_sets_timestamp(self):
        tag = NfcTag.objects.create(tag_id="tag-1", user=self.user, product_type="bag")

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"tag_id": "tag-1", "user_id": None})
        tag.refresh_from_db()
        self.assertIsNone(tag.user)
        self.assertIsNotNone(tag.unlinked_at)

    def test_nonexistent_tag_returns_404(self):
        response = self.client.patch(self._url("does-not-exist"), **_auth_headers(self.user))
        self.assertEqual(response.status_code, 404)

    def test_other_users_tag_returns_404(self):
        other_user = _make_user()
        NfcTag.objects.create(tag_id="tag-1", user=other_user, product_type="bag")

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 404)

    def test_already_unlinked_tag_returns_404(self):
        NfcTag.objects.create(
            tag_id="tag-1", user=self.user, product_type="bag", unlinked_at=timezone.now()
        )

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 404)


class ProductLinkViewTests(TestCase):
    def setUp(self):
        self.user = _make_user()

    def _url(self, tag_id):
        return f"/products/{tag_id}/link"

    def test_missing_token_returns_401(self):
        response = self.client.patch(self._url("tag-1"))
        self.assertEqual(response.status_code, 401)

    def test_new_tag_is_auto_registered_as_unknown(self):
        response = self.client.patch(self._url("new-tag"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["tag_id"], "new-tag")
        self.assertEqual(body["user_id"], self.user.pk)
        tag = NfcTag.objects.get(pk="new-tag")
        self.assertEqual(tag.product_type, "unknown")
        self.assertIsNone(tag.product_name)

    def test_relinking_own_previously_unlinked_tag(self):
        NfcTag.objects.create(
            tag_id="tag-1", user=None, product_type="bag", unlinked_at=timezone.now()
        )

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        tag = NfcTag.objects.get(pk="tag-1")
        self.assertEqual(tag.user_id, self.user.pk)
        self.assertIsNone(tag.unlinked_at)

    def test_relink_already_owned_tag_is_idempotent(self):
        NfcTag.objects.create(tag_id="tag-1", user=self.user, product_type="bag")

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], self.user.pk)

    def test_tag_owned_by_another_active_user_returns_409(self):
        other_user = _make_user()
        NfcTag.objects.create(tag_id="tag-1", user=other_user, product_type="bag")

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "CONFLICT")

    def test_tag_previously_unlinked_from_another_user_can_be_relinked(self):
        other_user = _make_user()
        NfcTag.objects.create(
            tag_id="tag-1", user=other_user, product_type="bag", unlinked_at=timezone.now()
        )

        response = self.client.patch(self._url("tag-1"), **_auth_headers(self.user))

        self.assertEqual(response.status_code, 200)
        tag = NfcTag.objects.get(pk="tag-1")
        self.assertEqual(tag.user_id, self.user.pk)
        self.assertIsNone(tag.unlinked_at)
