from django.shortcuts import render
from django.contrib.auth.decorators import login_required

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
    # TypeError("Cannot filter a query once a slice has been taken"), which
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
        'unknown_count': scope.filter(status='unknown').count(),
        'pending_count': scope.filter(status='pending').count(),
        'can_view_full': can_view_full,
    }
    return render(request, 'notifications/notifications.html', context)
