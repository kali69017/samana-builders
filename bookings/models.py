from django.db import models
from django.contrib.auth.models import User
from customers.models import Customer
from properties.models import Plot


class BookingGroup(models.Model):
    group_id = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='booking_groups')
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    payment_plan = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.group_id:
            last = BookingGroup.objects.order_by('-id').first()
            num = int(last.group_id.split('-')[1]) + 1 if last else 1
            self.group_id = f'GRP-{str(num).zfill(5)}'
        super().save(*args, **kwargs)


class CancellationPolicy(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name


class CancellationTier(models.Model):
    policy = models.ForeignKey(CancellationPolicy, on_delete=models.CASCADE, related_name='tiers')
    from_days = models.IntegerField(help_text="Days from booking date (inclusive)")
    to_days = models.IntegerField(help_text="Days from booking date (inclusive)")
    refund_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    deduction_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['from_days']


class Reservation(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('converted', 'Converted to Booking'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='reservations')
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='reservations')
    token_amount = models.DecimalField(max_digits=15, decimal_places=2)
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return f"Reservation - {self.customer.full_name} - {self.plot.plot_number}"
    
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(token_amount__gt=0),
                name='reservation_token_positive',
            ),
        ]


class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]
    
    SOURCE_CHOICES = [
        ('website', 'Website'),
        ('walk_in', 'Walk-In'),
        ('referral', 'Referral'),
        ('agent', 'Agent'),
        ('other', 'Other'),
    ]
    
    booking_id = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='bookings')
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='bookings')
    group = models.ForeignKey(BookingGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    booking_date = models.DateField(auto_now_add=True)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    advance_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='walk_in')
    agent = models.ForeignKey(
        'core.Agent', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bookings'
    )
    cancellation_policy = models.ForeignKey(CancellationPolicy, on_delete=models.SET_NULL, null=True, blank=True)
    cancellation_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    possession_date = models.DateField(null=True, blank=True)
    is_possession_taken = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings_cancelled')
    cancelled_reason = models.CharField(max_length=100, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.booking_id:
            from django.db import transaction
            with transaction.atomic():
                last_booking = Booking.objects.select_for_update().order_by('-id').first()
                if last_booking:
                    last_num = int(last_booking.booking_id.split('-')[1])
                    self.booking_id = f'BKG-{str(last_num + 1).zfill(5)}'
                else:
                    self.booking_id = 'BKG-00001'
        
        # Track status change for audit
        original = Booking.objects.filter(pk=self.pk).first() if self.pk else None
        if original is not None and original.status != self.status:
            from core.models import AuditLog
            AuditLog.objects.create(
                action='update',
                model_name='Booking',
                object_id=self.booking_id,
                description=f'Booking status changed from {original.status} to {self.status}'
            )

        super().save(*args, **kwargs)

        # Spec §3.12/§3.18: a customer becomes "mature" (linked to the shared
        # Accounts Receivable control head) on the confirmed transition — and
        # not before.
        if self.status == 'confirmed' and (original is None or original.status != 'confirmed'):
            self.customer.link_account_head()
    
    def __str__(self):
        return f"{self.booking_id} - {self.customer.full_name}"
    
    @property
    def remaining_balance(self):
        return self.total_amount - self.advance_paid

    @property
    def payment_progress(self):
        if self.total_amount > 0:
            return int((self.advance_paid / self.total_amount) * 100)
        return 0

    @property
    def agent_commission(self):
        """Commission earned by the sourcing agent on this booking."""
        if self.agent and self.agent.commission_rate:
            return (self.total_amount * self.agent.commission_rate) / 100
        return 0

    @property
    def payment_plan(self):
        """Human-readable payment plan label from the installment plan/group."""
        if hasattr(self, 'installment_plan') and self.installment_plan:
            plan = self.installment_plan
            return f"{plan.total_installments} {plan.get_frequency_display() or 'installments'}"
        group = self.group
        if group and group.payment_plan:
            return group.payment_plan
        return "Standard plan"

    @property
    def payment_plan_display(self):
        return self.payment_plan



    @property
    def amount_paid(self):
        """Verified money actually paid against this booking.

        Defaults to advance_paid (the single source of truth for the ledger);
        if there are verified Payment records that exceed advance_paid, uses
        the sum of verified payments instead so the detail screen reflects
        actual collections.
        """
        from payments.models import Payment
        from django.db.models import Sum
        verified = Payment.objects.filter(booking=self, status='verified').aggregate(
            total=Sum('amount'))['total'] or 0
        if verified > 0:
            return verified
        return self.advance_paid

    @property
    def total_charges(self):
        """Applicable plot charges on this booking's plot (excl. base price)."""
        return self.plot.total_charges if hasattr(self.plot, 'total_charges') else 0

    def get_payment_plan_display(self):
        """Django template-compatible accessor for the payment plan."""
        return self.payment_plan


    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gt=0),
                name='booking_total_amount_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(advance_paid__gte=0),
                name='booking_advance_non_negative',
            ),
        ]


class BookingTransfer(models.Model):
    PAYMENT_HANDLING_CHOICES = [
        ('transfer', 'Transfer to New Customer'),
        ('refund', 'Refund to Original Customer'),
    ]
    
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='transfers')
    from_customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='transfers_out')
    to_customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='transfers_in')
    transfer_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    previous_payments_handling = models.CharField(max_length=20, choices=PAYMENT_HANDLING_CHOICES, default='transfer')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfers_approved')
    transfer_date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    def __str__(self):
        return f"Transfer {self.booking.booking_id}: {self.from_customer} → {self.to_customer}"


class BookingAmendment(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='amendments')
    field_name = models.CharField(max_length=100)
    old_value = models.TextField()
    new_value = models.TextField()
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-changed_at']


class InstallmentPlanTemplate(models.Model):
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half_yearly', 'Half-Yearly'),
        ('yearly', 'Yearly'),
    ]
    
    name = models.CharField(max_length=100)
    project = models.ForeignKey('properties.Project', on_delete=models.CASCADE, related_name='plan_templates')
    total_installments = models.PositiveIntegerField()
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    down_payment_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=10.00)
    late_fee_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    grace_period_days = models.PositiveIntegerField(default=0)
    has_balloon_payment = models.BooleanField(default=False)
    balloon_installment_number = models.PositiveIntegerField(null=True, blank=True)
    balloon_multiplier = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} - {self.total_installments} {self.frequency}"


class InstallmentPlan(models.Model):
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half_yearly', 'Half-Yearly'),
        ('yearly', 'Yearly'),
    ]
    
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='installment_plan')
    template = models.ForeignKey(InstallmentPlanTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    total_installments = models.PositiveIntegerField(default=12)
    installment_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    down_payment_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    start_date = models.DateField()
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    due_day = models.PositiveIntegerField(default=1, help_text="Day of month for due date")
    late_fee_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    grace_period_days = models.PositiveIntegerField(default=0)
    total_late_fee_applied = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_auto_processed = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Plan for {self.booking.booking_id} - {self.total_installments} installments"
    
    def auto_generate(self):
        """Generate all installments based on plan configuration."""
        from datetime import date, timedelta
        from dateutil.relativedelta import relativedelta
        
        remaining = self.booking.total_amount - self.down_payment_amount
        self.installments.all().delete()
        
        for i in range(1, self.total_installments + 1):
            if self.frequency == 'monthly':
                due = self.start_date + relativedelta(months=i)
            elif self.frequency == 'quarterly':
                due = self.start_date + relativedelta(months=i * 3)
            elif self.frequency == 'half_yearly':
                due = self.start_date + relativedelta(months=i * 6)
            else:
                due = self.start_date + relativedelta(years=i)
            
            # Adjust to due_day
            try:
                due = due.replace(day=min(self.due_day, 28))
            except ValueError:
                due = due.replace(day=28)
            
            # Balloon payment
            amount = self.installment_amount
            if self.template and self.template.has_balloon_payment and i == self.template.balloon_installment_number:
                amount *= self.template.balloon_multiplier
            
            Installment.objects.create(
                plan=self,
                installment_number=i,
                due_date=due,
                amount=amount,
                status='pending'
            )

    def recalculate(self):
        """Recalculate the plan so unpaid installments cover exactly the
        booking's current remaining balance, preserving paid installments
        and the schedule (count and due dates). Called automatically after
        every payment is recorded, verified, or reversed.
        """
        from datetime import date
        from decimal import Decimal

        remaining = self.booking.remaining_balance
        unpaid = list(
            self.installments.exclude(status='paid').order_by('installment_number')
        )
        n = len(unpaid)
        if n == 0:
            return

        if remaining <= 0:
            # Fully paid: settle every unpaid installment.
            for inst in unpaid:
                inst.paid_amount = inst.amount + inst.late_fee
                inst.status = 'paid'
                inst.paid_date = inst.paid_date or date.today()
                inst.save()
            return

        # Money already allocated to partially-paid installments stays put;
        # the remaining balance is spread evenly across all unpaid ones.
        allocated = sum((inst.paid_amount for inst in unpaid), Decimal('0'))
        target_total = remaining + allocated
        base = (target_total / n).quantize(Decimal('0.01'))
        base = Decimal(base)

        for idx, inst in enumerate(unpaid):
            if idx < n - 1:
                inst.amount = base
            else:
                # Last installment absorbs any rounding remainder.
                inst.amount = target_total - base * (n - 1)
            if inst.paid_amount >= inst.amount:
                inst.status = 'paid'
                inst.paid_date = inst.paid_date or date.today()
            elif inst.paid_amount > 0:
                inst.status = 'partial'
            else:
                inst.status = 'pending'
            inst.save()

    class Meta:
        verbose_name_plural = 'Installment Plans'


class LateFeeConfiguration(models.Model):
    CALCULATION_CHOICES = [
        ('per_day', 'Per Day Fixed'),
        ('per_day_percentage', 'Percentage Per Day'),
        ('monthly_percentage', 'Monthly Percentage'),
        ('tiered', 'Tiered'),
    ]
    
    plan = models.OneToOneField(InstallmentPlan, on_delete=models.CASCADE, related_name='late_fee_config')
    calculation_method = models.CharField(max_length=20, choices=CALCULATION_CHOICES, default='per_day')
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_late_fee_per_installment = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    min_late_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    waiver_allowed = models.BooleanField(default=True)
    tiered_rules = models.JSONField(blank=True, default=dict)


class InstallmentReschedule(models.Model):
    REASONS = [
        ('customer_request', 'Customer Request'),
        ('financial_hardship', 'Financial Hardship'),
        ('system_error', 'System Error'),
        ('other', 'Other'),
    ]
    
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name='reschedules')
    installment = models.ForeignKey('Installment', on_delete=models.CASCADE, null=True, blank=True)
    original_due_date = models.DateField()
    new_due_date = models.DateField()
    reason = models.CharField(max_length=30, choices=REASONS)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    rescheduled_at = models.DateTimeField(auto_now_add=True)
    new_installment_count = models.PositiveIntegerField(null=True, blank=True)
    new_installment_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)


class Installment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('partial', 'Partial'),
    ]
    
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name='installments')
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    paid_date = models.DateField(null=True, blank=True)
    payment_allocation = models.JSONField(blank=True, default=dict, help_text="Audit trail of which payments covered this installment")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Installment {self.installment_number} - {self.plan.booking.booking_id}"
    
    @property
    def remaining_amount(self):
        return (self.amount + self.late_fee) - self.paid_amount
    
    class Meta:
        ordering = ['due_date']
        unique_together = ['plan', 'installment_number']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='installment_amount_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__gte=0),
                name='installment_paid_non_negative',
            ),
        ]


class PaymentReminder(models.Model):
    TYPE_CHOICES = [
        ('upcoming', 'Upcoming Due Reminder'),
        ('overdue', 'Overdue Reminder'),
        ('grace_period', 'Grace Period Ending'),
        ('late_fee', 'Late Fee Applied'),
    ]
    
    installment = models.ForeignKey(Installment, on_delete=models.CASCADE, related_name='reminders')
    reminder_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_via = models.CharField(max_length=20, choices=[('sms', 'SMS'), ('email', 'Email'), ('both', 'Both')])
    message = models.TextField()
    delivery_status = models.CharField(max_length=20, default='pending')


class EarlySettlement(models.Model):
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name='early_settlements')
    remaining_installments = models.PositiveIntegerField()
    total_remaining_amount = models.DecimalField(max_digits=15, decimal_places=2)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    settlement_amount = models.DecimalField(max_digits=15, decimal_places=2)
    approved = models.BooleanField(default=False)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)