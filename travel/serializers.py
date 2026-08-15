from rest_framework import serializers


class TripCreateRequestSerializer(serializers.Serializer):
    """POST /trips 요청 body 검증 (3.2, 여행 종료)"""

    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    end_at = serializers.DateTimeField(required=False, allow_null=True)