from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncWeek, TruncYear

from finance.accounting import customer_advance_head
from finance.models import VoucherLine
from payments.models import Payment


@dataclass(frozen=True)
class FinancialMetrics:
    start_date: date
    end_date: date
    collected: Decimal
    customer_advances_held: Decimal
    recognized_revenue: Decimal
    expenses: Decimal
    expense_groups: dict
    profit: Decimal


def _posted_lines(start_date, end_date):
    return VoucherLine.objects.filter(
        voucher__status='posted',
        voucher__date__gte=start_date,
        voucher__date__lte=end_date,
    )


def _expense_group(code, system_role):
    if system_role == 'office_expenses' or code.startswith('5.1.1'):
        return 'office'
    if system_role == 'project_costs' or code.startswith('5.1.2'):
        return 'project_cost'
    if system_role == 'salaries' or code.startswith('5.1.3'):
        return 'salaries'
    if code.startswith('5.1.4'):
        return 'depreciation'
    return 'operating'


def get_financial_metrics(start_date, end_date):
    collected = Payment.objects.filter(
        status='verified',
        payment_date__gte=start_date,
        payment_date__lte=end_date,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    advances = customer_advance_head()
    advances_lines = VoucherLine.objects.filter(
        voucher__status='posted',
        voucher__date__lte=end_date,
        account_head=advances,
    ).aggregate(debit=Sum('debit'), credit=Sum('credit'))
    customer_advances_held = (
        (advances_lines['credit'] or Decimal('0.00'))
        - (advances_lines['debit'] or Decimal('0.00'))
    )

    lines = _posted_lines(start_date, end_date)
    revenue_lines = lines.filter(account_head__code__startswith='4').aggregate(
        debit=Sum('debit'), credit=Sum('credit'))
    recognized_revenue = (
        (revenue_lines['credit'] or Decimal('0.00'))
        - (revenue_lines['debit'] or Decimal('0.00'))
    )

    expense_groups = {
        'operating': Decimal('0.00'),
        'office': Decimal('0.00'),
        'project_cost': Decimal('0.00'),
        'salaries': Decimal('0.00'),
        'depreciation': Decimal('0.00'),
    }
    expense_rows = lines.filter(
        account_head__code__startswith='5',
    ).values('account_head__code', 'account_head__system_role').annotate(
        debit=Sum('debit'), credit=Sum('credit'))
    for row in expense_rows:
        net = (row['debit'] or Decimal('0.00')) - (row['credit'] or Decimal('0.00'))
        group = _expense_group(
            row['account_head__code'], row['account_head__system_role'])
        expense_groups[group] += net
    expenses = sum(expense_groups.values(), Decimal('0.00'))
    profit = recognized_revenue - expenses

    return FinancialMetrics(
        start_date=start_date,
        end_date=end_date,
        collected=collected,
        customer_advances_held=customer_advances_held,
        recognized_revenue=recognized_revenue,
        expenses=expenses,
        expense_groups=expense_groups,
        profit=profit,
    )


def collected_by_project(start_date, end_date):
    rows = Payment.objects.filter(
        status='verified',
        payment_date__gte=start_date,
        payment_date__lte=end_date,
    ).values('booking__plot__project_id').annotate(total=Sum('amount'))
    return {
        row['booking__plot__project_id']: row['total'] or Decimal('0.00')
        for row in rows
    }


def collected_by_payment_type(start_date, end_date):
    rows = Payment.objects.filter(
        status='verified',
        payment_date__gte=start_date,
        payment_date__lte=end_date,
    ).values('payment_type').annotate(total=Sum('amount'))
    return {
        row['payment_type']: row['total'] or Decimal('0.00')
        for row in rows
    }


def collected_by_method(start_date, end_date):
    rows = Payment.objects.filter(
        status='verified',
        payment_date__gte=start_date,
        payment_date__lte=end_date,
    ).values('payment_method').annotate(total=Sum('amount'))
    return {
        row['payment_method']: row['total'] or Decimal('0.00')
        for row in rows
    }


def recognized_revenue_series(start_date, end_date, granularity='month'):
    trunc = {'week': TruncWeek, 'month': TruncMonth, 'year': TruncYear}.get(
        granularity, TruncMonth)
    rows = _posted_lines(start_date, end_date).filter(
        account_head__code__startswith='4',
    ).annotate(bucket=trunc('voucher__date')).values('bucket').annotate(
        debit=Sum('debit'), credit=Sum('credit')).order_by('bucket')
    return [
        (
            row['bucket'].date() if hasattr(row['bucket'], 'date') else row['bucket'],
            (row['credit'] or Decimal('0.00')) - (row['debit'] or Decimal('0.00')),
        )
        for row in rows
    ]
