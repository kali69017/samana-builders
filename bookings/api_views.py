from decimal import Decimal

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Sum
from payments.models import Payment
from .models import (
    Booking, BookingGroup, BookingTransfer, BookingAmendment,
    InstallmentPlan, InstallmentPlanTemplate, Installment,
    Reservation, CancellationPolicy, LateFeeConfiguration,
    PaymentReminder, EarlySettlement
)
from .serializers import (
    BookingSerializer, BookingCreateSerializer, BookingDetailSerializer,
    InstallmentPlanSerializer, InstallmentSerializer,
    InstallmentPlanTemplateSerializer, ReservationSerializer,
    BookingTransferSerializer, BookingAmendmentSerializer,
    EarlySettlementSerializer,
)


class IsStaffOrAbove(permissions.BasePermission):
    """Allow read for all authenticated, write for admin+."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        if hasattr(request.user, 'profile'):
            return request.user.profile.role in ['super_admin', 'admin', 'management', 'sales']
        return False
    
    def has_object_permission(self, request, view, obj):
        # Lower roles can view, but not delete
        if request.method == 'DELETE':
            if request.user.is_superuser:
                return True
            if hasattr(request.user, 'profile'):
                return request.user.profile.role in ['super_admin', 'admin', 'management']
            return False
        return True


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.select_related(
        'customer', 'plot', 'plot__project', 'created_by', 'group'
    ).all()
    serializer_class = BookingSerializer
    permission_classes = [IsStaffOrAbove]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return BookingCreateSerializer
        if self.action in ['retrieve', 'detail']:
            return BookingDetailSerializer
        return BookingSerializer
    
    def perform_create(self, serializer):
        booking = serializer.save(created_by=self.request.user)
        # Update plot status
        plot = booking.plot
        plot.status = 'booked'
        plot.save()
        from core.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Created booking {booking.booking_id} for {booking.customer.full_name} via API'
        )
    
    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        customer_id = self.request.query_params.get('customer')
        project_id = self.request.query_params.get('project')
        
        if status_filter:
            qs = qs.filter(status=status_filter)
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if project_id:
            qs = qs.filter(plot__project_id=project_id)
        
        return qs
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        reason = request.data.get('reason', 'other')
        notes = request.data.get('notes', '')
        
        plot = booking.plot
        plot.status = 'available'
        plot.save()
        
        booking.status = 'cancelled'
        booking.notes = (booking.notes + '\n---\nCancelled: ' + notes) if booking.notes else notes
        booking.save()
        
        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='cancel', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Cancelled booking {booking.booking_id} - Reason: {reason}'
        )
        
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        booking = self.get_object()
        booking.status = 'confirmed'
        booking.save()
        
        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='update', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Confirmed booking {booking.booking_id}'
        )
        
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['get'])
    def payment_summary(self, request, pk=None):
        booking = self.get_object()
        
        property_price = booking.total_amount
        
        installment_plan = getattr(booking, 'installment_plan', None)
        discount = 0
        down_payment = 0
        remaining_amount = property_price
        
        installments_data = []
        total_installments = 0
        paid_installments = 0
        installment_amount = 0
        
        if installment_plan:
            group = BookingGroup.objects.filter(bookings=booking).first()
            discount = group.discount_amount if group else 0
            down_payment = installment_plan.down_payment_amount
            remaining_amount = property_price - down_payment
            total_installments = installment_plan.total_installments
            installment_amount = installment_plan.installment_amount
            
            for inst in installment_plan.installments.all().order_by('installment_number'):
                if inst.status == 'paid':
                    paid_installments += 1
                installments_data.append({
                    'id': inst.id,
                    'installment_number': inst.installment_number,
                    'due_date': inst.due_date,
                    'amount': float(inst.amount),
                    'late_fee': float(inst.late_fee),
                    'paid_amount': float(inst.paid_amount),
                    'remaining_amount': float(inst.remaining_amount),
                    'status': inst.status,
                    'status_display': inst.get_status_display(),
                })
        
        final_price = property_price - discount
        total_paid = float(booking.advance_paid)
        outstanding = float(booking.remaining_balance)
        progress = booking.payment_progress
        
        return Response({
            'booking_id': booking.booking_id,
            'property_price': float(property_price),
            'discount': float(discount),
            'final_price': float(final_price),
            'down_payment': float(down_payment),
            'remaining_amount': float(remaining_amount),
            'total_paid': total_paid,
            'paid_installments': paid_installments,
            'total_installments': total_installments,
            'installment_amount': float(installment_amount),
            'outstanding': outstanding,
            'progress_percent': progress,
            'has_installment_plan': installment_plan is not None,
            'installment_plan': {
                'id': installment_plan.id,
                'total_installments': installment_plan.total_installments,
                'installment_amount': float(installment_plan.installment_amount),
                'down_payment_amount': float(installment_plan.down_payment_amount),
                'start_date': installment_plan.start_date,
                'frequency': installment_plan.frequency,
                'frequency_display': installment_plan.get_frequency_display(),
            } if installment_plan else None,
            'installments': installments_data,
        })


class InstallmentPlanViewSet(viewsets.ModelViewSet):
    queryset = InstallmentPlan.objects.prefetch_related('installments').all()
    serializer_class = InstallmentPlanSerializer
    permission_classes = [IsStaffOrAbove]
    
    def perform_create(self, serializer):
        plan = serializer.save()
        if self.request.data.get('generate_now', True):
            plan.auto_generate()


class InstallmentViewSet(viewsets.ModelViewSet):
    queryset = Installment.objects.select_related('plan__booking').all()
    serializer_class = InstallmentSerializer
    permission_classes = [IsStaffOrAbove]
    
    def get_queryset(self):
        qs = super().get_queryset()
        plan_id = self.request.query_params.get('plan')
        status_filter = self.request.query_params.get('status')
        
        if plan_id:
            qs = qs.filter(plan_id=plan_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        
        return qs
    
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        installment = self.get_object()
        booking = installment.plan.booking

        total = installment.amount + installment.late_fee
        new_paid = Decimal(str(request.data.get('paid_amount', total)))
        delta = new_paid - installment.paid_amount

        installment.paid_amount = new_paid
        installment.status = 'paid' if new_paid >= total else 'partial'
        installment.paid_date = request.data.get('paid_date', timezone.now().date())
        installment.save()

        # Keep booking revenue (advance_paid) consistent with the adjustment.
        if delta > 0:
            booking.advance_paid = min(booking.advance_paid + delta, booking.total_amount)
            if booking.remaining_balance <= 0:
                booking.status = 'completed'
            booking.save()

        return Response(InstallmentSerializer(installment).data)


class InstallmentPlanTemplateViewSet(viewsets.ModelViewSet):
    queryset = InstallmentPlanTemplate.objects.all()
    serializer_class = InstallmentPlanTemplateSerializer
    permission_classes = [IsStaffOrAbove]


class ReservationViewSet(viewsets.ModelViewSet):
    queryset = Reservation.objects.select_related('customer', 'plot', 'created_by').all()
    serializer_class = ReservationSerializer
    permission_classes = [IsStaffOrAbove]
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def convert(self, request, pk=None):
        """Convert reservation to booking."""
        reservation = self.get_object()
        reservation.status = 'converted'
        reservation.save()
        return Response({'status': 'converted'}, status=status.HTTP_200_OK)


class BookingTransferViewSet(viewsets.ModelViewSet):
    queryset = BookingTransfer.objects.select_related(
        'booking', 'from_customer', 'to_customer', 'approved_by'
    ).all()
    serializer_class = BookingTransferSerializer
    permission_classes = [IsStaffOrAbove]


class EarlySettlementViewSet(viewsets.ModelViewSet):
    queryset = EarlySettlement.objects.all()
    serializer_class = EarlySettlementSerializer
    permission_classes = [IsStaffOrAbove]