"""Tests for the booking pricing/validation/cancel-reopen upgrades.

Covers (from the client batch):
- Booking total cannot under-sell the plot's total cost (price + charges) in
  both the form and the API serializer.
- Holding/advance deposit must meet the plot's required holding_deposit.
- A booking with 0 advance cannot be confirmed (web + API).
- Booking cancel sets status + releases plot; reopen restores to pending.
- Plot total_cost/total_charges properties sum charges correctly.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bookings.models import Booking
from bookings.forms import BookingForm
from core.models import UserProfile
from customers.models import Customer
from properties.models import Plot, Project, ProjectPhase


class BookingPricingValidationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('bkadmin', 'bk@x.com', 'x')
        UserProfile.objects.create(user=self.admin, role='super_admin')
        self.project = Project.objects.create(name='QA Proj', location='Karachi')
        self.phase = ProjectPhase.objects.create(project=self.project, name='P1', launch_date='2026-01-01')
        self.plot = Plot.objects.create(
            plot_number='QA-01', project=self.project, phase=self.phase,
            size_marla='5', price='100000.00', holding_deposit='10000.00',
            development_charge='5000.00', lease_charge='2000.00', other_charges='1000.00',
            status='available',
        )
        self.customer = Customer.objects.create(
            first_name='QA', last_name='Buyer', phone='+92-300-0000000',
            cnic='4210100000000', email='qabuyer@example.com',
        )
        self.client.force_login(self.admin)

    def test_plot_total_cost_includes_all_charges(self):
        # base 100,000 + dev 5,000 + lease 2,000 + other 1,000 = 108,000
        self.assertEqual(self.plot.total_charges, Decimal('8000.00'))
        self.assertEqual(self.plot.total_cost, Decimal('108000.00'))

    def test_form_rejects_total_below_plot_total_cost(self):
        form = BookingForm(data={
            'customer': self.customer.pk, 'plot': self.plot.pk,
            'total_amount': '107000.00', 'advance_paid': '10000.00',
            'source': 'walk_in',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('below the plot total cost', str(form.errors))

    def test_form_rejects_advance_below_holding_deposit(self):
        form = BookingForm(data={
            'customer': self.customer.pk, 'plot': self.plot.pk,
            'total_amount': '108000.00', 'advance_paid': '5000.00',
            'source': 'walk_in',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('holding deposit', str(form.errors))

    def test_form_accepts_valid_booking_at_plot_total_cost(self):
        form = BookingForm(data={
            'customer': self.customer.pk, 'plot': self.plot.pk,
            'total_amount': '108000.00', 'advance_paid': '10000.00',
            'source': 'walk_in',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_api_rejects_total_below_plot_total_cost(self):
        from bookings.serializers import BookingCreateSerializer
        data = {
            'customer': self.customer.pk, 'plot': self.plot.pk,
            'total_amount': '107000.00', 'advance_paid': '10000.00',
        }
        s = BookingCreateSerializer(data=data)
        self.assertFalse(s.is_valid())
        self.assertIn('below the plot total cost', str(s.errors))

    def test_confirm_blocked_without_advance(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount='108000.00',
            advance_paid='0', status='pending',
        )
        resp = self.client.post(reverse('booking_confirm', args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'pending')
        self.assertEqual(resp.status_code, 302)


class BookingCancelReopenTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('bkadm2', 'bk2@x.com', 'x')
        UserProfile.objects.create(user=self.admin, role='super_admin')
        self.project = Project.objects.create(name='QA Proj2', location='Lahore')
        self.phase = ProjectPhase.objects.create(project=self.project, name='P1', launch_date='2026-01-01')
        self.plot = Plot.objects.create(
            plot_number='QA-02', project=self.project, phase=self.phase,
            size_marla='5', price='50000.00', holding_deposit='5000.00', status='booked',
        )
        self.customer = Customer.objects.create(
            first_name='QA', last_name='Cancel', phone='+92-300-1111111',
            cnic='4210100000001', email='qacancel@example.com',
        )
        self.client.force_login(self.admin)

    def test_cancel_releases_plot_and_reopen_reserves(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount='50000.00',
            advance_paid='0', status='pending',
        )
        # cancel
        resp = self.client.post(reverse('booking_cancel', args=[booking.pk]), {
            'reason': 'customer_request', 'notes': 'qa cancel'})
        booking.refresh_from_db(); self.plot.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertIsNotNone(booking.cancelled_at)
        self.assertIn('qa cancel', booking.notes)
        self.assertEqual(self.plot.status, 'available')
        # reopen
        resp = self.client.post(reverse('booking_reopen', args=[booking.pk]), {})
        booking.refresh_from_db(); self.plot.refresh_from_db()
        self.assertEqual(booking.status, 'pending')
        self.assertEqual(self.plot.status, 'reserved')

    def test_cancel_blocked_with_verified_payments(self):
        from payments.models import Payment
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount='50000.00',
            advance_paid='5000.00', status='confirmed',
        )
        Payment.objects.create(
            booking=booking, amount='5000.00', payment_date='2026-01-10',
            payment_method='cash', payment_type='down_payment', status='verified',
        )
        resp = self.client.post(reverse('booking_cancel', args=[booking.pk]), {
            'reason': 'customer_request'})
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')  # not cancelled