-- =========================================================
-- MCM NFC (Orte) ERD - FINAL (v5 기준)
-- API 명세서 최종본과 1:1로 대응하는 최종 스키마.
--
-- v4 대비 변경 사항 (API 명세서 v2/v3 확정 내용 반영):
--
--   1. PIN.included_in_segment BOOLEAN DEFAULT TRUE 추가
--      - 여행 종료(세그먼트 배정) 이후, 핀을 완전히 삭제하지 않고
--        "이 여행에 포함할지"만 껐다 켤 수 있게(제외/재포함) 하기 위함
--      - segment_id가 NULL이면 애초에 의미 없는 값(아직 미배정)
--
--   2. PIN.address VARCHAR(300) 추가
--      - 좌표를 자동 역지오코딩해 저장하는 값(수정 불가)
--      - 기존 place_name은 "사용자가 직접 입력하는 상세 장소명"으로 용도 축소
--        (미입력 시 빈 문자열, place_name 컬럼 자체는 변경 없음)
--
--   3. PHOTOBOOK.cover_photo_id INT nullable 추가 (FK -> PHOTO.photo_id)
--      - 포토북 커버 사진을 저장할 컬럼이 기존에 없었음
--      - 커버 새로고침(POST /photobooks/{id}/cover/refresh) 시 이 값만 갱신
--
--   4. TASTE_PROFILE_AXIS.status 값 도메인 확정
--      - ENUM('active','inactive') [임시값] -> ENUM('REFLECTED','PENDING')
--      - REFLECTED: 슬라이더 조정이 취향 프로파일에 반영 완료
--      - PENDING: 조정했지만 아직 미반영(현재는 동기 처리라 실사용 안 됨,
--        추후 비동기 전환 대비용으로 필드만 유지)
--
--   5. MCM_PRODUCT.unlinked_at DATETIME NULL 추가 (PRODUCT_UNLINK 테이블 대체)
--      - "다른 사용자가 같은 태그를 태깅하는 경우"는 스코프 밖으로 확정되어
--        태그:계정이 사실상 1:1이므로, 별도 이력 테이블 대신 컬럼 하나로 충분
--      - [확정] 연결 해제(7.2) 시 user_id는 그대로 NULL로 비운다(API 응답과 동일).
--        재등록 방지 판단은 "누가 해제했는지"가 아니라 "이 태그가 해제된 적
--        있는지"만 보면 되므로 unlinked_at IS NOT NULL 체크만으로 충분.
--        (다중 사용자 태깅을 스코프 밖으로 뒀기 때문에 성립하는 단순화)
--
--   6. FK에 ON DELETE 옵션 명시 (v4까지는 전부 기본값=RESTRICT였음)
--      - 여행 구간 삭제(DELETE /trips/{id}) 시 핀·사진·음성메모·포토북까지
--        cascade 삭제된다는 게 API v3에서 확정되었으므로, DB 레벨에서도
--        같은 규칙을 강제해야 애플리케이션 코드 경로와 무관하게 정합성 보장됨
--      - TRAVEL_SEGMENT -> PIN, PHOTOBOOK : CASCADE
--      - PIN -> PHOTO, VOICE_MEMO : CASCADE
--      - PIN -> PHOTOBOOK(photobook_id) : SET NULL (포토북만 단독 삭제되는
--        경우를 대비한 안전장치, 현재 API엔 포토북 단독 삭제 엔드포인트 없음)
--      - PHOTOBOOK -> PHOTO(cover_photo_id) : SET NULL (커버로 쓰인 사진이
--        삭제돼도 포토북 자체는 남아야 하므로)
--
--   보류/미반영:
--   - TRAVEL_SEGMENT.status, cover_photo_url 존치 여부: 팀 내 논의 중(부록 B),
--     결론 나기 전까지 컬럼 유지
--   - TAGGING_SESSION, RECOMMENDATION, TAG_PRODUCT_MAP: 불필요 확정되어 추가 안 함
--     (태깅 세션 개념 자체 제외 확정 / 추천은 PHOTO.is_pin_cover 플래그로 충분 확정 /
--      다중 사용자 태깅 시나리오 제외로 매핑·등록 분리 불필요 확정)
-- =========================================================

CREATE TABLE `USER` (
	`user_id`	INT	NOT NULL,
	`email`	VARCHAR(150)	NULL,
	`created_at`	DATETIME	NULL,
	`onboarding_completed`	BOOLEAN	NULL,
	`permission_intro_shown`	BOOLEAN	NULL,
	`account_identifier`	VARCHAR(150)	NULL
);

CREATE TABLE `TASTE_PROFILE` (
	`user_id`	INT	NOT NULL,
	`last_updated_at`	DATETIME	NULL,
	`taste`	TEXT	NULL
);

CREATE TABLE `TASTE_PROFILE_AXIS` (
	`axis_code`	VARCHAR(50)	NOT NULL,
	`user_id`	INT	NOT NULL,
	`value`	INT	NULL,
	`status`	ENUM('REFLECTED','PENDING')	NULL
);

CREATE TABLE `BASIC_QUESTION_RESPONSE` (
	`response_id`	INT	NOT NULL,
	`user_id`	INT	NULL,
	`round_no`	INT	NULL,
	`answer`	VARCHAR(100)	NULL,
	`answered_at`	DATETIME	NULL
);

CREATE TABLE `SELECTION_PHOTO` (
	`selection_photo_id`	INT	NOT NULL,
	`user_id`	INT	NULL,
	`round_no`	INT	NULL,
	`status`	BOOLEAN	NULL,
	`selected_at`	DATETIME	NULL
);

CREATE TABLE `COUNTRY_STAMP` (
	`country_code`	INT	NOT NULL,
	`user_id`	INT	NOT NULL,
	`country_name`	VARCHAR(50)	NULL
);

-- MCM_PRODUCT: unlinked_at으로 연결 해제 이력을 남겨 재등록(7.5 자동 등록)을 막음.
-- user_id는 해제 후에도 "누가 마지막으로 연결했었는지" 이력 보존을 위해 NULL로
-- 비우지 않는 것을 권장(비우려면 API 로직과 별도로 재확인 필요, 위 주석 5번 참고).
CREATE TABLE `MCM_PRODUCT` (
	`tag_id`	VARCHAR(100)	NOT NULL,
	`user_id`	INT	NULL,
	`product_type`	VARCHAR(30)	NULL,
	`product_name`	VARCHAR(100)	NULL,
	`registered_at`	DATETIME	NULL,
	`tag_count`	INT	NULL,
	`unlinked_at`	DATETIME	NULL
);

-- TRAVEL_SEGMENT.status, cover_photo_url: 존치 여부 팀 내 논의 중(보류)
CREATE TABLE `TRAVEL_SEGMENT` (
	`segment_id`	INT	NOT NULL,
	`user_id`	INT	NULL,
	`name`	VARCHAR(100)	NULL,
	`start_at`	DATETIME	NULL,
	`end_at`	DATETIME	NULL,
	`status`	BOOLEAN	NULL,
	`cover_photo_url`	VARCHAR(500)	NULL
);

-- PHOTOBOOK.cover_photo_id: 포토북 커버 사진 참조(신규)
CREATE TABLE `PHOTOBOOK` (
	`photobook_id`	INT	NOT NULL,
	`segment_id`	INT	NOT NULL,
	`title`	VARCHAR(100)	NULL,
	`generated_at`	DATETIME	NULL,
	`cover_photo_id`	INT	NULL
);

-- PIN:
--   segment_id          : nullable (여행 진행 중엔 NULL, 종료 시 배정)
--   photobook_id         : nullable ("포토북 선정 여부" 표현, 세그먼트로 유도 불가한 별도 정보)
--   included_in_segment  : 배정된 이후 이 여행에 포함할지 여부(제외/재포함 토글, 신규)
--   address               : 좌표 자동 역지오코딩 주소(신규, 수정 불가)
--   place_name            : 사용자가 직접 입력하는 상세 장소명(용도 축소, 컬럼 변경 없음)
CREATE TABLE `PIN` (
	`pin_id`	INT	NOT NULL,
	`segment_id`	INT	NULL,
	`photobook_id`	INT	NULL,
	`latitude`	DECIMAL(10,6)	NULL,
	`longitude`	DECIMAL(10,6)	NULL,
	`address`	VARCHAR(300)	NULL,
	`place_name`	VARCHAR(150)	NULL,
	`tagged_at`	DATETIME	NULL,
	`text_note`	VARCHAR(500)	NULL,
	`saved_at`	DATETIME	NULL,
	`city`	VARCHAR(100)	NULL,
	`included_in_segment`	BOOLEAN	NOT NULL DEFAULT TRUE
);

CREATE TABLE `PHOTO` (
	`photo_id`	INT	NOT NULL,
	`pin_id`	INT	NULL,
	`captured_at`	DATETIME	NULL,
	`latitude`	DECIMAL(10,6)	NULL,
	`longitude`	DECIMAL(10,6)	NULL,
	`source_type`	VARCHAR(30)	NULL,
	`photo_url`	VARCHAR(500)	NULL,
	`is_pin_cover`	BOOLEAN	NULL
);

CREATE TABLE `VOICE_MEMO` (
	`voice_memo_id`	INT	NOT NULL,
	`pin_id`	INT	NOT NULL,
	`audio_url`	VARCHAR(255)	NULL,
	`saved_at`	DATETIME	NULL
);

-- =========================================================
-- PRIMARY KEYS
-- =========================================================

ALTER TABLE `USER` ADD CONSTRAINT `PK_USER` PRIMARY KEY (`user_id`);
ALTER TABLE `TASTE_PROFILE` ADD CONSTRAINT `PK_TASTE_PROFILE` PRIMARY KEY (`user_id`);
ALTER TABLE `TASTE_PROFILE_AXIS` ADD CONSTRAINT `PK_TASTE_PROFILE_AXIS` PRIMARY KEY (`axis_code`, `user_id`);
ALTER TABLE `BASIC_QUESTION_RESPONSE` ADD CONSTRAINT `PK_BASIC_QUESTION_RESPONSE` PRIMARY KEY (`response_id`);
ALTER TABLE `SELECTION_PHOTO` ADD CONSTRAINT `PK_SELECTION_PHOTO` PRIMARY KEY (`selection_photo_id`);
ALTER TABLE `COUNTRY_STAMP` ADD CONSTRAINT `PK_COUNTRY_STAMP` PRIMARY KEY (`country_code`, `user_id`);
ALTER TABLE `MCM_PRODUCT` ADD CONSTRAINT `PK_MCM_PRODUCT` PRIMARY KEY (`tag_id`);
ALTER TABLE `TRAVEL_SEGMENT` ADD CONSTRAINT `PK_TRAVEL_SEGMENT` PRIMARY KEY (`segment_id`);
ALTER TABLE `PHOTOBOOK` ADD CONSTRAINT `PK_PHOTOBOOK` PRIMARY KEY (`photobook_id`);
ALTER TABLE `PIN` ADD CONSTRAINT `PK_PIN` PRIMARY KEY (`pin_id`);
ALTER TABLE `PHOTO` ADD CONSTRAINT `PK_PHOTO` PRIMARY KEY (`photo_id`);
ALTER TABLE `VOICE_MEMO` ADD CONSTRAINT `PK_VOICE_MEMO` PRIMARY KEY (`voice_memo_id`);

-- =========================================================
-- FOREIGN KEYS
-- =========================================================

-- taste 앱
ALTER TABLE `TASTE_PROFILE` ADD CONSTRAINT `FK_USER_TO_TASTE_PROFILE`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

ALTER TABLE `TASTE_PROFILE_AXIS` ADD CONSTRAINT `FK_USER_TO_TASTE_PROFILE_AXIS`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

ALTER TABLE `BASIC_QUESTION_RESPONSE` ADD CONSTRAINT `FK_USER_TO_BASIC_QUESTION_RESPONSE`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

ALTER TABLE `SELECTION_PHOTO` ADD CONSTRAINT `FK_USER_TO_SELECTION_PHOTO`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

-- accounts 앱
ALTER TABLE `COUNTRY_STAMP` ADD CONSTRAINT `FK_USER_TO_COUNTRY_STAMP`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

-- products 앱
ALTER TABLE `MCM_PRODUCT` ADD CONSTRAINT `FK_USER_TO_MCM_PRODUCT`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

-- travel 앱
ALTER TABLE `TRAVEL_SEGMENT` ADD CONSTRAINT `FK_USER_TO_TRAVEL_SEGMENT`
	FOREIGN KEY (`user_id`) REFERENCES `USER` (`user_id`);

-- 여행 구간 삭제 시 핀까지 cascade 삭제 (API v3 4.4 확정 사항)
ALTER TABLE `PIN` ADD CONSTRAINT `FK_TRAVEL_SEGMENT_TO_PIN`
	FOREIGN KEY (`segment_id`) REFERENCES `TRAVEL_SEGMENT` (`segment_id`)
	ON DELETE CASCADE;

-- 핀 삭제 시 사진도 cascade 삭제
ALTER TABLE `PHOTO` ADD CONSTRAINT `FK_PIN_TO_PHOTO`
	FOREIGN KEY (`pin_id`) REFERENCES `PIN` (`pin_id`)
	ON DELETE CASCADE;

-- 핀 삭제 시 음성메모도 cascade 삭제
ALTER TABLE `VOICE_MEMO` ADD CONSTRAINT `FK_PIN_TO_VOICE_MEMO`
	FOREIGN KEY (`pin_id`) REFERENCES `PIN` (`pin_id`)
	ON DELETE CASCADE;

-- photobooks 앱
-- 여행 구간 삭제 시 포토북도 cascade 삭제 (API v3 4.4 확정 사항)
ALTER TABLE `PHOTOBOOK` ADD CONSTRAINT `FK_TRAVEL_SEGMENT_TO_PHOTOBOOK`
	FOREIGN KEY (`segment_id`) REFERENCES `TRAVEL_SEGMENT` (`segment_id`)
	ON DELETE CASCADE;

-- PIN.photobook_id: nullable FK (선정 여부 표현). 포토북이 단독 삭제되는 경우를
-- 대비해 SET NULL(핀 자체는 남기고 선정 상태만 해제). 현재 API엔 포토북 단독
-- 삭제 엔드포인트가 없어 실질적으로는 세그먼트 cascade로 함께 정리되는 경로가 대부분.
ALTER TABLE `PIN` ADD CONSTRAINT `FK_PHOTOBOOK_TO_PIN`
	FOREIGN KEY (`photobook_id`) REFERENCES `PHOTOBOOK` (`photobook_id`)
	ON DELETE SET NULL;

-- PHOTOBOOK.cover_photo_id: 커버로 쓰인 사진이 삭제돼도 포토북 자체는 남아야 하므로 SET NULL
ALTER TABLE `PHOTOBOOK` ADD CONSTRAINT `FK_PHOTO_TO_PHOTOBOOK_COVER`
	FOREIGN KEY (`cover_photo_id`) REFERENCES `PHOTO` (`photo_id`)
	ON DELETE SET NULL;
