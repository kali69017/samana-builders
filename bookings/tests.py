from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from datetime import date, timedelta
from .models import Booking, InstallmentPlan, Installment
from .forms import BookingForm, InstallmentPlanForm
from customers.models import Customer
from properties.models import Project, Plot


class BookingFormTest(TestCase):
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
    
    def test_valid_booking_form(self):
        form_data = {
            'customer': self.customer.pk,
            'plot': self.plot.pk,
            'total_amount': '5000000',
            'advance_paid': '500000'
        }
        form = BookingForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_advance_exceeds_total(self):
        form_data = {
            'customer': self.customer.pk,
            'plot': self.plot.pk,
            'total_amount': '5000000',
            'advance_paid': '6000000'
        }
        form = BookingForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('advance_paid', form.errors)


class InstallmentPlanFormTest(TestCase):
    def test_valid_installment_plan_form(self):
        form_data = {
            'total_installments': '12',
            'installment_amount': '400000',
            'down_payment_amount': '100000',
            'start_date': date.today().isoformat(),
            'frequency': 'monthly',
            'due_day': '1',
            'late_fee_per_day': '1000',
            'grace_period_days': '0',
        }
        form = InstallmentPlanForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_invalid_due_day(self):
        form_data = {
            'total_installments': '12',
            'installment_amount': '400000',
            'down_payment_amount': '100000',
            'start_date': date.today().isoformat(),
            'frequency': 'monthly',
            'due_day': '32',
            'late_fee_per_day': '1000',
            'grace_period_days': '0',
        }
        form = InstallmentPlanForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('due_day', form.errors)


class BookingViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('testuser', 'test@example.com', 'testpass123')
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
    
    def test_booking_list_view(self):
        response = self.client.get('/bookings/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bookings')
    
    def test_booking_stats_context(self):
        Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), status='confirmed', created_by=self.user
        )
        plot2 = Plot.objects.create(
            plot_number='A-102', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('3000000')
        )
        Booking.objects.create(
            customer=self.customer, plot=plot2,
            total_amount=Decimal('3000000'), status='pending', created_by=self.user
        )
        response = self.client.get('/bookings/')
        self.assertEqual(response.context['confirmed_count'], 1)
        self.assertEqual(response.context['pending_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('8000000'))
        self.assertEqual(len(response.context['bookings']), 2)
    
    def test_booking_search_and_status_filter(self):
        Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), status='confirmed', created_by=self.user
        )
        plot2 = Plot.objects.create(
            plot_number='A-102', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('3000000')
        )
        Booking.objects.create(
            customer=self.customer, plot=plot2,
            total_amount=Decimal('3000000'), status='pending', created_by=self.user
        )
        response = self.client.get('/bookings/?search=A-101')
        self.assertEqual(len(response.context['bookings']), 1)
        self.assertEqual(response.context['total_amount'], Decimal('5000000'))
        self.assertEqual(response.context['confirmed_count'], 1)
        
        response = self.client.get('/bookings/?status=pending')
        self.assertEqual(len(response.context['bookings']), 1)
        self.assertEqual(response.context['pending_count'], 1)
        self.assertEqual(response.context['confirmed_count'], 0)
        self.assertEqual(response.context['total_amount'], Decimal('3000000'))
    
    def test_booking_create_view(self):
        response = self.client.get('/bookings/create/')
        self.assertEqual(response.status_code, 200)
    
    def test_booking_create_post(self):
        response = self.client.post('/bookings/create/', {
            'customer': self.customer.pk,
            'plot': self.plot.pk,
            'total_amount': '5000000',
            'advance_paid': '500000'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.count(), 1)
        
        # Check plot status updated
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, 'booked')
    
    def test_booking_detail_view(self):
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user
        )
        response = self.client.get(f'/bookings/{booking.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, booking.booking_id)
    
    def test_booking_delete_resets_plot_status(self):
        # Set plot status to booked (simulating a booking workflow)
        self.plot.status = 'booked'
        self.plot.save()
        
        booking = Booking.objects.create(
            customer=self.customer, plot=self.plot,
            total_amount=Decimal('5000000'), created_by=self.user
        )
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, 'booked')
        
        response = self.client.post(f'/bookings/{booking.pk}/delete/')
        self.assertEqual(response.status_code, 302)
        
        self.plot.refresh_from_db()
        self.assertEqual(self.plot.status, 'available')
