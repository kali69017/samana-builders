"""Business-rule tests for the Project and Plot APIs (the backend source of truth).

Covers: phase total plot sum <= project total, zero phases only for Coming Soon,
no Booking Open phases on Completed/Inactive projects, plot size conversion,
holding deposit <= price, creatable statuses, phase capacity, phase required when
the project has phases, price auto-fill, and (project, block, plot_number) uniqueness.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile
from properties.models import Project, ProjectPhase, Plot


class PropertiesRulesTestCase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@example.com', 'pass123456')
        self.client.force_authenticate(user=self.admin)

    def _project(self, **kw):
        defaults = dict(name='Rules', location='Karachi', total_plots=10, status='booking_open')
        defaults.update(kw)
        return Project.objects.create(**defaults)

    def _phase(self, project, name='Ph A', status_='booking_open', price_per_marla=None):
        return ProjectPhase.objects.create(
            project=project, phase_number=1, name=name, total_plots=10, status=status_,
            price_per_marla=price_per_marla if price_per_marla is not None else Decimal('100'),
        )

    def _plot(self, project, phase=None, block='A', number='P-1'):
        return Plot.objects.create(
            plot_number=number, project=project, phase=phase, block=block,
            plot_type='residential', size_marla=Decimal('5'), size_sqft=Decimal('1361.25'),
            price=Decimal('500000'), holding_deposit=Decimal('50000'), status='available',
        )


class ProjectRulesTests(PropertiesRulesTestCase):
    def phase_post(self, **kw):
        body = {
            'phase_number': 1, 'name': 'Phase One', 'total_plots': 4,
            'price_per_marla': '100', 'status': 'booking_open',
        }
        body.update(kw)
        return body

    def test_phase_sum_derives_project_total(self):
        resp = self.client.post(reverse('project-list'), {
            'name': 'Big', 'location': 'L', 'total_plots': 5, 'status': 'booking_open',
            'phases': [
                self.phase_post(name='A', phase_number=1, total_plots=4),
                self.phase_post(name='B', phase_number=2, total_plots=2),
            ],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['total_plots'], 6)
        self.assertEqual(Project.objects.get(name='Big').total_plots, 6)

    def test_phase_sum_within_total_creates_phases(self):
        resp = self.client.post(reverse('project-list'), {
            'name': 'Ok', 'location': 'L', 'total_plots': 6, 'status': 'booking_open',
            'phases': [
                self.phase_post(name='A', phase_number=1, total_plots=4),
                self.phase_post(name='B', phase_number=2, total_plots=2),
            ],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        project = Project.objects.get(pk=resp.data['id'])
        self.assertEqual(project.phases.count(), 2)

    def test_zero_phases_only_for_coming_soon(self):
        resp = self.client.post(reverse('project-list'), {
            'name': 'NoPhases', 'location': 'L', 'total_plots': 5, 'status': 'booking_open',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        resp2 = self.client.post(reverse('project-list'), {
            'name': 'NoPhases', 'location': 'L', 'total_plots': 5, 'status': 'coming_soon',
        }, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)

    def test_completed_project_phases_cannot_be_booking_open(self):
        resp = self.client.post(reverse('project-list'), {
            'name': 'Done', 'location': 'L', 'total_plots': 5, 'status': 'completed',
            'phases': [self.phase_post(name='A', status='booking_open')],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phases', resp.data)


class PlotRulesTests(PropertiesRulesTestCase):
    def plot_post(self, project, phase=None, **kw):
        body = {
            'plot_number': 'P-1', 'project': project.pk, 'phase': phase.pk if phase else None,
            'block': 'A', 'plot_type': 'residential',
            'size_unit': 'marla', 'size_value': '5',
            'price': '500000', 'holding_deposit': '50000', 'status': 'available',
        }
        body.update(kw)
        if body.get('price') in (None, ''):
            body.pop('price', None)
        return body

    def test_size_conversion_marla(self):
        project = self._project()
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, size_value='5'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(resp.data['size_marla']), Decimal('5.00'))
        self.assertEqual(Decimal(resp.data['size_sqft']), Decimal('1361.25'))

    def test_size_conversion_square_yards(self):
        project = self._project()
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, size_unit='sqyards', size_value='90'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(resp.data['size_sqft']), Decimal('810.00'))
        self.assertEqual(Decimal(resp.data['size_marla']), Decimal('2.98'))

    def test_holding_deposit_cannot_exceed_price(self):
        project = self._project()
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, holding_deposit='600000'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('holding_deposit', resp.data)

    def test_holding_deposit_must_be_positive(self):
        project = self._project()
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, holding_deposit='0'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('holding_deposit', resp.data)

    def test_booked_sold_cancelled_not_creatable(self):
        project = self._project()
        for bad in ('booked', 'sold', 'cancelled'):
            resp = self.client.post(reverse('plot-list'), self.plot_post(project, status=bad), format='json')
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, bad)
            self.assertIn('status', resp.data)

    def test_creatable_statuses_allowed(self):
        project = self._project()
        for i, ok in enumerate(('available', 'on_hold', 'reserved')):
            resp = self.client.post(
                reverse('plot-list'),
                self.plot_post(project, status=ok, plot_number='CREATABLE-%d' % i),
                format='json',
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, ok)

    def test_phase_capacity_rejects_overfill(self):
        project = self._project()
        phase = self._phase(project)  # total_plots 10
        self._plot(project, phase=phase)  # fills 1
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, phase=phase, plot_number='P-2'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)  # 2 <= 10 ok
        # Reduce capacity and try again
        phase.total_plots = 2
        phase.save()
        resp2 = self.client.post(reverse('plot-list'), self.plot_post(project, phase=phase, plot_number='P-3'), format='json')
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phase', resp2.data)

    def test_phase_required_when_project_has_phases(self):
        project = self._project()
        self._phase(project)
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, phase=None), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phase', resp.data)

    def test_price_autofill_from_phase_when_not_overridden(self):
        project = self._project()
        phase = self._phase(project, price_per_marla=Decimal('100'))
        resp = self.client.post(
            reverse('plot-list'),
            self.plot_post(project, phase=phase, price=None, holding_deposit='100'),
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(resp.data['price']), Decimal('500.00'))
        self.assertFalse(resp.data['price_overridden'])

    def test_manual_price_is_marked_overridden(self):
        project = self._project()
        phase = self._phase(project, price_per_marla=Decimal('100'))
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, phase=phase, price='999999'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(resp.data['price']), Decimal('999999'))
        self.assertTrue(resp.data['price_overridden'])

    def test_uniqueness_per_project_block_number(self):
        project = self._project()
        self._plot(project, block='A', number='P-1')
        # Same project+block+number -> friendly duplicate error.
        resp = self.client.post(reverse('plot-list'), self.plot_post(project, plot_number='P-1'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('plot_number', resp.data)
        self.assertIn('already exists', str(resp.data['plot_number']))
        # Same number in a different block is allowed.
        resp2 = self.client.post(reverse('plot-list'), self.plot_post(project, block='B', plot_number='P-1'), format='json')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)