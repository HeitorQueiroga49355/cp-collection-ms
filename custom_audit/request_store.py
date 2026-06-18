from contextvars import ContextVar

# ContextVar é thread-safe e seguro também em contextos assíncronos — cada
# thread/corrotina tem seu próprio slot, então requisições concorrentes
# nunca sobrescrevem o contexto umas das outras.
_current_request: ContextVar = ContextVar('current_request', default=None)


def set_current_request(request) -> None:
    _current_request.set(request)


def get_current_request():
    """Retorna None quando não há requisição ativa (Celery, management commands, etc.)."""
    return _current_request.get()


def clear_current_request() -> None:
    _current_request.set(None)
