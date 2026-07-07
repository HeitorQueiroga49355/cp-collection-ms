import uuid

from django.conf import settings
from django.db import models

from .managers import ColetaManager, ImovelManager



# ─── Imóvel ───────────────────────────────────────────────────────────────────

class Imovel(models.Model):
    id_externo = models.CharField('ID externo', max_length=100, unique=True)
    iptu = models.CharField('IPTU', max_length=20, unique=True)
    logradouro = models.CharField('logradouro', max_length=200)
    numero = models.CharField('número', max_length=20)
    complemento = models.CharField('complemento', max_length=100, blank=True)
    bairro = models.CharField('bairro', max_length=100)
    morador = models.CharField('morador', max_length=150)
    telefone = models.CharField('telefone', max_length=20, blank=True)
    elegivel = models.BooleanField('elegível', default=True)
    motivo_inelegivel = models.TextField('motivo inelegível', blank=True)
    proprietario_id = models.IntegerField('ID do proprietário (core)', null=True, blank=True, db_index=True)
    # Armazena o número total de moradores residentes no imóvel (dado sincronizado do Core)
    num_moradores = models.IntegerField('número de moradores', default=1)
    location = models.JSONField('localização (GeoJSON)', null=True, blank=True)
    sincronizado_em = models.DateTimeField('sincronizado em', auto_now=True)
    ativo = models.BooleanField('ativo', default=True)

    objects = ImovelManager()

    class Meta:
        verbose_name = 'imóvel'
        verbose_name_plural = 'imóveis'
        ordering = ['logradouro', 'numero']
        indexes = [
            models.Index(fields=['iptu']),
            models.Index(fields=['elegivel']),
        ]

    def __str__(self):
        return f"{self.iptu} — {self.logradouro}, {self.numero}"

    @property
    def endereco(self):
        return f"{self.logradouro}, {self.numero}"

    @staticmethod
    def montar_location(latitude, longitude):
        """Monta um Point GeoJSON ({type, coordinates: [lng, lat]}) a partir de
        latitude/longitude. Retorna None quando alguma coordenada está ausente
        (imóveis sem geocodificação)."""
        if latitude is None or longitude is None:
            return None
        return {'type': 'Point', 'coordinates': [float(longitude), float(latitude)]}


# ─── Coleta ───────────────────────────────────────────────────────────────────

class Coleta(models.Model):
    class Status(models.TextChoices):
        CONFIRMADA = 'confirmada', 'Confirmada'
        PENDENTE = 'pendente', 'Pendente'
        ERRO = 'erro', 'Erro'

    coleta_id = models.UUIDField(
        'ID da coleta',
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    offline_id = models.UUIDField(
        'ID offline',
        null=True,
        blank=True,
        unique=True,
    )
    codigo = models.CharField('código', max_length=20, blank=True)
    coletor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='coletas',
        verbose_name='coletor',
    )
    imovel = models.ForeignKey(
        Imovel,
        on_delete=models.PROTECT,
        related_name='coletas',
        verbose_name='imóvel',
    )
    data_hora = models.DateTimeField('data e hora')
    peso_total_kg = models.DecimalField('peso total (kg)', max_digits=8, decimal_places=3)
    foto_url = models.URLField('foto', blank=True)
    status = models.CharField(
        'status',
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMADA,
    )
    observacoes = models.TextField('observações', blank=True)
    sincronizado_core = models.BooleanField('sincronizado com core', default=False)
    tentativas_sincronizacao = models.IntegerField('tentativas de sincronização', default=0)
    erro_ultima_tentativa = models.TextField('erro última tentativa', blank=True)
    criado_em = models.DateTimeField('criado em', auto_now_add=True)

    objects = ColetaManager()

    class Meta:
        verbose_name = 'coleta'
        verbose_name_plural = 'coletas'
        ordering = ['-data_hora']
        indexes = [
            models.Index(fields=['coletor', 'data_hora']),
            models.Index(fields=['sincronizado_core']),
        ]

    def __str__(self):
        return f"Coleta {self.coleta_id} — {self.coletor}"

