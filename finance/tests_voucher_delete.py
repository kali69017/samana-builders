from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import UserProfile
from finance.admin import VoucherAdmin
from finance.models import AccountHead, Voucher, VoucherDeletionLog, VoucherLine


class VoucherDeleteTests(TestCase):
    def setUp(self):
        self.super_admin = self._user('super', 'super_admin', superuser=True)
        self.admin = self._user('admin1', 'admin')
        self.management = self._user('manager', 'management')
        self.accounts = self._user('accountant', 'accounts')
        self.sales = self._user('seller', 'sales')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.revenue = AccountHead.objects.get(system_role='revenue')

    def _user(self, username, role, superuser=False):
        if superuser:
            user = User.objects.create_superuser(username, f'{username}@example.com', 'pass123456')
        else:
            user = User.objects.create_user(username, f'{username}@example.com', 'pass123456')
        UserProfile.objects.create(user=user, role=role)
        return user

    def _manual_voucher(self, user=None, amount=Decimal('100'), voucher_type='JV'):
        voucher = Voucher.objects.create(
            voucher_type=voucher_type, date=date.today(), narration='Manual test voucher',
            created_by=user or self.admin,
        )
        if voucher_type == 'JV':
            VoucherLine.objects.create(
                voucher=voucher, account_head=self.cash, debit=amount, credit=0)
            VoucherLine.objects.create(
                voucher=voucher, account_head=self.revenue, debit=0, credit=amount)
        else:
            VoucherLine.objects.create(
                voucher=voucher, account_head=self.cash, debit=amount, credit=0)
            VoucherLine.objects.create(
                voucher=voucher, account_head=self.revenue, debit=0, credit=amount)
        voucher.post(user or self.admin)
        return voucher

    def _system_voucher(self):
        voucher = Voucher.objects.create(
            voucher_type='JV', date=date.today(), narration='System voucher',
            reference_type='Payment', reference_id=99999, created_by=self.admin,
        )
        VoucherLine.objects.create(
            voucher=voucher, account_head=self.cash, debit=50, credit=0)
        VoucherLine.objects.create(
            voucher=voucher, account_head=self.revenue, debit=0, credit=50)
        voucher.post(self.admin)
        return voucher

    def test_admin_can_delete_manual_voucher_with_snapshot(self):
        voucher = self._manual_voucher()
        number = voucher.voucher_number
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('finance_voucher_delete', args=[voucher.pk]),
            {'reason': 'Duplicate entry created by mistake'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Voucher.objects.filter(pk=voucher.pk).exists())
        log = VoucherDeletionLog.objects.get(voucher_number=number)
        self.assertEqual(log.deleted_by, self.admin)
        self.assertEqual(log.total, Decimal('100.00'))
        self.assertEqual(len(log.lines), 2)
        self.assertEqual(log.reason, 'Duplicate entry created by mistake')
        self.assertGreaterEqual(len(log.audit_logs), 1)

    def test_reason_is_required_and_minimum_length(self):
        voucher = self._manual_voucher()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('finance_voucher_delete', args=[voucher.pk]), {'reason': 'why'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())
        self.assertFalse(VoucherDeletionLog.objects.exists())

    def test_system_voucher_cannot_be_deleted(self):
        voucher = self._system_voucher()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('finance_voucher_delete', args=[voucher.pk]),
            {'reason': 'Trying to delete system voucher'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())
        with self.assertRaises(ValidationError):
            voucher.delete_manual_voucher(self.admin, 'Trying to delete system voucher')

    def test_management_accounts_and_sales_are_denied(self):
        for user in (self.management, self.accounts, self.sales):
            voucher = self._manual_voucher()
            self.client.force_login(user)
            response = self.client.post(
                reverse('finance_voucher_delete', args=[voucher.pk]),
                {'reason': 'Should not be allowed'},
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())

    def test_super_admin_can_delete(self):
        voucher = self._manual_voucher()
        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse('finance_voucher_delete', args=[voucher.pk]),
            {'reason': 'Super admin cleanup'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Voucher.objects.filter(pk=voucher.pk).exists())

    def test_api_delete_stays_405(self):
        voucher = self._manual_voucher()
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.delete(reverse('voucher-detail', args=[voucher.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())

    def test_django_admin_delete_is_superuser_only(self):
        voucher = self._manual_voucher()
        admin_view = VoucherAdmin(Voucher, None)
        request = RequestFactory().get('/admin/finance/voucher/')
        request.user = self.admin
        self.assertFalse(admin_view.has_delete_permission(request, voucher))
        request.user = self.super_admin
        self.assertTrue(admin_view.has_delete_permission(request, voucher))
        request.user = self.super_admin
        self.assertFalse(admin_view.has_delete_permission(request, self._system_voucher()))

    def test_number_gap_is_left_after_delete(self):
        first = self._manual_voucher()
        second = self._manual_voucher()
        second_number = second.voucher_number
        first.delete_manual_voucher(self.admin, 'Remove the duplicate')
        third = self._manual_voucher()
        first_num = int(first.voucher_number.split('-')[1])
        second_num = int(second_number.split('-')[1])
        third_num = int(third.voucher_number.split('-')[1])
        self.assertEqual(first_num + 1, second_num)
        self.assertEqual(second_num + 1, third_num)

    def test_integrity_passes_after_manual_delete(self):
        voucher = self._manual_voucher()
        voucher.delete_manual_voucher(self.admin, 'Remove balanced manual voucher')
        out = StringIO()
        call_command('finance_integrity_check', stdout=out)
        self.assertIn('Finance integrity check passed', out.getvalue())
