from rest_framework import serializers
from .models import (
    Department, Designation, SalaryComponent, Employee, EmployeeDocument,
    EmployeeSalary, PayrollRun, SalarySlip, SalarySlipItem, SalaryPayment,
    Attendance, Leave,
)


class DepartmentSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = ['id', 'name', 'description', 'is_active', 'employee_count']
        read_only_fields = ['id']


class DesignationSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Designation
        fields = ['id', 'title', 'is_active', 'employee_count']
        read_only_fields = ['id']


class SalaryComponentSerializer(serializers.ModelSerializer):
    component_type_display = serializers.CharField(source='get_component_type_display', read_only=True)

    class Meta:
        model = SalaryComponent
        fields = ['id', 'name', 'component_type', 'component_type_display', 'is_active']
        read_only_fields = ['id']


class EmployeeSalarySerializer(serializers.ModelSerializer):
    component_name = serializers.CharField(source='component.name', read_only=True)
    component_type = serializers.CharField(source='component.component_type', read_only=True)

    class Meta:
        model = EmployeeSalary
        fields = ['id', 'employee', 'component', 'component_name', 'component_type', 'amount', 'effective_from']
        read_only_fields = ['id']


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    department_name = serializers.CharField(source='department.name', read_only=True, allow_null=True)
    designation_name = serializers.CharField(source='designation.title', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    salaries = EmployeeSalarySerializer(many=True, read_only=True)

    def validate_cnic(self, value):
        value = (value or '').strip()
        if value:
            qs = Employee.objects.filter(cnic=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError('An employee with this CNIC already exists.')
        return value

    class Meta:
        model = Employee
        fields = ['id', 'employee_id', 'first_name', 'last_name', 'full_name',
                  'department', 'department_name', 'designation', 'designation_name',
                  'joining_date', 'cnic', 'phone', 'email', 'address', 'status', 'status_display',
                  'notes', 'salaries', 'created_at', 'updated_at']
        read_only_fields = ['id', 'employee_id', 'created_at', 'updated_at']


class SalarySlipItemSerializer(serializers.ModelSerializer):
    component_name = serializers.CharField(source='component.name', read_only=True)
    component_type = serializers.CharField(source='component.component_type', read_only=True)

    class Meta:
        model = SalarySlipItem
        fields = ['id', 'slip', 'component', 'component_name', 'component_type', 'amount']
        read_only_fields = ['id']


class SalarySlipSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    items = SalarySlipItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SalarySlip
        fields = ['id', 'employee', 'employee_name', 'run', 'status', 'status_display',
                  'gross', 'total_earnings', 'total_deductions', 'net', 'notes', 'items']
        read_only_fields = ['id', 'gross', 'total_earnings', 'total_deductions', 'net']


class SalaryPaymentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='slip.employee.full_name', read_only=True)
    method_display = serializers.CharField(source='get_method_display', read_only=True)

    class Meta:
        model = SalaryPayment
        fields = ['id', 'slip', 'employee_name', 'amount', 'payment_date', 'method',
                  'method_display', 'reference_number', 'created_at']
        read_only_fields = ['id', 'created_at']


class PayrollRunSerializer(serializers.ModelSerializer):
    period_label = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    slip_count = serializers.ReadOnlyField()
    total_net = serializers.ReadOnlyField()

    class Meta:
        model = PayrollRun
        fields = ['id', 'month', 'year', 'period_label', 'status', 'status_display',
                  'notes', 'slip_count', 'total_net', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Attendance
        fields = ['id', 'employee', 'employee_name', 'date',
                  'status', 'status_display', 'notes']
        read_only_fields = ['id']


class LeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    def validate(self, attrs):
        start = attrs.get('start_date')
        end = attrs.get('end_date')
        days = attrs.get('days')
        if start and end and end < start:
            raise serializers.ValidationError(
                {'end_date': 'End date cannot be before the start date.'}
            )
        if days is not None and days <= 0:
            raise serializers.ValidationError({'days': 'Leave days must be greater than 0.'})
        return attrs

    class Meta:
        model = Leave
        fields = ['id', 'employee', 'employee_name', 'leave_type', 'leave_type_display',
                  'start_date', 'end_date', 'days', 'reason', 'status', 'status_display',
                  'approved_by', 'applied_on']
        read_only_fields = ['id', 'applied_on', 'approved_by']
