from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from bookings.models import Booking
from bookings.serializers import BookingCreateSerializer
from customers.models import Customer
from finance.models import AccountHead
from payments.models import Payment, Refund
from payments.serializers import PaymentCreateSerializer, RefundSerializer
from properties.models import Plot, Project


class RefundIdempotencyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('idem', 'idem@example.com', 'pass123456')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            first_name='Idem', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(name='Idem Project', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='ID-1', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.plot2 = Plot.objects.create(
            plot_number='ID-2', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.plot3 = Plot.objects.create(
            plot_number='ID-3', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('5000000'),
            advance_paid=Decimal('1000000'), created_by=self.user,
        )
        Payment.objects.create(
            booking=self.booking, amount=Decimal('1000000'), payment_date=date.today(),
            payment_method='cash', payment_type='advance', status='verified',
            created_by=self.user,
        )
        self.account = AccountHead.objects.filter(
            is_leaf=True, is_active=True, account_kind='cash').first()

    def test_double_post_same_token_creates_one_refund(self):
        self.assertIsNotNone(self.account)
        data = {
            'booking': self.booking.pk,
            'paid_from': self.account.pk,
            'amount': '1000.00',
            'reason': 'overpayment',
            'refund_method': 'cash',
            'refund_date': date.today().isoformat(),
            'idempotency_key': 'refund-token-1',
        }
        first = self.client.post('/refunds/create/', data)
        second = self.client.post('/refunds/create/', data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Refund.objects.filter(idempotency_key='refund-token-1').count(), 1)

    def test_double_web_post_same_token_creates_one_payment_and_one_queue_set(self):
        self.assertIsNotNone(self.account)
        from notifications.models import NotificationLog
        data = {
            'booking': self.booking.pk,
            'received_into': self.account.pk,
            'amount': '1000.00',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'advance',
            'idempotency_key': 'payment-web-token-1',
        }
        first = self.client.post('/payments/create/', data)
        queued_after_first = NotificationLog.objects.count()
        second = self.client.post('/payments/create/', data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Payment.objects.filter(idempotency_key='payment-web-token-1').count(), 1)
        self.assertGreater(queued_after_first, 0)
        self.assertEqual(NotificationLog.objects.count(), queued_after_first)

    def test_double_api_post_same_token_creates_one_payment(self):
        self.assertIsNotNone(self.account)
        api = APIClient()
        api.force_authenticate(self.user)
        data = {
            'booking': self.booking.pk,
            'received_into': self.account.pk,
            'amount': '1000.00',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'advance',
            'idempotency_key': 'payment-token-1',
        }
        first = api.post('/api/payments/', data, format='json')
        second = api.post('/api/payments/', data, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 400, second.content)
        self.assertEqual(Payment.objects.filter(idempotency_key='payment-token-1').count(), 1)

    def test_web_payment_race_hits_constraint_and_redirects_existing(self):
        self.assertIsNotNone(self.account)
        data = {
            'booking': self.booking.pk,
            'received_into': self.account.pk,
            'amount': '1500.00',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'advance',
            'idempotency_key': 'payment-web-race',
        }
        first = self.client.post('/payments/create/', data)
        existing = Payment.objects.get(idempotency_key='payment-web-race')
        second_data = dict(data, amount='1600.00')
        with patch('core.views._find_existing_payment', side_effect=[None, existing]):
            second = self.client.post('/payments/create/', second_data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(second.url, f'/payments/{existing.pk}/')
        self.assertEqual(Payment.objects.filter(idempotency_key='payment-web-race').count(), 1)

    def test_web_refund_race_hits_constraint_and_redirects(self):
        self.assertIsNotNone(self.account)
        data = {
            'booking': self.booking.pk,
            'paid_from': self.account.pk,
            'amount': '1000.00',
            'reason': 'overpayment',
            'refund_method': 'cash',
            'refund_date': date.today().isoformat(),
            'idempotency_key': 'refund-race',
        }
        first = self.client.post('/refunds/create/', data)
        existing = Refund.objects.get(idempotency_key='refund-race')
        second_data = dict(data, amount='1001.00')
        with patch('payments.views_workflow._find_existing_refund',
                   side_effect=[None, existing]):
            second = self.client.post('/refunds/create/', second_data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Refund.objects.filter(idempotency_key='refund-race').count(), 1)

    def test_web_booking_race_hits_constraint_and_redirects_existing(self):
        data = {
            'customer': self.customer.pk,
            'plot': self.plot2.pk,
            'total_amount': '5000000.00',
            'advance_paid': '0',
            'source': 'walk_in',
            'notes': '',
            'idempotency_key': 'booking-web-race',
        }
        first = self.client.post('/bookings/create/', data)
        existing = Booking.objects.get(idempotency_key='booking-web-race')
        second_data = dict(data, plot=self.plot3.pk)
        with patch('core.views._find_existing_booking', side_effect=[None, existing]):
            second = self.client.post('/bookings/create/', second_data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(second.url, f'/bookings/{existing.pk}/')
        self.assertEqual(Booking.objects.filter(idempotency_key='booking-web-race').count(), 1)

    def test_api_booking_race_hits_constraint_and_returns_existing(self):
        api = APIClient()
        api.force_authenticate(self.user)
        data = {
            'customer': self.customer.pk,
            'plot': self.plot2.pk,
            'total_amount': '5000000.00',
            'advance_paid': '0',
            'source': 'walk_in',
            'idempotency_key': 'booking-api-race',
        }
        second_data = dict(data, plot=self.plot3.pk)
        with patch.object(BookingCreateSerializer, 'validate_idempotency_key',
                          return_value='booking-api-race'):
            first = api.post('/api/bookings/', data, format='json')
            second = api.post('/api/bookings/', second_data, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Booking.objects.filter(idempotency_key='booking-api-race').count(), 1)

    def test_api_payment_race_hits_constraint_and_returns_existing(self):
        self.assertIsNotNone(self.account)
        api = APIClient()
        api.force_authenticate(self.user)
        data = {
            'booking': self.booking.pk,
            'received_into': self.account.pk,
            'amount': '2500.00',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'advance',
            'idempotency_key': 'payment-api-race',
        }
        with patch.object(PaymentCreateSerializer, 'validate_idempotency_key',
                          return_value='payment-api-race'):
            first = api.post('/api/payments/', data, format='json')
            second = api.post('/api/payments/', data, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Payment.objects.filter(idempotency_key='payment-api-race').count(), 1)

    def test_api_refund_race_hits_constraint_and_returns_existing(self):
        self.assertIsNotNone(self.account)
        api = APIClient()
        api.force_authenticate(self.user)
        data = {
            'booking': self.booking.pk,
            'paid_from': self.account.pk,
            'amount': '1000.00',
            'reason': 'overpayment',
            'refund_method': 'cash',
            'refund_date': date.today().isoformat(),
            'idempotency_key': 'refund-api-race',
        }
        with patch.object(RefundSerializer, 'validate_idempotency_key',
                          return_value='refund-api-race'):
            first = api.post('/api/refunds/', data, format='json')
            second = api.post('/api/refunds/', data, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Refund.objects.filter(idempotency_key='refund-api-race').count(), 1)


class RefundBackAndDuplicateGuardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('refundguard', 'rg@example.com', 'pass123456')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            first_name='Guard', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(name='Guard P', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='G-1', project=self.project,
            size_marla=Decimal('5'), price=Decimal('5000000'), status='available',
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

    def data(self, key):
        return {
            'booking': self.booking.pk, 'paid_from': self.cash.pk,
            'amount': '10.00', 'reason': 'overpayment', 'refund_method': 'cash',
            'refund_date': date.today().isoformat(), 'idempotency_key': key,
        }

    def test_same_key_creates_one_refund(self):
        first = self.client.post('/refunds/create/', self.data('refund-same-key'))
        second = self.client.post('/refunds/create/', self.data('refund-same-key'))
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Refund.objects.filter(idempotency_key='refund-same-key').count(), 1)

    def test_recent_same_booking_amount_reason_is_blocked_with_new_key(self):
        first = self.client.post('/refunds/create/', self.data('refund-back-1'))
        second = self.client.post('/refunds/create/', self.data('refund-back-2'))
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, 'similar pending refund was created in the last 60 seconds')
        self.assertEqual(Refund.objects.filter(booking=self.booking, amount=Decimal('10.00')).count(), 1)

    def test_create_pages_are_no_store(self):
        for url in ('/refunds/create/', '/payments/create/', '/bookings/create/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn('no-store', response.headers.get('Cache-Control', ''))
