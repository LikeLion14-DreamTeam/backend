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

    # 구글 ID 토큰의 picture 클레임 — 로그인 시(POST /auth/google)에만 서버가 채운다.
    # 프런트가 직접 값을 보내 덮어쓸 수 있는 경로는 없음(PATCH /users/me에 노출 안 함).
    # 재로그인 시 picture 값이 없으면 기존 값을 그대로 유지한다. (#96)
    profile_image_url = models.CharField(max_length=500, null=True, blank=True)

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

    # 진행 중인 여행(3.1)의 이름을 사용자가 직접 수정했을 때만 채워지는 값. TravelSegment가
    # 아직 없는 상태(진행 중)라 저장할 곳이 없어 User에 둔다 — 유저당 진행 중 여행은 항상
    # 최대 1개(segment_id IS NULL인 핀 전체)라 유저 단위로 충분하다. 여행 종료(3.2) 성공 시
    # null로 리셋된다. docs/IMPLEMENTATION.md 참고.
    current_trip_name_override = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = "user"

    def __str__(self) -> str:
        return self.email
