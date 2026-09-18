"""Closeout writer tests: Refund / Expense / SalaryPayment → auto-vouchers, plus
the hard line/lock guards (spec §3.15–§3.18)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from expenses.models import Expense
from hr.models import (
    Department, Employee, EmployeeSalary, PayrollRun, SalaryComponent, SalarySlip,
    SalarySlipItem, SalaryPayment,
)
from payments.models import Payment, Refund
from properties.models import Plot, Project

from .models import AccountHead, AccountTransaction, Voucher, VoucherLine


class CloseoutWriterTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('close', 'c@example.com', 'pass12345')
        self.project = Project.objects.create(name='P1', location='Lahore')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan', phone='+92-300-9999999',
            cnic='35202-9999999-1', created_by=self.user,
        )
        self.plot = Plot.objects.create(
            plot_number='A-1', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user,
        )

    def _voucher(self, reference_type, reference_id):
        return Voucher.objects.get(reference_type=reference_type, reference_id=reference_id)

    def _assert_balanced(self, voucher):
        lines = list(voucher.lines.all())
        self.assertEqual(
            sum((l.debit for l in lines), Decimal('0.00')),
            sum((l.credit for l in lines), Decimal('0.00')),
        )

    # ── Refund → independent payment voucher ─────────────────────────────
    def test_refund_posts_independent_payment_voucher(self):
        refund = Refund.objects.create(
            booking=self.booking, amount=Decimal('5000'), reason='overpayment',
            refund_method='cash', status='approved',
        )
        refund.process(self.user)
        voucher = self._voucher('Refund', refund.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self._assert_balanced(voucher)

        ar = AccountHead.objects.get(code='1100')
        cash = AccountHead.objects.get(code='1000')
        self.assertTrue(any(
            l.account_head_id == ar.pk and l.debit == Decimal('5000')
            for l in voucher.lines.all()))
        self.assertTrue(any(
            l.account_head_id == cash.pk and l.credit == Decimal('5000')
            for l in voucher.lines.all()))
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='Refund', reference_id=refund.pk).exists())

    def test_refund_bank_method_uses_bank_head(self):
        refund = Refund.objects.create(
            booking=self.booking, amount=Decimal('7000'), reason='overpayment',
            refund_method='bank_transfer', status='approved',
        )
        refund.process(self.user)
        voucher = self._voucher('Refund', refund.pk)
        self.assertEqual(voucher.voucher_type, 'BP')
        bank = AccountHead.objects.get(code='1010')
        self.assertTrue(any(
            l.account_head_id == bank.pk and l.credit == Decimal('7000')
            for l in voucher.lines.all()))

    def test_refund_does_not_touch_original_receipt_voucher(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'), payment_date=date.today(),
            payment_method='cash', created_by=self.user,
        )
        receipt = self._voucher('Payment', payment.pk)
        receipt_number = receipt.voucher_number
        receipt_line_ids = list(receipt.lines.values_list('id', flat=True))

        refund = Refund.objects.create(
            booking=self.booking, amount=Decimal('5000'), reason='overpayment',
            refund_method='cash', status='approved',
        )
        refund.process(self.user)

        receipt.refresh_from_db()
        self.assertEqual(receipt.voucher_number, receipt_number)
        self.assertEqual(list(receipt.lines.values_list('id', flat=True)), receipt_line_ids)

    def test_refund_post_is_idempotent(self):
        refund = Refund.objects.create(
            booking=self.booking, amount=Decimal('5000'), reason='overpayment',
            refund_method='cash', status='approved',
        )
        refund.post_to_ledger()
        refund.post_to_ledger()
        self.assertEqual(
            Voucher.objects.filter(reference_type='Refund', reference_id=refund.pk).count(), 1)

    # ── Expense → payment voucher (default cash) ─────────────────────────
    def test_expense_posts_payment_voucher(self):
        expense = Expense.objects.create(
            project=self.project, description='Steel', amount=Decimal('12000'),
            expense_type='internal', expense_date=date.today(), status='paid',
            created_by=self.user,
        )
        expense.post_to_ledger(user=self.user)
        voucher = self._voucher('Expense', expense.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self._assert_balanced(voucher)

        cost_head = AccountHead.objects.get(code='5100')
        cash = AccountHead.objects.get(code='1000')
        self.assertTrue(any(
            l.account_head_id == cost_head.pk and l.debit == Decimal('12000')
            for l in voucher.lines.all()))
        self.assertTrue(any(
            l.account_head_id == cash.pk and l.credit == Decimal('12000')
            for l in voucher.lines.all()))
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='Expense', reference_id=expense.pk).exists())
        self.assertTrue(expense.is_posted_to_ledger())

    def test_expense_post_is_idempotent(self):
        expense = Expense.objects.create(
            project=self.project, description='Steel', amount=Decimal('12000'),
            expense_type='internal', expense_date=date.today(), status='paid',
            created_by=self.user,
        )
        expense.post_to_ledger()
        expense.post_to_ledger()
        self.assertEqual(
            Voucher.objects.filter(reference_type='Expense', reference_id=expense.pk).count(), 1)

    # ── SalaryPayment → payment voucher (method resolved) ────────────────
    def _salary_payment(self, method):
        dept = Department.objects.create(name=f'Eng-{method}')
        basic = SalaryComponent.objects.create(name=f'Basic-{method}', component_type='earning')
        emp = Employee.objects.create(
            first_name='Ali', last_name='Khan', department=dept, joining_date=date.today())
        EmployeeSalary.objects.create(employee=emp, component=basic, amount=Decimal('50000'))
        run = PayrollRun.objects.create(month=1, year=2026)
        slip = SalarySlip.objects.create(employee=emp, run=run)
        SalarySlipItem.objects.create(slip=slip, component=basic, amount=Decimal('50000'))
        slip.recalculate()
        return SalaryPayment.objects.create(
            slip=slip, amount=slip.net, payment_date=date.today(), method=method,
            created_by=self.user,
        )

    def test_salary_payment_posts_salaries_voucher(self):
        payment = self._salary_payment('cash')
        payment.post_to_ledger()
        voucher = self._voucher('SalaryPayment', payment.pk)
        self.assertEqual(voucher.voucher_type, 'CP')
        self._assert_balanced(voucher)

        salaries = AccountHead.objects.get(code='5200')
        self.assertEqual(salaries.name, 'Salaries')
        self.assertTrue(salaries.is_leaf)
        cash = AccountHead.objects.get(code='1000')
        self.assertTrue(any(
            l.account_head_id == salaries.pk and l.debit == Decimal('50000')
            for l in voucher.lines.all()))
        self.assertTrue(any(
            l.account_head_id == cash.pk and l.credit == Decimal('50000')
            for l in voucher.lines.all()))
        self.assertFalse(AccountTransaction.objects.filter(
            reference_type='SalaryPayment', reference_id=payment.pk).exists())

    def test_salary_payment_bank_method_uses_bank_head(self):
        payment = self._salary_payment('bank_transfer')
        payment.post_to_ledger()
        voucher = self._voucher('SalaryPayment', payment.pk)
        self.assertEqual(voucher.voucher_type, 'BP')
        bank = AccountHead.objects.get(code='1010')
        self.assertTrue(any(
            l.account_head_id == bank.pk and l.credit == Decimal('50000')
            for l in voucher.lines.all()))


class HardGuardTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('guard', 'g@example.com', 'pass12345')
        self.cash = AccountHead.objects.create(code='1000', name='Cash', nature='debit')
        self.capital = AccountHead.objects.create(code='3000', name='Capital', nature='credit')
        self.voucher = Voucher.objects.create(
            voucher_type='JV', date=date.today(), created_by=self.user)
        VoucherLine.objects.create(voucher=self.voucher, account_head=self.cash, debit=Decimal('100'))
        VoucherLine.objects.create(voucher=self.voucher, account_head=self.capital, credit=Decimal('100'))

    def test_locked_voucher_save_guard(self):
        self.voucher.post(self.user)
        self.voucher.narration = 'tampered'
        with self.assertRaises(ValidationError):
            self.voucher.save()

    def test_locked_line_create_guard(self):
        self.voucher.post(self.user)
        with self.assertRaises(ValidationError):
            VoucherLine.objects.create(
                voucher=self.voucher, account_head=self.cash, debit=Decimal('1'))

    def test_locked_line_delete_guard(self):
        self.voucher.post(self.user)
        line = self.voucher.lines.first()
        with self.assertRaises(ValidationError):
            line.delete()

    def test_draft_save_and_post_still_work(self):
        self.voucher.narration = 'draft edit'
        self.voucher.save()
        self.voucher.post(self.user)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.status, 'posted')

    def test_unlocked_posted_voucher_can_be_edited_and_reposted(self):
        self.voucher.post(self.user)
        self.voucher.unlock(self.user, reason='fix')
        self.voucher.narration = 'corrected'
        self.voucher.save()
        self.voucher.post(self.user)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.narration, 'corrected')
        self.assertTrue(self.voucher.is_locked)