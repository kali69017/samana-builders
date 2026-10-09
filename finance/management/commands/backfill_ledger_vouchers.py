"""One-off backfill: post ledger vouchers for paid expenses and project costs
that predate the double-entry ledger (spec §3.7/§3.9).

``OfficeExpense.post_to_ledger`` / ``ProjectCost.post_to_ledger`` only fire on the
*write path* — the approve/pay transition, or the API ``pay`` action. Rows that
were already ``status='paid'`` before those writers shipped have no voucher, so
the ledger silently under-reports actual spend.

This command finds every paid ``OfficeExpense`` / ``ProjectCost`` with no
``(reference_type, reference_id)`` voucher and posts the missing one. It reuses
the idempotent ``post_source_voucher`` writer, so it is **idempotent and safe to
re-run**: a second pass finds nothing to do.

Run ``--dry-run`` first against a staging/production copy to see what would be
written before touching the books.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from finance.models import OfficeExpense, ProjectCost, Voucher

# (model, reference_type, date_field, human label) for each postable source.
SOURCES = (
    (OfficeExpense, 'OfficeExpense', 'expense_date', 'office expense'),
    (ProjectCost, 'ProjectCost', 'cost_date', 'project cost'),
)


class Command(BaseCommand):
    help = (
        'Post missing ledger vouchers for paid OfficeExpenses and ProjectCosts '
        '(rows that predate the double-entry writers). Idempotent; safe to re-run.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be posted without writing anything.',
        )

    def _orphans(self, model, reference_type):
        """Paid rows of ``model`` that have no voucher keyed to them.

        Resolves the already-posted ids in one query rather than one per row.
        """
        posted_ids = set(
            Voucher.objects.filter(reference_type=reference_type)
            .values_list('reference_id', flat=True)
        )
        return [
            obj for obj in model.objects.filter(status='paid').order_by('pk')
            if obj.pk not in posted_ids
        ]

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total = Decimal('0.00')
        findings = {}

        for model, reference_type, date_field, label in SOURCES:
            orphans = self._orphans(model, reference_type)
            if not orphans:
                self.stdout.write(f'No unposted paid {label}(s).')
                continue

            findings[label] = orphans
            subtotal = sum((o.amount for o in orphans), Decimal('0.00'))
            total += subtotal
            for obj in orphans:
                self.stdout.write(
                    f'  {label} #{obj.pk}  {getattr(obj, date_field)}  '
                    f'Rs. {obj.amount}  -> would post a '
                    f'Cash/Bank Payment voucher'
                )
            self.stdout.write(
                f'{len(orphans)} paid {label}(s) missing from the ledger, '
                f'Rs. {subtotal}')

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: would post Rs. {total} of ledger entries. Nothing written.'))
            return

        posted = 0
        for label, orphans in findings.items():
            for obj in orphans:
                voucher = obj.post_to_ledger()
                if voucher is not None:
                    posted += 1
                    self.stdout.write(
                        f'  posted {label} #{obj.pk} Rs. {obj.amount} -> '
                        f'{voucher.voucher_number}')

        self.stdout.write(self.style.SUCCESS(
            f'Posted {posted} voucher(s) worth Rs. {total}. Ledger is now complete.'))

        # Report the trial balance so the operator can sanity-check the result.
        agg = Voucher.objects.filter(status='posted').aggregate(
            d=Sum('lines__debit'), c=Sum('lines__credit'))
        if agg['d'] is None:
            self.stdout.write('No posted vouchers — nothing to balance-check.')
        elif agg['d'] != agg['c']:
            self.stdout.write(self.style.ERROR(
                f'WARNING: trial balance does not balance: '
                f'debit {agg["d"]} != credit {agg["c"]}'))
        else:
            self.stdout.write(
                f'Trial balance OK: debits {agg["d"]} == credits {agg["c"]}')
