from django.contrib import admin
from .models import (
    Department, Designation, SalaryComponent, Employee, EmployeeDocument,
    EmployeeSalary, PayrollRun, SalarySlip, SalarySlipItem, SalaryPayment,
    Attendance, Leave,
)


class EmployeeSalaryInline(admin.TabularInline):
    model = EmployeeSalary
    extra = 0


class EmployeeDocumentInline(admin.TabularInline):
    model = EmployeeDocument
    extra = 0


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']
    search_fields = ['name']
    list_filter = ['is_active']


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ['title', 'is_active']
    search_fields = ['title']
    list_filter = ['is_active']


@admin.register(SalaryComponent)
class SalaryComponentAdmin(admin.ModelAdmin):
    list_display = ['name', 'component_type', 'is_active']
    list_filter = ['component_type', 'is_active']
    search_fields = ['name']


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'full_name', 'department', 'designation', 'status', 'joining_date']
    list_filter = ['status', 'department', 'designation']
    search_fields = ['employee_id', 'first_name', 'last_name', 'cnic', 'phone', 'email']
    readonly_fields = ['employee_id', 'created_at', 'updated_at']
    inlines = [EmployeeSalaryInline, EmployeeDocumentInline]
    fieldsets = (
        ('Personal', {'fields': ('employee_id', 'first_name', 'last_name', 'cnic', 'phone', 'email', 'address')}),
        ('Employment', {'fields': ('department', 'designation', 'joining_date', 'status', 'user')}),
        ('Notes', {'fields': ('notes',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'employee', 'uploaded_at']
    search_fields = ['title', 'employee__first_name', 'employee__last_name']
    readonly_fields = ['uploaded_at']


@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = ['employee', 'component', 'amount', 'effective_from']
    list_filter = ['component']
    search_fields = ['employee__first_name', 'employee__last_name', 'component__name']


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ['period_label', 'status', 'slip_count', 'total_net', 'created_at']
    list_filter = ['status', 'year', 'month']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SalarySlip)
class SalarySlipAdmin(admin.ModelAdmin):
    list_display = ['employee', 'run', 'gross', 'total_deductions', 'net', 'status']
    list_filter = ['status', 'run']
    search_fields = ['employee__first_name', 'employee__last_name']
    readonly_fields = ['gross', 'total_earnings', 'total_deductions', 'net', 'created_at', 'updated_at']


@admin.register(SalarySlipItem)
class SalarySlipItemAdmin(admin.ModelAdmin):
    list_display = ['slip', 'component', 'amount']
    search_fields = ['slip__employee__first_name', 'component__name']


@admin.register(SalaryPayment)
class SalaryPaymentAdmin(admin.ModelAdmin):
    list_display = ['slip', 'amount', 'payment_date', 'method', 'reference_number']
    list_filter = ['method', 'payment_date']
    readonly_fields = ['created_at']


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'status']
    list_filter = ['status', 'date']
    search_fields = ['employee__first_name', 'employee__last_name']


@admin.register(Leave)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ['employee', 'leave_type', 'start_date', 'end_date', 'days', 'status']
    list_filter = ['status', 'leave_type']
    search_fields = ['employee__first_name', 'employee__last_name']
    readonly_fields = ['applied_on']
