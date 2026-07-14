from rest_framework import serializers
from .models import Coletor


class ColetorSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    matricula = serializers.CharField(source='username', read_only=True)
    avatar_url = serializers.URLField(source='foto_perfil', read_only=True, allow_null=True)

    class Meta:
        model = Coletor
        fields = ['id', 'nome', 'matricula', 'email', 'avatar_url', 'zona', 'cargo']


class ColetorGestaoSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    matricula = serializers.CharField(source='username', read_only=True)
    avatar_url = serializers.URLField(source='foto_perfil', read_only=True, allow_null=True)

    class Meta:
        model = Coletor
        fields = ['id', 'nome', 'matricula', 'email', 'avatar_url', 'zona', 'cargo', 'ativo', 'criado_em']
