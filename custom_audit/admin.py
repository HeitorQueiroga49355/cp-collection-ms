from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'operacao', 'colecao', 'documento_id', 'usuario_matricula', 'ip_origem', 'endpoint')
    list_filter = ('operacao', 'colecao')
    search_fields = ('usuario_matricula', 'documento_id', 'endpoint')
    ordering = ('-timestamp',)
    readonly_fields = (
        'timestamp', 'usuario_matricula', 'operacao', 'colecao',
        'documento_id', 'dados_antes', 'dados_depois', 'ip_origem', 'endpoint',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
