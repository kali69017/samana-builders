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


class FixPaymentPostingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'fixpost', 'fixpost@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.advances = AccountHead.objects.get(system_role='customer_advances')
        self.customer = Customer.objects.create(
            first_name='Fix', last_name='Posting', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(
            name='Fix Posting Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='FIX-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.user,
        )

    def make_payment(self, status_value='pending', amount='100'):
        return Payment.objects.create(
            booking=self.booking, received_into=self.cash,
            amount=Decimal(amount), payment_date=date.today(),
            payment_method='cash', payment_type='advance',
            status=status_value, created_by=self.user,
        )

    def make_verified_payment_without_voucher(self, payment_id='PAY-90002'):
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

    def test_dry_run_lists_non_verified_payment_without_changing(self):
        payment = self.make_payment(status_value='pending')
        self.make_manual_payment_voucher(payment)
        out = StringIO()
        call_command('fix_payment_postings', '--dry-run', stdout=out)
        self.assertIn(payment.payment_id, out.getvalue())
        self.assertFalse(Voucher.objects.filter(
            reference_type='PaymentReversal', reference_id=payment.pk).exists())

    def test_command_posts_reversal_for_non_verified_payment(self):
        payment = self.make_payment(status_value='pending')
        self.make_manual_payment_voucher(payment)
        call_command('fix_payment_postings', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='PaymentReversal', reference_id=payment.pk).count(), 1)
        call_command('fix_payment_postings', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='PaymentReversal', reference_id=payment.pk).count(), 1)

    def test_dry_run_lists_verified_payment_missing_receipt(self):
        payment = self.make_verified_payment_without_voucher()
        out = StringIO()
        call_command('fix_payment_postings', '--dry-run', stdout=out)
        self.assertIn(payment.payment_id, out.getvalue())
        self.assertFalse(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).exists())

    def test_command_posts_missing_receipt_for_verified_payment(self):
        payment = self.make_verified_payment_without_voucher()
        call_command('fix_payment_postings', stdout=StringIO())
        self.assertEqual(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).count(), 1)
