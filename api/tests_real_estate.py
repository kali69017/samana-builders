"""Real-estate domain edge-case tests: installments, bookings, payments,
receipts, customers, plots, finance and HR invariants."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import (
    Booking, BookingTransfer, InstallmentPlan, InstallmentPlanTemplate, Installment,
    Reservation, CancellationPolicy, CancellationTier,
)
from core.models import UserProfile, Agent
from customers.models import Customer, CustomerNominee, CustomerLedgerEntry, format_cnic, format_phone
from finance.models import Office, ExpenseCategory, OfficeExpense, ProjectBudget, ProjectCost
from hr.models import Department, Employee, EmployeeSalary, PayrollRun, SalaryComponent, Attendance, Leave
from payments.models import Payment, Receipt, Refund, PaymentAllocation
from properties.models import Project, Plot, PriceHistory


def make_fixtures():
    user = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
    project = Project.objects.create(name='Real Estate', location='Lahore')
    plot = Plot.objects.create(plot_number='R-1', project=project, size_marla=Decimal('5'),
                               price=Decimal('5000000'), status='available')
    customer = Customer.objects.create(first_name='Test', last_name='Customer', phone='+92-300-1112222',
                                       cnic='35202-5555555-5', email='t@example.com', created_by=user)
    booking = Booking.objects.create(customer=customer, plot=plot, total_amount=Decimal('5000000'),
                                     advance_paid=Decimal('500000'), status='active', created_by=user)
    return user, project, plot, customer, booking


# ─── INSTALLMENTS ────────────────────────────────────────────────────────────
class InstallmentEdgeTests(TestCase):
    def setUp(self):
        self.user, self.project, self.plot, self.customer, self.booking = make_fixtures()
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=12, installment_amount=Decimal('375000'),
            down_payment_amount=Decimal('500000'), start_date=date(2026, 1, 15),
            frequency='monthly', due_day=15,
        )

    def test_auto_generate_creates_12(self):
        self.plan.auto_generate()
        self.assertEqual(self.plan.installments.count(), 12)

    def test_monthly_due_dates(self):
        self.plan.auto_generate()
        first = self.plan.installments.get(installment_number=1)
        self.assertEqual(first.due_date, date(2026, 2, 15))
        third = self.plan.installments.get(installment_number=3)
        self.assertEqual(third.due_date, date(2026, 4, 15))

    def _fresh_booking(self):
        plot = Plot.objects.create(plot_number=f'R-{Plot.objects.count() + 1}', project=self.project,
                                   size_marla=Decimal('5'), price=Decimal('3000000'))
        return Booking.objects.create(customer=self.customer, plot=plot, total_amount=Decimal('5000000'),
                                      advance_paid=Decimal('500000'), created_by=self.user)

    def test_due_day_clamped_to_28(self):
        plan = InstallmentPlan.objects.create(
            booking=self._fresh_booking(), total_installments=1, installment_amount=Decimal('375000'),
            down_payment_amount=Decimal('500000'), start_date=date(2026, 2, 1),
            frequency='monthly', due_day=31,
        )
        plan.auto_generate()
        first = plan.installments.get(installment_number=1)
        # start Feb 1 + 1 month = Mar 1, day clamped from 31 to 28 → Mar 28
        self.assertEqual(first.due_date, date(2026, 3, 28))

    def test_quarterly_due_dates(self):
        plan = InstallmentPlan.objects.create(
            booking=self._fresh_booking(), total_installments=4, installment_amount=Decimal('1000000'),
            down_payment_amount=Decimal('1000000'), start_date=date(2026, 1, 1),
            frequency='quarterly', due_day=1,
        )
        plan.auto_generate()
        second = plan.installments.get(installment_number=2)
        self.assertEqual(second.due_date, date(2026, 7, 1))

    def test_balloon_payment(self):
        tpl = InstallmentPlanTemplate.objects.create(
            name='Balloon', project=self.project, total_installments=4, frequency='monthly',
            down_payment_percentage=Decimal('10'), has_balloon_payment=True,
            balloon_installment_number=4, balloon_multiplier=Decimal('2'),
        )
        plan = InstallmentPlan.objects.create(
            booking=self._fresh_booking(), template=tpl, total_installments=4,
            installment_amount=Decimal('1000000'), down_payment_amount=Decimal('1000000'),
            start_date=date(2026, 1, 1), frequency='monthly',
        )
        plan.auto_generate()
        last = plan.installments.get(installment_number=4)
        self.assertEqual(last.amount, Decimal('2000000'))

    def test_installment_remaining_amount(self):
        inst = Installment.objects.create(plan=self.plan, installment_number=1,
                                          due_date=date(2026, 2, 15), amount=Decimal('375000'),
                                          late_fee=Decimal('1000'), paid_amount=Decimal('200000'))
        self.assertEqual(inst.remaining_amount, Decimal('176000'))

    def test_installment_partial_status(self):
        inst = Installment.objects.create(plan=self.plan, installment_number=1,
                                          due_date=date(2026, 2, 15), amount=Decimal('375000'),
                                          paid_amount=Decimal('100000'), status='partial')
        self.assertEqual(inst.remaining_amount, Decimal('275000'))

    def test_plan_unique_per_booking(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InstallmentPlan.objects.create(booking=self.booking, total_installments=6,
                                               installment_amount=Decimal('500000'),
                                               down_payment_amount=Decimal('2000000'),
                                               start_date=date(2026, 1, 1), frequency='monthly')

    def test_regenerate_deletes_old(self):
        self.plan.auto_generate()
        self.assertEqual(self.plan.installments.count(), 12)
        self.plan.auto_generate()
        self.assertEqual(self.plan.installments.count(), 12)


# ─── BOOKINGS ────────────────────────────────────────────────────────────────
class BookingEdgeTests(TestCase):
    def setUp(self):
        self.user, self.project, self.plot, self.customer, self.booking = make_fixtures()

    def test_remaining_balance(self):
        self.assertEqual(self.booking.remaining_balance, Decimal('4500000'))

    def test_payment_progress(self):
        self.assertEqual(self.booking.payment_progress, 10)

    def test_payment_progress_zero_total(self):
        # Zero-total bookings are blocked by the DB CheckConstraint. The
        # division-by-zero guard in payment_progress is therefore unreachable
        # via real data; assert the constraint contract instead. The inner
        # atomic isolates the expected failure so it does not poison the
        # test transaction.
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Booking.objects.create(customer=self.customer, plot=self.plot,
                                       total_amount=Decimal('0'),
                                       advance_paid=Decimal('0'), status='pending',
                                       created_by=self.user)
        # And a positive-total booking still computes progress fine.
        b = Booking.objects.create(customer=self.customer, plot=self.plot,
                                   total_amount=Decimal('1000'),
                                   advance_paid=Decimal('0'), status='pending',
                                   created_by=self.user)
        self.assertEqual(b.payment_progress, 0)

    def test_agent_commission(self):
        agent = Agent.objects.create(name='Agent', commission_rate=Decimal('2.5'))
        b = Booking.objects.create(customer=self.customer, plot=self.plot, total_amount=Decimal('1000000'),
                                   agent=agent, created_by=self.user)
        self.assertEqual(b.agent_commission, Decimal('25000'))

    def test_agent_commission_no_agent(self):
        self.assertEqual(self.booking.agent_commission, 0)

    def test_transfer_updates_customer(self):
        new_customer = Customer.objects.create(first_name='New', last_name='Owner', phone='+92-300-9998887',
                                               cnic='35202-6666666-6', created_by=self.user)
        BookingTransfer.objects.create(booking=self.booking, from_customer=self.customer,
                                       to_customer=new_customer, approved_by=self.user)
        self.booking.customer = new_customer
        self.booking.save()
        self.assertEqual(self.booking.customer, new_customer)

    def test_cancellation_policy_tiers(self):
        policy = CancellationPolicy.objects.create(name='Standard')
        CancellationTier.objects.create(policy=policy, from_days=0, to_days=30, refund_percentage=Decimal('75'))
        CancellationTier.objects.create(policy=policy, from_days=31, to_days=90, refund_percentage=Decimal('50'))
        self.assertEqual(policy.tiers.count(), 2)

    def test_booking_status_choices(self):
        valid = {c[0] for c in Booking.STATUS_CHOICES}
        self.assertEqual(valid, {'pending', 'confirmed', 'active', 'cancelled', 'completed'})

    def test_reservation_has_expiry(self):
        reservation = Reservation.objects.create(customer=self.customer, plot=self.plot,
                                                 token_amount=Decimal('100000'),
                                                 expires_at=timezone.now() + timedelta(days=7))
        self.assertIsNotNone(reservation.expires_at)


# ─── PAYMENTS & RECEIPTS ─────────────────────────────────────────────────────
class PaymentEdgeTests(TestCase):
    def setUp(self):
        self.user, self.project, self.plot, self.customer, self.booking = make_fixtures()

    def test_payment_id_sequential(self):
        p1 = Payment.objects.create(booking=self.booking, amount=Decimal('1000'), payment_date=date.today())
        p2 = Payment.objects.create(booking=self.booking, amount=Decimal('2000'), payment_date=date.today())
        self.assertEqual(p1.payment_id, 'PAY-00001')
        self.assertEqual(p2.payment_id, 'PAY-00002')

    def test_receipt_fiscal_year_july(self):
        p = Payment.objects.create(booking=self.booking, amount=Decimal('1000'), payment_date=date(2026, 7, 1))
        r = Receipt.objects.create(payment=p, receipt_date=date(2026, 7, 1))
        self.assertIn('FY26-27', r.receipt_number)

    def test_receipt_fiscal_year_january(self):
        p = Payment.objects.create(booking=self.booking, amount=Decimal('1000'), payment_date=date(2026, 1, 15))
        r = Receipt.objects.create(payment=p, receipt_date=date(2026, 1, 15))
        self.assertIn('FY25-26', r.receipt_number)

    def test_receipt_sequential(self):
        p = Payment.objects.create(booking=self.booking, amount=Decimal('1000'), payment_date=date(2026, 7, 1))
        r1 = Receipt.objects.create(payment=p, receipt_date=date(2026, 7, 1))
        r2 = Receipt.objects.create(payment=p, receipt_date=date(2026, 7, 1))
        self.assertNotEqual(r1.receipt_number, r2.receipt_number)

    def test_payment_allocation_unique(self):
        from django.db import IntegrityError, transaction
        p = Payment.objects.create(booking=self.booking, amount=Decimal('1000'), payment_date=date.today())
        inst = Installment.objects.create(
            plan=InstallmentPlan.objects.create(booking=self.booking, total_installments=1,
                                                installment_amount=Decimal('1000'),
                                                down_payment_amount=Decimal('0'),
                                                start_date=date.today(), frequency='monthly'),
            installment_number=1, due_date=date.today(), amount=Decimal('1000'))
        PaymentAllocation.objects.create(payment=p, installment=inst, amount=Decimal('1000'))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentAllocation.objects.create(payment=p, installment=inst, amount=Decimal('1000'))

    def test_refund_status_choices(self):
        valid = {c[0] for c in Refund.STATUS_CHOICES}
        self.assertEqual(valid, {'pending', 'approved', 'processed', 'rejected'})

    def test_payment_method_choices(self):
        valid = {c[0] for c in Payment.METHOD_CHOICES}
        self.assertIn('jazzcash', valid)
        self.assertIn('easypaisa', valid)


# ─── CUSTOMERS ───────────────────────────────────────────────────────────────
class CustomerEdgeTests(TestCase):
    def setUp(self):
        self.user, self.project, self.plot, self.customer, self.booking = make_fixtures()

    def test_cnic_formatting(self):
        self.assertEqual(format_cnic('3520255555555'), '35202-5555555-5')

    def test_phone_formatting(self):
        self.assertEqual(format_phone('03321507818'), '+92-332-1507818')

    def test_customer_nominee(self):
        nominee = CustomerNominee.objects.create(customer=self.customer, nominee_name='Nominee',
                                                relationship='Brother')
        self.assertEqual(self.customer.nominee, nominee)

    def test_ledger_running_balance_manual(self):
        e1 = CustomerLedgerEntry.objects.create(customer=self.customer, transaction_type='booking',
                                                debit=Decimal('5000000'), credit=Decimal('0'),
                                                running_balance=Decimal('5000000'), entry_date=date.today())
        e2 = CustomerLedgerEntry.objects.create(customer=self.customer, transaction_type='payment',
                                                debit=Decimal('0'), credit=Decimal('500000'),
                                                running_balance=Decimal('4500000'), entry_date=date.today())
        self.assertEqual(e2.running_balance, Decimal('4500000'))

    def test_customer_total_bookings(self):
        self.assertEqual(self.customer.total_bookings, 1)

    def test_customer_full_name(self):
        self.assertEqual(self.customer.full_name, 'Test Customer')


# ─── PLOTS / PROJECTS ────────────────────────────────────────────────────────
class PlotEdgeTests(TestCase):
    def setUp(self):
        self.user, self.project, self.plot, self.customer, self.booking = make_fixtures()

    def test_project_status_counts(self):
        self.assertEqual(self.project.available_plots, 1)
        Plot.objects.create(plot_number='R-2', project=self.project, size_marla=Decimal('5'),
                            price=Decimal('3000000'), status='available')
        self.assertEqual(self.project.available_plots, 2)

    def test_project_booked_plots(self):
        self.plot.status = 'booked'
        self.plot.save()
        self.assertEqual(self.project.booked_plots, 1)

    def test_plot_price_history(self):
        PriceHistory.objects.create(plot=self.plot, old_price=Decimal('4000000'),
                                    new_price=Decimal('5000000'), changed_by=self.user)
        self.assertEqual(self.plot.price_history.count(), 1)

    def test_plot_unique_constraint(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Plot.objects.create(plot_number='R-1', project=self.project, size_marla=Decimal('5'),
                                    price=Decimal('3000000'))


# ─── FINANCE ─────────────────────────────────────────────────────────────────
class FinanceEdgeTests(TestCase):
    def setUp(self):
        self.user, self.project, self.plot, self.customer, self.booking = make_fixtures()
        self.office = Office.objects.create(name='Head Office', office_type='head_office')
        self.category = ExpenseCategory.objects.create(name='Rent', category_type='rent')

    def test_office_expense_approval_flow(self):
        expense = OfficeExpense.objects.create(office=self.office, category=self.category,
                                               amount=Decimal('50000'), expense_date=date.today())
        self.assertEqual(expense.status, 'pending')
        expense.status = 'approved'
        expense.save()
        self.assertEqual(expense.status, 'approved')

    def test_project_budget_remaining(self):
        ProjectCost.objects.create(project=self.project, cost_category='material',
                                   amount=Decimal('30000'), cost_date=date.today(), status='paid')
        budget = ProjectBudget.objects.create(project=self.project, total_budget=Decimal('100000'))
        self.assertEqual(budget.remaining_budget, Decimal('70000'))

    def test_project_cost_categories(self):
        valid = {c[0] for c in ProjectCost.COST_CATEGORY_CHOICES}
        self.assertEqual(valid, {'material', 'labor', 'contractor', 'transportation', 'other'})


# ─── HR & PAYROLL ────────────────────────────────────────────────────────────
class HREdgeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.dept = Department.objects.create(name='Engineering')
        self.emp = Employee.objects.create(first_name='Ali', last_name='Khan', department=self.dept,
                                           joining_date=date.today())

    def test_payroll_run_unique_month(self):
        from django.db import IntegrityError, transaction
        PayrollRun.objects.create(month=8, year=2026)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PayrollRun.objects.create(month=8, year=2026)

    def test_attendance_unique_per_employee_date(self):
        from django.db import IntegrityError, transaction
        Attendance.objects.create(employee=self.emp, date=date.today())
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(employee=self.emp, date=date.today())

    def test_leave_days_default(self):
        leave = Leave.objects.create(employee=self.emp, leave_type='annual',
                                     start_date=date.today(), end_date=date.today() + timedelta(days=2))
        self.assertEqual(leave.days, 1)

    def test_employee_monthly_gross_empty(self):
        self.assertEqual(self.emp.monthly_gross, 0)

    def test_employee_id_format(self):
        self.assertTrue(self.emp.employee_id.startswith('EMP-'))


# ─── PERMISSIONS ─────────────────────────────────────────────────────────────
class PermissionEdgeTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        self.project = Project.objects.create(name='P', location='Lahore')
        self.plot = Plot.objects.create(plot_number='P-1', project=self.project, size_marla=Decimal('5'),
                                        price=Decimal('1000000'))

    def test_sales_cannot_create_payment(self):
        sales = User.objects.create_user('sales', 's@example.com', 'pass12345')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        customer = Customer.objects.create(first_name='C', last_name='K', phone='+92-300-1112222',
                                           cnic='35202-7777777-7', created_by=self.admin)
        booking = Booking.objects.create(customer=customer, plot=self.plot, total_amount=Decimal('1000000'),
                                         created_by=self.admin)
        resp = self.client.post(reverse('payment-list'), {
            'booking': booking.pk, 'amount': '10000', 'payment_date': date.today().isoformat(),
            'payment_method': 'cash', 'payment_type': 'installment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_sales_cannot_create_office_expense(self):
        sales = User.objects.create_user('sales2', 's2@example.com', 'pass12345')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        office = Office.objects.create(name='HO')
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': office.pk, 'amount': '1000', 'expense_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_denied(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(reverse('employee-list'))
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
