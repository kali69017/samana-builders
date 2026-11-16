from django.db import migrations


DROPPED_FEATURES = {
    'corner': {'is_corner': True},
    'corner plot': {'is_corner': True},
    'street corner': {'is_corner': True},
    'park facing': {'is_park_facing': True},
    'park view': {'is_park_facing': True},
    'south facing': {'facing_direction': 'S'},
}


def dedupe_features(apps, schema_editor):
    PlotFeature = apps.get_model('properties', 'PlotFeature')
    mapping = {}

    for feature in PlotFeature.objects.all():
        key = feature.name.strip().lower()
        changes = DROPPED_FEATURES.get(key)
        if not changes:
            continue
        for plot in feature.plot_set.all():
            if changes.get('is_corner'):
                plot.is_corner = True
            if changes.get('is_park_facing'):
                plot.is_park_facing = True
            if changes.get('facing_direction') and not plot.facing_direction:
                plot.facing_direction = changes['facing_direction']
            plot.save()
            plot.features.remove(feature)
        mapping[feature.name] = 'removed; transferred to plot flags'
        feature.delete()

    wide = PlotFeature.objects.filter(name__iexact='Wide Road').first()
    wider = PlotFeature.objects.filter(name__iexact='Wider Road').first()
    if wider:
        if wide is None:
            wider.name = 'Wide Road'
            wider.save(update_fields=['name'])
            mapping['Wider Road'] = 'renamed to Wide Road'
        else:
            for plot in wider.plot_set.all():
                plot.features.add(wide)
            mapping['Wider Road'] = 'merged into Wide Road'
            wider.delete()

    for old, action in sorted(mapping.items()):
        print(f'Plot feature migration: {old} -> {action}')


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0013_phase_number_required'),
    ]

    operations = [
        migrations.RunPython(dedupe_features, migrations.RunPython.noop),
    ]
