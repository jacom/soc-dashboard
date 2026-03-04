import json
import subprocess
import threading
import urllib.request

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import timedelta
from apps.alerts.models import Alert


@login_required
def dashboard(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Summary counts for today
    alerts_today = Alert.objects.filter(timestamp__gte=today_start)
    critical_count = alerts_today.filter(severity='CRITICAL').count()
    high_count = alerts_today.filter(severity='HIGH').count()
    medium_count = alerts_today.filter(severity='MEDIUM').count()
    total_count = alerts_today.count()

    # Last 24h for timeline chart
    last_24h = now - timedelta(hours=24)
    recent_alerts = Alert.objects.filter(timestamp__gte=last_24h).order_by('timestamp')

    # Build hourly buckets for the last 24 hours
    hourly_labels = []
    hourly_critical = []
    hourly_high = []
    hourly_medium = []
    hourly_low = []

    for i in range(24):
        bucket_start = last_24h + timedelta(hours=i)
        bucket_end = bucket_start + timedelta(hours=1)
        hourly_labels.append(timezone.localtime(bucket_start).strftime('%H:00'))
        bucket_qs = recent_alerts.filter(timestamp__gte=bucket_start, timestamp__lt=bucket_end)
        hourly_critical.append(bucket_qs.filter(severity='CRITICAL').count())
        hourly_high.append(bucket_qs.filter(severity='HIGH').count())
        hourly_medium.append(bucket_qs.filter(severity='MEDIUM').count())
        hourly_low.append(bucket_qs.filter(severity='LOW').count())

    # Top rules (last 7 days)
    from django.db.models import Count
    top_rules = (
        Alert.objects.filter(timestamp__gte=now - timedelta(days=7))
        .values('rule_description')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    # Recent critical/high alerts
    recent_critical = Alert.objects.filter(
        severity__in=['CRITICAL', 'HIGH'],
        timestamp__gte=now - timedelta(hours=24)
    ).select_related('ai_analysis')[:10]

    context = {
        'critical_count': critical_count,
        'high_count': high_count,
        'medium_count': medium_count,
        'total_count': total_count,
        'hourly_labels': hourly_labels,
        'hourly_critical': hourly_critical,
        'hourly_high': hourly_high,
        'hourly_medium': hourly_medium,
        'hourly_low': hourly_low,
        'top_rules': list(top_rules),
        'recent_critical': recent_critical,
    }
    return render(request, 'core/dashboard.html', context)


def _version_gt(a, b):
    """Return True if version a > version b (semver)."""
    try:
        return tuple(int(x) for x in a.split('.')) > tuple(int(x) for x in b.split('.'))
    except Exception:
        return False


@login_required
def check_update(request):
    """AJAX — ตรวจ version ใหม่จาก GitHub, cache 1 ชม."""
    from django.core.cache import cache
    CACHE_KEY = 'soc_latest_version'

    cached = cache.get(CACHE_KEY)
    if cached:
        return JsonResponse(cached)

    current = settings.APP_VERSION
    try:
        req = urllib.request.Request(
            'https://api.github.com/repos/jacom/SOC-Dashboard/releases/latest',
            headers={'User-Agent': 'SOC-Dashboard', 'Accept': 'application/vnd.github+json'},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        latest = data.get('tag_name', '').lstrip('v')
        result = {
            'ok': True,
            'current': current,
            'latest': latest,
            'has_update': _version_gt(latest, current),
            'release_url': data.get('html_url', ''),
            'release_name': data.get('name', f'v{latest}'),
        }
    except Exception as e:
        result = {'ok': False, 'current': current, 'latest': current, 'has_update': False}

    cache.set(CACHE_KEY, result, 3600)
    return JsonResponse(result)


@login_required
@require_POST
def do_update(request):
    """รัน update script แล้ว restart service."""
    from django.core.cache import cache

    script = settings.BASE_DIR / 'scripts' / 'update.sh'

    try:
        result = subprocess.run(
            ['bash', str(script)],
            capture_output=True, text=True, timeout=300,
            cwd=str(settings.BASE_DIR),
        )
        if result.returncode != 0:
            return JsonResponse({'ok': False, 'error': result.stderr[-1000:] or result.stdout[-500:]})
        output = result.stdout
    except subprocess.TimeoutExpired:
        return JsonResponse({'ok': False, 'error': 'Update timed out (5 min)'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})

    # ล้าง version cache เพื่อให้เช็คใหม่หลัง restart
    cache.delete('soc_latest_version')

    # Restart ใน background thread (หลังส่ง response)
    def _restart():
        import time
        time.sleep(1)
        subprocess.run(
            ['sudo', 'systemctl', 'restart', 'soc-dashboard', 'soc-fetcher', 'soc-bot'],
            timeout=30,
        )

    threading.Thread(target=_restart, daemon=True).start()

    return JsonResponse({'ok': True, 'output': output})
