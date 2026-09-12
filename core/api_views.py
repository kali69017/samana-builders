from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.db.models import Count, Sum
from .models import UserProfile, AuditLog, Lead, LeadNote, Agent, CompanySettings
from .serializers import (UserSerializer, UserCreateSerializer,
                           UserProfileSerializer, AuditLogSerializer,
                           LeadSerializer, LeadNoteSerializer,
                           AgentSerializer, CompanySettingsSerializer)


class IsAdminOrReadOnly(permissions.BasePermission):
    """Allow read for all authenticated, write only for admin/super_admin."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return (
            request.user.is_superuser or
            (hasattr(request.user, 'profile') and
             request.user.profile.role in ['super_admin', 'admin'])
        )


class IsSuperAdmin(permissions.BasePermission):
    """Allow only super_admin role."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return (
            hasattr(request.user, 'profile') and
            request.user.profile.role == 'super_admin'
        )


class IsStaffOrAbove(permissions.BasePermission):
    """Allow super_admin and admin."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if hasattr(request.user, 'profile'):
            return request.user.profile.role in ['super_admin', 'admin']
        return False


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.select_related('profile').all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer
    
    def perform_create(self, serializer):
        user = serializer.save()
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='User',
            object_id=user.username,
            description=f'Created user {user.username} via API'
        )
    
    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        if request.method == 'GET':
            serializer = self.get_serializer(request.user)
            return Response(serializer.data)
        elif request.method == 'PATCH':
            serializer = UserSerializer(
                request.user, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle user active status (admin only)."""
        user = self.get_object()
        if user == request.user:
            return Response(
                {'error': 'You cannot deactivate your own account.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.is_active = not user.is_active
        user.save()
        AuditLog.objects.create(
            user=request.user, action='update', model_name='User',
            object_id=user.username,
            description=f'{"Deactivated" if not user.is_active else "Activated"} user {user.username} via API'
        )
        return Response(UserSerializer(user).data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        qs = super().get_queryset()
        action_filter = self.request.query_params.get('action')
        model_filter = self.request.query_params.get('model')
        if action_filter:
            qs = qs.filter(action=action_filter)
        if model_filter:
            qs = qs.filter(model_name=model_filter)
        return qs[:100]  # Limit to latest 100


class ProfileViewSet(viewsets.GenericViewSet):
    """Self-service profile endpoint."""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def list(self, request):
        profile = getattr(request.user, 'profile', None)
        if not profile:
            return Response({'error': 'No profile found'}, status=404)
        serializer = self.get_serializer(profile)
        return Response(serializer.data)
    
    @action(detail=False, methods=['patch'])
    def update_profile(self, request):
        profile = getattr(request.user, 'profile', None)
        if not profile:
            return Response({'error': 'No profile found'}, status=404)
        serializer = self.get_serializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

class LeadViewSet(viewsets.ModelViewSet):
    """CRM lead management with status transitions and conversion."""
    queryset = Lead.objects.select_related('assigned_to', 'interest_project', 'converted_customer').all()
    serializer_class = LeadSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        source_filter = self.request.query_params.get('source')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if source_filter:
            qs = qs.filter(source=source_filter)
        return qs

    def perform_create(self, serializer):
        lead = serializer.save()
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Lead',
            object_id=str(lead.pk), description=f'Created lead {lead.display_name} via API'
        )

    @action(detail=True, methods=['post'])
    def set_status(self, request, pk=None):
        lead = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(Lead.LEAD_STATUS_CHOICES):
            return Response({'error': f'Invalid status. Must be one of {list(dict(Lead.LEAD_STATUS_CHOICES).keys())}'},
                            status=status.HTTP_400_BAD_REQUEST)
        lead.status = new_status
        if new_status == 'contacted':
            lead.is_contacted = True
        lead.save()
        AuditLog.objects.create(
            user=request.user, action='update', model_name='Lead',
            object_id=str(lead.pk), description=f'Updated lead {lead.display_name} status to {new_status}'
        )
        return Response(LeadSerializer(lead).data)

    @action(detail=True, methods=['post'])
    def convert(self, request, pk=None):
        """Convert a lead into a customer."""
        from customers.models import Customer
        from customers.models import format_cnic
        lead = self.get_object()
        if lead.converted_customer_id:
            return Response({'error': 'Lead is already converted.'}, status=status.HTTP_400_BAD_REQUEST)

        cnic_raw = (request.data.get('cnic') or '').strip()
        cnic = format_cnic(cnic_raw)
        if len(cnic_raw) < 13:
            return Response({'error': 'CNIC is required to convert a lead into a customer.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if Customer.objects.filter(cnic=cnic).exists():
            return Response({'error': f'A customer with CNIC {cnic} already exists.'},
                            status=status.HTTP_400_BAD_REQUEST)

        name = (request.data.get('name') or lead.name or '').strip()
        parts = name.split(' ', 1)
        first_name = request.data.get('first_name') or (parts[0] if parts else '')
        last_name = request.data.get('last_name') or (parts[1] if len(parts) > 1 else '')

        phone = (request.data.get('phone') or lead.phone or '').strip()
        if not phone:
            return Response({'error': 'Phone number is required to convert a lead into a customer.'},
                            status=status.HTTP_400_BAD_REQUEST)

        customer = Customer.objects.create(
            first_name=first_name or lead.name or 'Lead',
            last_name=last_name,
            email=request.data.get('email') or lead.email or None,
            phone=phone,
            cnic=cnic,
            city=request.data.get('city', ''),
            created_by=request.user,
        )
        lead.status = 'converted'
        lead.converted_customer = customer
        lead.save()
        from notifications.services import NotificationService
        NotificationService.send_customer_welcome(customer, user=request.user)

        AuditLog.objects.create(
            user=request.user, action='update', model_name='Lead',
            object_id=str(lead.pk), description=f'Converted lead {lead.display_name} to {customer.customer_id}'
        )
        return Response({
            'lead': LeadSerializer(lead).data,
            'customer_id': customer.customer_id,
            'customer_pk': customer.pk,
        }, status=status.HTTP_201_CREATED)


class LeadNoteViewSet(viewsets.ModelViewSet):
    queryset = LeadNote.objects.select_related('lead', 'created_by').all()
    serializer_class = LeadNoteSerializer
    permission_classes = [IsAdminOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.annotate(
        booking_count=Count('bookings'),
    ).all()
    serializer_class = AgentSerializer
    permission_classes = [IsAdminOrReadOnly]

    def perform_create(self, serializer):
        agent = serializer.save()
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Agent',
            object_id=agent.agent_id, description=f'Created agent {agent.name} via API'
        )

    @action(detail=True, methods=['get'])
    def bookings(self, request, pk=None):
        from bookings.serializers import BookingSerializer
        agent = self.get_object()
        bookings = agent.bookings.select_related('customer', 'plot', 'plot__project').all()
        return Response(BookingSerializer(bookings, many=True).data)


class CompanySettingsViewSet(viewsets.GenericViewSet):
    """Singleton company settings (retrieve + partial update)."""
    serializer_class = CompanySettingsSerializer
    permission_classes = [IsAdminOrReadOnly]

    def list(self, request):
        return Response(self.get_serializer(CompanySettings.load()).data)

    def update(self, request, *args, **kwargs):
        instance = CompanySettings.load()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def summary(self, request):
        """A small dashboard summary exposed over the API."""
        from bookings.models import Booking
        from customers.models import Customer
        from properties.models import Plot, Project
        from payments.models import Payment
        from expenses.models import Expense

        revenue = Booking.objects.aggregate(t=Sum('advance_paid'))['t'] or 0
        expenses = Expense.objects.aggregate(t=Sum('amount'))['t'] or 0

        return Response({
            'total_customers': Customer.objects.count(),
            'total_projects': Project.objects.exclude(status='inactive').count(),
            'total_plots': Plot.objects.count(),
            'available_plots': Plot.objects.filter(status='available').count(),
            'total_bookings': Booking.objects.count(),
            'active_bookings': Booking.objects.filter(status='active').count(),
            'pending_payments': Payment.objects.filter(status='pending').count(),
            'revenue': float(revenue),
            'expenses': float(expenses),
            'net_profit': float(revenue) - float(expenses),
        })
