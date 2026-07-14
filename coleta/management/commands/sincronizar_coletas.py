from django.core.management.base import BaseCommand

from coleta.models import Coleta
from coleta.services.auditoria import registrar_evento
from coleta.services.fila import publicar_coleta


class Command(BaseCommand):
    help = (
        'Publica coletas na fila RabbitMQ para sincronização com o Core. '
        'Por padrão envia apenas as não sincronizadas. '
        'Use --todos para incluir as já sincronizadas (o Core ignora duplicatas via id_microservico).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--todos',
            action='store_true',
            default=False,
            help='Republica todas as coletas, incluindo as já sincronizadas com o Core.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Apenas lista o que seria enviado, sem publicar na fila.',
        )

    def handle(self, *args, **options):
        todos = options['todos']
        dry_run = options['dry_run']

        qs = Coleta.objects.select_related('imovel')
        if not todos:
            qs = qs.filter(sincronizado_core=False)

        total = qs.count()

        if not total:
            self.stdout.write(self.style.SUCCESS('Nenhuma coleta para sincronizar.'))
            return

        modo = 'TODAS' if todos else 'apenas não sincronizadas'
        sufixo = ' [DRY-RUN]' if dry_run else ''
        self.stdout.write(f'Sincronizando {total} coleta(s) ({modo}){sufixo}...')

        enviadas = 0
        falhas = 0

        for coleta in qs:
            if dry_run:
                self.stdout.write(
                    f'  [dry-run] {coleta.coleta_id} | '
                    f'imóvel={coleta.imovel.id_externo} | '
                    f'sync={coleta.sincronizado_core}'
                )
                enviadas += 1
                continue

            try:
                ok = publicar_coleta(
                    coleta_id=str(coleta.coleta_id),
                    inscricao_imobiliaria=coleta.imovel.id_externo,
                    peso_total_kg=str(coleta.peso_total_kg),
                    data_hora=coleta.data_hora.isoformat(),
                    foto_url=str(coleta.foto_url) if coleta.foto_url else '',
                )
                coleta.tentativas_sincronizacao += 1

                if ok:
                    coleta.sincronizado_core = True
                    coleta.erro_ultima_tentativa = ''
                    enviadas += 1
                else:
                    coleta.erro_ultima_tentativa = 'Falha ao publicar na fila RabbitMQ'
                    falhas += 1

                coleta.save(update_fields=[
                    'sincronizado_core',
                    'tentativas_sincronizacao',
                    'erro_ultima_tentativa',
                ])
            except Exception as exc:
                falhas += 1
                registrar_evento(
                    'management_command', 'sincronizacao_item_falhou',
                    nivel='error',
                    coleta_offline_id=str(coleta.offline_id) if coleta.offline_id else None,
                    detalhe={'erro': str(exc), 'coleta_id': str(coleta.coleta_id)},
                )

        if not dry_run:
            registrar_evento(
                'management_command', 'sincronizacao_lote_executado',
                detalhe={
                    'total': total,
                    'enviadas': enviadas,
                    'falhas': falhas,
                    'modo': 'todos' if todos else 'pendentes',
                },
            )

        self.stdout.write(
            self.style.SUCCESS(f'Enviadas: {enviadas}/{total}')
            if not falhas
            else self.style.WARNING(f'Enviadas: {enviadas}/{total} | Falhas: {falhas}')
        )
