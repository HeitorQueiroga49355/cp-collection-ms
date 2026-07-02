from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0005_remover_gps_coleta'),
    ]

    operations = [
        migrations.AddField(
            model_name='imovel',
            name='latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, verbose_name='latitude'),
        ),
        migrations.AddField(
            model_name='imovel',
            name='longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, verbose_name='longitude'),
        ),
    ]
