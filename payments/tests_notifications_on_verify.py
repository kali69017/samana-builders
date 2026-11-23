from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, Voucher
from notifications.models import NotificationLog
from notifications.services import NotificationService
from payments.models import Payment, Receipt
from properties.models import Plot, Project


class NotificationOnVerifyBase:
    def setUp(self):
        self.user = User.objects.create_superuser(
            'notify', 'notify@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.customer = Customer.objects.create(
            first_name='Notify', last_name='Test', phone='03001234567',
            email='notify.customer@example.com', cnic='12345-1234567-1',
            created_by=self.user,
        )
        self.project = Project.objects.create(
            name='Notify Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='NOT-1', project=self.project, size_marla=Decimal('5'),
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

    def counts(self, payment):
        return {
            (row['notification_type'], row['channel']): row['count']
            for row in NotificationLog.objects.filter(
                related_payment_id=payment.payment_id,
            ).values('notification_type', 'channel').annotate(
                count=__import__('django.db.models', fromlist=['Count']).Count('id'))
        }


class NotificationOnVerifyModelTests(NotificationOnVerifyBase, TestCase):
    def test_pending_payment_queues_nothing(self):
        payment = self.make_payment(status_value='pending')
        self.assertEqual(self.counts(payment), {})

    def test_created_as_verified_queues_once(self):
        payment = self.make_payment(status_value='verified')
        self.assertEqual(self.counts(payment), {
            ('payment_confirmation', 'email'): 1,
            ('payment_confirmation', 'sms'): 1,
            ('payment_confirmation', 'whatsapp'): 1,
            ('receipt_notification', 'email'): 1,
            ('receipt_notification', 'whatsapp'): 1,
        })
        self.assertEqual(Receipt.objects.filter(payment=payment).count(), 1)

    def test_reject_bounce_and_reverse_queue_nothing(self):
        for target in ('rejected', 'bounced', 'reversed'):
            payment = self.make_payment(status_value='pending')
            payment.status = target
            payment.save()
            self.assertEqual(self.counts(payment), {})

    def test_verified_then_bounce_does_not_add_more_notifications(self):
        payment = self.make_payment(status_value='verified')
        before = self.counts(payment)
        payment.status = 'bounced'
        payment.save()
        self.assertEqual(self.counts(payment), before)

    def test_do_not_contact_is_logged_as_skipped(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        payment = self.make_payment(status_value='verified')
        logs = NotificationLog.objects.filter(related_payment_id=payment.payment_id)
        self.assertEqual(logs.count(), 5)
        self.assertFalse(logs.exclude(status='skipped').exists())

    def test_duplicate_queue_is_idempotent(self):
        payment = self.make_payment(status_value='pending')
        for _ in range(2):
            NotificationService.queue_notification(
                recipient_name=self.customer.full_name,
                recipient_contact=self.customer.email,
                channel='email',
                notification_type='payment_confirmation',
                subject='Duplicate test',
                message='Duplicate test',
                customer_id=self.customer.customer_id,
                booking_id=self.booking.booking_id,
                related_payment_id=payment.payment_id,
            )
        self.assertEqual(NotificationLog.objects.filter(
            notification_type='payment_confirmation',
            related_payment_id=payment.payment_id,
            channel='email',
        ).count(), 1)

    def test_failed_queue_rolls_back_payment_voucher_and_receipt(self):
        payment = self.make_payment(status_value='pending')
        with patch.object(
                NotificationService, 'queue_notification',
                side_effect=RuntimeError('queue failed')):
            with self.assertRaises(RuntimeError):
                payment.status = 'verified'
                payment.save()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertFalse(Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk).exists())
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())


class NotificationOnVerifyAPITests(NotificationOnVerifyBase, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)

    def create_api_payment(self):
        response = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk,
            'received_into': self.cash.pk,
            'amount': '100',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'advance',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return Payment.objects.get(payment_id=response.data['payment_id'])

    def test_api_pending_create_queues_nothing(self):
        payment = self.create_api_payment()
        self.assertEqual(self.counts(payment), {})

    def test_api_verify_queues_one_set_and_double_verify_does_not_duplicate(self):
        payment = self.create_api_payment()
        response = self.client.post(
            reverse('payment-verify', args=[payment.pk]),
            {'action': 'verify'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.counts(payment), {
            ('payment_confirmation', 'email'): 1,
            ('payment_confirmation', 'sms'): 1,
            ('payment_confirmation', 'whatsapp'): 1,
            ('receipt_notification', 'email'): 1,
            ('receipt_notification', 'whatsapp'): 1,
        })
        response = self.client.post(
            reverse('payment-verify', args=[payment.pk]),
            {'action': 'verify'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(sum(self.counts(payment).values()), 5)


class NotificationOnVerifyWebTests(NotificationOnVerifyBase, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(username='notify', password='pass123456')

    def test_web_create_is_pending_then_verify_queues_one_set(self):
        response = self.client.post(reverse('payment_create'), {
            'booking': self.booking.pk,
            'received_into': self.cash.pk,
            'amount': '100',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'advance',
        })
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.status, 'pending')
        self.assertFalse(Receipt.objects.filter(payment=payment).exists())
        self.assertEqual(self.counts(payment), {})
        response = self.client.post(reverse('payment_verify', args=[payment.pk]))
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'verified')
        self.assertEqual(Receipt.objects.filter(payment=payment).count(), 1)
        self.assertEqual(sum(self.counts(payment).values()), 5)
