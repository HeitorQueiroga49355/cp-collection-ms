import json
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import post_delete, post_save, pre_save

from coleta.models import Coleta, Imovel
from .models import AuditLog
from .request_store import get_current_request

logger = logging.getLogger(__name__)

AUDITED_MODELS = [Coleta, Imovel]


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------

def _serialize_instance(instance) -> dict:
    """
    Serializa os campos concretos (`_meta.fields`) de uma instância para dict —
    ignora relações reversas (evita N+1 e recursão) e nunca usa `__dict__`
    (inclui estado interno do Django) nem `values()` (perde o nome do campo de FK).
    """
    data = {}
    for field in instance._meta.fields:
        if field.many_to_many or field.one_to_many:
            continue
        try:
            value = field.value_from_object(instance)
            # Roundtrip JSON garante que o valor é 100% JSON-safe (ex: ObjectId
            # de FKs no backend Mongo cai no except e é convertido para string).
            data[field.name] = json.loads(json.dumps(value, cls=DjangoJSONEncoder))
        except Exception:
            data[field.name] = str(field.value_from_object(instance))
    return data


def _get_colecao_name(instance) -> str:
    return instance._meta.model_name


def _get_request_context() -> dict:
    request = get_current_request()
    if request is None:
        return {'ip_origem': None, 'endpoint': None, 'usuario_matricula': None}

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = (
        x_forwarded_for.split(',')[0].strip()
        if x_forwarded_for
        else request.META.get('REMOTE_ADDR', '')
    )

    user = getattr(request, 'user', None)
    matricula = None
    if user and not getattr(user, 'is_anonymous', True):
        matricula = (
            getattr(user, 'matricula', None)
            or getattr(user, 'username', None)
            or str(getattr(user, 'pk', ''))
            or None
        )

    return {
        'ip_origem': ip or None,
        'endpoint': getattr(request, 'path', None),
        'usuario_matricula': matricula,
    }


def _save_audit_log(operacao: str, instance, dados_antes: dict | None = None, dados_depois: dict | None = None) -> None:
    """Nunca lança exceção para o chamador — falha de auditoria não pode derrubar a operação principal."""
    ctx = _get_request_context()
    try:
        AuditLog.objects.create(
            operacao=operacao,
            colecao=_get_colecao_name(instance),
            documento_id=str(instance.pk) if instance.pk else None,
            dados_antes=dados_antes,
            dados_depois=dados_depois,
            ip_origem=ctx['ip_origem'],
            endpoint=ctx['endpoint'],
            usuario_matricula=ctx['usuario_matricula'],
        )
    except Exception:
        logger.exception(
            'custom_audit._save_audit_log: falha ao gravar [%s] para %s#%s',
            operacao,
            _get_colecao_name(instance),
            instance.pk,
        )


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------

def _pre_save_handler(sender, instance, **kwargs):
    """
    Guarda o estado anterior em `instance._audit_dados_antes` antes do save —
    depois do save o estado antigo já foi sobrescrito no banco, então não há
    como recuperá-lo a partir do post_save.
    """
    instance._audit_dados_antes = None

    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            instance._audit_dados_antes = _serialize_instance(old_instance)
        except sender.DoesNotExist:
            pass
        except Exception:
            logger.exception(
                'custom_audit.pre_save: falha ao buscar estado anterior de %s#%s',
                sender.__name__,
                instance.pk,
            )


def _post_save_handler(sender, instance, created, **kwargs):
    operacao = AuditLog.Operacao.INSERT if created else AuditLog.Operacao.UPDATE
    dados_antes = getattr(instance, '_audit_dados_antes', None)
    dados_depois = _serialize_instance(instance)
    _save_audit_log(operacao, instance, dados_antes=dados_antes, dados_depois=dados_depois)


def _post_delete_handler(sender, instance, **kwargs):
    dados_antes = _serialize_instance(instance)
    _save_audit_log(AuditLog.Operacao.DELETE, instance, dados_antes=dados_antes, dados_depois=None)


def connect_audit_signals():
    """
    Chamado uma única vez por `CustomAuditConfig.ready()`. `dispatch_uid` único
    por (signal, model) evita handlers duplicados (ex: auto-reloader em DEBUG).
    """
    for model in AUDITED_MODELS:
        model_name = model.__name__.lower()

        pre_save.connect(_pre_save_handler, sender=model, dispatch_uid=f'custom_audit_pre_save_{model_name}')
        post_save.connect(_post_save_handler, sender=model, dispatch_uid=f'custom_audit_post_save_{model_name}')
        post_delete.connect(_post_delete_handler, sender=model, dispatch_uid=f'custom_audit_post_delete_{model_name}')

        logger.info(
            "custom_audit: signals (pre_save, post_save, post_delete) conectados para o model '%s'.",
            model.__name__,
        )


# ---------------------------------------------------------------------------
# Helpers para operações bulk que pulam pre_save/post_save: bulk_create() e
# queryset.update() do ORM Django não disparam signals. queryset.delete() NÃO
# precisa de helper — o Collector do Django já emite post_delete por objeto
# (inclusive em deleções em cascata), então _post_delete_handler já cobre esse
# caso; criar um helper para ele duplicaria o log.
# ---------------------------------------------------------------------------

def bulk_create_with_audit(model_class, instances: list, **bulk_kwargs) -> list:
    created = model_class.objects.bulk_create(instances, **bulk_kwargs)
    for instance in created:
        _save_audit_log(AuditLog.Operacao.INSERT, instance, dados_antes=None, dados_depois=_serialize_instance(instance))
    return created


def queryset_update_with_audit(queryset, **update_kwargs) -> int:
    """Carrega todos os objetos afetados em memória — para querysets muito
    grandes (milhares+), processar em chunks."""
    affected = list(queryset)
    estados_antes = {obj.pk: _serialize_instance(obj) for obj in affected}

    count = queryset.update(**update_kwargs)

    for obj in queryset.model.objects.filter(pk__in=estados_antes.keys()):
        _save_audit_log(
            AuditLog.Operacao.UPDATE,
            obj,
            dados_antes=estados_antes.get(obj.pk),
            dados_depois=_serialize_instance(obj),
        )

    return count
