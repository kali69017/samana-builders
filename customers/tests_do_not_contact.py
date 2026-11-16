from datetime import date
from io import StringIO

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import UserProfile
from customers.admin import CustomerAdmin
from customers.models import Customer
from notifications.models import NotificationLog
from notifications.services import NotificationService


@override_settings(NOTIFICATIONS_SEND_IN_THREAD=False, EMAIL_ENABLED=False,
                   SENDPK_ENABLED=False, WHATSAPP_ENABLED=False)
class DoNotContactTests(TestCase):
    def setUp(self):
        self.admin = self._user('dncadmin', 'admin')
        self.management = self._user('dncmanager', 'management')
        self.accounts = self._user('dncaccounts', 'accounts')
        self.sales = self._user('dncsales', 'sales')
        self.customer = Customer.objects.create(
            first_name='Opt', last_name='Out', phone='+92-300-1234567',
            email='optout@example.com', cnic='12345-1234567-1', created_by=self.admin,
        )
        self.other = Customer.objects.create(
            first_name='Normal', last_name='Customer', phone='+92-300-7654321',
            email='normal@example.com', cnic='12345-1234567-2', created_by=self.admin,
        )

    def _user(self, username, role):
        user = User.objects.create_user(username, f'{username}@example.com', 'pass123456')
        UserProfile.objects.create(user=user, role=role)
        return user

    def test_every_channel_and_type_is_skipped(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        for channel in ('email', 'sms', 'whatsapp'):
            for notification_type in ('welcome', 'payment_confirmation',
                                      'installment_reminder'):
                log = NotificationService.queue_notification(
                    'Opt Out', self.customer.email if channel == 'email'
                    else self.customer.phone,
                    channel, notification_type, 'Message body',
                    customer_id=self.customer.customer_id,
                )
                self.assertEqual(log.status, 'skipped')
                self.assertEqual(
                    log.error_message,
                    'Skipped: customer opted out of all messages',
                )

    def test_direct_send_is_skipped(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        log = NotificationService.send_notification(
            'Opt Out', self.customer.email, 'email', 'welcome', 'Hello',
            customer_id=self.customer.customer_id,
        )
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.error_message,
                         'Skipped: customer opted out of all messages')

    def test_toggle_off_allows_queueing(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        self.customer.do_not_contact = False
        self.customer.save(update_fields=['do_not_contact'])
        log = NotificationService.queue_notification(
            'Opt Out', self.customer.email, 'email', 'welcome', 'Hello',
            customer_id=self.customer.customer_id,
        )
        self.assertEqual(log.status, 'queued')

    def test_contact_match_fallback_is_skipped(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        log = NotificationService.queue_notification(
            'Opt Out', self.customer.email, 'email', 'installment_reminder', 'Due',
        )
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.related_customer_id, self.customer.customer_id)

    def test_retry_command_skips_opted_out_customer(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        log = NotificationLog.objects.create(
            recipient_name='Opt Out', recipient_contact=self.customer.email,
            channel='email', notification_type='welcome', subject='Welcome',
            message='Hello', status='failed', attempts=1,
            related_customer_id=self.customer.customer_id,
        )
        out = StringIO()
        call_command('retry_failed_notifications', '--dry-run', stdout=out)
        self.assertIn('opted out of all messages', out.getvalue())
        log.refresh_from_db()
        self.assertEqual(log.status, 'failed')

    def test_process_queue_skips_opted_out_customer(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        log = NotificationLog.objects.create(
            recipient_name='Opt Out', recipient_contact=self.customer.email,
            channel='email', notification_type='welcome', subject='Welcome',
            message='Hello', status='queued',
            related_customer_id=self.customer.customer_id,
        )
        call_command('process_notification_queue', stdout=StringIO())
        log.refresh_from_db()
        self.assertEqual(log.status, 'skipped')
        self.assertEqual(log.error_message,
                         'Skipped: customer opted out of all messages')

    def test_toggle_permissions(self):
        url = reverse('customer_do_not_contact', args=[self.customer.pk])
        for user in (self.accounts, self.sales):
            self.client.force_login(user)
            response = self.client.post(url, {'do_not_contact': 'on'})
            self.assertEqual(response.status_code, 302)
            self.customer.refresh_from_db()
            self.assertFalse(self.customer.do_not_contact)
        for user in (self.admin, self.management):
            self.client.force_login(user)
            response = self.client.post(url, {
                'do_not_contact': 'on', 'do_not_contact_reason': 'Customer asked',
            })
            self.assertEqual(response.status_code, 302)
            self.customer.refresh_from_db()
            self.assertTrue(self.customer.do_not_contact)
            self.assertEqual(self.customer.do_not_contact_set_by, user)
            self.assertIsNotNone(self.customer.do_not_contact_at)
            self.customer.do_not_contact = False
            self.customer.save(update_fields=['do_not_contact'])

    def test_list_filter_and_badge(self):
        self.customer.do_not_contact = True
        self.customer.save(update_fields=['do_not_contact'])
        self.client.force_login(self.admin)
        response = self.client.get(reverse('customers'), {'do_not_contact': '1'})
        self.assertContains(response, 'Do not message')
        customers = list(response.context['customers'])
        self.assertIn(self.customer, customers)
        self.assertNotIn(self.other, customers)

    def test_admin_bulk_actions(self):
        model_admin = CustomerAdmin(Customer, None)
        request = RequestFactory().get('/admin/customers/customer/')
        request.user = self.admin
        request.session = {}
        request._messages = FallbackStorage(request)
        model_admin.stop_all_messages(request, Customer.objects.all())
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.do_not_contact)
        self.assertEqual(self.customer.do_not_contact_set_by, self.admin)
        model_admin.allow_messages(request, Customer.objects.all())
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.do_not_contact)

    def test_api_fields_are_read_only(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.patch(
            f'/api/customers/{self.customer.pk}/',
            {'do_not_contact': True, 'do_not_contact_reason': 'API attempt'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.do_not_contact)
