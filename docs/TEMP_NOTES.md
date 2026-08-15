# TEMP_NOTES.md

## 목적

이 문서는 정식 구현 전까지 **임시로 대체해둔 부분**만 모아두는 살아있는 체크리스트입니다.
"왜 이렇게 정했는지"는 `docs/IMPLEMENTATION.md` 결정 로그에 남기고, 이 문서에는
"아직 임시 상태인 것 / 무엇으로 교체해야 하는지 / 완료 조건"만 짧게 관리합니다.

항목이 실제로 정식 구현으로 교체되면 체크박스를 채우고, 완료 커밋 해시와 날짜를 남긴 뒤
아래 "완료된 항목" 섹션으로 옮깁니다 (삭제하지 않음 — 나중에 "언제 뭘 왜 치웠는지" 추적용).

---

## 진행 중인 임시 조치

### [ ] `taste/auth_temp.py` — 임시 인증
- **임시로 한 것**: accounts 앱의 구글 로그인(JWT)이 아직 없어서, 요청 바디(`user_id`) 또는
  쿼리 파라미터(`?user_id=`)로 사용자를 조회하는 `get_current_user(request)` 헬퍼로 대체.
- **정식으로 교체할 조건**: accounts 앱에 구글 OAuth + JWT 인증이 완성되면, 이 함수 내부만
  `request.user`를 반환하도록 교체 (호출부 코드 변경 불필요하도록 설계됨).
- **관련 이슈/커밋**: #28 (`taste/auth_temp.py` 최초 도입)

### [ ] `open-clip-torch`(CLIP) 의존성 — Windows 긴 경로 제한으로 설치 보류
- **임시로 한 것**: `poetry add open-clip-torch` 시도 시 PyTorch 배포 파일 중 하나의 경로가
  Windows 기본 경로 길이 제한(260자)을 넘어 설치 실패(`[WinError 206]`). `opencv-python`,
  `pillow`만 우선 추가된 상태.
- **정식으로 교체할 조건**: Windows "긴 경로 이름 사용" 옵션을 관리자 권한으로 켜고(레지스트리
  `HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled=1`) 재부팅한 뒤 재시도.
- **관련 이슈/커밋**: #37 (사진 카탈로그 작업 중 발견, 실제 CLIP 사용은 AI 실측 파이프라인
  이슈에서 진행)

---

## 완료된 항목

### [x] A/B·무드보드 사진 실물 파일 — 백엔드 접근 가능한 저장소 부재
- **임시로 한 것**: 사진 실물이 팀 구글 드라이브에만 있고 백엔드가 분석 가능한 저장소에는 없었음.
- **정식으로 교체한 것**: `taste/photo_catalog/{photo_id}.jpg`(66장, 리사이즈·재압축)와
  `taste/photo_catalog_manifest.py`(라운드→세트→photo_id 매핑) 추가.
- **완료**: #37, 2026-08-15
