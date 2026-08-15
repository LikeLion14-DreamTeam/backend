from rest_framework import serializers


class TripCreateRequestSerializer(serializers.Serializer):
    """POST /trips 요청 body 검증 (3.2, 여행 종료)"""

    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    end_at = serializers.DateTimeField(required=False, allow_null=True)


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