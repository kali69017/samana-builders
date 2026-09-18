"""API tests for the double-entry accounting endpoints (Voucher, AccountHead).

TDD: written before the endpoints exist.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile

from .models import AccountHead, Voucher, VoucherAuditLog, VoucherLine


class AccountingApiBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('apiadmin', 'a@example.com', 'pass12345')
        self.finance = User.objects.create_user('fin', 'f@example.com', 'pass12345')
        UserProfile.objects.create(user=self.finance, role='accounts')
        self.supervisor = User.objects.create_user('sup', 's@example.com', 'pass12345')
        UserProfile.objects.create(user=self.supervisor, role='management')
        self.sales = User.objects.create_user('sal', 'x@example.com', 'pass12345')
        UserProfile.objects.create(user=self.sales, role='sales')

        self.cash = AccountHead.objects.create(code='1000', name='Cash', nature='debit')
        self.capital = AccountHead.objects.create(code='3000', name='Capital', nature='credit')

    def as_user(self, user):
        self.client.force_authenticate(user=user)

    def make_voucher(self, user=None):
        return Voucher.objects.create(
            voucher_type='JV', date=date.today(), created_by=user or self.admin,
        )

    def balanced_payload(self):
        return {
            'voucher_type': 'JV', 'date': date.today().isoformat(), 'narration': 'Opening',
            'lines': [
                {'account_head': self.cash.pk, 'debit': '100.00', 'credit': '0.00'},
                {'account_head': self.capital.pk, 'debit': '0.00', 'credit': '100.00'},
            ],
        }


class VoucherApiTests(AccountingApiBase):
    # ── CRUD / permissions ───────────────────────────────────────────────
    def test_finance_can_create_draft_voucher_with_lines(self):
        self.as_user(self.finance)
        resp = self.client.post(reverse('voucher-list'), self.balanced_payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        voucher = Voucher.objects.get(pk=resp.data['id'])
        self.assertEqual(voucher.status, 'draft')
        self.assertEqual(voucher.lines.count(), 2)
        self.assertEqual(voucher.voucher_number, 'JV-00001')

    def test_sales_cannot_access_vouchers(self):
        self.as_user(self.sales)
        self.assertEqual(self.client.get(reverse('voucher-list')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post(reverse('voucher-list'), self.balanced_payload(), format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_update_draft_voucher_and_lines(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        self.as_user(self.finance)
        resp = self.client.patch(reverse('voucher-detail', args=[voucher.pk]), {
            'narration': 'edited',
            'lines': [
                {'account_head': self.cash.pk, 'debit': '250.00', 'credit': '0.00'},
                {'account_head': self.capital.pk, 'debit': '0.00', 'credit': '250.00'},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        voucher.refresh_from_db()
        self.assertEqual(voucher.narration, 'edited')
        self.assertEqual(voucher.lines.count(), 2)
        self.assertEqual(sum(l.debit for l in voucher.lines.all()), Decimal('250.00'))

    def test_update_locked_voucher_rejected(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.admin)
        self.as_user(self.finance)
        resp = self.client.patch(reverse('voucher-detail', args=[voucher.pk]), {'narration': 'nope'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_draft_voucher(self):
        voucher = self.make_voucher()
        self.as_user(self.finance)
        resp = self.client.delete(reverse('voucher-detail', args=[voucher.pk]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Voucher.objects.filter(pk=voucher.pk).exists())

    # ── post ─────────────────────────────────────────────────────────────
    def test_post_balanced_voucher_locks_it(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        self.as_user(self.supervisor)
        resp = self.client.post(reverse('voucher-post', args=[voucher.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, 'posted')
        self.assertTrue(voucher.is_locked)
        self.assertEqual(voucher.locked_by, self.supervisor)

    def test_post_unbalanced_voucher_rejected(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('99'))
        self.as_user(self.supervisor)
        resp = self.client.post(reverse('voucher-post', args=[voucher.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_requires_supervisor_role(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        for user in (self.sales, self.finance):
            self.as_user(user)
            resp = self.client.post(reverse('voucher-post', args=[voucher.pk]), {}, format='json')
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_twice_rejected(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        self.as_user(self.supervisor)
        self.client.post(reverse('voucher-post', args=[voucher.pk]), {}, format='json')
        resp = self.client.post(reverse('voucher-post', args=[voucher.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── unlock / audit ───────────────────────────────────────────────────
    def _posted_voucher(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.admin)
        return voucher

    def test_unlock_requires_supervisor_role(self):
        voucher = self._posted_voucher()
        self.as_user(self.finance)
        resp = self.client.post(reverse('voucher-unlock', args=[voucher.pk]),
                                {'reason': 'correction'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unlock_requires_reason(self):
        voucher = self._posted_voucher()
        self.as_user(self.supervisor)
        resp = self.client.post(reverse('voucher-unlock', args=[voucher.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_supervisor_unlock_writes_audit_row(self):
        voucher = self._posted_voucher()
        self.as_user(self.supervisor)
        resp = self.client.post(reverse('voucher-unlock', args=[voucher.pk]),
                                {'reason': 'wrong head'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, 'posted')
        self.assertFalse(voucher.is_locked)
        row = VoucherAuditLog.objects.get(voucher=voucher, event='unlocked')
        self.assertEqual(row.reason, 'wrong head')
        self.assertEqual(row.actor, self.supervisor)

    def test_audit_endpoint_returns_full_history(self):
        voucher = self._posted_voucher()
        voucher.unlock(self.supervisor, reason='fix')
        self.as_user(self.finance)
        resp = self.client.get(reverse('voucher-audit', args=[voucher.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        events = [row['event'] for row in resp.data]
        self.assertIn('created', events)
        self.assertIn('posted', events)
        self.assertIn('unlocked', events)

    # ── auto-generated vouchers are read-only ────────────────────────────
    def test_auto_generated_voucher_read_only_except_unlock(self):
        voucher = Voucher.objects.create(
            voucher_type='CR', date=date.today(), reference_type='Payment', reference_id=999,
            created_by=self.admin,
        )
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.admin)

        self.as_user(self.finance)
        detail = self.client.get(reverse('voucher-detail', args=[voucher.pk]))
        self.assertTrue(detail.data['is_auto_generated'])
        self.assertFalse(detail.data['is_editable'])

        patch = self.client.patch(reverse('voucher-detail', args=[voucher.pk]), {'narration': 'x'}, format='json')
        self.assertEqual(patch.status_code, status.HTTP_400_BAD_REQUEST)
        delete = self.client.delete(reverse('voucher-detail', args=[voucher.pk]))
        self.assertEqual(delete.status_code, status.HTTP_400_BAD_REQUEST)

        # unlock remains available to a supervisor
        self.as_user(self.supervisor)
        unlock = self.client.post(reverse('voucher-unlock', args=[voucher.pk]),
                                  {'reason': 'audit'}, format='json')
        self.assertEqual(unlock.status_code, status.HTTP_200_OK)


class AccountHeadApiTests(AccountingApiBase):
    def test_finance_can_create_head(self):
        self.as_user(self.finance)
        resp = self.client.post(reverse('accounthead-list'),
                                {'code': '1100', 'name': 'Petty Cash', 'nature': 'debit'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data['level'], 1)

    def test_create_child_sets_level_two(self):
        self.as_user(self.finance)
        resp = self.client.post(reverse('accounthead-list'),
                                {'code': '1100', 'name': 'Petty Cash', 'parent': self.cash.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data['level'], 2)

    def test_parent_at_max_depth_rejected(self):
        h2 = AccountHead.objects.create(code='A2', name='L2', parent=self.cash)
        h3 = AccountHead.objects.create(code='A3', name='L3', parent=h2)
        h4 = AccountHead.objects.create(code='A4', name='L4', parent=h3)
        self.as_user(self.finance)
        resp = self.client.post(reverse('accounthead-list'),
                                {'code': 'A5', 'name': 'L5', 'parent': h4.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_parent_cycle_rejected(self):
        child = AccountHead.objects.create(code='1100', name='Petty Cash', parent=self.cash)
        self.as_user(self.finance)
        resp = self.client.patch(reverse('accounthead-detail', args=[self.cash.pk]),
                                 {'parent': child.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_head_with_children_blocked(self):
        AccountHead.objects.create(code='1100', name='Petty Cash', parent=self.cash)
        self.as_user(self.finance)
        resp = self.client.delete(reverse('accounthead-detail', args=[self.cash.pk]))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_head_with_posted_lines_blocked(self):
        voucher = self.make_voucher()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.admin)
        self.as_user(self.finance)
        resp = self.client.delete(reverse('accounthead-detail', args=[self.cash.pk]))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_unused_head(self):
        head = AccountHead.objects.create(code='9000', name='Unused')
        self.as_user(self.finance)
        resp = self.client.delete(reverse('accounthead-detail', args=[head.pk]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_sales_cannot_access_account_heads(self):
        self.as_user(self.sales)
        self.assertEqual(self.client.get(reverse('accounthead-list')).status_code, status.HTTP_403_FORBIDDEN)