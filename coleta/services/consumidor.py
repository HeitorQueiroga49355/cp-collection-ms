import json
import logging
import os

import django
import pika

logger = logging.getLogger(__name__)

FILA_IMOVEIS = 'imoveis'


def _callback(canal, method, _properties, body):
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Mensagem inválida (não é JSON): {e} — descartando")
        canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    if 'iptu' not in payload:
        logger.error(f"Mensagem sem campo 'iptu' — descartando: {payload}")
        canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        from coleta.models import Imovel

        imovel, criado = Imovel.objects.upsert_from_evento(payload)
        acao = 'criado' if criado else 'atualizado'
        logger.info(f"Imóvel {acao}: IPTU={imovel.iptu}")
        canal.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        logger.error(f"Erro ao processar imóvel (iptu={payload.get('iptu')}): {e}")
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
