import importlib
from datetime import date
from decimal import Decimal
from io import StringIO

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, Voucher, VoucherLine

chart_migration = importlib.import_module(
    'finance.migrations.0015_customer_advances_liability')
from payments.models import Payment, Refund
from properties.models import Plot, Project


class CustomerLiabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('liability', 'liability@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.receivable = AccountHead.objects.get(system_role='receivable')
        self.advances = AccountHead.objects.get(system_role='customer_advances')
        self.customer = Customer.objects.create(
            first_name='Liability', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(name='Liability P', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='L-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )

    def _booking(self, status='active', advance=Decimal('0')):
        return Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=advance, status=status, created_by=self.user,
        )

    def _payment(self, booking, amount=Decimal('100'), method='cash', status='verified'):
        return Payment.objects.create(
            booking=booking, received_into=self.cash if method == 'cash' else self.bank,
            amount=amount, payment_date=date.today(), payment_method=method,
            status=status, created_by=self.user,
        )

    def _refund(self, booking, amount=Decimal('20'), method='bank_transfer'):
        refund = Refund.objects.create(
            booking=booking, paid_from=self.bank, amount=amount,
            reason='overpayment', refund_method=method, status='approved',
        )
        refund.post_to_ledger()
        return refund

    def _balance(self, account):
        agg = VoucherLine.objects.filter(
            voucher__status='posted', account_head=account,
        ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
        debit = agg['debit'] or Decimal('0.00')
        credit = agg['credit'] or Decimal('0.00')
        if account.nature == 'credit':
            return credit - debit
        return debit - credit

    def test_payment_credits_advances_for_all_booking_statuses(self):
        for status in ('pending', 'confirmed', 'active', 'completed'):
            booking = self._booking(status=status)
            payment = self._payment(booking)
            voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
            self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.cash)
            self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.advances)

    def test_refund_before_delivery_debits_advances(self):
        booking = self._booking()
        self._payment(booking)
        refund = self._refund(booking)
        voucher = Voucher.objects.get(reference_type='Refund', reference_id=refund.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.advances)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.bank)
        self.assertEqual(self._balance(self.advances), Decimal('80.00'))

    def test_delivery_posts_net_advances_and_is_idempotent(self):
        booking = self._booking()
        self._payment(booking)
        self._refund(booking)
        booking.mark_delivered(self.user, date.today())
        voucher = Voucher.objects.get(
            reference_type='BookingDelivery', reference_id=booking.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.advances)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.revenue)
        self.assertEqual(voucher.total_debit, Decimal('80.00'))
        self.assertEqual(self._balance(self.advances), Decimal('0.00'))
        self.assertEqual(self._balance(self.revenue), Decimal('80.00'))
        with self.assertRaises(ValidationError):
            booking.mark_delivered(self.user, date.today())
        self.assertEqual(Voucher.objects.filter(
            reference_type='BookingDelivery', reference_id=booking.pk).count(), 1)

    def test_payment_after_delivery_credits_revenue(self):
        booking = self._booking()
        self._payment(booking)
        booking.mark_delivered(self.user, date.today())
        payment = self._payment(booking, amount=Decimal('50'))
        voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.revenue)
        self.assertEqual(self._balance(self.revenue), Decimal('150.00'))

    def test_refund_after_delivery_debits_revenue(self):
        booking = self._booking()
        self._payment(booking)
        booking.mark_delivered(self.user, date.today())
        refund = self._refund(booking)
        voucher = Voucher.objects.get(reference_type='Refund', reference_id=refund.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.revenue)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.bank)
        self.assertEqual(self._balance(self.revenue), Decimal('80.00'))

    def test_delivery_blocked_for_pending_and_cancelled(self):
        for status in ('pending', 'cancelled'):
            booking = self._booking(status=status)
            with self.assertRaises(ValidationError):
                booking.mark_delivered(self.user, date.today())

    def test_confirmed_booking_can_be_delivered(self):
        booking = self._booking(status='confirmed')
        self._payment(booking)
        booking.mark_delivered(self.user, date.today())
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')
        self.assertEqual(booking.delivery_date, date.today())
        self.assertTrue(Voucher.objects.filter(
            reference_type='BookingDelivery', reference_id=booking.pk).exists())

    def test_confirmed_booking_shows_delivery_button_and_view(self):
        booking = self._booking(status='confirmed')
        self._payment(booking)
        self.client.force_login(self.user)
        detail = self.client.get(reverse('booking_detail', args=[booking.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Mark as Delivered')
        response = self.client.get(reverse('booking_deliver', args=[booking.pk]))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('booking_deliver', args=[booking.pk]), {
            'delivery_date': date.today().isoformat(),
            'confirm_unpaid': 'on',
        })
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'completed')
        self.assertEqual(booking.delivery_date, date.today())

    def test_delivery_date_cannot_be_future(self):
        booking = self._booking()
        with self.assertRaises(ValidationError):
            booking.mark_delivered(self.user, date(2099, 1, 1))

    def test_delivery_warning_requires_confirmation(self):
        booking = self._booking()
        self._payment(booking)
        self.client.force_login(self.user)
        url = reverse('booking_deliver', args=[booking.pk])
        response = self.client.get(url)
        self.assertContains(response, 'Unpaid balance')
        response = self.client.post(url, {'delivery_date': date.today().isoformat()})
        self.assertEqual(response.status_code, 200)
        booking.refresh_from_db()
        self.assertIsNone(booking.delivery_date)
        response = self.client.post(url, {
            'delivery_date': date.today().isoformat(),
            'confirm_unpaid': 'on',
        })
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.delivery_date, date.today())

    def test_chart_has_one_liability_control_head(self):
        self.assertFalse(AccountHead.objects.filter(
            name__iexact='Advances & Bookings', parent__code='1.2').exists())
        self.assertEqual(self.advances.name, 'Customer Advances & Bookings')
        self.assertEqual(self.advances.root.code, '2')
        self.assertEqual(self.advances.parent.code, '2.1')

    def test_chart_migration_removes_unused_fixed_asset_head(self):
        fixed_assets = AccountHead.objects.get(code='1.2')
        stale = AccountHead.objects.create(
            name='Advances & Bookings', parent=fixed_assets,
        )
        chart_migration.move_customer_advances(django_apps, None)
        self.assertFalse(AccountHead.objects.filter(pk=stale.pk).exists())
        self.assertEqual(
            AccountHead.objects.get(system_role='customer_advances').name,
            'Customer Advances & Bookings',
        )

    def test_chart_migration_stops_when_fixed_asset_head_has_lines(self):
        fixed_assets = AccountHead.objects.get(code='1.2')
        stale = AccountHead.objects.create(
            name='Advances & Bookings', parent=fixed_assets,
        )
        voucher = Voucher.objects.create(
            voucher_type='JV', date=date.today(), narration='Legacy fixed asset use',
            created_by=self.user,
        )
        VoucherLine.objects.create(
            voucher=voucher, account_head=stale, debit=Decimal('10'), credit=0)
        VoucherLine.objects.create(
            voucher=voucher, account_head=self.cash, debit=0, credit=Decimal('10'))
        with self.assertRaises(RuntimeError):
            chart_migration.move_customer_advances(django_apps, None)
        self.assertTrue(AccountHead.objects.filter(pk=stale.pk).exists())

    def test_integrity_check_reports_advances_mismatch(self):
        booking = self._booking()
        self._payment(booking)
        out = StringIO()
        call_command('finance_integrity_check', stdout=out)
        self.assertIn('Customer Advances balance: 100.00', out.getvalue())
        manual = Voucher.objects.create(
            voucher_type='JV', date=date.today(), narration='Bad manual posting',
            created_by=self.user,
        )
        VoucherLine.objects.create(
            voucher=manual, account_head=self.cash, debit=Decimal('5'), credit=0)
        VoucherLine.objects.create(
            voucher=manual, account_head=self.advances, debit=0, credit=Decimal('5'))
        manual.post(self.user)
        with self.assertRaises(Exception):
            call_command('finance_integrity_check', stdout=StringIO())

    def test_liability_conversion_corrects_cash_basis_payment(self):
        booking = self._booking()
        payment = self._payment(booking)
        voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE finance_voucherline SET account_head_id = %s '
                'WHERE voucher_id = %s AND credit > 0',
                [self.revenue.pk, voucher.pk],
            )
        call_command('convert_to_customer_liability', '--dry-run', stdout=StringIO())
        self.assertEqual(self._balance(self.revenue), Decimal('100.00'))
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertEqual(self._balance(self.revenue), Decimal('0.00'))
        self.assertEqual(self._balance(self.advances), Decimal('100.00'))
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='LiabilityConversion').count(), 1)

    def test_liability_conversion_handles_cash_basis_journal(self):
        booking = self._booking()
        payment = self._payment(booking)
        payment_voucher = Voucher.objects.get(
            reference_type='Payment', reference_id=payment.pk)
        cash_basis = Voucher.objects.create(
            voucher_type='JV', date=payment.payment_date,
            narration=f'Cash basis conversion for Payment voucher {payment_voucher.voucher_number}',
            reference_type='CashBasisConversion', reference_id=payment_voucher.pk,
            created_by=self.user,
        )
        VoucherLine.objects.create(
            voucher=cash_basis, account_head=self.revenue,
            debit=0, credit=Decimal('100'))
        VoucherLine.objects.create(
            voucher=cash_basis, account_head=self.cash,
            debit=Decimal('100'), credit=0)
        cash_basis.post(self.user)
        # Make the payment voucher non-revenue, as the old cash-basis data is.
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE finance_voucherline SET account_head_id = %s '
                'WHERE voucher_id = %s AND credit > 0',
                [self.cash.pk, payment_voucher.pk],
            )
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertEqual(self._balance(self.revenue), Decimal('0.00'))
        correction = Voucher.objects.get(
            reference_type='LiabilityConversion', reference_id=cash_basis.pk)
        self.assertEqual(correction.lines.get(debit__gt=0).account_head, self.revenue)
        self.assertEqual(correction.lines.get(credit__gt=0).account_head, self.advances)

    def test_legacy_receivable_payments_and_refunds_are_converted(self):
        booking = self._booking()
        payment = self._payment(booking)
        payment_voucher = Voucher.objects.get(
            reference_type='Payment', reference_id=payment.pk)
        refund = self._refund(booking)
        refund_voucher = Voucher.objects.get(
            reference_type='Refund', reference_id=refund.pk)
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE finance_voucherline SET account_head_id = %s '
                'WHERE voucher_id = %s AND credit > 0',
                [self.receivable.pk, payment_voucher.pk],
            )
            cursor.execute(
                'UPDATE finance_voucherline SET account_head_id = %s '
                'WHERE voucher_id = %s AND debit > 0',
                [self.receivable.pk, refund_voucher.pk],
            )
        self.assertEqual(self._balance(self.receivable), Decimal('-80.00'))
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='LiabilityConversion').count(), 2)
        self.assertEqual(self._balance(self.advances), Decimal('80.00'))
        self.assertEqual(self._balance(self.receivable), Decimal('0.00'))
        self.assertEqual(self._balance(self.revenue), Decimal('0.00'))
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='LiabilityConversion').count(), 2)

    def test_legacy_cash_basis_pair_is_not_double_corrected(self):
        booking = self._booking()
        payment = self._payment(booking)
        payment_voucher = Voucher.objects.get(
            reference_type='Payment', reference_id=payment.pk)
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE finance_voucherline SET account_head_id = %s '
                'WHERE voucher_id = %s AND credit > 0',
                [self.receivable.pk, payment_voucher.pk],
            )
        cash_basis = Voucher.objects.create(
            voucher_type='JV', date=payment.payment_date,
            narration='Cash basis conversion for legacy payment',
            reference_type='CashBasisConversion', reference_id=payment_voucher.pk,
            created_by=self.user,
        )
        VoucherLine.objects.create(
            voucher=cash_basis, account_head=self.receivable,
            debit=Decimal('100'), credit=0)
        VoucherLine.objects.create(
            voucher=cash_basis, account_head=self.revenue,
            debit=0, credit=Decimal('100'))
        cash_basis.post(self.user)
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='LiabilityConversion').count(), 1)
        self.assertTrue(Voucher.objects.filter(
            reference_type='LiabilityConversion', reference_id=cash_basis.pk).exists())
        self.assertFalse(Voucher.objects.filter(
            reference_type='LiabilityConversion', reference_id=payment_voucher.pk).exists())
        self.assertEqual(self._balance(self.advances), Decimal('100.00'))
        self.assertEqual(self._balance(self.receivable), Decimal('0.00'))
        self.assertEqual(self._balance(self.revenue), Decimal('0.00'))
