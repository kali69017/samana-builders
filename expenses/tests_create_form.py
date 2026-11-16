from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from expenses.models import Expense
from finance.models import AccountHead
from properties.models import Project


class ExpenseCreateFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('exp', 'exp@example.com', 'pass123456')
        self.client.login(username='exp', password='pass123456')
        self.project = Project.objects.create(name='E2E Expense P', location='Lahore', total_plots=1)
        self.expense_account = AccountHead.objects.get(system_role='office_expenses')
        self.bank = AccountHead.objects.get(system_role='bank_default')

    def test_payment_method_widget_and_errors_are_rendered(self):
        response = self.client.get('/expenses/create/')
        self.assertContains(response, 'id_payment_method')
        self.assertContains(response, 'Payment Method')
        response = self.client.post('/expenses/create/', {})
        self.assertContains(response, 'id_payment_method')
        self.assertContains(response, 'This field is required')
        self.assertContains(response, 'Please correct the following')

    def test_expense_can_be_created_with_visible_payment_method(self):
        response = self.client.post('/expenses/create/', {
            'project': self.project.pk,
            'expense_account': self.expense_account.pk,
            'paid_from': self.bank.pk,
            'description': 'E2E-EXPENSE-CREATE',
            'amount': '23.00',
            'expense_type': 'internal',
            'paid_to': 'E2E-Payee',
            'expense_date': date.today().isoformat(),
            'payment_method': 'bank_transfer',
            'payment_reference': 'E2E-REF',
        })
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(description='E2E-EXPENSE-CREATE')
        self.assertEqual(expense.payment_method, 'bank_transfer')
        self.assertEqual(expense.status, 'pending')
