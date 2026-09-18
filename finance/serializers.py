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


class OfficeExpenseSerializer(serializers.ModelSerializer):
    office_name = serializers.CharField(source='office.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = OfficeExpense
        fields = ['id', 'office', 'office_name', 'category', 'category_name', 'amount',
                  'expense_date', 'paid_to', 'payment_method', 'status', 'status_display',
                  'description', 'created_at']
        read_only_fields = ['id', 'created_at', 'status']

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0')
        return value


class ProjectCostSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    cost_category_display = serializers.CharField(source='get_cost_category_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectCost
        fields = ['id', 'project', 'project_name', 'cost_category', 'cost_category_display',
                  'amount', 'cost_date', 'vendor', 'invoice_ref', 'payment_method',
                  'payment_method_display', 'status', 'status_display',
                  'description', 'created_at']
        read_only_fields = ['id', 'created_at', 'status']

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0')
        return value


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
                  'is_leaf', 'is_active', 'level', 'balance', 'created_at']
        read_only_fields = ['id', 'is_leaf', 'level', 'balance', 'created_at']

    def validate(self, attrs):
        parent = attrs.get('parent', getattr(self.instance, 'parent', None))
        if parent is not None:
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
        return attrs


class VoucherLineSerializer(serializers.ModelSerializer):
    account_head_name = serializers.CharField(source='account_head.name', read_only=True)
    account_head_code = serializers.CharField(source='account_head.code', read_only=True)

    class Meta:
        model = VoucherLine
        fields = ['id', 'account_head', 'account_head_code', 'account_head_name',
                  'debit', 'credit', 'narration']
        read_only_fields = ['id']

    def validate_account_head(self, head):
        if not head.is_leaf:
            raise serializers.ValidationError('Postings are only allowed on leaf accounts.')
        return head

    def validate(self, attrs):
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


class VoucherSerializer(serializers.ModelSerializer):
    lines = VoucherLineSerializer(many=True)
    voucher_type_display = serializers.CharField(source='get_voucher_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_editable = serializers.BooleanField(read_only=True)
    is_auto_generated = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = ['id', 'voucher_number', 'voucher_type', 'voucher_type_display',
                  'date', 'narration', 'status', 'status_display', 'is_locked',
                  'is_editable', 'is_auto_generated', 'locked_by', 'locked_at',
                  'unlocked_by', 'unlocked_at', 'unlock_reason', 'reference_type',
                  'reference_id', 'lines', 'created_at']
        read_only_fields = ['id', 'voucher_number', 'status', 'is_locked', 'locked_by',
                            'locked_at', 'unlocked_by', 'unlocked_at', 'unlock_reason',
                            'reference_type', 'reference_id', 'created_at']

    def get_is_auto_generated(self, obj):
        return obj.reference_id is not None

    def create(self, validated_data):
        lines = validated_data.pop('lines', [])
        request = self.context.get('request')
        voucher = Voucher.objects.create(
            created_by=request.user if request else None, **validated_data,
        )
        for line in lines:
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
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            for line in lines:
                VoucherLine.objects.create(voucher=instance, **line)
        return instance
