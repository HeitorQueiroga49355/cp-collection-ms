import json
import logging
import os

import pika

logger = logging.getLogger(__name__)


def publicar_pesagem(pesagem_data: dict) -> bool:
    try:
        credentials = pika.PlainCredentials(
            username=os.getenv('RABBITMQ_DEFAULT_USER', 'guest'),
            password=os.getenv('RABBITMQ_DEFAULT_PASS', 'guest'),
        )
        parametros = pika.ConnectionParameters(
            host='rabbitmq',
            port=5672,
            credentials=credentials,
        )

        conexao = pika.BlockingConnection(parametros)
        canal = conexao.channel()

        canal.queue_declare(queue='pesagens', durable=True)

        canal.basic_publish(
            exchange='',
            routing_key='pesagens',
            body=json.dumps(pesagem_data, default=str),
            properties=pika.BasicProperties(delivery_mode=2),
        )

        conexao.close()
        logger.info(f"Pesagem publicada na fila: {pesagem_data}")
        return True

    except Exception as e:
        logger.error(f"Erro ao publicar na fila: {e}")
        return False
