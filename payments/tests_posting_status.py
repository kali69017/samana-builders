from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking
from customers.models import Customer
from finance.models import AccountHead, Voucher
from payments.models import Payment, Receipt
from properties.models import Plot, Project


class PaymentPostingBase:
    def setUp(self):
        self.user = User.objects.create_superuser(
            'posting', 'posting@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.advances = AccountHead.objects.get(system_role='customer_advances')
        self.customer = Customer.objects.create(
            first_name='Posting', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(
            name='Posting Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='POST-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.user,
        )

    def make_payment(self, status_value='pending', amount='100', method='cash'):
        return Payment.objects.create(
            booking=self.booking, received_into=self.cash if method == 'cash' else self.bank,
            amount=Decimal(amount), payment_date=date.today(),
            payment_method=method, payment_type='advance',
            status=status_value, created_by=self.user,
        )

    def payment_vouchers(self, payment):
        return Voucher.objects.filter(
            reference_type='Payment', reference_id=payment.pk)

    def reversal_vouchers(self, payment):
        return Voucher.objects.filter(
            reference_type='PaymentReversal', reference_id=payment.pk)


class PaymentPostingModelTests(PaymentPostingBase, TestCase):
    def test_pending_payment_posts_nothing(self):
        payment = self.make_payment(status_value='pending')
        self.assertEqual(self.payment_vouchers(payment).count(), 0)
        self.assertEqual(self.reversal_vouchers(payment).count(), 0)

    def test_created_as_verified_posts_once(self):
        payment = self.make_payment(status_value='verified')
        self.assertEqual(self.payment_vouchers(payment).count(), 1)
        payment.save()
        self.assertEqual(self.payment_vouchers(payment).count(), 1)

    def test_verify_transition_posts_once(self):
        payment = self.make_payment(status_value='pending')
        payment.status = 'verified'
        payment.verified_by = self.user
        payment.save()
        self.assertEqual(self.payment_vouchers(payment).count(), 1)
        payment.save()
        self.assertEqual(self.payment_vouchers(payment).count(), 1)

    def test_rejected_after_verified_posts_reversal(self):
        payment = self.make_payment(status_value='verified')
        payment.status = 'rejected'
        payment.save()
        self.assertEqual(self.reversal_vouchers(payment).count(), 1)

    def test_bounced_after_verified_posts_reversal(self):
        payment = self.make_payment(status_value='verified')
        payment.status = 'bounced'
        payment.save()
        self.assertEqual(self.reversal_vouchers(payment).count(), 1)

    def test_reversed_after_verified_posts_reversal(self):
        payment = self.make_payment(status_value='verified')
        payment.status = 'reversed'
        payment.save()
        self.assertEqual(self.reversal_vouchers(payment).count(), 1)

    def test_bounce_before_verify_posts_nothing(self):
        payment = self.make_payment(status_value='pending', method='cheque')
        payment.status = 'bounced'
        payment.save()
        self.assertEqual(self.payment_vouchers(payment).count(), 0)
        self.assertEqual(self.reversal_vouchers(payment).count(), 0)

    def test_post_delivery_reversal_debits_revenue(self):
        self.booking.delivery_date = date.today()
        self.booking.status = 'completed'
        self.booking.save()
        payment = self.make_payment(status_value='verified')
        self.assertEqual(
            Voucher.objects.get(
                reference_type='Payment', reference_id=payment.pk,
            ).lines.get(credit__gt=0).account_head,
            self.revenue,
        )
        payment.status = 'reversed'
        payment.save()
        reversal = self.reversal_vouchers(payment).get()
        self.assertEqual(reversal.lines.get(debit__gt=0).account_head, self.revenue)

    def test_posted_payment_amount_cannot_change(self):
        payment = self.make_payment(status_value='verified')
        payment.amount = Decimal('200')
        with self.assertRaises(ValidationError):
            payment.save()
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal('100'))

    def test_posted_payment_booking_cannot_change(self):
        payment = self.make_payment(status_value='verified')
        other_plot = Plot.objects.create(
            plot_number='POST-2', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), status='available',
        )
        other_booking = Booking.objects.create(
            customer=self.customer, plot=other_plot, total_amount=Decimal('1000'),
            status='confirmed', created_by=self.user,
        )
        payment.booking = other_booking
        with self.assertRaises(ValidationError):
            payment.save()

    def test_posted_payment_account_cannot_change(self):
        payment = self.make_payment(status_value='verified')
        payment.received_into = self.bank
        with self.assertRaises(ValidationError):
            payment.save()

    def test_queryset_update_blocks_posted_payment_fields(self):
        payment = self.make_payment(status_value='verified')
        with self.assertRaises(ValidationError):
            Payment.objects.filter(pk=payment.pk).update(amount=Decimal('200'))
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal('100'))


class PaymentPostingAPITests(PaymentPostingBase, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)

    def create_pending_api_payment(self, method='cash'):
        payload = {
            'booking': self.booking.pk,
            'received_into': self.cash.pk if method == 'cash' else self.bank.pk,
            'amount': '100',
            'payment_date': date.today().isoformat(),
            'payment_method': method,
            'payment_type': 'advance',
        }
        if method == 'cheque':
            payload['cheque_number'] = 'CHQ-1001'
            payload['bank_name'] = 'Test Bank'
        response = self.client.post(reverse('payment-list'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return Payment.objects.get(payment_id=response.data['payment_id'])

    def test_api_pending_create_posts_nothing(self):
        payment = self.create_pending_api_payment()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(self.payment_vouchers(payment).count(), 0)

    def test_api_approve_posts_once_and_double_approve_does_not_double_post(self):
        payment = self.create_pending_api_payment()
        response = self.client.post(
            reverse('payment-verify', args=[payment.pk]), {'action': 'verify'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.payment_vouchers(payment).count(), 1)
        self.assertTrue(Receipt.objects.filter(payment=payment).exists())
        response = self.client.post(
            reverse('payment-verify', args=[payment.pk]), {'action': 'verify'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.payment_vouchers(payment).count(), 1)

    def test_api_bounce_after_verify_posts_reversal(self):
        payment = self.create_pending_api_payment(method='cheque')
        self.client.post(
            reverse('payment-verify', args=[payment.pk]), {'action': 'verify'}, format='json')
        response = self.client.post(
            reverse('payment-mark-bounced', args=[payment.pk]),
            {'bounce_reason': 'insufficient funds'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.reversal_vouchers(payment).count(), 1)

    def test_api_bounce_before_verify_posts_nothing(self):
        payment = self.create_pending_api_payment(method='cheque')
        response = self.client.post(
            reverse('payment-mark-bounced', args=[payment.pk]),
            {'bounce_reason': 'insufficient funds'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.payment_vouchers(payment).count(), 0)
        self.assertEqual(self.reversal_vouchers(payment).count(), 0)

    def test_api_reject_pending_posts_nothing(self):
        payment = self.create_pending_api_payment()
        response = self.client.post(
            reverse('payment-verify', args=[payment.pk]), {'action': 'reject'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.payment_vouchers(payment).count(), 0)

    def test_api_update_blocks_posted_payment_amount(self):
        payment = self.create_pending_api_payment()
        self.client.post(
            reverse('payment-verify', args=[payment.pk]), {'action': 'verify'}, format='json')
        response = self.client.patch(
            reverse('payment-detail', args=[payment.pk]), {'amount': '200'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal('100'))
