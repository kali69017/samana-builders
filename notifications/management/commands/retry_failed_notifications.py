"""Retry failed notification logs, respecting opt-outs and a 3-attempt cap."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import NotificationLog
from notifications.services import NotificationService


class Command(BaseCommand):
    help = 'Retry failed notification logs from the last N days, up to 3 attempts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=2,
            help='Retry failures created within this many days (default 2).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be retried without changing any log.',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])
        logs = NotificationLog.objects.filter(
            status='failed', attempts__lt=3, created_at__gte=cutoff,
        ).order_by('created_at')

        retried = sent = failed = skipped = 0
        for log in logs:
            reason = NotificationService.preference_reason_for_log(log)
            if reason:
                skipped += 1
                self.stdout.write(f'Skipped {log.pk} ({log.channel}): {reason}')
                continue
            retried += 1
            if options['dry_run']:
                self.stdout.write(
                    f'Would retry {log.pk} ({log.channel}, attempts {log.attempts}/3)')
                continue
            result = NotificationService.retry_log(log)
            if result.status == 'sent':
                sent += 1
            elif result.status == 'skipped':
                skipped += 1
            else:
                failed += 1

        unknown = NotificationLog.objects.filter(status='unknown')
        if unknown.exists():
            self.stdout.write('Unknown outcomes, check the provider dashboard before retrying:')
            for log in unknown:
                self.stdout.write(
                    f'  {log.pk} {log.channel} {log.recipient_contact} '
                    f'provider_id={log.provider_message_id or "none"}')

        self.stdout.write(
            f'Retry candidates: {retried}. Sent: {sent}. Failed: {failed}. '
            f'Skipped: {skipped}.'
        )
