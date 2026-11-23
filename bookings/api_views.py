from decimal import Decimal

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Sum
from properties.models import Plot
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
    """Allow read for admin/management/sales/accounts, write for admin+."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            from core.permissions import user_role_allows
            return user_role_allows(request, ('super_admin', 'admin', 'management', 'sales', 'accounts'))
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

    def create(self, request, *args, **kwargs):
        idem_key = request.data.get('idempotency_key')
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            existing = Booking.objects.filter(idempotency_key=idem_key).first() if idem_key else None
            if existing is None:
                raise
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        from django.db import transaction
        with transaction.atomic():
            # Lock the plot row so two concurrent requests cannot both book it.
            plot = Plot.objects.select_for_update().get(pk=serializer.validated_data['plot'].pk)
            if plot.status in ('booked', 'sold', 'cancelled'):
                raise ValidationError({'plot': f'Plot {plot.plot_number} is not available for booking.'})
            from decimal import Decimal as _Decimal
            advance = _Decimal(serializer.validated_data.get('advance_paid') or 0)
            booking = serializer.save(
                created_by=self.request.user, advance_paid=_Decimal('0'))
            plot.status = 'booked'
            plot.save()
            # Record the upfront advance as a pending Payment. The booking
            # balance and receipt are only applied when it is verified.
            if advance > 0:
                from finance.accounting import cash_bank_head
                from payments.models import Payment
                Payment.objects.create(
                    booking=booking,
                    received_into=cash_bank_head('cash'),
                    amount=advance,
                    payment_date=timezone.now().date(),
                    payment_method='cash',
                    payment_type='down_payment',
                    status='pending',
                    created_by=self.request.user,
                    notes='Upfront advance recorded at booking, pending verification',
                )
            # Link the reservation if one exists for this customer+plot.
            from .models import Reservation
            Reservation.objects.filter(
                customer=booking.customer, plot=plot, status='active'
            ).update(status='converted')
            from core.models import AuditLog
            AuditLog.objects.create(
                user=self.request.user, action='create', model_name='Booking',
                object_id=booking.booking_id,
                description=f'Created booking {booking.booking_id} for {booking.customer.full_name} via API'
            )
            # This only queues; provider calls happen after commit.
            from notifications.services import NotificationService
            NotificationService.send_booking_notification(booking)

    def destroy(self, request, *args, **kwargs):
        """Delete a booking only when it has no payments.

        Deleting a booking that already has verified payments would silently
        destroy the payment, receipt, and ledger history — so those bookings
        must go through the refund/cancel workflow instead. On a successful
        delete the plot is released back to available.
        """
        from django.db.models import Sum
        booking = self.get_object()
        verified_amount = booking.payments.filter(status='verified').aggregate(
            total=Sum('amount'))['total'] or 0
        if verified_amount > 0:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {'detail': 'This booking has verified payments. Process a refund before deleting it.'}
            )
        plot = booking.plot
        response = super().destroy(request, *args, **kwargs)
        plot.status = 'available'
        plot.save(update_fields=['status'])
        return response
    
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

        # Guard: a booking with verified payments cannot be cancelled
        # through this endpoint — it needs the refund workflow instead.
        verified_amount = booking.payments.filter(status='verified').aggregate(
            total=Sum('amount'))['total'] or 0
        refunded_amount = booking.refunds.exclude(status='rejected').aggregate(
            total=Sum('amount'))['total'] or 0
        if verified_amount > refunded_amount:
            return Response(
                {'error': 'This booking has unrefunded verified payments. Process a refund before cancelling.'},
                status=status.HTTP_400_BAD_REQUEST
            )

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

        # Idempotent for already-confirmed/active/completed bookings (safe for
        # API retries); only blocked for cancelled bookings.
        if booking.status in ('confirmed', 'active', 'completed'):
            return Response(BookingSerializer(booking).data)
        if booking.status == 'cancelled':
            return Response(
                {'error': 'A cancelled booking cannot be confirmed.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ─── Task 2: no advance payment => cannot confirm (API bypass blocked) ──
        if booking.advance_paid <= 0:
            return Response(
                {'error': 'Cannot confirm booking: no advance payment has been recorded. '
                          'Record the deposit/advance before confirming.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        booking.status = 'confirmed'
        booking.save()

        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='update', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Confirmed booking {booking.booking_id}'
        )

        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        from django.core.exceptions import ValidationError
        from core.permissions import get_user_role
        if get_user_role(request) not in ('super_admin', 'admin', 'management'):
            return Response(
                {'error': 'Only super_admin, admin or management can mark a booking delivered.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        booking = self.get_object()
        paid = booking.amount_paid
        unpaid = max(booking.total_amount - paid, 0)
        if unpaid > 0 and str(request.data.get('confirm_unpaid', '')).lower() not in (
                '1', 'true', 'yes', 'on'):
            return Response(
                {'error': f'Confirm the unpaid balance of Rs. {unpaid} before delivering.',
                 'unpaid': str(unpaid)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            booking.mark_delivered(
                request.user, request.data.get('delivery_date'))
        except ValidationError as exc:
            return Response(
                {'error': ' '.join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='update', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Marked booking {booking.booking_id} delivered via API',
        )
        return Response(self.get_serializer(booking).data)

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
        verified_paid = booking.payments.filter(status='verified').aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        refunded = booking.refunds.exclude(status='rejected').aggregate(
            total=Sum('amount'))['total'] or Decimal('0.00')
        refundable = max(verified_paid - refunded, Decimal('0.00'))
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
            'refundable': float(refundable),
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
        """Record a pending payment for an installment.

        The installment becomes paid only when that payment is verified.
        """
        from django.db import transaction as db_transaction
        installment = self.get_object()
        booking = installment.plan.booking

        total = installment.amount + installment.late_fee
        target_paid = Decimal(str(request.data.get('paid_amount', total)))
        if target_paid < 0:
            return Response({'error': 'paid_amount cannot be negative.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if target_paid > total:
            return Response(
                {'error': f'paid_amount cannot exceed installment total {total}.'},
                status=status.HTTP_400_BAD_REQUEST)
        delta = target_paid - installment.paid_amount
        if delta <= 0:
            return Response(
                {'error': 'paid_amount must be greater than the amount already paid.'},
                status=status.HTTP_400_BAD_REQUEST)

        if installment.payments.filter(
                status__in=['pending', 'under_clearing']).exists():
            return Response(
                {'error': 'A payment for this installment is already pending verification.'},
                status=status.HTTP_400_BAD_REQUEST)

        payment_method = request.data.get('payment_method', 'cash')
        with db_transaction.atomic():
            installment = Installment.objects.select_for_update().get(pk=installment.pk)
            if installment.payments.filter(
                    status__in=['pending', 'under_clearing']).exists():
                return Response(
                    {'error': 'A payment for this installment is already pending verification.'},
                    status=status.HTTP_400_BAD_REQUEST)
            from finance.accounting import cash_bank_head
            Payment.objects.create(
                booking=booking,
                installment=installment,
                received_into=cash_bank_head(payment_method),
                amount=delta,
                payment_date=request.data.get('paid_date', timezone.now().date()),
                payment_method=payment_method,
                payment_type='installment',
                status='pending',
                created_by=request.user,
                notes='Installment payment recorded, pending verification',
            )

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
        """Convert reservation to booking.

        Creates an actual Booking for the reserved plot (token amount becomes
        the advance) and moves the plot to booked. Requires the customer and
        plot to still be valid, and fails cleanly if the plot was already
        booked by someone else in the meantime.
        """
        from django.db import transaction
        from django.db.models import Q
        from decimal import Decimal
        from .models import Booking, Plot
        from .serializers import BookingSerializer

        reservation = self.get_object()
        if reservation.status != 'active':
            return Response(
                {'error': f'Reservation is already {reservation.get_status_display()}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            plot = Plot.objects.select_for_update().get(pk=reservation.plot_id)
            if plot.status in ('booked', 'sold'):
                reservation.status = 'expired'
                reservation.save()
                return Response(
                    {'error': 'Plot is no longer available for conversion.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            booking = Booking.objects.create(
                customer=reservation.customer,
                plot=plot,
                total_amount=plot.price,
                advance_paid=Decimal('0'),
                status='confirmed',
                created_by=request.user,
                notes=f'Converted from reservation {reservation.pk}',
            )
            plot.status = 'booked'
            plot.save()
            reservation.status = 'converted'
            reservation.save()
            if reservation.token_amount > 0:
                from finance.accounting import cash_bank_head
                Payment.objects.create(
                    booking=booking,
                    received_into=cash_bank_head('cash'),
                    amount=reservation.token_amount,
                    payment_date=timezone.now().date(),
                    payment_method='cash',
                    payment_type='advance',
                    status='pending',
                    created_by=request.user,
                    notes='Reservation token converted to booking, pending verification',
                )

        from core.models import AuditLog
        AuditLog.objects.create(
            user=request.user, action='create', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Created booking {booking.booking_id} from reservation {reservation.pk}'
        )
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


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