"""Ledger report computation for the accounting module (spec §3).

The report is nature-aware: a debit-normal account's running balance grows with
debits (debit − credit); a credit-normal account's grows with credits
(credit − debit). Selecting a parent account rolls up every descendant leaf.
Only **posted** vouchers are included.
"""
from decimal import Decimal

from django.db.models import Sum

from .models import AccountHead, VoucherLine

ZERO = Decimal('0.00')


def _leaf_ids(head):
    """Primary keys of every leaf account at or under ``head``."""
    leaves = []
    stack = [head]
    while stack:
        node = stack.pop()
        children = list(node.children.all())
        if children:
            stack.extend(children)
        else:
            leaves.append(node.pk)
    return leaves


def build_ledger_report(head=None, date_from=None, date_to=None):
    """Return a ledger report dict for ``head`` (leaf) or its roll-up (parent).

    Keys: ``head``, ``nature``, ``rows`` (date, voucher_number, voucher_type,
    account, narration, debit, credit, balance), ``opening_balance``,
    ``total_debit``, ``total_credit``, ``closing_balance``.
    """
    if head is not None:
        head_ids = _leaf_ids(head)
        nature = head.nature
    else:
        head_ids = list(
            AccountHead.objects.filter(is_leaf=True).values_list('pk', flat=True)
        )
        nature = 'debit'

    base = VoucherLine.objects.filter(
        voucher__status='posted', account_head_id__in=head_ids,
    )

    opening = ZERO
    if date_from:
        agg = base.filter(voucher__date__lt=date_from).aggregate(
            d=Sum('debit'), c=Sum('credit'))
        debits = agg['d'] or ZERO
        credits = agg['c'] or ZERO
        opening = (debits - credits) if nature == 'debit' else (credits - debits)

    lines = base.select_related('voucher', 'account_head')
    if date_from:
        lines = lines.filter(voucher__date__gte=date_from)
    if date_to:
        lines = lines.filter(voucher__date__lte=date_to)
    lines = lines.order_by('voucher__date', 'voucher__id', 'id')

    rows = []
    running = opening
    total_debit = ZERO
    total_credit = ZERO
    for line in lines:
        total_debit += line.debit
        total_credit += line.credit
        delta = (line.debit - line.credit) if nature == 'debit' else (line.credit - line.debit)
        running += delta
        rows.append({
            'date': line.voucher.date,
            'voucher_number': line.voucher.voucher_number,
            'voucher_type': line.voucher.get_voucher_type_display(),
            'account': line.account_head,
            'narration': line.narration or line.voucher.narration,
            'debit': line.debit,
            'credit': line.credit,
            'balance': running,
        })

    return {
        'head': head,
        'nature': nature,
        'rows': rows,
        'opening_balance': opening,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'closing_balance': running,
    }