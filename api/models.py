import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import ColetaManager, ImovelManager


# ─── Coletor ──────────────────────────────────────────────────────────────────

class Coletor(AbstractUser):
    nome = models.CharField('nome completo', max_length=150, blank=True)
    foto_perfil = models.URLField('foto de perfil', blank=True)
    ativo = models.BooleanField('ativo', default=True)
    criado_em = models.DateTimeField('criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'coletor'
        verbose_name_plural = 'coletores'
        ordering = ['nome']

    def __str__(self):
        return self.nome or self.username


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
        'Coletor',
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


# ─── Parada ───────────────────────────────────────────────────────────────────

class Parada(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        COLETADO = 'COLETADO', 'Coletado'
        FALHOU = 'FALHOU', 'Falhou'

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
    ordem = models.PositiveIntegerField('ordem')
    status = models.CharField(
        'status',
        max_length=10,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    atualizado_em = models.DateTimeField('atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'parada'
        verbose_name_plural = 'paradas'
        ordering = ['rota', 'ordem']
        indexes = [
            models.Index(fields=['rota', 'status']),
        ]

    def __str__(self):
        return f"{self.rota} — #{self.ordem} ({self.status})"


# ─── Coleta ───────────────────────────────────────────────────────────────────

class Coleta(models.Model):
    class Origem(models.TextChoices):
        APP = 'APP', 'App em tempo real'
        SYNC_OFFLINE = 'SYNC_OFFLINE', 'Sincronização offline'

    coleta_id = models.UUIDField(
        'ID da coleta',
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    coletor = models.ForeignKey(
        Coletor,
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
    parada = models.ForeignKey(
        Parada,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coletas',
        verbose_name='parada',
    )
    data_hora = models.DateTimeField('data e hora')
    peso_total_kg = models.DecimalField('peso total (kg)', max_digits=8, decimal_places=3)
    pontos_gerados = models.IntegerField('pontos gerados', default=0)
    foto_url = models.URLField('foto', blank=True)
    latitude = models.DecimalField(
        'latitude', max_digits=10, decimal_places=7, null=True, blank=True
    )
    longitude = models.DecimalField(
        'longitude', max_digits=10, decimal_places=7, null=True, blank=True
    )
    sincronizado_core = models.BooleanField('sincronizado com core', default=False)
    origem = models.CharField(
        'origem',
        max_length=20,
        choices=Origem.choices,
        default=Origem.APP,
    )
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


# ─── Material de Coleta ───────────────────────────────────────────────────────

class MaterialColeta(models.Model):
    class Categoria(models.TextChoices):
        PAPEL = 'PAPEL', 'Papel/Papelão'
        PLASTICO = 'PLASTICO', 'Plástico'
        VIDRO = 'VIDRO', 'Vidro'
        METAL = 'METAL', 'Metal'
        ORGANICO = 'ORGANICO', 'Orgânico'

    coleta = models.ForeignKey(
        Coleta,
        on_delete=models.CASCADE,
        related_name='materiais',
        verbose_name='coleta',
    )
    categoria = models.CharField('categoria', max_length=20, choices=Categoria.choices)
    peso_kg = models.DecimalField('peso (kg)', max_digits=7, decimal_places=3)

    class Meta:
        verbose_name = 'material de coleta'
        verbose_name_plural = 'materiais de coleta'
        ordering = ['categoria']

    def __str__(self):
        return f"{self.get_categoria_display()} — {self.peso_kg}kg"
