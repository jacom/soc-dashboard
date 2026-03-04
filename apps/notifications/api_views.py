from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import NotificationLog
from .serializers import NotificationLogSerializer


class NotificationLogViewSet(viewsets.ModelViewSet):
    queryset = NotificationLog.objects.select_related('alert').order_by('-sent_at')

    def get_serializer_class(self):
        return NotificationLogSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated()]
        return []
