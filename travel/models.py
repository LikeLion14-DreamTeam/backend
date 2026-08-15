from django.db import models
from accounts.models import User

class TravelSegment(models.Model):
    segment_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", related_name="travel_segments")
    name = models.CharField(max_length=100)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    status = models.BooleanField(default=True)
    # 포토북 연동 전까지는 항상 null
    cover_photo_url = models.CharField(max_length=500, null=True, blank=True)
    # 2026-08-15 PM 결정: start_at/end_at을 사용자가 직접 지정한 적 있으면 True.
    # True인 동안은 핀 포함 여부(pin_exclusions)만 바뀌어도 날짜를 자동 재계산하지 않는다.
    # docs/IMPLEMENTATION.md 참고.
    dates_manually_set = models.BooleanField(default=False)

    class Meta:
        db_table = "travel_segment"

    def __str__(self):
        return self.name


class Pin(models.Model):
    pin_id = models.AutoField(primary_key=True)

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", related_name="pins")

    segment = models.ForeignKey(
        TravelSegment, on_delete=models.CASCADE, null=True, blank=True,
        db_column="segment_id", related_name="pins",
    )
    latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)

    address = models.CharField(max_length=300, null=True, blank=True)

    place_name = models.CharField(max_length=150, null=True, blank=True, default="")
    tagged_at = models.DateTimeField()
    text_note = models.CharField(max_length=500, null=True, blank=True)
    saved_at = models.DateTimeField(auto_now_add=True)

    city = models.CharField(max_length=100, null=True, blank=True)
    included_in_segment = models.BooleanField(default=True)

    class Meta:
        db_table = "pin"

    def __str__(self):
        return f"pin_id={self.pin_id}"


class Photo(models.Model):
    SOURCE_TYPE_CHOICES = [
        ("captured", "촬영"),
        ("uploaded", "업로드"),
    ]

    photo_id = models.AutoField(primary_key=True)
    pin = models.ForeignKey(Pin, on_delete=models.CASCADE, db_column="pin_id", related_name="photos")
    captured_at = models.DateTimeField()
    latitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)

    source_type = models.CharField(max_length=30, choices=SOURCE_TYPE_CHOICES, default="uploaded")
    photo_url = models.CharField(max_length=500)

    is_main = models.BooleanField(default=False)

    class Meta:
        db_table = "photo"

    def __str__(self):
        return f"photo_id={self.photo_id}"


class VoiceMemo(models.Model):
    voice_memo_id = models.AutoField(primary_key=True)
    pin = models.OneToOneField(Pin, on_delete=models.CASCADE, db_column="pin_id", related_name="voicememo")
    audio_url = models.CharField(max_length=255)
    saved_at = models.DateTimeField(auto_now_add=True)

    duration_sec = models.IntegerField(default=0)

    class Meta:
        db_table = "voice_memo"

    def __str__(self):
        return f"voice_memo_id={self.voice_memo_id}"


class CountryStamp(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id", related_name="country_stamps")
    country_code = models.CharField(max_length=10)
    country_name = models.CharField(max_length=100)

    class Meta:
        db_table = "country_stamp"
        unique_together = [("user", "country_code")]

    def __str__(self):
        return f"{self.country_name} ({self.country_code})"
