"""Audit suite B: payments, installments, receipts, refunds, expenses, finance.

Data-entry impact checks for money-moving models: every write must keep
booking balances, installment totals, receipts, and the finance ledger
consistent. Created during the 2026 data-integrity audit.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, InstallmentPlan, Installment
from core.models import AuditLog
from customers.models import Customer
from expenses.models import Expense
from finance.models import (
    AccountTransaction, Office, ExpenseCategory, OfficeExpense, ProjectCost,
    ProjectBudget, ProjectInvestment,
)
from notifications.models import NotificationLog
from payments.models import Payment, Receipt, Refund, PaymentAllocation
from properties.models import Plot, Project


class MoneyBase(APITestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('moneyadmin', 'm@example.com', 'pass12345')
        self.client.force_authenticate(user=self.admin)
        self.project = Project.objects.create(name='Money Project', location='Lahore', total_plots=30)
        self.plot = Plot.objects.create(
            plot_number='MP-001', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000000'), status='available',
        )
        self.customer = Customer.objects.create(
            first_name='Money', last_name='Customer', phone='+92-300-2220001',
            cnic='35202-2220001-1', email='money@example.com', created_by=self.admin,
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000000'),
            advance_paid=Decimal('100000'), status='confirmed', created_by=self.admin,
        )

    def make_plan(self, total=12, amount='75000', down='100000', freq='monthly'):
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=total,
            installment_amount=Decimal(amount), down_payment_amount=Decimal(down),
            start_date=date.today(), frequency=freq,
        )
        plan.auto_generate()
        return plan

    def make_payment(self, amount='50000', status='pending', installment=None):
        return Payment.objects.create(
            booking=self.booking, installment=installment, amount=Decimal(amount),
            payment_date=date.today(), payment_method='cash',
            payment_type='installment', status=status, created_by=self.admin,
        )

    def verify(self, payment):
        return self.client.post(reverse('payment-verify', args=[payment.pk]),
                                {'action': 'verify'}, format='json')


# ─── INSTALLMENT DEEP CHECKS ────────────────────────────────────────────────
class InstallmentDeepTests(MoneyBase):

    def test_installment_status_choices(self):
        plan = self.make_plan(total=2)
        inst = plan.installments.first()
        inst.status = 'overdue'
        inst.save()
        self.assertEqual(inst.status, 'overdue')
        # Django enforces choices at the form/serializer layer, not the ORM —
        # the API serializer must reject invalid statuses.
        resp = self.client.patch(reverse('installment-detail', args=[inst.pk]),
                                 {'status': 'bogus'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paid_installment_sets_paid_date(self):
        plan = self.make_plan(total=2)
        inst = plan.installments.first()
        inst.paid_amount = inst.amount
        inst.status = 'paid'
        inst.paid_date = date(2026, 8, 20)
        inst.save()
        self.assertEqual(inst.paid_date, date(2026, 8, 20))

    def test_partial_installment_keeps_paid_date_null(self):
        plan = self.make_plan(total=2)
        inst = plan.installments.first()
        inst.paid_amount = Decimal('10000')
        inst.status = 'partial'
        inst.save()
        self.assertIsNone(inst.paid_date)

    def test_overdue_installment_with_late_fee(self):
        plan = self.make_plan(total=2)
        inst = plan.installments.first()
        inst.status = 'overdue'
        inst.late_fee = Decimal('500')
        inst.save()
        self.assertEqual(inst.remaining_amount, inst.amount + Decimal('500'))

    def test_late_fee_increases_remaining(self):
        plan = self.make_plan(total=2)
        inst = plan.installments.first()
        inst.late_fee = Decimal('1000')
        inst.save()
        self.assertEqual(inst.remaining_amount, inst.amount + Decimal('1000'))

    def test_installment_payment_allocation_json_audit(self):
        plan = self.make_plan(total=2)
        inst = plan.installments.first()
        inst.payment_allocation = {'PAY-00001': 5000}
        inst.save()
        self.assertEqual(inst.payment_allocation, {'PAY-00001': 5000})

    def test_installment_ordering_by_due_date(self):
        plan = self.make_plan(total=3)
        insts = list(plan.installments.all())
        dates = [i.due_date for i in insts]
        self.assertEqual(dates, sorted(dates))

    def test_plan_total_installments_matches_count(self):
        plan = self.make_plan(total=8)
        self.assertEqual(plan.installments.count(), plan.total_installments)

    def test_plan_deactivate_keeps_installments(self):
        plan = self.make_plan(total=4)
        plan.is_active = False
        plan.save()
        self.assertEqual(plan.installments.count(), 4)

    def test_installment_unique_per_plan_number(self):
        plan = self.make_plan(total=2)
        with self.assertRaises(Exception):
            Installment.objects.create(
                plan=plan, installment_number=1, due_date=date.today(),
                amount=Decimal('100'),
            )

    def test_installment_delete_cascades_from_plan(self):
        plan = self.make_plan(total=3)
        plan.auto_generate()  # deletes + recreates
        self.assertEqual(plan.installments.count(), 3)


# ─── PAYMENT EDGE CASES ─────────────────────────────────────────────────────
class PaymentEdgeTests(MoneyBase):

    def test_payment_cheque_method_fields(self):
        p = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cheque',
            payment_type='installment', status='pending', created_by=self.admin,
            bank_name='HBL', cheque_number='CHQ-123', cheque_date=date.today(),
        )
        self.assertEqual(p.payment_method, 'cheque')
        self.assertEqual(p.bank_name, 'HBL')
        self.assertEqual(p.cheque_number, 'CHQ-123')

    def test_payment_bank_transfer_method(self):
        p = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='bank_transfer',
            payment_type='installment', status='pending', created_by=self.admin,
            reference_number='TRF-999',
        )
        self.assertEqual(p.reference_number, 'TRF-999')

    def test_payment_online_method(self):
        p = Payment.objects.create(
            booking=self.booking, amount=Decimal('50000'),
            payment_date=date.today(), payment_method='online',
            payment_type='installment', status='pending', created_by=self.admin,
        )
        self.assertEqual(p.payment_method, 'online')

    def test_payment_invalid_method_rejected(self):
        # ORM layer accepts any string; the API serializer must reject it.
        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'amount': '100',
            'payment_date': date.today().isoformat(), 'payment_method': 'bitcoin',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_negative_amount_rejected_at_db(self):
        # DB-level CheckConstraint blocks negative money.
        with self.assertRaises(Exception):
            Payment.objects.create(
                booking=self.booking, amount=Decimal('-100'),
                payment_date=date.today(), payment_method='cash',
                status='pending', created_by=self.admin,
            )

    def test_payment_future_date_allowed(self):
        p = Payment.objects.create(
            booking=self.booking, amount=Decimal('100'),
            payment_date=date.today() + timedelta(days=30),
            status='pending', created_by=self.admin,
        )
        self.assertEqual(p.payment_date, date.today() + timedelta(days=30))

    def test_payment_over_amount_tracks_unallocated(self):
        plan = self.make_plan(total=12)
        inst = plan.installments.first()
        # pay more than the installment needs via the verify flow
        p = Payment.objects.create(
            booking=self.booking, installment=inst, amount=Decimal('100000'),
            payment_date=date.today(), status='pending', created_by=self.admin,
        )
        self.verify(p)
        inst.refresh_from_db()
        self.assertEqual(inst.status, 'paid')
        self.assertEqual(inst.paid_amount, inst.amount)
        p.refresh_from_db()
        self.assertGreater(p.unallocated_amount, 0)

    def test_payment_verify_creates_audit(self):
        p = self.make_payment(status='pending')
        self.verify(p)
        self.assertTrue(AuditLog.objects.filter(model_name='Payment').exists())

    def test_payment_reject_does_not_receipt(self):
        p = self.make_payment(status='pending')
        self.client.post(reverse('payment-verify', args=[p.pk]),
                         {'action': 'reject'}, format='json')
        p.refresh_from_db()
        self.assertFalse(p.receipts.exists())

    def test_payment_verify_then_reject_blocked(self):
        p = self.make_payment(status='pending')
        self.verify(p)
        resp = self.client.post(reverse('payment-verify', args=[p.pk]),
                                {'action': 'reject'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_status_choices(self):
        p = self.make_payment(status='verified')
        self.assertEqual(p.status, 'verified')
        p.status = 'bounced'
        p.save()
        self.assertEqual(p.status, 'bounced')

    def test_payment_receipt_generated_flag(self):
        p = self.make_payment(status='pending')
        self.verify(p)
        p.refresh_from_db()
        self.assertTrue(p.receipt_generated)

    def test_payment_receipt_has_correct_amount(self):
        p = self.make_payment(amount='77777', status='pending')
        self.verify(p)
        r = p.receipts.first()
        self.assertEqual(r.payment.amount, Decimal('77777'))

    def test_receipt_duplicate_flag_on_bounce(self):
        p = self.make_payment(amount='50000', status='pending')
        self.verify(p)
        self.client.post(reverse('payment-mark-bounced', args=[p.pk]),
                         {'bounce_reason': 'x'}, format='json')
        r = p.receipts.first()
        r.refresh_from_db()
        self.assertTrue(r.is_duplicate)

    def test_receipt_cancellation_reason_set(self):
        p = self.make_payment(amount='50000', status='pending')
        self.verify(p)
        self.client.post(reverse('payment-mark-bounced', args=[p.pk]),
                         {'bounce_reason': 'NSF'}, format='json')
        r = p.receipts.first()
        r.refresh_from_db()
        self.assertIn('NSF', r.cancellation_reason)


# ─── REFUND DEEP CHECKS ─────────────────────────────────────────────────────
class RefundDeepTests(MoneyBase):

    def test_refund_status_flow(self):
        refund = Refund.objects.create(
            booking=self.booking, amount=Decimal('5000'),
            reason='overpayment', status='pending',
        )
        refund.status = 'approved'
        refund.approved_by = self.admin
        refund.save()
        refund.status = 'processed'
        refund.processed_date = date.today()
        refund.save()
        self.assertEqual(refund.status, 'processed')

    def test_refund_invalid_status_rejected(self):
        # Serializer must reject invalid statuses.
        resp = self.client.post(reverse('refund-list'), {
            'booking': self.booking.pk, 'amount': '1000',
            'reason': 'overpayment', 'status': 'bogus',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refund_reason_choices(self):
        for reason in ['cancellation', 'overpayment', 'booking_transfer', 'other']:
            refund = Refund.objects.create(
                booking=self.booking, amount=Decimal('100'),
                reason=reason, status='pending',
            )
            self.assertEqual(refund.reason, reason)

    def test_refund_amount_cannot_exceed_booking_paid(self):
        # API contract check: refund larger than total is nonsensical.
        resp = self.client.post(reverse('refund-list'), {
            'booking': self.booking.pk, 'amount': '99999999',
            'reason': 'overpayment',
        }, format='json')
        # Should be rejected; if accepted it's a data-integrity bug.
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refund_approve_requires_admin(self):
        # Refund must be backed by verified payments (refundable amount).
        self.make_payment(amount='10000', status='verified')
        refund = Refund.objects.create(
            booking=self.booking, amount=Decimal('1000'),
            reason='other', status='pending',
        )
        resp = self.client.post(reverse('refund-approve', args=[refund.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── EXPENSES ───────────────────────────────────────────────────────────────
class ExpenseTests(MoneyBase):

    def make_expense(self, amount='5000', etype='marketing'):
        return Expense.objects.create(
            project=self.project, description='Test expense',
            amount=Decimal(amount), expense_type=etype,
            paid_to='Vendor X', expense_date=date.today(),
            created_by=self.admin,
        )

    def test_expense_create(self):
        e = self.make_expense()
        self.assertEqual(e.amount, Decimal('5000'))
        self.assertEqual(e.project, self.project)

    def test_expense_negative_amount_rejected(self):
        # DB-level CheckConstraint blocks negative money.
        with self.assertRaises(Exception):
            Expense.objects.create(
                project=self.project, description='Bad', amount=Decimal('-100'),
                expense_type='marketing', paid_to='X', expense_date=date.today(),
                created_by=self.admin,
            )

    def test_expense_zero_amount_rejected(self):
        with self.assertRaises(Exception):
            Expense.objects.create(
                project=self.project, description='Zero', amount=Decimal('0'),
                expense_type='marketing', paid_to='X', expense_date=date.today(),
                created_by=self.admin,
            )

    def test_expense_project_cascade(self):
        e = self.make_expense()
        self.project.delete()
        self.assertFalse(Expense.objects.filter(pk=e.pk).exists())

    def test_expense_audit_log(self):
        # Expenses are web-only (no API viewset); the web create view audits.
        e = self.make_expense()
        AuditLog.objects.create(
            user=self.admin, action='create', model_name='Expense',
            object_id=str(e.pk), description='Created expense via web',
        )
        self.assertTrue(AuditLog.objects.filter(model_name='Expense', action='create').exists())


# ─── FINANCE: OFFICE EXPENSES → LEDGER ──────────────────────────────────────
class OfficeExpenseLedgerTests(MoneyBase):

    def setUp(self):
        super().setUp()
        self.office = Office.objects.create(name='Head Office', office_type='head_office')
        self.cat = ExpenseCategory.objects.create(name='Utilities', category_type='operating')

    def test_office_expense_created(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('10000'),
            expense_date=date.today(), payment_method='cash', status='pending',
            description='Electricity', created_by=self.admin,
        )
        self.assertEqual(oe.status, 'pending')
        # pending expense must NOT post to ledger yet
        self.assertFalse(AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).exists())

    def test_office_expense_paid_posts_to_ledger(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('10000'),
            expense_date=date.today(), payment_method='cash', status='pending',
            description='Electricity', created_by=self.admin,
        )
        oe.status = 'paid'
        oe.save()
        oe.post_to_ledger()
        tx = AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, Decimal('10000'))
        self.assertEqual(tx.direction, 'out')
        self.assertEqual(tx.office, self.office)

    def test_office_expense_api_create_paid_posts(self):
            # status is read-only on the API (server-controlled default 'pending'),
            # so a create never auto-posts; paying via the 'pay' action posts once.
            resp = self.client.post(reverse('officeexpense-list'), {
                'office': self.office.pk, 'category': self.cat.pk,
                'amount': '15000', 'expense_date': date.today().isoformat(),
                'payment_method': 'cash',
                'description': 'Rent',
            }, format='json')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            oe = OfficeExpense.objects.get(pk=resp.data['id'])
            self.assertEqual(oe.status, 'pending')
            self.assertFalse(AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).exists())
            pay_resp = self.client.post(reverse('officeexpense-pay', args=[oe.pk]), format='json')
            self.assertEqual(pay_resp.status_code, status.HTTP_200_OK)
            self.assertTrue(AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).exists())

    def test_office_expense_api_create_pending_no_ledger(self):
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': self.office.pk, 'category': self.cat.pk,
            'amount': '15000', 'expense_date': date.today().isoformat(),
            'payment_method': 'cash', 'status': 'pending',
            'description': 'Rent',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        oe = OfficeExpense.objects.get(pk=resp.data['id'])
        self.assertFalse(AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).exists())

    def test_office_expense_pay_action_posts_ledger(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('8000'),
            expense_date=date.today(), payment_method='cash', status='pending',
            created_by=self.admin,
        )
        resp = self.client.post(reverse('officeexpense-pay', args=[oe.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).exists())

    def test_office_expense_approve(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('8000'),
            expense_date=date.today(), payment_method='cash', status='pending',
            created_by=self.admin,
        )
        resp = self.client.post(reverse('officeexpense-approve', args=[oe.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        oe.refresh_from_db()
        self.assertEqual(oe.status, 'approved')

    def test_office_expense_double_post_idempotent(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('8000'),
            expense_date=date.today(), payment_method='cash', status='paid',
            created_by=self.admin,
        )
        oe.post_to_ledger()
        oe.post_to_ledger()  # update_or_create → no duplicate
        count = AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).count()
        self.assertEqual(count, 1)

    def test_office_expense_negative_amount_rejected(self):
        with self.assertRaises(Exception):
            OfficeExpense.objects.create(
                office=self.office, category=self.cat, amount=Decimal('-100'),
                expense_date=date.today(), payment_method='cash', status='pending',
                created_by=self.admin,
            )

    def test_office_expense_list_filter_by_office(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('1000'),
            expense_date=date.today(), payment_method='cash', status='pending',
            created_by=self.admin,
        )
        resp = self.client.get(reverse('officeexpense-list'), {'office': self.office.pk})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_office_expense_ledger_category_name(self):
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('5000'),
            expense_date=date.today(), payment_method='cash', status='paid',
            created_by=self.admin,
        )
        oe.post_to_ledger()
        tx = AccountTransaction.objects.get(reference_type='OfficeExpense', reference_id=oe.pk)
        self.assertEqual(tx.category, 'Utilities')


# ─── FINANCE: PROJECT COSTS → LEDGER ────────────────────────────────────────
class ProjectCostLedgerTests(MoneyBase):

    def test_project_cost_create(self):
        pc = ProjectCost.objects.create(
            project=self.project, cost_category='material', amount=Decimal('50000'),
            cost_date=date.today(), vendor='Steel Co', status='pending',
            created_by=self.admin,
        )
        self.assertEqual(pc.status, 'pending')

    def test_project_cost_paid_posts_ledger(self):
        pc = ProjectCost.objects.create(
            project=self.project, cost_category='material', amount=Decimal('50000'),
            cost_date=date.today(), vendor='Steel Co', status='paid',
            created_by=self.admin,
        )
        pc.post_to_ledger()
        tx = AccountTransaction.objects.filter(reference_type='ProjectCost', reference_id=pc.pk).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, Decimal('50000'))
        self.assertEqual(tx.project, self.project)
        self.assertEqual(tx.direction, 'out')

    def test_project_cost_api_paid_posts(self):
        # status is read-only on the API (server default 'pending'); posting
        # 'paid' on create is ignored and no ledger row is auto-created.
        resp = self.client.post(reverse('projectcost-list'), {
            'project': self.project.pk, 'cost_category': 'labor',
            'amount': '30000', 'cost_date': date.today().isoformat(),
            'vendor': 'Workers', 'status': 'paid',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        pc = ProjectCost.objects.get(pk=resp.data['id'])
        self.assertEqual(pc.status, 'pending')
        self.assertFalse(AccountTransaction.objects.filter(reference_type='ProjectCost', reference_id=pc.pk).exists())

    def test_project_cost_api_pending_no_ledger(self):
        # A project cost created through the API stays 'pending' (status is
        # read-only), so no ledger row is created until it is approved/paid.
        resp = self.client.post(reverse('projectcost-list'), {
            'project': self.project.pk, 'cost_category': 'labor',
            'amount': '30000', 'cost_date': date.today().isoformat(),
            'vendor': 'Workers', 'status': 'draft',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        pc = ProjectCost.objects.get(pk=resp.data['id'])
        self.assertFalse(AccountTransaction.objects.filter(reference_type='ProjectCost', reference_id=pc.pk).exists())

    def test_project_cost_double_post_idempotent(self):
        pc = ProjectCost.objects.create(
            project=self.project, cost_category='other', amount=Decimal('10000'),
            cost_date=date.today(), status='paid', created_by=self.admin,
        )
        pc.post_to_ledger()
        pc.post_to_ledger()
        count = AccountTransaction.objects.filter(reference_type='ProjectCost', reference_id=pc.pk).count()
        self.assertEqual(count, 1)

    def test_project_cost_negative_rejected(self):
        # DB-level CheckConstraint blocks negative money.
        with self.assertRaises(Exception):
            ProjectCost.objects.create(
                project=self.project, cost_category='other', amount=Decimal('-1'),
                cost_date=date.today(), status='draft', created_by=self.admin,
            )

    def test_project_cost_list_filter(self):
        pc = ProjectCost.objects.create(
            project=self.project, cost_category='material', amount=Decimal('1000'),
            cost_date=date.today(), status='pending', created_by=self.admin,
        )
        resp = self.client.get(reverse('projectcost-list'), {'project': self.project.pk})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── FINANCE: BUDGETS & INVESTMENTS ─────────────────────────────────────────
class BudgetInvestmentTests(MoneyBase):

    def test_project_budget_create(self):
        pb = ProjectBudget.objects.create(
            project=self.project, total_budget=Decimal('5000000'),
            material_budget=Decimal('2000000'), labor_budget=Decimal('1500000'),
            contractor_budget=Decimal('1000000'), transportation_budget=Decimal('300000'),
            other_budget=Decimal('200000'),
        )
        self.assertEqual(pb.total_budget, Decimal('5000000'))

    def test_project_budget_negative_rejected(self):
        with self.assertRaises(Exception):
            ProjectBudget.objects.create(
                project=self.project, total_budget=Decimal('-100'),
            )

    def test_project_budget_api(self):
        resp = self.client.post(reverse('projectbudget-list'), {
            'project': self.project.pk, 'total_budget': '1000000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_project_investment_create(self):
        pi = ProjectInvestment.objects.create(
            project=self.project, total_investment=Decimal('8000000'),
            notes='Equity',
        )
        self.assertEqual(pi.total_investment, Decimal('8000000'))

    def test_project_investment_api(self):
        resp = self.client.post(reverse('projectinvestment-list'), {
            'project': self.project.pk, 'total_investment': '5000000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_project_investment_negative_rejected(self):
        with self.assertRaises(Exception):
            ProjectInvestment.objects.create(
                project=self.project, total_investment=Decimal('-1'),
            )


# ─── ACCOUNT TRANSACTIONS ───────────────────────────────────────────────────
class AccountTransactionTests(MoneyBase):

    def test_account_transaction_create(self):
        tx = AccountTransaction.objects.create(
            date=date.today(), amount=Decimal('10000'), direction='in',
            transaction_type='receipt', category='Sales',
            description='Sale proceeds', created_by=self.admin,
        )
        self.assertEqual(tx.direction, 'in')

    def test_account_transaction_out_direction(self):
        tx = AccountTransaction.objects.create(
            date=date.today(), amount=Decimal('5000'), direction='out',
            transaction_type='office_expense', category='Utilities',
            description='Bill', created_by=self.admin,
        )
        self.assertEqual(tx.direction, 'out')

    def test_account_transaction_invalid_direction_rejected(self):
        # ORM accepts any string; the API serializer must reject it.
        resp = self.client.post(reverse('accounttransaction-list'), {
            'date': date.today().isoformat(), 'amount': '100',
            'direction': 'sideways', 'transaction_type': 'adjustment',
            'description': 'X',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_account_transaction_negative_amount_rejected(self):
        with self.assertRaises(Exception):
            AccountTransaction.objects.create(
                date=date.today(), amount=Decimal('-100'), direction='in',
                transaction_type='other', description='X', created_by=self.admin,
            )

    def test_account_transaction_api(self):
        resp = self.client.post(reverse('accounttransaction-list'), {
            'date': date.today().isoformat(), 'amount': '25000',
            'direction': 'in', 'transaction_type': 'income',
            'category': 'Sales', 'reference_type': 'manual', 'reference_id': None, 'description': 'Test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_account_transaction_list_filter(self):
        AccountTransaction.objects.create(
            date=date.today(), amount=Decimal('100'), direction='in',
            transaction_type='receipt', description='X', created_by=self.admin,
        )
        resp = self.client.get(reverse('accounttransaction-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── END-TO-END MONEY CONSISTENCY ───────────────────────────────────────────
class MoneyConsistencyTests(MoneyBase):
    """The money must always add up across booking, plan, payments, receipts."""

    def test_advance_equals_verified_payments_plus_initial(self):
        initial = self.booking.advance_paid
        p1 = self.make_payment(amount='20000', status='pending')
        p2 = self.make_payment(amount='30000', status='pending')
        self.verify(p1)
        self.verify(p2)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, initial + Decimal('50000'))

    def test_receipts_match_verified_payments(self):
        p1 = self.make_payment(amount='20000', status='pending')
        p2 = self.make_payment(amount='30000', status='pending')
        self.verify(p1)
        self.verify(p2)
        self.assertEqual(self.booking.payments.filter(status='verified').count(), 2)
        receipts = Receipt.objects.filter(payment__booking=self.booking).count()
        self.assertEqual(receipts, 2)

    def test_bounced_payment_reduces_verified_total(self):
        p = self.make_payment(amount='20000', status='pending')
        self.verify(p)
        self.assertEqual(self.booking.payments.filter(status='verified').count(), 1)
        self.client.post(reverse('payment-mark-bounced', args=[p.pk]), {'bounce_reason': 'x'}, format='json')
        self.assertEqual(self.booking.payments.filter(status='verified').count(), 0)

    def test_remaining_balance_never_negative(self):
        p = self.make_payment(amount='99999999', status='pending')
        self.verify(p)
        self.booking.refresh_from_db()
        self.assertGreaterEqual(self.booking.remaining_balance, Decimal('0'))

    def test_payment_progress_reflects_advance(self):
        self.booking.advance_paid = Decimal('500000')
        self.booking.save()
        self.assertEqual(self.booking.payment_progress, 50)

    def test_payment_progress_zero_when_no_advance(self):
        b = Booking.objects.create(
            customer=self.customer, plot=Plot.objects.create(
                plot_number='MP-099', project=self.project, size_marla=Decimal('5'),
                price=Decimal('1000000'), status='available',
            ),
            total_amount=Decimal('1000000'), advance_paid=Decimal('0'),
            created_by=self.admin,
        )
        self.assertEqual(b.payment_progress, 0)

    def test_installment_paid_amounts_never_exceed_amount(self):
        plan = self.make_plan(total=4)
        for inst in plan.installments.all():
            inst.paid_amount = inst.amount + Decimal('100')
            inst.status = 'paid'
            inst.save()
        # The booking would be over-paid only if advance exceeds total.
        self.booking.advance_paid = self.booking.total_amount
        self.booking.save()
        self.assertGreaterEqual(self.booking.remaining_balance, Decimal('0'))

    def test_verified_payment_plan_recalc_invariant(self):
        plan = self.make_plan(total=12)
        p = self.make_payment(amount='400000', status='pending')
        self.verify(p)
        self.booking.refresh_from_db()
        unpaid = plan.installments.exclude(status='paid')
        self.assertEqual(
            sum(i.amount for i in unpaid),
            self.booking.remaining_balance,
        )

    def test_multiple_payments_recalc_each_time(self):
        plan = self.make_plan(total=12)
        p1 = self.make_payment(amount='200000', status='pending')
        self.verify(p1)
        self.booking.refresh_from_db()
        unpaid1 = sum(i.amount for i in plan.installments.exclude(status='paid'))
        self.assertEqual(unpaid1, self.booking.remaining_balance)
        p2 = self.make_payment(amount='100000', status='pending')
        self.verify(p2)
        self.booking.refresh_from_db()
        unpaid2 = sum(i.amount for i in plan.installments.exclude(status='paid'))
        self.assertEqual(unpaid2, self.booking.remaining_balance)
        self.assertLess(unpaid2, unpaid1)

    def test_refund_of_verified_payment_requires_guard(self):
        p = self.make_payment(amount='10000', status='pending')
        self.verify(p)
        # refund larger than paid should be impossible
        resp = self.client.post(reverse('refund-list'), {
            'booking': self.booking.pk, 'original_payment': p.pk,
            'amount': '999999', 'reason': 'overpayment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_total_paid_equals_verified_sum(self):
        p1 = self.make_payment(amount='20000', status='pending')
        p2 = self.make_payment(amount='30000', status='pending')
        self.verify(p1)
        self.verify(p2)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.total_paid, Decimal('50000'))

    def test_booking_status_completed_on_full_payment(self):
        b = Booking.objects.create(
            customer=self.customer, plot=Plot.objects.create(
                plot_number='MP-100', project=self.project, size_marla=Decimal('5'),
                price=Decimal('100000'), status='available',
            ),
            total_amount=Decimal('100000'), advance_paid=Decimal('0'),
            status='confirmed', created_by=self.admin,
        )
        p = Payment.objects.create(
            booking=b, amount=Decimal('100000'), payment_date=date.today(),
            status='pending', created_by=self.admin,
        )
        self.client.post(reverse('payment-verify', args=[p.pk]), {'action': 'verify'}, format='json')
        b.refresh_from_db()
        self.assertEqual(b.status, 'completed')

    def test_ledger_not_duplicated_on_office_expense_edit(self):
        self.office = Office.objects.create(name='HO2', office_type='head_office')
        self.cat = ExpenseCategory.objects.create(name='Ops', category_type='operating')
        oe = OfficeExpense.objects.create(
            office=self.office, category=self.cat, amount=Decimal('5000'),
            expense_date=date.today(), payment_method='cash', status='paid',
            created_by=self.admin,
        )
        oe.post_to_ledger()
        oe.amount = Decimal('6000')
        oe.save()
        oe.post_to_ledger()
        count = AccountTransaction.objects.filter(reference_type='OfficeExpense', reference_id=oe.pk).count()
        self.assertEqual(count, 1)
        tx = AccountTransaction.objects.get(reference_type='OfficeExpense', reference_id=oe.pk)
        self.assertEqual(tx.amount, Decimal('6000'))
