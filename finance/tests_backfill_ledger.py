"""Backfill command: post missing ledger vouchers for paid expenses/costs that
predate the double-entry writers (spec §3.7/§3.9)."""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from properties.models import Project

from .models import Office, OfficeExpense, ProjectCost, Voucher


class BackfillLedgerVouchersTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('bf', 'bf@example.com', 'pass12345')
        self.office = Office.objects.create(name='HO', office_type='head_office')
        self.project = Project.objects.create(name='P1', location='Lahore')

    def _legacy_expense(self, amount, status):
        """A paid expense with NO voucher — simulate by creating then nulling
        the reference, which is what pre-writer data looks like."""
        expense = OfficeExpense.objects.create(
            office=self.office, amount=amount, status='pending',
            expense_date='2026-01-05', created_by=self.user,
        )
        OfficeExpense.objects.filter(pk=expense.pk).update(status=status)
        return expense

    def _legacy_cost(self, amount, status):
        cost = ProjectCost.objects.create(
            project=self.project, amount=amount, status='pending',
            cost_date='2026-01-06', created_by=self.user,
        )
        ProjectCost.objects.filter(pk=cost.pk).update(status=status)
        return cost

    def test_backfill_posts_paid_office_expense(self):
        expense = self._legacy_expense(Decimal('25000.00'), 'paid')
        self.assertFalse(Voucher.objects.filter(
            reference_type='OfficeExpense', reference_id=expense.pk).exists())

        call_command('backfill_ledger_vouchers')

        voucher = Voucher.objects.get(
            reference_type='OfficeExpense', reference_id=expense.pk)
        self.assertEqual(voucher.status, 'posted')
        self.assertTrue(voucher.is_locked)
        # OfficeExpense default payment_method='bank_transfer' -> Bank Payment
        self.assertEqual(voucher.voucher_type, 'BP')
        dr = sum((l.debit for l in voucher.lines.all()), Decimal('0'))
        cr = sum((l.credit for l in voucher.lines.all()), Decimal('0'))
        self.assertEqual(dr, Decimal('25000.00'))
        self.assertEqual(dr, cr)

    def test_backfill_posts_paid_project_cost(self):
        cost = self._legacy_cost(Decimal('10000.00'), 'paid')
        call_command('backfill_ledger_vouchers')
        voucher = Voucher.objects.get(
            reference_type='ProjectCost', reference_id=cost.pk)
        self.assertEqual(voucher.status, 'posted')
        dr = sum((l.debit for l in voucher.lines.all()), Decimal('0'))
        self.assertEqual(dr, Decimal('10000.00'))

    def test_backfill_skips_unpaid_rows(self):
        pending = self._legacy_expense(Decimal('500.00'), 'pending')
        approved = self._legacy_expense(Decimal('600.00'), 'approved')
        call_command('backfill_ledger_vouchers')
        self.assertFalse(Voucher.objects.filter(
            reference_type='OfficeExpense', reference_id=pending.pk).exists())
        self.assertFalse(Voucher.objects.filter(
            reference_type='OfficeExpense', reference_id=approved.pk).exists())

    def test_backfill_is_idempotent(self):
        self._legacy_expense(Decimal('25000.00'), 'paid')
        self._legacy_cost(Decimal('10000.00'), 'paid')
        call_command('backfill_ledger_vouchers')
        after_first = Voucher.objects.count()
        call_command('backfill_ledger_vouchers')
        self.assertEqual(Voucher.objects.count(), after_first)

    def test_backfill_does_not_duplicate_already_posted(self):
        """A cost that already has a voucher must not get a second one."""
        cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('10000.00'), status='paid',
            cost_date='2026-01-06', created_by=self.user,
        )
        cost.post_to_ledger()
        self.assertEqual(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).count(), 1)
        call_command('backfill_ledger_vouchers')
        self.assertEqual(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).count(), 1)

    def test_dry_run_reports_without_writing(self):
        self._legacy_expense(Decimal('25000.00'), 'paid')
        out = StringIO()
        call_command('backfill_ledger_vouchers', '--dry-run', stdout=out)
        text = out.getvalue()
        self.assertIn('DRY RUN', text)
        self.assertIn('25000', text)
        self.assertEqual(Voucher.objects.count(), 0)

    def test_trial_balance_balances_after_backfill(self):
        self._legacy_expense(Decimal('25000.00'), 'paid')
        self._legacy_cost(Decimal('10000.00'), 'paid')
        call_command('backfill_ledger_vouchers')
        total = Decimal('0.00')
        for v in Voucher.objects.filter(status='posted'):
            dr = sum((l.debit for l in v.lines.all()), Decimal('0'))
            cr = sum((l.credit for l in v.lines.all()), Decimal('0'))
            self.assertEqual(dr, cr, f'{v.voucher_number} is unbalanced')
            total += dr
        self.assertEqual(total, Decimal('35000.00'))
