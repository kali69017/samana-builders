from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Sum
from django.test import TestCase

from bookings.models import Booking
from customers.models import Customer
from expenses.models import Expense
from finance.accounting import customer_advance_head
from finance.models import (
    AccountHead, ExpenseCategory, Office, OfficeExpense, ProjectCost, VoucherLine,
)
from finance.reporting import get_financial_metrics
from hr.models import Employee, PayrollRun, SalaryPayment, SalarySlip
from payments.models import Payment, Refund
from properties.models import Plot, Project


class ReportingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'report', 'report@example.com', 'pass123456')
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.office_head = AccountHead.objects.get(system_role='office_expenses')
        self.project_cost_head = AccountHead.objects.get(system_role='project_costs')
        self.salaries_head = AccountHead.objects.get(system_role='salaries')
        operating_parent = AccountHead.objects.get(code='5.1')
        self.operating_head = AccountHead.objects.create(
            name='Reporting Operating Expense', parent=operating_parent)

        self.customer = Customer.objects.create(
            first_name='Report', last_name='Test', phone='03001234567',
            cnic='12345-1234567-1', created_by=self.user,
        )
        self.project = Project.objects.create(
            name='Report Project', location='Lahore', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='REP-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('2000'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('2000'),
            advance_paid=Decimal('0'), status='confirmed', created_by=self.user,
        )
        self.office = Office.objects.create(name='Report Office')
        self.category = ExpenseCategory.objects.create(name='Report Category')

    def test_metrics_match_posted_voucher_lines(self):
        expense = Expense.objects.create(
            project=self.project, expense_account=self.operating_head,
            paid_from=self.cash, amount=Decimal('100'),
            description='Operating expense', expense_date=date.today(),
            payment_method='cash', status='paid', created_by=self.user,
        )
        expense.post_to_ledger(self.user)

        office_expense = OfficeExpense.objects.create(
            office=self.office, category=self.category,
            expense_account=self.office_head, paid_from=self.cash,
            amount=Decimal('200'), expense_date=date.today(),
            payment_method='cash', status='paid', created_by=self.user,
        )
        office_expense.post_to_ledger()

        project_cost = ProjectCost.objects.create(
            project=self.project, cost_category='material',
            expense_account=self.project_cost_head, paid_from=self.cash,
            amount=Decimal('300'), cost_date=date.today(),
            payment_method='cash', status='paid', created_by=self.user,
        )
        project_cost.post_to_ledger()

        employee = Employee.objects.create(
            first_name='Report', last_name='Employee', joining_date=date.today())
        run = PayrollRun.objects.create(month=11, year=2026)
        slip = SalarySlip.objects.create(employee=employee, run=run, net=Decimal('400'))
        salary = SalaryPayment.objects.create(
            slip=slip, amount=Decimal('400'), payment_date=date.today(),
            method='bank_transfer')
        salary.post_to_ledger()

        payment = Payment.objects.create(
            booking=self.booking, received_into=self.cash,
            amount=Decimal('1000'), payment_date=date.today(),
            payment_method='cash', payment_type='advance',
            status='verified', created_by=self.user,
        )
        refund = Refund.objects.create(
            booking=self.booking, paid_from=self.cash, amount=Decimal('100'),
            reason='overpayment', refund_method='cash', refund_date=date.today(),
            status='processed', approved_by=self.user, processed_by=self.user,
        )
        refund.post_to_ledger()
        self.booking.mark_delivered(self.user, date.today())

        metrics = get_financial_metrics(date.today(), date.today())
        self.assertEqual(metrics.collected, Decimal('1000.00'))
        self.assertEqual(metrics.customer_advances_held, Decimal('0.00'))
        self.assertEqual(metrics.recognized_revenue, Decimal('900.00'))
        self.assertEqual(metrics.expenses, Decimal('1000.00'))
        self.assertEqual(metrics.profit, Decimal('-100.00'))
        self.assertEqual(metrics.expense_groups['operating'], Decimal('100.00'))
        self.assertEqual(metrics.expense_groups['office'], Decimal('200.00'))
        self.assertEqual(metrics.expense_groups['project_cost'], Decimal('300.00'))
        self.assertEqual(metrics.expense_groups['salaries'], Decimal('400.00'))
        self.assertEqual(sum(metrics.expense_groups.values(), Decimal('0.00')),
                         metrics.expenses)

        posted = VoucherLine.objects.filter(voucher__status='posted')
        revenue_lines = posted.filter(account_head__code__startswith='4').aggregate(
            debit=Sum('debit'),
            credit=Sum('credit'))
        self.assertEqual(
            metrics.recognized_revenue,
            (revenue_lines['credit'] or Decimal('0.00'))
            - (revenue_lines['debit'] or Decimal('0.00')),
        )
        expense_lines = posted.filter(account_head__code__startswith='5').aggregate(
            debit=Sum('debit'),
            credit=Sum('credit'))
        self.assertEqual(
            metrics.expenses,
            (expense_lines['debit'] or Decimal('0.00'))
            - (expense_lines['credit'] or Decimal('0.00')),
        )
        advances = customer_advance_head()
        advance_lines = posted.filter(account_head=advances).aggregate(
            debit=Sum('debit'),
            credit=Sum('credit'))
        self.assertEqual(
            metrics.customer_advances_held,
            (advance_lines['credit'] or Decimal('0.00'))
            - (advance_lines['debit'] or Decimal('0.00')),
        )

