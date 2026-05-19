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


# ─── Rota ─────────────────────────────────────────────────────────────────────

class Rota(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'

    codigo = models.CharField('código', max_length=20, blank=True)
    nome = models.CharField('nome', max_length=100)
    zona = models.CharField('zona', max_length=100, blank=True)
    coletor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rotas',
        verbose_name='coletor',
    )
    data = models.DateField('data')
    status = models.CharField(
        'status',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    total_imoveis = models.IntegerField('total de imóveis', default=0)
    imoveis_visitados = models.IntegerField('imóveis visitados', default=0)
    hora_prevista_encerro = models.TimeField('hora prevista de encerro', null=True, blank=True)

    class Meta:
        verbose_name = 'rota'
        verbose_name_plural = 'rotas'
        ordering = ['-data', 'nome']

    def __str__(self):
        return f"{self.codigo or self.nome} — {self.data}"

    def progresso_percentual(self) -> float:
        if not self.total_imoveis:
            return 0.0
        return round(self.imoveis_visitados / self.total_imoveis * 100, 2)


# ─── Parada (Imóvel na Rota) ──────────────────────────────────────────────────

class RotaImovel(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente'
        COLETADO = 'coletado', 'Coletado'
        RECUSADO = 'recusado', 'Recusado'

    rota = models.ForeignKey(
        Rota,
        on_delete=models.CASCADE,
        related_name='paradas',
        verbose_name='rota',
    )
    imovel = models.ForeignKey(
        Imovel,
        on_delete=models.PROTECT,
        related_name='paradas',
        verbose_name='imóvel',
    )
    sequencia = models.IntegerField('sequência', default=0)
    status = models.CharField(
        'status',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    distancia_metros = models.FloatField('distância (metros)', null=True, blank=True)

    class Meta:
        verbose_name = 'parada'
        verbose_name_plural = 'paradas'
        ordering = ['sequencia']
        unique_together = [('rota', 'imovel')]

    def __str__(self):
        return f"{self.rota} → {self.imovel}"


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
    pontos_gerados = models.DecimalField('pontos gerados', max_digits=8, decimal_places=2, default=0)
    foto_url = models.URLField('foto', blank=True)
    gps_latitude = models.FloatField('latitude', null=True, blank=True)
    gps_longitude = models.FloatField('longitude', null=True, blank=True)
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

