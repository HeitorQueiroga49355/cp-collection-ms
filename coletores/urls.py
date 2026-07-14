from django.urls import path

from .views import GestaoColetorDetalheView, GestaoColetoresView, LoginView, LogoutView, MeView, RegisterView

urlpatterns = [
    path('auth/register', RegisterView.as_view(), name='auth-register'),
    path('auth/login', LoginView.as_view(), name='auth-login'),
    path('auth/logout', LogoutView.as_view(), name='auth-logout'),
    path('me', MeView.as_view(), name='me'),
    path('gestao/coletores', GestaoColetoresView.as_view(), name='gestao-coletores'),
    path('gestao/coletores/<str:pk>', GestaoColetorDetalheView.as_view(), name='gestao-coletor-detalhe'),
]
