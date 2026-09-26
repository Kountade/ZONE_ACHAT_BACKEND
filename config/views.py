from django.shortcuts import render

# Create your views here.
# apps/config/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import Etablissement
from .serializers import EtablissementSerializer
from users.permissions import IsAdmin


class EtablissementViewSet(viewsets.ModelViewSet):
    queryset = Etablissement.objects.all()
    serializer_class = EtablissementSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdmin()]
        else:
            return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['get'], url_path='unique')
    def get_unique(self, request):
        etab = Etablissement.objects.first()
        if etab:
            serializer = self.get_serializer(etab)
            return Response(serializer.data)
        return Response({"detail": "Aucun établissement trouvé."}, status=status.HTTP_404_NOT_FOUND)
