from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import FileExtensionValidator


class Expense(models.Model):
    EXPENSE_TYPES = [
        ('internal', 'Internal'),
        ('external', 'External'),
        ('miscellaneous', 'Miscellaneous'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ]

    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online'),
    ]

    project = models.ForeignKey(
        'properties.Project', on_delete=models.CASCADE,
        related_name='expenses', verbose_name='Project',
    )
    description = models.TextField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES, default='internal')
    paid_to = models.CharField(max_length=200, blank=True, verbose_name='Paid To')
    payment_method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default='cash',
        verbose_name='Payment Method',
        help_text='Determines the Cash/Bank ledger head the expense posts against.',
    )
    expense_date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='expenses_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ─── Expense approval workflow ─────────────────────────────────────────
    payment_reference = models.CharField(
        max_length=100, blank=True,
        verbose_name='Payment Reference / Cheque No.',
        help_text='Cheque No. / Bank Reference / Transaction ID for this expense.',
    )
    receipt_attachment = models.FileField(
        upload_to='expenses/receipts/', blank=True, null=True,
        validators=[FileExtensionValidator(['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'])],
        verbose_name='Receipt / Bill Attachment',
        help_text='Upload a scanned receipt, bill, or invoice as proof.',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name='Approval Status', db_index=True,
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses_approved', verbose_name='Approved By',
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name='Approved At')

    def __str__(self):
        return f"{self.expense_type.title()} · {self.amount} — {self.project.name}"

    @property
    def status_label(self):
        return self.get_status_display()

    def can_be_posted(self):
        """An expense may only hit the final ledger once approved/paid."""
        return self.status in ('approved', 'paid') and not self.status == 'rejected'

    def post_to_ledger(self, user=None):
        """Post this expense to the ledger exactly once (idempotent).

        Spec §3.16: posts a Cash/Bank Payment voucher against the Project Costs
        head, resolving Cash vs Bank from ``payment_method``. Keyed on
        ``reference_type='Expense'`` + ``reference_id=self.pk``.
        """
        from decimal import Decimal
        from finance.accounting import (
            cash_bank_head, post_source_voucher, project_cost_head, voucher_type_for,
        )
        return post_source_voucher(
            reference_type='Expense', reference_id=self.pk,
            voucher_type=voucher_type_for(self.payment_method, 'payment'),
            date=self.expense_date,
            narration=f"{self.project.name} - {self.get_expense_type_display()}: "
                      f"{self.description or self.paid_to}",
            lines=[
                (project_cost_head(), self.amount, Decimal('0.00')),
                (cash_bank_head(self.payment_method), Decimal('0.00'), self.amount),
            ],
            user=user or self.created_by,
        )

    def is_posted_to_ledger(self):
        from finance.models import Voucher
        return Voucher.objects.filter(
            reference_type='Expense', reference_id=self.pk,
        ).exists()

    class Meta:
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['project', 'expense_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='expense_amount_positive',
            ),
        ]