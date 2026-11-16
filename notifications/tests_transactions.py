from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings

from notifications.models import NotificationLog
from notifications.services import DeliveryResult, EmailService, NotificationService


@override_settings(NOTIFICATIONS_SEND_IN_THREAD=False, EMAIL_ENABLED=False,
                   SENDPK_ENABLED=False, WHATSAPP_ENABLED=False)
class NotificationTransactionTests(TransactionTestCase):
    def _log(self):
        return NotificationLog.objects.create(
            recipient_name='Queue Probe',
            recipient_contact='queue-probe@example.com',
            channel='email',
            notification_type='welcome',
            subject='Queue probe',
            message='Body',
            status='queued',
        )

    def test_worker_delivers_outside_a_transaction(self):
        observed = []

        def fake_send(*args, **kwargs):
            observed.append(connection.in_atomic_block)
            return DeliveryResult(True, 'ok')

        log = self._log()
        with patch.object(EmailService, 'send', side_effect=fake_send):
            NotificationService.process_notification_id(log.pk)
        self.assertEqual(observed, [False])

    def test_process_queue_delivers_outside_a_transaction(self):
        observed = []

        def fake_send(*args, **kwargs):
            observed.append(connection.in_atomic_block)
            return DeliveryResult(True, 'ok')

        self._log()
        with patch.object(EmailService, 'send', side_effect=fake_send):
            call_command('process_notification_queue', stdout=StringIO())
        self.assertEqual(observed, [False])
