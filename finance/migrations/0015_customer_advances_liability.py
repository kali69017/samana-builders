"""Move the customer advances control head to Liabilities.

Client decision: money received from a customer before delivery is a customer
liability, not fixed assets and not revenue. The old Fixed Assets head
"Advances & Bookings" is removed only when it has never been posted to, and the
customer_advances role is renamed to the new control-head name under Current
Liabilities.
"""
from django.db import migrations


def _next_child_code(AccountHead, parent):
    prefix = f'{parent.code}.'
    numbers = []
    for code in AccountHead.objects.filter(parent=parent).values_list('code', flat=True):
        if code.startswith(prefix) and code[len(prefix):].isdigit():
            numbers.append(int(code[len(prefix):]))
    return f'{prefix}{max(numbers, default=0) + 1}'


def move_customer_advances(apps, schema_editor):
    AccountHead = apps.get_model('finance', 'AccountHead')
    VoucherLine = apps.get_model('finance', 'VoucherLine')

    fixed_assets = AccountHead.objects.filter(code='1.2').first()
    if fixed_assets is not None:
        stale = AccountHead.objects.filter(
            parent=fixed_assets, name__iexact='Advances & Bookings',
        ).first()
        if stale is not None:
            if VoucherLine.objects.filter(account_head=stale).exists():
                raise RuntimeError(
                    'Fixed Assets head 1.2.5 Advances & Bookings has ledger lines. '
                    'Stop and resolve it manually before migrating.'
                )
            if AccountHead.objects.filter(parent=stale).exists():
                raise RuntimeError(
                    'Fixed Assets head 1.2.5 Advances & Bookings has child accounts. '
                    'Stop and resolve it manually before migrating.'
                )
            print(f'Deleting unposted Fixed Assets head {stale.code} {stale.name}')
            stale.delete()

    current_liabilities = AccountHead.objects.filter(code='2.1').first()
    if current_liabilities is None:
        raise RuntimeError('Current Liabilities head 2.1 is missing.')

    advances = AccountHead.objects.filter(system_role='customer_advances').first()
    if advances is None:
        advances = AccountHead.objects.filter(
            parent=current_liabilities, name__iexact='Customer Advances & Bookings',
        ).first()
    if advances is None:
        advances = AccountHead.objects.filter(
            parent=current_liabilities, name__iexact='Customer Advances',
        ).first()

    if advances is None:
        code = _next_child_code(AccountHead, current_liabilities)
        advances = AccountHead.objects.create(
            code=code,
            name='Customer Advances & Bookings',
            parent=current_liabilities,
            nature='credit',
            account_kind='normal',
            system_role='customer_advances',
            is_active=True,
            is_leaf=True,
        )
        print(f'Created {advances.code} Customer Advances & Bookings')
    else:
        root = advances
        while root.parent_id:
            root = AccountHead.objects.get(pk=root.parent_id)
        if root.code != '2':
            if VoucherLine.objects.filter(account_head=advances).exists():
                raise RuntimeError(
                    'The customer_advances account is outside Liabilities and has '
                    'ledger lines. Stop and resolve it manually before migrating.'
                )
            advances.parent = current_liabilities
            advances.nature = 'credit'
        advances.name = 'Customer Advances & Bookings'
        advances.system_role = 'customer_advances'
        advances.is_active = True
        advances.save(update_fields=['name', 'parent', 'nature', 'system_role', 'is_active'])
        print(f'Updated {advances.code} Customer Advances & Bookings')

    for head in AccountHead.objects.all():
        AccountHead.objects.filter(pk=head.pk).update(
            is_leaf=not AccountHead.objects.filter(parent=head).exists()
        )


def reverse_move(apps, schema_editor):
    # The rename is intentionally not reversed; ledger links make a reverse risky.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0014_expense_category_actions'),
    ]

    operations = [
        migrations.RunPython(move_customer_advances, reverse_move),
    ]
