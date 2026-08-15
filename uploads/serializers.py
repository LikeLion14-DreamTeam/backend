from rest_framework import serializers

FILE_TYPE_CHOICES = [
    ("photo", "사진"),
    ("voice", "음성"),
]


class UploadRequestSerializer(serializers.Serializer):
    """POST /uploads 요청 body 검증."""

    file_type = serializers.ChoiceField(choices=FILE_TYPE_CHOICES)
    content_type = serializers.CharField()
