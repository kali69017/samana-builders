from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def money(value, decimals=0):
    """Format a numeric/money value with thousands separators.

    e.g. money(2776000, 0) -> '2,776,000'
         money(2776000, 2) -> '2,776,000.00'
    Non-numeric / None input is returned unchanged.
    """
    if value is None or value == '':
        return ''
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    try:
        nd = int(decimals)
    except (TypeError, ValueError):
        nd = 0
    if nd <= 0:
        return f'{num:,.0f}'
    return f'{num:,.{nd}f}'
