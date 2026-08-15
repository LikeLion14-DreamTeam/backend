"""
uploads/views.py
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication

from .serializers import UploadRequestSerializer
from .tokens import MAX_AGE_SECONDS, generate_presigned_put_url, issue_file_token


@api_view(["POST"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def request_upload(request):
    """POST /uploads — S3 presigned URL 발급 (파일 업로드 2단계 계약 1단계)"""
    serializer = UploadRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    file_type = serializer.validated_data["file_type"]
    content_type = serializer.validated_data["content_type"]

    token, uid = issue_file_token(request.user, file_type, content_type)
    expires_at = timezone.now() + timezone.timedelta(seconds=MAX_AGE_SECONDS)
    upload_url = generate_presigned_put_url(uid, content_type)

    return Response(
        {"upload_url": upload_url, "file_id": token, "expires_at": expires_at},
        status=status.HTTP_200_OK,
    )
