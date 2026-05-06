from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Coletor, Coleta, Imovel, MaterialColeta, Parada, Rota


# ─── Coletor ──────────────────────────────────────────────────────────────────

@admin.register(Coletor)
class ColetorAdmin(UserAdmin):
    list_display = ('username', 'nome', 'email', 'ativo', 'criado_em')
    search_fields = ('username', 'nome', 'email')
    list_filter = ('ativo', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Dados do Coletor', {'fields': ('nome', 'foto_perfil', 'ativo')}),
    )


# ─── Imóvel ───────────────────────────────────────────────────────────────────

@admin.register(Imovel)
class ImovelAdmin(admin.ModelAdmin):
    list_display = ('iptu', 'logradouro', 'numero', 'bairro', 'morador', 'elegivel', 'ativo', 'sincronizado_em')
    search_fields = ('iptu', 'id_externo', 'logradouro', 'bairro', 'morador')
    list_filter = ('elegivel', 'ativo')


# ─── Rota ─────────────────────────────────────────────────────────────────────

@admin.register(Rota)
class RotaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'coletor', 'data', 'status', 'total_imoveis', 'imoveis_visitados')
    search_fields = ('nome', 'coletor__nome', 'coletor__username')
    list_filter = ('status', 'data')


# ─── Parada ───────────────────────────────────────────────────────────────────

@admin.register(Parada)
class ParadaAdmin(admin.ModelAdmin):
    list_display = ('rota', 'imovel', 'ordem', 'status', 'atualizado_em')
    search_fields = ('rota__nome', 'imovel__iptu', 'imovel__logradouro')
    list_filter = ('status',)


# ─── Coleta ───────────────────────────────────────────────────────────────────

class MaterialColetaInline(admin.TabularInline):
    model = MaterialColeta
    extra = 0
    fields = ('categoria', 'peso_kg')


@admin.register(Coleta)
class ColetaAdmin(admin.ModelAdmin):
    list_display = (
        'coleta_id', 'coletor', 'imovel', 'data_hora',
        'peso_total_kg', 'pontos_gerados', 'origem', 'sincronizado_core',
    )
    search_fields = ('coleta_id', 'coletor__nome', 'coletor__username', 'imovel__iptu')
    list_filter = ('origem', 'sincronizado_core')
    readonly_fields = ('coleta_id', 'criado_em')
    inlines = [MaterialColetaInline]


# ─── Material de Coleta ───────────────────────────────────────────────────────

@admin.register(MaterialColeta)
class MaterialColetaAdmin(admin.ModelAdmin):
    list_display = ('coleta', 'categoria', 'peso_kg')
    search_fields = ('coleta__coleta_id', 'categoria')
    list_filter = ('categoria',)
