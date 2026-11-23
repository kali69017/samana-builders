from django.contrib import admin
from core.permissions import PAYMENT_VERIFIER_ROLES
from .models import Payment, Receipt, Refund, PaymentAllocation


class ReceiptInline(admin.TabularInline):
    model = Receipt
    extra = 0
    fields = ['receipt_number', 'receipt_date', 'generated_by', 'is_duplicate']
    readonly_fields = ['receipt_number', 'receipt_date', 'generated_by']
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    fields = ['installment', 'amount', 'allocated_at', 'allocated_by']
    readonly_fields = ['allocated_at', 'allocated_by']
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id', 'booking', 'customer_name', 'amount', 'payment_date',
                   'payment_method', 'status', 'created_by', 'verified_by']
    search_fields = ['payment_id', 'booking__booking_id', 'booking__customer__first_name',
                    'booking__customer__last_name', 'reference_number']
    list_filter = ['status', 'payment_method', 'payment_date']
    readonly_fields = ['payment_id', 'created_at', 'updated_at', 'verified_at']
    inlines = [ReceiptInline, PaymentAllocationInline]
    fieldsets = (
        ('Payment Info', {
            'fields': ('payment_id', 'booking', 'installment', 'amount', 'payment_date', 'payment_method')
        }),
        ('Reference', {
            'fields': ('reference_number', 'bank_name', 'cheque_number', 'cheque_date', 'clearance_date')
        }),
        ('Status', {
            'fields': ('status', 'bounce_reason', 'bounce_fee', 'unallocated_amount', 'notes')
        }),
        ('Verification', {
            'fields': ('verified_by', 'verified_at', 'receipt_generated')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def customer_name(self, obj):
        return obj.booking.customer.full_name if obj.booking else '-'
    customer_name.short_description = 'Customer'
    customer_name.admin_order_field = 'booking__customer__first_name'

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.pk and obj._posted_receipt_exists():
            readonly.extend([
                'amount', 'booking', 'received_into', 'payment_date', 'payment_method',
            ])
        return readonly

    def _is_payment_verifier(self, request):
        if request.user.is_superuser:
            return True
        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        return role in PAYMENT_VERIFIER_ROLES

    def has_module_permission(self, request):
        return self._is_payment_verifier(request)

    def has_view_permission(self, request, obj=None):
        return self._is_payment_verifier(request)

    def has_change_permission(self, request, obj=None):
        return self._is_payment_verifier(request)

    def has_delete_permission(self, request, obj=None):
        # Only superusers can delete payments
        return request.user.is_superuser


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_id', 'receipt_number', 'payment', 'receipt_date', 'generated_by', 'is_duplicate']
    search_fields = ['receipt_number', 'payment__payment_id']
    list_filter = ['receipt_date', 'is_duplicate']
    readonly_fields = ['receipt_id', 'receipt_number', 'generated_at', 'generated_by']
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ['booking', 'amount', 'reason', 'status', 'approved_by', 'created_at']
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['booking__booking_id']
    readonly_fields = ['created_at', 'processed_date']
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ['payment', 'installment', 'amount', 'allocated_at', 'allocated_by']
    list_filter = ['allocated_at']
    readonly_fields = ['allocated_at', 'allocated_by']
    
    def has_change_permission(self, request, obj=None):
        return False