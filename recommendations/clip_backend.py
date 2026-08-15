"""
recommendations 앱이 쓰는 CLIP 임베딩/축 실측 함수의 디스패처.

`taste.photo_measurement`의 `get_image_embedding`/`measure_all_axes`는 CLIP/torch를
그 자리에서 직접 로드해서 실행한다 — 배포 서버(EC2 t3.micro, 메모리 1GiB)에는 이걸 감당할
여유가 없어(2026-08-16 결정, docs/IMPLEMENTATION.md 참고), 실제 CLIP 연산은 별도 Lambda
컨테이너(`lambda_clip_service/`)로 위임한다.

`settings.CLIP_BACKEND`로 두 모드를 전환한다:
- "local"(기본값, 테스트/로컬 개발용): `taste.photo_measurement`를 그대로 로컬에서 호출.
  기존 recommendations 테스트가 AWS 자격증명 없이도 그대로 통과하게 하려고 기본값을
  local로 둔다 — 절대 이 기본값을 바꾸지 말 것.
- "lambda"(배포 환경): 이미지를 JPEG로 인코딩 → base64 → `boto3` Lambda `invoke()`로
  전달, 응답 JSON을 같은 반환 형식으로 파싱해서 돌려준다.

`recommendations/scoring.py`는 `taste.photo_measurement`를 직접 import하지 않고 이 모듈을
통해서만 호출한다 — 그래야 scoring.py 쪽 코드 변경 없이 백엔드만 전환할 수 있다.

**`taste.photo_measurement`(torch/opencv/open_clip) import는 반드시 함수 안에서 지연
로딩할 것 — 파일 최상단에서 import하지 않는다.** `travel/views.py`가 모듈 최상단에서
`recommendations.travel_adapter`를 import하기 때문에(→ `scoring.py` → 이 모듈), Django
서버가 뜨는 순간 URL 라우팅 단계에서 이 모듈이 로드된다. 여기서 `taste.photo_measurement`를
최상단에서 import해버리면 `CLIP_BACKEND` 값과 무관하게 서버 기동 시점에 torch/CLIP이 항상
메모리에 올라가버려서, EC2 t3.micro(메모리 1GiB)에 배포한 의미가 없어진다(2026-08-16 확인).
"""

import base64
import json

from django.conf import settings


class ClipBackendError(Exception):
    """Lambda 호출 실패 또는 Lambda가 {"error": ...} 응답을 돌려줬을 때."""


def _lambda_client():
    import boto3

    return boto3.client(
        "lambda",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


def _encode_image(image):
    """cv2 BGR numpy 배열 -> JPEG base64 문자열."""
    import cv2

    ok, buffer = cv2.imencode(".jpg", image)
    if not ok:
        raise ClipBackendError("이미지를 JPEG로 인코딩하지 못했습니다.")
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _invoke_lambda(image, mode):
    payload = {"image_base64": _encode_image(image), "mode": mode}
    response = _lambda_client().invoke(
        FunctionName=settings.CLIP_LAMBDA_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    body = json.loads(response["Payload"].read())

    if "FunctionError" in response or "error" in body:
        raise ClipBackendError(body.get("error", "Lambda 호출 실패 (원인 불명)"))
    return body


def get_image_embedding(image):
    if settings.CLIP_BACKEND == "lambda":
        import numpy as np

        body = _invoke_lambda(image, "embedding")
        return np.array(body["embedding"])

    from taste.photo_measurement import get_image_embedding as _local_get_image_embedding

    return _local_get_image_embedding(image)


def measure_all_axes(image):
    if settings.CLIP_BACKEND == "lambda":
        body = _invoke_lambda(image, "axes")
        return body["axes"]

    from taste.photo_measurement import measure_all_axes as _local_measure_all_axes

    return _local_measure_all_axes(image)
