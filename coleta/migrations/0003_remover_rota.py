from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0002_remover_materialcoleta'),
    ]

    operations = [
        migrations.DeleteModel(
            name='RotaImovel',
        ),
        migrations.DeleteModel(
            name='Rota',
        ),
    ]
