import logging

logger = logging.getLogger(__name__)


def registrar_evento(origem, evento, *, nivel='info', coletor_id=None, coleta_offline_id=None, fila=None, detalhe=None):
    from coleta.models import EventoAuditoria
    try:
        EventoAuditoria.objects.create(
            origem=origem,
            evento=evento,
            nivel=nivel,
            coletor_id=coletor_id,
            coleta_offline_id=coleta_offline_id,
            fila=fila,
            detalhe=detalhe,
        )
    except Exception:
        logger.exception('Falha ao registrar evento de auditoria: %s', evento)
