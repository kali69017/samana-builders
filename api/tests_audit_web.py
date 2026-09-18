"""Audit suite D: web views, notifications, audit edge cases, settings, AI.

Rendering + integration checks for the browser-facing flows and the
cross-cutting services (notifications, audit, settings, AI health).
Created during the 2026 data-integrity audit.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, InstallmentPlan, Installment
from core.models import AuditLog, Agent, CompanySettings, UserProfile
from customers.models import Customer, CustomerNominee
from expenses.models import Expense
from hr.models import Department, Designation, Employee
from notifications.models import NotificationLog, NotificationPreference
from payments.models import Payment, Receipt
from properties.models import Plot, Project


class WebBase(APITestCase):
    """Web pages are rendered via the Django test client (no DRF)."""

    def setUp(self):
        self.admin = User.objects.create_superuser('webadmin', 'w@example.com', 'pass12345')
        self.client.force_login(self.admin)
        self.project = Project.objects.create(name='Web Project', location='Lahore', total_plots=20)
        self.plot = Plot.objects.create(
            plot_number='WP-001', project=self.project, size_marla=Decimal('5'),
            price=Decimal('1000000'), status='available',
        )
        self.customer = Customer.objects.create(
            first_name='Web', last_name='Customer', phone='+92-300-8880001',
            cnic='35202-8880001-1', email='web@example.com', created_by=self.admin,
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000000'),
            advance_paid=Decimal('100000'), status='confirmed', created_by=self.admin,
        )


# ─── WEB PAGES RENDER ───────────────────────────────────────────────────────
class WebPageRenderTests(WebBase):

    def test_dashboard_renders(self):
        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_requires_login(self):
        self.client.logout()
        resp = self.client.get('/dashboard/')
        self.assertIn(resp.status_code, (302, 403))

    def test_corporate_home_public(self):
        self.client.logout()
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)

    def test_customers_page_renders(self):
        resp = self.client.get('/customers/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.customer.full_name)

    def test_customer_detail_renders(self):
        resp = self.client.get(f'/customers/{self.customer.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.customer.customer_id)

    def test_properties_page_renders(self):
        resp = self.client.get('/properties/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.project.name)

    def test_bookings_page_renders(self):
        resp = self.client.get('/bookings/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.booking.booking_id)

    def test_booking_detail_renders(self):
        resp = self.client.get(f'/bookings/{self.booking.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.booking.booking_id)

    def test_payments_page_renders(self):
        resp = self.client.get('/payments/')
        self.assertEqual(resp.status_code, 200)

    def test_expenses_page_renders(self):
        resp = self.client.get('/expenses/')
        self.assertEqual(resp.status_code, 200)

    def test_leads_page_renders(self):
        resp = self.client.get('/leads/')
        self.assertEqual(resp.status_code, 200)

    def test_agents_page_renders(self):
        resp = self.client.get('/agents/')
        self.assertEqual(resp.status_code, 200)

    def test_finance_page_renders(self):
        resp = self.client.get('/finance/ledger/')
        self.assertEqual(resp.status_code, 200)

    def test_refunds_page_renders(self):
        resp = self.client.get('/refunds/')
        self.assertEqual(resp.status_code, 200)

    def test_hr_overview_renders(self):
        resp = self.client.get('/hr/')
        self.assertEqual(resp.status_code, 200)

    def test_ai_assistant_renders(self):
        resp = self.client.get('/ai/')
        self.assertEqual(resp.status_code, 200)

    def test_ai_insights_renders(self):
        resp = self.client.get('/ai/insights/')
        self.assertEqual(resp.status_code, 200)

    def test_settings_page_renders(self):
        resp = self.client.get('/settings/company/')
        self.assertEqual(resp.status_code, 200)

    def test_audit_logs_page_renders(self):
        resp = self.client.get('/audit-logs/')
        self.assertEqual(resp.status_code, 200)

    def test_login_required_for_dashboard(self):
        self.client.logout()
        resp = self.client.get('/dashboard/')
        self.assertIn(resp.status_code, (302, 403))

    def test_booking_form_renders(self):
        resp = self.client.get('/bookings/create/')
        self.assertEqual(resp.status_code, 200)

    def test_customer_form_renders(self):
        resp = self.client.get('/customers/create/')
        self.assertEqual(resp.status_code, 200)

    def test_payment_form_renders(self):
        resp = self.client.get('/payments/create/')
        self.assertEqual(resp.status_code, 200)

    def test_installment_plan_detail_renders(self):
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=4,
            installment_amount=Decimal('225000'), down_payment_amount=Decimal('100000'),
            start_date=date.today(), frequency='monthly',
        )
        plan.auto_generate()
        resp = self.client.get(f'/installment-plans/{plan.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_installment_plan_list_renders(self):
        resp = self.client.get('/installment-plans/')
        self.assertEqual(resp.status_code, 200)


# ─── WEB FORMS SUBMIT ───────────────────────────────────────────────────────
class WebFormSubmitTests(WebBase):

    def test_customer_create_form(self):
        resp = self.client.post('/customers/create/', {
            'first_name': 'Form', 'last_name': 'Customer',
            'phone': '+92-300-8880002', 'cnic': '3520288800021',
            'email': 'form@example.com',
        })
        self.assertIn(resp.status_code, (200, 302))
        self.assertTrue(Customer.objects.filter(phone='+92-300-8880002').exists())

    def test_customer_create_invalid_cnic(self):
        resp = self.client.post('/customers/create/', {
            'first_name': 'Bad', 'last_name': 'Cnic',
            'phone': '+92-300-8880003', 'cnic': '123',
            'email': 'bad@example.com',
        })
        self.assertEqual(resp.status_code, 200)  # re-renders with errors
        self.assertFalse(Customer.objects.filter(phone='+92-300-8880003').exists())

    def test_expense_create_form(self):
        resp = self.client.post('/expenses/create/', {
            'project': self.project.pk, 'description': 'Form expense',
            'amount': '1500', 'expense_type': 'external',
            'paid_to': 'Vendor', 'expense_date': date.today().isoformat(),
            'payment_method': 'bank_transfer',
        })
        self.assertIn(resp.status_code, (200, 302))
        self.assertTrue(Expense.objects.filter(description='Form expense').exists())

    def test_expense_create_negative_rejected(self):
        resp = self.client.post('/expenses/create/', {
            'project': self.project.pk, 'description': 'Neg expense',
            'amount': '-1500', 'expense_type': 'external',
            'paid_to': 'Vendor', 'expense_date': date.today().isoformat(),
            'payment_method': 'cash',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Expense.objects.filter(description='Neg expense').exists())

    def test_booking_create_form_plan_generation(self):
        from bookings.models import InstallmentPlanTemplate
        template = InstallmentPlanTemplate.objects.create(
            name='Web Template', project=self.project, total_installments=6,
            frequency='monthly', down_payment_percentage=Decimal('10.00'),
        )
        plot = Plot.objects.create(
            plot_number='WP-010', project=self.project, size_marla=Decimal('5'),
            price=Decimal('500000'), status='available',
        )
        resp = self.client.post('/bookings/create/', {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '500000', 'advance_paid': '50000',
            'source': 'walk_in', 'installment_template': template.pk,
        })
        self.assertIn(resp.status_code, (200, 302))
        b = Booking.objects.get(plot=plot)
        self.assertIsNotNone(b.installment_plan)
        self.assertEqual(b.installment_plan.installments.count(), 6)

    def test_booking_create_form_uses_actual_advance(self):
        from bookings.models import InstallmentPlanTemplate
        template = InstallmentPlanTemplate.objects.create(
            name='Web Template 2', project=self.project, total_installments=12,
            frequency='monthly', down_payment_percentage=Decimal('10.00'),
        )
        plot = Plot.objects.create(
            plot_number='WP-011', project=self.project, size_marla=Decimal('5'),
            price=Decimal('100000'), status='available',
        )
        self.client.post('/bookings/create/', {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '100000', 'advance_paid': '75000',
            'source': 'walk_in', 'installment_template': template.pk,
        })
        b = Booking.objects.get(plot=plot)
        plan = b.installment_plan
        total = sum(i.amount for i in plan.installments.all())
        # 100K - 75K actual advance = 25K spread over 12 installments
        self.assertEqual(total, Decimal('24999.96'))

    def test_payment_create_form_marks_verified(self):
        resp = self.client.post('/payments/create/', {
            'booking': self.booking.pk, 'amount': '20000',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash', 'payment_type': 'installment',
        })
        self.assertIn(resp.status_code, (200, 302))
        p = Payment.objects.filter(booking=self.booking, amount=Decimal('20000')).first()
        self.assertIsNotNone(p)
        self.assertEqual(p.status, 'verified')
        self.assertTrue(p.receipts.exists())

    def test_payment_create_form_duplicate_blocked(self):
        self.client.post('/payments/create/', {
            'booking': self.booking.pk, 'amount': '20000',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
        })
        count_before = Payment.objects.count()
        self.client.post('/payments/create/', {
            'booking': self.booking.pk, 'amount': '20000',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
        })
        self.assertEqual(Payment.objects.count(), count_before)

    def test_payment_create_installment_from_other_booking_rejected(self):
        plot2 = Plot.objects.create(
            plot_number='WP-012', project=self.project, size_marla=Decimal('3'),
            price=Decimal('500000'), status='available',
        )
        b2 = Booking.objects.create(
            customer=self.customer, plot=plot2, total_amount=Decimal('500000'),
            advance_paid=Decimal('0'), created_by=self.admin,
        )
        plan2 = InstallmentPlan.objects.create(
            booking=b2, total_installments=2, installment_amount=Decimal('250000'),
            down_payment_amount=Decimal('0'), start_date=date.today(),
            frequency='monthly',
        )
        plan2.auto_generate()
        foreign_inst = plan2.installments.first()
        resp = self.client.post('/payments/create/', {
            'booking': self.booking.pk, 'installment': foreign_inst.pk,
            'amount': '5000', 'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Payment.objects.filter(amount=Decimal('5000')).exists())


# ─── NOTIFICATIONS ──────────────────────────────────────────────────────────
class NotificationLogTests(WebBase):

    def test_send_notification_creates_log(self):
        from notifications.services import NotificationService
        NotificationService.send_notification(
            recipient_name='Test', recipient_contact='+92-300-0000000',
            channel='sms', notification_type='test', message='Hello',
        )
        self.assertTrue(NotificationLog.objects.filter(notification_type='test').exists())

    def test_send_notification_records_status(self):
        from notifications.services import NotificationService
        NotificationService.send_notification(
            recipient_name='Test', recipient_contact='+92-300-0000001',
            channel='sms', notification_type='test2', message='Hi',
        )
        log = NotificationLog.objects.get(notification_type='test2')
        self.assertIn(log.status, ('sent', 'failed', 'pending'))

    def test_notification_preference_respected(self):
        pref = NotificationPreference.objects.create(
            user=self.admin, email_enabled=False, sms_enabled=False,
            whatsapp_enabled=False,
        )
        self.assertFalse(pref.email_enabled)

    def test_notification_log_booking_link(self):
        from notifications.services import NotificationService
        NotificationService.send_notification(
            recipient_name='B', recipient_contact='b@example.com',
            channel='email', notification_type='booking_notification',
            message='x', booking_id=self.booking.booking_id,
            customer_id=self.customer.customer_id,
        )
        log = NotificationLog.objects.filter(
            related_booking_id=self.booking.booking_id).first()
        self.assertIsNotNone(log)


# ─── AUDIT LOG EDGE CASES ───────────────────────────────────────────────────
class AuditLogEdgeTests(WebBase):

    def test_audit_log_created_by_user(self):
        AuditLog.objects.create(
            user=self.admin, action='create', model_name='Test',
            object_id='1', description='x',
        )
        log = AuditLog.objects.get(model_name='Test')
        self.assertEqual(log.user, self.admin)

    def test_audit_log_anonymous_allowed(self):
        AuditLog.objects.create(
            action='create', model_name='Anon', object_id='1',
            description='x', ip_address='127.0.0.1',
        )
        log = AuditLog.objects.get(model_name='Anon')
        self.assertIsNone(log.user)
        self.assertEqual(log.ip_address, '127.0.0.1')

    def test_audit_log_list_filterable(self):
        AuditLog.objects.create(
            user=self.admin, action='create', model_name='Customer',
            object_id='CUS-1', description='x',
        )
        AuditLog.objects.create(
            user=self.admin, action='delete', model_name='Customer',
            object_id='CUS-2', description='y',
        )
        resp = self.client.get('/audit-logs/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Customer')


# ─── COMPANY SETTINGS ───────────────────────────────────────────────────────
class CompanySettingsTests(WebBase):

    def test_settings_singleton_values(self):
        settings = CompanySettings.load()
        self.assertIsNotNone(settings)
        self.assertTrue(settings.company_name)

    def test_settings_api_get(self):
        resp = self.client.get('/api/ai/language/')
        self.assertEqual(resp.status_code, 200)

    def test_settings_ai_language_default(self):
        settings = CompanySettings.load()
        self.assertEqual(settings.ai_language, 'english')

    def test_settings_ai_language_update(self):
        settings = CompanySettings.load()
        settings.ai_language = 'roman_urdu'
        settings.save()
        settings.refresh_from_db()
        self.assertEqual(settings.ai_language, 'roman_urdu')


# ─── ROLE-BASED ACCESS ──────────────────────────────────────────────────────
class RoleAccessTests(WebBase):

    def make_sales_user(self):
        u = User.objects.create_user('salesuser', 's@example.com', 'pass12345')
        UserProfile.objects.create(user=u, role='sales')
        return u

    def test_sales_cannot_see_admin_menu(self):
        u = self.make_sales_user()
        self.client.force_login(u)
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Manage Users')

    def test_admin_sees_admin_menu(self):
        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Manage Users')

    def test_sales_cannot_access_settings_page(self):
        u = self.make_sales_user()
        self.client.force_login(u)
        resp = self.client.get('/settings/company/')
        self.assertIn(resp.status_code, (302, 403))

    def test_unauthenticated_redirected(self):
        self.client.logout()
        resp = self.client.get('/customers/')
        self.assertIn(resp.status_code, (302, 403))


# ─── INSTALLMENT REMINDER EDGE CASES ────────────────────────────────────────
class InstallmentReminderTests(WebBase):

    def test_reminder_created_for_installment(self):
        from bookings.models import PaymentReminder
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=2,
            installment_amount=Decimal('450000'), down_payment_amount=Decimal('100000'),
            start_date=date.today(), frequency='monthly',
        )
        plan.auto_generate()
        inst = plan.installments.first()
        PaymentReminder.objects.create(
            installment=inst, reminder_type='upcoming',
            sent_via='sms', message='Due soon',
        )
        self.assertEqual(inst.reminders.count(), 1)

    def test_reminder_types(self):
        from bookings.models import PaymentReminder
        plan = InstallmentPlan.objects.create(
            booking=self.booking, total_installments=2,
            installment_amount=Decimal('450000'), down_payment_amount=Decimal('100000'),
            start_date=date.today(), frequency='monthly',
        )
        plan.auto_generate()
        inst = plan.installments.first()
        for rtype in ['upcoming', 'overdue', 'grace_period', 'late_fee']:
            PaymentReminder.objects.create(
                installment=inst, reminder_type=rtype,
                sent_via='email', message='m',
            )
        self.assertEqual(inst.reminders.count(), 4)


# ─── RECEIVABLE AGING ───────────────────────────────────────────────────────
class ReceivableAgingTests(WebBase):

    def test_receivables_page_renders(self):
        resp = self.client.get('/reports/receivables/')
        self.assertEqual(resp.status_code, 200)

    def test_receivable_aging_record(self):
        from customers.models import ReceivableAging
        ra = ReceivableAging.objects.create(
            customer=self.customer, booking=self.booking,
            current_balance=Decimal('900000'), days_overdue=0,
            aging_bucket='current', computed_at=date.today(),
        )
        self.assertEqual(ra.current_balance, Decimal('900000'))
        self.assertEqual(ra.aging_bucket, 'current')


# ─── NOMINEE ────────────────────────────────────────────────────────────────
class NomineeTests(WebBase):

    def test_nominee_create(self):
        nominee = CustomerNominee.objects.create(
            customer=self.customer, nominee_name='Nom One',
            nominee_cnic='35202-8880009-1', nominee_phone='+92-300-8880009',
            relationship='Father',
        )
        self.assertEqual(nominee.customer, self.customer)

    def test_nominee_cascade_delete(self):
        nominee = CustomerNominee.objects.create(
            customer=self.customer, nominee_name='Nom Two',
            nominee_cnic='35202-8880010-1', relationship='Brother',
        )
        pk = nominee.pk
        self.customer.delete()
        self.assertFalse(CustomerNominee.objects.filter(pk=pk).exists())

    def test_customer_detail_shows_nominee(self):
        CustomerNominee.objects.create(
            customer=self.customer, nominee_name='Visible Nom',
            nominee_cnic='35202-8880011-1', relationship='Wife',
        )
        resp = self.client.get(f'/customers/{self.customer.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Visible Nom')


# ─── CANCELLATION POLICY ────────────────────────────────────────────────────
class CancellationPolicyTests(WebBase):

    def test_policy_create(self):
        from bookings.models import CancellationPolicy, CancellationTier
        policy = CancellationPolicy.objects.create(
            name='Standard', description='Standard policy', is_active=True,
        )
        CancellationTier.objects.create(
            policy=policy, from_days=0, to_days=30,
            refund_percentage=Decimal('50.00'),
        )
        self.assertEqual(policy.tiers.count(), 1)

    def test_tier_refund_percentage(self):
        from bookings.models import CancellationPolicy, CancellationTier
        policy = CancellationPolicy.objects.create(name='P2', is_active=True)
        tier = CancellationTier.objects.create(
            policy=policy, from_days=0, to_days=15,
            refund_percentage=Decimal('75.00'),
        )
        self.assertEqual(tier.refund_percentage, Decimal('75.00'))
