from django.core.exceptions import ValidationError
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import (
    AccountTransaction, AccountHead, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment, Voucher,
)
from .serializers import (
    AccountTransactionSerializer, AccountHeadSerializer, OfficeSerializer,
    ExpenseCategorySerializer, OfficeExpenseSerializer, ProjectBudgetSerializer,
    ProjectCostSerializer, ProjectInvestmentSerializer, VoucherSerializer,
    VoucherAuditLogSerializer,
)


def _validation_error_detail(exc):
    if hasattr(exc, 'message_dict'):
        return exc.message_dict
    return getattr(exc, 'messages', [str(exc)])


class IsFinanceOrAbove(permissions.BasePermission):
    """Read for authenticated staff, write for finance roles."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            from core.permissions import is_portal_customer
            return not is_portal_customer(request.user)
        if request.user.is_superuser:
            return True
        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        return role in ['super_admin', 'admin', 'management', 'accounts']


class AccountTransactionViewSet(viewsets.ModelViewSet):
    queryset = AccountTransaction.objects.select_related('employee').all()
    serializer_class = AccountTransactionSerializer
    permission_classes = [IsFinanceOrAbove]

    def get_queryset(self):
        qs = super().get_queryset()
        transaction_type = self.request.query_params.get('transaction_type')
        direction = self.request.query_params.get('direction')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if transaction_type:
            qs = qs.filter(transaction_type=transaction_type)
        if direction:
            qs = qs.filter(direction=direction)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs


class OfficeViewSet(viewsets.ModelViewSet):
    queryset = Office.objects.all()
    serializer_class = OfficeSerializer
    permission_classes = [IsFinanceOrAbove]

    def destroy(self, request, *args, **kwargs):
        office = self.get_object()
        if office.expenses.exists() or office.transactions.exists():
            return Response(
                {'error': f"Cannot delete office '{office.name}' — it still has "
                          'expenses or ledger transactions.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsFinanceOrAbove]


class OfficeExpenseViewSet(viewsets.ModelViewSet):
    queryset = OfficeExpense.objects.select_related('office', 'category').all()
    serializer_class = OfficeExpenseSerializer
    permission_classes = [IsFinanceOrAbove]

    def get_queryset(self):
        qs = super().get_queryset()
        office_id = self.request.query_params.get('office')
        status_filter = self.request.query_params.get('status')
        if office_id:
            qs = qs.filter(office_id=office_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        expense = serializer.save(created_by=self.request.user)
        if expense.status == 'paid':
            expense.post_to_ledger()

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        expense = self.get_object()
        expense.status = 'approved'
        expense.approved_by = request.user
        expense.save()
        return Response(OfficeExpenseSerializer(expense).data)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        expense = self.get_object()
        expense.status = 'paid'
        expense.save()
        expense.post_to_ledger()
        return Response(OfficeExpenseSerializer(expense).data)


class ProjectCostViewSet(viewsets.ModelViewSet):
    queryset = ProjectCost.objects.select_related('project').all()
    serializer_class = ProjectCostSerializer
    permission_classes = [IsFinanceOrAbove]

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get('project')
        category = self.request.query_params.get('category')
        if project_id:
            qs = qs.filter(project_id=project_id)
        if category:
            qs = qs.filter(cost_category=category)
        return qs

    def perform_create(self, serializer):
        cost = serializer.save(created_by=self.request.user)
        if cost.status == 'paid':
            cost.post_to_ledger()


class ProjectBudgetViewSet(viewsets.ModelViewSet):
    queryset = ProjectBudget.objects.select_related('project').all()
    serializer_class = ProjectBudgetSerializer
    permission_classes = [IsFinanceOrAbove]


class ProjectInvestmentViewSet(viewsets.ModelViewSet):
    queryset = ProjectInvestment.objects.select_related('project').all()
    serializer_class = ProjectInvestmentSerializer
    permission_classes = [IsFinanceOrAbove]


# ─── DOUBLE-ENTRY ACCOUNTING ─────────────────────────────────────────────────
class IsFinanceRole(permissions.BasePermission):
    """Finance roles only for *all* methods (no read leak to other staff)."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        return role in ('super_admin', 'admin', 'management', 'accounts')


class IsManagementOrAbove(permissions.BasePermission):
    """Supervisor gate (super_admin/admin/management) — mirrors management_or_above."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        return role in ('super_admin', 'admin', 'management')


class AccountHeadViewSet(viewsets.ModelViewSet):
    queryset = AccountHead.objects.select_related('parent').all()
    serializer_class = AccountHeadSerializer
    permission_classes = [IsFinanceRole]

    def destroy(self, request, *args, **kwargs):
        head = self.get_object()
        if head.children.exists():
            return Response(
                {'error': 'Cannot delete an account head that has children.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if head.voucher_lines.filter(voucher__status='posted').exists():
            return Response(
                {'error': 'Cannot delete an account head that has posted voucher lines.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class VoucherViewSet(viewsets.ModelViewSet):
    queryset = (
        Voucher.objects
        .select_related('created_by', 'locked_by', 'unlocked_by')
        .prefetch_related('lines__account_head', 'audit_logs')
        .all()
    )
    serializer_class = VoucherSerializer
    permission_classes = [IsFinanceRole]

    def get_permissions(self):
        if self.action == 'unlock':
            return [IsManagementOrAbove()]
        return super().get_permissions()

    def update(self, request, *args, **kwargs):
        voucher = self.get_object()
        if voucher.reference_id is not None:
            return Response(
                {'error': 'Auto-generated vouchers are read-only except for unlock.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not voucher.is_editable:
            return Response(
                {'error': 'Voucher is posted and locked; unlock it before editing.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        voucher = self.get_object()
        if voucher.reference_id is not None:
            return Response(
                {'error': 'Auto-generated vouchers cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not voucher.is_editable:
            return Response(
                {'error': 'Posted and locked vouchers cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def post(self, request, pk=None):
        voucher = self.get_object()
        try:
            voucher.post(request.user)
        except ValidationError as exc:
            return Response({'error': _validation_error_detail(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(voucher).data)

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        voucher = self.get_object()
        try:
            voucher.unlock(request.user, reason=request.data.get('reason', ''))
        except ValidationError as exc:
            return Response({'error': _validation_error_detail(exc)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(voucher).data)

    @action(detail=True, methods=['get'])
    def audit(self, request, pk=None):
        voucher = self.get_object()
        rows = voucher.audit_logs.select_related('actor').all()
        return Response(VoucherAuditLogSerializer(rows, many=True).data)
