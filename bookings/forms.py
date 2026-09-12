from django import forms
from django.db import models
from django.utils import timezone
from datetime import timedelta
from .models import (
    Booking, BookingGroup, Reservation,
    InstallmentPlan, InstallmentPlanTemplate, Installment, LateFeeConfiguration
)
from customers.models import Customer
from properties.models import Plot


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['customer', 'plot', 'total_amount', 'advance_paid', 'source', 'agent', 'notes']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'plot': forms.Select(attrs={'class': 'form-control'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'advance_paid': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01'}),
            'source': forms.Select(attrs={'class': 'form-control'}),
            'agent': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_active=True)
        self.fields['plot'].queryset = Plot.objects.filter(
            models.Q(status='available') | models.Q(status='booked', bookings__pk=self.instance.pk if self.instance else None)
        ).distinct()
        self.fields['advance_paid'].initial = 0
        self.fields['source'].required = False
        self.fields['agent'].required = False
        self.fields['notes'].required = False

    def clean_total_amount(self):
        amount = self.cleaned_data.get('total_amount')
        if amount and amount <= 0:
            raise forms.ValidationError('Total amount must be greater than 0')
        return amount

    def clean_advance_paid(self):
        advance = self.cleaned_data.get('advance_paid')
        total = self.cleaned_data.get('total_amount')
        if advance and total and advance > total:
            raise forms.ValidationError('Advance cannot exceed total amount')
        if advance and advance < 0:
            raise forms.ValidationError('Advance cannot be negative')
        return advance

    def clean(self):
        cleaned = super().clean()
        from decimal import Decimal
        plot = cleaned.get('plot')
        total = cleaned.get('total_amount')
        advance = cleaned.get('advance_paid')

        if plot:
            # ─── Task 1: booking amount must match the plot/unit price ─────
            # The plot's defined price + charges is the source of truth. A
            # booking may only be created at a value the plot supports; sellers
            # cannot silently sell below the defined price without an explicit
            # discount/approval mechanism (a Group with a discount_amount).
            # ─── Task 1 + Task 12: booking amount must not under-sell the plot ──
            plot_total_cost = plot.total_cost if hasattr(plot, 'total_cost') else (plot.price or 0)
            if total is not None:
                if plot_total_cost and Decimal(str(total)) < Decimal(str(plot_total_cost)):
                    raise forms.ValidationError(
                        'Total amount (Rs. {:,}) is below the plot total cost of Rs. {:,} '
                        '(price + development/lease/other charges). You cannot sell below '
                        'the defined cost.'.format(int(total), int(plot_total_cost))
                    )

            # ─── Task 1: deposit/holding amount consistency ─────────────────
            # The upfront advance/holding deposit recorded on the booking must
            # be at least the plot's holding_deposit (the token required to
            # reserve/confirm the plot), when one is defined.
            required_deposit = plot.holding_deposit if plot.holding_deposit is not None else 0
            if required_deposit:
                if advance is None or advance < required_deposit:
                    raise forms.ValidationError(
                        'Advance/holding deposit (Rs. {:,}) is below the required '
                        'token/holding amount (Rs. {:,}) for this plot.'.format(
                            int(advance or 0), int(required_deposit))
                    )

        return cleaned


class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ['customer', 'plot', 'token_amount', 'expires_at']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-control'}),
            'plot': forms.Select(attrs={'class': 'form-control'}),
            'token_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expires_at': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(is_active=True)
        self.fields['plot'].queryset = Plot.objects.filter(status='available')
        self.fields['expires_at'].initial = timezone.now() + timedelta(days=7)

    def clean_token_amount(self):
        amount = self.cleaned_data.get('token_amount')
        if amount and amount <= 0:
            raise forms.ValidationError('Token amount must be greater than 0')
        return amount


class InstallmentPlanForm(forms.ModelForm):
    generate_now = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Generate installments immediately'
    )

    class Meta:
        model = InstallmentPlan
        fields = ['total_installments', 'installment_amount', 'down_payment_amount',
                  'start_date', 'frequency', 'due_day', 'late_fee_per_day', 'grace_period_days']
        widgets = {
            'total_installments': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Number of Installments'}),
            'installment_amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Amount per Installment', 'step': '0.01'}),
            'down_payment_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'frequency': forms.Select(attrs={'class': 'form-control'}),
            'due_day': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Day of Month (1-28)'}),
            'late_fee_per_day': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Late Fee Per Day', 'step': '0.01'}),
            'grace_period_days': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Grace Period (days)'}),
        }

    def clean_due_day(self):
        day = self.cleaned_data.get('due_day')
        if day and (day < 1 or day > 28):
            raise forms.ValidationError('Day must be between 1 and 28')
        return day

    def clean_total_installments(self):
        count = self.cleaned_data.get('total_installments')
        if count and count <= 0:
            raise forms.ValidationError('Must have at least 1 installment')
        return count


class InstallmentForm(forms.ModelForm):
    class Meta:
        model = Installment
        fields = ['due_date', 'amount', 'late_fee']
        widgets = {
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'late_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class InstallmentPlanTemplateForm(forms.ModelForm):
    class Meta:
        model = InstallmentPlanTemplate
        fields = ['name', 'project', 'total_installments', 'frequency',
                  'down_payment_percentage', 'late_fee_per_day', 'grace_period_days',
                  'has_balloon_payment', 'balloon_installment_number', 'balloon_multiplier']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'project': forms.Select(attrs={'class': 'form-control'}),
            'total_installments': forms.NumberInput(attrs={'class': 'form-control'}),
            'frequency': forms.Select(attrs={'class': 'form-control'}),
            'down_payment_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'late_fee_per_day': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'grace_period_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'has_balloon_payment': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'balloon_installment_number': forms.NumberInput(attrs={'class': 'form-control'}),
            'balloon_multiplier': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class BookingCancelForm(forms.Form):
    cancellation_reason = forms.ChoiceField(
        choices=[
            ('customer_request', 'Customer Request'),
            ('payment_default', 'Payment Default'),
            ('transfer', 'Transfer to Another Booking'),
            ('other', 'Other'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Cancellation notes...'})
    )
    apply_cancellation_fee = forms.BooleanField(
        required=False, initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )