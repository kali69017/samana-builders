from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import Customer
from .forms import CustomerForm


class CustomerFormTest(TestCase):
    def test_valid_customer_form(self):
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': '35202-1234567-1',
            'email': 'ahmed@example.com',
            'city': 'Lahore'
        }
        form = CustomerForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_invalid_cnic_format(self):
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': 'invalid-cnic',
            'email': 'ahmed@example.com'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('cnic', form.errors)
    
    def test_invalid_phone_format(self):
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '123',
            'cnic': '35202-1234567-1',
            'email': 'ahmed@example.com'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)


class CustomerViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('testuser', 'test@example.com', 'testpass123')
        self.client.login(username='testuser', password='testpass123')
    
    def test_customer_list_view(self):
        response = self.client.get('/customers/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customers')
    
    def test_customer_create_view(self):
        response = self.client.get('/customers/create/')
        self.assertEqual(response.status_code, 200)
    
    def test_customer_create_post(self):
        response = self.client.post('/customers/create/', {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': '35202-1234567-1',
            'email': 'ahmed@example.com',
            'city': 'Lahore'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.assertEqual(Customer.objects.count(), 1)
    
    def test_customer_edit_view(self):
        customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1'
        )
        response = self.client.get(f'/customers/{customer.pk}/edit/')
        self.assertEqual(response.status_code, 200)
    
    def test_customer_delete_view(self):
        customer = Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1'
        )
        response = self.client.post(f'/customers/{customer.pk}/delete/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Customer.objects.count(), 0)
    
    def test_customer_search(self):
        Customer.objects.create(
            first_name='Ahmed', last_name='Khan',
            phone='+92-300-1234567', cnic='35202-1234567-1'
        )
        response = self.client.get('/customers/?search=Ahmed')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ahmed')
    
    def test_unauthenticated_access(self):
        self.client.logout()
        response = self.client.get('/customers/')
        self.assertEqual(response.status_code, 302)  # Redirect to login
