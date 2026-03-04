from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from .models import Incident
from apps.alerts.models import Alert


@login_required
def incident_list(request):
    qs = Incident.objects.select_related('alert', 'alert__ai_analysis_chat', 'approved_by')

    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 25)
    page = request.GET.get('page', 1)
    incidents = paginator.get_page(page)

    # Smart page_range with ellipsis
    current = incidents.number
    total = paginator.num_pages
    pages = sorted(set([1, total] + list(range(max(1, current - 2), min(total, current + 2) + 1))))
    page_range = []
    prev = None
    for p in pages:
        if prev and p - prev > 1:
            page_range.append('...')
        page_range.append(p)
        prev = p

    context = {
        'incidents': incidents,
        'status_choices': Incident.STATUS_CHOICES,
        'status_filter': status_filter or '',
        'page_range': page_range,
    }
    return render(request, 'incidents/list.html', context)


@login_required
def incident_detail(request, pk):
    incident = get_object_or_404(
        Incident.objects.select_related('alert', 'alert__ai_analysis', 'alert__ai_analysis_chat'),
        pk=pk,
    )
    return render(request, 'incidents/detail.html', {'incident': incident})


@login_required
def incident_create(request):
    alerts = Alert.objects.values('id', 'rule_description', 'severity', 'agent_name').order_by('-id')
    prefill_alert_id = request.GET.get('alert_id', '')

    if request.method == 'POST':
        errors = {}
        values = request.POST

        alert_id = values.get('alert_id', '').strip()
        thehive_case_id = values.get('thehive_case_id', '').strip()
        title = values.get('title', '').strip()
        status = values.get('status', 'New')
        severity = values.get('severity', '').strip()
        thehive_url = values.get('thehive_url', '').strip()

        if not alert_id:
            errors['alert_id'] = 'Alert is required.'
        if not thehive_case_id:
            errors['thehive_case_id'] = 'TheHive Case ID is required.'
        elif Incident.objects.filter(thehive_case_id=thehive_case_id).exists():
            errors['thehive_case_id'] = 'An incident with this Case ID already exists.'
        if not title:
            errors['title'] = 'Title is required.'

        if not errors:
            incident = Incident.objects.create(
                alert_id=alert_id,
                thehive_case_id=thehive_case_id,
                title=title,
                status=status,
                severity=severity,
                thehive_url=thehive_url,
                approved_by=request.user,
            )
            messages.success(request, f'Incident {thehive_case_id} created.')
            return redirect('incidents:detail', pk=incident.pk)

        return render(request, 'incidents/form.html', {
            'form_title': 'New Incident',
            'action_url': '/incidents/create/',
            'submit_label': 'Create Incident',
            'incident': None,
            'alerts': alerts,
            'status_choices': Incident.STATUS_CHOICES,
            'severity_choices': Alert.SEVERITY,
            'errors': errors,
            'values': values,
            'prefill_alert_id': prefill_alert_id,
        })

    return render(request, 'incidents/form.html', {
        'form_title': 'New Incident',
        'action_url': '/incidents/create/',
        'submit_label': 'Create Incident',
        'incident': None,
        'alerts': alerts,
        'status_choices': Incident.STATUS_CHOICES,
        'severity_choices': Alert.SEVERITY,
        'errors': {},
        'values': {},
        'prefill_alert_id': prefill_alert_id,
    })


@login_required
def incident_edit(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    alerts = Alert.objects.values('id', 'rule_description', 'severity', 'agent_name').order_by('-id')

    if request.method == 'POST':
        errors = {}
        values = request.POST

        alert_id = values.get('alert_id', '').strip()
        thehive_case_id = values.get('thehive_case_id', '').strip()
        title = values.get('title', '').strip()
        status = values.get('status', 'New')
        severity = values.get('severity', '').strip()
        thehive_url = values.get('thehive_url', '').strip()

        if not alert_id:
            errors['alert_id'] = 'Alert is required.'
        if not thehive_case_id:
            errors['thehive_case_id'] = 'TheHive Case ID is required.'
        elif Incident.objects.filter(thehive_case_id=thehive_case_id).exclude(pk=pk).exists():
            errors['thehive_case_id'] = 'An incident with this Case ID already exists.'
        if not title:
            errors['title'] = 'Title is required.'

        if not errors:
            incident.alert_id = alert_id
            incident.thehive_case_id = thehive_case_id
            incident.title = title
            incident.status = status
            incident.severity = severity
            incident.thehive_url = thehive_url
            incident.approved_by = request.user
            incident.save()
            messages.success(request, f'Incident {thehive_case_id} updated.')
            return redirect('incidents:detail', pk=incident.pk)

        return render(request, 'incidents/form.html', {
            'form_title': f'Edit Incident {incident.thehive_case_id}',
            'action_url': f'/incidents/{pk}/edit/',
            'submit_label': 'Save Changes',
            'incident': incident,
            'alerts': alerts,
            'status_choices': Incident.STATUS_CHOICES,
            'severity_choices': Alert.SEVERITY,
            'errors': errors,
            'values': values,
            'prefill_alert_id': '',
        })

    values = {
        'alert_id': str(incident.alert_id),
        'thehive_case_id': incident.thehive_case_id,
        'title': incident.title,
        'status': incident.status,
        'severity': incident.severity,
        'thehive_url': incident.thehive_url,
    }
    return render(request, 'incidents/form.html', {
        'form_title': f'Edit Incident {incident.thehive_case_id}',
        'action_url': f'/incidents/{pk}/edit/',
        'submit_label': 'Save Changes',
        'incident': incident,
        'alerts': alerts,
        'status_choices': Incident.STATUS_CHOICES,
        'severity_choices': Alert.SEVERITY,
        'errors': {},
        'values': values,
        'prefill_alert_id': '',
    })


@login_required
@require_POST
def incident_delete(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    case_id = incident.thehive_case_id
    incident.delete()
    messages.success(request, f'Incident {case_id} deleted.')
    return redirect('incidents:list')

@login_required
@require_POST
def sync_thehive(request):
    """Pull status of all open Incidents from TheHive and update local DB."""
    import json as _json
    import re
    import urllib.request
    import urllib.error
    from django.http import JsonResponse
    from apps.config.models import IntegrationConfig

    configs = {c.key: c.value for c in IntegrationConfig.objects.filter(
        key__in=['THEHIVE_URL', 'THEHIVE_API_KEY']
    )}
    base_url = configs.get('THEHIVE_URL', '').rstrip('/')
    api_key  = configs.get('THEHIVE_API_KEY', '')
    if not base_url or not api_key:
        return JsonResponse({'ok': False, 'error': 'TheHive URL / API Key ยังไม่ได้ตั้งค่า'})

    STATUS_MAP = {
        'New': 'New', 'InProgress': 'InProgress',
        'Resolved': 'Resolved', 'Closed': 'Closed',
    }
    open_incidents = Incident.objects.exclude(status__in=['Resolved', 'Closed'])
    updated = skipped = errors = 0

    for inc in open_incidents:
        # Extract TheHive internal case _id from stored URL
        m = re.search(r'/cases/([^/]+)/details', inc.thehive_url or '')
        if not m:
            skipped += 1
            continue
        case_id = m.group(1)
        try:
            req = urllib.request.Request(
                f'{base_url}/api/v1/case/{case_id}',
                headers={'Authorization': f'Bearer {api_key}'},
                method='GET',
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            th_status = data.get('status', '')
            new_status = STATUS_MAP.get(th_status, '')
            if new_status and new_status != inc.status:
                inc.status = new_status
                inc.save(update_fields=['status', 'updated_at'])
                updated += 1
        except urllib.error.HTTPError as e:
            if e.code == 404:
                skipped += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    return JsonResponse({
        'ok': True, 'updated': updated,
        'skipped': skipped, 'errors': errors,
        'total': open_incidents.count(),
    })


@login_required
def export_incidents_csv(request):
    import csv
    from django.http import HttpResponse
    status_filter = request.GET.get('status', '')
    qs = Incident.objects.select_related('alert')
    if status_filter:
        qs = qs.filter(status=status_filter)
    qs = qs.order_by('-created_at')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="incidents.csv"'
    w = csv.writer(response)
    w.writerow(['ID','Case ID','Title','Status','Severity','Alert ID',
                'Agent','Created At','TheHive URL'])
    for inc in qs:
        w.writerow([
            inc.id, inc.thehive_case_id, inc.title, inc.status,
            inc.severity, inc.alert_id,
            inc.alert.agent_name if inc.alert else '',
            inc.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            inc.thehive_url or '',
        ])
    return response
