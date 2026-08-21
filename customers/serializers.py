from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Customer, CustomerLedgerEntry


class CustomerLedgerEntrySerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    booking_id_display = serializers.CharField(source='booking.booking_id', read_only=True, allow_null=True)
    
    class Meta:
        model = CustomerLedgerEntry
        fields = ['id', 'customer', 'booking', 'booking_id_display', 'transaction_type',
                  'transaction_type_display', 'reference_id', 'debit', 'credit',
                  'running_balance', 'description', 'entry_date', 'created_by',
                  'created_by_name', 'created_at']
        read_only_fields = ['id', 'running_balance', 'created_at', 'created_by']


class CustomerSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    total_bookings = serializers.ReadOnlyField()
    total_paid = serializers.ReadOnlyField()
    current_balance = serializers.ReadOnlyField()
    document_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = ['id', 'customer_id', 'first_name', 'last_name', 'full_name', 'email',
                  'phone', 'alternate_phone', 'cnic', 'address', 'city', 'notes',
                  'document', 'image', 'document_name',
                  'is_active', 'total_bookings', 'total_paid', 'current_balance',
                  'created_at', 'updated_at', 'created_by']
        read_only_fields = ['id', 'customer_id', 'created_at', 'updated_at', 'created_by']
    
    def get_document_name(self, obj):
        if obj.document:
            import os
            return os.path.basename(obj.document.name)
        return None
    
    def validate_cnic(self, value):
        import re
        pattern = r'^\d{5}-\d{7}-\d{1}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError('CNIC format must be XXXXX-XXXXXXX-X')
        return value
    
    def validate_phone(self, value):
        import re
        pattern = r'^\+?[\d\-]{10,15}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError('Enter a valid phone number (10-15 digits)')
        return value


class CustomerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'alternate_phone',
                  'cnic', 'address', 'city', 'notes', 'is_active',
                  'document', 'image']
        read_only_fields = ['customer_id']

    def validate_cnic(self, value):
        import re
        pattern = r'^\d{5}-\d{7}-\d{1}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError('CNIC format must be XXXXX-XXXXXXX-X')
        return value
    
    def validate_phone(self, value):
        import re
        pattern = r'^\+?[\d\-]{10,15}$'
        if not re.match(pattern, value):
            raise serializers.ValidationError('Enter a valid phone number (10-15 digits)')
        return value


class CustomerProfileCreateSerializer(serializers.Serializer):
    """Create a Django login linked to an existing Customer."""
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True)
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('Username already exists')
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Email is already in use')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match'})
        return attrs

    def create(self, validated_data):
        customer = validated_data['customer']
        validated_data.pop('confirm_password')
        password = validated_data.pop('password')
        user = User(username=validated_data['username'], email=validated_data['email'])
        user.set_password(password)
        user.save()
        customer.user = user
        customer.save(update_fields=['user'])
        return user


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Detailed customer with ledger summary and payment info."""
    full_name = serializers.ReadOnlyField()
    total_bookings = serializers.ReadOnlyField()
    total_paid = serializers.ReadOnlyField()
    current_balance = serializers.ReadOnlyField()
    ledger_summary = serializers.SerializerMethodField()
    document_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Customer
        fields = ['id', 'customer_id', 'first_name', 'last_name', 'full_name', 'email',
                  'phone', 'alternate_phone', 'cnic', 'address', 'city', 'notes',
                  'document', 'image', 'document_name',
                  'is_active', 'total_bookings', 'total_paid', 'current_balance',
                  'ledger_summary', 'created_at', 'updated_at']
        read_only_fields = ['id', 'customer_id', 'created_at', 'updated_at']
    
    def get_document_name(self, obj):
        if obj.document:
            import os
            return os.path.basename(obj.document.name)
        return None
    
    def get_ledger_summary(self, obj):
        from django.db.models import Sum
        total_debit = obj.ledger_entries.aggregate(total=Sum('debit'))['total'] or 0
        total_credit = obj.ledger_entries.aggregate(total=Sum('credit'))['total'] or 0
        return {
            'total_debit': total_debit,
            'total_credit': total_credit,
            'balance': total_debit - total_credit,
        }
