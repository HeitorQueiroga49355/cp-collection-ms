from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    class Operacao(models.TextChoices):
        INSERT = 'INSERT', 'Insert'
        UPDATE = 'UPDATE', 'Update'
        DELETE = 'DELETE', 'Delete'
        SELECT = 'SELECT', 'Select'

    timestamp = models.DateTimeField('timestamp', default=timezone.now)
    usuario_matricula = models.CharField('matrícula do usuário', max_length=50, null=True, blank=True)
    operacao = models.CharField('operação', max_length=10, choices=Operacao.choices)
    colecao = models.CharField('coleção', max_length=100)
    documento_id = models.CharField('ID do documento', max_length=255, null=True, blank=True)
    dados_antes = models.JSONField('dados antes', null=True, blank=True)
    dados_depois = models.JSONField('dados depois', null=True, blank=True)
    ip_origem = models.CharField('IP de origem', max_length=50, null=True, blank=True)
    endpoint = models.CharField('endpoint', max_length=500, null=True, blank=True)

    class Meta:
        # Índices (incluindo o TTL) são geridos via `manage.py ensure_audit_indexes`,
        # não aqui — `expireAfterSeconds` não é expressável em models.Index.
        db_table = 'audit_logs'
        verbose_name = 'log de auditoria'
        verbose_name_plural = 'logs de auditoria'
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.operacao}] {self.colecao}#{self.documento_id} by {self.usuario_matricula} at {self.timestamp}"
