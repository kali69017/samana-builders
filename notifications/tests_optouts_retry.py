from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from customers.models import Customer
from notifications.models import NotificationLog, NotificationPreference
from notifications.services import NotificationService


class NotificationPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('pref', 'pref@example.com', 'pass123456')
        self.customer = Customer.objects.create(
            first_name='Pref', last_name='Customer', phone='03001234567',
            email='pref@example.com', cnic='12345-1234567-1', user=self.user,
        )
        NotificationPreference.objects.create(
            user=self.user, email_enabled=False, sms_enabled=False, whatsapp_enabled=False,
        )

    def test_email_opt_out_skips_before_provider(self):
        with patch('notifications.services.EmailService.send') as send:
            log = NotificationService.send_notification(
                recipient_name='Pref', recipient_contact='pref@example.com',
                channel='email', notification_type='general', message='hello',
                customer_id=self.customer.customer_id,
            )
        self.assertEqual(log.status, 'skipped')
        self.assertIn('email notifications disabled', log.error_message)
        send.assert_not_called()

    def test_sms_opt_out_skips_before_provider(self):
        with patch('notifications.services.SMSService.send') as send:
            log = NotificationService.send_notification(
                recipient_name='Pref', recipient_contact='03001234567',
                channel='sms', notification_type='general', message='hello',
                customer_id=self.customer.customer_id,
            )
        self.assertEqual(log.status, 'skipped')
        self.assertIn('sms notifications disabled', log.error_message)
        send.assert_not_called()

    def test_whatsapp_opt_out_skips_before_provider(self):
        with patch('notifications.services.WhatsAppService.send') as send:
            log = NotificationService.send_notification(
                recipient_name='Pref', recipient_contact='03001234567',
                channel='whatsapp', notification_type='general', message='hello',
                customer_id=self.customer.customer_id,
            )
        self.assertEqual(log.status, 'skipped')
        self.assertIn('whatsapp notifications disabled', log.error_message)
        send.assert_not_called()

    def test_contact_fallback_matches_customer_by_email(self):
        with patch('notifications.services.EmailService.send') as send:
            log = NotificationService.send_notification(
                recipient_name='Pref', recipient_contact='pref@example.com',
                channel='email', notification_type='general', message='hello',
            )
        self.assertEqual(log.status, 'skipped')
        send.assert_not_called()


@override_settings(EMAIL_ENABLED=True)
class RetryFailedNotificationsTests(TestCase):
    def failed_log(self, attempts=1, **kwargs):
        defaults = dict(
            recipient_name='Retry', recipient_contact='retry@example.com',
            channel='email', notification_type='general', subject='s',
            message='m', status='failed', attempts=attempts, error_message='boom',
        )
        defaults.update(kwargs)
        return NotificationLog.objects.create(**defaults)

    def test_retry_success_updates_same_log(self):
        log = self.failed_log()
        with patch('notifications.services.EmailService.send', return_value=(True, 'ok')):
            call_command('retry_failed_notifications', stdout=StringIO())
        log.refresh_from_db()
        self.assertEqual(log.status, 'sent')
        self.assertEqual(log.attempts, 2)
        self.assertEqual(log.error_message, '')

    def test_retry_dry_run_does_not_change_attempts(self):
        log = self.failed_log()
        with patch('notifications.services.EmailService.send') as send:
            out = StringIO()
            call_command('retry_failed_notifications', '--dry-run', stdout=out)
        log.refresh_from_db()
        self.assertEqual(log.attempts, 1)
        self.assertEqual(log.status, 'failed')
        send.assert_not_called()
        self.assertIn('Would retry', out.getvalue())

    def test_retry_stops_at_three_attempts(self):
        log = self.failed_log(attempts=3)
        with patch('notifications.services.EmailService.send') as send:
            call_command('retry_failed_notifications', stdout=StringIO())
        log.refresh_from_db()
        self.assertEqual(log.attempts, 3)
        self.assertEqual(log.status, 'failed')
        send.assert_not_called()

    def test_retry_skips_opted_out_customer(self):
        user = User.objects.create_user('retrypref', 'retrypref@example.com', 'pass123456')
        customer = Customer.objects.create(
            first_name='Retry', last_name='Pref', phone='03007654321',
            email='retry@example.com', cnic='12345-7654321-1', user=user,
        )
        NotificationPreference.objects.create(user=user, email_enabled=False)
        log = self.failed_log(related_customer_id=customer.customer_id)
        with patch('notifications.services.EmailService.send') as send:
            out = StringIO()
            call_command('retry_failed_notifications', stdout=out)
        log.refresh_from_db()
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.attempts, 1)
        send.assert_not_called()
        self.assertIn('Skipped', out.getvalue())
