from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date
from .models import Payment, Receipt
from .forms import PaymentForm
from customers.models import Customer
from properties.models import Project, Plot
from bookings.models import Booking


class PaymentFormTest(TestCase):
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
    
    def test_valid_payment_form(self):
        form_data = {
            'booking': self.booking.pk,
            'amount': '100000',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'down_payment'
        }
        form = PaymentForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_invalid_amount(self):
        form_data = {
            'booking': self.booking.pk,
            'amount': '-100',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash'
        }
        form = PaymentForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)


@override_settings(SENDPK_ENABLED=False)
class PaymentViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123', is_superuser=True)
        self.client.login(username='testuser', password='testpass123')
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
    
    def test_payment_list_view(self):
        response = self.client.get('/payments/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payments')
    
    def test_payment_create_view(self):
        response = self.client.get('/payments/create/')
        self.assertEqual(response.status_code, 200)
    
    def test_payment_create_post(self):
        response = self.client.post('/payments/create/', {
            'booking': self.booking.pk,
            'amount': '100000',
            'payment_date': date.today().isoformat(),
            'payment_method': 'cash',
            'payment_type': 'down_payment'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.count(), 1)

        payment = Payment.objects.get()
        self.assertEqual(payment.status, 'verified')

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.advance_paid, Decimal('100000'))


class ReceiptTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123', is_superuser=True)
        self.client.login(username='testuser', password='testpass123')
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
        self.payment = Payment.objects.create(
            booking=self.booking,
            amount=Decimal('100000'),
            payment_date=date.today(),
            payment_method='bank_transfer',
            reference_number='',
            method_data={},
            status='verified',
            created_by=self.user
        )

    def test_receipt_number_sequential(self):
        r1 = Receipt.objects.create(payment=self.payment, generated_by=self.user)
        r2 = Receipt.objects.create(payment=self.payment, generated_by=self.user)
        self.assertNotEqual(r1.receipt_number, r2.receipt_number)
        self.assertTrue(r1.receipt_number.endswith('00001') or r2.receipt_number.endswith('00001'))

    def test_receipt_number_unique(self):
        r1 = Receipt.objects.create(payment=self.payment, generated_by=self.user)
        r2 = Receipt.objects.create(payment=self.payment, generated_by=self.user)
        self.assertNotEqual(r1.receipt_number, r2.receipt_number)

    def test_receipt_renders_with_empty_method_data(self):
        receipt = Receipt.objects.create(payment=self.payment, generated_by=self.user)
        response = self.client.get(f'/receipts/{receipt.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, receipt.receipt_number)
        self.assertContains(response, 'info@samanabuilders.com')
        self.assertNotContains(response, 'computer-generated')

    def test_receipt_renders_with_method_data(self):
        self.payment.method_data = {'company_account_title': 'Samana', 'company_account_number': '012345'}
        self.payment.save()
        receipt = Receipt.objects.create(payment=self.payment, generated_by=self.user)
        response = self.client.get(f'/receipts/{receipt.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Samana')
