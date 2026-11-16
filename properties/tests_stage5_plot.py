from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from properties.forms import PlotForm
from properties.models import Plot, PlotFeature, Project, ProjectPhase

dedupe_features = import_module('properties.migrations.0014_dedupe_plot_features').dedupe_features


class PlotPhaseDropdownTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'pass123456')
        self.client.login(username='root', password='pass123456')
        self.project = Project.objects.create(name='P', location='L', total_plots=10)
        self.phase = ProjectPhase.objects.create(
            project=self.project, phase_number=1, name='Phase 1', total_plots=10,
            price_per_marla=Decimal('100'),
        )

    def test_unbound_form_starts_with_empty_phase_queryset(self):
        self.assertEqual(PlotForm().fields['phase'].queryset.count(), 0)

    def test_bound_form_loads_only_the_selected_projects_phases(self):
        other = Project.objects.create(name='Q', location='L', total_plots=10)
        ProjectPhase.objects.create(project=other, phase_number=1, name='Other Phase', total_plots=10)
        form = PlotForm(data={
            'plot_number': 'P-1', 'project': self.project.pk, 'phase': self.phase.pk,
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'price': '500', 'holding_deposit': '50', 'status': 'available',
        })
        self.assertEqual(list(form.fields['phase'].queryset), [self.phase])

    def test_plot_form_has_searchable_project_and_empty_initial_phase(self):
        response = self.client.get('/properties/plot/create/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].fields['phase'].queryset.count(), 0)
        self.assertContains(response, 'id="project-search"')
        self.assertContains(response, 'data-initial-phase')

    def test_plot_form_sections_and_block_hint(self):
        response = self.client.get('/properties/plot/create/')
        self.assertContains(response, 'Availability')
        self.assertContains(response, 'e.g. A, B, C')
        self.assertContains(response, 'id="plot-submit"')

    def test_form_marks_a_manual_price_edit_as_overridden(self):
        plot = Plot.objects.create(
            plot_number='P-9', project=self.project, phase=self.phase,
            size_marla=Decimal('5'), size_sqft=Decimal('1361.25'),
            price=Decimal('500'), holding_deposit=Decimal('50'), status='available',
        )
        form = PlotForm(data={
            'plot_number': plot.plot_number, 'project': self.project.pk, 'phase': self.phase.pk,
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'price': '650', 'holding_deposit': '50', 'status': 'available',
        }, instance=plot)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data['price_overridden'])
        self.assertEqual(form.cleaned_data['price'], Decimal('650'))

    def test_phase_is_required_before_the_plot_can_be_created(self):
        response = self.client.post('/properties/plot/create/', {
            'plot_number': 'P-1', 'project': self.project.pk, 'plot_type': 'residential',
            'size_unit': 'marla', 'size_value': '5', 'price': '500',
            'holding_deposit': '50', 'status': 'available',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a phase')


class PlotPriceSnapshotTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'pass123456')
        self.client.force_authenticate(self.admin)
        self.project = Project.objects.create(name='P', location='L', total_plots=10)
        self.phase = ProjectPhase.objects.create(
            project=self.project, phase_number=1, name='Phase 1', total_plots=10,
            price_per_marla=Decimal('100'),
        )

    def test_price_is_snapshot_after_create(self):
        response = self.client.post('/api/plots/', {
            'plot_number': 'P-1', 'project': self.project.pk, 'phase': self.phase.pk,
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'holding_deposit': '50', 'status': 'available',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Decimal(response.data['price']), Decimal('500.00'))

        self.phase.price_per_marla = Decimal('200')
        self.phase.save()
        patch = self.client.patch(f"/api/plots/{response.data['id']}/", {'description': 'changed'}, format='json')
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.data)
        self.assertEqual(Decimal(patch.data['price']), Decimal('500.00'))

    def test_new_plot_uses_current_phase_price(self):
        self.phase.price_per_marla = Decimal('200')
        self.phase.save()
        response = self.client.post('/api/plots/', {
            'plot_number': 'P-2', 'project': self.project.pk, 'phase': self.phase.pk,
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'holding_deposit': '50', 'status': 'available',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Decimal(response.data['price']), Decimal('1000.00'))

    def test_manual_price_is_recorded_as_overridden(self):
        response = self.client.post('/api/plots/', {
            'plot_number': 'P-3', 'project': self.project.pk, 'phase': self.phase.pk,
            'plot_type': 'residential', 'size_unit': 'marla', 'size_value': '5',
            'price': '777', 'holding_deposit': '50', 'status': 'available',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Decimal(response.data['price']), Decimal('777.00'))
        self.assertTrue(response.data['price_overridden'])


class PlotFeatureMigrationTests(TestCase):
    def test_dedupes_features_and_transfers_flags(self):
        project = Project.objects.create(name='P', location='L', total_plots=10)
        plot = Plot.objects.create(
            plot_number='P-1', project=project, size_marla=Decimal('5'), price=Decimal('100'),
        )
        names = ['Corner', 'Corner Plot', 'Street Corner', 'Park Facing', 'Park View',
                 'South Facing', 'Wide Road', 'Wider Road', 'Main Boulevard']
        features = {name: PlotFeature.objects.create(name=name) for name in names}
        for name in names:
            plot.features.add(features[name])

        dedupe_features(apps, None)

        plot.refresh_from_db()
        self.assertTrue(plot.is_corner)
        self.assertTrue(plot.is_park_facing)
        self.assertEqual(plot.facing_direction, 'S')
        remaining = set(plot.features.values_list('name', flat=True))
        self.assertEqual(remaining, {'Wide Road', 'Main Boulevard'})
        self.assertFalse(PlotFeature.objects.filter(
            name__in=['Corner', 'Corner Plot', 'Street Corner', 'Park Facing',
                      'Park View', 'South Facing', 'Wider Road']
        ).exists())

    def test_wide_road_rename_when_only_wider_exists(self):
        PlotFeature.objects.create(name='Wider Road')
        dedupe_features(apps, None)
        self.assertTrue(PlotFeature.objects.filter(name='Wide Road').exists())
        self.assertFalse(PlotFeature.objects.filter(name='Wider Road').exists())
