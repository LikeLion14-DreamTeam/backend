from rest_framework import serializers

from .models import User


class GoogleLoginRequestSerializer(serializers.Serializer):
    """POST /auth/google 요청 body 검증 (1.1)
    """

    google_id_token = serializers.CharField()


class UserUpdateRequestSerializer(serializers.Serializer):
    """PATCH /users/me 요청 body 검증 (1.4)"""

    onboarding_completed = serializers.BooleanField(required=False)
    permission_intro_shown = serializers.BooleanField(required=False)


class UserSerializer(serializers.ModelSerializer):
    """응답으로 내려줄 사용자 정보 (1.1/1.3/1.4 공통)"""

    class Meta:
        model = User
        fields = [
            "user_id",
            "email",
            "created_at",
            "onboarding_completed",
            "permission_intro_shown",
            "account_identifier",
        ]