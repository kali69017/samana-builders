from django import forms
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
            'cnic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '37405-0235722-4'}),
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
        fields = ['employee', 'date', 'status', 'check_in', 'check_out', 'notes']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'check_in': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'check_out': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['check_in'].required = False
        self.fields['check_out'].required = False
        self.fields['notes'].required = False


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
