from django.test import TestCase, Client
from django.contrib.auth.models import User
from decimal import Decimal
from .models import Project, ProjectPhase, Plot
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
            'size_unit': 'marla',
            'size_value': '5.00',
            'price': '5000000',
            'holding_deposit': '500000',
            'status': 'available'
        }
        form = PlotForm(data=form_data)
        self.assertTrue(form.is_valid())
        # unit + value maps to stored marla/sqft.
        self.assertEqual(form.cleaned_data['size_marla'], Decimal('5.00'))

    def test_valid_plot_form_sqyards(self):
        form_data = {
            'plot_number': 'A-102',
            'project': self.project.pk,
            'plot_type': 'residential',
            'size_unit': 'sqyards',
            'size_value': '90',
            'price': '5000000',
            'holding_deposit': '500000',
            'status': 'available'
        }
        form = PlotForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['size_sqft'], Decimal('810'))
        self.assertEqual(form.cleaned_data['size_marla'], round(Decimal('810') / Decimal('272.25'), 2))

    def test_invalid_price(self):
        form_data = {
            'plot_number': 'A-101',
            'project': self.project.pk,
            'plot_type': 'residential',
            'size_unit': 'marla',
            'size_value': '5.00',
            'price': '-100',
            'holding_deposit': '500000',
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

    def test_project_search_filters_by_name_and_plot(self):
        # Search must filter the plots and projects lists (was ignored before).
        from decimal import Decimal
        plot = Plot.objects.create(
            plot_number='A-101', project=self.project, size_marla=Decimal('5.00'),
            price=Decimal('5000000'), status='available',
        )
        other = Project.objects.create(name='Other Estate', location='Karachi', total_plots=10)
        Plot.objects.create(
            plot_number='Z-999', project=other, size_marla=Decimal('5.00'),
            price=Decimal('5000000'), status='available',
        )

        resp = self.client.get('/properties/', {'search': 'Test Project'})
        self.assertContains(resp, 'Test Project')
        self.assertContains(resp, 'A-101')
        self.assertNotContains(resp, 'Other Estate')
        self.assertNotContains(resp, 'Z-999')
        self.assertEqual(resp.context['plots'].count(), 1)

        resp2 = self.client.get('/properties/', {'search': 'A-101'})
        self.assertContains(resp2, 'A-101')
        self.assertEqual(resp2.context['plots'].count(), 1)

    def test_plot_price_json_endpoint(self):
        """The booking form's auto-fill source returns the plot's real price/holding."""
        from decimal import Decimal
        plot = Plot.objects.create(
            plot_number='A-101', project=self.project, size_marla=Decimal('5.00'),
            price=Decimal('1185600'), status='available',
        )
        resp = self.client.get(f'/properties/plot/{plot.pk}/price/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['id'], plot.pk)
        self.assertEqual(data['price'], '1185600.00')
        self.assertEqual(data['total_cost'], '1185600.00')
        self.assertEqual(data['holding_deposit'], '0.00')
    
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
            'size_unit': 'marla',
            'size_value': '10.00',
            'price': '10000000',
            'holding_deposit': '500000',
            'status': 'available'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Plot.objects.count(), 1)

    def test_project_create_with_phases_web(self):
        resp = self.client.post('/properties/project/create/', {
            'name': 'Phased', 'location': 'L', 'total_plots': 10, 'status': 'booking_open',
            'phases-TOTAL_FORMS': '2', 'phases-INITIAL_FORMS': '0',
            'phases-MIN_NUM_FORMS': '0', 'phases-MAX_NUM_FORMS': '1000',
            'phases-0-phase_number': '1',
            'phases-0-name': 'Phase One', 'phases-0-total_plots': '6', 'phases-0-price_per_marla': '100',
            'phases-0-status': 'booking_open',
            'phases-1-phase_number': '2',
            'phases-1-name': 'Phase Two', 'phases-1-total_plots': '4', 'phases-1-price_per_marla': '100',
            'phases-1-status': 'booking_open',
        })
        self.assertEqual(resp.status_code, 302)
        project = Project.objects.get(name='Phased')
        self.assertEqual(project.phases.count(), 2)

    def test_project_total_derived_from_phase_sum_web(self):
        resp = self.client.post('/properties/project/create/', {
            'name': 'Over', 'location': 'L', 'total_plots': 5, 'status': 'booking_open',
            'phases-TOTAL_FORMS': '2', 'phases-INITIAL_FORMS': '0',
            'phases-MIN_NUM_FORMS': '0', 'phases-MAX_NUM_FORMS': '1000',
            'phases-0-phase_number': '1',
            'phases-0-name': 'A', 'phases-0-total_plots': '4', 'phases-0-price_per_marla': '100',
            'phases-0-status': 'booking_open',
            'phases-1-phase_number': '2',
            'phases-1-name': 'B', 'phases-1-total_plots': '2', 'phases-1-price_per_marla': '100',
            'phases-1-status': 'booking_open',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Project.objects.get(name='Over').total_plots, 6)

    def test_plot_create_with_phase_web(self):
        phase = ProjectPhase.objects.create(project=self.project, phase_number=1, name='Ph',
                                            total_plots=10, status='booking_open',
                                            price_per_marla=100)
        resp = self.client.post('/properties/plot/create/', {
            'plot_number': 'C-301', 'project': self.project.pk, 'phase': phase.pk,
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'price': '500000', 'holding_deposit': '50000', 'status': 'available',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Plot.objects.filter(plot_number='C-301').exists())

    def test_plot_duplicate_web_shows_friendly_error(self):
        Plot.objects.create(plot_number='D-1', project=self.project, block='A', plot_type='residential',
                            size_marla=5, size_sqft=1361.25, price=500000, holding_deposit=50000,
                            status='available')
        resp = self.client.post('/properties/plot/create/', {
            'plot_number': 'D-1', 'project': self.project.pk, 'block': 'A',
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'price': '500000', 'holding_deposit': '50000', 'status': 'available',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists in this project and block')
    
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
