from django.db import models
from travel.models import TravelSegment


class Photobook(models.Model):
    photobook_id = models.AutoField(primary_key=True)
    # 여행 구간 하나당 포토북 정확히 1개
    segment = models.OneToOneField(
        TravelSegment, on_delete=models.CASCADE, db_column="segment_id", related_name="photobook"
    )
    name = models.CharField(max_length=100)
    # 5.6/6.4와 동일한 취향 프로파일 스코어링으로 채워짐. recommendations 연동 전까지 null
    cover_photo_url = models.CharField(max_length=500, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "photobook"

    def __str__(self):
        return self.name
