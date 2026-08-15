from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404


def get_current_user(request):
    """
    임시 인증 헬퍼. accounts 앱의 구글 로그인(JWT) 완성 전까지, 요청 바디 또는
    쿼리 파라미터의 user_id로 사용자를 조회한다 (GET은 body가 없어 쿼리 파라미터 사용).
    accounts 인증이 완성되면 이 함수 내부만 request.user를 반환하도록 교체하면
    된다 (호출부 코드 변경 불필요).
    """
    user_id = request.data.get("user_id") or request.query_params.get("user_id")
    return get_object_or_404(get_user_model(), pk=user_id)
