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


class LegacyConversionSkipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'legacy', 'legacy@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.receivable = AccountHead.objects.get(system_role='receivable')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.advances = AccountHead.objects.get(system_role='customer_advances')
        self.customer = Customer.objects.create(
            first_name='Legacy', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(
            name='Legacy Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='LEG-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.user,
        )

    def make_pending_payment(self):
        return Payment.objects.create(
            booking=self.booking, received_into=self.cash,
            amount=Decimal('100'), payment_date=date.today(),
            payment_method='cash', payment_type='advance',
            status='pending', created_by=self.user,
        )

    def make_legacy_payment_voucher(self, payment, credit_head):
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
            voucher=voucher, account_head=credit_head,
            debit=Decimal('0'), credit=payment.amount)
        voucher.post(self.user)
        return voucher

    def test_customer_liability_conversion_skips_unverified_payment(self):
        payment = self.make_pending_payment()
        self.make_legacy_payment_voucher(payment, self.revenue)
        out = StringIO()
        call_command('convert_to_customer_liability', '--dry-run', stdout=out)
        self.assertIn('Skipped 1 unverified payment(s)', out.getvalue())
        call_command('convert_to_customer_liability', stdout=StringIO())
        self.assertFalse(Voucher.objects.filter(
            reference_type='LiabilityConversion').exists())

    def test_cash_basis_conversion_skips_unverified_payment(self):
        payment = self.make_pending_payment()
        self.make_legacy_payment_voucher(payment, self.receivable)
        out = StringIO()
        call_command('convert_to_cash_basis', '--dry-run', stdout=out)
        self.assertIn('Skipped 1 unverified payment(s)', out.getvalue())
        call_command('convert_to_cash_basis', stdout=StringIO())
        self.assertFalse(Voucher.objects.filter(
            reference_type='CashBasisConversion').exists())
