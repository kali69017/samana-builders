"""Backfill command: link mature customers (pre-existing confirmed bookings) to
the shared AR control head (spec §3.12/§3.18)."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from properties.models import Plot, Project

from .models import AccountHead


class BackfillCustomerAccountHeadsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('bf', 'bf@example.com', 'pass12345')
        self.project = Project.objects.create(name='P1', location='Lahore')

    def _customer(self, n):
        return Customer.objects.create(
            first_name=f'C{n}', last_name='X', phone=f'+92-300-000000{n}',
            cnic=f'35202-000000{n}-1', created_by=self.user,
        )

    def _legacy_booking(self, customer, status):
        """Create a booking and force its status via queryset.update() so the
        save()-time trigger does not run — simulating pre-existing data."""
        plot = Plot.objects.create(
            plot_number=f'P-{customer.pk}-{status}', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('1000000'),
        )
        booking = Booking.objects.create(
            customer=customer, plot=plot, total_amount=Decimal('1000000'),
            created_by=self.user,
        )
        if status != 'pending':
            Booking.objects.filter(pk=booking.pk).update(status=status)
        return booking

    def test_backfill_links_only_confirmed_customers(self):
        confirmed = self._customer(1)
        self._legacy_booking(confirmed, 'confirmed')
        pending = self._customer(2)
        self._legacy_booking(pending, 'pending')
        cancelled = self._customer(3)
        self._legacy_booking(cancelled, 'cancelled')

        call_command('backfill_customer_account_heads')

        confirmed.refresh_from_db()
        pending.refresh_from_db()
        cancelled.refresh_from_db()
        self.assertIsNotNone(confirmed.account_head)
        self.assertEqual(confirmed.account_head.code, '1100')
        self.assertIsNone(pending.account_head)
        self.assertIsNone(cancelled.account_head)
        self.assertEqual(AccountHead.objects.filter(code='1100').count(), 1)

    def test_backfill_is_idempotent(self):
        customer = self._customer(1)
        self._legacy_booking(customer, 'confirmed')
        call_command('backfill_customer_account_heads')
        customer.refresh_from_db()
        head_id = customer.account_head_id
        call_command('backfill_customer_account_heads')
        customer.refresh_from_db()
        self.assertEqual(customer.account_head_id, head_id)
        self.assertEqual(AccountHead.objects.filter(code='1100').count(), 1)

    def test_dry_run_reports_without_writing(self):
        from io import StringIO
        customer = self._customer(1)
        self._legacy_booking(customer, 'confirmed')
        out = StringIO()
        call_command('backfill_customer_account_heads', '--dry-run', stdout=out)
        customer.refresh_from_db()
        self.assertIsNone(customer.account_head)
        self.assertFalse(AccountHead.objects.filter(code='1100').exists())
        self.assertIn('would link', out.getvalue().lower())
        self.assertIn('1 customer', out.getvalue())