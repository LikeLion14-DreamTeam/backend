from rest_framework import serializers


class PhotobookUpdateRequestSerializer(serializers.Serializer):
    """PATCH /photobooks/{photobookId} 요청 body 검증 (6.3)"""

    name = serializers.CharField(max_length=100)
