from django.db import models
from django.contrib.auth.models import User


class Project(models.Model):
    STATUS_CHOICES = [
        ('coming_soon', 'Coming Soon'),
        ('booking_open', 'Booking Open'),
        ('under_construction', 'Under Construction'),
        ('completed', 'Completed'),
        ('inactive', 'Inactive'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200)
    total_plots = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='booking_open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    @property
    def available_plots(self):
        return self.plots.filter(status='available').count()
    
    @property
    def booked_plots(self):
        return self.plots.filter(status__in=['booked', 'reserved']).count()
    
    @property
    def sold_plots(self):
        return self.plots.filter(status='sold').count()
    
    class Meta:
        verbose_name_plural = 'Projects'


class ProjectPhase(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='phases')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    launch_date = models.DateField()
    total_plots = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    price_per_marla = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    def __str__(self):
        return f"{self.project.name} - {self.name}"


class PlotFeature(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, blank=True)
    
    def __str__(self):
        return self.name


class PlotDocument(models.Model):
    plot = models.ForeignKey('Plot', on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=100)
    file = models.FileField(upload_to='plot_documents/%Y/%m/')
    uploaded_at = models.DateTimeField(auto_now_add=True)


class Plot(models.Model):
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('reserved', 'Reserved'),
        ('on_hold', 'On Hold'),
        ('booked', 'Booked'),
        ('sold', 'Sold'),
        ('cancelled', 'Cancelled'),
    ]
    
    TYPE_CHOICES = [
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('industrial', 'Industrial'),
    ]
    
    plot_number = models.CharField(max_length=50)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='plots')
    phase = models.ForeignKey(ProjectPhase, on_delete=models.SET_NULL, null=True, blank=True, related_name='plots')
    plot_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='residential')
    size_marla = models.DecimalField(max_digits=10, decimal_places=2, help_text="Size in Marla")
    size_sqft = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Size in Square Feet")
    price = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    block = models.CharField(max_length=50, blank=True, help_text="Block/Sector e.g. A, B, C")
    street_number = models.CharField(max_length=20, blank=True)
    is_corner = models.BooleanField(default=False)
    is_park_facing = models.BooleanField(default=False)
    facing_direction = models.CharField(max_length=20, blank=True, help_text="North/South/East/West")
    features = models.ManyToManyField(PlotFeature, blank=True)
    holding_deposit = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Required token/holding amount")
    development_charge = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Development/infrastructure charge payable by the buyer")
    lease_charge = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Lease/registration charge payable by the buyer")
    other_charges = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Other one-off plot charges (e.g. documentation)")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.project.name} - {self.plot_number}"
    
    @property
    def total_charges(self):
        """Sum of all additional plot charges (excluding base price)."""
        from decimal import Decimal
        return (
            Decimal(self.development_charge or 0)
            + Decimal(self.lease_charge or 0)
            + Decimal(self.other_charges or 0)
        )

    @property
    def total_cost(self):
        """Full payable price for the plot = base price + all charges.

        Single source of truth for 'total plot cost' used by bookings,
        payment screens, receipts, customer statements, and reports so
        nothing double-counts or omits a charge.
        """
        from decimal import Decimal
        return Decimal(self.price or 0) + self.total_charges

    class Meta:
        unique_together = ['project', 'plot_number']
        ordering = ['project', 'plot_number']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['project', 'status']),
        ]


class ProjectMilestone(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('delayed', 'Delayed'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='milestones')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    start_date = models.DateField(null=True, blank=True, help_text='Planned start date')
    milestone_type = models.CharField(
        max_length=20,
        choices=[
            ('construction', 'Construction'),
            ('payment', 'Payment'),
            ('development', 'Development'),
            ('documentation', 'Documentation'),
            ('handover', 'Handover'),
            ('other', 'Other'),
        ],
        default='construction',
        help_text='Category of this milestone'
    )
    completion_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, blank=True, null=True, help_text='Completion % (0-100)')
    progress_date = models.DateField(null=True, blank=True, help_text='Date of last progress/completion update')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project.name} — {self.title}"

    class Meta:
        ordering = ['order', 'target_date']


class PriceHistory(models.Model):
    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name='price_history')
    old_price = models.DecimalField(max_digits=15, decimal_places=2)
    new_price = models.DecimalField(max_digits=15, decimal_places=2)
    change_reason = models.CharField(max_length=100, blank=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = 'Price Histories'
        ordering = ['-changed_at']


class PlotImport(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    file = models.FileField(upload_to='plot_imports/')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], default='pending')
    error_log = models.TextField(blank=True)
    plots_created = models.PositiveIntegerField(default=0)
    plots_failed = models.PositiveIntegerField(default=0)