"""One-off backfill: link customers with pre-existing confirmed bookings to the
shared Accounts Receivable control head (spec §3.12/§3.18).

The save()-time trigger only fires on a future confirmed transition, so this
command links customers whose bookings were already confirmed before the
trigger shipped. Idempotent and safe to re-run.
"""
from django.core.management.base import BaseCommand

from customers.models import Customer
from finance.accounting import receivable_head


class Command(BaseCommand):
    help = (
        'Link "mature" customers (those with a confirmed booking) to the shared '
        'Accounts Receivable control head. Idempotent; safe to re-run.'
    )

    def handle(self, *args, **options):
        head = receivable_head()
        customers = (
            Customer.objects
            .filter(account_head__isnull=True, bookings__status='confirmed')
            .distinct()
        )
        linked = 0
        for customer in customers:
            customer.account_head = head
            customer.save(update_fields=['account_head'])
            linked += 1
        self.stdout.write(self.style.SUCCESS(
            f'Linked {linked} customer(s) to {head.code} {head.name}.'))