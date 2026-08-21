"""Tests for the Finance module (office expenses, project costs, ledger)."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile
from properties.models import Project
from .models import (
    AccountTransaction, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment,
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
                                               status='paid', created_by=self.user)
        expense.post_to_ledger()
        tx = AccountTransaction.objects.get(reference_type='OfficeExpense', reference_id=expense.pk)
        self.assertEqual(tx.transaction_type, 'office_expense')
        self.assertEqual(tx.direction, 'out')
        self.assertEqual(tx.office, self.office)

    def test_project_cost_posts_to_ledger(self):
        cost = ProjectCost.objects.create(project=self.project, cost_category='material',
                                          amount=Decimal('100000'), cost_date=date.today(),
                                          status='paid', created_by=self.user)
        cost.post_to_ledger()
        tx = AccountTransaction.objects.get(reference_type='ProjectCost', reference_id=cost.pk)
        self.assertEqual(tx.transaction_type, 'project_cost')
        self.assertEqual(tx.project, self.project)

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
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': self.office.pk, 'category': self.category.pk, 'amount': '25000',
            'expense_date': date.today().isoformat(), 'status': 'paid',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(AccountTransaction.objects.filter(transaction_type='office_expense').exists())

    def test_create_office_expense_zero_rejected(self):
        resp = self.client.post(reverse('officeexpense-list'), {
            'office': self.office.pk, 'amount': '0', 'expense_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_project_cost_posts_ledger(self):
        resp = self.client.post(reverse('projectcost-list'), {
            'project': self.project.pk, 'cost_category': 'material', 'amount': '50000',
            'cost_date': date.today().isoformat(), 'status': 'paid',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(AccountTransaction.objects.filter(transaction_type='project_cost').exists())

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
