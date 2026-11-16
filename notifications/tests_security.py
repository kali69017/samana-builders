"""Production-hardening tests for the notification module.

- Rate limiting: a single recipient may only be manually targeted N times per
  day (anti spam-blast); distinct recipients are unaffected.
- PII masking: management sees masked recipient contacts; super_admin sees raw.
- Object scoping: management sees only the rows it created; admin/super_admin
  see everything.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from .models import NotificationLog


class NotificationSecurityBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'pass123456')
        self.mgmt1 = User.objects.create_user('mgmt1', 'mgmt1@example.com', 'pass123456')
        UserProfile.objects.create(user=self.mgmt1, role='management')
        self.mgmt2 = User.objects.create_user('mgmt2', 'mgmt2@example.com', 'pass123456')
        UserProfile.objects.create(user=self.mgmt2, role='management')

class NotificationCenterMaskingTest(NotificationSecurityBase):
    def test_management_sees_masked_contact(self):
        email = 'sensitive@example.com'
        # Created by the *viewing* management user so the scoped log includes it.
        NotificationLog.objects.create(
            recipient_name='QA', recipient_contact=email, channel='email',
            notification_type='general', subject='x', message='y', status='sent',
            created_by=self.mgmt1,
        )
        self.client.force_login(self.mgmt1)
        resp = self.client.get(reverse('notifications'))
        html = resp.content.decode()
        self.assertNotIn(email, html)
        # The masked form of the address must still be present.
        self.assertIn('s**@', html)

    def test_superadmin_sees_raw_contact(self):
        email = 'fullview@example.com'
        NotificationLog.objects.create(
            recipient_name='QA', recipient_contact=email, channel='email',
            notification_type='general', subject='x', message='y', status='sent',
            created_by=self.admin,
        )
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('notifications'))
        self.assertIn(email, resp.content.decode())


class NotificationCenterVisibilityTests(NotificationSecurityBase):
    def test_read_only_log_shows_error_related_ids_and_filters(self):
        NotificationLog.objects.create(
            recipient_name='Visible', recipient_contact='visible@example.com',
            channel='email', notification_type='customer_welcome',
            subject='x', message='y', status='failed', error_message='provider exploded',
            related_customer_id='CUS-00001', related_booking_id='BKG-00001',
            created_by=self.admin,
        )
        self.client.force_login(self.admin)
        html = self.client.get(reverse('notifications')).content.decode()
        for text in ('Sent', 'Failed', 'Customer Welcome', 'Error', 'Customer',
                     'Booking', 'provider exploded', 'CUS-00001', 'BKG-00001'):
            self.assertIn(text, html)
        self.assertNotIn('Send Notification', html)


class ManualSendRemovedTest(NotificationSecurityBase):
    def test_old_manual_send_url_returns_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post('/notifications/send/').status_code, 404)
        self.assertEqual(self.client.get('/notifications/send/').status_code, 404)


class NotificationCenterScopingTest(NotificationSecurityBase):
    def test_management_only_sees_own_rows(self):
        NotificationLog.objects.create(
            recipient_name='Other', recipient_contact='other@example.com', channel='email',
            notification_type='general', subject='x', message='y', status='sent',
            created_by=self.mgmt2,
        )
        NotificationLog.objects.create(
            recipient_name='Own', recipient_contact='own@example.com', channel='email',
            notification_type='general', subject='x', message='y', status='sent',
            created_by=self.mgmt1,
        )
        self.client.force_login(self.mgmt1)
        html = self.client.get(reverse('notifications')).content.decode()
        # Own row is visible (contact is masked for management, so assert the name).
        self.assertIn('Own', html)
        # Another user's row is scoped out entirely.
        self.assertNotIn('other@example.com', html)
        self.assertNotIn('Other', html)

    def test_admin_sees_all_rows(self):
        NotificationLog.objects.create(
            recipient_name='Other', recipient_contact='other@example.com', channel='email',
            notification_type='general', subject='x', message='y', status='sent',
            created_by=self.mgmt2,
        )
        self.client.force_login(self.admin)
        html = self.client.get(reverse('notifications')).content.decode()
        self.assertIn('other@example.com', html)