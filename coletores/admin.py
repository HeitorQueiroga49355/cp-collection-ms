from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Coletor


@admin.register(Coletor)
class ColetorAdmin(UserAdmin):
    list_display = ('username', 'nome', 'email', 'ativo', 'criado_em')
    search_fields = ('username', 'nome', 'email')
    list_filter = ('ativo', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Dados do Coletor', {'fields': ('nome', 'foto_perfil', 'ativo')}),
    )
