from rest_framework import serializers

from .models import PERMISSION_STATUS_CHOICES, User

PERMISSION_TYPE_CHOICES = [
    ("camera", "카메라"),
    ("location", "위치"),
    ("microphone", "마이크"),
    ("nfc", "NFC"),
]

PERMISSION_OS_CHOICES = [
    ("android", "안드로이드"),
    ("ios", "iOS"),
]


class GoogleLoginRequestSerializer(serializers.Serializer):
    """POST /auth/google 요청 body 검증 (1.1)
    """

    google_id_token = serializers.CharField()


class UserUpdateRequestSerializer(serializers.Serializer):
    """PATCH /users/me 요청 body 검증 (1.4)."""

    onboarding_completed = serializers.BooleanField(required=False)
    permission_intro_shown = serializers.BooleanField(required=False)


class PermissionEventRequestSerializer(serializers.Serializer):
    """POST /events/permissions 요청 body 검증 (1.5)"""

    permission_type = serializers.ChoiceField(choices=PERMISSION_TYPE_CHOICES)
    status = serializers.ChoiceField(choices=PERMISSION_STATUS_CHOICES)
    os = serializers.ChoiceField(choices=PERMISSION_OS_CHOICES)


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