"""
SOC Dashboard API client.
Pushes alerts, incidents, and notifications to the Django dashboard.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

DASHBOARD_URL = os.environ.get('DASHBOARD_URL', 'http://localhost:8002')
DASHBOARD_API_TOKEN = os.environ.get('DASHBOARD_API_TOKEN', '')


def _headers() -> dict:
    return {
        'Authorization': f'Token {DASHBOARD_API_TOKEN}',
        'Content-Type': 'application/json',
    }


def save_alert_to_dashboard(alert: dict, ai_analysis: dict | None = None) -> int | None:
    """
    POST alert (with optional AI analysis) to Dashboard API.
    Returns the dashboard alert ID on success, None on failure.
    """
    payload = {
        'wazuh_id': alert.get('wazuh_id', ''),
        'timestamp': alert.get('timestamp', ''),
        'agent_name': alert.get('agent_name', ''),
        'agent_ip': alert.get('agent_ip'),
        'rule_id': alert.get('rule_id', ''),
        'rule_level': alert.get('rule_level', 0),
        'rule_description': alert.get('rule_description', ''),
        'rule_groups': alert.get('rule_groups', []),
        'mitre_id': alert.get('mitre_id', ''),
        'src_ip': alert.get('src_ip'),
        'severity': alert.get('severity', 'INFO'),
        'raw_data': alert.get('raw_data', {}),
    }

    if ai_analysis:
        payload['ai_analysis'] = {
            'attack_type': ai_analysis.get('attack_type', ''),
            'mitre_technique': ai_analysis.get('mitre_technique', ''),
            'severity_assessment': ai_analysis.get('severity_assessment', ''),
            'impact': ai_analysis.get('impact', ''),
            'recommendations': str(ai_analysis.get('recommendations', '')),
            'false_positive_pct': int(ai_analysis.get('false_positive_pct', 0)),
            'summary': ai_analysis.get('summary', ''),
            'raw_response': ai_analysis.get('raw_response', ''),
        }

    try:
        resp = requests.post(
            f"{DASHBOARD_URL}/api/alerts/",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get('id')
        else:
            logger.error(f"Dashboard API error {resp.status_code}: {resp.text[:200]}")
            return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to SOC Dashboard at {DASHBOARD_URL}")
        return None
    except Exception as e:
        logger.error(f"Error saving alert to dashboard: {e}")
        return None


def save_incident(
    alert_id: int,
    case_id: str,
    title: str,
    status: str,
    severity: str,
    case_url: str,
) -> bool:
    """POST incident record to Dashboard API."""
    payload = {
        'alert': alert_id,
        'thehive_case_id': case_id,
        'title': title,
        'status': status,
        'severity': severity,
        'thehive_url': case_url,
    }

    try:
        resp = requests.post(
            f"{DASHBOARD_URL}/api/incidents/",
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return True
        else:
            logger.error(f"Dashboard incident API error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Error saving incident to dashboard: {e}")
        return False


def save_notification(
    alert_id: int,
    channel: str,
    status: str,
    message_preview: str,
    error_message: str = '',
) -> bool:
    """POST notification log entry to Dashboard API."""
    payload = {
        'alert': alert_id,
        'channel': channel,
        'status': status,
        'message_preview': message_preview,
        'error_message': error_message,
    }

    try:
        resp = requests.post(
            f"{DASHBOARD_URL}/api/notifications/",
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Error saving notification log: {e}")
        return False
