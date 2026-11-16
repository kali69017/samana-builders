"""Drain queued notification logs and process stale sending rows."""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import NotificationLog
from notifications.services import NotificationService


class Command(BaseCommand):
    help = 'Process queued notification logs.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--loop', action='store_true')
        parser.add_argument('--interval', type=int, default=10)
        parser.add_argument('--dry-run', action='store_true')

    def _run_once(self, limit, dry_run):
        if dry_run:
            cutoff = timezone.now() - timedelta(minutes=10)
            stale = NotificationLog.objects.filter(
                status='sending', sending_at__lt=cutoff).count()
        else:
            stale = NotificationService.mark_stale_sending()
        ids = list(NotificationLog.objects.filter(
            status='queued').order_by('created_at').values_list('pk', flat=True)[:limit])
        if dry_run:
            self.stdout.write(
                f'Would process {len(ids)} queued rows and mark {stale} stale sending rows unknown.')
            return 0
        processed = 0
        for log_id in ids:
            try:
                if NotificationService.process_notification_id(log_id):
                    processed += 1
            except Exception as exc:
                NotificationLog.objects.filter(
                    pk=log_id, status='sending').update(
                    status='unknown',
                    error_message=f'Worker exception, check provider: {exc}',
                    sending_at=None,
                )
        self.stdout.write(f'Processed {processed} queued rows. Stale marked unknown: {stale}.')
        return processed

    def handle(self, *args, **options):
        limit = options['limit']
        if not options['loop']:
            self._run_once(limit, options['dry_run'])
            return
        while True:
            self._run_once(limit, options['dry_run'])
            if options['dry_run']:
                return
            time.sleep(options['interval'])
