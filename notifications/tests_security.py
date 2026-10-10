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

    def manual_send(self, user, contact, channel='email'):
        """POST to the manual-send endpoint as ``user``; returns the response."""
        self.client.force_login(user)
        return self.client.post(reverse('send_notification'), {
            'recipient_name': 'QA',
            'recipient_contact': contact,
            'channel': channel,
            'subject': 't',
            'message': 'm',
        })


class ManualSendRateLimitTest(NotificationSecurityBase):
    def test_same_recipient_beyond_cap_is_refused(self):
        # First three to the same address are fine.
        for _ in range(3):
            resp = self.manual_send(self.mgmt1, 'victim@example.com')
            self.assertEqual(resp.status_code, 302)
        # The fourth must be throttled.
        resp = self.manual_send(self.mgmt1, 'victim@example.com')
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(
            NotificationLog.objects.filter(recipient_contact='victim@example.com').count(), 3,
        )

    def test_distinct_recipients_are_not_limited(self):
        for i in range(5):
            resp = self.manual_send(self.mgmt1, f'user{i}@example.com')
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(NotificationLog.objects.filter(recipient_contact__startswith='user').count(), 5)

    def test_limit_is_per_recipient_not_global(self):
        for i in range(4):
            self.assertEqual(self.manual_send(self.mgmt1, f'a{i}@example.com').status_code, 302)
        # A fresh recipient still goes through.
        self.assertEqual(self.manual_send(self.mgmt1, 'fresh@example.com').status_code, 302)


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