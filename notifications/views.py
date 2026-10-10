from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta
from core.permissions import management_or_above, get_user_role, SUPER_ADMIN, ADMIN
from .models import NotificationLog


@login_required
@management_or_above
def notifications_view(request):
    channel_filter = request.GET.get('channel', '')
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')

    # Object-level scoping: super_admin/admin see the whole log; other roles see
    # only the rows they created. This stops one management user from harvesting
    # every customer's contact details.
    role = get_user_role(request)
    can_view_full = role in (SUPER_ADMIN, ADMIN)
    if can_view_full:
        scope = NotificationLog.objects.all()
    else:
        scope = NotificationLog.objects.filter(created_by=request.user)

    # Filter *before* slicing. Doing it the other way round raises
    # TypeError("Cannot filter a query once a slice has been taken."), which
    # turned every filter submit on this page into a 500.
    logs = scope
    if channel_filter:
        logs = logs.filter(channel=channel_filter)
    if type_filter:
        logs = logs.filter(notification_type=type_filter)
    if status_filter:
        logs = logs.filter(status=status_filter)
    logs = logs[:100]

    context = {
        'logs': logs,
        'channel_filter': channel_filter,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'total_count': scope.count(),
        'sent_count': scope.filter(status='sent').count(),
        'skipped_count': scope.filter(status='skipped').count(),
        'failed_count': scope.filter(status='failed').count(),
        'pending_count': scope.filter(status='pending').count(),
        'can_view_full': can_view_full,
    }
    return render(request, 'notifications/notifications.html', context)


def _manual_send_rate_limited(recipient_contact):
    """Anti spam-blast: at most N manual 'general' sends to one address per day.

    Counted on the raw posted contact string so formatting variants of the same
    number still count once a victim is being hammered, while legit distinct
    recipients are unaffected.
    """
    from django.conf import settings
    cap = getattr(settings, 'NOTIFICATION_MANUAL_RATE_LIMIT', 3)
    window = timezone.now() - timedelta(hours=24)
    return NotificationLog.objects.filter(
        notification_type='general',
        recipient_contact=recipient_contact,
        created_at__gte=window,
    ).count() >= cap


@login_required
@management_or_above
def send_manual_notification(request):
    if request.method == 'POST':
        from .services import NotificationService
        recipient_name = request.POST.get('recipient_name', '')
        recipient_contact = request.POST.get('recipient_contact', '')
        channel = request.POST.get('channel', 'email')
        subject = request.POST.get('subject', '')
        message = request.POST.get('message', '')

        if not recipient_contact or not message:
            messages.error(request, 'Recipient contact and message are required.')
            return redirect('notifications')

        if _manual_send_rate_limited(recipient_contact):
            # Anti spam-blast: refuse with an HTTP 429 rather than another 302 +
            # flash, so automation sees the throttle instead of a seemingly
            # successful submission.
            return HttpResponse(
                'Rate limit: too many notifications to this recipient. Try again later.',
                status=429,
            )

        log = NotificationService.send_notification(
            recipient_name=recipient_name,
            recipient_contact=recipient_contact,
            channel=channel,
            notification_type='general',
            subject=subject,
            message=message,
            user=request.user,
        )

        if log.status == 'sent':
            messages.success(request, f'Notification sent successfully via {channel}.')
        elif log.status == 'skipped':
            messages.warning(
                request,
                f'Not sent: {channel} notifications are disabled on this deployment.'
            )
        else:
            messages.error(request, f'Failed to send notification: {log.error_message}')

        return redirect('notifications')

    return redirect('notifications')
