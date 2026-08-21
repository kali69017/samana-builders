from django.contrib import admin
from .models import Project, ProjectPhase, Plot, PlotFeature, PlotDocument, PriceHistory, PlotImport, ProjectMilestone


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'total_plots', 'status', 'available_plots', 'booked_plots', 'sold_plots']
    search_fields = ['name', 'location']
    list_filter = ['status']


@admin.register(ProjectPhase)
class ProjectPhaseAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'launch_date', 'total_plots', 'price_per_marla', 'is_active']
    list_filter = ['project', 'is_active', 'launch_date']
    search_fields = ['name', 'project__name']


@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = ['plot_number', 'project', 'phase', 'block', 'plot_type', 'size_marla', 'price', 'status']
    search_fields = ['plot_number', 'project__name', 'block']
    list_filter = ['status', 'plot_type', 'project', 'phase']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Plot Info', {
            'fields': ('plot_number', 'project', 'phase', 'block', 'street_number', 'plot_type')
        }),
        ('Size & Pricing', {
            'fields': ('size_marla', 'size_sqft', 'price', 'holding_deposit')
        }),
        ('Status & Features', {
            'fields': ('status', 'is_corner', 'is_park_facing', 'facing_direction', 'features')
        }),
        ('Details', {
            'fields': ('description',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(PlotFeature)
class PlotFeatureAdmin(admin.ModelAdmin):
    list_display = ['name', 'icon']
    search_fields = ['name']


@admin.register(PlotDocument)
class PlotDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'plot', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['title', 'plot__plot_number']


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ['plot', 'old_price', 'new_price', 'change_reason', 'changed_by', 'changed_at']
    list_filter = ['changed_at']
    search_fields = ['plot__plot_number', 'change_reason']
    readonly_fields = ['changed_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PlotImport)
class PlotImportAdmin(admin.ModelAdmin):
    list_display = ['project', 'status', 'plots_created', 'plots_failed', 'uploaded_by', 'uploaded_at']
    list_filter = ['status', 'project']
    readonly_fields = ['uploaded_at', 'plots_created', 'plots_failed', 'error_log']


@admin.register(ProjectMilestone)
class ProjectMilestoneAdmin(admin.ModelAdmin):
    list_display = ['project', 'title', 'status', 'target_date', 'completed_date', 'order']
    list_filter = ['status', 'project']
    search_fields = ['title', 'project__name']
    readonly_fields = ['created_at', 'updated_at']