"""Unified financial ledger.

Every money movement in the ERP (income, office expenses, project costs,
contractor payments, payroll, refunds) writes an ``AccountTransaction`` row so
that reporting has a single source of truth. Phase 1 covers payroll; office and
project costs add their links in later phases.
"""
from django.db import models
from django.contrib.auth.models import User


class AccountTransaction(models.Model):
    DIRECTION_CHOICES = [
        ('in', 'Money In'),
        ('out', 'Money Out'),
    ]

    TRANSACTION_TYPE_CHOICES = [
        ('income', 'Income'),
        ('office_expense', 'Office Expense'),
        ('project_cost', 'Project Cost'),
        ('contractor_payment', 'Contractor Payment'),
        ('payroll', 'Payroll'),
        ('refund', 'Refund'),
        ('adjustment', 'Adjustment'),
    ]

    date = models.DateField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default='out')
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPE_CHOICES)
    category = models.CharField(max_length=100, blank=True)

    # Source references (polymorphic) — the model/object that produced this entry.
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.PositiveIntegerField(null=True, blank=True)

    employee = models.ForeignKey(
        'hr.Employee', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions',
    )
    project = models.ForeignKey(
        'properties.Project', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions',
    )
    office = models.ForeignKey(
        'finance.Office', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions',
    )
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.direction} {self.amount} on {self.date}"

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['transaction_type']),
            models.Index(fields=['date']),
            models.Index(fields=['direction']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='account_transaction_amount_positive',
            ),
            models.UniqueConstraint(
                # A source object (reference_type + reference_id) must map to at
                # most one ledger row. This is the root-cause guard against
                # duplicate ledger transactions (e.g. a payroll run posted twice
                # creates two SalaryPayment-watching rows). NULL reference_id
                # (unlinked/ad hoc entries) is intentionally exempt.
                fields=['reference_type', 'reference_id'],
                condition=models.Q(reference_id__isnull=False),
                name='account_transaction_reference_unique',
            ),
        ]


class Office(models.Model):
    OFFICE_TYPE_CHOICES = [
        ('head_office', 'Head Office'),
        ('branch', 'Branch'),
    ]

    name = models.CharField(max_length=150, unique=True)
    office_type = models.CharField(max_length=20, choices=OFFICE_TYPE_CHOICES, default='branch')
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.get_office_type_display()})"

    class Meta:
        ordering = ['office_type', 'name']


class ExpenseCategory(models.Model):
    CATEGORY_TYPE_CHOICES = [
        ('rent', 'Rent'),
        ('utilities', 'Utilities'),
        ('internet', 'Internet'),
        ('maintenance', 'Maintenance'),
        ('stationery', 'Stationery'),
        ('salaries', 'Salaries'),
        ('misc', 'Miscellaneous'),
    ]

    name = models.CharField(max_length=100, unique=True)
    category_type = models.CharField(max_length=20, choices=CATEGORY_TYPE_CHOICES, default='misc')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['category_type', 'name']
        verbose_name_plural = 'Expense Categories'


class OfficeExpense(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]

    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online'),
    ]

    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name='expenses')
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, related_name='expenses')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    expense_date = models.DateField()
    paid_to = models.CharField(max_length=200, blank=True)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='bank_transfer')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='office_expenses_approved')
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='office_expenses_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.office.name} - {self.category.name if self.category else 'Expense'} - {self.amount}"

    def post_to_ledger(self):
        AccountTransaction.objects.update_or_create(
            reference_type='OfficeExpense', reference_id=self.pk,
            defaults={
                'date': self.expense_date,
                'amount': self.amount,
                'direction': 'out',
                'transaction_type': 'office_expense',
                'category': self.category.name if self.category else 'Office Expense',
                'office': self.office,
                'description': f'{self.office.name} - {self.description or self.category}',
                'created_by': self.created_by,
            },
        )

    class Meta:
        ordering = ['-expense_date', '-created_at']
        indexes = [models.Index(fields=['office', 'expense_date'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='office_expense_amount_positive',
            ),
        ]


class ProjectBudget(models.Model):
    project = models.OneToOneField('properties.Project', on_delete=models.CASCADE, related_name='budget')
    total_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    material_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    labor_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    contractor_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    transportation_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    other_budget = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Budget for {self.project.name}"

    @property
    def total_actual(self):
        return sum((c.amount for c in self.project.costs.filter(status='paid')), 0)

    @property
    def remaining_budget(self):
        return self.total_budget - self.total_actual

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_budget__gte=0),
                name='project_budget_total_non_negative',
            ),
        ]


class ProjectCost(models.Model):
    COST_CATEGORY_CHOICES = [
        ('material', 'Material'),
        ('labor', 'Labor'),
        ('contractor', 'Contractor'),
        ('transportation', 'Transportation'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]

    project = models.ForeignKey('properties.Project', on_delete=models.CASCADE, related_name='costs')
    cost_category = models.CharField(max_length=20, choices=COST_CATEGORY_CHOICES, default='other')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    cost_date = models.DateField()
    vendor = models.CharField(max_length=200, blank=True)
    invoice_ref = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='project_costs_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project.name} - {self.get_cost_category_display()} - {self.amount}"

    def post_to_ledger(self):
        AccountTransaction.objects.update_or_create(
            reference_type='ProjectCost', reference_id=self.pk,
            defaults={
                'date': self.cost_date,
                'amount': self.amount,
                'direction': 'out',
                'transaction_type': 'project_cost',
                'category': self.get_cost_category_display(),
                'project': self.project,
                'description': f'{self.project.name} - {self.get_cost_category_display()}: {self.description or self.vendor}',
                'created_by': self.created_by,
            },
        )

    class Meta:
        ordering = ['-cost_date', '-created_at']
        indexes = [models.Index(fields=['project', 'cost_category'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='project_cost_amount_positive',
            ),
        ]


class ProjectInvestment(models.Model):
    """Total investment committed to a project (manually maintained)."""
    project = models.OneToOneField('properties.Project', on_delete=models.CASCADE, related_name='investment')
    total_investment = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_investment__gte=0),
                name='project_investment_non_negative',
            ),
        ]

    def __str__(self):
        return f"Investment for {self.project.name}: {self.total_investment}"
