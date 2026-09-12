from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import models as db_models
from django.shortcuts import get_object_or_404
from .models import Customer, CustomerLedgerEntry
from .serializers import (
    CustomerSerializer, CustomerDetailSerializer,
    CustomerLedgerEntrySerializer, CustomerCreateSerializer,
    CustomerProfileCreateSerializer,
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


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def destroy(self, request, *args, **kwargs):
        """Block deletion of customers with financial history."""
        customer = self.get_object()
        if customer.bookings.exists() or customer.ledger_entries.exists():
            return Response(
                {'error': 'Cannot delete a customer with bookings or ledger history. Deactivate them instead.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CustomerCreateSerializer
        if self.action in ['retrieve', 'detail']:
            return CustomerDetailSerializer
        return CustomerSerializer
    
    def perform_create(self, serializer):
        customer = serializer.save(created_by=self.request.user)
        from notifications.services import NotificationService
        NotificationService.send_customer_welcome(customer, user=self.request.user)
        from core.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Customer',
            object_id=customer.customer_id,
            description=f'Created customer {customer.full_name} via API'
        )
    
    def perform_update(self, serializer):
        customer = serializer.save()
        from core.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user, action='update', model_name='Customer',
            object_id=customer.customer_id,
            description=f'Updated customer {customer.full_name} via API'
        )
    
    def perform_destroy(self, instance):
        from core.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user, action='delete', model_name='Customer',
            object_id=instance.customer_id,
            description=f'Deleted customer {instance.customer_id} via API'
        )
        instance.delete()
    
    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search', '')
        is_active = self.request.query_params.get('is_active')
        
        if search:
            qs = qs.filter(
                db_models.Q(customer_id__icontains=search) |
                db_models.Q(first_name__icontains=search) |
                db_models.Q(last_name__icontains=search) |
                db_models.Q(phone__icontains=search) |
                db_models.Q(cnic__icontains=search)
            )
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ['true', '1'])
        
        return qs
    
    @action(detail=False, methods=['get'])
    def search(self, request):
        query = request.query_params.get('q', '')
        if query:
            customers = Customer.objects.filter(
                db_models.Q(customer_id__icontains=query) |
                db_models.Q(first_name__icontains=query) |
                db_models.Q(last_name__icontains=query) |
                db_models.Q(phone__icontains=query) |
                db_models.Q(cnic__icontains=query)
            )
        else:
            customers = Customer.objects.all()
        
        page = self.paginate_queryset(customers)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(customers, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def ledger(self, request, pk=None):
        customer = self.get_object()
        entries = customer.ledger_entries.select_related('booking', 'created_by').all()
        serializer = CustomerLedgerEntrySerializer(entries, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def bookings(self, request, pk=None):
        customer = self.get_object()
        from bookings.serializers import BookingSerializer
        bookings = customer.bookings.select_related('plot', 'plot__project').all()
        serializer = BookingSerializer(bookings, many=True)
        return Response(serializer.data)


class CustomerProfileCreateView(APIView):
    """Admin creates a customer portal login linked to an existing Customer."""
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request):
        serializer = CustomerProfileCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        customer = serializer.validated_data['customer']

        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='create', model_name='CustomerProfile',
            object_id=customer.customer_id,
            description=f'Created customer profile for {customer.customer_id} ({user.username})'
        )

        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'customer_id': customer.customer_id,
            'full_name': customer.full_name,
        }, status=status.HTTP_201_CREATED)


class CustomerLedgerEntryViewSet(viewsets.ModelViewSet):
    queryset = CustomerLedgerEntry.objects.select_related('customer', 'booking', 'created_by').all()
    serializer_class = CustomerLedgerEntrySerializer
    permission_classes = [IsAdminOrSuperAdmin]
    
    def perform_create(self, serializer):
        entry = serializer.save(created_by=self.request.user)
        # Calculate running balance
        last_entry = CustomerLedgerEntry.objects.filter(
            customer=entry.customer,
            entry_date__lt=entry.entry_date
        ).order_by('-entry_date', '-created_at').first()
        
        prev_balance = last_entry.running_balance if last_entry else 0
        entry.running_balance = prev_balance + entry.debit - entry.credit
        entry.save(update_fields=['running_balance'])