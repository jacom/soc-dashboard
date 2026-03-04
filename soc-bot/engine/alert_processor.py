"""
Alert processor: orchestrates the full pipeline for each incoming alert.
"""
import logging
import os

import redis

from engine.rule_engine import classify_severity, get_actions, load_config
from integrations import ollama, thehive, line_notify
from integrations.dashboard import save_alert_to_dashboard, save_incident, save_notification

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/2')
DASHBOARD_URL = os.environ.get('DASHBOARD_URL', 'http://localhost:8002')
DASHBOARD_FRONTEND_URL = os.environ.get('DJANGO_DASHBOARD_URL', 'http://localhost:8500')

# Redis TTL for dedup keys (24 hours)
DEDUP_TTL = 86400
DEDUP_PREFIX = 'soc:processed:'


def get_redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def is_already_processed(wazuh_id: str, r: redis.Redis) -> bool:
    """Check if this alert has already been processed (deduplication)."""
    key = f"{DEDUP_PREFIX}{wazuh_id}"
    return r.exists(key) == 1


def mark_processed(wazuh_id: str, r: redis.Redis) -> None:
    """Mark alert as processed in Redis."""
    key = f"{DEDUP_PREFIX}{wazuh_id}"
    r.setex(key, DEDUP_TTL, '1')


def process_alert(parsed_alert: dict, r: redis.Redis, config: dict | None = None) -> bool:
    """
    Full pipeline for a single alert:
    1. Dedup check
    2. Classify severity
    3. Execute actions (AI analysis, TheHive, LINE, Dashboard)

    Returns True if alert was processed, False if skipped.
    """
    if config is None:
        config = load_config()

    wazuh_id = parsed_alert.get('wazuh_id', '')

    # Skip if already processed
    if is_already_processed(wazuh_id, r):
        logger.debug(f"Skipping already-processed alert: {wazuh_id}")
        return False

    # Classify severity
    rule_level = parsed_alert.get('rule_level', 0)
    severity = classify_severity(rule_level, config)
    parsed_alert['severity'] = severity

    actions = get_actions(severity, config)
    logger.info(f"Processing [{severity}] alert: {parsed_alert.get('rule_description', '')[:60]} (Level {rule_level})")

    ai_analysis = None
    dashboard_id = None

    # 1. AI Analysis
    if 'ai_analyze' in actions:
        logger.debug("Running AI analysis...")
        ai_analysis = ollama.analyze_alert(parsed_alert)
        if ai_analysis:
            logger.info(f"  AI: {ai_analysis.get('attack_type')} ({ai_analysis.get('false_positive_pct')}% FP)")
        else:
            logger.warning("  AI analysis returned no result")

    # 2. Save to Dashboard (get the dashboard alert ID for links)
    if 'save_dashboard' in actions:
        dashboard_id = save_alert_to_dashboard(parsed_alert, ai_analysis)
        if dashboard_id:
            parsed_alert['dashboard_id'] = dashboard_id
            logger.info(f"  Saved to dashboard: Alert #{dashboard_id}")

    # 3. Create TheHive case
    if 'create_thehive' in actions:
        logger.debug("Creating TheHive case...")
        case_result = thehive.create_case(parsed_alert, ai_analysis)
        if case_result and dashboard_id:
            # Save incident record to dashboard
            save_incident(
                alert_id=dashboard_id,
                case_id=case_result.get('case_id', case_result.get('case_number', '')),
                title=case_result.get('title', ''),
                status='New',
                severity=severity,
                case_url=case_result.get('url', ''),
            )
            logger.info(f"  TheHive case created: {case_result.get('case_number', '')}")

    # 4. LINE Notify
    if 'notify_line' in actions:
        logger.debug("Sending LINE notification...")
        success = line_notify.send_notification(
            parsed_alert,
            ai_analysis=ai_analysis,
            dashboard_url=DASHBOARD_FRONTEND_URL,
        )
        if dashboard_id:
            status = 'sent' if success else 'failed'
            preview = line_notify.build_message_preview(parsed_alert, ai_analysis)
            save_notification(
                alert_id=dashboard_id,
                channel='LINE',
                status=status,
                message_preview=preview,
            )
        logger.info(f"  LINE notification: {'sent' if success else 'failed'}")

    # Mark as processed in Redis
    mark_processed(wazuh_id, r)
    return True


def process_batch(alerts: list[dict], r: redis.Redis, config: dict | None = None) -> tuple[int, int]:
    """
    Process a batch of parsed alerts.
    Returns (processed_count, skipped_count).
    """
    if config is None:
        config = load_config()

    processed = 0
    skipped = 0

    for alert in alerts:
        try:
            was_processed = process_alert(alert, r, config)
            if was_processed:
                processed += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error(f"Error processing alert {alert.get('wazuh_id', '')}: {e}", exc_info=True)
            skipped += 1

    return processed, skipped
