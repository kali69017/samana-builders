"""Tests for the Finance module (office expenses, project costs, ledger)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile
from properties.models import Project
from .models import (
    AccountTransaction, AccountHead, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment, Voucher, VoucherLine,
)


class FinanceModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.office = Office.objects.create(name='Head Office', office_type='head_office')
        self.category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        self.project = Project.objects.create(name='Test Project', location='Lahore')

    def test_office_expense_posts_to_ledger(self):
        expense = OfficeExpense.objects.create(office=self.office, category=self.category,
                                               amount=Decimal('50000'), expense_date=date.today(),
                                               payment_method='cash', status='paid',
                                               created_by=self.user)
        expense.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='OfficeExpense', reference_id=expense.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self.assertTrue(voucher.is_locked)
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='OfficeExpense', reference_id=expense.pk).exists())

    def test_project_cost_posts_to_ledger(self):
        cost = ProjectCost.objects.create(project=self.project, cost_category='material',
                                          amount=Decimal('100000'), cost_date=date.today(),
                                          status='paid', created_by=self.user)
        cost.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='ProjectCost', reference_id=cost.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).exists())

    def test_budget_actual_and_remaining(self):
        ProjectCost.objects.create(project=self.project, cost_category='labor',
                                   amount=Decimal('40000'), cost_date=date.today(), status='paid')
        budget = ProjectBudget.objects.create(project=self.project, total_budget=Decimal('100000'),
                                              labor_budget=Decimal('50000'))
        self.assertEqual(budget.total_actual, Decimal('40000'))
        self.assertEqual(budget.remaining_budget, Decimal('60000'))

    def test_investment_create(self):
        inv = ProjectInvestment.objects.create(project=self.project, total_investment=Decimal('5000000'))
        self.assertEqual(inv.total_investment, Decimal('5000000'))


class FinanceAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        self.office = Office.objects.create(name='Head Office', office_type='head_office')
        self.category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        self.project = Project.objects.create(name='P1', location='Lahore')

    def test_create_office(self):
        resp = self.client.post(reverse('office-list'), {'name': 'Branch A', 'office_type': 'branch'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_office_expense_posts_ledger(self):
        # status is read-only on the API (server default 'pending'); a create
        # never auto-posts. Paying via the 'pay' action posts a voucher.
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': self.office.pk, 'category': self.category.pk, 'amount': '25000',
            'expense_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        oe_id = resp.data['id']
        self.assertFalse(Voucher.objects.filter(
            reference_type='OfficeExpense', reference_id=oe_id).exists())
        pay_resp = self.client.post(reverse('officeexpense-pay', args=[oe_id]), format='json')
        self.assertEqual(pay_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(Voucher.objects.filter(
            reference_type='OfficeExpense', reference_id=oe_id).exists())
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='OfficeExpense', reference_id=oe_id).exists())

    def test_create_office_expense_zero_rejected(self):
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': self.office.pk, 'amount': '0', 'expense_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_project_cost_posts_ledger(self):
        # status is read-only on the API (server default 'pending'); a create
        # never auto-posts to the ledger.
        resp = self.client.post(reverse('projectcost-list'), {
            'project': self.project.pk, 'cost_category': 'material', 'amount': '50000',
            'cost_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        pc = ProjectCost.objects.get(pk=resp.data['id'])
        self.assertEqual(pc.status, 'pending')
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='ProjectCost', reference_id=pc.pk).exists())

    def test_office_expense_approve_action(self):
        expense = OfficeExpense.objects.create(office=self.office, amount=Decimal('10000'), expense_date=date.today())
        resp = self.client.post(reverse('officeexpense-approve', args=[expense.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'approved')

    def test_project_budget_api(self):
        resp = self.client.post(reverse('projectbudget-list'), {
            'project': self.project.pk, 'total_budget': '200000', 'material_budget': '100000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_non_finance_cannot_create_expense(self):
        sales = User.objects.create_user('sales', 's@example.com', 'pass12345')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': self.office.pk, 'amount': '1000', 'expense_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class AccountingModelTest(TestCase):
    """Double-entry foundation: AccountHead / Voucher / VoucherLine."""

    def setUp(self):
        self.user = User.objects.create_superuser('acct', 'acct@example.com', 'pass12345')
        self.cash = AccountHead.objects.create(code='1000', name='Cash', nature='debit')
        self.capital = AccountHead.objects.create(code='3000', name='Capital', nature='credit')

    def _draft(self, voucher_type='JV', **kwargs):
        return Voucher.objects.create(
            voucher_type=voucher_type, date=date.today(),
            created_by=self.user, **kwargs,
        )

    # ── Chart of accounts ────────────────────────────────────────────────
    def test_creating_child_clears_parent_leaf_flag(self):
        self.assertTrue(self.cash.is_leaf)
        child = AccountHead.objects.create(code='1100', name='Petty Cash', parent=self.cash)
        self.cash.refresh_from_db()
        self.assertFalse(self.cash.is_leaf)
        self.assertTrue(child.is_leaf)
        self.assertEqual(child.level, 2)

    def test_depth_capped_at_four_levels(self):
        h1 = AccountHead.objects.create(code='A1', name='L1')
        h2 = AccountHead.objects.create(code='A2', name='L2', parent=h1)
        h3 = AccountHead.objects.create(code='A3', name='L3', parent=h2)
        h4 = AccountHead.objects.create(code='A4', name='L4', parent=h3)
        self.assertEqual(h4.level, 4)
        with self.assertRaises(ValidationError):
            AccountHead.objects.create(code='A5', name='L5', parent=h4)

    def test_posting_to_non_leaf_head_rejected(self):
        AccountHead.objects.create(code='1100', name='Petty Cash', parent=self.cash)
        self.cash.refresh_from_db()
        voucher = self._draft()
        line = VoucherLine(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        with self.assertRaises(ValidationError):
            line.full_clean()

    # ── Numbering ────────────────────────────────────────────────────────
    def test_voucher_numbering_is_per_type(self):
        first = self._draft('CP')
        second = self._draft('CP')
        journal = self._draft('JV')
        self.assertEqual(first.voucher_number, 'CP-00001')
        self.assertEqual(second.voucher_number, 'CP-00002')
        self.assertEqual(journal.voucher_number, 'JV-00001')

    # ── Posting ──────────────────────────────────────────────────────────
    def test_post_balanced_voucher_locks_and_stamps(self):
        voucher = self._draft()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))

        voucher.post(self.user)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, 'posted')
        self.assertTrue(voucher.is_locked)
        self.assertEqual(voucher.locked_by, self.user)
        self.assertIsNotNone(voucher.locked_at)
        self.assertFalse(voucher.is_editable)

    def test_post_unbalanced_voucher_rejected(self):
        voucher = self._draft()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('99'))
        with self.assertRaises(ValidationError):
            voucher.post(self.user)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, 'draft')

    def test_post_requires_lines(self):
        voucher = self._draft()
        with self.assertRaises(ValidationError):
            voucher.post(self.user)

    def test_post_twice_while_locked_rejected(self):
        voucher = self._draft()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.user)
        with self.assertRaises(ValidationError):
            voucher.post(self.user)

    # ── Lock / edit / unlock ─────────────────────────────────────────────
    def test_locked_voucher_and_lines_are_not_editable(self):
        voucher = self._draft()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.user)

        with self.assertRaises(ValidationError):
            voucher.clean()
        new_line = VoucherLine(voucher=voucher, account_head=self.cash, debit=Decimal('50'))
        with self.assertRaises(ValidationError):
            new_line.full_clean()

    def test_unlock_requires_reason_and_only_flips_lock(self):
        voucher = self._draft()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.user)

        with self.assertRaises(ValidationError):
            voucher.unlock(self.user, reason='   ')

        voucher.unlock(self.user, reason='Wrong cost centre')
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, 'posted')
        self.assertFalse(voucher.is_locked)
        self.assertEqual(voucher.unlocked_by, self.user)
        self.assertIsNotNone(voucher.unlocked_at)
        self.assertEqual(voucher.unlock_reason, 'Wrong cost centre')
        self.assertTrue(voucher.is_editable)

    def test_repost_after_unlock_relocks_and_updates_holder(self):
        voucher = self._draft()
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('100'))
        voucher.post(self.user)
        first_locked_at = voucher.locked_at
        voucher.unlock(self.user, reason='fix')
        VoucherLine.objects.create(voucher=voucher, account_head=self.cash, debit=Decimal('1'))
        VoucherLine.objects.create(voucher=voucher, account_head=self.capital, credit=Decimal('1'))

        other = User.objects.create_user('supervisor', 'sup@example.com', 'pass12345')
        voucher.post(other)
        voucher.refresh_from_db()
        self.assertTrue(voucher.is_locked)
        self.assertEqual(voucher.status, 'posted')
        self.assertEqual(voucher.locked_by, other)
        self.assertGreaterEqual(voucher.locked_at, first_locked_at)

    # ── Constraints ──────────────────────────────────────────────────────
    def test_reference_source_is_unique(self):
        self._draft('CR', reference_type='Payment', reference_id=7)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._draft('CR', reference_type='Payment', reference_id=7)

    def test_manual_vouchers_exempt_from_source_uniqueness(self):
        self._draft('JV')
        self._draft('JV')
        self.assertEqual(Voucher.objects.count(), 2)

    def test_line_cannot_have_both_sides(self):
        voucher = self._draft()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VoucherLine.objects.create(
                    voucher=voucher, account_head=self.cash,
                    debit=Decimal('10'), credit=Decimal('10'),
                )
