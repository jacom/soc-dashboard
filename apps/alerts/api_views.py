from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .models import Alert
from .serializers import AlertSerializer, AlertCreateSerializer


class AlertViewSet(viewsets.ModelViewSet):
    queryset = Alert.objects.select_related('ai_analysis').order_by('-timestamp')
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_fields = ['severity', 'agent_name', 'rule_id']
    search_fields = ['rule_description', 'agent_name', 'mitre_id']
    ordering_fields = ['timestamp', 'severity', 'rule_level']

    def get_serializer_class(self):
        if self.action == 'create':
            return AlertCreateSerializer
        return AlertSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated()]
        return []

    def create(self, request, *args, **kwargs):
        serializer = AlertCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Check for duplicate wazuh_id
            wazuh_id = serializer.validated_data.get('wazuh_id')
            if Alert.objects.filter(wazuh_id=wazuh_id).exists():
                existing = Alert.objects.get(wazuh_id=wazuh_id)
                return Response(
                    AlertSerializer(existing).data,
                    status=status.HTTP_200_OK
                )
            alert = serializer.save()
            return Response(
                AlertSerializer(alert).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
