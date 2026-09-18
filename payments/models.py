from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from bookings.models import Booking, Installment


class Payment(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Verification'),
        ('under_clearing', 'Under Clearing'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('bounced', 'Bounced'),
        ('reversed', 'Reversed'),
        ('partially_applied', 'Partially Applied'),
    ]
    
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online Payment'),
        ('jazzcash', 'JazzCash'),
        ('easypaisa', 'Easypaisa'),
        ('raast', 'Raast Transfer'),
    ]
    
    PAYMENT_TYPE_CHOICES = [
        ('down_payment', 'Down Payment'),
        ('installment', 'Installment'),
        ('full_payment', 'Full Payment'),
        ('advance', 'Advance'),
        ('final_payment', 'Final Payment'),
        ('late_fee', 'Late Fee'),
        ('adjustment', 'Adjustment'),
        ('other', 'Other'),
    ]
    
    payment_id = models.CharField(max_length=20, unique=True, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    installment = models.ForeignKey(Installment, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='cash')
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, default='other')
    reference_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Cheque fields
    bank_name = models.CharField(max_length=100, blank=True)
    cheque_number = models.CharField(max_length=50, blank=True)
    cheque_date = models.DateField(null=True, blank=True)
    clearance_date = models.DateField(null=True, blank=True)
    bounce_reason = models.TextField(blank=True)
    bounce_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    method_data = models.JSONField(default=dict, blank=True, help_text="Method-specific payment details")
    unallocated_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    receipt_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_verified')
    verified_at = models.DateTimeField(null=True, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.payment_id:
            from django.db import transaction
            with transaction.atomic():
                last_payment = Payment.objects.select_for_update().order_by('-id').first()
                if last_payment:
                    last_num = int(last_payment.payment_id.split('-')[1])
                    self.payment_id = f'PAY-{str(last_num + 1).zfill(5)}'
                else:
                    self.payment_id = 'PAY-00001'
        super().save(*args, **kwargs)
        self.post_to_ledger()

    def post_to_ledger(self):
        """Create the Cash/Bank Receipt voucher for this payment (idempotent).

        Spec §3.7/§3.8: vouchers replace the ledger as the books of record, but
        this does **not** touch ``Booking.advance_paid`` — headline revenue stays
        ``advance_paid``-based, and voucher income is never summed into revenue.
        Keyed on ``(reference_type, reference_id)`` so re-saves never duplicate.
        """
        from finance.accounting import (
            cash_bank_head, post_source_voucher, receivable_head, voucher_type_for,
        )
        return post_source_voucher(
            reference_type='Payment', reference_id=self.pk,
            voucher_type=voucher_type_for(self.payment_method, 'receipt'),
            date=self.payment_date,
            narration=f'Payment {self.payment_id} - {self.get_payment_method_display()}',
            lines=[
                (cash_bank_head(self.payment_method), self.amount, Decimal('0.00')),
                (receivable_head(), Decimal('0.00'), self.amount),
            ],
            user=self.created_by,
        )
    
    def __str__(self):
        return f"{self.payment_id} - {self.booking.booking_id}"
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['payment_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='payment_amount_positive',
            ),
        ]


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')
    installment = models.ForeignKey(Installment, on_delete=models.CASCADE, related_name='allocations')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    allocated_at = models.DateTimeField(auto_now_add=True)
    allocated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        unique_together = ['payment', 'installment']


class Refund(models.Model):
    REASON_CHOICES = [
        ('cancellation', 'Booking Cancellation'),
        ('overpayment', 'Overpayment'),
        ('booking_transfer', 'Booking Transfer'),
        ('other', 'Other'),
    ]

    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online Payment'),
        ('easypaisa', 'Easypaisa'),
        ('raast', 'Raast Transfer'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('processed', 'Processed'),
        ('rejected', 'Rejected'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='refunds')
    original_payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    refund_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='bank_transfer')
    refund_date = models.DateField(null=True, blank=True)
    supporting_document = models.FileField(upload_to='refunds/%Y/%m/', blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='refunds_approved')
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds_processed')
    processed_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ─── Computed helpers ──────────────────────────────────────────────────────
    @property
    def project(self):
        return self.booking.plot.project if self.booking and self.booking.plot_id else None

    @property
    def plot(self):
        return self.booking.plot if self.booking and self.booking.plot_id else None

    @property
    def total_paid(self):
        """Sum of verified payments received on the booking."""
        if not self.booking_id:
            return 0
        from django.db.models import Sum
        total = self.booking.payments.filter(status='verified').aggregate(t=Sum('amount'))['t']
        return total or 0

    @property
    def total_refunded(self):
        """Sum of all refunds on this booking excluding rejected ones.

        When computing for a stored refund, excludes the current instance so a
        refund does not cap itself during validation (its own amount must not
        reduce the available-for-refund it is checked against).
        """
        if not self.booking_id:
            return 0
        from django.db.models import Sum
        qs = Refund.objects.filter(booking_id=self.booking_id).exclude(
            status='rejected')
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        total = qs.aggregate(t=Sum('amount'))['t']
        return total or 0

    @property
    def refundable_amount(self):
        """Maximum amount still refundable for this booking (never negative)."""
        return max(self.total_paid - self.total_refunded, 0)

    @property
    def refund_percentage(self):
        """Share of the total verified paid amount that this refund represents."""
        if not self.total_paid:
            return 0
        return (self.amount / self.total_paid) * 100

    # ─── Validation ────────────────────────────────────────────────────────────
    def clean(self):
        from django.core.exceptions import ValidationError
        refundable = self.refundable_amount
        if self.amount is not None and self.amount > refundable:
            raise ValidationError({
                'amount': f'Refund amount Rs. {self.amount} cannot exceed the '
                          f'refundable amount Rs. {refundable} for this booking.'
            })

    # ─── Workflow ──────────────────────────────────────────────────────────────
    def validate_refund_limit(self):
        """Raise if this refund's amount exceeds the currently refundable amount."""
        from django.core.exceptions import ValidationError
        refundable = self.refundable_amount
        if self.amount is not None and self.amount > refundable:
            raise ValidationError(
                f'Refund amount Rs. {self.amount} cannot exceed the '
                f'refundable amount Rs. {refundable} for this booking.'
            )

    def apply_approval(self, user=None):
        """Apply the financial effect of an approved refund.

        Money returned to the customer reduces the booking's advance_paid
        (and thus restores the remaining balance). This keeps the booking
        balance, payment ledger, and receivables consistent with the money
        actually held. Safe to call on approval.
        """
        self.validate_refund_limit()
        from decimal import Decimal
        booking = self.booking
        amount = Decimal(self.amount or 0)
        if booking and amount > 0:
            # Reduce money held on the booking by the refunded amount.
            booking.advance_paid = max(booking.advance_paid - amount, Decimal('0'))
            booking.save(update_fields=['advance_paid', 'updated_at'])
        self.status = 'approved'
        self.approved_by = user
        if not self.processed_date:
            self.processed_date = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'processed_date', 'notes', 'updated_at'])

    def reject(self, notes='', user=None):
        self.status = 'rejected'
        if notes:
            self.notes = notes
        self.save(update_fields=['status', 'notes', 'updated_at'])

    def post_to_ledger(self):
        """Idempotently post an independent payment voucher for this refund.

        Spec §3.15: a refund never reverses or mutates the original receipt
        voucher. It is a separate Cash/Bank Payment voucher — debit Accounts
        Receivable, credit Cash/Bank (resolved from ``refund_method``) — keyed on
        ``reference_type='Refund'`` + ``reference_id``.
        """
        from datetime import date
        from finance.accounting import (
            cash_bank_head, post_source_voucher, receivable_head, voucher_type_for,
        )
        post_date = self.refund_date
        if not post_date:
            post_date = self.processed_date.date() if self.processed_date else date.today()
        return post_source_voucher(
            reference_type='Refund', reference_id=self.pk,
            voucher_type=voucher_type_for(self.refund_method, 'payment'),
            date=post_date,
            narration=f'Refund of Rs. {self.amount} for booking '
                      f'{self.booking.booking_id} - {self.get_reason_display()}',
            lines=[
                (receivable_head(), self.amount, Decimal('0.00')),
                (cash_bank_head(self.refund_method), Decimal('0.00'), self.amount),
            ],
            user=self.processed_by,
        )

    def process(self, user=None):
        """Mark the approved refund as processed and post it to the ledger exactly once."""
        from django.core.exceptions import ValidationError
        from finance.models import Voucher

        if self.status != 'approved':
            raise ValidationError('Only an approved refund can be processed.')

        # Guard: never double-post to the ledger.
        already_posted = Voucher.objects.filter(
            reference_type='Refund', reference_id=self.pk
        ).exists()

        self.status = 'processed'
        self.processed_by = user
        self.processed_date = timezone.now()
        self.save(update_fields=['status', 'processed_by', 'processed_date', 'notes', 'updated_at'])

        if not already_posted:
            self.post_to_ledger()
        return self

    def mark_processed(self, user=None):
        """Alias for :meth:`process`."""
        return self.process(user=user)

    def __str__(self):
        return f"Refund for {self.booking.booking_id} - {self.get_status_display()}"

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='refund_amount_positive',
            ),
        ]


class Receipt(models.Model):
    receipt_id = models.CharField(max_length=20, unique=True, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='receipts')
    receipt_number = models.CharField(max_length=50, blank=True, unique=True)
    receipt_date = models.DateField(default=None, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    receipt_template = models.CharField(max_length=50, default='standard')
    pdf_file = models.FileField(upload_to='receipts/%Y/%m/', blank=True)
    is_duplicate = models.BooleanField(default=False)
    cancellation_reason = models.TextField(blank=True)
    
    def save(self, *args, **kwargs):
        if not self.receipt_id:
            from django.db import transaction
            with transaction.atomic():
                last_receipt = Receipt.objects.select_for_update().order_by('-id').first()
                if last_receipt:
                    last_num = int(last_receipt.receipt_id.split('-')[1])
                    self.receipt_id = f'RCP-{str(last_num + 1).zfill(5)}'
                else:
                    self.receipt_id = 'RCP-00001'

        if not self.receipt_date:
            if self.payment and self.payment.payment_date:
                self.receipt_date = self.payment.payment_date
            else:
                from datetime import date
                self.receipt_date = date.today()

        if not self.receipt_number:
            from datetime import date
            from django.db import transaction
            ref_date = self.receipt_date or date.today()
            if ref_date.month >= 7:
                fy_start = ref_date.year
                fy_end = ref_date.year + 1
            else:
                fy_start = ref_date.year - 1
                fy_end = ref_date.year
            fy_short = f'{str(fy_start)[2:]}-{str(fy_end)[2:]}'
            prefix = f'RCP-FY{fy_short}/'
            with transaction.atomic():
                last = Receipt.objects.select_for_update().filter(receipt_number__startswith=prefix).order_by('-receipt_number').first()
                if last:
                    try:
                        next_num = int(last.receipt_number.rsplit('/', 1)[1]) + 1
                    except (ValueError, IndexError):
                        next_num = 1
                else:
                    next_num = 1
            self.receipt_number = f'{prefix}{str(next_num).zfill(5)}'

        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.receipt_number} - {self.payment.payment_id}"
    
    class Meta:
        verbose_name_plural = 'Receipts'


class PaymentAttachment(models.Model):
    ATTACHMENT_TYPES = [
        ('cheque_image', 'Cheque Image'),
        ('payment_screenshot', 'Payment Screenshot'),
        ('receipt_image', 'Receipt Image'),
        ('other', 'Other'),
    ]
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='payments/%Y/%m/')
    attachment_type = models.CharField(max_length=30, choices=ATTACHMENT_TYPES)
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.filename} - {self.payment.payment_id}"