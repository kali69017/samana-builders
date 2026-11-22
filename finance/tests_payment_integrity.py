from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, Voucher, VoucherLine
from payments.models import Payment
from properties.models import Plot, Project


class PaymentIntegrityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'integrity', 'integrity@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.advances = AccountHead.objects.get(system_role='customer_advances')
        self.customer = Customer.objects.create(
            first_name='Integrity', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(
            name='Integrity Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='INT-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.user,
        )

    def make_payment(self, status_value='verified', amount='100'):
        return Payment.objects.create(
            booking=self.booking, received_into=self.cash,
            amount=Decimal(amount), payment_date=date.today(),
            payment_method='cash', payment_type='advance',
            status=status_value, created_by=self.user,
        )

    def make_verified_payment_without_voucher(self, payment_id='PAY-90001'):
        Payment.objects.bulk_create([
            Payment(
                payment_id=payment_id, booking=self.booking,
                received_into=self.cash, amount=Decimal('100'),
                payment_date=date.today(), payment_method='cash',
                payment_type='advance', status='verified', created_by=self.user,
            ),
        ])
        return Payment.objects.get(payment_id=payment_id)

    def make_manual_payment_voucher(self, payment):
        voucher = Voucher.objects.create(
            voucher_type='CR', date=date.today(),
            narration='Legacy payment voucher',
            reference_type='Payment', reference_id=payment.pk,
            created_by=self.user,
        )
        VoucherLine.objects.create(
            voucher=voucher, account_head=self.cash,
            debit=payment.amount, credit=Decimal('0'))
        VoucherLine.objects.create(
            voucher=voucher, account_head=self.advances,
            debit=Decimal('0'), credit=payment.amount)
        voucher.post(self.user)
        return voucher

    def test_integrity_flags_pending_payment_with_voucher_without_reversal(self):
        payment = self.make_payment(status_value='pending')
        self.make_manual_payment_voucher(payment)
        with self.assertRaises(Exception):
            call_command('finance_integrity_check', stdout=StringIO())

    def test_integrity_flags_verified_payment_without_voucher(self):
        self.make_verified_payment_without_voucher()
        with self.assertRaises(Exception):
            call_command('finance_integrity_check', stdout=StringIO())

    def test_integrity_flags_verified_payment_with_reversal(self):
        payment = self.make_payment(status_value='verified')
        payment.status = 'reversed'
        payment.save()
        Payment.objects.filter(pk=payment.pk).update(status='verified')
        with self.assertRaises(Exception):
            call_command('finance_integrity_check', stdout=StringIO())

    def test_integrity_passes_for_reversed_payment_with_matching_reversal(self):
        payment = self.make_payment(status_value='verified')
        payment.status = 'reversed'
        payment.save()
        call_command('finance_integrity_check', stdout=StringIO())

    def test_integrity_flags_source_advances_mismatch(self):
        self.make_payment(status_value='verified')
        manual = Voucher.objects.create(
            voucher_type='JV', date=date.today(),
            narration='Bad manual advance',
            created_by=self.user,
        )
        VoucherLine.objects.create(
            voucher=manual, account_head=self.cash,
            debit=Decimal('5'), credit=Decimal('0'))
        VoucherLine.objects.create(
            voucher=manual, account_head=self.advances,
            debit=Decimal('0'), credit=Decimal('5'))
        manual.post(self.user)
        with self.assertRaises(Exception):
            call_command('finance_integrity_check', stdout=StringIO())
