import re
import logging

from django.utils.deprecation import MiddlewareMixin

from .request_store import set_current_request, clear_current_request
from .models import AuditLog

logger = logging.getLogger(__name__)


# Mapeamento endpoint -> coleção auditada para operações SELECT (ver coleta/urls.py).
# Padrões de path literal (sem ID) vêm antes do padrão genérico de detalhe — caso
# contrário "historico"/"pendentes"/"buscar"/"proximos" seriam capturados como ID.
SELECT_ENDPOINT_MAP = [
    (re.compile(r'^/api/imoveis/buscar/?$'), 'imovel', None),
    (re.compile(r'^/api/imoveis/proximos/?$'), 'imovel', None),
    (re.compile(r'^/api/coletas/historico/?$'), 'coleta', None),
    (re.compile(r'^/api/coletas/pendentes/?$'), 'coleta', None),
    (re.compile(r'^/api/imoveis/(?P<doc_id>[^/]+)/?$'), 'imovel', 'doc_id'),
    (re.compile(r'^/api/coletas/(?P<doc_id>[^/]+)/?$'), 'coleta', 'doc_id'),
]


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _resolve_user(request):
    """
    Resolve o usuário autenticado da requisição.

    O middleware roda antes da autenticação do DRF, então `request.user`
    normalmente ainda não está populado — por isso decodifica o JWT manualmente
    como segunda tentativa.
    """
    user = getattr(request, 'user', None)
    if user and not getattr(user, 'is_anonymous', True):
        return user

    try:
        from rest_framework_simplejwt.authentication import JWTAuthentication
        auth_result = JWTAuthentication().authenticate(request)
        if auth_result:
            user, _ = auth_result
            return user
    except Exception:
        pass

    return None


def _get_usuario_matricula(user) -> str | None:
    if user is None:
        return None
    return (
        getattr(user, 'matricula', None)
        or getattr(user, 'username', None)
        or str(getattr(user, 'pk', ''))
        or None
    )


def _match_select_endpoint(path: str):
    """Retorna (colecao, documento_id) se o path corresponder a um endpoint
    auditável como SELECT, ou (None, None) caso contrário."""
    for pattern, colecao, group_name in SELECT_ENDPOINT_MAP:
        match = pattern.match(path)
        if match:
            documento_id = match.group(group_name) if group_name else None
            return colecao, documento_id
    return None, None


class CustomAuditMiddleware(MiddlewareMixin):
    """
    Ciclo de vida por requisição:
      1. Injeta `request` no contextvars -> disponível para os Django Signals.
      2. Processa a view normalmente (get_response).
      3. Se GET + 2xx + endpoint mapeado -> grava AuditLog com operacao='SELECT'.
      4. Limpa contextvars no bloco `finally` (garantido mesmo com exceções).
    """

    def __call__(self, request):
        set_current_request(request)
        try:
            response = self.get_response(request)
            self._handle_select_audit(request, response)
        except Exception:
            logger.exception(
                'CustomAuditMiddleware: erro inesperado no ciclo de request %s %s',
                request.method,
                request.path,
            )
            raise
        finally:
            clear_current_request()

        return response

    def _handle_select_audit(self, request, response) -> None:
        if request.method != 'GET':
            return

        status_code = getattr(response, 'status_code', 0)
        if not (200 <= status_code < 300):
            return

        colecao, documento_id = _match_select_endpoint(request.path)
        if colecao is None:
            return

        user = _resolve_user(request)

        try:
            AuditLog.objects.create(
                operacao=AuditLog.Operacao.SELECT,
                colecao=colecao,
                documento_id=documento_id,
                usuario_matricula=_get_usuario_matricula(user),
                ip_origem=_get_client_ip(request),
                endpoint=request.path,
                dados_antes=None,
                dados_depois=None,
            )
        except Exception:
            logger.exception(
                'CustomAuditMiddleware: falha ao gravar log SELECT para %s',
                request.path,
            )
