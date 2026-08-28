from django.contrib import admin

from .models import AiInteractionLog


@admin.register(AiInteractionLog)
class AiInteractionLogAdmin(admin.ModelAdmin):
    list_display = ('feature', 'status', 'user', 'model', 'latency_ms', 'created_at')
    list_filter = ('feature', 'status', 'created_at')
    search_fields = ('prompt', 'response', 'error_message', 'user__username')
    readonly_fields = ('prompt', 'response', 'error_message', 'latency_ms', 'created_at')
