from django.core.management.base import BaseCommand
from django.db import connections

from custom_audit.models import AuditLog


class Command(BaseCommand):
    help = (
        'Garante que todos os índices da coleção `audit_logs` existam no MongoDB, '
        'incluindo o índice TTL de 90 dias para limpeza automática.'
    )

    TTL_90_DAYS = 7776000  # 90 * 24 * 3600 segundos

    def handle(self, *args, **options):
        colecao = connections['default'].get_collection(AuditLog._meta.db_table)

        colecao.create_index('timestamp', expireAfterSeconds=self.TTL_90_DAYS, name='audit_ttl_90d')
        self.stdout.write(self.style.SUCCESS('Índice TTL (90 dias) em `timestamp` garantido.'))

        colecao.create_index('usuario_matricula', name='idx_usuario_matricula')
        self.stdout.write(self.style.SUCCESS('Índice em `usuario_matricula` garantido.'))

        colecao.create_index('colecao', name='idx_colecao')
        self.stdout.write(self.style.SUCCESS('Índice em `colecao` garantido.'))

        colecao.create_index('operacao', name='idx_operacao')
        self.stdout.write(self.style.SUCCESS('Índice em `operacao` garantido.'))

        colecao.create_index([('colecao', 1), ('timestamp', -1)], name='idx_colecao_timestamp')
        self.stdout.write(self.style.SUCCESS('Índice composto `colecao + timestamp` garantido.'))

        self.stdout.write(self.style.SUCCESS('Todos os índices de audit_logs verificados/criados com sucesso.'))
