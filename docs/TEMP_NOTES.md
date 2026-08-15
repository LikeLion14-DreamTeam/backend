
# TEMP_NOTES.md

## 목적

이 문서는 정식 구현 전까지 **임시로 대체해둔 부분**만 모아두는 살아있는 체크리스트입니다.
"왜 이렇게 정했는지"는 `docs/IMPLEMENTATION.md` 결정 로그에 남기고, 이 문서에는
"아직 임시 상태인 것 / 무엇으로 교체해야 하는지 / 완료 조건"만 짧게 관리합니다.

항목이 실제로 정식 구현으로 교체되면 체크박스를 채우고, 완료 커밋 해시와 날짜를 남긴 뒤
아래 "완료된 항목" 섹션으로 옮깁니다 (삭제하지 않음 — 나중에 "언제 뭘 왜 치웠는지" 추적용).

---

## 진행 중인 임시 조치

### [ ] recommendations 앱 CLIP 런타임 배포 (미착수)
- **임시로 한 것**: taste 온보딩 카탈로그는 정적 사전계산으로 CLIP 배포 부담을 없앴지만,
  recommendations(5.2.1, 유저 업로드 사진 스코어링)는 사진이 매번 새로 올라와서 런타임에 CLIP을
  실제로 돌려야 함 — 아직 recommendations 앱 자체가 미착수라 배포 방식도 미정.
- **정식으로 교체할 조건**: recommendations 앱 착수 시 CLIP 가중치를 Docker 이미지에 미리
  포함하거나 영구 볼륨으로 캐싱하는 방식을 배포 담당자와 정해야 함.
- **관련 이슈/커밋**: 아직 이슈 없음 (`docs/IMPLEMENTATION.md` 2026-08-15 결정 로그 참고)

---

## 완료된 항목

### [x] `taste/auth_temp.py` + 모델 FK — 임시 인증 및 임시 User 참조
- **임시로 한 것**: accounts 앱의 구글 로그인(JWT)이 아직 없어서, 요청 바디(`user_id`) 또는
  쿼리 파라미터(`?user_id=`)로 사용자를 조회하는 `get_current_user(request)` 헬퍼로 대체.
  taste 6개 모델의 user FK는 `settings.AUTH_USER_MODEL`(Django 기본 `auth.User`)을 참조 중이었음.
- **정식으로 교체한 것**: taste 6개 모델의 user FK를 `accounts.models.User`로 직접 교체
  (마이그레이션 `0004_alter_basicquestionresponse_user_and_more`). `taste/auth_temp.py` 삭제,
  taste 5개 뷰에 `accounts.authentication.JWTAccessAuthentication` +
  `rest_framework.permissions.IsAuthenticated` 적용, `request.user`로 사용자 조회하도록 전환
  (travel 앱과 동일 패턴). 테스트도 실제 `AccessToken.for_user()`로 발급한 JWT 기반으로 갱신.
- **완료**: #69, 2026-08-15

### [x] A/B·무드보드 사진 실물 파일 — 백엔드 접근 가능한 저장소 부재
- **임시로 한 것**: 사진 실물이 팀 구글 드라이브에만 있고 백엔드가 분석 가능한 저장소에는 없었음.
- **정식으로 교체한 것**: `taste/photo_catalog/{photo_id}.jpg`(66장, 리사이즈·재압축)와
  `taste/photo_catalog_manifest.py`(라운드→세트→photo_id 매핑) 추가.
- **완료**: #37, 2026-08-15

### [x] `open-clip-torch`(CLIP) 의존성 — Windows 긴 경로 제한으로 설치 보류
- **임시로 한 것**: `poetry add open-clip-torch` 시도 시 PyTorch 배포 파일 경로가 Windows 기본
  경로 길이 제한(260자)을 넘어 설치 실패(`[WinError 206]`).
- **정식으로 교체한 것**: Windows "긴 경로 이름 사용" 옵션 활성화 + 재부팅 후 재시도, 추가로
  `requires-python`을 `>=3.12,<3.13`으로 좁혀 `torchvision` 버전 충돌도 함께 해결.
  `open-clip-torch`, `torch`, `torchvision` 정상 설치·import 확인.
- **완료**: 2026-08-15 (별도 이슈 없이 진행, 다음 측정 함수 이슈의 선행 작업)
