import logging
import time

import pika
from django.core.management.base import BaseCommand

from coleta.services.auditoria import registrar_evento
from coleta.services.consumidor import iniciar_consumidor

logger = logging.getLogger(__name__)

ESPERA_RECONEXAO_SEGUNDOS = 5


class Command(BaseCommand):
    help = 'Inicia o consumidor RabbitMQ que recebe imóveis de outros sistemas.'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando consumidor de imóveis...')
        registrar_evento('management_command', 'consumidor_iniciado', fila='imoveis')

        while True:
            try:
                iniciar_consumidor()
            except pika.exceptions.AMQPConnectionError as e:
                logger.error(f"Conexão perdida com RabbitMQ: {e}. Reconectando em {ESPERA_RECONEXAO_SEGUNDOS}s...")
                registrar_evento(
                    'fila_consume', 'consumidor_reconectado',
                    nivel='warning',
                    fila='imoveis',
                )
                time.sleep(ESPERA_RECONEXAO_SEGUNDOS)
            except KeyboardInterrupt:
                self.stdout.write('Consumidor encerrado.')
                registrar_evento('management_command', 'consumidor_parado', fila='imoveis')
                break
