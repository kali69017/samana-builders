"""Send payment reminders for installments due soon (or already overdue).

Usage:
    python manage.py send_installment_reminders --days=7
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.models import Installment
from notifications.services import NotificationService


class Command(BaseCommand):
    help = 'Send SMS/email reminders for installments due within the next N days.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=7,
            help='Remind installments due within this many days (default 7).',
        )

    def handle(self, *args, **options):
        days = options['days']
        today = timezone.localdate()
        cutoff = today + timedelta(days=days)

        installments = (
            Installment.objects
            .filter(status__in=['pending', 'overdue', 'partial'], due_date__lte=cutoff)
            .select_related('plan__booking__customer', 'plan__booking__plot', 'plan__booking__plot__project')
            .order_by('due_date')
        )

        sent = 0
        for installment in installments:
            try:
                NotificationService.send_installment_reminder(installment)
                sent += 1
            except Exception as exc:
                self.stderr.write(f'Failed for installment {installment.pk}: {exc}')

        self.stdout.write(self.style.SUCCESS(f'Sent {sent} installment reminders (due by {cutoff}).'))
