from django.contrib import admin
from django.utils import timezone
from .models import Customer, CustomerLedgerEntry, ReceivableAging


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['customer_id', 'first_name', 'last_name', 'phone', 'cnic',
                    'is_active', 'do_not_contact', 'created_at']
    search_fields = ['customer_id', 'first_name', 'last_name', 'phone', 'cnic']
    list_filter = ['is_active', 'do_not_contact', 'city', 'created_at']
    readonly_fields = ['customer_id', 'created_at', 'updated_at',
                       'do_not_contact_set_by', 'do_not_contact_at']
    actions = ['stop_all_messages', 'allow_messages']

    @admin.action(description='Stop all messages')
    def stop_all_messages(self, request, queryset):
        updated = queryset.update(
            do_not_contact=True,
            do_not_contact_reason='Stopped from Django admin',
            do_not_contact_set_by=request.user,
            do_not_contact_at=timezone.now(),
        )
        self.message_user(request, f'Stopped messages for {updated} customer(s).')

    @admin.action(description='Allow messages')
    def allow_messages(self, request, queryset):
        updated = queryset.update(
            do_not_contact=False,
            do_not_contact_reason='',
            do_not_contact_set_by=request.user,
            do_not_contact_at=timezone.now(),
        )
        self.message_user(request, f'Allowed messages for {updated} customer(s).')
    fieldsets = (
        ('Identification', {
            'fields': ('customer_id', 'first_name', 'last_name', 'email', 'phone', 'alternate_phone', 'cnic')
        }),
        ('Address', {
            'fields': ('address', 'city')
        }),
        ('Status', {
            'fields': ('is_active', 'notes')
        }),
        ('Messaging', {
            'fields': ('do_not_contact', 'do_not_contact_reason',
                       'do_not_contact_set_by', 'do_not_contact_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CustomerLedgerEntry)
class CustomerLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['customer', 'transaction_type', 'debit', 'credit', 'running_balance', 'entry_date']
    list_filter = ['transaction_type', 'entry_date']
    search_fields = ['customer__first_name', 'customer__last_name', 'reference_id', 'description']
    readonly_fields = ['running_balance', 'created_at']
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReceivableAging)
class ReceivableAgingAdmin(admin.ModelAdmin):
    list_display = ['customer', 'booking', 'current_balance', 'days_overdue', 'aging_bucket', 'computed_at']
    list_filter = ['aging_bucket', 'computed_at']
    search_fields = ['customer__first_name', 'customer__last_name']
    readonly_fields = ['computed_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False