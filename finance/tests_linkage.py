"""Customer → AccountHead linkage trigger tests (spec §3.12, §3.18).

A customer becomes "mature" (linked to the shared 1100 Accounts Receivable
control head) on the confirmed-booking transition — and not before.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from properties.models import Plot, Project

from .models import AccountHead


class CustomerLinkageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('link', 'l@example.com', 'pass12345')
        self.project = Project.objects.create(name='P1', location='Lahore')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan', phone='+92-300-8888888',
            cnic='35202-8888888-1', created_by=self.user,
        )
        self.plot = Plot.objects.create(
            plot_number='A-1', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user,
        )

    def test_pending_booking_does_not_link(self):
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.account_head)
        self.assertFalse(AccountHead.objects.filter(code='1100').exists())

    def test_confirmed_transition_links_to_control_head(self):
        self.booking.status = 'confirmed'
        self.booking.save()
        self.customer.refresh_from_db()
        self.assertIsNotNone(self.customer.account_head)
        self.assertEqual(self.customer.account_head.code, '1100')
        self.assertEqual(self.customer.account_head.name, 'Accounts Receivable')

    def test_cancelled_booking_does_not_link(self):
        self.booking.status = 'cancelled'
        self.booking.save()
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.account_head)

    def test_link_is_shared_control_head_not_per_customer(self):
        second = Customer.objects.create(
            first_name='Bilal', last_name='Khan', phone='+92-300-7777777',
            cnic='35202-7777777-1', created_by=self.user,
        )
        plot2 = Plot.objects.create(
            plot_number='A-2', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        booking2 = Booking.objects.create(
            customer=second, plot=plot2, total_amount=Decimal('5000000'),
            created_by=self.user,
        )
        for booking in (self.booking, booking2):
            booking.status = 'confirmed'
            booking.save()
        self.customer.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.customer.account_head_id, second.account_head_id)
        self.assertEqual(AccountHead.objects.filter(code='1100').count(), 1)

    def test_resave_does_not_duplicate_or_change_head(self):
        self.booking.status = 'confirmed'
        self.booking.save()
        self.customer.refresh_from_db()
        head_id = self.customer.account_head_id
        self.booking.save()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.account_head_id, head_id)