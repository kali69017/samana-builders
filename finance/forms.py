from decimal import Decimal

from django import forms
from django.forms import formset_factory, inlineformset_factory
from .models import (
    Office, ExpenseCategory, OfficeExpense, ProjectCost, ProjectBudget,
    ProjectInvestment, AccountHead, Voucher, VoucherLine,
)


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

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        duplicate = ExpenseCategory.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('A category with this name already exists.')
        return name


class OfficeExpenseForm(forms.ModelForm):
    class Meta:
        model = OfficeExpense
        fields = ['office', 'category', 'expense_account', 'paid_from', 'amount',
                  'expense_date', 'paid_to', 'payment_method', 'description']
        widgets = {
            'office': forms.Select(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'expense_account': forms.Select(attrs={'class': 'form-control'}),
            'paid_from': forms.Select(attrs={'class': 'form-control'}),
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
        self.fields['expense_account'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, nature='debit', code__startswith='5.',
        )
        self.fields['paid_from'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, account_kind__in=['cash', 'bank'],
        )
        self.fields['expense_account'].required = True
        self.fields['paid_from'].required = True

    def clean(self):
        cleaned = super().clean()
        from .accounting import validate_cash_bank_account, validate_expense_account
        try:
            validate_expense_account(cleaned.get('expense_account'))
        except forms.ValidationError as exc:
            self.add_error('expense_account', exc)
        try:
            validate_cash_bank_account(
                cleaned.get('paid_from'), cleaned.get('payment_method') or 'cash')
        except forms.ValidationError as exc:
            self.add_error('paid_from', exc)
        return cleaned

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError('Amount must be greater than 0')
        return amount


class ProjectCostForm(forms.ModelForm):
    class Meta:
        model = ProjectCost
        fields = ['project', 'cost_category', 'expense_account', 'paid_from', 'amount',
                  'cost_date', 'vendor', 'invoice_ref', 'payment_method', 'description']
        widgets = {
            'project': forms.Select(attrs={'class': 'form-control'}),
            'cost_category': forms.Select(attrs={'class': 'form-control'}),
            'expense_account': forms.Select(attrs={'class': 'form-control'}),
            'paid_from': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'cost_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'vendor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'invoice_ref': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vendor'].required = False
        self.fields['invoice_ref'].required = False
        self.fields['description'].required = False
        self.fields['expense_account'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, nature='debit', code__startswith='5.',
        )
        self.fields['paid_from'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, account_kind__in=['cash', 'bank'],
        )
        self.fields['expense_account'].required = True
        self.fields['paid_from'].required = True

    def clean(self):
        cleaned = super().clean()
        from .accounting import validate_cash_bank_account, validate_expense_account
        try:
            validate_expense_account(cleaned.get('expense_account'))
        except forms.ValidationError as exc:
            self.add_error('expense_account', exc)
        try:
            validate_cash_bank_account(
                cleaned.get('paid_from'), cleaned.get('payment_method') or 'cash')
        except forms.ValidationError as exc:
            self.add_error('paid_from', exc)
        return cleaned

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


# ─── DOUBLE-ENTRY ACCOUNTING ─────────────────────────────────────────────────
class AccountHeadForm(forms.ModelForm):
    class Meta:
        model = AccountHead
        fields = ['name', 'parent', 'account_kind', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'parent': forms.Select(attrs={'class': 'form-control'}),
            'account_kind': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = AccountHead.objects.all()
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields['parent'].queryset = qs
        self.fields['parent'].required = True
        self.fields['parent'].empty_label = 'Select parent account'

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get('parent')
        if parent and parent.level >= 4:
            self.add_error('parent', 'Parent is already at level 4; max depth is 4.')
        kind = cleaned.get('account_kind')
        if kind and kind != 'normal' and parent and parent.root.code != '1':
            self.add_error('account_kind', 'Cash and bank flags are only allowed under Assets.')
        return cleaned


class VoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = ['voucher_type', 'date', 'narration']
        widgets = {
            'voucher_type': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'narration': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['narration'].required = False


CASH_BANK_VOUCHER_KINDS = {
    'CR': 'cash',
    'CP': 'cash',
    'BR': 'bank',
    'BP': 'bank',
}


class CashBankVoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = ['voucher_type', 'date', 'narration', 'cash_bank_account']
        widgets = {
            'voucher_type': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'narration': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'cash_bank_account': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['narration'].required = False
        self.fields['voucher_type'].choices = [
            choice for choice in Voucher.TYPE_CHOICES if choice[0] in CASH_BANK_VOUCHER_KINDS
        ]
        self.fields['cash_bank_account'].queryset = AccountHead.objects.filter(
            is_leaf=True, is_active=True, account_kind__in=['cash', 'bank'],
        )
        self.fields['cash_bank_account'].required = True

    def clean(self):
        cleaned = super().clean()
        voucher_type = cleaned.get('voucher_type')
        account = cleaned.get('cash_bank_account')
        expected = CASH_BANK_VOUCHER_KINDS.get(voucher_type)
        if expected and account:
            if account.parent_id is None:
                self.add_error('cash_bank_account', 'Select a leaf cash or bank account, not a root.')
            elif account.account_kind != expected:
                self.add_error(
                    'cash_bank_account',
                    f'Select an account flagged as {expected} for this voucher type.',
                )
        return cleaned


class ContraLineForm(forms.Form):
    account_head = forms.ModelChoiceField(
        queryset=AccountHead.objects.filter(is_leaf=True, is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    amount = forms.DecimalField(
        max_digits=15, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    narration = forms.CharField(
        required=False, max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
    )

    def clean_account_head(self):
        head = self.cleaned_data.get('account_head')
        if head and head.parent_id is None:
            raise forms.ValidationError('Postings are not allowed on a level 1 root.')
        return head


ContraLineFormSet = formset_factory(
    ContraLineForm, extra=4, min_num=1, validate_min=True,
)


class VoucherLineForm(forms.ModelForm):
    class Meta:
        model = VoucherLine
        fields = ['account_head', 'debit', 'credit', 'narration']
        widgets = {
            'account_head': forms.Select(attrs={'class': 'form-control'}),
            'debit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'credit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'narration': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account_head'].queryset = AccountHead.objects.filter(is_leaf=True, is_active=True)
        self.fields['account_head'].required = False
        self.fields['narration'].required = False

    def clean(self):
        cleaned = super().clean()
        # Allow fully blank extra rows to be ignored by the formset.
        if not cleaned.get('account_head') and not cleaned.get('debit') and not cleaned.get('credit'):
            return cleaned
        if not cleaned.get('account_head'):
            self.add_error('account_head', 'Select an account head.')
        debit = cleaned.get('debit') or Decimal('0.00')
        credit = cleaned.get('credit') or Decimal('0.00')
        if debit and credit:
            raise forms.ValidationError('A line cannot have both a debit and a credit.')
        if not debit and not credit:
            self.add_error('debit', 'Enter a debit or a credit.')
        return cleaned


VoucherLineFormSet = inlineformset_factory(
    Voucher, VoucherLine, form=VoucherLineForm,
    extra=4, can_delete=False, min_num=1, validate_min=True,
)
