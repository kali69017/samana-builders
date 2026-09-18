from django.urls import path, include
from rest_framework.routers import DefaultRouter
from api.views import csrf_token, api_login, api_logout, current_user, portal_dashboard
from core.api_views import (
    UserViewSet, AuditLogViewSet, ProfileViewSet,
    LeadViewSet, LeadNoteViewSet, AgentViewSet, CompanySettingsViewSet,
)
from customers.api_views import (
    CustomerViewSet, CustomerLedgerEntryViewSet, CustomerProfileCreateView
)
from properties.api_views import (
    ProjectViewSet, ProjectPhaseViewSet, PlotViewSet,
    PlotFeatureViewSet, PriceHistoryViewSet, ProjectMilestoneViewSet,
    plots_list_api
)
from bookings.api_views import (
    BookingViewSet, InstallmentPlanViewSet, InstallmentViewSet,
    InstallmentPlanTemplateViewSet, ReservationViewSet,
    BookingTransferViewSet, EarlySettlementViewSet
)
from payments.api_views import (
    PaymentViewSet, ReceiptViewSet, RefundViewSet, PaymentAllocationViewSet
)
from hr.api_views import (
    DepartmentViewSet, DesignationViewSet, SalaryComponentViewSet,
    EmployeeViewSet, EmployeeSalaryViewSet, PayrollRunViewSet,
    SalarySlipViewSet, SalaryPaymentViewSet, AttendanceViewSet, LeaveViewSet,
)
from finance.api_views import (
    AccountTransactionViewSet, AccountHeadViewSet, OfficeViewSet,
    ExpenseCategoryViewSet, OfficeExpenseViewSet, ProjectCostViewSet,
    ProjectBudgetViewSet, ProjectInvestmentViewSet, VoucherViewSet,
)

router = DefaultRouter()

# Core
router.register(r'users', UserViewSet)
router.register(r'audit-logs', AuditLogViewSet)
router.register(r'profile', ProfileViewSet, basename='profile')
router.register(r'leads', LeadViewSet)
router.register(r'lead-notes', LeadNoteViewSet)
router.register(r'agents', AgentViewSet)

# Customers
router.register(r'customers', CustomerViewSet)
router.register(r'customer-ledger', CustomerLedgerEntryViewSet)

# Properties
router.register(r'projects', ProjectViewSet)
router.register(r'project-phases', ProjectPhaseViewSet)
router.register(r'plots', PlotViewSet)
router.register(r'plot-features', PlotFeatureViewSet)
router.register(r'price-history', PriceHistoryViewSet)
router.register(r'project-milestones', ProjectMilestoneViewSet)

# Bookings
router.register(r'bookings', BookingViewSet)
router.register(r'installment-plans', InstallmentPlanViewSet)
router.register(r'installments', InstallmentViewSet)
router.register(r'installment-plan-templates', InstallmentPlanTemplateViewSet)
router.register(r'reservations', ReservationViewSet)
router.register(r'booking-transfers', BookingTransferViewSet)
router.register(r'early-settlements', EarlySettlementViewSet)

# Payments
router.register(r'payments', PaymentViewSet)
router.register(r'receipts', ReceiptViewSet)
router.register(r'refunds', RefundViewSet)
router.register(r'payment-allocations', PaymentAllocationViewSet)

# HR & Payroll
router.register(r'departments', DepartmentViewSet)
router.register(r'designations', DesignationViewSet)
router.register(r'salary-components', SalaryComponentViewSet)
router.register(r'employees', EmployeeViewSet)
router.register(r'employee-salaries', EmployeeSalaryViewSet)
router.register(r'payroll-runs', PayrollRunViewSet)
router.register(r'salary-slips', SalarySlipViewSet)
router.register(r'salary-payments', SalaryPaymentViewSet)
router.register(r'attendance', AttendanceViewSet)
router.register(r'leaves', LeaveViewSet)

# Finance
router.register(r'account-transactions', AccountTransactionViewSet)
router.register(r'offices', OfficeViewSet)
router.register(r'expense-categories', ExpenseCategoryViewSet)
router.register(r'office-expenses', OfficeExpenseViewSet)
router.register(r'project-costs', ProjectCostViewSet)
router.register(r'project-budgets', ProjectBudgetViewSet)
router.register(r'project-investments', ProjectInvestmentViewSet)
router.register(r'account-heads', AccountHeadViewSet)
router.register(r'vouchers', VoucherViewSet)

urlpatterns = [
    # Public homepage endpoints (must come before the router's {pk} detail routes)
    path('plots/list/', plots_list_api, name='plots_list'),

    # Company settings singleton (GET + PATCH/PUT on the list URL)
    path('company-settings/', CompanySettingsViewSet.as_view({
        'get': 'list', 'patch': 'update', 'put': 'update',
    }), name='company-settings'),
    path('company-settings/summary/', CompanySettingsViewSet.as_view({
        'get': 'summary',
    }), name='company-settings-summary'),

    path('', include(router.urls)),

    # Auth
    path('auth/csrf/', csrf_token, name='api_csrf'),
    path('auth/login/', api_login, name='api_login'),
    path('auth/logout/', api_logout, name='api_logout'),
    path('auth/me/', current_user, name='api_me'),

    # AI features (LangChain + DeepSeek)
    path('ai/', include('ai.urls')),

    # Customer portal login creation + portal data
    path('customer-profiles/', CustomerProfileCreateView.as_view(), name='customer_profile_create'),
    path('portal/', portal_dashboard, name='portal_dashboard'),

    path('auth/', include('rest_framework.urls', namespace='rest_framework')),
]