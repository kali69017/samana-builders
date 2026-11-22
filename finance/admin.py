from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import (
    AccountHead, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment, Voucher, VoucherLine,
    VoucherDeletionLog,
)


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


@admin.register(AccountHead)
class AccountHeadAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'parent', 'nature', 'account_kind', 'system_role', 'is_active']
    list_filter = ['nature', 'account_kind', 'is_active']
    search_fields = ['code', 'name']
    readonly_fields = ['code', 'nature']


class VoucherLineInline(admin.TabularInline):
    model = VoucherLine
    extra = 0
    can_delete = False
    readonly_fields = ['account_head', 'debit', 'credit', 'narration']


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ['voucher_number', 'voucher_type', 'date', 'status', 'cash_bank_account']
    list_filter = ['voucher_type', 'status']
    search_fields = ['voucher_number', 'narration']
    readonly_fields = ['voucher_number', 'status', 'is_locked', 'locked_by', 'locked_at',
                       'unlocked_by', 'unlocked_at', 'unlock_reason', 'reference_type',
                       'reference_id', 'created_at', 'updated_at']
    inlines = [VoucherLineInline]

    def has_delete_permission(self, request, obj=None):
        if not request.user.is_superuser:
            return False
        if obj is not None and not obj.is_manual:
            return False
        return True

    def delete_model(self, request, obj):
        if not obj.is_manual:
            raise PermissionDenied('Only manual vouchers can be deleted.')
        obj.delete_manual_voucher(request.user, 'Deleted from Django admin')

    def delete_queryset(self, request, queryset):
        if queryset.exclude(reference_type='', reference_id__isnull=True).exists():
            raise PermissionDenied('Only manual vouchers can be deleted.')
        for voucher in queryset:
            voucher.delete_manual_voucher(request.user, 'Deleted from Django admin')


@admin.register(VoucherDeletionLog)
class VoucherDeletionLogAdmin(admin.ModelAdmin):
    list_display = ['voucher_number', 'voucher_type', 'date', 'total',
                    'deleted_by', 'deleted_at', 'reason']
    list_filter = ['voucher_type', 'deleted_at']
    search_fields = ['voucher_number', 'reason']
    readonly_fields = [field.name for field in VoucherDeletionLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
