from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import OperationalError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from notifications.models import NotificationLog
from notifications.services import NotificationService


class NotificationOutboxTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('outbox', 'o@example.com', 'pass123456')

    def test_thread_sender_is_off_in_tests(self):
        from django.conf import settings
        self.assertFalse(settings.NOTIFICATIONS_SEND_IN_THREAD)

    def test_customer_request_queues_without_calling_providers(self):
        self.client.force_login(self.admin)
        with patch('notifications.services.EmailService.send') as email_send, \
                patch('notifications.services.SMSService.send') as sms_send:
            response = self.client.post('/customers/create/', {
                'first_name': 'Queue', 'last_name': 'Test',
                'email': 'queue@example.com', 'phone': '03001234567',
                'cnic': '12345-1234567-1', 'is_active': 'on',
            })
        self.assertEqual(response.status_code, 302)
        log = NotificationLog.objects.filter(recipient_contact='queue@example.com').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'queued')
        email_send.assert_not_called()
        sms_send.assert_not_called()

    def test_on_commit_not_fired_when_transaction_rolls_back(self):
        with patch('notifications.services.NotificationService._schedule') as schedule:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    NotificationService.queue_notification(
                        recipient_name='Rollback', recipient_contact='r@example.com',
                        channel='email', notification_type='general', message='m',
                    )
                    raise RuntimeError('rollback')
        self.assertFalse(NotificationLog.objects.filter(recipient_name='Rollback').exists())
        schedule.assert_not_called()

    def test_atomic_claim_prevents_double_send(self):
        log = NotificationLog.objects.create(
            recipient_name='Claim', recipient_contact='c@example.com', channel='email',
            notification_type='general', message='m', status='queued',
        )
        self.assertTrue(NotificationService._claim(log.pk))
        self.assertFalse(NotificationService._claim(log.pk))

    def test_stuck_sending_is_marked_unknown(self):
        log = NotificationLog.objects.create(
            recipient_name='Stuck', recipient_contact='s@example.com', channel='email',
            notification_type='general', message='m', status='sending',
            sending_at=timezone.now() - timedelta(minutes=11),
        )
        call_command('process_notification_queue', stdout=__import__('io').StringIO())
        log.refresh_from_db()
        self.assertEqual(log.status, 'unknown')
        self.assertIn('provider dashboard', log.error_message)

    def test_dry_run_changes_nothing(self):
        log = NotificationLog.objects.create(
            recipient_name='Dry', recipient_contact='d@example.com', channel='email',
            notification_type='general', message='m', status='queued',
        )
        call_command('process_notification_queue', '--dry-run', stdout=__import__('io').StringIO())
        log.refresh_from_db()
        self.assertEqual(log.status, 'queued')


@override_settings(EMAIL_ENABLED=True)
class NotificationOutcomeTests(TestCase):
    def test_read_timeout_is_unknown_not_retryable(self):
        log = NotificationLog.objects.create(
            recipient_name='Unknown', recipient_contact='u@example.com', channel='email',
            notification_type='general', message='m', status='queued',
            attempts=1,
        )
        with patch('notifications.services.EmailService.send') as send:
            from notifications.services import DeliveryResult
            send.return_value = DeliveryResult(False, 'read timeout', retryable=False)
            NotificationService._deliver(log)
        log.refresh_from_db()
        self.assertEqual(log.status, 'unknown')

    def test_permanent_error_sets_attempts_to_three(self):
        log = NotificationLog.objects.create(
            recipient_name='Permanent', recipient_contact='p@example.com', channel='email',
            notification_type='general', message='m', status='queued',
            attempts=1,
        )
        with patch('notifications.services.EmailService.send') as send:
            from notifications.services import DeliveryResult
            send.return_value = DeliveryResult(False, 'invalid', permanent=True)
            NotificationService._deliver(log)
        log.refresh_from_db()
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.attempts, 3)


class EventPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('prefuser', 'pref@example.com', 'pass123456')
        from customers.models import Customer
        from notifications.models import NotificationPreference
        self.customer = Customer.objects.create(
            first_name='Pref', last_name='Customer', phone='03001234567',
            email='pref@example.com', user=self.user,
        )
        NotificationPreference.objects.create(user=self.user)

    def _queue(self, notification_type):
        return NotificationService.queue_notification(
            recipient_name=self.customer.full_name,
            recipient_contact=self.customer.email,
            channel='email', notification_type=notification_type,
            message='m', customer_id=self.customer.customer_id,
        )

    def test_each_mapped_event_flag_blocks_queueing(self):
        from notifications.models import NotificationPreference
        from notifications.services import EVENT_PREF_FIELD
        for notification_type, field in EVENT_PREF_FIELD.items():
            with self.subTest(notification_type=notification_type):
                NotificationPreference.objects.filter(user=self.user).update(**{field: False})
                log = self._queue(notification_type)
                self.assertEqual(log.status, 'skipped')
                self.assertIn('disabled', log.error_message)
                NotificationPreference.objects.filter(user=self.user).update(**{field: True})

    def test_unmapped_type_is_always_allowed(self):
        log = self._queue('customer_welcome')
        self.assertEqual(log.status, 'queued')


@override_settings(EMAIL_ENABLED=True)
class QueueLockRetryTests(TestCase):
    def test_final_status_save_retries_database_locked(self):
        from notifications.services import DeliveryResult
        log = NotificationLog.objects.create(
            recipient_name='Lock', recipient_contact='lock@example.com', channel='email',
            notification_type='general', message='m', status='queued', attempts=1,
        )
        with patch('notifications.services.EmailService.send',
                   return_value=DeliveryResult(True, 'ok')), \
                patch.object(NotificationLog, 'save',
                             side_effect=[OperationalError('database is locked'), None]) as save:
            NotificationService._deliver(log)
        self.assertEqual(log.status, 'sent')
        self.assertEqual(2, save.call_count)
