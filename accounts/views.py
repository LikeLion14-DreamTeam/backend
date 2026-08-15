"""
accounts/views.py
1.1 로그인 / 1.2 로그아웃 / 1.3 내 정보 조회 / 1.4 정보 수정.
"""
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import AccessToken

from config.settings import get_secret

from .authentication import JWTAccessAuthentication
from .models import User
from .serializers import (
    GoogleLoginRequestSerializer,
    UserSerializer,
    UserUpdateRequestSerializer,
)

def _get_google_client_id() -> str:
    """settings/secrets.json에서 GOOGLE_CLIENT_ID를 필요 시점에 로드합니다.
    import 시점에 설정 누락으로 서버가 뜨지 않는 문제를 방지하기 위함입니다.
    """
    return get_secret("GOOGLE_CLIENT_ID")


def issue_session_token(user: User) -> str:
    """user_id claim이 들어간 JWT 세션 토큰 1개를 만듭니다."""
    token = AccessToken.for_user(user)
    return str(token)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def google_login(request):
    """POST /auth/google (1.1)"""
    serializer = GoogleLoginRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    raw_id_token = serializer.validated_data["google_id_token"]

    try:
        idinfo = google_id_token.verify_oauth2_token(
            raw_id_token, google_requests.Request(), _get_google_client_id()
        )
    except ValueError as exc:
        return Response(
            {"message": f"유효하지 않은 구글 ID 토큰입니다: {exc}", "code": "VALIDATION_ERROR"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account_identifier = idinfo.get("sub")
    email = idinfo.get("email")
    if not account_identifier or not email:
        return Response(
            {"message": "구글 계정 정보가 올바르지 않습니다.", "code": "VALIDATION_ERROR"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 우리 User 테이블에서 조회, 없으면 새로 생성
    user, created = User.objects.get_or_create(
        account_identifier=account_identifier,
        defaults={"email": email},
    )
    if not created and user.email != email:
        # 기존 회원이면 이메일이 바뀌었을 수 있으니 최신 값으로 갱신
        user.email = email
        user.save(update_fields=["email"])

    session_token = issue_session_token(user)

    return Response(
        {
            "session_token": session_token,
            "user": UserSerializer(user).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def logout(request):
    """POST /auth/logout — 현재 기기 로그아웃 (1.2)
    """
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "PATCH"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def me(request):
    """GET/PATCH /users/me — 조회(1.3)·수정(1.4)을 메서드로 분기
    """
    if request.method == "GET":
        return Response(UserSerializer(request.user).data)
    return _me_update(request)


def _me_update(request):
    """PATCH /users/me — 계정 정보 수정 (1.4)
    """
    serializer = UserUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    update_fields = []
    for field in ("onboarding_completed", "permission_intro_shown"):
        if field in data:
            setattr(request.user, field, data[field])
            update_fields.append(field)
    if update_fields:
        request.user.save(update_fields=update_fields)

    return Response(
        {
            "user_id": request.user.user_id,
            "onboarding_completed": request.user.onboarding_completed,
            "permission_intro_shown": request.user.permission_intro_shown,
        }
    )