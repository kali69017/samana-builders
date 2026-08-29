from .permissions import (
    get_user_role, MANAGEMENT_ROLES, ADMIN_ROLES, PAYMENTS_ACCESS_ROLES,
    FINANCE_ROLES, ACCOUNTS, SALES, HR_MANAGEMENT_ROLES, PAYROLL_ROLES,
)


def user_theme_processor(request):
    """Pass the logged-in user's saved theme to all templates."""
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile:
            return {'user_theme': profile.theme}
    return {'user_theme': 'professional-blue'}


def erp_context(request):
    """Pass role + permission flags to all templates for role-aware UI."""
    from django.conf import settings
    role = get_user_role(request)
    user = request.user
    if user.is_authenticated:
        display_name = user.get_full_name() or user.username
        initials = (display_name[0] if display_name else 'U').upper()
    else:
        display_name = ''
        initials = ''
    return {
        'user_role': role,
                'user_display_name': display_name,
                'user_initials': initials,
                'is_employee': bool(getattr(user, 'employee', None)),
                'can_view_payments': role in PAYMENTS_ACCESS_ROLES,
        'can_view_expenses': role in FINANCE_ROLES,
        'can_manage_users': role in ADMIN_ROLES,
        'can_view_users': role in MANAGEMENT_ROLES,
        'can_backup': role in ADMIN_ROLES,
        'can_audit': role in MANAGEMENT_ROLES,
        'can_delete': role in MANAGEMENT_ROLES,
        'can_view_leads': role in MANAGEMENT_ROLES + (ACCOUNTS, SALES),
        'can_view_reports': role in FINANCE_ROLES,
        'can_manage_settings': role in ADMIN_ROLES,
        'can_manage_hr': role in HR_MANAGEMENT_ROLES,
        'can_view_payroll': role in PAYROLL_ROLES,
        'whatsapp_number': getattr(settings, 'WHATSAPP_PHONE_NUMBER', ''),
    }


def company_context(request):
    """Expose company branding/settings to every template."""
    from .models import CompanySettings
    try:
        company = CompanySettings.load()
    except Exception:
        company = None
    currency_symbol = getattr(company, 'currency_symbol', 'Rs.') or 'Rs.'
    return {
        'company': company,
        'company_name': getattr(company, 'company_name', 'Samana Builders') or 'Samana Builders',
        'currency_symbol': currency_symbol,
    }
