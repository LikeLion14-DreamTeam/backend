"""
accounts/models.py
"""
from django.db import models

PERMISSION_STATUS_CHOICES = [
    ("granted", "허용"),
    ("denied", "거부"),
    ("unsupported", "미지원"),
]


class User(models.Model):
    """
    구글 OAuth로만 가입/로그인 (1.1)
    """

    is_authenticated = True
    is_anonymous = False

    user_id = models.AutoField(primary_key=True)

    account_identifier = models.CharField(
        max_length=150,
        unique=True,
        help_text="구글 ID 토큰의 sub 값. 로그인 시 이 값으로 계정 조회/생성",
    )
    email = models.EmailField(max_length=150)

    created_at = models.DateTimeField(auto_now_add=True)  # 행이 처음 생성될 때 자동 기록

    # 로그인 후 온보딩 화면으로 보낼지, 바로 홈으로 보낼지 분기용
    onboarding_completed = models.BooleanField(default=False)
    # 권한 안내 화면을 이미 봤는지
    permission_intro_shown = models.BooleanField(default=False)

    camera_permission = models.CharField(
        max_length=20, choices=PERMISSION_STATUS_CHOICES, null=True, blank=True
    )
    location_permission = models.CharField(
        max_length=20, choices=PERMISSION_STATUS_CHOICES, null=True, blank=True
    )
    microphone_permission = models.CharField(
        max_length=20, choices=PERMISSION_STATUS_CHOICES, null=True, blank=True
    )

    class Meta:
        db_table = "user"

    def __str__(self) -> str:
        return self.email
