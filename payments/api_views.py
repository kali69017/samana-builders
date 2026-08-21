from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone
from django.db import models as db_models
from .models import Payment, Receipt, Refund, PaymentAllocation
from .serializers import (
    PaymentSerializer, PaymentCreateSerializer, PaymentDetailSerializer,
    PaymentVerificationSerializer, ReceiptSerializer, RefundSerializer,
    PaymentAllocationSerializer,
)


class IsStaffReadAdminWrite(permissions.BasePermission):
    """Finance roles can read and create, only management can verify/delete."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        if hasattr(request.user, 'profile'):
            return request.user.profile.role in ['super_admin', 'admin', 'management', 'accounts']
        return False
    
    def has_object_permission(self, request, view, obj):
        if request.method == 'DELETE':
            if request.user.is_superuser:
                return True
            if hasattr(request.user, 'profile'):
                return request.user.profile.role in ['super_admin', 'admin', 'management']
            return False
        return True


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related(
        'booking', 'booking__customer', 'installment', 'created_by', 'verified_by'
    ).all()
    serializer_class = PaymentSerializer
    permission_classes = [IsStaffReadAdminWrite]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PaymentCreateSerializer
        if self.action in ['retrieve', 'detail']:
            return PaymentDetailSerializer
        return PaymentSerializer
    
    def perform_create(self, serializer):
        payment = serializer.save(created_by=self.request.user)
        from core.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Payment',
            object_id=payment.payment_id,
            description=f'Created payment {payment.payment_id} for booking {payment.booking.booking_id} via API'
        )
    
    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        method_filter = self.request.query_params.get('method')
        booking_id = self.request.query_params.get('booking')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        
        if status_filter:
            qs = qs.filter(status=status_filter)
        if method_filter:
            qs = qs.filter(payment_method=method_filter)
        if booking_id:
            qs = qs.filter(booking_id=booking_id)
        if date_from:
            qs = qs.filter(payment_date__gte=date_from)
        if date_to:
            qs = qs.filter(payment_date__lte=date_to)
        
        return qs
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """Verify or reject a payment. Admin-only in practice (checked below)."""
        user_role = None
        if hasattr(request.user, 'profile'):
            user_role = request.user.profile.role
        
        if not request.user.is_superuser and user_role not in ['super_admin', 'admin']:
            return Response(
                {'error': 'Only administrators can verify payments.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        payment = self.get_object()

        # Guard against re-verifying/rejecting an already-finalized payment,
        # which would double-count the booking advance and installment amounts.
        if payment.status in ['verified', 'rejected', 'reversed']:
            return Response(
                {'error': f'Payment is already {payment.get_status_display()}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = PaymentVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_type = serializer.validated_data['action']
        notes = serializer.validated_data.get('notes', '')
        
        if action_type == 'verify':
            payment.status = 'verified'
            payment.verified_by = request.user
            payment.verified_at = timezone.now()
            payment.notes = notes
            
            # Update installment if linked
            if payment.installment:
                installment = payment.installment
                installment.paid_amount += payment.amount
                if installment.paid_amount >= installment.amount:
                    installment.status = 'paid'
                    installment.paid_date = payment.payment_date
                else:
                    installment.status = 'partial'
                installment.save()
            
            # Update booking advance
            booking = payment.booking
            booking.advance_paid += payment.amount
            if booking.remaining_balance <= 0:
                booking.status = 'completed'
            booking.save()
        else:
            payment.status = 'rejected'
            payment.verified_by = request.user
            payment.verified_at = timezone.now()
            payment.notes = notes
        
        payment.save()
        
        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='verify' if action_type == 'verify' else 'reject',
            model_name='Payment',
            object_id=payment.payment_id,
            description=f'{action_type.title()} payment {payment.payment_id} via API'
        )
        
        return Response(PaymentSerializer(payment).data)
    
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload_attachment(self, request, pk=None):
        """Upload an attachment for a payment."""
        payment = self.get_object()
        file = request.FILES.get('file')
        attachment_type = request.data.get('attachment_type', 'other')
        
        if not file:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        from .models import PaymentAttachment
        attachment = PaymentAttachment.objects.create(
            payment=payment,
            file=file,
            attachment_type=attachment_type,
            filename=file.name,
            uploaded_by=request.user
        )
        
        from .serializers import PaymentAttachmentSerializer
        return Response(
            PaymentAttachmentSerializer(attachment, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['post'])
    def mark_bounced(self, request, pk=None):
        """Mark a cheque payment as bounced."""
        payment = self.get_object()
        bounce_reason = request.data.get('bounce_reason', '')
        bounce_fee = request.data.get('bounce_fee', 0)
        
        payment.status = 'bounced'
        payment.bounce_reason = bounce_reason
        payment.bounce_fee = bounce_fee
        payment.save()
        
        return Response(PaymentSerializer(payment).data)


class ReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Receipt.objects.select_related('payment', 'generated_by').all()
    serializer_class = ReceiptSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        qs = super().get_queryset()
        payment_id = self.request.query_params.get('payment')
        if payment_id:
            qs = qs.filter(payment_id=payment_id)
        return qs


class RefundViewSet(viewsets.ModelViewSet):
    queryset = Refund.objects.select_related(
        'booking', 'original_payment', 'approved_by'
    ).all()
    serializer_class = RefundSerializer
    permission_classes = [IsStaffReadAdminWrite]
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        refund = self.get_object()
        refund.status = 'approved'
        refund.approved_by = request.user
        refund.save()
        return Response(RefundSerializer(refund).data)


class PaymentAllocationViewSet(viewsets.ModelViewSet):
    queryset = PaymentAllocation.objects.select_related('payment', 'installment', 'allocated_by').all()
    serializer_class = PaymentAllocationSerializer
    permission_classes = [IsStaffReadAdminWrite]
    
    def perform_create(self, serializer):
        serializer.save(allocated_by=self.request.user)