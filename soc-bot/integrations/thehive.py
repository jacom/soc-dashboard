"""
TheHive 5 REST API client for case management.
API docs: https://docs.strangebee.com/thehive/api-docs/
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

THEHIVE_URL = os.environ.get('THEHIVE_URL', '')
THEHIVE_API_KEY = os.environ.get('THEHIVE_API_KEY', '')
THEHIVE_TLP = int(os.environ.get('THEHIVE_TLP', '2'))
THEHIVE_PAP = int(os.environ.get('THEHIVE_PAP', '2'))


def _headers() -> dict:
    return {
        'Authorization': f'Bearer {THEHIVE_API_KEY}',
        'Content-Type': 'application/json',
    }


def _severity_to_int(severity: str) -> int:
    """Convert severity string to TheHive severity integer."""
    return {
        'CRITICAL': 4,
        'HIGH': 3,
        'MEDIUM': 2,
        'LOW': 1,
        'INFO': 1,
    }.get(severity, 2)


def create_case(alert: dict, ai_analysis: dict | None = None) -> dict | None:
    """
    Create a case in TheHive for the given alert.
    Returns dict with case_id and URL, or None on failure.
    """
    if not THEHIVE_URL or not THEHIVE_API_KEY:
        logger.debug("TheHive integration disabled (no URL or API key)")
        return None

    severity_int = _severity_to_int(alert.get('severity', 'MEDIUM'))

    # Build case description
    description = _build_description(alert, ai_analysis)

    case_data = {
        'title': f"[{alert.get('severity')}] {alert.get('rule_description', 'Wazuh Alert')[:200]}",
        'description': description,
        'severity': severity_int,
        'tlp': THEHIVE_TLP,
        'pap': THEHIVE_PAP,
        'tags': [
            'wazuh',
            'soc-bot',
            f"agent:{alert.get('agent_name', 'unknown')}",
            f"rule:{alert.get('rule_id', '')}",
            alert.get('severity', 'UNKNOWN').lower(),
        ],
        'tasks': _build_tasks(alert, ai_analysis),
    }

    # Add MITRE tag if available
    if alert.get('mitre_id'):
        case_data['tags'].append(f"mitre:{alert['mitre_id']}")

    try:
        resp = requests.post(
            f"{THEHIVE_URL}/api/case",
            json=case_data,
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        case = resp.json()
        case_id = case.get('_id', case.get('id', ''))
        case_num = case.get('caseId', case.get('number', ''))
        case_url = f"{THEHIVE_URL}/cases/{case_num}/details"

        logger.info(f"TheHive case created: #{case_num} (ID: {case_id})")
        return {
            'case_id': case_id,
            'case_number': str(case_num),
            'url': case_url,
            'title': case_data['title'],
        }

    except requests.exceptions.ConnectionError:
        logger.warning(f"TheHive not reachable at {THEHIVE_URL}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"TheHive API error: {e} - {e.response.text if e.response else ''}")
        return None
    except Exception as e:
        logger.error(f"TheHive case creation failed: {e}")
        return None


def _build_description(alert: dict, ai_analysis: dict | None) -> str:
    """Build markdown description for TheHive case."""
    lines = [
        f"## Wazuh Alert — {alert.get('rule_description', '')}",
        "",
        "### Alert Details",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Wazuh ID** | `{alert.get('wazuh_id', '')}` |",
        f"| **Rule ID** | {alert.get('rule_id', '')} |",
        f"| **Rule Level** | {alert.get('rule_level', '')} |",
        f"| **Agent** | {alert.get('agent_name', '')} ({alert.get('agent_ip', 'N/A')}) |",
        f"| **Source IP** | {alert.get('src_ip', 'N/A')} |",
        f"| **Timestamp** | {alert.get('timestamp', '')} |",
        f"| **Severity** | {alert.get('severity', '')} |",
    ]

    if alert.get('mitre_id'):
        lines.append(f"| **MITRE ATT&CK** | {alert['mitre_id']} |")

    if ai_analysis:
        lines.extend([
            "",
            "### AI Security Analysis",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Attack Type** | {ai_analysis.get('attack_type', 'N/A')} |",
            f"| **MITRE Technique** | {ai_analysis.get('mitre_technique', 'N/A')} |",
            f"| **Severity Assessment** | {ai_analysis.get('severity_assessment', 'N/A')} |",
            f"| **False Positive %** | {ai_analysis.get('false_positive_pct', 'N/A')}% |",
            "",
            f"**Summary:** {ai_analysis.get('summary', 'N/A')}",
            "",
            f"**Impact:** {ai_analysis.get('impact', 'N/A')}",
            "",
            f"**Recommendations:** {ai_analysis.get('recommendations', 'N/A')}",
        ])

    return "\n".join(lines)


def _build_tasks(alert: dict, ai_analysis: dict | None) -> list:
    """Build default investigation tasks for the case."""
    tasks = [
        {'title': 'Verify alert validity and rule trigger conditions', 'status': 'Waiting'},
        {'title': f"Investigate agent: {alert.get('agent_name', 'unknown')}", 'status': 'Waiting'},
    ]

    if alert.get('src_ip'):
        tasks.append({
            'title': f"Investigate source IP: {alert['src_ip']}",
            'status': 'Waiting',
        })

    if ai_analysis:
        recs = ai_analysis.get('recommendations', '')
        if recs:
            tasks.append({
                'title': f"Apply AI recommendations: {str(recs)[:100]}",
                'status': 'Waiting',
            })

    tasks.append({'title': 'Document findings and close case', 'status': 'Waiting'})
    return tasks
