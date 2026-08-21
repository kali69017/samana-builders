from django.contrib import admin
from .models import (
    AccountTransaction, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment,
)


@admin.register(AccountTransaction)
class AccountTransactionAdmin(admin.ModelAdmin):
    list_display = ['date', 'transaction_type', 'direction', 'amount', 'category', 'employee', 'reference_type']
    list_filter = ['transaction_type', 'direction', 'date']
    search_fields = ['description', 'category', 'reference_type', 'employee__first_name', 'employee__last_name']
    readonly_fields = ['created_at']


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ['name', 'office_type', 'is_active']
    list_filter = ['office_type', 'is_active']
    search_fields = ['name']


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category_type', 'is_active']
    list_filter = ['category_type', 'is_active']
    search_fields = ['name']


@admin.register(OfficeExpense)
class OfficeExpenseAdmin(admin.ModelAdmin):
    list_display = ['office', 'category', 'amount', 'expense_date', 'status']
    list_filter = ['status', 'office', 'category']
    search_fields = ['description', 'paid_to']


@admin.register(ProjectBudget)
class ProjectBudgetAdmin(admin.ModelAdmin):
    list_display = ['project', 'total_budget', 'material_budget', 'labor_budget', 'contractor_budget']
    search_fields = ['project__name']


@admin.register(ProjectCost)
class ProjectCostAdmin(admin.ModelAdmin):
    list_display = ['project', 'cost_category', 'amount', 'cost_date', 'status']
    list_filter = ['cost_category', 'status']
    search_fields = ['project__name', 'vendor', 'description']


@admin.register(ProjectInvestment)
class ProjectInvestmentAdmin(admin.ModelAdmin):
    list_display = ['project', 'total_investment', 'updated_at']
    search_fields = ['project__name']
