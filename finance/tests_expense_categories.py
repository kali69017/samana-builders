from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile
from finance.models import AccountHead, ExpenseCategory, Office, OfficeExpense


class ExpenseCategoryBase:
    def make_users(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'pass123456')
        self.finance = User.objects.create_user('fin', 'f@example.com', 'pass123456')
        UserProfile.objects.create(user=self.finance, role='accounts')
        self.sales = User.objects.create_user('sales', 's@example.com', 'pass123456')
        UserProfile.objects.create(user=self.sales, role='sales')

    def make_used_category(self):
        category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        office = Office.objects.create(name='Head Office')
        OfficeExpense.objects.create(
            office=office, category=category, amount=Decimal('100'),
            expense_date=date.today(), payment_method='cash', status='pending',
            expense_account=AccountHead.objects.get(system_role='office_expenses'),
            paid_from=AccountHead.objects.get(system_role='cash_default'),
        )
        return category


class ExpenseCategoryWebTests(ExpenseCategoryBase, TestCase):
    def setUp(self):
        self.make_users()
        self.client.force_login(self.finance)

    def test_list_shows_edit_delete_and_deactivate_actions(self):
        used = self.make_used_category()
        unused = ExpenseCategory.objects.create(name='Internet', category_type='internet')
        response = self.client.get(reverse('finance_expense_categories'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Actions')
        self.assertContains(response, reverse('finance_expense_category_edit', args=[used.pk]))
        self.assertContains(response, reverse('finance_expense_category_edit', args=[unused.pk]))
        self.assertContains(response, 'Deactivate')
        self.assertContains(response, 'Deactivate it instead')
        self.assertContains(response, 'disabled')

    def test_edit_prefills_and_saves(self):
        category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        response = self.client.get(reverse('finance_expense_category_edit', args=[category.pk]))
        self.assertContains(response, 'Rent')
        response = self.client.post(reverse('finance_expense_category_edit', args=[category.pk]), {
            'name': 'Building Rent', 'category_type': 'rent', 'is_active': 'on',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        category.refresh_from_db()
        self.assertEqual(category.name, 'Building Rent')
        self.assertContains(response, 'Category updated successfully')

    def test_edit_duplicate_name_case_insensitive(self):
        ExpenseCategory.objects.create(name='Rent', category_type='rent')
        other = ExpenseCategory.objects.create(name='Utilities', category_type='utilities')
        response = self.client.post(reverse('finance_expense_category_edit', args=[other.pk]), {
            'name': ' rent ', 'category_type': 'utilities', 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        other.refresh_from_db()
        self.assertEqual(other.name, 'Utilities')

    def test_delete_unused_succeeds_after_confirmation(self):
        category = ExpenseCategory.objects.create(name='Internet', category_type='internet')
        confirm = self.client.get(reverse('finance_expense_category_delete', args=[category.pk]))
        self.assertEqual(confirm.status_code, 200)
        response = self.client.post(
            reverse('finance_expense_category_delete', args=[category.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExpenseCategory.objects.filter(pk=category.pk).exists())
        self.assertContains(response, 'Category deleted successfully')

    def test_delete_used_is_blocked(self):
        category = self.make_used_category()
        response = self.client.post(
            reverse('finance_expense_category_delete', args=[category.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ExpenseCategory.objects.filter(pk=category.pk).exists())
        self.assertContains(response, 'used by 1 records')
        self.assertContains(response, 'Deactivate it instead')

    def test_deactivate_and_activate(self):
        category = self.make_used_category()
        response = self.client.post(
            reverse('finance_expense_category_toggle_active', args=[category.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        category.refresh_from_db()
        self.assertFalse(category.is_active)
        self.assertContains(response, 'Category deactivated')
        self.client.post(reverse('finance_expense_category_toggle_active', args=[category.pk]))
        category.refresh_from_db()
        self.assertTrue(category.is_active)

    def test_sales_cannot_edit_or_delete(self):
        self.client.force_login(self.sales)
        category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        edit = self.client.get(reverse('finance_expense_category_edit', args=[category.pk]))
        self.assertEqual(edit.status_code, 302)
        delete = self.client.post(reverse('finance_expense_category_delete', args=[category.pk]))
        self.assertEqual(delete.status_code, 302)
        self.assertTrue(ExpenseCategory.objects.filter(pk=category.pk).exists())


class ExpenseCategoryApiTests(ExpenseCategoryBase, APITestCase):
    def setUp(self):
        self.make_users()
        self.client.force_authenticate(self.finance)

    def test_api_edit_and_case_insensitive_duplicate(self):
        ExpenseCategory.objects.create(name='Rent', category_type='rent')
        other = ExpenseCategory.objects.create(name='Utilities', category_type='utilities')
        ok = self.client.patch(f'/api/expense-categories/{other.pk}/', {
            'name': 'Building Utilities',
        }, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        duplicate = self.client.patch(f'/api/expense-categories/{other.pk}/', {
            'name': ' rent ',
        }, format='json')
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', duplicate.data)

    def test_api_delete_unused(self):
        category = ExpenseCategory.objects.create(name='Internet', category_type='internet')
        response = self.client.delete(f'/api/expense-categories/{category.pk}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_api_delete_used_returns_400(self):
        category = self.make_used_category()
        response = self.client.delete(f'/api/expense-categories/{category.pk}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('used by 1 records', response.data['error'])
        self.assertTrue(ExpenseCategory.objects.filter(pk=category.pk).exists())

    def test_api_sales_cannot_edit_or_delete(self):
        self.client.force_authenticate(self.sales)
        category = ExpenseCategory.objects.create(name='Rent', category_type='rent')
        patch = self.client.patch(f'/api/expense-categories/{category.pk}/', {
            'name': 'X',
        }, format='json')
        delete = self.client.delete(f'/api/expense-categories/{category.pk}/')
        self.assertEqual(patch.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_fk_is_protected(self):
        category = self.make_used_category()
        with self.assertRaises(ProtectedError):
            category.delete()
