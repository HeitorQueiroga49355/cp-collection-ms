from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status


class RegistrarPesagemView(APIView):
    def post(self, request):
        return Response({'detalhe': 'não implementado'}, status=status.HTTP_501_NOT_IMPLEMENTED)
