from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from properties.forms import ProjectPhaseFormSet
from properties.models import Plot, Project, ProjectPhase


class ProjectPhaseStatusModelTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P', location='L', total_plots=10)

    def test_sold_out_is_derived(self):
        phase = ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=2)
        self.assertFalse(phase.is_sold_out)
        Plot.objects.create(plot_number='S-1', project=self.project, phase=phase,
                            size_marla=Decimal('5'), price=Decimal('100'), status='sold')
        self.assertFalse(phase.is_sold_out)
        Plot.objects.create(plot_number='S-2', project=self.project, phase=phase,
                            size_marla=Decimal('5'), price=Decimal('100'), status='sold')
        self.assertTrue(phase.is_sold_out)

    def test_sold_out_is_false_for_zero_capacity(self):
        phase = ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=0)
        self.assertFalse(phase.is_sold_out)


class ProjectFormStage3Tests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'pass123456')
        self.client.login(username='root', password='pass123456')

    def test_new_project_form_starts_with_zero_phase_cards(self):
        self.assertEqual(ProjectPhaseFormSet().total_form_count(), 0)
        response = self.client.get('/properties/project/create/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['formset'].total_form_count(), 0)
        self.assertContains(response, 'id="phase-empty-template"')
        self.assertContains(response, 'id="add-phase"')

    def test_phase_card_has_required_fields_and_derived_sold_out_is_not_selectable(self):
        response = self.client.get('/properties/project/create/')
        for field in ('phase_number', 'name', 'status', 'launch_date', 'total_plots',
                      'price_per_marla', 'description'):
            self.assertContains(response, f'phases-__prefix__-{field}')
        self.assertNotContains(response, 'value="sold_out"')
        self.assertContains(response, 'Plots created:')
        self.assertContains(response, 'plots allocated')

    def post_project(self, status_value='booking_open', total='1', phases=()):
        data = {
            'name': 'Derived', 'location': 'L', 'total_plots': total, 'status': status_value,
            'phases-TOTAL_FORMS': str(len(phases)), 'phases-INITIAL_FORMS': '0',
            'phases-MIN_NUM_FORMS': '0', 'phases-MAX_NUM_FORMS': '1000',
        }
        for index, phase in enumerate(phases):
            data.update({
                f'phases-{index}-phase_number': phase['phase_number'],
                f'phases-{index}-name': phase['name'],
                f'phases-{index}-total_plots': phase['total_plots'],
                f'phases-{index}-price_per_marla': phase['price_per_marla'],
                f'phases-{index}-status': phase.get('status', 'booking_open'),
            })
        return self.client.post('/properties/project/create/', data)

    def test_project_total_is_sum_of_phases_ignoring_client_value(self):
        response = self.post_project(total='1', phases=[
            {'phase_number': '1', 'name': 'Phase 1', 'total_plots': '10', 'price_per_marla': '100'},
            {'phase_number': '2', 'name': 'Phase 2', 'total_plots': '20', 'price_per_marla': '100'},
            {'phase_number': '3', 'name': 'Phase 3', 'total_plots': '30', 'price_per_marla': '100'},
        ])
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name='Derived')
        self.assertEqual(project.total_plots, 60)
        self.assertEqual(project.phases.count(), 3)

    def test_zero_phases_requires_coming_soon(self):
        response = self.post_project(status_value='booking_open', total='10')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'unless its status is Coming Soon')
        self.assertFalse(Project.objects.filter(name='Derived').exists())

    def test_coming_soon_can_have_zero_phases_and_editable_total(self):
        response = self.post_project(status_value='coming_soon', total='10')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.get(name='Derived').total_plots, 10)

    def test_phase_number_errors_render_under_the_field(self):
        response = self.post_project(total='10', phases=[
            {'phase_number': '0', 'name': '', 'total_plots': '0', 'price_per_marla': '0'},
        ])
        self.assertEqual(response.status_code, 200)
        for field in ('phase_number', 'name', 'total_plots', 'price_per_marla'):
            self.assertContains(response, f'phases-0-{field}')

    def test_remove_disabled_for_phase_with_plots(self):
        project = Project.objects.create(name='Protected', location='L', total_plots=5)
        phase = ProjectPhase.objects.create(project=project, name='Phase 1', phase_number=1, total_plots=5)
        Plot.objects.create(plot_number='P-1', project=project, phase=phase,
                            size_marla=Decimal('5'), price=Decimal('100'))
        response = self.client.get(f'/properties/project/{project.pk}/edit/')
        self.assertContains(response, 'already has plots')
        self.assertContains(response, 'disabled')

    def test_project_form_disables_submit_while_submitting(self):
        response = self.client.get('/properties/project/create/')
        self.assertContains(response, "submitBtn.disabled = true")

    def test_duplicate_phase_number_is_reported_on_the_field(self):
        response = self.post_project(total='10', phases=[
            {'phase_number': '1', 'name': 'Phase 1', 'total_plots': '5', 'price_per_marla': '100'},
            {'phase_number': '1', 'name': 'Phase 1 again', 'total_plots': '5', 'price_per_marla': '100'},
        ])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A phase with this number already exists in this project.')

    def test_project_total_read_only_when_phases_exist(self):
        project = Project.objects.create(name='With phases', location='L', total_plots=10)
        ProjectPhase.objects.create(project=project, name='Phase 1', phase_number=1, total_plots=10)
        response = self.client.get(f'/properties/project/{project.pk}/edit/')
        self.assertContains(response, 'name="total_plots"')
        self.assertContains(response, 'readonly')

    def test_sold_out_is_computed_in_list_view(self):
        project = Project.objects.create(name='Sold project', location='L', total_plots=1)
        phase = ProjectPhase.objects.create(project=project, name='Phase 1', phase_number=1, total_plots=1)
        Plot.objects.create(plot_number='S-1', project=project, phase=phase,
                            size_marla=Decimal('5'), price=Decimal('100'), status='sold')
        response = self.client.get('/properties/')
        self.assertContains(response, 'Phase 1 (Sold Out)')

    def test_completed_project_cannot_have_booking_open_phase(self):
        response = self.post_project(status_value='completed', total='10', phases=[
            {'phase_number': '1', 'name': 'Phase 1', 'total_plots': '10', 'price_per_marla': '100',
             'status': 'booking_open'},
        ])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cannot be Booking Open when the project is Completed or Inactive')


class ProjectStage3APITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'pass123456')
        self.client.force_authenticate(self.admin)

    def phase(self, number, total='10'):
        return {'phase_number': number, 'name': f'Phase {number}', 'total_plots': total,
                'price_per_marla': '100', 'status': 'booking_open'}

    def test_project_total_derived_from_phases(self):
        response = self.client.post('/api/projects/', {
            'name': 'Three', 'location': 'L', 'total_plots': 1, 'status': 'booking_open',
            'phases': [self.phase(1, '10'), self.phase(2, '20'), self.phase(3, '30')],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['total_plots'], 60)
        self.assertEqual(len(response.data['phases']), 3)

    def test_update_ignores_client_total_when_phases_exist(self):
        project = Project.objects.create(name='P', location='L', total_plots=10, status='booking_open')
        ProjectPhase.objects.create(project=project, name='Phase 1', phase_number=1, total_plots=10)
        response = self.client.patch(f'/api/projects/{project.pk}/', {'total_plots': 999}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        project.refresh_from_db()
        self.assertEqual(project.total_plots, 10)

    def test_phase_status_sold_out_is_rejected(self):
        project = Project.objects.create(name='P', location='L', total_plots=10)
        response = self.client.post('/api/project-phases/', {
            'project': project.pk, 'phase_number': 1, 'name': 'Phase 1',
            'total_plots': 10, 'price_per_marla': '100', 'status': 'sold_out',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('status', response.data)

    def test_phase_is_sold_out_is_exposed(self):
        project = Project.objects.create(name='P', location='L', total_plots=2, status='booking_open')
        phase = ProjectPhase.objects.create(project=project, name='Phase 1', phase_number=1, total_plots=2)
        Plot.objects.create(plot_number='S-1', project=project, phase=phase,
                            size_marla=Decimal('5'), price=Decimal('100'), status='sold')
        Plot.objects.create(plot_number='S-2', project=project, phase=phase,
                            size_marla=Decimal('5'), price=Decimal('100'), status='sold')
        response = self.client.get(f'/api/project-phases/{phase.pk}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_sold_out'])

    def test_duplicate_nested_phase_number_is_rejected(self):
        response = self.client.post('/api/projects/', {
            'name': 'Dup', 'location': 'L', 'total_plots': 20, 'status': 'booking_open',
            'phases': [self.phase(1), self.phase(1)],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phases', response.data)

    def test_direct_phase_rejects_booking_open_for_completed_project(self):
        project = Project.objects.create(name='Done', location='L', total_plots=10, status='completed')
        response = self.client.post('/api/project-phases/', {
            'project': project.pk, 'phase_number': 1, 'name': 'Phase 1',
            'total_plots': 10, 'price_per_marla': '100', 'status': 'booking_open',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('status', response.data)

    def test_delete_phase_with_booking_is_blocked(self):
        from bookings.models import Booking
        from customers.models import Customer
        project = Project.objects.create(name='P', location='L', total_plots=10)
        phase = ProjectPhase.objects.create(project=project, name='Phase 1', phase_number=1, total_plots=10)
        plot = Plot.objects.create(plot_number='P-1', project=project, phase=phase,
                                   size_marla=Decimal('5'), price=Decimal('100'))
        customer = Customer.objects.create(first_name='A', last_name='B', phone='03001234567',
                                           cnic='12345-1234567-1')
        Booking.objects.create(customer=customer, plot=plot, total_amount=100, advance_paid=10)
        response = self.client.delete(f'/api/project-phases/{phase.pk}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ProjectPhaseRemovalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('phaseadmin', 'phase@example.com', 'pass123456')
        self.client.login(username='phaseadmin', password='pass123456')
        self.project = Project.objects.create(
            name='Remove P', location='Lahore', total_plots=20, status='booking_open')
        self.phase1 = ProjectPhase.objects.create(
            project=self.project, phase_number=1, name='Phase 1',
            total_plots=10, price_per_marla=Decimal('100'), status='booking_open')
        self.phase2 = ProjectPhase.objects.create(
            project=self.project, phase_number=2, name='Phase 2',
            total_plots=10, price_per_marla=Decimal('100'), status='booking_open')

    def test_remove_control_is_rendered(self):
        response = self.client.get(f'/properties/project/{self.project.pk}/edit/')
        self.assertContains(response, 'remove-phase')
        self.assertContains(response, 'phases-0-DELETE')

    def test_saved_phase_can_be_deleted_through_formset(self):
        response = self.client.post(f'/properties/project/{self.project.pk}/edit/', {
            'name': 'Remove P', 'location': 'Lahore', 'total_plots': '10',
            'status': 'booking_open',
            'phases-TOTAL_FORMS': '2', 'phases-INITIAL_FORMS': '2',
            'phases-MIN_NUM_FORMS': '0', 'phases-MAX_NUM_FORMS': '1000',
            'phases-0-id': str(self.phase1.pk), 'phases-0-phase_number': '1',
            'phases-0-name': 'Phase 1', 'phases-0-total_plots': '10',
            'phases-0-price_per_marla': '100', 'phases-0-status': 'booking_open',
            'phases-1-id': str(self.phase2.pk), 'phases-1-phase_number': '2',
            'phases-1-name': 'Phase 2', 'phases-1-total_plots': '10',
            'phases-1-price_per_marla': '100', 'phases-1-status': 'booking_open',
            'phases-1-DELETE': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectPhase.objects.filter(pk=self.phase2.pk).exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.total_plots, 10)

    def test_phase_with_plot_cannot_be_deleted_through_formset(self):
        Plot.objects.create(
            plot_number='LOCK-1', project=self.project, phase=self.phase1,
            size_marla=Decimal('5'), price=Decimal('100'), status='available')
        response = self.client.post(f'/properties/project/{self.project.pk}/edit/', {
            'name': 'Remove P', 'location': 'Lahore', 'total_plots': '20',
            'status': 'booking_open',
            'phases-TOTAL_FORMS': '2', 'phases-INITIAL_FORMS': '2',
            'phases-MIN_NUM_FORMS': '0', 'phases-MAX_NUM_FORMS': '1000',
            'phases-0-id': str(self.phase1.pk), 'phases-0-phase_number': '1',
            'phases-0-name': 'Phase 1', 'phases-0-total_plots': '10',
            'phases-0-price_per_marla': '100', 'phases-0-status': 'booking_open',
            'phases-0-DELETE': 'on',
            'phases-1-id': str(self.phase2.pk), 'phases-1-phase_number': '2',
            'phases-1-name': 'Phase 2', 'phases-1-total_plots': '10',
            'phases-1-price_per_marla': '100', 'phases-1-status': 'booking_open',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProjectPhase.objects.filter(pk=self.phase1.pk).exists())

    def test_block_placeholder_is_short_hint(self):
        response = self.client.get('/properties/plot/create/')
        self.assertContains(response, 'placeholder="e.g. A, B, C"')
