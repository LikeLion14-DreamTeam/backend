from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth_temp import get_current_user
from .models import BasicQuestionResponse, OnboardingProgress, OnboardingStage
from .serializers import BasicQuestionResponseSerializer


@api_view(["POST"])
def submit_basic_question_response(request):
    serializer = BasicQuestionResponseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    round_no = serializer.validated_data["round_no"]
    answer = serializer.validated_data["answer"]

    user = get_current_user(request)
    progress, _ = OnboardingProgress.objects.get_or_create(user=user)

    if (
        progress.current_stage != OnboardingStage.BASIC_QUESTION
        or progress.current_round != round_no
    ):
        return Response(
            {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "현재 진행 중인 라운드가 아닙니다.",
                },
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    response_obj, _ = BasicQuestionResponse.objects.update_or_create(
        user=user, round_no=round_no, defaults={"answer": answer}
    )

    if round_no == 5:
        progress.current_stage = OnboardingStage.AB_SELECTION
        progress.current_round = 1
    else:
        progress.current_round += 1
    progress.save()

    return Response(BasicQuestionResponseSerializer(response_obj).data)
