from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0004_remover_pontos_gerados'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='coleta',
            name='gps_latitude',
        ),
        migrations.RemoveField(
            model_name='coleta',
            name='gps_longitude',
        ),
    ]
