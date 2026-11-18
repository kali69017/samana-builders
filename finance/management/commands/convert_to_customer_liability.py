"""Convert payment vouchers that credited revenue to the customer-liability model.

Existing vouchers are never edited. For each undelivered booking payment whose
posted voucher credited revenue, this posts an additive correcting journal:
Dr Revenue / Cr Customer Advances & Bookings. Idempotent on
(LiabilityConversion, source voucher id).
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum

from finance.accounting import (
    customer_advance_head, post_source_voucher, receivable_head, revenue_head,
)
from finance.models import Voucher, VoucherLine


class Command(BaseCommand):
    help = ('Post correcting journals from cash-basis revenue to Customer '
            'Advances & Bookings for payments on undelivered bookings.')

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
            reference_type='LiabilityConversion', reference_id=source.pk,
        ).exists()

    def handle(self, *args, **options):
        dry = options['dry_run']
        revenue = revenue_head()
        advances = customer_advance_head()
        before_revenue = self._balance(revenue)
        before_advances = self._balance(advances)
        receivable = receivable_head()

        corrections = 0
        total = Decimal('0.00')
        skipped_delivered = 0
        cash_basis_source_ids = set(Voucher.objects.filter(
            reference_type='CashBasisConversion', status='posted',
        ).values_list('reference_id', flat=True))
        vouchers = Voucher.objects.filter(
            reference_type__in=['Payment', 'Refund', 'CashBasisConversion'],
            status='posted',
        ).order_by('id')

        def post_correction(voucher, amount, debit, credit, label):
            nonlocal corrections, total
            corrections += 1
            total += amount
            if dry:
                return
            post_source_voucher(
                reference_type='LiabilityConversion', reference_id=voucher.pk,
                voucher_type='JV', date=voucher.date,
                narration=(
                    f'Customer liability conversion for {label} voucher '
                    f'{voucher.voucher_number}'
                ),
                lines=[
                    (debit, amount, Decimal('0.00')),
                    (credit, Decimal('0.00'), amount),
                ],
                user=voucher.created_by,
            )

        for voucher in vouchers:
            if self._conversion_exists(voucher):
                continue
            from payments.models import Payment, Refund

            amount = Decimal('0.00')
            debit = None
            credit = None
            label = voucher.reference_type

            if voucher.reference_type == 'CashBasisConversion':
                source_voucher = Voucher.objects.filter(pk=voucher.reference_id).first()
                if source_voucher is None or source_voucher.reference_type != 'Payment':
                    continue
                payment = Payment.objects.select_related('booking').filter(
                    pk=source_voucher.reference_id).first()
                if payment is None:
                    continue
                if (payment.booking.delivery_date is not None
                        and payment.payment_date >= payment.booking.delivery_date):
                    skipped_delivered += 1
                    continue
                amount = voucher.lines.filter(
                    account_head=revenue, credit__gt=0,
                ).aggregate(total=Sum('credit'))['total'] or Decimal('0.00')
                debit, credit = revenue, advances
                label = 'cash-basis payment'

            elif voucher.reference_type == 'Payment':
                if voucher.pk in cash_basis_source_ids:
                    # The paired CashBasisConversion voucher is the correction point.
                    continue
                payment = Payment.objects.select_related('booking').filter(
                    pk=voucher.reference_id).first()
                if payment is None:
                    continue
                delivered = bool(
                    payment.booking.delivery_date
                    and payment.payment_date >= payment.booking.delivery_date
                )
                line = voucher.lines.filter(credit__gt=0).select_related(
                    'account_head').first()
                if line is None or line.account_head in (advances,):
                    continue
                amount = line.credit
                if line.account_head == revenue:
                    if delivered:
                        skipped_delivered += 1
                        continue
                    debit, credit = revenue, advances
                elif line.account_head == receivable:
                    debit = receivable
                    credit = revenue if delivered else advances
                else:
                    continue

            elif voucher.reference_type == 'Refund':
                refund = Refund.objects.select_related('booking').filter(
                    pk=voucher.reference_id).first()
                if refund is None:
                    continue
                post_date = refund.refund_date or voucher.date
                delivered = bool(
                    refund.booking.delivery_date
                    and post_date >= refund.booking.delivery_date
                )
                line = voucher.lines.filter(debit__gt=0).select_related(
                    'account_head').first()
                if line is None or line.account_head in (advances,):
                    continue
                amount = line.debit
                if line.account_head == revenue:
                    if delivered:
                        skipped_delivered += 1
                        continue
                    debit, credit = advances, revenue
                elif line.account_head == receivable:
                    debit = revenue if delivered else advances
                    credit = receivable
                else:
                    continue

            if amount <= 0 or debit is None or credit is None:
                continue
            post_correction(voucher, amount, debit, credit, label)

        after_revenue = self._balance(revenue)
        after_advances = self._balance(advances)
        prefix = 'Would post' if dry else 'Posted'
        self.stdout.write(
            f'{prefix} {corrections} customer liability correction(s) '
            f'totalling {total}.')
        if skipped_delivered:
            self.stdout.write(
                f'Skipped {skipped_delivered} delivered-booking payment(s); '
                'their revenue is already correct.')
        self.stdout.write(f'Revenue balance before: {before_revenue}')
        self.stdout.write(f'Revenue balance after: {after_revenue}')
        self.stdout.write(f'Customer Advances balance before: {before_advances}')
        self.stdout.write(f'Customer Advances balance after: {after_advances}')
