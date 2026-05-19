from django.contrib import admin

from .models import Coleta, Imovel


@admin.register(Imovel)
class ImovelAdmin(admin.ModelAdmin):
    list_display = ('iptu', 'logradouro', 'numero', 'bairro', 'morador', 'elegivel', 'ativo', 'sincronizado_em')
    search_fields = ('iptu', 'id_externo', 'logradouro', 'bairro', 'morador')
    list_filter = ('elegivel', 'ativo')


@admin.register(Coleta)
class ColetaAdmin(admin.ModelAdmin):
    list_display = ('coleta_id', 'coletor', 'imovel', 'data_hora', 'peso_total_kg', 'sincronizado_core')
    search_fields = ('coleta_id', 'coletor__nome', 'coletor__username', 'imovel__iptu')
    list_filter = ('sincronizado_core',)
    readonly_fields = ('coleta_id', 'criado_em')
