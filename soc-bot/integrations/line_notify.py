"""
LINE Notify integration for SOC alert notifications.
API: https://notify-api.line.me/api/notify
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

LINE_NOTIFY_TOKEN = os.environ.get('LINE_NOTIFY_TOKEN', '')
LINE_NOTIFY_URL = 'https://notify-api.line.me/api/notify'

SEVERITY_EMOJI = {
    'CRITICAL': '🔴',
    'HIGH':     '🟠',
    'MEDIUM':   '🟡',
    'LOW':      '🟢',
    'INFO':     '⚪',
}

MESSAGE_TEMPLATE = """
{severity_emoji} [{severity}] SOC ALERT

📋 {rule_description}
🔢 Rule: {rule_id} (Level {rule_level})
🖥️  Agent: {agent_name}{agent_ip_str}
🌐 Source IP: {src_ip}
⏰ Time: {timestamp}

🤖 AI Analysis:
• Type: {attack_type}
• MITRE: {mitre}
• Impact: {impact}
• Actions: {recommendations}
• False Positive: {fp_pct}%

🔗 {dashboard_url}"""


def send_notification(alert: dict, ai_analysis: dict | None = None, dashboard_url: str = '') -> bool:
    """
    Send LINE Notify message for the given alert.
    Returns True if sent successfully, False otherwise.
    """
    if not LINE_NOTIFY_TOKEN:
        logger.debug("LINE Notify disabled (no token configured)")
        return False

    severity = alert.get('severity', 'UNKNOWN')
    agent_ip = alert.get('agent_ip')
    agent_ip_str = f" ({agent_ip})" if agent_ip else ""

    if ai_analysis:
        attack_type = ai_analysis.get('attack_type', 'Unknown')
        mitre = ai_analysis.get('mitre_technique', 'N/A')
        impact = ai_analysis.get('impact', 'N/A')[:80]
        recs = ai_analysis.get('recommendations', 'N/A')
        if isinstance(recs, list):
            recs = ', '.join(recs[:3])
        fp_pct = ai_analysis.get('false_positive_pct', 0)
    else:
        attack_type = 'Not analyzed'
        mitre = 'N/A'
        impact = 'Not analyzed'
        recs = 'Review manually'
        fp_pct = 0

    # Format timestamp
    timestamp = alert.get('timestamp', '')[:19].replace('T', ' ')

    # Build alert URL
    alert_url = dashboard_url
    if alert.get('dashboard_id'):
        alert_url = f"{dashboard_url}/alerts/{alert['dashboard_id']}/"

    message = MESSAGE_TEMPLATE.format(
        severity_emoji=SEVERITY_EMOJI.get(severity, '⚠️'),
        severity=severity,
        rule_description=alert.get('rule_description', '')[:80],
        rule_id=alert.get('rule_id', ''),
        rule_level=alert.get('rule_level', ''),
        agent_name=alert.get('agent_name', 'unknown'),
        agent_ip_str=agent_ip_str,
        src_ip=alert.get('src_ip') or 'N/A',
        timestamp=timestamp,
        attack_type=attack_type[:60],
        mitre=mitre,
        impact=impact,
        recommendations=str(recs)[:100],
        fp_pct=fp_pct,
        dashboard_url=alert_url or '#',
    )

    try:
        resp = requests.post(
            LINE_NOTIFY_URL,
            headers={'Authorization': f'Bearer {LINE_NOTIFY_TOKEN}'},
            data={'message': message},
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info(f"LINE notification sent for alert {alert.get('wazuh_id', '')}")
            return True
        else:
            logger.error(f"LINE Notify returned {resp.status_code}: {resp.text}")
            return False

    except requests.exceptions.ConnectionError:
        logger.error("Cannot reach LINE Notify API (network issue?)")
        return False
    except Exception as e:
        logger.error(f"LINE notification failed: {e}")
        return False


def build_message_preview(alert: dict, ai_analysis: dict | None = None) -> str:
    """Build a short preview of the notification message for logging."""
    severity = alert.get('severity', 'UNKNOWN')
    emoji = SEVERITY_EMOJI.get(severity, '⚠️')
    rule_desc = alert.get('rule_description', '')[:50]
    agent = alert.get('agent_name', 'unknown')
    attack = ai_analysis.get('attack_type', 'N/A')[:30] if ai_analysis else 'N/A'
    return f"{emoji} [{severity}] {rule_desc} | Agent: {agent} | Type: {attack}"
