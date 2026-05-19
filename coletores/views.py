from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Coletor
from .serializers import ColetorSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        matricula = request.data.get('matricula', '').strip()
        senha = request.data.get('senha', '')
        nome = request.data.get('nome', '').strip()
        email = request.data.get('email', '').strip()
        zona = request.data.get('zona', '').strip()
        cargo = request.data.get('cargo', '').strip()

        if not matricula or not senha:
            return Response(
                {'error': 'matricula e senha são obrigatórios'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Coletor.objects.filter(username=matricula).exists():
            return Response(
                {'error': 'Matrícula já cadastrada', 'field': 'matricula'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if email and Coletor.objects.filter(email=email).exists():
            return Response(
                {'error': 'E-mail já cadastrado', 'field': 'email'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(senha)
        except ValidationError as exc:
            return Response({'error': exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        user = Coletor.objects.create_user(
            username=matricula,
            password=senha,
            nome=nome,
            email=email,
            zona=zona,
            cargo=cargo or 'Agente de coleta',
        )

        refresh = RefreshToken.for_user(user)
        return Response({
            'token': str(refresh.access_token),
            'user': {
                'id': str(user.id),
                'nome': user.nome or user.username,
                'matricula': user.username,
                'email': user.email,
                'avatar_url': None,
                'zona': user.zona,
                'role': 'coletor',
            },
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        matricula = request.data.get('matricula')
        senha = request.data.get('senha')

        if not matricula or not senha:
            return Response(
                {'error': 'Credenciais inválidas'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = authenticate(request, username=matricula, password=senha)
        if not user:
            return Response(
                {'error': 'Credenciais inválidas'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'token': str(refresh.access_token),
            'user': {
                'id': str(user.id),
                'nome': user.nome or user.username,
                'matricula': user.username,
                'email': user.email,
                'avatar_url': user.foto_perfil or None,
                'zona': user.zona,
                'role': 'coletor',
            },
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response({'message': 'Logout realizado com sucesso'})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        return Response({
            'id': str(user.id),
            'nome': user.nome or user.username,
            'matricula': user.username,
            'email': user.email,
            'avatar_url': user.foto_perfil or None,
            'zona': user.zona,
            'cargo': user.cargo,
        })
