from django.apps import AppConfig


class CustomAuditConfig(AppConfig):
    name = 'custom_audit'
    verbose_name = 'Auditoria Customizada'

    def ready(self):
        from .signals import connect_audit_signals
        connect_audit_signals()
