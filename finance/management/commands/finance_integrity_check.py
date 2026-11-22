from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from finance.models import Voucher, VoucherLine
from finance.accounting import customer_advance_head
from payments.models import Payment, Refund


class Command(BaseCommand):
    help = (
        'Check posted debits equal credits, no root postings, payment vouchers '
        'match payment status, verified payments have receipt vouchers, and '
        'Customer Advances matches payments minus refunds for undelivered bookings.'
    )

    def handle(self, *args, **options):
        agg = VoucherLine.objects.filter(voucher__status='posted').aggregate(
            debit=Sum('debit'), credit=Sum('credit'))
        debit = agg['debit'] or Decimal('0.00')
        credit = agg['credit'] or Decimal('0.00')
        root_lines = VoucherLine.objects.filter(
            voucher__status='posted', account_head__parent__isnull=True,
        ).count()
        unbalanced = 0
        for voucher in VoucherLine.objects.filter(voucher__status='posted').values_list(
                'voucher_id', flat=True).distinct():
            line_agg = VoucherLine.objects.filter(voucher_id=voucher).aggregate(
                debit=Sum('debit'), credit=Sum('credit'))
            if (line_agg['debit'] or 0) != (line_agg['credit'] or 0):
                unbalanced += 1

        payment_issues = []
        for voucher in Voucher.objects.filter(
                reference_type='Payment', status='posted').order_by('id'):
            payment = Payment.objects.filter(pk=voucher.reference_id).first()
            if payment is None:
                payment_issues.append(
                    f'{voucher.voucher_number}: missing Payment #{voucher.reference_id}')
                continue
            reversals = list(Voucher.objects.filter(
                reference_type='PaymentReversal',
                reference_id=payment.pk,
                status='posted',
            ).order_by('id'))
            if payment.status == 'verified':
                if reversals:
                    payment_issues.append(
                        f'{payment.payment_id}: verified payment has a reversal')
            else:
                if len(reversals) != 1:
                    payment_issues.append(
                        f'{payment.payment_id}: status {payment.status} has '
                        f'{len(reversals)} reversal vouchers')
                elif reversals[0].total_debit != payment.amount:
                    payment_issues.append(
                        f'{payment.payment_id}: reversal amount '
                        f'{reversals[0].total_debit} does not match {payment.amount}')

        receipt_issues = []
        for payment in Payment.objects.filter(status='verified').order_by('id'):
            count = Voucher.objects.filter(
                reference_type='Payment', reference_id=payment.pk,
                status='posted').count()
            if count != 1:
                receipt_issues.append(
                    f'{payment.payment_id}: {count} receipt vouchers')

        advances = customer_advance_head()
        advances_lines = VoucherLine.objects.filter(
            voucher__status='posted', account_head=advances,
        ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
        advances_balance = (
            (advances_lines['credit'] or Decimal('0.00'))
            - (advances_lines['debit'] or Decimal('0.00'))
        )
        expected_payments = Payment.objects.filter(
            status='verified', booking__delivery_date__isnull=True,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expected_refunds = Refund.objects.filter(
            status='processed', booking__delivery_date__isnull=True,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        expected_advances = expected_payments - expected_refunds
        advances_mismatch = advances_balance != expected_advances

        self.stdout.write(f'Posted debit total: {debit}')
        self.stdout.write(f'Posted credit total: {credit}')
        self.stdout.write(f'Difference: {debit - credit}')
        self.stdout.write(f'Unbalanced posted vouchers: {unbalanced}')
        self.stdout.write(f'Posted lines on level 1 roots: {root_lines}')
        self.stdout.write(f'Payment posting issues: {len(payment_issues)}')
        for issue in payment_issues:
            self.stdout.write(f'  {issue}')
        self.stdout.write(f'Verified payment receipt issues: {len(receipt_issues)}')
        for issue in receipt_issues:
            self.stdout.write(f'  {issue}')
        self.stdout.write(f'Customer Advances balance: {advances_balance}')
        self.stdout.write(
            f'Customer Advances expected for undelivered bookings: {expected_advances}')
        if advances_mismatch:
            self.stdout.write(
                f'Customer Advances mismatch: {advances_balance - expected_advances}')
        if (
            debit != credit or unbalanced or root_lines
            or payment_issues or receipt_issues or advances_mismatch
        ):
            raise CommandError('Finance integrity check failed.')
        self.stdout.write(self.style.SUCCESS('Finance integrity check passed.'))
