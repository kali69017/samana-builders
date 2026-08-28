import re
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from .models import Customer, CustomerLedgerEntry, CustomerNominee, format_cnic, format_phone


def validate_cnic(value):
    # Only 13 digits, no dashes or other characters allowed.
    if not re.match(r'^\d{13}$', value or ''):
        raise ValidationError('CNIC must be exactly 13 digits (numbers only, no dashes)')


def validate_phone(value):
    pattern = r'^\+92-\d{3}-\d{7}$'
    if not re.match(pattern, value):
        raise ValidationError('Phone must be in format +92-300-1234567')


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['first_name', 'last_name', 'email', 'phone', 'alternate_phone',
                  'cnic', 'occupation', 'occupation_other', 'address', 'city',
                  'notes', 'document', 'image', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+92-300-1234567'}),
            'alternate_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+92-300-1234567'}),
            'cnic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 3740502357224',
                                            'inputmode': 'numeric',
                                            'pattern': '[0-9]{13}', 'autocomplete': 'off'}),
            'occupation': forms.Select(attrs={'class': 'form-control', 'placeholder': ' '}),
            'occupation_other': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': ' '}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': ' '}),
            'document': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.doc,.docx,.jpg,.jpeg,.png'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hard-cap the input at 13 digits. The model stores the canonical
        # dashed form (15 chars), so Django would otherwise render
        # maxlength="15" from the model field — set it here to win.
        self.fields['cnic'].widget.attrs['maxlength'] = '13'
        # When editing, pre-fill the raw 13-digit value (strip dashes) so the
        # field shows 13 characters and re-submission passes validation.
        if self.instance and self.instance.pk and self.instance.cnic:
            raw = re.sub(r'\D', '', self.instance.cnic or '')
            self.initial['cnic'] = raw

    def clean_cnic(self):
        cnic = self.cleaned_data.get('cnic')
        if cnic:
            # Accept the raw 13 digits (no dashes). Dashes from a pasted
            # value are stripped before the length check.
            cnic = re.sub(r'\D', '', cnic)
            validate_cnic(cnic)
            # Store in the canonical display format (XXXXX-XXXXXXX-X).
            return format_cnic(cnic)
        return cnic

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            phone = format_phone(phone)
        validate_phone(phone)
        return phone

    def clean_alternate_phone(self):
        phone = self.cleaned_data.get('alternate_phone')
        if phone:
            phone = format_phone(phone)
            validate_phone(phone)
        return phone

    def clean(self):
        cleaned = super().clean()
        occupation = cleaned.get('occupation')
        other = cleaned.get('occupation_other')
        if occupation == 'other' and not (other and other.strip()):
            self.add_error('occupation_other', 'Please specify your occupation.')
        return cleaned


class CustomerProfileForm(forms.Form):
    """Create a Django login linked to an existing Customer."""
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.filter(is_active=True),
        label='Customer',
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
        if User.objects.filter(email=email).exists():
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
        customer = self.cleaned_data['customer']
        user = User(username=self.cleaned_data['username'], email=self.cleaned_data['email'])
        user.set_password(self.cleaned_data['password'])
        user.save()
        customer.user = user
        customer.save(update_fields=['user'])
        return user


class CustomerLedgerEntryForm(forms.ModelForm):
    class Meta:
        model = CustomerLedgerEntry
        fields = ['customer', 'booking', 'transaction_type', 'reference_id',
                  'debit', 'credit', 'description', 'entry_date']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'booking': forms.Select(attrs={'class': 'form-control'}),
            'transaction_type': forms.Select(attrs={'class': 'form-control'}),
            'reference_id': forms.TextInput(attrs={'class': 'form-control'}),
            'debit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'credit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'entry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
    
    def clean(self):
        cleaned = super().clean()
        debit = cleaned.get('debit', 0) or 0
        credit = cleaned.get('credit', 0) or 0
        if debit == 0 and credit == 0:
            raise forms.ValidationError('Either debit or credit must be greater than 0')
        return cleaned


class CustomerNomineeForm(forms.ModelForm):
    class Meta:
        model = CustomerNominee
        fields = ['nominee_name', 'nominee_cnic', 'nominee_phone', 'relationship']
        widgets = {
            'nominee_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'nominee_cnic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 3740502357224',
                                                   'inputmode': 'numeric',
                                                   'pattern': '[0-9]{13}', 'autocomplete': 'off'}),
            'nominee_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+92-300-1234567'}),
            'relationship': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Father, Wife, Son'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hard-cap the input at 13 digits. The model stores the canonical
        # dashed form (15 chars), so Django would otherwise render
        # maxlength="15" from the model field — set it here to win.
        self.fields['nominee_cnic'].widget.attrs['maxlength'] = '13'
        # When editing, pre-fill the raw 13-digit value (strip dashes) so the
        # field shows 13 characters and re-submission passes validation.
        if self.instance and self.instance.pk and self.instance.nominee_cnic:
            raw = re.sub(r'\D', '', self.instance.nominee_cnic or '')
            self.initial['nominee_cnic'] = raw

    def clean_nominee_cnic(self):
        cnic = self.cleaned_data.get('nominee_cnic')
        if cnic:
            # Accept the raw 13 digits (no dashes). Dashes from a pasted
            # value are stripped before the length check.
            cnic = re.sub(r'\D', '', cnic)
            # Same rule as customer CNIC: exactly 13 digits, no dashes.
            validate_cnic(cnic)
            return format_cnic(cnic)
        return cnic