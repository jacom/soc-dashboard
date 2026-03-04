import json
import logging
import re
import urllib.request
import urllib.error

from .models import AIAnalysisChat
from .ai_analyzer import _ollama_lock

logger = logging.getLogger(__name__)


def _get_config():
    from apps.config.models import IntegrationConfig
    configs = {c.key: c.value for c in IntegrationConfig.objects.filter(
        key__in=['OPENAI_URL', 'OPENAI_MODEL', 'OPENAI_API_KEY']
    )}
    return (
        configs.get('OPENAI_URL', 'http://localhost:11434').rstrip('/'),
        configs.get('OPENAI_MODEL', 'openchat:latest'),
        configs.get('OPENAI_API_KEY', ''),
    )


def _build_event_json(alert) -> dict:
    """Extract structured fields from alert for the chat prompt."""
    raw = alert.raw_data or {}
    win = raw.get('data', {}).get('win', {})
    sys_data = win.get('system', {})
    event_data = win.get('eventdata', {})

    provider = sys_data.get('providerName', '') or raw.get('data', {}).get('srcuser', '')
    event_id = sys_data.get('eventID', '') or sys_data.get('eventId', '')
    win_severity = sys_data.get('level', '') or sys_data.get('keywords', '')

    # Message: try eventdata first, fallback to rule description
    message = (
        event_data.get('data', '')
        or event_data.get('CommandLine', '')
        or raw.get('data', {}).get('message', '')
        or alert.rule_description
    )

    return {
        'event_source': alert.rule_groups[0] if alert.rule_groups else 'unknown',
        'provider': provider,
        'event_id': event_id,
        'severity': win_severity or alert.severity,
        'hostname': alert.agent_name,
        'agent_ip': str(alert.agent_ip) if alert.agent_ip else '',
        'src_ip': str(alert.src_ip) if alert.src_ip else '',
        'rule_level': alert.rule_level,
        'rule_description': alert.rule_description,
        'message': str(message)[:800],
        'groups': alert.rule_groups or [],
        'mitre': alert.mitre_id or '',
        'timestamp': alert.timestamp.isoformat(),
    }


SYSTEM_PROMPT = (
    "You are a SOC security analyst. Analyze the security log and respond ONLY with valid JSON. "
    "No markdown, no extra text."
)

USER_PROMPT_TEMPLATE = """\
Analyze this security event log and respond with JSON only.
NOTE: Wazuh has already assessed this alert as severity={wazuh_severity} (rule level {rule_level}/15). \
Use this as a strong baseline when determining risk_level.

{log_json}

Respond with this exact JSON format (root_cause and recommended_action in English, _th fields in Thai):
{{
  "risk_level": "Low|Medium|High|Critical",
  "is_malicious": "malicious|misconfiguration|benign|unknown",
  "root_cause": "Possible root cause in English",
  "root_cause_th": "สาเหตุที่เป็นไปได้ เป็นภาษาไทย",
  "recommended_action": "Recommended actions in English",
  "recommended_action_th": "การดำเนินการที่แนะนำ เป็นภาษาไทย",
  "should_create_incident": true or false
}}"""


def _parse(text: str) -> dict:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return {}
    raw = match.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r'(?<=": ")([^"]*?)(?=")',
                         lambda m: m.group(0).replace('\n', ' ').replace('\r', ''), raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


def analyze_alert_chat(alert) -> bool:
    """Call OpenAI-compatible chat completions API and save AIAnalysisChat."""
    if AIAnalysisChat.objects.filter(alert=alert).exists():
        return True

    url, model, api_key = _get_config()
    if not url:
        return False

    event_json = json.dumps(_build_event_json(alert), ensure_ascii=False, indent=2)
    user_content = USER_PROMPT_TEMPLATE.format(
        log_json=event_json,
        wazuh_severity=alert.severity,
        rule_level=alert.rule_level,
    )

    payload = json.dumps({
        'model': model,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': user_content},
        ],
        'temperature': 0.2,
        'stream': False,
    }).encode()

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}' if api_key else 'Bearer ollama',
    }

    if not _ollama_lock.acquire(blocking=False):
        logger.warning('Ollama is busy — skipping chat analysis for alert %s', alert.id)
        return False
    try:
        req = urllib.request.Request(
            f'{url}/v1/chat/completions',
            data=payload,
            headers=headers,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
        raw_response = result['choices'][0]['message']['content']
    except urllib.error.URLError as e:
        logger.warning(f'Chat API connection error: {e.reason}')
        return False
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.warning(f'Chat API response parse error: {e}')
        return False
    except Exception as e:
        logger.error(f'Chat API error: {e}')
        return False
    finally:
        _ollama_lock.release()

    data = _parse(raw_response)
    if not data:
        logger.warning(f'Could not parse chat response for alert {alert.id}: {raw_response[:200]}')
        return False

    valid_risks = {'Low', 'Medium', 'High', 'Critical'}
    risk_level = data.get('risk_level', 'Medium')
    if risk_level not in valid_risks:
        risk_level = 'Medium'

    should_inc = data.get('should_create_incident', False)
    if isinstance(should_inc, str):
        should_inc = should_inc.lower() in ('true', 'yes', '1')

    try:
        AIAnalysisChat.objects.create(
            alert=alert,
            model_used=model,
            risk_level=risk_level,
            is_malicious=str(data.get('is_malicious', 'unknown'))[:50],
            root_cause=str(data.get('root_cause', '')),
            root_cause_th=str(data.get('root_cause_th', '')),
            recommended_action=str(data.get('recommended_action', '')),
            recommended_action_th=str(data.get('recommended_action_th', '')),
            should_create_incident=bool(should_inc),
            raw_response=raw_response,
        )
        logger.info(f'Chat analysis saved for alert {alert.id}')
        return True
    except Exception as e:
        logger.error(f'Error saving chat analysis for alert {alert.id}: {e}')
        return False
