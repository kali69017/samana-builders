from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from core.models import UserProfile, AuditLog
from customers.models import Customer
from properties.models import Project, Plot
from bookings.models import Booking, InstallmentPlan, Installment
from payments.models import Payment, Receipt
from notifications import wa_templates


class CustomerModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
    
    def test_customer_creation(self):
        customer = Customer.objects.create(
            first_name='Ahmed',
            last_name='Khan',
            phone='+92-300-1234567',
            cnic='35202-1234567-1',
            email='ahmed@example.com',
            created_by=self.user
        )
        self.assertEqual(customer.customer_id, 'CUS-00001')
        self.assertEqual(customer.full_name, 'Ahmed Khan')
    
    def test_customer_id_auto_increment(self):
        c1 = Customer.objects.create(
            first_name='Test1', last_name='User1',
            phone='+92-300-1111111', cnic='35202-1111111-1',
            created_by=self.user
        )
        c2 = Customer.objects.create(
            first_name='Test2', last_name='User2',
            phone='+92-300-2222222', cnic='35202-2222222-2',
            created_by=self.user
        )
        self.assertEqual(c1.customer_id, 'CUS-00001')
        self.assertEqual(c2.customer_id, 'CUS-00002')


class ProjectModelTest(TestCase):
    def test_project_creation(self):
        project = Project.objects.create(
            name='Test Project',
            location='Lahore',
            total_plots=100
        )
        self.assertEqual(project.name, 'Test Project')
        self.assertEqual(project.status, 'booking_open')


class PlotModelTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            name='Test Project',
            location='Lahore',
            total_plots=100
        )
    
    def test_plot_creation(self):
        plot = Plot.objects.create(
            plot_number='A-101',
            project=self.project,
            plot_type='residential',
            size_marla=Decimal('5.00'),
            price=Decimal('5000000'),
            status='available'
        )
        self.assertEqual(plot.plot_number, 'A-101')
        self.assertEqual(plot.status, 'available')
    
    def test_plot_unique_together(self):
        Plot.objects.create(
            plot_number='A-101',
            project=self.project,
            size_marla=Decimal('5.00'),
            price=Decimal('5000000')
        )
        with self.assertRaises(Exception):
            Plot.objects.create(
                plot_number='A-101',
                project=self.project,
                size_marla=Decimal('5.00'),
                price=Decimal('5000000')
            )


class BookingModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            created_by=self.user
        )
        self.project = Project.objects.create(name='Test', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000')
        )
    
    def test_booking_creation(self):
        booking = Booking.objects.create(
            customer=self.customer,
            plot=self.plot,
            total_amount=Decimal('5000000'),
            advance_paid=Decimal('500000'),
            created_by=self.user
        )
        self.assertEqual(booking.booking_id, 'BKG-00001')
        self.assertEqual(booking.remaining_balance, Decimal('4500000'))
    
    def test_booking_id_auto_increment(self):
        b1 = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user
        )
        self.assertEqual(b1.booking_id, 'BKG-00001')


class PaymentModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            created_by=self.user
        )
        self.project = Project.objects.create(name='Test', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000')
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user
        )
    
    def test_payment_creation(self):
        payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('100000'),
            payment_date=date.today(),
            payment_method='cash',
            created_by=self.user
        )
        self.assertEqual(payment.payment_id, 'PAY-00001')
        self.assertEqual(payment.status, 'pending')
    
    def test_payment_verification(self):
        payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('100000'),
            payment_date=date.today(),
            payment_method='cash',
            created_by=self.user
        )
        payment.status = 'verified'
        payment.verified_by = self.user
        payment.save()
        
        self.booking.advance_paid += payment.amount
        self.booking.save()
        
        self.assertEqual(payment.status, 'verified')
        self.assertEqual(self.booking.advance_paid, Decimal('100000'))


class UserProfileTest(TestCase):
    def test_user_profile_creation(self):
        user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        profile = UserProfile.objects.create(
            user=user,
            role='sales',
            phone='+92-300-1234567'
        )
        self.assertEqual(profile.role, 'sales')
        # get_full_name() returns empty if no first/last name set
        self.assertIn('Sales', str(profile))


class AuditLogTest(TestCase):
    def test_audit_log_creation(self):
        user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
        log = AuditLog.objects.create(
            user=user,
            action='create',
            model_name='Customer',
            object_id='CUS-00001',
            description='Created customer Ahmed Khan'
        )
        self.assertEqual(log.action, 'create')
        self.assertEqual(log.model_name, 'Customer')


class BookingConfirmWhatsAppTest(TestCase):
    """Confirming a booking notifies the customer on WhatsApp via a template."""

    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'boss@example.com', 'testpass123')
        self.customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            email='ahmed@example.com', created_by=self.user,
        )
        self.project = Project.objects.create(name='Bahria Town', location='Lahore')
        self.plot = Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
        )
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), advance_paid=Decimal('1000000'),
            status='pending', created_by=self.user,
        )
        self.client.force_login(self.user)

    @override_settings(
        SENDPK_ENABLED=False,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        WHATSAPP_ENABLED=True,
        WHATSAPP_API_TOKEN='test-token',
        WHATSAPP_PHONE_NUMBER_ID='1276551565544996',
        WHATSAPP_API_VERSION='v25.0',
        WHATSAPP_TEMPLATE_LANGUAGE='en_US',
        **{e['env_setting']: e['suggested_name'] for e in wa_templates.templates()},
    )
    def test_confirm_sends_approved_template(self):
        resp = Mock(status_code=200)
        resp.json.return_value = {'messages': [{'id': 'wamid.CONFIRM1'}]}
        with patch('notifications.services.requests.post', return_value=resp) as mock_post:
            self.client.post(f'/bookings/{self.booking.pk}/confirm/')

        self.booking.refresh_from_db()
        self.assertEqual('confirmed', self.booking.status)

        # Templates are POSITIONAL, so there is no parameter_name to key on.
        # Resolve the template and its parameter order from the spec instead of
        # hardcoding either, so renaming a template cannot silently pass here.
        template_name = wa_templates.template_name('booking_approval')
        payloads = [c.kwargs['json'] for c in mock_post.call_args_list
                    if c.kwargs['json'].get('template', {}).get('name') == template_name]
        self.assertEqual(1, len(payloads))
        texts = [p['text'] for c in payloads[0]['template']['components'] for p in c['parameters']]
        params = dict(zip(wa_templates.parameter_order('booking_approval'), texts))
        self.assertEqual(5, len(params))
        self.assertEqual('Ahmed Khan', params['customer_name'])
        self.assertEqual('BKG-00001', params['booking_id'])
        self.assertEqual('A-101', params['plot_number'])
        self.assertEqual('Bahria Town', params['project_name'])
        self.assertEqual('5,000,000', params['total_amount'])
