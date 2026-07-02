from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0008_remover_lat_long_imovel'),
    ]

    operations = [
        migrations.AddField(
            model_name='imovel',
            name='proprietario_id',
            field=models.IntegerField(blank=True, db_index=True, null=True, verbose_name='ID do proprietário (core)'),
        ),
    ]
