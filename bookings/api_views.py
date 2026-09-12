from decimal import Decimal

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
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
        from django.db import transaction
        with transaction.atomic():
            # Lock the plot row so two concurrent requests cannot both book it.
            plot = Plot.objects.select_for_update().get(pk=serializer.validated_data['plot'].pk)
            if plot.status in ('booked', 'sold', 'cancelled'):
                raise ValidationError({'plot': f'Plot {plot.plot_number} is not available for booking.'})
            booking = serializer.save(created_by=self.request.user)
            plot.status = 'booked'
            plot.save()
            # Record the upfront advance as a real verified Payment so the
            # payment ledger, receipts, and customer payment history stay
            # consistent with booking.advance_paid.
            from decimal import Decimal as _Decimal
            advance = _Decimal(serializer.validated_data.get('advance_paid') or 0)
            if advance > 0:
                from payments.models import Payment, Receipt
                payment = Payment.objects.create(
                    booking=booking,
                    amount=advance,
                    payment_date=timezone.now().date(),
                    payment_method='cash',
                    payment_type='down_payment',
                    status='verified',
                    verified_by=self.request.user,
                    verified_at=timezone.now(),
                    created_by=self.request.user,
                    notes='Upfront advance collected at booking',
                )
                Receipt.objects.create(
                    payment=payment,
                    receipt_date=payment.payment_date,
                    generated_by=self.request.user,
                )
                payment.receipt_generated = True
                payment.save(update_fields=['receipt_generated'])
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
        # Match the web flow: notify the customer about the new booking.
        try:
            from notifications.services import NotificationService
            NotificationService.send_booking_notification(booking)
        except Exception:
            # Notifications must never fail the booking creation.
            import logging
            logging.getLogger(__name__).warning(
                'Booking notification failed for %s', booking.booking_id)

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
        if verified_amount > 0:
            return Response(
                {'error': 'This booking has verified payments. Process a refund before cancelling.'},
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
        """Mark an installment paid and record a verified Payment for the ledger."""
        from django.db import transaction as db_transaction
        installment = self.get_object()
        booking = installment.plan.booking

        total = installment.amount + installment.late_fee
        new_paid = Decimal(str(request.data.get('paid_amount', total)))
        if new_paid < 0:
            return Response({'error': 'paid_amount cannot be negative.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if new_paid > total:
            return Response(
                {'error': f'paid_amount cannot exceed installment total {total}.'},
                status=status.HTTP_400_BAD_REQUEST)

        delta = new_paid - installment.paid_amount

        with db_transaction.atomic():
            installment.paid_amount = new_paid
            installment.status = 'paid' if new_paid >= total else 'partial'
            installment.paid_date = request.data.get('paid_date', timezone.now().date())
            installment.save()

            # Record a real Payment row so the ledger, receipts, and
            # customer totals stay consistent with advance_paid.
            if delta > 0:
                Payment.objects.create(
                    booking=booking,
                    installment=installment,
                    amount=delta,
                    payment_date=request.data.get('paid_date', timezone.now().date()),
                    payment_method=request.data.get('payment_method', 'cash'),
                    payment_type='installment',
                    status='verified',
                    verified_by=request.user,
                    verified_at=timezone.now(),
                    created_by=request.user,
                    notes='Marked paid via installment action',
                )
                booking.advance_paid = min(booking.advance_paid + delta, booking.total_amount)
                if booking.remaining_balance <= 0:
                    booking.status = 'completed'
                booking.save()

                # Recalculate the plan: this installment is now settled, so
                # later installments must adjust to the new remaining balance.
                if hasattr(booking, 'installment_plan') and booking.installment_plan:
                    booking.installment_plan.recalculate()

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
                advance_paid=reservation.token_amount,
                status='confirmed',
                created_by=request.user,
                notes=f'Converted from reservation {reservation.pk}',
            )
            plot.status = 'booked'
            plot.save()
            reservation.status = 'converted'
            reservation.save()

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