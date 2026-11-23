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
from django.db import connection, models, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Lower
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
        constraints = [
            models.UniqueConstraint(
                Lower('name'), name='uniq_expense_category_name_ci',
            ),
        ]


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
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name='expenses',
    )
    expense_account = models.ForeignKey(
        'finance.AccountHead', on_delete=models.PROTECT, null=True, blank=True,
        related_name='office_expenses_posted_to',
        help_text='Expense account under the Expenses root.',
    )
    paid_from = models.ForeignKey(
        'finance.AccountHead', on_delete=models.PROTECT, null=True, blank=True,
        related_name='office_expenses_paid_from',
        help_text='Cash or bank account used to pay this expense.',
    )
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

    def delete(self, *args, **kwargs):
        from .accounting import block_source_delete
        block_source_delete(self, 'OfficeExpense')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.office.name} - {self.category.name if self.category else 'Expense'} - {self.amount}"

    @property
    def posted_voucher(self):
        """The ledger voucher this expense posted to, or None if not yet posted.

        FIN-EC-03: a posted voucher is immutable, so editing the expense does NOT
        rewrite it. ``ledger_out_of_sync`` flags the resulting divergence.
        """
        if not self.pk:
            return None
        return Voucher.objects.filter(
            reference_type='OfficeExpense', reference_id=self.pk).first()

    @property
    def ledger_out_of_sync(self):
        """True when a posted voucher exists but its amount no longer matches.

        Edits to a paid expense deliberately do not rewrite the immutable voucher,
        so the two records can permanently disagree. This is the reconciliation
        signal the list and edit form surface to the user.
        """
        voucher = self.posted_voucher
        if voucher is None:
            return False
        return voucher.total_debit != self.amount

    def post_to_ledger(self):
        """Post through the central finance posting service (idempotent)."""
        from .accounting import post_office_expense
        return post_office_expense(self)

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

    project = models.ForeignKey('properties.Project', on_delete=models.CASCADE, related_name='costs')
    cost_category = models.CharField(max_length=20, choices=COST_CATEGORY_CHOICES, default='other')
    expense_account = models.ForeignKey(
        'finance.AccountHead', on_delete=models.PROTECT, null=True, blank=True,
        related_name='project_costs_posted_to',
        help_text='Expense account under the Expenses root.',
    )
    paid_from = models.ForeignKey(
        'finance.AccountHead', on_delete=models.PROTECT, null=True, blank=True,
        related_name='project_costs_paid_from',
        help_text='Cash or bank account used to pay this cost.',
    )
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

    def delete(self, *args, **kwargs):
        from .accounting import block_source_delete
        block_source_delete(self, 'ProjectCost')
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} - {self.get_cost_category_display()} - {self.amount}"

    @property
    def posted_voucher(self):
        """The ledger voucher this cost posted to, or None if not yet posted."""
        if not self.pk:
            return None
        return Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=self.pk).first()

    @property
    def ledger_out_of_sync(self):
        """True when a posted voucher exists but its amount no longer matches.

        Same FIN-EC-03 contract as ``OfficeExpense``: the immutable voucher is
        never rewritten, so flag the divergence rather than hiding it.
        """
        voucher = self.posted_voucher
        if voucher is None:
            return False
        return voucher.total_debit != self.amount

    def post_to_ledger(self):
        """Post through the central finance posting service (idempotent)."""
        from .accounting import post_project_cost
        return post_project_cost(self)

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

ACCOUNT_KIND_CHOICES = [
    ('normal', 'Normal'),
    ('cash', 'Cash'),
    ('bank', 'Bank'),
]

SYSTEM_ROLE_CHOICES = [
    ('cash_default', 'Cash default'),
    ('bank_default', 'Bank default'),
    ('receivable', 'Accounts receivable'),
    ('project_costs', 'Project costs'),
    ('office_expenses', 'Office expenses'),
    ('salaries', 'Salaries'),
    ('customer_advances', 'Customer advances'),
    ('revenue', 'Revenue'),
    ('refunds', 'Refunds'),
    ('payable', 'Accounts payable'),
]

ROOT_NATURES = {
    '1': 'debit',
    '2': 'credit',
    '3': 'credit',
    '4': 'credit',
    '5': 'debit',
}


class AccountHead(models.Model):
    """Chart-of-accounts head. Tree up to 4 levels; only leaves are postable."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=150)
    parent = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='children',
    )
    nature = models.CharField(max_length=10, choices=NATURE_CHOICES, default='debit')
    account_kind = models.CharField(
        max_length=10, choices=ACCOUNT_KIND_CHOICES, default='normal',
    )
    system_role = models.CharField(
        max_length=30, choices=SYSTEM_ROLE_CHOICES, null=True, blank=True,
        help_text='Stable role used by automated finance postings.',
    )
    is_leaf = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(
                fields=['system_role'],
                condition=Q(system_role__isnull=False),
                name='uniq_account_system_role',
            ),
        ]

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
    def root(self):
        node = self
        while node.parent_id:
            node = node.parent
        return node

    @property
    def is_root(self):
        return self.parent_id is None

    @property
    def is_asset(self):
        return self.root.code == '1'

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
        if self.parent_id and self.pk:
            node = self.parent
            while node is not None:
                if node.pk == self.pk:
                    errors['parent'] = 'Parent cannot be a descendant of this account.'
                    break
                node = node.parent
        if self.account_kind != 'normal' and self.root.code != '1':
            errors['account_kind'] = 'Cash and bank flags are only allowed under Assets.'
        if errors:
            raise ValidationError(errors)

    def _next_child_code(self, parent):
        prefix = f'{parent.code}.'
        numbers = []
        for code in AccountHead.objects.filter(parent=parent).values_list('code', flat=True):
            if code.startswith(prefix):
                suffix = code[len(prefix):]
                if suffix.isdigit():
                    numbers.append(int(suffix))
        return f'{prefix}{max(numbers, default=0) + 1}'

    def _subtree_height(self):
        children = list(self.children.all())
        if not children:
            return 1
        return 1 + max(child._subtree_height() for child in children)

    def _refresh_descendant_codes(self):
        for index, child in enumerate(self.children.order_by('code'), start=1):
            child.code = f'{self.code}.{index}'
            child.nature = self.nature
            AccountHead.objects.filter(pk=child.pk).update(code=child.code, nature=child.nature)
            child._refresh_descendant_codes()

    def _root_guard(self, old, update_fields):
        if old.parent_id is not None:
            return
        allowed = {'is_leaf'}
        changed = {
            field for field in ('code', 'name', 'parent', 'nature', 'account_kind',
                                'system_role', 'is_active')
            if getattr(self, field) != getattr(old, field)
        }
        if changed and not (changed <= allowed and set(update_fields or ()) <= allowed):
            raise ValidationError('Level 1 root accounts cannot be edited or deactivated.')

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        if self._state.adding:
            if not self.parent_id:
                if self.code not in ROOT_NATURES:
                    raise ValidationError({'parent': 'A non-root account must have a parent.'})
                self.nature = ROOT_NATURES[self.code]
                super().save(*args, **kwargs)
                return
            with transaction.atomic():
                parent = AccountHead.objects.select_for_update().get(pk=self.parent_id)
                self.parent = parent
                if not self.code:
                    self.code = self._next_child_code(parent)
                self.nature = parent.nature
                self.full_clean()
                super().save(*args, **kwargs)
                if parent.is_leaf:
                    AccountHead.objects.filter(pk=parent.pk).update(is_leaf=False)
            return

        with transaction.atomic():
            old = AccountHead.objects.select_for_update().get(pk=self.pk)
            self._root_guard(old, update_fields)
            if old.parent_id is None:
                self.nature = 'debit' if self.code == '1' else (
                    'debit' if self.code == '5' else 'credit'
                )
                super().save(*args, **kwargs)
                return

            if old.parent_id != self.parent_id:
                if self.voucher_lines.exists():
                    raise ValidationError(
                        {'parent': 'The parent cannot be changed after ledger entries exist.'}
                    )
                parent = AccountHead.objects.select_for_update().get(pk=self.parent_id)
                if parent.level + self._subtree_height() > 4:
                    raise ValidationError(
                        {'parent': 'Chart of accounts supports only 4 levels.'}
                    )
                self.parent = parent
                self.nature = parent.nature
                self.code = self._next_child_code(parent)
                self.full_clean()
                super().save(*args, **kwargs)
                self._refresh_descendant_codes()
                if parent.is_leaf:
                    AccountHead.objects.filter(pk=parent.pk).update(is_leaf=False)
                if old.parent_id and not old.parent.children.exists():
                    AccountHead.objects.filter(pk=old.parent_id).update(is_leaf=True)
                return

            self.nature = self.root.nature if self.parent_id else self.nature
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.parent_id is None:
            raise ValidationError('Level 1 root accounts cannot be deleted.')
        if self.children.exists():
            raise ValidationError('An account with children cannot be deleted.')
        if self.voucher_lines.exists():
            raise ValidationError('An account with ledger entries cannot be deleted.')
        if self.system_role:
            raise ValidationError('A system account cannot be deleted.')
        parent = self.parent
        result = super().delete(*args, **kwargs)
        if parent and not parent.children.exists():
            AccountHead.objects.filter(pk=parent.pk).update(is_leaf=True)
        return result


class VoucherQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError('Vouchers cannot be deleted. Reverse them with a new voucher instead.')


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
    cash_bank_account = models.ForeignKey(
        'finance.AccountHead', on_delete=models.PROTECT, null=True, blank=True,
        related_name='vouchers_using_cash_bank',
        help_text='Cash or bank account used by receipt and payment vouchers.',
    )

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

    objects = VoucherQuerySet.as_manager()

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

    def delete(self, *args, **kwargs):
        raise ValidationError(
            'Vouchers cannot be deleted. Reverse them with a new voucher instead.'
        )

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
    def is_manual(self):
        """True only for a voucher with no source record."""
        return not self.reference_type and self.reference_id is None

    def delete_manual_voucher(self, user, reason):
        """Delete a manual voucher and write an immutable deletion snapshot.

        This is the only deletion path. Source-generated vouchers are refused so
        the source record remains the place to make a correction.
        """
        reason = (reason or '').strip()
        if not self.is_manual:
            raise ValidationError(
                'Only manual vouchers can be deleted. Correct the source record instead.'
            )
        if len(reason) < 5:
            raise ValidationError({'reason': 'A deletion reason of at least 5 characters is required.'})
        with transaction.atomic():
            voucher = Voucher.objects.select_for_update().get(pk=self.pk)
            if not voucher.is_manual:
                raise ValidationError(
                    'Only manual vouchers can be deleted. Correct the source record instead.'
                )
            lines = [
                {
                    'account_code': line.account_head.code,
                    'account_name': line.account_head.name,
                    'debit': str(line.debit),
                    'credit': str(line.credit),
                    'narration': line.narration,
                }
                for line in voucher.lines.select_related('account_head').order_by('id')
            ]
            audit_logs = [
                {
                    'event': row.event,
                    'actor': row.actor.username if row.actor else '',
                    'reason': row.reason,
                    'created_at': row.created_at.isoformat(),
                }
                for row in voucher.audit_logs.select_related('actor').order_by('id')
            ]
            log = VoucherDeletionLog.objects.create(
                voucher_number=voucher.voucher_number,
                voucher_type=voucher.voucher_type,
                date=voucher.date,
                narration=voucher.narration,
                status=voucher.status,
                total=voucher.total_debit,
                lines=lines,
                audit_logs=audit_logs,
                created_by=voucher.created_by,
                deleted_by=user,
                reason=reason,
            )
            voucher.audit_logs.all().delete()
            quote = connection.ops.quote_name
            with connection.cursor() as cursor:
                cursor.execute(
                    f'DELETE FROM {quote(VoucherLine._meta.db_table)} '
                    f'WHERE {quote("voucher_id")} = %s',
                    [voucher.pk],
                )
                cursor.execute(
                    f'DELETE FROM {quote(Voucher._meta.db_table)} '
                    f'WHERE {quote("id")} = %s',
                    [voucher.pk],
                )
        return log

    @property
    def is_posted_locked(self):
        return self.status == 'posted' and self.is_locked

    @property
    def total_debit(self):
        return sum((line.debit for line in self.lines.all()), Decimal('0.00'))

    @property
    def total_credit(self):
        return sum((line.credit for line in self.lines.all()), Decimal('0.00'))

    @property
    def is_balanced(self):
        return self.total_debit == self.total_credit

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


class VoucherLineQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError('Voucher lines cannot be deleted. Edit the voucher instead.')


class VoucherLine(models.Model):
    """One leg of a voucher. Exactly one of debit/credit is non-zero."""

    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='lines')
    account_head = models.ForeignKey(
        AccountHead, on_delete=models.PROTECT, related_name='voucher_lines',
    )
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    narration = models.CharField(max_length=255, blank=True)

    objects = VoucherLineQuerySet.as_manager()

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
        raise ValidationError(
            'Voucher lines cannot be deleted. Edit the voucher instead.'
        )

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


class VoucherDeletionLogQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError('Voucher deletion records cannot be deleted.')


class VoucherDeletionLog(models.Model):
    """Immutable snapshot of a deleted manual voucher and its audit history."""

    voucher_number = models.CharField(max_length=30, db_index=True)
    voucher_type = models.CharField(max_length=2, choices=Voucher.TYPE_CHOICES)
    date = models.DateField()
    narration = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Voucher.STATUS_CHOICES)
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    lines = models.JSONField(default=list, blank=True)
    audit_logs = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vouchers_deleted_snapshots_created',
    )
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vouchers_deleted',
    )
    deleted_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    objects = VoucherDeletionLogQuerySet.as_manager()

    class Meta:
        ordering = ['-deleted_at', '-id']
        verbose_name = 'Deleted voucher'
        verbose_name_plural = 'Deleted vouchers'

    def __str__(self):
        return f'{self.voucher_number} deleted by {self.deleted_by}'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Voucher deletion records cannot be edited.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Voucher deletion records cannot be deleted.')
