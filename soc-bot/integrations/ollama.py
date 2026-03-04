"""
Ollama LLM client for AI-powered alert analysis.
API docs: https://github.com/ollama/ollama/blob/main/docs/api.md
"""
import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'openchat')
OLLAMA_TIMEOUT = int(os.environ.get('OLLAMA_TIMEOUT', '120'))

PROMPT_TEMPLATE = """You are an expert SOC analyst. Analyze this Wazuh security alert and respond ONLY with valid JSON.

Alert Details:
- Rule ID: {rule_id}
- Rule Level: {rule_level}
- Description: {rule_description}
- Agent: {agent_name} ({agent_ip})
- Source IP: {src_ip}
- Rule Groups: {rule_groups}
- MITRE ID: {mitre_id}
- Timestamp: {timestamp}

Respond with this EXACT JSON structure (no markdown, no extra text):
{{
  "attack_type": "Brief attack type classification",
  "mitre_technique": "T1xxx or N/A",
  "severity_assessment": "CRITICAL or HIGH or MEDIUM or LOW",
  "impact": "Brief impact description (1-2 sentences)",
  "recommendations": "Comma-separated list of 2-3 recommended actions",
  "false_positive_pct": 0,
  "summary": "One sentence summary of this security event"
}}"""


def analyze_alert(alert: dict, retries: int = 2) -> dict | None:
    """
    Send alert to Ollama for AI analysis.
    Returns parsed JSON dict or None on failure.
    """
    prompt = PROMPT_TEMPLATE.format(
        rule_id=alert.get('rule_id', ''),
        rule_level=alert.get('rule_level', 0),
        rule_description=alert.get('rule_description', ''),
        agent_name=alert.get('agent_name', ''),
        agent_ip=alert.get('agent_ip', 'N/A'),
        src_ip=alert.get('src_ip', 'N/A'),
        rule_groups=', '.join(alert.get('rule_groups', [])),
        mitre_id=alert.get('mitre_id', 'N/A'),
        timestamp=alert.get('timestamp', ''),
    )

    payload = {
        'model': OLLAMA_MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {
            'temperature': 0.1,  # Low temperature for consistent structured output
            'num_predict': 400,
        },
    }

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            raw_response = resp.json().get('response', '')

            # Parse JSON from response
            analysis = _parse_json_response(raw_response)
            if analysis:
                logger.info(f"AI analysis complete: {analysis.get('attack_type', 'unknown')}")
                return {**analysis, 'raw_response': raw_response}
            else:
                logger.warning(f"Could not parse AI response (attempt {attempt + 1}): {raw_response[:200]}")

        except requests.exceptions.ConnectionError:
            logger.warning(f"Ollama not reachable at {OLLAMA_URL}")
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama timeout on attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"Ollama error on attempt {attempt + 1}: {e}")

        if attempt < retries:
            time.sleep(2)

    return None


def _parse_json_response(text: str) -> dict | None:
    """Extract and parse JSON from LLM response text."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from code block or surrounding text
    import re
    patterns = [
        r'```json\s*(\{.*?\})\s*```',
        r'```\s*(\{.*?\})\s*```',
        r'(\{[^{}]*"attack_type"[^{}]*\})',
        r'(\{.*?\})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    return None


def check_ollama_available() -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m['name'] for m in resp.json().get('models', [])]
            available = any(OLLAMA_MODEL in m for m in models)
            if not available:
                logger.warning(f"Model '{OLLAMA_MODEL}' not found in Ollama. Available: {models}")
            return True
        return False
    except Exception:
        return False
