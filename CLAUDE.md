# CLAUDE.md

이 파일은 Claude Code가 이 repo에서 세션을 열 때마다 자동으로 읽는 프로젝트 지침입니다.
모든 작업자(Claude Code 포함)는 아래 규칙을 따릅니다.

중요 규칙: 답변은 모두 한국어로 진행, 코드 추가 및 수정 전 근거를 댈 것

## 프로젝트 개요

Orte — NFC 태깅으로 여행 순간을 기록하고 취향 기반으로 사진을 추천해 포토북으로 아카이빙하는 서비스.

- 백엔드: Django + Django REST Framework (DRF)
- DB: MySQL (로컬은 Docker 사용)
- 스펙 원문: `docs/spec.md` (ERD + 기능명세서) — 모르는 도메인 용어나 기능 흐름은 반드시 이 파일을 먼저 참조할 것
  - `spec.md` 맨 위 "0. 원본 스펙 최신화 상태 체크리스트"를 항상 먼저 확인한다. 원본 기능명세서와 이 체크리스트 내용이 다르면 체크리스트를 따른다.
- 구현 결정 로그: `docs/IMPLEMENTATION.md` — 스펙에 없지만 구현하며 확정한 세부 규칙은 여기 기록

## 앱 구조 원칙

- Django 앱은 도메인 단위로 완전히 분리한다. 하나의 앱 폴더 안에 `models.py`, `serializers.py`, `views.py`, `urls.py`, `admin.py`, `apps.py`, `migrations/`가 전부 독립적으로 존재한다.
- 다른 앱의 모델을 참조할 때는 `from <app_name>.models import <Model>` 형태로만 import한다. 앱 간 모델 정의를 중복 생성하지 않는다.
- 현재 앱 목록과 담당 도메인:

| 앱 | 담당 도메인 | 주요 모델 |
|---|---|---|
| accounts | 계정·인증 | User, Session |
| taste | 취향 프로파일 온보딩 | TasteProfile, TasteProfileAxis, OnboardingProgress, BasicQuestionResponse, SelectionPhoto, ProfileRetrainHistory |
| recommendations | 추천 | RecommendationResult, RecommendationEdit, RecommendationRegenHistory |
| products | NFC 제품 | NfcTag |
| travel | 여행 기록 핵심 | TravelSegment, Pin, TaggingSession, Photo, VoiceMemo, CountryStamp |
| photobooks | 포토북 | Photobook, PhotobookPin, PhotobookPhotoLayout |

- 이 문서를 읽는 작업자(및 Claude Code)는 taste, recommendations 앱을 우선 담당한다. 다른 앱 코드를 수정해야 할 일이 생기면 먼저 알릴 것.

## 작업 진행 방식 (중요)

**코드를 바로 작성하지 않는다.** 아래 순서를 반드시 지킨다.

1. 요청받은 기능에 대해 먼저 설계안을 제시한다 — 모델 필드/타입, API 엔드포인트(메서드+경로), 요청/응답 스키마, 핵심 로직 흐름을 텍스트로 정리해서 보여준다.
2. 설계안에 대한 승인을 받는다.
3. 승인 후에만 실제 파일을 생성/수정한다.
4. 스펙(`docs/spec.md`)에 없는 세부 규칙을 새로 정했다면, 코드 작성과 함께 `docs/IMPLEMENTATION.md`에 그 결정과 이유를 짧게 남긴다.

작은 수정(오탈자, 이미 승인된 설계의 단순 반영)까지 매번 재승인받을 필요는 없지만, 새로운 엔드포인트·모델·로직 분기가 생기는 작업은 항상 이 순서를 따른다.

**PR 올리기 전에 이번 PR에서 완성된 API 엔드포인트 목록(메서드+경로+간단 설명)을 별도로 정리해서 알려준다.** 사용자가 이걸 보고 팀 공유용 API 문서를 업데이트하는 데 씀.

## 핵심 도메인 로직 — 취향 프로파일과 추천

혼동하기 쉬운 세 가지 흐름을 구분해서 구현한다.

1. **최초 추천 (5.2.1)**: 핀에 연결된 사진을 유사도로 축소 → 현재 `TasteProfileAxis` 값으로 스코어링 → 상위 3장 확정 추천. `TasteProfileAxis`는 변경하지 않는다.
2. **재추천 / 새로고침 (5.2.3)**: 최초 추천과 동일한 스코어링 함수를 재사용하되, 상위 10장 후보 중 3장을 랜덤으로 뽑는다. `TasteProfileAxis`는 변경하지 않는다. (후보가 10장 미만일 때의 처리 기준은 `docs/IMPLEMENTATION.md`에 확정되는 대로 따른다.)
3. **재학습 (7.3)**: 온보딩 설문(기본질문 5문항 + A/B 5쌍 + 무드보드 2라운드)을 처음부터 다시 진행 → 완료 시 `TasteProfileAxis`를 전체 교체. 진행 중에는 기존 프로파일을 유지해 추천이 끊기지 않게 한다.
4. **추천 사진 수정 (5.2.2)**: 사용자가 추천 결과에서 사진을 추가/제외하면 이 신호는 `TasteProfileAxis` 보정에 누적 반영된다 (재학습과는 별개의 점진적 보정 경로).

재추천(2번)과 프로파일 보정(4번)을 같은 로직으로 혼동하지 않는다 — 재추천 버튼 자체는 프로파일을 건드리지 않는다.

## 커밋 메시지 규칙

형식: `타입: 설명 (#이슈번호)`

| 타입 | 설명 |
|---|---|
| feat | 기능 추가 |
| fix | 버그 수정 |
| docs | 문서 수정 |
| style | 포맷팅 등 로직 무관 변경 |
| refactor | 리팩토링 |
| test | 테스트 코드 추가/수정 |
| chore | 빌드, 설정, 패키지 매니저 등 |

- 제목 50자 이내, 명령형
- 예: `feat: 취향 온보딩 A/B 선택 API 구현 (#12)`

## 브랜치 전략

- `main`: 배포 가능 안정 브랜치. 직접 push 금지, PR로만.
- `develop`: 개발 통합 브랜치. 직접 push 금지, PR로만.
- `feature/{이슈번호}-{작업내용}`, `fix/{이슈번호}-{작업내용}`: develop에서 분기, 완료 후 develop으로 PR.
- 병합 방식: Squash and merge. 병합된 브랜치는 삭제.
- PR에는 `Closes #이슈번호` 작성.

## 하지 말아야 할 것

- 스펙에 명시되지 않은 로직을 임의로 추측해서 구현하지 않는다 — 애매하면 먼저 질문한다.
- `.env` 값이나 DB 비밀번호를 코드/문서에 하드코딩하지 않는다.
- 다른 담당자가 맡은 앱(accounts, products, travel, photobooks)의 모델·마이그레이션을 사전 협의 없이 수정하지 않는다.