from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(
            name='MaterialColeta',
        ),
    ]
