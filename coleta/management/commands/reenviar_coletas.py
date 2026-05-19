from django.core.management.base import BaseCommand

from coleta.models import Coleta
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
        for coleta in pendentes.select_related('imovel'):
            enviado = publicar_coleta(
                coleta_id=str(coleta.coleta_id),
                inscricao_imobiliaria=coleta.imovel.id_externo,
                pontuacao=str(coleta.pontos_gerados),
                peso_total_kg=str(coleta.peso_total_kg),
                data_hora=coleta.data_hora.isoformat(),
            )
            coleta.tentativas_sincronizacao += 1
            coleta.sincronizado_core = enviado
            coleta.erro_ultima_tentativa = '' if enviado else 'Falha ao publicar na fila RabbitMQ'
            coleta.save(update_fields=['sincronizado_core', 'tentativas_sincronizacao', 'erro_ultima_tentativa'])

            if enviado:
                enviadas += 1

        self.stdout.write(f'Enviadas: {enviadas}/{total}')
