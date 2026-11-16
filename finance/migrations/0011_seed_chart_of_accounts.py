from django.db import migrations

ROOTS = [
    ('1', 'Assets', 'debit'),
    ('2', 'Liabilities', 'credit'),
    ('3', 'Capital', 'credit'),
    ('4', 'Revenue', 'credit'),
    ('5', 'Expenses', 'debit'),
]

REFERENCE_TREE = [
    ('1.1', 'Current Assets', '1', 'debit', 'normal', None),
    ('1.1.1', 'Cash & Banks', '1.1', 'debit', 'normal', None),
    ('1.1.1.1', 'Cash', '1.1.1', 'debit', 'cash', 'cash_default'),
    ('1.1.1.2', 'Bank', '1.1.1', 'debit', 'bank', 'bank_default'),
    ('1.1.2', 'Receivables', '1.1', 'debit', 'normal', None),
    ('1.1.2.1', 'Accounts Receivable', '1.1.2', 'debit', 'normal', 'receivable'),
    ('1.1.4', 'Prepaid & Advances', '1.1', 'debit', 'normal', None),
    ('1.2', 'Fixed Assets', '1', 'debit', 'normal', None),
    ('1.2.1', 'Furniture, Fixture & Fittings', '1.2', 'debit', 'normal', None),
    ('1.2.2', 'Office Equipment', '1.2', 'debit', 'normal', None),
    ('1.2.3', 'Electrical Equipment', '1.2', 'debit', 'normal', None),
    ('1.2.4', 'Motor Vehicles', '1.2', 'debit', 'normal', None),
    ('1.2.5', 'Advances & Bookings', '1.2', 'debit', 'normal', None),
    ('2.1', 'Current Liabilities', '2', 'credit', 'normal', None),
    ('2.1.1', 'Customer Advances', '2.1', 'credit', 'normal', 'customer_advances'),
    ('2.1.2', 'Refunds Payable', '2.1', 'credit', 'normal', 'refunds'),
    ('2.1.3', 'Accounts Payable', '2.1', 'credit', 'normal', 'payable'),
    ('3.1', 'Owner Capital', '3', 'credit', 'normal', None),
    ('4.1', 'Sales Revenue', '4', 'credit', 'normal', None),
    ('4.1.1', 'Plot Sales Revenue', '4.1', 'credit', 'normal', 'revenue'),
    ('5.1', 'Operating Expenses', '5', 'debit', 'normal', None),
    ('5.1.1', 'Office Expenses', '5.1', 'debit', 'normal', 'office_expenses'),
    ('5.1.2', 'Project Costs', '5.1', 'debit', 'normal', 'project_costs'),
    ('5.1.3', 'Salaries', '5.1', 'debit', 'normal', 'salaries'),
    ('5.1.4', 'Depreciation', '5.1', 'debit', 'normal', None),
]

# old code -> (new code, new parent code, name, kind, system role)
OLD_TO_NEW = [
    ('100', '1.1', '1', 'Current Assets', 'normal', None),
    ('1000', '1.1.1.1', '1.1.1', 'Cash', 'cash', 'cash_default'),
    ('1010', '1.1.1.2', '1.1.1', 'Bank', 'bank', 'bank_default'),
    ('110', '1.1.2', '1.1', 'Receivables', 'normal', None),
    ('1100', '1.1.2.1', '1.1.2', 'Accounts Receivable', 'normal', 'receivable'),
    ('500', '5.1', '5', 'Operating Expenses', 'normal', None),
    ('5000', '5.1.1', '5.1', 'Office Expenses', 'normal', 'office_expenses'),
    ('5100', '5.1.2', '5.1', 'Project Costs', 'normal', 'project_costs'),
    ('5200', '5.1.3', '5.1', 'Salaries', 'normal', 'salaries'),
    ('5900', '5.1.4', '5.1', 'Depreciation', 'normal', None),
]


GROUP_CODES = {'1.1', '1.1.1', '1.1.2', '1.1.4', '1.2', '2.1', '4.1', '5.1'}


def _map_old(AccountHead, old_code, new_code, parent_code, name, kind, role):
    head = AccountHead.objects.filter(code=old_code).first()
    if head is None:
        return
    parent = AccountHead.objects.filter(code=parent_code).first()
    head.code = new_code
    head.name = name
    head.parent = parent
    head.account_kind = kind
    head.system_role = role
    head.is_active = True
    head.save(update_fields=['code', 'name', 'parent', 'account_kind',
                             'system_role', 'is_active'])
    print(f'Account mapping: {old_code} -> {new_code} {name}')


def _ensure_reference(AccountHead, group_only):
    for code, name, parent_code, nature, kind, role in REFERENCE_TREE:
        if (code in GROUP_CODES) != group_only:
            continue
        parent = AccountHead.objects.filter(code=parent_code).first()
        AccountHead.objects.update_or_create(
            code=code,
            defaults={'name': name, 'parent': parent, 'nature': nature,
                      'account_kind': kind, 'system_role': role, 'is_active': True},
        )


def _next_code(AccountHead, parent):
    prefix = f'{parent.code}.'
    numbers = []
    for code in AccountHead.objects.filter(parent=parent).values_list('code', flat=True):
        if code.startswith(prefix) and code[len(prefix):].isdigit():
            numbers.append(int(code[len(prefix):]))
    return f'{prefix}{max(numbers, default=0) + 1}'


def _classify_unknown(apps):
    AccountHead = apps.get_model('finance', 'AccountHead')
    known_prefixes = ('1.', '2.', '3.', '4.', '5.')
    fixed_codes = {code for code, _name, _nature in ROOTS}
    fixed_codes.update(entry[0] for entry in REFERENCE_TREE)
    fixed_codes.update(entry[1] for entry in OLD_TO_NEW)

    unknown = [
        head for head in AccountHead.objects.all()
        if head.code not in fixed_codes
        and not head.code.startswith(known_prefixes)
    ]
    if not unknown:
        return

    holding_code = '1.9'
    holding = AccountHead.objects.filter(code=holding_code).first()
    if holding is None:
        root = AccountHead.objects.get(code='1')
        holding = AccountHead.objects.create(
            code=holding_code, name='Holding - Unclassified', parent=root,
            nature='debit', account_kind='normal', is_active=True,
        )
        print(f'Created holding parent: {holding_code} {holding.name}')

    def depth(head):
        count = 1
        node = head
        while node.parent_id:
            node = AccountHead.objects.get(pk=node.parent_id)
            count += 1
        return count

    def level(node):
        return depth(node)

    children = {}
    for head in unknown:
        if head.parent_id:
            children.setdefault(head.parent_id, []).append(head)

    def height(head):
        kids = children.get(head.pk, [])
        return 1 if not kids else 1 + max(height(kid) for kid in kids)

    mapped_ids = {}
    for head in sorted(unknown, key=depth):
        old_code = head.code
        parent = None
        if head.parent_id:
            parent = mapped_ids.get(head.parent_id) or AccountHead.objects.filter(
                pk=head.parent_id).first()
        if parent is None:
            if old_code.startswith('A'):
                parent = AccountHead.objects.get(code='1.1')
            elif old_code.startswith('L'):
                parent = AccountHead.objects.get(code='2.1')
            elif old_code.startswith('C'):
                parent = AccountHead.objects.get(code='3')
            elif old_code.startswith('R'):
                parent = AccountHead.objects.get(code='4.1')
            elif old_code.startswith('E'):
                parent = AccountHead.objects.get(code='5.1')
            else:
                parent = holding
                print(f'Unclassified head sent to holding: {old_code} {head.name}')
        while parent.parent_id and level(parent) + height(head) > 4:
            parent = AccountHead.objects.get(pk=parent.parent_id)
        if level(parent) + height(head) > 4:
            parent = holding
            print(f'Head moved to holding for depth: {old_code} {head.name}')
        new_code = _next_code(AccountHead, parent)
        AccountHead.objects.filter(pk=head.pk).update(
            code=new_code, parent=parent, nature=parent.nature)
        head.code = new_code
        head.parent = parent
        head.nature = parent.nature
        mapped_ids[head.pk] = head
        print(f'Unknown account mapping: {old_code} -> {new_code} {head.name}')


def seed_chart(apps, schema_editor):
    AccountHead = apps.get_model('finance', 'AccountHead')

    for code, name, nature in ROOTS:
        AccountHead.objects.update_or_create(
            code=code,
            defaults={'name': name, 'parent': None, 'nature': nature,
                      'is_active': True, 'system_role': None},
        )

    # Move old parent-level groups first.
    for old_code, new_code, parent_code, name, kind, role in OLD_TO_NEW:
        if new_code in GROUP_CODES:
            _map_old(AccountHead, old_code, new_code, parent_code, name, kind, role)

    # Ensure every group parent exists on a fresh database.
    _ensure_reference(AccountHead, group_only=True)

    # Move old leaf accounts into their new parents and codes.
    for old_code, new_code, parent_code, name, kind, role in OLD_TO_NEW:
        if new_code not in GROUP_CODES:
            _map_old(AccountHead, old_code, new_code, parent_code, name, kind, role)

    # Ensure every reference leaf and system role exists on a fresh database.
    _ensure_reference(AccountHead, group_only=False)

    # Place legacy or unknown heads that are not part of the reference tree.
    _classify_unknown(apps)

    for head in AccountHead.objects.all():
        has_children = AccountHead.objects.filter(parent=head).exists()
        AccountHead.objects.filter(pk=head.pk).update(is_leaf=not has_children)


def reverse_seed_chart(apps, schema_editor):
    # Reverse is intentionally a no-op. Reverting codes would risk ledger links.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0010_accounthead_roles_and_kind'),
    ]

    operations = [
        migrations.RunPython(seed_chart, reverse_seed_chart),
    ]
