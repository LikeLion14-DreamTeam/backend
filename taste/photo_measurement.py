"""
taste 온보딩 고정 사진 카탈로그의 축별 실측값(0~100)을 계산하는 함수.

이 모듈은 사전계산 스크립트(precompute_photo_measurements 관리 커맨드)에서만 호출된다.
배포 서버 런타임에서는 이 모듈이 아니라 사전계산 결과(`taste/photo_measurements.py`)만
읽으므로, CLIP/torch는 로컬/CI에서 사전계산을 돌릴 때만 필요하다.

인물 감지 방식(얼굴 DNN + 전신/상반신 Haar cascade 조합)은 팀원이 2026-08-11 실제 여행
사진 40장으로 CLIP 단독 vs 하이브리드를 비교 검증한 결과를 그대로 따른 것이다 — Haar cascade
단독은 반복 패턴(키패드 등)을 얼굴로 오탐하는 사례가 실측으로 확인되어 DNN으로 교체했다.
"""

import cv2
import numpy as np
import open_clip
import torch

_CLIP_MODEL = None
_CLIP_PREPROCESS = None
_CLIP_TOKENIZER = None

_DENSITY_PROMPTS = (
    "a minimal photo with lots of empty negative space",
    "a busy, densely composed photo filling the frame",
)

_DNN_MODEL_DIR = __import__("pathlib").Path(__file__).resolve().parent / "dnn_models"
_FACE_NET = cv2.dnn.readNetFromCaffe(
    str(_DNN_MODEL_DIR / "deploy.prototxt"),
    str(_DNN_MODEL_DIR / "res10_300x300_ssd_iter_140000.caffemodel"),
)
_FACE_CONF_THRESHOLD = 0.6

_FULLBODY_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_fullbody.xml")
_UPPERBODY_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_upperbody.xml")
_BODY_MIN_NEIGHBORS = 6


def _detect_faces_dnn(image):
    h, w = image.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(image, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0))
    _FACE_NET.setInput(blob)
    detections = _FACE_NET.forward()

    max_ratio = 0.0
    count = 0
    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]
        if confidence > _FACE_CONF_THRESHOLD:
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            x1, y1, x2, y2 = box.astype(int)
            face_area = max(0, x2 - x1) * max(0, y2 - y1)
            max_ratio = max(max_ratio, face_area / (h * w))
            count += 1
    return count, max_ratio


def _detect_body_boxes(gray, cascade, image_area, h, w):
    min_size = (int(w * 0.05), int(h * 0.05))
    boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=_BODY_MIN_NEIGHBORS, minSize=min_size)
    max_ratio = max(((bw * bh) / image_area for (_, _, bw, bh) in boxes), default=0.0)
    return len(boxes), max_ratio


def _detect_person(image):
    """(사람 감지 여부, 감지된 박스 중 가장 큰 면적 비율)."""
    h, w = image.shape[:2]
    image_area = h * w
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    face_count, face_ratio = _detect_faces_dnn(image)
    fullbody_count, fullbody_ratio = _detect_body_boxes(gray, _FULLBODY_CASCADE, image_area, h, w)
    upperbody_count, upperbody_ratio = _detect_body_boxes(gray, _UPPERBODY_CASCADE, image_area, h, w)

    person_found = face_count > 0 or fullbody_count > 0 or upperbody_count > 0
    max_ratio = max(face_ratio, fullbody_ratio, upperbody_ratio)
    return person_found, max_ratio


def _get_clip():
    global _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_TOKENIZER
    if _CLIP_MODEL is None:
        _CLIP_MODEL, _, _CLIP_PREPROCESS = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai"
        )
        _CLIP_MODEL.eval()
        _CLIP_TOKENIZER = open_clip.get_tokenizer("ViT-B-32")
    return _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_TOKENIZER


def load_image(path):
    """BGR(cv2 기본 채널 순서) numpy 배열로 이미지를 읽는다."""
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    return image


def get_image_embedding(image):
    """CLIP 이미지 임베딩(정규화됨) — recommendations 앱의 유사 사진 판별에 재사용된다."""
    model, preprocess, _tokenizer = _get_clip()
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    from PIL import Image as PILImage

    pil_image = PILImage.fromarray(rgb)

    with torch.no_grad():
        image_input = preprocess(pil_image).unsqueeze(0)
        image_features = model.encode_image(image_input)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)

    return image_features.squeeze(0).numpy()


def measure_brightness(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    v_mean = hsv[:, :, 2].mean()
    return float(v_mean / 255 * 100)


def measure_vividness(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    s_mean = hsv[:, :, 1].mean()
    return float(s_mean / 255 * 100)


def measure_tone(image):
    # cv2는 BGR 순서라 채널 0=B, 2=R
    b_mean = image[:, :, 0].mean()
    r_mean = image[:, :, 2].mean()
    diff = r_mean - b_mean  # -255 ~ 255, 따뜻할수록(R 우세) 큼
    return float(np.clip((diff + 128) / 255 * 100, 0, 100))


def _measure_density_clip(image):
    model, preprocess, tokenizer = _get_clip()
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    from PIL import Image as PILImage

    pil_image = PILImage.fromarray(rgb)

    with torch.no_grad():
        image_input = preprocess(pil_image).unsqueeze(0)
        text_input = tokenizer(list(_DENSITY_PROMPTS))

        image_features = model.encode_image(image_input)
        text_features = model.encode_text(text_input)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

        similarity = (100.0 * image_features @ text_features.T).softmax(dim=-1)
        dense_prob = similarity[0, 1].item()  # index 1 = "꽉 차고 밀도 있는" 쪽 확률

    return dense_prob * 100


def _measure_density_edges(image):
    """Canny 엣지 비율 — 여백이 많은 구도는 엣지가 적고, 꽉 찬/복잡한 구도는 엣지가 많다."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    edge_ratio = (edges > 0).mean()
    return float(np.clip(edge_ratio * 600, 0, 100))


def measure_density(image):
    # 스펙상 "CLIP + 인물크기(OpenCV) 병합" 방식 — 인물 크기 대신 엣지 밀도로 "얼마나 꽉
    # 찼는지"를 보완 측정(인물이 없는 풍경 사진도 밀도를 가질 수 있어 더 일반적인 대체 신호).
    clip_score = _measure_density_clip(image)
    edge_score = _measure_density_edges(image)
    return float(0.5 * clip_score + 0.5 * edge_score)


def measure_photo_type(image):
    """인물(높은 값) vs 풍경(낮은 값). 얼굴 DNN + 전신/상반신 Haar cascade 중 하나라도
    사람을 감지하면 인물 쪽으로, 셋 다 못 찾으면 풍경 쪽으로 판정한다."""
    person_found, area_ratio = _detect_person(image)
    if not person_found:
        return 15.0
    return float(np.clip(55 + area_ratio * 600, 0, 100))


MEASURE_FUNCTIONS = {
    "brightness": measure_brightness,
    "vividness": measure_vividness,
    "tone": measure_tone,
    "density": measure_density,
    "photo_type": measure_photo_type,
}


def measure_all_axes(image):
    return {axis_code: func(image) for axis_code, func in MEASURE_FUNCTIONS.items()}
