from django.contrib.auth.models import AbstractUser
from django.db import models


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
