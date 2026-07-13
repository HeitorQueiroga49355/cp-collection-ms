from django.db import migrations


def create_2dsphere_index(apps, schema_editor):
    from django.db import connections
    collection = connections['default'].get_collection('coleta_imovel')
    collection.create_index([('location', '2dsphere')], sparse=True)


def drop_2dsphere_index(apps, schema_editor):
    from django.db import connections
    collection = connections['default'].get_collection('coleta_imovel')
    collection.drop_index('location_2dsphere')


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0010_evento_auditoria'),
    ]

    operations = [
        migrations.RunPython(create_2dsphere_index, drop_2dsphere_index),
    ]
