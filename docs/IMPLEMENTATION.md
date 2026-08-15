# IMPLEMENTATION.md

## 스코프
현재는 `taste`, `recommendations` 앱 작업 로그로 좁게 운영. 다른 담당자도 이 방식을 쓰기 원하면
프로젝트 전체 공용 문서로 확장 가능 (섹션을 앱별로 나누는 정도로 충분히 전환 가능).

이 문서는 `docs/spec.md`에 없는, 구현하면서 새로 확정한 세부 규칙을 기록하는 곳입니다.
"왜 이렇게 짰는지"를 나중에(본인 포함) 추적할 수 있게 결정 + 이유 + 날짜를 남깁니다.

---

## 결정 로그

### 2026-08-13 — 온보딩 기본 질문 7개 → 5개로 축소
- **결정**: 기본 질문을 A/B 5쌍과 동일한 5축(밝기·채도·색온도·구도·사진종류)으로 재구성.
- **이유**: 기존 7문항 분기 구조(인물/풍경 상위축 → 세부축) 대신, A/B와 같은 5축을 텍스트로 먼저 물어
  실측(A/B 선택 행동)과의 크로스체크 신호로 활용. 문항 수 감소로 온보딩 이탈률도 개선 기대.
- **영향 범위**: `BasicQuestionResponse` 모델의 `round_no` 범위가 1~5로 축소. 기존 스펙 문서의
  "7개 고정" 관련 비즈니스 규칙 문구는 spec.md에서 갱신 표시함 (원본 파일은 미수정).

### 2026-08-13 — 온보딩 마지막 자유 텍스트 프롬프트 입력 — 스코프 아웃
- **결정**: 온보딩 마지막 단계에 자유 텍스트 프롬프트를 받는 안은 채택하지 않음.
- **이유**: (1) 서비스 원칙("말로 묻지 않고 고르게 한다")과 충돌, (2) 현재 축 체계(정량 측정 가능한 5~6축)에
  자유 텍스트를 매핑할 신뢰할 수 있는 경로가 없음, (3) 개인화 강화가 목적이라면 재학습 시점 활용이나
  선택적 보조 입력 등 대안이 더 적합.
- **영향 범위**: taste 앱 모델에 프롬프트 저장 필드 불필요.

### 2026-08-13 — 재추천(5.2.3) 시 취향 프로파일 불변 확정
- **결정**: "재추천 받기" 버튼은 `TASTE_PROFILE_AXIS`를 전혀 변경하지 않는다. 현재 저장된 축 값 기준으로
  후보 사진을 스코어링해 상위 10장을 추리고, 그중 3장을 랜덤으로 골라 교체한다.
- **이유**: 기능명세서 5.2.3의 "재추천 요청 자체는 취향 프로파일 보정 신호로 사용하지 않는다"는 원문 규칙을
  그대로 유지하기로 확정. 최초 추천(상위 3장 확정)과 달리 재추천은 매번 다른 조합을 보여주되 취향과
  무관해지지 않도록 상위 10장이라는 풀 제한을 둠.
- **영향 범위**:
  - `recommendations` 앱에 스코어링 공용 함수(`score_photos_by_taste`)를 두고 최초 추천/재추천 양쪽에서 재사용.
  - 재추천 전용 함수는 상위 10장 추출 후 `random.sample(..., 3)` 적용.
  - `RecommendationRegenHistory`에 재추천 이벤트 기록, `TasteProfileAxis` 쪽 테이블에는 어떤 변경도 발생시키지 않음.
- **미확정 (다음에 정할 것)**: 핀의 사진 후보가 10장 미만일 때의 처리.
  - 옵션 A: 있는 사진 전체를 풀로 삼아 그중 3장 랜덤
  - 옵션 B: 10장 미만이면 재추천 자체를 비활성화 (스펙 원문의 "3장 이하" 기준보다 엄격해짐)
  - → 확정되는 대로 이 항목 갱신하고 spec.md에도 반영.

### 2026-08-13 — 재학습(7.3) vs 재추천(5.2.3) vs 추천 수정(5.2.2) 3분리 확정
- **결정**: 취향 프로파일에 영향을 주는 경로를 아래 세 가지로 명확히 분리.
  1. 재학습: 온보딩 설문 전체 replay → 완료 시 프로파일 전체 교체
  2. 재추천: 프로파일 불변, 스코어링 결과만 재추출(랜덤)
  3. 추천 사진 추가/제외: 프로파일에 점진적 보정 신호로 누적
- **이유**: 세 기능이 이름이 비슷해 혼동 소지가 있어 명시적으로 문서화. `taste`와 `recommendations` 앱
  경계를 정하는 기준이 됨 — 프로파일 자체를 쓰는 로직은 taste, 추천 스코어링/셔플 로직은 recommendations.

### 2026-08-13 — MCM_PRODUCT PK 단일키(tag_id) 확정
- **결정**: `MCM_PRODUCT`의 PK를 `tag_id` 단일키로 확정. (구) 다이어그램상 `tag_id`+`user_id` 복합 PK안은 폐기.
- **이유**: 기능명세서 7.5 비즈니스 규칙 "하나의 태그는 하나의 계정에만 등록할 수 있으며, 최초로 태깅한 계정에 귀속된다"와
  단일 PK가 정합. 복합 PK였다면 같은 태그가 여러 계정에 등록 가능한 구조로 오해될 여지가 있었음.
- **영향 범위**: `products` 앱 `NfcTag` 모델의 PK 설계. taste/recommendations와 직접 관련은 없으나 ERD 전체 일관성을 위해 기록.

### 2026-08-13 — ERD의 FK 제약 처리 원칙
- **결정**: SQL export 파일에 FK 제약이 일부만(3개) 명시돼 있어도, ERD 다이어그램에 그려진 관계선은 전부 유효한
  관계로 간주하고 Django `models.ForeignKey`로 구현한다. SQL 파일 자체는 최종 DDL이 아니라 설계 스냅샷으로 취급.
- **이유**: 다이어그램 툴 특성상 관계선과 실제 FK 제약 export가 별개로 동작하는 것으로 추정. Django 마이그레이션이
  ForeignKey 정의 시 FK 제약을 자동 생성하므로 SQL 파일을 수동으로 고칠 필요 없음.
- **영향 범위**: 전 앱 공통 원칙. 특히 taste/recommendations는 `USER`, `PIN` 참조가 많아 해당.

### 2026-08-13 — 핀 수동 생성(5.1.2) 시 좌표는 사진이 아닌 세션 GPS 기준
- **결정**: 수동 핀 생성 시, 핀의 좌표는 업로드/촬영된 사진의 메타데이터가 아니라 **태깅 세션 시작 시점의 기기 GPS 좌표**로 결정한다.
  즉 "핀 먼저(위치 확정) → 사진 나중(그 세션에 연결)" 순서.
- **이유**: 기능명세서 8.1에 "촬영 파이프라인에서 사진 파일의 촬영 위치 정보가 생성되지 않으므로, 세션 시작 시점의
  위치 좌표를 별도 필드로 저장한다"고 명시되어 있어, 사진 자체엔 신뢰 가능한 좌표가 없다는 전제가 깔려 있음.
  5.4(주변 사진 추가)는 예외적으로 사진의 촬영 좌표를 쓰지만, 이는 기존 핀 보완용이지 핀 생성 로직과는 무관.
- **영향 범위**: taste/recommendations와 직접 관련 없으나(travel 앱 소관), 5.2.1 추천 스코어링 시 "핀 좌표"를 참조할 때
  이 기준(세션 GPS)을 신뢰하고 사용하면 됨.

### 2026-08-14 — taste 앱 User FK는 우선 Django 기본 auth.User로
- **결정**: `accounts` 앱과 커스텀 User 모델이 아직 없어서(AUTH_USER_MODEL 미설정), taste 앱의 모든 모델은
  당장 `settings.AUTH_USER_MODEL`(현재는 Django 기본 `auth.User`)을 FK로 참조한다.
- **이유**: accounts는 다른 담당자 영역이라 사전 협의 없이 만들 수 없음(CLAUDE.md). `settings.AUTH_USER_MODEL`
  참조로 작성해두면 나중에 accounts가 커스텀 User로 바뀌어도 taste 쪽 모델 코드 수정이 필요 없음.
- **영향 범위**: `taste` 앱 6개 모델(TasteProfile, TasteProfileAxis, BasicQuestionResponse, SelectionPhoto,
  OnboardingProgress, ProfileRetrainHistory)의 user FK 전부.

### 2026-08-14 — ABSelectionLog는 만들지 않음, SelectionPhoto가 A/B+무드보드 통합 관리
- **결정**: 앱-모델 매핑표에 있던 `ABSelectionLog`는 별도로 만들지 않는다. ERD의 `SELECTION_PHOTO` 하나로
  A/B 사진 쌍 선택(5라운드)과 무드보드 사진 선택(2라운드)을 모두 관리한다. `round_no`는 AB 1~5, 무드보드
  이어서 6~7로 하나의 연속된 번호를 쓴다(ERD에 필드 추가 없이 라운드 구분 가능).
- **이유**: SELECTION_PHOTO가 이미 "사진 선택" 이벤트 전반을 담당하는 테이블로 설계돼 있어, A/B용 로그
  테이블을 별도로 두면 같은 개념(사진 선택 기록)이 두 테이블로 쪼개져 중복됨. AI 실측값은 로그 테이블 없이
  A/B 라운드에서 선택된 사진을 즉시 분석해 `TasteProfileAxis.value`에 바로 반영하는 방식으로 처리.
- **영향 범위**: `taste` 앱 모델 목록에서 `ABSelectionLog` 제외. `SelectionPhoto.round_no` 1~5=A/B,
  6~7=무드보드로 애플리케이션 코드에서 해석(상수로 관리).

### 2026-08-14 — 마이페이지 슬라이더/축 6개 → 5개로 정정, 무드보드는 축 값에 신호로만 기여
- **결정**: `TasteProfileAxis.axis_code`는 5개(brightness, vividness, tone, density, photo_type)만 사용.
  무드보드 1라운드(캐릭터 각도·거리 9장 중 3장, 구도 선호)와 2라운드(여행사진 9장 중 3장, 선택 사진 분석)는
  별도 축(distance/angle 등)을 새로 만들지 않고, 둘 다 **`density`(구도와 밀도) 축을 포함한 기존 5축에 대한
  추가 신호**로 반영한다.
- **이유**: 기본질문 Q4가 이미 "구도/밀도"를 하나의 축으로 묶어서 다루고 있어, 무드보드의 구도 관련 신호를
  같은 축에 합치는 게 개념적으로 일관됨. 축 체계를 5개로 유지하면서 신호 소스만 늘어나는 구조.
- **영향 범위**: `docs/spec.md` 체크리스트에 새 행 추가로 반영. `TasteProfileAxis` 모델의 `axis_code` 선택지.
  무드보드 분석 결과를 축에 반영하는 구체 로직(가중 평균 등)은 recommendations/taste API 구현 시점에 별도 결정.

### 2026-08-14 — API 명세서(`docs/Orte_API_명세서.md`) 신규 추가, 파일명 정리
- **결정**: 기존 `docs/Orte_API_명세서_v1.md`(빈 파일)는 사실 "기능명세서" 내용을 담기로 했던 파일이라
  `docs/Orte_기능명세서_v1.md`로 이름을 바꾸고, 실제 API 엔드포인트 명세는 새 파일
  `docs/Orte_API_명세서.md`에 정리한다. `docs/spec.md` 내 파일명 참조도 함께 갱신.
- **이유**: "API 명세서"라는 이름의 파일에 기능명세서 내용이 들어가는 건 혼동 소지가 있어 분리.
- **영향 범위**: `docs/spec.md`의 파일명 참조 5곳.

### 2026-08-14 — API 명세서 기준으로 축 5개 재확인, 필드명 정합화
- **결정**: 새로 채워진 `docs/Orte_API_명세서.md`의 2.4(취향 축 목록 조회) 예시가 최초엔 6개 축
  (brightness/vividness/tone/density/framing/angle)으로 적혀 있었으나, 사용자 확인 후 **5개 축
  (brightness/vividness/tone/density/photo_type)이 맞는 것으로 확정** — API 명세서 예시 쪽을 수정.
  필드명은 반대로 API 명세서 쪽이 기준: `BasicQuestionResponse`는 API 응답 키가 `response`이지만
  ERD(SQL)의 실제 컬럼명이 `answer`라서 **모델 필드명은 ERD 그대로 `answer` 유지, 시리얼라이저에서
  `response`로 노출**하는 방식으로 처리. `SelectionPhoto.photo_index`(라운드 내 0~8)는 ERD에 없는
  자체 추가 필드였으므로 API 명세서 예시(`"photo_id": 2011`)를 따라 **`photo_id`로 이름 변경,
  의미도 "라운드 내 순번"이 아니라 "고정 사진 카탈로그 전역 유일 ID"로 정정**.
- **이유**: ERD(SQL)는 다른 개발자와 합의된 문서라 필드명을 임의로 바꾸지 않는 원칙 유지. API 응답
  바디 키는 시리얼라이저 레벨에서 얼마든지 다르게 노출 가능하므로 ERD를 건드릴 필요가 없음.
  `photo_id`는 ERD에 없던 필드라 API 명세서 기준으로 자유롭게 맞춤.
- **영향 범위**: `taste/models.py`의 `SelectionPhoto.photo_id`(구 `photo_index`), `unique_together`.
  로컬 마이그레이션 히스토리 재생성(0001로 스쿼시, 개발 중 데이터 없어 안전). taste API 구현 시
  `BasicQuestionResponse` 시리얼라이저에서 `answer` ↔ `response` 매핑 필요.

### 2026-08-14 — TasteProfile.version 필드 추가하지 않기로 결정
- **결정**: 기능명세서 7.2/7.3, 부록 스키마 변경표에 "취향 프로파일 버전을 저장, 재학습 시 1 증가"라고
  명시돼 있었지만, **`TasteProfile`에 `version` 필드를 추가하지 않기로 확정**.
- **이유**: version의 유일한 실사용처였던 "추천 결과에 적용 프로파일 버전 기록"이 API 명세서(더 최신/
  최종 문서) 부록 B에서 "`PHOTO.is_pin_cover` 플래그로 단순화, 추천 이력·버전 관리 미보존"으로 이미
  취소됨. 마이페이지 슬라이더 화면에도 버전 노출 없음. 기능명세서가 API 명세서보다 최신화가 덜 된
  문서라는 점을 사용자가 확인 — 두 문서가 충돌하면 API 명세서를 우선한다는 원칙에 따라 제외.
- **영향 범위**: `TasteProfile` 모델에 `version` 필드 없음 (ERD `TASTE_PROFILE`도 당연히 변경 없음).
  나중에 실제로 프로파일 버전을 참조하는 기능이 부활하면 그때 다시 검토.

### 2026-08-14 — ProfileRetrainHistory에서 이전 축 값 스냅샷 제거, started_at 추가
- **결정**: `ProfileRetrainHistory.previous_axis_snapshot`(JSONField) 필드를 제거하고, 대신
  `started_at`(재학습 시작 시각)을 추가. 최종 필드는 `user`, `started_at`, `completed_at`만 유지.
- **이유**: 기능명세서 7.3 데이터 항목이 "재학습 이력에는 여행자 식별자, 시작 시각, 완료 시각을
  저장하며 **이전 프로파일 값은 보관하지 않는다**"고 명시. `previous_axis_snapshot`은 감사/디버깅
  목적으로 제가 임의로 추가했던 필드라 스펙과 직접 충돌 — 이력(시각) 자체는 저장하되 내용 스냅샷은
  저장하지 않는 것으로 정정. `ProfileRetrainHistory`는 ERD에 없는 taste 앱 자체 신규 테이블이라
  이 변경은 ERD와 무관(팀 공유 문서 변경 없음).
- **영향 범위**: `taste/models.py`의 `ProfileRetrainHistory`. 로컬 마이그레이션 재생성.

### 2026-08-14 — 온보딩 기본질문 제출 API 구현 (#28), 임시 인증 방식 도입
- **결정**: `POST /users/me/basic-question-responses` (API 명세서 2.1)를 구현. 진짜 로그인(구글 OAuth
  + JWT)이 accounts 앱에 아직 없어서, `taste/auth_temp.py`의 `get_current_user(request)` 헬퍼로
  요청 바디의 `user_id`를 받아 사용자를 조회하는 임시 인증을 도입. 호출부는 이 함수 하나만 통해서
  유저를 얻고, 나중에 accounts 인증이 완성되면 함수 내부만 `request.user`를 반환하도록 교체하면
  나머지 코드(serializer, view 로직) 변경 없이 실제 인증으로 전환 가능.
  라운드 건너뛰기 방지(`OnboardingProgress.current_round`와 요청 `round_no` 불일치 시 400),
  5라운드 완료 시 `OnboardingProgress.current_stage`를 `AB_SELECTION`으로 전환하는 로직도 함께 구현
  (API 명세서엔 없는, 저희가 정한 세부 로직).
- **이유**: accounts 담당자와 사전 협의 없이 accounts 앱을 만들 수 없다는 CLAUDE.md 원칙을 지키면서도
  taste API 개발이 완전히 멈추지 않도록, 인증 지점만 격리해 임시로 대체.
- **영향 범위**: `taste/auth_temp.py`(신규, **배포 전 반드시 accounts 실제 인증으로 교체 필요**),
  `taste/serializers.py`(신규, `BasicQuestionResponseSerializer` — 모델 필드 `answer`를 API 키
  `response`로, 모델 `id`를 API 키 `response_id`로 매핑), `taste/views.py`, `taste/urls.py`(신규),
  `config/urls.py`(taste.urls include 추가, prefix 없이 명세서 경로 그대로 마운트).
- **미확정**: accounts 인증이 완성되는 시점에 `auth_temp.py` 제거 및 교체 작업 필요.

### 2026-08-14 — A/B·무드보드 후보 사진: 라운드당 3세트 준비, 랜덤 제시 (무드보드 1라운드 예외)
- **결정**: A/B 라운드는 라운드당 2장짜리 세트를 3개(총 6장), 무드보드 라운드는 9장짜리 세트를 3개
  (총 27장) 준비해두고 그중 하나를 랜덤으로 사용자에게 제시한다. 단, **무드보드 1라운드는 예외** —
  구도(각도·거리) 선호를 측정하는 라운드라 세트 랜덤을 쓰지 않고 고정된 9장 그대로 사용한다.
- **이유**: (사용자 확인) 이 랜덤 제시 로직은 "어떤 후보 사진을 보여줄지 고르는" 단계의 관심사이고,
  `SelectionPhoto.photo_id`가 처음부터 라운드 내 순번이 아니라 **고정 카탈로그 전역 유일 ID**로
  설계되어 있어(위 "API 명세서 기준 축 5개 재확인" 항목 참고), 라운드당 후보가 몇 세트든 저장
  스키마·제출 API(`POST /users/me/selection-photos`) 로직에는 영향이 없음. 라운드 완료 판정
  (A/B 2장 제출·true 1개, 무드보드 9장 제출·true 3개)도 어느 세트가 나왔는지와 무관하게 동일.
- **영향 범위**: 이번 결정 자체는 모델/API 설계 변경 없음. **다만 후보 사진을 사용자에게 내려주는
  별도 엔드포인트(아직 API 명세서에 없음, 미설계)를 나중에 만들 때 라운드→3세트 매핑과 무드보드
  1라운드 예외 처리를 반영해야 함** — 그 작업을 시작할 때 이 항목 참고.

### 2026-08-14 — A/B·무드보드 사진 선택 기록 API 구현 (#30)
- **결정**: `POST /users/me/selection-photos` (API 명세서 2.2)를 구현. `SelectionPhoto` round_no
  1~7(1~5=A/B, 6~7=무드보드) 매핑과 `OnboardingProgress.current_stage`(AB_SELECTION/MOODBOARD)
  + `current_round`(단계 내 번호)를 서로 변환하는 로직 추가. 라운드가 기대 후보 수만큼 채워지면
  (A/B 2장, 무드보드 9장) 라운드 완료로 보고 다음 라운드/단계로 진행하며, 이때 `status=True` 개수가
  기대치(A/B 1개, 무드보드 3개)와 다르면 `VALIDATION_ERROR`. 무드보드 2라운드 완료 시
  `current_stage`를 `COMPLETED`로 전환(단, 취향 축 값 계산/`TasteProfile` 생성은 이번 범위 밖 — 별도
  이슈에서 진행).
- **이유**: 라운드 진행 판정 기준을 명세서가 정해주지 않아 자체 설계 필요. 기본질문 API(#28)와 같은
  건너뛰기 방지 패턴 재사용.
- **영향 범위**: `taste/serializers.py`(`SelectionPhotoSerializer` 추가), `taste/views.py`
  (`submit_selection_photo`), `taste/urls.py`.
- **미확정**: 온보딩 완료(`COMPLETED`) 시점에 실제 `TasteProfileAxis` 값을 계산해 반영하는 로직은
  별도 이슈로 분리 예정.

### 2026-08-15 — 취향 축 목록 조회 API 구현 (#33)
- **결정**: `GET /users/me/taste-profile/axes` (API 명세서 2.4)를 구현. `TasteProfileAxis`를
  `axis_code`, `value`, `status` 3개 필드만 노출하는 read-only 시리얼라이저로 응답. 정렬은
  `AxisCode` 정의 순서(brightness→vividness→tone→density→photo_type) 고정. 아직 온보딩을
  완료하지 않아 해당 유저의 축 row가 하나도 없으면 `axes: []` 빈 배열을 반환(별도 404 처리 없음).
  GET이라 body가 없어서, `auth_temp.get_current_user`가 `request.data`뿐 아니라
  `request.query_params`에서도 `user_id`를 읽도록 확장(`?user_id=` 쿼리 파라미터 방식).
- **이유**: 응답 예시 축이 API 명세서상 일시적으로 6개(framing/angle 포함)로 잘못 채워져 있던 걸
  사용자 확인 후 5개(photo_type 포함)로 재정정(위 2026-08-14 결정과 동일 기준 재확인). 빈 배열
  응답은 스펙에 명시가 없어 가장 단순한 기본값으로 채택 — 온보딩 미완료 유저의 접근을 막을지는
  스펙 미확정이라 이번 범위에서 별도 차단 로직은 넣지 않음.
- **영향 범위**: `taste/auth_temp.py`(`get_current_user` 쿼리 파라미터 지원 추가),
  `taste/serializers.py`(`TasteProfileAxisSerializer` 추가), `taste/views.py`
  (`list_taste_profile_axes`), `taste/urls.py`, `docs/Orte_API_명세서.md` 2.4 예시 축 개수 수정(6→5).
- **미확정**: 온보딩 미완료 유저가 이 API를 호출했을 때 빈 배열 대신 별도 에러를 줘야 하는지는
  프론트 쪽 UX 결정에 따라 나중에 바뀔 수 있음.

---

## 템플릿 (새 결정 추가 시 아래 형식 복사해서 사용)

```
### YYYY-MM-DD — 결정 제목
- **결정**: 무엇을 정했는지 한두 문장
- **이유**: 왜 이렇게 정했는지
- **영향 범위**: 어떤 모델/함수/앱이 영향받는지
- **미확정**: (있다면) 아직 안 정해진 부분
```