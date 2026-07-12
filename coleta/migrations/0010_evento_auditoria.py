from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coleta', '0009_imovel_proprietario_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventoAuditoria',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('origem', models.CharField(choices=[('api', 'API (mobile)'), ('fila_publish', 'Publicação em fila'), ('fila_consume', 'Consumo de fila'), ('management_command', 'Comando administrativo')], max_length=30)),
                ('nivel', models.CharField(choices=[('info', 'Info'), ('warning', 'Atenção'), ('error', 'Erro')], default='info', max_length=10)),
                ('evento', models.CharField(max_length=100)),
                ('coletor_id', models.CharField(blank=True, max_length=50, null=True)),
                ('coleta_offline_id', models.CharField(blank=True, max_length=50, null=True)),
                ('fila', models.CharField(blank=True, max_length=50, null=True)),
                ('detalhe', models.JSONField(blank=True, null=True)),
            ],
            options={
                'db_table': 'evento_auditoria',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='eventoauditoria',
            index=models.Index(fields=['timestamp'], name='evento_auditoria_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='eventoauditoria',
            index=models.Index(fields=['origem'], name='evento_auditoria_origem_idx'),
        ),
        migrations.AddIndex(
            model_name='eventoauditoria',
            index=models.Index(fields=['coletor_id'], name='evento_auditoria_coletor_idx'),
        ),
    ]
