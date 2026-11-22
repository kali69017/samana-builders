"""Convert existing accrual-basis vouchers to the cash-basis mapping.

The conversion is additive: existing vouchers are never edited or deleted.
For each old Booking voucher it posts Dr Revenue / Cr Receivable, and for each
old Payment voucher that credited Receivable it posts Dr Receivable / Cr Revenue.
Every conversion is idempotent on (CashBasisConversion, source voucher id).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from finance.accounting import post_source_voucher, receivable_head, revenue_head
from finance.models import Voucher, VoucherLine


class Command(BaseCommand):
    help = (
        'ONE-TIME LEGACY TOOL: convert old accrual-basis vouchers to the '
        'deprecated cash-basis mapping for verified payments. Do not run on a '
        'new database.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def _balance(self, account):
        agg = VoucherLine.objects.filter(
            voucher__status='posted', account_head=account,
        ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
        debit = agg['debit'] or Decimal('0.00')
        credit = agg['credit'] or Decimal('0.00')
        if account.nature == 'credit':
            return credit - debit
        return debit - credit

    def _conversion_exists(self, source):
        return Voucher.objects.filter(
            reference_type='CashBasisConversion', reference_id=source.pk,
        ).exists()

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            'DEPRECATED: cash basis is no longer the accounting model. '
            'This command is kept for history only.'))
        dry = options['dry_run']
        receivable = receivable_head()
        revenue = revenue_head()
        before_ar = self._balance(receivable)
        before_revenue = self._balance(revenue)

        payment_journals = 0
        booking_journals = 0
        skipped_unverified = 0
        from payments.models import Payment

        for voucher in Voucher.objects.filter(
                reference_type='Payment', status='posted',
        ):
            if self._conversion_exists(voucher):
                continue
            payment = Payment.objects.filter(pk=voucher.reference_id).first()
            if payment is None or payment.status != 'verified':
                skipped_unverified += 1
                continue
            credited_ar = voucher.lines.filter(
                account_head=receivable, credit__gt=0,
            ).aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
            if credited_ar <= 0:
                continue
            payment_journals += 1
            if dry:
                continue
            post_source_voucher(
                reference_type='CashBasisConversion', reference_id=voucher.pk,
                voucher_type='JV', date=payment.payment_date if payment else voucher.date,
                narration=f'Cash basis conversion for Payment voucher {voucher.voucher_number}',
                lines=[
                    (receivable, credited_ar, Decimal('0.00')),
                    (revenue, Decimal('0.00'), credited_ar),
                ],
                user=voucher.created_by,
            )

        for voucher in Voucher.objects.filter(
                reference_type='Booking', status='posted',
        ):
            if self._conversion_exists(voucher):
                continue
            amount = voucher.total_debit
            if amount <= 0:
                continue
            booking_journals += 1
            if dry:
                continue
            from bookings.models import Booking
            booking = Booking.objects.filter(pk=voucher.reference_id).first()
            post_source_voucher(
                reference_type='CashBasisConversion', reference_id=voucher.pk,
                voucher_type='JV', date=booking.booking_date if booking else voucher.date,
                narration=f'Cash basis conversion for Booking voucher {voucher.voucher_number}',
                lines=[
                    (revenue, amount, Decimal('0.00')),
                    (receivable, Decimal('0.00'), amount),
                ],
                user=voucher.created_by,
            )

        after_ar = self._balance(receivable)
        after_revenue = self._balance(revenue)
        prefix = 'Would post' if dry else 'Posted'
        self.stdout.write(
            f'{prefix} {payment_journals} payment correction(s) and '
            f'{booking_journals} booking reversal(s).')
        if skipped_unverified:
            self.stdout.write(
                f'Skipped {skipped_unverified} unverified payment(s); '
                'their vouchers are not converted.')
        self.stdout.write(f'Receivable balance before: {before_ar}')
        self.stdout.write(f'Receivable balance after: {after_ar}')
        self.stdout.write(f'Revenue balance before: {before_revenue}')
        self.stdout.write(f'Revenue balance after: {after_revenue}')
