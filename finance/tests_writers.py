"""Writer-migration tests: Payment / OfficeExpense / ProjectCost → auto-vouchers.

TDD: these describe the target behavior for the double-entry writers. They are
expected to fail until the writers are implemented.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment
from properties.models import Plot, Project

from .models import (
    AccountHead, AccountTransaction, Office, ExpenseCategory, OfficeExpense,
    ProjectCost, Voucher, VoucherAuditLog,
)


class WriterMigrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('writer', 'w@example.com', 'pass12345')
        self.office = Office.objects.create(name='Head Office', office_type='head_office')
        self.category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        self.project = Project.objects.create(name='P1', location='Lahore')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan', phone='+92-300-1111111',
            cnic='35202-1111111-1', created_by=self.user,
        )
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user,
        )

    # ── helpers ──────────────────────────────────────────────────────────
    def _voucher_for(self, reference_type, reference_id):
        return Voucher.objects.get(reference_type=reference_type, reference_id=reference_id)

    def _assert_balanced(self, voucher):
        lines = list(voucher.lines.all())
        self.assertGreater(len(lines), 1)
        self.assertEqual(
            sum((line.debit for line in lines), Decimal('0.00')),
            sum((line.credit for line in lines), Decimal('0.00')),
        )

    # ── Payment → receipt voucher ────────────────────────────────────────
    def test_cash_payment_posts_cash_receipt_voucher(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'), payment_date=date.today(),
            payment_method='cash', created_by=self.user,
        )
        voucher = self._voucher_for('Payment', payment.pk)
        self.assertEqual(voucher.voucher_type, 'CR')
        self.assertEqual(voucher.status, 'posted')
        self.assertTrue(voucher.is_locked)
        self._assert_balanced(voucher)

        cash = AccountHead.objects.get(code='1000')
        self.assertTrue(any(
            line.account_head_id == cash.pk and line.debit == Decimal('100000')
            for line in voucher.lines.all()
        ))

    def test_bank_payment_posts_bank_receipt_voucher(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('250000'), payment_date=date.today(),
            payment_method='bank_transfer', created_by=self.user,
        )
        voucher = self._voucher_for('Payment', payment.pk)
        self.assertEqual(voucher.voucher_type, 'BR')
        self._assert_balanced(voucher)

        bank = AccountHead.objects.get(code='1010')
        self.assertTrue(any(
            line.account_head_id == bank.pk and line.debit == Decimal('250000')
            for line in voucher.lines.all()
        ))

    def test_payment_resave_does_not_duplicate_voucher(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'), payment_date=date.today(),
            payment_method='cash', created_by=self.user,
        )
        payment.amount = Decimal('120000')
        payment.save()
        self.assertEqual(
            Voucher.objects.filter(reference_type='Payment', reference_id=payment.pk).count(), 1,
        )

    def test_payment_save_does_not_touch_advance_paid(self):
        Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'), payment_date=date.today(),
            payment_method='cash', created_by=self.user,
        )
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, Decimal('0'))

    # ── OfficeExpense → payment voucher ──────────────────────────────────
    def test_office_expense_posts_voucher_not_account_transaction(self):
        expense = OfficeExpense.objects.create(
            office=self.office, category=self.category, amount=Decimal('25000'),
            expense_date=date.today(), payment_method='cash', status='paid',
            created_by=self.user,
        )
        expense.post_to_ledger()

        voucher = self._voucher_for('OfficeExpense', expense.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self._assert_balanced(voucher)
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='OfficeExpense', reference_id=expense.pk).exists())

        cash = AccountHead.objects.get(code='1000')
        self.assertTrue(any(
            line.account_head_id == cash.pk and line.credit == Decimal('25000')
            for line in voucher.lines.all()
        ))

    def test_office_expense_bank_method_uses_bank_head(self):
        expense = OfficeExpense.objects.create(
            office=self.office, category=self.category, amount=Decimal('25000'),
            expense_date=date.today(), payment_method='bank_transfer', status='paid',
            created_by=self.user,
        )
        expense.post_to_ledger()
        voucher = self._voucher_for('OfficeExpense', expense.pk)
        self.assertEqual(voucher.voucher_type, 'BP')
        bank = AccountHead.objects.get(code='1010')
        self.assertTrue(any(
            line.account_head_id == bank.pk and line.credit == Decimal('25000')
            for line in voucher.lines.all()
        ))

    def test_office_expense_post_is_idempotent(self):
        expense = OfficeExpense.objects.create(
            office=self.office, category=self.category, amount=Decimal('25000'),
            expense_date=date.today(), payment_method='cash', status='paid',
            created_by=self.user,
        )
        expense.post_to_ledger()
        expense.post_to_ledger()
        self.assertEqual(
            Voucher.objects.filter(reference_type='OfficeExpense', reference_id=expense.pk).count(), 1,
        )

    # ─ ProjectCost → payment voucher, Paid only ─────────────────────────
    def test_project_cost_posts_only_when_paid(self):
        cost = ProjectCost.objects.create(
            project=self.project, cost_category='material', amount=Decimal('40000'),
            cost_date=date.today(), status='draft', created_by=self.user,
        )
        cost.post_to_ledger()
        self.assertFalse(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).exists())

        cost.status = 'approved'
        cost.save()
        cost.post_to_ledger()
        self.assertFalse(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).exists())

        cost.status = 'paid'
        cost.save()
        cost.post_to_ledger()
        voucher = self._voucher_for('ProjectCost', cost.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self._assert_balanced(voucher)
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).exists())

    def test_project_cost_post_is_idempotent(self):
        cost = ProjectCost.objects.create(
            project=self.project, cost_category='material', amount=Decimal('40000'),
            cost_date=date.today(), status='paid', created_by=self.user,
        )
        cost.post_to_ledger()
        cost.post_to_ledger()
        self.assertEqual(
            Voucher.objects.filter(reference_type='ProjectCost', reference_id=cost.pk).count(), 1,
        )


class VoucherAuditLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('sup', 'sup@example.com', 'pass12345')
        self.cash = AccountHead.objects.create(code='1000', name='Cash', nature='debit')
        self.capital = AccountHead.objects.create(code='3000', name='Capital', nature='credit')
        self.voucher = Voucher.objects.create(
            voucher_type='JV', date=date.today(), created_by=self.user,
        )
        from .models import VoucherLine
        VoucherLine.objects.create(voucher=self.voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=self.voucher, account_head=self.capital, credit=Decimal('100'))

    def test_creation_is_logged(self):
        events = list(self.voucher.audit_logs.values_list('event', flat=True))
        self.assertIn('created', events)

    def test_post_is_logged(self):
        self.voucher.post(self.user)
        self.assertTrue(self.voucher.audit_logs.filter(event='posted').exists())

    def test_unlock_logs_reason_and_actor(self):
        self.voucher.post(self.user)
        self.voucher.unlock(self.user, reason='wrong head')
        row = self.voucher.audit_logs.get(event='unlocked')
        self.assertEqual(row.reason, 'wrong head')
        self.assertEqual(row.actor, self.user)

    def test_repost_is_logged_and_history_retained(self):
        self.voucher.post(self.user)
        self.voucher.unlock(self.user, reason='fix')
        self.voucher.post(self.user)
        events = list(self.voucher.audit_logs.values_list('event', flat=True))
        self.assertEqual(events.count('posted'), 1)
        self.assertEqual(events.count('unlocked'), 1)
        self.assertEqual(events.count('reposted'), 1)