from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment, Refund
from properties.models import Plot, Project
from finance.models import AccountHead


class BookingPaymentSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('psum', 'psum@example.com', 'pass123456')
        self.customer = Customer.objects.create(
            first_name='Psum', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(name='Psum', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('5000000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('5000000'),
            advance_paid=Decimal('1000'), status='confirmed', created_by=self.user,
        )
        self.cash = AccountHead.objects.get(system_role='cash_default')
        Payment.objects.create(
            booking=self.booking, received_into=self.cash, amount=Decimal('1000'),
            payment_date=date.today(), payment_method='cash', status='verified',
            created_by=self.user,
        )
        Refund.objects.create(
            booking=self.booking, paid_from=self.cash, amount=Decimal('200'),
            reason='overpayment', refund_method='cash', status='processed',
            processed_by=self.user,
        )

    def test_payment_summary_has_refundable_and_correct_route(self):
        self.assertEqual(
            reverse('booking-payment-summary', args=[self.booking.pk]),
            f'/api/bookings/{self.booking.pk}/payment_summary/',
        )
        api = APIClient()
        api.force_authenticate(self.user)
        response = api.get(f'/api/bookings/{self.booking.pk}/payment_summary/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_paid'], 1000.0)
        self.assertEqual(response.data['outstanding'], 4999000.0)
        self.assertEqual(response.data['refundable'], 800.0)

    def test_hyphenated_summary_url_is_not_the_route(self):
        api = APIClient()
        api.force_authenticate(self.user)
        response = api.get(f'/api/bookings/{self.booking.pk}/payment-summary/')
        self.assertEqual(response.status_code, 404)


class PaymentFormSummaryTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('pform', 'pform@example.com', 'pass123456')
        self.client.login(username='pform', password='pass123456')

    def test_payment_form_uses_working_summary_url_and_error_region(self):
        response = self.client.get('/payments/create/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('/payment_summary/', html)
        self.assertNotIn('/payment-summary/', html)
        self.assertIn('id="paymentSummaryError"', html)
        self.assertIn('id="summaryRefundable"', html)
