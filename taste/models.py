from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import User


class AxisCode(models.TextChoices):
    BRIGHTNESS = "brightness", "밝기"
    VIVIDNESS = "vividness", "채도"
    TONE = "tone", "색온도"
    DENSITY = "density", "구도와 밀도"
    PHOTO_TYPE = "photo_type", "사진종류"


class AxisStatus(models.TextChoices):
    REFLECTED = "REFLECTED", "반영 완료"
    PENDING = "PENDING", "미반영"


class OnboardingStage(models.TextChoices):
    BASIC_QUESTION = "BASIC_QUESTION", "기본 질문"
    AB_SELECTION = "AB_SELECTION", "A/B 선택"
    MOODBOARD = "MOODBOARD", "무드보드"
    COMPLETED = "COMPLETED", "완료"


class TasteProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="taste_profile",
    )
    taste = models.TextField(blank=True, default="")
    last_updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"TasteProfile(user={self.user_id})"


class TasteProfileAxis(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="taste_axes",
    )
    axis_code = models.CharField(max_length=50, choices=AxisCode.choices)
    value = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    status = models.CharField(
        max_length=20, choices=AxisStatus.choices, default=AxisStatus.PENDING
    )

    class Meta:
        unique_together = [("user", "axis_code")]

    def __str__(self):
        return f"TasteProfileAxis(user={self.user_id}, axis={self.axis_code})"


class BasicQuestionResponse(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="basic_question_responses",
    )
    round_no = models.PositiveSmallIntegerField()
    answer = models.CharField(max_length=100)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "round_no")]

    def __str__(self):
        return f"BasicQuestionResponse(user={self.user_id}, round={self.round_no})"


class SelectionPhoto(models.Model):
    """
    round_no 1~5: A/B 선택 5라운드, round_no 6~7: 무드보드 2라운드
    (round-axis 매핑은 코드 상수로 관리, DB엔 axis_code 컬럼 없음 — ERD 그대로 유지)

    photo_id는 라운드 내 순번이 아니라 고정 사진 카탈로그 전역에서 유일한 ID다
    (API 명세서 2.2 예시 기준, 코드/설정에 박힌 정적 자산의 식별자).
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="selection_photos",
    )
    round_no = models.PositiveSmallIntegerField()
    photo_id = models.PositiveIntegerField()
    status = models.BooleanField()
    selected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "round_no", "photo_id")]

    def __str__(self):
        return f"SelectionPhoto(user={self.user_id}, round={self.round_no}, photo={self.photo_id})"


class OnboardingProgress(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="onboarding_progress",
    )
    current_stage = models.CharField(
        max_length=20,
        choices=OnboardingStage.choices,
        default=OnboardingStage.BASIC_QUESTION,
    )
    current_round = models.PositiveSmallIntegerField(default=1)
    is_retrain = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"OnboardingProgress(user={self.user_id}, stage={self.current_stage})"


class ProfileRetrainHistory(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="profile_retrain_history",
    )
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"ProfileRetrainHistory(user={self.user_id}, completed_at={self.completed_at})"
