"""
Auto alert pipeline with sequential queue.

Queue guarantees:
  - Only ONE alert is analyzed at a time (no concurrent Ollama/MOPH calls)
  - Wazuh fetch is skipped if queue is not idle (worker busy or items pending)
  - MOPH retry logic is in moph_notifier.py

Pipeline steps per alert:
  Step 1  AI Analysis (Ollama)
          severity_assessment = CRITICAL/HIGH → Step 2
          severity_assessment = MEDIUM        → Step 4 (TheHive only)
          severity_assessment = LOW/INFO      → stop

  Step 2  Chat AI Analysis
          risk_level = Critical/High → Step 3 + Step 4
          risk_level other           → stop

  Step 3  MOPH Notify (LINE Flex Message)
  Step 4  TheHive incident (auto create)
"""
import json
import logging
import queue
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ── Queue & worker state ───────────────────────────────────────
_pipeline_queue = queue.Queue()
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_is_processing = False   # True while worker is actively running run_pipeline


def is_busy() -> bool:
    """True if worker is processing or queue has pending alerts."""
    return _is_processing or not _pipeline_queue.empty()


def queue_depth() -> int:
    return _pipeline_queue.qsize()


# ── Worker ─────────────────────────────────────────────────────

def _worker_loop():
    global _is_processing
    logger.info('Pipeline: worker thread started')
    while True:
        try:
            alert_id = _pipeline_queue.get(timeout=120)
        except queue.Empty:
            continue

        _is_processing = True
        try:
            from .models import Alert
            try:
                alert = Alert.objects.get(pk=alert_id)
            except Alert.DoesNotExist:
                logger.warning(f'Pipeline: alert_id={alert_id} not found in DB')
                continue
            run_pipeline(alert)
        except Exception as e:
            logger.error(f'Pipeline: worker error for alert_id={alert_id}: {e}')
        finally:
            _is_processing = False
            _pipeline_queue.task_done()
            # Close DB connection after each task to prevent idle connection accumulation
            try:
                from django.db import connection as _db_conn
                _db_conn.close()
            except Exception:
                pass


def _ensure_worker():
    global _worker_thread
    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name='pipeline-worker')
            _worker_thread.start()


def enqueue_pipeline(alert):
    """Add alert to sequential pipeline queue (replaces run_pipeline_in_thread)."""
    _ensure_worker()
    _pipeline_queue.put(alert.id)
    logger.info(
        f'Pipeline: alert {alert.id} [{alert.severity}] enqueued '
        f'(queue depth={_pipeline_queue.qsize()})'
    )


# ── TheHive: standalone push ───────────────────────────────────

def _push_to_thehive_auto(alert) -> tuple[bool, str]:
    """Create a TheHive case and save Incident to DB. Returns (ok, error_msg)."""
    from apps.config.models import IntegrationConfig
    from apps.incidents.models import Incident

    if alert.incidents.exists():
        return False, 'Already has incident'

    configs = {c.key: c.value for c in IntegrationConfig.objects.filter(
        key__in=['THEHIVE_URL', 'THEHIVE_API_KEY']
    )}
    thehive_url = configs.get('THEHIVE_URL', '').rstrip('/')
    api_key = configs.get('THEHIVE_API_KEY', '')

    if not thehive_url or not api_key:
        return False, 'TheHive URL or API Key not set'

    sev_map = {'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'INFO': 1}
    tags = list(set(list(alert.rule_groups or []) + [alert.severity, 'wazuh', 'auto']))
    if alert.mitre_id:
        tags.append(alert.mitre_id)

    ai   = getattr(alert, 'ai_analysis', None)
    chat = getattr(alert, 'ai_analysis_chat', None)

    description = (
        f"## Alert Details\n"
        f"| Field | Value |\n|---|---|\n"
        f"| Rule | {alert.rule_description} |\n"
        f"| Rule ID | {alert.rule_id} (Level {alert.rule_level}) |\n"
        f"| Agent | {alert.agent_name} ({alert.agent_ip or 'N/A'}) |\n"
        f"| Source IP | {alert.src_ip or 'N/A'} |\n"
        f"| MITRE ATT&CK | {alert.mitre_id or 'N/A'} |\n"
        f"| Timestamp | {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')} |\n"
        f"| Wazuh ID | {alert.wazuh_id} |\n"
    )
    if ai:
        description += (
            f"\n## AI Analysis (Ollama)\n"
            f"- **Attack Type**: {ai.attack_type}\n"
            f"- **Severity Assessment**: {ai.severity_assessment}\n"
            f"- **Summary**: {ai.summary}\n"
            f"- **Impact**: {ai.impact}\n"
            f"- **Recommendations**: {ai.recommendations}\n"
            f"- **False Positive**: {ai.false_positive_pct}%\n"
        )
    if chat:
        description += (
            f"\n## Chat AI Analysis\n"
            f"- **Risk Level**: {chat.risk_level}\n"
            f"- **Classification**: {chat.is_malicious}\n"
            f"- **Root Cause**: {chat.root_cause}\n"
            f"- **Recommended Action**: {chat.recommended_action}\n"
        )

    case_payload = {
        'title':       f'[{alert.severity}] {alert.rule_description[:120]}',
        'description': description,
        'severity':    sev_map.get(alert.severity, 2),
        'tags':        tags,
        'status':      'New',
        'source':      'SOC Dashboard',
        'sourceRef':   str(alert.wazuh_id)[:100],
    }

    try:
        req = urllib.request.Request(
            f'{thehive_url}/api/case',
            data=json.dumps(case_payload).encode(),
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return False, f'TheHive HTTP {e.code}: {e.read().decode()[:200]}'
    except Exception as e:
        return False, str(e)

    case_id     = result.get('_id') or result.get('id', '')
    case_number = result.get('caseId') or result.get('number', '')
    case_url    = f'{thehive_url}/cases/{case_id}/details'

    try:
        Incident.objects.create(
            alert=alert,
            thehive_case_id=f'#{case_number}' if case_number else case_id,
            title=case_payload['title'],
            status='New',
            severity=alert.severity,
            thehive_url=case_url,
        )
        logger.info(f'Pipeline: TheHive case #{case_number} created for alert {alert.id}')
        return True, ''
    except Exception as e:
        return False, f'Case created in TheHive but DB error: {e}'


# ── Pipeline logic ─────────────────────────────────────────────

def run_pipeline(alert):
    """
    Sequential pipeline — called by worker thread only (never call directly from web request).

    severity_assessment = CRITICAL/HIGH → Chat AI → if risk Critical/High → LINE + TheHive
    severity_assessment = MEDIUM        → TheHive only (no LINE, no Chat AI)
    severity_assessment = LOW/INFO      → stop
    """
    from .ai_analyzer import analyze_alert
    from .chat_analyzer import analyze_alert_chat
    from .models import AIAnalysis, AIAnalysisChat
    from apps.notifications.moph_notifier import send_moph_notify
    from apps.notifications.models import NotificationLog

    logger.info(f'Pipeline: start for alert {alert.id} [{alert.severity}]')

    # ── Step 1: AI Analysis ────────────────────────────────────
    ok = analyze_alert(alert)
    if not ok:
        logger.warning(f'Pipeline: AI analysis failed for alert {alert.id} — stop')
        return

    try:
        ai = AIAnalysis.objects.get(alert=alert)
    except AIAnalysis.DoesNotExist:
        logger.warning(f'Pipeline: AIAnalysis missing for alert {alert.id} — stop')
        return

    # ── MEDIUM path: TheHive only ──────────────────────────────
    if ai.severity_assessment == 'MEDIUM':
        logger.info(f'Pipeline: alert {alert.id} AI=MEDIUM → TheHive only')
        ok, err = _push_to_thehive_auto(alert)
        if not ok:
            logger.warning(f'Pipeline: TheHive failed for alert {alert.id}: {err}')
        return

    if ai.severity_assessment not in ('CRITICAL', 'HIGH'):
        logger.info(f'Pipeline: alert {alert.id} AI={ai.severity_assessment} → stop')
        return

    # ── Step 2: Chat AI Analysis ────────────────────────────────
    ok = analyze_alert_chat(alert)
    if not ok:
        logger.warning(f'Pipeline: Chat AI failed for alert {alert.id} — stop')
        return

    try:
        chat = AIAnalysisChat.objects.get(alert=alert)
    except AIAnalysisChat.DoesNotExist:
        logger.warning(f'Pipeline: AIAnalysisChat missing for alert {alert.id} — stop')
        return

    if chat.risk_level not in ('Critical', 'High'):
        logger.info(f'Pipeline: alert {alert.id} Chat={chat.risk_level} → stop')
        return

    # ── Step 3: MOPH Notify (sequential, with retry in send_moph_notify) ──
    ok, err = send_moph_notify(alert)
    NotificationLog.objects.create(
        alert=alert,
        channel='MOPH',
        status='sent' if ok else 'failed',
        message_preview=f'[{alert.severity}] {alert.rule_description[:100]}',
        error_message=err if not ok else '',
    )
    if ok:
        logger.info(f'Pipeline: MOPH Notify sent for alert {alert.id}')
    else:
        logger.warning(f'Pipeline: MOPH Notify failed for alert {alert.id}: {err}')

    # ── Step 4: TheHive incident ────────────────────────────────
    ok, err = _push_to_thehive_auto(alert)
    if not ok:
        logger.warning(f'Pipeline: TheHive failed for alert {alert.id}: {err}')
