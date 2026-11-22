from django.core.management.base import BaseCommand

from finance.models import Voucher
from finance.accounting import post_payment_reversal
from payments.models import Payment


class Command(BaseCommand):
    help = (
        'Repair legacy payment posting mismatches without deleting vouchers. '
        'Reverses receipts on non-verified payments and posts missing receipts '
        'for verified payments.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List the corrections without posting anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        receipt_ids = set(Voucher.objects.filter(
            reference_type='Payment', status='posted',
        ).values_list('reference_id', flat=True))
        reversal_ids = set(Voucher.objects.filter(
            reference_type='PaymentReversal', status='posted',
        ).values_list('reference_id', flat=True))

        non_verified = Payment.objects.filter(
            pk__in=receipt_ids).exclude(status='verified').order_by('id')
        missing_receipt = Payment.objects.filter(
            status='verified').exclude(pk__in=receipt_ids).order_by('id')

        reversals_needed = [
            payment for payment in non_verified if payment.pk not in reversal_ids
        ]
        self.stdout.write(
            f'Non-verified payments with receipts needing reversal: '
            f'{len(reversals_needed)}')
        for payment in reversals_needed:
            self.stdout.write(
                f'  {payment.payment_id} status={payment.status} '
                f'amount={payment.amount}')
        self.stdout.write(
            f'Verified payments missing receipts: {missing_receipt.count()}')
        for payment in missing_receipt:
            self.stdout.write(
                f'  {payment.payment_id} amount={payment.amount}')

        if dry_run:
            self.stdout.write('DRY_RUN: no changes made.')
            return

        reversed_count = 0
        for payment in reversals_needed:
            voucher = post_payment_reversal(payment)
            if voucher is not None:
                reversed_count += 1
                self.stdout.write(
                    f'  reversed {payment.payment_id} with {voucher.voucher_number}')

        receipt_count = 0
        for payment in missing_receipt:
            voucher = payment.post_to_ledger()
            if voucher is not None:
                receipt_count += 1
                self.stdout.write(
                    f'  posted {payment.payment_id} receipt {voucher.voucher_number}')

        self.stdout.write(
            f'Corrections posted: reversals={reversed_count} receipts={receipt_count}')
