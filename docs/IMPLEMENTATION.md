# IMPLEMENTATION.md

## 스코프
2026-08-14부터 `taste`/`recommendations` 전용에서 프로젝트 전체 공용 문서로 확장.
`accounts`/`products`/`travel` 담당자의 결정도 같은 형식으로 이 파일에 함께 남긴다.
구분이 필요하면 항목 제목 앞에 `[앱이름]`을 붙인다.

이 문서는 ERD(`MCM_NFC_ERD_v5`)나 `docs/spec.md`에 없는, 구현하면서 새로 확정한 세부 규칙을
기록하는 곳입니다. "왜 이렇게 짰는지"를 나중에(본인 포함) 추적할 수 있게 결정 + 이유 + 날짜를
남깁니다. API 응답 스키마 자체가 바뀌는 변경은 여기 대신 `docs/API_CHANGES.md`에 남긴다.

---

## 결정 로그

### 2026-08-14 — [accounts] Session 테이블 제거, JWT 무상태 인증으로 전환
- **결정**: `accounts.models.Session`을 삭제하고, `djangorestframework-simplejwt`로 access_token(15분)/
  refresh_token(14일) 쌍을 발급하는 무상태 방식으로 전환. 서버에는 토큰을 저장하는 테이블이 없다.
  로그인(`POST /auth/google/login`) 응답이 `session_token` → `access_token`/`refresh_token`으로 바뀌고,
  `POST /auth/token/refresh`가 신규 추가됨. (실제 API 계약 변경 상세는 `docs/API_CHANGES.md` 참고)
- **이유**: 최종 ERD(2026-08-14 확인본)에 SESSION 테이블이 없음 — 사용자 확정 지시. JWT 도입 요청과도 부합.
- **영향 범위**: `accounts/models.py`(Session 삭제), `accounts/authentication.py`(JWTAccessAuthentication으로 교체),
  `accounts/views.py`, `accounts/serializers.py`, `accounts/urls.py`, `config/settings.py`(SIMPLE_JWT 설정).
- **트레이드오프**: 서버가 특정 기기의 토큰만 강제로 무효화할 방법이 없음. `POST /auth/logout`은 인증된 요청인지
  확인 후 204만 반환하고, 실제 무효화는 클라이언트가 로컬 토큰을 폐기하는 것으로 대체. 탈취된 토큰은 자연 만료
  (access 15분) 전까지 유효 — 노출 범위를 줄이려고 access 수명을 짧게 잡음.
- **관련 마이그레이션**: `accounts/migrations/0002_delete_session.py`. 참고: 0001_initial.py의 `token` 필드
  default가 `accounts.models.generate_session_token`을 참조하고 있었는데, 그 함수를 models.py에서 지우면서
  마이그레이션 파일이 깨지지 않도록 0001 안에 동일 로직(`_generate_session_token`)을 인라인 처리함.

### 2026-08-14 — [products] NfcTag(MCM_PRODUCT) 필드 보정
- **결정**: `tag_count`(기본값 0), `unlinked_at`(nullable) 필드 추가. `user` FK를 nullable + `on_delete=SET_NULL`로 변경.
  연결 해제(7.4.1) 시 `user=None`, `unlinked_at=now()`로 처리 — 재등록 가능 여부는 `unlinked_at IS NULL` 여부로 판단.
- **이유**: 최종 ERD의 MCM_PRODUCT 정의 반영. ERD 원문 안에 "연결 해제 시 user_id를 NULL로 비운다([확정] 표기)"와
  "이력 보존을 위해 비우지 않는 것을 권장" 두 문구가 서로 모순되게 남아 있었는데, `[확정]` 쪽을 채택.
- **영향 범위**: `products/models.py`. API 응답 스키마 변경 없음(둘 다 내부 컬럼, 프론트 영향 없음).
- **관련 마이그레이션**: `products/migrations/0002_nfctag_tag_count_nfctag_unlinked_at_and_more.py`

### 2026-08-14 — [accounts] 경로를 원문 API 명세서 기준으로 정정
- **결정**: `POST /auth/google/login` → `POST /auth/google`, `GET /me` → `GET /users/me`로 경로 변경.
- **이유**: 두 경로 모두 원래 코드가 원문(`Orte_API_명세서.md`, 프론트에 공유된 최종본)과 다른 이름으로
  구현돼 있었음. 원문이 프론트 기준이므로 원문에 맞춤.
- **영향 범위**: `accounts/urls.py`. **주의**: 프론트가 이미 `/auth/google/login`, `/me`로 붙여놓은 상태였다면
  이 변경으로 깨질 수 있음 — 배포 전 프론트 담당자와 확인 필요.

### 2026-08-14 — [accounts] 권한 상태(1.2/1.3/7.6) — 새 테이블 대신 USER 컬럼으로 저장
- **결정**: `PermissionEvent` 같은 별도 이력 테이블을 만들지 않고, `USER`에 `camera_permission`/
  `location_permission`/`microphone_permission` 3개 컬럼(nullable)만 추가. `POST /events/permissions`가
  이 컬럼을 최신 값으로 덮어쓰고(upsert), `GET /users/me/permissions`는 그대로 읽어서 반환.
  한 번도 보고 안 된 권한은 `null`로 응답.
- **이유**: ERD를 최대한 안 건드리는 방향을 원함 + 과거 이력을 DB에서 조회할 필요가 없다고 확인받음
  (원문의 "분석용으로 기록한다"는 문구는 있으나, 실제 필요한 건 최신 상태뿐).
- **영향 범위**: `accounts/models.py`(컬럼 추가), `accounts/views.py`(`events_permissions`,
  `permissions_summary`, `permission_intro_ack`), `accounts/serializers.py`.
- **nfc 처리**: `nfc`는 저장할 컬럼을 안 둠 — 7.6 응답 대상이 아니고(v3.5에서 조회 대상 제외 확정),
  "서버가 실제 권한을 판단하지 않는다"는 원문 규칙과도 맞아서 DB 대신 `request_logger`로만 남김.
  나중에 이력이 실제로 필요해지면 이 로그를 별도 테이블로 옮기는 것도 가능.

### 2026-08-14 — [travel] Pin.user, TaggingSession 테이블은 ERD와 다르게 유지(코드 변경 없음)
- **결정**: 최종 ERD엔 `PIN.user_id`(FK)와 `TAGGING_SESSION` 테이블이 없지만, 현재 코드의 `travel.models.Pin.user`와
  `travel.models.TaggingSession`은 그대로 유지하고 수정하지 않는다.
- **이유**:
  - `Pin.user`: `segment_id`가 진행 중인 여행에서는 NULL이라, 이 FK 없이는 소유자 판별(권한 체크,
    `PERMISSION_DENIED`)이 불가능해짐. API 응답에는 노출되지 않는 내부 전용 필드라 프론트 영향 없음.
  - `TaggingSession`: 이미 공유된 `Orte_API_명세서.md` 8장(`POST /tagging-sessions`, `.../photos`, `.../complete`)이
    세션 개념을 전제로 한 엔드포인트라, ERD보다 이미 넘어간 API 계약을 우선함.
- **영향 범위**: 없음(현행 유지 결정이라 코드 변경 없음). 나중에 ERD 쪽을 갱신해서 맞출지는 팀 논의 필요.
- **미확정**: `TravelSegment.status`/`cover_photo_url` 컬럼 존치 여부 — ERD에도 "팀 내 논의 중"으로 보류 표시되어 있어
  현행 유지, 결론 나면 이 항목 갱신.

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

### 2026-08-14 — [travel] 태깅 세션을 DB 테이블 대신 서명 토큰으로 관리
- **결정**: `TaggingSession` 모델/테이블을 삭제한다. `POST /tagging-sessions`가 세션 상태
  (`segment_id`, `start_type`, `nfc_tag_id`, 시작 좌표, `started_at`, `continue_pin_id`)를
  `django.core.signing`으로 서명한 `session_id` 토큰으로 발급하고, 서버는 이 토큰을 검증만
  할 뿐 별도 DB 행을 두지 않는다. `Photo`는 `tagging_session`(FK) 대신 `session_key`(문자열,
  인덱스만) 컬럼으로 "같은 세션에서 찍힌 사진"을 grouping한다. `POST /tagging-sessions/{id}/complete`도
  DB를 건드리지 않고 `Photo.objects.filter(session_key=uid).count()`로 폐기 여부만 판단한다.
- **이유**: 팀 운영진 가이드라인("DB에 기능을 넣지 말고 view에서 구현") + ERD를 이미 정리/축소해둔
  상태를 유지하고 싶다는 요청. `TaggingSession`은 원래 최종 ERD에 없던 테이블(API 명세서 부록 B에
  gap으로만 명시)이라, 아예 DB에 테이블을 안 만드는 쪽으로 결론. `accounts`의 JWT 무상태 인증과
  같은 패턴(서버가 세션을 저장하지 않고 서명된 토큰만 검증)이라 프로젝트 전체와도 일관됨.
- **영향 범위**: `travel/models.py`(`TaggingSession` 삭제, `Photo.session_key` 추가),
  `travel/tokens.py`(신규 — 토큰 발급/검증), `travel/views.py`, `travel/serializers.py`,
  `travel/urls.py`. API 응답 스키마는 원문 그대로(`session_id`가 원래도 예시상 문자열 형태였음).
- **트레이드오프**: DB에서 "지금 진행 중인 세션 목록"을 직접 조회할 수 없음(운영/디버깅 시
  `Photo.session_key`로 역산해야 함). 클라이언트가 토큰을 잃어버리면 그 세션은 복구 불가
  (다만 DB 테이블로 관리했어도 별도 조회 API가 없어 사실상 동일).
- **세션 만료**: 6시간(`travel/tokens.py SESSION_MAX_AGE`). 업로드 토큰(`uploads`)은 30분.

### 2026-08-14 — [uploads] 신규 앱, DB 테이블 없이 서명 토큰으로 파일 업로드 관리
- **결정**: `POST /uploads`(사전 서명 URL 발급) ~ 실제 업로드 2단계 계약(API 명세서 상단
  "파일 업로드" 절)을 S3 없이 로컬 디스크로 구현하되, `UploadedFile` 같은 DB 테이블을 두지
  않는다. `file_id` 자체를 `django.core.signing`으로 서명한 토큰으로 발급하고, 실제 바이트는
  `MEDIA_ROOT/uploads/{uid}{ext}`에 저장한다. "업로드 완료 여부"는 디스크에 파일이 있는지로,
  "이미 사용됨"은 `uploads/consumed/`로 파일을 옮기는 것으로 판단한다(재사용 방지).
- **이유**: 위 태깅 세션 결정과 동일 — DB에 기능(및 신규 테이블)을 넣지 말라는 가이드라인,
  ERD 미변경 방침. `Photo`/`VoiceMemo`(도메인 테이블)에 업로드 상태 컬럼을 억지로 얹는 대안도
  검토했으나, 도메인 테이블 의미가 흐려지고 나중에 걷어내기도 더 어려워 기각.
- **영향 범위**: `uploads` 앱 신규(`tokens.py`, `views.py`, `serializers.py`, `urls.py`,
  모델 없음), `config/settings.py`(`MEDIA_ROOT`/`MEDIA_URL`), `config/urls.py`(DEBUG 시
  미디어 서빙 + `uploads.urls`/`travel.urls` include).
- **API 명세서에 없는 보조 엔드포인트**: `PUT /uploads/{file_id}/content` — S3였다면 프론트가
  `upload_url`(presigned PUT URL)로 직접 업로드하는 자리. `upload_url` 자체를 서버가 매번
  새로 만들어 내려주므로 프론트 계약(`POST /uploads` 요청/응답 형태)엔 영향 없음.
- **2026-08-15 갱신으로 대체됨**: 아래 "[uploads] S3 presigned URL 방식으로 전환" 항목 참고.
  이 로컬 디스크 구현은 실제 S3 연동 전까지의 임시 조치였고, 지금은 원래 API 명세서(2단계
  presigned URL 방식) 그대로 구현됨.

### 2026-08-15 — [uploads] S3 presigned URL 방식으로 전환 (로컬 디스크 임시 구현 대체)
- **결정**: 위 2026-08-14 로컬 디스크 구현을 걷어내고, API 명세서 원문대로 실제 S3 presigned
  URL 방식으로 전환한다. `POST /uploads`가 `boto3.generate_presigned_url("put_object", ...)`로
  진짜 S3 presigned PUT URL을 발급하고, 프론트는 그 URL로 S3에 직접 업로드한다. 로컬 전용이던
  `PUT /uploads/{file_id}/content` 보조 엔드포인트는 더 이상 필요 없어 삭제.
- **이유**: 프론트-백엔드 연동을 앞두고 팀 운영진이 EC2/RDS/S3 인프라 구성을 요구, 실제 배포
  환경에서 로컬 디스크는 인스턴스 교체 시 파일 유실·다중 인스턴스 확장 불가 문제가 있어 원래
  스펙(S3)으로 되돌리기로 결정.
- **영향 범위**: `uploads/tokens.py`(로컬 파일 경로 대신 S3 key 기반 — `head_object`로 존재
  확인, `copy_object`+`delete_object`로 pending→consumed 이동 재현), `uploads/views.py`
  (`upload_content` 뷰 삭제, `request_upload`가 presigned URL 발급), `uploads/urls.py`
  (`PUT .../content` 라우트 삭제), `config/settings.py`(`AWS_ACCESS_KEY_ID`/
  `AWS_SECRET_ACCESS_KEY`/`AWS_REGION`/`AWS_STORAGE_BUCKET_NAME` 추가, `MEDIA_ROOT`/
  `MEDIA_URL`은 더 이상 안 씀), `pyproject.toml`(`boto3` 추가).
- **`resolve_and_consume` 함수 시그니처는 그대로 유지** — `travel/views.py`의 호출부
  (`_attach_voice_memo`, `_pin_photos_register`)는 전혀 수정하지 않음. 반환값이 로컬 상대
  경로에서 S3 절대 URL(`https://{bucket}.s3.{region}.amazonaws.com/...`)로 바뀌었는데,
  호출부가 `request.build_absolute_uri(relative_url)`로 감싸는 부분은 Django가 절대 URI를
  그대로 통과시켜주므로 변경 불필요.
- **버킷 접근 정책**: private+presigned GET 대신 **public-read**로 결정(버킷 정책에서
  `s3:GetObject`만 `Principal: "*"`로 공개, 쓰기/삭제는 IAM 사용자 전용). 프론트 URL 변경이
  거의 없고(고정 URL, 매 응답마다 재서명 불필요), 개인 여행 사진이라 완전 비공개까지는
  필요 없다고 판단. 보안 요구사항이 생기면 private+presigned GET으로 전환 가능(백엔드만
  변경, 프론트는 여전히 URL 문자열 하나만 받으므로 영향 없음).
- **IAM**: 버킷 전용 인라인 정책(`s3-orte-uploads-access` — `PutObject`/`GetObject`/
  `DeleteObject`/`ListBucket`, 리소스는 `dreamteam-orte-uploads` 버킷으로 한정)을 기존 IAM
  사용자에 연결. 애플리케이션 전용 IAM 사용자로 분리하지 않고 기존 사용자를 재사용 — 시간
  제약상 임시 조치, 여유 생기면 분리 검토.

### 2026-08-14 — [products] NfcTag 자동등록을 위한 product_type/product_name 보정
- **결정**: `NfcTag.PRODUCT_TYPE_CHOICES`에 `unknown`(미확인) 추가, `product_name`을
  nullable로 변경.
- **이유**: `POST /tagging-sessions`에서 미등록 NFC 태그를 자동등록(7.5)할 때 서버는 실제
  제품 정보를 알 수 없다. API 명세서 7.4 응답 예시에 이미
  `{"product_type": "unknown", "product_name": null}` 케이스가 명시돼 있어 그대로 반영.
- **영향 범위**: `products/models.py`. ERD 문서엔 두 컬럼 다 이미 존재해서 다이어그램 변경
  없음 — Django 레벨 제약(choices, nullable)만 완화.
- **관련 마이그레이션**: `products/migrations/0003_alter_nfctag_product_name_alter_nfctag_product_type.py`

### 2026-08-14 — [travel] VoiceMemo.record_source로 음성 수정 제한 구현
- **결정**: `VoiceMemo.record_source`(`nfc`|`manual`) 추가. 값은 그 음성을 만든 태깅 세션의
  `start_type`을 그대로 복사한다. `PATCH /pins/{id}/context`에서 기존 음성의
  `record_source == 'nfc'`면 교체 요청을 거부(400)한다.
- **이유**: 기능명세서 "텍스트 기록 사후 수정 가능, 촬영 흐름 음성 메모는 수정 불가"(핵심 규칙
  14번, 5.2/8.2) 규칙 구현. `POST /pins/manual`(5.1.2)이 만드는 것도 결국 `start_type=manual`인
  태깅 세션이라, "수동 입력 음성"은 별도 엔드포인트가 아니라 `start_type=manual` 세션에서 만들어진
  음성과 동일한 개념으로 확인 후 반영.
- **영향 범위**: `travel/models.py`, `travel/views.py`(`_attach_voice_memo`).
- **관련 마이그레이션**: `travel/migrations/0002_remove_photo_tagging_session_photo_session_key_and_more.py`

### 2026-08-14 — [travel] 핀 place_name — 지오코딩 미연동으로 우선 null 고정
- **결정**: `POST /pins`에서 좌표가 있어도 `place_name`은 지금 단계에선 항상 `null`로 저장한다.
- **이유**: 역지오코딩(좌표→장소명) 연동이 프로젝트에 아직 없음. API 명세서도 "좌표를 확보하지
  못하면 place_name: null"만 명시하고 있어, 지오코딩 연동 전까지는 좌표가 있어도 동일하게
  처리하는 게 안전한 기본값.
- **미확정**: 지오코딩 서비스(Kakao/Google 등) 연동 여부·시점은 별도 확인 필요.
- **2026-08-15 갱신으로 대체됨(오류 정정)**: 이후 `POST /pins`(8.2) 최종 구현에서 역지오코딩은
  **프론트가 수행**하고 `city`/`country_name`/`address`를 요청 body에 실어 보내는 것으로 확정됨
  (`travel/views.py` `pin_create`가 `data.get("city")`/`data.get("country_name")`을 그대로
  저장). 즉 서버가 지오코딩을 못 해서 null이라는 이 항목의 전제는 더 이상 유효하지 않음.
  `place_name`은 애초에 지오코딩 대상이 아니라 "사용자가 직접 입력하는 상세 장소명"으로
  API 명세서에 정의되어 있었음(혼동 주의).

### 2026-08-14 — [travel] VoiceMemo.duration_sec — 임시로 0 고정
- **결정**: `POST /pins`, `PATCH /pins/{id}/context`에서 음성 저장 시 `duration_sec=0`으로
  고정한다.
- **이유**: `POST /uploads`, `PUT .../content`, `POST /pins` 어느 요청에도 클라이언트가
  음성 길이(초)를 실어 보내는 필드가 없다. 서버가 오디오 파일을 직접 디코딩해서 길이를 재는
  로직은 이번 범위에 없어 임시값으로 둠.
- **미확정**: 프론트가 `duration_sec`을 어느 요청에 실어 보낼지(또는 서버가 파일에서 직접
  추출할지) 확인 필요 — 확인되는 대로 이 항목 갱신.

### 2026-08-14 — [travel] 진행 중 여정 자동생성 시 이름 규칙 — 임시로 날짜 기반
- **결정**: `POST /tagging-sessions` 호출 시 진행 중인 `TravelSegment`가 없으면
  `"YYYY-MM-DD 여행"` 형식으로 자동 생성한다.
- **이유**: API 명세서에 자동생성 여정의 이름 규칙이 명시돼 있지 않음. 필수 필드라 임시값 필요.
- **미확정**: 실제 원하는 이름 규칙(예: 방문 국가/도시 기반) 확인 필요.

### 2026-08-14 — [travel] 여권 도장(COUNTRY_STAMP) 데이터 소스 부재 — 구조만 구현, 항상 빈 값
- **결정**: `GET /home`의 `passport_preview`, `GET /passport/stamps`는 응답 스키마·페이지네이션
  계약(`cursor`/`limit`/`next_cursor`)은 그대로 구현하되, 실제 값은 지금 단계에서 항상
  `stamp_count: 0, stamps: []`로 나간다.
- **이유**: `COUNTRY_STAMP`(국가/도시 집계)를 채우려면 핀의 국가/도시를 알아야 하는데, `Pin`에는
  좌표(`lat`/`lng`)만 있고 국가/도시 정보가 없다. `place_name`도 지오코딩 미연동으로 항상 `null`
  (2026-08-13 결정 참고). 핀 생성 흐름 어디에도 국가/도시를 입력받거나 계산하는 로직이 없어
  `CountryStamp` 행 자체가 생성될 방법이 없음.
- **영향 범위**: `travel/views.py`(`home`, `passport_stamps`). 모델/마이그레이션 변경 없음
  (`CountryStamp`는 이미 존재하는 테이블, 그대로 조회만 함 — 항상 빈 쿼리셋).
- **미확정**: 역지오코딩 연동 또는 국가 수동 입력 UI 중 어느 쪽으로 `CountryStamp`를 채울지 결정
  필요. 결정되는 대로 `home`/`passport_stamps`는 코드 변경 없이 자동으로 채워짐(쿼리 기반 구현).
- **2026-08-15 갱신으로 대체됨(오류 정정)**: `POST /pins`(8.2) 최종 구현에서 프론트가 역지오코딩한
  `country_name`을 요청 body로 보내고, 서버(`pin_create`)가 `resolve_country_code`로 변환해
  `CountryStamp.objects.get_or_create(...)`를 실행 — `CountryStamp` 행이 정상적으로 생성됨.
  `country_stamps`(3.3) 뷰도 실제 `CountryStamp` 쿼리 결과를 반환하도록 이미 구현되어 있어
  "항상 빈 값"이라는 이 항목의 결론은 더 이상 유효하지 않음. (`home`/`passport_preview`는 최종
  API 명세 채택 시점에 이미 전면 폐기되어 현재 코드에 없음 — 위 "최종 API 명세 채택" 항목 참고.)

### 2026-08-13 — 핀 수동 생성(5.1.2) 시 좌표는 사진이 아닌 세션 GPS 기준
- **결정**: 수동 핀 생성 시, 핀의 좌표는 업로드/촬영된 사진의 메타데이터가 아니라 **태깅 세션 시작 시점의 기기 GPS 좌표**로 결정한다.
  즉 "핀 먼저(위치 확정) → 사진 나중(그 세션에 연결)" 순서.
- **이유**: 기능명세서 8.1에 "촬영 파이프라인에서 사진 파일의 촬영 위치 정보가 생성되지 않으므로, 세션 시작 시점의
  위치 좌표를 별도 필드로 저장한다"고 명시되어 있어, 사진 자체엔 신뢰 가능한 좌표가 없다는 전제가 깔려 있음.
  5.4(주변 사진 추가)는 예외적으로 사진의 촬영 좌표를 쓰지만, 이는 기존 핀 보완용이지 핀 생성 로직과는 무관.
- **영향 범위**: taste/recommendations와 직접 관련 없으나(travel 앱 소관), 5.2.1 추천 스코어링 시 "핀 좌표"를 참조할 때
  이 기준(세션 GPS)을 신뢰하고 사용하면 됨.

### 2026-08-14 — [travel] Pin.included_in_segment 필드를 코드에 반영 (ERD 반영, 신규 아님)
- **결정**: `Pin`에 `included_in_segment`(불리언, 기본 `True`) 필드를 추가한다.
  `PATCH /trips/{tripId}`의 `pin_range`/`pin_overrides`(4.2)로 이 값을 조정하고,
  여정 상세 조회·사진 집계는 이 값이 `True`인 핀만 대상으로 한다.
- **이유**: 이 컬럼은 원래 최종 ERD에 이미 존재하던 컬럼인데(사용자 공유 ERD 스크린샷으로 확인)
  Django 코드에는 아직 반영이 안 되어 있었음. 새로 추가하는 스키마 변경이 아니라 기존 ERD를
  코드가 뒤늦게 따라잡는 것.
- **영향 범위**: `travel/models.py`(`Pin.included_in_segment`), `travel/views.py`
  (`_trip_detail`, `_trip_update`), `travel/serializers.py`(`PinRangeSerializer`,
  `PinOverrideSerializer`, `TripUpdateRequestSerializer`).
- **적용 순서**: `pin_range`를 먼저 적용(범위 밖 핀은 전부 제외로 리셋 후 범위 안만 포함)한 다음
  `pin_overrides`를 나중에 덮어쓴다 — 한 요청에 둘 다 오면 "나중 조작 우선" 원칙.
- **롤백 규칙**: 최종적으로 포함된 핀이 0개면 이번 PATCH 전체(이름/기간 변경 포함)를 롤백하고
  400(`VALIDATION_ERROR`)을 반환한다 — `transaction.atomic()` + `transaction.set_rollback(True)`.
- **관련 마이그레이션**: `travel/migrations/0003_pin_included_in_segment.py`

### 2026-08-14 — [travel] PATCH /trips/{tripId} 동시 수정 충돌(409) — 미구현
- **결정**: "동시 수정 충돌 시 409 CONFLICT" 케이스는 이번 구현에서 다루지 않는다.
- **이유**: API 명세서 요청 body(`name`/`start_at`/`end_at`/`pin_range`/`pin_overrides`)에 버전이나
  타임스탬프 등 충돌 감지에 쓸 수 있는 필드가 없어, 현재 스펙만으로는 "충돌"을 판별할 방법이 없음.
- **영향 범위**: `travel/views.py`(`_trip_update`)에 미구현 사유를 주석으로 남김.
- **미확정**: 충돌 감지 방식(예: `updated_at` 기반 낙관적 락, 버전 필드 추가 등)을 팀과 협의 필요.
  확정되면 이 항목 갱신 + 필요 시 API 명세서에 요청 필드 추가 논의.

### 2026-08-14 — [travel] 최종 API 명세(`Orte_API_명세서_최종.md`) 채택 — 태깅 세션 기반 구현 전면 폐기
- **결정**: 팀 합의된 최종 API 명세서(`docs/Orte_API_명세서_최종.md`, 사용자 업로드분)를 기준으로 travel 앱을
  전면 재설계한다. 기존에 만들었던 서명 토큰 기반 태깅 세션 구현(`POST /tagging-sessions` 등, #9/#10),
  `GET /home`/`GET /passport/stamps`(구 이슈1), `POST /trips/{tripId}/end`(구 이슈2),
  `GET`/`PATCH /trips/{tripId}`(구 이슈3, `pin_range`/`pin_overrides` 방식)는 전부 폐기한다.
- **이유**: 최종본은 "태깅 세션" 개념 자체를 없애고 "1태깅=1핀"으로 단순화했고(0-1절), 여행 진행 중에는
  `TRAVEL_SEGMENT` 레코드 자체가 없다가(`segment_id=NULL`인 핀 전체 = 진행중 여행) "여행 종료"
  시점에만 세그먼트가 생성되는 구조로 바뀌었다. 기존 세션 토큰 아키텍처와 근본적으로 양립 불가.
- **영향 범위**: `travel/models.py`(전면 재작성), `travel/tokens.py`(삭제), `travel/views.py`/
  `travel/serializers.py`/`travel/urls.py`(비워서 이슈 순서대로 재작성 예정), 기존 travel 마이그레이션
  전부 삭제 후 `0001_initial`로 재생성(로컬 개발 DB라 데이터 보존 없이 테이블을 지우고 새로 만듦 — 사용자 승인).
- **새 이슈 순서** (모두 이 최종본 기준, taskId #20~#30): 1) 모델 재설계 2) `POST /pins`(8.2, 핀 생성)
  3) `POST /pins/{pinId}/photos`(5.5, 사진 등록) 4) `GET /trips/current`(3.1) 5) `POST /trips`(3.2, 여행 종료)
  6) 여행 구간 관리(4.1~4.5) 7) 핀 조회/수정/삭제(5.1~5.3) 8) 사진 목록/삭제·음성메모 조회(5.4/5.7/5.8)
  9) 대표사진 새로고침(5.6, recommendations 담당자와 경계 협의 필요) 10) 국가별 도장 목록(3.3, 데이터 소스 미확정).
  products 앱 쪽(`7.1`/`7.2`/`8.1`)도 이 최종본 기준으로 달라져 별도 갱신 필요(순서 미정).

### 2026-08-14 — [travel] 모델 재설계 세부 결정 3가지
- **`TravelSegment.status`를 BooleanField로**: ERD가 BOOLEAN이라 그대로 반영. 세그먼트는 "여행 종료"
  시점에만 생성되므로 현재 흐름상 사실상 항상 `True` — 최종본 어디에도 `False`가 되는 케이스가 없음.
  나중에 아카이브/비활성화 같은 용도가 생기면 이 필드를 재활용할 수 있음.
- **`Photo.source_type`은 유지, 값은 사실상 항상 `"uploaded"`**: 최종본에서 사진 등록 경로가
  `POST /pins/{pinId}/photos`(5.5) 하나뿐이라 "촬영/업로드" 구분이 실질적으로 무의미해졌지만,
  ERD 컬럼이라 필드 자체는 지우지 않고 유지(choices도 그대로 남김).
- **`Pin.city`는 여전히 항상 null**: 최종본 5.1/3.3 문구가 "`PIN.도시` 값을 실시간 집계"를 전제하지만,
  좌표→도시 변환(지오코딩) 연동이 명세 어디에도 없어 채울 방법이 없음. `Pin.address`는 반대로 "프론트가
  역지오코딩해서 채워 보낸다"고 명시되어 있어(8.2) 요청으로 받은 값을 그대로 저장하면 되므로 문제 없음.
  **(2026-08-15 정정: 틀림 — `POST /pins`(8.2) 최종 구현은 `address`뿐 아니라 `city`/`country_name`도
  전부 프론트가 역지오코딩해서 요청 body로 보내고 서버가 그대로 저장하는 구조로 확정됨. `Pin.city`는
  더 이상 항상 null이 아니며, `country_name`은 `CountryStamp` 생성에도 쓰임. `travel/views.py`의
  `pin_create` 참고.)**

### 2026-08-14 — [travel] POST /pins(8.2) 구현 — nfc_tag_id/audio_file 처리 방식 확정
- **결정 1 (`audio_file`)**: 필드명은 `audio_file`이지만 실제 값은 `uploads` 앱에서 발급받은
  `file_id`로 취급한다. `resolve_and_consume`으로 검증·소모 처리 후 절대 URL로 변환해
  `VoiceMemo.audio_url`에 저장. 5.5(사진 등록)의 `file_id`와 일관된 방식.
- **결정 2 (`nfc_tag_id` 미등록/미소유 태그)**: `POST /pins` 호출 시 `nfc_tag_id`가 이 계정에
  연결되어 있지 않으면(태그가 없거나, 다른 계정 소유이거나, `unlinked_at`이 설정된 경우) `400
  VALIDATION_ERROR`로 거부한다. 자동 등록하지 않음 — 8.1(`PATCH /products/{tagId}/link`)이 먼저
  호출되어 있어야 한다는 전제.
- **결정 3 (태깅 횟수 집계)**: `PIN` 테이블엔 태그를 참조하는 컬럼이 없어(ERD 확인) 핀 생성마다
  `NfcTag.tag_count`를 `F()` 표현식으로 +1 하는 카운터 방식을 쓴다. 7.1의 "태깅 횟수 = 이 태그로
  생성된 핀 수"를 이 카운터로 충족.
- **이유**: 세 가지 모두 최종 명세 원문에 명시적으로 안 나와 있어 확인 후 결정(택1: 추천안 채택).
- **영향 범위**: `travel/views.py`(`pin_create`), `travel/serializers.py`(`PinCreateRequestSerializer`).
  핀 생성과 태그 카운터 증가, 음성 첨부는 `transaction.atomic()`으로 묶여있어 음성 첨부 실패 시
  핀 생성까지 전부 롤백된다(#9/#10에서 확인한 것과 동일한 원자성 패턴).

### 2026-08-14 — [accounts] 최종 API 명세 기준 재설계 — ID 토큰 로그인 + session_token 단일 발급
- **결정 1 (로그인 흐름)**: `POST /auth/google`이 받는 값을 `code`(구글 인가코드) →
  `google_id_token`(프론트가 구글 로그인 SDK로 이미 발급받은 ID 토큰)으로 변경. 서버는
  `google-auth` 라이브러리로 이 토큰을 구글 공개키로 검증만 하고, 기존처럼 구글 토큰
  엔드포인트와 통신(코드 교환 + userinfo 조회)하지 않는다. **프론트가 로그인 SDK 사용
  방식을 바꿔야 하는 변경이라 프론트 팀 확인 필요** (사용자에게 별도 안내함).
- **결정 2 (토큰 발급)**: `access_token`/`refresh_token` 2개 발급 → `session_token` 1개
  발급으로 변경. 최종본에 refresh 엔드포인트가 없어서 `POST /auth/token/refresh`는
  삭제. 수명은 재로그인 빈도를 낮추기 위해 14일로 설정(`config/settings.py`
  `SIMPLE_JWT.ACCESS_TOKEN_LIFETIME`) — 원문에 명시 없어 확인 후 결정.
- **결정 3 (User 모델)**: `google_id`→`account_identifier`로 이름 변경(ERD 컬럼명),
  `display_name`/`last_login_at`은 최종 ERD에 없어 완전 삭제 — 확인 후 결정.
- **결정 4 (엔드포인트 삭제)**: `GET /users/me/permissions`(권한 요약 조회),
  `POST /users/me/permission-intro-ack`는 최종본에 없어 삭제. `permission_intro_shown`은
  신규 `PATCH /users/me`(1.4)로 직접 덮어쓰는 방식으로 대체 — 확인 후 결정. **프론트가
  이 두 엔드포인트를 이미 쓰고 있었다면 영향 있음** (사용자에게 별도 안내함).
- **영향 없음**: `POST /events/permissions`(1.5)는 필드(`permission_type`/`status`/`os`)가
  최종본과 이미 일치해 변경 없음.
- **영향 범위**: `accounts/models.py`, `accounts/views.py`(전면 재작성), `accounts/serializers.py`,
  `accounts/urls.py`, `accounts/authentication.py`(주석만 갱신, 검증 로직은 동일),
  `config/settings.py`(SIMPLE_JWT, REFRESH_TOKEN_LIFETIME 제거), `pyproject.toml`
  (`google-auth` 의존성 추가 — `poetry install` 필요).
- **관련 마이그레이션**: `accounts/migrations/0004_remove_user_display_name_remove_user_google_id_and_more.py`

### 2026-08-14 — [전체] 응답 포맷 — success/data 래핑 대신 평평한 형태 유지
- **결정**: 최종 API 명세서 "0-2 공통사항"이 `{success, data}`/`{success, error}` 래핑을
  선언하지만, 문서 전체에서 실제로 이 래핑을 쓰는 예시는 5.5의 409 CONFLICT 하나뿐이고
  나머지 모든 성공/실패 예시는 래핑 없는 평평한 JSON이다. 원문 내부 모순으로 판단,
  지금까지 구현해온 방식(평평한 `{message, code}` 에러 / 필드 그대로 노출하는 성공 응답)을
  그대로 유지하기로 확정.
- **이유**: 실제 각 엔드포인트 예시(반례 없음)가 공통사항 선언보다 훨씬 많고 구체적이라
  더 신뢰할 수 있는 근거로 판단. 확인 후 결정.
- **영향 범위**: 전 앱 공통. 5.5의 409 CONFLICT 응답도 예시의 `{success, error}` 형태
  대신 `{message, code}`로 통일해서 구현(`travel/views.py pin_photos_register`).

### 2026-08-14 — [travel] POST /pins/{pinId}/photos(5.5) 반경 검증·잘못된 file_id 처리
- **결정 1**: 핀 자체에 좌표가 없으면(위치권한 거부 등) 반경 1km 검증을 생략하고, 좌표가
  있는 사진은 전부 등록 대상으로 취급한다(기준점이 없어 거리 계산 자체가 불가능).
- **결정 2**: `file_id`가 유효하지 않으면(만료/이미사용/업로드 안됨/남의 파일/타입 불일치)
  원문의 `OUT_OF_RADIUS`/`MISSING_COORDINATES`와 같은 패턴으로 `rejected`에
  `"INVALID_FILE"` reason을 추가해 그 사진만 제외하고 나머지는 정상 등록한다 — 원문이
  명시한 "반경 밖/좌표 없는 사진만 제외, 요청 전체는 거부하지 않음" 원칙을 그대로 확장.
- **영향 범위**: `travel/views.py`(`pin_photos_register`, `_distance_km` — Haversine 공식).
  둘 다 확인 후 결정.

### 2026-08-14 — [travel] POST /pins — city 필드 신규 요청(API 계약 변경, 프론트 확인 필요)
- **결정**: `POST /pins`(8.2) 요청에 선택 필드 `city`(string)를 새로 추가한다. 프론트가 이미
  수행하는 역지오코딩 결과에서 뽑은 도시명을 그대로 실어 보내면 `Pin.city`에 저장한다.
- **이유**: PM 요청으로 `POST /trips`(3.2) 자동 여행 이름 생성 규칙을 "방문 도시 나열"
  방식으로 바꾸기로 함(아래 항목). 서버는 좌표만으로 도시명을 알 수 없어 프론트가 가진
  역지오코딩 결과를 요청에 실어 받는 것 외엔 방법이 없음.
- **영향 범위**: `travel/serializers.py`(`PinCreateRequestSerializer.city`),
  `travel/views.py`(`pin_create`). **API 계약 변경 — 프론트 팀에 별도 전달함.**
- **하위호환**: 선택 필드라 `city`를 안 보내도 요청 자체는 그대로 동작(`Pin.city=null`),
  이 경우 여행 이름은 날짜 기반으로 자동 폴백.

### 2026-08-14 — [travel] POST /trips(3.2) 구현 — 자동 여행 이름 생성 규칙 확정
- **결정**: `name`을 안 보내면, 배정 대상 핀(`segment_id IS NULL`) 전체를 `tagged_at` 순으로
  훑어 `city`가 있는 값만 모으고, 같은 도시가 연속/비연속으로 여러 번 나와도 처음 등장한
  순서 기준으로 한 번만 남긴 뒤(`", "`로 join) 이름으로 쓴다. `city` 있는 핀이 하나도 없으면
  `"YYYY-MM-DD 여행"`(당일) 또는 `"YYYY-MM-DD~YYYY-MM-DD 여행"`(복수일) 형식으로 폴백한다.
- **이유**: PM이 날짜 기반 대신 방문 도시 나열 방식을 요청. `city` 필드가 이제 막
  추가되어(위 항목) 당분간 대부분 요청엔 `city`가 비어 있을 것이므로 날짜 폴백을 항상
  같이 구현해 이름이 비는 상황을 방지.
- **결정(배정/포함 판단)**: `start_at`은 배정 대상 중 가장 이른 `tagged_at`, `end_at`은
  요청값이 없으면 가장 늦은 `tagged_at`. `end_at`보다 늦게 태깅된 핀도 세그먼트에는
  배정하되(`segment` FK만 연결) `included_in_segment=False`로 자동 제외한다. 배정 대상이
  0개이거나, 배정 후 포함 핀이 0개가 되면(과거 시각의 `end_at` 지정 등) 둘 다 409
  `CONFLICT`로 거부한다.
- **결정(photobook_id)**: `photobooks` 앱이 아직 없어 응답의 `photobook_id`는 항상 `null`
  스텁으로 둔다. 앱이 생기면 별도 이슈로 실제 생성 연결.
- **영향 범위**: `travel/views.py`(`trip_create`, `_default_trip_name`),
  `travel/serializers.py`(`TripCreateRequestSerializer`), `travel/urls.py`. 모델 변경 없음
  (`Pin.city`/`TravelSegment`는 이슈1에서 이미 존재).
- **검증**: `/tmp` 샌드박스에서 sqlite3로 마이그레이션(변경 없음 확인) + APIClient 스모크
  테스트 15건(핀 없음 409, 도시 중복제거, name 오버라이드, 날짜 폴백, end_at 부분 포함/제외,
  end_at으로 전부 제외 시 409) 전부 통과.

### 2026-08-14 — [travel] Pin.segment on_delete: SET_NULL → CASCADE (모델 변경, 마이그레이션)
- **결정**: `Pin.segment`의 `on_delete`를 `SET_NULL`에서 `CASCADE`로 변경.
- **이유**: 원문 0-1/4.4에 "여행 구간 삭제 시 핀·사진·음성메모·포토북까지 DB
  `ON DELETE CASCADE`로 강제 삭제"라고 명시. `SET_NULL`이면 세그먼트를 지워도
  핀이 `segment=NULL`로 풀려 "진행 중 여행"으로 되살아나는 버그가 됨.
- **영향 범위**: `travel/models.py`(`Pin.segment`). `null=True`는 유지 —
  진행 중 여행(핀 생성 시 `segment=NULL`)은 그대로 동작하고, 세그먼트 "자체가
  삭제될 때"의 동작만 바뀐 것.
- **관련 마이그레이션**: `travel/migrations/0002_alter_pin_segment.py`

### 2026-08-14 — [travel] 이슈6: 여행 구간 관리(4.1~4.5) 구현
- **엔드포인트**: `GET/POST /trips`(4.1 목록/3.2 종료, 같은 경로라 하나의
  dispatcher `trip_list_or_create`로 묶음), `GET/PATCH/DELETE /trips/{segmentId}`
  (4.2~4.4, `trip_detail` dispatcher), `GET /trips/{segmentId}/pins`(4.5).
- **페이지네이션**: 0-2 공통사항의 커서 방식을 서명 없는 평문 id 커서로 구현
  (`_parse_pagination`). 4.1은 `segment_id` 내림차순(최근 종료 여행 먼저),
  4.5는 `pin_id` 오름차순(태깅 순서 프록시). 모든 목록 쿼리가 `request.user`로
  필터링돼 있어 커서를 서명하지 않아도 다른 사용자 데이터 열람은 불가 — 확인 후 결정.
  `limit` 기본 20/최대 100, 잘못된 cursor/limit 값은 에러 대신 기본값으로 무시.
- **4.2 pin_count/photo_count**: `included_in_segment=True`인 핀만 집계
  (원문 예시와 일치, 4.5는 반대로 제외된 핀도 플래그와 함께 전부 노출).
- **4.3 pin_exclusions 검증 (확인 후 결정)**: 이 세그먼트 소속이 아니거나
  본인 소유가 아닌 `pin_id`가 하나라도 섞이면 요청 전체를 400
  `VALIDATION_ERROR`로 거부한다(일부만 조용히 무시하지 않음). 반영 후 포함
  핀이 0개가 되면 이름 변경까지 포함해 전체를 롤백(`transaction.atomic()` +
  `set_rollback`)하고 400 반환 — 기존 구 이슈3(`pin_range`/`pin_overrides`
  롤백) 패턴 재사용. `start_at`/`end_at`은 남은 포함 핀 기준 자동 재계산.
- **포토북 재생성/삭제 — 스킵**: 4.3(포함 핀 변경 시 포토북 재생성), 4.4
  (세그먼트 삭제 시 포토북 함께 삭제)는 `photobooks` 앱이 아직 없어 구현
  불가. 로그만 남기고 실제 동작 없음(3.2 `photobook_id: null` 결정과 동일
  맥락) — 앱 생기면 별도 이슈로 진행.
- **소유권 체크**: 기존 패턴 유지(`.get(pk=..., user=request.user)` +
  `DoesNotExist` → 404, `PERMISSION_DENIED`와 구분 안 함 — 존재 여부 자체를
  노출하지 않는 쪽이 더 안전하다고 판단).
- **영향 범위**: `travel/models.py`(위 CASCADE 변경), `travel/views.py`
  (`trip_list_or_create`, `trip_detail`, `trip_pins`, `_parse_pagination`),
  `travel/serializers.py`(`TripPatchRequestSerializer`,
  `PinExclusionItemSerializer`), `travel/urls.py`.
- **검증**: `/tmp` 샌드박스에서 sqlite3로 마이그레이션 재생성·적용 확인 +
  APIClient 스모크 테스트 37건(목록 페이지네이션·타 유저 격리, 상세 집계,
  핀 목록 페이지네이션·제외 핀 노출, 이름만 수정, pin_exclusions 반영,
  소속 아닌 pin_id 거부 시 이름도 롤백, 전부 제외 시 롤백, cascade 삭제,
  전 구간 404 처리) 전부 통과.

### 2026-08-14 — [travel] VoiceMemo.duration_sec 추가 — 임시로 0 고정
- **결정**: `VoiceMemo`에 `duration_sec`(IntegerField, 기본 0) 추가.
- **이유**: 5.1(`GET /pins/{pinId}`) 응답의 `voice_memo`에 `duration_sec`이
  필요한데, `POST /uploads`·`PUT .../content`·`POST /pins` 어느 요청에도
  클라이언트가 음성 길이(초)를 실어 보내는 필드가 없고 서버가 오디오를 직접
  디코딩하는 로직도 이번 범위에 없음 — 이전 구 스펙 구현 때와 동일한 미확정
  사유. 5.8(`GET /pins/{pinId}/voice-memos`) 응답엔 `duration_sec`이 없어
  영향 없음.
- **영향 범위**: `travel/models.py`(`VoiceMemo.duration_sec`),
  `travel/views.py`(`_pin_detail_get`).
- **관련 마이그레이션**: `travel/migrations/0003_voicememo_duration_sec.py`
- **미확정**: 프론트가 길이를 어느 요청에 실어 보낼지, 또는 서버가 파일에서
  직접 추출할지 — 확인되는 대로 이 항목 갱신.

### 2026-08-14 — [travel] 이슈7: 핀 조회/수정/삭제(5.1~5.3) 구현
- **엔드포인트**: `GET/PATCH/DELETE /pins/{pinId}` 하나의 dispatcher(`pin_detail`)로 묶음.
- **5.1 representative_photos**: `Photo.is_main=True`인 것만 반환. 대표사진
  선정 로직(5.6, 이슈9)이 아직 없어(recommendations 팀 협의 대기) 지금은
  항상 빈 배열 — 사용자 확인 후 예정된 동작으로 진행.
- **5.2 수정 가능 필드**: `place_name`/`text_note`만. 원문 규칙대로 좌표·주소·
  음성메모는 요청에 와도 무시(애초에 시리얼라이저에 필드 자체가 없음).
- **5.3 삭제 제약**: `segment_id IS NULL`(진행 중)인 핀만 삭제 가능. 이미
  배정된 핀은 409(`code: "CONFLICT"`, 메시지에 "여행 구간 편집에서
  제외해주세요" 안내 — 원문의 괄호 라벨 `USE_TRIP_EXCLUSION`은 실제 코드값
  대신 메시지로 녹임, 기존 CONFLICT 코드 컨벤션과 동일). 삭제 시 연결된
  사진·음성메모는 기존 `on_delete=CASCADE`로 자동 삭제.
- **결정(NfcTag.tag_count 미조정)**: 핀 삭제 시 태그의 `tag_count`는 감소시키지
  않는다 — 원문에 명시 없고, "생성된 핀 수" 누적 카운터로 유지하는 쪽이 단순함.
  나중에 "현재 존재하는 핀 수" 의미로 바꿔야 한다면 재검토.
- **영향 범위**: `travel/views.py`(`pin_detail` 및 하위 3개 헬퍼),
  `travel/serializers.py`(`PinUpdateRequestSerializer`), `travel/urls.py`.
- **검증**: `/tmp` 샌드박스에서 sqlite3로 마이그레이션 재생성·적용 확인 +
  APIClient 스모크 테스트 26건(상세 조회·음성메모/대표사진 유무, 부분 수정,
  진행중/배정됨 삭제 분기, cascade 삭제, 전 구간 404 처리) 전부 통과.

### 2026-08-14 — [travel] 이슈8: 사진 목록/삭제 + 음성메모 조회(5.4/5.7/5.8) 구현
- **엔드포인트**: `GET/POST /pins/{pinId}/photos`(5.4 목록/5.5 등록, 기존 `pin_photos_register`를
  `pin_photos` dispatcher로 확장), `DELETE /photos/{photoId}`(5.7, 신규 최상위 경로),
  `GET /pins/{pinId}/voice-memos`(5.8).
- **5.4 필드명**: 원문 그대로 `file_path`(내부 `Photo.photo_url` 값), `is_pin_cover`
  (내부 `is_main`) 사용. `photo_id` 오름차순 커서 페이지네이션(기존 4.1/4.5와 동일 방식).
- **5.7 대표사진 자동 대체 (확인 후 결정)**: 삭제된 사진이 `is_main=True`였을 때만
  같은 핀의 나머지 `is_main=False` 사진 중 1장을 `order_by("?")`(DB 레벨 랜덤)로 뽑아
  대체한다. 취향 기반 정렬(5.6/이슈9)은 아직 없어 여기서는 단순 랜덤으로 처리 — 이슈9
  구현 후 재검토 여지 있음. 대체할 사진이 없으면 그냥 대표사진 수가 줄어든 채로 둔다.
  삭제된 사진이 원래 대표사진이 아니었으면 아무 것도 건드리지 않는다.
- **5.8 vs 5.1 응답 차이**: 5.8은 `audio_file`(재생 URL)/`saved_at`을 포함하고
  `duration_sec`은 없음(5.1과 반대) — 원문 각 절 응답 예시를 그대로 따름.
- **영향 범위**: `travel/views.py`(`pin_photos`/`_pin_photos_list`/`_pin_photos_register`,
  `photo_delete`, `pin_voice_memos`), `travel/urls.py`. 모델/시리얼라이저 변경 없음.
- **검증**: `/tmp` 샌드박스에서 makemigrations로 변경 없음 확인 + APIClient 스모크
  테스트 24건(목록 페이지네이션·필드명, 대표사진 아닌 사진 삭제 시 영향 없음, 대표사진
  삭제 시 자동 대체, 대체 후보 없을 때 정상 처리, 음성메모 유무·필드 구성, 전 구간 404
  처리) 전부 통과.

### 2026-08-14 — [travel] POST /pins — country_code/country_name 필드 신규 요청(API 계약 변경, 프론트 확인 필요)
- **결정**: `POST /pins`(8.2) 요청에 선택 필드 `country_code`, `country_name`을
  새로 추가한다. `city`와 동일한 패턴 — 프론트가 이미 하는 역지오코딩 결과에서
  국가 정보도 같이 뽑아 보내면 서버가 `CountryStamp`에 반영한다.
- **이유**: 3.3(`GET /users/me/country-stamps`) 구현을 위해 국가 정보가
  필요한데, `Pin`엔 좌표만 있고 지오코딩 연동이 없어 서버가 자체적으로 국가를
  판별할 방법이 없음. `city`를 핀 생성 시점에 받기로 한 것과 같은 이유로
  같은 요청에 묶는 게 프론트 입장에서도 자연스러움(한 번의 역지오코딩 결과를
  한 번에 전송).
- **영향 범위**: `travel/serializers.py`(`PinCreateRequestSerializer`),
  `travel/views.py`(`pin_create`). **API 계약 변경 — 프론트 팀에 city 필드와
  함께 전달 예정.**
- **하위호환**: 선택 필드라 안 보내도 요청은 그대로 동작(도장 안 쌓임).

### 2026-08-14 — [travel] 이슈10: 국가별 도장 목록(3.3) 구현
- **결정 1 (적립 방식)**: `POST /pins`에 `country_code`+`country_name`이 둘 다
  오면 `CountryStamp.objects.get_or_create(user=, country_code=, defaults={country_name})`
  로 적립. 이미 있는 국가면 중복 생성 안 함(모델의 `unique_together`가 이미 보장).
- **결정 2 (영구 보존, 확인 후 결정)**: 그 나라의 핀을 나중에 전부 삭제해도
  `CountryStamp`는 지우지 않는다 — "방문 도장"이라는 개념상 한 번 찍힌 도장은
  없어지지 않는 여권 스탬프 컨셉으로 판단. 원문에 명시적 규칙은 없음.
- **결정 3 (응답, 페이지네이션 없음)**: 원문 3.3 응답 예시에 `next_cursor`가
  없어 이 목록은 페이지네이션 없이 전체를 한 번에 반환한다(국가 개수가
  많아야 수십 개 수준이라 커서가 필요 없다고 판단). 정렬은 `id`(적립 순서)
  오름차순.
- **영향 범위**: `travel/views.py`(`pin_create`에 적립 로직 추가,
  `country_stamps` 신규), `travel/serializers.py`(위 필드 추가),
  `travel/urls.py`. `CountryStamp` 모델 자체는 변경 없음(이미 존재하던 필드로
  충분).
- **검증**: `/tmp` 샌드박스에서 makemigrations로 모델 변경 없음 확인 +
  APIClient 스모크 테스트 13건(빈 목록, 같은 국가 중복 적립 방지, 국가 필드
  없는 핀은 적립 안 됨, 적립 순서 정렬, 핀 삭제 후에도 도장 유지, 타 유저
  격리) 전부 통과.

### 2026-08-14 — [travel] country_code를 프론트 요청이 아닌 서버 자체 매핑으로 계산하도록 변경
- **결정**: 이슈10 초기 구현은 `POST /pins`에서 `country_code`/`country_name`을
  둘 다 프론트에서 받는 구조였는데, 이를 폐기하고 `country_name`(한글 국가명)만
  받아 서버가 `travel/country_codes.py`의 정적 매핑 테이블로 ISO 3166-1 alpha-2
  코드("KR", "JP" 등)를 직접 계산하는 방식으로 변경.
- **이유**: 원문 3.3 응답 예시의 `country_code`(82, 81)가 국제전화 국가번호
  스타일이라 표준 국가 코드 체계와 다르고, 프론트가 쓰는 역지오코딩 API마다
  국가 코드 형식이 다르거나 아예 안 줄 수도 있어 프론트에 추가로 물어봐야 할
  게 많았음. 반면 국가명(한글 표시명)은 프론트가 화면에 어차피 보여줘야 해서
  이미 갖고 있을 값이라, 서버가 이름→코드 변환을 전담하면 프론트 쪽 확인
  없이 바로 진행 가능 — 확인 후 결정.
  국가명이 매핑 표에 없으면(오타, 흔치 않은 표기 등) 도장을 생성하지 않고
  조용히 스킵한다(에러 없음). 매핑 표는 195개국 전부를 처음부터 커버하진
  않고, 실제로 필요한 국가가 나올 때마다 추가하는 방식으로 운영.
- **영향 범위**: `travel/serializers.py`(`PinCreateRequestSerializer`에서
  `country_code` 필드 제거, `country_name`만 유지), `travel/views.py`
  (`pin_create`가 `resolve_country_code` 호출), `travel/country_codes.py`
  (신규 — 한글 국가명→ISO 코드 정적 매핑 테이블 + `resolve_country_code`).
  이전에 작성한 `docs/API_CHANGES.md`의 `country_code` 요청 필드 안내는 이
  변경으로 무효 — 최신 내용으로 갱신함.
- **검증**: `/tmp` 샌드박스에서 makemigrations로 모델 변경 없음 확인 +
  스모크 테스트 14건(매핑 조회 기본/별칭/공백처리/미확인 국가, 클라이언트가
  `country_code`를 억지로 보내도 서버가 무시하고 자체 계산, 미확인 국가명은
  에러 없이 도장 생략) 전부 통과.

### 2026-08-14 — [products] 최종 API 명세 기준 3개 엔드포인트 구현 (7.1/7.2/8.1)
- **엔드포인트**: `GET /users/me/products`(7.1), `PATCH /products/{tagId}/unlink`(7.2),
  `PATCH /products/{tagId}/link`(8.1). `products/urls.py` 신규 생성, `config/urls.py`에
  include 추가.
- **7.1 product_type 대문자 변환**: 모델엔 소문자로 저장(`bag`/`charm`/`keyring`/`unknown`)
  하지만 원문 응답 예시가 대문자(`"BAG"`)라 응답 직렬화 시점에만 `.upper()`로 변환한다.
  저장 형식(모델 choices)은 그대로 유지 — 확인 후 결정.
- **8.1 link 분기 로직 (확인 후 결정, 원문에 세부 규칙 없음)**:
  - 태그가 아예 없으면 새로 생성(`product_type="unknown"`, `product_name=null`)하고
    이 계정에 연결.
  - 있는데 과거에 연결 해제된 태그(`unlinked_at IS NOT NULL`)면 이 계정으로 재연결
    (`unlinked_at`을 다시 `null`로).
  - 있는데 다른 계정이 이미 연결 중이면(`unlinked_at IS NULL`, 다른 `user`) 409
    `CONFLICT` — 7.5의 "하나의 태그는 하나의 계정에만 등록" 원칙.
  - 이미 이 계정이 연결 중이면 그대로 200 반환(멱등 처리, 아무것도 안 바꿈).
  - `tag_count`는 연결 해제/재연결 어느 경우에도 리셋하지 않는다 — 원문이 "다중
    사용자 태깅은 스코프 밖, 태그:계정 사실상 1:1"로 이미 못 박아 둬서, 재연결 시
    이전 소유자의 카운트가 새 소유자에게 그대로 보이는 것도 스코프 밖 취급.
- **소유권 체크**: 기존 패턴 유지 — unlink는 `.get(pk=, user=request.user,
  unlinked_at__isnull=True)` + 404. link는 태그 존재 여부와 무관하게 무조건 200/409만
  응답하므로 별도 404 없음.
- **영향 범위**: `products/views.py`(전면 구현), `products/urls.py`(신규),
  `config/urls.py`(include 추가). 모델 변경 없음(이미 이슈3에서 필요한 필드 다 갖춤).
- **검증**: `/tmp` 샌드박스에서 makemigrations로 모델 변경 없음 확인 + APIClient
  스모크 테스트 24건(신규 태그 자동생성, 목록 조회·대문자 변환·카운트, 동일 계정
  재연결 멱등성, 타 계정 소유 태그 연결 시도 409, 연결 해제·해제 후 목록 미노출·
  이중 해제 404, 해제된 태그를 다른 계정이 재연결 성공, 비소유 태그 해제 404)
  전부 통과.

---

### 2026-08-15 — [travel] 4.3 여행 구간 날짜 직접 수정 + dates_manually_set 플래그
- **결정**: `PATCH /trips/{segmentId}`(4.3)에 `start_at`/`end_at` 선택 필드 추가. 직접
  보내면 그 범위 안의 핀만 자동으로 `included_in_segment=true`, 밖은 `false`로 설정된다
  (같은 요청의 `pin_exclusions`가 있으면 그게 우선 적용됨). `TravelSegment.dates_manually_set`
  (기본 `False`)을 추가해서, 한 번이라도 직접 날짜를 지정하면 그 이후엔 `pin_exclusions`만
  오는 요청에서 날짜를 자동 재계산하지 않고 유지한다. 한 번도 직접 지정한 적 없으면
  기존처럼 포함 핀 기준 자동 계산 유지. `POST /trips`(3.2)에서 `end_at`을 직접 입력한
  경우도 동일하게 처음부터 `dates_manually_set=True`로 생성한다(일관성).
- **이유**: PM 요청 — 사진을 안 찍은 날도 실제로는 여행 중이었을 수 있는데, "마지막 태깅
  시각 = 여행 종료 시각"으로 자동 계산하면 그런 날이 여행 기간에서 빠짐. 그렇다고 자동
  계산 기능 자체를 없애면 날짜를 한 번도 안 만진 사용자 경험이 나빠져서, "직접 지정한
  적 있는지" 상태를 플래그로 기억해 두 경우를 다 지원하기로 함.
- **영향 범위**: `travel/models.py`(`TravelSegment.dates_manually_set` 추가),
  `travel/migrations/0004_travelsegment_dates_manually_set.py`,
  `travel/serializers.py`(`TripPatchRequestSerializer`에 필드 추가 + `start_at<=end_at` 검증),
  `travel/views.py`(`_trip_detail_patch`, `_trip_create`).
- **검증**: sqlite 대체 스모크 테스트 3건 — (1) 날짜 직접 지정 시 범위 밖 핀 자동 제외 +
  플래그 True 전환, (2) 플래그 True 상태에서 `pin_exclusions`만 보내도 날짜 유지,
  (3) 플래그 False인 여정은 기존처럼 포함 핀 기준 자동 재계산 — 전부 통과.

### 2026-08-15 — [travel] 5.5 종료된 여정의 핀에도 사진 수동 추가 허용
- **결정**: `POST /pins/{pinId}/photos`에서 `pin.segment_id`가 채워진(이미 종료된 여행)
  경우 409로 거부하던 걸 없애고, 모든 핀에 사진을 추가할 수 있게 변경. 대표사진(`is_main`)은
  자동으로 재선정하지 않고 그대로 유지(원래도 등록 시점에 `is_main`을 건드리지 않았어서
  코드 변경 없이 자연스럽게 충족됨) — 바꾸고 싶으면 5.6(대표사진 새로고침)을 수동으로 호출.
  포토북 즉시 재생성은 `photobooks` 앱이 없어 로그만 남기고 스킵(4.3의 포토북 재생성
  스킵과 동일 패턴) — 앱 생기면 반영 필요.
- **이유**: 프론트 질문("종료된 여정 핀엔 사진 추가 안 되는 게 맞나요")에 PM이 "추후 가능하게
  하자고 했던 걸로 기억한다"고 답변. 대표사진/포토북 갱신 이슈를 팀에서 논의한 결과, 비용
  문제 없으면 포토북은 즉시 재생성, 대표사진은 수동 전환 가능하니 그대로 유지하기로 결정.
- **영향 범위**: `travel/views.py`의 `_pin_photos_register`(5.5). `DELETE /photos/{photoId}`
  (5.7)는 원래도 이 제약이 없었어서 변경 없음(이미 대칭이었음).
- **최종 확정 (2026-08-15 오전, 팀 논의)**: 사진 수동 추가 자체는 여정 종료 여부·핀의
  `included_in_segment` 값과 무관하게 전부 허용. 다만 종료된 여정에 **포함된**
  (`included_in_segment=true`) 핀에 사진이 추가된 경우에 한해 그 여정의 포토북을 재생성
  대상으로 본다(제외된 핀에 사진이 추가돼도 포토북엔 영향 없음 — 애초에 그 핀이 포토북에
  안 들어가니까). 대표사진은 추가 시점엔 안 바뀌고, 5.6(대표사진 새로고침, 이슈9 구현 시)을
  호출하면 그 시점에 새로 추가된 사진까지 포함해서 재선정돼야 한다 — 이슈9 설계에 반영 예정.
  위치정보 유실 우려(팀 질문)는 검토 결과 문제없음: `latitude`/`longitude`는 이미지 EXIF가
  아니라 요청 body에 별도 필드로 명시적으로 받고 있고, 값이 없으면 애초에
  `MISSING_COORDINATES`로 등록 자체가 거부돼(핀에 안 붙음) 포토북 재생성에 위치정보 없는
  사진이 섞여 들어갈 수 없음.
- **미확정**: 포토북 즉시 재생성 로직 자체는 `photobooks` 앱 구현 시점에 마저 붙여야 함.

## 2026-08-15: photobooks 앱 신설 — 모델 설계 + 6.1/6.2/6.3 구현 (#53)

- **배경**: 포토북 6.1(목록)/6.2(상세)/6.3(이름 수정)을 구현하며 `photobooks` 앱을 처음 만듦.
  6.4(커버 새로고침)는 recommendations 스코어링 함수가 아직 없어(#28과 동일한 블로커) 이번
  범위에서 제외.
- **`PhotobookPin`/`PhotobookPhotoLayout` 중간 테이블 미생성**: 구 ERD(spec.md)엔 있었지만,
  최종 API 응답(6.2)이 핀 목록을 `segment_id` 기준으로 바로 집계해서 내려주는 구조라(4.5
  `trip_pins`와 동일 패턴) 별도 조인 테이블 없이 `Photobook.segment`(OneToOne)만으로 충분함.
  필요해지면 그때 추가.
- **`Photobook.name`은 `TravelSegment.name`과 독립**: 생성 시점(3.2, `POST /trips`)에
  `segment.name`을 복사해오지만, 이후 6.3으로 포토북 이름만 수정해도 여행 구간 이름엔 영향
  없음(반대도 마찬가지). 스펙 원문에 명시가 없어 자체 결정 — 두 화면(여행 구간 편집 vs
  포토북)의 이름 수정 액션이 서로 다른 사용자 의도(여행 자체 이름 vs 포토북 표지 이름)라고
  보는 게 자연스럽다고 판단.
- **`cover_photo_url`은 생성 시 null**: 최초 커버 사진 선정도 취향 프로파일 스코어링(1등 확정)이
  필요한데 recommendations 앱이 아직 없어 호출 대상이 없음. 6.4(새로고침, 상위10 랜덤)와 완전히
  같은 스코어링 함수를 재사용하는 구조라, recommendations 담당자가 함수를 만들 때 최초 선정
  로직과 6.4를 함께 붙이는 게 효율적 — 이슈9(#28)와 묶어서 처리 예정.
- **`_trip_create`(3.2)에 자동 생성 훅 추가**: `TravelSegment` 생성과 같은 트랜잭션 안에서
  `Photobook.objects.create(segment=segment, name=segment.name)` 호출. 응답의 `photobook_id`가
  이제 실제 값으로 채워짐(이전엔 `photobooks` 앱이 없어 항상 `null`이었음).
- **검증**: sqlite 대체 테스트로 (1) 3.2 호출 시 포토북 자동 생성 + `photobook_id` 응답 반영,
  (2) 6.1 목록의 `cities`/`photo_count` 실시간 집계, (3) 6.2 `total_days` 계산 및 `pins` 시간순
  정렬, (4) 6.3 이름 수정 시 `segment.name` 불변, (5) 타 계정 접근 404 — 전부 통과 확인.

### 2026-08-15 — [travel] 핀 대표사진 선정을 `is_main`(Boolean)에서 `taste_rank`(Integer)로 변경
- **결정**: `Photo.is_main` 삭제 → `Photo.taste_rank`(IntegerField, null=True) 추가. 핀에 속한
  사진은 몇 장이든(1장이어도) 전부 순위를 매긴다. `taste_rank<=3`인 사진이 핀의 대표사진
  (5.1 `representative_photos`, 5.4 `is_pin_cover`).
- **이유**: 포토북(6.2)에서 핀당 4장을 보여줘야 하는 요구사항이 생겼는데, 대표사진 최대 3장
  개념(is_main)과 필요 개수가 다르다. 정수 순위 필드 하나로 "핀 상세=순위 1~3",
  "포토북=순위 1~4"처럼 용도별로 잘라 쓸 수 있는 구조가 boolean보다 유연함.
- **API 응답은 안 바뀜**: 5.4 응답의 `is_pin_cover`는 명세서에 명시된 필드라 그대로 유지하되,
  내부적으로 `taste_rank<=3`을 그 자리에서 계산해서 채운다(`docs/API_CHANGES.md`에 스키마
  변경 없음으로 기록 — 이 항목은 내부 구현 변경).
- **`taste_rank`는 핀 자체 대표사진 전용**: 수동 새로고침(5.6)에서만 갱신되고, 사진이 추가돼도
  자동으로는 안 바뀐다(기존 5.5 규칙 유지). 포토북(6.2)이 쓰는 핀별 사진 선정은 이 필드가
  아니라 `photobooks.PhotobookPhotoLayout`으로 완전히 별개로 관리한다 — 새로고침(5.6)이나
  사진 추가로 인한 포토북 쪽 재계산이 핀 상세 화면의 대표사진에 영향을 주지 않게 하기 위한
  의도적 분리(사용자 확인받음).
- **`photo_delete`(5.7) 단순화**: 기존엔 대표사진이 삭제되면 랜덤으로 다른 사진을 승격시키는
  코드가 있었는데, `taste_rank` 기반에서는 필요 없어졌다 — 대표사진 목록 자체가 매번
  "`taste_rank` 순으로 상위 3장"을 다시 계산하는 값이라, 삭제로 순위에 빈 자리가 생겨도 자동
  으로 다음 순위 사진이 상위 3장에 들어온다. 관련 코드 삭제.
- **영향 범위**: `travel/models.py`(`Photo.taste_rank`), `travel/migrations/0005_photo_taste_rank.py`,
  `travel/views.py`(`_pin_detail_get`, `photo_delete`, 아래 `_pin_photos_list` 신규).
- **블로커**: 실제 순위 계산(최초 선정 5.2.1, 새로고침 5.6)은 recommendations 팀원의 취향
  스코어링 함수가 있어야 동작. 지금은 필드/쿼리 구조만 준비된 상태(이슈9 #28과 동일 블로커).

### 2026-08-15 — [travel] `_pin_photos_list`(5.4) 누락 구현 — 호출 시 NameError 나던 버그 수정
- **결정**: `pin_photos`(GET/POST dispatcher, 5.4/5.5)가 GET 요청 시 `_pin_photos_list`를
  호출하는데, 이 함수가 파일 어디에도 정의돼 있지 않았다(과거 브랜치 분리 작업 중 누락된 것으로
  추정). `captured_at` 순 정렬 + 커서 페이지네이션(`photo_id` 기준)으로 신규 작성.
- **이유**: `GET /pins/{pinId}/photos` 호출 시 500(`NameError`)이 나는 실제 버그였음. 오늘
  `taste_rank` 작업하면서 같은 함수를 손대야 해서 같이 발견·수정.
- **영향 범위**: `travel/views.py`. API 응답 스키마는 명세서 원문(`file_path`/`is_pin_cover`
  포함) 그대로 구현 — 신규 구현이라 `API_CHANGES.md`에 별도 기록 없음(원문과 계약 동일).

### 2026-08-15 — [photobooks] 도시별 핀 선정(`PhotobookPin`) + 핀별 사진 선정(`PhotobookPhotoLayout`)
- **결정**: 포토북 상세(6.2)를 도시별 카드 구조로 재설계하면서, 아래 두 모델을 신규 추가하고
  포토북 생성 시점(`_trip_create`, 3.2)에 한 번 확정해서 저장한다(이후 고정, 매 조회마다
  재계산 안 함).
  - `PhotobookPin`(photobook, pin, order): 도시별로 보여줄 핀 최대 3개. 우선순위 규칙 —
    1순위 음성메모+텍스트 둘 다 있는 핀, 2순위 둘 중 하나만 있는 핀, 3순위(음성/텍스트 둘 다
    없음)는 랜덤. 도시에 핀이 3개 이하면 우선순위 계산 없이 전부 포함. `order`는 도시 안에서만
    유효한 순번(01/02/03, 도시마다 1부터 다시 시작).
  - `PhotobookPhotoLayout`(photobook_pin, photo, order): 그 핀 카드에 보여줄 사진 최대 4장.
    1등(`order=1`)이 크게 표시되는 사진. 사진이 4장 안 되면 있는 만큼만.
- **이유**: 사용자 확인 — "방문 도시마다 최소 핀 1개는 포함"이 목표인데, 매 조회마다 랜덤/
  우선순위를 다시 계산하면 조회할 때마다 다른 핀·사진이 보이는 문제가 생겨 생성 시점에 고정.
- **`Photo.taste_rank`와 완전히 분리**: 포토북 사진 선정 로직이 이 필드를 읽거나 쓰지 않는다.
  핀 상세(5.1/5.4)의 대표사진과 포토북(6.2)의 핀별 사진은 서로 다른 선정 결과.
- **사진 추가 시 재계산 트리거**: 종료된 여정의 핀(`segment_id` 있고 `included_in_segment=True`)
  에 `POST /pins/{pinId}/photos`(5.5)로 사진이 추가되면, 그 핀의 `PhotobookPhotoLayout`만
  재계산(`photobooks.services.recompute_photo_layout_for_pin`). `PhotobookPin`(어느 핀이
  포함되는지)은 안 바뀐다 — 핀 선정은 생성 시점에만 확정.
- **블로커/TODO**: `_select_photos_for_pin`(사진 4장 선정)은 recommendations 스코어링 함수가
  아직 없어 임시로 `captured_at` 순 상위 N장을 사용하는 placeholder. 함수 준비되면
  `photobooks/services.py`의 이 함수 내부만 교체하면 되고 호출부(생성 훅, 재계산 트리거)는
  안 건드려도 됨.
- **영향 범위**: `photobooks/models.py`(`PhotobookPin`, `PhotobookPhotoLayout` 신규),
  `photobooks/migrations/0002_photobookpin_photobookphotolayout.py`,
  `photobooks/services.py`(신규 — 선정 로직), `photobooks/views.py`(`_photobook_detail_get`
  전면 재작성, `docs/API_CHANGES.md` 참고), `travel/views.py`(`_trip_create`에 생성 훅,
  `_pin_photos_register`에 재계산 트리거).
- **검증**: sqlite 대체 테스트로 (1) 우선순위 규칙(1순위/2순위 핀이 실제로 선정됨, 도시 핀
  5개 중 3개만 선정), (2) 3개 이하 도시는 전부 포함, (3) 핀당 사진 레이아웃 4장 이하,
  (4) 6.2 응답의 `pin_count`/도시 그룹핑/좌표 포함, (5) 5.4 정상 동작(`file_path`/
  `is_pin_cover`), (6) 5.1 대표사진 3장 + 삭제 후에도 정상 동작, (7) 5.5로 사진 추가 시
  `PhotobookPhotoLayout` 재계산 확인 — 전부 통과.

### 2026-08-15 — [accounts] GET /users/me(1.3) 마이페이지 통계 — 핀 개수는 NFC/수동 구분 안 함
- **결정**: 마이페이지 통계 `pin_count`("태깅 횟수")는 NFC 태깅으로 만든 핀과 수동으로(지도에서
  직접 입력) 추가한 핀을 구분하지 않고 전체 핀 개수로 집계한다.
- **이유**: `Pin` 모델에 생성 방식(NFC/수동)을 구분해서 저장하는 필드가 없다. 구분하려면
  `source_type` 같은 필드를 새로 추가하고 `POST /pins`(8.2)에서 `nfc_tag_id` 존재 여부로
  채워야 하는데, 지금 단계에서는 그 정도 구분 없이 "핀 개수 = 태깅 횟수"로 간단히 가기로
  결정(사용자 확인).
- **영향 범위**: `accounts/views.py`(`_me_get` 신규, `UserSerializer`는 안 건드림 — 1.1 로그인
  응답엔 이 통계 미포함). `completed_trip_count`(`TravelSegment` 개수), `visited_city_count`
  (사용자 핀의 distinct `city`, 진행 중 여정 포함 전체 기준)도 같이 추가.
- **미확정**: 나중에 NFC/수동을 구분해야 할 필요가 생기면(예: "진짜 태깅만" 통계를 따로
  보여달라는 요청), `Pin.source_type` 필드 추가가 필요 — 그때 이 항목 갱신.
- **검증**: sqlite 대체 테스트로 완료 여정 1개(핀 3개, 도시 2개) + 진행 중 핀 2개(도시 1개,
  city null 1개) 상황에서 `pin_count=5`, `completed_trip_count=1`, `visited_city_count=3`
  확인.

### 2026-08-15 — [travel] Pin.country_name 신규 추가 — 4.1 응답 국가 집계용
- **결정**: `Pin`에 `country_name`(문자열, nullable) 필드 신규 추가. `city`와 완전히 같은
  패턴 — `POST /pins`(8.2)에서 받은 `country_name` 원본 문자열을 검증/매핑 없이 그대로
  저장. 기존의 `CountryStamp`(사용자 단위 국가 도장, `country_code` 기준) 갱신 로직과는
  별개로 동작 — 이 필드는 오직 여행 구간 단위 국가 표시용.
- **이유**: 프론트 요청으로 `GET /trips`(4.1) 응답에 여행 구간별 도시/국가 목록을 추가해야
  했는데, `city`는 이미 `Pin.city`에 저장돼 있어 바로 집계 가능했지만 국가는 저장하는 곳이
  없었다(`country_name`은 `CountryStamp` 갱신에만 쓰이고 버려짐 — 핀-CountryStamp 간
  직접 연결도 없어 역추정 불가능). 사용자 확인 후 `Pin.country_name` 신규 필드 방식으로 결정.
- **영향 범위**: `travel/models.py`(`Pin.country_name`), `travel/views.py`(`pin_create`에서
  저장, `_countries_with_cities` 헬퍼 신규 — `_trip_list`(4.1)에서 사용).
- **미확정**: 이 필드 추가 전에 만들어진 핀은 `country_name=NULL`로 남고 소급 채우기 불가
  (핀별 국가 원본 데이터가 없음) — 그런 핀은 `city`가 있어도 4.1 응답에서 완전히 빠짐(아래
  항목 참고). 문제 되면 그때 논의.
- **검증**: sqlite 대체 테스트로 (1) 도시 2개(국가 둘 다 "일본") + `country_name` 없는 핀
  1개가 섞인 여행 구간, (2) 일본(도쿄,오사카)+대한민국(서울,부산) 4개 도시 핀에 `country_name`
  없는 핀 1개를 추가로 섞은 여행 구간, 두 경우 모두 확인. `POST /pins`로 만든 핀의
  `country_name`이 실제로 저장되는지도 확인.

### 2026-08-15 — [travel] GET /trips(4.1) countries — 평평한 배열 2개 대신 국가별 중첩 구조로 변경
- **결정**: 처음엔 `cities`/`countries`를 각각 독립적인 평평한 문자열 배열로 구현했으나,
  한 여행 구간에서 여러 국가를 다닌 경우(예: 일본+대한민국) 두 배열이 서로 매핑 정보 없이
  따로 존재해 "어느 도시가 어느 국가 소속인지" 프론트가 알 수 없는 문제가 있었다. 이를
  `countries: [{ "country_name": "...", "cities": [...] }]` — 국가 객체 안에 그 국가에서
  방문한 도시 배열이 중첩된 구조로 변경. 최상위 `cities` 필드는 삭제.
- **이유**: 사용자 확인(멀티 국가 시나리오 질문 후 중첩 구조로 확정).
- **영향 범위**: `travel/views.py`의 `_cities_and_countries` → `_countries_with_cities`로
  교체(국가 우선으로 그룹핑한 뒤 그 안에서 도시 distinct). `_trip_list`(4.1) 응답에서
  `cities` 필드 제거.
- **주의**: `country_name`이 없는 핀은 국가 그룹 자체가 안 생겨서, 그 핀의 `city`가 있어도
  응답 어디에도 안 나타난다(평평한 배열 구조였을 때는 `cities`에는 최소한 보였음 — 중첩
  구조로 바뀌면서 생긴 트레이드오프). 오래된 핀이 많이 섞인 여행 구간을 볼 때 프론트에서
  "도시는 있는데 목록엔 안 보임" 문의가 올 수 있음 — 그땐 이 항목 참고.
- **검증**: 일본(도쿄,오사카)+대한민국(서울,부산) 핀 4개 + country_name 없는 핀 1개(오키나와)
  섞인 여행 구간에서 `countries`가 `[{"country_name":"일본","cities":["도쿄","오사카"]},
  {"country_name":"대한민국","cities":["서울","부산"]}]`로 나오고 오키나와는 어디에도 안
  뜨는 것까지 확인.

### 2026-08-15 — [travel] GET /trips/{segmentId}(4.2) 응답에 voice_memo_count 추가
- **결정**: `photo_count`와 완전히 같은 패턴으로 `voice_memo_count`
  (`VoiceMemo.objects.filter(pin__in=included).count()`) 추가.
- **이유**: 프론트 요청.
- **영향 범위**: `travel/views.py`(`_trip_detail_get`). 내부 로직만 추가, 애매한 지점 없음.
- **검증**: 음성메모 2개가 달린 핀이 포함된 여행 구간에서 `voice_memo_count=2` 확인.

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

### 2026-08-15 — 무드보드 1라운드는 별도 축이 아니라 density(구도) 신호, OpenAI Vision API 도입 보류
- **결정**: 무드보드 1라운드(거리×방향 9장 중 3장)는 별도의 distance/angle 축을 만들지 않고
  기존 `density`(구도와 밀도) 축 하나에 신호로 흡수한다 — density를 "여백 대비 밀도"뿐 아니라
  "구도" 전반(피사체 거리·방향 포함)으로 넓게 해석. 방향(정면/측면/뒷모습) 판별을 위한 OpenAI
  Vision API(`analyze_direction`) 신규 도입은 **이번 스코프에 포함하지 않음** (보류).
- **이유**: 팀 문서에서 angle을 마이페이지 6번째 축으로 부활시키고 OpenAI Vision API를 새로
  붙이자는 안이 잠깐 나왔으나, 사용자 확인 결과 5축 결정(2026-08-14)이 여전히 유효하고 무드보드
  1라운드는 애초에 density 축을 검증하려는 라운드였음이 확인됨. 방향 판별은 기존 OpenCV
  얼굴 검출(정면/측면 캐스케이드)과 density 계산에 이미 쓰는 인물 크기(OpenCV) 측정만으로도
  충분히 근사 가능하다고 판단 — 외부 API 호출에 따른 지연·비용·장애 리스크 대비 이득이 크지
  않아 도입을 보류. 정확도가 부족하면 추후 재검토.
- **영향 범위**: `TasteProfileAxis.axis_code`는 계속 5개 유지. 축 계산 로직(별도 이슈)에서
  무드보드 1라운드 사진은 density 측정 함수(CLIP+OpenCV 인물크기)의 입력으로만 사용.
- **미확정**: OpenCV 방향 판별 정확도가 실제로 충분한지는 AI 분석 파이프라인 구현 이슈에서 검증 필요.

### 2026-08-15 — 기본 질문 선택지-축 값 매핑 정의 (#35)
- **결정**: `taste/axis_mapping.py`에 `BASIC_QUESTION_AXIS_MAPPING` 상수 추가. 기본 질문 5라운드
  각각의 실제 선택지 문구(팀이 확정한 문구)와 그에 대응하는 축 값(0~100, 2지선다)을 정의.
  예: brightness 라운드는 "환하고 밝은 느낌"(80) / "어둡고 무드있는 느낌"(20). density만 방향을
  반대로 둠("여백" 20, "꽉 참" 80) — 나머지는 1번 선택지가 축의 높은 값 쪽에 대응.
  매핑 데이터 무결성(5라운드 전부 존재, 축 코드 중복 없음, 선택지 2개, 값 범위 0~100, 라운드 내
  값 중복 없음)을 검증하는 테스트를 `taste/tests.py`에 추가.
- **이유**: `BasicQuestionResponse.answer`는 자유 텍스트가 아니라 팀이 확정한 2지선다 칩 문구
  중 하나가 저장되는 구조인데, 이 문구를 축 값으로 변환하는 규칙이 스펙 어디에도 없어서 별도
  결정 필요 — 팀에서 공유한 문항 문구를 그대로 채택하고 값(80/20)은 이번에 확정.
- **영향 범위**: `taste/axis_mapping.py`(신규), `taste/tests.py`. 실제 `TasteProfileAxis` 값을
  계산해 저장하는 로직(온보딩 완료 트리거)은 이번 이슈 범위 밖 — A/B·무드보드 AI 실측 파이프라인과
  함께 별도 이슈에서 이 매핑을 가져다 쓸 예정.
- **미확정**: A/B·무드보드 사진 실물 파일을 백엔드가 접근 가능한 저장소(S3/static 등)로 옮기는
  작업이 선행돼야 AI 실측 파이프라인 이슈를 시작할 수 있음.

### 2026-08-15 — TRAVEL_SEGMENT.dates_manually_set 컬럼 추가 (travel 앱, 문서 동기화)
- **결정**: travel 담당자가 ERD 원본에 `TRAVEL_SEGMENT.dates_manually_set`(BOOLEAN, 기본 false)
  컬럼을 추가함에 따라 `docs/Orte_sql_v1.sql`, `docs/spec.md`의 ERD 요약 표를 동일하게 갱신.
- **이유**: 4.3(여행 구간 편집)에서 날짜를 사용자가 직접 선택할 수 있게 되면서, 이후 핀을 껐다
  켜는 등으로 날짜가 자동 재계산될 때 사용자가 직접 정한 날짜를 덮어쓰지 않으려면 "직접 정한
  적 있는지"를 서버가 기억해야 함. travel 앱 소관 테이블이라 Django 모델 자체는 건드리지 않고
  공유 문서(ERD SQL, spec.md)만 동기화.
- **영향 범위**: taste/recommendations 로직에는 직접 영향 없음. travel 앱 담당자가 Django
  모델/마이그레이션 반영.

### 2026-08-15 — 5.6(재추천) 구현 시 참고: 종료된 여정에 추가된 사진도 포함해야 함
- **결정**: (아직 미구현, recommendations 앱 착수 시 참고용 메모) 5.5에서 종료된 여정의 핀에도
  사진을 수동으로 추가할 수 있게 되면서, 그 시점엔 대표 사진(추천 결과)이 바로 바뀌지 않지만
  5.6(새로고침/재추천) 호출 시에는 그 사이 새로 추가된 사진까지 후보 풀에 포함해서 재선정해야 함.
- **이유**: travel 담당자가 5.5 사진 추가 로직을 종료된 여정까지 확장하면서, 대표 사진 갱신
  타이밍(추가 즉시 vs 재추천 시점)을 recommendations 쪽에 명확히 알려옴.
- **영향 범위**: `recommendations` 앱의 재추천 스코어링 함수(향후 구현 예정, 이전 결정 로그의
  `score_photos_by_taste` 참고)가 후보 사진을 조회할 때 핀에 연결된 **현재 시점의 전체 사진**을
  기준으로 삼아야 함(추천 호출 시점 스냅샷이 아니라 매번 최신 조회) — 별도 캐싱/스냅샷 로직을
  두지 않는 이상 자연히 만족되는 조건이라, 구현 시 "사진 목록을 캐싱하지 말 것"만 유의하면 됨.
- **미확정**: recommendations 앱 자체가 아직 미착수라 실제 코드 반영은 나중.

### 2026-08-15 — 무드보드 1라운드 "방향" 신호는 축이 아니라 TasteProfile.taste 텍스트로 (최종)
- **결정**: 무드보드 1라운드(거리×방향 9장 중 3장)에서 **거리(distance)**는 계속 `density` 축
  신호로 흡수하고(2026-08-15 앞선 결정 유지), **방향(direction: 정면/측면/뒷모습)**은 별도 축을
  만들지 않는 대신 `TasteProfile.taste`(기존 자유 텍스트 필드)를 생성할 때 반영하는 요소 중
  하나로 포함한다. 즉 슬라이더로 노출·조작 불가능하고, 추천 스코어링에만 내부적으로 쓰인다.
  무드보드 2라운드(조합 사진 9장 중 3장)는 이 논의와 무관하게 기존 결정대로 — 선택된 3장을
  A/B와 동일한 측정 함수로 분석해 **5개 축 전부**에 신호 반영.
- **이유**: density(여백 대비 밀도)와 무드보드 1라운드의 "거리"는 이미 A/B 라운드4 측정 방식
  자체가 "CLIP + 인물크기(OpenCV)"라 상당 부분 겹침. 반면 "방향"은 density 개념과 겹치지 않는
  별개 신호인데, 이를 위해 6번째 축을 새로 만들면 마이페이지 슬라이더 개수·모델·API 응답이
  전부 늘어나는 큰 변경이 됨. `TasteProfile.taste`가 이미 "서버가 내부적으로 계산해 추천에만
  쓰는 자유 텍스트"로 설계돼 있어(API 명세서 2.3), 새 필드를 추가하지 않고 이 필드의 생성 요소
  중 하나로 편입하는 것으로 확정. 이 축 개수 논의는 오늘 하루 동안 여러 번 뒤집혔던 사안이라
  (6개→5개→1라운드 density만→방향 별도 고려→최종 이 결정) 이번이 최종안.
- **영향 범위**: `TasteProfileAxis.axis_code`는 계속 5개 유지, 모델 변경 없음. `TasteProfile.taste`
  생성 로직(2.3 PUT 내부 트리거 구현 시)이 축 값뿐 아니라 무드보드 1라운드 선택 결과(방향
  선호)도 입력으로 받아야 함 — 아직 이 생성 로직 자체가 미구현이라 실제 코드 반영은 AI 실측
  파이프라인/취향 프로파일 계산 이슈에서 진행.
- **미확정**: 방향 선호를 어떤 규칙으로 텍스트 문구화할지(예: 선택 3장 중 다수결로 "정면 클로즈업
  선호" 식 템플릿 문장 생성 등)는 아직 안 정함 — 실제 계산 로직 설계 시 확정.

### 2026-08-15 — 사진 카탈로그 저장 및 세트 매니페스트 구성 (#37)
- **결정**: A/B·무드보드 고정 사진 66장을 `taste/photo_catalog/{photo_id}.jpg`로 저장.
  `photo_id`는 `round_no`를 접두어로 사용(1~5라운드는 `{round_no}001~006`, 6라운드는
  `6001~6009`, 7라운드는 `7001~7027`). `taste/photo_catalog_manifest.py`에 라운드→세트→
  photo_id 매핑을 상수로 정의, A/B는 기획 참조값(`value`: 20/80)도 함께 기록(실측 함수 검증용,
  실제 유저 응답 아님). 매니페스트-실제 파일 1:1 대응 등을 검증하는 테스트 추가.
  원본 사진은 짧은 변 800px로 리사이즈, JPEG quality 85로 재압축(21.2MB → 6.1MB).
  `opencv-python`, `pillow` 의존성을 `pyproject.toml`에 추가.
- **이유**: `photo_id`가 라운드 내 순번이 아니라 카탈로그 전역 유일 ID로 설계돼 있어(2026-08-14
  결정), 파일 저장도 라운드/세트 하위 폴더 없이 평평한 구조로 충분. 원본 그대로 커밋하면 git
  히스토리에 27MB가 영구히 남으므로, AI 분석에 불필요한 고해상도를 리사이즈로 줄임.
  리사이즈 도중 `4001~4006.jpg`(density), `5001~5006.jpg`(phototype) 6개 파일이 확장자만
  `.jpg`이고 실제로는 **AVIF**로 인코딩된 것을 발견 — opencv가 디코딩하지 못해 확인됨.
  Pillow로 디코딩해 진짜 JPEG로 재저장하여 해결.
- **영향 범위**: `taste/photo_catalog/`(신규, 66개 파일), `taste/photo_catalog_manifest.py`(신규),
  `taste/tests.py`(`PhotoCatalogManifestTests` 추가), `pyproject.toml`/`poetry.lock`
  (`opencv-python`, `pillow` 추가).
- **미확정**: CLIP 계열(`open-clip-torch`) 의존성은 Windows 긴 경로 제한 문제로 설치 보류 중
  (`docs/TEMP_NOTES.md` 참고 예정). 실제 측정 함수(HSV/R-B/CLIP+인물크기/사람 감지)와
  `TasteProfile.taste` 텍스트 생성 로직은 별도 이슈에서 구현.

### 2026-08-15 — `open-clip-torch` 설치 완료, Python 상한 버전 고정
- **결정**: Windows "긴 경로 이름 사용" 옵션을 켠 뒤(`docs/TEMP_NOTES.md` 참고) `open-clip-torch`
  설치 재시도 → `torchvision` 최신판(0.28.0)이 Python 3.14.1 특정 패치 버전만 배제하는데
  `pyproject.toml`의 `requires-python = ">=3.12"`가 위쪽을 안 막아놔서 충돌 발생. 실제로 팀 전체가
  pyenv로 3.12.1에 고정해서 쓰므로 `requires-python`을 `">=3.12,<3.13"`으로 좁혀서 해결.
  `torch 2.13.0+cpu`, `open_clip 3.3.0`, `cv2 5.0.0` 전부 정상 import 확인.
- **이유**: 실제 사용 범위를 정직하게 반영하는 제약이라 임시방편이 아님 — 3.13/3.14대 지원은
  현재 아무도 안 씀.
- **영향 범위**: `pyproject.toml`(`requires-python`), `poetry.lock`.

### 2026-08-15 — taste 온보딩 사진 실측은 정적 사전계산, recommendations는 런타임 CLIP 필요 (배포 메모)
- **결정**: taste 온보딩 카탈로그(고정 66장)의 축 실측값은 **CLIP을 배포 서버에서 매번 돌리지
  않고, 로컬/CI에서 한 번 미리 계산해 정적 데이터로 저장**한다 — 배포 환경엔 CLIP/torch 자체가
  필요 없어짐. 다만 이건 taste 온보딩에만 해당하고, **`recommendations`(5.2.1, 유저가 매번
  새로 올리는 여행 사진 스코어링)는 사진이 고정돼 있지 않아 런타임에 CLIP을 실제로 돌려야 함** —
  이 경우엔 배포 환경에 CLIP 가중치 캐싱(Docker 이미지에 미리 포함 또는 영구 볼륨)이 실제로 필요.
  비전 LLM API(GPT-4V 등) 대안도 검토했으나, 유저 사진마다 매번 호출되는 고빈도 작업이라 사용량
  비례 비용·프라이버시(외부로 사진 전송)·외부 API 지연 부담이 있어 자체 호스팅 CLIP을 권장.
- **이유**: taste와 recommendations는 "사진이 고정 자산인가 매번 새로 올라오는가"가 근본적으로
  달라서 같은 CLIP 배포 전략을 못 씀 — 이 구분을 착각하면 recommendations 설계 시 "이미 해결된
  문제"로 잘못 넘어갈 수 있어 명시적으로 기록.
- **영향 범위**: taste 이번 이슈(측정 함수)는 배포 부담 없음. `recommendations` 앱 착수 시
  CLIP 가중치 캐싱 인프라를 반드시 별도로 준비해야 함(비용 문제는 현재 우선순위 아님, 확인됨).
- **미확정**: recommendations의 정확한 배포 방식(Docker 이미지에 가중치 포함 vs 영구 볼륨)은
  실제 배포 인프라 담당자와 착수 시점에 논의 필요.

### 2026-08-15 — 사진 실측 함수 구현 및 사전계산 완료 (#39)
- **결정**: `taste/photo_measurement.py`에 5개 축 측정 함수 구현.
  - brightness/vividness/tone: HSV V·S채널 평균, R−B 채널차 (순수 픽셀 계산, AI 아님)
  - density: CLIP 제로샷(영어 프롬프트) + Canny 엣지 밀도 50:50 가중 평균
  - photo_type: 얼굴 DNN(SSD+ResNet, `res10_300x300_ssd_iter_140000.caffemodel`) + 전신/상반신
    Haar cascade 조합 — 셋 중 하나라도 사람을 감지하면 인물 쪽 점수
  - `taste/dnn_models/`에 얼굴 검출 모델 파일 2개(약 10MB) 추가(OpenCV 공식 GitHub에서 받음)
  - `taste/management/commands/precompute_photo_measurements.py` 신규: 카탈로그 66장 전체를
    측정해 `taste/photo_measurements.py`(정적 데이터)로 저장하는 1회성 개발자 커맨드. 실행 완료.
  - 테스트는 `photo_measurements.py`(정적 데이터)만 검증 — CLIP/torch를 테스트 시점에 다시
    돌리지 않아 빠름(15개 테스트 0.014초). A/B 라운드는 참조값(20/80) 대비 방향성만 검증.
- **이유**: 초기 구현(HOG 사람 감지, 한국어 CLIP 프롬프트, CLIP 단독 density)을 66장 카탈로그로
  실측 검증한 결과 photo_type이 전부 미검출(10.0 고정), density 신호가 거의 없었음(60.8 vs 62.0).
  마침 팀원이 2026-08-11에 실제 여행 사진 40장으로 CLIP 단독 vs 하이브리드(규칙기반+DNN 얼굴
  검출+Haar 전신/상반신+CLIP 구도) 방식을 미리 비교 검증해둔 문서가 있어 그 결론을 그대로 채택.
  Haar cascade 얼굴 검출 단독은 반복 패턴(키패드 등)을 얼굴로 오탐하는 사례가 실측으로 확인되어
  DNN으로 교체된 이력이 있음. 이 교체 후 재검증하니 density가 20.8 vs 67.8로, photo_type이
  15.0 vs 47.6으로 개선되어 5개 축 전부 방향성 테스트를 통과함.
- **영향 범위**: `taste/photo_measurement.py`(신규), `taste/dnn_models/`(신규, 모델 파일 2개),
  `taste/management/commands/precompute_photo_measurements.py`(신규), `taste/photo_measurements.py`
  (신규, 사전계산 결과), `taste/tests.py`(`PhotoMeasurementsTests` 추가), `pyproject.toml`
  (`opencv-python`을 5.0→4.x로 다운그레이드 — 5.0에 `HOGDescriptor`/`CascadeClassifier`가 아예
  없는 것을 발견).
- **미확정**: photo_type 측정이 인물 3장 중 1장을 놓치는 경계 사례가 여전히 있음(팀원의 40장
  테스트에서도 유사한 경계 사례 1건 보고됨) — A/B 큐레이션이 충분히 극단적이라 축 계산 정확도에
  큰 영향은 없을 것으로 판단, 추후 실사용 데이터로 재검토. `recommendations` 앱에서 유저 사진에
  같은 방식(얼굴 DNN+Haar)을 적용할 때도 이 한계를 참고할 것.

### 2026-08-15 — A/B 라운드는 실측값 대신 매니페스트 참조값을 축 계산에 사용
- **결정**: 온보딩 완료 시 실제 `TasteProfileAxis` 값을 계산할 때, **A/B 라운드(1~5)는
  `taste/photo_measurements.py`의 실측값이 아니라 `taste/photo_catalog_manifest.py`에 이미
  있는 큐레이션 참조값(20/80)을 그대로 사용**한다. 무드보드(6~7라운드)는 애초에 참조값이 없으므로
  기존 계획대로 실측값을 사용한다.
- **이유**: A/B 사진은 "이 사진은 80쪽이다"라고 기획 단계에서 이미 의도를 확정하고 만든 것이라,
  굳이 실측값(노이즈 있음 — 같은 80쪽 안에서도 개별 값이 38.6~99.3까지 벌어짐)을 다시 쓰는 것보다
  큐레이션값을 직접 쓰는 게 더 안정적이고 예측 가능함. 실측 함수는 이 큐레이션이 의도대로 됐는지
  검증하는 QA 용도로 유지.
- **영향 범위**: `taste/photo_catalog_manifest.py` 상단 주석 갱신(참조값의 역할 변경 명시).
  온보딩 완료 시 축 계산 트리거(다음 이슈, 아직 미착수)를 설계할 때 이 구분(A/B=매니페스트값,
  무드보드=실측값)을 그대로 반영해야 함.

### 2026-08-15 — recommendations는 별도 엔드포인트 없이 travel의 Pin/Photo API 내부 로직
- **결정**: API 명세서를 다시 확인한 결과, 추천 관련 내용(최초 추천·재추천·대표사진 관리)은
  별도의 "recommendations" 섹션이 없고 전부 **5번 섹션(여행 기록 탐색, `/pins/...`,
  `/photos/...`) 안에 있음** — 5.4(사진 목록의 `is_pin_cover`), 5.5(사진 등록 시 내부적으로
  최초 추천 계산), 5.6(`POST /pins/{pinId}/representative-photos/refresh`, 재추천),
  5.7(사진 삭제 시 대표사진 자동 대체). 이 리소스들은 전부 `Pin`/`Photo` 소관이라 **travel
  앱의 엔드포인트**이며, `recommendations` 앱은 REST 엔드포인트를 직접 갖지 않고 travel의
  뷰가 내부적으로 호출하는 **스코어링 함수(모듈)만 제공**하는 구조로 확정.
  기능명세서 5.2.2(추천 사진 개별 추가/제외)는 API 명세서에 대응 엔드포인트가 없는데, 사용자
  확인 결과 **의도적으로 뺀 게 맞음** — "개별 사진 단위 수정은 제공하지 않는다"(5.6 설명)와
  일치. `RecommendationEdit` 모델도 이에 따라 불필요 확정.
- **이유**: `recommendations` 앱 스코프를 정확히 잡아야 실제 구현 범위(엔드포인트 vs 함수)를
  오판하지 않음 — REST API로 착각하고 뷰/URL을 만들면 travel 앱 영역을 침범하게 됨.
- **영향 범위**: `recommendations` 앱은 모델도 URL도 없이 스코어링 함수(예:
  `recommendations/scoring.py`의 `score_photos_by_taste` 등, 2026-08-13 결정 로그 참고)만
  구현하면 됨. **실제 엔드포인트(5.5/5.6/5.7)는 travel 담당자가 만들고, 그 안에서 이 스코어링
  함수를 import해서 호출하는 구조** — travel 담당자와 함수 시그니처를 미리 맞춰야 함(연동 지점).
- **미확정**: 스코어링 함수의 정확한 시그니처(입력: user, pin의 사진 목록 / 출력: 정렬된 사진
  리스트 등)는 recommendations 착수 시 확정, travel 담당자와 공유 필요.

### 2026-08-15 — 온보딩 완료 시 취향 축 계산 및 taste 텍스트 생성 구현 (#55)
- **결정**: `taste/onboarding_completion.py`에 `compute_and_save_taste_profile(user)` 구현.
  `taste/views.py`의 `_advance_progress()`에서 무드보드 2라운드 완료로 `COMPLETED` 전환되는
  시점에 호출. 축별 가중 평균: brightness/vividness/tone/photo_type은 기본질문 0.4 + A/B 0.4 +
  무드보드2라운드 실측 0.2, density는 기본질문 0.3 + A/B 0.3 + 무드보드1라운드 실측 0.2 +
  무드보드2라운드 실측 0.2. `TasteProfile.taste`는 축 값을 구간별(≥60/≤40) 형용사로 변환해
  조합 + 무드보드1라운드 선택 3장의 거리·방향 라벨 다수결로 구도 선호 문구를 추가해 생성.
  전체 온보딩 시뮬레이션(기본질문 전부 고값 응답 + A/B 전부 80쪽 선택 + 무드보드1 "가까이" 3장
  선택)으로 검증 — 5개 축 전부 70대로 계산되고 taste 텍스트에 "가까이·정면 구도를 선호합니다"가
  정확히 반영됨을 확인.
  `TasteProfileAxis.value`에 `MinValueValidator(0)`, `MaxValueValidator(100)` 추가(마이그레이션
  포함) — 명세서에 범위가 명시돼 있진 않으나 기존 0~100 관례를 모델 레벨에서도 강제.
  `taste/photo_catalog_manifest.py`의 무드보드1라운드(round_no 6) 9장에 거리(가까이/중경/멀리)·
  방향(정면/측면/뒷모습) 라벨 추가(사용자 확인, 업로드 순서가 3x3 그리드 그대로).
- **이유**: API 명세서 2.3이 "클라이언트가 직접 호출하지 않는 내부 트리거"로 명시돼 있어 별도
  공개 엔드포인트 없이 온보딩 완료 로직 안에 구현. 가중치는 기본질문·A/B를 "본 신호", 무드보드를
  "보정 신호"로 두기로 한 기존 방침(2026-08-14)을 수치화한 것 — 스펙에 정확한 숫자가 없어 이번에
  임의로 확정.
- **영향 범위**: `taste/onboarding_completion.py`(신규), `taste/views.py`(`_advance_progress`),
  `taste/models.py`(`TasteProfileAxis.value` 검증 추가, 마이그레이션 `0002`),
  `taste/photo_catalog_manifest.py`(무드보드1 라벨 추가).
- **미확정**: 가중치 수치(0.4/0.4/0.2 등)는 임의로 정한 초기값이라, 실사용 데이터가 쌓이면
  재조정 가능성 있음.

### 2026-08-15 — PHOTO.is_pin_cover: BOOLEAN → INT(순위) 변경 (travel 확정, 문서 동기화)
- **결정**: travel 담당자가 `PHOTO.is_pin_cover`를 BOOLEAN(대표사진 여부)에서 **INT(대표사진
  순위, 1/2/3, 대표사진 아니면 NULL)**로 확정 변경. `docs/Orte_sql_v1.sql`, `docs/spec.md` ERD
  요약 동기화.
- **이유**: 사용자가 사진을 업로드할 때 단순히 대표사진 여부만 표시하는 게 아니라, 스코어링
  결과로 **순위를 매겨서** 추천하는 것으로 확정됨.
- **영향 범위**: taste/recommendations 직접 모델 변경 없음(travel 소관). 다만 **recommendations
  스코어링 함수의 출력 형태가 바뀜** — 기존엔 "대표사진 3장 리스트"만 반환하면 됐지만, 이제
  각 사진에 순위(1/2/3)를 매겨서 반환해야 함. 2026-08-15 앞선 결정(recommendations는 스코어링
  함수만 제공)의 함수 시그니처 설계 시 이 순위 출력을 반영해야 함.
- **미확정**: 순위 매기는 함수의 정확한 반환 타입(예: `[(photo_id, rank), ...]` vs 정렬된
  리스트를 travel 쪽에서 enumerate)은 recommendations 착수 시 travel 담당자와 확정.

### 2026-08-15 — 취향 축 값 수정 API 구현 (#57)
- **결정**: `PUT /users/me/taste-profile/axes/{axisCode}` (API 명세서 2.5) 구현.
  `TasteProfileAxis.value`만 수정 가능(`status`는 클라이언트가 못 보냄, 응답 시 항상
  `REFLECTED`). 저장 즉시 `taste/onboarding_completion.py`의 `regenerate_taste_text(user)`를
  호출해 `TasteProfile.taste`를 현재 축 값 기준으로 재생성(2.3 내부 트리거). 이 함수는
  `compute_and_save_taste_profile`(#55)에서 쓰던 텍스트 생성 로직을 분리해 재사용.
  온보딩을 완료하지 않아 해당 축이 없는 유저가 호출하면 `404 NOT_FOUND`.
- **이유**: 명세서 2.5 설명 "이 호출은 내부적으로 2.3을 트리거한다"를 그대로 구현. 축 자체가
  없는 유저 처리 기준은 명세서에 없어 이번에 404로 확정(가장 단순한 기본값).
- **영향 범위**: `taste/serializers.py`(`TasteProfileAxisUpdateSerializer` 추가),
  `taste/views.py`(`update_taste_profile_axis`), `taste/urls.py`,
  `taste/onboarding_completion.py`(`regenerate_taste_text` 분리).
- **참고(고치지 않기로 함)**: 테스트 중 값 범위 초과 시 에러 응답이 프로젝트 관례
  (`{success:false, error:{code,message}}`)가 아니라 DRF 기본 형식으로 나가는 걸 발견 —
  기존 #28/#30 엔드포인트에도 동일하게 있던 문제. API 명세서엔 이 형식이 "모든 에러의 규칙"으로
  명시된 게 아니라 5.5의 CONFLICT 예시 하나뿐이라, 강제 규약은 아님을 확인 — 지금은 그대로 두고
  넘어감(고치려면 `config/settings.py`에 공유 예외 핸들러 추가가 필요해 다른 담당자와 협의 필요).

### 2026-08-15 — 취향 프로파일 재학습(7.3) 구현 (#59)
- **결정**: 별도의 "재학습 시작" 엔드포인트를 만들지 않고, `POST /users/me/basic-question-responses`
  (2.1)가 `OnboardingProgress.current_stage == COMPLETED` 상태에서 `round_no == 1`로 호출되면
  재학습 시작으로 간주하도록 확장(`_start_retrain`). 이때 `OnboardingProgress`를
  `BASIC_QUESTION`/1라운드로 리셋하고 `is_retrain=True`로 표시, 이전 `BasicQuestionResponse`/
  `SelectionPhoto`를 전부 삭제한 뒤 `ProfileRetrainHistory`(`started_at=now`,
  `completed_at=None`) row를 생성한다. 온보딩 재완료(`_advance_progress`가 `COMPLETED`로
  전환) 시 `is_retrain=True`였으면 해당 `ProfileRetrainHistory.completed_at`을 채우고
  `is_retrain`을 `False`로 리셋 — 이후 흐름은 최초 온보딩과 동일하게
  `compute_and_save_taste_profile()`이 처리.
  `ProfileRetrainHistory.completed_at`을 `auto_now_add=True`(row 생성 시 자동 기록)에서
  `null=True`로 변경 — 시작 시각과 완료 시각이 서로 다른 시점에 기록돼야 하는데 기존 필드로는
  불가능했음(마이그레이션 `0003`).
- **이유**: 기능명세서 7.3 "재학습 진행 중에는 기존 프로파일을 유지"는 `compute_and_save_taste_profile`이
  완료 시점에만 호출되므로 기존 구조로 자연히 충족됨. 이전 `SelectionPhoto`를 지우지 않고
  재학습을 시작하면, 라운드 완료 판정(해당 round_no의 행 개수 세기)이 재학습 첫 제출만으로
  "라운드가 이미 다 찼다"고 오판하는 버그가 실제로 재현되어(테스트로 발견) 이전 행을 삭제하는
  것으로 수정.
- **영향 범위**: `taste/models.py`(`ProfileRetrainHistory.completed_at`),
  `taste/migrations/0003_alter_profileretrainhistory_completed_at.py`(신규),
  `taste/views.py`(`_start_retrain`, `_advance_progress`), `taste/tests.py`(`RetrainFlowTests`).
- **미확정**: 5.2.2(추천 사진 수정 누적 보정 신호) 초기화는 기능명세서에 "재학습 완료 시 누적된
  수정 신호 초기화"로 명시돼 있으나, 이 신호 자체가 아직 recommendations 쪽에 구현이 없어
  이번 범위에서는 처리할 대상이 없음 — recommendations 착수 시 함께 고려.

### 2026-08-15 — GET 2.4 응답에 last_updated_at 추가
- **결정**: `GET /users/me/taste-profile/axes`(2.4) 응답에 최상위 필드 `last_updated_at`
  추가(`TasteProfile.last_updated_at`, 온보딩 미완료로 `TasteProfile`이 없으면 `null`).
  `docs/Orte_API_명세서.md` 2.4 예시도 동일하게 갱신.
- **이유**: FE가 마이페이지에 "취향 프로파일 마지막 갱신 시각"을 표시해야 하는데, 이 값
  자체(`TasteProfile.last_updated_at`, `auto_now=True`)는 재학습 완료·2.5 슬라이더 수정·
  최초 온보딩 완료 시 이미 정확히 갱신되고 있었으나 어떤 응답에도 노출되지 않고 있었음.
  로직 변경 없이 응답 필드만 추가하면 되는 단순 보강.
- **영향 범위**: `taste/views.py`(`list_taste_profile_axes`), `taste/tests.py`
  (`ListTasteProfileAxesViewTests` 추가), `docs/Orte_API_명세서.md` 2.4.

### 2026-08-15 — recommendations 앱 스캐폴딩 및 스코어링 함수 설계 초안
- **결정**: travel의 `Pin`/`Photo` 모델이 아직 develop에 머지되지 않아 착수는 못 하지만, 미리
  준비 가능한 부분을 진행. `python manage.py startapp recommendations`로 앱 생성,
  `config/settings.py`의 `PROJECT_APPS`에 등록(모델 없음, 마이그레이션도 안 생김). 5.2.1/5.2.3
  기준으로 `recommendations/scoring.py`에 스코어링 함수 설계·구현:
  - `reduce_similar_photos`: 촬영 시각 근접(120초 이내) + CLIP 임베딩 코사인 유사도(0.9 이상)로
    유사 사진 축소
  - `score_photo`: `taste.photo_measurement.measure_all_axes()` 재사용, 유저
    `TasteProfileAxis`와 축별 절댓값 차이 평균을 100에서 뺀 값을 점수로 사용
  - `select_initial_recommendations`(5.2.1): 축소 → 스코어링 → 상위 3장
  - `select_refreshed_recommendations`(5.2.3): 축소 없이 전체 스코어링 → 상위 10장 후보 →
    3장 무작위 선정(정확히 3장이면 무작위 없이 그대로)
  - travel 모델 없이도 검증 가능하도록, 사진을 `(photo_id, image, captured_at)` 튜플로 받는
    duck-typed 인터페이스로 설계 — travel 연동 시 호출부에서 이 형태로 변환해서 넘기면 됨.
  - `taste/photo_measurement.py`에 `get_image_embedding()` 공개 함수 추가(기존 private
    CLIP 로딩 재사용) — recommendations가 유사도 판별에 재사용.
  - 테스트는 taste의 `photo_catalog` 샘플 사진을 알고리즘 검증용으로만 재사용(사진 내용 자체는
    무의미, 로직 동작만 확인). 11개 전체 통과.
  - `docs/spec.md` 5.2.3 요약의 "추천 버전을 1 증가시켜 저장" 문구가 API 명세서의 `is_main`
    플래그 단순화 결정과 어긋나는 것을 발견해 취소선 처리 및 정정.
- **이유**: travel 브랜치가 리뷰/수정 중이라 당장 못 붙이지만, 알고리즘 설계와 스코어링 로직
  자체는 travel 모델과 무관하게 미리 만들어둘 수 있어 시간 활용.
- **영향 범위**: `recommendations/`(신규 앱), `config/settings.py`(`PROJECT_APPS`),
  `taste/photo_measurement.py`(`get_image_embedding` 추가), `docs/spec.md`(5.2.3 정정).
- **미확정**: `TIME_PROXIMITY_SECONDS`/`SIMILARITY_THRESHOLD` 구체적 수치는 임의 초기값이라
  실제 여행 사진으로 재검증 필요. 출력 형식(순위 포함 여부)은 travel 담당자와 연동 시 협의.
  travel의 `Pin`/`Photo` 모델이 실제로 머지되면 이 스코어링 함수를 travel 뷰(5.5/5.6/5.7)에
  연결하는 작업이 남음.

### 2026-08-15 — taste 앱 실제 인증(JWT) 전환 (#69)
- **결정**: accounts 앱의 구글 로그인 + JWT 인증이 develop에 머지됨에 따라, taste 6개 모델의
  user FK를 `settings.AUTH_USER_MODEL`에서 `accounts.models.User`로 직접 교체(마이그레이션
  `0004`). `taste/auth_temp.py`를 삭제하고, taste 5개 뷰(2.1/2.2/2.4/2.5)에
  `@authentication_classes([JWTAccessAuthentication])` + `@permission_classes([IsAuthenticated])`
  적용, `request.user`로 사용자를 얻도록 전환 — travel 앱과 동일한 패턴. **API 계약 변경**:
  기존에 요청 바디/쿼리로 받던 `user_id`가 사라지고, 이제 `Authorization: Bearer {JWT}` 헤더로만
  인증한다(FE 공유 필요).
- **이유**: `accounts.User`가 `AbstractBaseUser`를 상속하지 않은 순수 `models.Model`이라
  `AUTH_USER_MODEL`로 지정 불가능해서 FK를 직접 바꿔야 했음(2026-08-14 결정 로그에서 이미 확인된
  사항). 로컬 dev DB에 실 데이터가 없어 기존 테스트용 더미 행만 정리하고 마이그레이션 적용.
- **영향 범위**: `taste/models.py`(6개 모델 FK), `taste/migrations/0004_...`(신규),
  `taste/views.py`(5개 뷰 전부), `taste/auth_temp.py`(삭제), `taste/tests.py`(JWT 기반으로 갱신,
  `_make_user`/`_auth_headers` 헬퍼 추가). `docs/TEMP_NOTES.md` 해당 항목 완료 처리.
- **미확정**: 없음 — TEMP_NOTES.md에 있던 3단계 계획을 전부 완료.

### 2026-08-15 — recommendations ↔ travel 실제 연동 (#71)
- **결정**: travel의 `Pin`/`Photo`가 develop에 머지되어(`Photo.taste_rank`: IntegerField,
  nullable) `recommendations/travel_adapter.py`를 신규 작성해 `scoring.py`와 실제 모델을
  연결했다.
  - `rank_pin_photos(pin)`(5.2.1): 핀 생성 시점 사진 전체를 `rank_all_photos()`로 순위 매겨
    `Photo.taste_rank`에 저장.
  - `refresh_pin_photos(pin)`(5.6): 호출 시점의 사진 전체(5.5로 나중에 추가된 것 포함)를
    다시 스코어링해 `taste_rank` 갱신.
  - 둘 다 사진 다운로드(`requests.get` + `cv2.imdecode`) → `TasteProfileAxis` 조회 →
    스코어링 → `Photo.objects.bulk_update(["taste_rank"])` 순으로 처리하는 공통 헬퍼
    `_score_and_save`를 공유. 온보딩 미완료(취향 축 없음)/사진 0장인 핀은 그냥 아무 것도
    안 함(에러 아님).
  - **5.6에도 유사 사진 축소를 적용하기로 함(스펙 원문엔 5.2.1에만 명시)**: 처음엔 5.2.3
    원문에 없다는 이유로 축소 없이 상위 10장/무작위 3장만 구현했으나, 사용자 판단으로
    "비슷한 사진 3장이 무작위 추천에 한꺼번에 뽑히는 것"을 막기 위해 5.2.1과 같은 로직을
    통합하기로 결정. `scoring.py`에 `_rank_for_refresh` 공통 헬퍼를 추가해
    `select_refreshed_recommendations`(3개 photo_id 반환)와 `rank_all_photos_for_refresh`
    (전체 순위 반환) 둘 다 이 헬퍼를 재사용하도록 리팩터링.
- **이유**: `taste_rank`가 정수 하나로 순위를 저장하는 구조라, "무작위로 뽑힌 3장"과 "그 외
  전체 사진"이 서로 겹치지 않는 순위를 받아야 함. 유사 사진 그룹은 대표 1장만 상위 순위
  경쟁(최초 추천이든 재추천 후보 풀이든)에 참여시키고 나머지는 개별 점수로 뒤에 이어붙이는
  방식으로, 두 흐름(5.2.1/5.2.3) 모두 "유사 사진 여러 장이 나란히 최상위를 차지하는" 문제를
  막는다.
- **영향 범위**: `recommendations/scoring.py`(`_rank_for_refresh`, `rank_all_photos_for_refresh`
  추가, `select_refreshed_recommendations` 리팩터링), `recommendations/travel_adapter.py`(신규),
  `recommendations/tests.py`(스코어링 함수 테스트 보강 + `travel_adapter.py`용 `TestCase` 통합
  테스트 추가, 총 50개).
- **미확정**: 후보 클러스터 수가 상위 N(3)보다 적을 때(예: 핀에 서로 다른 사진이 2장뿐이고
  나머지가 전부 그 유사 사진)는 상위권에 같은 클러스터의 중복 사진이 어쩔 수 없이 섞인다 —
  핀의 모든 사진에 순위를 매겨야 하는 요건상 불가피한 것으로 보고 별도 처리는 하지 않음.
  travel 담당자가 5.5/5.6 뷰에서 `rank_pin_photos`/`refresh_pin_photos`를 실제로 호출하는
  작업은 이번 범위에 포함되지 않음(travel 쪽에서 진행).

---

## 템플릿 (새 결정 추가 시 아래 형식 복사해서 사용)

```
### YYYY-MM-DD — 결정 제목
- **결정**: 무엇을 정했는지 한두 문장
- **이유**: 왜 이렇게 정했는지
- **영향 범위**: 어떤 모델/함수/앱이 영향받는지
- **미확정**: (있다면) 아직 안 정해진 부분
```