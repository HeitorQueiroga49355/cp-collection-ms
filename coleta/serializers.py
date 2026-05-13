from decimal import Decimal

from rest_framework import serializers

from .models import Coleta, Imovel, MaterialColeta, Rota, RotaImovel


# ─── Imovel ───────────────────────────────────────────────────────────────────

class ImovelResumoSerializer(serializers.ModelSerializer):
    numero_iptu = serializers.CharField(source='iptu')
    endereco = serializers.SerializerMethodField()

    class Meta:
        model = Imovel
        fields = ['id', 'numero_iptu', 'endereco']

    def get_endereco(self, obj):
        return f"{obj.logradouro}, {obj.numero}"


class ImovelBuscarSerializer(serializers.ModelSerializer):
    numero_iptu = serializers.CharField(source='iptu')
    endereco = serializers.SerializerMethodField()
    numero_endereco = serializers.CharField(source='numero')
    ultimo_coleta = serializers.SerializerMethodField()

    class Meta:
        model = Imovel
        fields = [
            'id', 'numero_iptu', 'endereco', 'numero_endereco',
            'bairro', 'morador', 'elegivel', 'ultimo_coleta',
        ]

    def get_endereco(self, obj):
        return f"{obj.logradouro}, {obj.numero}"

    def get_ultimo_coleta(self, obj):
        coleta = obj.coletas.order_by('-data_hora').first()
        if not coleta:
            return None
        return {
            'data': coleta.data_hora.date().isoformat(),
            'peso_kg': float(coleta.peso_total_kg),
            'materiais': list(coleta.materiais.values_list('tipo', flat=True)),
        }


class ImovelDetailSerializer(serializers.ModelSerializer):
    numero_iptu = serializers.CharField(source='iptu')
    endereco = serializers.SerializerMethodField()
    numero_endereco = serializers.CharField(source='numero')
    motivo_inelegivel = serializers.SerializerMethodField()
    historico_coletas = serializers.SerializerMethodField()
    total_coletas = serializers.SerializerMethodField()

    class Meta:
        model = Imovel
        fields = [
            'id', 'numero_iptu', 'endereco', 'numero_endereco', 'bairro',
            'complemento', 'morador', 'telefone', 'elegivel', 'motivo_inelegivel',
            'historico_coletas', 'total_coletas',
        ]

    def get_endereco(self, obj):
        return f"{obj.logradouro}, {obj.numero}"

    def get_motivo_inelegivel(self, obj):
        return obj.motivo_inelegivel or None

    def get_historico_coletas(self, obj):
        return [
            {
                'data': c.data_hora.date().isoformat(),
                'peso_kg': float(c.peso_total_kg),
                'materiais': list(c.materiais.values_list('tipo', flat=True)),
            }
            for c in obj.coletas.order_by('-data_hora')[:10]
        ]

    def get_total_coletas(self, obj):
        return obj.coletas.count()


# ─── Material ─────────────────────────────────────────────────────────────────

class MaterialColetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterialColeta
        fields = ['tipo', 'peso_kg']


class MaterialColetaInputSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=MaterialColeta.Tipo.choices)
    peso_kg = serializers.DecimalField(max_digits=8, decimal_places=3)


# ─── GPS ──────────────────────────────────────────────────────────────────────

class GpsSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


# ─── Coleta ───────────────────────────────────────────────────────────────────

class ColetaInputSerializer(serializers.Serializer):
    imovel_id = serializers.CharField()
    materiais = MaterialColetaInputSerializer(many=True)
    foto_url = serializers.URLField(required=False, allow_null=True, allow_blank=True)
    foto_base64 = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    gps = GpsSerializer(required=False, allow_null=True)
    data_hora = serializers.DateTimeField()
    observacoes = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    offline_id = serializers.UUIDField(required=False, allow_null=True)


class ColetaOutputSerializer(serializers.ModelSerializer):
    imovel_id = serializers.CharField(source='imovel.id')
    coletor_id = serializers.CharField(source='coletor.id')
    materiais = MaterialColetaSerializer(many=True)
    taxa_pontuacao = serializers.SerializerMethodField()
    gps = serializers.SerializerMethodField()
    sincronizado = serializers.BooleanField(source='sincronizado_core')

    class Meta:
        model = Coleta
        fields = [
            'id', 'codigo', 'imovel_id', 'coletor_id', 'status',
            'data_hora', 'peso_total_kg', 'pontos_gerados', 'taxa_pontuacao',
            'materiais', 'foto_url', 'gps', 'offline_id', 'sincronizado',
        ]

    def get_taxa_pontuacao(self, obj):
        return 1.5

    def get_gps(self, obj):
        if obj.gps_latitude is None:
            return None
        return {'latitude': obj.gps_latitude, 'longitude': obj.gps_longitude}


class ColetaHistoricoItemSerializer(serializers.ModelSerializer):
    imovel = ImovelResumoSerializer()
    material_principal = serializers.SerializerMethodField()
    peso_kg = serializers.DecimalField(source='peso_total_kg', max_digits=8, decimal_places=1)
    pontos = serializers.DecimalField(source='pontos_gerados', max_digits=8, decimal_places=2)
    hora = serializers.SerializerMethodField()
    sincronizado = serializers.BooleanField(source='sincronizado_core')

    class Meta:
        model = Coleta
        fields = [
            'id', 'codigo', 'imovel', 'material_principal',
            'peso_kg', 'pontos', 'data_hora', 'hora', 'sincronizado',
        ]

    def get_material_principal(self, obj):
        mat = obj.materiais.order_by('-peso_kg').first()
        return mat.tipo if mat else None

    def get_hora(self, obj):
        return obj.data_hora.strftime('%H:%M')


class ColetaDetailSerializer(serializers.ModelSerializer):
    imovel = serializers.SerializerMethodField()
    coletor = serializers.SerializerMethodField()
    materiais = MaterialColetaSerializer(many=True)
    pontos = serializers.DecimalField(source='pontos_gerados', max_digits=8, decimal_places=2)
    taxa_pontuacao_por_kg = serializers.SerializerMethodField()
    gps = serializers.SerializerMethodField()
    sincronizado = serializers.BooleanField(source='sincronizado_core')

    class Meta:
        model = Coleta
        fields = [
            'id', 'codigo', 'imovel', 'coletor', 'materiais',
            'peso_total_kg', 'pontos', 'taxa_pontuacao_por_kg',
            'data_hora', 'foto_url', 'gps', 'sincronizado', 'status',
        ]

    def get_imovel(self, obj):
        return {
            'id': str(obj.imovel.id),
            'numero_iptu': obj.imovel.iptu,
            'endereco': f"{obj.imovel.logradouro}, {obj.imovel.numero}",
            'bairro': obj.imovel.bairro,
            'morador': obj.imovel.morador,
        }

    def get_coletor(self, obj):
        return {
            'id': str(obj.coletor.id),
            'nome': obj.coletor.nome or obj.coletor.username,
            'matricula': obj.coletor.username,
        }

    def get_taxa_pontuacao_por_kg(self, obj):
        return 1.5

    def get_gps(self, obj):
        if obj.gps_latitude is None:
            return None
        return {'latitude': obj.gps_latitude, 'longitude': obj.gps_longitude}


# ─── Rota ─────────────────────────────────────────────────────────────────────

class RotaImovelSerializer(serializers.ModelSerializer):
    numero_iptu = serializers.CharField(source='imovel.iptu')
    endereco = serializers.SerializerMethodField()
    bairro = serializers.CharField(source='imovel.bairro')
    morador = serializers.CharField(source='imovel.morador')
    elegivel = serializers.BooleanField(source='imovel.elegivel')

    class Meta:
        model = RotaImovel
        fields = [
            'id', 'numero_iptu', 'endereco', 'bairro', 'status',
            'sequencia', 'distancia_metros', 'morador', 'elegivel',
        ]

    def get_endereco(self, obj):
        return f"{obj.imovel.logradouro}, {obj.imovel.numero}"
