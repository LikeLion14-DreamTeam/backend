"""
taste 사진 카탈로그(taste/photo_catalog/)의 축 실측값을 미리 계산해 taste/photo_measurements.py에
정적 데이터로 저장하는 개발자용 1회성 커맨드.

카탈로그 사진이 추가/교체될 때만 수동으로 재실행한다. 런타임 요청 경로에서는 호출되지 않는다.
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from taste.photo_catalog_manifest import PHOTO_CATALOG_MANIFEST
from taste.photo_measurement import load_image, measure_all_axes

CATALOG_DIR = Path(__file__).resolve().parent.parent.parent / "photo_catalog"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "photo_measurements.py"

HEADER = '''"""
taste/photo_catalog/ 사진들의 축별 실측값(0~100) 사전계산 결과.

`python manage.py precompute_photo_measurements`로 자동 생성된다 — 직접 수정하지 말 것.
카탈로그 사진이 바뀌면 이 커맨드를 다시 실행해서 갱신한다.
"""

PHOTO_MEASUREMENTS = '''


class Command(BaseCommand):
    help = "taste 사진 카탈로그의 축 실측값을 계산해 photo_measurements.py로 저장한다."

    def handle(self, *args, **options):
        photo_ids = []
        for entry in PHOTO_CATALOG_MANIFEST.values():
            for photo_set in entry["sets"]:
                photo_ids.extend(photo["photo_id"] for photo in photo_set["photos"])

        measurements = {}
        for photo_id in sorted(photo_ids):
            path = CATALOG_DIR / f"{photo_id}.jpg"
            image = load_image(path)
            measurements[photo_id] = measure_all_axes(image)
            self.stdout.write(f"{photo_id}: {measurements[photo_id]}")

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(HEADER)
            f.write("{\n")
            for photo_id, values in measurements.items():
                rounded = {axis: round(v, 2) for axis, v in values.items()}
                f.write(f"    {photo_id}: {rounded!r},\n")
            f.write("}\n")

        self.stdout.write(self.style.SUCCESS(f"{len(measurements)}개 photo_id 사전계산 완료 → {OUTPUT_PATH}"))
