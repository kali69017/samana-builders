"""One-off backfill: link customers with pre-existing confirmed bookings to the
shared Accounts Receivable control head (spec §3.12/§3.18).

The save()-time trigger only fires on a future confirmed transition, so this
command links customers whose bookings were already confirmed before the
trigger shipped. Idempotent and safe to re-run.

Run ``--dry-run`` first against a staging/production copy to see the count
without writing anything.
"""
from django.core.management.base import BaseCommand

from customers.models import Customer
from finance.accounting import RECEIVABLE, receivable_head


class Command(BaseCommand):
    help = (
        'Link "mature" customers (those with a confirmed booking) to the shared '
        'Accounts Receivable control head. Idempotent; safe to re-run.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report how many customers would be linked without writing.',
        )

    def handle(self, *args, **options):
        customers = (
            Customer.objects
            .filter(account_head__isnull=True, bookings__status='confirmed')
            .distinct()
        )
        count = customers.count()

        if options['dry_run']:
            from finance.models import AccountHead
            head = AccountHead.objects.filter(code=RECEIVABLE[0]).first()
            target = (f'{head.code} {head.name}' if head
                      else f'{RECEIVABLE[0]} {RECEIVABLE[1]} (not yet created)')
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: would link {count} customer(s) to {target}.'))
            return

        head = receivable_head()
        linked = 0
        for customer in customers:
            customer.account_head = head
            customer.save(update_fields=['account_head'])
            linked += 1
        self.stdout.write(self.style.SUCCESS(
            f'Linked {linked} customer(s) to {head.code} {head.name}.'))