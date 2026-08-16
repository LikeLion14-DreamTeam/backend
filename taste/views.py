from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import JWTAccessAuthentication

from .models import (
    AxisCode,
    AxisStatus,
    BasicQuestionResponse,
    OnboardingProgress,
    OnboardingStage,
    ProfileRetrainHistory,
    SelectionPhoto,
    TasteProfile,
    TasteProfileAxis,
)
from .onboarding_completion import compute_and_save_taste_profile, regenerate_taste_text
from .serializers import (
    BasicQuestionResponseSerializer,
    OnboardingProgressSerializer,
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
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def submit_basic_question_response(request):
    serializer = BasicQuestionResponseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    round_no = serializer.validated_data["round_no"]
    answer = serializer.validated_data["answer"]

    user = request.user
    progress, _ = OnboardingProgress.objects.get_or_create(user=user)

    is_current_round = (
        progress.current_stage == OnboardingStage.BASIC_QUESTION
        and progress.current_round == round_no
    )
    is_past_round = (
        progress.current_stage == OnboardingStage.BASIC_QUESTION
        and round_no < progress.current_round
    ) or progress.current_stage in (OnboardingStage.AB_SELECTION, OnboardingStage.MOODBOARD)

    if progress.current_stage == OnboardingStage.COMPLETED and round_no == 1:
        _start_retrain(progress)
        is_current_round = True
    elif not (is_current_round or is_past_round):
        return _validation_error("현재 진행 중인 라운드가 아닙니다.")

    response_obj, _ = BasicQuestionResponse.objects.update_or_create(
        user=user, round_no=round_no, defaults={"answer": answer}
    )

    if is_current_round:
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
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def submit_selection_photo(request):
    serializer = SelectionPhotoSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    round_no = serializer.validated_data["round_no"]
    photo_id = serializer.validated_data["photo_id"]
    is_selected = serializer.validated_data["status"]

    user = request.user
    progress, _ = OnboardingProgress.objects.get_or_create(user=user)

    expected_round_no = _progress_round_no(progress)
    if expected_round_no is None or round_no > expected_round_no:
        return _validation_error("현재 진행 중인 라운드가 아닙니다.")

    photo_obj, created = SelectionPhoto.objects.update_or_create(
        user=user, round_no=round_no, photo_id=photo_id, defaults={"status": is_selected}
    )

    # 이미 존재하는 행(=지난 라운드에서 이미 제출된 사진)의 status만 덮어쓰는 경우엔 개수
    # 정합성 재검증·라운드 전진을 건너뛴다. 검증을 매번 다시 돌리면, 이미 다 찬 라운드에서
    # 선택을 바꾸려고 두 번 나눠 제출할 때 그 중간 상태가 일시적으로 정합성 조건을 깨서
    # 정상적인 편집 흐름이 400으로 막힌다.
    if created:
        total_expected, true_expected = _expected_counts(round_no)
        round_photos = SelectionPhoto.objects.filter(user=user, round_no=round_no)
        if round_photos.count() >= total_expected:
            true_count = round_photos.filter(status=True).count()
            if true_count != true_expected:
                return _validation_error(
                    f"선택한 사진 수가 올바르지 않습니다 ({true_count}/{true_expected})."
                )
            if round_no == expected_round_no:
                _advance_progress(progress)

    return Response(SelectionPhotoSerializer(photo_obj).data)


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def get_onboarding_progress(request):
    user = request.user
    progress, _ = OnboardingProgress.objects.get_or_create(user=user)
    return Response(OnboardingProgressSerializer(progress).data)


@api_view(["GET"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def list_taste_profile_axes(request):
    user = request.user
    axes = TasteProfileAxis.objects.filter(user=user)
    axes = sorted(axes, key=lambda axis: AXIS_CODE_ORDER.index(axis.axis_code))

    profile = TasteProfile.objects.filter(user=user).first()
    last_updated_at = profile.last_updated_at if profile else None

    return Response({
        "last_updated_at": last_updated_at,
        "axes": TasteProfileAxisSerializer(axes, many=True).data,
    })


@api_view(["PUT"])
@authentication_classes([JWTAccessAuthentication])
@permission_classes([IsAuthenticated])
def update_taste_profile_axis(request, axis_code):
    user = request.user
    axis = get_object_or_404(TasteProfileAxis, user=user, axis_code=axis_code)

    serializer = TasteProfileAxisUpdateSerializer(axis, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save(status=AxisStatus.REFLECTED)

    regenerate_taste_text(user)

    return Response(TasteProfileAxisUpdateSerializer(axis).data)
