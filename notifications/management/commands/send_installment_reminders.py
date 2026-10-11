"""Send SMS/email payment reminders for installments due soon, and overdue alerts.

Runs once a day from a scheduler/cron (Docker `scheduler` service, or host cron).
Covers both cases, with a per-booking cooldown so a customer is not hit every day:

    python manage.py send_installment_reminders --days=7 --cooldown=6

  - installments due within ``--days`` (default 7)  -> installment_reminder
  - installments that are now past-due              -> overdue_payment
A booking/type already notified in the last ``--cooldown`` days is skipped.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.models import Installment
from notifications.models import NotificationLog
from notifications.services import NotificationService


class Command(BaseCommand):
    help = 'Send SMS/email reminders for installments due soon, and overdue alerts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=7,
            help='Remind installments due within this many days (default 7).',
        )
        parser.add_argument(
            '--cooldown', type=int, default=6,
            help='Minimum days between notifications to the same booking/type (default 6).',
        )

    def handle(self, *args, **options):
        days = options['days']
        cooldown = options['cooldown']
        today = timezone.localdate()
        cutoff = today + timedelta(days=days)
        cooldown_since = timezone.now() - timedelta(days=cooldown)

        installments = (
            Installment.objects
            .filter(status__in=['pending', 'overdue', 'partial'])
            .select_related(
                'plan__booking__customer', 'plan__booking__plot',
                'plan__booking__plot__project',
            )
            .order_by('due_date')
        )

        reminders = overdue = skipped = 0
        for installment in installments:
            try:
                due = installment.due_date
                if installment.status == 'overdue' or due < today:
                    ntype = 'overdue_payment'
                elif due <= cutoff:
                    ntype = 'installment_reminder'
                else:
                    # Not due in the window and not overdue.
                    continue

                booking = installment.plan.booking
                already = NotificationLog.objects.filter(
                    notification_type=ntype,
                    related_booking_id=str(booking.booking_id),
                    created_at__gte=cooldown_since,
                ).exists()
                if already:
                    skipped += 1
                    continue

                if ntype == 'overdue_payment':
                    NotificationService.send_overdue_payment_alert(installment)
                    overdue += 1
                else:
                    NotificationService.send_installment_reminder(installment)
                    reminders += 1
            except Exception as exc:  # never stop the whole run for one bad row
                self.stderr.write(f'Failed for installment {installment.pk}: {exc}')

        self.stdout.write(self.style.SUCCESS(
            f'Reminders: {reminders} · Overdue: {overdue} · Skipped (cooldown): {skipped} '
            f'(due by {cutoff}).))'
        ))
