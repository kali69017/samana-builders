from django.contrib.auth.models import User
from django.test import TestCase

from customers.forms import CustomerForm
from customers.models import Customer
from customers.serializers import CustomerCreateSerializer


class CustomerNameLengthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('name', 'name@example.com', 'pass123456')
        self.client.login(username='name', password='pass123456')

    def test_model_form_and_serializer_limit_is_100(self):
        self.assertEqual(Customer._meta.get_field('first_name').max_length, 100)
        self.assertEqual(Customer._meta.get_field('last_name').max_length, 100)
        self.assertEqual(CustomerForm.base_fields['first_name'].max_length, 100)
        self.assertEqual(CustomerForm.base_fields['last_name'].max_length, 100)
        self.assertEqual(CustomerCreateSerializer().fields['first_name'].max_length, 100)
        self.assertEqual(CustomerCreateSerializer().fields['last_name'].max_length, 100)

    def test_long_name_shows_length_error_instead_of_truncating(self):
        response = self.client.post('/customers/create/', {
            'first_name': 'X' * 101,
            'last_name': 'Test',
            'email': 'long@example.com',
            'phone': '+92-300-7777701',
            'cnic': '3740577777012',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'at most 100 characters')
        self.assertFalse(Customer.objects.filter(email='long@example.com').exists())

    def test_100_character_name_saves(self):
        name = 'X' * 100
        response = self.client.post('/customers/create/', {
            'first_name': name,
            'last_name': 'Test',
            'email': 'limit@example.com',
            'phone': '+92-300-7777702',
            'cnic': '3740577777022',
        })
        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(email='limit@example.com')
        self.assertEqual(customer.first_name, name)
