from django import forms
from properties.models import Project
from .models import Expense


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['project', 'expense_account', 'paid_from', 'description', 'amount',
                  'expense_type', 'paid_to', 'expense_date', 'payment_method',
                  'payment_reference', 'receipt_attachment']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'expense_account': forms.Select(attrs={'class': 'form-control'}),
            'paid_from': forms.Select(attrs={'class': 'form-control'}),
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
        from finance.models import AccountHead
        self.fields['project'].queryset = Project.objects.exclude(status='inactive')
        self.fields['expense_account'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, nature='debit', code__startswith='5.',
        )
        self.fields['paid_from'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, account_kind__in=['cash', 'bank'],
        )
        self.fields['expense_account'].required = True
        self.fields['paid_from'].required = False
        self.fields['payment_reference'].required = False

    def clean(self):
        cleaned = super().clean()
        from finance.accounting import validate_cash_bank_account, validate_expense_account
        try:
            validate_expense_account(cleaned.get('expense_account'))
        except forms.ValidationError as exc:
            self.add_error('expense_account', exc)
        account = cleaned.get('paid_from')
        if account:
            try:
                validate_cash_bank_account(account, cleaned.get('payment_method'))
            except forms.ValidationError as exc:
                self.add_error('paid_from', exc)
        return cleaned