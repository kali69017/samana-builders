from django.core.exceptions import ValidationError
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import (
    AccountHead, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment, Voucher,
)
from .serializers import (
    AccountHeadSerializer, OfficeSerializer,
    ExpenseCategorySerializer, OfficeExpenseSerializer, ProjectBudgetSerializer,
    ProjectCostSerializer, ProjectInvestmentSerializer, VoucherSerializer,
    VoucherAuditLogSerializer,
)


def _validation_error_detail(exc):
    if hasattr(exc, 'message_dict'):
        return exc.message_dict
    return getattr(exc, 'messages', [str(exc)])


class IsFinanceOrAbove(permissions.BasePermission):
    """Read + write for finance roles (super_admin/admin/management/accounts)."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            from core.permissions import user_role_allows
            return user_role_allows(request, ('super_admin', 'admin', 'management', 'accounts'))
        if request.user.is_superuser:
            return True
        role = getattr(getattr(request.user, 'profile', None), 'role', None)
        return role in ['super_admin', 'admin', 'management', 'accounts']


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

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        from .views import expense_category_usage
        used = expense_category_usage(category)
        if used:
            return Response(
                {'error': f'This category is used by {used} records. Deactivate it instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            category.delete()
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


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

    def destroy(self, request, *args, **kwargs):
        expense = self.get_object()
        if Voucher.objects.filter(reference_type='OfficeExpense', reference_id=expense.pk).exists():
            return Response(
                {'error': 'An office expense with a posted voucher cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        expense = self.get_object()
        if expense.status == 'paid':
            # Illegal transition: the voucher is posted and locked, so the source
            # must not fall back to an unposted state or it silently desyncs from
            # the ledger. 400 matches the house convention for transition guards
            # (see tests/finance/finance.spec.ts FIN-SEC-03).
            return Response(
                {'detail': 'A paid office expense is already posted to the ledger.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        expense.status = 'approved'
        expense.approved_by = request.user
        expense.save()
        return Response(OfficeExpenseSerializer(expense).data)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        expense = self.get_object()
        # Pay may only follow approve — paying a draft/pending expense would post
        # money that was never approved (FIN-SEC-03).
        if expense.status == 'paid':
            return Response(OfficeExpenseSerializer(expense).data)
        if expense.status != 'approved':
            return Response(
                {'detail': 'Only approved expenses can be paid '
                           f'(current status: {expense.get_status_display()}).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
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

    def destroy(self, request, *args, **kwargs):
        cost = self.get_object()
        if Voucher.objects.filter(reference_type='ProjectCost', reference_id=cost.pk).exists():
            return Response(
                {'error': 'A project cost with a posted voucher cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        cost = self.get_object()
        if cost.status == 'paid':
            return Response(
                {'detail': 'A paid project cost is already posted to the ledger.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cost.status = 'approved'
        cost.save()
        return Response(ProjectCostSerializer(cost).data)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        cost = self.get_object()
        # Pay may only follow approve — posting an unapproved cost would move
        # money out of the ledger without approval (FIN-SEC-03).
        if cost.status == 'paid':
            return Response(ProjectCostSerializer(cost).data)
        if cost.status != 'approved':
            return Response(
                {'detail': 'Only approved project costs can be paid '
                           f'(current status: {cost.get_status_display()}).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cost.status = 'paid'
        cost.save()
        cost.post_to_ledger()
        return Response(ProjectCostSerializer(cost).data)


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
        if head.parent_id is None:
            return Response(
                {'error': 'Level 1 root accounts cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if head.children.exists():
            return Response(
                {'error': 'Cannot delete an account head that has children.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if head.voucher_lines.exists():
            return Response(
                {'error': 'Cannot delete an account head that has ledger entries.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if head.system_role:
            return Response(
                {'error': 'A system account cannot be deleted.'},
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
        # Posting is supervisor-only; finance users may create/edit drafts but
        # cannot post their own vouchers (spec §3.6).
        if self.action in ('post', 'unlock'):
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
        return Response(
            {'error': 'Vouchers cannot be deleted. Reverse them with a new voucher instead.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

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
