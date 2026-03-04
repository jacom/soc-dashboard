import json
import logging
import re
import threading

import requests

from .models import AIAnalysis

logger = logging.getLogger(__name__)

# Prevent concurrent Ollama requests from crashing the server (OOM)
_ollama_lock = threading.Semaphore(1)


def _get_ollama_config():
    from apps.config.models import IntegrationConfig
    configs = {
        c.key: c.value
        for c in IntegrationConfig.objects.filter(key__in=['OLLAMA_URL', 'OLLAMA_MODEL'])
    }
    return (
        configs.get('OLLAMA_URL', 'http://localhost:11434').rstrip('/'),
        configs.get('OLLAMA_MODEL', 'openchat'),
    )


def _build_prompt(alert) -> str:
    import json as _json
    from .chat_analyzer import _build_event_json
    event_json = _json.dumps(_build_event_json(alert), ensure_ascii=False, indent=2)

    return f"""You are a cybersecurity SOC analyst. Analyze the security alert below and respond with valid JSON only — no markdown, no code block, no extra text.

Each text field must have TWO versions: English (_en) and Thai (_th).
Use precise cybersecurity terminology in English. For Thai, use natural Thai security vocabulary — do NOT translate technical terms word-for-word if it sounds unnatural.

Alert data:
{event_json}

Respond with exactly this JSON structure:
{{
  "attack_type_en": "Short attack type name in English, e.g. SSH Brute Force, Port Scan, Rootcheck Violation",
  "attack_type_th": "ชื่อประเภทการโจมตีสั้นๆ เป็นภาษาไทย เช่น การโจมตี SSH Brute Force, การสแกนพอร์ต",
  "mitre_technique": "MITRE ATT&CK ID or empty string e.g. T1110.001",
  "severity_assessment": "CRITICAL|HIGH|MEDIUM|LOW|INFO",
  "false_positive_pct": <integer 0-100>,
  "summary_en": "1-2 sentence summary of what happened in English",
  "summary_th": "สรุปเหตุการณ์ 1-2 ประโยคเป็นภาษาไทย",
  "impact_en": "Potential impact if this is a real attack, in English",
  "impact_th": "ผลกระทบที่อาจเกิดขึ้นหากเป็นการโจมตีจริง เป็นภาษาไทย",
  "recommendations_en": "Immediate actions to take in English. If src_ip exists, include block recommendation",
  "recommendations_th": "การดำเนินการเร่งด่วนเป็นภาษาไทย หากมี src_ip ให้ระบุการบล็อกด้วย",
  "remediation_steps_en": "Detailed steps separated by | e.g. 1.Investigate logs | 2.Block IP x.x.x.x | 3.Update system",
  "remediation_steps_th": "ขั้นตอนละเอียดคั่นด้วย | เช่น 1.ตรวจสอบ log | 2.บล็อก IP x.x.x.x | 3.อัปเดตระบบ"
}}"""


def _parse_response(text: str) -> dict:
    """Extract JSON from Ollama response, handling markdown code blocks and literal newlines."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return {}
    raw = match.group()
    # Try as-is first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Replace literal newlines inside quoted strings with space
    cleaned = re.sub(r'(?<=": ")([^"]*?)(?=")', lambda m: m.group(0).replace('\n', ' ').replace('\r', ''), raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    return {}


def analyze_alert(alert) -> bool:
    """Call Ollama, parse response, save AIAnalysis. Returns True if successful."""
    if AIAnalysis.objects.filter(alert=alert).exists():
        return True

    ollama_url, ollama_model = _get_ollama_config()
    if not ollama_url:
        return False

    if not _ollama_lock.acquire(blocking=False):
        logger.warning('Ollama is busy — skipping analysis for alert %s', alert.id)
        return False
    try:
        resp = requests.post(
            f'{ollama_url}/api/generate',
            json={'model': ollama_model, 'prompt': _build_prompt(alert), 'stream': False},
            timeout=300,
        )
        resp.raise_for_status()
        raw_response = resp.json().get('response', '')
    except requests.exceptions.ConnectionError:
        logger.warning(f'Cannot connect to Ollama at {ollama_url}')
        return False
    except requests.exceptions.Timeout:
        logger.warning('Ollama request timed out')
        return False
    except Exception as e:
        logger.error(f'Ollama error: {e}')
        return False
    finally:
        _ollama_lock.release()

    data = _parse_response(raw_response)
    if not data:
        logger.warning(f'Could not parse Ollama response for alert {alert.id}')
        return False

    valid_severities = {'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'}
    severity_assessment = data.get('severity_assessment', alert.severity)
    if severity_assessment not in valid_severities:
        severity_assessment = alert.severity

    try:
        fp_pct = max(0, min(100, int(data.get('false_positive_pct', 0))))
    except (ValueError, TypeError):
        fp_pct = 0

    try:
        AIAnalysis.objects.create(
            alert=alert,
            # Thai fields
            attack_type=str(data.get('attack_type_th') or data.get('attack_type', 'Unknown'))[:200],
            summary=str(data.get('summary_th') or data.get('summary', '')),
            impact=str(data.get('impact_th') or data.get('impact', '')),
            recommendations=str(data.get('recommendations_th') or data.get('recommendations', '')),
            remediation_steps=str(data.get('remediation_steps_th') or data.get('remediation_steps', '')),
            # English fields
            attack_type_en=str(data.get('attack_type_en', ''))[:200],
            summary_en=str(data.get('summary_en', '')),
            impact_en=str(data.get('impact_en', '')),
            recommendations_en=str(data.get('recommendations_en', '')),
            remediation_steps_en=str(data.get('remediation_steps_en', '')),
            # Common
            mitre_technique=str(data.get('mitre_technique', ''))[:50],
            severity_assessment=severity_assessment,
            false_positive_pct=fp_pct,
            raw_response=raw_response,
        )
        logger.info(f'AI analysis saved for alert {alert.id}')
        return True
    except Exception as e:
        logger.error(f'Error saving AI analysis for alert {alert.id}: {e}')
        return False
