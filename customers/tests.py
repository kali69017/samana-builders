from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import Customer, CustomerNominee
from .forms import CustomerForm, CustomerNomineeForm


class CustomerFormTest(TestCase):
    def test_valid_customer_form(self):
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': '3520212345671',
            'email': 'ahmed@example.com',
            'city': 'Lahore'
        }
        form = CustomerForm(data=form_data)
        self.assertTrue(form.is_valid())
        # stored in canonical dashed display format
        self.assertEqual(form.cleaned_data['cnic'], '35202-1234567-1')

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

    def test_cnic_with_dashes_accepted_and_canonicalized(self):
        # Dashed input is accepted for usability (paste / edit prefill) and
        # stored in the canonical format.
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': '35202-1234567-1',  # dashes stripped, then validated
            'email': 'ahmed@example.com'
        }
        form = CustomerForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['cnic'], '35202-1234567-1')

    def test_cnic_too_short_rejected(self):
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': '35202123456',  # 11 digits
            'email': 'ahmed@example.com'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('cnic', form.errors)

    def test_cnic_with_letters_rejected(self):
        form_data = {
            'first_name': 'Ahmed',
            'last_name': 'Khan',
            'phone': '+92-300-1234567',
            'cnic': '35202123456AB',
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
            'cnic': '3520212345671',
            'email': 'ahmed@example.com'
        }
        form = CustomerForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_nominee_cnic_valid_13_digits(self):
        form = CustomerNomineeForm(data={
            'nominee_name': 'Ali Raza',
            'nominee_cnic': '3740523456789',
            'nominee_phone': '+92-300-1234567',
            'relationship': 'Father',
        })
        self.assertTrue(form.is_valid(), form.errors)
        # stored in canonical dashed format
        self.assertEqual(form.cleaned_data['nominee_cnic'], '37405-2345678-9')

    def test_nominee_cnic_with_dashes_accepted_and_canonicalized(self):
        # Dashed input is accepted for usability (paste / edit prefill) and
        # stored in the canonical format.
        form = CustomerNomineeForm(data={
            'nominee_name': 'Ali Raza',
            'nominee_cnic': '37405-2345678-9',
            'nominee_phone': '+92-300-1234567',
            'relationship': 'Father',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['nominee_cnic'], '37405-2345678-9')

    def test_nominee_cnic_too_short_rejected(self):
        form = CustomerNomineeForm(data={
            'nominee_name': 'Ali Raza',
            'nominee_cnic': '3740523456',
            'nominee_phone': '+92-300-1234567',
            'relationship': 'Father',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('nominee_cnic', form.errors)

    def test_nominee_cnic_optional(self):
        form = CustomerNomineeForm(data={
            'nominee_name': 'Ali Raza',
            'nominee_cnic': '',
            'nominee_phone': '+92-300-1234567',
            'relationship': 'Father',
        })
        self.assertTrue(form.is_valid(), form.errors)


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
            'cnic': '3520212345671',
            'email': 'ahmed@example.com',
            'city': 'Lahore'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.assertEqual(Customer.objects.count(), 1)
        # stored in canonical dashed format
        self.assertEqual(Customer.objects.first().cnic, '35202-1234567-1')
    
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


class CnicMaxLengthTests(TestCase):
    """Regression: the CNIC inputs must hard-cap at 13 characters.

    The model stores the canonical dashed form (15 chars), so Django's
    ModelForm would otherwise render maxlength="15" from the model field.
    The form __init__ must override it to 13 (the actual bug reported).
    """

    def setUp(self):
        self.user = User.objects.create_superuser('cnicadmin', 'ca@example.com', 'pass12345')
        self.customer = Customer.objects.create(
            first_name='Max', last_name='Length',
            phone='+92-300-1234567', cnic='35202-1234567-1',
            created_by=self.user,
        )

    def test_customer_cnic_input_maxlength_13(self):
        html = str(CustomerForm()['cnic'])
        self.assertIn('maxlength="13"', html)
        self.assertNotIn('maxlength="15"', html)

    def test_nominee_cnic_input_maxlength_13(self):
        html = str(CustomerNomineeForm()['nominee_cnic'])
        self.assertIn('maxlength="13"', html)
        self.assertNotIn('maxlength="15"', html)

    def test_customer_edit_prefills_raw_13_digits(self):
        form = CustomerForm(instance=self.customer)
        # Stored value is dashed (15 chars); the field must show raw 13.
        self.assertEqual(form.initial['cnic'], '3520212345671')

    def test_customer_edit_resubmit_valid(self):
        # Editing a customer used to fail because the dashed stored CNIC
        # failed the raw-13-digit validator.
        form = CustomerForm(data={
            'first_name': 'Max', 'last_name': 'Length',
            'phone': '+92-300-1234567', 'cnic': '35202-1234567-1',
            'email': '', 'alternate_phone': '', 'occupation': '',
            'occupation_other': '', 'address': '', 'city': '',
            'notes': '', 'is_active': 'on',
        }, instance=self.customer)
        self.assertTrue(form.is_valid(), form.errors)

    def test_nominee_edit_prefills_raw_13_digits(self):
        nominee = CustomerNominee.objects.create(
            customer=self.customer, nominee_name='Nom',
            nominee_cnic='35202-1234567-1', relationship='Father',
        )
        form = CustomerNomineeForm(instance=nominee)
        self.assertEqual(form.initial['nominee_cnic'], '3520212345671')

    def test_nominee_edit_resubmit_valid(self):
        nominee = CustomerNominee.objects.create(
            customer=self.customer, nominee_name='Nom',
            nominee_cnic='35202-1234567-1', relationship='Father',
        )
        form = CustomerNomineeForm(data={
            'nominee_name': 'Nom', 'nominee_cnic': '35202-1234567-1',
            'nominee_phone': '', 'relationship': 'Father',
        }, instance=nominee)
        self.assertTrue(form.is_valid(), form.errors)
