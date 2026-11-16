from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from finance.models import AccountHead, VoucherLine
from finance.accounting import booking_net_advances, customer_advance_head


class Command(BaseCommand):
    help = ('Check posted debits equal credits, no root postings, and that Customer '
            'Advances matches posted payments minus refunds for undelivered bookings.')

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

        advances = customer_advance_head()
        advances_lines = VoucherLine.objects.filter(
            voucher__status='posted', account_head=advances,
        ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
        advances_balance = (
            (advances_lines['credit'] or Decimal('0.00'))
            - (advances_lines['debit'] or Decimal('0.00'))
        )
        from bookings.models import Booking
        expected_advances = sum(
            (booking_net_advances(booking)
             for booking in Booking.objects.filter(delivery_date__isnull=True)),
            Decimal('0.00'),
        )
        advances_mismatch = advances_balance != expected_advances

        self.stdout.write(f'Posted debit total: {debit}')
        self.stdout.write(f'Posted credit total: {credit}')
        self.stdout.write(f'Difference: {debit - credit}')
        self.stdout.write(f'Unbalanced posted vouchers: {unbalanced}')
        self.stdout.write(f'Posted lines on level 1 roots: {root_lines}')
        self.stdout.write(f'Customer Advances balance: {advances_balance}')
        self.stdout.write(
            f'Customer Advances expected for undelivered bookings: {expected_advances}')
        if advances_mismatch:
            self.stdout.write(
                f'Customer Advances mismatch: {advances_balance - expected_advances}')
        if debit != credit or unbalanced or root_lines or advances_mismatch:
            raise CommandError('Finance integrity check failed.')
        self.stdout.write(self.style.SUCCESS('Finance integrity check passed.'))
