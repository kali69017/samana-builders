"""Tests for the SendPK SMS integration and notification messages."""
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from bookings.models import Booking, InstallmentPlan
from customers.models import Customer
from payments.models import Payment
from properties.models import Plot, Project
from .models import NotificationLog
from .services import SMSService, NotificationService


class SMSNormalizationTest(TestCase):
    def test_normalize_phone(self):
        self.assertEqual(SMSService.normalize_phone('+92-300-1234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone('0300-1234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone('923001234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone('3001234567'), '923001234567')
        self.assertEqual(SMSService.normalize_phone(''), '')


class SMSServiceSendTest(TestCase):
    @override_settings(SENDPK_ENABLED=False)
    def test_send_disabled_does_not_hit_network(self):
        with patch('notifications.services.requests.post') as mock_post:
            ok, detail = SMSService.send('+92-300-1234567', 'Hello')
        self.assertTrue(ok)
        mock_post.assert_not_called()

    @override_settings(SENDPK_ENABLED=True, SENDPK_API_KEY='test-key', SENDPK_SENDER_ID='SAMANA')
    def test_send_success(self):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {
            'success': 'true',
            'results': [{'status': 'OK', 'messageid': '6502124', 'gsm': '923001234567'}],
        }
        with patch('notifications.services.requests.post', return_value=mock_resp) as mock_post:
            ok, detail = SMSService.send('+92-300-1234567', 'Hello')
        self.assertTrue(ok)
        self.assertIn('6502124', detail)
        payload = mock_post.call_args.kwargs['data']
        self.assertEqual(payload['mobile'], '923001234567')
        self.assertEqual(payload['sender'], 'SAMANA')

    @override_settings(SENDPK_ENABLED=True, SENDPK_API_KEY='test-key', SENDPK_SENDER_ID='SAMANA')
    def test_send_failure(self):
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json.return_value = {'success': 'false', 'results': [{'status': '8', 'error': 'Low Credit'}]}
        with patch('notifications.services.requests.post', return_value=mock_resp):
            ok, detail = SMSService.send('+92-300-1234567', 'Hello')
        self.assertFalse(ok)

    def test_send_invalid_phone(self):
        ok, detail = SMSService.send('abc', 'Hello')
        self.assertFalse(ok)
        self.assertIn('Invalid', detail)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotificationMessageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            email='ahmed@example.com', created_by=self.user,
        )
        self.project = Project.objects.create(name='Test', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), advance_paid=Decimal('1000000'),
            status='active', created_by=self.user,
        )
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=4,
            installment_amount=Decimal('1000000'), down_payment_amount=Decimal('1000000'),
            start_date=date.today(), frequency='monthly',
        )
        self.plan.auto_generate()

    def test_payment_confirmation_sms_contains_remaining_and_next_installment(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('120000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='verified', created_by=self.user,
        )
        with patch('notifications.services.SMSService.send', return_value=(True, 'OK ID:123')):
            NotificationService.send_payment_confirmation(payment)

        sms_log = NotificationLog.objects.filter(
            channel='sms', notification_type='payment_confirmation'
        ).first()
        self.assertIsNotNone(sms_log)
        # remaining balance = 5,000,000 - 1,000,000
        self.assertIn('Remaining', sms_log.message)
        self.assertIn('4,000,000', sms_log.message)
        # next unpaid installment is #1
        self.assertIn('#1', sms_log.message)

    def test_installment_reminder_sends_sms(self):
        installment = self.plan.installments.filter(installment_number=1).first()
        with patch('notifications.services.SMSService.send', return_value=(True, 'OK ID:456')):
            NotificationService.send_installment_reminder(installment)

        sms_log = NotificationLog.objects.filter(
            channel='sms', notification_type='installment_reminder'
        ).first()
        self.assertIsNotNone(sms_log)
        self.assertIn('installment #1', sms_log.message)

    def test_sms_log_stores_concise_message_not_full_email(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('120000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='verified', created_by=self.user,
        )
        with patch('notifications.services.SMSService.send', return_value=(True, 'OK ID:123')):
            NotificationService.send_payment_confirmation(payment)

        sms_log = NotificationLog.objects.get(channel='sms', notification_type='payment_confirmation')
        email_log = NotificationLog.objects.get(channel='email', notification_type='payment_confirmation')
        # SMS is concise; email is verbose
        self.assertLess(len(sms_log.message), len(email_log.message))
        self.assertNotIn('Payment ID', sms_log.message)
