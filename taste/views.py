from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .auth_temp import get_current_user
from .models import (
    AxisCode,
    AxisStatus,
    BasicQuestionResponse,
    OnboardingProgress,
    OnboardingStage,
    ProfileRetrainHistory,
    SelectionPhoto,
    TasteProfileAxis,
)
from .onboarding_completion import compute_and_save_taste_profile, regenerate_taste_text
from .serializers import (
    BasicQuestionResponseSerializer,
    SelectionPhotoSerializer,
    TasteProfileAxisSerializer,
    TasteProfileAxisUpdateSerializer,
)

AXIS_CODE_ORDER = [choice.value for choice in AxisCode]

# SelectionPhoto.round_no: 1~5 = A/B, 6~7 = 무드보드 (연속 번호)
AB_ROUND_NUMBERS = range(1, 6)
MOODBOARD_ROUND_NUMBERS = range(6, 8)


def _validation_error(message):
    return Response(
        {"success": False, "error": {"code": "VALIDATION_ERROR", "message": message}},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _start_retrain(progress):
    """온보딩 완료 상태에서 1라운드가 다시 제출되면 재학습 시작으로 간주한다.
    별도의 "재학습 시작" 엔드포인트는 두지 않고 2.1(기본 질문 제출)을 그대로 재사용한다.

    이전 온보딩의 BasicQuestionResponse/SelectionPhoto를 지우고 시작한다 — 지우지 않으면
    이전 라운드의 행이 그대로 남아있어 라운드 완료 판정(행 개수 세기)이 재학습 중 첫 제출만으로
    "이미 다 찼다"고 잘못 판단하는 문제가 있다."""
    progress.current_stage = OnboardingStage.BASIC_QUESTION
    progress.current_round = 1
    progress.is_retrain = True
    progress.completed_at = None
    BasicQuestionResponse.objects.filter(user=progress.user).delete()
    SelectionPhoto.objects.filter(user=progress.user).delete()
    ProfileRetrainHistory.objects.create(user=progress.user, started_at=timezone.now())


@api_view(["POST"])
def submit_basic_question_response(request):
    serializer = BasicQuestionResponseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    round_no = serializer.validated_data["round_no"]
    answer = serializer.validated_data["answer"]

    user = get_current_user(request)
    progress, _ = OnboardingProgress.objects.get_or_create(user=user)

    if progress.current_stage == OnboardingStage.COMPLETED and round_no == 1:
        _start_retrain(progress)
    elif (
        progress.current_stage != OnboardingStage.BASIC_QUESTION
        or progress.current_round != round_no
    ):
        return _validation_error("현재 진행 중인 라운드가 아닙니다.")

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


def _progress_round_no(progress):
    """OnboardingProgress의 단계 내 라운드 번호를 SelectionPhoto.round_no(1~7)로 변환."""
    if progress.current_stage == OnboardingStage.AB_SELECTION:
        return progress.current_round
    if progress.current_stage == OnboardingStage.MOODBOARD:
        return progress.current_round + 5
    return None


def _expected_counts(round_no):
    """(라운드당 기대 제출 수, 그중 status=True 기대 수)."""
    if round_no in AB_ROUND_NUMBERS:
        return 2, 1
    return 9, 3


def _advance_progress(progress):
    if progress.current_stage == OnboardingStage.AB_SELECTION:
        if progress.current_round == 5:
            progress.current_stage = OnboardingStage.MOODBOARD
            progress.current_round = 1
        else:
            progress.current_round += 1
    elif progress.current_stage == OnboardingStage.MOODBOARD:
        if progress.current_round == 2:
            progress.current_stage = OnboardingStage.COMPLETED
            progress.current_round = 1
            progress.completed_at = timezone.now()
            if progress.is_retrain:
                history = ProfileRetrainHistory.objects.filter(
                    user=progress.user, completed_at__isnull=True
                ).order_by("-started_at").first()
                if history is not None:
                    history.completed_at = timezone.now()
                    history.save()
                progress.is_retrain = False
            compute_and_save_taste_profile(progress.user)
        else:
            progress.current_round += 1
    progress.save()


@api_view(["POST"])
def submit_selection_photo(request):
    serializer = SelectionPhotoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    round_no = serializer.validated_data["round_no"]
    photo_id = serializer.validated_data["photo_id"]
    is_selected = serializer.validated_data["status"]

    user = get_current_user(request)
    progress, _ = OnboardingProgress.objects.get_or_create(user=user)

    expected_round_no = _progress_round_no(progress)
    if (
        progress.current_stage not in (OnboardingStage.AB_SELECTION, OnboardingStage.MOODBOARD)
        or round_no != expected_round_no
    ):
        return _validation_error("현재 진행 중인 라운드가 아닙니다.")

    photo_obj, _ = SelectionPhoto.objects.update_or_create(
        user=user, round_no=round_no, photo_id=photo_id, defaults={"status": is_selected}
    )

    total_expected, true_expected = _expected_counts(round_no)
    round_photos = SelectionPhoto.objects.filter(user=user, round_no=round_no)
    if round_photos.count() >= total_expected:
        true_count = round_photos.filter(status=True).count()
        if true_count != true_expected:
            return _validation_error(
                f"선택한 사진 수가 올바르지 않습니다 ({true_count}/{true_expected})."
            )
        _advance_progress(progress)

    return Response(SelectionPhotoSerializer(photo_obj).data)


@api_view(["GET"])
def list_taste_profile_axes(request):
    user = get_current_user(request)
    axes = TasteProfileAxis.objects.filter(user=user)
    axes = sorted(axes, key=lambda axis: AXIS_CODE_ORDER.index(axis.axis_code))
    return Response({"axes": TasteProfileAxisSerializer(axes, many=True).data})


@api_view(["PUT"])
def update_taste_profile_axis(request, axis_code):
    user = get_current_user(request)
    axis = get_object_or_404(TasteProfileAxis, user=user, axis_code=axis_code)

    serializer = TasteProfileAxisUpdateSerializer(axis, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save(status=AxisStatus.REFLECTED)

    regenerate_taste_text(user)

    return Response(TasteProfileAxisUpdateSerializer(axis).data)
