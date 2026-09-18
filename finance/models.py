"""Unified financial ledger.

Phase 1 wrote single-entry ``AccountTransaction`` rows. Phase 2 (in progress)
makes the double-entry ``Voucher``/``VoucherLine`` ledger the books of record;
``AccountTransaction`` is deprecated outright with no bridge (spec §3.7).

Writers migrated (all money movements now post vouchers):
- ``Payment`` — Cash/Bank Receipt voucher on save.
- ``OfficeExpense`` / ``ProjectCost`` — Cash/Bank Payment voucher (ProjectCost
  only on the Paid transition).
- ``Refund`` / ``Expense`` / ``SalaryPayment`` — Cash/Bank Payment voucher.

``AccountTransaction`` is retained only as a deprecated model with no writers.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone
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
        """Idempotently post a Cash/Bank Payment voucher for this expense.

        Replaces the legacy single-entry ``AccountTransaction`` write (spec
        §3.7) — nothing is written to ``AccountTransaction`` any more. Keyed on
        ``(reference_type, reference_id)`` so re-posting never duplicates.
        """
        from .accounting import (
            cash_bank_head, office_expense_head, post_source_voucher,
            voucher_type_for,
        )
        return post_source_voucher(
            reference_type='OfficeExpense', reference_id=self.pk,
            voucher_type=voucher_type_for(self.payment_method, 'payment'),
            date=self.expense_date,
            narration=f'Office expense - {self.office.name}'
                      f"{f' - {self.category.name}' if self.category else ''}",
            lines=[
                (office_expense_head(), self.amount, Decimal('0.00')),
                (cash_bank_head(self.payment_method), Decimal('0.00'), self.amount),
            ],
            user=self.created_by,
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

    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online'),
    ]

    project = models.ForeignKey('properties.Project', on_delete=models.CASCADE, related_name='costs')
    cost_category = models.CharField(max_length=20, choices=COST_CATEGORY_CHOICES, default='other')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    cost_date = models.DateField()
    vendor = models.CharField(max_length=200, blank=True)
    invoice_ref = models.CharField(max_length=100, blank=True)
    payment_method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default='cash',
        help_text='Determines the Cash/Bank ledger head the cost posts against.',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='project_costs_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project.name} - {self.get_cost_category_display()} - {self.amount}"

    def post_to_ledger(self):
        """Post a Payment voucher, but only once the cost is Paid (spec §3.9).

        Fires exactly at the Paid transition and nowhere else; idempotent via the
        ``(reference_type, reference_id)`` key. No ``AccountTransaction`` write.
        """
        if self.status != 'paid':
            return None
        from .accounting import (
            cash_bank_head, post_source_voucher, project_cost_head,
            voucher_type_for,
        )
        method = self.payment_method
        return post_source_voucher(
            reference_type='ProjectCost', reference_id=self.pk,
            voucher_type=voucher_type_for(method, 'payment'),
            date=self.cost_date,
            narration=f'{self.project.name} - {self.get_cost_category_display()}',
            lines=[
                (project_cost_head(), self.amount, Decimal('0.00')),
                (cash_bank_head(method), Decimal('0.00'), self.amount),
            ],
            user=self.created_by,
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


# ─── DOUBLE-ENTRY ACCOUNTING (Accounting Module) ───────────────────────────────
# Phase 2 draft. Replaces the single-entry ``AccountTransaction`` ledger as the
# source of truth for the books once live. ``AccountTransaction`` is deprecated
# outright: writers stop, nothing syncs to it, nothing read-only-bridges it.

NATURE_CHOICES = [
    ('debit', 'Debit Normal'),
    ('credit', 'Credit Normal'),
]


class AccountHead(models.Model):
    """Chart-of-accounts head. Tree up to 4 levels; only leaves are postable."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children',
    )
    nature = models.CharField(max_length=10, choices=NATURE_CHOICES, default='debit')
    is_leaf = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.name}'

    @property
    def level(self):
        level = 1
        node = self
        while node.parent_id:
            level += 1
            node = node.parent
        return level

    @property
    def balance(self):
        """Signed balance respecting the account's nature (for ledger reports)."""
        dr = self.voucher_lines.aggregate(t=Sum('debit'))['t'] or 0
        cr = self.voucher_lines.aggregate(t=Sum('credit'))['t'] or 0
        return dr - cr if self.nature == 'debit' else cr - dr

    def clean(self):
        errors = {}
        if self.level > 4:
            errors['parent'] = 'Chart of accounts supports only 4 levels.'
        if self.pk and self.parent_id == self.pk:
            errors['parent'] = 'An account cannot be its own parent.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.parent_id:
                parent = AccountHead.objects.select_for_update().get(pk=self.parent_id)
                if parent.is_leaf:
                    parent.is_leaf = False
                    parent.save(update_fields=['is_leaf'])
            self.full_clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        parent = self.parent
        result = super().delete(*args, **kwargs)
        if parent and not parent.children.exists():
            parent.is_leaf = True
            parent.save(update_fields=['is_leaf'])
        return result


class Voucher(models.Model):
    """An accounting voucher (receipt / payment / journal): draft or posted.

    Workflow: a user inputs a draft; an authorized finance user posts it
    (``post``), setting ``status='posted'`` and ``is_locked=True``. A posted
    voucher is immutable until a supervisor unlocks it
    (``unlock(reason=...)``), which only flips ``is_locked`` — ``status`` stays
    'posted'. Re-posting after edits re-locks it and refreshes
    ``locked_by``/``locked_at``. Post is gated to finance users, unlock to
    supervisors, mirroring the office-expense approve/pay permission pattern.

    Auto-generated vouchers (Payment, OfficeExpense, ProjectCost, Refund,
    SalaryPayment) reference their source object via ``reference_type`` /
    ``reference_id``; the conditional unique constraint guarantees one source
    maps to at most one voucher (idempotency), unlike the old
    ``AccountTransaction.reference`` pattern which is NOT reused for lines.
    """

    TYPE_CHOICES = [
        ('CR', 'Cash Receipt'),
        ('CP', 'Cash Payment'),
        ('BR', 'Bank Receipt'),
        ('BP', 'Bank Payment'),
        ('JV', 'Journal Voucher'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
    ]

    voucher_number = models.CharField(max_length=30, unique=True, editable=False)
    voucher_type = models.CharField(max_length=2, choices=TYPE_CHOICES)
    date = models.DateField()
    narration = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')

    # Drafts are freely editable. Posting flips ``status`` to 'posted' and sets
    # ``is_locked``; unlock flips ``is_locked`` back without touching ``status``.
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='locked_vouchers',
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    unlocked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='unlocked_vouchers',
    )
    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlock_reason = models.TextField(blank=True)

    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.PositiveIntegerField(null=True, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vouchers_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                # One source object → at most one voucher (auto-generation idempotency).
                # Manual vouchers (null reference) are exempt.
                fields=['reference_type', 'reference_id'],
                condition=models.Q(reference_id__isnull=False),
                name='voucher_source_unique',
            ),
        ]

    def __str__(self):
        return f'{self.voucher_number} ({self.get_voucher_type_display()})'

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not is_new and not kwargs.get('update_fields') and not self.is_editable:
            raise ValidationError(
                f'Voucher {self.voucher_number} is posted and locked; a supervisor '
                'must unlock it before it can be edited.'
            )
        if not self.voucher_number:
            with transaction.atomic():
                last = (
                    Voucher.objects.filter(voucher_type=self.voucher_type)
                    .select_for_update().order_by('-id').first()
                )
                if last:
                    last_num = int(last.voucher_number.split('-')[1])
                    self.voucher_number = f'{self.voucher_type}-{str(last_num + 1).zfill(5)}'
                else:
                    self.voucher_number = f'{self.voucher_type}-00001'
        super().save(*args, **kwargs)
        if is_new:
            self._log_event('created', self.created_by)

    def _log_event(self, event, user=None, reason=''):
        """Append one row to this voucher's lifecycle history (see §3.10)."""
        VoucherAuditLog.objects.create(
            voucher=self, event=event, actor=user, reason=reason,
        )

    @property
    def is_editable(self):
        """Drafts are editable; posted vouchers only while unlocked."""
        return self.status == 'draft' or not self.is_locked

    @property
    def is_posted_locked(self):
        return self.status == 'posted' and self.is_locked

    def clean(self):
        if self.pk and not self.is_editable:
            raise ValidationError(
                f'Voucher {self.voucher_number} is posted and locked; a supervisor '
                'must unlock it before it can be edited.'
            )

    def post(self, user=None):
        """Authorize and post the voucher atomically.

        Validates the voucher is balanced and that every line posts to a leaf
        head, then flips ``status`` to 'posted' and locks it. Safe to call on an
        unlocked posted voucher to re-post after edits — this re-locks and
        refreshes ``locked_by``/``locked_at``.
        """
        if not self.pk:
            raise ValidationError('Save the voucher before posting it.')
        if self.is_posted_locked:
            raise ValidationError(
                f'Voucher {self.voucher_number} is already posted and locked.'
            )
        lines = list(self.lines.select_related('account_head'))
        if not lines:
            raise ValidationError('Cannot post a voucher with no lines.')
        for line in lines:
            line.clean()
        total_dr = sum((line.debit for line in lines), Decimal('0.00'))
        total_cr = sum((line.credit for line in lines), Decimal('0.00'))
        if total_dr != total_cr:
            raise ValidationError(
                f'Voucher is not balanced: debit {total_dr} != credit {total_cr}.'
            )
        prior_post = self.audit_logs.filter(event__in=['posted', 'reposted']).exists()
        with transaction.atomic():
            self.status = 'posted'
            self.is_locked = True
            self.locked_by = user
            self.locked_at = timezone.now()
            self.save(update_fields=[
                'status', 'is_locked', 'locked_by', 'locked_at', 'updated_at',
            ])
            self._log_event('reposted' if prior_post else 'posted', user)
        return self

    def unlock(self, user=None, reason=None):
        """Supervisor action: make a posted, locked voucher editable again.

        ``reason`` is mandatory and recorded on the voucher. ``status`` stays
        'posted'; only ``is_locked`` flips to False. Role gating (supervisor /
        ``management_or_above``) is enforced at the view layer, mirroring the
        office-expense approve/pay pattern.
        """
        if not self.pk or self.status != 'posted' or not self.is_locked:
            raise ValidationError('Only a posted, locked voucher can be unlocked.')
        if not (reason or '').strip():
            raise ValidationError({'unlock_reason': 'An unlock reason is required.'})
        with transaction.atomic():
            self.is_locked = False
            self.unlocked_by = user
            self.unlocked_at = timezone.now()
            self.unlock_reason = reason.strip()
            self.save(update_fields=[
                'is_locked', 'unlocked_by', 'unlocked_at', 'unlock_reason',
                'updated_at',
            ])
            self._log_event('unlocked', user, reason=reason.strip())
        return self


class VoucherLine(models.Model):
    """One leg of a voucher. Exactly one of debit/credit is non-zero."""

    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='lines')
    account_head = models.ForeignKey(
        AccountHead, on_delete=models.PROTECT, related_name='voucher_lines',
    )
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    narration = models.CharField(max_length=255, blank=True)

    def clean(self):
        errors = {}
        if self.voucher_id and not self.voucher.is_editable:
            raise ValidationError(
                f'Voucher {self.voucher.voucher_number} is posted and locked; '
                'unlock it before changing its lines.'
            )
        if self.debit and self.credit:
            errors['credit'] = 'A line cannot have both a debit and a credit.'
        if not self.debit and not self.credit:
            errors['debit'] = 'A line must have a debit or a credit.'
        if self.debit < 0 or self.credit < 0:
            errors['debit'] = 'Amounts cannot be negative.'
        if self.account_head_id and not self.account_head.is_leaf:
            errors['account_head'] = 'Postings are only allowed on leaf accounts.'
        if errors:
            raise ValidationError(errors)

    def _assert_editable(self):
        if self.voucher_id and not self.voucher.is_editable:
            raise ValidationError(
                f'Voucher {self.voucher.voucher_number} is posted and locked; '
                'unlock it before changing its lines.'
            )

    def save(self, *args, **kwargs):
        # Hard guard (spec §3.18): clean() is not called by save(), so enforce
        # the post/unlock rule here too.
        self._assert_editable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_editable()
        return super().delete(*args, **kwargs)

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=(Q(debit__gt=0) & Q(credit=0)) | (Q(credit__gt=0) & Q(debit=0)),
                name='voucher_line_single_side_nonzero',
            ),
        ]

    def __str__(self):
        return f'{self.voucher.voucher_number} {self.account_head.name}'


VOUCHER_EVENT_CHOICES = [
    ('created', 'Created'),
    ('posted', 'Posted'),
    ('unlocked', 'Unlocked'),
    ('reposted', 'Re-posted'),
]


class VoucherAuditLog(models.Model):
    """Append-only history of a voucher's lifecycle (one row per event).

    See the module spec §3.10: ``Voucher``'s ``locked_*``/``unlocked_*`` fields
    only cache the *current* lock state; this log retains every post/unlock/
    re-post cycle (who, when, and why) for financial auditability.
    """

    voucher = models.ForeignKey(
        Voucher, on_delete=models.CASCADE, related_name='audit_logs',
    )
    event = models.CharField(max_length=10, choices=VOUCHER_EVENT_CHOICES)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='voucher_events',
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Voucher audit log'
        verbose_name_plural = 'Voucher audit logs'

    def __str__(self):
        return f'{self.voucher.voucher_number} {self.event}'
