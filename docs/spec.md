# spec.md

이 문서는 참조 전용입니다. 이 문서 자체를 수정하지 않습니다. 스펙과 다르게 구현하기로 결정한 사항은
`docs/IMPLEMENTATION.md`에 별도로 기록합니다.

---

## 0. 원본 스펙 최신화 상태 체크리스트

`Orte_기능명세서_v1.md`(원본)는 팀 논의가 진행되며 일부 최신화가 안 된 부분이 있습니다.
**아래 목록에 있는 항목은 이 표(spec.md)의 내용을 원본보다 우선 적용**하고, 목록에 없는 부분은
원본을 그대로 신뢰해도 됩니다. 새로운 결정이 나올 때마다 이 표에 행을 추가합니다.

| 항목 | 원본 스펙 내용 | 확정된 최신 내용 | 상태 |
|---|---|---|---|
| 기본 질문 문항 수 | 7문항, 적응형 분기(인물/풍경 상위축 → 세부축) | 5문항, A/B 5쌍과 1:1 대응 축(밝기·채도·색온도·구도·사진종류) | ✅ 반영 완료 |
| 마이페이지 슬라이더 축 개수 | 6개 | 6개 유지 (5문항+A/B로 4축, 무드보드 1라운드로 distance·angle 2축 커버) | ✅ 반영 완료 (축소 검토했으나 유지로 결론) |
| 온보딩 마지막 자유 텍스트 프롬프트 | 원문에 없음 (팀 제안이었으나 미반영 상태) | 스코프 아웃 확정 — 추가하지 않음 | ✅ 반영 완료 |
| 5.1.2 핀 수동 입력 시 좌표 출처 | (구) "세션 시작 시점의 위치 좌표를 저장"이라고만 명시, 사진과의 관계 불명확 | **[Orte_기능명세서_v1 반영]** 5.1.2가 전면 개정됨 — 촬영 흐름 대신 2단계(위치 지정 화면에서 지도 드래그로 좌표 확정 → 정보 입력 화면에서 사진 업로드) 구조로 변경. 좌표는 여전히 지도 지정(사진 아님)으로 결정되어 기존 "핀 우선" 결론과 합치. 다만 **시각(시간) 필드만** 업로드 사진 중 가장 이른 촬영 시각으로 자동 입력 — 좌표와 시각의 출처가 서로 다름에 유의 | ✅ 반영 완료 |
| 재추천(5.2.3) 결과 산출 방식 | (구) "새로 선정한 대표 사진 3장으로 교체"까지만 명시, 방식 불명확 | **[Orte_기능명세서_v1에서 공식 반영]** 상위 10장 후보 중 3장 랜덤 셔플로 확정, 프로파일 불변. 우리가 정했던 내용이 원문에 그대로 채택됨 — 더 이상 "우리 임의 확정"이 아니라 스펙 원문 자체가 이 로직 | ✅ 반영 완료 (원문과 완전 일치) |
| 재추천 시 후보 10장 미만 처리 | (구) 원문엔 "3장 이하면 재추천 미제공"만 명시 | **[Orte_기능명세서_v1에서 확정]** 10장 미만이면 등록된 사진 전체를 후보로 사용. 후보가 정확히 3장이면 무작위 선정 없이 그대로 사용하고 "더 제안할 조합 없음" 안내 표시 | ✅ 반영 완료 (옵션 A로 확정) |
| 온보딩 순서 재구성 시 여정 종료 흐름 | (구) 진행 중 여정 종료는 3.1에서만 트리거 | v1에서 여행 구간 관리가 홈에서 제거되어 아카이브로 이동. 진행 중 여정 카드에는 구간 관리 진입점 자체가 없어짐 (종료된 여정만 구간 관리 가능) | ✅ 반영 완료 (taste/recommendations 직접 영향 없음, 참고용) |
| MCM_PRODUCT PK 구성 | (구) 다이어그램상 `tag_id`+`user_id` 복합 PK | `tag_id` 단일 PK로 확정 (SQL export 기준) | ✅ 반영 완료 |
| ERD의 FK 제약 누락 | SQL export엔 3개 FK만 존재 (TASTE_PROFILE_AXIS, COUNTRY_STAMP, TASTE_PROFILE → USER) | 다이어그램에 그려진 관계선은 전부 유효한 관계로 간주하고 Django `models.ForeignKey`로 구현. SQL 파일 자체는 최종 DDL이 아닌 설계 스냅샷으로 취급 | ✅ 반영 완료 |
| 무드보드 1라운드 캐릭터 소재 | 원문에 언급 없음 (사진 페어/무드보드 소재 미지정) | 브랜드 톤 유지한 3D 마스코트 캐릭터(사자 또는 사람)로 확정, 프롬프트 별도 문서 관리 | ✅ 반영 완료 (구현과 무관, 에셋 결정) |
| 마이페이지 슬라이더 축 개수 (재정정) | (구) 위 행에서 "6개 유지"로 정리했었음 | **5개로 정정.** 기본질문 5개·A/B 5쌍이 1:1로 검증하는 축(밝기·채도·색온도·구도와 밀도·사진종류)만 슬라이더/축으로 사용. 별도 distance·angle 축은 만들지 않음 — taste 앱 모델 설계(#26) 중 확정 | ✅ 반영 완료 (2026-08-14) |
| 무드보드 2라운드 결과의 축 반영 방식 | 원문에 구체적 반영 방식 없음 | 무드보드 1라운드(캐릭터 각도·거리 9장 중 3장, 구도 선호)와 2라운드(여행사진 9장 중 3장, 선택 사진 분석)는 **모두 `density`(구도와 밀도) 축을 포함한 5개 축에 대한 추가 신호**로 반영. 별도 축을 새로 만들지 않고 기존 5축 체계에 신호만 더하는 구조 | ✅ 반영 완료 (2026-08-14) |

> 검토 필요 항목이 새로 발견되면 이 표에 먼저 추가하고, 결정되면 상태를 ✅로 바꾸면서
> `docs/IMPLEMENTATION.md`에도 같은 내용을 결정 로그로 남깁니다.

---

## 1. ERD (2026.08 기준, `Orte_sql_v1.sql` 반영)

### USER
| 필드 | 타입 | 비고 |
|---|---|---|
| user_id (PK) | INT | |
| email | VARCHAR(150) | |
| created_at | DATETIME | |
| onboarding_completed | BOOLEAN | |
| permission_intro_shown | BOOLEAN | |
| account_identifier | VARCHAR(150) | |

### TASTE_PROFILE
| 필드 | 타입 | 비고 |
|---|---|---|
| user_id (PK, FK→USER) | INT | |
| last_updated_at | DATETIME | |
| taste | TEXT | |

### TASTE_PROFILE_AXIS
| 필드 | 타입 | 비고 |
|---|---|---|
| axis_code (PK) | VARCHAR(50) | 예: brightness, vividness, tone, density, photo_type (5축 확정안 기준) |
| user_id (PK, FK→USER) | INT | |
| value | INT | |
| status | ENUM('REFLECTED','PENDING') | |

### BASIC_QUESTION_RESPONSE
| 필드 | 타입 | 비고 |
|---|---|---|
| response_id (PK) | INT | |
| user_id (FK→USER) | INT | |
| round_no | INT | |
| answer | VARCHAR(100) | |
| answered_at | DATETIME | |

### SELECTION_PHOTO
| 필드 | 타입 | 비고 |
|---|---|---|
| selection_photo_id (PK) | INT | |
| user_id (FK→USER) | INT | |
| round_no | INT | |
| status | BOOLEAN | |
| selected_at | DATETIME | |

### COUNTRY_STAMP
| 필드 | 타입 | 비고 |
|---|---|---|
| country_code (PK) | INT | |
| user_id (PK, FK→USER) | INT | |
| country_name | VARCHAR(50) | |

### MCM_PRODUCT
| 필드 | 타입 | 비고 |
|---|---|---|
| tag_id (PK) | VARCHAR(100) | 단일 PK로 확정 (2026.08) |
| user_id (FK→USER) | INT | |
| product_type | VARCHAR(30) | |
| product_name | VARCHAR(100) | |
| registered_at | DATETIME | |
| tag_count | INT | |
| unlinked_at | DATETIME | |

### TRAVEL_SEGMENT
| 필드 | 타입 | 비고 |
|---|---|---|
| segment_id (PK) | INT | |
| user_id (FK→USER) | INT | |
| name | VARCHAR(100) | |
| start_at | DATETIME | |
| end_at | DATETIME | |
| status | BOOLEAN | |
| cover_photo_url | VARCHAR(500) | |

### PIN
| 필드 | 타입 | 비고 |
|---|---|---|
| pin_id (PK) | INT | |
| segment_id (FK→TRAVEL_SEGMENT) | INT | |
| photobook_id (FK→PHOTOBOOK) | INT | |
| latitude | DECIMAL(10,6) | |
| longitude | DECIMAL(10,6) | |
| address | VARCHAR(300) | |
| place_name | VARCHAR(150) | |
| tagged_at | DATETIME | |
| text_note | VARCHAR(500) | |
| saved_at | DATETIME | |
| city | VARCHAR(100) | |
| included_in_segment | BOOLEAN | |

### PHOTO
| 필드 | 타입 | 비고 |
|---|---|---|
| photo_id (PK) | INT | |
| pin_id (FK→PIN) | INT | |
| captured_at | DATETIME | |
| latitude | DECIMAL(10,6) | |
| longitude | DECIMAL(10,6) | |
| source_type | VARCHAR(30) | 촬영/업로드 |
| photo_url | VARCHAR(500) | |
| is_main | BOOLEAN | |

### VOICE_MEMO
| 필드 | 타입 | 비고 |
|---|---|---|
| voice_memo_id (PK) | INT | |
| pin_id (FK→PIN) | INT | |
| audio_url | VARCHAR(255) | |
| saved_at | DATETIME | |

### PHOTOBOOK
| 필드 | 타입 | 비고 |
|---|---|---|
| photobook_id (PK) | INT | |
| segment_id (FK→TRAVEL_SEGMENT) | INT | |
| cover_photo_id (FK→PHOTO) | INT | |
| title | VARCHAR(100) | |
| generated_at | DATETIME | |

### 앱-모델 매핑

| 앱 | 담당 도메인 | 포함 모델 |
|---|---|---|
| accounts | 계정·인증 | User, Session |
| taste | 취향 프로파일 온보딩 | TasteProfile, TasteProfileAxis, OnboardingProgress, BasicQuestionResponse, SelectionPhoto, ProfileRetrainHistory |
| recommendations | 추천 | RecommendationResult, RecommendationEdit, RecommendationRegenHistory |
| products | NFC 제품 | NfcTag |
| travel | 여행 기록 핵심 | TravelSegment, Pin, TaggingSession, Photo, VoiceMemo, CountryStamp |
| photobooks | 포토북 | Photobook, PhotobookPin, PhotobookPhotoLayout |

> 참고: `OnboardingProgress`, `ProfileRetrainHistory`, `RecommendationResult`, `RecommendationEdit`,
> `RecommendationRegenHistory`는 ERD 다이어그램에는 아직 반영되지 않았고 기능명세서 데이터 항목 기준으로
> taste/recommendations 앱에서 신규 설계가 필요함. 설계 확정 시 `docs/IMPLEMENTATION.md`에 필드 정의를 남길 것.
> (`ABSelectionLog`는 검토 후 제외 확정 — `SelectionPhoto`가 A/B+무드보드 선택을 통합 관리. 2026-08-14,
> `docs/IMPLEMENTATION.md` 결정 로그 참고)

### 온보딩 설문 구조 (2026.08 확정, 기능명세서보다 최신)

- 기본 질문: 7문항 → **5문항으로 축소 확정**. A/B 5쌍과 1:1 대응하는 축만 사용.
  - Q1 밝기(brightness), Q2 채도(vividness), Q3 색온도(tone), Q4 구도/밀도(density), Q5 사진종류(인물/풍경)
  - 말로 답한 것(기본질문)과 실제 고른 것(A/B)의 크로스체크 목적으로 축이 의도적으로 중복됨.
- A/B 5쌍: 위 5축과 1:1 대응, AI 실측 방식은 아래 표 참조.

| 라운드 | 검증 축 | AI 측정 방식 |
|---|---|---|
| 1 | brightness | 픽셀 계산 (HSV 명도) |
| 2 | vividness | 픽셀 계산 (HSV 채도) |
| 3 | tone | 픽셀 계산 (R-B 채널 차) |
| 4 | density | CLIP + 인물크기(OpenCV) 병합 |
| 5 | 사진종류 | OpenCV 사람 감지 |

- 무드보드 2라운드:
  - 1라운드: 거리(클로즈업/중경/광각) × 방향(정면/측면/뒷모습) 3×3=9장 중 3장 선택. distance·angle 축 계측.
    angle 측정은 OpenAI Vision API 신규 구현(`analyze_direction`) 필요.
  - 2라운드: 여러 축이 동시에 섞인 조합 사진 9장 중 3장 선택 (조합 선호 파악용).
- 마이페이지(7.2) 슬라이더 축: 6개 확정 (밝은↔어두운, 선명한↔차분한, 웜↔쿨, 여백 많은↔꽉 찬, 클로즈업↔넓게, 정면↔뒷모습·옆모습)
  → 5문항(기본질문+A/B) + 무드보드 1라운드(distance, angle)가 합쳐져 6축을 채움.
- 온보딩 마지막 자유 텍스트 프롬프트 입력: **스코프 아웃 확정** (원칙 충돌, 데이터 구조 불일치로 보류).

### 재학습 vs 재추천 로직 (2026.08 확정)

- **재학습 (7.3)**: 온보딩 설문(기본질문 5 + A/B 5 + 무드보드 2라운드) 전체를 처음부터 다시 진행.
  완료 시 `TASTE_PROFILE_AXIS` 전체 교체, 이전 값/누적 보정 신호는 삭제. 진행 중에는 기존 프로파일 유지.
- **재추천 (5.2.3, "재추천 받기" 버튼)**: `TASTE_PROFILE_AXIS`를 변경하지 않음.
  최초 추천과 동일한 스코어링 함수로 후보 사진을 정렬 → **상위 10장 중 3장 랜덤 셔플**하여 교체.
  (기능명세서 원문의 "재추천 요청 자체는 프로파일 보정 신호로 사용하지 않는다" 규칙과 일치.)
- **최초 추천 (5.2.1)**: 스코어링 후 **상위 3장 확정** 추천.
- **추천 사진 수정 (5.2.2)**: 사용자의 추가/제외 선택은 `TASTE_PROFILE_AXIS` 보정 신호로 누적 반영 (재학습과 별개의 점진적 경로).
- 미확정: 재추천 시 후보 사진이 10장 미만인 핀의 처리 기준 (전체 풀 랜덤 vs 재추천 비활성화). `docs/IMPLEMENTATION.md`에서 확정 예정.

---

## 2. 기능명세서 원문 (Orte_기능명세서_v1.md)

> 아래는 팀이 작성한 기능명세서 원문입니다. 표 형태 원본은 별도 파일(`Orte_기능명세서_v1.md`)로도 보관하고,
> 이 문서에는 taste(2번 영역)와 recommendations(5.2.1~5.2.3 영역) 관련 섹션만 발췌해 둡니다.
> 전체 원문이 필요하면 repo의 원본 파일을 참조할 것.

### 2. 취향 프로파일 온보딩 (요약)

> 주의: 아래 원문은 "기본 질문 7개"로 되어 있으나, 위 "온보딩 설문 구조 (2026.08 확정)" 섹션의 5문항 안이 최신입니다.
> 원문의 세부 로직(적응형 분기, 칩 표시, 이어하기 등)은 문항 수 변경과 무관하게 유효합니다.

- 여행자는 최초 이용 시 사진 취향을 파악하는 기본 질문에 답할 수 있다.
- 여행자는 차이가 뚜렷한 사진 A/B 쌍 5회 선택을 통해 취향 프로파일을 생성할 수 있다.
- 여행자는 무드보드 9장 중 3장 선택을 2회 수행해 취향 프로파일을 보완할 수 있다.
- 온보딩 화면에서 사진과 전체 진행 상태를 확인할 수 있다.
- 온보딩을 중단한 여행자는 다음 진입 시 이전 진행 상태를 이어서 진행할 수 있다 (2.4 온보딩 이어하기).
- 여행자는 온보딩의 어느 단계도 건너뛸 수 없으며, 모든 문항에 답해야 홈으로 진입할 수 있다.

핵심 비즈니스 규칙:
- 온보딩 순서: 기본 질문 → A/B 사진 → 무드보드.
- 각 단계 모두 건너뛰기 불가.
- 온보딩 이어하기는 세 단계 전체에 동일 적용, 완료 후에는 제공 안 함.

### 5.2.1 핀별 사진 추천 (요약)

- 핀에 연결된 사진에서 촬영 시각 근접도 + 이미지 유사도로 유사 사진을 줄인다.
- 남은 사진을 취향 프로파일 가중치로 스코어링해 대표 사진 3장 선정.
- 핀을 처음 열 때 주변 1km 이내 태깅 없이 촬영한 사진 업로드를 유도하고, 업로드 시 재선정.
- 사진이 1장이면 유사사진 제거 생략, 3장 미만이면 있는 대로 순서대로 추천.
- 추천 결과는 점수·등급 비노출, 대표 사진 3장 묶음으로만 표시.

### 5.2.2 추천 사진 수정 반영 (요약)

- 여행자는 추천 사진을 제외하거나, 추천되지 않은 사진을 추가할 수 있다.
- 수정 결과는 즉시 반영되고, 선택 신호는 취향 프로파일 보정에 누적된다.
- 모든 추천 사진을 제외하면 해당 핀은 대표 사진 없음 상태.

### 5.2.3 추천 사진 재추천 요청(새로고침) (요약, v1 전면 개정 반영)

- 핀에 연결된 사진이 4장 이상일 때만 제공 (3장 이하면 재추천 버튼 없음).
- 요청 시점의 취향 프로파일로 핀에 등록된 전체 사진을 스코어링, 상위 10장을 후보로 추림.
- 10장 미만이면 등록된 사진 전체를 후보로 사용. 후보가 정확히 3장이면 무작위 선정 없이 그대로 사용.
- 후보 중 3장을 무작위 선정해 추천 결과 교체, 직전 추천 포함 사진도 후보에 남아 다시 선정될 수 있음.
- 추천 버전을 1 증가시켜 저장. 이전 추천 결과는 보존하지 않고 최신으로 교체.
- 재추천 요청과 결과는 취향 프로파일 학습에 반영하지 않음 — `TASTE_PROFILE_AXIS` 불변.
- 프로파일이 재학습/수정 신호로 바뀌어도 기존 추천은 소급 재계산하지 않으며, 재추천을 요청한 핀에만 새 프로파일 적용.
- 재추천 횟수 제한 없음.

### 7.2 취향 프로파일 시각화 (요약)

- 마이페이지에서 6개 축을 양극 슬라이더로 표시 (읽기 전용).
- 값 변경은 7.3 재학습과 5.2.2 추천 수정을 통해서만 발생. 슬라이더 직접 조작 불가.
- 점수·등급 형태 수치는 노출하지 않음.

### 7.3 취향 재학습 (요약)

- 재학습 진입 시 "기존 프로파일이 교체된다"는 확인 안내 후 진행.
- 진행하면 2.1 기본질문부터 무드보드까지 전체 온보딩 흐름 재시작.
- 완료 시점에만 새 응답으로 프로파일 교체, 이전 프로파일과 누적 보정 신호는 삭제.
- 재학습 진행 중(미완료)에는 기존 프로파일을 그대로 유지해 추천이 끊기지 않게 함.
- 재학습 중단 시 프로파일 교체하지 않고, 다시 진입하면 2.4 온보딩 이어하기 적용.
- 이미 생성된 추천 결과는 소급 재계산하지 않음 — 이후 생성되는 추천부터 새 프로파일 적용.

---

## 3. 참고 — 기능명세서 전체 원문 위치

기능명세서 전체(계정/인증, 여행 구간, 지도, 포토북, 마이페이지, NFC 태깅 등 taste/recommendations 외 전 영역)는
`Orte_기능명세서_v1.md` 원본 파일을 참조. 이 spec.md는 taste/recommendations 담당자의 작업 참조 편의를 위해
관련 섹션만 발췌 정리한 것으로, 전체 스펙의 최종본은 원본 파일이다.