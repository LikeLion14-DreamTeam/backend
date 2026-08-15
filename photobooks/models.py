from django.db import models
from travel.models import Photo, Pin, TravelSegment


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


class PhotobookPin(models.Model):
    """
    포토북(6.2)에 도시별로 보여줄 핀 선정 결과. 포토북 생성 시점에 도시별 우선순위 규칙
    (음성메모+텍스트 둘다 > 둘 중 하나 > 랜덤)으로 최대 3개씩 확정해 저장
    """

    photobook_pin_id = models.AutoField(primary_key=True)
    photobook = models.ForeignKey(
        Photobook, on_delete=models.CASCADE, db_column="photobook_id", related_name="photobook_pins"
    )
    pin = models.ForeignKey(Pin, on_delete=models.CASCADE, db_column="pin_id", related_name="photobook_pins")
    # 같은 도시 안에서의 표시 순번(01/02/03)
    order = models.IntegerField()

    class Meta:
        db_table = "photobook_pin"
        unique_together = [("photobook", "pin")]
        ordering = ["order"]

    def __str__(self):
        return f"photobook_id={self.photobook_id} pin_id={self.pin_id} order={self.order}"


class PhotobookPhotoLayout(models.Model):
    """
    포토북 속 각 핀 카드에 보여줄 사진(최대 4장, 1등은 큰 사진) 선정 결과
    Photo.taste_rank(핀 자체 대표사진용)와는 별개로 관리 — 포토북 전용 스코어링/선정
    """

    layout_id = models.AutoField(primary_key=True)
    photobook_pin = models.ForeignKey(
        PhotobookPin, on_delete=models.CASCADE, db_column="photobook_pin_id", related_name="photo_layouts"
    )
    photo = models.ForeignKey(
        Photo, on_delete=models.CASCADE, db_column="photo_id", related_name="photobook_layouts"
    )
    # 1등 = 큰 사진, 2~4등 = 작은 썸네일
    order = models.IntegerField()

    class Meta:
        db_table = "photobook_photo_layout"
        unique_together = [("photobook_pin", "photo")]
        ordering = ["order"]

    def __str__(self):
        return f"photobook_pin_id={self.photobook_pin_id} photo_id={self.photo_id} order={self.order}"
