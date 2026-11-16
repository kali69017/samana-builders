from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, ProjectCost, Voucher
from properties.models import Plot, Project


class FinanceLinkBackfillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('bf', 'bf@example.com', 'pass123456')
        self.customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        self.project = Project.objects.create(name='P', location='L', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='pending',
        )
        Booking.objects.filter(pk=self.booking.pk).update(status='confirmed')
        self.booking.refresh_from_db()
        self.cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('200'), cost_date=date.today(),
            payment_method='cash', status='paid',
        )

    def test_dry_run_writes_nothing(self):
        out = StringIO()
        call_command('backfill_finance_links', '--dry-run', stdout=out)
        self.booking.refresh_from_db()
        self.cost.refresh_from_db()
        self.assertIsNone(self.booking.receivable_account)
        self.assertIsNone(self.cost.expense_account)
        self.assertFalse(Voucher.objects.filter(reference_type='Booking').exists())
        self.assertIn('Receivable balance before', out.getvalue())

    def test_backfill_links_but_does_not_post_booking_vouchers(self):
        out = StringIO()
        call_command('backfill_finance_links', stdout=out)
        self.booking.refresh_from_db()
        self.cost.refresh_from_db()
        self.assertEqual(self.booking.receivable_account.system_role, 'receivable')
        self.assertEqual(self.booking.revenue_account.system_role, 'revenue')
        self.assertEqual(self.cost.expense_account.system_role, 'project_costs')
        self.assertEqual(self.cost.paid_from.system_role, 'cash_default')
        self.assertFalse(Voucher.objects.filter(
            reference_type='Booking', reference_id=self.booking.pk).exists())

        voucher_count = Voucher.objects.count()
        call_command('backfill_finance_links', stdout=StringIO())
        self.assertEqual(Voucher.objects.count(), voucher_count)
        self.assertEqual(Voucher.objects.filter(
            reference_type='Booking', reference_id=self.booking.pk).count(), 0)
