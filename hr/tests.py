"""Tests for the HR & Payroll module."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile
from finance.models import AccountTransaction, Voucher
from .models import (
    Department, Designation, SalaryComponent, Employee, EmployeeSalary,
    PayrollRun, SalarySlip, SalarySlipItem, SalaryPayment, Attendance, Leave,
)


def seed_components():
    basic = SalaryComponent.objects.create(name='Basic Salary', component_type='earning')
    hra = SalaryComponent.objects.create(name='House Rent', component_type='earning')
    tax = SalaryComponent.objects.create(name='Income Tax', component_type='deduction')
    return basic, hra, tax


class EmployeeModelTest(TestCase):
    def test_employee_id_auto_generated(self):
        dept = Department.objects.create(name='Engineering')
        emp1 = Employee.objects.create(first_name='A', last_name='B', department=dept, joining_date=date.today())
        emp2 = Employee.objects.create(first_name='C', last_name='D', department=dept, joining_date=date.today())
        self.assertEqual(emp1.employee_id, 'EMP-00001')
        self.assertEqual(emp2.employee_id, 'EMP-00002')

    def test_monthly_gross(self):
        dept = Department.objects.create(name='Eng')
        emp = Employee.objects.create(first_name='A', last_name='B', department=dept, joining_date=date.today())
        basic, hra, tax = seed_components()
        EmployeeSalary.objects.create(employee=emp, component=basic, amount=Decimal('50000'))
        EmployeeSalary.objects.create(employee=emp, component=hra, amount=Decimal('10000'))
        EmployeeSalary.objects.create(employee=emp, component=tax, amount=Decimal('2000'))
        self.assertEqual(emp.monthly_gross, Decimal('60000'))

    def test_salary_slip_recalculate(self):
        dept = Department.objects.create(name='Eng')
        emp = Employee.objects.create(first_name='A', last_name='B', department=dept, joining_date=date.today())
        basic, hra, tax = seed_components()
        run = PayrollRun.objects.create(month=1, year=2026)
        slip = SalarySlip.objects.create(employee=emp, run=run)
        SalarySlipItem.objects.create(slip=slip, component=basic, amount=Decimal('50000'))
        SalarySlipItem.objects.create(slip=slip, component=hra, amount=Decimal('10000'))
        SalarySlipItem.objects.create(slip=slip, component=tax, amount=Decimal('2000'))
        net = slip.recalculate()
        self.assertEqual(slip.gross, Decimal('60000'))
        self.assertEqual(slip.total_deductions, Decimal('2000'))
        self.assertEqual(net, Decimal('58000'))


class PayrollWorkflowTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.dept = Department.objects.create(name='Engineering')
        self.basic, self.hra, self.tax = seed_components()
        self.emp = Employee.objects.create(first_name='Ali', last_name='Khan', department=self.dept, joining_date=date.today())
        EmployeeSalary.objects.create(employee=self.emp, component=self.basic, amount=Decimal('50000'))
        EmployeeSalary.objects.create(employee=self.emp, component=self.hra, amount=Decimal('10000'))
        EmployeeSalary.objects.create(employee=self.emp, component=self.tax, amount=Decimal('2000'))

    def test_generate_slips_creates_slip_with_items(self):
        run = PayrollRun.objects.create(month=8, year=2026)
        count = run.generate_slips()
        self.assertEqual(count, 1)
        slip = run.slips.get(employee=self.emp)
        self.assertEqual(slip.items.count(), 3)
        self.assertEqual(slip.net, Decimal('58000'))

    def test_full_payroll_flow_posts_to_ledger(self):
        run = PayrollRun.objects.create(month=8, year=2026)
        run.generate_slips()
        for slip in run.slips.all():
            slip.recalculate()
            slip.status = 'approved'
            slip.save(update_fields=['status'])
        run.status = 'processed'
        run.save(update_fields=['status'])
        for slip in run.slips.filter(status='approved'):
            payment = SalaryPayment.objects.create(slip=slip, amount=slip.net, payment_date=date.today())
            payment.post_to_ledger()
            slip.status = 'paid'
            slip.save(update_fields=['status'])
        run.status = 'paid'
        run.save(update_fields=['status'])

        payment = SalaryPayment.objects.get(slip__run=run)
        voucher = Voucher.objects.get(
            reference_type='SalaryPayment', reference_id=payment.pk)
        self.assertEqual(voucher.voucher_type, 'BP')
        self.assertEqual(
            sum((line.debit for line in voucher.lines.all()), Decimal('0.00')),
            Decimal('58000'),
        )


class HRAPITest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        self.dept = Department.objects.create(name='Engineering')

    def test_create_employee(self):
        resp = self.client.post(reverse('employee-list'), {
            'first_name': 'Ali', 'last_name': 'Khan', 'joining_date': date.today().isoformat(),
            'department': self.dept.pk,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['employee_id'].startswith('EMP-'))

    def test_create_employee_requires_joining_date(self):
        resp = self.client.post(reverse('employee-list'), {
            'first_name': 'Ali', 'last_name': 'Khan',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payroll_run_generate_process_pay(self):
        basic = SalaryComponent.objects.create(name='Basic Salary', component_type='earning')
        emp = Employee.objects.create(first_name='Ali', last_name='Khan', department=self.dept, joining_date=date.today())
        EmployeeSalary.objects.create(employee=emp, component=basic, amount=Decimal('50000'))

        run = PayrollRun.objects.create(month=8, year=2026)
        resp = self.client.post(reverse('payrollrun-generate', args=[run.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp = self.client.post(reverse('payrollrun-process', args=[run.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        resp = self.client.post(reverse('payrollrun-pay', args=[run.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['paid'], 1)
        self.assertTrue(Voucher.objects.filter(reference_type='SalaryPayment').exists())

    def test_leave_approve_action(self):
        emp = Employee.objects.create(first_name='Ali', last_name='Khan', department=self.dept, joining_date=date.today())
        leave = Leave.objects.create(employee=emp, leave_type='annual', start_date=date.today(), end_date=date.today() + timedelta(days=2), days=3)
        resp = self.client.post(reverse('leave-approve', args=[leave.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        leave.refresh_from_db()
        self.assertEqual(leave.status, 'approved')

    def test_non_hr_cannot_create_employee(self):
        sales = User.objects.create_user('sales', 's@example.com', 'pass12345')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        resp = self.client.post(reverse('employee-list'), {
            'first_name': 'Ali', 'last_name': 'Khan', 'joining_date': date.today().isoformat(),
            'department': self.dept.pk,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_account_transactions_list(self):
        AccountTransaction.objects.create(date=date.today(), amount=Decimal('100'), direction='out', transaction_type='payroll')
        resp = self.client.get(reverse('accounttransaction-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)
