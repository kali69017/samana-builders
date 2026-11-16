from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, Voucher, VoucherLine
from payments.models import Payment, Refund
from properties.models import Plot, Project


class CashBasisWritingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('cash', 'cash@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.receivable = AccountHead.objects.get(system_role='receivable')
        self.customer = Customer.objects.create(
            first_name='Cash', last_name='Basis', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(name='Cash P', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='C-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )

    def test_booking_does_not_post_and_cancel_reopen_do_not_post(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed', created_by=self.user,
        )
        self.assertFalse(Voucher.objects.filter(reference_type='Booking').exists())
        booking.status = 'cancelled'
        booking.save()
        booking.status = 'pending'
        booking.save()
        self.assertFalse(Voucher.objects.filter(
            reference_type__in=['BookingCancel', 'BookingReopen']).exists())

    def test_pending_and_confirmed_payments_credit_advances(self):
        for status in ('pending', 'confirmed'):
            booking = Booking.objects.create(
                customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
                status=status, created_by=self.user,
            )
            payment = Payment.objects.create(
                booking=booking, received_into=self.cash, amount=Decimal('100'),
                payment_date=date.today(), payment_method='cash', status='verified',
                created_by=self.user,
            )
            voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
            self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.cash)
            self.assertEqual(voucher.lines.get(credit__gt=0).account_head,
                             AccountHead.objects.get(system_role='customer_advances'))

    def test_refund_before_delivery_debits_advances_and_credits_cash(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            status='confirmed', created_by=self.user,
        )
        refund = Refund.objects.create(
            booking=booking, paid_from=self.bank, amount=Decimal('50'),
            reason='overpayment', refund_method='bank_transfer', status='approved',
        )
        refund.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='Refund', reference_id=refund.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head,
                         AccountHead.objects.get(system_role='customer_advances'))
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.bank)

    def test_receivable_is_seeded_and_advances_are_used(self):
        self.assertIsNotNone(self.receivable)
        self.assertIsNotNone(AccountHead.objects.get(system_role='customer_advances'))
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            status='confirmed', created_by=self.user,
        )
        payment = Payment.objects.create(
            booking=booking, received_into=self.cash, amount=Decimal('100'),
            payment_date=date.today(), payment_method='cash', status='verified',
            created_by=self.user,
        )
        roles = set(VoucherLine.objects.filter(
            voucher__reference_type='Payment', voucher__reference_id=payment.pk,
        ).values_list('account_head__system_role', flat=True))
        self.assertEqual(roles, {'cash_default', 'customer_advances'})

    def test_backfill_does_not_create_booking_vouchers(self):
        Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            status='confirmed', created_by=self.user,
        )
        call_command('backfill_finance_links', stdout=StringIO())
        self.assertFalse(Voucher.objects.filter(reference_type='Booking').exists())


class CashBasisConversionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('conv', 'conv@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.receivable = AccountHead.objects.get(system_role='receivable')
        self.customer = Customer.objects.create(
            first_name='Conv', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(name='Conv P', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='V-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed', created_by=self.user,
        )
        self.booking_voucher = self._old_voucher(
            'Booking', self.booking.pk, self.booking.booking_date,
            [(self.receivable, Decimal('1000'), Decimal('0')),
             (self.revenue, Decimal('0'), Decimal('1000'))],
        )
        self.payment_voucher = self._old_voucher(
            'Payment', 777, date.today(),
            [(self.cash, Decimal('100'), Decimal('0')),
             (self.receivable, Decimal('0'), Decimal('100'))],
        )

    def _old_voucher(self, reference_type, reference_id, voucher_date, lines):
        voucher = Voucher.objects.create(
            voucher_type='JV', date=voucher_date,
            narration=f'Old {reference_type}', reference_type=reference_type,
            reference_id=reference_id, created_by=self.user,
        )
        for head, debit, credit in lines:
            VoucherLine.objects.create(
                voucher=voucher, account_head=head, debit=debit, credit=credit,
            )
        voucher.post(self.user)
        return voucher

    def _balance(self, account):
        debit = sum((l.debit for l in VoucherLine.objects.filter(
            voucher__status='posted', account_head=account)), Decimal('0'))
        credit = sum((l.credit for l in VoucherLine.objects.filter(
            voucher__status='posted', account_head=account)), Decimal('0'))
        if account.nature == 'credit':
            return credit - debit
        return debit - credit

    def _report_numbers(self):
        self.client.force_login(self.user)
        dashboard = self.client.get('/dashboard/')
        financial = self.client.get('/reports/financial/')
        receivables = self.client.get('/reports/receivables/')
        sales = self.client.get('/reports/sales/')
        return (
            dashboard.context['total_revenue'],
            financial.context['total_revenue'],
            receivables.context['total_receivables'],
            sales.context['total_sales'],
        )

    def test_dry_run_posts_nothing(self):
        before = Voucher.objects.count()
        call_command('convert_to_cash_basis', '--dry-run', stdout=StringIO())
        self.assertEqual(Voucher.objects.count(), before)
        self.assertEqual(self._balance(self.receivable), Decimal('900.00'))

    def test_conversion_posts_once_and_leaves_receivable_zero(self):
        self.assertEqual(self._balance(self.receivable), Decimal('900.00'))
        call_command('convert_to_cash_basis', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='CashBasisConversion').count(), 2)
        self.assertEqual(self._balance(self.receivable), Decimal('0.00'))
        self.assertEqual(self._balance(self.revenue), Decimal('100.00'))
        self.booking_voucher.refresh_from_db()
        self.payment_voucher.refresh_from_db()
        self.assertEqual(self.booking_voucher.narration, 'Old Booking')
        self.assertEqual(self.payment_voucher.narration, 'Old Payment')
        call_command('convert_to_cash_basis', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='CashBasisConversion').count(), 2)

    def test_reports_and_dashboard_do_not_change(self):
        before = self._report_numbers()
        call_command('convert_to_cash_basis', stdout=StringIO())
        after = self._report_numbers()
        self.assertEqual(before, after)
