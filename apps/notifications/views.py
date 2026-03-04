from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import NotificationLog


@login_required
def notification_list(request):
    qs = NotificationLog.objects.select_related('alert')

    channel = request.GET.get('channel')
    status = request.GET.get('status')
    if channel:
        qs = qs.filter(channel=channel)
    if status:
        qs = qs.filter(status=status)

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 25)
    page = request.GET.get('page', 1)
    notifications = paginator.get_page(page)

    context = {
        'notifications': notifications,
        'channel_choices': NotificationLog.CHANNEL_CHOICES,
        'status_choices': NotificationLog.STATUS_CHOICES,
        'channel_filter': channel or '',
        'status_filter': status or '',
    }
    return render(request, 'notifications/list.html', context)


@login_required
@require_POST
def notification_retry(request, pk):
    from django.http import JsonResponse
    notif = get_object_or_404(NotificationLog, pk=pk)
    if notif.channel != 'MOPH':
        return JsonResponse({'ok': False, 'error': f'Retry not supported for channel: {notif.channel}'})

    from apps.notifications.moph_notifier import send_moph_notify
    ok, err = send_moph_notify(notif.alert)
    NotificationLog.objects.create(
        alert=notif.alert,
        channel='MOPH',
        status='sent' if ok else 'failed',
        message_preview=notif.message_preview,
        error_message=err if not ok else '',
    )
    return JsonResponse({'ok': ok, 'error': err if not ok else ''})
