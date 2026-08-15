# 취향 온보딩 A/B·무드보드 고정 사진 카탈로그 매니페스트.
# round_no -> {axis_code, sets: [{set_no, photos: [{photo_id, value?}]}]}
#
# A/B(round_no 1~5)의 `value`는 기획 단계에서 "이 사진은 축의 20/80 쪽"이라고 큐레이션한
# 값이며, **온보딩 완료 시 실제 축 계산에도 이 값을 그대로 사용한다** (2026-08-15 결정 —
# 사진별 실측값은 노이즈가 있어 A/B처럼 이미 의도가 확정된 큐레이션 사진에는 매니페스트
# 참조값이 더 안정적). `taste/photo_measurements.py`의 실측값은 이 참조값과 방향이
# 일치하는지 검증하는 QA 용도로만 쓴다.
# 무드보드(round_no 6~7)는 사전 참조값이 없다 — `taste/photo_measurements.py`의 실측값을
# 그대로 축 계산에 사용한다 (6라운드는 density만, 7라운드는 5개 축 전부).

PHOTO_CATALOG_MANIFEST = {
    1: {
        "axis_code": "brightness",
        "sets": [
            {"set_no": 1, "photos": [{"photo_id": 1001, "value": 20}, {"photo_id": 1002, "value": 80}]},
            {"set_no": 2, "photos": [{"photo_id": 1003, "value": 20}, {"photo_id": 1004, "value": 80}]},
            {"set_no": 3, "photos": [{"photo_id": 1005, "value": 20}, {"photo_id": 1006, "value": 80}]},
        ],
    },
    2: {
        "axis_code": "vividness",
        "sets": [
            {"set_no": 1, "photos": [{"photo_id": 2001, "value": 20}, {"photo_id": 2002, "value": 80}]},
            {"set_no": 2, "photos": [{"photo_id": 2003, "value": 20}, {"photo_id": 2004, "value": 80}]},
            {"set_no": 3, "photos": [{"photo_id": 2005, "value": 20}, {"photo_id": 2006, "value": 80}]},
        ],
    },
    3: {
        "axis_code": "tone",
        "sets": [
            {"set_no": 1, "photos": [{"photo_id": 3001, "value": 20}, {"photo_id": 3002, "value": 80}]},
            {"set_no": 2, "photos": [{"photo_id": 3003, "value": 20}, {"photo_id": 3004, "value": 80}]},
            {"set_no": 3, "photos": [{"photo_id": 3005, "value": 20}, {"photo_id": 3006, "value": 80}]},
        ],
    },
    4: {
        "axis_code": "density",
        "sets": [
            {"set_no": 1, "photos": [{"photo_id": 4001, "value": 20}, {"photo_id": 4002, "value": 80}]},
            {"set_no": 2, "photos": [{"photo_id": 4003, "value": 20}, {"photo_id": 4004, "value": 80}]},
            {"set_no": 3, "photos": [{"photo_id": 4005, "value": 20}, {"photo_id": 4006, "value": 80}]},
        ],
    },
    5: {
        "axis_code": "photo_type",
        "sets": [
            {"set_no": 1, "photos": [{"photo_id": 5001, "value": 20}, {"photo_id": 5002, "value": 80}]},
            {"set_no": 2, "photos": [{"photo_id": 5003, "value": 20}, {"photo_id": 5004, "value": 80}]},
            {"set_no": 3, "photos": [{"photo_id": 5005, "value": 20}, {"photo_id": 5006, "value": 80}]},
        ],
    },
    6: {
        # 거리(가까이/중경/멀리) x 방향(정면/측면(왼쪽)/뒷모습) 3x3 그리드, 업로드 순서 그대로
        # (2026-08-15 사용자 확인·정정). density 신호로만 쓰이고 이 라벨은 taste 텍스트의
        # 구도 선호 문구 생성에 쓰인다.
        "axis_code": None,
        "sets": [
            {
                "set_no": 1,
                "photos": [
                    {"photo_id": 6001, "distance": "가까이", "direction": "정면"},
                    {"photo_id": 6002, "distance": "가까이", "direction": "측면"},
                    {"photo_id": 6003, "distance": "가까이", "direction": "뒷모습"},
                    {"photo_id": 6004, "distance": "중경", "direction": "정면"},
                    {"photo_id": 6005, "distance": "중경", "direction": "측면"},
                    {"photo_id": 6006, "distance": "중경", "direction": "뒷모습"},
                    {"photo_id": 6007, "distance": "멀리", "direction": "정면"},
                    {"photo_id": 6008, "distance": "멀리", "direction": "측면"},
                    {"photo_id": 6009, "distance": "멀리", "direction": "뒷모습"},
                ],
            },
        ],
    },
    7: {
        "axis_code": None,
        "sets": [
            {
                "set_no": set_no,
                "photos": [{"photo_id": 7000 + (set_no - 1) * 9 + i} for i in range(1, 10)],
            }
            for set_no in (1, 2, 3)
        ],
    },
}

