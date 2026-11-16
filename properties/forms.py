from django import forms
from decimal import Decimal as _Decimal
from .models import (
    Project, ProjectPhase, Plot, PlotFeature, ProjectMilestone,
    MARLA_TO_SQFT, SQYARD_TO_SQFT,
)


def resolve_size(unit, value):
    """One shared size conversion (single constants defined in models.py)."""
    value = _Decimal(str(value))
    if unit == 'sqyards':
        sqft = (value * SQYARD_TO_SQFT).quantize(_Decimal('0.01'))
        marla = (sqft / MARLA_TO_SQFT).quantize(_Decimal('0.01'))
    else:
        marla = value.quantize(_Decimal('0.01'))
        sqft = (marla * MARLA_TO_SQFT).quantize(_Decimal('0.01'))
    return marla, sqft


def phase_has_dependents(phase):
    """True when a phase has plots or bookings and must not be deleted."""
    if not phase or not phase.pk:
        return False
    if phase.plots.exists():
        return True
    from bookings.models import Booking
    return Booking.objects.filter(plot__phase=phase).exists()


def active_phase_forms(phase_forms):
    return [
        form for form in phase_forms
        if not (form.is_bound and form.cleaned_data.get('DELETE'))
    ]


def phase_total_plots(phase_forms):
    return sum(
        int(form.cleaned_data.get('total_plots') or 0) for form in active_phase_forms(phase_forms)
        if form.is_bound and form.cleaned_data.get('total_plots') is not None
    )


def get_project_phase_errors(status, total_plots, phase_forms):
    """Cross-form rules for a project and its (non-deleted) phase forms.

    Returns a list of human-readable errors; empty when the project is valid.
    Project total plots is derived from phases by the caller, so there is no
    client-supplied total to compare against.
    """
    errors = []
    active = active_phase_forms(phase_forms)

    if not active and status != 'coming_soon':
        errors.append('A project must have at least one phase unless its status is Coming Soon.')
    if status in ('completed', 'inactive'):
        statuses = [f.cleaned_data.get('status') for f in active]
        if 'booking_open' in statuses:
            errors.append('Phases cannot be Booking Open when the project is Completed or Inactive.')
    return errors


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'description', 'location', 'total_plots', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': ' '}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'total_plots': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        has_phases = bool(self.instance and self.instance.pk and self.instance.phases.exists())
        if has_phases:
            self.fields['total_plots'].widget.attrs['readonly'] = True
            self.fields['total_plots'].help_text = (
                'Derived from the phase total plots while this project has phases.'
            )
        else:
            self.fields['total_plots'].help_text = 'Editable only while the project has no phases.'


class ProjectPhaseForm(forms.ModelForm):
    class Meta:
        model = ProjectPhase
        fields = ['project', 'phase_number', 'name', 'description', 'launch_date',
                  'total_plots', 'price_per_marla', 'status']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'phase_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'step': '1'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'launch_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'total_plots': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_marla': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_delete_phase = True
        self.delete_blocked_reason = ''
        if phase_has_dependents(self.instance):
            self.can_delete_phase = False
            self.delete_blocked_reason = (
                'This phase already has plots or bookings and cannot be removed.'
            )

    def clean_phase_number(self):
        value = self.cleaned_data.get('phase_number')
        if value is not None and value <= 0:
            raise forms.ValidationError('Phase number must be greater than 0.')
        project_id = (
            self.cleaned_data.get('project').pk if self.cleaned_data.get('project')
            else getattr(self.instance, 'project_id', None)
        )
        if value is not None and project_id:
            duplicate = ProjectPhase.objects.filter(project_id=project_id, phase_number=value)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError('A phase with this number already exists in this project.')
        return value

    def clean_total_plots(self):
        value = self.cleaned_data.get('total_plots')
        if value is None or value <= 0:
            raise forms.ValidationError('Total plots must be greater than 0')
        return value

    def clean_price_per_marla(self):
        value = self.cleaned_data.get('price_per_marla')
        if value is None or value <= 0:
            raise forms.ValidationError('Price per marla must be greater than 0')
        return value


class _ProjectPhaseFormSetBase(forms.BaseInlineFormSet):
    def validate_unique(self):
        # Duplicate phase numbers are reported per field in clean(); skip the
        # generic non-form unique error so the user sees which card is wrong.
        pass

    def clean(self):
        super().clean()
        if not self.is_bound:
            return
        seen_numbers = {}
        for form in self.forms:
            if form.cleaned_data.get('DELETE') and phase_has_dependents(form.instance):
                form.add_error(
                    'DELETE',
                    'This phase already has plots or bookings and cannot be removed.',
                )
            number = form.cleaned_data.get('phase_number')
            if number is not None and not form.cleaned_data.get('DELETE'):
                if number in seen_numbers:
                    form.add_error(
                        'phase_number',
                        'A phase with this number already exists in this project.',
                    )
                else:
                    seen_numbers[number] = form


# Inline phases on the project form, so a project's phases are set where it's created.
ProjectPhaseFormSet = forms.inlineformset_factory(
    Project, ProjectPhase, form=ProjectPhaseForm, formset=_ProjectPhaseFormSetBase,
    extra=0, can_delete=True,
)


class PlotForm(forms.ModelForm):
    SIZE_UNITS = [('marla', 'Size in Marla'), ('sqyards', 'Size in Square Yards')]
    size_unit = forms.ChoiceField(
        choices=SIZE_UNITS, initial='marla', label='Size Unit',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    size_value = forms.DecimalField(
        max_digits=12, decimal_places=2, label='Size Value',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
    )

    class Meta:
        model = Plot
        fields = ['plot_number', 'project', 'phase', 'block', 'street_number',
                  'plot_type', 'size_unit', 'size_value', 'size_marla', 'size_sqft',
                  'price', 'price_overridden', 'holding_deposit', 'status',
                  'is_corner', 'is_park_facing', 'facing_direction', 'features', 'description']
        widgets = {
            'plot_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'project': forms.Select(attrs={'class': 'form-control'}),
            'phase': forms.Select(attrs={'class': 'form-control'}),
            'block': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. A, B, C'}),
            'street_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'plot_type': forms.Select(attrs={'class': 'form-control'}),
            # Derived from size_unit + size_value — hidden so the user picks one.
            'size_marla': forms.HiddenInput(),
            'size_sqft': forms.HiddenInput(),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'price_overridden': forms.HiddenInput(),
            'holding_deposit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_corner': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_park_facing': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'facing_direction': forms.Select(attrs={'class': 'form-control', 'choices': Plot.FACING_CHOICES}),
            'features': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The size fields are derived from unit+value; make the hidden ones optional so
        # the form doesn't require them directly.
        self.fields['size_marla'].required = False
        self.fields['size_sqft'].required = False
        self.fields['size_value'].required = True
        self.fields['price_overridden'].required = False

        # Prefill unit + value from the stored size when editing a plot.
        if self.instance and self.instance.pk:
            if getattr(self.instance, 'size_sqft', None):
                self.fields['size_unit'].initial = 'sqyards'
                self.fields['size_value'].initial = round(float(self.instance.size_sqft) / float(SQYARD_TO_SQFT), 2)
            else:
                self.fields['size_value'].initial = self.instance.size_marla
            # Do not auto-recalc an explicitly overridden price on edit.
            project = getattr(self.instance, 'project', None)
        else:
            project = None
            # On create only flow-selectable statuses are allowed.
            self.fields['status'].choices = [
                (k, v) for k, v in Plot.STATUS_CHOICES if k in Plot.CREATABLE_STATUSES
            ]

        # Dynamic phase queryset: start empty, then show only the chosen
        # project's phases (the client loads them on project change).
        if project is None and self.is_bound:
            project_id = self.data.get('project')
            if project_id:
                project = Project.objects.filter(pk=project_id).first()
        if project is not None:
            self.fields['phase'].queryset = project.phases.all()
        else:
            self.fields['phase'].queryset = ProjectPhase.objects.none()
        initial_phase = ''
        if self.instance and self.instance.pk:
            initial_phase = self.instance.phase_id or ''
        elif self.is_bound:
            initial_phase = self.data.get('phase', '')
        self.fields['phase'].widget.attrs['data-initial-phase'] = initial_phase

    def clean_size_value(self):
        value = self.cleaned_data.get('size_value')
        if value is None or value <= 0:
            raise forms.ValidationError('Size must be greater than 0')
        return value

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price and price <= 0:
            raise forms.ValidationError('Price must be greater than 0')
        return price

    def clean(self):
        cleaned = super().clean()
        unit = cleaned.get('size_unit')
        value = cleaned.get('size_value')
        if value is not None and value > 0:
            marla, sqft = resolve_size(unit, value)
            cleaned['size_marla'] = marla
            cleaned['size_sqft'] = sqft
        else:
            marla = cleaned.get('size_marla')
            sqft = cleaned.get('size_sqft')

        project = cleaned.get('project')
        phase = cleaned.get('phase')

        if project and project.phases.exists() and not phase:
            self.add_error('phase', 'Select a phase: this project has phases defined.')
        if phase and project and phase.project_id != project.id:
            self.add_error('phase', 'The phase must belong to the selected project.')

        # Friendly duplicate check (runs before Django's auto unique-together validation).
        if project and cleaned.get('plot_number'):
            dup = Plot.objects.filter(
                project=project,
                block=cleaned.get('block') or '',
                plot_number=cleaned.get('plot_number'),
            )
            if self.instance and self.instance.pk:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                self.add_error(
                    'plot_number',
                    'A plot with this number already exists in this project and block. Plot numbers must be unique per project and block.',
                )
        if phase:
            existing = phase.plots.count()
            if self.instance and self.instance.pk and self.instance.phase_id == phase.pk:
                existing -= 1
            if existing + 1 > phase.total_plots:
                self.add_error('phase', f'Phase capacity reached: this phase allows {phase.total_plots} plots.')

        # Price: auto-fill from the phase on create only. Once a plot exists the
        # price is a snapshot and must not be recalculated when the phase changes.
        price = cleaned.get('price')
        overridden = cleaned.get('price_overridden', False)
        if self.instance.pk:
            price_changed = price is not None and price != self.instance.price
            cleaned['price_overridden'] = bool(overridden) or price_changed
            if price is None or price <= 0:
                self.add_error('price', 'Price must be greater than 0.')
        elif not overridden and phase and phase.price_per_marla and marla not in (None, 0):
            cleaned['price'] = round(phase.price_per_marla * marla, 2)
            cleaned['price_overridden'] = False
        else:
            cleaned['price_overridden'] = bool(price)
            if price is None or price <= 0:
                self.add_error('price', 'Price must be greater than 0. It is auto-calculated from the '
                                        'phase price per marla, or set a manual price.')

        deposit = cleaned.get('holding_deposit')
        if deposit is None or deposit <= 0:
            self.add_error('holding_deposit', 'Holding deposit must be greater than 0.')
        elif price and deposit > price:
            self.add_error('holding_deposit', 'Holding deposit cannot exceed the price.')

        return cleaned


class PlotBulkCreateForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.exclude(status='inactive'),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    block = forms.CharField(
        max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. A, B, C'})
    )
    prefix = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Plot prefix (e.g. PLT)'})
    )
    start_number = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Start number'})
    )
    end_number = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'End number'})
    )
    plot_type = forms.ChoiceField(
        choices=Plot.TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    size_marla = forms.DecimalField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Size in Marla', 'step': '0.01'})
    )
    price = forms.DecimalField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Price in PKR', 'step': '0.01'})
    )
    holding_deposit = forms.DecimalField(
        required=False, initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Holding Deposit', 'step': '0.01'})
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_number')
        end = cleaned.get('end_number')
        if start and end and start > end:
            raise forms.ValidationError('Start number must be less than or equal to end number')
        return cleaned


class ProjectMilestoneForm(forms.ModelForm):
    class Meta:
        model = ProjectMilestone
        fields = ['project', 'title', 'description', 'start_date', 'target_date',
                  'milestone_type', 'completion_percent', 'progress_date', 'status', 'order']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'target_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'milestone_type': forms.Select(attrs={'class': 'form-control'}),
            'completion_percent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'}),
            'progress_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }