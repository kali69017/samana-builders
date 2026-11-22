"""Shared helpers for the double-entry accounting writers (Phase 2).

The auto-writers resolve well-known chart-of-accounts heads by system role and
post an idempotent ``Voucher`` keyed on ``(reference_type, reference_id)``. See
``specs/accounting-module.md`` §3.5–§3.9.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import AccountHead, Voucher, VoucherLine

# Methods treated as bank (everything except literal cash).
BANK_METHODS = {'bank_transfer', 'cheque', 'online', 'jazzcash', 'easypaisa', 'raast'}


def get_system_account(role):
    """Resolve a system account by stable role, never by a hard-coded code."""
    try:
        return AccountHead.objects.get(system_role=role)
    except AccountHead.DoesNotExist as exc:
        raise RuntimeError(
            f'System account role "{role}" is not configured. Run the finance seed migration.'
        ) from exc


def cash_bank_head(method, explicit=None):
    """Resolve the user-selected or default Cash/Bank asset head."""
    if explicit is not None:
        return explicit
    return get_system_account('cash_default' if method == 'cash' else 'bank_default')


def receivable_head():
    return get_system_account('receivable')


def refund_head():
    return get_system_account('refunds')


def customer_advance_head():
    return get_system_account('customer_advances')


def revenue_head():
    return get_system_account('revenue')


def payable_head():
    return get_system_account('payable')


def office_expense_head():
    return get_system_account('office_expenses')


def project_cost_head():
    return get_system_account('project_costs')


def salaries_head():
    return get_system_account('salaries')


def account_is_under(account, root_code):
    if account is None or account.parent_id is None:
        return False
    return account.root.code == root_code


def validate_cash_bank_account(account, method=None):
    from django.core.exceptions import ValidationError
    if account is None:
        raise ValidationError('Select a cash or bank account.')
    if account.parent_id is None:
        raise ValidationError('Postings are not allowed on a level 1 root.')
    expected = 'cash' if method == 'cash' else 'bank'
    if account.account_kind != expected:
        raise ValidationError(f'Select an account flagged as {expected}.')


def validate_expense_account(account):
    from django.core.exceptions import ValidationError
    if account is None:
        raise ValidationError('Select an expense account.')
    if account.parent_id is None:
        raise ValidationError('Postings are not allowed on a level 1 root.')
    if not account_is_under(account, '5'):
        raise ValidationError('The expense account must be under Expenses.')


def block_source_delete(instance, reference_type):
    """Refuse deletion of a source record once it has a posted voucher."""
    if not instance.pk:
        return
    if Voucher.objects.filter(reference_type=reference_type, reference_id=instance.pk).exists():
        from django.core.exceptions import ValidationError
        raise ValidationError(
            f'{reference_type} {instance.pk} has a posted voucher and cannot be deleted.'
        )


def voucher_type_for(method, direction):
    """``direction`` is 'receipt' (money in) or 'payment' (money out)."""
    is_cash = method == 'cash'
    if direction == 'receipt':
        return 'CR' if is_cash else 'BR'
    return 'CP' if is_cash else 'BP'


def post_payment(payment):
    """Post money received from a customer.

    Before delivery the money is a customer liability (credit Customer
    Advances & Bookings). A payment received on or after the delivery date is
    recognised as revenue immediately.
    """
    booking = payment.booking
    delivered = bool(
        booking.delivery_date and payment.payment_date >= booking.delivery_date
    )
    credit_head = revenue_head() if delivered else customer_advance_head()
    return post_source_voucher(
        reference_type='Payment', reference_id=payment.pk,
        voucher_type=voucher_type_for(payment.payment_method, 'receipt'),
        date=payment.payment_date,
        narration=f'Payment {payment.payment_id} - {payment.get_payment_method_display()}',
        lines=[
            (cash_bank_head(payment.payment_method, payment.received_into),
             payment.amount, Decimal('0.00')),
            (credit_head, Decimal('0.00'), payment.amount),
        ],
        user=payment.created_by,
    )


def post_payment_reversal(payment):
    """Post the exact inverse of a posted payment receipt voucher.

    The reversal is idempotent on ``('PaymentReversal', payment id)``. It uses
    the original voucher lines, so a pre-delivery receipt reverses Customer
    Advances and a post-delivery receipt reverses Revenue.
    """
    original = Voucher.objects.filter(
        reference_type='Payment', reference_id=payment.pk, status='posted',
    ).prefetch_related('lines__account_head').first()
    if original is None:
        return None
    inverse_types = {'CR': 'CP', 'BR': 'BP', 'CP': 'CR', 'BP': 'BR'}
    lines = [
        (line.account_head, line.credit, line.debit)
        for line in original.lines.select_related('account_head').order_by('id')
    ]
    return post_source_voucher(
        reference_type='PaymentReversal', reference_id=payment.pk,
        voucher_type=inverse_types.get(original.voucher_type, 'JV'),
        date=timezone.localdate(),
        narration=(
            f'Reversal of Payment {payment.payment_id} - '
            f'{payment.get_status_display()}'
        ),
        lines=lines,
        user=payment.verified_by or payment.created_by,
    )


def post_refund(refund):
    """Post money paid back to a customer.

    A refund paid before delivery reduces the customer liability. A refund paid
    on or after delivery reduces revenue.
    """
    from datetime import date
    post_date = refund.refund_date or (
        refund.processed_date.date() if refund.processed_date else date.today())
    delivery_date = refund.booking.delivery_date
    after_delivery = bool(delivery_date and post_date >= delivery_date)
    debit_head = revenue_head() if after_delivery else customer_advance_head()
    return post_source_voucher(
        reference_type='Refund', reference_id=refund.pk,
        voucher_type=voucher_type_for(refund.refund_method, 'payment'),
        date=post_date,
        narration=f'Refund of Rs. {refund.amount} for booking '
                  f'{refund.booking.booking_id} - {refund.get_reason_display()}',
        lines=[
            (debit_head, refund.amount, Decimal('0.00')),
            (cash_bank_head(refund.refund_method, refund.paid_from),
             Decimal('0.00'), refund.amount),
        ],
        user=refund.processed_by,
    )


def booking_net_advances(booking, as_of=None):
    """Posted customer money held for a booking, net of posted refunds.

    Uses only Payment and Refund records that actually have a posted voucher.
    Refunds are limited to vouchers dated on or before ``as_of`` when supplied,
    which is the delivery date for the delivery posting.
    """
    from payments.models import Payment, Refund

    payment_ids = Voucher.objects.filter(
        reference_type='Payment', status='posted',
    ).values_list('reference_id', flat=True)
    refunds = Voucher.objects.filter(
        reference_type='Refund', status='posted',
    )
    if as_of is not None:
        refunds = refunds.filter(date__lte=as_of)
    refund_ids = refunds.values_list('reference_id', flat=True)

    paid = Payment.objects.filter(
        booking=booking, pk__in=payment_ids,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    refunded = Refund.objects.filter(
        booking=booking, pk__in=refund_ids,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    return paid - refunded


def post_booking_delivery(booking, user=None):
    """Move a delivered booking's net advances from liability to revenue.

    Idempotent through the standard ``(reference_type, reference_id)`` guard.
    """
    amount = booking_net_advances(booking, as_of=booking.delivery_date)
    if amount <= 0:
        return None
    return post_source_voucher(
        reference_type='BookingDelivery', reference_id=booking.pk,
        voucher_type='JV', date=booking.delivery_date,
        narration=f'Delivery of booking {booking.booking_id}: customer advances recognised as revenue',
        lines=[
            (customer_advance_head(), amount, Decimal('0.00')),
            (revenue_head(), Decimal('0.00'), amount),
        ],
        user=user,
    )


def post_expense(expense):
    expense_head = expense.expense_account or project_cost_head()
    credit_head = expense.paid_from or (
        cash_bank_head(expense.payment_method) if expense.status == 'paid' else payable_head()
    )
    return post_source_voucher(
        reference_type='Expense', reference_id=expense.pk,
        voucher_type=voucher_type_for(expense.payment_method, 'payment'),
        date=expense.expense_date,
        narration=f"{expense.project.name} - {expense.get_expense_type_display()}: "
                  f"{expense.description or expense.paid_to}",
        lines=[
            (expense_head, expense.amount, Decimal('0.00')),
            (credit_head, Decimal('0.00'), expense.amount),
        ],
        user=expense.created_by,
    )


def post_project_cost(cost):
    if cost.status != 'paid':
        return None
    return post_source_voucher(
        reference_type='ProjectCost', reference_id=cost.pk,
        voucher_type=voucher_type_for(cost.payment_method, 'payment'),
        date=cost.cost_date,
        narration=f'{cost.project.name} - {cost.get_cost_category_display()}',
        lines=[
            (cost.expense_account or project_cost_head(), cost.amount, Decimal('0.00')),
            (cash_bank_head(cost.payment_method, cost.paid_from),
             Decimal('0.00'), cost.amount),
        ],
        user=cost.created_by,
    )


def post_office_expense(expense):
    return post_source_voucher(
        reference_type='OfficeExpense', reference_id=expense.pk,
        voucher_type=voucher_type_for(expense.payment_method, 'payment'),
        date=expense.expense_date,
        narration=f'Office expense - {expense.office.name}'
                  f"{f' - {expense.category.name}' if expense.category else ''}",
        lines=[
            (expense.expense_account or office_expense_head(), expense.amount, Decimal('0.00')),
            (cash_bank_head(expense.payment_method, expense.paid_from),
             Decimal('0.00'), expense.amount),
        ],
        user=expense.created_by,
    )


def post_salary_payment(payment):
    employee = payment.slip.employee
    return post_source_voucher(
        reference_type='SalaryPayment', reference_id=payment.pk,
        voucher_type=voucher_type_for(payment.method, 'payment'),
        date=payment.payment_date,
        narration=f'Salary payment for {employee.full_name} '
                  f'({payment.slip.run.period_label})',
        lines=[
            (salaries_head(), payment.amount, Decimal('0.00')),
            (cash_bank_head(payment.method), Decimal('0.00'), payment.amount),
        ],
        user=payment.created_by,
    )


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