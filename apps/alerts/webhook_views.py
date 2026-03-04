"""
Webhook endpoint for receiving alerts pushed by Wazuh Custom Integration.
POST /api/wazuh-webhook/  with raw Wazuh JSON alert in body.
Auth: Token header (same dashboard API token).
"""
import logging
from datetime import datetime, timezone

from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import Alert
from .wazuh_fetcher import classify_severity, _parse_alert

logger = logging.getLogger(__name__)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def wazuh_webhook(request):
    """
    Receive a single Wazuh alert JSON from the custom integration script
    and save it to the DB.
    """
    raw = request.data

    if not raw:
        return Response({'error': 'Empty body'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        parsed = _parse_alert(raw)
    except Exception as e:
        logger.error(f'Webhook parse error: {e}')
        return Response({'error': f'Parse error: {e}'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        alert, created = Alert.objects.get_or_create(
            wazuh_id=parsed['wazuh_id'],
            defaults={
                'timestamp':        parsed['timestamp'],
                'agent_name':       parsed['agent_name'],
                'agent_ip':         parsed['agent_ip'],
                'rule_id':          parsed['rule_id'],
                'rule_level':       parsed['rule_level'],
                'rule_description': parsed['rule_description'],
                'rule_groups':      parsed['rule_groups'],
                'mitre_id':         parsed['mitre_id'],
                'src_ip':           parsed['src_ip'],
                'severity':         parsed['severity'],
                'raw_data':         parsed['raw_data'],
            }
        )
    except Exception as e:
        logger.error(f'Webhook DB save error: {e}')
        return Response({'error': f'DB error: {e}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if created and alert.severity in ('CRITICAL', 'HIGH'):
        from .pipeline import run_pipeline_in_thread
        run_pipeline_in_thread(alert)

    logger.info(
        f"Webhook: [{parsed['severity']}] {parsed['rule_description'][:60]} "
        f"({'new' if created else 'duplicate'})"
    )
    return Response({
        'id': alert.id,
        'wazuh_id': alert.wazuh_id,
        'created': created,
        'severity': alert.severity,
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
