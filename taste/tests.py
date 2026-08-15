from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .axis_mapping import BASIC_QUESTION_AXIS_MAPPING
from .models import (
    AxisCode,
    BasicQuestionResponse,
    OnboardingProgress,
    ProfileRetrainHistory,
    SelectionPhoto,
    TasteProfile,
    TasteProfileAxis,
)
from .onboarding_completion import compute_and_save_taste_profile
from .photo_catalog_manifest import PHOTO_CATALOG_MANIFEST
from .photo_measurements import PHOTO_MEASUREMENTS

PHOTO_CATALOG_DIR = Path(__file__).resolve().parent / "photo_catalog"


class BasicQuestionAxisMappingTests(SimpleTestCase):
    def test_covers_all_five_rounds(self):
        self.assertEqual(set(BASIC_QUESTION_AXIS_MAPPING.keys()), {1, 2, 3, 4, 5})

    def test_covers_all_axis_codes_without_duplicates(self):
        axis_codes = [entry["axis_code"] for entry in BASIC_QUESTION_AXIS_MAPPING.values()]
        self.assertEqual(set(axis_codes), set(AxisCode.values))
        self.assertEqual(len(axis_codes), len(set(axis_codes)))

    def test_each_round_has_exactly_two_choices(self):
        for round_no, entry in BASIC_QUESTION_AXIS_MAPPING.items():
            with self.subTest(round_no=round_no):
                self.assertEqual(len(entry["choices"]), 2)

    def test_choice_values_within_range(self):
        for round_no, entry in BASIC_QUESTION_AXIS_MAPPING.items():
            for choice_text, value in entry["choices"].items():
                with self.subTest(round_no=round_no, choice=choice_text):
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, 100)

    def test_choice_values_are_distinct_within_round(self):
        for round_no, entry in BASIC_QUESTION_AXIS_MAPPING.items():
            with self.subTest(round_no=round_no):
                values = list(entry["choices"].values())
                self.assertEqual(len(values), len(set(values)))


class PhotoCatalogManifestTests(SimpleTestCase):
    def _all_photo_ids(self):
        photo_ids = []
        for entry in PHOTO_CATALOG_MANIFEST.values():
            for photo_set in entry["sets"]:
                photo_ids.extend(photo["photo_id"] for photo in photo_set["photos"])
        return photo_ids

    def test_covers_all_seven_rounds(self):
        self.assertEqual(set(PHOTO_CATALOG_MANIFEST.keys()), set(range(1, 8)))

    def test_ab_rounds_have_three_sets_of_two_photos(self):
        for round_no in range(1, 6):
            entry = PHOTO_CATALOG_MANIFEST[round_no]
            with self.subTest(round_no=round_no):
                self.assertEqual(len(entry["sets"]), 3)
                for photo_set in entry["sets"]:
                    self.assertEqual(len(photo_set["photos"]), 2)
                    values = {photo["value"] for photo in photo_set["photos"]}
                    self.assertEqual(values, {20, 80})

    def test_ab_round_axis_codes_match_model_choices(self):
        for round_no in range(1, 6):
            with self.subTest(round_no=round_no):
                self.assertIn(PHOTO_CATALOG_MANIFEST[round_no]["axis_code"], AxisCode.values)

    def test_moodboard_round1_has_one_fixed_set_of_nine(self):
        entry = PHOTO_CATALOG_MANIFEST[6]
        self.assertEqual(len(entry["sets"]), 1)
        self.assertEqual(len(entry["sets"][0]["photos"]), 9)

    def test_moodboard_round2_has_three_sets_of_nine(self):
        entry = PHOTO_CATALOG_MANIFEST[7]
        self.assertEqual(len(entry["sets"]), 3)
        for photo_set in entry["sets"]:
            self.assertEqual(len(photo_set["photos"]), 9)

    def test_no_duplicate_photo_ids(self):
        photo_ids = self._all_photo_ids()
        self.assertEqual(len(photo_ids), len(set(photo_ids)))

    def test_photo_catalog_directory_matches_manifest_exactly(self):
        manifest_ids = {f"{photo_id}.jpg" for photo_id in self._all_photo_ids()}
        actual_files = {
            path.name for path in PHOTO_CATALOG_DIR.iterdir() if path.suffix == ".jpg"
        }
        self.assertEqual(manifest_ids, actual_files)


class PhotoMeasurementsTests(SimpleTestCase):
    """
    photo_measurements.py는 precompute_photo_measurements 커맨드가 생성한 정적 데이터라,
    여기서는 CLIP/torch를 다시 돌리지 않고 저장된 값만 검증한다.
    """

    def _all_manifest_photo_ids(self):
        photo_ids = []
        for entry in PHOTO_CATALOG_MANIFEST.values():
            for photo_set in entry["sets"]:
                photo_ids.extend(photo["photo_id"] for photo in photo_set["photos"])
        return photo_ids

    def test_covers_every_catalog_photo(self):
        self.assertEqual(set(PHOTO_MEASUREMENTS.keys()), set(self._all_manifest_photo_ids()))

    def test_every_photo_has_all_five_axes_within_range(self):
        for photo_id, values in PHOTO_MEASUREMENTS.items():
            with self.subTest(photo_id=photo_id):
                self.assertEqual(set(values.keys()), set(AxisCode.values))
                for axis_code, value in values.items():
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, 100)

    def test_ab_reference_direction_matches_curated_value(self):
        """A/B 라운드(1~5)에서, 기획 참조값이 80인 사진들의 평균 측정값이 20인 사진들의
        평균보다 실제로 높은지 축별로 검증한다 (절대값 일치가 아니라 방향성만 검증)."""
        for round_no in range(1, 6):
            entry = PHOTO_CATALOG_MANIFEST[round_no]
            axis_code = entry["axis_code"]
            low_values, high_values = [], []
            for photo_set in entry["sets"]:
                for photo in photo_set["photos"]:
                    measured = PHOTO_MEASUREMENTS[photo["photo_id"]][axis_code]
                    (low_values if photo["value"] == 20 else high_values).append(measured)

            with self.subTest(round_no=round_no, axis_code=axis_code):
                self.assertGreater(sum(high_values) / len(high_values), sum(low_values) / len(low_values))


class OnboardingCompletionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="onboarding_completion_test_user")

    def _answer_basic_questions(self, pick_high):
        for round_no, entry in BASIC_QUESTION_AXIS_MAPPING.items():
            choices = entry["choices"]
            answer = max(choices, key=choices.get) if pick_high else min(choices, key=choices.get)
            BasicQuestionResponse.objects.create(user=self.user, round_no=round_no, answer=answer)

    def _answer_ab_rounds(self, pick_high):
        for round_no in range(1, 6):
            for photo_set in PHOTO_CATALOG_MANIFEST[round_no]["sets"]:
                for photo in photo_set["photos"]:
                    is_selected = (photo["value"] == 80) == pick_high
                    SelectionPhoto.objects.create(
                        user=self.user, round_no=round_no, photo_id=photo["photo_id"], status=is_selected
                    )

    def _answer_moodboard(self, distance):
        mb1_photos = PHOTO_CATALOG_MANIFEST[6]["sets"][0]["photos"]
        chosen = {p["photo_id"] for p in mb1_photos if p["distance"] == distance}
        for photo in mb1_photos:
            SelectionPhoto.objects.create(
                user=self.user, round_no=6, photo_id=photo["photo_id"], status=photo["photo_id"] in chosen
            )

        mb2_photos = PHOTO_CATALOG_MANIFEST[7]["sets"][0]["photos"]
        for i, photo in enumerate(mb2_photos):
            SelectionPhoto.objects.create(
                user=self.user, round_no=7, photo_id=photo["photo_id"], status=(i < 3)
            )

    def test_high_answers_produce_high_axis_values(self):
        self._answer_basic_questions(pick_high=True)
        self._answer_ab_rounds(pick_high=True)
        self._answer_moodboard(distance="가까이")

        compute_and_save_taste_profile(self.user)

        axes = {a.axis_code: a.value for a in TasteProfileAxis.objects.filter(user=self.user)}
        self.assertEqual(set(axes.keys()), set(AxisCode.values))
        for axis_code, value in axes.items():
            with self.subTest(axis_code=axis_code):
                self.assertGreater(value, 50)

        profile = TasteProfile.objects.get(user=self.user)
        self.assertIn("가까이", profile.taste)
        self.assertIn("정면", profile.taste)

    def test_low_answers_produce_low_axis_values(self):
        self._answer_basic_questions(pick_high=False)
        self._answer_ab_rounds(pick_high=False)
        self._answer_moodboard(distance="멀리")

        compute_and_save_taste_profile(self.user)

        axes = {a.axis_code: a.value for a in TasteProfileAxis.objects.filter(user=self.user)}
        for axis_code, value in axes.items():
            with self.subTest(axis_code=axis_code):
                self.assertLess(value, 50)


class ListTasteProfileAxesViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="list_axes_test_user")

    def test_no_profile_returns_null_last_updated_at_and_empty_axes(self):
        response = self.client.get(f"/users/me/taste-profile/axes?user_id={self.user.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"last_updated_at": None, "axes": []})

    def test_existing_profile_returns_last_updated_at(self):
        TasteProfileAxis.objects.create(user=self.user, axis_code="brightness", value=60)
        TasteProfile.objects.create(user=self.user, taste="")

        response = self.client.get(f"/users/me/taste-profile/axes?user_id={self.user.pk}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNotNone(body["last_updated_at"])
        self.assertEqual(len(body["axes"]), 1)


class UpdateTasteProfileAxisViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="axis_update_test_user")
        self.axis = TasteProfileAxis.objects.create(user=self.user, axis_code="brightness", value=50)
        TasteProfile.objects.create(user=self.user, taste="")
        self.url = "/users/me/taste-profile/axes/brightness"

    def test_valid_update_returns_reflected(self):
        response = self.client.put(
            self.url,
            data={"value": 70, "user_id": self.user.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "axis_code": "brightness",
            "user_id": self.user.pk,
            "value": 70,
            "status": "REFLECTED",
        })
        self.axis.refresh_from_db()
        self.assertEqual(self.axis.value, 70)

    def test_out_of_range_value_returns_400(self):
        response = self.client.put(
            self.url,
            data={"value": 150, "user_id": self.user.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_axis_returns_404(self):
        response = self.client.put(
            "/users/me/taste-profile/axes/vividness",
            data={"value": 70, "user_id": self.user.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_update_regenerates_taste_text(self):
        self.client.put(
            self.url,
            data={"value": 80, "user_id": self.user.pk},
            content_type="application/json",
        )
        profile = TasteProfile.objects.get(user=self.user)
        self.assertIn("밝은", profile.taste)


class RetrainFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="retrain_test_user")

    def _complete_onboarding(self, pick_high):
        for round_no, entry in BASIC_QUESTION_AXIS_MAPPING.items():
            choices = entry["choices"]
            answer = max(choices, key=choices.get) if pick_high else min(choices, key=choices.get)
            resp = self.client.post(
                "/users/me/basic-question-responses",
                data={"round_no": round_no, "response": answer, "user_id": self.user.pk},
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200, resp.content)

        for round_no in range(1, 6):
            # A/B는 라운드당 3세트 중 실제로는 1세트(2장)만 제시·제출된다.
            photo_set = PHOTO_CATALOG_MANIFEST[round_no]["sets"][0]
            for photo in photo_set["photos"]:
                is_selected = (photo["value"] == 80) == pick_high
                resp = self.client.post(
                    "/users/me/selection-photos",
                    data={
                        "photo_id": photo["photo_id"],
                        "round_no": round_no,
                        "status": is_selected,
                        "user_id": self.user.pk,
                    },
                    content_type="application/json",
                )
                self.assertEqual(resp.status_code, 200, resp.content)

        mb1_photos = PHOTO_CATALOG_MANIFEST[6]["sets"][0]["photos"]
        distance = "가까이" if pick_high else "멀리"
        chosen = {p["photo_id"] for p in mb1_photos if p["distance"] == distance}
        for photo in mb1_photos:
            resp = self.client.post(
                "/users/me/selection-photos",
                data={
                    "photo_id": photo["photo_id"],
                    "round_no": 6,
                    "status": photo["photo_id"] in chosen,
                    "user_id": self.user.pk,
                },
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200, resp.content)

        mb2_photos = PHOTO_CATALOG_MANIFEST[7]["sets"][0]["photos"]
        for i, photo in enumerate(mb2_photos):
            resp = self.client.post(
                "/users/me/selection-photos",
                data={
                    "photo_id": photo["photo_id"],
                    "round_no": 7,
                    "status": i < 3,
                    "user_id": self.user.pk,
                },
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200, resp.content)

    def test_retrain_replaces_profile(self):
        self._complete_onboarding(pick_high=True)
        first_axes = {a.axis_code: a.value for a in TasteProfileAxis.objects.filter(user=self.user)}
        self.assertTrue(all(v > 50 for v in first_axes.values()))

        self._complete_onboarding(pick_high=False)

        progress = OnboardingProgress.objects.get(user=self.user)
        self.assertEqual(progress.current_stage, "COMPLETED")
        self.assertFalse(progress.is_retrain)

        second_axes = {a.axis_code: a.value for a in TasteProfileAxis.objects.filter(user=self.user)}
        self.assertTrue(all(v < 50 for v in second_axes.values()))

        history = ProfileRetrainHistory.objects.get(user=self.user)
        self.assertIsNotNone(history.completed_at)
        self.assertGreaterEqual(history.completed_at, history.started_at)

    def test_in_progress_retrain_keeps_old_profile(self):
        self._complete_onboarding(pick_high=True)
        first_axes = {a.axis_code: a.value for a in TasteProfileAxis.objects.filter(user=self.user)}

        entry = BASIC_QUESTION_AXIS_MAPPING[1]
        low_answer = min(entry["choices"], key=entry["choices"].get)
        resp = self.client.post(
            "/users/me/basic-question-responses",
            data={"round_no": 1, "response": low_answer, "user_id": self.user.pk},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        progress = OnboardingProgress.objects.get(user=self.user)
        self.assertEqual(progress.current_stage, "BASIC_QUESTION")
        self.assertTrue(progress.is_retrain)

        current_axes = {a.axis_code: a.value for a in TasteProfileAxis.objects.filter(user=self.user)}
        self.assertEqual(current_axes, first_axes)
