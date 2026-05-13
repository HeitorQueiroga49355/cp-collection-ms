import random
import string
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Coleta, Imovel, MaterialColeta, Rota, RotaImovel
from .serializers import (
    ColetaDetailSerializer,
    ColetaHistoricoItemSerializer,
    ColetaInputSerializer,
    ColetaOutputSerializer,
    ImovelBuscarSerializer,
    ImovelDetailSerializer,
    RotaImovelSerializer,
)


def _hoje():
    return timezone.localdate()


def _gerar_codigo():
    letras = ''.join(random.choices(string.ascii_uppercase, k=4))
    numeros = ''.join(random.choices(string.digits, k=4))
    return f"{letras}-{numeros}"


def _calcular_pontos(materiais_data):
    taxas = MaterialColeta.TAXA_PONTUACAO
    return sum(Decimal(str(m['peso_kg'])) * Decimal(str(taxas.get(m['tipo'], 1.0))) for m in materiais_data)


# ─── Rotas ────────────────────────────────────────────────────────────────────

class RotaHojeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rota = Rota.objects.filter(coletor=request.user, data=_hoje()).first()
        if not rota:
            return Response({'error': 'Nenhuma rota para hoje'}, status=status.HTTP_404_NOT_FOUND)

        coletas_hoje = Coleta.objects.filter(coletor=request.user, data_hora__date=_hoje())
        total_kg = sum(c.peso_total_kg for c in coletas_hoje)
        total_pontos = sum(c.pontos_gerados for c in coletas_hoje)

        imoveis_coletados = rota.paradas.filter(status=RotaImovel.Status.COLETADO).count()
        imoveis_recusados = rota.paradas.filter(status=RotaImovel.Status.RECUSADO).count()
        imoveis_pendentes = rota.paradas.filter(status=RotaImovel.Status.PENDENTE).count()
        imoveis_fora_fila = rota.total_imoveis - imoveis_coletados - imoveis_recusados - imoveis_pendentes

        proximo_imovel = None
        proxima_parada = rota.paradas.filter(status=RotaImovel.Status.PENDENTE).order_by('sequencia').first()
        if proxima_parada:
            imovel = proxima_parada.imovel
            proximo_imovel = {
                'id': str(imovel.id),
                'numero_iptu': imovel.iptu,
                'endereco': f"{imovel.logradouro}, {imovel.numero}",
                'bairro': imovel.bairro,
                'distancia_metros': proxima_parada.distancia_metros,
            }

        hora_encerro = None
        if rota.hora_prevista_encerro:
            hora_encerro = rota.hora_prevista_encerro.strftime('%H:%M')

        return Response({
            'id': str(rota.id),
            'codigo': rota.codigo,
            'zona': rota.zona,
            'total_imoveis': rota.total_imoveis,
            'imoveis_coletados': imoveis_coletados,
            'imoveis_recusados': imoveis_recusados,
            'imoveis_fora_fila': max(imoveis_fora_fila, 0),
            'total_kg': float(total_kg),
            'total_pontos': float(total_pontos),
            'hora_prevista_encerro': hora_encerro,
            'tempo_restante_minutos': None,
            'proximo_imovel': proximo_imovel,
        })


class RotaParadasView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            rota = Rota.objects.get(pk=pk, coletor=request.user)
        except Rota.DoesNotExist:
            return Response({'error': 'Rota não encontrada'}, status=status.HTTP_404_NOT_FOUND)

        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 20))
        offset = (page - 1) * limit

        paradas_qs = rota.paradas.select_related('imovel')
        total = paradas_qs.count()
        paradas = paradas_qs[offset:offset + limit]

        serializer = RotaImovelSerializer(paradas, many=True)
        return Response({
            'paradas': serializer.data,
            'total': total,
            'page': page,
            'total_pages': max(1, -(-total // limit)),
        })


# ─── Imóveis ──────────────────────────────────────────────────────────────────

class ImovelBuscarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo = request.query_params.get('tipo')
        valor = request.query_params.get('valor', '').strip()
        rota_id = request.query_params.get('rota_id')

        if not tipo or not valor:
            return Response({'error': 'Parâmetros tipo e valor são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        qs = Imovel.objects.filter(ativo=True)

        if rota_id:
            qs = qs.filter(paradas__rota_id=rota_id)

        if tipo == 'numero':
            qs = qs.filter(iptu=valor)
        elif tipo == 'qrcode':
            qs = qs.filter(id_externo=valor)
        elif tipo == 'endereco':
            qs = qs.filter(logradouro__icontains=valor)
        else:
            return Response({'error': 'Tipo de busca inválido'}, status=status.HTTP_400_BAD_REQUEST)

        imovel = qs.first()
        if not imovel:
            return Response({'error': 'Imóvel não encontrado'}, status=status.HTTP_404_NOT_FOUND)

        return Response(ImovelBuscarSerializer(imovel).data)


class ImovelDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            imovel = Imovel.objects.get(pk=pk, ativo=True)
        except Imovel.DoesNotExist:
            return Response({'error': 'Imóvel não encontrado'}, status=status.HTTP_404_NOT_FOUND)

        return Response(ImovelDetailSerializer(imovel).data)


# ─── Coletas ──────────────────────────────────────────────────────────────────

class ColetaCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ColetaInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        offline_id = data.get('offline_id')

        if offline_id:
            coleta_existente = Coleta.objects.filter(offline_id=offline_id).first()
            if coleta_existente:
                return Response(ColetaOutputSerializer(coleta_existente).data, status=status.HTTP_201_CREATED)

        try:
            imovel = Imovel.objects.get(pk=data['imovel_id'], ativo=True)
        except Imovel.DoesNotExist:
            return Response({'error': 'Imóvel não encontrado', 'field': 'imovel_id'}, status=status.HTTP_400_BAD_REQUEST)

        if not imovel.elegivel:
            return Response(
                {'error': 'Imóvel não elegível para participar', 'field': 'imovel_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        materiais_data = data['materiais']
        peso_total = sum(Decimal(str(m['peso_kg'])) for m in materiais_data)
        pontos = _calcular_pontos(materiais_data)
        gps = data.get('gps')

        with transaction.atomic():
            coleta = Coleta.objects.create(
                coletor=request.user,
                imovel=imovel,
                data_hora=data['data_hora'],
                peso_total_kg=peso_total,
                pontos_gerados=pontos,
                foto_url=data.get('foto_url') or '',
                gps_latitude=gps['latitude'] if gps else None,
                gps_longitude=gps['longitude'] if gps else None,
                status=Coleta.Status.CONFIRMADA,
                observacoes=data.get('observacoes') or '',
                offline_id=offline_id,
                codigo=_gerar_codigo(),
                sincronizado_core=False,
            )

            for m in materiais_data:
                MaterialColeta.objects.create(
                    coleta=coleta,
                    tipo=m['tipo'],
                    peso_kg=m['peso_kg'],
                )

            parada = RotaImovel.objects.filter(
                rota__coletor=request.user,
                rota__data=_hoje(),
                imovel=imovel,
            ).first()
            if parada:
                parada.status = RotaImovel.Status.COLETADO
                parada.save(update_fields=['status'])

        return Response(ColetaOutputSerializer(coleta).data, status=status.HTTP_201_CREATED)


class ColetaHistoricoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo_periodo = request.query_params.get('tipo_periodo', 'hoje')
        data_param = request.query_params.get('data')
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 30))

        hoje = _hoje()
        qs = Coleta.objects.filter(coletor=request.user).prefetch_related('materiais').select_related('imovel')

        if data_param:
            qs = qs.filter(data_hora__date=data_param)
        elif tipo_periodo == 'hoje':
            qs = qs.filter(data_hora__date=hoje)
        elif tipo_periodo == 'ontem':
            from datetime import timedelta
            qs = qs.filter(data_hora__date=hoje - timedelta(days=1))
        elif tipo_periodo == 'semana':
            from datetime import timedelta
            qs = qs.filter(data_hora__date__gte=hoje - timedelta(days=7))
        elif tipo_periodo == 'mes':
            qs = qs.filter(data_hora__year=hoje.year, data_hora__month=hoje.month)

        total_coletas = qs.count()
        total_kg = sum(c.peso_total_kg for c in qs)
        total_pontos = sum(c.pontos_gerados for c in qs)

        offset = (page - 1) * limit
        coletas_pagina = qs[offset:offset + limit]

        return Response({
            'coletas': ColetaHistoricoItemSerializer(coletas_pagina, many=True).data,
            'resumo': {
                'total_coletas': total_coletas,
                'total_kg': float(total_kg),
                'total_pontos': float(total_pontos),
            },
            'page': page,
            'total_pages': max(1, -(-total_coletas // limit)),
        })


class ColetaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            coleta = Coleta.objects.select_related('imovel', 'coletor').prefetch_related('materiais').get(
                pk=pk, coletor=request.user
            )
        except Coleta.DoesNotExist:
            return Response({'error': 'Coleta não encontrada'}, status=status.HTTP_404_NOT_FOUND)

        return Response(ColetaDetailSerializer(coleta).data)


class ColetaPendentesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pendentes = Coleta.objects.filter(coletor=request.user, sincronizado_core=False)
        resultado = [
            {
                'offline_id': str(c.offline_id) if c.offline_id else None,
                'id': str(c.id),
                'imovel_id': str(c.imovel_id),
                'materiais': list(c.materiais.values('tipo', 'peso_kg')),
                'data_hora': c.data_hora.isoformat(),
                'sincronizado': c.sincronizado_core,
                'tentativas_sincronizacao': c.tentativas_sincronizacao,
                'erro_ultima_tentativa': c.erro_ultima_tentativa or None,
            }
            for c in pendentes.prefetch_related('materiais')
        ]
        return Response({'pendentes': resultado, 'total': len(resultado)})


# ─── Sincronização ────────────────────────────────────────────────────────────

class SincronizarView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        coletas_data = request.data.get('coletas', [])
        resultados = []
        sincronizadas = 0
        erros = 0

        for item in coletas_data:
            offline_id = item.get('offline_id')
            try:
                coleta_existente = Coleta.objects.filter(offline_id=offline_id).first() if offline_id else None
                if coleta_existente:
                    resultados.append({
                        'offline_id': offline_id,
                        'sucesso': True,
                        'coleta_id': str(coleta_existente.id),
                        'erro': None,
                    })
                    sincronizadas += 1
                    continue

                imovel = Imovel.objects.get(pk=item['imovel_id'], ativo=True)
                if not imovel.elegivel:
                    raise ValueError('Imóvel não elegível para participar')

                materiais_data = item.get('materiais', [])
                peso_total = sum(Decimal(str(m['peso_kg'])) for m in materiais_data)
                pontos = _calcular_pontos(materiais_data)
                gps = item.get('gps')

                with transaction.atomic():
                    coleta = Coleta.objects.create(
                        coletor=request.user,
                        imovel=imovel,
                        data_hora=item['data_hora'],
                        peso_total_kg=peso_total,
                        pontos_gerados=pontos,
                        foto_url=item.get('foto_url') or '',
                        gps_latitude=gps['latitude'] if gps else None,
                        gps_longitude=gps['longitude'] if gps else None,
                        status=Coleta.Status.CONFIRMADA,
                        offline_id=offline_id,
                        codigo=_gerar_codigo(),
                        sincronizado_core=False,
                    )
                    for m in materiais_data:
                        MaterialColeta.objects.create(coleta=coleta, tipo=m['tipo'], peso_kg=m['peso_kg'])

                resultados.append({
                    'offline_id': offline_id,
                    'sucesso': True,
                    'coleta_id': str(coleta.id),
                    'erro': None,
                })
                sincronizadas += 1

            except Exception as exc:
                resultados.append({
                    'offline_id': offline_id,
                    'sucesso': False,
                    'coleta_id': None,
                    'erro': str(exc),
                })
                erros += 1

        resp_status = status.HTTP_200_OK if erros == 0 else status.HTTP_207_MULTI_STATUS
        return Response({
            'sincronizadas': sincronizadas,
            'erros': erros,
            'resultados': resultados,
        }, status=resp_status)


class SincronizacaoStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pendentes_qs = Coleta.objects.filter(coletor=request.user, sincronizado_core=False)
        sincronizadas_hoje = Coleta.objects.filter(
            coletor=request.user,
            sincronizado_core=True,
            data_hora__date=_hoje(),
        ).count()

        ultima = Coleta.objects.filter(
            coletor=request.user,
            sincronizado_core=True,
        ).order_by('-criado_em').first()

        detalhes = [
            {
                'offline_id': str(c.offline_id) if c.offline_id else None,
                'imovel': f"{c.imovel.logradouro}, {c.imovel.numero}",
                'status': 'pendente',
                'tentativas': c.tentativas_sincronizacao,
                'erro': c.erro_ultima_tentativa or None,
            }
            for c in pendentes_qs.select_related('imovel')
        ]

        return Response({
            'pendentes': pendentes_qs.count(),
            'sincronizadas_hoje': sincronizadas_hoje,
            'ultima_sincronizacao': ultima.criado_em.isoformat() if ultima else None,
            'conectado': True,
            'proxima_tentativa_automatica': None,
            'detalhes': detalhes,
        })