from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

# ─── Role constants and groups ─────────────────────────────────────────────
SUPER_ADMIN = 'super_admin'
ADMIN = 'admin'
MANAGEMENT = 'management'
ACCOUNTS = 'accounts'
SALES = 'sales'
HR = 'hr'
PROJECT_MANAGER = 'project_manager'
CONTRACTOR = 'contractor'
STAFF = 'staff'

# super_admin + admin + management: full module access (except user management/backup)
MANAGEMENT_ROLES = (SUPER_ADMIN, ADMIN, MANAGEMENT)
# super_admin + admin + management + accounts: finance (payments) access
FINANCE_ROLES = (SUPER_ADMIN, ADMIN, MANAGEMENT, ACCOUNTS)
# super_admin + admin: user management and database backup
ADMIN_ROLES = (SUPER_ADMIN, ADMIN)
# Payments view/create (sales is excluded)
PAYMENTS_ACCESS_ROLES = (SUPER_ADMIN, ADMIN, MANAGEMENT, ACCOUNTS)
# HR management (employees, salary, attendance, leave, payroll)
HR_MANAGEMENT_ROLES = (SUPER_ADMIN, ADMIN, MANAGEMENT, HR)
# Payroll viewing + processing (accounts can record salary payments)
PAYROLL_ROLES = (SUPER_ADMIN, ADMIN, MANAGEMENT, HR, ACCOUNTS)


def get_user_role(request):
    """Return the effective ERP role for the request user (or None)."""
    if not request.user.is_authenticated:
        return None
    if request.user.is_superuser:
        return SUPER_ADMIN
    profile = getattr(request.user, 'profile', None)
    if profile:
        return profile.role
    return None


def user_has_role(request, *roles):
    return get_user_role(request) in roles


def role_required(*roles):
    """
    Generic decorator that checks if the user has one of the required roles.
    Three access levels: super_admin, admin, staff.
    Usage: @role_required('super_admin', 'admin')
    
    super_admin and admin can access everything.
    staff can view/create bookings/payments but NOT verify payments, delete, or manage users.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            # Superuser always has access
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # Check user profile role
            if hasattr(request.user, 'profile'):
                if request.user.profile.role in roles:
                    return view_func(request, *args, **kwargs)
            
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('dashboard')
        return wrapper
    return decorator


def super_admin_required(view_func):
    """Allow only super_admin role"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        
        if hasattr(request.user, 'profile') and request.user.profile.role == 'super_admin':
            return view_func(request, *args, **kwargs)
        
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper


def admin_or_above(view_func):
    """Allow only super_admin and admin roles"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        
        if hasattr(request.user, 'profile'):
            if request.user.profile.role in ['super_admin', 'admin']:
                return view_func(request, *args, **kwargs)
        
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper


def management_or_above(view_func):
    """Allow super_admin, admin and management roles."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        if hasattr(request.user, 'profile') and request.user.profile.role in MANAGEMENT_ROLES:
            return view_func(request, *args, **kwargs)

        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper


def finance_or_above(view_func):
    """Allow super_admin, admin, management and accounts (finance) roles."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        if hasattr(request.user, 'profile') and request.user.profile.role in FINANCE_ROLES:
            return view_func(request, *args, **kwargs)

        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper


def payments_access(view_func):
    """Allow payment view/create: super_admin, admin, management and accounts."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        if hasattr(request.user, 'profile') and request.user.profile.role in PAYMENTS_ACCESS_ROLES:
            return view_func(request, *args, **kwargs)

        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper

def hr_required(view_func):
    """Allow HR management: super_admin, admin, management and HR roles."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        if hasattr(request.user, 'profile') and request.user.profile.role in HR_MANAGEMENT_ROLES:
            return view_func(request, *args, **kwargs)

        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper


def payroll_access(view_func):
    """Allow payroll view/process: super_admin, admin, management, HR and accounts."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        if hasattr(request.user, 'profile') and request.user.profile.role in PAYROLL_ROLES:
            return view_func(request, *args, **kwargs)

        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')
    return wrapper
