# uploads 앱은 DB 모델을 두지 않는다.
#
# 파일 업로드 상태(발급~업로드 완료~소모)는 django.core.signing으로 서명된 토큰과
# 로컬 디스크 파일 존재 여부로만 관리한다 — docs/IMPLEMENTATION.md 2026-08-14
# "uploads: 토큰 기반, 신규 테이블 없음" 결정 참고. 실제 로직은 uploads/tokens.py.
