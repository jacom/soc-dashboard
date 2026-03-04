from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Incident
from .serializers import IncidentSerializer


class IncidentViewSet(viewsets.ModelViewSet):
    queryset = Incident.objects.select_related('alert').order_by('-created_at')

    def get_serializer_class(self):
        return IncidentSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated()]
        return []
