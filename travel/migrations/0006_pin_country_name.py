# Generated manually on 2026-08-15 — 4.1(GET /trips) 응답에 여행 구간별 국가 목록을
# 내려주기 위해 Pin.country_name 추가. docs/IMPLEMENTATION.md 참고.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('travel', '0005_photo_taste_rank'),
    ]

    operations = [
        migrations.AddField(
            model_name='pin',
            name='country_name',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
    ]
