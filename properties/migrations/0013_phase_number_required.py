import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0012_move_blocks_out'),
    ]

    operations = [
        migrations.AlterField(
            model_name='projectphase',
            name='phase_number',
            field=models.PositiveIntegerField(
                help_text='Society-style phase number, for example 3 in Phase 3',
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
    ]
