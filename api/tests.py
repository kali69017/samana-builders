"""Comprehensive API test suite for the Samana Builders ERP.

Covers authentication, every registered ViewSet, role-based permissions, and the
new CRM / settings / milestone endpoints. Uses DRF's APITestCase with session
authentication (matching the project's DEFAULT_AUTHENTICATION_CLASSES).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile, Lead, LeadNote, Agent, CompanySettings
from customers.models import Customer
from properties.models import Project, Plot, ProjectMilestone
from bookings.models import Booking, InstallmentPlan, Installment
from payments.models import Payment, Receipt, Refund


class ApiBaseTestCase(APITestCase):
    """Shared fixtures: superuser, project, plot, customer, booking."""

    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass123')
        self.client.force_authenticate(user=self.admin)

        self.project = Project.objects.create(name='Samana Hills', location='Lahore', total_plots=100)
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'), status='available',
        )
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            email='ahmed@example.com', created_by=self.admin,
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), advance_paid=Decimal('500000'),
            status='confirmed', created_by=self.admin,
        )

    def create_available_plot(self, number='A-102', price='3000000'):
        return Plot.objects.create(
            plot_number=number, project=self.project,
            size_marla=Decimal('3.00'), price=Decimal(price), status='available',
        )


class AuthenticationApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('staff', 'staff@example.com', 'staffpass123')
        UserProfile.objects.create(user=self.user, role='admin')

    def test_csrf_endpoint(self):
        resp = self.client.get(reverse('api_csrf'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_login_success(self):
        resp = self.client.post(reverse('api_login'), {'username': 'staff', 'password': 'staffpass123'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'staff')
        self.assertEqual(resp.data['role'], 'admin')

    def test_login_invalid_credentials(self):
        resp = self.client.post(reverse('api_login'), {'username': 'staff', 'password': 'wrong'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_current_user_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(reverse('api_me'))
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class CustomerApiTests(ApiBaseTestCase):
    def test_list_customers(self):
        resp = self.client.get(reverse('customer-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)

    def test_create_customer(self):
        resp = self.client.post(reverse('customer-list'), {
            'first_name': 'Bilal', 'last_name': 'Raza',
            'phone': '+92-301-9998887', 'cnic': '35202-9999999-9',
            'email': 'bilal@example.com',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['customer_id'].startswith('CUS-'))

    def test_create_customer_invalid_cnic(self):
        resp = self.client.post(reverse('customer-list'), {
            'first_name': 'Bad', 'last_name': 'Cnic',
            'phone': '+92-301-9998887', 'cnic': 'invalid',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_customer(self):
        resp = self.client.get(reverse('customer-detail', args=[self.customer.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['customer_id'], self.customer.customer_id)

    def test_update_customer(self):
        resp = self.client.patch(reverse('customer-detail', args=[self.customer.pk]), {'city': 'Karachi'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.city, 'Karachi')

    def test_delete_customer(self):
        resp = self.client.delete(reverse('customer-detail', args=[self.customer.pk]))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Customer.objects.filter(pk=self.customer.pk).exists())

    def test_customer_search(self):
        resp = self.client.get(reverse('customer-list') + '?search=Ahmed')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_customer_bookings_action(self):
        resp = self.client.get(reverse('customer-bookings', args=[self.customer.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)


class PropertyApiTests(ApiBaseTestCase):
    def test_list_projects(self):
        resp = self.client.get(reverse('project-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_project(self):
        resp = self.client.post(reverse('project-list'), {'name': 'New Project', 'location': 'Islamabad', 'total_plots': 50}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_list_plots_filter(self):
        resp = self.client.get(reverse('plot-list') + f'?project={self.project.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_plot_change_status(self):
        plot = self.create_available_plot()
        resp = self.client.post(reverse('plot-change-status', args=[plot.pk]), {'status': 'reserved'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        plot.refresh_from_db()
        self.assertEqual(plot.status, 'reserved')

    def test_plot_change_status_invalid(self):
        plot = self.create_available_plot()
        resp = self.client.post(reverse('plot-change-status', args=[plot.pk]), {'status': 'nope'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class BookingApiTests(ApiBaseTestCase):
    def test_create_booking(self):
        plot = self.create_available_plot()
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '3000000', 'advance_paid': '300000', 'source': 'walk_in',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        plot.refresh_from_db()
        self.assertEqual(plot.status, 'booked')

    def test_confirm_booking(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.create_available_plot(),
            total_amount=Decimal('3000000'), status='pending', created_by=self.admin,
        )
        resp = self.client.post(reverse('booking-confirm', args=[booking.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')

    def test_cancel_booking(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.create_available_plot(),
            total_amount=Decimal('3000000'), status='active', created_by=self.admin,
        )
        resp = self.client.post(reverse('booking-cancel', args=[booking.pk]), {'reason': 'customer_request'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(booking.plot.status, 'available')

    def test_payment_summary(self):
        resp = self.client.get(reverse('booking-payment-summary', args=[self.booking.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('progress_percent', resp.data)


class InstallmentApiTests(ApiBaseTestCase):
    def setUp(self):
        super().setUp()
        self.plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=4,
            installment_amount=Decimal('1000000'), down_payment_amount=Decimal('1000000'),
            start_date=date.today(), frequency='monthly',
        )
        self.plan.auto_generate()

    def test_list_installment_plans(self):
        resp = self.client.get(reverse('installmentplan-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_installment_paid(self):
        inst = self.plan.installments.first()
        resp = self.client.post(reverse('installment-mark-paid', args=[inst.pk]), {'paid_date': date.today().isoformat()}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        inst.refresh_from_db()
        self.assertEqual(inst.status, 'paid')

    def test_installment_filter_by_plan(self):
        resp = self.client.get(reverse('installment-list') + f'?plan={self.plan.pk}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 4)


class PaymentApiTests(ApiBaseTestCase):
    def test_create_payment(self):
        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'amount': '100000',
            'payment_date': date.today().isoformat(), 'payment_method': 'cash',
            'payment_type': 'installment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['payment_id'].startswith('PAY-'))

    def test_create_payment_cheque_requires_number(self):
        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'amount': '100000',
            'payment_date': date.today().isoformat(), 'payment_method': 'cheque',
            'payment_type': 'installment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_payment(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='pending', created_by=self.admin,
        )
        resp = self.client.post(reverse('payment-verify', args=[payment.pk]), {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'verified')

    def test_reject_payment(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='pending', created_by=self.admin,
        )
        resp = self.client.post(reverse('payment-verify', args=[payment.pk]), {'action': 'reject'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'rejected')

    def test_mark_bounced(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cheque', payment_type='installment',
            status='pending', created_by=self.admin,
        )
        resp = self.client.post(reverse('payment-mark-bounced', args=[payment.pk]), {'bounce_reason': 'insufficient funds'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'bounced')

    def test_verify_requires_admin(self):
        sales = User.objects.create_user('sales', 'sales@example.com', 'salespass123')
        UserProfile.objects.create(user=sales, role='sales')
        self.client.force_authenticate(user=sales)
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='pending', created_by=self.admin,
        )
        resp = self.client.post(reverse('payment-verify', args=[payment.pk]), {'action': 'verify'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class RefundApiTests(ApiBaseTestCase):
    def test_create_refund(self):
        resp = self.client.post(reverse('refund-list'), {
            'booking': self.booking.pk, 'amount': '50000', 'reason': 'overpayment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_approve_refund(self):
        refund = Refund.objects.create(booking=self.booking, amount=Decimal('50000'), reason='other')
        resp = self.client.post(reverse('refund-approve', args=[refund.pk]), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        refund.refresh_from_db()
        self.assertEqual(refund.status, 'approved')


class ReceiptApiTests(ApiBaseTestCase):
    def test_list_receipts(self):
        payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100000'),
            payment_date=date.today(), payment_method='cash', payment_type='installment',
            status='verified', created_by=self.admin,
        )
        Receipt.objects.create(payment=payment, generated_by=self.admin)
        resp = self.client.get(reverse('receipt-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)


class LeadApiTests(ApiBaseTestCase):
    def test_create_lead(self):
        resp = self.client.post(reverse('lead-list'), {
            'name': 'Zain', 'phone': '+92-300-5551234', 'source': 'hero', 'status': 'new',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_list_leads(self):
        Lead.objects.create(name='Lead A', phone='+92-300-1112222')
        resp = self.client.get(reverse('lead-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_filter_leads_by_status(self):
        Lead.objects.create(name='Lead A', phone='+92-300-1112222', status='new')
        Lead.objects.create(name='Lead B', phone='+92-300-3334444', status='converted')
        resp = self.client.get(reverse('lead-list') + '?status=new')
        self.assertEqual(len(resp.data), 1)

    def test_set_status(self):
        lead = Lead.objects.create(name='Lead A', phone='+92-300-1112222')
        resp = self.client.post(reverse('lead-set-status', args=[lead.pk]), {'status': 'contacted'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'contacted')
        self.assertTrue(lead.is_contacted)

    def test_convert_lead_to_customer(self):
        lead = Lead.objects.create(name='Convert Me', phone='+92-300-5551234')
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]), {
            'first_name': 'Convert', 'last_name': 'Me', 'phone': '+92-300-5551234',
            'cnic': '35202-7777777-7',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'converted')
        self.assertIsNotNone(lead.converted_customer)

    def test_create_lead_note(self):
        lead = Lead.objects.create(name='Lead A', phone='+92-300-1112222')
        resp = self.client.post(reverse('leadnote-list'), {'lead': lead.pk, 'note': 'Follow up tomorrow'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(lead.lead_notes.count(), 1)


class AgentApiTests(ApiBaseTestCase):
    def test_create_agent(self):
        resp = self.client.post(reverse('agent-list'), {
            'name': 'Agent Smith', 'phone': '+92-300-8887777', 'commission_rate': '2.5',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['agent_id'].startswith('AGT-'))

    def test_list_agents(self):
        Agent.objects.create(name='Agent A', commission_rate=2)
        resp = self.client.get(reverse('agent-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_agent_bookings_action(self):
        agent = Agent.objects.create(name='Agent A', commission_rate=2)
        booking = Booking.objects.create(
            customer=self.customer, plot=self.create_available_plot(),
            total_amount=Decimal('3000000'), agent=agent, created_by=self.admin,
        )
        resp = self.client.get(reverse('agent-bookings', args=[agent.pk]))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)


class CompanySettingsApiTests(ApiBaseTestCase):
    def test_retrieve_settings(self):
        resp = self.client.get(reverse('company-settings'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('company_name', resp.data)

    def test_update_settings(self):
        resp = self.client.patch(reverse('company-settings'), {'company_name': 'Acme Developers'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(CompanySettings.load().company_name, 'Acme Developers')

    def test_dashboard_summary(self):
        resp = self.client.get(reverse('company-settings-summary'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('revenue', resp.data)
        self.assertIn('total_customers', resp.data)


class MilestoneApiTests(ApiBaseTestCase):
    def test_create_milestone(self):
        resp = self.client.post(reverse('projectmilestone-list'), {
            'project': self.project.pk, 'title': 'Foundation', 'status': 'pending', 'order': 1,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_milestone_set_status(self):
        m = ProjectMilestone.objects.create(project=self.project, title='Foundation', status='pending')
        resp = self.client.post(reverse('projectmilestone-set-status', args=[m.pk]), {'status': 'completed'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        m.refresh_from_db()
        self.assertEqual(m.status, 'completed')
        self.assertIsNotNone(m.completed_date)


class PermissionApiTests(ApiBaseTestCase):
    """Verify role-gated write access is enforced over the API."""

    def setUp(self):
        super().setUp()
        self.sales = User.objects.create_user('salesperson', 'sales2@example.com', 'salespass123')
        UserProfile.objects.create(user=self.sales, role='sales')
        self.client.force_authenticate(user=self.sales)

    def test_sales_cannot_create_payment(self):
        resp = self.client.post(reverse('payment-list'), {
            'booking': self.booking.pk, 'amount': '100000',
            'payment_date': date.today().isoformat(), 'payment_method': 'cash',
            'payment_type': 'installment',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_sales_can_read_customers(self):
        resp = self.client.get(reverse('customer-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated_gets_denied(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(reverse('customer-list'))
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
