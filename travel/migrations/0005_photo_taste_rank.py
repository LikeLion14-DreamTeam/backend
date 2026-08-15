# Generated manually on 2026-08-15 — 핀 대표사진 선정을 Boolean(is_main)에서
# 순위 기반(taste_rank)으로 변경. docs/IMPLEMENTATION.md 참고.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('travel', '0004_travelsegment_dates_manually_set'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='photo',
            name='is_main',
        ),
        migrations.AddField(
            model_name='photo',
            name='taste_rank',
            field=models.IntegerField(null=True, blank=True),
        ),
    ]
