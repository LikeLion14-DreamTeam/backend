from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers


class RoundedDecimalField(serializers.DecimalField):
    """위도/경도용 DecimalField.

    브라우저 Geolocation API는 소수점 10자리 이상의 원본 정밀도로 좌표를 내려주는데,
    기본 DecimalField는 이 원본 값의 전체 유효숫자 개수가 max_digits를 넘으면 반올림 없이
    그대로 거부해버린다("Ensure that there are no more than N digits in total").
    그래서 max_digits 검증 전에 decimal_places 자리로 먼저 반올림한다 — GPS 오차 범위상
    소수점 6자리(약 11cm 정밀도)면 충분하므로 값 손실 우려는 없다. (2026-08-17, 프론트 연동
    중 발견 — docs/IMPLEMENTATION.md 참고)
    """

    def validate_precision(self, value):
        if self.decimal_places is not None:
            quantizer = Decimal(1).scaleb(-self.decimal_places)
            value = value.quantize(quantizer, rounding=ROUND_HALF_UP)
        return super().validate_precision(value)


class PinCreateRequestSerializer(serializers.Serializer):
    """
    POST /pins 요청 body 검증 (8.2)
    """

    nfc_tag_id = serializers.CharField(required=False, allow_null=True)
    latitude = RoundedDecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)
    longitude = RoundedDecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)
    address = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=300)
    city = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=100)
    country_name = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=100)
    country_code = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=10)
    place_name = serializers.CharField(required=False, allow_blank=True, max_length=150, default="")
    text_note = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=500)
    audio_file = serializers.CharField(required=False, allow_null=True)
    duration_sec = serializers.IntegerField(required=False, default=0, min_value=0)
    # 프론트가 촬영/태깅 시점의 디바이스 시각을 보내면 그대로 신뢰해서 저장한다(서버 검증
    # 없음). 안 보내면 기존처럼 서버 수신 시각으로 폴백 — 하위호환. docs/IMPLEMENTATION.md 참고.
    tagged_at = serializers.DateTimeField(required=False, allow_null=True)


class TripCreateRequestSerializer(serializers.Serializer):
    """POST /trips 요청 body 검증 (3.2, 여행 종료)"""

    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    end_at = serializers.DateTimeField(required=False, allow_null=True)


class TripCurrentPatchRequestSerializer(serializers.Serializer):
    """PATCH /trips/current 요청 body 검증 (신규 — 진행 중인 여행 이름 수정)

    빈 문자열("")은 자동 생성 이름으로 되돌리는 요청으로 취급한다(user.current_trip_name_override를
    다시 null로). docs/IMPLEMENTATION.md 참고.
    """

    name = serializers.CharField(required=True, allow_blank=True, max_length=100)


class PinExclusionItemSerializer(serializers.Serializer):
    """PATCH /trips/{segmentId}(4.3) 요청의 pin_exclusions 배열 원소 검증용"""

    pin_id = serializers.IntegerField()
    included_in_segment = serializers.BooleanField()


class TripPatchRequestSerializer(serializers.Serializer):
    """PATCH /trips/{segmentId} 요청 body 검증 (4.3)
    """

    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)
    pin_exclusions = PinExclusionItemSerializer(many=True, required=False)

    def validate(self, attrs):
        start_at = attrs.get("start_at")
        end_at = attrs.get("end_at")
        if start_at and end_at and start_at > end_at:
            raise serializers.ValidationError("start_at은 end_at보다 늦을 수 없습니다.")
        return attrs

class PinUpdateRequestSerializer(serializers.Serializer):
    """PATCH /pins/{pinId} 요청 body 검증 (5.2)
    place_name/text_note만 수정 가능"""

    place_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    text_note = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=500)


class PhotoRegisterItemSerializer(serializers.Serializer):
    """POST /pins/{pinId}/photos(5.5) 
    요청의 photos 배열 원소"""

    file_id = serializers.CharField()
    captured_at = serializers.DateTimeField()
    latitude = RoundedDecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)
    longitude = RoundedDecimalField(max_digits=10, decimal_places=6, required=False, allow_null=True)


class PhotoRegisterRequestSerializer(serializers.Serializer):
    """POST /pins/{pinId}/photos(5.5) 요청 body 검증"""

    photos = PhotoRegisterItemSerializer(many=True, allow_empty=False)