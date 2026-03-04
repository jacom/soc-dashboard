import json
import logging
import time
import urllib.request
import urllib.error
from django.utils import timezone

logger = logging.getLogger(__name__)

SEVERITY_BG = {
    'CRITICAL': '#FFD5D5',
    'HIGH':     '#FFF3CD',
    'MEDIUM':   '#D5E8FF',
    'LOW':      '#D5FFE0',
    'INFO':     '#E8E8E8',
}
SEVERITY_TEXT = {
    'CRITICAL': '#CC0000',
    'HIGH':     '#8B6914',
    'MEDIUM':   '#1A5FBF',
    'LOW':      '#1A7A2F',
    'INFO':     '#555555',
}


def _get_config():
    from apps.config.models import IntegrationConfig
    keys = [
        'MOPH_NOTIFY_URL', 'MOPH_NOTIFY_CLIENT_KEY', 'MOPH_NOTIFY_SECRET_KEY',
        'MOPH_IMG_CRITICAL', 'MOPH_IMG_HIGH', 'MOPH_IMG_MEDIUM',
        'MOPH_IMG_LOW', 'MOPH_IMG_INFO',
    ]
    return {c.key: c.value for c in IntegrationConfig.objects.filter(key__in=keys)}


def _header_image_url(configs, severity: str) -> str:
    return (
        configs.get(f'MOPH_IMG_{severity}', '')
        or configs.get('MOPH_IMG_MEDIUM', '')
    )


def _detail_row(label: str, value: str, value_bold=True) -> dict:
    return {
        'type': 'box',
        'layout': 'horizontal',
        'contents': [
            {
                'type': 'text', 'text': label,
                'flex': 0, 'size': 'sm',
                'align': 'start', 'gravity': 'center',
                'color': '#888888',
            },
            {
                'type': 'text', 'text': str(value) if value else '—',
                'size': 'sm', 'align': 'start',
                'gravity': 'center', 'margin': 'md',
                'weight': 'bold' if value_bold else 'regular',
                'wrap': True, 'color': '#333333',
            },
        ],
    }


def build_flex_payload(alert) -> dict:
    configs    = _get_config()
    severity   = alert.severity
    bg_color   = SEVERITY_BG.get(severity, '#E8E8E8')
    text_color = SEVERITY_TEXT.get(severity, '#333333')
    header_img = _header_image_url(configs, severity)
    local_ts   = timezone.localtime(alert.timestamp)
    date_str   = local_ts.strftime('%d/%m/%Y')
    time_str   = local_ts.strftime('%H:%M:%S')

    # ── Header (severity image) ──────────────────────────────────────
    header = {
        'type': 'box',
        'layout': 'vertical',
        'paddingTop': '20px',
        'paddingBottom': '0px',
        'paddingStart': '0px',
        'paddingEnd': '0px',
        'contents': [
            {
                'type': 'image',
                'url': header_img,
                'size': 'full',
                'aspectRatio': '3120:885',
                'aspectMode': 'cover',
            }
        ],
    } if header_img else None

    # ── Body ─────────────────────────────────────────────────────────
    body_contents = [
        # 1. Title badge
        {
            'type': 'box',
            'layout': 'vertical',
            'backgroundColor': bg_color,
            'cornerRadius': '15px',
            'margin': 'xs',
            'paddingTop': 'lg',
            'paddingBottom': 'lg',
            'paddingStart': '8px',
            'paddingEnd': '8px',
            'contents': [
                {
                    'type': 'text',
                    'text': f'[{severity}] Security Alert',
                    'size': 'lg',
                    'weight': 'bold',
                    'color': text_color,
                    'align': 'center',
                    'adjustMode': 'shrink-to-fit',
                }
            ],
        },
        # 2. Rule description
        {
            'type': 'box',
            'layout': 'vertical',
            'margin': '20px',
            'contents': [
                {
                    'type': 'text',
                    'text': alert.rule_description[:120],
                    'size': '15px',
                    'wrap': True,
                    'align': 'center',
                    'gravity': 'center',
                    'adjustMode': 'shrink-to-fit',
                    'color': '#2D2D2D',
                }
            ],
        },
        # 3. Separator
        {'type': 'separator', 'margin': '18px'},
        # 4. Detail rows
        {
            'type': 'box',
            'layout': 'vertical',
            'margin': '13px',
            'spacing': 'sm',
            'contents': [
                _detail_row('Alert ID', f'#{alert.id}'),
                {'type': 'separator', 'margin': 'sm'},
                _detail_row('Agent',    alert.agent_name),
                {'type': 'separator', 'margin': 'sm'},
                _detail_row('Agent IP', str(alert.agent_ip) if alert.agent_ip else '—'),
                {'type': 'separator', 'margin': 'sm'},
                _detail_row('Src IP',   str(alert.src_ip) if alert.src_ip else '—'),
                {'type': 'separator', 'margin': 'sm'},
                _detail_row('Rule Lv.', f'{alert.rule_id} (Level {alert.rule_level})'),
            ] + ([
                {'type': 'separator', 'margin': 'sm'},
                _detail_row('MITRE', alert.mitre_id),
            ] if alert.mitre_id else []),
        },
        # 5. Separator
        {'type': 'separator', 'margin': '18px'},
        # 6. Date / Time
        {
            'type': 'box',
            'layout': 'horizontal',
            'margin': '13px',
            'contents': [
                {
                    'type': 'box',
                    'layout': 'horizontal',
                    'flex': 1,
                    'contents': [
                        {'type': 'text', 'text': 'วันที่', 'flex': 0,
                         'size': 'sm', 'align': 'start', 'gravity': 'center'},
                        {'type': 'text', 'text': date_str, 'weight': 'bold',
                         'size': 'sm', 'align': 'start', 'gravity': 'center', 'margin': 'md'},
                    ],
                },
                {'type': 'separator'},
                {
                    'type': 'box',
                    'layout': 'horizontal',
                    'flex': 1,
                    'contents': [
                        {'type': 'text', 'text': 'เวลา', 'flex': 0,
                         'size': 'sm', 'margin': 'lg'},
                        {'type': 'text', 'text': time_str, 'weight': 'bold',
                         'size': 'sm', 'align': 'start', 'gravity': 'center', 'margin': 'md'},
                    ],
                },
            ],
        },
    ]

    bubble = {
        'type': 'bubble',
        'size': 'mega',
        'body': {
            'type': 'box',
            'layout': 'vertical',
            'contents': body_contents,
        },
    }
    if header:
        bubble['header'] = header

    alt_text = f'[{severity}] #{alert.id} {alert.rule_description[:55]}'

    # messages เป็น array ตามที่ API กำหนด
    return {
        'messages': [
            {
                'type': 'flex',
                'altText': alt_text,
                'contents': bubble,
            }
        ]
    }


_RETRY_DELAYS = [5, 10, 15]   # backoff วินาที ระหว่าง retry


def send_moph_notify(alert) -> tuple[bool, str]:
    """ส่ง LINE Flex Message ผ่าน MOPH Notify พร้อม retry 3 ครั้ง"""
    configs    = _get_config()
    base_url   = configs.get('MOPH_NOTIFY_URL', '').rstrip('/')
    client_key = configs.get('MOPH_NOTIFY_CLIENT_KEY', '')
    secret_key = configs.get('MOPH_NOTIFY_SECRET_KEY', '')

    if not base_url or not client_key or not secret_key:
        return False, 'MOPH Notify ยังไม่ได้ตั้งค่า URL / Client Key / Secret Key'

    payload_bytes = json.dumps(build_flex_payload(alert), ensure_ascii=False).encode('utf-8')
    endpoint = f'{base_url}/api/notify/send'
    headers  = {
        'Content-Type': 'application/json',
        'client-key':   client_key,
        'secret-key':   secret_key,
    }

    last_err = ''
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.info(f'MOPH Notify: alert {alert.id} retry {attempt}/3 — waiting {delay}s')
            time.sleep(delay)

        req = urllib.request.Request(endpoint, data=payload_bytes, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode()
                logger.info(f'MOPH Notify sent for alert {alert.id} (attempt {attempt+1}): {body[:100]}')
                return True, ''
        except urllib.error.HTTPError as e:
            last_err = f'HTTP {e.code}: {e.read().decode()[:200]}'
            logger.warning(f'MOPH Notify attempt {attempt+1} HTTP {e.code} for alert {alert.id}')
        except Exception as e:
            last_err = str(e)
            logger.warning(f'MOPH Notify attempt {attempt+1} error for alert {alert.id}: {e}')

    logger.error(f'MOPH Notify failed after {len(_RETRY_DELAYS)+1} attempts for alert {alert.id}: {last_err}')
    return False, last_err
