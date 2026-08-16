"""
taste 온보딩 고정 사진 카탈로그의 축별 실측값(0~100)을 계산하는 함수.

taste 온보딩 자체는 사전계산 스크립트(precompute_photo_measurements 관리 커맨드)에서만
이 모듈을 호출하고, 배포 서버 런타임에서는 사전계산 결과(`taste/photo_measurements.py`)만
읽는다.

⚠️ 2026-08-16: `recommendations` 앱(#71~)이 이 모듈의 `compute_phash`/`measure_all_axes`를
실제 유저 여행 사진 스코어링에 재사용한다 — "로컬/CI 사전계산 전용"이 아니라 운영 서버
런타임에서도 매 요청마다 호출된다.

2026-08-16(#94): CLIP(open-clip-torch/torch) 의존성을 완전히 제거했다. 원래 유사사진
판별에 CLIP 임베딩+코사인유사도를, 구도/밀도(density) 축 측정에 CLIP+엣지검출 블렌드를
썼는데, 사진 1장당 CLIP 순전파가 2번씩 들어가는 게 MVP 단계 인프라 부담(EC2 메모리,
docs/TEMP_NOTES.md의 배포 미해결 이슈) 대비 과하다는 판단. 유사사진 판별은
perceptual hash(pHash)로 교체(원본 기능명세서가 애초에 "perceptual hash + 시간 근접도"를
명시하고 있어 스펙에 더 가깝게 되돌아간 것). density는 CLIP 없이 블러+엣지검출 단독으로
교체 — 엣지검출만 쓰면 미세 텍스처(모래 잔물결 등)와 구도상 여백을 구분 못해 방향이
틀리는 사례가 실측(온보딩 큐레이션 사진)으로 확인됐으나, Canny 엣지검출 전에 가우시안
블러를 넣어 미세 텍스처를 뭉개니 큐레이션 사진 3쌍 전부 방향이 정확해짐을 확인하고 채택.
자세한 근거는 docs/IMPLEMENTATION.md 결정 로그 참고.

인물 감지 방식(얼굴 DNN + 전신/상반신 Haar cascade 조합)은 팀원이 2026-08-11 실제 여행
사진 40장으로 CLIP 단독 vs 하이브리드를 비교 검증한 결과를 그대로 따른 것이다 — Haar cascade
단독은 반복 패턴(키패드 등)을 얼굴로 오탐하는 사례가 실측으로 확인되어 DNN으로 교체했다.
"""

import cv2
import numpy as np

_PHASH_SIZE = 8  # 해시 한 변 길이 — 8이면 64비트 해시
_PHASH_IMAGE_SIZE = _PHASH_SIZE * 4  # DCT 전 리사이즈 크기 (고주파 영역 확보용)

_DENSITY_BLUR_KSIZE = 11  # 엣지검출 전 가우시안 블러 커널 — 미세 텍스처(모래 등) 제거용
_DENSITY_EDGE_SCALE = 3500.0  # 블러 후 엣지 비율 → 0~100 스케일링 상수. density 큐레이션
# 사진(4001~4006)뿐 아니라 카탈로그 전체 66장의 raw 엣지 비율 분포(90th percentile≈0.027)
# 기준으로 과도한 상한(100) 클리핑을 줄이도록 재보정함 (2026-08-16, #94).

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


def load_image(path):
    """BGR(cv2 기본 채널 순서) numpy 배열로 이미지를 읽는다."""
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    return image


def compute_phash(image):
    """perceptual hash(pHash, DCT 기반) — recommendations 앱의 유사 사진 판별에 재사용된다.
    64비트(8x8) 불리언 배열을 반환하며, 두 해시의 해밍 거리로 유사도를 비교한다
    (`hamming_distance` 참고). CLIP 임베딩 대신 채택 — 원본 기능명세서가 애초에
    "perceptual hash + 시간 근접도"를 명시하고 있음 (#94, docs/IMPLEMENTATION.md 참고)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (_PHASH_IMAGE_SIZE, _PHASH_IMAGE_SIZE), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    dct_low = dct[:_PHASH_SIZE, :_PHASH_SIZE]
    median = np.median(dct_low)
    return dct_low > median


def hamming_distance(hash_a, hash_b):
    """두 pHash(불리언 배열) 사이의 해밍 거리 — 값이 작을수록 비슷한 사진."""
    return int(np.count_nonzero(hash_a != hash_b))


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


def measure_density(image):
    """Canny 엣지 비율 — 여백이 많은 구도는 엣지가 적고, 꽉 찬/복잡한 구도는 엣지가 많다.
    엣지검출 전에 가우시안 블러를 넣어 모래알·잔물결 같은 미세 텍스처를 뭉개고, 바위 윤곽선
    같은 굵은 구조적 경계만 남긴다 — 블러 없이 엣지검출만 쓰면 "텍스처는 많지만 여백은 넓은"
    사진(예: 모래사막)에서 방향이 뒤집히는 사례가 실측으로 확인됨 (#94, docs/IMPLEMENTATION.md
    참고). 이전에는 CLIP 결과와 50:50 블렌딩했으나, 블러 추가로 CLIP 없이도 큐레이션된
    검증 사진에서 정확한 방향이 나와 CLIP 절반을 제거했다.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (_DENSITY_BLUR_KSIZE, _DENSITY_BLUR_KSIZE), 0)
    edges = cv2.Canny(blurred, 100, 200)
    edge_ratio = (edges > 0).mean()
    return float(np.clip(edge_ratio * _DENSITY_EDGE_SCALE, 0, 100))


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
