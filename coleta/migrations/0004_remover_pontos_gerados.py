from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0003_remover_rota'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='coleta',
            name='pontos_gerados',
        ),
    ]
