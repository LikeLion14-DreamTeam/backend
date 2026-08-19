import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication

from .models import NfcTag

request_logger = logging.getLogger("request_logger")


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def my_products(request):
    """
    GET /users/me/products — 등록 제품 목록 조회 (7.1)
    """
    tags = NfcTag.objects.filter(user=request.user, unlinked_at__isnull=True).order_by("registered_at")
    return Response(
        {
            "products": [
                {
                    "tag_id": tag.tag_id,
                    "product_type": tag.product_type.upper(),
                    "product_name": tag.product_name,
                    "registered_at": tag.registered_at,
                    "tagging_count": tag.tag_count,
                }
                for tag in tags
            ]
        }
    )


@api_view(["PATCH"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def product_unlink(request, tag_id):
    """
    PATCH /products/{tagId}/unlink — 제품 연결 해제 (7.2)
    """
    try:
        tag = NfcTag.objects.get(pk=tag_id, user=request.user, unlinked_at__isnull=True)
    except NfcTag.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    tag.user = None
    tag.unlinked_at = timezone.now()
    tag.save(update_fields=["user", "unlinked_at"])

    request_logger.info("PATCH /products/%s/unlink", tag_id)
    return Response({"tag_id": tag.tag_id, "user_id": None})


@api_view(["PATCH"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def product_link(request, tag_id):
    """
    PATCH /products/{tagId}/link — 태그 자동 등록/연결 (8.1)
    """
    tag, created = NfcTag.objects.get_or_create(
        pk=tag_id,
        defaults={"user": request.user, "product_type": "bag", "product_name": "Ottomar 비세토스 위켄더"},
    )

    # TODO(demo): 시연 기간 동안 하나의 NFC 태그로 여러 계정이 반복 시연해야 해서, 다른
    # 계정에 이미 연결된 태그라도 태깅한 계정으로 소유권을 즉시 넘기도록 8.1의 409 CONFLICT
    # 보호를 임시로 비활성화함. 시연 종료 후 원복 필요.
    if not created:
        if tag.user_id != request.user.user_id or tag.unlinked_at is not None:
            tag.user = request.user
            tag.unlinked_at = None
            tag.save(update_fields=["user", "unlinked_at"])

    request_logger.info("PATCH /products/%s/link created=%s", tag_id, created)
    return Response({"tag_id": tag.tag_id, "user_id": tag.user_id, "registered_at": tag.registered_at})
