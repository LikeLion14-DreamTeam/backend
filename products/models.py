from django.db import models
from accounts.models import User


class NfcTag(models.Model):
    PRODUCT_TYPE_CHOICES = [
        ("bag", "가방"),
        ("charm", "참"),
        ("keyring", "키링"),
        # 실제 제품 카탈로그 연동 전까지는 8.1 자동등록 시 쓰지 않음(MVP 하드코딩 기본값으로
        # 대체, docs/IMPLEMENTATION.md 참고). 과거 데이터 호환을 위해 choice는 유지.
        ("unknown", "미확인"),
    ]

    tag_id = models.CharField(max_length=100, primary_key=True)
    # 연결 해제(7.4.1) 시 NULL로 비운다 — ERD [확정] 사항. 재등록 방지는
    # user_id가 아니라 unlinked_at IS NOT NULL로 판단한다.
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="user_id",
        related_name="nfc_tags",
    )
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    # product_type='unknown'인 자동등록 태그는 이름도 알 수 없으므로 nullable.
    product_name = models.CharField(max_length=100, null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    # 이 태그로 시작된 태깅 세션 수(7.1/7.4). 태깅 세션 로그에서 재집계하는 편이
    # 정합성엔 안전하다는 API 명세서 노트가 있으나, ERD에 컬럼으로 정의되어 있어 우선 반영.
    tag_count = models.PositiveIntegerField(default=0)
    # 연결 해제(7.4.1) 시각. NULL이면 아직 연결 해제된 적 없음 — 재등록 가능 여부 판단 기준.
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "nfc_tag"

    def __str__(self):
        return f"{self.product_name} ({self.tag_id})"