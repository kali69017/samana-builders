"""Tests for the email-code password-reset feature."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import PasswordResetCode, UserProfile


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='resetuser', email='resetuser@example.com', password='oldpass123',
        )
        UserProfile.objects.create(user=self.user, role='staff')

    def _request_code(self, email=None):
        with patch('notifications.services.EmailService.send') as m:
            m.return_value = (True, 'sent')
            resp = self.client.post(reverse('password_reset_request'), {
                'email': email or self.user.email,
            })
            called = m.call_count
            to_email = str(m.call_args.kwargs.get('to_email') or m.call_args[1][0]) if called else ''
        return resp, called, to_email

    def test_request_generates_and_emails_code(self):
        resp, called, to_email = self._request_code()
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('password_reset_verify'), resp.url)
        self.assertEqual(called, 1)
        self.assertEqual(to_email.lower(), self.user.email.lower())
        code = PasswordResetCode.objects.filter(user=self.user, used=False).first()
        self.assertIsNotNone(code)
        self.assertTrue(code.code.isdigit())
        self.assertEqual(len(code.code), 6)

    def test_request_unknown_email_no_error(self):
        """No account enumeration: unknown email still redirects to verify."""
        resp, called, to_email = self._request_code('nobody@example.com')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(called, 0)

    def test_verify_wrong_code_rejected(self):
        self._request_code()
        old = self.user.password
        resp = self.client.post(reverse('password_reset_verify'), {
            'code': '000000', 'new_password': 'newpass123', 'confirm_password': 'newpass123',
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, old)
        self.assertContains(resp, 'Invalid or expired')

    def test_verify_password_mismatch_rejected(self):
        resp, _, _ = self._request_code()
        code = PasswordResetCode.objects.filter(user=self.user, used=False).first().code
        old = self.user.password
        self.client.post(reverse('password_reset_verify'), {
            'code': code, 'new_password': 'newpass123', 'confirm_password': 'different',
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, old)

    def test_verify_short_password_rejected(self):
        self._request_code()
        code = PasswordResetCode.objects.filter(user=self.user, used=False).first().code
        old = self.user.password
        self.client.post(reverse('password_reset_verify'), {
            'code': code, 'new_password': '123', 'confirm_password': '123',
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, old)

    def test_full_successful_reset(self):
        resp, _, _ = self._request_code()
        code = PasswordResetCode.objects.filter(user=self.user, used=False).first().code
        old = self.user.password
        resp = self.client.post(reverse('password_reset_verify'), {
            'code': code, 'new_password': 'newpass123', 'confirm_password': 'newpass123',
        })
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.password, old)
        self.assertTrue(self.user.check_password('newpass123'))
        self.assertFalse(self.user.check_password('oldpass123'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp.url)
        # code consumed
        self.assertFalse(PasswordResetCode.objects.filter(user=self.user, used=False).exists())

    def test_expired_code_rejected(self):
        self._request_code()
        rec = PasswordResetCode.objects.filter(user=self.user, used=False).first()
        from django.utils import timezone
        from datetime import timedelta
        rec.expires_at = timezone.now() - timedelta(minutes=1)
        rec.save(update_fields=['expires_at'])
        old = self.user.password
        self.client.post(reverse('password_reset_verify'), {
            'code': rec.code, 'new_password': 'newpass123', 'confirm_password': 'newpass123',
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, old)

    def test_verify_without_session_redirects_to_request(self):
        # fresh client, no reset_user_id in session
        resp = self.client.post(reverse('password_reset_verify'), {
            'code': '123456', 'new_password': 'newpass123', 'confirm_password': 'newpass123',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('password_reset_request'), resp.url)

    def test_no_pending_migrations(self):
        from io import StringIO
        buf = StringIO()
        # No migration changes should be pending (model matches migrations).
        call_command('makemigrations', '--check', '--dry-run', stdout=buf)
        self.assertIn('No changes detected', buf.getvalue())