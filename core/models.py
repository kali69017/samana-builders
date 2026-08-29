from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    THEME_CHOICES = [
        ('professional-blue', 'Professional Blue'),
        ('modern-green', 'Modern Green'),
        ('elegant-dark', 'Elegant Dark'),
        ('warm-earth', 'Warm Earth'),
        ('minimalist-purple', 'Minimalist Purple'),
    ]

    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('admin', 'Admin'),
        ('management', 'Management'),
        ('accounts', 'Accounts'),
        ('sales', 'Sales'),
        ('hr', 'HR'),
        ('project_manager', 'Project Manager'),
        ('contractor', 'Contractor'),
        ('staff', 'Staff'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='sales')
    theme = models.CharField(max_length=30, choices=THEME_CHOICES, default='professional-blue')
    phone = models.CharField(max_length=20, blank=True)
    cnic = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_role_display()}"
    
    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'


class LoginAttempt(models.Model):
    username = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_success = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']


class ApprovalChain(models.Model):
    name = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    trigger_field = models.CharField(max_length=100)
    trigger_value = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ApprovalStep(models.Model):
    chain = models.ForeignKey(ApprovalChain, on_delete=models.CASCADE, related_name='steps')
    step_order = models.PositiveIntegerField()
    role = models.CharField(max_length=20, choices=UserProfile.ROLE_CHOICES)
    can_approve = models.BooleanField(default=True)
    can_reject = models.BooleanField(default=True)
    min_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['step_order']


class ApprovalRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    
    approval_step = models.ForeignKey(ApprovalStep, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approval_requests')
    object_id = models.PositiveIntegerField()
    object_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approvals_given')
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)


class Lead(models.Model):
    LEAD_SOURCE_CHOICES = [
        ('hero', 'Hero Enquiry'),
        ('strip', 'Launch Strip'),
        ('newsletter', 'Newsletter Subscribe'),
        ('referral', 'Referral'),
        ('walk_in', 'Walk-In'),
        ('agent', 'Agent'),
        ('other', 'Other'),
    ]
    LEAD_STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('qualified', 'Qualified'),
        ('converted', 'Converted'),
        ('lost', 'Lost'),
    ]

    name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=20, choices=LEAD_SOURCE_CHOICES, default='hero')
    status = models.CharField(max_length=20, choices=LEAD_STATUS_CHOICES, default='new')
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='leads_assigned'
    )
    interest_project = models.ForeignKey(
        'properties.Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='leads'
    )
    budget = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    is_contacted = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    converted_customer = models.ForeignKey(
        'customers.Customer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='converted_leads'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name or self.email or self.phone} - {self.get_source_display()}"

    @property
    def display_name(self):
        return self.name or self.email or self.phone or f'Lead #{self.pk}'

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['source']),
        ]


class LeadNote(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='lead_notes')
    note = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Note for {self.lead.display_name}"

    class Meta:
        ordering = ['-created_at']


class Agent(models.Model):
    """Sales agent / dealer / channel partner who sources bookings."""
    agent_id = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    cnic = models.CharField(max_length=15, blank=True)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Commission percentage paid to the agent per booking'
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.agent_id:
            from django.db import transaction
            with transaction.atomic():
                last = Agent.objects.select_for_update().order_by('-id').first()
                num = int(last.agent_id.split('-')[1]) + 1 if last else 1
                self.agent_id = f'AGT-{str(num).zfill(5)}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.agent_id} - {self.name}"

    @property
    def total_commission_earned(self):
        """Gross commission across all of this agent's bookings."""
        return sum((b.agent_commission for b in self.bookings.all()), 0)

    @property
    def commission_paid(self):
        """Total commission money actually paid out to this agent."""
        from django.db.models import Sum
        return self.commission_payments.aggregate(total=Sum('amount'))['total'] or 0

    @property
    def commission_balance(self):
        """Commission earned but not yet paid to the agent."""
        return self.total_commission_earned - self.commission_paid

    class Meta:
        ordering = ['name']


class AgentCommissionPayment(models.Model):
    """A payment made to an agent against earned commission.

    Tracks the money the company actually pays out versus what has been
    earned. This lets finance see total earned, total paid, and the
    remaining balance owed to each agent.
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='commission_payments')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField(default=None, null=True, blank=True)
    method = models.CharField(max_length=30, blank=True, default='cash',
                              help_text='Cash / Bank Transfer / Cheque, etc.')
    reference = models.CharField(max_length=100, blank=True, help_text='Cheque no. / transaction id / notes')
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='agent_commission_payments')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.agent.name} — Rs. {self.amount} ({self.payment_date})"

    class Meta:
        ordering = ['-payment_date', '-created_at']


class CompanySettings(models.Model):
    """Singleton holding company-wide branding and finance settings."""

    AI_LANGUAGE_CHOICES = [
        ('english', 'English'),
        ('roman_urdu', 'Roman Urdu'),
    ]

    company_name = models.CharField(max_length=200, default='Samana Builders & Developers')
    tagline = models.CharField(max_length=300, blank=True, default='Real Estate Developers')
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    logo = models.ImageField(upload_to='company/', blank=True, null=True)
    currency = models.CharField(max_length=10, default='PKR')
    currency_symbol = models.CharField(max_length=5, default='Rs.')
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Default tax %')
    receipt_footer = models.TextField(blank=True, help_text='Footer text printed on receipts/invoices')
    facebook = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    twitter = models.URLField(blank=True)
    ai_language = models.CharField(
        max_length=20, choices=AI_LANGUAGE_CHOICES, default='english',
        help_text='Global language for AI assistant replies (English or Roman Urdu).'
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        # Enforce singleton
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    class Meta:
        verbose_name = 'Company Settings'
        verbose_name_plural = 'Company Settings'


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('verify', 'Verify'),
        ('reject', 'Reject'),
        ('transfer', 'Transfer'),
        ('cancel', 'Cancel'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.action} - {self.model_name}"

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['model_name', 'object_id']),
            models.Index(fields=['timestamp']),
        ]


class PasswordResetCode(models.Model):
    """One-time 6-digit code emailed to a user to reset their password."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_codes')
    code = models.CharField(max_length=6)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Reset code for {self.user.username} ({'used' if self.used else 'active'})"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    class Meta:
        ordering = ['-created_at']

