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
    bairro = models.CharField('bairro', max_length=100)
    morador = models.CharField('morador', max_length=150)
    elegivel = models.BooleanField('elegível', default=True)
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


# ─── Rota ─────────────────────────────────────────────────────────────────────

class Rota(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        CONCLUIDA = 'CONCLUIDA', 'Concluída'

    nome = models.CharField('nome', max_length=100)
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

    class Meta:
        verbose_name = 'rota'
        verbose_name_plural = 'rotas'
        ordering = ['-data', 'nome']

    def __str__(self):
        return f"{self.nome} — {self.data}"

    def progresso_percentual(self) -> float:
        if not self.total_imoveis:
            return 0.0
        return round(self.imoveis_visitados / self.total_imoveis * 100, 2)


# ─── Coleta ───────────────────────────────────────────────────────────────────

class Coleta(models.Model):
    coleta_id = models.UUIDField(
        'ID da coleta',
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
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
    sincronizado_core = models.BooleanField('sincronizado com core', default=False)
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

    def peso_por_categoria(self) -> dict:
        return {m.categoria: m.peso_kg for m in self.materiais.all()}
