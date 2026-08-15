# Generated manually on 2026-08-15 — 4.3 여행 구간 날짜 직접 수정 기능 (PM 결정,
# docs/IMPLEMENTATION.md 참고).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('travel', '0003_voicememo_duration_sec'),
    ]

    operations = [
        migrations.AddField(
            model_name='travelsegment',
            name='dates_manually_set',
            field=models.BooleanField(default=False),
        ),
    ]
