from django.core.management.base import BaseCommand

from coleta.models import Coleta
from coleta.services.auditoria import registrar_evento
from coleta.services.fila import publicar_coleta


class Command(BaseCommand):
    help = 'Reenvia para a fila RabbitMQ as coletas que ainda não foram sincronizadas.'

    def handle(self, *args, **options):
        pendentes = Coleta.objects.filter(sincronizado_core=False)
        total = pendentes.count()

        if not total:
            self.stdout.write('Nenhuma coleta pendente.')
            return

        enviadas = 0
        falhas = 0
        for coleta in pendentes.select_related('imovel'):
            try:
                enviado = publicar_coleta(
                    coleta_id=str(coleta.coleta_id),
                    inscricao_imobiliaria=coleta.imovel.id_externo,
                    peso_total_kg=str(coleta.peso_total_kg),
                    data_hora=coleta.data_hora.isoformat(),
                )
                coleta.tentativas_sincronizacao += 1
                coleta.sincronizado_core = enviado
                coleta.erro_ultima_tentativa = '' if enviado else 'Falha ao publicar na fila RabbitMQ'
                coleta.save(update_fields=['sincronizado_core', 'tentativas_sincronizacao', 'erro_ultima_tentativa'])

                if enviado:
                    enviadas += 1
                else:
                    falhas += 1
            except Exception as exc:
                falhas += 1
                registrar_evento(
                    'management_command', 'reenvio_item_falhou',
                    nivel='error',
                    coleta_offline_id=str(coleta.offline_id) if coleta.offline_id else None,
                    detalhe={'erro': str(exc), 'coleta_id': str(coleta.coleta_id)},
                )

        registrar_evento(
            'management_command', 'reenvio_lote_executado',
            detalhe={'total_reenviado': enviadas, 'total_falhas': falhas},
        )
        self.stdout.write(f'Enviadas: {enviadas}/{total}')
