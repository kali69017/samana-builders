import re

from django.db import migrations


def parse_phase_numbers(apps, schema_editor):
    ProjectPhase = apps.get_model('properties', 'ProjectPhase')
    for phase in ProjectPhase.objects.filter(phase_number__isnull=True):
        match = re.fullmatch(r'\s*Phase\s+(\d+)\s*', phase.name or '', re.IGNORECASE)
        if match:
            phase.phase_number = int(match.group(1))
            phase.save(update_fields=['phase_number'])


def reverse_parse_phase_numbers(apps, schema_editor):
    ProjectPhase = apps.get_model('properties', 'ProjectPhase')
    ProjectPhase.objects.update(phase_number=None)


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0009_phase_number'),
    ]

    operations = [
        migrations.RunPython(parse_phase_numbers, reverse_parse_phase_numbers),
    ]
