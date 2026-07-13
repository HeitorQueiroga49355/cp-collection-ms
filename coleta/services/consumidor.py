import json
import logging
import os

import django
import pika

from coleta.services.auditoria import registrar_evento

logger = logging.getLogger(__name__)

FILA_IMOVEIS = 'imoveis'


def _callback(canal, method, _properties, body):
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Mensagem inválida (não é JSON): {e} — descartando")
        registrar_evento(
            'fila_consume', 'mensagem_malformada',
            nivel='error',
            fila=FILA_IMOVEIS,
            detalhe={'body': body[:500].decode('utf-8', errors='replace')},
        )
        canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    if not payload.get('inscricao_imobiliaria'):
        logger.error(f"Mensagem sem 'inscricao_imobiliaria' — descartando: {payload}")
        registrar_evento(
            'fila_consume', 'mensagem_campo_ausente',
            nivel='warning',
            fila=FILA_IMOVEIS,
            detalhe=payload,
        )
        canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        from coleta.models import Imovel

        imovel, criado = Imovel.objects.upsert_from_evento(payload)
        acao_log = 'criado' if criado else 'atualizado'
        logger.info(
            f"Imóvel {acao_log}: id_externo={imovel.id_externo} "
            f"(acao={payload.get('acao', '-')})"
        )
        canal.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logger.error(
            f"Erro ao processar imóvel "
            f"(inscricao={payload.get('inscricao_imobiliaria')}): {e}"
        )
        registrar_evento(
            'fila_consume', 'mensagem_reenfileirada',
            nivel='warning',
            fila=FILA_IMOVEIS,
            detalhe={'erro': str(e), 'inscricao_imobiliaria': payload.get('inscricao_imobiliaria')},
        )
        canal.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def iniciar_consumidor():
    credentials = pika.PlainCredentials(
        username=os.getenv('RABBITMQ_DEFAULT_USER', 'guest'),
        password=os.getenv('RABBITMQ_DEFAULT_PASS', 'guest'),
    )
    parametros = pika.ConnectionParameters(
        host=os.getenv('RABBITMQ_HOST', 'rabbitmq'),
        port=int(os.getenv('RABBITMQ_PORT', 5672)),
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=300,
    )

    conexao = pika.BlockingConnection(parametros)
    canal = conexao.channel()

    canal.queue_declare(queue=FILA_IMOVEIS, durable=True)
    canal.basic_qos(prefetch_count=1)
    canal.basic_consume(queue=FILA_IMOVEIS, on_message_callback=_callback)

    logger.info(f"Aguardando mensagens na fila '{FILA_IMOVEIS}'...")
    canal.start_consuming()
