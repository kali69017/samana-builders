from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Expense(models.Model):
    EXPENSE_TYPES = [
        ('internal', 'Internal'),
        ('external', 'External'),
        ('miscellaneous', 'Miscellaneous'),
    ]

    project = models.ForeignKey(
        'properties.Project', on_delete=models.CASCADE,
        related_name='expenses', verbose_name='Project',
    )
    description = models.TextField()
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    expense_type = models.CharField(max_length=20, choices=EXPENSE_TYPES, default='internal')
    paid_to = models.CharField(max_length=200, blank=True, verbose_name='Paid To')
    expense_date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='expenses_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.expense_type.title()} · {self.amount} — {self.project.name}"

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