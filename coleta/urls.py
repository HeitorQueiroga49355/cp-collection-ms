from django.urls import path

from .views import (
    ColetaCreateView,
    ColetaDetailView,
    ColetaHistoricoView,
    ColetasMoradorView,
    ColetaPendentesView,
    ImovelBuscarView,
    ImovelDetailView,
    ImovelProximosView,
    SincronizacaoStatusView,
    SincronizarView,
    ImovelSupervisorListView,
    ColetaSupervisorListView,
)

urlpatterns = [
    path('imoveis/buscar', ImovelBuscarView.as_view(), name='imovel-buscar'),
    path('imoveis/proximos', ImovelProximosView.as_view(), name='imovel-proximos'),
    path('imoveis/<str:pk>', ImovelDetailView.as_view(), name='imovel-detail'),

    path('coletas/morador', ColetasMoradorView.as_view(), name='coletas-morador'),
    path('coletas/historico', ColetaHistoricoView.as_view(), name='coleta-historico'),
    path('coletas/pendentes', ColetaPendentesView.as_view(), name='coleta-pendentes'),
    path('coletas/<str:pk>', ColetaDetailView.as_view(), name='coleta-detail'),
    path('coletas', ColetaCreateView.as_view(), name='coleta-create'),

    path('supervisor/imoveis', ImovelSupervisorListView.as_view(), name='imovel-supervisor-list'),
    path('supervisor/coletas', ColetaSupervisorListView.as_view(), name='coleta-supervisor-list'),

    path('sincronizar', SincronizarView.as_view(), name='sincronizar'),
    path('sincronizacao/status', SincronizacaoStatusView.as_view(), name='sincronizacao-status'),
]
