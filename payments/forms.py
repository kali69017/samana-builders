from django import forms
from django.db.models import Sum
from .models import Payment, Refund
from bookings.models import Booking, Installment


class PaymentForm(forms.ModelForm):
    payment_type = forms.ChoiceField(
        choices=[('', 'Select type...'), ('down_payment', 'Down Payment'), ('installment', 'Installment'),
                 ('advance', 'Advance'), ('final_payment', 'Final Payment'), ('late_fee', 'Late Fee'),
                 ('adjustment', 'Adjustment')],
        required=True, widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Payment
        fields = ['booking', 'installment', 'amount', 'payment_date', 'payment_method', 'payment_type',
                  'reference_number', 'bank_name', 'cheque_number', 'cheque_date', 'notes', 'method_data']
        widgets = {
            'booking': forms.Select(attrs={'class': 'form-control', 'id': 'id_booking'}),
            'installment': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': ' ', 'step': '0.01', 'id': 'id_amount'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date', 'id': 'id_payment_date'}),
            'payment_method': forms.Select(attrs={'class': 'form-control', 'id': 'id_payment_method'}),
            'reference_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'cheque_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': ' '}),
            'cheque_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
            'method_data': forms.HiddenInput(attrs={'id': 'id_method_data'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['booking'].queryset = Booking.objects.filter(status__in=['pending', 'confirmed', 'active'])
        self.fields['installment'].queryset = Installment.objects.filter(status__in=['pending', 'overdue', 'partial'])
        self.fields['installment'].required = False
        self.fields['reference_number'].required = False
        self.fields['notes'].required = False
        self.fields['bank_name'].required = False
        self.fields['cheque_number'].required = False
        self.fields['cheque_date'].required = False
        self.fields['method_data'].required = False

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise forms.ValidationError('Amount must be greater than 0')
        return amount

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('payment_method')
        if method == 'cheque':
            if not cleaned.get('cheque_number'):
                raise forms.ValidationError('Cheque number is required for cheque payments')
            if not cleaned.get('bank_name'):
                raise forms.ValidationError('Bank name is required for cheque payments')
        
        # Validate installment belongs to the selected booking
        installment = cleaned.get('installment')
        booking = cleaned.get('booking')
        if installment and booking:
            if installment.plan.booking_id != booking.pk:
                raise forms.ValidationError('Selected installment does not belong to this booking.')
        
        # Validate amount doesn't exceed remaining balance
        if booking and cleaned.get('amount'):
            if cleaned['amount'] > booking.remaining_balance:
                # Allow but warn - overpayment is valid for advance
                pass
        
        return cleaned


class RefundForm(forms.ModelForm):
    class Meta:
        model = Refund
        fields = ['booking', 'amount', 'reason', 'refund_method', 'refund_date',
                  'supporting_document', 'notes']
        widgets = {
            'booking': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': ' '}),
            'reason': forms.Select(attrs={'class': 'form-control'}),
            'refund_method': forms.Select(attrs={'class': 'form-control'}),
            'refund_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'supporting_document': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['booking'].queryset = Booking.objects.select_related('customer').all()
        self.fields['notes'].required = False
        self.fields['refund_date'].required = False
        self.fields['supporting_document'].required = False

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError('Amount must be greater than 0')
        return amount

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get('amount')
        booking = cleaned.get('booking')
        if amount and booking:
            total_paid = booking.payments.filter(status='verified').aggregate(
                t=Sum('amount'))['t'] or 0
            refund_qs = Refund.objects.filter(booking_id=booking.pk).exclude(status='rejected')
            if self.instance and self.instance.pk:
                refund_qs = refund_qs.exclude(pk=self.instance.pk)
            total_refunded = refund_qs.aggregate(t=Sum('amount'))['t'] or 0
            refundable = max(total_paid - total_refunded, 0)
            if amount > refundable:
                raise forms.ValidationError(
                    f'Refund amount cannot exceed the refundable amount '
                    f'(Rs. {refundable}) for this booking.'
                )
        return cleaned


class PaymentFilterForm(forms.Form):
    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('draft', 'Draft'),
        ('bounced', 'Bounced'),
    ]
    
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False,
                               widget=forms.Select(attrs={'class': 'form-control'}))
    method = forms.ChoiceField(
        choices=[('', 'All Methods')] + list(Payment.METHOD_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(required=False,
                                widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    date_to = forms.DateField(required=False,
                              widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))