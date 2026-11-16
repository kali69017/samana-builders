import re

from django.db import migrations


def _block_letter(name):
    match = re.fullmatch(r'\s*Block\s+([A-Za-z])\s*', name or '')
    return match.group(1).upper() if match else None


def move_blocks_out(apps, schema_editor):
    ProjectPhase = apps.get_model('properties', 'ProjectPhase')
    Plot = apps.get_model('properties', 'Plot')
    Booking = apps.get_model('bookings', 'Booking')

    block_phases = [
        phase for phase in ProjectPhase.objects.select_related('project')
        if _block_letter(phase.name)
    ]
    if not block_phases:
        return

    block_phase_ids = {phase.pk for phase in block_phases}
    planned = []
    for phase in block_phases:
        letter = _block_letter(phase.name)
        for plot in Plot.objects.filter(phase_id=phase.pk):
            planned.append((plot, letter, plot.block or letter))

    # Collision pre-check: never guess when two plots would share the same
    # (project, block, plot_number) key after the move.
    planned_pks = {plot.pk for plot, _letter, _block in planned}
    planned_keys = {}
    collisions = []
    for plot, _letter, target_block in planned:
        key = (plot.project_id, target_block, plot.plot_number)
        if key in planned_keys:
            collisions.append((plot.project_id, target_block, plot.plot_number))
        planned_keys[key] = plot.pk
    for plot, _letter, target_block in planned:
        existing = Plot.objects.filter(
            project_id=plot.project_id,
            block=target_block,
            plot_number=plot.plot_number,
        ).exclude(pk__in=planned_pks)
        if existing.exists():
            collisions.append((plot.project_id, target_block, plot.plot_number))
    if collisions:
        details = ', '.join(f'project {project} block {block} plot {number}'
                            for project, block, number in sorted(set(collisions)))
        raise RuntimeError(f'Block migration stopped, plot collisions: {details}')

    unresolved = {}
    for phase in block_phases:
        real_phases = list(
            ProjectPhase.objects.filter(project_id=phase.project_id)
            .exclude(pk__in=block_phase_ids)
            .exclude(phase_number__isnull=True)
        )
        target_phase = real_phases[0] if len(real_phases) == 1 else None
        letter = _block_letter(phase.name)
        for plot in Plot.objects.filter(phase_id=phase.pk):
            plot.block = plot.block or letter
            plot.phase = target_phase
            plot.save(update_fields=['block', 'phase'])
            if target_phase is None:
                unresolved.setdefault(phase.project.name, []).append(plot.plot_number)

    for project_name, plot_numbers in unresolved.items():
        print(
            f'Block migration: {project_name} plots left with no phase '
            f'(could not determine a real phase): {", ".join(plot_numbers)}'
        )

    for phase in block_phases:
        if phase.plots.exists():
            print(f'Block migration: kept phase "{phase.name}" because it still has plots')
            continue
        if Booking.objects.filter(plot__phase=phase).exists():
            print(f'Block migration: kept phase "{phase.name}" because it still has bookings')
            continue
        phase.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0011_phase_status_choices'),
        ('bookings', '0005_booking_cancelled_at_booking_cancelled_by_and_more'),
    ]

    operations = [
        migrations.RunPython(move_blocks_out, migrations.RunPython.noop),
    ]
