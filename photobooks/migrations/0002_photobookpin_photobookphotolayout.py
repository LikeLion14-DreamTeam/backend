# Generated manually on 2026-08-15 — 포토북 도시별 핀 선정(PhotobookPin) +
# 핀별 대표사진 선정(PhotobookPhotoLayout) 신규. docs/IMPLEMENTATION.md 참고.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('photobooks', '0001_initial'),
        ('travel', '0005_photo_taste_rank'),
    ]

    operations = [
        migrations.CreateModel(
            name='PhotobookPin',
            fields=[
                ('photobook_pin_id', models.AutoField(primary_key=True, serialize=False)),
                ('order', models.IntegerField()),
                ('photobook', models.ForeignKey(db_column='photobook_id', on_delete=django.db.models.deletion.CASCADE, related_name='photobook_pins', to='photobooks.photobook')),
                ('pin', models.ForeignKey(db_column='pin_id', on_delete=django.db.models.deletion.CASCADE, related_name='photobook_pins', to='travel.pin')),
            ],
            options={
                'db_table': 'photobook_pin',
                'ordering': ['order'],
                'unique_together': {('photobook', 'pin')},
            },
        ),
        migrations.CreateModel(
            name='PhotobookPhotoLayout',
            fields=[
                ('layout_id', models.AutoField(primary_key=True, serialize=False)),
                ('order', models.IntegerField()),
                ('photo', models.ForeignKey(db_column='photo_id', on_delete=django.db.models.deletion.CASCADE, related_name='photobook_layouts', to='travel.photo')),
                ('photobook_pin', models.ForeignKey(db_column='photobook_pin_id', on_delete=django.db.models.deletion.CASCADE, related_name='photo_layouts', to='photobooks.photobookpin')),
            ],
            options={
                'db_table': 'photobook_photo_layout',
                'ordering': ['order'],
                'unique_together': {('photobook_pin', 'photo')},
            },
        ),
    ]
