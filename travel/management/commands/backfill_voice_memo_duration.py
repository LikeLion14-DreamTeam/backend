"""
duration_sec이 채워지지 않은(0으로 남아있는) 기존 VoiceMemo를 찾아, 실제 오디오 파일을
ffprobe로 분석해서 길이를 채우는 1회성 백필 커맨드.

VoiceMemo.duration_sec을 채워주는 코드가 없어 기존 레코드가 전부 0으로 저장돼 있던 문제
(docs/IMPLEMENTATION.md 2026-08-20 항목 참고)를 해결하기 위한 것 — 이후 등록되는 음성
메모는 POST /pins(8.2) 요청의 duration_sec 필드로 채워지므로, 이 커맨드는 그 이전에
만들어진 레코드만 대상으로 한다.

ffmpeg(ffprobe)가 설치된 환경에서 실행해야 한다. 배포 서버에 직접 설치하기보다, 별도
환경(로컬 또는 일회성 작업용 서버)에서 실제 DB에 접속해 돌리는 걸 권장한다 — #104 사진
백필 커맨드와 같은 이유.
"""

import subprocess
import tempfile
import time

import requests
from django.core.management.base import BaseCommand

from travel.models import VoiceMemo


class Command(BaseCommand):
    help = "duration_sec이 0인 기존 VoiceMemo를 실제 오디오 파일 분석으로 채운다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sleep", type=float, default=0.5,
            help="레코드 한 개 처리 후 대기 시간(초). 기본 0.5초.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="이번 실행에서 처리할 최대 개수(테스트용). 기본은 대상 전체.",
        )

    def handle(self, *args, **options):
        sleep_sec = options["sleep"]
        limit = options["limit"]

        queryset = VoiceMemo.objects.filter(duration_sec=0).order_by("voice_memo_id")
        if limit:
            queryset = queryset[:limit]
        voice_memos = list(queryset)
        total = len(voice_memos)
        self.stdout.write(f"백필 대상 {total}개")

        done = 0
        failed = 0
        for vm in voice_memos:
            try:
                duration = self._probe_duration(vm.audio_url)
            except Exception as exc:
                failed += 1
                self.stderr.write(f"[실패] voice_memo_id={vm.voice_memo_id} url={vm.audio_url} error={exc}")
                time.sleep(sleep_sec)
                continue

            vm.duration_sec = duration
            vm.save(update_fields=["duration_sec"])

            done += 1
            self.stdout.write(f"[{done}/{total}] voice_memo_id={vm.voice_memo_id} duration_sec={duration} 완료")
            time.sleep(sleep_sec)

        self.stdout.write(self.style.SUCCESS(f"백필 완료: 성공 {done}개, 실패 {failed}개"))

    def _probe_duration(self, audio_url):
        response = requests.get(audio_url, timeout=10)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".audio") as f:
            f.write(response.content)
            f.flush()

            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    f.name,
                ],
                capture_output=True, text=True, check=True,
            )

        return round(float(result.stdout.strip()))
