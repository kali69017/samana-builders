from django import forms
from .models import Project, ProjectPhase, Plot, PlotFeature, ProjectMilestone


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


class ProjectPhaseForm(forms.ModelForm):
    class Meta:
        model = ProjectPhase
        fields = ['project', 'name', 'description', 'launch_date', 'total_plots', 'price_per_marla', 'is_active']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'launch_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'total_plots': forms.NumberInput(attrs={'class': 'form-control'}),
            'price_per_marla': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# Inline phases on the project form, so a project's phases are set where it's created.
ProjectPhaseFormSet = forms.inlineformset_factory(
    Project, ProjectPhase, form=ProjectPhaseForm, extra=2, can_delete=True,
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
                  'price', 'holding_deposit', 'status', 'is_corner', 'is_park_facing',
                  'facing_direction', 'features', 'description']
        widgets = {
            'plot_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'project': forms.Select(attrs={'class': 'form-control'}),
            'phase': forms.Select(attrs={'class': 'form-control'}),
            'block': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'street_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'plot_type': forms.Select(attrs={'class': 'form-control'}),
            # Derived from size_unit + size_value — hidden so the user picks one.
            'size_marla': forms.HiddenInput(),
            'size_sqft': forms.HiddenInput(),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'holding_deposit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_corner': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_park_facing': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'facing_direction': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
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

        # Prefill unit + value from the stored size when editing a plot.
        if self.instance and self.instance.pk:
            if getattr(self.instance, 'size_sqft', None):
                self.fields['size_unit'].initial = 'sqyards'
                self.fields['size_value'].initial = round(float(self.instance.size_sqft) / 9, 2)
            else:
                self.fields['size_value'].initial = self.instance.size_marla

        # Dynamic phase queryset: only show phases belonging to the selected project.
        project = getattr(self.instance, 'project', None)
        if project is not None:
            self.fields['phase'].queryset = project.phases.all()
        else:
            self.fields['phase'].queryset = ProjectPhase.objects.all()

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
        from decimal import Decimal as _D
        unit = cleaned.get('size_unit')
        value = cleaned.get('size_value')
        if value is not None:
            if unit == 'sqyards':
                sqft = value * 9
                cleaned['size_sqft'] = sqft
                cleaned['size_marla'] = round(sqft / _D('272.25'), 2)
            else:  # marla
                cleaned['size_marla'] = value
                cleaned['size_sqft'] = round(value * _D('272.25'), 2)
        return cleaned


class PlotBulkCreateForm(forms.Form):
    project = forms.ModelChoiceField(
        queryset=Project.objects.exclude(status='inactive'),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    block = forms.CharField(
        max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Block (e.g. A, B, C)'})
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