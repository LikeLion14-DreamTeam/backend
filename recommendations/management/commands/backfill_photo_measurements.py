"""
기존 Photo 중 measured_* 캐시가 없는 것들을 찾아 한 장씩 계산해서 채우는 백필 커맨드 (#104).

한 번에 몰아서 처리하면 서버(특히 메모리가 빠듯한 배포 환경)에 부하가 몰릴 수 있어, 사진
한 장 처리할 때마다 즉시 저장하고(중단돼도 이어서 재실행 가능하도록) 사이에 짧게 쉰다.

배포 서버에서 직접 돌리기보다, 로컬/별도 환경에서 실제 DB·S3에 접속해서 돌리는 걸 권장한다
(무거운 CV 연산 자체를 배포 서버가 짊어지지 않도록) — docs/IMPLEMENTATION.md 참고.
"""

import time

from django.core.management.base import BaseCommand

from taste.photo_measurement import measure_all_axes
from travel.models import Photo

from ...travel_adapter import _download_image

_MEASURED_UPDATE_FIELDS = [
    "measured_brightness", "measured_vividness", "measured_tone",
    "measured_density", "measured_photo_type",
]


class Command(BaseCommand):
    help = "measured_* 캐시가 없는 기존 Photo를 찾아 실측값을 계산해서 채운다 (#104)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sleep", type=float, default=0.5,
            help="사진 한 장 처리 후 대기 시간(초). 기본 0.5초.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="이번 실행에서 처리할 최대 개수(테스트용). 기본은 대상 전체.",
        )

    def handle(self, *args, **options):
        sleep_sec = options["sleep"]
        limit = options["limit"]

        queryset = Photo.objects.filter(measured_brightness__isnull=True).order_by("photo_id")
        if limit:
            queryset = queryset[:limit]
        photos = list(queryset)
        total = len(photos)
        self.stdout.write(f"백필 대상 {total}장")

        done = 0
        failed = 0
        for photo in photos:
            try:
                image = _download_image(photo.photo_url)
                measured = measure_all_axes(image)
            except Exception as exc:
                failed += 1
                self.stderr.write(f"[실패] photo_id={photo.photo_id} url={photo.photo_url} error={exc}")
                time.sleep(sleep_sec)
                continue

            photo.measured_brightness = measured["brightness"]
            photo.measured_vividness = measured["vividness"]
            photo.measured_tone = measured["tone"]
            photo.measured_density = measured["density"]
            photo.measured_photo_type = measured["photo_type"]
            photo.save(update_fields=_MEASURED_UPDATE_FIELDS)

            done += 1
            self.stdout.write(f"[{done}/{total}] photo_id={photo.photo_id} 완료")
            time.sleep(sleep_sec)

        self.stdout.write(self.style.SUCCESS(f"백필 완료: 성공 {done}장, 실패 {failed}장"))
