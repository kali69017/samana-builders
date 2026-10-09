from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.permissions import management_or_above
from .models import NotificationLog


@login_required
@management_or_above
def notifications_view(request):
    channel_filter = request.GET.get('channel', '')
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')

    # Filter *before* slicing. Doing it the other way round raises
    # TypeError("Cannot filter a query once a slice has been taken."), which
    # turned every filter submit on this page into a 500.
    logs = NotificationLog.objects.all()
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
        'total_count': NotificationLog.objects.count(),
        'sent_count': NotificationLog.objects.filter(status='sent').count(),
        'skipped_count': NotificationLog.objects.filter(status='skipped').count(),
        'failed_count': NotificationLog.objects.filter(status='failed').count(),
        'pending_count': NotificationLog.objects.filter(status='pending').count(),
    }
    return render(request, 'notifications/notifications.html', context)


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
