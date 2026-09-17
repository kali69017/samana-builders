from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from .models import Project, Plot
from .forms import ProjectForm, PlotForm


class ProjectFormTest(TestCase):
    def test_valid_project_form(self):
        form_data = {
            'name': 'Test Project',
            'location': 'Lahore',
            'total_plots': 100,
            'status': 'booking_open'
        }
        form = ProjectForm(data=form_data)
        self.assertTrue(form.is_valid())


class PlotFormTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            name='Test Project', location='Lahore', total_plots=100
        )
    
    def test_valid_plot_form(self):
        form_data = {
            'plot_number': 'A-101',
            'project': self.project.pk,
            'plot_type': 'residential',
            'size_marla': '5.00',
            'price': '5000000',
            'holding_deposit': '0',
            'status': 'available'
        }
        form = PlotForm(data=form_data)
        self.assertTrue(form.is_valid())
    
    def test_invalid_price(self):
        form_data = {
            'plot_number': 'A-101',
            'project': self.project.pk,
            'plot_type': 'residential',
            'size_marla': '5.00',
            'price': '-100',
            'holding_deposit': '0',
            'status': 'available'
        }
        form = PlotForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('price', form.errors)


class PropertyViewTest(TestCase):
    def setUp(self):
            self.client = Client()
            self.user = User.objects.create_user('testuser', 'test@example.com', 'testpass123')
            # project/plot create now require management_or_above; give the test
            # user an admin profile so they pass the gate.
            from core.models import UserProfile
            UserProfile.objects.create(user=self.user, role='admin')
            self.client.login(username='testuser', password='testpass123')
            self.project = Project.objects.create(
                name='Test Project', location='Lahore', total_plots=100
            )
    
    def test_properties_list_view(self):
        response = self.client.get('/properties/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Properties')
    
    def test_project_create_view(self):
        response = self.client.get('/properties/project/create/')
        self.assertEqual(response.status_code, 200)
    
    def test_project_create_post(self):
        response = self.client.post('/properties/project/create/', {
            'name': 'New Project',
            'location': 'Karachi',
            'total_plots': 50,
            'status': 'coming_soon'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.count(), 2)
    
    def test_plot_create_view(self):
        response = self.client.get('/properties/plot/create/')
        self.assertEqual(response.status_code, 200)
    
    def test_plot_create_post(self):
        response = self.client.post('/properties/plot/create/', {
            'plot_number': 'B-201',
            'project': self.project.pk,
            'plot_type': 'commercial',
            'size_marla': '10.00',
            'price': '10000000',
            'holding_deposit': '0',
            'status': 'available'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Plot.objects.count(), 1)
    
    def test_plot_filter_by_status(self):
        Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
            status='available'
        )
        Plot.objects.create(
            plot_number='A-102', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
            status='booked'
        )
        response = self.client.get('/properties/?status=available')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A-101')
        self.assertNotContains(response, 'A-102')
    
    def test_available_plots_count_in_context(self):
        Plot.objects.create(
            plot_number='A-101', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
            status='available'
        )
        Plot.objects.create(
            plot_number='A-102', project=self.project,
            size_marla=Decimal('5.00'), price=Decimal('5000000'),
            status='booked'
        )
        response = self.client.get('/properties/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['available_plots_count'], 1)
