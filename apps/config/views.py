import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import ssl
import base64
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from .models import IntegrationConfig

from django.conf import settings as _settings
SOC_BOT_ENV_PATH = str(_settings.BASE_DIR / 'soc-bot' / '.env')

GROUPS = ['wazuh', 'ollama', 'openai', 'thehive', 'line', 'moph', 'system']

# Keys to include in .env file (order matters)
ENV_SECTIONS = {
    'wazuh': '# Wazuh API',
    'ollama': '# Ollama',
    'thehive': '# TheHive (set to empty string to disable)',
    'line': '# LINE Notify (set to empty string to disable)',
    'system': '# Polling / System',
}


def _get_configs_by_group():
    configs = IntegrationConfig.objects.all()
    grouped = {g: [] for g in GROUPS}
    for cfg in configs:
        if cfg.group in grouped:
            grouped[cfg.group].append(cfg)
    return grouped


@login_required
def settings_view(request):
    if request.method == 'POST':
        for key, val in request.POST.items():
            if key.startswith('cfg_'):
                cfg_key = key[4:]  # strip 'cfg_' prefix
                IntegrationConfig.objects.filter(key=cfg_key).update(value=val)

        _write_env_file()
        messages.success(
            request,
            'Settings saved. Bot will use new config on next restart.'
        )
        return redirect('config_app:settings')

    grouped = _get_configs_by_group()
    bot_status = _get_bot_status()

    # MOPH image URLs เรียงตามลำดับ severity (alphabetical sort ผิด)
    _img_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
    _moph_img_map = {
        cfg.key.replace('MOPH_IMG_', ''): cfg
        for cfg in grouped.get('moph', [])
        if 'IMG' in cfg.key
    }
    for cfg in _moph_img_map.values():
        cfg.severity = cfg.key.replace('MOPH_IMG_', '')
    moph_img_ordered = [_moph_img_map[s] for s in _img_order if s in _moph_img_map]

    # Auto-dismiss: แยก config ออกจาก generic loop เพื่อไม่ให้ duplicate input
    _AUTODISMISS_KEYS = {'AUTODISMISS_ENABLED', 'AUTODISMISS_DAYS', 'AUTODISMISS_SEVERITIES'}
    _ad_cfg = {c.key: c.value for c in grouped.get('system', [])
               if c.key in _AUTODISMISS_KEYS}
    # Remove autodismiss from system group — ใช้ dedicated UI แทน
    grouped['system'] = [c for c in grouped.get('system', [])
                         if c.key not in _AUTODISMISS_KEYS]

    ad_severities = _ad_cfg.get('AUTODISMISS_SEVERITIES', 'INFO,LOW')
    ad_sev_list   = [s.strip() for s in ad_severities.split(',') if s.strip()]

    return render(request, 'config/settings.html', {
        'grouped': grouped,
        'groups': GROUPS,
        'bot_status': bot_status,
        'moph_img_ordered': moph_img_ordered,
        # Auto-dismiss
        'autodismiss_enabled':     _ad_cfg.get('AUTODISMISS_ENABLED', 'false'),
        'autodismiss_days':        _ad_cfg.get('AUTODISMISS_DAYS', '90'),
        'autodismiss_severities':  ad_severities,
        'autodismiss_sev_list':    ad_sev_list,
        'autodismiss_sev_choices': ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'],
    })


def _write_env_file():
    configs = {c.key: c.value for c in IntegrationConfig.objects.all()}
    lines = []

    # Wazuh
    lines.append('# Wazuh API')
    for key in ['WAZUH_API_URL', 'WAZUH_USER', 'WAZUH_PASSWORD']:
        lines.append(f'{key}={configs.get(key, "")}')
    lines.append('')

    # Ollama
    lines.append('# Ollama')
    for key in ['OLLAMA_URL', 'OLLAMA_MODEL']:
        lines.append(f'{key}={configs.get(key, "")}')
    lines.append('')

    # TheHive
    lines.append('# TheHive (set to empty string to disable)')
    for key in ['THEHIVE_URL', 'THEHIVE_API_KEY']:
        lines.append(f'{key}={configs.get(key, "")}')
    lines.append('')

    # LINE
    lines.append('# LINE Notify (set to empty string to disable)')
    lines.append(f'LINE_NOTIFY_TOKEN={configs.get("LINE_NOTIFY_TOKEN", "")}')
    lines.append('')

    # Dashboard API (fixed — not editable via UI)
    lines.append('# SOC Dashboard API')
    lines.append(f'DASHBOARD_URL={configs.get("DJANGO_DASHBOARD_URL", "http://localhost:8002")}')
    lines.append('DASHBOARD_API_TOKEN=b06c4b198a70bf3584db2bf0a62dd79a5aca7143')
    lines.append('')

    # Redis (fixed)
    lines.append('# Redis (for deduplication state)')
    lines.append('REDIS_URL=redis://127.0.0.1:6379/2')
    lines.append('')

    # System
    lines.append('# Polling interval in seconds')
    lines.append(f'POLL_INTERVAL={configs.get("POLL_INTERVAL", "30")}')
    lines.append('')
    lines.append('# Log level: DEBUG, INFO, WARNING, ERROR')
    lines.append(f'LOG_LEVEL={configs.get("LOG_LEVEL", "INFO")}')
    lines.append('')

    with open(SOC_BOT_ENV_PATH, 'w') as f:
        f.write('\n'.join(lines))


def _get_bot_status():
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'soc-bot'],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        if status == 'active':
            return {'status': 'active', 'label': 'Running', 'badge': 'success'}
        elif status == 'inactive':
            return {'status': 'inactive', 'label': 'Stopped', 'badge': 'secondary'}
        elif status == 'failed':
            return {'status': 'failed', 'label': 'Failed', 'badge': 'danger'}
        else:
            return {'status': status, 'label': status.title(), 'badge': 'warning'}
    except Exception as e:
        return {'status': 'unknown', 'label': 'Unknown', 'badge': 'secondary'}


@login_required
@require_POST
def test_connection(request, group):
    configs = {c.key: c.value for c in IntegrationConfig.objects.all()}

    try:
        if group == 'wazuh':
            return _test_wazuh(configs)
        elif group == 'ollama':
            return _test_ollama(configs)
        elif group == 'openai':
            return _test_openai(configs)
        elif group == 'thehive':
            return _test_thehive(configs)
        elif group == 'line':
            return _test_line(configs)
        elif group == 'moph':
            return _test_moph(configs)
        else:
            return JsonResponse({'ok': False, 'message': f'Unknown group: {group}'})
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)})


def _test_wazuh(configs):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    results = []

    # 1. Test Manager API (port 55000)
    url = configs.get('WAZUH_API_URL', '').rstrip('/')
    user = configs.get('WAZUH_USER', '')
    password = configs.get('WAZUH_PASSWORD', '')
    if url:
        auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
        req = urllib.request.Request(
            f'{url}/security/user/authenticate',
            method='POST',
            headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'},
            data=b''
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get('data', {}).get('token'):
                    results.append('Manager API ✓ JWT token obtained')
                else:
                    results.append('Manager API ✓ Connected')
        except urllib.error.HTTPError as e:
            results.append(f'Manager API ✗ HTTP {e.code}')
        except urllib.error.URLError as e:
            results.append(f'Manager API ✗ {e.reason}')
    else:
        results.append('Manager API — URL not set')

    # 2. Test Indexer (port 9200)
    idx_url = configs.get('WAZUH_INDEXER_URL', '').rstrip('/')
    idx_user = configs.get('WAZUH_INDEXER_USER', 'admin')
    idx_pass = configs.get('WAZUH_INDEXER_PASSWORD', '')
    if idx_url:
        auth_idx = base64.b64encode(f'{idx_user}:{idx_pass}'.encode()).decode()
        req2 = urllib.request.Request(
            f'{idx_url}/',
            method='GET',
            headers={'Authorization': f'Basic {auth_idx}'},
        )
        try:
            with urllib.request.urlopen(req2, context=ctx, timeout=10) as resp:
                data2 = json.loads(resp.read())
                version = data2.get('version', {}).get('number', '')
                results.append(f'Indexer ✓ Connected (OpenSearch {version})')
        except urllib.error.HTTPError as e:
            if e.code == 401:
                results.append('Indexer ✗ Authentication failed — check Indexer Password')
            else:
                results.append(f'Indexer ✗ HTTP {e.code}')
        except urllib.error.URLError as e:
            results.append(f'Indexer ✗ {e.reason}')
    else:
        results.append('Indexer — URL not set')

    all_ok = all('✓' in r for r in results)
    return JsonResponse({'ok': all_ok, 'message': ' | '.join(results)})


def _test_ollama(configs):
    url = configs.get('OLLAMA_URL', '').rstrip('/')
    if not url:
        return JsonResponse({'ok': False, 'message': 'OLLAMA_URL is not set'})

    try:
        req = urllib.request.Request(f'{url}/api/tags', method='GET')
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read())
                models = [m['name'] for m in data.get('models', [])]
                msg = f'Connected — {len(models)} model(s) available'
                if models:
                    msg += f': {", ".join(models[:3])}'
                return JsonResponse({'ok': True, 'message': msg})
    except urllib.error.HTTPError as e:
        return JsonResponse({'ok': False, 'message': f'HTTP {e.code}'})
    except urllib.error.URLError as e:
        return JsonResponse({'ok': False, 'message': f'Connection error: {e.reason}'})


def _test_openai(configs):
    url = configs.get('OPENAI_URL', '').rstrip('/')
    model = configs.get('OPENAI_MODEL', '')
    api_key = configs.get('OPENAI_API_KEY', '')
    if not url:
        return JsonResponse({'ok': False, 'message': 'OPENAI_URL is not set'})

    try:
        payload = json.dumps({
            'model': model,
            'messages': [{'role': 'user', 'content': 'Reply with: ok'}],
            'max_tokens': 5,
        }).encode()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}' if api_key else 'Bearer ollama',
        }
        req = urllib.request.Request(
            f'{url}/v1/chat/completions',
            data=payload,
            headers=headers,
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            reply = data['choices'][0]['message']['content']
            return JsonResponse({'ok': True, 'message': f'Connected — model: {model}, reply: {reply[:50]}'})
    except urllib.error.HTTPError as e:
        return JsonResponse({'ok': False, 'message': f'HTTP {e.code}: {e.read().decode()[:100]}'})
    except urllib.error.URLError as e:
        return JsonResponse({'ok': False, 'message': f'Connection error: {e.reason}'})
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)})


def _test_thehive(configs):
    url = configs.get('THEHIVE_URL', '').rstrip('/')
    api_key = configs.get('THEHIVE_API_KEY', '')

    if not url:
        return JsonResponse({'ok': False, 'message': 'THEHIVE_URL is not set'})

    try:
        req = urllib.request.Request(
            f'{url}/api/status',
            method='GET',
            headers={'Authorization': f'Bearer {api_key}'} if api_key else {}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return JsonResponse({'ok': True, 'message': 'Connected — TheHive is reachable'})
    except urllib.error.HTTPError as e:
        return JsonResponse({'ok': False, 'message': f'HTTP {e.code}'})
    except urllib.error.URLError as e:
        return JsonResponse({'ok': False, 'message': f'Connection error: {e.reason}'})


def _test_line(configs):
    token = configs.get('LINE_NOTIFY_TOKEN', '')
    if not token:
        return JsonResponse({'ok': False, 'message': 'LINE_NOTIFY_TOKEN is not set'})

    try:
        data = urllib.parse.urlencode({'message': '[SOC Test] Connection test from SOC Dashboard'}).encode()
        req = urllib.request.Request(
            'https://notify-api.line.me/api/notify',
            method='POST',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data=data
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return JsonResponse({'ok': True, 'message': 'Connected — LINE message sent successfully'})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return JsonResponse({'ok': False, 'message': f'HTTP {e.code}: {body[:200]}'})
    except urllib.error.URLError as e:
        return JsonResponse({'ok': False, 'message': f'Connection error: {e.reason}'})


def _test_moph(configs):
    base_url = configs.get('MOPH_NOTIFY_URL', '').rstrip('/')
    client_key = configs.get('MOPH_NOTIFY_CLIENT_KEY', '')
    secret_key = configs.get('MOPH_NOTIFY_SECRET_KEY', '')

    if not base_url:
        return JsonResponse({'ok': False, 'message': 'MOPH_NOTIFY_URL is not set'})
    if not client_key or not secret_key:
        return JsonResponse({'ok': False, 'message': 'Client Key หรือ Secret Key ยังไม่ได้กรอก'})

    try:
        payload = json.dumps({'messages': [{'type': 'text', 'text': '[SOC Test] ทดสอบการเชื่อมต่อ MOPH Notify'}]}).encode()
        req = urllib.request.Request(
            f'{base_url}/api/notify/send',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'client-key': client_key,
                'secret-key': secret_key,
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            return JsonResponse({'ok': True, 'message': f'Connected — {body[:100]}'})
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return JsonResponse({'ok': False, 'message': f'HTTP {e.code}: {body}'})
    except urllib.error.URLError as e:
        return JsonResponse({'ok': False, 'message': f'Connection error: {e.reason}'})
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)})


@login_required
@require_POST
def moph_test_flex(request):
    """Send a real Flex Message to MOPH Notify using the latest HIGH/CRITICAL alert."""
    from apps.alerts.models import Alert
    from apps.notifications.moph_notifier import build_flex_payload, _get_config

    alert = (
        Alert.objects.filter(severity__in=['CRITICAL', 'HIGH', 'MEDIUM'])
        .order_by('-timestamp').first()
    )
    if not alert:
        alert = Alert.objects.order_by('-timestamp').first()
    if not alert:
        return JsonResponse({'ok': False, 'message': 'ไม่มี alert ในระบบ'})

    configs = _get_config()
    base_url   = configs.get('MOPH_NOTIFY_URL', '').rstrip('/')
    client_key = configs.get('MOPH_NOTIFY_CLIENT_KEY', '')
    secret_key = configs.get('MOPH_NOTIFY_SECRET_KEY', '')

    if not base_url or not client_key or not secret_key:
        return JsonResponse({'ok': False, 'message': 'ยังไม่ได้ตั้งค่า URL / Client Key / Secret Key'})

    payload_dict = build_flex_payload(alert)
    payload_bytes = json.dumps(payload_dict, ensure_ascii=False).encode('utf-8')

    req = urllib.request.Request(
        f'{base_url}/api/notify/send',
        data=payload_bytes,
        headers={
            'Content-Type': 'application/json',
            'client-key':   client_key,
            'secret-key':   secret_key,
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            return JsonResponse({
                'ok': True,
                'message': f'ส่งสำเร็จ (Alert #{alert.id} — {alert.severity})',
                'api_response': body[:500],
                'payload_preview': json.dumps(payload_dict, ensure_ascii=False, indent=2)[:1000],
            })
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        return JsonResponse({
            'ok': False,
            'message': f'HTTP {e.code}',
            'api_response': body,
            'payload_preview': json.dumps(payload_dict, ensure_ascii=False, indent=2)[:1000],
        })
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)})


@login_required
def ollama_models(request):
    """Return list of locally installed Ollama models."""
    configs = {c.key: c.value for c in IntegrationConfig.objects.filter(key='OLLAMA_URL')}
    url = configs.get('OLLAMA_URL', '').rstrip('/')
    if not url:
        return JsonResponse({'ok': False, 'models': [], 'message': 'OLLAMA_URL not set'})

    try:
        req = urllib.request.Request(f'{url}/api/tags', method='GET')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            models = []
            for m in data.get('models', []):
                size_bytes = m.get('size', 0)
                if size_bytes >= 1024 ** 3:
                    size_str = f'{size_bytes / 1024**3:.1f} GB'
                else:
                    size_str = f'{size_bytes / 1024**2:.0f} MB'
                models.append({'name': m['name'], 'size': size_str})
            return JsonResponse({'ok': True, 'models': models})
    except urllib.error.URLError as e:
        return JsonResponse({'ok': False, 'models': [], 'message': f'Cannot connect: {e.reason}'})
    except Exception as e:
        return JsonResponse({'ok': False, 'models': [], 'message': str(e)})


@login_required
def ollama_stats(request):
    from apps.alerts.models import Alert, AIAnalysis
    total = Alert.objects.filter(severity__in=['CRITICAL', 'HIGH', 'MEDIUM']).count()
    analyzed = AIAnalysis.objects.filter(
        alert__severity__in=['CRITICAL', 'HIGH', 'MEDIUM']
    ).count()
    return JsonResponse({'total': total, 'analyzed': analyzed, 'pending': total - analyzed})


@login_required
def pipeline_status(request):
    """Live pipeline status — reads from soc-fetcher status file + DB counts."""
    import json, pathlib
    from apps.alerts.models import Alert, AIAnalysis

    total    = Alert.objects.filter(severity__in=['CRITICAL', 'HIGH', 'MEDIUM']).count()
    analyzed = AIAnalysis.objects.filter(alert__severity__in=['CRITICAL', 'HIGH', 'MEDIUM']).count()

    # Read busy/queue_depth from soc-fetcher status file (written every 60s)
    status_file = pathlib.Path('/tmp/soc_pipeline_status.json')
    trigger_pending = pathlib.Path('/tmp/soc_batch_trigger').exists()
    busy = False
    queue_depth = 0
    try:
        data = json.loads(status_file.read_text())
        busy        = data.get('busy', False)
        queue_depth = data.get('queue_depth', 0)
    except Exception:
        pass

    return JsonResponse({
        'busy':            busy or trigger_pending,
        'queue_depth':     queue_depth,
        'trigger_pending': trigger_pending,
        'total':           total,
        'analyzed':        analyzed,
        'pending':         total - analyzed,
    })


@login_required
@require_POST
def run_autodismiss(request):
    """Run auto-dismiss immediately (ignores the enabled flag, uses current days/severity settings)."""
    from django.utils import timezone
    from apps.alerts.models import Alert
    configs = {c.key: c.value for c in IntegrationConfig.objects.filter(
        key__in=['AUTODISMISS_DAYS', 'AUTODISMISS_SEVERITIES']
    )}
    try:
        days = int(configs.get('AUTODISMISS_DAYS', '90'))
    except ValueError:
        days = 90
    sevs = [s.strip() for s in configs.get('AUTODISMISS_SEVERITIES', 'INFO,LOW').split(',') if s.strip()]
    if not sevs:
        return JsonResponse({'ok': False, 'error': 'No severity selected'})

    cutoff = timezone.now() - timezone.timedelta(days=days)
    count = Alert.objects.filter(
        severity__in=sevs,
        timestamp__lt=cutoff,
        dismissed=False,
    ).update(dismissed=True, dismissed_at=timezone.now())
    return JsonResponse({'ok': True, 'dismissed': count, 'days': days, 'severities': sevs})


@login_required
@require_POST
def batch_analyze(request):
    import pathlib
    from apps.alerts.models import Alert
    # Count unanalyzed (so UI knows how many to expect)
    count = Alert.objects.filter(
        severity__in=['CRITICAL', 'HIGH', 'MEDIUM'],
        ai_analysis__isnull=True,
    ).count()
    # Signal soc-fetcher to pick up and process (avoids multi-process queue conflict)
    pathlib.Path('/tmp/soc_batch_trigger').touch()
    return JsonResponse({'ok': True, 'queued': count})


@login_required
@require_POST
def restart_bot(request):
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'soc-bot'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return JsonResponse({'ok': True, 'message': 'soc-bot restarted successfully'})
        else:
            return JsonResponse({
                'ok': False,
                'message': result.stderr.strip() or 'Restart failed (non-zero exit)'
            })
    except subprocess.TimeoutExpired:
        return JsonResponse({'ok': False, 'message': 'Restart timed out'})
    except Exception as e:
        return JsonResponse({'ok': False, 'message': str(e)})
