from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('travel', '0004_travelsegment_dates_manually_set'),
    ]

    operations = [
        migrations.CreateModel(
            name='Photobook',
            fields=[
                ('photobook_id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100)),
                ('cover_photo_url', models.CharField(blank=True, max_length=500, null=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('segment', models.OneToOneField(db_column='segment_id', on_delete=django.db.models.deletion.CASCADE, related_name='photobook', to='travel.travelsegment')),
            ],
            options={
                'db_table': 'photobook',
            },
        ),
    ]
