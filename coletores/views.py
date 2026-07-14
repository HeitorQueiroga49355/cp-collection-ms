from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
import jwt as pyjwt

from .models import Coletor
from .serializers import ColetorGestaoSerializer, ColetorSerializer


def _decode_core_jwt(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header.startswith('Bearer '):
        return None, 'Token ausente'
    token = auth_header[7:]
    try:
        payload = pyjwt.decode(token, settings.CORE_JWT_SECRET_KEY, algorithms=['HS256'])
        return payload, None
    except pyjwt.ExpiredSignatureError:
        return None, 'Token expirado'
    except pyjwt.InvalidTokenError as exc:
        return None, str(exc)


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


class GestaoColetoresView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        payload, erro = _decode_core_jwt(request)
        if erro:
            return Response({'error': erro}, status=status.HTTP_401_UNAUTHORIZED)

        coletores = Coletor.objects.all().order_by('-criado_em')

        search = request.query_params.get('search', '').strip()
        if search:
            coletores = coletores.filter(
                Q(username__icontains=search) | Q(nome__icontains=search) | Q(email__icontains=search)
            )

        ativo_param = request.query_params.get('ativo')
        if ativo_param is not None:
            coletores = coletores.filter(ativo=ativo_param.lower() == 'true')

        serializer = ColetorGestaoSerializer(coletores, many=True)
        return Response(serializer.data)

    def post(self, request):
        payload, erro = _decode_core_jwt(request)
        if erro:
            return Response({'error': erro}, status=status.HTTP_401_UNAUTHORIZED)

        matricula = request.data.get('matricula', '').strip()
        senha = request.data.get('senha', '').strip()
        nome = request.data.get('nome', '').strip()
        email = request.data.get('email', '').strip()
        zona = request.data.get('zona', '').strip()
        cargo = request.data.get('cargo', '').strip()

        if not matricula or not senha:
            return Response({'error': 'matricula e senha são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        if Coletor.objects.filter(username=matricula).exists():
            return Response({'error': 'Matrícula já cadastrada', 'field': 'matricula'}, status=status.HTTP_400_BAD_REQUEST)

        if email and Coletor.objects.filter(email=email).exists():
            return Response({'error': 'E-mail já cadastrado', 'field': 'email'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(senha)
        except ValidationError as exc:
            return Response({'error': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        coletor = Coletor.objects.create_user(
            username=matricula,
            password=senha,
            nome=nome,
            email=email,
            zona=zona,
            cargo=cargo or 'Agente de coleta',
        )

        serializer = ColetorGestaoSerializer(coletor)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class GestaoColetorDetalheView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, pk):
        payload, erro = _decode_core_jwt(request)
        if erro:
            return Response({'error': erro}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            coletor = Coletor.objects.get(pk=pk)
        except Coletor.DoesNotExist:
            return Response({'error': 'Coletor não encontrado'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ColetorGestaoSerializer(coletor)
        return Response(serializer.data)

    def patch(self, request, pk):
        payload, erro = _decode_core_jwt(request)
        if erro:
            return Response({'error': erro}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            coletor = Coletor.objects.get(pk=pk)
        except Coletor.DoesNotExist:
            return Response({'error': 'Coletor não encontrado'}, status=status.HTTP_404_NOT_FOUND)

        nome = request.data.get('nome')
        email = request.data.get('email')
        zona = request.data.get('zona')
        cargo = request.data.get('cargo')
        ativo = request.data.get('ativo')

        if nome is not None:
            coletor.nome = nome
        if email is not None:
            if email != coletor.email and Coletor.objects.filter(email=email).exclude(pk=pk).exists():
                return Response({'error': 'E-mail já cadastrado', 'field': 'email'}, status=status.HTTP_400_BAD_REQUEST)
            coletor.email = email
        if zona is not None:
            coletor.zona = zona
        if cargo is not None:
            coletor.cargo = cargo
        if ativo is not None:
            coletor.ativo = bool(ativo)

        coletor.save()
        serializer = ColetorGestaoSerializer(coletor)
        return Response(serializer.data)

    def delete(self, request, pk):
        payload, erro = _decode_core_jwt(request)
        if erro:
            return Response({'error': erro}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            coletor = Coletor.objects.get(pk=pk)
        except Coletor.DoesNotExist:
            return Response({'error': 'Coletor não encontrado'}, status=status.HTTP_404_NOT_FOUND)

        coletor.ativo = False
        coletor.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
