from pathlib import Path

from django.test import SimpleTestCase

from .axis_mapping import BASIC_QUESTION_AXIS_MAPPING
from .models import AxisCode
from .photo_catalog_manifest import PHOTO_CATALOG_MANIFEST

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
