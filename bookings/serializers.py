from rest_framework import serializers
from .models import (
    Booking, BookingGroup, BookingTransfer, BookingAmendment,
    InstallmentPlan, InstallmentPlanTemplate, Installment,
    Reservation, CancellationPolicy, CancellationTier,
    LateFeeConfiguration, PaymentReminder, EarlySettlement
)
from customers.serializers import CustomerSerializer
from properties.serializers import PlotSerializer


# ─── INSTALLMENTS ────────────────────────────────────────────────────────────────

class InstallmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    remaining_amount = serializers.ReadOnlyField()
    
    class Meta:
        model = Installment
        fields = ['id', 'installment_number', 'due_date', 'amount', 'late_fee',
                  'paid_amount', 'remaining_amount', 'status', 'status_display',
                  'paid_date', 'payment_allocation', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


# ─── INSTALLMENT PLANS ───────────────────────────────────────────────────────────

class InstallmentPlanSerializer(serializers.ModelSerializer):
    installments = InstallmentSerializer(many=True, read_only=True)
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    
    class Meta:
        model = InstallmentPlan
        fields = ['id', 'booking', 'total_installments', 'installment_amount',
                  'down_payment_amount', 'start_date', 'frequency', 'frequency_display',
                  'due_day', 'late_fee_per_day', 'grace_period_days',
                  'total_late_fee_applied', 'is_active', 'installments', 'created_at']
        read_only_fields = ['id', 'total_late_fee_applied', 'created_at']


class InstallmentPlanTemplateSerializer(serializers.ModelSerializer):
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    
    class Meta:
        model = InstallmentPlanTemplate
        fields = ['id', 'name', 'project', 'total_installments', 'frequency',
                  'frequency_display', 'down_payment_percentage', 'late_fee_per_day',
                  'grace_period_days', 'has_balloon_payment',
                  'balloon_installment_number', 'balloon_multiplier',
                  'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


# ─── RESERVATIONS ────────────────────────────────────────────────────────────────

class ReservationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    plot_number = serializers.CharField(source='plot.plot_number', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    def validate_token_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Token amount must be greater than 0')
        return value

    def validate(self, data):
        plot = data.get('plot')
        if plot and plot.status in ('booked', 'sold'):
            raise serializers.ValidationError(
                {'plot': f'Plot {plot.plot_number} is already booked or sold.'}
            )
        return data

    class Meta:
        model = Reservation
        fields = ['id', 'customer', 'customer_name', 'plot', 'plot_number',
                  'token_amount', 'reserved_at', 'expires_at', 'status', 'status_display']
        read_only_fields = ['id', 'reserved_at']


# ─── BOOKINGS ────────────────────────────────────────────────────────────────────

class BookingSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    plot_number = serializers.CharField(source='plot.plot_number', read_only=True)
    project_name = serializers.CharField(source='plot.project.name', read_only=True)
    remaining_balance = serializers.ReadOnlyField()
    payment_progress = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    
    class Meta:
        model = Booking
        fields = ['id', 'booking_id', 'customer', 'customer_name', 'plot', 'plot_number',
                  'project_name', 'booking_date', 'total_amount', 'advance_paid',
                  'remaining_balance', 'payment_progress', 'status', 'status_display',
                  'source', 'source_display', 'possession_date', 'is_possession_taken',
                  'notes', 'created_at', 'updated_at', 'created_by']
        read_only_fields = ['id', 'booking_id', 'booking_date', 'created_at',
                           'updated_at', 'created_by', 'payment_progress']
    
    def validate_total_amount(self, value):
        if value and value <= 0:
            raise serializers.ValidationError('Total amount must be greater than 0')
        return value
    
    def validate_advance_paid(self, value):
        if value and value < 0:
            raise serializers.ValidationError('Advance cannot be negative')
        return value


class BookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = ['customer', 'plot', 'total_amount', 'advance_paid', 'source', 'agent', 'notes']

    def validate_total_amount(self, value):
        if value and value <= 0:
            raise serializers.ValidationError('Total amount must be greater than 0')
        return value

    def validate_advance_paid(self, value):
        if value and value < 0:
            raise serializers.ValidationError('Advance cannot be negative')
        total = self.initial_data.get('total_amount', 0)
        if value and total and value > float(total):
            raise serializers.ValidationError('Advance cannot exceed total amount')
        return value

    def validate_agent(self, value):
        if value and not value.is_active:
            raise serializers.ValidationError(
                {'agent': f'Agent {value.name} is inactive and cannot be assigned to bookings.'}
            )
        return value

    def validate(self, data):
        plot = data.get('plot')
        if plot:
            # A plot can only be booked if it is currently available or
            # reserved for this same customer. This prevents double-booking.
            if plot.status in ('booked', 'sold'):
                raise serializers.ValidationError(
                    {'plot': f'Plot {plot.plot_number} is already booked or sold.'}
                )
            if plot.status == 'cancelled':
                raise serializers.ValidationError(
                    {'plot': f'Plot {plot.plot_number} is cancelled and cannot be booked.'}
                )
            # Guard against a second active booking on the same plot.
            if Booking.objects.filter(
                plot=plot, status__in=['pending', 'confirmed', 'active']
            ).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise serializers.ValidationError(
                    {'plot': f'Plot {plot.plot_number} already has an active booking.'}
                )
        return data


class BookingDetailSerializer(serializers.ModelSerializer):
    """Full booking detail with payments and installments."""
    customer = CustomerSerializer(read_only=True)
    plot_detail = PlotSerializer(source='plot', read_only=True)
    installment_plan = InstallmentPlanSerializer(read_only=True)
    remaining_balance = serializers.ReadOnlyField()
    payment_progress = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    
    class Meta:
        model = Booking
        fields = ['id', 'booking_id', 'customer', 'plot', 'plot_detail',
                  'booking_date', 'total_amount', 'advance_paid', 'remaining_balance',
                  'payment_progress', 'status', 'status_display', 'source', 'source_display',
                  'possession_date', 'is_possession_taken', 'notes',
                  'installment_plan', 'created_at', 'updated_at', 'created_by']
        read_only_fields = ['id', 'booking_id', 'booking_date', 'created_at',
                           'updated_at', 'created_by', 'payment_progress']


# ─── TRANSFERS ───────────────────────────────────────────────────────────────────

class BookingTransferSerializer(serializers.ModelSerializer):
    from_customer_name = serializers.CharField(source='from_customer.full_name', read_only=True)
    to_customer_name = serializers.CharField(source='to_customer.full_name', read_only=True)
    booking_id_display = serializers.CharField(source='booking.booking_id', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True, allow_null=True)

    def validate(self, attrs):
        from_customer = attrs.get('from_customer')
        to_customer = attrs.get('to_customer')
        transfer_fee = attrs.get('transfer_fee')
        if from_customer and to_customer and from_customer.pk == to_customer.pk:
            raise serializers.ValidationError(
                {'to_customer': 'The transfer target cannot be the same customer as the source.'}
            )
        if transfer_fee is not None and transfer_fee < 0:
            raise serializers.ValidationError(
                {'transfer_fee': 'Transfer fee cannot be negative.'}
            )
        return attrs

    class Meta:
        model = BookingTransfer
        fields = ['id', 'booking', 'booking_id_display', 'from_customer',
                  'from_customer_name', 'to_customer', 'to_customer_name',
                  'transfer_fee', 'previous_payments_handling',
                  'approved_by', 'approved_by_name', 'transfer_date', 'notes']
        read_only_fields = ['id', 'transfer_date']


class BookingAmendmentSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True)
    
    class Meta:
        model = BookingAmendment
        fields = ['id', 'booking', 'field_name', 'old_value', 'new_value',
                  'changed_by', 'changed_by_name', 'changed_at']
        read_only_fields = ['id', 'changed_at']


# ─── EARLY SETTLEMENT ────────────────────────────────────────────────────────────

class EarlySettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = EarlySettlement
        fields = ['id', 'plan', 'remaining_installments', 'total_remaining_amount',
                  'discount_percentage', 'discount_amount', 'settlement_amount',
                  'approved', 'settled_at', 'created_at']
        read_only_fields = ['id', 'created_at']