import re

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.models import UserProfile
from .models import (
    Department, Designation, SalaryComponent, Employee, EmployeeSalary,
    PayrollRun, Attendance, Leave,
)


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class DesignationForm(forms.ModelForm):
    class Meta:
        model = Designation
        fields = ['title', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class SalaryComponentForm(forms.ModelForm):
    class Meta:
        model = SalaryComponent
        fields = ['name', 'component_type', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'component_type': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['first_name', 'last_name', 'department', 'designation',
                  'joining_date', 'cnic', 'phone', 'email', 'address', 'status', 'notes']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'department': forms.Select(attrs={'class': 'form-control'}),
            'designation': forms.Select(attrs={'class': 'form-control'}),
            'joining_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'cnic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 3740502357224',
                                           'inputmode': 'numeric', 'autocomplete': 'off'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+92-300-1234567'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cnic'].required = False
        self.fields['phone'].required = False
        self.fields['email'].required = False
        self.fields['address'].required = False
        self.fields['notes'].required = False
        # Hard-cap the CNIC input at 13 digits (model stores the canonical
        # dashed form, 15 chars — override the model-derived maxlength).
        self.fields['cnic'].widget.attrs['maxlength'] = '13'
        self.fields['cnic'].widget.attrs['pattern'] = '[0-9]{13}'
        # When editing, pre-fill the raw 13-digit value (strip dashes).
        if self.instance and self.instance.pk and self.instance.cnic:
            raw = re.sub(r'\D', '', self.instance.cnic or '')
            self.initial['cnic'] = raw

    def clean_cnic(self):
        cnic = self.cleaned_data.get('cnic')
        if cnic:
            cnic = re.sub(r'\D', '', cnic)
            if len(cnic) != 13:
                raise forms.ValidationError('CNIC must be exactly 13 digits (numbers only, no dashes)')
            # Store in the canonical display format (XXXXX-XXXXXXX-X).
            return f'{cnic[:5]}-{cnic[5:12]}-{cnic[12:]}'
        return cnic


class EmployeeSalaryForm(forms.ModelForm):
    class Meta:
        model = EmployeeSalary
        fields = ['component', 'amount']
        widgets = {
            'component': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
        }


class PayrollRunForm(forms.ModelForm):
    class Meta:
        model = PayrollRun
        fields = ['month', 'year', 'notes']
        widgets = {
            'month': forms.Select(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = Attendance
        fields = ['employee', 'date', 'status', 'notes']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }


class LeaveForm(forms.ModelForm):
    class Meta:
        model = Leave
        fields = ['employee', 'leave_type', 'start_date', 'end_date', 'days', 'reason']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-control'}),
            'leave_type': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'days': forms.NumberInput(attrs={'class': 'form-control'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reason'].required = False


class EmployeeProfileForm(forms.Form):
    """Create an ERP login linked to an existing Employee."""

    employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(status='active').exclude(user__isnull=False),
        label='Employee',
        widget=forms.Select(attrs={'class': 'form-control', 'placeholder': ' '}),
    )
    username = forms.CharField(
        max_length=150, label='Username',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
    )
    password = forms.CharField(
        label='Password', min_length=6,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': ' '}),
    )
    confirm_password = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': ' '}),
    )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise ValidationError('Username already exists')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exists():
            raise ValidationError('Email is already in use')
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm = cleaned.get('confirm_password')
        if password and confirm and password != confirm:
            self.add_error('confirm_password', ValidationError('Passwords do not match'))
        return cleaned

    def save(self):
        employee = self.cleaned_data['employee']
        user = User(username=self.cleaned_data['username'], email=self.cleaned_data['email'])
        user.set_password(self.cleaned_data['password'])
        user.save()
        # Give the employee a staff-level ERP profile so they land on the
        # ERP dashboard (their own Leave portal) after logging in.
        UserProfile.objects.create(user=user, role='staff')
        employee.user = user
        employee.save(update_fields=['user'])
        return user
