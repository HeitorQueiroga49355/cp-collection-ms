from rest_framework import serializers
from .models import Coletor


class ColetorSerializer(serializers.ModelSerializer):
    matricula = serializers.CharField(source='username', read_only=True)
    avatar_url = serializers.URLField(source='foto_perfil', read_only=True)

    class Meta:
        model = Coletor
        fields = ['id', 'nome', 'matricula', 'email', 'avatar_url', 'zona', 'cargo']
