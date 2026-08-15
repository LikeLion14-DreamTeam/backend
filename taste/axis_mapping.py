from .models import AxisCode

# 기본 질문 5문항의 선택지 문구 -> 축 값(0~100) 매핑.
# round_no(1~5)는 BasicQuestionResponse.round_no와 동일한 값이며, 각 라운드는 축 하나와 1:1 대응한다.
BASIC_QUESTION_AXIS_MAPPING = {
    1: {
        "axis_code": AxisCode.BRIGHTNESS,
        "choices": {
            "환하고 밝은 느낌": 80,
            "어둡고 무드있는 느낌": 20,
        },
    },
    2: {
        "axis_code": AxisCode.VIVIDNESS,
        "choices": {
            "선명하고 생생한 색": 80,
            "차분하고 톤 다운된 색": 20,
        },
    },
    3: {
        "axis_code": AxisCode.TONE,
        "choices": {
            "따뜻한 느낌": 80,
            "차가운 느낌": 20,
        },
    },
    4: {
        "axis_code": AxisCode.DENSITY,
        "choices": {
            "여백이 있는 여유로운 구도": 20,
            "꽉 차고 밀도 있는 구도": 80,
        },
    },
    5: {
        "axis_code": AxisCode.PHOTO_TYPE,
        "choices": {
            "그 순간 함께 한 사람들": 80,
            "그 순간의 풍경": 20,
        },
    },
}
