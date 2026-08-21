from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    UserProfile, AuditLog, LoginAttempt, ApprovalChain, ApprovalStep, ApprovalRequest,
    Lead, LeadNote, Agent, CompanySettings,
)


class UserProfileSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    
    class Meta:
        model = UserProfile
        fields = ['role', 'role_display', 'phone', 'cnic', 'is_active']


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name',
                  'is_active', 'profile', 'last_login', 'date_joined']
        read_only_fields = ['id', 'last_login', 'date_joined']


class UserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=30)
    last_name = serializers.CharField(max_length=30)
    role = serializers.ChoiceField(choices=['super_admin', 'admin', 'sales', 'accounts', 'management'])
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    cnic = serializers.CharField(max_length=15, required=False, allow_blank=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('Username already exists')
        return value

    def create(self, validated_data):
        role = validated_data.pop('role', 'sales')
        phone = validated_data.pop('phone', '')
        cnic = validated_data.pop('cnic', '')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        UserProfile.objects.create(
            user=user,
            role=role,
            phone=phone,
            cnic=cnic,
        )
        return user


class AuditLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True, allow_null=True, default='System')
    
    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'user_username', 'action', 'model_name', 'object_id', 'description', 'ip_address', 'timestamp']
        read_only_fields = ['id', 'timestamp']


class LoginAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginAttempt
        fields = '__all__'


class ApprovalStepSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    
    class Meta:
        model = ApprovalStep
        fields = '__all__'


class ApprovalChainSerializer(serializers.ModelSerializer):
    steps = ApprovalStepSerializer(many=True, read_only=True)
    
    class Meta:
        model = ApprovalChain
        fields = '__all__'


class ApprovalRequestSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source='requested_by.username', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.username', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = '__all__'
        read_only_fields = ['created_at', 'reviewed_at']


class LeadSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.username', read_only=True, allow_null=True)
    interest_project_name = serializers.CharField(source='interest_project.name', read_only=True, allow_null=True)

    class Meta:
        model = Lead
        fields = ['id', 'name', 'email', 'phone', 'source', 'source_display', 'status',
                  'status_display', 'assigned_to', 'assigned_to_name', 'interest_project',
                  'interest_project_name', 'budget', 'is_contacted', 'notes',
                  'converted_customer', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'converted_customer']

    def validate(self, attrs):
        if not any([attrs.get('name'), attrs.get('email'), attrs.get('phone')]):
            raise serializers.ValidationError('At least a name, email, or phone is required.')
        return attrs


class LeadNoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)

    class Meta:
        model = LeadNote
        fields = ['id', 'lead', 'note', 'created_by', 'created_by_name', 'created_at']
        read_only_fields = ['id', 'created_at', 'created_by']


class AgentSerializer(serializers.ModelSerializer):
    booking_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Agent
        fields = ['id', 'agent_id', 'name', 'phone', 'email', 'cnic',
                  'commission_rate', 'is_active', 'notes', 'booking_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'agent_id', 'created_at', 'updated_at']

    def validate_commission_rate(self, value):
        if value is not None and (value < 0 or value > 100):
            raise serializers.ValidationError('Commission rate must be between 0 and 100.')
        return value


class CompanySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySettings
        fields = ['id', 'company_name', 'tagline', 'phone', 'email', 'address',
                  'website', 'logo', 'currency', 'currency_symbol', 'tax_rate',
                  'receipt_footer', 'facebook', 'instagram', 'twitter', 'updated_at']
        read_only_fields = ['id', 'updated_at']