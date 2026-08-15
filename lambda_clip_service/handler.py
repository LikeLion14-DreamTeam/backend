"""
Lambda 진입점(clip-scoring 함수).

boto3 invoke(RequestResponse, 동기)로 호출된다고 가정한다. Payload 예시:

    {"image_base64": "<jpeg base64>", "mode": "embedding"}
    -> {"embedding": [0.1, 0.2, ...]}

    {"image_base64": "<jpeg base64>", "mode": "axes"}
    -> {"axes": {"brightness": 62.3, "vividness": ..., "tone": ..., "density": ..., "photo_type": ...}}

에러 시 {"error": "메시지"} 반환(예외를 그대로 올리지 않음 — 호출 쪽(Django)에서
`"error" in response` 로 판별하도록).
"""

import base64

import cv2
import numpy as np

from photo_measurement import get_image_embedding, measure_all_axes


def _decode_image(image_base64):
    raw = base64.b64decode(image_base64)
    array = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("이미지 디코딩 실패 — 올바른 JPEG/PNG base64인지 확인 필요")
    return image


def lambda_handler(event, context):
    try:
        mode = event.get("mode")
        image_base64 = event.get("image_base64")
        if not image_base64:
            return {"error": "image_base64가 없습니다."}
        if mode not in ("embedding", "axes"):
            return {"error": f"알 수 없는 mode: {mode!r} (embedding 또는 axes만 지원)"}

        image = _decode_image(image_base64)

        if mode == "embedding":
            embedding = get_image_embedding(image)
            return {"embedding": embedding.tolist()}

        axes = measure_all_axes(image)
        return {"axes": axes}

    except Exception as exc:  # noqa: BLE001 — Lambda 응답으로 에러를 그대로 돌려주기 위해 광범위하게 잡음
        return {"error": f"{type(exc).__name__}: {exc}"}
