"""
accounts/authentication.py

"""
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .models import User


class JWTAccessAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate_header(self, request):
        return self.keyword

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise AuthenticationFailed(
                "Authorization 헤더 형식이 올바르지 않습니다. 'Bearer <token>' 형태여야 합니다."
            )

        raw_token = parts[1]

        try:
            access_token = AccessToken(raw_token)
        except TokenError as exc:
            raise AuthenticationFailed(f"유효하지 않거나 만료된 토큰입니다: {exc}")

        user_id = access_token.get("user_id")
        if user_id is None:
            raise AuthenticationFailed("토큰에 user_id claim이 없습니다.")

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise AuthenticationFailed("토큰에 해당하는 사용자를 찾을 수 없습니다.")

        return (user, access_token)
