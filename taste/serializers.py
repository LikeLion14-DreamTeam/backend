from django.core.validators import MaxValueValidator, MinValueValidator
from rest_framework import serializers

from .models import BasicQuestionResponse, SelectionPhoto, TasteProfileAxis


class BasicQuestionResponseSerializer(serializers.ModelSerializer):
    response_id = serializers.IntegerField(source="id", read_only=True)
    response = serializers.CharField(source="answer", max_length=100)
    round_no = serializers.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    class Meta:
        model = BasicQuestionResponse
        fields = ["response_id", "user_id", "round_no", "response", "answered_at"]
        read_only_fields = ["user_id", "answered_at"]


class SelectionPhotoSerializer(serializers.ModelSerializer):
    round_no = serializers.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)]
    )

    class Meta:
        model = SelectionPhoto
        fields = ["photo_id", "user_id", "round_no", "status", "selected_at"]
        read_only_fields = ["user_id", "selected_at"]


class TasteProfileAxisSerializer(serializers.ModelSerializer):
    class Meta:
        model = TasteProfileAxis
        fields = ["axis_code", "value", "status"]
        read_only_fields = fields


class TasteProfileAxisUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TasteProfileAxis
        fields = ["axis_code", "user_id", "value", "status"]
        read_only_fields = ["axis_code", "user_id", "status"]
