from decimal import Decimal
from importlib import import_module

from django.apps import apps
from django.test import TestCase

from properties.models import Plot, Project, ProjectPhase

move_blocks_out = import_module('properties.migrations.0012_move_blocks_out').move_blocks_out


class BlockPhaseMigrationTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            name='Silver Oak Villas', location='L', total_plots=30, status='under_construction',
        )
        self.real = ProjectPhase.objects.create(
            project=self.project, phase_number=3, name='Phase 3',
            total_plots=10, price_per_marla=Decimal('100'),
        )
        ProjectPhase.objects.create(
            project=self.project, phase_number=1, name='Phase 1',
            total_plots=10, price_per_marla=Decimal('100'),
        )
        ProjectPhase.objects.create(
            project=self.project, phase_number=5, name='Phase 5',
            total_plots=10, price_per_marla=Decimal('100'),
        )
        self.block_a = ProjectPhase.objects.create(
            project=self.project, phase_number=90, name='Block A',
            total_plots=10, price_per_marla=Decimal('100'),
        )
        self.block_b = ProjectPhase.objects.create(
            project=self.project, phase_number=91, name='Block B',
            total_plots=10, price_per_marla=Decimal('100'),
        )

    def plot(self, number, phase, block=''):
        return Plot.objects.create(
            plot_number=number, project=self.project, phase=phase, block=block,
            size_marla=Decimal('5'), price=Decimal('100'), status='available',
        )

    def test_moves_plots_out_of_block_phases_and_sets_block(self):
        first = self.plot('A-1', self.block_a)
        second = self.plot('A-2', self.block_a, block='B')
        third = self.plot('B-1', self.block_b)

        move_blocks_out(apps, None)

        for plot in (first, second, third):
            plot.refresh_from_db()
            self.assertIsNone(plot.phase)
        self.assertEqual(first.block, 'A')
        self.assertEqual(second.block, 'B')
        self.assertEqual(third.block, 'B')
        self.assertFalse(ProjectPhase.objects.filter(name__in=['Block A', 'Block B']).exists())
        self.assertTrue(ProjectPhase.objects.filter(pk=self.real.pk).exists())

    def test_moves_to_only_real_phase_when_determinable(self):
        other = Project.objects.create(name='Other', location='L', total_plots=10)
        real = ProjectPhase.objects.create(
            project=other, phase_number=7, name='Phase 7', total_plots=10,
        )
        block = ProjectPhase.objects.create(
            project=other, phase_number=1, name='Block A', total_plots=10,
        )
        plot = Plot.objects.create(
            plot_number='A-1', project=other, phase=block, size_marla=Decimal('5'),
            price=Decimal('100'), status='available',
        )

        move_blocks_out(apps, None)

        plot.refresh_from_db()
        self.assertEqual(plot.phase_id, real.pk)
        self.assertEqual(plot.block, 'A')

    def test_collision_stops_before_changing_data(self):
        self.plot('X-1', self.block_a)
        self.plot('X-1', self.real, block='A')

        with self.assertRaises(RuntimeError):
            move_blocks_out(apps, None)

        self.assertTrue(ProjectPhase.objects.filter(pk=self.block_a.pk).exists())
        self.assertEqual(Plot.objects.get(plot_number='X-1', phase=self.block_a).block, '')
