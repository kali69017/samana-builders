from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db import models as db_models
from .models import Project, ProjectPhase, Plot, PriceHistory, PlotFeature, ProjectMilestone
from .serializers import (
    ProjectSerializer, ProjectPhaseSerializer,
    PlotSerializer, PlotDetailSerializer,
    PriceHistorySerializer, PlotFeatureSerializer,
    ProjectMilestoneSerializer,
)


class IsAdminOrSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        if hasattr(request.user, 'profile'):
            return request.user.profile.role in ['super_admin', 'admin']
        return False


class ReadOnlyForLowerRoles(permissions.BasePermission):
    """Lower roles can view but not modify."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        if hasattr(request.user, 'profile'):
            return request.user.profile.role in ['super_admin', 'admin', 'management']
        return False


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [ReadOnlyForLowerRoles]
    
    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs


class ProjectPhaseViewSet(viewsets.ModelViewSet):
    queryset = ProjectPhase.objects.all()
    serializer_class = ProjectPhaseSerializer
    permission_classes = [ReadOnlyForLowerRoles]
    
    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs


class PlotViewSet(viewsets.ModelViewSet):
    queryset = Plot.objects.select_related('project', 'phase').prefetch_related('features').all()
    serializer_class = PlotSerializer
    permission_classes = [ReadOnlyForLowerRoles]
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PlotDetailSerializer
        return PlotSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        status_filter = self.request.query_params.get('status')
        plot_type = self.request.query_params.get('plot_type')
        
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if plot_type:
            qs = qs.filter(plot_type=plot_type)
        
        return qs
    
    def perform_create(self, serializer):
        plot = serializer.save()
        from core.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Plot',
            object_id=str(plot.id),
            description=f'Created plot {plot.plot_number} in {plot.project.name}'
        )
    
    def perform_update(self, serializer):
        old_price = None
        if self.get_object():
            old_price = self.get_object().price
        plot = serializer.save()
        # Track price change
        if old_price and old_price != plot.price:
            PriceHistory.objects.create(
                plot=plot, old_price=old_price, new_price=plot.price,
                changed_by=self.request.user,
                change_reason='API update'
            )
    
    @action(detail=True, methods=['post'])
    def change_status(self, request, pk=None):
        plot = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(Plot.STATUS_CHOICES):
            return Response({'error': f'Invalid status. Must be one of: {dict(Plot.STATUS_CHOICES).keys()}'},
                           status=status.HTTP_400_BAD_REQUEST)
        old_status = plot.status
        plot.status = new_status
        plot.save()
        return Response(PlotSerializer(plot).data)


class PlotFeatureViewSet(viewsets.ModelViewSet):
    queryset = PlotFeature.objects.all()
    serializer_class = PlotFeatureSerializer
    permission_classes = [ReadOnlyForLowerRoles]


class PriceHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PriceHistory.objects.select_related('plot', 'changed_by').all()
    serializer_class = PriceHistorySerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        qs = super().get_queryset()
        plot_id = self.request.query_params.get('plot')
        if plot_id:
            qs = qs.filter(plot_id=plot_id)
        return qs


@api_view(['GET'])
@permission_classes([AllowAny])
def plots_list_api(request):
    """Public endpoint for homepage project locations.

    Only AVAILABLE plots are exposed — booked/sold inventory is a data leak.
    """
    from .models import Plot
    from .serializers import PlotSerializer

    plots = Plot.objects.select_related('project', 'phase').filter(
        status='available'
    )[:20]
    serializer = PlotSerializer(plots, many=True)
    return Response(serializer.data)


class ProjectMilestoneViewSet(viewsets.ModelViewSet):
    queryset = ProjectMilestone.objects.select_related('project').all()
    serializer_class = ProjectMilestoneSerializer
    permission_classes = [ReadOnlyForLowerRoles]

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    @action(detail=True, methods=['post'])
    def set_status(self, request, pk=None):
        from datetime import date
        milestone = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(ProjectMilestone.STATUS_CHOICES):
            return Response({'error': f'Invalid status. Must be one of {list(dict(ProjectMilestone.STATUS_CHOICES).keys())}'},
                            status=status.HTTP_400_BAD_REQUEST)
        milestone.status = new_status
        milestone.completed_date = date.today() if new_status == 'completed' else None
        milestone.save()
        return Response(ProjectMilestoneSerializer(milestone).data)
