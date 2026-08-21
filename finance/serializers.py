from rest_framework import serializers
from .models import (
    AccountTransaction, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment,
)


class AccountTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)
    employee_name = serializers.CharField(source='employee.full_name', read_only=True, allow_null=True)

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
        read_only_fields = ['id', 'created_at']

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than 0')
        return value


class ProjectCostSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    cost_category_display = serializers.CharField(source='get_cost_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectCost
        fields = ['id', 'project', 'project_name', 'cost_category', 'cost_category_display',
                  'amount', 'cost_date', 'vendor', 'invoice_ref', 'status', 'status_display',
                  'description', 'created_at']
        read_only_fields = ['id', 'created_at']

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
