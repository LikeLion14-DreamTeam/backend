## 브랜치 전략

- `main`: 배포 가능한 안정 브랜치. 직접 push 금지, PR로만 merge
- `feature/{이슈번호}-{작업내용}`: 기능 개발 브랜치
  - 예: feature/12-login-api
- `fix/{이슈번호}-{작업내용}`: 버그 수정 브랜치
  - 예: fix/20-cors-error
- PR 필수, 팀원 1명 이상 리뷰 승인 후 Squash and merge, merge된 브랜치는 삭제

## 커밋 메시지 규칙

형식: `타입: 설명` (이슈 번호 있으면 끝에 `(#이슈번호)`)

| 타입 | 설명 |
|---|---|
| feat | 기능 추가 |
| fix | 버그 수정 |
| docs | 문서 수정 |
| style | 코드 포맷팅 (로직 변경 없음) |
| refactor | 리팩토링 |
| test | 테스트 코드 |
| chore | 빌드, 설정 등 |

예: `feat: 로그인 API 구현 (#12)`

## 이슈 사용법

Issues 탭에서 작업 단위로 등록 → 번호로 브랜치명 짓기 → PR 설명에 `Closes #12` 작성하면 merge 시 자동 종료
