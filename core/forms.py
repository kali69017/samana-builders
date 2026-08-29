from django import forms
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from .models import UserProfile, Lead, LeadNote, Agent, AgentCommissionPayment, CompanySettings


class UserForm(forms.ModelForm):
    """Form for editing User fields."""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UserProfileForm(forms.ModelForm):
    """Form for editing UserProfile fields."""
    class Meta:
        model = UserProfile
        fields = ['role', 'theme', 'is_active']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-control'}),
            'theme': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CreateUserForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    first_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    last_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        help_text='Super Admin accounts cannot be created from here.',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    cnic = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )

    def __init__(self, *args, **kwargs):
        self.actor = kwargs.pop('actor', None)
        super().__init__(*args, **kwargs)

    def clean_role(self):
        role = self.cleaned_data.get('role')
        if role == 'super_admin':
            actor_is_super_admin = bool(
                self.actor and (self.actor.is_superuser or getattr(getattr(self.actor, 'profile', None), 'role', None) == 'super_admin')
            )
            if actor_is_super_admin:
                raise forms.ValidationError('A Super Admin cannot create another Super Admin account.')
            raise forms.ValidationError('Super Admin accounts cannot be created from here.')
        return role

    def clean_password_confirm(self):
        password = self.cleaned_data.get('password')
        password_confirm = self.cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('Passwords do not match')
        return password_confirm

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already exists')
        return username


class RestoreBackupForm(forms.Form):
    backup_file = forms.FileField(
        label='Backup ZIP file',
        help_text='Upload a previously downloaded Samana backup ZIP file.',
        validators=[FileExtensionValidator(['zip'])],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )

    def clean_backup_file(self):
        uploaded = self.cleaned_data.get('backup_file')
        if uploaded and uploaded.size == 0:
            raise forms.ValidationError('The uploaded file appears to be empty.')
        return uploaded


class UserEditForm(forms.ModelForm):
    """Form for editing an existing user, profile and password together."""
    role = forms.ChoiceField(
        choices=[(k, v) for k, v in UserProfile.ROLE_CHOICES if k != 'super_admin'],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    new_password = forms.CharField(
        label='New Password', required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    confirm_password = forms.CharField(
        label='Confirm New Password', required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    phone = forms.CharField(
        max_length=20, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )
    cnic = forms.CharField(
        max_length=15, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(self.instance, 'profile', None)
        if profile:
            # Existing super admin roles stay visible so they can be viewed/edited.
            if profile.role == 'super_admin':
                self.fields['role'].choices = UserProfile.ROLE_CHOICES
            self.fields['role'].initial = profile.role
            self.fields['phone'].initial = profile.phone
            self.fields['cnic'].initial = profile.cnic

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password')
        p2 = cleaned.get('confirm_password')
        if p1 or p2:
            if p1 != p2:
                raise forms.ValidationError('Passwords do not match.')
            if len(p1) < 8:
                raise forms.ValidationError('Password must be at least 8 characters.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit)
        password = self.cleaned_data.get('new_password')
        if password:
            user.set_password(password)
            if commit:
                user.save()
        if commit and hasattr(user, 'profile'):
            user.profile.role = self.cleaned_data['role']
            user.profile.phone = self.cleaned_data['phone']
            user.profile.cnic = self.cleaned_data['cnic']
            user.profile.save()
        return user

class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ['name', 'email', 'phone', 'source', 'status', 'assigned_to',
                  'interest_project', 'budget', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+92-300-1234567'}),
            'source': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'assigned_to': forms.Select(attrs={'class': 'form-control'}),
            'interest_project': forms.Select(attrs={'class': 'form-control'}),
            'budget': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['name'].required = False
        self.fields['email'].required = False
        self.fields['phone'].required = False

    def clean(self):
        cleaned = super().clean()
        if not any([cleaned.get('name'), cleaned.get('email'), cleaned.get('phone')]):
            raise forms.ValidationError('At least a name, email, or phone is required.')
        return cleaned


class LeadNoteForm(forms.ModelForm):
    class Meta:
        model = LeadNote
        fields = ['note']
        widgets = {
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Add a note...'}),
        }


class AgentForm(forms.ModelForm):
    class Meta:
        model = Agent
        fields = ['name', 'phone', 'email', 'cnic', 'commission_rate', 'is_active', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+92-300-1234567'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'cnic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '37405-0235722-4'}),
            'commission_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def clean_commission_rate(self):
        rate = self.cleaned_data.get('commission_rate')
        if rate is not None and (rate < 0 or rate > 100):
            raise forms.ValidationError('Commission rate must be between 0 and 100.')
        return rate


class AgentCommissionPaymentForm(forms.ModelForm):
    class Meta:
        model = AgentCommissionPayment
        fields = ['amount', 'payment_date', 'method', 'reference']
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'method': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cash / Bank Transfer / Cheque'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cheque no. / tx id / notes'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError('Payment amount must be greater than 0.')
        return amount


class CompanySettingsForm(forms.ModelForm):
    class Meta:
        model = CompanySettings
        fields = ['company_name', 'tagline', 'phone', 'email', 'address', 'website',
                  'logo', 'currency', 'currency_symbol', 'tax_rate', 'receipt_footer',
                  'facebook', 'instagram', 'twitter', 'ai_language']
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'tagline': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'currency': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'currency_symbol': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'receipt_footer': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'facebook': forms.URLInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'instagram': forms.URLInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'twitter': forms.URLInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'ai_language': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'ai_language': 'AI Language',
        }
