from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import UserProfile
from properties.forms import ProjectPhaseForm
from properties.models import Project, ProjectPhase, parse_phase_number


class PhaseNumberModelTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P', location='L', total_plots=10)
        self.other = Project.objects.create(name='Q', location='L', total_plots=10)

    def test_parse_phase_number_from_name(self):
        self.assertEqual(parse_phase_number('Phase 1'), 1)
        self.assertEqual(parse_phase_number('Phase 12'), 12)
        self.assertIsNone(parse_phase_number('Block A'))
        self.assertIsNone(parse_phase_number('Phase One'))

    def test_unique_phase_number_per_project(self):
        ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectPhase.objects.create(project=self.project, name='Duplicate', phase_number=1, total_plots=5)

    def test_same_phase_number_allowed_across_projects(self):
        ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=5)
        ProjectPhase.objects.create(project=self.other, name='Phase 1', phase_number=1, total_plots=5)
        self.assertEqual(ProjectPhase.objects.filter(phase_number=1).count(), 2)

    def test_phase_number_is_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectPhase.objects.create(project=self.project, name='Block A', total_plots=5)

    def test_default_ordering(self):
        ProjectPhase.objects.create(project=self.project, name='Phase 2', phase_number=2, total_plots=5)
        ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=5)
        ProjectPhase.objects.create(project=self.other, name='Phase 1', phase_number=1, total_plots=5)
        self.assertEqual(
            list(ProjectPhase.objects.values_list('project_id', 'phase_number', 'name')),
            [(self.project.pk, 1, 'Phase 1'), (self.project.pk, 2, 'Phase 2'), (self.other.pk, 1, 'Phase 1')],
        )


class PhaseNumberFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P', location='L', total_plots=10)

    def data(self, **kw):
        body = {
            'project': self.project.pk, 'phase_number': 1, 'name': 'Phase 1',
            'total_plots': 5, 'price_per_marla': '100', 'status': 'booking_open',
        }
        body.update(kw)
        return body

    def test_form_accepts_and_returns_phase_number(self):
        form = ProjectPhaseForm(data=self.data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['phase_number'], 1)

    def test_form_rejects_zero_phase_number(self):
        form = ProjectPhaseForm(data=self.data(phase_number=0))
        self.assertFalse(form.is_valid())
        self.assertIn('phase_number', form.errors)

    def test_form_reports_duplicate_phase_number_on_field(self):
        ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=5)
        form = ProjectPhaseForm(data=self.data(name='Another'))
        self.assertFalse(form.is_valid())
        self.assertIn('phase_number', form.errors)
        self.assertIn('already exists', str(form.errors['phase_number']))


class PhaseNumberAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'pass123456')
        self.client.force_authenticate(self.admin)
        self.project = Project.objects.create(name='P', location='L', total_plots=10)
        self.other = Project.objects.create(name='Q', location='L', total_plots=10)

    def data(self, **kw):
        body = {
            'project': self.project.pk, 'phase_number': 1, 'name': 'Phase 1',
            'total_plots': 5, 'price_per_marla': '100', 'status': 'booking_open',
        }
        body.update(kw)
        return body

    def test_api_accepts_and_returns_phase_number(self):
        response = self.client.post('/api/project-phases/', self.data(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['phase_number'], 1)

    def test_api_rejects_non_positive_phase_number(self):
        response = self.client.post('/api/project-phases/', self.data(phase_number=0), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phase_number', response.data)

    def test_api_reports_duplicate_on_phase_number_field(self):
        ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=5)
        response = self.client.post('/api/project-phases/', self.data(name='Another'), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phase_number', response.data)
        self.assertIn('already exists', str(response.data['phase_number']))

    def test_api_allows_same_number_across_projects(self):
        ProjectPhase.objects.create(project=self.project, name='Phase 1', phase_number=1, total_plots=5)
        response = self.client.post(
            '/api/project-phases/', self.data(project=self.other.pk), format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
