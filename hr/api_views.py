from datetime import date

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.db import models as db_models
from django.db.models import Count

from core.models import AuditLog
from .models import (
    Department, Designation, SalaryComponent, Employee, EmployeeSalary,
    PayrollRun, SalarySlip, SalarySlipItem, SalaryPayment, Attendance, Leave,
)
from .serializers import (
    DepartmentSerializer, DesignationSerializer, SalaryComponentSerializer,
    EmployeeSerializer, EmployeeSalarySerializer, PayrollRunSerializer,
    SalarySlipSerializer, SalarySlipItemSerializer, SalaryPaymentSerializer,
    AttendanceSerializer, LeaveSerializer,
)


class IsHRManagement(permissions.BasePermission):
    """Read for authenticated staff, write for HR management roles."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        return role in ['super_admin', 'admin', 'management', 'hr']


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.annotate(employee_count=Count('employees')).all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsHRManagement]


class DesignationViewSet(viewsets.ModelViewSet):
    queryset = Designation.objects.annotate(employee_count=Count('employees')).all()
    serializer_class = DesignationSerializer
    permission_classes = [IsHRManagement]


class SalaryComponentViewSet(viewsets.ModelViewSet):
    queryset = SalaryComponent.objects.all()
    serializer_class = SalaryComponentSerializer
    permission_classes = [IsHRManagement]


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.select_related('department', 'designation').prefetch_related('salaries').all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsHRManagement]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        search = self.request.query_params.get('search')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if search:
            qs = qs.filter(
                db_models.Q(employee_id__icontains=search) |
                db_models.Q(first_name__icontains=search) |
                db_models.Q(last_name__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        emp = serializer.save(created_by=self.request.user)
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='Employee',
            object_id=emp.employee_id, description=f'Created employee {emp.full_name} via API')

    @action(detail=True, methods=['post'])
    def add_salary(self, request, pk=None):
        employee = self.get_object()
        serializer = EmployeeSalarySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        es = serializer.save(employee=employee)
        return Response(EmployeeSalarySerializer(es).data, status=status.HTTP_201_CREATED)


class EmployeeSalaryViewSet(viewsets.ModelViewSet):
    queryset = EmployeeSalary.objects.select_related('employee', 'component').all()
    serializer_class = EmployeeSalarySerializer
    permission_classes = [IsHRManagement]


class PayrollRunViewSet(viewsets.ModelViewSet):
    queryset = PayrollRun.objects.all()
    serializer_class = PayrollRunSerializer
    permission_classes = [IsHRManagement]

    def perform_create(self, serializer):
        run = serializer.save(created_by=self.request.user)
        AuditLog.objects.create(
            user=self.request.user, action='create', model_name='PayrollRun',
            object_id=str(run.pk), description=f'Created payroll run {run.period_label} via API')

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        run = self.get_object()
        count = run.generate_slips()
        return Response({'generated': count})

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        run = self.get_object()
        with transaction.atomic():
            for slip in run.slips.all():
                slip.recalculate()
                slip.status = 'approved'
                slip.save(update_fields=['status'])
            run.status = 'processed'
            run.save(update_fields=['status'])
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        run = self.get_object()
        paid = 0
        with transaction.atomic():
            for slip in run.slips.filter(status='approved'):
                payment, created = SalaryPayment.objects.get_or_create(
                    slip=slip,
                    defaults={'amount': slip.net, 'payment_date': date.today(),
                              'method': 'bank_transfer', 'created_by': request.user})
                if created:
                    payment.post_to_ledger()
                slip.status = 'paid'
                slip.save(update_fields=['status'])
                paid += 1
            run.status = 'paid'
            run.save(update_fields=['status'])
        return Response({'paid': paid})


class SalarySlipViewSet(viewsets.ModelViewSet):
    queryset = SalarySlip.objects.select_related('employee', 'run').prefetch_related('items').all()
    serializer_class = SalarySlipSerializer
    permission_classes = [IsHRManagement]


class SalaryPaymentViewSet(viewsets.ModelViewSet):
    queryset = SalaryPayment.objects.select_related('slip__employee').all()
    serializer_class = SalaryPaymentSerializer
    permission_classes = [IsHRManagement]

    def perform_create(self, serializer):
        payment = serializer.save(created_by=self.request.user)
        payment.post_to_ledger()


class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.select_related('employee').all()
    serializer_class = AttendanceSerializer
    permission_classes = [IsHRManagement]

    def get_queryset(self):
        qs = super().get_queryset()
        date_filter = self.request.query_params.get('date')
        employee_id = self.request.query_params.get('employee')
        if date_filter:
            qs = qs.filter(date=date_filter)
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        return qs


class LeaveViewSet(viewsets.ModelViewSet):
    queryset = Leave.objects.select_related('employee', 'approved_by').all()
    serializer_class = LeaveSerializer
    permission_classes = [IsHRManagement]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        leave = self.get_object()
        leave.status = 'approved'
        leave.approved_by = request.user
        leave.save()
        return Response(LeaveSerializer(leave).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        leave = self.get_object()
        leave.status = 'rejected'
        leave.approved_by = request.user
        leave.save()
        return Response(LeaveSerializer(leave).data)
