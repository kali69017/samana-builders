from decimal import Decimal

from rest_framework import serializers
from .models import (
    AccountTransaction, AccountHead, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment, Voucher, VoucherAuditLog,
    VoucherLine,
)


class AccountTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)
    employee_name = serializers.CharField(source='employee.full_name', read_only=True, allow_null=True)

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0')
        return value

    def validate_direction(self, value):
        if value not in ('in', 'out'):
            raise serializers.ValidationError("Direction must be 'in' or 'out'.")
        return value

    class Meta:
        model = AccountTransaction
        fields = ['id', 'date', 'amount', 'direction', 'direction_display',
                  'transaction_type', 'transaction_type_display', 'category',
                  'reference_type', 'reference_id', 'employee', 'employee_name',
                  'description', 'created_at']
        read_only_fields = ['id', 'created_at']


class OfficeSerializer(serializers.ModelSerializer):
    office_type_display = serializers.CharField(source='get_office_type_display', read_only=True)

    class Meta:
        model = Office
        fields = ['id', 'name', 'office_type', 'office_type_display', 'address', 'is_active']
        read_only_fields = ['id']


class ExpenseCategorySerializer(serializers.ModelSerializer):
    category_type_display = serializers.CharField(source='get_category_type_display', read_only=True)

    class Meta:
        model = ExpenseCategory
        fields = ['id', 'name', 'category_type', 'category_type_display', 'is_active']
        read_only_fields = ['id']

    def validate_name(self, value):
        name = (value or '').strip()
        duplicate = ExpenseCategory.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError('A category with this name already exists.')
        return name


class OfficeExpenseSerializer(serializers.ModelSerializer):
    office_name = serializers.CharField(source='office.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = OfficeExpense
        fields = ['id', 'office', 'office_name', 'category', 'category_name',
                  'expense_account', 'paid_from', 'amount', 'expense_date', 'paid_to',
                  'payment_method', 'status', 'status_display', 'description', 'created_at']
        read_only_fields = ['id', 'created_at', 'status']

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0')
        return value

    def validate(self, attrs):
        from finance.accounting import validate_cash_bank_account, validate_expense_account
        if self.instance is None:
            try:
                validate_expense_account(attrs.get('expense_account'))
                validate_cash_bank_account(
                    attrs.get('paid_from'), attrs.get('payment_method') or 'cash')
            except Exception as exc:
                raise serializers.ValidationError(str(exc))
        return attrs


class ProjectCostSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    cost_category_display = serializers.CharField(source='get_cost_category_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectCost
        fields = ['id', 'project', 'project_name', 'cost_category', 'cost_category_display',
                  'expense_account', 'paid_from', 'amount', 'cost_date', 'vendor',
                  'invoice_ref', 'payment_method', 'payment_method_display', 'status',
                  'status_display', 'description', 'created_at']
        read_only_fields = ['id', 'created_at', 'status']

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0')
        return value

    def validate(self, attrs):
        from finance.accounting import validate_cash_bank_account, validate_expense_account
        if self.instance is None:
            try:
                validate_expense_account(attrs.get('expense_account'))
                validate_cash_bank_account(
                    attrs.get('paid_from'), attrs.get('payment_method') or 'cash')
            except Exception as exc:
                raise serializers.ValidationError(str(exc))
        return attrs


class ProjectBudgetSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    total_actual = serializers.ReadOnlyField()
    remaining_budget = serializers.ReadOnlyField()

    class Meta:
        model = ProjectBudget
        fields = ['id', 'project', 'project_name', 'total_budget', 'material_budget',
                  'labor_budget', 'contractor_budget', 'transportation_budget', 'other_budget',
                  'total_actual', 'remaining_budget', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class ProjectInvestmentSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = ProjectInvestment
        fields = ['id', 'project', 'project_name', 'total_investment', 'notes', 'updated_at']
        read_only_fields = ['id', 'updated_at']


# ─── DOUBLE-ENTRY ACCOUNTING ─────────────────────────────────────────────────
class AccountHeadSerializer(serializers.ModelSerializer):
    level = serializers.IntegerField(read_only=True)
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True, allow_null=True)

    class Meta:
        model = AccountHead
        fields = ['id', 'code', 'name', 'parent', 'parent_name', 'nature',
                  'account_kind', 'system_role', 'is_leaf', 'is_active', 'level',
                  'balance', 'created_at']
        read_only_fields = ['id', 'code', 'nature', 'system_role', 'is_leaf', 'level',
                            'balance', 'created_at']

    def validate(self, attrs):
        if self.instance and self.instance.parent_id is None:
            raise serializers.ValidationError(
                'Level 1 root accounts cannot be edited or deactivated.')
        parent = attrs.get('parent', getattr(self.instance, 'parent', None))
        if parent is None:
            raise serializers.ValidationError({'parent': 'Select a parent account.'})
        if self.instance and parent.pk == self.instance.pk:
            raise serializers.ValidationError(
                {'parent': 'An account cannot be its own parent.'})
        if parent.level >= 4:
            raise serializers.ValidationError(
                {'parent': 'Parent is already at level 4; max depth is 4.'})
        node = parent
        while node is not None:
            if self.instance and node.pk == self.instance.pk:
                raise serializers.ValidationError(
                    {'parent': 'Parent cannot be a descendant of this account.'})
            node = node.parent
        kind = attrs.get('account_kind', getattr(self.instance, 'account_kind', 'normal'))
        if kind != 'normal' and parent.root.code != '1':
            raise serializers.ValidationError(
                {'account_kind': 'Cash and bank flags are only allowed under Assets.'})
        return attrs


class VoucherLineSerializer(serializers.ModelSerializer):
    account_head_name = serializers.CharField(source='account_head.name', read_only=True)
    account_head_code = serializers.CharField(source='account_head.code', read_only=True)
    amount = serializers.DecimalField(
        max_digits=15, decimal_places=2, write_only=True, required=False,
    )

    class Meta:
        model = VoucherLine
        fields = ['id', 'account_head', 'account_head_code', 'account_head_name',
                  'amount', 'debit', 'credit', 'narration']
        read_only_fields = ['id']

    def validate_account_head(self, head):
        if not head.is_leaf:
            raise serializers.ValidationError('Postings are only allowed on leaf accounts.')
        if head.parent_id is None:
            raise serializers.ValidationError('Postings are not allowed on a level 1 root.')
        return head

    def validate(self, attrs):
        if attrs.get('amount') is not None:
            if attrs['amount'] <= 0:
                raise serializers.ValidationError('Amount must be greater than zero.')
            return attrs
        debit = attrs.get('debit', getattr(self.instance, 'debit', Decimal('0.00')))
        credit = attrs.get('credit', getattr(self.instance, 'credit', Decimal('0.00')))
        if debit and credit:
            raise serializers.ValidationError('A line cannot have both a debit and a credit.')
        if not debit and not credit:
            raise serializers.ValidationError('A line must have a debit or a credit.')
        if debit < 0 or credit < 0:
            raise serializers.ValidationError('Amounts cannot be negative.')
        return attrs


class VoucherAuditLogSerializer(serializers.ModelSerializer):
    event_display = serializers.CharField(source='get_event_display', read_only=True)
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = VoucherAuditLog
        fields = ['id', 'event', 'event_display', 'actor', 'actor_name', 'reason', 'created_at']

    def get_actor_name(self, obj):
        if not obj.actor:
            return None
        return obj.actor.get_full_name() or obj.actor.username


CASH_BANK_KIND = {'CR': 'cash', 'CP': 'cash', 'BR': 'bank', 'BP': 'bank'}


def _line_amount(line):
    if line.get('amount') is not None:
        return line['amount']
    return (line.get('debit') or Decimal('0.00')) + (line.get('credit') or Decimal('0.00'))


class VoucherSerializer(serializers.ModelSerializer):
    lines = VoucherLineSerializer(many=True)
    voucher_type_display = serializers.CharField(source='get_voucher_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_editable = serializers.BooleanField(read_only=True)
    is_auto_generated = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = ['id', 'voucher_number', 'voucher_type', 'voucher_type_display',
                  'date', 'narration', 'cash_bank_account', 'status', 'status_display',
                  'is_locked', 'is_editable', 'is_auto_generated', 'locked_by', 'locked_at',
                  'unlocked_by', 'unlocked_at', 'unlock_reason', 'reference_type',
                  'reference_id', 'lines', 'created_at']
        read_only_fields = ['id', 'voucher_number', 'status', 'is_locked', 'locked_by',
                            'locked_at', 'unlocked_by', 'unlocked_at', 'unlock_reason',
                            'reference_type', 'reference_id', 'created_at']

    def get_is_auto_generated(self, obj):
        return obj.reference_id is not None

    def validate(self, attrs):
        voucher_type = attrs.get('voucher_type', getattr(self.instance, 'voucher_type', None))
        cash_account = attrs.get(
            'cash_bank_account', getattr(self.instance, 'cash_bank_account', None))
        lines = attrs.get('lines', None)
        if lines is None and self.instance is not None:
            lines = [
                {'account_head': line.account_head, 'debit': line.debit,
                 'credit': line.credit, 'narration': line.narration}
                for line in self.instance.lines.select_related('account_head')
            ]
        if not lines:
            raise serializers.ValidationError({'lines': 'Enter at least one voucher line.'})

        lines_provided = 'lines' in attrs
        legacy_header_edit = (
            self.instance is not None
            and cash_account is None
            and 'cash_bank_account' not in attrs
            and not lines_provided
        )
        if voucher_type in CASH_BANK_KIND and not legacy_header_edit:
            expected = CASH_BANK_KIND[voucher_type]
            if cash_account is None:
                raise serializers.ValidationError(
                    {'cash_bank_account': 'Select the cash or bank account.'})
            if cash_account.parent_id is None:
                raise serializers.ValidationError(
                    {'cash_bank_account': 'Postings are not allowed on a level 1 root.'})
            if cash_account.account_kind != expected:
                raise serializers.ValidationError(
                    {'cash_bank_account': f'Select an account flagged as {expected}.'})
            for line in lines:
                account = line.get('account_head')
                if account is not None and account.pk == cash_account.pk:
                    raise serializers.ValidationError(
                        {'lines': 'A contra account cannot be the cash or bank account.'})
                if _line_amount(line) <= 0:
                    raise serializers.ValidationError(
                        {'lines': 'Contra amounts must be greater than zero.'})
            if self.instance is not None and len(lines) != self.instance.lines.count():
                raise serializers.ValidationError(
                    {'lines': 'Cash and bank voucher line count cannot change.'})
        else:
            debit = sum((line.get('debit') or Decimal('0.00') for line in lines), Decimal('0.00'))
            credit = sum((line.get('credit') or Decimal('0.00') for line in lines), Decimal('0.00'))
            if debit <= 0 or debit != credit:
                raise serializers.ValidationError(
                    {'lines': f'Journal is not balanced: debit {debit} does not equal credit {credit}.'})
        return attrs

    def _cash_bank_lines(self, voucher_type, cash_account, lines):
        entries = [(line['account_head'], _line_amount(line), line.get('narration', ''))
                   for line in lines]
        total = sum((amount for _head, amount, _note in entries), Decimal('0.00'))
        if voucher_type in ('CR', 'BR'):
            out = [(cash_account, total, Decimal('0.00'), '')]
            out.extend((head, Decimal('0.00'), amount, note)
                       for head, amount, note in entries)
            return out
        out = [(head, amount, Decimal('0.00'), note)
               for head, amount, note in entries]
        out.append((cash_account, Decimal('0.00'), total, ''))
        return out

    def create(self, validated_data):
        lines = validated_data.pop('lines', [])
        request = self.context.get('request')
        voucher = Voucher.objects.create(
            created_by=request.user if request else None, **validated_data,
        )
        if voucher.voucher_type in CASH_BANK_KIND:
            for head, debit, credit, narration in self._cash_bank_lines(
                voucher.voucher_type, voucher.cash_bank_account, lines,
            ):
                VoucherLine.objects.create(
                    voucher=voucher, account_head=head, debit=debit, credit=credit,
                    narration=narration,
                )
        else:
            for line in lines:
                line.pop('amount', None)
                VoucherLine.objects.create(voucher=voucher, **line)
        return voucher

    def update(self, instance, validated_data):
        lines = validated_data.pop('lines', None)
        if instance.reference_id is not None:
            raise serializers.ValidationError(
                'Auto-generated vouchers are read-only except for unlock.')
        if not instance.is_editable:
            raise serializers.ValidationError(
                'This voucher is posted and locked; unlock it before editing.')
        if instance.voucher_type in CASH_BANK_KIND:
            if lines is not None:
                raise serializers.ValidationError(
                    {'lines': 'Cash and bank voucher lines cannot be edited.'})
            new_account = validated_data.get('cash_bank_account', instance.cash_bank_account)
            if new_account != instance.cash_bank_account:
                raise serializers.ValidationError(
                    {'cash_bank_account': 'The cash or bank account cannot be changed after creation.'})
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines is not None:
            existing = list(instance.lines.order_by('id'))
            if len(existing) != len(lines):
                raise serializers.ValidationError(
                    {'lines': 'Line count cannot change. Create a new voucher instead.'})
            for line_obj, line in zip(existing, lines):
                line_obj.account_head = line['account_head']
                line_obj.debit = line.get('debit', Decimal('0.00'))
                line_obj.credit = line.get('credit', Decimal('0.00'))
                line_obj.narration = line.get('narration', '')
                line_obj.save()
        return instance
