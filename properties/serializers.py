from decimal import Decimal

from rest_framework import serializers

from .models import (
    Project, ProjectPhase, Plot, PriceHistory, PlotFeature, ProjectMilestone,
    MARLA_TO_SQFT, SQYARD_TO_SQFT,
)


class PlotFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotFeature
        fields = ['id', 'name', 'icon']


class PlotSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    project_phase_name = serializers.CharField(source='phase.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    plot_type_display = serializers.CharField(source='get_plot_type_display', read_only=True)
    # Size is entered as a unit + value; marla/sqft are derived server-side and
    # exposed read-only (users cannot write them).
    size_unit = serializers.ChoiceField(
        choices=[('marla', 'Size in Marla'), ('sqyards', 'Size in Square Yards')], write_only=True,
    )
    size_value = serializers.DecimalField(max_digits=12, decimal_places=2, write_only=True)
    size_marla = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    size_sqft = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, allow_null=True)
    # Price is optional on input: auto-calculated from the phase, or set manually.
    price = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, allow_null=True)

    class Meta:
        model = Plot
        fields = ['id', 'plot_number', 'project', 'project_name', 'phase', 'block',
                  'street_number', 'project_phase_name', 'plot_type', 'plot_type_display',
                  'size_unit', 'size_value', 'size_marla', 'size_sqft',
                  'price', 'price_overridden', 'holding_deposit', 'status',
                  'status_display', 'is_corner', 'is_park_facing', 'facing_direction',
                  'features', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        # No auto UniqueTogetherValidator: the friendly check in validate() reports
        # duplicates under plot_number; the DB constraint stays as the backstop.
        validators = []

    def validate_size_value(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Size must be greater than 0')
        return value

    def _resolve_size(self, unit, value):
        """One place for the size conversion (reuses the model constants)."""
        value = Decimal(value)
        if unit == 'sqyards':
            sqft = (value * SQYARD_TO_SQFT).quantize(Decimal('0.01'))
            marla = (sqft / MARLA_TO_SQFT).quantize(Decimal('0.01'))
        else:
            marla = value.quantize(Decimal('0.01'))
            sqft = (marla * MARLA_TO_SQFT).quantize(Decimal('0.01'))
        return marla, sqft

    def validate(self, attrs):
        # Size: only resolve if both unit and value provided (create) or on full update.
        size_unit = attrs.get('size_unit')
        size_value = attrs.get('size_value')
        if size_unit is not None and size_value is not None:
            marla, sqft = self._resolve_size(size_unit, size_value)
            attrs['size_marla'] = marla
            attrs['size_sqft'] = sqft
        else:
            # On partial update without size fields: keep existing derived sizes.
            if self.instance:
                attrs['size_marla'] = self.instance.size_marla
                attrs['size_sqft'] = self.instance.size_sqft
        attrs.pop('size_unit', None)
        attrs.pop('size_value', None)

        marla = attrs.get('size_marla')
        project = attrs.get('project', getattr(self.instance, 'project', None) if self.instance else None)
        phase = attrs.get('phase', getattr(self.instance, 'phase', None) if self.instance else None)

        if phase is not None and project is not None and phase.project_id != project.id:
            raise serializers.ValidationError({'phase': 'The phase must belong to the selected project.'})
        if phase is None and project is not None and project.phases.exists():
            raise serializers.ValidationError({'phase': 'Select a phase: this project has phases defined.'})
        if phase is not None:
            existing = phase.plots.count()
            if self.instance and self.instance.phase_id == phase.pk:
                existing -= 1
            if existing + 1 > phase.total_plots:
                raise serializers.ValidationError(
                    {'phase': f'Phase capacity reached: this phase allows {phase.total_plots} plots.'}
                )

        # Price: auto-fill from the phase on create only. Once a plot exists the
        # stored price is a snapshot and is never recalculated from the phase.
        manual_price = 'price' in attrs
        if self.instance is not None:
            if not manual_price:
                attrs['price'] = self.instance.price
                attrs['price_overridden'] = getattr(self.instance, 'price_overridden', False)
            else:
                price = attrs.get('price')
                if price is None or price <= 0:
                    raise serializers.ValidationError({'price': 'Price must be greater than 0.'})
                attrs['price_overridden'] = True
        elif not manual_price:
            if phase is not None and phase.price_per_marla:
                attrs['price'] = (phase.price_per_marla * marla).quantize(Decimal('0.01'))
                attrs['price_overridden'] = False
            else:
                raise serializers.ValidationError(
                    {'price': 'Price must be greater than 0. It is auto-calculated from the phase '
                              'price per marla, or set a manual price.'}
                )
        else:
            price = attrs.get('price')
            if price is None or price <= 0:
                raise serializers.ValidationError({'price': 'Price must be greater than 0.'})
            attrs['price_overridden'] = True

        # On partial update, only validate holding_deposit if it's being changed.
        if 'holding_deposit' in attrs or self.instance is None:
            deposit = attrs.get('holding_deposit', getattr(self.instance, 'holding_deposit', None) if self.instance else None)
            if deposit is None or deposit <= 0:
                raise serializers.ValidationError({'holding_deposit': 'Holding deposit must be greater than 0.'})
            if deposit > attrs['price']:
                raise serializers.ValidationError({'holding_deposit': 'Holding deposit cannot exceed the price.'})

        # Friendly uniqueness check (kept in the serializer so the message lands on
        # plot_number instead of DRF's non-field unique-together error).
        if project is not None and attrs.get('plot_number'):
            dup = Plot.objects.filter(
                project=project,
                block=attrs.get('block') or '',
                plot_number=attrs.get('plot_number'),
            )
            if self.instance is not None:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                raise serializers.ValidationError(
                    {'plot_number': 'A plot with this number already exists in this project and block. '
                                    'Plot numbers must be unique per project and block.'}
                )

        if self.instance is None and attrs.get('status', 'available') in ('booked', 'sold', 'cancelled'):
            raise serializers.ValidationError(
                {'status': 'Booked, Sold and Cancelled can only be set by the booking/payment flow.'}
            )

        return attrs


class PlotDetailSerializer(serializers.ModelSerializer):
    """Detailed plot with price history and full related data."""
    project_name = serializers.CharField(source='project.name', read_only=True)
    project_phase_name = serializers.CharField(source='phase.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    plot_type_display = serializers.CharField(source='get_plot_type_display', read_only=True)
    features = PlotFeatureSerializer(many=True, read_only=True)
    price_history = serializers.SerializerMethodField()

    class Meta:
        model = Plot
        fields = ['id', 'plot_number', 'project', 'project_name', 'phase',
                  'project_phase_name', 'plot_type', 'plot_type_display',
                  'size_marla', 'size_sqft', 'price', 'price_overridden',
                  'holding_deposit', 'status', 'status_display', 'block', 'street_number',
                  'is_corner', 'is_park_facing', 'facing_direction', 'features',
                  'price_history', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_price_history(self, obj):
        history = PriceHistory.objects.filter(plot=obj).order_by('-changed_at')[:10]
        return PriceHistorySerializer(history, many=True).data


class PriceHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True, allow_null=True)

    class Meta:
        model = PriceHistory
        fields = ['id', 'plot', 'old_price', 'new_price', 'change_reason',
                  'changed_by', 'changed_by_name', 'changed_at']
        read_only_fields = ['id', 'changed_at']


class ProjectPhaseSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)  # writable so nested edits can reference existing phases
    available_plots = serializers.SerializerMethodField()
    is_sold_out = serializers.ReadOnlyField()

    class Meta:
        model = ProjectPhase
        fields = ['id', 'project', 'phase_number', 'name', 'description', 'launch_date',
                  'total_plots', 'available_plots', 'is_sold_out', 'price_per_marla', 'status']
        # Friendly duplicate message is raised from validate(); keep the DB
        # constraint as the backstop.
        validators = []

    def get_available_plots(self, obj):
        return obj.plots.filter(status='available').count()

    def validate_phase_number(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Phase number must be greater than 0.')
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        number = attrs.get('phase_number', getattr(self.instance, 'phase_number', None))
        project = attrs.get('project', getattr(self.instance, 'project', None))
        if number is not None and project is not None:
            duplicate = ProjectPhase.objects.filter(project=project, phase_number=number)
            if self.instance is not None:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError(
                    {'phase_number': 'A phase with this number already exists in this project.'}
                )
        status_value = attrs.get('status', getattr(self.instance, 'status', None))
        if project is not None and project.status in ('completed', 'inactive') and status_value == 'booking_open':
            raise serializers.ValidationError(
                {'status': 'Phases cannot be Booking Open when the project is Completed or Inactive.'}
            )
        return attrs

    def validate_total_plots(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Total plots must be greater than 0')
        return value

    def validate_price_per_marla(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Price per marla must be greater than 0')
        return value


class _NestedProjectPhaseSerializer(ProjectPhaseSerializer):
    """Phase representation nested inside a project: project is parent-set."""

    class Meta(ProjectPhaseSerializer.Meta):
        fields = ['id', 'phase_number', 'name', 'description', 'launch_date',
                  'total_plots', 'available_plots', 'is_sold_out', 'price_per_marla', 'status']


class ProjectSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    available_plots = serializers.ReadOnlyField()
    booked_plots = serializers.ReadOnlyField()
    sold_plots = serializers.ReadOnlyField()
    total_phase_plots = serializers.SerializerMethodField()
    phases = _NestedProjectPhaseSerializer(many=True, required=False)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'location', 'total_plots',
                  'status', 'status_display', 'available_plots', 'booked_plots', 'sold_plots',
                  'total_phase_plots', 'phases', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_total_phase_plots(self, obj):
        return sum((p.total_plots or 0) for p in obj.phases.all())

    def _effective_phases(self, attrs):
        """Return the phases that will exist after this save (merge existing for rules)."""
        if attrs.get('phases') is not None:
            return attrs['phases']
        if self.instance is not None:
            return [{'status': p.status, 'total_plots': p.total_plots} for p in self.instance.phases.all()]
        return []

    def validate(self, attrs):
        status_ = attrs.get('status', getattr(self.instance, 'status', None) if self.instance else None)
        total_plots = attrs.get('total_plots', getattr(self.instance, 'total_plots', 0) if self.instance else 0)
        phases = self._effective_phases(attrs)

        if not phases and status_ != 'coming_soon':
            raise serializers.ValidationError(
                {'phases': 'A project must have at least one phase unless its status is Coming Soon.'}
            )
        if status_ in ('completed', 'inactive'):
            for ph in phases:
                if ph.get('status') == 'booking_open':
                    raise serializers.ValidationError(
                        {'phases': 'Phases cannot be Booking Open when the project is Completed or Inactive.'}
                    )
        if phases:
            attrs['total_plots'] = sum(Decimal(str(ph.get('total_plots') or 0)) for ph in phases)
        elif self.instance is not None and attrs.get('phases') is None and self.instance.phases.exists():
            attrs['total_plots'] = sum(
                Decimal(str(p.total_plots or 0)) for p in self.instance.phases.all()
            )
        seen_numbers = set()
        for ph in phases:
            number = ph.get('phase_number')
            if number is None:
                continue
            if number in seen_numbers:
                raise serializers.ValidationError(
                    {'phases': f'Phase number {number} is used more than once in this project.'}
                )
            seen_numbers.add(number)
        return attrs

    def create(self, validated_data):
        phases = validated_data.pop('phases', [])
        project = Project.objects.create(**validated_data)
        for pdata in phases:
            ProjectPhase.objects.create(project=project, **pdata)
        return project

    def update(self, instance, validated_data):
        phases = validated_data.pop('phases', None)
        project = super().update(instance, validated_data)
        if phases is not None:
            seen = set()
            for pdata in phases:
                pid = pdata.pop('id', None)
                if pid:
                    phase = ProjectPhase.objects.get(pk=pid, project=project)
                    for key, value in pdata.items():
                        setattr(phase, key, value)
                    phase.save()
                    seen.add(phase.pk)
                else:
                    phase = ProjectPhase.objects.create(project=project, **pdata)
                    seen.add(phase.pk)
            for old in project.phases.exclude(pk__in=seen):
                if old.plots.exists():
                    raise serializers.ValidationError(
                        {'phases': f'Phase "{old.name}" already has plots and cannot be removed.'}
                    )
                old.delete()
        return project


class ProjectMilestoneSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectMilestone
        fields = ['id', 'project', 'project_name', 'title', 'description',
                  'target_date', 'completed_date', 'status', 'status_display',
                  'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']