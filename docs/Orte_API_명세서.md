# Orte API 명세서 (최종)

기준 문서: `dreamteam-erd_final.sql`(ERD 최종본), 기능명세서(6.3 도시별 포토북 취소선 반영본)

이 문서는 v1 → 상세 v2 → 상세 v3까지의 개정과, 이후 팀 논의로 확정된 사항을 모두 반영한 최종본이다. v3 대비 달라진 부분은 문서 맨 아래 **부록 A**에 정리했다.

세션 토큰이 필요한 모든 API의 Header는 다음과 같다.
```json
{
    "Authorization": "Bearer {session_token}"
}
```
`session_token`은 **JWT**이며 payload에 `user_id`, `exp`를 포함한다.

---

## 0-1. 여행/여정 생명주기 (핵심 구조)

- 여행 중에는 `TRAVEL_SEGMENT`가 존재하지 않는다. 태깅으로 생성되는 `PIN`은 `segment_id = NULL` 상태로 계속 쌓인다.
- 계정당 진행 중인 여행은 1개뿐이므로, `segment_id`가 `NULL`인 핀 전체 = "현재 진행 중인 여행"이다.
- 사용자가 **여행 종료**를 선택하는 순간에만 `TRAVEL_SEGMENT`가 생성되고, 그 시점까지 쌓여 있던 `NULL` 핀들이 세그먼트로 배정된다. "여정을 생성"하는 행위 자체가 "여행을 종료"하는 행위다.
- 여행이 끝난 뒤에는 핀·사진을 더 추가할 수 없고, 구간 상세 편집에서 핀을 빼거나(제외) 다시 넣는(재포함) 것만 가능하다. 핀을 실제로 삭제하거나 `segment_id`를 비우는 게 아니라 `PIN.included_in_segment`(기본값 `true`) 플래그를 토글한다.
  - `segment_id = NULL` → 아직 여행 진행 중이라 미배정
  - `segment_id = 값`, `included_in_segment = true` → 그 여행에 포함된 핀
  - `segment_id = 값`, `included_in_segment = false` → 한 번 배정됐다가 제외된 핀 (재포함 가능, 태깅 이력은 남음)
- 여행을 삭제하면 그 여행에 속한 핀·사진·음성메모까지 전부 삭제되고, 포토북도 함께 삭제된다(DB `ON DELETE CASCADE`로 강제됨).
- **태깅 세션 개념은 사용하지 않는다.** 한 번의 태깅 = 핀 1개. 같은 자리에서 연속 촬영한 사진은 전부 같은 핀에 붙고, 새로 태깅하면 위치·시간과 무관하게 무조건 새 핀이 생긴다. 이 규칙만으로 "이 사진이 어느 촬영 묶음인지"가 `PHOTO.pin_id`로 이미 결정되므로 별도 세션 테이블이 필요 없다.

---

## 0-2. 공통 사항

**Base URL**: `https://api.orte.app/v1`

**인증**: 구글 로그인 후 발급되는 JWT 세션 토큰을 `Authorization: Bearer {session_token}` 헤더로 전달. 로그인 화면을 제외한 모든 엔드포인트는 인증 필수.

**공통 에러 코드**: `UNAUTHENTICATED`, `PERMISSION_DENIED`(본인 데이터 아님), `NOT_FOUND`, `VALIDATION_ERROR`, `CONFLICT`(동시 수정, 종료된 여행 접근 등), `RATE_LIMITED`, `INTERNAL_ERROR`

**날짜/시각**: ISO 8601 UTC (`2026-08-13T09:00:00.000000Z`)

**목록 조회 페이지네이션**: 커서 기반. 요청 `?cursor=&limit=`, 응답에 `next_cursor`(없으면 `null`) 포함.

**파일 업로드**: 사진·음성은 S3 사전 서명 URL 발급 후 업로드하는 2단계 방식.
```
POST /uploads
Request: { "file_type": "photo" | "voice", "content_type": "image/jpeg" }
Response: { "upload_url": "...", "file_id": "...", "expires_at": "..." }
```

**비동기 작업 상태 확인**: 추천 재계산, 포토북 생성처럼 `_job`/`photobook_id` 형태로 큐잉되는 작업은 별도의 잡 상태 조회 엔드포인트를 두지 않는다. 클라이언트는 대상 리소스(`GET /pins/{pinId}`, `GET /photobooks/{photobookId}`)를 짧은 간격으로 재조회(폴링)해 값이 채워졌는지 확인한다.

---

## 1. 계정·인증 및 권한

## 1.1 구글 로그인

Method `POST` · EndPoint `/auth/google` · 인증 불필요

Body
```json
{ "google_id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." }
```
Response
```json
{
    "session_token": "sess_9f2c1a...",
    "user": {
        "user_id": 1,
        "email": "khs121056@gmail.com",
        "created_at": "2026-08-01T00:00:00.000000Z",
        "onboarding_completed": false,
        "permission_intro_shown": false,
        "account_identifier": "google-oauth-sub-id"
    }
}
```
- `onboarding_completed=false`이면 클라이언트는 온보딩(2번)으로 라우팅한다.

## 1.2 로그아웃

Method `POST` · EndPoint `/auth/logout` · 인증 필요 · Response `204 No Content`

네트워크 실패와 무관하게 클라이언트는 로컬 세션을 즉시 폐기한다.

## 1.3 내 계정 정보 조회

Method `GET` · EndPoint `/users/me` · 인증 필요

Response
```json
{
    "user_id": 1,
    "email": "khs121056@gmail.com",
    "created_at": "2026-08-01T00:00:00.000000Z",
    "onboarding_completed": true,
    "permission_intro_shown": true,
    "account_identifier": "google-oauth-sub-id"
}
```

## 1.4 계정 정보 수정

Method `PATCH` · EndPoint `/users/me` · 인증 필요

Body
```json
{ "onboarding_completed": true, "permission_intro_shown": true }
```
Response
```json
{ "user_id": 1, "onboarding_completed": true, "permission_intro_shown": true }
```

## 1.5 권한 이벤트 기록

Method `POST` · EndPoint `/events/permissions` · 인증 필요

Body
```json
{ "permission_type": "camera|location|microphone|nfc", "status": "granted|denied|unsupported", "os": "android|ios" }
```
NFC는 OS 권한 체계 대상이 아니므로 이 엔드포인트로는 안내 노출 여부만 기록하고 서버가 실제 권한을 판단하지 않는다.

---

## 2. 취향 프로파일 온보딩

> 응답 목록 조회, taste 텍스트 단독 GET 조회는 제공하지 않는다. taste 텍스트는 클라이언트가 직접 읽지 않고, 서버가 응답·축 값으로부터 계산해 추천에만 내부적으로 사용한다.

## 2.1 기본 질문 응답 저장

Method `POST` · EndPoint `/users/me/basic-question-responses` · 인증 필요

Body
```json
{ "round_no": 3, "response": "인물 중심" }
```
Response
```json
{
    "response_id": 501, "user_id": 1, "round_no": 3,
    "response": "인물 중심", "answered_at": "2026-08-13T09:00:00.000000Z"
}
```

## 2.2 A/B·무드보드 사진 선택 기록

Method `POST` · EndPoint `/users/me/selection-photos` · 인증 필요

라운드 번호는 A/B(1~5)와 무드보드(6~7)를 통합한 시퀀스를 그대로 사용한다(축·A/B·무드보드 구분은 `round_no` 기준으로 서버 내부 상수 매핑을 사용하며 별도 컬럼을 두지 않는다).

Body
```json
{ "photo_id": 2011, "round_no": 2, "status": true }
```
Response
```json
{
    "photo_id": 2011, "user_id": 1, "round_no": 2,
    "status": true, "selected_at": "2026-08-13T09:05:00.000000Z"
}
```

## 2.3 취향 프로파일 갱신 (내부 트리거 전용)

클라이언트가 자유 텍스트를 입력해서 호출하는 API가 아니라, 아래 두 흐름이 끝나는 시점에만 서버 내부적으로 호출된다: 1) 취향 재학습(기본 질문 재응답) 완료 시, 2) 마이페이지에서 슬라이더로 축 값을 직접 조정할 때(2.5).

Method `PUT` · EndPoint `/users/me/taste-profile` · 인증 필요

Body
```json
{ "taste": "따뜻한 색감과 클로즈업 인물 사진을 선호" }
```
Response
```json
{ "user_id": 1, "taste": "따뜻한 색감과 클로즈업 인물 사진을 선호", "last_updated_at": "2026-08-13T09:10:00.000000Z" }
```
- 이전 taste는 보존하지 않고 완전히 덮어쓴다. 조회(GET)는 제공하지 않는다.

## 2.4 취향 축 목록 조회

Method `GET` · EndPoint `/users/me/taste-profile/axes` · 인증 필요

Response
```json
{
    "axes": [
        { "axis_code": "brightness", "value": 62, "status": "REFLECTED" },
        { "axis_code": "vividness", "value": 40, "status": "REFLECTED" },
        { "axis_code": "tone", "value": 55, "status": "REFLECTED" },
        { "axis_code": "density", "value": 30, "status": "REFLECTED" },
        { "axis_code": "framing", "value": 70, "status": "REFLECTED" },
        { "axis_code": "angle", "value": 45, "status": "REFLECTED" }
    ]
}
```
`status`: `REFLECTED`(반영 완료) / `PENDING`(미반영). 현재는 2.5가 동기 처리라 실질적으로 항상 `REFLECTED`이며, `PENDING`은 추천 로직이 무거워져 비동기로 전환될 경우를 대비한 필드다.

## 2.5 취향 축 값 수정

축 하나의 값을 마이페이지 슬라이더로 직접 조정. 저장과 동시에 서버가 taste 프로파일 전체를 동기적으로 재계산하고 반영하므로, 응답 시점에는 이미 `status: "REFLECTED"`다.

Method `PUT` · EndPoint `/users/me/taste-profile/axes/{axisCode}` · 인증 필요

Param `{ "axisCode": "brightness" }`

Body
```json
{ "value": 70 }
```
Response
```json
{ "axis_code": "brightness", "user_id": 1, "value": 70, "status": "REFLECTED" }
```
- `status`는 클라이언트가 보내지 않는다(서버 응답 전용).
- 이 호출은 내부적으로 2.3을 트리거한다.

---

## 3. 홈

## 3.1 진행 중인 여행 요약 조회

`segment_id`가 `NULL`인 핀들을 그때그때 집계해 반환. 실제 `TRAVEL_SEGMENT` 레코드는 없다.

Method `GET` · EndPoint `/trips/current` · 인증 필요

Response
```json
{
    "has_pins": true, "pin_count": 7, "photo_count": 41,
    "started_at": "2026-08-01T09:00:00.000000Z",
    "cities": ["도쿄", "요코하마"]
}
```
`has_pins: false`면 빈 상태(클라이언트는 태깅 유도 문구 표시).

## 3.2 여행 종료(여정 생성)

`segment_id`가 `NULL`인 핀 전체를 모아 새 `TRAVEL_SEGMENT`를 생성하고 배정. 성공 시 포토북 생성이 트리거된다.

Method `POST` · EndPoint `/trips` · 인증 필요

Body
```json
{ "name": "도쿄 3일", "end_at": "2026-08-03T15:00:00.000000Z" }
```
Response
```json
{
    "segment_id": 12, "user_id": 1, "name": "도쿄 3일",
    "start_at": "2026-08-01T09:00:00.000000Z", "end_at": "2026-08-03T15:00:00.000000Z",
    "status": true, "pin_count": 7, "photobook_id": 30
}
```
- `name` 미입력 시 기본값은 배정 대상 핀들의 방문 도시를 방문 순서대로 나열한 문자열(예: `"도쿄, 요코하마"`).
- `end_at` 미입력 시: 배정 대상 핀들의 `tagged_at` 최댓값(마지막 핀 시각)을 사용한다.
- `end_at`을 직접 입력한 경우: 그 값을 그대로 쓰고, 그 시각 이후 태깅된 핀은 세그먼트에 배정하되 `included_in_segment=false`로 자동 처리해 이 여행에서 제외한다.
- `start_at`은 배정 대상 핀들의 `tagged_at` 최솟값으로 서버가 계산한다.
- 배정 대상 핀이 0개면 `409 CONFLICT (EMPTY_TRIP)`.
- **[신규] `end_at`을 배정 대상 핀들의 최솟값보다도 이르게 입력해, 배정된 핀 전부가 `included_in_segment=false`로 자동 제외되는 경우에도 `409 CONFLICT (EMPTY_TRIP)`를 반환한다.** 배정 자체는 0개가 아니어도 "실제로 포함되는 핀"이 0개인 빈 여행이 생성되는 것을 막기 위함(4.3의 "핀을 하나도 남기지 않고 전부 제외하면 VALIDATION_ERROR"와 동일한 취지).

## 3.3 국가별 방문 도장 목록

Method `GET` · EndPoint `/users/me/country-stamps` · 인증 필요

Response
```json
{
    "stamps": [
        { "country_code": 82, "country_name": "대한민국" },
        { "country_code": 81, "country_name": "일본" }
    ]
}
```

---

## 4. 여행 구간 관리

> 아래는 전부 여행 종료 이후(`TRAVEL_SEGMENT`가 실제로 존재하는) 상태에서만 동작한다. 여행 진행 중에는 대상 세그먼트 자체가 없어 호출할 수 없다.

## 4.1 여행 구간 목록 조회

Method `GET` · EndPoint `/trips` · 인증 필요 · Param `{ "cursor": null, "limit": 20 }`

Response
```json
{
    "trips": [
        { "segment_id": 12, "name": "도쿄 3일", "start_at": "...", "end_at": "..." }
    ],
    "next_cursor": null
}
```

## 4.2 여행 구간 상세 조회

Method `GET` · EndPoint `/trips/{segmentId}` · 인증 필요

Response
```json
{
    "segment_id": 12, "user_id": 1, "name": "도쿄 3일",
    "start_at": "...", "end_at": "...", "status": true,
    "pin_count": 7, "photo_count": 41
}
```

## 4.3 여행 구간 수정

이름 수정, 또는 포함 핀 제외/재포함.

Method `PATCH` · EndPoint `/trips/{segmentId}` · 인증 필요

Body
```json
{
    "name": "도쿄 3일",
    "pin_exclusions": [
        { "pin_id": 105, "included_in_segment": false },
        { "pin_id": 108, "included_in_segment": true }
    ]
}
```
Response
```json
{
    "segment_id": 12, "name": "도쿄 3일",
    "start_at": "...", "end_at": "...", "pin_count": 6, "photo_count": 34
}
```
- `pin_exclusions`는 `included_in_segment`를 `false`(제외)와 `true`(재포함) 양쪽 다 허용한다.
- 시작/종료 핀이 제외·재포함되면 `start_at`/`end_at`은 남은 포함 핀 기준으로 서버가 자동 재계산한다.
- 저장 시 포함 핀 구성이 바뀌므로 해당 세그먼트의 포토북을 재생성한다. 재생성 시 `included_in_segment=false`인 핀은 대상에서 제외한다.
- 핀을 하나도 남기지 않고 전부 제외하면 `VALIDATION_ERROR`.

## 4.4 여행 구간 삭제

여행 구간과 그에 속한 핀·사진·음성메모를 전부 삭제하고, 포토북도 함께 삭제한다(cascade, DB FK 레벨에서 강제됨).

Method `DELETE` · EndPoint `/trips/{segmentId}` · 인증 필요 · Response `204 No Content`

## 4.5 구간 내 핀 목록 조회

제외된 핀도 `included_in_segment: false`로 함께 표시.

Method `GET` · EndPoint `/trips/{segmentId}/pins` · 인증 필요

Response
```json
{
    "pins": [
        {
            "pin_id": 101, "place_name": "시부야 스카이",
            "latitude": 35.660, "longitude": 139.702,
            "tagged_at": "...", "included_in_segment": true
        }
    ],
    "next_cursor": null
}
```

---

## 5. 여행 기록 탐색

## 5.1 핀 상세 조회

Method `GET` · EndPoint `/pins/{pinId}` · 인증 필요

Response
```json
{
    "pin_id": 101, "segment_id": 12,
    "latitude": 35.660, "longitude": 139.702,
    "address": "일본 도쿄도 시부야구 도겐자카 1-2-3",
    "place_name": "시부야 스카이",
    "tagged_at": "...", "text_note": "노을이 예뻤다",
    "voice_memo": { "voice_memo_id": 55, "duration_sec": 12 },
    "representative_photos": [
        { "photo_id": 900, "url": "..." },
        { "photo_id": 903, "url": "..." },
        { "photo_id": 907, "url": "..." }
    ]
}
```
`address`는 좌표를 자동 역지오코딩해 저장한 값(수정 불가). `place_name`은 사용자가 직접 입력한 상세 장소명으로 미입력 시 빈 문자열.

## 5.2 핀 정보 수정

장소명(사용자 입력)·텍스트 기록만 수정 가능. 좌표·주소·음성메모는 생성 이후 수정 불가.

Method `PATCH` · EndPoint `/pins/{pinId}` · 인증 필요

Body
```json
{ "place_name": "시부야 스카이", "text_note": "노을이 예뻤다" }
```
Response
```json
{ "pin_id": 101, "place_name": "시부야 스카이", "text_note": "노을이 예뻤다" }
```

## 5.3 핀 삭제

아직 여정으로 배정되지 않은(`segment_id = NULL`, 진행 중) 핀만 삭제 가능. 이미 종료된 여행에 속한 핀은 4.3의 제외(`included_in_segment=false`)를 사용한다.

Method `DELETE` · EndPoint `/pins/{pinId}` · 인증 필요 · Response `204 No Content`

`segment_id`가 이미 채워진 핀에 호출하면 `409 CONFLICT (USE_TRIP_EXCLUSION)`.

## 5.4 핀 사진 목록 조회

Method `GET` · EndPoint `/pins/{pinId}/photos` · 인증 필요

Response
```json
{
    "photos": [
        { "photo_id": 900, "captured_at": "...", "file_path": "...", "is_pin_cover": true }
    ],
    "next_cursor": null
}
```

## 5.5 사진 등록

핀 반경 1km 이내에서 촬영된 사진만 추가 등록. 반경 밖이거나 좌표가 없는 사진이 섞여 있으면 **그 사진들만 제외**하고 나머지는 정상 등록(요청 전체를 거부하지 않음). 핀이 이미 종료된 여행(`segment_id`가 채워짐)에 속해 있으면 사진 추가 자체를 거부한다.

Method `POST` · EndPoint `/pins/{pinId}/photos` · 인증 필요

Body
```json
{
    "photos": [
        { "file_id": "file_10", "captured_at": "...", "latitude": 35.660, "longitude": 139.702 },
        { "file_id": "file_11", "captured_at": "...", "latitude": 35.700, "longitude": 139.800 },
        { "file_id": "file_12", "captured_at": "..." }
    ]
}
```
Response (정상)
```json
{
    "added": [ { "photo_id": 951, "file_id": "file_10" } ],
    "rejected": [
        { "file_id": "file_11", "reason": "OUT_OF_RADIUS" },
        { "file_id": "file_12", "reason": "MISSING_COORDINATES" }
    ]
}
```
Response (이미 종료된 여행의 핀인 경우)
```json
{ "success": false, "error": { "code": "CONFLICT", "message": "이미 종료된 여행에는 사진을 추가할 수 없습니다." } }
```
- `segment_id IS NOT NULL`이면 요청 전체를 `409 CONFLICT`로 거부한다. 이 조건을 통과한 뒤에만 반경/좌표 검증(`rejected`)을 수행한다.

## 5.6 대표사진 새로고침

핀의 대표사진 3장을 한 번에 다시 뽑는다. 개별 사진 단위 수정은 제공하지 않는다.

Method `POST` · EndPoint `/pins/{pinId}/representative-photos/refresh` · 인증 필요

Response
```json
{
    "representative_photos": [
        { "photo_id": 907, "url": "..." },
        { "photo_id": 912, "url": "..." },
        { "photo_id": 920, "url": "..." }
    ]
}
```
- 선정 로직: 핀에 포함된 사진을 새로고침 시점의 취향 프로파일 기준으로 재정렬해 상위 10개를 뽑고, 그중 무작위 3개를 대표사진으로 지정(기존 3장 플래그 해제 후 새 3장에 `is_pin_cover=true`). 이전 추천 이력은 보존하지 않는다.
- 이미 생성된 핀의 대표사진은 이후 취향 프로파일이 바뀌어도 자동 갱신되지 않는다. 사용자가 새로고침을 직접 눌렀을 때만 그 시점 프로파일로 재계산한다.
- 이 새로고침 행위 자체는 취향 프로파일 학습(보정 신호)에 반영하지 않는다.

## 5.7 사진 삭제

Method `DELETE` · EndPoint `/photos/{photoId}` · 인증 필요 · Response `204 No Content`

삭제된 사진이 대표사진(`is_pin_cover=true`)이었다면, 남은 사진 중에서 서버가 자동으로 대체 1장을 채워 항상 최대 3장을 유지한다.

## 5.8 음성 메모 조회

음성 메모는 8.2(핀 생성) 시점에만 등록되며 이후 추가·삭제·교체는 불가. **텍스트 변환(STT)은 수행하지 않으며 원본 음성 재생만 제공한다.**

Method `GET` · EndPoint `/pins/{pinId}/voice-memos` · 인증 필요

Response
```json
{
    "voice_memo": {
        "voice_memo_id": 55,
        "audio_file": "https://cdn.orte.app/voices/55.m4a",
        "saved_at": "..."
    }
}
```
음성 메모가 없으면 `voice_memo: null`.

---

## 6. 포토북 아카이브

> 포토북은 3.2(여행 종료) 시점에 자동 생성되고, 4.3에서 포함 핀이 바뀌면 자동 재생성된다. 클라이언트가 직접 생성/삭제를 호출하는 엔드포인트는 없다(삭제는 4.4의 부수 효과).

## 6.1 포토북 목록 조회

Method `GET` · EndPoint `/photobooks` · 인증 필요 · Param `{ "cursor": null, "limit": 20 }`

Response
```json
{
    "photobooks": [
        {
            "photobook_id": 30, "segment_id": 12, "name": "도쿄 3일",
            "start_at": "...", "end_at": "...",
            "cities": ["도쿄", "요코하마"], "photo_count": 24,
            "cover_photo_url": "..."
        }
    ],
    "next_cursor": null
}
```

## 6.2 포토북 상세 조회

프론트에서 지도(핀+동선) 화면을 그릴 수 있도록 핀별 사진 개수를 포함한 전체 핀 목록도 함께 내려준다.

Method `GET` · EndPoint `/photobooks/{photobookId}` · 인증 필요

Response
```json
{
    "photobook_id": 30, "segment_id": 12, "name": "도쿄 3일",
    "start_at": "...", "end_at": "...", "total_days": 3,
    "cities": ["도쿄", "요코하마"],
    "cover_photo_url": "...",
    "pins": [
        { "pin_id": 101, "latitude": 35.660, "longitude": 139.702, "place_name": "시부야 스카이", "photo_count": 5 }
    ]
}
```
`pins`는 촬영 시각 순으로 정렬되며, 프론트는 인접 핀을 이어 동선을 그리고 `photo_count`로 구간 농도(그라데이션)를 표현한다.

## 6.3 포토북 이름 수정

Method `PATCH` · EndPoint `/photobooks/{photobookId}` · 인증 필요

Body `{ "name": "도쿄 여행" }` → Response `{ "photobook_id": 30, "name": "도쿄 여행" }`

## 6.4 포토북 커버 사진 새로고침

Method `POST` · EndPoint `/photobooks/{photobookId}/cover/refresh` · 인증 필요

Response
```json
{ "cover_photo_url": "..." }
```
선정 로직: 포토북에 포함된 사진을 새로고침 시점 취향 프로파일 기준으로 재정렬해 상위 10개를 뽑고, 그중 무작위 1장을 커버로 지정(5.6과 동일한 방식, 대상만 핀 단위 → 포토북 단위로 확장).

> **[제거] 포토북 포함 핀 목록 조회**는 별도 엔드포인트를 두지 않는다. 6.2가 이미 지도용 `pins` 배열을 전부 내려주므로 중복이었다.

---

## 7. 마이페이지

## 7.1 등록 제품 목록 조회

Method `GET` · EndPoint `/users/me/products` · 인증 필요

Response
```json
{
    "products": [
        { "tag_id": "tag_abc", "product_type": "BAG", "product_name": "MCM 백팩", "registered_at": "...", "tagging_count": 5 }
    ]
}
```
- `tagging_count`는 이 태그로 생성된 핀 수로 집계한다(태깅 세션 개념을 쓰지 않으므로, "핀 개수 = 태깅 횟수"가 자연스러운 대체 지표: 계속 촬영은 같은 핀에 사진만 추가될 뿐 새 핀을 만들지 않으므로 중복 집계되지 않는다).
- 다른 사용자가 동일 태그를 태깅하는 시나리오는 스코프 밖으로 확정, 태그:계정은 사실상 1:1로 취급한다.

## 7.2 제품 연결 해제

잘못 등록된 제품의 계정 연결 해제.

Method `PATCH` · EndPoint `/products/{tagId}/unlink` · 인증 필요

Response
```json
{ "tag_id": "tag_abc", "user_id": null }
```
- 해제 시 `user_id`를 `null`로 비우고 `unlinked_at`을 현재 시각으로 채운다. 이후 같은 태그가 다시 태깅되면 `unlinked_at IS NOT NULL`인지만 확인해 자동 등록을 막는다(누가 해제했었는지는 스코프 밖이라 별도로 보존하지 않는다).

프로필 조회(1.3), 취향 프로파일 시각화(2.4), 로그아웃(1.2)은 마이페이지에서도 그대로 재사용된다.

---

## 8. NFC 태깅 및 핀 저장

## 8.1 태그 자동 등록(현재 계정에 연결)

Method `PATCH` · EndPoint `/products/{tagId}/link` · 인증 필요

Response
```json
{ "tag_id": "tag_abc", "user_id": 1, "registered_at": "..." }
```

## 8.2 촬영 결과로 핀 생성

NFC 태깅(또는 여행 계속하기·지도에서 수동 입력) 후 촬영한 결과를 핀으로 저장. 여행 구간을 지정하지 않는다 — 서버가 `segment_id = NULL`로 생성한다.

Method `POST` · EndPoint `/pins` · 인증 필요

Body
```json
{
    "nfc_tag_id": "tag_abc",
    "latitude": 35.660, "longitude": 139.702,
    "address": "일본 도쿄도 시부야구 도겐자카 1-2-3",
    "place_name": "",
    "text_note": "노을이 예뻤다",
    "audio_file": "https://cdn.orte.app/voices/55.m4a"
}
```
Response
```json
{
    "pin_id": 101, "segment_id": null,
    "latitude": 35.660, "longitude": 139.702,
    "address": "일본 도쿄도 시부야구 도겐자카 1-2-3",
    "place_name": "", "tagged_at": "...",
    "text_note": "노을이 예뻤다",
    "voice_memo": { "voice_memo_id": 55 }
}
```
- `nfc_tag_id`는 선택 값이다. NFC 태깅 없이(여행 계속하기, 지도에서 수동 입력) 생성할 때는 생략한다. 다만 위치·시간과 무관하게 매 태깅마다 새 핀이 생성되는 규칙이므로 "같은 핀에 이어서 촬영"이라는 흐름은 없다 — 새로 태깅하면 항상 새 핀이다.
- `address`는 프론트가 좌표를 역지오코딩해서 채운다(자동). `place_name`은 사용자가 그 자리에서 입력하지 않으면 빈 문자열.
- `audio_file`은 이 시점에만 등록 가능하며 원본 음성만 저장한다(텍스트 변환 없음). 이후에는 5.8로 조회만 되고 수정·삭제 API는 없다.
- 촬영한 사진들은 핀 생성 후 **5.5 사진 등록**으로 별도 첨부한다.
- 텍스트 기록만 나중에 고치고 싶다면 **5.2 핀 정보 수정**을 사용한다.

---

## 부록 A. 이번 최종본에서 확정/변경된 사항 요약 (v3 대비)

| 항목 | v3 | 최종본 |
|---|---|---|
| 3.2 빈 여행 방지 | 배정 대상 핀 0개일 때만 `EMPTY_TRIP` | `end_at`을 이르게 입력해 배정된 핀 전부가 제외되는 경우도 `EMPTY_TRIP`로 확장 |
| 7.1/7.4 태깅 횟수 정의 | 태깅 세션 수로 집계(세션 테이블 전제) | 세션 개념 제거 확정 → **핀 개수**로 집계하도록 재정의 |
| 7.2 연결 해제 재등록 방지 | 별도 `PRODUCT_UNLINK` 테이블 검토 | `MCM_PRODUCT.unlinked_at` 컬럼으로 단순화(다중 사용자 태깅 스코프 제외로 성립) |
| 세션 토큰 형식 | "세션 토큰"으로만 표기 | JWT임을 명시 |
| 비동기 작업 확인 방법 | 미정 | 폴링 방식(별도 상태 엔드포인트 없음) 확정 |

## 부록 B. 스코프 밖으로 확정되어 이번 최종본에 반영하지 않은 것

- **태깅 세션 단위 사진 그룹핑**(구 5.3): "1태깅=1핀" 규칙으로 대체되어 그룹핑 자체가 불필요해짐.
- **추천 버전 관리·재추천 이력 보존**: `PHOTO.is_pin_cover` 플래그 방식으로 단순화, 이력 미보존.
- **다중 사용자의 동일 태그 태깅**: 태그:계정을 사실상 1:1로 가정.
- **여행 진행 중 별도 여정 분리 생성**: 검토했으나 파급 범위가 커서 보류, 기존 "여행 종료 후 구간 편집"(4.3) 방식 유지.
- **6.3 도시별 포토북**(자유형 콜라주 레이아웃): 기능명세서 원문에서 취소선 처리되어 스코프 제외.

## 부록 C. 기능명세서 하위 기능 커버리지 체크

| 기능 | 커버 엔드포인트 |
|---|---|
| 1.1~1.4 / 1.5 | `/auth/*`, `/users/me`, `/events/permissions` |
| 2.1~2.5 | `/users/me/basic-question-responses`, `/users/me/selection-photos`, `/users/me/taste-profile*` |
| 3.1~3.3 | `/trips/current`, `/trips`(POST), `/users/me/country-stamps` |
| 4.1~4.5 | `/trips`, `/trips/{id}`, `/trips/{id}/pins` |
| 5.1~5.8 | `/pins/{id}`, `/pins/{id}/photos`, `/pins/{id}/representative-photos/refresh`, `/photos/{id}`, `/pins/{id}/voice-memos` |
| 6.1~6.4 | `/photobooks`, `/photobooks/{id}`, `/photobooks/{id}/cover/refresh` |
| 7.1~7.2 | `/users/me/products`, `/products/{tagId}/unlink` |
| 8.1~8.2 | `/products/{tagId}/link`, `/pins`(POST) |

6.3(도시별 포토북)은 기능명세서 원문 취소선 처리로 커버리지에서 제외했다.