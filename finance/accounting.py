"""Shared helpers for the double-entry accounting writers (Phase 2).

The auto-writers resolve well-known chart-of-accounts heads by code and post an
idempotent ``Voucher`` keyed on ``(reference_type, reference_id)``. See
``specs/accounting-module.md`` §3.5–§3.9.
"""
from django.db import transaction

from .models import AccountHead, Voucher, VoucherLine

# Canonical heads used by the auto-writers: (code, name, nature).
CASH = ('1000', 'Cash', 'debit')
BANK = ('1010', 'Bank', 'debit')
RECEIVABLE = ('1100', 'Accounts Receivable', 'debit')
OFFICE_EXPENSE = ('5000', 'Office Expenses', 'debit')
PROJECT_COST = ('5100', 'Project Costs', 'debit')
SALARIES = ('5200', 'Salaries', 'debit')

# Methods treated as bank (everything except literal cash).
BANK_METHODS = {'bank_transfer', 'cheque', 'online', 'jazzcash', 'easypaisa', 'raast'}


def get_head(spec):
    """Return (creating if needed) the ``AccountHead`` for a (code, name, nature) spec."""
    code, name, nature = spec
    head, _ = AccountHead.objects.get_or_create(
        code=code, defaults={'name': name, 'nature': nature},
    )
    return head


def cash_bank_head(method):
    """Resolve the Cash or Bank asset head from a payment method."""
    return get_head(CASH if method == 'cash' else BANK)


def receivable_head():
    return get_head(RECEIVABLE)


def office_expense_head():
    return get_head(OFFICE_EXPENSE)


def project_cost_head():
    return get_head(PROJECT_COST)


def salaries_head():
    return get_head(SALARIES)


def voucher_type_for(method, direction):
    """``direction`` is 'receipt' (money in) or 'payment' (money out)."""
    is_cash = method == 'cash'
    if direction == 'receipt':
        return 'CR' if is_cash else 'BR'
    return 'CP' if is_cash else 'BP'


def post_source_voucher(*, reference_type, reference_id, voucher_type, date,
                        narration, lines, user=None):
    """Idempotently create + post a voucher for a source object.

    ``lines`` is an iterable of ``(account_head, debit, credit)`` triples. If a
    voucher already exists for ``(reference_type, reference_id)`` it is returned
    untouched — re-saving the source object never duplicates a voucher.
    """
    existing = Voucher.objects.filter(
        reference_type=reference_type, reference_id=reference_id,
    ).first()
    if existing:
        return existing
    with transaction.atomic():
        voucher = Voucher.objects.create(
            voucher_type=voucher_type, date=date, narration=narration,
            reference_type=reference_type, reference_id=reference_id,
            created_by=user,
        )
        for head, debit, credit in lines:
            VoucherLine.objects.create(
                voucher=voucher, account_head=head, debit=debit, credit=credit,
            )
        voucher.post(user)
    return voucher