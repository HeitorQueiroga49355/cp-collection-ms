import random
import string
from decimal import Decimal

import jwt as pyjwt
from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Coleta, Imovel
from .serializers import (
    ColetaDetailSerializer,
    ColetaHistoricoItemSerializer,
    ColetaInputSerializer,
    ColetaOutputSerializer,
    ImovelBuscarSerializer,
    ImovelDetailSerializer,
)
from .services.fila import publicar_coleta
from .services.storage import upload_foto_coleta


def _decode_core_jwt(request):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, 'Token JWT ausente ou mal formatado'
    token = auth_header[7:]
    try:
        payload = pyjwt.decode(
            token,
            settings.CORE_JWT_SECRET_KEY,
            algorithms=['HS256'],
        )
        return payload, None
    except pyjwt.ExpiredSignatureError:
        return None, 'Token expirado'
    except pyjwt.InvalidTokenError as exc:
        return None, f'Token inválido: {exc}'


def _hoje():
    return timezone.localdate()


def _dia_range(date):
    """Return (start, end) as UTC-aware datetimes spanning the given local date."""
    from datetime import datetime, time
    import pytz
    tz = pytz.timezone('America/Fortaleza')
    start = tz.localize(datetime.combine(date, time.min))
    end = tz.localize(datetime.combine(date, time.max))
    return start, end


def _gerar_codigo():
    letras = ''.join(random.choices(string.ascii_uppercase, k=4))
    numeros = ''.join(random.choices(string.digits, k=4))
    return f"{letras}-{numeros}"


def _distancia_metros(lng1, lat1, coords):
    """Distância em metros entre (lng1, lat1) e um ponto GeoJSON [lng, lat]."""
    from math import asin, cos, radians, sin, sqrt

    lng2, lat2 = coords[0], coords[1]
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))



# ─── Imóveis ──────────────────────────────────────────────────────────────────

class ImovelBuscarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo = request.query_params.get('tipo')
        valor = request.query_params.get('valor', '').strip()

        if not tipo or not valor:
            return Response({'error': 'Parâmetros tipo e valor são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        print(tipo, valor)

        qs = Imovel.objects.filter(ativo=True)

        print(qs.all())

        if tipo == 'numero':
            qs = qs.filter(iptu=valor)
        elif tipo == 'qrcode':
            qs = qs.filter(id=valor)
        elif tipo == 'endereco':
            qs = qs.filter(logradouro__icontains=valor)
            limit = min(int(request.query_params.get('limit', 20)), 100)
            imoveis = qs[:limit]
            return Response({'imoveis': ImovelBuscarSerializer(imoveis, many=True).data, 'total': len(imoveis)})
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


class ImovelProximosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        lat = request.query_params.get('lat')
        lng = request.query_params.get('lng')
        raio = request.query_params.get('raio', 200)

        if lat is None or lng is None:
            return Response({'error': 'Parâmetros lat e lng são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lat = float(lat)
            lng = float(lng)
            raio = float(raio)
        except (TypeError, ValueError):
            return Response({'error': 'Parâmetros lat, lng e raio devem ser numéricos'}, status=status.HTTP_400_BAD_REQUEST)

        # Filtro com $near: retorna apenas imóveis ativos dentro do raio (em metros),
        # já ordenados do mais próximo ao mais distante. Imóveis sem coordenadas são
        # excluídos automaticamente (não constam no índice 2dsphere).
        filtro = {
            'ativo': True,
            'location': {
                '$near': {
                    '$geometry': {'type': 'Point', 'coordinates': [lng, lat]},
                    '$maxDistance': raio,
                }
            },
        }

        colecao = connections['default'].get_collection(Imovel._meta.db_table)
        documentos = list(colecao.find(filtro))

        print(documentos)
        # $near não devolve a distância; calcula-se manualmente (haversine, em metros).
        for doc in documentos:
            coords = (doc.get('location') or {}).get('coordinates')
            doc['distancia'] = _distancia_metros(lng, lat, coords) if coords else 0.0


        # __date (TruncDate) não é suportado pelo backend MongoDB; filtra-se por
        # intervalo do dia local, mesmo recurso usado em SincronizacaoStatusView.
        from datetime import datetime, time
        hoje = _hoje()
        inicio_hoje = timezone.make_aware(datetime.combine(hoje, time.min))
        fim_hoje = timezone.make_aware(datetime.combine(hoje, time.max))

        ids = [doc['_id'] for doc in documentos]
        coletados_hoje = set(
            Coleta.objects.filter(
                coletor=request.user,
                imovel_id__in=ids,
                data_hora__gte=inicio_hoje,
                data_hora__lte=fim_hoje,
            ).values_list('imovel_id', flat=True)
        )

        imoveis = [
            {
                'id': str(doc['_id']),
                'id_externo': doc.get('id_externo'),
                'logradouro': doc.get('logradouro'),
                'numero': doc.get('numero'),
                'bairro': doc.get('bairro'),
                'complemento': doc.get('complemento') or '',
                'elegivel': doc.get('elegivel', True),
                'distancia': round(doc['distancia'], 1),
                'coletado_hoje': doc['_id'] in coletados_hoje,
                'location': doc.get('location'),
            }
            for doc in documentos
        ]

        return Response({'imoveis': imoveis, 'total': len(imoveis)})


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

        foto_url = ''
        arquivo = request.FILES.get('foto')
        if arquivo:
            try:
                foto_url = upload_foto_coleta(arquivo, content_type=arquivo.content_type or 'image/jpeg')
            except Exception as exc:
                return Response({'error': f'Falha ao enviar foto: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)

        peso_total = Decimal(str(data['peso_total_kg']))

        with transaction.atomic():
            coleta = Coleta.objects.create(
                coletor=request.user,
                imovel=imovel,
                data_hora=data['data_hora'],
                peso_total_kg=peso_total,
                foto_url=foto_url,
                status=Coleta.Status.CONFIRMADA,
                observacoes=data.get('observacoes') or '',
                offline_id=offline_id,
                codigo=_gerar_codigo(),
                sincronizado_core=False,
            )

        enviado = publicar_coleta(
            coleta_id=str(coleta.id),
            inscricao_imobiliaria=coleta.imovel.id_externo,
            peso_total_kg=str(coleta.peso_total_kg),
            data_hora=coleta.data_hora.isoformat(),
        )
        coleta.sincronizado_core = enviado
        coleta.tentativas_sincronizacao = 1
        coleta.erro_ultima_tentativa = '' if enviado else 'Falha ao publicar na fila RabbitMQ'
        coleta.save(update_fields=['sincronizado_core', 'tentativas_sincronizacao', 'erro_ultima_tentativa'])

        return Response(ColetaOutputSerializer(coleta).data, status=status.HTTP_201_CREATED)


class ColetaHistoricoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tipo_periodo = request.query_params.get('tipo_periodo', 'hoje')
        data_param = request.query_params.get('data')
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 30))

        hoje = _hoje()
        qs = Coleta.objects.filter(coletor=request.user).select_related('imovel')

        if data_param:
            from datetime import date as date_type
            parsed = date_type.fromisoformat(data_param)
            start, end = _dia_range(parsed)
            qs = qs.filter(data_hora__gte=start, data_hora__lte=end)
        elif tipo_periodo == 'hoje':
            start, end = _dia_range(hoje)
            qs = qs.filter(data_hora__gte=start, data_hora__lte=end)
        elif tipo_periodo == 'ontem':
            from datetime import timedelta
            start, end = _dia_range(hoje - timedelta(days=1))
            qs = qs.filter(data_hora__gte=start, data_hora__lte=end)
        elif tipo_periodo == 'semana':
            from datetime import timedelta
            start, _ = _dia_range(hoje - timedelta(days=7))
            _, end = _dia_range(hoje)
            qs = qs.filter(data_hora__gte=start, data_hora__lte=end)
        elif tipo_periodo == 'mes':
            import calendar
            from datetime import date as date_type
            first_day = date_type(hoje.year, hoje.month, 1)
            last_day = date_type(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
            start, _ = _dia_range(first_day)
            _, end = _dia_range(last_day)
            qs = qs.filter(data_hora__gte=start, data_hora__lte=end)

        total_coletas = qs.count()
        total_kg = sum(c.peso_total_kg for c in qs)

        offset = (page - 1) * limit
        coletas_pagina = qs[offset:offset + limit]

        return Response({
            'coletas': ColetaHistoricoItemSerializer(coletas_pagina, many=True).data,
            'resumo': {
                'total_coletas': total_coletas,
                'total_kg': float(total_kg),
            },
            'page': page,
            'total_pages': max(1, -(-total_coletas // limit)),
        })


class ColetaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            coleta = Coleta.objects.select_related('imovel', 'coletor').get(
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
                'peso_total_kg': str(c.peso_total_kg),
                'data_hora': c.data_hora.isoformat(),
                'sincronizado': c.sincronizado_core,
                'tentativas_sincronizacao': c.tentativas_sincronizacao,
                'erro_ultima_tentativa': c.erro_ultima_tentativa or None,
            }
            for c in pendentes
        ]
        return Response({'pendentes': resultado, 'total': len(resultado)})


# ─── Portal do Morador ────────────────────────────────────────────────────────

class ColetasMoradorView(APIView):
    """
    GET /coletas/morador — retorna as coletas dos imóveis do morador autenticado
    via JWT do core (validado com CORE_JWT_SECRET_KEY), paginadas e ordenadas
    decrescentemente pela data de criação.
    """
    # A autenticação JWT global (JWTAuthentication) valida tokens do próprio
    # microsserviço contra o modelo Coletor — rodaria antes do permission_classes
    # e derrubaria com 401 qualquer token do core (assinado para o Usuario/morador).
    # A validação do token do core é feita manualmente em _decode_core_jwt.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        payload, erro = _decode_core_jwt(request)
        if erro:
            return Response({'error': erro}, status=status.HTTP_401_UNAUTHORIZED)

        user_id = payload.get('user_id')
        if not user_id:
            return Response({'error': 'Token sem user_id'}, status=status.HTTP_401_UNAUTHORIZED)

        page = max(1, int(request.query_params.get('page', 1)))
        limit = min(max(1, int(request.query_params.get('limit', 20))), 100)

        qs = (
            Coleta.objects
            .filter(imovel__proprietario_id=user_id)
            .select_related('imovel')
            .order_by('-criado_em')
        )

        total = qs.count()
        offset = (page - 1) * limit
        coletas_pagina = qs[offset:offset + limit]

        return Response({
            'coletas': ColetaHistoricoItemSerializer(coletas_pagina, many=True).data,
            'page': page,
            'total': total,
            'total_pages': max(1, -(-total // limit)),
        })


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

                peso_total = Decimal(str(item['peso_total_kg']))

                with transaction.atomic():
                    coleta = Coleta.objects.create(
                        coletor=request.user,
                        imovel=imovel,
                        data_hora=item['data_hora'],
                        peso_total_kg=peso_total,
                        foto_url=item.get('foto_url') or '',
                        status=Coleta.Status.CONFIRMADA,
                        offline_id=offline_id,
                        codigo=_gerar_codigo(),
                        sincronizado_core=False,
                    )

                enviado = publicar_coleta(
                    coleta_id=str(coleta.id),
                    inscricao_imobiliaria=coleta.imovel.id_externo,
                    peso_total_kg=str(coleta.peso_total_kg),
                    data_hora=coleta.data_hora.isoformat(),
                )
                coleta.sincronizado_core = enviado
                coleta.tentativas_sincronizacao = 1
                coleta.erro_ultima_tentativa = '' if enviado else 'Falha ao publicar na fila RabbitMQ'
                coleta.save(update_fields=['sincronizado_core', 'tentativas_sincronizacao', 'erro_ultima_tentativa'])

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
        
        hoje = _hoje()
        from datetime import datetime, time
        hoje_inicio = datetime.combine(hoje, time.min)
        hoje_fim = datetime.combine(hoje, time.max)

        sincronizadas_hoje = Coleta.objects.filter(
            coletor=request.user,
            sincronizado_core=True,
            data_hora__gte=hoje_inicio,
            data_hora__lte=hoje_fim,
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