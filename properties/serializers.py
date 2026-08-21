from rest_framework import serializers
from .models import Project, ProjectPhase, Plot, PriceHistory, PlotFeature, ProjectMilestone


class PlotFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlotFeature
        fields = ['id', 'name', 'icon']


class PlotSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    project_phase_name = serializers.CharField(source='phase.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    plot_type_display = serializers.CharField(source='get_plot_type_display', read_only=True)
    
    class Meta:
        model = Plot
        fields = ['id', 'plot_number', 'project', 'project_name', 'phase', 'block',
                  'street_number', 'project_phase_name', 'plot_type', 'plot_type_display',
                  'size_marla', 'size_sqft', 'price', 'holding_deposit', 'status',
                  'status_display', 'is_corner', 'is_park_facing', 'facing_direction',
                  'features', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_price(self, value):
        if value and value <= 0:
            raise serializers.ValidationError('Price must be greater than 0')
        return value
    
    def validate_size_marla(self, value):
        if value and value <= 0:
            raise serializers.ValidationError('Size must be greater than 0')
        return value


class PlotDetailSerializer(serializers.ModelSerializer):
    """Detailed plot with price history and full related data."""
    project_name = serializers.CharField(source='project.name', read_only=True)
    project_phase_name = serializers.CharField(source='phase.name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    plot_type_display = serializers.CharField(source='get_plot_type_display', read_only=True)
    features = PlotFeatureSerializer(many=True, read_only=True)
    price_history = serializers.SerializerMethodField()
    
    class Meta:
        model = Plot
        fields = ['id', 'plot_number', 'project', 'project_name', 'phase',
                  'project_phase_name', 'plot_type', 'plot_type_display',
                  'size_marla', 'size_sqft', 'price', 'holding_deposit', 'status',
                  'status_display', 'block', 'street_number', 'is_corner',
                  'is_park_facing', 'facing_direction', 'features', 'price_history',
                  'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_price_history(self, obj):
        history = PriceHistory.objects.filter(plot=obj).order_by('-changed_at')[:10]
        return PriceHistorySerializer(history, many=True).data


class PriceHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = PriceHistory
        fields = ['id', 'plot', 'old_price', 'new_price', 'change_reason',
                  'changed_by', 'changed_by_name', 'changed_at']
        read_only_fields = ['id', 'changed_at']


class ProjectPhaseSerializer(serializers.ModelSerializer):
    available_plots = serializers.SerializerMethodField()
    
    class Meta:
        model = ProjectPhase
        fields = ['id', 'project', 'name', 'description', 'launch_date',
                  'total_plots', 'available_plots', 'price_per_marla', 'is_active']
    
    def get_available_plots(self, obj):
        return obj.plots.filter(status='available').count()


class ProjectSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    available_plots = serializers.ReadOnlyField()
    booked_plots = serializers.ReadOnlyField()
    sold_plots = serializers.ReadOnlyField()
    phases = ProjectPhaseSerializer(many=True, read_only=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'location', 'total_plots',
                  'status', 'status_display', 'available_plots', 'booked_plots', 'sold_plots',
                  'latitude', 'longitude', 'phases', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProjectMilestoneSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source='project.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ProjectMilestone
        fields = ['id', 'project', 'project_name', 'title', 'description',
                  'target_date', 'completed_date', 'status', 'status_display',
                  'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']