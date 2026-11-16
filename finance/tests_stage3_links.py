from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking
from customers.models import Customer
from expenses.forms import ExpenseForm
from finance.forms import OfficeExpenseForm, ProjectCostForm
from finance.models import AccountHead, Office, OfficeExpense, ProjectCost, Voucher
from payments.forms import PaymentForm, RefundForm
from payments.models import Payment, Refund
from properties.models import Plot, Project


class FinanceAccountLinkFormTests(TestCase):
    def setUp(self):
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.office_expense = AccountHead.objects.get(system_role='office_expenses')
        self.project_cost = AccountHead.objects.get(system_role='project_costs')
        self.project = Project.objects.create(name='P', location='L', total_plots=1)
        self.customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )

    def test_payment_form_requires_received_into(self):
        form = PaymentForm(data={
            'booking': self.booking.pk, 'amount': '100', 'payment_date': date.today(),
            'payment_method': 'cash', 'payment_type': 'down_payment',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('received_into', form.errors)

    def test_payment_form_rejects_bank_account_for_cash_method(self):
        form = PaymentForm(data={
            'booking': self.booking.pk, 'received_into': self.bank.pk, 'amount': '100',
            'payment_date': date.today(), 'payment_method': 'cash',
            'payment_type': 'down_payment',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('received_into', form.errors)

    def test_refund_form_requires_paid_from(self):
        form = RefundForm(data={
            'booking': self.booking.pk, 'amount': '50', 'reason': 'other',
            'refund_method': 'cash',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('paid_from', form.errors)

    def test_expense_form_requires_expense_account(self):
        form = ExpenseForm(data={
            'project': self.project.pk, 'amount': '100', 'expense_type': 'internal',
            'expense_date': date.today(), 'payment_method': 'cash',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('expense_account', form.errors)

    def test_project_and_office_expense_forms_require_accounts(self):
        office = Office.objects.create(name='HO')
        office_form = OfficeExpenseForm(data={
            'office': office.pk, 'amount': '100', 'expense_date': date.today(),
            'payment_method': 'cash',
        })
        self.assertFalse(office_form.is_valid())
        self.assertIn('expense_account', office_form.errors)
        self.assertIn('paid_from', office_form.errors)

        cost_form = ProjectCostForm(data={
            'project': self.project.pk, 'cost_category': 'material', 'amount': '100',
            'cost_date': date.today(), 'payment_method': 'cash',
        })
        self.assertFalse(cost_form.is_valid())
        self.assertIn('expense_account', cost_form.errors)
        self.assertIn('paid_from', cost_form.errors)


class CentralPostingTests(TestCase):
    def setUp(self):
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.receivable = AccountHead.objects.get(system_role='receivable')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.advances = AccountHead.objects.get(system_role='customer_advances')
        self.payable = AccountHead.objects.get(system_role='payable')
        self.office_expense = AccountHead.objects.get(system_role='office_expenses')
        self.project_cost = AccountHead.objects.get(system_role='project_costs')
        self.customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        self.project = Project.objects.create(name='P', location='L', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )

    def test_payment_uses_received_into_and_is_idempotent(self):
        payment = Payment.objects.create(
            booking=self.booking, received_into=self.bank, amount=Decimal('100'),
            payment_date=date.today(), payment_method='bank_transfer', status='verified',
        )
        voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.bank)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.advances)
        payment.save()
        self.assertEqual(
            Voucher.objects.filter(reference_type='Payment', reference_id=payment.pk).count(), 1)

    def test_refund_uses_paid_from(self):
        refund = Refund.objects.create(
            booking=self.booking, paid_from=self.cash, amount=Decimal('50'),
            reason='other', refund_method='cash', status='approved',
        )
        refund.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='Refund', reference_id=refund.pk)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.cash)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.advances)

    def test_unpaid_expense_uses_payable_and_paid_expense_uses_cash(self):
        from expenses.models import Expense
        unpaid = Expense.objects.create(
            project=self.project, expense_account=self.project_cost, amount=Decimal('100'),
            description='unpaid', expense_date=date.today(), payment_method='cash',
            status='approved',
        )
        unpaid.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='Expense', reference_id=unpaid.pk)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.payable)

        paid = Expense.objects.create(
            project=self.project, expense_account=self.project_cost, paid_from=self.cash,
            amount=Decimal('100'), description='paid', expense_date=date.today(),
            payment_method='cash', status='paid',
        )
        paid.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='Expense', reference_id=paid.pk)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.cash)

    def test_project_cost_and_office_expense_use_chosen_accounts(self):
        cost = ProjectCost.objects.create(
            project=self.project, expense_account=self.project_cost, paid_from=self.bank,
            amount=Decimal('200'), cost_date=date.today(), payment_method='bank_transfer',
            status='paid',
        )
        cost.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='ProjectCost', reference_id=cost.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.project_cost)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.bank)

        office = Office.objects.create(name='HO')
        expense = OfficeExpense.objects.create(
            office=office, expense_account=self.office_expense, paid_from=self.cash,
            amount=Decimal('300'), expense_date=date.today(), payment_method='cash',
            status='paid',
        )
        expense.post_to_ledger()
        voucher = Voucher.objects.get(reference_type='OfficeExpense', reference_id=expense.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.office_expense)
        self.assertEqual(voucher.lines.get(credit__gt=0).account_head, self.cash)


class BookingAndInstallmentLinkTests(TestCase):
    def setUp(self):
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.receivable = AccountHead.objects.get(system_role='receivable')
        self.revenue = AccountHead.objects.get(system_role='revenue')
        self.customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        self.project = Project.objects.create(name='P', location='L', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )

    def test_confirmed_booking_does_not_post_a_voucher(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )
        self.assertFalse(Voucher.objects.filter(
            reference_type='Booking', reference_id=booking.pk).exists())

    def test_payment_advances_account_is_configurable(self):
        advances = AccountHead.objects.get(system_role='customer_advances')
        refunds = AccountHead.objects.get(system_role='refunds')
        advances.system_role = None
        advances.save(update_fields=['system_role'])
        refunds.system_role = 'customer_advances'
        refunds.save(update_fields=['system_role'])
        try:
            booking = Booking.objects.create(
                customer=self.customer, plot=self.plot, total_amount=Decimal('500'),
                advance_paid=Decimal('100'), status='pending',
            )
            payment = Payment.objects.create(
                booking=booking, received_into=self.cash, amount=Decimal('100'),
                payment_date=date.today(), payment_method='cash', status='verified',
            )
            voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
            self.assertEqual(voucher.lines.get(credit__gt=0).account_head, refunds)
        finally:
            refunds.system_role = 'refunds'
            refunds.save(update_fields=['system_role'])
            advances.system_role = 'customer_advances'
            advances.save(update_fields=['system_role'])

    def test_installment_links_receivable_without_voucher(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )
        from bookings.models import InstallmentPlan
        plan = InstallmentPlan.objects.create(
            booking=booking, total_installments=2, installment_amount=Decimal('450'),
            down_payment_amount=Decimal('100'), start_date=booking.booking_date,
        )
        plan.auto_generate()
        self.assertEqual(plan.installments.count(), 2)
        for installment in plan.installments.all():
            self.assertEqual(installment.receivable_account, self.receivable)
        self.assertFalse(Voucher.objects.filter(reference_type='Installment').exists())


class BookingCancelReopenLedgerTests(TestCase):
    def setUp(self):
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        self.project = Project.objects.create(name='P', location='L', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )

    def test_cancel_and_reopen_do_not_post_booking_vouchers(self):
        self.assertFalse(Voucher.objects.filter(
            reference_type='Booking', reference_id=self.booking.pk).exists())
        self.booking.status = 'cancelled'
        self.booking.save()
        self.assertFalse(Voucher.objects.filter(
            reference_type='BookingCancel', reference_id=self.booking.pk).exists())
        self.booking.status = 'pending'
        self.booking.save()
        self.assertFalse(Voucher.objects.filter(
            reference_type='BookingReopen', reference_id=self.booking.pk).exists())


class FinanceAccountLinkAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@example.com', 'pass123456')
        self.client.force_authenticate(self.admin)
        self.cash = AccountHead.objects.get(system_role='cash_default')
        self.bank = AccountHead.objects.get(system_role='bank_default')
        self.customer = Customer.objects.create(
            first_name='A', last_name='B', phone='03001234567', cnic='12345-1234567-1',
        )
        self.project = Project.objects.create(name='P', location='L', total_plots=1)
        self.plot = Plot.objects.create(
            plot_number='P-1', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000'), holding_deposit=Decimal('100'), status='available',
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000'),
            advance_paid=Decimal('100'), status='confirmed',
        )

    def test_cancel_after_full_refund_is_allowed_without_booking_reversal(self):
        payment = Payment.objects.create(
            booking=self.booking, received_into=self.cash, amount=Decimal('100'),
            payment_date=date.today(), payment_method='cash', status='verified',
        )
        refund = Refund.objects.create(
            booking=self.booking, paid_from=self.cash, amount=Decimal('100'),
            reason='other', refund_method='cash', status='approved',
        )
        refund.post_to_ledger()
        response = self.client.post(f'/api/bookings/{self.booking.pk}/cancel/', {
            'reason': 'customer_request',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Voucher.objects.filter(
            reference_type='BookingCancel', reference_id=self.booking.pk).exists())

    def test_payment_api_requires_received_into(self):
        response = self.client.post('/api/payments/', {
            'booking': self.booking.pk, 'amount': '100', 'payment_date': date.today(),
            'payment_method': 'cash', 'payment_type': 'down_payment',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('received_into', response.data)

    def test_payment_api_uses_received_into(self):
        response = self.client.post('/api/payments/', {
            'booking': self.booking.pk, 'received_into': self.cash.pk, 'amount': '100',
            'payment_date': date.today(), 'payment_method': 'cash',
            'payment_type': 'down_payment',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        payment = Payment.objects.get(payment_id=response.data['payment_id'])
        voucher = Voucher.objects.get(reference_type='Payment', reference_id=payment.pk)
        self.assertEqual(voucher.lines.get(debit__gt=0).account_head, self.cash)

    def test_refund_api_requires_paid_from(self):
        response = self.client.post('/api/refunds/', {
            'booking': self.booking.pk, 'amount': '50', 'reason': 'other',
            'refund_method': 'cash',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('paid_from', response.data)

    def test_project_cost_api_requires_accounts(self):
        response = self.client.post('/api/project-costs/', {
            'project': self.project.pk, 'cost_category': 'material', 'amount': '100',
            'cost_date': date.today(), 'payment_method': 'cash',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_office_expense_api_requires_accounts(self):
        office = Office.objects.create(name='HO')
        response = self.client.post('/api/office-expenses/', {
            'office': office.pk, 'amount': '100', 'expense_date': date.today(),
            'payment_method': 'cash',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
