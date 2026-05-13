from django.urls import path

from .views import (
    ColetaCreateView,
    ColetaDetailView,
    ColetaHistoricoView,
    ColetaPendentesView,
    ImovelBuscarView,
    ImovelDetailView,
    MateriaisView,
    RotaHojeView,
    RotaParadasView,
    SincronizacaoStatusView,
    SincronizarView,
)

urlpatterns = [
    path('rotas/hoje', RotaHojeView.as_view(), name='rota-hoje'),
    path('rotas/<str:pk>/paradas', RotaParadasView.as_view(), name='rota-paradas'),

    path('imoveis/buscar', ImovelBuscarView.as_view(), name='imovel-buscar'),
    path('imoveis/<str:pk>', ImovelDetailView.as_view(), name='imovel-detail'),

    path('coletas/historico', ColetaHistoricoView.as_view(), name='coleta-historico'),
    path('coletas/pendentes', ColetaPendentesView.as_view(), name='coleta-pendentes'),
    path('coletas/<str:pk>', ColetaDetailView.as_view(), name='coleta-detail'),
    path('coletas', ColetaCreateView.as_view(), name='coleta-create'),

    path('sincronizar', SincronizarView.as_view(), name='sincronizar'),
    path('sincronizacao/status', SincronizacaoStatusView.as_view(), name='sincronizacao-status'),
]
