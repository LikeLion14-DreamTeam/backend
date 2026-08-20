"""
uploads/tokens.py
"""
import io
import uuid

import boto3
import pillow_heif
from botocore.exceptions import ClientError
from django.conf import settings
from django.core import signing
from PIL import Image, ImageOps, ImageOps

# OpenCV(cv2.imdecode)가 HEIC/HEIF를 디코딩 못 해 recommendations 스코어링이 그대로
# 죽고(#102), 브라우저도 HEIC를 직접 렌더링 못 한다. 등록 시점(resolve_and_consume)에
# JPEG로 변환해 저장하면 이후 스코어링·화면 표시 전부 일반 JPEG로 취급된다.
pillow_heif.register_heif_opener()

SALT = "uploads.file"
MAX_AGE_SECONDS = 60 * 30  # 30분 — presigned URL 만료 시간

PENDING_PREFIX = "uploads/pending/"
CONSUMED_PREFIX = "uploads/consumed/"

HEIC_CONTENT_TYPES = {"image/heic", "image/heif"}

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/aac": ".aac",
}


class FileNotUploadedError(Exception):
    """PUT(S3 presigned URL 업로드)가 아직 안 온 file_id를 참조했을 때."""


class FileAlreadyConsumedError(Exception):
    """이미 Photo/VoiceMemo에 연결된 file_id를 다시 참조했을 때."""


def _s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


def _object_exists(s3, key):
    try:
        s3.head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
            return False
        raise


def _ext_for(content_type):
    return _EXT_BY_CONTENT_TYPE.get(content_type, "")


def issue_file_token(user, file_type, content_type):
    """POST /uploads에서 호출. (file_id 토큰, uid) 튜플을 반환한다."""
    uid = uuid.uuid4().hex
    payload = {
        "uid": uid,
        "user_id": user.user_id,
        "file_type": file_type,
        "content_type": content_type,
    }
    token = signing.dumps(payload, salt=SALT)
    return token, uid


def verify_file_token(token, max_age=MAX_AGE_SECONDS):
    """서명/만료를 검증하고 payload dict를 반환한다.

    유효하지 않으면 signing.BadSignature, 만료면 signing.SignatureExpired를 던진다.
    """
    return signing.loads(token, salt=SALT, max_age=max_age)


def pending_key(uid, content_type):
    return f"{PENDING_PREFIX}{uid}{_ext_for(content_type)}"


def generate_presigned_put_url(uid, content_type, expires_in=MAX_AGE_SECONDS):
    """POST /uploads 응답의 upload_url — 프론트가 여기로 직접 PUT한다."""
    key = pending_key(uid, content_type)
    return _s3_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def _find_pending_key(s3, uid):
    """PENDING_PREFIX 아래서 uid로 시작하는 객체 key를 찾는다. 없으면 None."""
    resp = s3.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Prefix=f"{PENDING_PREFIX}{uid}")
    contents = resp.get("Contents", [])
    return contents[0]["Key"] if contents else None


def resolve_and_consume(token, *, user, expected_file_type, max_age=MAX_AGE_SECONDS):
    """
    file_id(token)를 검증하고, S3에 실제로 업로드된 파일을 pending → consumed로
    옮긴 뒤 최종 공개 URL을 반환한다. (재사용 방지: consumed에 이미 있으면 에러)
    """
    payload = verify_file_token(token, max_age=max_age)

    if payload["user_id"] != user.user_id:
        raise PermissionError("본인이 업로드한 파일이 아닙니다.")
    if payload["file_type"] != expected_file_type:
        raise ValueError(f"{expected_file_type} 타입 파일이 아닙니다.")

    uid = payload["uid"]
    s3 = _s3_client()
    bucket = settings.AWS_STORAGE_BUCKET_NAME

    pending = _find_pending_key(s3, uid)
    if not pending:
        raise FileNotUploadedError("아직 업로드가 완료되지 않은 파일입니다.")

    filename = pending.rsplit("/", 1)[-1]
    is_heic = payload["content_type"].lower() in HEIC_CONTENT_TYPES
    if is_heic:
        stem = filename.rsplit(".", 1)[0]
        consumed_key = f"{CONSUMED_PREFIX}{stem}.jpg"
    else:
        consumed_key = f"{CONSUMED_PREFIX}{filename}"

    if _object_exists(s3, consumed_key):
        raise FileAlreadyConsumedError("이미 사용된 file_id입니다.")

    if is_heic:
        pending_bytes = s3.get_object(Bucket=bucket, Key=pending)["Body"].read()
        jpeg_buffer = io.BytesIO()
        with Image.open(io.BytesIO(pending_bytes)) as image:
            # HEIC의 EXIF Orientation을 그냥 두면 화면 표시/CV 분석 양쪽에서 무시된다
            # (브라우저 img 태그는 존중하지만 cv2.imdecode는 orientation을 안 봄) — 픽셀
            # 자체를 회전/반전시켜서 저장해야 어디서 열어도 항상 올바르게 보인다.
            # exif_transpose가 회전을 픽셀에 반영한 새 이미지를 반환하므로, 그 결과를
            # JPEG로 저장하면 Orientation 태그 없이도 항상 올바른 방향으로 보인다.
            # (2026-08-20, 프론트 리포트로 발견 — docs/IMPLEMENTATION.md 참고)
            transposed = ImageOps.exif_transpose(image)
            transposed.convert("RGB").save(jpeg_buffer, format="JPEG", quality=90)
        s3.put_object(
            Bucket=bucket, Key=consumed_key, Body=jpeg_buffer.getvalue(), ContentType="image/jpeg"
        )
        s3.delete_object(Bucket=bucket, Key=pending)
    else:
        s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": pending}, Key=consumed_key)
        s3.delete_object(Bucket=bucket, Key=pending)

    return f"https://{bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{consumed_key}"
