import json
import logging
import os

import pika

logger = logging.getLogger(__name__)


def publicar_coleta(
    coleta_id: str,
    inscricao_imobiliaria: str,
    pontuacao: str,
    peso_total_kg: str,
    data_hora: str,
) -> bool:
    payload = {
        'coleta_id': coleta_id,
        'inscricao_imobiliaria': inscricao_imobiliaria,
        'pontuacao': pontuacao,
        'peso_total_kg': peso_total_kg,
        'data_hora': data_hora,
    }
    try:
        credentials = pika.PlainCredentials(
            username=os.getenv('RABBITMQ_DEFAULT_USER', 'guest'),
            password=os.getenv('RABBITMQ_DEFAULT_PASS', 'guest'),
        )
        parametros = pika.ConnectionParameters(
            host=os.getenv('RABBITMQ_HOST', 'rabbitmq'),
            port=int(os.getenv('RABBITMQ_PORT', 5672)),
            credentials=credentials,
        )

        conexao = pika.BlockingConnection(parametros)
        canal = conexao.channel()

        canal.queue_declare(queue='coletas', durable=True)

        canal.basic_publish(
            exchange='',
            routing_key='coletas',
            body=json.dumps(payload, default=str),
            properties=pika.BasicProperties(delivery_mode=2),
        )

        conexao.close()
        logger.info(f"Coleta publicada na fila: {payload}")
        return True

    except Exception as e:
        logger.error(f"Erro ao publicar coleta na fila: {e}")
        return False
