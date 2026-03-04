"""
Wazuh REST API client.
Docs: https://documentation.wazuh.com/current/user-manual/api/
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

WAZUH_API_URL = os.environ.get('WAZUH_API_URL', 'https://localhost:55000')
WAZUH_USER = os.environ.get('WAZUH_USER', 'wazuh')
WAZUH_PASSWORD = os.environ.get('WAZUH_PASSWORD', '')

_jwt_token = None
_token_expiry = 0


def _authenticate() -> str:
    """Obtain JWT token from Wazuh API."""
    global _jwt_token, _token_expiry
    url = f"{WAZUH_API_URL}/security/user/authenticate"
    try:
        resp = requests.post(
            url,
            auth=(WAZUH_USER, WAZUH_PASSWORD),
            verify=False,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data['data']['token']
        _jwt_token = token
        # Wazuh tokens expire after 900 seconds; refresh after 800
        _token_expiry = time.time() + 800
        logger.debug("Wazuh authentication successful")
        return token
    except Exception as e:
        logger.error(f"Wazuh authentication failed: {e}")
        raise


def _get_token() -> str:
    """Return a valid JWT token, re-authenticating if needed."""
    global _jwt_token, _token_expiry
    if _jwt_token is None or time.time() >= _token_expiry:
        return _authenticate()
    return _jwt_token


def _headers() -> dict:
    return {
        'Authorization': f'Bearer {_get_token()}',
        'Content-Type': 'application/json',
    }


def fetch_alerts(since: datetime, min_level: int = 3, limit: int = 100) -> list[dict]:
    """
    Fetch alerts from Wazuh API newer than `since`.
    Returns a list of alert dicts.
    """
    # Format: 2024-01-15T10:30:00+00:00
    since_str = since.strftime('%Y-%m-%dT%H:%M:%S+00:00')

    params = {
        'limit': limit,
        'sort': '+timestamp',
        'q': f'rule.level>={min_level};timestamp>{since_str}',
    }

    url = f"{WAZUH_API_URL}/security/events"

    try:
        resp = requests.get(
            url,
            headers=_headers(),
            params=params,
            verify=False,
            timeout=60,
        )

        # Re-authenticate if token expired
        if resp.status_code == 401:
            logger.info("Wazuh token expired, re-authenticating...")
            _authenticate()
            resp = requests.get(
                url,
                headers=_headers(),
                params=params,
                verify=False,
                timeout=60,
            )

        resp.raise_for_status()
        data = resp.json()

        alerts = data.get('data', {}).get('affected_items', [])
        total = data.get('data', {}).get('total_affected_items', 0)
        logger.info(f"Fetched {len(alerts)}/{total} alerts from Wazuh since {since_str}")
        return alerts

    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to Wazuh API at {WAZUH_API_URL}. Is Wazuh running?")
        return []
    except Exception as e:
        logger.error(f"Error fetching Wazuh alerts: {e}")
        return []


def parse_alert(raw: dict) -> dict:
    """
    Parse raw Wazuh alert into a normalized dict for processing.
    """
    agent = raw.get('agent', {})
    rule = raw.get('rule', {})
    data = raw.get('data', {})

    # Extract MITRE technique
    mitre = rule.get('mitre', {})
    mitre_ids = mitre.get('id', [])
    mitre_id = mitre_ids[0] if mitre_ids else ''

    # Try to extract source IP from various locations
    src_ip = (
        data.get('srcip') or
        data.get('src_ip') or
        raw.get('data', {}).get('win', {}).get('system', {}).get('computer', '') or
        None
    )

    # Wazuh alert ID (combination of timestamp + agent)
    alert_id = raw.get('id', '') or f"{raw.get('timestamp', '')}-{agent.get('id', '')}"

    # Parse timestamp
    timestamp_str = raw.get('timestamp', '')
    try:
        # Wazuh format: 2024-01-15T10:30:00.000+0000
        ts = datetime.fromisoformat(timestamp_str.replace('+0000', '+00:00'))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)

    return {
        'wazuh_id': alert_id,
        'timestamp': ts.isoformat(),
        'agent_name': agent.get('name', 'unknown'),
        'agent_ip': agent.get('ip') or None,
        'rule_id': str(rule.get('id', '')),
        'rule_level': int(rule.get('level', 0)),
        'rule_description': rule.get('description', ''),
        'rule_groups': rule.get('groups', []),
        'mitre_id': mitre_id,
        'src_ip': src_ip if src_ip and src_ip != '127.0.0.1' else None,
        'raw_data': raw,
    }
