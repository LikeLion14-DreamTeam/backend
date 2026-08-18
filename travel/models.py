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
    # 2026-08-15: 4.1(GET /trips) 응답에 여행 구간별 국가 목록을 내려주기 위해 추가.
    # POST /pins에서 받은 country_name 원본 문자열을 city처럼 그대로 저장(매핑/검증 없음).
    # CountryStamp(사용자 단위 도장)와는 별개 — 이 필드가 생기기 전 핀들은 country_name=NULL로 남고
    # 소급 채우기는 불가능(핀-CountryStamp 간 직접 연결이 없음). docs/IMPLEMENTATION.md 참고.
    country_name = models.CharField(max_length=100, null=True, blank=True)
    # 2026-08-16: 3.2(국가 도장 탭 → 국가별 핀 목록) 필터링용. POST /pins에서 country_code가
    # 확정되는 시점(직접 지정 또는 country_name 매핑)에 함께 저장한다. country_name과 마찬가지로
    # 이 필드가 생기기 전 핀들은 NULL로 남고 소급 채우기는 불가능. docs/IMPLEMENTATION.md 참고.
    country_code = models.CharField(max_length=10, null=True, blank=True)
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

    # 핀 자체 대표사진(5.1/5.4) 선정용 순위. 사진이 1장이어도 순위를 매긴다(핀 사진 전체에 순위 부여).
    # 수동 새로고침(5.6)에서만 갱신되고, 사진이 추가된다고 자동으로는 안 바뀐다.
    # 포토북(6.2)에서 쓰는 핀별 대표사진 선정은 이 필드가 아니라 photobooks.PhotobookPhotoLayout로 별도 관리한다.
    taste_rank = models.IntegerField(null=True, blank=True)

    # taste.photo_measurement.measure_all_axes()의 실측값 캐시(0~100). 사진 고유의 객관적
    # 속성이라 취향축이 바뀌어도 값이 안 바뀐다 — 재추천 때마다 매번 재계산하던 걸 없애기 위해
    # 최초 스코어링 시점에 한 번 계산해서 저장하고, 이후로는 계속 재사용한다. 아직 계산 안 된
    # 기존 사진은 null(백필 전까지). (#104)
    measured_brightness = models.FloatField(null=True, blank=True)
    measured_vividness = models.FloatField(null=True, blank=True)
    measured_tone = models.FloatField(null=True, blank=True)
    measured_density = models.FloatField(null=True, blank=True)
    measured_photo_type = models.FloatField(null=True, blank=True)

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
