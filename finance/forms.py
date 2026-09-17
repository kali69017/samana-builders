from django import forms
from .models import Office, ExpenseCategory, OfficeExpense, ProjectCost, ProjectBudget, ProjectInvestment


class OfficeForm(forms.ModelForm):
    class Meta:
        model = Office
        fields = ['name', 'office_type', 'address', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'office_type': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['name', 'category_type', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'category_type': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class OfficeExpenseForm(forms.ModelForm):
    class Meta:
        model = OfficeExpense
        fields = ['office', 'category', 'amount', 'expense_date', 'paid_to',
                  'payment_method', 'description']
        widgets = {
            'office': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'expense_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'paid_to': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['paid_to'].required = False
        self.fields['description'].required = False

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError('Amount must be greater than 0')
        return amount


class ProjectCostForm(forms.ModelForm):
    class Meta:
        model = ProjectCost
        fields = ['project', 'cost_category', 'amount', 'cost_date', 'vendor',
                  'invoice_ref', 'description']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'cost_category': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'cost_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'vendor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'invoice_ref': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vendor'].required = False
        self.fields['invoice_ref'].required = False
        self.fields['description'].required = False

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError('Amount must be greater than 0')
        return amount


class ProjectBudgetForm(forms.ModelForm):
    class Meta:
        model = ProjectBudget
        fields = ['total_budget', 'material_budget', 'labor_budget',
                  'contractor_budget', 'transportation_budget', 'other_budget']
        widgets = {
            'total_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'material_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'labor_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'contractor_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'transportation_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class ProjectInvestmentForm(forms.ModelForm):
    class Meta:
        model = ProjectInvestment
        fields = ['total_investment', 'notes']
        widgets = {
            'total_investment': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['notes'].required = False
