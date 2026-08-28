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


class PlotForm(forms.ModelForm):
    class Meta:
        model = Plot
        fields = ['plot_number', 'project', 'phase', 'block', 'street_number',
                  'plot_type', 'size_marla', 'size_sqft', 'price',
                  'holding_deposit', 'status', 'is_corner', 'is_park_facing',
                  'facing_direction', 'features', 'description']
        widgets = {
            'plot_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'project': forms.Select(attrs={'class': 'form-control'}),
            'phase': forms.Select(attrs={'class': 'form-control'}),
            'block': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'street_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'plot_type': forms.Select(attrs={'class': 'form-control'}),
            'size_marla': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'size_sqft': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'holding_deposit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_corner': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_park_facing': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'facing_direction': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'features': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price and price <= 0:
            raise forms.ValidationError('Price must be greater than 0')
        return price

    def clean_size_marla(self):
        size = self.cleaned_data.get('size_marla')
        if size and size <= 0:
            raise forms.ValidationError('Size must be greater than 0')
        return size


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
        fields = ['project', 'title', 'description', 'target_date', 'status', 'order']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'target_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }