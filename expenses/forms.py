from django import forms
from properties.models import Project
from .models import Expense


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['project', 'description', 'amount', 'expense_type', 'paid_to',
                  'expense_date', 'payment_method', 'payment_reference',
                  'receipt_attachment']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'expense_type': forms.Select(attrs={'class': 'form-control'}),
            'paid_to': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'expense_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'payment_reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'receipt_attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.exclude(status='inactive')
        self.fields['payment_reference'].required = False