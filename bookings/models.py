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
    
    def save(self, *args, **kwargs):
        if not self.booking_id:
            last_booking = Booking.objects.order_by('-id').first()
            if last_booking:
                last_num = int(last_booking.booking_id.split('-')[1])
                self.booking_id = f'BKG-{str(last_num + 1).zfill(5)}'
            else:
                self.booking_id = 'BKG-00001'
        
        # Track status change for audit
        if self.pk:
            original = Booking.objects.get(pk=self.pk)
            if original.status != self.status:
                from core.models import AuditLog
                AuditLog.objects.create(
                    action='update',
                    model_name='Booking',
                    object_id=self.booking_id,
                    description=f'Booking status changed from {original.status} to {self.status}'
                )
        
        super().save(*args, **kwargs)
    
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

    class Meta:
        ordering = ['-created_at']


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