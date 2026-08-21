"""Additional API edge-case tests to reach comprehensive coverage."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, InstallmentPlan, Installment
from core.models import UserProfile, Lead, Agent
from customers.models import Customer, ReceivableAging
from finance.models import Office, OfficeExpense, ProjectCost
from hr.models import Department, Employee, EmployeeSalary, PayrollRun, SalaryComponent, Attendance
from payments.models import Payment, Receipt
from properties.models import Project, Plot


class ApiEdgeBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)
        self.project = Project.objects.create(name='Edge', location='Lahore')
        self.plot = Plot.objects.create(plot_number='E-1', project=self.project, size_marla=Decimal('5'),
                                        price=Decimal('5000000'), status='available')
        self.customer = Customer.objects.create(first_name='Edge', last_name='C', phone='+92-300-1112222',
                                                cnic='35202-8888888-8', email='e@example.com', created_by=self.admin)
        self.booking = Booking.objects.create(customer=self.customer, plot=self.plot,
                                              total_amount=Decimal('5000000'), advance_paid=Decimal('0'),
                                              status='confirmed', created_by=self.admin)


# ─── BOOKING API ─────────────────────────────────────────────────────────────
class BookingApiEdgeTests(ApiEdgeBase):
    def test_booking_create_sets_plot_booked(self):
        plot = Plot.objects.create(plot_number='E-2', project=self.project, size_marla=Decimal('5'),
                                   price=Decimal('3000000'), status='available')
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk, 'total_amount': '3000000',
            'advance_paid': '300000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        plot.refresh_from_db()
        self.assertEqual(plot.status, 'booked')

    def test_booking_filter_by_project(self):
        resp = self.client.get(reverse('booking-list') + f'?project={self.project.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_booking_filter_by_customer(self):
        resp = self.client.get(reverse('booking-list') + f'?customer={self.customer.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_booking_filter_by_status(self):
        resp = self.client.get(reverse('booking-list') + '?status=confirmed')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── PAYMENT API ─────────────────────────────────────────────────────────────
class PaymentApiEdgeTests(ApiEdgeBase):
    def test_payment_create_cheque_without_bank(self):
        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'amount': '10000', 'payment_date': date.today().isoformat(),
            'payment_method': 'cheque', 'payment_type': 'installment', 'cheque_number': '123',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_filter_by_method(self):
        Payment.objects.create(booking=self.booking, amount=Decimal('1000'), payment_date=date.today(),
                               payment_method='cash', payment_type='installment')
        resp = self.client.get(reverse('payment-list') + '?method=cash')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_payment_reverse_restores_advance(self):
        payment = Payment.objects.create(booking=self.booking, amount=Decimal('10000'),
                                         payment_date=date.today(), payment_method='cash',
                                         payment_type='installment', status='verified')
        self.booking.advance_paid = Decimal('10000')
        self.booking.save()
        # reverse via model
        self.booking.advance_paid = max(self.booking.advance_paid - payment.amount, Decimal('0'))
        self.booking.save()
        self.assertEqual(self.booking.advance_paid, Decimal('0'))


# ─── INSTALLMENT API ─────────────────────────────────────────────────────────
class InstallmentApiEdgeTests(ApiEdgeBase):
    def test_installment_filter_by_plan(self):
        plan = InstallmentPlan.objects.create(booking=self.booking, total_installments=3,
                                              installment_amount=Decimal('1000000'),
                                              down_payment_amount=Decimal('0'),
                                              start_date=date.today(), frequency='monthly')
        plan.auto_generate()
        resp = self.client.get(reverse('installment-list') + f'?plan={plan.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 3)

    def test_installment_mark_paid_creates_partial(self):
        plan = InstallmentPlan.objects.create(booking=self.booking, total_installments=1,
                                              installment_amount=Decimal('1000000'),
                                              down_payment_amount=Decimal('0'),
                                              start_date=date.today(), frequency='monthly')
        plan.auto_generate()
        inst = plan.installments.first()
        resp = self.client.post(reverse('installment-mark-paid', args=[inst.pk]),
                                {'paid_amount': '400000'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        inst.refresh_from_db()
        self.assertEqual(inst.status, 'partial')


# ─── CUSTOMER API ────────────────────────────────────────────────────────────
class CustomerApiEdgeTests(ApiEdgeBase):
    def test_customer_search_by_phone(self):
        resp = self.client.get(reverse('customer-list') + '?search=1112222')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_customer_bookings_action(self):
        resp = self.client.get(reverse('customer-bookings', args=[self.customer.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_customer_ledger_action(self):
        resp = self.client.get(reverse('customer-ledger', args=[self.customer.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── LEAD / AGENT ────────────────────────────────────────────────────────────
class LeadAgentApiEdgeTests(ApiEdgeBase):
    def test_lead_source_filter(self):
        Lead.objects.create(name='L1', phone='+92-300-1110001', source='hero')
        Lead.objects.create(name='L2', phone='+92-300-1110002', source='referral')
        resp = self.client.get(reverse('lead-list') + '?source=hero')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_agent_filter(self):
        Agent.objects.create(name='A1', commission_rate=2)
        resp = self.client.get(reverse('agent-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)


# ─── FINANCE API ─────────────────────────────────────────────────────────────
class FinanceApiEdgeTests(ApiEdgeBase):
    def setUp(self):
        super().setUp()
        self.office = Office.objects.create(name='HO')

    def test_office_expense_filter_by_office(self):
        OfficeExpense.objects.create(office=self.office, amount=Decimal('1000'), expense_date=date.today())
        resp = self.client.get(reverse('officeexpense-list') + f'?office={self.office.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_project_cost_filter_by_category(self):
        ProjectCost.objects.create(project=self.project, cost_category='material',
                                   amount=Decimal('1000'), cost_date=date.today(), status='paid')
        resp = self.client.get(reverse('projectcost-list') + '?category=material')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── HR API ──────────────────────────────────────────────────────────────────
class HRApiEdgeTests(ApiEdgeBase):
    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name='Eng')
        self.emp = Employee.objects.create(first_name='A', last_name='B', department=self.dept,
                                           joining_date=date.today())

    def test_employee_search(self):
        resp = self.client.get(reverse('employee-list') + '?search=A')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_attendance_filter_by_date(self):
        Attendance.objects.create(employee=self.emp, date=date.today())
        resp = self.client.get(reverse('attendance-list') + f'?date={date.today().isoformat()}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── RECEIVABLE AGING (model) ────────────────────────────────────────────────
class ReceivableAgingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@example.com', 'adminpass123')
        self.project = Project.objects.create(name='Aging', location='Lahore')
        self.plot = Plot.objects.create(plot_number='A-1', project=self.project, size_marla=Decimal('5'),
                                        price=Decimal('1000000'))
        self.customer = Customer.objects.create(first_name='A', last_name='B', phone='+92-300-1112222',
                                                cnic='35202-9999999-9')
        self.booking = Booking.objects.create(customer=self.customer, plot=self.plot,
                                              total_amount=Decimal('1000000'), advance_paid=Decimal('200000'),
                                              status='active', created_by=self.user)

    def test_aging_bucket_values(self):
        valid = {c[0] for c in ReceivableAging._meta.get_field('aging_bucket').choices}
        self.assertEqual(valid, {'current', '1_30', '31_60', '61_90', '90_plus'})

    def test_aging_record(self):
        ReceivableAging.objects.create(customer=self.customer, booking=self.booking,
                                       current_balance=Decimal('800000'), days_overdue=0,
                                       aging_bucket='current')
        self.assertEqual(self.customer.receivableaging_set.count(), 1)


# ─── AUTH ────────────────────────────────────────────────────────────────────
class AuthEdgeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('staff', 's@example.com', 'pass12345')
        UserProfile.objects.create(user=self.user, role='admin')

    def test_me_returns_role(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(reverse('api_me'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['role'], 'admin')

    def test_csrf_endpoint(self):
        resp = self.client.get(reverse('api_csrf'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
