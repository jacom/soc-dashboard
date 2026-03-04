"""
Wazuh Alert Fetcher — pulls alerts from Wazuh Indexer (OpenSearch) and saves to DB.
Credentials are read from IntegrationConfig model (Settings UI).
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
import urllib3

from .models import Alert

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_SEVERITY_RANGES = [
    (range(12, 16), 'CRITICAL'),
    (range(8, 12),  'HIGH'),
    (range(6, 8),   'MEDIUM'),
    (range(4, 6),   'LOW'),
    (range(0, 4),   'INFO'),
]


def _get_indexer_credentials():
    """Read Wazuh Indexer credentials from IntegrationConfig DB."""
    from apps.config.models import IntegrationConfig
    configs = {
        c.key: c.value
        for c in IntegrationConfig.objects.filter(
            key__in=['WAZUH_INDEXER_URL', 'WAZUH_INDEXER_USER', 'WAZUH_INDEXER_PASSWORD']
        )
    }
    return (
        configs.get('WAZUH_INDEXER_URL', 'https://localhost:9200').rstrip('/'),
        configs.get('WAZUH_INDEXER_USER', 'admin'),
        configs.get('WAZUH_INDEXER_PASSWORD', ''),
    )


def classify_severity(rule_level: int) -> str:
    for level_range, severity in _SEVERITY_RANGES:
        if rule_level in level_range:
            return severity
    return 'INFO'


def _parse_alert(raw: dict) -> dict:
    agent = raw.get('agent', {})
    rule = raw.get('rule', {})
    data = raw.get('data', {})

    mitre_ids = rule.get('mitre', {}).get('id', [])
    mitre_id = mitre_ids[0] if mitre_ids else ''

    src_ip = data.get('srcip') or data.get('src_ip') or None
    if src_ip == '127.0.0.1':
        src_ip = None

    alert_id = raw.get('id', '') or f"{raw.get('timestamp', '')}-{agent.get('id', '')}"

    timestamp_str = raw.get('timestamp', '')
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('+0000', '+00:00'))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)

    rule_level = int(rule.get('level', 0))

    return {
        'wazuh_id':         alert_id,
        'timestamp':        ts,
        'agent_name':       agent.get('name', 'unknown'),
        'agent_ip':         agent.get('ip') or None,
        'rule_id':          str(rule.get('id', '')),
        'rule_level':       rule_level,
        'rule_description': rule.get('description', ''),
        'rule_groups':      rule.get('groups', []),
        'mitre_id':         mitre_id,
        'src_ip':           src_ip,
        'severity':         classify_severity(rule_level),
        'raw_data':         raw,
    }


def _analyze_in_thread(alert):
    """Used by batch_analyze (manual re-analysis). Auto-pipeline uses run_pipeline_in_thread."""
    import threading
    from .ai_analyzer import analyze_alert

    def _run(a):
        try:
            analyze_alert(a)
        finally:
            # Release DB connection when thread finishes
            try:
                from django.db import connection as _db_conn
                _db_conn.close()
            except Exception:
                pass

    threading.Thread(target=_run, args=(alert,), daemon=True).start()


def fetch_and_save(hours: int = 1, min_level: int = 3, limit: int = 500) -> dict:
    """
    Query Wazuh Indexer (OpenSearch) for alerts and save new ones to DB.

    Returns:
        { fetched, created, skipped, errors, error_msg }

    Note: Wazuh fetching always runs regardless of pipeline/Ollama status.
    Pipeline (Ollama AI analysis) is independent — busy pipeline must not block data ingestion.
    """
    stats = {'fetched': 0, 'created': 0, 'skipped': 0, 'errors': 0, 'error_msg': '', 'busy': False}

    indexer_url, idx_user, idx_password = _get_indexer_credentials()

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since.strftime('%Y-%m-%dT%H:%M:%S')

    query = {
        'size': limit,
        'sort': [{'timestamp': {'order': 'asc'}}],
        'query': {
            'bool': {
                'must': [
                    {'range': {'rule.level': {'gte': min_level}}},
                    {'range': {'timestamp': {'gte': since_str}}},
                ]
            }
        }
    }

    _retry_delays = [5, 15, 30]
    resp = None
    for attempt, delay in enumerate([0] + _retry_delays):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.post(
                f'{indexer_url}/wazuh-alerts-4.x-*/_search',
                json=query,
                auth=(idx_user, idx_password),
                verify=False,
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            stats['error_msg'] = f'Cannot connect to Wazuh Indexer at {indexer_url} — check Indexer URL in Settings'
            return stats
        except requests.exceptions.Timeout:
            stats['error_msg'] = f'Connection to Wazuh Indexer timed out ({indexer_url})'
            return stats
        except Exception as e:
            stats['error_msg'] = f'Indexer error: {e}'
            return stats

        if resp.status_code == 429:
            if attempt < len(_retry_delays):
                logger.warning(f'Indexer rate limited (429) — retrying in {_retry_delays[attempt]}s (attempt {attempt + 1}/3)')
                continue
            stats['error_msg'] = 'Indexer rate limited (429) — too many requests. Will retry next run.'
            return stats

        if resp.status_code == 401:
            stats['error_msg'] = 'Indexer authentication failed — check Indexer Username/Password in Settings'
            return stats

        if resp.status_code == 404:
            stats['error_msg'] = 'Index wazuh-alerts-4.x-* not found — no alerts have been ingested yet'
            return stats

        try:
            resp.raise_for_status()
        except Exception as e:
            stats['error_msg'] = f'Indexer error: {e}'
            return stats

        break  # success

    hits = resp.json().get('hits', {}).get('hits', [])
    stats['fetched'] = len(hits)

    for hit in hits:
        raw = hit.get('_source', {})
        try:
            parsed = _parse_alert(raw)
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
            if created:
                stats['created'] += 1
                if alert.severity in ('CRITICAL', 'HIGH'):
                    from .pipeline import enqueue_pipeline
                    enqueue_pipeline(alert)
            else:
                stats['skipped'] += 1
        except Exception as e:
            logger.error(f"Error saving alert: {e}")
            stats['errors'] += 1

    return stats
